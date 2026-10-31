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
    fixtures: list = field(default_factory=list)   # (x0, y0, x1, y1, height, kind[, facing]): game assets
    terraces: list = field(default_factory=list)   # Stepped auditorium floors (Terrace).
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
        self.terraces = []

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
        return LevelPlan(self.index, self.rect, self.rooms, fixtures=self.fixtures,
                         terraces=self.terraces)


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
                    level.fixtures.append((x0 + .8, y1 - 1.6, x1 - .8, y1 - 1.0, 1.1, 'bar_counter'))
            elif level.index == 0 and room.kind == 'storage':
                room.kind = 'kitchen'
            elif level.index > 0 and room.kind == 'living':
                room.kind = 'vip'
    return plan


def plan_apartments(spec, rng):
    """Double-loaded corridor block of flats; walk-up plan on small or shallow plates."""
    if len(spec.levels) < 2:
        return plan_walkup(spec, rng)
    return plan_corridor(spec, rng, _flat, (4.6, 9.5), fallback=plan_walkup)


def plan_school(spec, rng):
    """Classrooms either side of a corridor, WCs by the stair, exits at the corridor ends."""
    return plan_corridor(spec, rng, _single('classroom'), (6.5, 9.5), wc=True, exits=True,
                         fallback=plan_open)


def plan_civic(spec, rng):
    """Offices off a corridor (police, clinics, administration)."""
    return plan_corridor(spec, rng, _single('office'), (3.2, 6.5), wc=True, exits=True,
                         fallback=plan_open)


def _single(kind):
    def unit(tiling, spec, level, rect, tag, corridor_low, rng):
        tiling.add(f'{kind}{tag}', kind, rect, 'corridor')
    return unit


def plan_corridor(spec, rng, unit, widths, wc=False, exits=False, fallback=None):
    """Rooms either side of a corridor along the building, a stair core at the back.

    ``unit`` fills each slice of the two strips (flats, classrooms, offices);
    slices are cut at facade piers so their walls never land on windows.
    """
    fallback = fallback or plan_walkup
    x0, y0, x1, y1 = _common_rect(spec)
    multi = len(spec.levels) > 1
    if y1 - y0 < 11.5 or x1 - x0 < 14:
        return fallback(spec, rng)
    side_piers = sorted(spec.piers(0)['left'])
    middle = (y0 + y1) / 2
    pairs = [(a, b) for a, b in zip(side_piers, side_piers[1:])
             if dims.CORRIDOR - EPS <= b - a <= 3.6 and a - y0 >= 4.4 and y1 - b >= 4.4]
    if not pairs:
        return fallback(spec, rng)
    ca, cb = min(pairs, key=lambda pair: abs(sum(pair) / 2 - middle))
    front_piers = spec.piers(0)['front']
    sx0 = sx1 = None
    axis, entry = 'y', -1
    if multi:
        long_side = stair_length([level.height for level in spec.levels]) + dims.CORE_WALL / 2
        short_side = stair_width() + dims.CORE_WALL
        back_depth = y1 - cb
        if back_depth + EPS >= long_side:
            need, axis = short_side, 'y'
        elif back_depth + EPS >= short_side:
            need, axis = long_side + dims.CORE_WALL / 2, 'x'
        else:
            return fallback(spec, rng)
        target = (x0 + x1) / 2 + rng.choice((-1, 0, 1)) * (x1 - x0) * .2
        span = _snap_span(front_piers, x0 + 4.4, x1 - 4.4, need, target, ends=False)
        if span is None:
            return fallback(spec, rng)
        sx0, sx1 = span
        entry = -1 if axis == 'y' else (-1 if (sx0 + sx1) / 2 > (x0 + x1) / 2 else 1)
    door = _front_door(spec)
    lobby_span = None
    if door:
        lobby_span = _snap_span(front_piers, x0, x1, max(door[1] - door[0] + .8, 3.0),
                                (door[0] + door[1]) / 2)
    levels = []
    for level in spec.levels:
        rect = spec.interior_rect(level.index)
        lx0, ly0, lx1, ly1 = rect
        tiling = Tiling(rect, level.index)
        is_ground = level.index == 0
        tiling.add('corridor', 'corridor', (lx0, ca, lx1, cb),
                   'lobby' if is_ground and lobby_span else None if is_ground else 'stair')
        if multi:
            tiling.add('stair', 'stair', (sx0, cb, sx1, ly1), 'corridor' if is_ground else None,
                       wall=dims.CORE_WALL, stair=(axis, entry, dims.STAIR_FLIGHT))
        if is_ground and lobby_span:
            la, lb = lobby_span
            tiling.add('lobby', 'lobby', (la, ly0, lb, ca))
            pieces = [_split_bays(lx0, la, front_piers, *widths),
                      _split_bays(lb, lx1, front_piers, *widths)]
        else:
            pieces = [_split_bays(lx0, lx1, front_piers, *widths)]
        number = 0
        for cuts in pieces:
            for a, b in zip(cuts, cuts[1:]):
                unit(tiling, spec, level, (a, ly0, b, ca), f'f{number}', corridor_low=False, rng=rng)
                number += 1
        back = ((lx0, sx0), (sx1, lx1)) if multi else ((lx0, lx1),)
        for block, (bx0, bx1) in enumerate(back):
            cuts = _split_bays(bx0, bx1, front_piers, *widths)
            for index, (a, b) in enumerate(zip(cuts, cuts[1:])):
                beside_stair = multi and ((block == 0 and index == len(cuts) - 2) or
                                          (block == 1 and index == 0))
                if wc and beside_stair and b - a >= dims.MIN_BATH:
                    tiling.add(f'wc{number}', 'bath', (a, cb, b, ly1), 'corridor')
                else:
                    unit(tiling, spec, level, (a, cb, b, ly1), f'b{number}', corridor_low=True,
                         rng=rng)
                number += 1
        levels.append(tiling.level())
    doors = []
    if lobby_span:
        doors.append(('front', (lobby_span[0] + lobby_span[1]) / 2, door[2]))
    if exits:
        doors += [('left', (ca + cb) / 2, 1.6), ('right', (ca + cb) / 2, 1.6)]
    return Plan(levels, doors or None)


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
            tiling.fixtures.append((mid - 2.2, ry, mid + 2.2, ry + .9, 1.1, 'reception_desk'))
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


