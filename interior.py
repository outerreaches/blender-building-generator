# SPDX-License-Identifier: GPL-3.0-or-later
"""Interior facts for the game: rooms to furnish, lifts, railings and
fixtures (pure Python).

Furniture, railings, lift doors and lift cars are game assets, so none of
them is modelled. ``interior_facts(building)`` lists where they go, in the
building's object space (footprint centred on the origin, z up from the
ground floor), with the shell's own damage rules: a room, rail, lift door or
fixture is listed only where the mesh keeps the floor or flight under it.
"""
import math

from . import dims, geom2d, layouts
from .shell import SLAB_CLEARANCE

RAIL_HEIGHT = .9        # Handrail above the stair nosings.
GUARD_HEIGHT = 1.1      # Guard rail at a floor edge.
RAMP_RAIL_HEIGHT = 1.0
LIFT_CAR_HEIGHT = 2.4
SAMPLE = .5             # Grid spacing for the standing share of a floor.
MIN_STANDING = .1       # Rooms with less floor left are left out.
MIN_RUN = .6            # Shortest wall run worth listing.
WALL_STANDS = 2.0       # A wall run needs this much wall above the floor.
DOOR_MARGIN = .1        # Wall kept clear either side of a door.
FIXTURE_KINDS = ('bar_counter', 'reception_desk', 'service_counter', 'shop_counter')


def interior_facts(building):
    """{'rooms', 'lifts', 'railings', 'fixtures'} for a built ``shell.Building``."""
    spec, plan, field = building.spec, building.plan, building.field
    cx, cy = spec.width / 2, spec.depth / 2
    facts = {'rooms': [], 'lifts': [], 'railings': [], 'fixtures': []}
    built = {lp.index: lp for lp in plan.levels}
    for lp in plan.levels:
        level = spec.levels[lp.index]
        for room in lp.rooms:
            if room.kind == 'shaft':
                continue
            entry = _room(spec, field, lp, level, room)
            if entry is not None:
                facts['rooms'].append(entry)
        for x0, y0, x1, y1, height, kind in lp.fixtures:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            if field.damaged and (field.height(mx, my) < level.z + height + .2 or
                                  field.in_blast(mx, my, level.z + height / 2) or
                                  not _has_floor(field, level, mx, my)):
                continue
            facts['fixtures'].append({'kind': kind, 'floor': lp.index, 'x': mx, 'y': my,
                                      'z': level.z, 'facing': (0.0, -1.0),
                                      'size': (x1 - x0, y1 - y0, height)})
    facts['lifts'] = _lifts(spec, field, plan)
    facts['railings'] = _railings(spec, field, plan, built)
    return _centred(facts, cx, cy)


# -- rooms -------------------------------------------------------------------

def _has_floor(field, level, x, y):
    """Whether the floor of ``level`` stands at (x, y), as the shell builds it."""
    if level.index == 0 or not field.damaged:
        return True
    return field.slab_value(x, y, level.z, SLAB_CLEARANCE) >= 0


def _zone(field, z):
    """Plan box outside which nothing is broken at height ``z`` (None: intact)."""
    return field.damaged_bounds(z) if field.damaged else None


def _ceiling(spec, level):
    """Clear height of a storey, as the shell builds its partitions."""
    last = level.index == len(spec.levels) - 1
    if last and spec.roof_kind == 'NONE':
        return level.height
    return level.height - (spec.roof_slab if last else spec.slab)


def _inside(rect, x, y):
    return rect[0] < x < rect[2] and rect[1] < y < rect[3]


def _within(rect, x, y):
    return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]


