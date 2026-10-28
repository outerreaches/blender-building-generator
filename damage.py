# SPDX-License-Identifier: GPL-3.0-or-later
"""Damage model: one break field over the footprint.

``BreakField`` answers "how high does the building still stand here?". The
facade walls read it along their outer line (a profile), floor slabs contour
it, and interior walls and stairs are clipped by it, so every element of a
damaged building agrees on what is missing.

Two kinds of damage combine by taking the minimum:

* a ragged top (weathering): fine, slope-limited wall-top profiles over the
  intact floors, with the storeys above the break line removed inside;
* craters (collapse): polygonal plan regions with a jagged floor height and
  sloped sides, so cuts through facades are trapezoids and V-notches with
  broken edges rather than boxes.
"""
import math
import random

from . import geom2d

PROFILE_STEP = .6        # Sampling step for damage profiles along a line.
PROFILE_TOLERANCE = .12  # Douglas-Peucker tolerance; keeps edges crisp.


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
    """A collapse: plan polygon, broken floor height and side slope."""

    def __init__(self, polygon, floor, slope, roughness, seed, corner=None):
        self.polygon = polygon
        self.floor = floor
        self.slope = slope
        self.roughness = roughness
        self.seed = seed
        self.corner = corner
        xs = [x for x, _ in polygon]
        ys = [y for _, y in polygon]
        self.bounds = (min(xs), min(ys), max(xs), max(ys))

    def height(self, x, y):
        distance = geom2d.distance_outside(x, y, self.polygon)
        jag = value_noise(self.seed, x, y, 1.7) * self.roughness
        return self.floor + self.slope * distance + jag

    def reach(self, z):
        """How far beyond the polygon the crater still cuts below ``z``."""
        return max(0.0, (z - self.floor + self.roughness) / max(self.slope, .1))


class BreakField:
    """Standing height over a W x D footprint (x right, y back, z up).

    ``level_zs`` are the floor surfaces of every storey, ground first.
    ``min_height`` protects the ground floor (entrances stay usable).
    """

    def __init__(self, width, depth, top, level_zs, seed=0, damage=0.0,
                 pointiness=.5, resolution=1.0, min_height=0.0, cap_height=None,
                 chunk_cut=False):
        self.width, self.depth, self.top = width, depth, top
        self.level_zs = list(level_zs)
        self.seed = seed
        self.damage = damage
        self.min_height = max(0.0, min_height)
        self.ragged = None
        self.break_base = None
        self.craters = []
        if damage > 0 and top > 0:
            self._make_ragged_top(pointiness, resolution, cap_height)
        if chunk_cut:
            self._make_craters()

    # -- queries ---------------------------------------------------------
    @property
    def damaged(self):
        return self.ragged is not None or bool(self.craters)

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

    def wall_profile(self, origin, direction, ua, ub, side=None):
        """Top of an exterior wall along its outer line, as [(u, z)].

        ``side`` names the facade (front/right/back/left) whose ragged
        profile applies; u is measured from that facade's start corner.
        """
        if side is not None and self.ragged is not None:
            profile = self._clip(self.ragged[side], ua, ub)
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
        if not self.damaged or length < 1e-6:
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
        if not self.damaged:
            return self.top
        best = self.top
        for i in range(samples + 1):
            for j in range(samples + 1):
                best = min(best, self.height(self.width * i / samples, self.depth * j / samples))
        if self.ragged is not None:
            best = min(best, min(min(z for _, z in p) for p in self.ragged.values()))
        return max(self.min_height, best)

    def damaged_bounds(self, z, margin=1.0):
        """Plan box where the field may drop below ``z``; None if intact there."""
        if self.break_base is not None and z > self.break_base + .2:
            return (0.0, 0.0, self.width, self.depth)
        box = None
        for crater in self.craters:
            if crater.floor - crater.roughness > z:
                continue
            reach = crater.reach(z) + margin
            x0, y0, x1, y1 = crater.bounds
            candidate = (max(0.0, x0 - reach), max(0.0, y0 - reach),
                         min(self.width, x1 + reach), min(self.depth, y1 + reach))
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
        # One ragged storey above the break line; intact floors keep windows.
        candidates = [z for z in self.level_zs if 0 < z <= low + 1e-6]
        upper = [z for z in self.level_zs if z > 0]
        break_base = max(candidates) if candidates else (min(upper) if upper else low)
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

    @staticmethod
    def _clip(profile, ua, ub):
        inner = [(u, z) for u, z in profile if ua < u < ub]
        return geom2d.clean_profile([(ua, geom2d.interp(profile, ua))] + inner +
                                    [(ub, geom2d.interp(profile, ub))])

    # -- craters ---------------------------------------------------------
    def _make_craters(self):
        """Corner collapse plus, on taller buildings, a facade bay failure.

        Keeps the v0.9 chunk sizes and heights, but each cut is a jagged
        polygon in plan with sloped sides, so facades break in diagonals and
        steps instead of rectangles.
        """
        rng = random.Random((self.seed * 40503) ^ 0xB10C)
        width, depth, total = self.width, self.depth, self.top
        floors = len(self.level_zs)
        aggressive = floors >= 8
        very_tall = floors >= 12
        sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
        span = (.45, .7) if very_tall else (.38, .6) if aggressive else (.32, .52)
        chunk_w = width * rng.uniform(*span)
        chunk_d = depth * rng.uniform(*span)
        fraction = (.28, .5) if very_tall else (.3, .52) if aggressive else (.45, .68)
        floor = max(self.min_height, total * rng.uniform(*fraction))
        cx = 0.0 if sign_x < 0 else width
        cy = 0.0 if sign_y < 0 else depth
        polygon = self._corner_polygon(rng, cx, cy, sign_x, sign_y, chunk_w, chunk_d)
        rise = max(1.0, total - floor)
        slope = max(1.3, min(6.0, rise / (max(chunk_w, chunk_d) * rng.uniform(.45, .8))))
        self.craters.append(Crater(polygon, floor, slope, rng.uniform(.25, .55),
                                   self.seed ^ 0x3A11, corner=(sign_x, sign_y)))
        # A step in the break: a smaller, higher lobe beside the corner.
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
                                       rng.uniform(.2, .45), self.seed ^ 0x77E5))
        if floors >= 4 and (aggressive or rng.random() < .6):
            # A vertical bay failure that runs out through the top: lost
            # slices take their support above with them.
            side = rng.randrange(4)
            bite = rng.uniform(.3, .5) if aggressive else rng.uniform(.25, .4)
            base = max(self.min_height, total * (rng.uniform(.18, .42) if aggressive
                                                 else rng.uniform(.25, .5)))
            if side < 2:
                polygon = self._blob(rng, width * rng.uniform(.25, .75), 0.0 if side == 0 else depth,
                                     width * bite / 2, depth * rng.uniform(.18, .35))
            else:
                polygon = self._blob(rng, 0.0 if side == 2 else width, depth * rng.uniform(.25, .75),
                                     width * rng.uniform(.18, .35), depth * bite / 2)
            rise = max(1.0, total - base)
            slope = max(2.0, min(8.0, rise / (max(width, depth) * bite * .6)))
            self.craters.append(Crater(polygon, base, slope, rng.uniform(.25, .5),
                                       self.seed ^ 0x9E37))

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
        count = max(2, int(math.ceil(length / PROFILE_STEP)) + 1)
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


def _ccw(points):
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return points if area > 0 else list(reversed(points))