def _back_zone(spec, level, rect, depth, minimum=dims.MIN_ROOM):
    """y of a wall cutting a back zone off the plate, on a side pier (or None)."""
    x0, y0, x1, y1 = rect
    options = [p for p in spec.piers(level.index)['left'] if y0 + minimum <= p <= y1 - 2.0]
    if not options:
        return None
    return min(options, key=lambda p: abs((y1 - p) - depth))


def plan_shop(spec, rng):
    """Sales room on the street, store room and WC behind, a counter."""
    if len(spec.levels) > 1:
        return plan_walkup(spec, rng, 'shop', 'flat')
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    cut = _back_zone(spec, spec.levels[0], rect, 3.5)
    if cut is None:
        tiling.add('shop', 'shop', rect)
    else:
        tiling.add('shop', 'shop', (x0, y0, x1, cut))
        split = [p for p in spec.piers(0)['back'] if x0 + dims.MIN_BATH <= p <= x0 + 3.2 and
                 x1 - p >= dims.MIN_ROOM]
        if split:
            tiling.add('wc', 'bath', (x0, cut, split[0], y1), 'shop')
            tiling.add('store', 'storage', (split[0], cut, x1, y1), 'shop')
        else:
            tiling.add('store', 'storage', (x0, cut, x1, y1), 'shop')
        tiling.fixtures.append((x0 + (x1 - x0) * .45, cut - 1.5, x1 - .8, cut - .9, 1.05,
                                'shop_counter'))
    return Plan([tiling.level()])


def plan_restaurant(spec, rng):
    """Dining room on the street, counter, kitchen and restrooms behind."""
    if len(spec.levels) > 1:
        return plan_walkup(spec, rng, 'shop', 'flat')
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    cut = _back_zone(spec, spec.levels[0], rect, (y1 - y0) * .42)
    if cut is None:
        tiling.add('dining', 'bar', rect)
        return Plan([tiling.level()])
    tiling.add('dining', 'bar', (x0, y0, x1, cut))
    split = [p for p in spec.piers(0)['back'] if x0 + 2.4 <= p <= x0 + 4.5 and x1 - p >= 4.0]
    if split:
        tiling.add('restrooms', 'bath', (x0, cut, split[0], y1), 'dining')
        tiling.add('kitchen', 'kitchen', (split[0], cut, x1, y1), 'dining')
    else:
        tiling.add('kitchen', 'kitchen', (x0, cut, x1, y1), 'dining')
    left = split[0] if split else x0
    tiling.fixtures.append((left + 1.0, cut - 1.6, x1 - 1.0, cut - 1.0, 1.05, 'service_counter'))
    return Plan([tiling.level()])