def _room(spec, field, lp, level, room):
    x0, y0, x1, y1 = room.rect
    outer = spec.interior_rect(lp.index)
    has_slabs = lp.index == 0 or spec.has_slabs
    clear = _clear_rect(room.rect, outer, lp.walls)
    ceiling = _ceiling(spec, level)
    # Share of the floor (outside designed openings) and of the storey above
    # that still stand.
    floor, above, total = 0, 0, 0
    floor_zone = _zone(field, level.z + SLAB_CLEARANCE)
    top = level.z + level.height - .05
    above_zone = _zone(field, top)
    nx = max(1, round((clear[2] - clear[0]) / SAMPLE))
    ny = max(1, round((clear[3] - clear[1]) / SAMPLE))
    for i in range(nx):
        for j in range(ny):
            px = clear[0] + (clear[2] - clear[0]) * (i + .5) / nx
            py = clear[1] + (clear[3] - clear[1]) * (j + .5) / ny
            if any(_inside(hole, px, py) for hole in lp.holes):
                continue
            total += 1
            floor += has_slabs and (floor_zone is None or not _within(floor_zone, px, py) or
                                    _has_floor(field, level, px, py))
            above += (above_zone is None or not _within(above_zone, px, py) or
                      field.height(px, py) >= top)
    standing = floor / total if total else 1.0
    if standing < MIN_STANDING:
        return None
    doors, door_spans = _room_doors(spec, lp, level, room, clear)
    windows, gaps = _room_windows(spec, lp, level, clear)
    return {'name': room.name, 'kind': room.kind, 'floor': lp.index, 'unit': room.unit or '',
            'group': room.group or '', 'rect': clear, 'z': level.z, 'height': ceiling,
            'standing': round(standing, 3), 'ceiling': round(above / total if total else 1.0, 3),
            'doors': doors, 'windows': windows,
            'wall_runs': _wall_runs(spec, field, lp, level, room.rect, clear, outer,
                                    door_spans, gaps)}


def _clear_rect(rect, outer, walls, eps=1e-6):
    """Room rect inside its partitions (half their thickness off each side
    that has one; the outer walls already bound the interior rect)."""
    x0, y0, x1, y1 = rect

    def half(line, horizontal, lo, hi):
        widest = 0.0
        for wall in walls:
            (ax, ay), (bx, by) = wall.start, wall.end
            if horizontal and abs(ay - by) < eps and abs(ay - line) < eps:
                if min(hi, max(ax, bx)) - max(lo, min(ax, bx)) > .05:
                    widest = max(widest, wall.thickness / 2)
            if not horizontal and abs(ax - bx) < eps and abs(ax - line) < eps:
                if min(hi, max(ay, by)) - max(lo, min(ay, by)) > .05:
                    widest = max(widest, wall.thickness / 2)
        return widest
    return (x0 + (0.0 if abs(x0 - outer[0]) < eps else half(x0, False, y0, y1)),
            y0 + (0.0 if abs(y0 - outer[1]) < eps else half(y0, True, x0, x1)),
            x1 - (0.0 if abs(x1 - outer[2]) < eps else half(x1, False, y0, y1)),
            y1 - (0.0 if abs(y1 - outer[3]) < eps else half(y1, True, x0, x1)))


