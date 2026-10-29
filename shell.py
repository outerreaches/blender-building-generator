# SPDX-License-Identifier: GPL-3.0-or-later
"""Assemble a whole building as closed solids (pure Python).

``build_building(params)`` runs the pipeline: spec (storeys, tiers, facade
bays) -> interior plan (rooms, doors, stairs, slab holes) -> break field
(damage) -> geometry. Every element is a closed solid built from its final
outline, so damage, openings and plans of any shape cannot leave holes.
"""
import math
import random

from . import damage, dims, geom2d, layouts, rubble, solids
from .meshdata import (MAT_DOOR_FRAME, MAT_FLOOR, MAT_INTERIOR_WALL, MAT_ROOF, MAT_STAIRS,
                       MAT_WALLS, MAT_WINDOW_FRAME, MeshData)
from .spec import BuildingSpec

SLAB_CLEARANCE = .3     # Field must stand this far above a slab for it to remain.
FINE_GRID = .6          # Slab contouring step where damage cuts through.


class Building:
    """Result of the pipeline: mesh plus what downstream code needs to know."""

    def __init__(self, mesh, spec, plan, field):
        self.mesh = mesh
        self.spec = spec
        self.plan = plan
        self.field = field

    @property
    def damage_min_height(self):
        return self.field.lowest()


def wall_top(spec):
    """Highest undamaged wall: parapet, or the gable ridge."""
    rise = float(spec.params.get('roof_height', 2.0)) if spec.roof_kind == 'GABLE' else 0.0
    return spec.top + spec.parapet + rise


def make_field(spec, params):
    damage_amount = float(params.get('damage_amount', 0)) if params.get('enable_damage') else 0.0
    if params.get('chunk_cut'):
        # Collapses do the heavy damage; the top only weathers lightly.
        damage_amount *= .35
    door = float(params.get('door_height', 2.4))
    # The ground floor and its entrances always stand.
    min_height = max(door + .5, spec.levels[0].height * .8)
    return damage.BreakField(
        spec.width, spec.depth, wall_top(spec), [level.z for level in spec.levels],
        seed=spec.seed, damage=damage_amount,
        pointiness=float(params.get('damage_pointiness', .5)),
        resolution=float(params.get('damage_resolution', 1.0)),
        min_height=min(min_height, spec.top), cap_height=params.get('damage_cap_height'),
        chunk_cut=bool(params.get('chunk_cut')), collapse=params.get('collapse'),
        tiers=[(spec.levels[tier.first].z, spec.levels[tier.last].ceiling, tier.rect)
               for tier in spec.tiers])


def build_building(params):
    params = dict(params)
    spec = BuildingSpec(params)
    plan = layouts.plan_building(spec)
    spec.build_openings(plan.doors)
    field = make_field(spec, params)
    rng = random.Random((spec.seed * 2246822519) ^ 0x5E11)
    _trim_broken_windows(spec, field)
    _damage_openings(spec, field, params, rng)
    mesh = MeshData()
    roof_intact = _roof_intact(spec, field)
    _walls(mesh, spec, field, roof_intact)
    _columns(mesh, spec)
    _slabs(mesh, spec, field, plan)
    _roof(mesh, spec, field, roof_intact, params)
    _facade_details(mesh, spec, field, params)
    _interiors(mesh, spec, field, plan)
    rubble.interior_fill(mesh, rng, spec, field, params)
    rubble.exterior_piles(mesh, rng, spec, params)
    for x, y, rx, ry, peak, base in field.debris:
        # Upper-floor debris sinks into its slab so its underside shares no
        # plane with partitions standing on the same floor.
        rubble.mound(mesh, rng, x, y, rx, ry, peak, segments=9,
                     base=base - .03 if base > 0 else base)
    if params.get('interior_mound'):
        rubble.interior_mound(mesh, rng, spec)
    return Building(mesh, spec, plan, field)


# -- damage on facades -------------------------------------------------------

def _trim_broken_windows(spec, field):
    """Fill windows the break line passes through above the sill.

    A window whose wall is broken off just above its head would survive as a
    hole in a thin spike of wall; ruins read better as solid broken masonry
    there. Windows below an intact wall, or below a break that already took
    the sill, are kept.
    """
    if not field.damaged:
        return
    for tier in spec.tiers:
        for facade in tier.facades:
            profile = field.wall_profile(facade.origin, facade.direction, facade.ua, facade.ub,
                                         side=facade.side)
            keep = []
            for opening in facade.openings:
                if opening.kind != 'window':
                    keep.append(opening)
                    continue
                sill = min(z for _, z in opening.bottom)
                head = max(z for _, z in opening.top)
                a, b = opening.u0 - .3, opening.u1 + .3
                lowest = min([geom2d.interp(profile, a + (b - a) * k / 8) for k in range(9)] +
                             [z for u, z in profile if a <= u <= b])
                if sill + .3 < lowest < head + .6:
                    continue
                keep.append(opening)
            facade.openings = keep