def plan_strip(spec, rng):
    """A row of shop units, each with its own street door, back room and back door."""
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    cut = _back_zone(spec, spec.levels[0], rect, 3.5)
    cuts = _split_bays(x0, x1, spec.piers(0)['front'], 5.5, 10.5)
    doors = []
    for number, (a, b) in enumerate(zip(cuts, cuts[1:])):
        if cut is None:
            tiling.add(f'shop{number}', 'shop', (a, y0, b, y1), unit=f'u{number}')
        else:
            tiling.add(f'shop{number}', 'shop', (a, y0, b, cut), unit=f'u{number}')
            tiling.add(f'back{number}', 'storage', (a, cut, b, y1), f'shop{number}', unit=f'u{number}')
        doors.append(('front', (a + b) / 2, 1.6))
        doors.append(('back', (a + b) / 2, 1.2))
        tiling.fixtures.append((a + 1.0, y0 + (cut or y1 - y0) * .55, b - 1.0,
                                y0 + (cut or y1 - y0) * .55 + .6, 1.0, 'shop_counter'))
    return Plan([tiling.level()], doors)


def plan_bigbox(spec, rng):
    """Open sales floor, stockroom along the back, an office and WC by the entrance."""
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    cut = _back_zone(spec, spec.levels[0], rect, min(12.0, (y1 - y0) * .3), 6.0)
    sales_y1 = cut if cut is not None else y1
    office_x = [p for p in spec.piers(0)['front'] if x0 + 5.0 <= p <= x0 + 9.0]
    office_y = [p for p in spec.piers(0)['left'] if y0 + 4.0 <= p <= y0 + 7.0 and p < sales_y1 - 6]
    if office_x and office_y:
        ox, oy = office_x[0], office_y[0]
        blocks = [(x0, y0, ox, oy)]
        _tile_around(tiling, (x0, y0, x1, sales_y1), blocks, 'sales', 'shop')
        half = [p for p in spec.piers(0)['front'] if x0 + 2.4 <= p <= ox - 2.0]
        if half:
            tiling.add('office', 'office', (x0, y0, half[0], oy))
            tiling.add('wc', 'bath', (half[0], y0, ox, oy))
        else:
            tiling.add('office', 'office', (x0, y0, ox, oy))
    else:
        _tile_around(tiling, (x0, y0, x1, sales_y1), [], 'sales', 'shop')
    if cut is not None:
        tiling.add('stock', 'storage', (x0, cut, x1, y1))
    return Plan([tiling.level()])


def plan_hotel(spec, rng):
    """Hotel: guest rooms either side of a corridor on the upper floors; on the
    ground floor a lobby with the reception desk, a dining room on the street
    side and the kitchen and offices behind."""
    if len(spec.levels) < 2:
        return plan_motel(spec, rng)
    plan = plan_corridor(spec, rng, _hotel_unit, (3.6, 4.9), wc=True, exits=True,
                         fallback=plan_walkup)
    if plan.levels:
        lobby = next((r for r in plan.levels[0].rooms if r.kind == 'lobby'), None)
        if lobby is not None and lobby.width >= 3.6 and lobby.depth >= 4.5:
            x0, y0, x1, y1 = lobby.rect
            # Along a side wall, clear of the street door and the corridor door.
            plan.levels[0].fixtures.append((x0 + .5, y0 + 1.6, x0 + 1.2, y1 - 1.6, 1.1,
                                            'reception_desk', (1.0, 0.0)))
    return plan


def _hotel_unit(tiling, spec, level, rect, tag, corridor_low, rng):
    if level.index == 0:
        if not corridor_low:
            tiling.add(f'dining{tag}', 'bar', rect, 'corridor', group='dining')
        elif tiling.get('kitchen') is None:
            tiling.add('kitchen', 'kitchen', rect, 'corridor')
        else:
            tiling.add(f'office{tag}', 'office' if rng.random() < .6 else 'storage', rect,
                       'corridor')
        return
    _guest_room(tiling, spec, level, rect, tag, corridor_low, rng)


