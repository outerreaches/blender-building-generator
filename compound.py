# SPDX-License-Identifier: GPL-3.0-or-later
"""Floor plans for compound footprints (L, T, U, courtyard), pure Python.

Each wing's zone (``footprint.zones``) gets a corridor along it: a spine
along the main wing and the bars, a branch up each wing. Where a wing meets a
bar its corridor carries on through the bar's row to the spine (a stub), so
the corridors form one network; a courtyard gets a passage out to its court.
The stair stands in the main wing's back row, the lobby at the street door,
and flats, offices or shops fill the rows either side, cut at piers. Sheds
are one open hall across their wings. See docs/design/footprints.md.
"""
from dataclasses import dataclass, field

from . import dims, footprint
from .layouts import EPS, Plan, Tiling, _split_bays, stair_length, stair_width

DOUBLE = 11.5          # Across a zone for rooms both sides of a corridor,
SINGLE = 6.6           # for rooms on one side; narrower zones are a run of rooms.
UNITS = {'RESIDENTIAL': (4.6, 9.5), 'STOREFRONT': (4.6, 9.5), 'OFFICE': (3.2, 6.5),
         'CIVIC': (3.2, 6.5), 'HOTEL': (3.6, 5.0)}
SIDES = ('front', 'right', 'back', 'left')
PROGRAMS = ('RESIDENTIAL', 'STOREFRONT', 'OFFICE', 'CIVIC', 'HOTEL', 'WAREHOUSE')


class ZoneSide:
    """One side of a zone: where a wall may meet it. Along a facade only at
    a pier or a window-free stretch; along a joint (inside the building)
    anywhere."""

    def __init__(self, spec, zone, side):
        x0, y0, x1, y1 = zone.rect
        self.side = side
        self.along_x = side in ('front', 'back')
        self.lo, self.hi = (x0, x1) if self.along_x else (y0, y1)
        line = {'front': y0, 'back': y1, 'left': x0, 'right': x1}[side]
        outward = {'front': -1, 'back': 1, 'left': -1, 'right': 1}[side]
        self.facades = []
        self.blocked = []
        self.piers = []
        covered = []
        axis = 0 if self.along_x else 1
        for facade in spec.facades_on(side):
            origin_line = facade.origin[1] if self.along_x else facade.origin[0]
            if abs(origin_line - (line + outward * spec.t)) > 1e-4:
                continue
            a, b = sorted((facade.point(0)[axis], facade.point(facade.length)[axis]))
            if b < self.lo - EPS or a > self.hi + EPS:
                continue
            self.facades.append(facade)
            covered.append((max(a, self.lo), min(b, self.hi)))
            for opening in facade.openings:
                u0, u1 = facade.point(opening.u0)[axis], facade.point(opening.u1)[axis]
                self.blocked.append((min(u0, u1), max(u0, u1)))
            self.piers += [facade.point(u)[axis] for u in facade.bays]
        self.exterior = sorted(covered)
        self.joint = _gaps(self.lo, self.hi, self.exterior)

    def clear(self, value, half=dims.CORE_WALL / 2 + .05):
        """A wall of half-thickness ``half`` may meet the side at ``value``."""
        if value < self.lo - EPS or value > self.hi + EPS:
            return False
        if any(a - EPS <= value <= b + EPS for a, b in self.joint):
            return True
        return not any(a - half < value < b + half for a, b in self.blocked)

    def spots(self, lo=None, hi=None, step=.3):
        """Places a wall may meet the side in [lo, hi]: piers, the ends of
        window-free stretches, and a fine grid along joints."""
        lo = self.lo if lo is None else lo
        hi = self.hi if hi is None else hi
        found = [p for p in self.piers if lo - EPS <= p <= hi + EPS and self.clear(p, .1)]
        for a, b in self.joint:
            v = max(a, lo)
            while v <= min(b, hi) + EPS:
                found.append(v)
                v += step
        return sorted(set(round(v, 4) for v in found if self.clear(v)))


def _gaps(lo, hi, spans):
    gaps, cursor = [], lo
    for a, b in sorted(spans):
        if a > cursor + EPS:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi - EPS:
        gaps.append((cursor, hi))
    return gaps