def _damage_openings(spec, field, params, rng):
    """Ground breaches (exposed fills) and blast holes, replacing whole windows."""
    base = spec.tiers[0]
    if params.get('expose_fill'):
        facade = rng.choice(base.facades)
        bays = facade.bays
        if len(bays) >= 2:
            span = min(len(bays) - 1, rng.choice((1, 2)))
            first = rng.randrange(0, len(bays) - span)
            height = min(spec.levels[0].height * rng.uniform(1.6, 2.4),
                         (spec.top + spec.parapet) * .8)
            _replace_with_hole(facade, bays[first] + .15, bays[first + span] - .15, 0.0, height,
                               rng, grounded=True)
    for tier in spec.tiers:
        for facade in tier.facades:
            for u0, u1, z0, z1 in field.blast_spans(facade.origin, facade.direction, facade.ua,
                                                    facade.ub, facade.base + .3, facade.top):
                corner = (u0 <= facade.ua + .05, u1 >= facade.ub - .05)

                def outline(rng, a, b, low, high, corner=corner):
                    return damage.blast_outline(rng, a, b, low, high, *corner)
                _replace_with_hole(facade, u0, u1, z0, z1, rng, grounded=False, outline=outline)
    holes = int(round(field.damage * 3 * rng.uniform(.3, 1.0))) if field.damage else 0
    for _ in range(holes):
        tier = rng.choice(spec.tiers)
        facade = rng.choice(tier.facades)
        windows = [o for o in facade.openings if o.kind == 'window']
        if not windows:
            continue
        window = rng.choice(windows)
        z0 = min(z for _, z in window.bottom)
        z1 = max(z for _, z in window.top)
        bay = next(((a, b) for a, b in zip(facade.bays, facade.bays[1:])
                    if a <= window.u0 and window.u1 <= b), None)
        if bay is None or z0 < field.min_height:
            continue
        below = max([max(z for _, z in o.top) for o in facade.openings
                     if o is not window and o.u0 < bay[1] and o.u1 > bay[0] and
                     max(z for _, z in o.top) <= z0 + 1e-6] + [facade.base])
        above = min([min(z for _, z in o.bottom) for o in facade.openings
                     if o is not window and o.u0 < bay[1] and o.u1 > bay[0] and
                     min(z for _, z in o.bottom) >= z1 - 1e-6] + [facade.top])
        low = max(below + .25, z0 - rng.uniform(.3, .7))
        high = min(above - .25, z1 + rng.uniform(.3, .9))
        if high - low < 1.0:
            continue
        if any(o.kind != 'window' and o.u0 < bay[1] + .1 and o.u1 > bay[0] - .1 and
               min(z for _, z in o.bottom) < high + .5 and max(z for _, z in o.top) > low - .5
               for o in facade.openings):
            continue  # Never swallow a door or another breach.
        _replace_with_hole(facade, bay[0] + .12, bay[1] - .12, low, high, rng, grounded=False,
                           keep=(window.u0, window.u1, z0, z1))