def _guest_room(tiling, spec, level, rect, tag, corridor_low, rng):
    """A guest room: entry passage and bathroom on the corridor side, the
    bedroom beyond."""
    x0, y0, x1, y1 = rect
    width, depth = x1 - x0, y1 - y0
    side_piers = spec.piers(level.index)['left']
    if corridor_low:
        options = [p for p in side_piers if y0 + dims.MIN_BATH <= p <= y1 - 3.0]
        split = min(options, key=lambda p: abs(p - (y0 + 2.4))) if options else None
    else:
        options = [p for p in side_piers if y0 + 3.0 <= p <= y1 - dims.MIN_BATH]
        split = min(options, key=lambda p: abs(p - (y1 - 2.4))) if options else None
    if split is None or width < dims.CORRIDOR + dims.MIN_BATH or depth < 5.4:
        tiling.add(f'room{tag}', 'bedroom', rect, 'corridor', unit=tag)
        return
    inner = (x0, y0, x1, split) if corridor_low else (x0, split, x1, y1)
    outer = (x0, split, x1, y1) if corridor_low else (x0, y0, x1, split)
    ix0, iy0, ix1, iy1 = inner
    pieces = [('entry', dims.CORRIDOR, 'corridor'), ('bath', width - dims.CORRIDOR, f'entry{tag}')]
    if rng.random() < .5:
        pieces.reverse()
    cursor = ix0
    for name, size, parent in pieces:
        kind = 'hall' if name == 'entry' else 'bath'
        tiling.add(f'{name}{tag}', kind, (cursor, iy0, cursor + size, iy1), parent, unit=tag)
        cursor += size
    tiling.add(f'room{tag}', 'bedroom', outer, f'entry{tag}', unit=tag)


def plan_motel(spec, rng):
    """Motel: a row of rooms, each with its own door on the front and a bath
    at the back; the office (reception desk) and a store at one end."""
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    piers = spec.piers(0)['front']
    cut = _back_zone(spec, spec.levels[0], rect, 2.4, dims.MIN_BATH)
    office_right = spec.params.get('office_side', 'left') == 'right'
    span = 5.5
    if office_right:
        options = [p for p in piers if x1 - 8.0 <= p <= x1 - 4.4]
        ox = min(options, key=lambda p: abs(x1 - p - span)) if options else None
    else:
        options = [p for p in piers if x0 + 4.4 <= p <= x0 + 8.0]
        ox = min(options, key=lambda p: abs(p - x0 - span)) if options else None
    doors = []
    rooms_lo, rooms_hi = x0, x1
    if not spec.params.get('motel_office', True):
        ox = None                        # A wing of rooms only.
    if ox is not None:
        oa, ob = (ox, x1) if office_right else (x0, ox)
        rooms_lo, rooms_hi = (x0, ox) if office_right else (ox, x1)
        tiling.add('office', 'lobby', (oa, y0, ob, cut if cut is not None else y1))
        if cut is not None:
            tiling.add('store', 'storage', (oa, cut, ob, y1), 'office')
        tiling.fixtures.append((oa + .8, y0 + 2.4, ob - .8, y0 + 3.0, 1.1, 'reception_desk'))
        doors.append(('front', (oa + ob) / 2, 1.4))
    cuts = _split_bays(rooms_lo, rooms_hi, piers, 3.6, 4.8)
    for number, (a, b) in enumerate(zip(cuts, cuts[1:])):
        unit = f'r{number}'
        tiling.add(f'room{number}', 'bedroom', (a, y0, b, cut if cut is not None else y1), unit=unit)
        if cut is not None:
            tiling.add(f'bath{number}', 'bath', (a, cut, b, y1), f'room{number}', unit=unit)
        # The door takes the first bay of the room, the window the next.
        inner = [p for p in piers if a + 1e-6 < p < b - 1e-6]
        bay_end = inner[0] if inner else b
        doors.append(('front', (a + bay_end) / 2, 1.0))
    return Plan([tiling.level()], doors)


# Cinema auditoriums have stadium seating: the floor rises in tiers from a
# flat strip in front of the screen. Risers stay under the player's 0.4 m step
# offset, so the tiers are walked straight up.
TERRACE_TREAD = 1.0
TERRACE_RISER = .3
TERRACE_FLAT = 4.0        # Least depth of the flat strip before the first tier.
TERRACE_HEADROOM = 2.6    # Clear height kept over the top tier.
TERRACE_PIECE = 2.4       # Tiers are built in pieces this wide (damage takes pieces).
SEAT_PITCH = .6
SEAT_SIZE = (.55, .55, .9)
SEAT_BACK = .6            # Seat centre behind its tier's front edge.
SEAT_AISLE = 1.0          # Side aisles; rows wider than SEAT_SPLIT get a centre aisle.
SEAT_CENTRE_AISLE = 1.2
SEAT_SPLIT = 14.0