def _room_doors(spec, lp, level, room, clear):
    """Doors into the room: the openings in the partitions on its sides and
    the street doors on its outer walls, as (x, y at floor on the wall line,
    inward normal, width, height, room on the other side), plus their spans
    per side for the wall runs."""
    doors, spans = [], []
    x0, y0, x1, y1 = room.rect
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    for wall in lp.walls:
        (ax, ay), (bx, by) = wall.start, wall.end
        if abs(ay - by) < 1e-6 and (abs(ay - y0) < 1e-6 or abs(ay - y1) < 1e-6):
            axis, line, origin, sign, lo, hi = 'x', ay, ax, 1.0 if bx >= ax else -1.0, x0, x1
        elif abs(ax - bx) < 1e-6 and (abs(ax - x0) < 1e-6 or abs(ax - x1) < 1e-6):
            axis, line, origin, sign, lo, hi = 'y', ax, ay, 1.0 if by >= ay else -1.0, y0, y1
        else:
            continue
        for offset, width, height in wall.openings:
            centre = origin + sign * (offset + width / 2)
            if not lo - 1e-6 <= centre <= hi + 1e-6:
                continue
            if axis == 'x':
                x, y, normal = centre, line, (0.0, 1.0 if my > line else -1.0)
            else:
                x, y, normal = line, centre, (1.0 if mx > line else -1.0, 0.0)
            across = (x - normal[0] * .3, y - normal[1] * .3)
            other = next((r.name for r in lp.rooms if r is not room and _inside(r.rect, *across)), '')
            doors.append({'x': x, 'y': y, 'normal': normal, 'width': width, 'height': height,
                          'to': other})
            spans.append((axis, line, centre - width / 2, centre + width / 2))
    tier = spec.tiers[spec.tier_of(lp.index)]
    for facade in tier.facades:
        fnx, fny = facade.normal
        for opening in facade.openings:
            if opening.kind != 'door':
                continue
            bottom = min(z for _, z in opening.bottom)
            if abs(bottom - level.z) > .05:
                continue
            u = (opening.u0 + opening.u1) / 2
            ox, oy = facade.point(u)
            x, y = ox - fnx * spec.t, oy - fny * spec.t
            if not _on_edge(room.rect, x, y):
                continue
            width = opening.u1 - opening.u0
            top = max(z for _, z in opening.top)
            doors.append({'x': x, 'y': y, 'normal': (-fnx, -fny), 'width': width,
                          'height': top - bottom, 'to': 'street'})
            axis = 'x' if abs(fny) > .5 else 'y'
            along = x if axis == 'x' else y
            spans.append((axis, y if axis == 'x' else x, along - width / 2, along + width / 2))
    return doors, spans


def _on_edge(rect, x, y, eps=.05):
    x0, y0, x1, y1 = rect
    on_x = (abs(y - y0) < eps or abs(y - y1) < eps) and x0 - eps <= x <= x1 + eps
    on_y = (abs(x - x0) < eps or abs(x - x1) < eps) and y0 - eps <= y <= y1 + eps
    return on_x or on_y


def _facade_frame(spec, facade):
    """(axis, inner face line, (point -> u), (u -> along)) of a facade."""
    (ox, oy), (dx, dy) = facade.origin, facade.direction
    nx, ny = facade.normal
    if abs(dy) < 1e-9:           # Runs along x: the wall line is y = const.
        return 'x', oy - ny * spec.t, (lambda along: (along - ox) * dx), (lambda u: ox + dx * u)
    return 'y', ox - nx * spec.t, (lambda along: (along - oy) * dy), (lambda u: oy + dy * u)


def _room_windows(spec, lp, level, clear):
    """Windows along the room's outer walls, and every opening (windows,
    doors and damage) as (axis, line, a, b) spans for the wall runs."""
    windows, gaps = [], []
    tier = spec.tiers[spec.tier_of(lp.index)]
    top = level.z + WALL_STANDS
    for facade in tier.facades:
        axis, line, _, along = _facade_frame(spec, facade)
        x0, y0, x1, y1 = clear
        if axis == 'x':
            if not (abs(line - y0) < .05 or abs(line - y1) < .05):
                continue
            lo, hi = x0, x1
        else:
            if not (abs(line - x0) < .05 or abs(line - x1) < .05):
                continue
            lo, hi = y0, y1
        nx, ny = facade.normal
        for opening in facade.openings:
            bottom = min(z for _, z in opening.bottom)
            head = max(z for _, z in opening.top)
            a, b = sorted((along(opening.u0), along(opening.u1)))
            a, b = max(a, lo), min(b, hi)
            if b - a < .05:
                continue
            if bottom < top and head > level.z:
                gaps.append((axis, line, a, b))
            # A window belongs to the storey just above its bottom (glazing and
            # broken sills can start a little below their floor).
            if opening.kind in ('window', 'notch') and level.z <= bottom + .3 < level.z + level.height:
                sill = max(0.0, bottom - level.z)
                head_room = min(head, level.z + _ceiling(spec, level)) - level.z
                if head_room - sill < .1:
                    continue
                mid = (a + b) / 2
                x, y = (mid, line) if axis == 'x' else (line, mid)
                windows.append({'x': x, 'y': y, 'normal': (nx, ny), 'width': b - a, 'sill': sill,
                                'head': head_room, 'broken': opening.kind == 'notch'})
    return windows, gaps