def _replace_with_hole(facade, u0, u1, z0, z1, rng, grounded, keep=None, outline=None):
    if u1 - u0 < .8:
        return
    near = [o for o in facade.openings if o.u0 < u1 + .1 and o.u1 > u0 - .1 and
            min(z for _, z in o.bottom) < z1 + .5 and max(z for _, z in o.top) > z0 - .5]
    # Doors survive: the hole starts above them.
    for door in [o for o in near if o.kind == 'door']:
        z0 = max(z0, max(z for _, z in door.top) + .6)
    if z1 - z0 < 1.0:
        return
    if outline is not None:
        # Blast holes keep their ragged outline: windows it touches are filled
        # in (broken masonry) instead of stretching the hole around them.
        bottom, top = outline(rng, u0, u1, z0, z1)
        bottom = [(u, max(facade.base + .05, z)) for u, z in bottom]
        for opening in [o for o in near if o.kind != 'door']:
            if _touches_outline(opening, bottom, top):
                facade.openings.remove(opening)
        facade.openings.append(solids.Opening(u0, u1, bottom, top, MAT_WALLS, 'breach'))
        return
    victims = [o for o in near if o.kind != 'door' and
               min(z for _, z in o.bottom) < z1 + .5 and max(z for _, z in o.top) > z0 - .5]
    for opening in victims:
        facade.openings.remove(opening)
    bottom, top = damage.breach_outline(rng, u0, u1, z0, z1, grounded)
    # The hole must contain every opening it swallowed.
    for opening in victims:
        ob, ot = min(z for _, z in opening.bottom), max(z for _, z in opening.top)
        bottom = [(u, min(z, ob - .1) if opening.u0 - .2 <= u <= opening.u1 + .2 else z)
                  for u, z in bottom]
        top = [(u, max(z, ot + .1) if opening.u0 - .2 <= u <= opening.u1 + .2 else z)
               for u, z in top]
    bottom = [(u, max(facade.base, z)) for u, z in bottom]
    facade.openings.append(solids.Opening(u0, u1, bottom, top, MAT_WALLS, 'breach'))


def _touches_outline(opening, bottom, top, margin=.15):
    """Whether a rectangular opening comes within ``margin`` of a hole outline."""
    a = max(opening.u0, bottom[0][0]) - margin
    b = min(opening.u1, bottom[-1][0]) + margin
    if b <= a:
        return False
    ob, ot = min(z for _, z in opening.bottom), max(z for _, z in opening.top)
    for k in range(9):
        u = a + (b - a) * k / 8
        low, high = geom2d.interp(bottom, u), geom2d.interp(top, u)
        if max(ob, low) < min(ot, high) + margin:
            return True
    return False


# -- walls -------------------------------------------------------------------

def _roof_intact(spec, field):
    """Roof features (gable, plant room) only stand on an undamaged top."""
    if not field.damaged:
        return True
    top_tier = spec.tiers[-1]
    x0, y0, x1, y1 = top_tier.rect
    for i in range(7):
        for j in range(7):
            x = x0 + (x1 - x0) * i / 6
            y = y0 + (y1 - y0) * j / 6
            if field.height(x, y) < spec.top + spec.parapet - .05:
                return False
    if field.ragged is not None:
        return False
    return True


def _walls(mesh, spec, field, roof_intact):
    gable = spec.roof_kind == 'GABLE' and roof_intact
    rise = float(spec.params.get('roof_height', 2.0))
    for tier in spec.tiers:
        for facade in tier.facades:
            profile = field.wall_profile(facade.origin, facade.direction, facade.ua, facade.ub,
                                         side=facade.side)
            for ua, ub, height in facade.segments:
                top = [(ua, height), (ub, height)]
                if gable and tier is spec.tiers[-1] and facade.side in ('left', 'right'):
                    # Gable ends rise to the ridge under the roof planes.
                    half = facade.length / 2
                    top = [(ua, height + rise * ua / half), (half, height + rise),
                           (ub, height + rise * (facade.length - ub) / half)]
                top = geom2d.profile_min(top, profile)
                solids.wall_solid(mesh, facade.origin, facade.direction, spec.t, ua, ub,
                                  facade.base, top, facade.openings, MAT_WALLS)


def _columns(mesh, spec):
    for x, y, size, z0, z1 in spec.columns:
        solids.box(mesh, x - size / 2, y - size / 2, z0, x + size / 2, y + size / 2, z1, MAT_WALLS)


# -- slabs -------------------------------------------------------------------

def _grid(lo, hi, cuts, fine=None):
    values = {lo, hi}
    values.update(c for c in cuts if lo < c < hi)
    if fine is not None:
        a, b = max(lo, fine[0]), min(hi, fine[1])
        if b > a:
            count = max(1, int(math.ceil((b - a) / FINE_GRID)))
            values.update(a + (b - a) * k / count for k in range(count + 1))
    # Merge near-duplicates (float noise would make zero-width cells); keep the
    # exact plate edges and hole edges.
    exact = {lo, hi} | {c for c in cuts if lo < c < hi}
    result = []
    for value in sorted(values):
        if result and value - result[-1] < 1e-4:
            if value in exact and result[-1] not in exact:
                result[-1] = value
            continue
        result.append(value)
    return result