@dataclass
class ZonePlan:
    zone: object
    corridor: tuple = None        # Rect, or None (a run of rooms).
    rows: list = field(default_factory=list)   # (rect, corridor side of the row)
    end: tuple = None             # A room across the far end (corridor stops short).


def _frame(zone):
    """(along lo, along hi, across lo, across hi) for a zone."""
    x0, y0, x1, y1 = zone.rect
    return (x0, x1, y0, y1) if zone.axis == 'x' else (y0, y1, x0, x1)


def _rect(zone, a0, a1, c0, c1):
    """A rect from along/across coordinates."""
    return (a0, c0, a1, c1) if zone.axis == 'x' else (c0, a0, c1, a1)


def _end_sides(zone):
    return ('left', 'right') if zone.axis == 'x' else ('front', 'back')


def _long_sides(zone):
    return ('front', 'back') if zone.axis == 'x' else ('left', 'right')


def _corridor_span(zone, sides, rng):
    """(c0, c1) across the zone for its corridor, its walls meeting both ends
    where they may, nearest the middle; and how many rows (2, 1 or 0)."""
    a0, a1, c0, c1 = _frame(zone)
    across = c1 - c0
    w = dims.CORRIDOR
    if across < SINGLE:
        return None, 0
    ends = [sides[s] for s in _end_sides(zone)]
    widest = w + 1.2              # A corridor up to 3 m wide, to land its walls.
    if across >= DOUBLE:
        middle = (c0 + c1) / 2
        options = []
        for a in _common(ends, c0 + 4.4, c1 - 4.4 - w):
            for b in _common(ends, a + w, min(a + widest, c1 - 4.4)):
                options.append((abs((a + b) / 2 - middle) + (b - a - w), a, b))
                break
        if options:
            _, a, b = min(options)
            return (a, b), 2
    # One row: the corridor along a long side (only its inner wall meets the ends).
    for lo, hi, near in ((c1 - widest, c1 - w, c1), (c0 + w, c0 + widest, c0)):
        found = [v for v in _common(ends, lo, hi) if abs(v - near) <= across - 4.4]
        if found:
            wall = min(found, key=lambda v: abs(v - near))
            return ((wall, c1) if near == c1 else (c0, wall)), 1
    return None, 0


def _common(sides, lo, hi, step=.05):
    """Positions in [lo, hi] where a wall may meet every one of ``sides``."""
    found, v = [], lo
    while v <= hi + EPS:
        if all(side.clear(v) for side in sides):
            found.append(round(v, 4))
        v += step
    return found


def layout(spec, rng):
    """Corridors, stubs, rows and the stair over a compound footprint."""
    zones = footprint.zones(spec.wings, spec.t)
    sides = {(z.index, s): ZoneSide(spec, z, s) for z in zones for s in SIDES}
    plans = []
    for zone in zones:
        span, rows = _corridor_span(zone, {s: sides[(zone.index, s)] for s in SIDES}, rng)
        zp = ZonePlan(zone)
        a0, a1, c0, c1 = _frame(zone)
        if span is not None:
            zp.corridor = _rect(zone, a0, a1, *span)
            if rows == 2 or span[0] > c0 + EPS:
                zp.rows.append((_rect(zone, a0, a1, c0, span[0]), 'high'))
            if rows == 2 or span[1] < c1 - EPS:
                zp.rows.append((_rect(zone, a0, a1, span[1], c1), 'low'))
        else:
            zp.rows.append((zone.rect, None))
        plans.append(zp)
    # Stubs: a wing's corridor carries on through the row of the bar it meets
    # to the bar's corridor.
    stubs = []
    for zp in plans:
        zone = zp.zone
        for other_index, side, lo, hi in zone.joints:
            other = plans[other_index]
            # This zone runs into the joint (its axis crosses it); the other
            # runs along it.
            crosses = (zone.axis == 'y') == (side in ('front', 'back'))
            if not crosses or other.zone.axis == zone.axis:
                continue
            if zp.corridor is not None:
                cx0, cy0, cx1, cy1 = zp.corridor
                c0, c1 = (cx0, cx1) if zone.axis == 'y' else (cy0, cy1)
            else:
                a0, a1, b0, b1 = _frame(zone)
                middle = (b0 + b1) / 2
                c0, c1 = middle - dims.CORRIDOR / 2, middle + dims.CORRIDOR / 2
            stub = _stub(other, side, c0, c1)
            if stub is not None:
                stubs.append((other_index, stub))
    return zones, sides, plans, stubs