def _wall_runs(spec, field, lp, level, rect, clear, outer, door_spans, gaps):
    """Stretches of standing, unbroken wall along the clear rect: (x0, y0,
    x1, y1, inward normal) at floor level. Walls are judged as the shell
    builds them: partitions by their top profile and blown spans, outer
    walls by the facade's broken top (their holes are among ``gaps``)."""
    runs = []
    x0, y0, x1, y1 = clear
    ceiling = level.z + _ceiling(spec, level)
    sides = [('x', y0, x0, x1, (0.0, 1.0), rect[1], abs(rect[1] - outer[1]) < 1e-6),
             ('x', y1, x0, x1, (0.0, -1.0), rect[3], abs(rect[3] - outer[3]) < 1e-6),
             ('y', x0, y0, y1, (1.0, 0.0), rect[0], abs(rect[0] - outer[0]) < 1e-6),
             ('y', x1, y0, y1, (-1.0, 0.0), rect[2], abs(rect[2] - outer[2]) < 1e-6)]
    tier = spec.tiers[spec.tier_of(lp.index)]
    for axis, line, lo, hi, inward, wall_line, exterior in sides:
        pieces = []          # (a, b, standing spans) along the side
        if exterior:
            for facade in tier.facades:
                f_axis, f_line, to_u, _ = _facade_frame(spec, facade)
                if f_axis != axis or abs(f_line - line) > .05:
                    continue
                profile = field.wall_profile(facade.origin, facade.direction, facade.ua, facade.ub,
                                             side=facade.side)
                pieces.append((lo, hi, _above(lambda m: geom2d.interp(profile, to_u(m)),
                                              level.z + WALL_STANDS, lo, hi)))
        else:
            for wall in lp.walls:
                (ax, ay), (bx, by) = wall.start, wall.end
                if axis == 'x' and abs(ay - by) < 1e-6 and abs(ay - wall_line) < 1e-6:
                    start, direction = min(ax, bx), (1.0, 0.0)
                    a, b = max(lo, min(ax, bx)), min(hi, max(ax, bx))
                elif axis == 'y' and abs(ax - bx) < 1e-6 and abs(ax - wall_line) < 1e-6:
                    start, direction = min(ay, by), (0.0, 1.0)
                    a, b = max(lo, min(ay, by)), min(hi, max(ay, by))
                else:
                    continue
                if b - a < 1e-6:
                    continue
                length = math.hypot(bx - ax, by - ay)
                profile = field.line_profile(ax, ay, bx, by, ceiling)
                spans = _above(lambda m: geom2d.interp(profile, m - start),
                               level.z + WALL_STANDS, a, b)
                blown = [(start + u0, start + u1) for u0, u1, z0, z1 in
                         field.blast_spans((ax, ay), direction, 0.0, length, level.z, ceiling)
                         if z1 - z0 >= .6 * (ceiling - level.z)] if field.damaged else []
                pieces.append((a, b, _subtract(spans, blown)))
        cuts = [(a - DOOR_MARGIN, b + DOOR_MARGIN) for d_axis, d_line, a, b in door_spans
                if d_axis == axis and abs(d_line - wall_line) < .2]
        if exterior:
            cuts += [(a, b) for g_axis, g_line, a, b in gaps
                     if g_axis == axis and abs(g_line - line) < .05]
        for _, _, standing in pieces:
            for s0, e0 in _subtract(standing, cuts):
                if e0 - s0 >= MIN_RUN:
                    start = (s0, line) if axis == 'x' else (line, s0)
                    end = (e0, line) if axis == 'x' else (line, e0)
                    runs.append({'start': start, 'end': end, 'normal': inward})
    return runs