def slab(mesh, field, rect, z_bottom, z_top, holes=(), material=MAT_FLOOR, clearance=SLAB_CLEARANCE):
    x0, y0, x1, y1 = rect
    if x1 - x0 < .2 or y1 - y0 < .2:
        return
    holes = [(max(x0, h[0]), max(y0, h[1]), min(x1, h[2]), min(y1, h[3])) for h in holes]
    holes = [h for h in holes if h[2] - h[0] > .05 and h[3] - h[1] > .05]
    level = z_top + clearance
    zone = field.damaged_bounds(level) if field.damaged else None
    fx = (zone[0], zone[2]) if zone else None
    fy = (zone[1], zone[3]) if zone else None
    xs = _grid(x0, x1, [h[0] for h in holes] + [h[2] for h in holes], fx)
    ys = _grid(y0, y1, [h[1] for h in holes] + [h[3] for h in holes], fy)
    if zone is None:
        def inside(x, y):
            return 1.0
    else:
        def inside(x, y):
            return field.slab_value(x, y, z_top, clearance)
    solids.slab_solid(mesh, xs, ys, z_bottom, z_top, inside, material, holes)


def _slabs(mesh, spec, field, plan):
    planned = {level.index: level for level in plan.levels}
    t = spec.t
    for level in spec.levels:
        if level.index == 0:
            rect = spec.interior_rect(0)
            slab(mesh, field, rect, -dims.GROUND_SLAB, 0.0, clearance=-10.0)
            continue
        if not spec.has_slabs:
            continue
        below = spec.levels[level.index - 1].rect
        here = level.rect
        outer = below if _contains(below, here) else here
        rect = (outer[0] + t, outer[1] + t, outer[2] - t, outer[3] - t)
        holes = planned[level.index].holes if level.index in planned else []
        slab(mesh, field, rect, level.z - spec.slab, level.z, holes)


def _contains(outer, inner, eps=1e-6):
    return (outer[0] <= inner[0] + eps and outer[1] <= inner[1] + eps and
            outer[2] >= inner[2] - eps and outer[3] >= inner[3] - eps)


# -- roof --------------------------------------------------------------------

def _roof(mesh, spec, field, intact, params):
    tier = spec.tiers[-1]
    rect = spec.interior_rect(spec.levels[-1].index)
    top = spec.top
    if spec.roof_kind in ('FLAT', 'GABLE'):
        # Flat roof slab, or the ceiling under a gable roof.
        slab(mesh, field, rect, top - spec.roof_slab, top, material=MAT_ROOF if spec.roof_kind == 'FLAT'
             else MAT_FLOOR, clearance=0.0)
    if not intact:
        return
    if spec.roof_kind == 'GABLE':
        _gable(mesh, spec, tier, float(params.get('roof_height', 2.0)),
               float(params.get('roof_overhang', .4)))
    box = params.get('roof_box')
    if box and spec.roof_kind == 'FLAT':
        fw, fd, height = box
        x0, y0, x1, y1 = tier.rect
        w, d = (x1 - x0) * fw, (y1 - y0) * fd
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        solids.box(mesh, cx - w / 2, cy - d / 2, top, cx + w / 2, cy + d / 2, top + height, MAT_WALLS)
        crown = params.get('crown')
        if crown == 'STEPPED':
            solids.box(mesh, cx - w * .3, cy - d * .3, top + height, cx + w * .3, cy + d * .3,
                       top + height * 1.8, MAT_WALLS)
        elif crown == 'MAST':
            solids.box(mesh, cx - .3, cy - .3, top + height, cx + .3, cy + .3,
                       top + height + max(8.0, spec.top * .12), MAT_ROOF)


def _gable(mesh, spec, tier, rise, overhang):
    """Two roof planes over the ridge (along x), as closed sloped slabs."""
    x0, y0, x1, y1 = tier.rect
    top = spec.top
    ridge_y = (y0 + y1) / 2
    half = (y1 - y0) / 2
    slope = rise / half
    thickness = .2
    xa, xb = x0 - overhang, x1 + overhang
    for sign in (-1, 1):
        edge_y = (y0 - overhang) if sign < 0 else (y1 + overhang)
        edge_z = top - overhang * slope
        ridge_z = top + rise
        if sign < 0:
            lower = [(xa, edge_y, edge_z), (xb, edge_y, edge_z), (xb, ridge_y, ridge_z), (xa, ridge_y, ridge_z)]
        else:
            lower = [(xa, ridge_y, ridge_z), (xb, ridge_y, ridge_z), (xb, edge_y, edge_z), (xa, edge_y, edge_z)]
        upper = [(x, y, z + thickness) for x, y, z in lower]
        solids.hexahedron(mesh, lower + upper, MAT_ROOF)


