# SPDX-License-Identifier: GPL-3.0-or-later
"""Rubble as closed solids: mounds, piles, fills and the collapsed-lot heap."""
import math

from . import solids
from .meshdata import MAT_RUBBLE


def mound(mesh, rng, cx, cy, rx, ry, peak, segments=10, rings=3, base=0.0):
    """Jittered rubble mound with a flat underside."""
    angles = [math.tau * index / segments for index in range(segments)]
    jitter = [rng.uniform(.82, 1.15) for _ in range(segments)]
    apex = mesh.vert((cx + rng.uniform(-.15, .15) * rx, cy + rng.uniform(-.15, .15) * ry,
                      base + peak))
    rows = []
    for ring in range(1, rings + 1):
        t = ring / rings
        height = 0.0 if ring == rings else peak * (1 - t) ** 1.3 * rng.uniform(.9, 1.08)
        rows.append([mesh.vert((cx + math.cos(a) * rx * t * jitter[i],
                                cy + math.sin(a) * ry * t * jitter[i], base + max(0.0, height)))
                     for i, a in enumerate(angles)])
    for index in range(segments):
        following = (index + 1) % segments
        mesh.face((apex, rows[0][index], rows[0][following]), MAT_RUBBLE)
    for ring in range(1, rings):
        inner, outer = rows[ring - 1], rows[ring]
        for index in range(segments):
            following = (index + 1) % segments
            mesh.face((inner[index], outer[index], outer[following], inner[following]), MAT_RUBBLE)
    mesh.face(list(reversed(rows[-1])), MAT_RUBBLE)


def pile(mesh, rng, cx, cy, radius, height, base=0.0):
    """Small irregular cone of debris."""
    sides = rng.randint(5, 7)
    ring = []
    for index in range(sides):
        angle = math.tau * index / sides + rng.uniform(-.3, .3) / sides * 3
        r = radius * rng.uniform(.7, 1.0)
        ring.append(mesh.vert((cx + r * math.cos(angle), cy + r * math.sin(angle), base)))
    apex = mesh.vert((cx + rng.uniform(-.3, .3) * radius, cy + rng.uniform(-.3, .3) * radius,
                      base + height * rng.uniform(.8, 1.0)))
    mesh.face(list(reversed(ring)), MAT_RUBBLE)
    for index in range(sides):
        mesh.face((ring[index], ring[(index + 1) % sides], apex), MAT_RUBBLE)


def slanted_fill(mesh, rng, rect, height, cap, base=0.0):
    """Box of rubble with a tilted, uneven top (partially filled storeys)."""
    x0, y0, x1, y1 = rect
    sx, sy = rng.uniform(-.3, .3), rng.uniform(-.3, .3)
    heights = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        h = height + sx * (x - x0) + sy * (y - y0) + rng.uniform(-.2, .2)
        heights.append(min(cap, max(base + .3, h)))
    corners = [(x0, y0, base), (x1, y0, base), (x1, y1, base), (x0, y1, base)]
    corners += [(x, y, h) for (x, y, _), h in zip(corners, heights)]
    solids.hexahedron(mesh, corners, MAT_RUBBLE)


