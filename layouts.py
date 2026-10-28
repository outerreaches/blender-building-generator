# SPDX-License-Identifier: GPL-3.0-or-later
"""Interior planning: rooms, partitions, doors, cores and stairs.

Pure Python. Every storey is planned as a complete tiling of its interior by
rectangular rooms. Programs (apartments, walk-ups, offices, ...) lay out the
rooms and say which room each one should open from; a resolver then makes
sure every room is actually reachable through a door that fits, from the
street doors on the ground floor or from the stair above it. Partitions are
derived from the edges between rooms, only meet a facade at a pier (never on
a window), and every size is checked against the Ares player capsule.
"""
import math
import random
from dataclasses import dataclass, field

from . import dims

EPS = 1e-6
DOOR_MARGIN = .2
# Rooms a door would rather open from, best first.
PREFERENCE = {'corridor': 0, 'lobby': 0, 'hall': 0, 'landing': 0, 'open': 1, 'shop': 1,
              'bar': 1, 'plant': 1, 'living': 2, 'kitchen': 2, 'stair': 3}


@dataclass
class Room:
    name: str
    kind: str
    rect: tuple
    parent: str = None
    wall: float = dims.PARTITION
    group: str = None
    stair: tuple = None      # (axis, entry, flight[, mode]) for stair rooms.
    unit: str = None         # Flat/suite the room belongs to; doors stay inside it.

    @property
    def width(self):
        return self.rect[2] - self.rect[0]

    @property
    def depth(self):
        return self.rect[3] - self.rect[1]


@dataclass
class Stair:
    zone: tuple       # Clear rect for flights and landings.
    axis: str         # Direction the flights run: 'x' or 'y'.
    entry: int        # -1: entry landing at the low end of the axis, +1 at the high end.
    landing: float
    flight: float
    riser: float = dims.STAIR_RISER   # Maximum riser.


@dataclass
class Wall:
    start: tuple
    end: tuple
    thickness: float
    openings: list = field(default_factory=list)   # (offset, width, height)


@dataclass
class LevelPlan:
    index: int
    rect: tuple
    rooms: list = field(default_factory=list)
    walls: list = field(default_factory=list)
    fixtures: list = field(default_factory=list)   # (x0, y0, x1, y1, height)
    holes: list = field(default_factory=list)      # Openings in this storey's floor slab.
    stair: Stair = None                            # Flights from this storey up.
    doors: list = field(default_factory=list)      # (room, parent, axis, line, centre, width)
    roots: list = field(default_factory=list)
    issues: list = field(default_factory=list)


@dataclass
class Plan:
    levels: list
    doors: list = None   # Street doors [(side, centre, width)]; None keeps the spec's.
    notes: list = field(default_factory=list)


# -- sizes -------------------------------------------------------------------

# (max riser, tread, landing). Compact and steep stairs are for small plates;
# 0.25 m risers are still well inside the player's 0.4 m step offset.
STAIR_MODES = {'normal': (dims.STAIR_RISER, dims.STAIR_TREAD, dims.STAIR_LANDING),
               'compact': (dims.STAIR_RISER, .25, 1.0),
               'steep': (.25, .25, 1.0)}


def stair_length(heights, mode='normal'):
    """Clear length of a switchback for the tallest storey it serves."""
    riser, tread, landing = STAIR_MODES[mode]
    risers = max(2, math.ceil(max(heights) / riser))
    return math.ceil(risers / 2) * tread + 2 * landing


def stair_width(flight=dims.STAIR_FLIGHT):
    return 2 * flight + dims.STAIR_WELL


# -- small helpers -------------------------------------------------------------

def _snap_span(piers, lo, hi, need, target, ends=True):
    """Pier-aligned [a, b] inside [lo, hi], at least ``need`` wide, near ``target``.

    ``ends`` allows lo/hi themselves as edges (when they are the plate's walls).
    """
    candidates = sorted({p for p in piers if lo - EPS <= p <= hi + EPS} |
                        ({lo, hi} if ends else set()))
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


def _wall_spots(spec, side, lo, hi, thickness=dims.CORE_WALL):
    """Facade coordinates in [lo, hi] where a wall may meet it: piers first,
    then the ends of window-free stretches (kept clear by half the wall)."""
    clear = thickness / 2 + .05
    spots = [p for p in spec.piers(0)[side] if lo - EPS <= p <= hi + EPS]
    for a, b in spec.solid_spans(side):
        for value in (a + clear, b - clear):
            if a + clear <= b - clear and lo - EPS <= value <= hi + EPS:
                spots.append(value)
    return sorted(set(spots))


def _cut_near(piers, lo, hi, target, minimum):
    """Pier nearest ``target`` leaving ``minimum`` on both sides, or None."""
    options = [p for p in piers if lo + minimum <= p <= hi - minimum]
    return min(options, key=lambda p: abs(p - target)) if options else None


def _split_bays(lo, hi, piers, low=4.6, high=9.5):
    """Cut [lo, hi] at piers into pieces of roughly flat width."""
    cuts = [lo]
    inner = [p for p in piers if lo + 2.4 < p < hi - 2.4]
    while hi - cuts[-1] > high:
        options = [p for p in inner if low <= p - cuts[-1] <= high and hi - p >= low]
        if not options:
            break
        target = cuts[-1] + (low + high) / 2
        cuts.append(min(options, key=lambda p: abs(p - target)))
    cuts.append(hi)
    return cuts


def _shared_segment(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    for line, other in ((ay1, by0), (ay0, by1)):
        if abs(line - other) < EPS:
            lo, hi = max(ax0, bx0), min(ax1, bx1)
            if hi - lo > EPS:
                return ('x', line, lo, hi)
    for line, other in ((ax1, bx0), (ax0, bx1)):
        if abs(line - other) < EPS:
            lo, hi = max(ay0, by0), min(ay1, by1)
            if hi - lo > EPS:
                return ('y', line, lo, hi)
    return None


def _stair_clip(room, axis, line, a, b):
    """Part of a shared edge where a stair room may have its door (entry landing)."""
    flights, entry = room.stair[:2]
    mode = room.stair[3] if len(room.stair) > 3 else 'normal'
    x0, y0, x1, y1 = room.rect
    landing = STAIR_MODES[mode][2]
    if flights == 'y':
        end = y0 if entry < 0 else y1
        if axis == 'x':
            return (a, b) if abs(line - end) < EPS else (0.0, 0.0)
        zone = (y0, y0 + landing) if entry < 0 else (y1 - landing, y1)
    else:
        end = x0 if entry < 0 else x1
        if axis == 'y':
            return (a, b) if abs(line - end) < EPS else (0.0, 0.0)
        zone = (x0, x0 + landing) if entry < 0 else (x1 - landing, x1)
    return max(a, zone[0]), min(b, zone[1])


def door_window(a, b):
    """(axis, line, lo, hi) where a door between rooms a and b may go, or None."""
    shared = _shared_segment(a.rect, b.rect)
    if shared is None:
        return None
    axis, line, lo, hi = shared
    for room in (a, b):
        if room.stair is not None:
            lo, hi = _stair_clip(room, axis, line, lo, hi)
    if hi - lo < dims.DOOR_WIDTH + 2 * DOOR_MARGIN:
        return None
    return axis, line, lo, hi


def _same_group(a, b):
    return a.group is not None and a.group == b.group and _shared_segment(a.rect, b.rect)


class Tiling:
    def __init__(self, rect, index):
        self.rect = rect
        self.index = index
        self.rooms = []
        self.fixtures = []

    def add(self, name, kind, rect, parent=None, **extra):
        x0, y0, x1, y1 = rect
        if x1 - x0 < .3 or y1 - y0 < .3:
            return None
        room = Room(f'{name}_{self.index}', kind, (x0, y0, x1, y1),
                    None if parent is None else f'{parent}_{self.index}', **extra)
        self.rooms.append(room)
        return room

    def get(self, name):
        return next((room for room in self.rooms if room.name == f'{name}_{self.index}'), None)

    def covered(self):
        area = sum(room.width * room.depth for room in self.rooms)
        x0, y0, x1, y1 = self.rect
        return abs(area - (x1 - x0) * (y1 - y0)) < 1e-3

    def level(self):
        return LevelPlan(self.index, self.rect, self.rooms, fixtures=self.fixtures)


def _common_rect(spec):
    rects = [spec.interior_rect(level.index) for level in spec.levels]
    return (max(r[0] for r in rects), max(r[1] for r in rects),
            min(r[2] for r in rects), min(r[3] for r in rects))


def _front_door(spec):
    doors = spec.door_bays('front')
    if not doors:
        return None
    first, last, width = doors[0][:3]
    front = spec.ground_facade('front')
    return (front.point(front.bays[first])[0], front.point(front.bays[last + 1])[0], width)


def _tile_around(tiling, rect, blocks, name, kind, parent=None):
    """Tile ``rect`` minus axis-aligned blocks with column bands of one group."""
    x0, y0, x1, y1 = rect
    blocks = [b for b in blocks if b]
    xs = sorted({x0, x1} | {b[0] for b in blocks} | {b[2] for b in blocks})
    ys = sorted({y0, y1} | {b[1] for b in blocks} | {b[3] for b in blocks})
    count = 0
    names = []
    for i in range(len(xs) - 1):
        start = None
        cx = (xs[i] + xs[i + 1]) / 2
        for j in range(len(ys)):
            free = j < len(ys) - 1 and not any(
                b[0] <= cx <= b[2] and b[1] <= (ys[j] + ys[j + 1]) / 2 <= b[3] for b in blocks)
            if free and start is None:
                start = j
            if not free and start is not None:
                room = tiling.add(f'{name}{count}', kind, (xs[i], ys[start], xs[i + 1], ys[j]),
                                  parent, group=name)
                if room is not None:
                    names.append(room.name)
                count += 1
                start = None
    return names


# -- programs ----------------------------------------------------------------

def plan_walkup(spec, rng, ground='flat', upper='flat', flight=dims.STAIR_FLIGHT):
    """Central stair column: hall and stair from front to back, rooms either side.

    The classic town house / tenement plan. The street door opens into the
    hall, which leads to a switchback at the back; every storey's rooms open
    off the hall (or the landing in front of the stair).
    """
    common = _common_rect(spec)
    x0, y0, x1, y1 = common
    multi = len(spec.levels) > 1
    door = _front_door(spec)
    target = (door[0] + door[1]) / 2 if door else (x0 + x1) / 2
    need = stair_width(flight) + dims.CORE_WALL if multi else dims.CORRIDOR
    if door:
        need = max(need, door[1] - door[0] + .8)
    span = _snap_span(spec.piers(0)['front'], x0, x1, need, target)
    heights = [level.height for level in spec.levels]
    mode = 'normal'
    stair_long = stair_length(heights) + dims.CORE_WALL / 2
    if multi and y1 - y0 < stair_long + 1.8:
        mode = 'compact'
        stair_long = stair_length(heights, mode) + dims.CORE_WALL / 2
    if span is None or (x1 - x0) - (span[1] - span[0]) < 2.0 or (
            multi and y1 - y0 < stair_long + 1.8):
        return plan_open(spec, rng)
    cx0, cx1 = span
    # A side strip too narrow for a room joins the column instead.
    if cx0 - x0 < dims.MIN_ROOM:
        cx0 = x0
    if x1 - cx1 < dims.MIN_ROOM:
        cx1 = x1
    if cx0 == x0 and cx1 == x1:
        return plan_open(spec, rng)
    stair_y0 = y1
    if multi:
        # The hall/stair wall only meets a facade when the column reaches it;
        # then it must land on solid wall there.
        limit = y1 - stair_long
        touching = [side for side, flag in (('left', cx0 <= x0 + EPS), ('right', cx1 >= x1 - EPS))
                    if flag]
        spots = None
        for side in touching:
            found = {round(v, 6) for v in _wall_spots(spec, side, y0 + 1.8, limit)}
            spots = found if spots is None else spots & found
        if spots is None:
            stair_y0 = limit
        elif spots:
            stair_y0 = max(spots)
        else:
            return plan_open(spec, rng)
    # A back door in the stair column would open onto the turning landing, and
    # one into a flat makes no sense: back doors go into back rooms that want
    # them (shop stores, house kitchens).
    doors = [('front', target, door[2] if door else dims.EXTERIOR_DOOR_MIN)]
    if ground in ('shop', 'house_ground'):
        wide = [(bx0, bx1) for bx0, bx1 in ((x0, cx0), (cx1, x1)) if bx1 - bx0 >= 2.6]
        if ground == 'house_ground':
            wide = wide[-1:]
        for bx0, bx1 in wide:
            if ground == 'shop':
                doors.append(('front', (bx0 + bx1) / 2, 1.6))
            doors.append(('back', (bx0 + bx1) / 2, 1.2))
    levels = []
    for level in spec.levels:
        rect = spec.interior_rect(level.index)
        lx0, ly0, lx1, ly1 = rect
        tiling = Tiling(rect, level.index)
        is_ground = level.index == 0
        tiling.add('hall', 'hall' if is_ground else 'landing', (cx0, ly0, cx1, stair_y0),
                   None if is_ground else 'stair')
        if multi:
            tiling.add('stair', 'stair', (cx0, stair_y0, cx1, ly1), 'hall' if is_ground else None,
                       wall=dims.CORE_WALL, stair=('y', -1, flight, mode))
        program = ground if is_ground else upper
        for tag, (bx0, bx1) in (('a', (lx0, cx0)), ('b', (cx1, lx1))):
            _side_block(tiling, spec, level, (bx0, ly0, bx1, ly1), tag, program)
        levels.append(tiling.level())
    return Plan(levels, doors)


def _side_block(tiling, spec, level, rect, tag, program):
    x0, y0, x1, y1 = rect
    if x1 - x0 < .3:
        return
    if x1 - x0 < dims.MIN_ROOM:
        tiling.add(f'nook{tag}', 'hall', rect, 'hall')
        return
    piers = spec.piers(level.index)['left']
    depth = y1 - y0
    if depth < 2 * dims.MIN_ROOM + .2:
        tiling.add(f'room{tag}', 'shop' if program == 'shop' else 'living', rect, 'hall')
        return
    split = _cut_near(piers, y0, y1, y0 + depth * (.62 if program == 'shop' else .55),
                      dims.MIN_ROOM)
    if split is None:
        tiling.add(f'room{tag}', 'shop' if program == 'shop' else 'living', rect, 'hall')
        return
    names = {'shop': ('shop', 'storage', None),
             'house_ground': ('living', 'kitchen', 'bath'),
             'house_upper': ('bedroom', 'bedroom', 'bath'),
             'flat': ('living', 'bedroom', 'bath')}[program]
    front_kind, back_kind, small_kind = names
    tiling.add(f'front{tag}', front_kind, (x0, y0, x1, split), 'hall')
    back = (x0, split, x1, y1)
    width = x1 - x0
    hall_side_low = abs(x1 - tiling.get('hall').rect[0]) > EPS
    back_piers = spec.piers(level.index)['back']
    # The small room sits against the hall (no window needed); its partition
    # reaches the back facade, so it must stand on a pier.
    if hall_side_low:
        cuts = [p for p in back_piers if x0 + dims.MIN_BATH <= p <= min(x0 + 3.0, x1 - dims.MIN_ROOM)]
    else:
        cuts = [p for p in back_piers if max(x1 - 3.0, x0 + dims.MIN_ROOM) <= p <= x1 - dims.MIN_BATH]
    if small_kind and cuts and y1 - split >= dims.MIN_BATH:
        if hall_side_low:
            cut = min(cuts)
            tiling.add(f'small{tag}', small_kind, (x0, split, cut, y1), 'hall')
            tiling.add(f'back{tag}', back_kind, (cut, split, x1, y1), 'hall')
        else:
            cut = max(cuts)
            tiling.add(f'small{tag}', small_kind, (cut, split, x1, y1), 'hall')
            tiling.add(f'back{tag}', back_kind, (x0, split, cut, y1), 'hall')
    elif small_kind and y1 - split <= 3.4 and level.index > 0:
        tiling.add(f'small{tag}', small_kind, back, 'hall')
    else:
        tiling.add(f'back{tag}', back_kind, back, f'front{tag}')


def plan_house(spec, rng):
    return plan_walkup(spec, rng, 'house_ground', 'house_upper', flight=1.1)


def plan_storefront(spec, rng):
    return plan_walkup(spec, rng, 'shop', 'flat')


def plan_bar(spec, rng):
    """Bar room on the street, kitchen behind, private rooms upstairs."""
    plan = plan_walkup(spec, rng, 'shop', 'flat')
    for level in plan.levels:
        for room in level.rooms:
            if level.index == 0 and room.kind == 'shop':
                room.kind = 'bar'
                x0, y0, x1, y1 = room.rect
                if x1 - x0 > 3.5 and y1 - y0 > 4.0:
                    level.fixtures.append((x0 + .8, y1 - 1.6, x1 - .8, y1 - 1.0, 1.1))
            elif level.index == 0 and room.kind == 'storage':
                room.kind = 'kitchen'
            elif level.index > 0 and room.kind == 'living':
                room.kind = 'vip'
    return plan


def plan_apartments(spec, rng):
    """Double-loaded corridor block; walk-up plan on small or shallow plates."""
    x0, y0, x1, y1 = _common_rect(spec)
    if y1 - y0 < 11.5 or x1 - x0 < 14 or len(spec.levels) < 2:
        return plan_walkup(spec, rng)
    side_piers = sorted(spec.piers(0)['left'])
    middle = (y0 + y1) / 2
    pairs = [(a, b) for a, b in zip(side_piers, side_piers[1:])
             if dims.CORRIDOR - EPS <= b - a <= 3.6 and a - y0 >= 4.4 and y1 - b >= 4.4]
    ca, cb = (min(pairs, key=lambda pair: abs(sum(pair) / 2 - middle)) if pairs else
              (middle - dims.CORRIDOR / 2, middle + dims.CORRIDOR / 2))
    long_side = stair_length([level.height for level in spec.levels]) + dims.CORE_WALL / 2
    short_side = stair_width() + dims.CORE_WALL
    back_depth = y1 - cb
    if back_depth + EPS >= long_side:
        need, axis = short_side, 'y'
    elif back_depth + EPS >= short_side:
        need, axis = long_side + dims.CORE_WALL / 2, 'x'
    else:
        return plan_walkup(spec, rng)
    front_piers = spec.piers(0)['front']
    target = (x0 + x1) / 2 + rng.choice((-1, 0, 1)) * (x1 - x0) * .2
    span = _snap_span(front_piers, x0 + 4.4, x1 - 4.4, need, target, ends=False)
    if span is None:
        return plan_walkup(spec, rng)
    sx0, sx1 = span
    door = _front_door(spec)
    lobby_span = None
    if door:
        lobby_span = _snap_span(front_piers, x0, x1, max(door[1] - door[0] + .8, 3.0),
                                (door[0] + door[1]) / 2)
    entry = -1 if axis == 'y' else (-1 if (sx0 + sx1) / 2 > (x0 + x1) / 2 else 1)
    levels = []
    for level in spec.levels:
        rect = spec.interior_rect(level.index)
        lx0, ly0, lx1, ly1 = rect
        tiling = Tiling(rect, level.index)
        is_ground = level.index == 0
        tiling.add('corridor', 'corridor', (lx0, ca, lx1, cb),
                   'lobby' if is_ground and lobby_span else None if is_ground else 'stair')
        tiling.add('stair', 'stair', (sx0, cb, sx1, ly1), 'corridor' if is_ground else None,
                   wall=dims.CORE_WALL, stair=(axis, entry, dims.STAIR_FLIGHT))
        if is_ground and lobby_span:
            la, lb = lobby_span
            tiling.add('lobby', 'lobby', (la, ly0, lb, ca))
            pieces = [_split_bays(lx0, la, front_piers), _split_bays(lb, lx1, front_piers)]
        else:
            pieces = [_split_bays(lx0, lx1, front_piers)]
        number = 0
        for cuts in pieces:
            for a, b in zip(cuts, cuts[1:]):
                _flat(tiling, spec, level, (a, ly0, b, ca), f'f{number}', corridor_low=False, rng=rng)
                number += 1
        for bx0, bx1 in ((lx0, sx0), (sx1, lx1)):
            cuts = _split_bays(bx0, bx1, front_piers)
            for a, b in zip(cuts, cuts[1:]):
                _flat(tiling, spec, level, (a, cb, b, ly1), f'b{number}', corridor_low=True, rng=rng)
                number += 1
        levels.append(tiling.level())
    doors = [('front', (lobby_span[0] + lobby_span[1]) / 2, door[2])] if lobby_span else None
    return Plan(levels, doors)


def _flat(tiling, spec, level, rect, tag, corridor_low, rng):
    """One flat: hall and bathroom on the corridor side, living room and bedroom outside."""
    x0, y0, x1, y1 = rect
    width, depth = x1 - x0, y1 - y0
    if width < .3:
        return
    if width < 4.4 or depth < 5.4:
        tiling.add(f'studio{tag}', 'living', rect, 'corridor')
        return
    side_piers = spec.piers(level.index)['left']
    if corridor_low:
        options = [p for p in side_piers if y0 + dims.MIN_BATH <= p <= y1 - 3.0]
        split = min(options, key=lambda p: abs(p - (y0 + 2.6))) if options else None
    else:
        options = [p for p in side_piers if y0 + 3.0 <= p <= y1 - dims.MIN_BATH]
        split = min(options, key=lambda p: abs(p - (y1 - 2.6))) if options else None
    if split is None:
        tiling.add(f'studio{tag}', 'living', rect, 'corridor')
        return
    if corridor_low:
        inner_rect, outer_rect = (x0, y0, x1, split), (x0, split, x1, y1)
    else:
        inner_rect, outer_rect = (x0, split, x1, y1), (x0, y0, x1, split)
    ix0, iy0, ix1, iy1 = inner_rect
    hall_w = max(dims.CORRIDOR, min(2.4, width - dims.MIN_BATH - .1))
    rest = width - hall_w
    if rest < dims.MIN_BATH:
        tiling.add(f'hall{tag}', 'hall', inner_rect, 'corridor', unit=tag)
    else:
        # Bathroom next to the hall; a kitchen takes what is left if it is a room.
        bath_w = rest if rest < dims.MIN_BATH + dims.MIN_ROOM else min(2.6, rest - dims.MIN_ROOM)
        pieces = [('hall', hall_w, 'corridor'), ('bath', bath_w, f'hall{tag}')]
        if rest - bath_w > .01:
            pieces.append(('kitchen', rest - bath_w, f'hall{tag}'))
        if rng.random() < .5:
            pieces.reverse()
        cursor = ix0
        for kind, size, parent in pieces:
            tiling.add(f'{kind}{tag}', kind, (cursor, iy0, cursor + size, iy1), parent, unit=tag)
            cursor += size
    ox0, oy0, ox1, oy1 = outer_rect
    splits = [p for p in spec.piers(level.index)['front'] if ox0 + 2.6 <= p <= ox1 - 2.6]
    if splits and width >= 5.6:
        cut = min(splits, key=lambda p: abs(p - (ox0 + width * .58)))
        tiling.add(f'living{tag}', 'living', (ox0, oy0, cut, oy1), f'hall{tag}', unit=tag)
        tiling.add(f'bed{tag}', 'bedroom', (cut, oy0, ox1, oy1), f'hall{tag}', unit=tag)
    else:
        tiling.add(f'living{tag}', 'living', outer_rect, f'hall{tag}', unit=tag)


def _tower_core(spec, elevators):
    """Central core rect sized for a switchback beside an elevator bank."""
    x0, y0, x1, y1 = _common_rect(spec)
    long_side = stair_length([level.height for level in spec.levels]) + dims.CORE_WALL
    short_side = stair_width() + dims.CORE_WALL
    shaft_w, shaft_d = dims.ELEVATOR_SHAFT
    plate_w, plate_d = x1 - x0, y1 - y0
    while elevators >= 0:
        core_w = short_side + elevators * (shaft_w + dims.CORE_WALL)
        if core_w + 2 * 3.2 <= plate_w and long_side + 2 * 3.2 <= plate_d:
            break
        elevators -= 1
    if elevators < 0:
        return None
    if elevators and long_side - (shaft_d + dims.CORE_WALL) < dims.MIN_BATH + .2:
        long_side = shaft_d + dims.CORE_WALL + dims.MIN_BATH + .2
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rect = (cx - core_w / 2, cy - long_side / 2, cx + core_w / 2, cy + long_side / 2)
    return rect, elevators, short_side, shaft_d + dims.CORE_WALL


def _ring(tiling, rect, core_rect, kind):
    """Four bands of one group around a central core."""
    x0, y0, x1, y1 = rect
    cx0, cy0, cx1, cy1 = core_rect
    tiling.add(f'{kind}F', kind, (x0, y0, x1, cy0), group=kind)
    tiling.add(f'{kind}B', kind, (x0, cy1, x1, y1), group=kind)
    tiling.add(f'{kind}L', kind, (x0, cy0, cx0, cy1), group=kind)
    tiling.add(f'{kind}R', kind, (cx1, cy0, x1, cy1), group=kind)


def plan_office(spec, rng, fit_out=True):
    """Office floors around a central core; the ground floor is a lobby."""
    floors = len(spec.levels)
    elevators = 0 if floors < 4 else 2 if floors < 12 else 3 if floors < 20 else 4
    core = _tower_core(spec, elevators)
    if core is None:
        return plan_walkup(spec, rng, 'shop', 'flat')
    core_rect, elevators, short_side, bank_d = core
    cx0, cy0, cx1, cy1 = core_rect
    flip = rng.random() < .5
    stair_x = (cx1 - short_side, cx1) if flip else (cx0, cx0 + short_side)
    bank_x = (cx0, cx1 - short_side) if flip else (cx0 + short_side, cx1)
    style = rng.choice(('open', 'cellular', 'mixed')) if fit_out else 'open'
    door = _front_door(spec)
    levels = []
    doors = None
    for level in spec.levels:
        rect = spec.interior_rect(level.index)
        tiling = Tiling(rect, level.index)
        is_ground = level.index == 0
        tiling.add('stair', 'stair', (stair_x[0], cy0, stair_x[1], cy1), None,
                   wall=dims.CORE_WALL, stair=('y', -1, dims.STAIR_FLIGHT))
        if elevators:
            width = (bank_x[1] - bank_x[0]) / elevators
            for index in range(elevators):
                sx = bank_x[0] + width * index
                tiling.add(f'lift{index}', 'shaft', (sx, cy0, sx + width, cy0 + bank_d),
                           wall=dims.CORE_WALL)
            tiling.add('wc', 'bath', (bank_x[0], cy0 + bank_d, bank_x[1], cy1),
                       wall=dims.CORE_WALL)
        if is_ground:
            doors = _office_ground(tiling, spec, rect, core_rect, door, fit_out)
        elif level.kind == 'MECHANICAL':
            _ring(tiling, rect, core_rect, 'plant')
        elif fit_out:
            _office_floor(tiling, spec, level, rect, core_rect, style)
        else:
            _ring(tiling, rect, core_rect, 'open')
        levels.append(tiling.level())
    return Plan(levels, doors)


def _office_ground(tiling, spec, rect, core_rect, door, fit_out):
    x0, y0, x1, y1 = rect
    cx0, cy0, cx1, cy1 = core_rect
    if not (fit_out and spec.lobby == 'RETAIL' and door and cx0 - x0 > 5 and x1 - cx1 > 5):
        _ring(tiling, rect, core_rect, 'lobby')
        if door and cy0 - y0 > 6:
            mid = (door[0] + door[1]) / 2
            ry = y0 + (cy0 - y0) * .55
            tiling.fixtures.append((mid - 2.2, ry, mid + 2.2, ry + .9, 1.1))
        return None
    # Lobby strip from the entrance to the lifts; shops either side with
    # their own street doors.
    piers = spec.piers(0)['front']
    la, lb = _snap_span(piers, cx0, cx1, 4.0, (door[0] + door[1]) / 2, ends=False) or (cx0, cx1)
    depths = [p for p in spec.piers(0)['left'] if y0 + 4.0 <= p <= cy0]
    if not depths:
        _ring(tiling, rect, core_rect, 'lobby')
        return None
    sy = max(depths)
    tiling.add('lobbyF', 'lobby', (la, y0, lb, cy0), group='lobby')
    tiling.add('lobbyB', 'lobby', (x0, cy1, x1, y1), group='lobby')
    tiling.add('lobbyL', 'lobby', (x0, sy, la, cy1), group='lobby')
    tiling.add('lobbyR', 'lobby', (lb, sy, x1, cy1), group='lobby')
    tiling.add('lobbyC', 'lobby', (la, cy0, cx0, cy1), group='lobby')
    tiling.add('lobbyD', 'lobby', (cx1, cy0, lb, cy1), group='lobby')
    tiling.add('shopL', 'shop', (x0, y0, la, sy), 'lobbyF')
    tiling.add('shopR', 'shop', (lb, y0, x1, sy), 'lobbyF')
    return [('front', (la + lb) / 2, max(door[2], dims.ENTRANCE_WIDTH)),
            ('front', (x0 + la) / 2, 1.8), ('front', (lb + x1) / 2, 1.8),
            ('back', (x0 + x1) / 2, 1.6)]


def _office_floor(tiling, spec, level, rect, core_rect, style):
    """Open plan around the core; cellular floors get offices along the back."""
    x0, y0, x1, y1 = rect
    cx0, cy0, cx1, cy1 = core_rect
    cellular = style == 'cellular' or (style == 'mixed' and level.index % 2 == 0)
    side = [p for p in spec.piers(level.index)['left']
            if cy1 + dims.CORRIDOR + .4 <= p <= y1 - 3.6]
    if not cellular or not side:
        _ring(tiling, rect, core_rect, 'open')
        return
    oy = min(side, key=lambda p: abs(y1 - p - 4.2))
    tiling.add('openF', 'open', (x0, y0, x1, cy0), group='open')
    tiling.add('openL', 'open', (x0, cy0, cx0, oy), group='open')
    tiling.add('openR', 'open', (cx1, cy0, x1, oy), group='open')
    tiling.add('openB', 'open', (cx0, cy1, cx1, oy), group='open')
    cuts = _split_bays(x0, x1, spec.piers(level.index)['back'], low=3.0, high=6.5)
    for number, (a, b) in enumerate(zip(cuts, cuts[1:])):
        kind = 'meeting' if number == 0 and b - a > 4.5 else 'office'
        tiling.add(f'{kind}{number}', kind, (a, oy, b, y1), 'openB')


def plan_core_only(spec, rng):
    """Tower shell without fit-out: core, lifts and stairs on open floors."""
    return plan_office(spec, rng, fit_out=False)


def plan_warehouse(spec, rng):
    """Open hall, an office and WC at the front corner, a stair at the back."""
    x0, y0, x1, y1 = _common_rect(spec)
    multi = len(spec.levels) > 1
    long_side = stair_length([level.height for level in spec.levels]) + dims.CORE_WALL / 2
    short_side = stair_width() + dims.CORE_WALL / 2
    front_piers = spec.piers(0)['front']
    door = _front_door(spec)
    door_mid = (door[0] + door[1]) / 2 if door else (x0 + x1) / 2
    office_left = door_mid > (x0 + x1) / 2
    edge = _cut_near(front_piers, x0, x1, x0 + 7.0 if office_left else x1 - 7.0, 3.0)
    depth = _cut_near(spec.piers(0)['left'], y0, y1, y0 + 5.0, 3.0)
    office = (0, 0, 0, 0)
    if edge is not None and depth is not None:
        office = (x0, y0, edge, depth) if office_left else (edge, y0, x1, depth)
    stair_rect = None
    if multi:
        back = spec.piers(0)['back']
        side = [p for p in spec.piers(0)['left'] if y0 + 6 <= p <= y1 - long_side + EPS]
        if office_left:
            xs = [p for p in back if x1 - short_side - 2.0 <= p <= x1 - short_side + EPS]
            sx = (max(xs), x1) if xs else None
        else:
            xs = [p for p in back if x0 + short_side - EPS <= p <= x0 + short_side + 2.0]
            sx = (x0, min(xs)) if xs else None
        if sx is None or not side:
            return plan_open(spec, rng)
        stair_rect = (sx[0], max(side), sx[1], y1)
    levels = []
    for level in spec.levels:
        rect = spec.interior_rect(level.index)
        tiling = Tiling(rect, level.index)
        is_ground = level.index == 0
        blocks = [stair_rect]
        has_office = is_ground and office[2] - office[0] > 2.9 and office[3] - office[1] > 2.9
        if has_office:
            blocks.append(office)
        _tile_around(tiling, rect, blocks, 'floor', 'open')
        if has_office:
            # The WC sits behind the office; its wall meets the side facade on solid wall.
            side = 'left' if office_left else 'right'
            spots = _wall_spots(spec, side, office[1] + dims.MIN_ROOM, office[3] - dims.MIN_BATH,
                                dims.PARTITION)
            if spots:
                cut = max(spots)
                tiling.add('office', 'office', (office[0], office[1], office[2], cut))
                tiling.add('wc', 'bath', (office[0], cut, office[2], office[3]))
            else:
                tiling.add('office', 'office', office)
        if stair_rect:
            tiling.add('stair', 'stair', stair_rect, None, wall=dims.CORE_WALL,
                       stair=('y', -1, dims.STAIR_FLIGHT))
        levels.append(tiling.level())
    return Plan(levels)


def _back_stair(spec, rect, heights, flight):
    """Stair room against the back wall whose walls meet facades on solid wall.

    Tries normal, compact and steep stairs, flights along y then x. Returns
    (rect, axis, mode) or None.
    """
    x0, y0, x1, y1 = rect
    # Walls on both long sides when the stair floats along the back wall.
    short = stair_width(flight) + dims.CORE_WALL
    spots = sorted({x0, x1} | set(_wall_spots(spec, 'back', x0, x1)))
    for mode in ('normal', 'compact', 'steep'):
        long_side = stair_length(heights, mode) + dims.CORE_WALL / 2
        for along_y in (True, False):
            need_x, need_y = (short, long_side) if along_y else (long_side, short)
            best = None
            for xa in spots:
                for xb in spots:
                    width = xb - xa
                    if width + EPS < need_x or width > need_x + 3.0:
                        continue
                    left, right = xa - x0, x1 - xb
                    if (EPS < left < 1.2) or (EPS < right < 1.2) or (left < EPS and right < EPS):
                        continue
                    if left < EPS or right < EPS:
                        side = 'left' if left < EPS else 'right'
                        ys = _wall_spots(spec, side, y0 + 1.2, y1 - need_y)
                        if not ys:
                            continue
                        ya = max(ys)
                    else:
                        ya = y1 - need_y
                        if ya - y0 < 1.2:
                            continue
                    score = (width - need_x) + (y1 - ya - need_y) + (0 if right < EPS else .5)
                    if best is None or score < best[0]:
                        best = (score, (xa, ya, xb, y1))
            if best is not None:
                return best[1], ('y' if along_y else 'x'), mode
    return None


def plan_open(spec, rng):
    """One open room per storey around a back stair (fallback plan)."""
    rect = _common_rect(spec)
    heights = [level.height for level in spec.levels]
    found = _back_stair(spec, rect, heights, 1.1) if len(spec.levels) > 1 else None
    stair_rect, axis, mode = found if found else (None, 'y', 'normal')
    notes = []
    storeys = spec.levels
    if len(spec.levels) > 1 and found is None:
        # No stair fits this plate: only the ground floor is fitted out.
        notes.append('no stair fits; upper floors are not enterable')
        storeys = spec.levels[:1]
    levels = []
    for level in storeys:
        level_rect = spec.interior_rect(level.index)
        tiling = Tiling(level_rect, level.index)
        _tile_around(tiling, level_rect, [stair_rect], 'room', 'open')
        if stair_rect:
            tiling.add('stair', 'stair', stair_rect, None, wall=dims.CORE_WALL,
                       stair=(axis, -1, 1.1, mode))
        levels.append(tiling.level())
    return Plan(levels, notes=notes)


PLANNERS = {
    'STOREFRONT': plan_storefront,
    'RESIDENTIAL': plan_apartments,
    'OFFICE': plan_office,
    'HOUSE': plan_house,
    'WAREHOUSE': plan_warehouse,
    'BAR': plan_bar,
}


# -- planning entry point ----------------------------------------------------

def plan_building(spec, profile=None, rng=None):
    """Plan every storey of ``spec``. Returns a Plan (no levels: no interior)."""
    params = spec.params
    profile = profile or params.get('building_profile', 'NONE')
    rng = rng or random.Random((spec.seed * 1103515245) ^ 0x1A70)
    tower_core = bool(params.get('skyscraper') and spec.has_slabs and
                      params.get('interior_fill', 'NONE') == 'NONE')
    if not spec.has_slabs and len(spec.levels) > 1:
        return Plan([])
    if tower_core:
        planner = plan_core_only if profile in (None, 'NONE') else plan_office
    else:
        planner = PLANNERS.get(profile)
    if planner is None:
        return Plan([])
    plan = planner(spec, rng)
    entrances = _entrance_rooms(spec, plan)
    for level in plan.levels:
        roots = entrances if level.index == 0 else [r.name for r in level.rooms if r.kind == 'stair']
        if not roots:
            roots = [r.name for r in level.rooms if r.kind == 'stair'] or \
                [max(level.rooms, key=lambda r: r.width * r.depth).name]
        resolve(level, roots)
        finish_level(level)
    previous = None
    for level in plan.levels:
        holes = []
        if previous is not None and previous.stair is not None:
            holes.append(stair_hole(previous.stair, spec.levels[previous.index].height))
        if level.index > 0:
            for room in level.rooms:
                if room.kind == 'shaft':
                    holes.append(_clear(room, level.rect))
        level.holes = holes
        previous = level
    return plan


def _entrance_rooms(spec, plan):
    """Ground rooms behind the street doors the plan (or spec) will use."""
    if not plan.levels:
        return []
    ground = plan.levels[0]
    if plan.doors is not None:
        doors = plan.doors
    else:
        doors = []
        for side in ('front', 'back', 'left', 'right'):
            for door in spec.door_bays(side):
                doors.append((side, spec.door_centre(side, door), door[2]))
    x0, y0, x1, y1 = ground.rect
    names = []
    for side, centre, _ in doors:
        point = {'front': (centre, y0 + .01), 'back': (centre, y1 - .01),
                 'left': (x0 + .01, centre), 'right': (x1 - .01, centre)}[side]
        room = room_at(ground, *point)
        if room is not None and room.name not in names:
            names.append(room.name)
    return names


def resolve(level, roots):
    """Make every room reachable through a door that fits.

    Keeps a room's requested parent when a door fits on their shared wall,
    otherwise re-parents it to the best reachable neighbour (circulation
    first). Rooms of one group are open to each other and need no door.
    """
    rooms = level.rooms
    lookup = {room.name: room for room in rooms}
    level.roots = [name for name in roots if name in lookup]
    reached = set(level.roots)
    for room in rooms:
        if room.name in reached:
            room.parent = None
    pending = [room for room in rooms if room.name not in reached]
    while pending:
        progress = False
        for room in list(pending):
            parent = lookup.get(room.parent)
            if parent is not None and parent.name in reached and door_window(room, parent):
                reached.add(room.name)
                pending.remove(room)
                progress = True
                continue
            mate = next((other for other in rooms if other.name in reached and
                         _same_group(room, other)), None)
            if mate is not None:
                room.parent = None
                reached.add(room.name)
                pending.remove(room)
                progress = True
        if progress:
            continue
        best = None
        for room in pending:
            for other in rooms:
                if other.name not in reached:
                    continue
                window = door_window(room, other)
                if window is None:
                    continue
                if room.kind == 'shaft' and other.kind not in PREFERENCE:
                    continue
                same_unit = room.unit is not None and other.unit == room.unit
                score = (0 if same_unit else 1, PREFERENCE.get(other.kind, 4),
                         0 if other.name == room.parent else 1, -(window[3] - window[2]))
                if best is None or score < best[0]:
                    best = (score, room, other)
        if best is None:
            for room in pending:
                level.issues.append(f'{room.name} unreachable')
            break
        _, room, other = best
        room.parent = other.name
        reached.add(room.name)
        pending.remove(room)


def finish_level(level):
    """Derive partitions, doors and the stair for a resolved storey."""
    lookup = {room.name: room for room in level.rooms}
    doors = []
    for room in level.rooms:
        parent = lookup.get(room.parent)
        if parent is None:
            continue
        window = door_window(room, parent)
        if window is None:
            level.issues.append(f'no door fits between {room.name} and {parent.name}')
            continue
        axis, line, lo, hi = window
        width = dims.DOOR_WIDTH
        if room.kind in ('bath', 'bedroom', 'office', 'storage', 'kitchen') and hi - lo > 3.2:
            centre = lo + .45 + width / 2      # Doors near a corner, like real rooms.
        else:
            centre = (lo + hi) / 2
        doors.append((room.name, parent.name, axis, line, centre, width))
    level.doors = doors
    level.walls = _walls(level, [(axis, line, centre, width)
                                 for _, _, axis, line, centre, width in doors])
    stair = next((room for room in level.rooms if room.kind == 'stair'), None)
    if stair is not None:
        level.stair = _stair_from_room(stair, level.rect)


def _walls(level, doors):
    """Partitions between rooms, resolved so wall boxes never overlap.

    Runs along x pass through junctions; runs along y stop at the face of any
    x-run they meet (and split where one crosses). At an L corner the x-run is
    extended over the corner square.
    """
    rooms = level.rooms
    lines = {}
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            if a.group is not None and a.group == b.group:
                continue
            shared = _shared_segment(a.rect, b.rect)
            if shared is None:
                continue
            axis, line, lo, hi = shared
            lines.setdefault((axis, round(line, 6)), []).append((lo, hi, max(a.wall, b.wall)))
    runs = {}
    for key, pieces in lines.items():
        pieces.sort()
        merged = []
        for lo, hi, thickness in pieces:
            if merged and lo <= merged[-1][1] + EPS and abs(merged[-1][2] - thickness) < EPS:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi), thickness)
            else:
                merged.append((lo, hi, thickness))
        runs[key] = merged
    xs = [(line, lo, hi, t) for (axis, line), items in runs.items() if axis == 'x'
          for lo, hi, t in items]
    ys = [(line, lo, hi, t) for (axis, line), items in runs.items() if axis == 'y'
          for lo, hi, t in items]
    rx0, ry0, rx1, ry1 = level.rect
    extended = []
    for y, lo, hi, t in xs:
        new_lo, new_hi = lo, hi
        # Ends where another run continues the same line are not corners.
        continued = {end for end in (lo, hi) for y2, lo2, hi2, _ in xs
                     if abs(y2 - y) < EPS and (lo2, hi2) != (lo, hi) and
                     (abs(lo2 - end) < EPS or abs(hi2 - end) < EPS)}
        for x, ylo, yhi, ty in ys:
            passes = ylo < y - EPS and yhi > y + EPS
            touches = ylo - EPS <= y <= yhi + EPS
            if not touches:
                continue
            for end, sign in ((lo, -1), (hi, 1)):
                if abs(x - end) > EPS:
                    continue
                if not passes and end in continued:
                    continue
                if passes:   # T junction: stop at the y-run's face.
                    if sign < 0:
                        new_lo = max(new_lo, x + ty / 2)
                    else:
                        new_hi = min(new_hi, x - ty / 2)
                else:        # L corner: cover the corner square.
                    if sign < 0:
                        new_lo = min(new_lo, x - ty / 2)
                    else:
                        new_hi = max(new_hi, x + ty / 2)
        extended.append((y, max(new_lo, rx0), min(new_hi, rx1), t))
    pieces = [('x', y, lo, hi, t) for y, lo, hi, t in extended if hi - lo > .05]
    for x, lo, hi, t in ys:
        segments = [(lo, hi)]
        for y, xlo, xhi, tx in extended:
            if not (xlo - EPS <= x <= xhi + EPS and lo - tx / 2 - EPS <= y <= hi + tx / 2 + EPS):
                continue
            c0, c1 = y - tx / 2, y + tx / 2
            following = []
            for s0, s1 in segments:
                if c1 <= s0 or c0 >= s1:
                    following.append((s0, s1))
                    continue
                if c0 > s0:
                    following.append((s0, c0))
                if c1 < s1:
                    following.append((c1, s1))
            segments = following
        pieces.extend(('y', x, s0, s1, t) for s0, s1 in segments if s1 - s0 > .05)
    walls = []
    placed = set()
    for axis, line, lo, hi, t in pieces:
        openings = []
        for index, (door_axis, door_line, centre, width) in enumerate(doors):
            if index in placed or door_axis != axis or abs(door_line - line) > EPS:
                continue
            if lo + .05 <= centre - width / 2 and centre + width / 2 <= hi - .05:
                openings.append((centre - width / 2 - lo, width, dims.DOOR_HEIGHT))
                placed.add(index)
        start, end = ((lo, line), (hi, line)) if axis == 'x' else ((line, lo), (line, hi))
        walls.append(Wall(start, end, t, openings))
    for index, door in enumerate(doors):
        if index not in placed:
            level.issues.append(f'door at {door[1]:.2f}/{door[2]:.2f} fell on a junction')
    return walls


def _clear(room, plate):
    """Clear rect inside a room's walls (walls are centred on internal edges)."""
    x0, y0, x1, y1 = room.rect
    half = room.wall / 2
    px0, py0, px1, py1 = plate
    return (x0 + (0 if abs(x0 - px0) < EPS else half), y0 + (0 if abs(y0 - py0) < EPS else half),
            x1 - (0 if abs(x1 - px1) < EPS else half), y1 - (0 if abs(y1 - py1) < EPS else half))


def _stair_from_room(room, plate):
    zone = _clear(room, plate)
    axis, entry, flight = room.stair[:3]
    mode = room.stair[3] if len(room.stair) > 3 else 'normal'
    riser, _, landing = STAIR_MODES[mode]
    short = (zone[2] - zone[0]) if axis == 'y' else (zone[3] - zone[1])
    flight = min(flight, (short - dims.STAIR_WELL) / 2, 1.6)
    return Stair(zone, axis, entry, landing, flight, riser)


# -- stairs ------------------------------------------------------------------

def stair_landing(stair, rise):
    """Landing length actually used for a storey of height ``rise``."""
    risers = max(2, math.ceil(rise / stair.riser - 1e-9))
    first = math.ceil(risers / 2)
    length = (stair.zone[3] - stair.zone[1]) if stair.axis == 'y' else (stair.zone[2] - stair.zone[0])
    return min(stair.landing, max(.9, (length - first * .22) / 2))