# -- facade details ----------------------------------------------------------

def _facade_details(mesh, spec, field, params):
    base = spec.tiers[0]
    if params.get('facade_pilasters'):
        _pilasters(mesh, spec, field, base, params)
    if params.get('cornice'):
        _cornices(mesh, spec, field)
    if spec.lobby != 'NONE' or params.get('entrance_canopy'):
        _canopy(mesh, spec, field)


def _profile_min(facade, field, u0, u1, tier_top):
    profile = field.wall_profile(facade.origin, facade.direction, facade.ua, facade.ub,
                                 side=facade.side)
    interp = geom2d.interp
    samples = [interp(profile, u0 + (u1 - u0) * k / 4) for k in range(5)]
    samples += [z for u, z in profile if u0 <= u <= u1]
    return min(tier_top, min(samples))


def _pilasters(mesh, spec, field, tier, params):
    width = float(params.get('pilaster_width', .4))
    depth = float(params.get('pilaster_depth', .15))
    style = params.get('pilaster_style', 'CORNERS')
    sides = {'FRONT': ('front',), 'FRONT_BACK': ('front', 'back'),
             'ALL': ('front', 'back', 'left', 'right')}.get(params.get('pilaster_sides', 'FRONT'),
                                                              ('front',))
    for facade in tier.facades:
        if facade.side not in sides:
            continue
        positions = set()
        if style in ('CORNERS', 'CORNERS_CENTER', 'FULL'):
            positions.update((width / 2, facade.length - width / 2))
        if style in ('CORNERS_CENTER', 'FULL'):
            positions.add(facade.length / 2)
        if style in ('BETWEEN_WINDOWS', 'FULL'):
            positions.update(facade.bays[1:-1])
        nx, ny = facade.normal
        for u in sorted(positions):
            u0, u1 = u - width / 2, u + width / 2
            if any(o.u0 < u1 and o.u1 > u0 and o.kind != 'window' for o in facade.openings) \
                    and style != 'CORNERS':
                continue
            height = _profile_min(facade, field, max(0.0, u0), min(facade.length, u1), tier.top)
            if height - facade.base < 1.0:
                continue
            ax, ay = facade.point(u0)
            bx, by = facade.point(u1)
            outline = [(ax - nx * .02, ay - ny * .02), (bx - nx * .02, by - ny * .02),
                       (bx + nx * depth, by + ny * depth), (ax + nx * depth, ay + ny * depth)]
            solids.prism(mesh, _ccw(outline), facade.base, height, MAT_WALLS)


def _cornices(mesh, spec, field):
    """Projecting bands at the roof line and the first-floor line, on intact stretches."""
    tier = spec.tiers[0]
    bands = []
    if len(spec.levels) > 1:
        z = spec.levels[1].z
        bands.append((z - spec.slab - .05, z + .1, .12))
    if tier is spec.tiers[-1]:
        bands.append((tier.top - .45, tier.top - .1, .3))
    for z0, z1, depth in bands:
        for facade in tier.facades:
            profile = field.wall_profile(facade.origin, facade.direction, 0.0, facade.length,
                                         side=facade.side)
            ends = (-depth, facade.length + depth) if facade.side in ('front', 'back') else (0.0, facade.length)
            for a, b in _intact_runs(profile, ends, z1):
                if any(o.u0 < b and o.u1 > a and max(z for _, z in o.top) > z0 and
                       min(z for _, z in o.bottom) < z1 for o in facade.openings):
                    for a2, b2 in _clear_runs(facade, a, b, z0, z1):
                        _band(mesh, facade, a2, b2, z0, z1, depth)
                else:
                    _band(mesh, facade, a, b, z0, z1, depth)


def _intact_runs(profile, ends, z):
    interp = geom2d.interp
    a, b = ends
    step = .25
    runs = []
    start = None
    u = a
    while u <= b + 1e-9:
        ok = interp(profile, min(max(u, profile[0][0]), profile[-1][0])) >= z + .05
        if ok and start is None:
            start = u
        if not ok and start is not None:
            if u - step - start > .5:
                runs.append((start, u - step))
            start = None
        u += step
    if start is not None and b - start > .5:
        runs.append((start, b))
    return runs