@dataclass
class Terrace:
    """Stadium seating in an auditorium: the floor rises in ``rows`` tiers from
    a flat strip ``flat`` deep along the rect's low-y edge (the screen wall,
    which the room is entered by) to its far wall. Seats face -y."""
    room: str
    rect: tuple
    rows: int
    flat: float

    def tiers(self):
        """[(y0, y1, top)] per tier, ``top`` above the floor; the last tier
        runs to the far wall."""
        x0, y0, x1, y1 = self.rect
        result = []
        for row in range(1, self.rows + 1):
            a = y0 + self.flat + (row - 1) * TERRACE_TREAD
            result.append((a, y1 if row == self.rows else a + TERRACE_TREAD,
                           row * TERRACE_RISER))
        return result

    def pieces(self):
        """(x0, y0, x1, y1, top, row) solids, 2 cm into the walls round them so
        none of their faces lies on a wall face."""
        x0, y0, x1, y1 = self.rect
        count = max(1, math.ceil((x1 - x0) / TERRACE_PIECE))
        cuts = [x0 + (x1 - x0) * i / count for i in range(count + 1)]
        cuts[0], cuts[-1] = x0 - .02, x1 + .02
        result = []
        for row, (a, b, top) in enumerate(self.tiers(), 1):
            b += .02 if row == self.rows else 0.0
            result.extend((u, a, v, b, top, row) for u, v in zip(cuts, cuts[1:]))
        return result

    def seats(self):
        """(x, y, top) seat centres in rows on every tier, with side aisles and,
        in a wide room, a centre aisle."""
        x0, y0, x1, y1 = self.rect
        lo, hi = x0 + SEAT_AISLE, x1 - SEAT_AISLE
        blocks = [(lo, hi)]
        if hi - lo > SEAT_SPLIT:
            mid = (lo + hi) / 2
            blocks = [(lo, mid - SEAT_CENTRE_AISLE / 2), (mid + SEAT_CENTRE_AISLE / 2, hi)]
        result = []
        for a, _, top in self.tiers():
            for u, v in blocks:
                count = int((v - u + 1e-9) // SEAT_PITCH)
                start = (u + v) / 2 - (count - 1) * SEAT_PITCH / 2
                result.extend((start + i * SEAT_PITCH, a + SEAT_BACK, top) for i in range(count))
        return result


def terrace(name, rect, clear, flat):
    """A Terrace for an auditorium with ``clear`` height, or None if it is too
    small for two tiers."""
    x0, y0, x1, y1 = rect
    rows = min(int((y1 - y0 - flat) // TERRACE_TREAD),
               int((clear - TERRACE_HEADROOM) // TERRACE_RISER))
    if rows < 2 or x1 - x0 < 2 * SEAT_AISLE + 2 * SEAT_PITCH:
        return None
    return Terrace(name, rect, rows, flat)


def terrace_lost(field, z, piece):
    """Whether damage has taken a terrace piece (the shell leaves it out and
    its seats go with it)."""
    x0, y0, x1, y1, top, _ = piece
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return field.damaged and (field.height(cx, cy) < z + top + .2 or
                              field.in_blast(cx, cy, z + top / 2))


def plan_cinema(spec, rng):
    """Cinema: a lobby across the front (ticket desk, concession counter) and
    behind it one big auditorium (``params['cinema'] == 'PALACE'``), two side
    by side ('TWIN') or a corridor to several ('MULTIPLEX'), restrooms at the
    lobby ends. Each auditorium's screen is on the wall it is entered by; its
    floor rises in tiers (stadium seating) from the flat strip in front of the
    screen, where its exits are too."""
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    tiling = Tiling(rect, 0)
    piers = spec.piers(0)
    variant = spec.params.get('cinema', 'MULTIPLEX')
    palace = variant == 'PALACE'
    side = [p for p in piers['left'] if any(abs(p - q) < 1e-6 for q in piers['right'])]
    side = side or piers['left']
    target = y0 + (10.0 if variant == 'MULTIPLEX' else 7.0)
    options = [p for p in side if y0 + 5.0 <= p <= y1 - 12.0]
    if not options:
        return plan_open(spec, rng)
    lobby_y = min(options, key=lambda p: abs(p - target))
    level = spec.levels[0]
    clear = level.height - (spec.roof_slab if len(spec.levels) == 1 else spec.slab)
    # Side exits open from the first bay behind the lobby wall; the flat strip
    # in front of the screen covers it.
    beyond = [p for p in side if p >= lobby_y + 1.6 + dims.MIN_PIER - 1e-6]
    bay_end = beyond[0] if beyond else lobby_y + TERRACE_FLAT
    exit_y = (lobby_y + bay_end) / 2
    flat = max(TERRACE_FLAT, bay_end - lobby_y + .6)

    def auditorium(name, room_rect, parent):
        tiling.add(name, 'auditorium', room_rect, parent)
        seating = terrace(f'{name}_0', room_rect, clear, flat)
        if seating is not None:
            tiling.terraces.append(seating)

    doors = [('front', (x0 + x1) / 2, 2.4 if palace else 3.6)]
    ends = [p for p in piers['front'] if x0 + 3.0 <= p <= x0 + 5.5]
    ends_r = [p for p in piers['front'] if x1 - 5.5 <= p <= x1 - 3.0]
    la, lb = x0, x1
    if ends and ends_r and x1 - x0 > 20:
        la, lb = ends[0], ends_r[-1]
        tiling.add('wc_a', 'bath', (x0, y0, la, lobby_y), 'lobby')
        tiling.add('wc_b', 'bath', (lb, y0, x1, lobby_y), 'lobby')
    tiling.add('lobby', 'lobby', (la, y0, lb, lobby_y))
    # Concession counter along the back of the lobby, ticket desk by the door.
    mid = (la + lb) / 2
    tiling.fixtures.append((la + 1.0, lobby_y - 2.2, mid - 1.6, lobby_y - 1.5, 1.05,
                            'service_counter'))
    tiling.fixtures.append((lb - 3.4, y0 + 1.6, lb - 1.0, y0 + 2.3, 1.1, 'reception_desk'))
    middle = [p for p in piers['back'] if x0 + (x1 - x0) * .35 <= p <= x1 - (x1 - x0) * .35]
    if variant == 'TWIN' and middle:
        split = min(middle, key=lambda p: abs(p - (x0 + x1) / 2))
        auditorium('screen0', (x0, lobby_y, split, y1), 'lobby')
        auditorium('screen1', (split, lobby_y, x1, y1), 'lobby')
        doors += [('left', exit_y, 1.6), ('right', exit_y, 1.6)]
        return Plan([tiling.level()], doors)
    hall = [p for p in side if lobby_y + 2.4 <= p <= lobby_y + 4.8]
    hall_y = min(hall, key=lambda p: abs(p - lobby_y - 3.0)) if hall else None
    if palace or variant == 'TWIN' or hall_y is None or y1 - hall_y < 10:
        auditorium('auditorium', (x0, lobby_y, x1, y1), 'lobby')
        doors += [('left', exit_y, 1.6), ('right', exit_y, 1.6)]
        return Plan([tiling.level()], doors)
    # Multiplex: the corridor runs the width, with an exit at each end.
    tiling.add('corridor', 'corridor', (x0, lobby_y, x1, hall_y), 'lobby')
    cuts = _split_bays(x0, x1, piers['back'], 10.0, 16.0)
    flat = TERRACE_FLAT
    for number, (a, b) in enumerate(zip(cuts, cuts[1:])):
        auditorium(f'screen{number}', (a, hall_y, b, y1), 'corridor')
    doors += [('left', (lobby_y + hall_y) / 2, 1.6), ('right', (lobby_y + hall_y) / 2, 1.6)]
    return Plan([tiling.level()], doors)


MALL_CONCOURSE = 9.0       # Width of a mall's concourse.


def plan_mall(spec, rng):
    """Enclosed mall: an anchor store at each end, a concourse between them
    lined with shop units, an entrance hall from the front door, a food court
    and restrooms on the back row.

    ``params['anchors']`` gives the anchors' widths (left, right); the widest
    front door is the main entrance. Anchor walls stand
    on piers shared by the front and back facades; the concourse only meets
    internal walls, so it needs no pier.
    """
    rect = spec.interior_rect(0)
    x0, y0, x1, y1 = rect
    piers = spec.piers(0)
    left_w, right_w = spec.params.get('anchors', (24.0, 24.0))
    common = [p for p in piers['front'] if any(abs(p - q) < 1e-6 for q in piers['back'])]
    if not common:
        return plan_bigbox(spec, rng)
    xa = min(common, key=lambda p: abs(p - (x0 + left_w)))
    xb = min(common, key=lambda p: abs(p - (x1 - right_w)))
    if xb - xa < 18 or xa - x0 < 10 or x1 - xb < 10:
        return plan_bigbox(spec, rng)
    tiling = Tiling(rect, 0)
    front_depth = min(13.0, (y1 - y0 - MALL_CONCOURSE) * .4)
    cy0 = y0 + front_depth
    cy1 = cy0 + MALL_CONCOURSE
    fronts = spec.door_bays('front')
    entrance = (spec.door_centre('front', max(fronts, key=lambda d: d[2])) if fronts
                else (x0 + x1) / 2)
    # The concourse is one open space with the entrance hall, the food court and
    # the anchors' mall fronts (one group: no walls between them).
    common = 'common'
    tiling.add('concourse', 'corridor', (xa, cy0, xb, cy1), group=common)
    # Front row: shop units, the entrance hall at the main door. Counters
    # face the concourse the customers come from.
    cuts = _split_bays(xa, xb, piers['front'], 6.0, 11.0)
    for number, (a, b) in enumerate(zip(cuts, cuts[1:])):
        if a <= entrance <= b:
            tiling.add('entrance', 'lobby', (a, y0, b, cy0), group=common)
            continue
        tiling.add(f'shopF{number}', 'shop', (a, y0, b, cy0), 'concourse', unit=f'f{number}')
        if b - a > 3.5:
            tiling.fixtures.append((a + 1.0, y0 + 1.2, b - 1.0, y0 + 1.8, 1.0, 'shop_counter',
                                    (0.0, 1.0)))
    # Back row: shop units, a food court opposite the entrance, restrooms beside it.
    cuts = _split_bays(xa, xb, piers['back'], 6.0, 11.0)
    units = list(zip(cuts, cuts[1:]))
    middle = min(range(len(units)), key=lambda k: abs((units[k][0] + units[k][1]) / 2 - entrance))
    food = [middle]
    if units[middle][1] - units[middle][0] < 10 and middle + 1 < len(units):
        food.append(middle + 1)
    restrooms = max(food) + 1 if max(food) + 1 < len(units) else min(food) - 1
    for number, (a, b) in enumerate(units):
        if number in food[1:]:
            continue
        if number == food[0]:
            b = units[food[-1]][1]
            tiling.add('food_court', 'bar', (a, cy1, b, y1), group=common)
            tiling.fixtures.append((a + 1.0, y1 - 2.2, b - 1.0, y1 - 1.4, 1.05, 'service_counter'))
        elif number == restrooms:
            tiling.add('restrooms', 'bath', (a, cy1, b, y1), 'concourse')
        else:
            tiling.add(f'shopB{number}', 'shop', (a, cy1, b, y1), 'concourse', unit=f'b{number}')
            if b - a > 3.5:
                tiling.fixtures.append((a + 1.0, y1 - 1.8, b - 1.0, y1 - 1.2, 1.0, 'shop_counter'))
    # Anchors: a sales floor open to the concourse and the street, stock behind.
    for name, (a, b), side in (('L', (x0, xa), 'left'), ('R', (xb, x1), 'right')):
        options = [p for p in piers[side] if y0 + 20.0 <= p <= y1 - 6.0]
        cut = min(options, key=lambda p: abs(y1 - p - 10.0)) if options else None
        tiling.add(f'anchor{name}', 'shop', (a, y0, b, cut if cut is not None else y1), group=common)
        tiling.fixtures.append((a + 2.0, y0 + 4.0, a + 2.0 + min(8.0, b - a - 4.0), y0 + 4.8, 1.0,
                                'shop_counter'))
        if cut is not None:
            tiling.add(f'stock{name}', 'storage', (a, cut, b, y1), f'anchor{name}')
    return Plan([tiling.level()])


def plan_bay(spec, rng):
    """One open hall (vehicle bays, depots)."""
    rect = spec.interior_rect(0)
    tiling = Tiling(rect, 0)
    tiling.add('hall', 'open', rect)
    return Plan([tiling.level()])


PLANNERS = {
    'SHOP': plan_shop,
    'RESTAURANT': plan_restaurant,
    'STRIP': plan_strip,
    'BIGBOX': plan_bigbox,
    'BAY': plan_bay,
    'MALL': plan_mall,
    'HOTEL': plan_hotel,
    'MOTEL': plan_motel,
    'CINEMA': plan_cinema,
    'SCHOOL': plan_school,
    'CIVIC': plan_civic,
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
    # A room with its own street door still opens into the building (a back
    # room into its shop, a stock room into the sales floor): once everything
    # is reached, the door it asked for is added back, or one to its best
    # neighbour when it asked for none or that room is not beside it.
    kept = {}
    for room in rooms:
        if room.name in reached:
            if room.parent is not None:
                kept[room.name] = room.parent
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
    for name in level.roots:
        room = lookup[name]
        if (room.parent is not None or any(o.parent == name for o in rooms) or
                any(_same_group(room, o) for o in rooms if o is not room)):
            continue                      # Already opens into the building.
        other = lookup.get(kept.get(name))
        if other is not None and not _same_group(room, other) and door_window(room, other):
            room.parent = other.name
            continue
        # Nothing requested beside it: the best neighbour instead, inside its
        # own unit or onto shared circulation (never into another tenancy).
        options = [o for o in rooms if o is not room and door_window(room, o) is not None and
                   (room.unit is None or o.unit == room.unit or
                    (o.unit is None and o.kind in PREFERENCE))]
        if options:
            room.parent = min(options, key=lambda o: (
                0 if room.unit is not None and o.unit == room.unit else 1,
                PREFERENCE.get(o.kind, 4), -(door_window(room, o)[3] - door_window(room, o)[2]))).name


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
        elif room.kind == 'auditorium' and hi - lo > 3.2:
            centre = lo + 1.2 + width / 2      # Beside the screen, not under it.
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


class StairFrame:
    """Measurements of a switchback for one storey's rise, and the map from
    stair coordinates to plan coordinates: ``a`` runs along the flights
    (0 = entry end), ``b`` across them (0 = flight-one side)."""

    def __init__(self, stair, rise):
        self.stair = stair
        zx0, zy0, zx1, zy1 = stair.zone
        risers = max(2, math.ceil(rise / stair.riser - 1e-9))
        self.riser = rise / risers
        self.first = math.ceil(risers / 2)
        self.second = risers - self.first
        self.length = (zy1 - zy0) if stair.axis == 'y' else (zx1 - zx0)
        self.across = (zx1 - zx0) if stair.axis == 'y' else (zy1 - zy0)
        self.landing = stair_landing(stair, rise)
        run = self.length - 2 * self.landing
        self.tread_a = run / self.first
        self.tread_b = run / max(1, self.second)
        self.flight = stair.flight
        self.mid = self.first * self.riser
        self.rise = rise

    def xs_ys(self, a0, a1, b0, b1):
        """Plan extents (x0, x1), (y0, y1) of the stair rectangle a0..a1, b0..b1."""
        zx0, zy0, zx1, zy1 = self.stair.zone
        if self.stair.axis == 'y':
            ys = (zy0 + a0, zy0 + a1) if self.stair.entry < 0 else (zy1 - a1, zy1 - a0)
            xs = (zx0 + b0, zx0 + b1)
        else:
            xs = (zx0 + a0, zx0 + a1) if self.stair.entry < 0 else (zx1 - a1, zx1 - a0)
            ys = (zy1 - b1, zy1 - b0)
        return xs, ys

    def point(self, a, b):
        """Plan point (x, y) of stair coordinates (a, b)."""
        (x, _), (y, _) = self.xs_ys(a, a, b, b)
        return x, y


def stair_steps(stair, rise):
    """Boxes (x0, y0, z0, x1, y1, z1) of a switchback from 0 to ``rise``.

    Flight one climbs from the entry landing to the turning landing along one
    side; flight two climbs back along the other side and arrives at the
    entry landing of the storey above. Each step is a block with a stepped
    soffit ``STAIR_WAIST`` below the tread under it, and the turning landing
    is a slab, so the flights of the storey above leave headroom over these.
    """
    f = StairFrame(stair, rise)
    boxes = []

    def place(a0, a1, b0, b1, z1, z0=0.0):
        xs, ys = f.xs_ys(a0, a1, b0, b1)
        boxes.append((xs[0], ys[0], z0, xs[1], ys[1], z1))

    def underside(top):
        return max(0.0, top - f.riser - dims.STAIR_WAIST)

    for index in range(f.first):
        top = (index + 1) * f.riser
        place(f.landing + index * f.tread_a, f.landing + (index + 1) * f.tread_a, 0, f.flight,
              top, underside(top))
    place(f.length - f.landing, f.length, 0, f.across, f.mid,
          max(0.0, f.mid - dims.STAIR_LANDING_SLAB))
    for index in range(f.second):
        a1 = f.length - f.landing - index * f.tread_b
        top = f.mid + (index + 1) * f.riser
        place(a1 - f.tread_b, a1, f.across - f.flight, f.across, top, underside(top))
    return boxes, f.riser, min(f.tread_a, f.tread_b), f.landing


def stair_railing(stair, rise):
    """Inner handrail line of a switchback, (x, y, z) from its foot to the
    storey above: along flight one's nosings on the well side, across the
    end of the well on the turning landing, and back up flight two."""
    f = StairFrame(stair, rise)
    inner_one, inner_two = f.flight, f.across - f.flight
    turn = f.length - f.landing
    points = [(f.landing + i * f.tread_a, inner_one, (i + 1) * f.riser) for i in range(f.first)]
    points += [(turn, inner_one, f.mid), (turn, inner_two, f.mid)]
    points += [(turn - i * f.tread_b, inner_two, f.mid + (i + 1) * f.riser)
               for i in range(f.second)]
    result = []
    for a, b, z in points:
        x, y = f.point(a, b)
        if not result or (x, y, z) != result[-1]:
            result.append((x, y, z))
    return result


def stair_hole_guard(stair, rise):
    """Guard line (x, y) on the storey a switchback arrives at, where no
    flight continues up: the edge of the slab opening beside the arriving
    flight, from the wall to the well."""
    f = StairFrame(stair, rise)
    return [f.point(f.landing, 0.0), f.point(f.landing, f.across - f.flight)]


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