def _subtract(spans, cuts):
    for c0, c1 in sorted(cuts):
        result = []
        for a, b in spans:
            if c1 <= a or c0 >= b:
                result.append((a, b))
                continue
            if c0 > a:
                result.append((a, c0))
            if c1 < b:
                result.append((c1, b))
        spans = result
    return [(a, b) for a, b in spans if b - a > 1e-6]


def _above(top, height, a, b, step=.25):
    """Spans of [a, b] where ``top(m)`` reaches ``height``."""
    count = max(1, math.ceil((b - a) / step))
    kept, start = [], None
    for k in range(count + 1):
        m = a + (b - a) * k / count
        ok = top(m) >= height - 1e-6
        if ok and start is None:
            start = m
        if not ok and start is not None:
            kept.append((start, m))
            start = None
    if start is not None:
        kept.append((start, b))
    return [(s, e) for s, e in kept if e - s > 1e-6]


# -- lifts -------------------------------------------------------------------

def _lifts(spec, field, plan):
    # One lift per shaft position; rooms are named per storey (lift0_3).
    shafts = {}
    for lp in plan.levels:
        for room in lp.rooms:
            if room.kind == 'shaft':
                key = tuple(round(v, 3) for v in room.rect)
                shafts.setdefault(key, []).append((lp, room))
    lifts = []
    for number, (key, stops) in enumerate(sorted(shafts.items())):
        name = stops[0][1].name.rsplit('_', 1)[0]
        doors = []
        for lp, room in stops:
            level = spec.levels[lp.index]
            mx, my = (room.rect[0] + room.rect[2]) / 2, (room.rect[1] + room.rect[3]) / 2
            for a, b, axis, line, centre, width in lp.doors:
                if room.name not in (a, b):
                    continue
                if axis == 'x':
                    x, y, normal = centre, line, (0.0, -1.0 if my > line else 1.0)
                else:
                    x, y, normal = line, centre, (-1.0 if mx > line else 1.0, 0.0)
                front = (x + normal[0] * .6, y + normal[1] * .6)
                if field.damaged and (field.height(x, y) < level.z + dims.DOOR_HEIGHT + .2 or
                                      field.in_blast(x, y, level.z + 1.2) or
                                      not _has_floor(field, level, *front)):
                    continue
                doors.append({'floor': lp.index, 'x': x, 'y': y, 'z': level.z, 'normal': normal,
                              'width': width, 'height': dims.DOOR_HEIGHT})
        if not doors:
            continue
        lp, room = stops[0]
        inset = room.wall / 2 + .05
        x0, y0, x1, y1 = room.rect
        rect = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
        served = sorted({door['floor'] for door in doors})
        bottom = spec.levels[stops[0][0].index].z
        top_level = spec.levels[served[-1]]
        lifts.append({'name': name, 'rect': rect, 'bottom': bottom,
                      'top': top_level.z + top_level.height, 'floors': served, 'doors': doors,
                      'car': {'floor': served[0], 'z': spec.levels[served[0]].z,
                              'height': LIFT_CAR_HEIGHT}})
    return lifts


# -- railings ----------------------------------------------------------------

def _railings(spec, field, plan, built):
    railings = []
    last = len(spec.levels) - 1
    for lp in plan.levels:
        level = spec.levels[lp.index]
        if lp.stair is not None and lp.index < last:
            points = [(x, y, level.z + z) for x, y, z in layouts.stair_railing(lp.stair, level.height)]
            # The steps the shell builds (same test as shell._interiors); a
            # rail point stays where it rests on one of them.
            steps = []
            for x0, y0, z0, x1, y1, z1 in layouts.stair_steps(lp.stair, level.height)[0]:
                mx, my = (x0 + x1) / 2, (y0 + y1) / 2
                if not field.damaged or (field.height(mx, my) >= level.z + z1 + .2 and
                                         not field.in_blast(mx, my, level.z + z1 / 2)):
                    steps.append((x0, y0, x1, y1, level.z + z1))

            def stands(x, y, z, steps=steps):
                return any(abs(top - z) < 1e-6 and x0 - 1e-6 <= x <= x1 + 1e-6 and
                           y0 - 1e-6 <= y <= y1 + 1e-6 for x0, y0, x1, y1, top in steps)
            for run in _runs(points, stands):
                railings.append({'kind': 'stair', 'floor': lp.index, 'points': run,
                                 'height': RAIL_HEIGHT})
        below = built.get(lp.index - 1)
        upper = lp.stair is not None and lp.index < last
        if below is not None and below.stair is not None and not upper:
            down = spec.levels[below.index]
            frame = layouts.StairFrame(below.stair, down.height)
            (ax, ay), (bx, by) = layouts.stair_hole_guard(below.stair, down.height)
            back = frame.point(frame.landing - .3, (frame.across - frame.flight) / 2)
            if _has_floor(field, level, *back):
                railings.append({'kind': 'guard', 'floor': lp.index,
                                 'points': [(ax, ay, level.z), (bx, by, level.z)],
                                 'height': GUARD_HEIGHT})
    for ramp in spec.params.get('ramps', ()) or ():
        index = ramp['level']
        if index + 1 >= len(spec.levels):
            continue
        z0, z1 = spec.levels[index].z, spec.levels[index + 1].z
        x0, y0, x1, y1 = ramp['rect']
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        if field.damaged and (field.height(mx, my) < z1 + .3 or field.in_blast(mx, my, (z0 + z1) / 2)):
            continue
        rise = ramp.get('rise', '+y')
        low, high = (z0, z1) if rise[0] == '+' else (z1, z0)
        if rise[1] == 'y':
            sides = [[(x, y0, low), (x, y1, high)] for x in (x0, x1)]
        else:
            sides = [[(x0, y, low), (x1, y, high)] for y in (y0, y1)]
        for side in sides:
            railings.append({'kind': 'ramp', 'floor': index, 'points': side,
                             'height': RAMP_RAIL_HEIGHT})
    return railings


def _runs(points, keep):
    """Split a polyline where its points fail ``keep(x, y, z)``."""
    runs, current = [], []
    for point in points:
        if keep(*point):
            current.append(point)
            continue
        if len(current) >= 2:
            runs.append(current)
        current = []
    if len(current) >= 2:
        runs.append(current)
    return runs


# -- object space ------------------------------------------------------------

def _centred(facts, cx, cy):
    """Move plan coordinates (0..width, 0..depth) to object space."""
    def p(x, y):
        return (round(x - cx, 4), round(y - cy, 4))
    for room in facts['rooms']:
        x0, y0, x1, y1 = room['rect']
        room['rect'] = p(x0, y0) + p(x1, y1)
        for item in room['doors'] + room['windows']:
            item['x'], item['y'] = p(item['x'], item['y'])
        for run in room['wall_runs']:
            run['start'], run['end'] = p(*run['start']), p(*run['end'])
    for lift in facts['lifts']:
        x0, y0, x1, y1 = lift['rect']
        lift['rect'] = p(x0, y0) + p(x1, y1)
        for door in lift['doors']:
            door['x'], door['y'] = p(door['x'], door['y'])
    for rail in facts['railings']:
        rail['points'] = [p(x, y) + (round(z, 4),) for x, y, z in rail['points']]
    for fixture in facts['fixtures']:
        fixture['x'], fixture['y'] = p(fixture['x'], fixture['y'])
    return facts