def stair_steps(stair, rise):
    """Boxes (x0, y0, z0, x1, y1, z1) of a switchback from 0 to ``rise``.

    Flight one climbs from the entry landing to the turning landing along one
    side; flight two climbs back along the other side and arrives at the
    entry landing of the storey above. Everything is solid to the floor.
    """
    zx0, zy0, zx1, zy1 = stair.zone
    risers = max(2, math.ceil(rise / stair.riser - 1e-9))
    riser = rise / risers
    first = math.ceil(risers / 2)
    second = risers - first
    length = (zy1 - zy0) if stair.axis == 'y' else (zx1 - zx0)
    across = (zx1 - zx0) if stair.axis == 'y' else (zy1 - zy0)
    landing = stair_landing(stair, rise)
    run = length - 2 * landing
    tread_a = run / first
    tread_b = run / max(1, second)
    flight = stair.flight
    boxes = []

    def place(a0, a1, b0, b1, z1):
        # a: along the flights (0 = entry end); b: across (0 = flight-one side).
        if stair.axis == 'y':
            ys = (zy0 + a0, zy0 + a1) if stair.entry < 0 else (zy1 - a1, zy1 - a0)
            xs = (zx0 + b0, zx0 + b1)
        else:
            xs = (zx0 + a0, zx0 + a1) if stair.entry < 0 else (zx1 - a1, zx1 - a0)
            ys = (zy1 - b1, zy1 - b0)
        boxes.append((xs[0], ys[0], 0.0, xs[1], ys[1], z1))

    for index in range(first):
        place(landing + index * tread_a, landing + (index + 1) * tread_a, 0, flight,
              (index + 1) * riser)
    mid = first * riser
    place(length - landing, length, 0, across, mid)
    for index in range(second):
        a1 = length - landing - index * tread_b
        place(a1 - tread_b, a1, across - flight, across, mid + (index + 1) * riser)
    return boxes, riser, min(tread_a, tread_b), landing


