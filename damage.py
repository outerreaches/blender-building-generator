# SPDX-License-Identifier: GPL-3.0-or-later
"""Damage model: one break field over the footprint.

``BreakField`` answers "how high does the building still stand here?". The
facade walls read it along their outer line (a profile), floor slabs contour
it, and interior walls and stairs are clipped by it, so every element of a
damaged building agrees on what is missing.

Damage combines by taking the minimum of:

* a ragged top (weathering): fine, slope-limited wall-top profiles over the
  intact floors, with the storeys above the break line removed inside;
* craters (collapse): polygonal plan regions with a jagged floor height and
  sloped (optionally terraced) sides, so cuts through facades are diagonals,
  steps and V-notches rather than boxes.

Blasts are the exception to "everything above a surface is gone": bounded
volumes that blow out one to three storeys mid-height while the floors above
survive (walls get jagged holes, intermediate slabs and partitions go).

Collapses come in archetypes (``COLLAPSES``) picked per building by seed.
"""
import math
import random

from . import geom2d

PROFILE_STEP = .6        # Sampling step for damage profiles along a line.
PROFILE_TOLERANCE = .12  # Douglas-Peucker tolerance; keeps edges crisp.
COLLAPSES = ('CORNER', 'STEPPED', 'SHEAR', 'CLEAVE', 'SAWTOOTH', 'GUTTED', 'BLOWOUT')