def _stub(bar, side, c0, c1):
    """In ``bar``, from the joint (the other zone's ``side``) to its corridor."""
    if bar.corridor is None:
        return None
    x0, y0, x1, y1 = bar.zone.rect
    bx0, by0, bx1, by1 = bar.corridor
    if side == 'front':          # The wing is behind the bar's back... its front meets the bar.
        return (c0, by1, c1, y1) if by1 < y1 - EPS else None
    if side == 'back':
        return (c0, y0, c1, by0) if by0 > y0 + EPS else None
    if side == 'left':
        return (bx1, c0, x1, c1) if bx1 < x1 - EPS else None
    return (x0, c0, bx0, c1) if bx0 > x0 + EPS else None


def _stair(spec, zones, sides, plans, stubs, heights, lobby=None):
    """A stair room in a row (the main zone first), its walls on clear spots
    of the row's outer side, clear of the stubs. Flights across the row
    (door on the corridor) in any stair mode before flights along it, whose
    door is at the end abutting a corridor stub."""
    short = stair_width() + dims.CORE_WALL
    for flights in ('across', 'along'):
        for mode in ('normal', 'compact', 'steep'):
            long_side = stair_length(heights, mode) + dims.CORE_WALL / 2
            for zp in plans:
                found = _stair_in(spec, zp, sides, stubs, flights, mode, short, long_side, lobby)
                if found is not None:
                    return found
    return None


def _stair_in(spec, zp, sides, stubs, flights, mode, short, long_side, lobby=None):
    zone = zp.zone
    for row, corridor_side in sorted(zp.rows, key=lambda r: r[1] != 'low'):
        if corridor_side is None:
            continue
        rx0, ry0, rx1, ry1 = row
        ra0, ra1, rc0, rc1 = (rx0, rx1, ry0, ry1) if zone.axis == 'x' else (ry0, ry1, rx0, rx1)
        depth = rc1 - rc0
        if flights == 'across':
            if depth + EPS < long_side:
                continue
            need = short
        else:
            if depth + EPS < short:
                continue
            need = long_side + dims.CORE_WALL / 2
        out_side = sides[(zone.index, _outer_side(zone, corridor_side))]
        blocked = [_along(zone, s) for index, s in stubs if index == zone.index and _overlap(s, row)]
        if lobby is not None and zone.index == 0 and _overlap(lobby, row):
            blocked.append(_along(zone, lobby))
        middle = (ra0 + ra1) / 2
        best = None
        for a in out_side.spots(ra0, ra1 - need):
            # The far wall on the next clear spot (a wider room widens the well).
            far = [v for v in _common([out_side], a + need, min(ra1, a + need + 1.2))]
            if not far:
                continue
            b = far[0]
            if any(s0 < b - EPS and a < s1 - EPS for s0, s1 in blocked):
                continue
            # Next to the row's ends and the stubs: no gap, or a room's width.
            edges = [ra0, ra1] + [v for span in blocked for v in span]
            if any(EPS < a - e < dims.MIN_ROOM for e in edges if e <= a + EPS) or \
                    any(EPS < e - b < dims.MIN_ROOM for e in edges if e >= b - EPS):
                continue
            touching = [e for e in edges[2:] if abs(e - a) < EPS or abs(e - b) < EPS]
            if flights == 'along' and not touching:
                continue            # Its door is at an end: on a stub.
            score = abs((a + b) / 2 - middle)
            if best is None or score < best[0]:
                best = (score, a, b, touching)
        if best is None:
            continue
        _, a, b, touching = best
        rect = _rect(zone, a, b, rc0, rc1)
        if flights == 'across':
            axis = 'y' if zone.axis == 'x' else 'x'
            entry = -1 if corridor_side == 'low' else 1
        else:
            axis = zone.axis
            entry = -1 if any(abs(e - a) < EPS for e in touching) else 1
        return rect, (axis, entry, dims.STAIR_FLIGHT, mode), zone.index
    return None


def _outer_side(zone, corridor_side):
    """The zone side a row faces away from its corridor."""
    if zone.axis == 'x':
        return 'front' if corridor_side == 'high' else 'back'
    return 'left' if corridor_side == 'high' else 'right'