def stair_hole(stair, rise):
    """Slab opening above a switchback: everything but the entry landing."""
    zx0, zy0, zx1, zy1 = stair.zone
    landing = stair_landing(stair, rise)
    if stair.axis == 'y':
        return (zx0, zy0 + landing, zx1, zy1) if stair.entry < 0 else (zx0, zy0, zx1, zy1 - landing)
    return (zx0 + landing, zy0, zx1, zy1) if stair.entry < 0 else (zx0, zy0, zx1 - landing, zy1)


# -- validation --------------------------------------------------------------

def reachable(level):
    """Rooms reachable from the storey's roots through its doors and open groups."""
    graph = {room.name: set() for room in level.rooms}
    for room, parent, *_ in level.doors:
        graph[room].add(parent)
        graph[parent].add(room)
    for i, a in enumerate(level.rooms):
        for b in level.rooms[i + 1:]:
            if _same_group(a, b):
                graph[a.name].add(b.name)
                graph[b.name].add(a.name)
    seen = set()
    stack = [name for name in level.roots if name in graph]
    while stack:
        name = stack.pop()
        if name not in seen:
            seen.add(name)
            stack.extend(graph[name] - seen)
    return seen


def room_at(level, x, y):
    for room in level.rooms:
        x0, y0, x1, y1 = room.rect
        if x0 - EPS <= x <= x1 + EPS and y0 - EPS <= y <= y1 + EPS:
            return room
    return None