def interior_fill(mesh, rng, spec, field, params):
    """FILLED / PARTIAL / RUBBLE_PILES interiors, kept below the damage line."""
    mode = params.get('interior_fill', 'NONE')
    if mode == 'NONE':
        return
    cap = min(spec.top - .1, field.lowest() - .1)
    if params.get('has_patio') and len(spec.levels) >= 2:
        cap = min(cap, spec.levels[-1].z - .1)
    if mode == 'FILLED':
        _tiered_fill(mesh, rng, spec, max(.3, cap))
    elif mode == 'PARTIAL':
        floors = len(spec.levels)
        fill = min(int(params.get('fill_floors', max(1, floors // 2))), floors - 1)
        if fill > 0:
            height = min(spec.levels[fill].z - rng.uniform(.3, .6), cap - .5)
            _tiered_fill(mesh, rng, spec, height, cap)
    elif mode == 'RUBBLE_PILES':
        x0, y0, x1, y1 = _fill_rect(spec, spec.tiers[0])
        density = float(params.get('rubble_density', .3))
        placed = []
        for _ in range(min(5, 2 + int(density * 3))):
            for _attempt in range(10):
                cx, cy = rng.uniform(x0 + .8, x1 - .8), rng.uniform(y0 + .8, y1 - .8)
                radius = rng.uniform(.4, min(1.2, min(x1 - x0, y1 - y0) * .25))
                if all(math.hypot(cx - px, cy - py) >= (radius + pr) * .8 for px, py, pr in placed):
                    placed.append((cx, cy, radius))
                    pile(mesh, rng, cx, cy, radius, rng.uniform(.3, .8))
                    break


def _fill_rect(spec, tier):
    """A tier's interior, inset so the fill never shares a plane with slab
    edges or wall faces."""
    x0, y0, x1, y1 = tier.rect
    inset = spec.t + .03
    return (x0 + inset, y0 + inset, x1 - inset, y1 - inset)


def _tiered_fill(mesh, rng, spec, height, cap=None):
    """Fill up to ``height`` inside each tier's own walls: a podium's fill
    stops in the slab under the set-back tower, which carries on narrower.
    With ``cap``, the top piece gets a tilted, uneven surface."""
    tiers = spec.tiers
    for index, tier in enumerate(tiers):
        base = 0.0 if index == 0 else spec.levels[tier.first].z - spec.slab / 2
        if height <= base + .3:
            break
        ceiling = (spec.levels[tiers[index + 1].first].z - spec.slab / 2
                   if index + 1 < len(tiers) else math.inf)
        rect = _fill_rect(spec, tier)
        if rect[2] - rect[0] < .5 or rect[3] - rect[1] < .5:
            break
        if height <= ceiling and cap is not None:
            slanted_fill(mesh, rng, rect, height, min(cap, ceiling), base)
        else:
            solids.box(mesh, rect[0], rect[1], base, rect[2], rect[3], min(height, ceiling),
                       MAT_RUBBLE)
        if height <= ceiling:
            break


def exterior_piles(mesh, rng, spec, params):
    if not params.get('exterior_rubble', False):
        return
    width, depth = spec.width, spec.depth
    spread = float(params.get('rubble_spread', 2.0))
    for _ in range(int(params.get('exterior_rubble_piles', 4))):
        side = rng.randrange(4)
        if side == 0:
            x, y = rng.uniform(.5, width - .5), rng.uniform(-spread * .8, -.3)
        elif side == 1:
            x, y = rng.uniform(.5, width - .5), rng.uniform(depth + .3, depth + spread * .8)
        elif side == 2:
            x, y = rng.uniform(-spread * .8, -.3), rng.uniform(.5, depth - .5)
        else:
            x, y = rng.uniform(width + .3, width + spread * .8), rng.uniform(.5, depth - .5)
        pile(mesh, rng, x, y, rng.uniform(.4, 1.0), rng.uniform(.2, .6))


def corner_mound(mesh, rng, spec, corner):
    """Debris at the foot of a collapsed corner."""
    sign_x, sign_y = corner
    width, depth = spec.width, spec.depth
    cx = (0 if sign_x < 0 else width) - sign_x * width * .12
    cy = (0 if sign_y < 0 else depth) - sign_y * depth * .12
    mound(mesh, rng, cx, cy, width * rng.uniform(.2, .34), depth * rng.uniform(.2, .34),
          rng.uniform(1.4, 3.0), segments=9)


def interior_mound(mesh, rng, spec):
    """Mound inside a standing wall ring, visible from above."""
    x0, y0, x1, y1 = spec.interior_rect(0)
    peak = min(spec.top * .55, rng.uniform(1.8, 3.6))
    # The rim jitters out to 1.15 radii: keep it inside the walls.
    mound(mesh, rng, (x0 + x1) / 2, (y0 + y1) / 2, max(1.5, (x1 - x0) / 2 / 1.16 - .3),
          max(1.5, (y1 - y0) / 2 / 1.16 - .3), peak)


def collapsed_lot(mesh, rng, width, depth):
    """Overlapping low mounds where a building came down (centred on the lot)."""
    scale = rng.uniform(.38, .5)
    mound(mesh, rng, rng.uniform(-.06, .06) * width, rng.uniform(-.06, .06) * depth,
          width * scale, depth * scale, rng.uniform(2.0, 3.4), segments=12)
    mound(mesh, rng, rng.uniform(-.2, .2) * width, rng.uniform(-.2, .2) * depth,
          width * scale * rng.uniform(.45, .65), depth * scale * rng.uniform(.45, .65),
          rng.uniform(.8, 1.6), segments=12)
    if rng.random() < .6:
        mound(mesh, rng, rng.uniform(-.24, .24) * width, rng.uniform(-.24, .24) * depth,
              width * scale * rng.uniform(.3, .5), depth * scale * rng.uniform(.3, .5),
              rng.uniform(.5, 1.1), segments=12)


# -- gutted floors -----------------------------------------------------------

REACH = 1.16          # A mound's rim jitters out to 1.15 radii.
DEBRIS_CLEAR = .3     # Kept clear round stairs, shafts, slab openings and walls.
DOOR_CLEAR = 1.3      # Kept clear either side of a doorway.
STREET_CLEAR = 2.0    # Kept clear inside a street door.
RIDGE_STEP = 2.4      # Spacing of the low ridges along a fallen partition.
SLAB_CLEARANCE = .3   # As shell.SLAB_CLEARANCE: where a slab still stands.
WALKWAYS = ('corridor', 'hall', 'landing')   # Kept clear of debris.
FLOOR_HEAPS = 10      # Most heaps and strewn pieces on one floor (big tower
FLOOR_PIECES = 40     # plates would otherwise carry thousands of faces).


def floor_debris(mesh, rng, spec, field, plan):
    """Rubble on gutted floors: low broken ridges where the partitions came
    down (``LevelPlan.fallen``), heaps against the walls still standing and
    broken pieces strewn over each room.

    Stairs, lift shafts, columns, slab openings, doorways, corridors and the
    space inside street doors stay clear, and no debris lies where the floor
    has broken away.
    """
    for lp in plan.levels:
        level = spec.levels[lp.index]
        x0, y0, x1, y1 = spec.interior_rect(lp.index)
        inner = (x0 + .05, y0 + .05, x1 - .05, y1 - .05)
        clear = _kept_clear(spec, lp)
        # Leave the collapse's own debris on this floor alone.
        clear += [(x - rx * REACH, y - ry * REACH, x + rx * REACH, y + ry * REACH)
                  for x, y, rx, ry, _, base in field.debris if abs(base - level.z) < .5]
        placed = []

        def put(cx, cy, rx, ry, peak, segments=8, rings=2):
            box = (cx - rx * REACH, cy - ry * REACH, cx + rx * REACH, cy + ry * REACH)
            if not (inner[0] <= box[0] and inner[1] <= box[1] and
                    box[2] <= inner[2] and box[3] <= inner[3]):
                return
            if any(_overlap(box, other) for other in clear + placed):
                return
            if field.damaged:
                points = [(cx, cy)] + [(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
                for x, y in points:
                    if field.in_blast(x, y, level.z + .3):
                        return
                    if lp.index > 0 and field.slab_value(x, y, level.z, SLAB_CLEARANCE) < .2:
                        return
            placed.append(box)
            # Sunk into the slab deeper than the damage debris: the underside
            # shares no plane with the slab, the partitions or another mound.
            mound(mesh, rng, cx, cy, rx, ry, peak, segments=segments, rings=rings,
                  base=level.z - .05)
            return True

        def strew(cx, cy, radius, height):
            box = (cx - radius, cy - radius, cx + radius, cy + radius)
            if not (inner[0] <= box[0] and inner[1] <= box[1] and
                    box[2] <= inner[2] and box[3] <= inner[3]):
                return
            if any(_overlap(box, other) for other in clear + placed):
                return
            if field.damaged and (field.in_blast(cx, cy, level.z + .3) or (
                    lp.index > 0 and field.slab_value(cx, cy, level.z, SLAB_CLEARANCE) < .2)):
                return
            placed.append(box)
            pile(mesh, rng, cx, cy, radius, height, base=level.z - .05)
            return True

        for axis, line, lo, hi in lp.fallen:
            count = max(1, int((hi - lo) / RIDGE_STEP))
            for k in range(count):
                along, across = rng.uniform(.45, .8), rng.uniform(.28, .42)
                peak = rng.uniform(.16, .32)
                u = lo + (k + .5) * (hi - lo) / count + rng.uniform(-.3, .3)
                off = line + rng.uniform(-.12, .12)
                if rng.random() < .3:
                    continue
                if axis == 'x':
                    put(u, off, along, across, peak, segments=8, rings=2)
                else:
                    put(off, u, across, along, peak, segments=8, rings=2)
        rooms = [room for room in lp.rooms if room.kind not in ('stair', 'shaft') + WALKWAYS]
        rng.shuffle(rooms)
        budget = {'heaps': FLOOR_HEAPS, 'pieces': FLOOR_PIECES}
        for room in rooms:
            rx0, ry0, rx1, ry1 = room.rect
            area = (rx1 - rx0) * (ry1 - ry0)
            # Heaps against the walls: debris collects where it fell.
            for _ in range(min(5, 1 + int(area / 22))):
                size = min(rng.uniform(.6, 1.3), (rx1 - rx0) / 4.5, (ry1 - ry0) / 4.5)
                rx, ry = size * rng.uniform(.8, 1.2), size * rng.uniform(.8, 1.2)
                peak = rng.uniform(.35, .8)
                side = rng.randrange(4)
                pad_x, pad_y = rx * REACH + .2, ry * REACH + .2
                if rx1 - rx0 <= 2 * pad_x or ry1 - ry0 <= 2 * pad_y:
                    continue
                cx = rng.uniform(rx0 + pad_x, rx1 - pad_x)
                cy = rng.uniform(ry0 + pad_y, ry1 - pad_y)
                cx, cy = ((rx0 + pad_x, cy), (rx1 - pad_x, cy),
                          (cx, ry0 + pad_y), (cx, ry1 - pad_y))[side]
                if budget['heaps'] > 0 and put(cx, cy, rx, ry, peak):
                    budget['heaps'] -= 1
            # Broken pieces strewn over the floor.
            for _ in range(min(24, int(area / 2.5))):
                radius = rng.uniform(.14, .34)
                height = rng.uniform(.08, .26)
                cx = rng.uniform(rx0 + .3, rx1 - .3)
                cy = rng.uniform(ry0 + .3, ry1 - .3)
                if budget['pieces'] > 0 and strew(cx, cy, radius, height):
                    budget['pieces'] -= 1


def _kept_clear(spec, lp):
    clear = []
    for room in lp.rooms:
        if room.kind in ('stair', 'shaft'):
            clear.append(_grow(room.rect, DEBRIS_CLEAR))
    for hole in lp.holes:
        clear.append(_grow(hole, DEBRIS_CLEAR))
    for x, y, size in lp.columns:
        clear.append(_grow((x - size / 2, y - size / 2, x + size / 2, y + size / 2), .1))
    for _, _, axis, line, centre, width in lp.doors:
        half = width / 2 + .3
        if axis == 'x':
            clear.append((centre - half, line - DOOR_CLEAR, centre + half, line + DOOR_CLEAR))
        else:
            clear.append((line - DOOR_CLEAR, centre - half, line + DOOR_CLEAR, centre + half))
    for wall in lp.walls:
        (ax, ay), (bx, by) = wall.start, wall.end
        clear.append(_grow((min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)),
                           wall.thickness / 2 + .05))
    if lp.index == 0:
        for side, centre, width in spec.entrances():
            half = width / 2 + .3
            clear.append({'front': (centre - half, -1.0, centre + half, STREET_CLEAR),
                          'back': (centre - half, spec.depth - STREET_CLEAR, centre + half,
                                   spec.depth + 1.0),
                          'left': (-1.0, centre - half, STREET_CLEAR, centre + half),
                          'right': (spec.width - STREET_CLEAR, centre - half, spec.width + 1.0,
                                    centre + half)}[side])
    return clear


def _grow(rect, by):
    return (rect[0] - by, rect[1] - by, rect[2] + by, rect[3] + by)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