def _along(zone, rect):
    x0, y0, x1, y1 = rect
    return (x0, x1) if zone.axis == 'x' else (y0, y1)


def _minus_spans(lo, hi, spans):
    pieces, cursor = [], lo
    for a, b in sorted(spans):
        if a > cursor + EPS:
            pieces.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < hi - EPS:
        pieces.append((cursor, hi))
    return pieces


def plan_compound(spec, rng, profile):
    """Plan every storey of a compound building (None if no program fits)."""
    if profile == 'WAREHOUSE':
        return _plan_hall(spec, rng)
    zones, sides, plans, stubs = layout(spec, rng)
    heights = [level.height for level in spec.levels]
    multi = len(spec.levels) > 1
    low, high = UNITS.get(profile, UNITS['RESIDENTIAL'])
    main = plans[0]
    door = _front_door(spec)
    lobby = None
    if door is not None and main.corridor is not None:
        rows = [r for r in main.rows if r[1] == 'high']
        if rows:
            (rx0, ry0, rx1, ry1), _ = rows[0]
            piers = sides[(0, 'front')].spots()
            lobby = _snap(piers, rx0, rx1, max(door[1] - door[0] + .8, 3.0),
                          (door[0] + door[1]) / 2)
            if lobby is not None:
                lobby = (lobby[0], ry0, lobby[1], ry1)
    stair = _stair(spec, zones, sides, plans, stubs, heights, lobby) if multi else None
    notes = [] if stair or not multi else ['no stair fits; upper floors are not enterable']
    court = _court_passage(spec, plans, sides, stubs, stair)
    levels = []
    storeys = spec.levels if stair or not multi else spec.levels[:1]
    shops = []
    for level in storeys:
        tiling = Tiling(spec.interior_rect(level.index), level.index)
        ground = level.index == 0
        for zp in plans:
            if zp.corridor is not None:
                tiling.add(f'corridor{zp.zone.index}', 'corridor', zp.corridor, group='corridor')
        for k, (zone_index, stub) in enumerate(stubs):
            tiling.add(f'stub{k}', 'corridor', stub, group='corridor')
        if court is not None and court[0] is not None:
            tiling.add('court', 'corridor', court[0], group='corridor')
        if stair is not None:
            tiling.add('stair', 'stair', stair[0], wall=dims.CORE_WALL, stair=stair[1])
        if ground and lobby is not None:
            tiling.add('lobby', 'lobby', lobby, group='corridor')
        number = 0
        for zp in plans:
            zone = zp.zone
            blocks = [s for index, s in stubs if index == zone.index]
            if court is not None and court[0] is not None and court[1] == zone.index:
                blocks.append(court[0])
            if stair is not None and stair[2] == zone.index:
                blocks.append(stair[0])
            if ground and lobby is not None and zone.index == 0:
                blocks.append(lobby)
            for row, corridor_side in zp.rows:
                if corridor_side:
                    outer = sides[(zone.index, _outer_side(zone, corridor_side))]
                    cut_sides = [outer]
                else:
                    # A run of rooms across the zone: their walls meet both sides.
                    outer = sides[(zone.index, _long_sides(zone)[0])]
                    cut_sides = [sides[(zone.index, k)] for k in _long_sides(zone)]
                rx0, ry0, rx1, ry1 = row
                ra0, ra1 = (rx0, rx1) if zone.axis == 'x' else (ry0, ry1)
                rc0, rc1 = (ry0, ry1) if zone.axis == 'x' else (rx0, rx1)
                taken = [_along(zone, b) for b in blocks if _overlap(b, row)]
                previous = None
                for p0, p1 in _minus_spans(ra0, ra1, taken):
                    spots = (outer.spots(p0, p1) if len(cut_sides) == 1 else
                             _common(cut_sides, p0, p1, .1))
                    cuts = _split_bays(p0, p1, spots, low, high)
                    for c0, c1 in zip(cuts, cuts[1:]):
                        rect = _rect(zone, c0, c1, rc0, rc1)
                        tag = f'{zone.index}_{number}'
                        number += 1
                        corridor = f'corridor{zone.index}' if zp.corridor is not None else previous
                        # The zone's ends this unit stands against.
                        ends = [sides[(zone.index, k)] for k, v in zip(_end_sides(zone), (ra0, ra1))
                                if abs((c0 if k in ('left', 'front') else c1) - v) < EPS]
                        name = _unit(tiling, spec, profile, level, rect, corridor_side, zone,
                                     tag, corridor, outer, rng, ends)
                        if (ground and profile == 'STOREFRONT' and zone.index == 0 and
                                corridor_side == 'high' and name is not None):
                            shops.append((c0 + c1) / 2)
                        previous = name
        levels.append(tiling.level())
    doors = []
    if door is not None and lobby is not None:
        doors.append(('front', (lobby[0] + lobby[2]) / 2, door[2]))
    elif door is not None:
        doors.append(('front', (door[0] + door[1]) / 2, door[2]))
    for centre in shops:
        if lobby is None or not lobby[0] - 1 < centre < lobby[2] + 1:
            doors.append(('front', centre, 1.6))
    if court is not None:
        doors.append(court[2])
    return Plan(levels, doors or None, notes)


def _overlap(a, b):
    return a[0] < b[2] - EPS and b[0] < a[2] - EPS and a[1] < b[3] - EPS and b[1] < a[3] - EPS


def _snap(spots, lo, hi, need, target):
    candidates = sorted(set(spots) | {lo, hi})
    best = None
    for i, a in enumerate(candidates):
        for b in candidates[i + 1:]:
            if b - a + EPS < need:
                continue
            score = (b - a - need) * .5 + abs((a + b) / 2 - target)
            if best is None or score < best[0]:
                best = (score, a, b)
            break
    return None if best is None else (best[1], best[2])


def _front_door(spec):
    doors = spec.door_bays('front')
    if not doors:
        return None
    first, last, width = doors[0][:3]
    facade = spec.ground_facade('front')
    return (facade.point(facade.bays[first])[0], facade.point(facade.bays[last + 1])[0], width)


def _court_passage(spec, plans, sides, stubs, stair):
    """A way out to a courtyard: a passage from the main corridor through
    its back row to the court facade, as wide as the bays the door takes
    there, and the door."""
    court = [i for i, f in enumerate(spec.facades_on('back')) if getattr(f, 'court', False)]
    main = plans[0]
    if not court or main.corridor is None:
        return None
    facade = spec.facades_on('back')[court[0]]
    x0, y0, x1, y1 = main.zone.rect
    cx0, cy0, cx1, cy1 = main.corridor
    blocks = [s for index, s in stubs if index == 0]
    if stair is not None and stair[2] == 0:
        blocks.append(stair[0])
    height = dims.DOOR_HEIGHT + .1
    count = len(facade.bays) - 1
    for k in sorted(range(count), key=lambda k: abs(k - (count - 1) / 2)):
        door = spec._door_bays(facade, (facade.bays[k] + facade.bays[k + 1]) / 2 / facade.length,
                               1.4, height, 'door')
        if door is None:
            continue
        first, last = door[0], door[1]
        a = facade.point(facade.bays[first])[0]
        b = facade.point(facade.bays[last + 1])[0]
        p0, p1 = min(a, b), max(a, b)
        centre = (p0 + p1) / 2
        if cy1 >= y1 - EPS:
            # The corridor runs along the court: its door opens straight out.
            return None, 0, ('back', centre, 1.4, height, court[0])
        rect = (p0, cy1, p1, y1)
        if any(_overlap(rect, block) for block in blocks):
            continue
        # No sliver beside the stair, a stub or the row's end: close the gap.
        for block in [(x0, 0, x0, 0), (x1, 0, x1, 0)] + blocks:
            if EPS < block[0] - p1 < dims.MIN_ROOM:
                p1 = block[0]
            if EPS < p0 - block[2] < dims.MIN_ROOM:
                p0 = block[2]
        return (p0, cy1, p1, y1), 0, ('back', centre, 1.4, height, court[0])
    return None


def _unit(tiling, spec, profile, level, rect, corridor_side, zone, tag, corridor, outer, rng,
          ends=()):
    """One unit in a row: a flat, an office, a shop. Returns its main room's name.
    ``ends``: the zone's end sides the unit stands against (where the wall
    between its hall strip and its rooms meets them)."""
    x0, y0, x1, y1 = rect
    along = (x1 - x0) if zone.axis == 'x' else (y1 - y0)
    deep = (y1 - y0) if zone.axis == 'x' else (x1 - x0)
    parent = corridor
    ground = level.index == 0
    def named(room):
        return room.name if room is not None else None
    if profile in ('OFFICE', 'CIVIC'):
        return named(tiling.add(f'office{tag}', 'office', rect, parent))
    if profile == 'HOTEL' and not ground:
        return named(tiling.add(f'room{tag}', 'bedroom', rect, parent, unit=tag))
    if profile == 'STOREFRONT' and ground:
        kind = 'shop' if corridor_side == 'high' and zone.index == 0 else 'storage'
        return named(tiling.add(f'{kind}{tag}', kind, rect, parent))
    # A flat: hall and bath on the corridor side, living room (and bedroom) out.
    if along < 4.4 or deep < 5.4 or corridor_side is None:
        room = tiling.add(f'studio{tag}', 'living', rect, parent, unit=tag)
        return room.name if room else None
    # The hall strip's depth: where its wall may meet the ends it reaches.
    edge = {('x', 'high'): y1, ('x', 'low'): y0, ('y', 'high'): x1, ('y', 'low'): x0}[
        (zone.axis, corridor_side)]
    toward = -1 if corridor_side == 'high' else 1
    inner = None
    for candidate in [min(2.6, deep - 3.0) - k * .05 for k in range(15)]:
        if candidate >= dims.MIN_BATH and all(e.clear(edge + toward * candidate) for e in ends):
            inner = candidate
            break
    if inner is None:
        room = tiling.add(f'studio{tag}', 'living', rect, parent, unit=tag)
        return room.name if room else None

    def part(a0, a1, c0, c1):
        """Unit-local (along from the unit's start, across from its corridor side)."""
        if zone.axis == 'x':
            if corridor_side == 'high':      # Corridor above: across runs down from y1.
                return (x0 + a0, y1 - c1, x0 + a1, y1 - c0)
            return (x0 + a0, y0 + c0, x0 + a1, y0 + c1)
        if corridor_side == 'high':          # Corridor to the right: across runs left from x1.
            return (x1 - c1, y0 + a0, x1 - c0, y0 + a1)
        return (x0 + c0, y0 + a0, x0 + c1, y0 + a1)
    hall_w = max(dims.CORRIDOR, min(2.4, along - dims.MIN_BATH - .1))
    rest = along - hall_w
    hall = tiling.add(f'hall{tag}', 'hall', part(0, hall_w, 0, inner), parent, unit=tag)
    if rest >= dims.MIN_BATH:
        bath_w = rest if rest < dims.MIN_BATH + dims.MIN_ROOM else min(2.6, rest - dims.MIN_ROOM)
        tiling.add(f'bath{tag}', 'bath', part(hall_w, hall_w + bath_w, 0, inner), f'hall{tag}',
                   unit=tag)
        if rest - bath_w > .01:
            tiling.add(f'kitchen{tag}', 'kitchen', part(hall_w + bath_w, along, 0, inner),
                       f'hall{tag}', unit=tag)
    elif rest > .3:
        tiling.add(f'store{tag}', 'storage', part(hall_w, along, 0, inner), f'hall{tag}', unit=tag)
    # Living room and bedroom across the outer part; their wall meets the
    # outer side at a pier.
    start = x0 if zone.axis == 'x' else y0
    cut = None
    if along >= 5.6:
        options = [v - start for v in outer.spots(start + 2.6, start + along - 2.6)]
        if options:
            cut = min(options, key=lambda v: abs(v - along * .58))
    if cut is None:
        tiling.add(f'living{tag}', 'living', part(0, along, inner, deep), f'hall{tag}', unit=tag)
    else:
        tiling.add(f'living{tag}', 'living', part(0, cut, inner, deep), f'hall{tag}', unit=tag)
        tiling.add(f'bed{tag}', 'bedroom', part(cut, along, inner, deep), f'hall{tag}', unit=tag)
    return hall.name if hall else None


def _plan_hall(spec, rng):
    """A shed: one open hall over every wing, an office at the main wing's
    front corner, a stair in a back corner."""
    zones = footprint.zones(spec.wings, spec.t)
    sides = {(z.index, s): ZoneSide(spec, z, s) for z in zones for s in SIDES}
    main = zones[0]
    x0, y0, x1, y1 = main.rect
    multi = len(spec.levels) > 1
    heights = [level.height for level in spec.levels]
    stair = None
    if multi:
        short = stair_width() + dims.CORE_WALL
        back = sides[(0, 'back')]
        for mode in ('normal', 'compact', 'steep'):
            long_side = stair_length(heights, mode) + dims.CORE_WALL / 2
            if y1 - y0 < long_side + 4:
                continue
            for a in back.spots():
                b = a + short
                if b > x1 + EPS or not back.clear(b) or not (a - x0 < EPS or a - x0 > 2.4):
                    continue
                if x1 - b > EPS and x1 - b < 2.4:
                    continue
                # Not across a joint: the hall carries on into the wings there.
                if any(ja < b and a < jb for ja, jb in back.joint):
                    continue
                stair = ((a, y1 - long_side, b, y1), ('y', -1, dims.STAIR_FLIGHT, mode))
                break
            if stair:
                break
        if stair is None:
            # A free-standing core in the main hall, its walls meeting no facade.
            for mode in ('normal', 'compact', 'steep'):
                long_side = stair_length(heights, mode) + dims.CORE_WALL / 2
                if y1 - y0 >= long_side + 4.0 and x1 - x0 >= short + 6.0:
                    cx = (x0 + x1) / 2
                    stair = ((cx - short / 2, y1 - 1.5 - long_side, cx + short / 2, y1 - 1.5),
                             ('y', -1, dims.STAIR_FLIGHT, mode))
                    break
    office = None
    front = sides[(0, 'front')]
    door = _front_door(spec)
    middle = (door[0] + door[1]) / 2 if door else (x0 + x1) / 2
    left = middle > (x0 + x1) / 2
    edge_options = front.spots(x0 + 3.0, x0 + 9.0) if left else front.spots(x1 - 9.0, x1 - 3.0)
    beside = sides[(0, 'left' if left else 'right')]
    depths = beside.spots(y0 + 3.0, min(y1 - 3.0, y0 + 7.0))
    if edge_options and depths and y1 - y0 > 9:
        edge = min(edge_options, key=lambda v: abs(v - (x0 + 7.0 if left else x1 - 7.0)))
        back = min(depths, key=lambda v: abs(v - (y0 + 5.0)))
        office = (x0, y0, edge, back) if left else (edge, y0, x1, back)
    levels = []
    storeys = spec.levels if stair or not multi else spec.levels[:1]
    for level in storeys:
        tiling = Tiling(spec.interior_rect(level.index), level.index)
        blocks = [stair[0]] if stair else []
        if office and level.index == 0:
            blocks.append(office)
            tiling.add('office', 'office', office)
        if stair:
            tiling.add('stair', 'stair', stair[0], wall=dims.CORE_WALL, stair=stair[1])
        for zone in zones:
            _tile_open(tiling, zone.rect, [b for b in blocks if _overlap(b, zone.rect)],
                       f'hall{zone.index}_')
        levels.append(tiling.level())
    notes = [] if stair or not multi else ['no stair fits; upper floors are not enterable']
    return Plan(levels, notes=notes, framed=True)


def _tile_open(tiling, rect, blocks, name):
    """``rect`` less ``blocks`` as open-floor rooms of one hall (group 'hall')."""
    x0, y0, x1, y1 = rect
    xs = sorted({x0, x1} | {min(max(b[0], x0), x1) for b in blocks} |
                {min(max(b[2], x0), x1) for b in blocks})
    ys = sorted({y0, y1} | {min(max(b[1], y0), y1) for b in blocks} |
                {min(max(b[3], y0), y1) for b in blocks})
    count = 0
    for i in range(len(xs) - 1):
        start = None
        cx = (xs[i] + xs[i + 1]) / 2
        for j in range(len(ys)):
            free = j < len(ys) - 1 and not any(
                b[0] <= cx <= b[2] and b[1] <= (ys[j] + ys[j + 1]) / 2 <= b[3] for b in blocks)
            if free and start is None:
                start = j
            if not free and start is not None:
                tiling.add(f'{name}{count}', 'open', (xs[i], ys[start], xs[i + 1], ys[j]),
                           group='hall')
                count += 1
                start = None