def _hash_noise(seed, ix, iy):
    value = (ix * 73856093) ^ (iy * 19349663) ^ (seed * 83492791)
    value = ((value ^ (value >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((value ^ (value >> 16)) & 0xFFFF) / 0xFFFF * 2 - 1


def value_noise(seed, x, y, cell):
    """Smooth lattice noise in [-1, 1]."""
    gx, gy = x / cell, y / cell
    ix, iy = math.floor(gx), math.floor(gy)
    fx, fy = gx - ix, gy - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = _hash_noise(seed, ix, iy)
    b = _hash_noise(seed, ix + 1, iy)
    c = _hash_noise(seed, ix, iy + 1)
    d = _hash_noise(seed, ix + 1, iy + 1)
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy


class Crater:
    """A collapse: plan polygon, broken floor height and side slope.

    With ``terraces`` (storey floor heights) the sides break storey by
    storey: ledges at the slab lines with short drops between them.
    """

    def __init__(self, polygon, floor, slope, roughness, seed, terraces=None):
        self.polygon = polygon
        self.floor = floor
        self.slope = slope
        self.roughness = roughness
        self.seed = seed
        self.terraces = sorted(terraces) if terraces else None
        xs = [x for x, _ in polygon]
        ys = [y for _, y in polygon]
        self.bounds = (min(xs), min(ys), max(xs), max(ys))

    def height(self, x, y):
        distance = geom2d.distance_outside(x, y, self.polygon)
        jag = value_noise(self.seed, x, y, 1.7) * self.roughness
        h = self.floor + self.slope * distance
        if self.terraces:
            below = [z for z in self.terraces if z <= h]
            if below and below[-1] > self.floor:
                ledge = below[-1] + .9
                h = min(h, ledge + (h - ledge) * .15)
        return h + jag

    def reach(self, z):
        """How far beyond the polygon the crater still cuts below ``z``."""
        return max(0.0, (z - self.floor + self.roughness) / max(self.slope, .1))


class Blast:
    """A blown-out volume: plan polygon between z0 and z1, storeys above intact."""

    def __init__(self, polygon, z0, z1, roughness, seed):
        self.polygon = polygon
        self.z0, self.z1 = z0, z1
        self.roughness = roughness
        self.seed = seed
        xs = [x for x, _ in polygon]
        ys = [y for _, y in polygon]
        self.bounds = (min(xs), min(ys), max(xs), max(ys))

    def signed(self, x, y):
        """Jagged signed distance: negative inside the blown-out area."""
        return (geom2d.signed_distance(x, y, self.polygon) +
                value_noise(self.seed, x, y, 1.3) * self.roughness)

    def holds(self, z, margin=.1):
        return self.z0 + margin < z < self.z1 - margin


class BreakField:
    """Standing height over a W x D footprint (x right, y back, z up).

    ``level_zs`` are the floor surfaces of every storey, ground first.
    ``min_height`` protects the ground floor (entrances stay usable).
    ``collapse`` forces one of ``COLLAPSES``; by default it is picked by seed.
    """

    def __init__(self, width, depth, top, level_zs, seed=0, damage=0.0,
                 pointiness=.5, resolution=1.0, min_height=0.0, cap_height=None,
                 chunk_cut=False, collapse=None, tiers=None, roof=None):
        self.width, self.depth, self.top = width, depth, top
        # Underside of the roof slab (single-storey buildings keep their roof
        # only while every wall still reaches it).
        self.roof = roof
        # (z_from, z_to, rect): the footprint standing at each height, so a
        # collapse lands on the walls that exist there (podiums, setbacks).
        self.tiers = tiers or [(0.0, top, (0.0, 0.0, width, depth))]
        self.level_zs = list(level_zs)
        self.seed = seed
        self.damage = damage
        self.min_height = max(0.0, min_height)
        self.ragged = None
        self.break_base = None
        self.craters = []
        self.blasts = []
        self.debris = []        # (x, y, rx, ry, peak, base_z) rubble suggestions.
        self.collapse = None
        if damage > 0 and top > 0:
            self._make_ragged_top(pointiness, resolution, cap_height)
        if chunk_cut:
            self._make_collapse(collapse)

    # -- queries ---------------------------------------------------------
    @property
    def damaged(self):
        return self.ragged is not None or bool(self.craters) or bool(self.blasts)

    def interior_top(self, x, y):
        if self.break_base is None:
            return self.top
        # Partitions of the broken storey stand as knee-to-chest-high stubs.
        noise = value_noise(self.seed ^ 0x51AB, x, y, 3.5)
        return self.break_base + 1.2 + .35 * noise

    def height(self, x, y):
        """Standing height for slabs, partitions and stairs."""
        h = self.interior_top(x, y)
        for crater in self.craters:
            h = min(h, crater.height(x, y))
        return max(self.min_height, h)

    def slab_value(self, x, y, z, clearance):
        """>= 0 where the slab whose top is at ``z`` still stands."""
        value = self.height(x, y) - (z + clearance)
        for blast in self.blasts:
            if blast.holds(z):
                value = min(value, blast.signed(x, y))
        return value

    def in_blast(self, x, y, z):
        return any(blast.holds(z, 0.0) and blast.signed(x, y) < 0 for blast in self.blasts)

    def blast_spans(self, origin, direction, ua, ub, z_lo, z_hi):
        """Where blasts cross a wall line: [(u0, u1, z0, z1)] clipped to the wall."""
        ox, oy = origin
        dx, dy = direction
        result = []
        x0, y0 = ox + dx * ua, oy + dy * ua
        x1, y1 = ox + dx * ub, oy + dy * ub
        for blast in self.blasts:
            if blast.z1 <= z_lo or blast.z0 >= z_hi:
                continue
            ts = [0.0] + geom2d.segment_crossings(x0, y0, x1, y1, blast.polygon) + [1.0]
            for a, b in zip(ts, ts[1:]):
                mid = (a + b) / 2
                if b - a > 1e-6 and geom2d.point_in_polygon(x0 + (x1 - x0) * mid,
                                                            y0 + (y1 - y0) * mid, blast.polygon):
                    result.append((ua + (ub - ua) * a, ua + (ub - ua) * b,
                                   max(z_lo, blast.z0), min(z_hi, blast.z1)))
        return result

    def wall_profile(self, origin, direction, ua, ub, side=None, along=0.0):
        """Top of an exterior wall along its outer line, as [(u, z)].

        ``side`` names the facade (front/right/back/left) whose ragged
        profile applies; u is measured from that facade's start corner, which
        stands ``along`` from the start of its side's profile (facades of a
        non-rectangular footprint share their side's weathering line).
        """
        if side is not None and self.ragged is not None:
            profile = self._clip(self.ragged[side], ua + along, ub + along)
            if along:
                profile = [(u - along, z) for u, z in profile]
        else:
            profile = [(ua, self.top), (ub, self.top)]
        for crater in self.craters:
            profile = geom2d.profile_min(
                profile, self._crater_profile(crater, origin, direction, ua, ub))
        return [(u, max(self.min_height, z)) for u, z in profile]

    def line_profile(self, x0, y0, x1, y1, ceiling):
        """Top of an interior element along a line, capped at ``ceiling``."""
        length = math.hypot(x1 - x0, y1 - y0)
        profile = [(0.0, ceiling), (length, ceiling)]
        if not (self.ragged is not None or self.craters) or length < 1e-6:
            return profile
        if self.break_base is None and not any(
                self._crater_near(crater, x0, y0, x1, y1, ceiling) for crater in self.craters):
            return profile
        dx, dy = (x1 - x0) / length, (y1 - y0) / length
        count = max(2, int(math.ceil(length / PROFILE_STEP)) + 1)
        samples = [(length * index / (count - 1),
                    self.height(x0 + dx * length * index / (count - 1),
                                y0 + dy * length * index / (count - 1)))
                   for index in range(count)]
        return geom2d.profile_min(profile, geom2d.simplify(samples, PROFILE_TOLERANCE))

    def lowest(self, samples=12):
        """Lowest standing height over the footprint (sampled)."""
        if not (self.ragged is not None or self.craters):
            return self.top
        best = self.top
        for i in range(samples + 1):
            for j in range(samples + 1):
                best = min(best, self.height(self.width * i / samples, self.depth * j / samples))
        if self.ragged is not None:
            best = min(best, min(min(z for _, z in p) for p in self.ragged.values()))
        return max(self.min_height, best)

    def damaged_bounds(self, z, margin=1.0):
        """Plan box where slabs at ``z`` may be broken; None if intact there."""
        if self.break_base is not None and z > self.break_base + .2:
            return (0.0, 0.0, self.width, self.depth)
        boxes = []
        for crater in self.craters:
            if crater.floor - crater.roughness > z:
                continue
            reach = crater.reach(z) + margin
            x0, y0, x1, y1 = crater.bounds
            boxes.append((x0 - reach, y0 - reach, x1 + reach, y1 + reach))
        for blast in self.blasts:
            if blast.holds(z - .3):
                x0, y0, x1, y1 = blast.bounds
                pad = blast.roughness + margin
                boxes.append((x0 - pad, y0 - pad, x1 + pad, y1 + pad))
        box = None
        for x0, y0, x1, y1 in boxes:
            candidate = (max(0.0, x0), max(0.0, y0), min(self.width, x1), min(self.depth, y1))
            if candidate[0] >= candidate[2] or candidate[1] >= candidate[3]:
                continue
            box = candidate if box is None else (
                min(box[0], candidate[0]), min(box[1], candidate[1]),
                max(box[2], candidate[2]), max(box[3], candidate[3]))
        return box

    def _crater_near(self, crater, x0, y0, x1, y1, z):
        if crater.floor - crater.roughness > z:
            return False
        reach = crater.reach(z) + .5
        bx0, by0, bx1, by1 = crater.bounds
        return not (max(x0, x1) < bx0 - reach or min(x0, x1) > bx1 + reach or
                    max(y0, y1) < by0 - reach or min(y0, y1) > by1 + reach)

    # -- ragged top ------------------------------------------------------
    def _make_ragged_top(self, pointiness, resolution, cap_height):
        """Fine irregular wall tops, median-smoothed and slope-clamped.

        Same character as the v0.9 profiles: a one-storey ragged parapet above
        the break line, adjoining walls sharing their corner heights.
        """
        rng = random.Random((self.seed * 2654435761) ^ 0xDA7A6E)
        total = self.top
        damage = self.damage
        base_loss = total * .55 * damage
        variance = base_loss * pointiness * 1.5
        absolute_min = max(self.min_height, total * .1)
        low = max(self.min_height, total - base_loss)
        if cap_height is not None:
            low = min(low, cap_height)
        walls = (('front', self.width), ('right', self.depth),
                 ('back', self.width), ('left', self.depth))
        intensity = {name: (rng.uniform(1.0, 1.25) if rng.random() < damage * .4 else 1.0)
                     for name, _ in walls}
        max_step = max(1.5, total * .06)
        raw = {}
        for name, length in walls:
            samples = max(3, int(round(length / 1.2 * max(resolution, .25))))
            heights = []
            for _ in range(samples + 1):
                loss = base_loss * intensity[name] + (rng.random() - .5) * variance * intensity[name]
                heights.append(max(absolute_min, min(total, total - max(0.0, loss))))
            median = heights[:]
            for index in range(1, len(heights) - 1):
                median[index] = sorted(heights[index - 1:index + 2])[1]
            averaged = median[:]
            for index in range(1, len(median) - 1):
                averaged[index] = .25 * median[index - 1] + .5 * median[index] + .25 * median[index + 1]
            heights = averaged
            for index in range(1, len(heights) - 1):
                heights[index] = min(heights[index],
                                     max(heights[index - 1], heights[index + 1]) + max_step)
            raw[name] = heights
        # Facades run CCW (front, right, back, left); each end meets the next start.
        order = [name for name, _ in walls]
        for index, name in enumerate(order):
            following = order[(index + 1) % 4]
            shared = (raw[name][-1] + raw[following][0]) / 2
            shared = min(shared, raw[name][-2] + max_step, raw[following][1] + max_step)
            raw[name][-1] = raw[following][0] = shared
        upper = [z for z in self.level_zs if z > 0]
        if not upper:
            self._single_storey_top(raw, walls)
            return
        # One ragged storey above the break line; intact floors keep windows.
        candidates = [z for z in self.level_zs if 0 < z <= low + 1e-6]
        break_base = max(candidates) if candidates else min(upper)
        ceiling = min([z for z in self.level_zs if z > break_base + 1e-6] + [total])
        if cap_height is not None:
            ceiling = min(ceiling, max(cap_height, break_base + .4))
        ceiling = max(ceiling, break_base + .4)
        self.break_base = break_base
        self.ragged = {}
        for name, length in walls:
            heights = [min(max(h, break_base + .35), ceiling) for h in raw[name]]
            count = len(heights)
            self.ragged[name] = [(length * index / (count - 1), max(self.min_height, h))
                                 for index, h in enumerate(heights)]

    def _single_storey_top(self, raw, walls):
        """Ragged walls of a one-storey building.

        The heights spread over everything above the protected ground-floor
        height instead of flattening against it, and the roof stays only if
        every wall still reaches its underside; otherwise it has fallen in and
        the shell stands open (the break line is the ground floor).
        """
        total = self.top
        floor = min(self.min_height, total)
        lowest = min(min(heights) for heights in raw.values())
        span = total - lowest
        self.ragged = {}
        for name, length in walls:
            heights = raw[name]
            if span > 1e-6:
                heights = [floor + (h - lowest) * (total - floor) / span for h in heights]
            count = len(heights)
            self.ragged[name] = [(length * index / (count - 1), max(self.min_height, h))
                                 for index, h in enumerate(heights)]
        standing = min(min(z for _, z in profile) for profile in self.ragged.values())
        if self.roof is None or standing < self.roof - 1e-6:
            self.break_base = 0.0

    @staticmethod
    def _clip(profile, ua, ub):
        inner = [(u, z) for u, z in profile if ua < u < ub]
        return geom2d.clean_profile([(ua, geom2d.interp(profile, ua))] + inner +
                                    [(ub, geom2d.interp(profile, ub))])

    # -- collapses -------------------------------------------------------
    def _make_collapse(self, kind=None):
        """Pick a collapse archetype for this building and build it."""
        rng = random.Random((self.seed * 40503) ^ 0xB10C)
        floors = len(self.level_zs)
        if kind not in COLLAPSES:
            weights = {'CORNER': 3.0, 'STEPPED': 2.0, 'SHEAR': 2.0, 'SAWTOOTH': 2.0,
                       'CLEAVE': 1.5 if floors >= 4 else 0.0,
                       'GUTTED': 1.5 if floors >= 4 else 0.0,
                       'BLOWOUT': 2.0 if floors >= 5 else 0.0}
            roll = rng.uniform(0, sum(weights.values()))
            for name in COLLAPSES:
                roll -= weights[name]
                if roll <= 0:
                    kind = name
                    break
            else:
                kind = 'CORNER'
        self.collapse = kind
        getattr(self, f'_collapse_{kind.lower()}')(rng)

    def _upper_floor(self, rng, fractions):
        """A break height as a fraction of the building, above the ground storey."""
        return max(self.min_height, self.top * rng.uniform(*fractions))

    def _rect_at(self, z):
        """Footprint of the storeys standing at height ``z``."""
        for z_from, z_to, rect in self.tiers:
            if z_from - 1e-6 <= z <= z_to + 1e-6:
                return rect
        return self.tiers[-1][2] if z > self.tiers[-1][1] else self.tiers[0][2]

    def _top_rect(self):
        return self.tiers[-1][2]

    @staticmethod
    def _facade(side, rect):
        """(origin, along, inward, length) of a facade line of ``rect``."""
        x0, y0, x1, y1 = rect
        w, d = x1 - x0, y1 - y0
        return {0: ((x0, y0), (1.0, 0.0), (0.0, 1.0), w),
                1: ((x1, y0), (0.0, 1.0), (-1.0, 0.0), d),
                2: ((x1, y1), (-1.0, 0.0), (0.0, -1.0), w),
                3: ((x0, y1), (0.0, -1.0), (1.0, 0.0), d)}[side]

    def _collapse_corner(self, rng, stepped=False):
        """Corner collapse, a higher lobe beside it and on taller buildings a bay failure."""
        total = self.top
        floors = len(self.level_zs)
        aggressive = floors >= 8
        very_tall = floors >= 12
        sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
        span = (.45, .7) if very_tall else (.38, .6) if aggressive else (.32, .52)
        floor = self._upper_floor(rng, (.28, .5) if very_tall else (.3, .52) if aggressive
                                  else (.45, .68))
        rx0, ry0, rx1, ry1 = self._rect_at(floor + 1.0)
        width, depth = rx1 - rx0, ry1 - ry0
        chunk_w = width * rng.uniform(*span)
        chunk_d = depth * rng.uniform(*span)
        cx = rx0 if sign_x < 0 else rx1
        cy = ry0 if sign_y < 0 else ry1
        polygon = self._corner_polygon(rng, cx, cy, sign_x, sign_y, chunk_w, chunk_d)
        rise = max(1.0, total - floor)
        slope = max(1.3, min(6.0, rise / (max(chunk_w, chunk_d) * rng.uniform(.45, .8))))
        if stepped:
            slope = max(1.0, slope * rng.uniform(.55, .8))
        terraces = self.level_zs if stepped else None
        self.craters.append(Crater(polygon, floor, slope, rng.uniform(.25, .55),
                                   self.seed ^ 0x3A11, terraces))
        self._corner_debris(rng, sign_x, sign_y)
        width, depth = self.width, self.depth
        lobe_floor = floor + rng.uniform(.25, .6) * min(rise, 12.0)
        if lobe_floor < total - 1.0:
            if rng.random() < .5:
                lobe = self._blob(rng, cx - sign_x * chunk_w * rng.uniform(.7, 1.0), cy,
                                  chunk_w * rng.uniform(.22, .36),
                                  min(depth * .35, chunk_d * rng.uniform(.4, .7)))
            else:
                lobe = self._blob(rng, cx, cy - sign_y * chunk_d * rng.uniform(.7, 1.0),
                                  min(width * .35, chunk_w * rng.uniform(.4, .7)),
                                  chunk_d * rng.uniform(.22, .36))
            self.craters.append(Crater(lobe, lobe_floor, slope * rng.uniform(.8, 1.3),
                                       rng.uniform(.2, .45), self.seed ^ 0x77E5, terraces))
        if floors >= 4 and (aggressive or rng.random() < .6):
            self._bay_failure(rng, aggressive)

    def _collapse_stepped(self, rng):
        self._collapse_corner(rng, stepped=True)

    def _bay_failure(self, rng, aggressive):
        """A vertical bay slice running out through the top of one facade."""
        total = self.top
        side = rng.randrange(4)
        bite = rng.uniform(.3, .5) if aggressive else rng.uniform(.25, .4)
        base = self._upper_floor(rng, (.18, .42) if aggressive else (.25, .5))
        x0, y0, x1, y1 = self._rect_at(base + 1.0)
        width, depth = x1 - x0, y1 - y0
        if side < 2:
            polygon = self._blob(rng, x0 + width * rng.uniform(.25, .75), y0 if side == 0 else y1,
                                 width * bite / 2, depth * rng.uniform(.18, .35))
        else:
            polygon = self._blob(rng, x0 if side == 2 else x1, y0 + depth * rng.uniform(.25, .75),
                                 width * rng.uniform(.18, .35), depth * bite / 2)
        rise = max(1.0, total - base)
        slope = max(2.0, min(8.0, rise / (max(width, depth) * bite * .6)))
        self.craters.append(Crater(polygon, base, slope, rng.uniform(.25, .5), self.seed ^ 0x9E37))

    def _collapse_shear(self, rng):
        """One whole side sheared off: a diagonal break plane rising across the plan."""
        side = rng.randrange(4)
        floor = self._upper_floor(rng, (.25, .55))
        rect = self._rect_at(floor + 1.0)
        (ox, oy), (ax, ay), (ix, iy), length = self._facade(side, rect)
        across = (rect[3] - rect[1]) if side in (0, 2) else (rect[2] - rect[0])
        outer = [(ox + ax * u - ix * 2.5, oy + ay * u - iy * 2.5) for u in (-2.5, length + 2.5)]
        inner = []
        count = 6
        tilt = rng.uniform(-.12, .12) * across
        for index in range(count + 1):
            u = length + 2.5 - (length + 5.0) * index / count
            offset = max(.2, rng.uniform(.3, 1.6) + tilt * (u / max(length, 1.0) - .5))
            inner.append((ox + ax * u + ix * offset, oy + ay * u + iy * offset))
        polygon = _ccw(outer + inner)
        slope = max(.6, min(5.0, (self.top - floor) / (across * rng.uniform(.4, .95))))
        self.craters.append(Crater(polygon, floor, slope, rng.uniform(.3, .6), self.seed ^ 0x5EA4))
        # Debris all along the sheared side.
        mx, my = ox + ax * length / 2, oy + ay * length / 2
        rx = length * .45 if side in (0, 2) else 3.0
        ry = 3.0 if side in (0, 2) else length * .45
        self.debris.append((mx - ix * 2.5, my - iy * 2.5, rx, ry, rng.uniform(1.6, 3.0), 0.0))

    def _collapse_cleave(self, rng):
        """Split along a diagonal in plan: one half gone above a low break."""
        sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
        floor = self._upper_floor(rng, (.22, .48))
        rx0, ry0, rx1, ry1 = self._rect_at(floor + 1.0)
        width, depth = rx1 - rx0, ry1 - ry0
        cx = rx0 if sign_x < 0 else rx1
        cy = ry0 if sign_y < 0 else ry1
        ix, iy = -sign_x, -sign_y
        a = width * rng.uniform(.65, 1.05)
        b = depth * rng.uniform(.65, 1.05)
        points = [(cx - ix * 2.5, cy - iy * 2.5), (cx + ix * (a + 2.5), cy - iy * 2.5)]
        for index in range(1, 6):
            t = index / 6
            jitter = rng.uniform(-.9, .9)
            px, py = cx + ix * a * (1 - t), cy + iy * b * t
            # Jitter across the cut line.
            nx, ny = b, a
            norm = math.hypot(nx, ny)
            points.append((px + ix * nx / norm * jitter, py + iy * ny / norm * jitter))
        points.append((cx - ix * 2.5, cy + iy * (b + 2.5)))
        slope = rng.uniform(1.6, 4.0)
        self.craters.append(Crater(_ccw(points), floor, slope, rng.uniform(.3, .6),
                                   self.seed ^ 0xC1EA))
        self._corner_debris(rng, sign_x, sign_y, scale=1.4)

    def _collapse_sawtooth(self, rng):
        """Several bites of different depths along the roofline."""
        floor_height = self.top / max(1, len(self.level_zs))
        count = rng.randint(2, 4)
        used = []
        for number in range(count):
            floor = max(self.min_height, self.top - floor_height * rng.uniform(1.0, 4.5))
            rect = self._rect_at(floor + 1.0)
            for _attempt in range(8):
                side = rng.randrange(4)
                (ox, oy), (ax, ay), (ix, iy), length = self._facade(side, rect)
                u = length * rng.uniform(.1, .9)
                if all(abs(u - pu) > length * .25 or side != ps for ps, pu in used):
                    break
            used.append((side, u))
            px, py = ox + ax * u, oy + ay * u
            along = length * rng.uniform(.1, .22)
            into = rng.uniform(2.0, 5.0)
            rx, ry = (along, into) if side in (0, 2) else (into, along)
            self.craters.append(Crater(self._blob(rng, px, py, rx, ry), floor,
                                       rng.uniform(3.0, 7.0), rng.uniform(.3, .5),
                                       self.seed ^ (0x5A70 + number)))

    def _collapse_gutted(self, rng):
        """Facades stand; the middle of the floor plates has fallen in."""
        tx0, ty0, tx1, ty1 = self._top_rect()
        width, depth = tx1 - tx0, ty1 - ty0
        cx = tx0 + width * rng.uniform(.4, .6)
        cy = ty0 + depth * rng.uniform(.4, .6)
        rx = width * rng.uniform(.2, .32)
        ry = depth * rng.uniform(.2, .32)
        polygon = self._blob(rng, cx, cy, rx, ry, count=9)
        x0, y0, x1, y1 = geom2d.polygon_bounds(polygon)
        clearance = max(.8, min(x0 - tx0, y0 - ty0, tx1 - x1, ty1 - y1))
        floor_level = self.level_zs[1] if len(self.level_zs) > 1 else self.min_height
        floor = max(self.min_height, floor_level + rng.uniform(.5, 1.4))
        # Steep enough that the cut never reaches the facades.
        slope = max(rng.uniform(8.0, 14.0), (self.top - floor) / max(.5, clearance - .6) * 1.15)
        self.craters.append(Crater(polygon, floor, slope, rng.uniform(.3, .5), self.seed ^ 0x6077))
        self.debris.append((cx, cy, rx * .7, ry * .7, rng.uniform(1.2, 2.4), floor_level))
        if rng.random() < .85:
            # A bite through one facade so the hollow reads from the street.
            self._collapse_sawtooth_single(rng)

    def _collapse_sawtooth_single(self, rng):
        floor_height = self.top / max(1, len(self.level_zs))
        side = rng.randrange(4)
        floor = max(self.min_height, self.top - floor_height * rng.uniform(1.0, 2.5))
        (ox, oy), (ax, ay), (ix, iy), length = self._facade(side, self._rect_at(floor + 1.0))
        u = length * rng.uniform(.2, .8)
        along, into = length * rng.uniform(.1, .18), rng.uniform(2.0, 4.0)
        rx, ry = (along, into) if side in (0, 2) else (into, along)
        self.craters.append(Crater(self._blob(rng, ox + ax * u, oy + ay * u, rx, ry), floor,
                                   rng.uniform(3.0, 6.0), .4, self.seed ^ 0x5A7F))

    def _collapse_blowout(self, rng):
        """One or two storeys-high holes blown through mid-height; floors above survive."""
        zs = self.level_zs
        floors = len(zs)
        count = 1 if floors < 8 else rng.choice((1, 2, 2))
        taken = []
        for number in range(count):
            lowest = max(1, next((i for i, z in enumerate(zs) if z >= self.min_height), 1))
            first = max(lowest, int(floors * .25))
            last = max(first, int(floors * .75) - 1)
            if last >= floors - 1:
                last = floors - 2
            if last < first:
                return
            j = rng.randint(first, last)
            span = min(rng.choice((1, 2, 2, 3, 3)), floors - 1 - j)
            if span < 1 or any(abs(j - other) < 3 for other in taken):
                continue
            taken.append(j)
            z0 = zs[j] + rng.uniform(.15, .5)
            z1 = zs[j + span] - rng.uniform(.05, .5)
            rect = self._rect_at((z0 + z1) / 2)
            x0, y0, x1, y1 = rect
            if rng.random() < .3:
                sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
                px = x0 if sign_x < 0 else x1
                py = y0 if sign_y < 0 else y1
                rx, ry = (x1 - x0) * rng.uniform(.25, .4), (y1 - y0) * rng.uniform(.25, .4)
                ix, iy = -sign_x, -sign_y
            else:
                side = rng.randrange(4)
                (ox, oy), (ax, ay), (ix, iy), length = self._facade(side, rect)
                u = length * rng.uniform(.2, .8)
                px, py = ox + ax * u, oy + ay * u
                across = (y1 - y0) if side in (0, 2) else (x1 - x0)
                along = min(length * .45, rng.uniform(4.5, 9.0))
                into = min(across * .6, rng.uniform(4.0, 9.0))
                rx, ry = (along, into) if side in (0, 2) else (into, along)
            polygon = self._blob(rng, px, py, rx, ry, count=8)
            self.blasts.append(Blast(polygon, z0, z1, rng.uniform(.3, .6),
                                     self.seed ^ (0xB1A5 + number)))
            # Debris on the floor of the blown storey, and spilled to the street.
            self.debris.append((px + ix * min(rx, ry) * .6, py + iy * min(rx, ry) * .6,
                                rx * .5, ry * .5, rng.uniform(.5, 1.1), zs[j]))
            self.debris.append((px - ix * 2.0, py - iy * 2.0, max(rx, ry) * .45,
                                max(rx, ry) * .35, rng.uniform(.7, 1.5), 0.0))

    def _corner_debris(self, rng, sign_x, sign_y, scale=1.0):
        width, depth = self.width, self.depth
        cx = (0 if sign_x < 0 else width) - sign_x * width * .12
        cy = (0 if sign_y < 0 else depth) - sign_y * depth * .12
        self.debris.append((cx, cy, width * rng.uniform(.2, .34) * scale,
                            depth * rng.uniform(.2, .34) * scale, rng.uniform(1.4, 3.0), 0.0))

    @staticmethod
    def _corner_polygon(rng, cx, cy, sign_x, sign_y, chunk_w, chunk_d):
        """Irregular polygon around a building corner, reaching past the facades."""
        out = 1.5
        ix, iy = -sign_x, -sign_y  # Inward directions.
        a = chunk_w * rng.uniform(.35, .6)
        b = chunk_d * rng.uniform(.35, .6)
        points = [
            (cx - ix * out, cy - iy * out),
            (cx + ix * a, cy - iy * out),
            (cx + ix * a * rng.uniform(.75, 1.05), cy + iy * b * rng.uniform(.25, .5)),
            (cx + ix * a * rng.uniform(.4, .7), cy + iy * b * rng.uniform(.6, .95)),
            (cx + ix * a * rng.uniform(.15, .35), cy + iy * b),
            (cx - ix * out, cy + iy * b),
        ]
        return _ccw(points)

    @staticmethod
    def _blob(rng, cx, cy, rx, ry, count=7):
        """Jagged convex-ish polygon centred on (cx, cy)."""
        phase = rng.uniform(0, math.tau)
        points = []
        for index in range(count):
            angle = phase + math.tau * index / count
            scale = rng.uniform(.75, 1.15)
            points.append((cx + math.cos(angle) * rx * scale, cy + math.sin(angle) * ry * scale))
        return _ccw(points)

    def _crater_profile(self, crater, origin, direction, ua, ub):
        ox, oy = origin
        dx, dy = direction
        x0, y0 = ox + dx * ua, oy + dy * ua
        x1, y1 = ox + dx * ub, oy + dy * ub
        if not self._crater_near(crater, x0, y0, x1, y1, self.top):
            return [(ua, self.top), (ub, self.top)]
        length = ub - ua
        step = PROFILE_STEP / 2 if crater.terraces else PROFILE_STEP
        count = max(2, int(math.ceil(length / step)) + 1)
        us = {ua, ub}
        us.update(ua + length * index / (count - 1) for index in range(count))
        us.update(ua + length * t for t in geom2d.segment_crossings(x0, y0, x1, y1,
                                                                    crater.polygon))
        samples = [(u, min(self.top, crater.height(ox + dx * u, oy + dy * u)))
                   for u in sorted(us)]
        return geom2d.simplify(samples, PROFILE_TOLERANCE)


def breach_outline(rng, u0, u1, z0, z1, grounded=True):
    """Jagged x-monotone (bottom, top) outline of a blown-out wall opening."""
    count = max(3, int((u1 - u0) / .7))
    bottom, top = [], []
    for index in range(count + 1):
        t = index / count
        u = u0 + (u1 - u0) * t
        arch = math.sin(math.pi * t)
        inner = 0 < index < count
        height = (z1 - z0) * (.2 + .8 * arch) * (rng.uniform(.75, 1.0) if inner else 1.0)
        base = z0 if grounded else z0 + (z1 - z0) * .3 * (1 - arch) * (rng.uniform(.3, 1.0) if inner else 1.0)
        bottom.append((u, base))
        top.append((u, max(base + .25, z0 + height)))
    return bottom, top


def blast_outline(rng, u0, u1, z0, z1, open_start=False, open_end=False):
    """Ragged blast hole through a wall: broken along the floor line, arched above.

    The bottom runs roughly level near the slab with jagged chips, the top
    rises in a ragged arch, and the ends pinch unless they reach a corner. Bottom and
    top stay functions of u, so the hole is a valid x-monotone wall opening.
    """
    us = [u0]
    while us[-1] < u1 - .4:
        us.append(min(u1, us[-1] + rng.uniform(.35, .9)))
    if u1 - us[-1] > 1e-6:
        us.append(u1)
    height = z1 - z0
    lean = rng.uniform(-.25, .25)
    bottom, top = [], []
    for index, u in enumerate(us):
        t = (u - u0) / max(u1 - u0, 1e-6)
        # 0 at a pinched end, 1 mid-way; ends at a wall corner stay full height
        # (the blast took the corner).
        start = 1.0 if open_start else min(1.0, 2 * t)
        finish = 1.0 if open_end else min(1.0, 2 * (1 - t))
        shape = min(start, finish) ** .3
        inner = 0 < index < len(us) - 1
        low = z0 + (1 - shape) * height * .35
        high = z1 - (1 - shape) * height * .45 + lean * height * (t - .5)
        if inner:
            low += rng.uniform(-.25, .3) + (rng.uniform(.3, .8) if rng.random() < .12 else 0.0)
            high += rng.uniform(-.6, .6) - (rng.uniform(.5, 1.3) if rng.random() < .18 else 0.0)
        bottom.append((u, low))
        top.append((u, max(low + .5, high)))
    return bottom, top


def _ccw(points):
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return points if area > 0 else list(reversed(points))