def _clear_runs(facade, a, b, z0, z1):
    blocked = sorted((o.u0 - .05, o.u1 + .05) for o in facade.openings
                     if max(z for _, z in o.top) > z0 and min(z for _, z in o.bottom) < z1)
    runs, cursor = [], a
    for lo, hi in blocked:
        if lo > cursor + .3:
            runs.append((cursor, min(lo, b)))
        cursor = max(cursor, hi)
    if b > cursor + .3:
        runs.append((cursor, b))
    return [(lo, hi) for lo, hi in runs if hi > lo]


def _band(mesh, facade, u0, u1, z0, z1, depth, embed=.035):
    """Projecting band on a facade; ``embed`` differs per feature so hidden
    back faces of crossing features never share a plane."""
    nx, ny = facade.normal
    ax, ay = facade.point(u0)
    bx, by = facade.point(u1)
    outline = [(ax - nx * embed, ay - ny * embed), (bx - nx * embed, by - ny * embed),
               (bx + nx * depth, by + ny * depth), (ax + nx * depth, ay + ny * depth)]
    solids.prism(mesh, _ccw(outline), z0, z1, MAT_WALLS)


def _canopy(mesh, spec, field):
    front = spec.ground_facade('front')
    doors = [o for o in front.openings if o.kind == 'door']
    if not doors:
        return
    door = max(doors, key=lambda o: o.u1 - o.u0)
    head = max(z for _, z in door.top)
    z0 = head + .35
    if z0 + .25 > spec.levels[0].ceiling - .1 or field.height(*front.point((door.u0 + door.u1) / 2)) < z0 + 1:
        return
    u0 = max(0.0, door.u0 - 1.0)
    u1 = min(front.length, door.u1 + 1.0)
    depth = 2.2 if spec.lobby != 'NONE' else 1.2
    _band(mesh, front, u0, u1, z0, z0 + .25, depth, embed=.05)


def _ccw(points):
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return points if area > 0 else list(reversed(points))


# -- interiors ---------------------------------------------------------------

def _interiors(mesh, spec, field, plan):
    for level_plan in plan.levels:
        level = spec.levels[level_plan.index]
        last = level.index == len(spec.levels) - 1
        ceiling = level.ceiling - (spec.roof_slab if last else spec.slab)
        if last and spec.roof_kind == 'NONE':
            ceiling = level.ceiling
        for wall in level_plan.walls:
            _partition(mesh, field, wall, level.z, ceiling)
        if level_plan.stair is not None and not last:
            boxes, *_ = layouts.stair_steps(level_plan.stair, level.height)
            for x0, y0, z0, x1, y1, z1 in boxes:
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                if field.damaged and (field.height(cx, cy) < level.z + z1 + .2 or
                                      field.in_blast(cx, cy, level.z + z1 / 2)):
                    continue
                solids.box(mesh, x0, y0, level.z + z0, x1, y1, level.z + z1, MAT_STAIRS)
        for x0, y0, x1, y1, height in level_plan.fixtures:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if field.damaged and (field.height(cx, cy) < level.z + height + .2 or
                                  field.in_blast(cx, cy, level.z + height / 2)):
                continue
            solids.box(mesh, x0, y0, level.z, x1, y1, level.z + height, MAT_INTERIOR_WALL)


def _partition(mesh, field, wall, z, ceiling):
    (ax, ay), (bx, by) = wall.start, wall.end
    t = wall.thickness
    if abs(ay - by) < 1e-9:
        origin, direction, length = (ax, ay - t / 2), (1.0, 0.0), bx - ax
    else:
        origin, direction, length = (ax + t / 2, ay), (0.0, 1.0), by - ay
    if length < .05:
        return
    top = field.line_profile(ax, ay, bx, by, ceiling)
    blown = []
    for u0, u1, z0, z1 in field.blast_spans((ax, ay), direction, 0.0, length, z, ceiling):
        if z1 - z0 >= .6 * (ceiling - z):
            blown.append((max(0.0, u0), min(length, u1)))
    blown = _merge_spans(blown)
    openings = [solids.Opening(a, b, [(a, z), (b, z)], [(a, ceiling + 1), (b, ceiling + 1)],
                               MAT_INTERIOR_WALL, 'breach') for a, b in blown if b - a > .05]
    for offset, width, height in wall.openings:
        if any(offset < b + .05 and offset + width > a - .05 for a, b in blown):
            continue
        openings.append(solids.Opening.rect(offset, offset + width, z, z + height,
                                            MAT_DOOR_FRAME, 'door'))
    solids.wall_solid(mesh, origin, direction, t, 0.0, length, z, top, openings, MAT_INTERIOR_WALL)


def _merge_spans(spans):
    merged = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1] + .05:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged
