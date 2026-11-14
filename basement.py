# SPDX-License-Identifier: GPL-3.0-or-later
"""Basements: one or two storeys under a building, reached by its own stair
carried on down. Pure Python.

A basement fills the building's interior rectangle. Its storeys are
``layouts.LevelPlan``s with indices -1 (under the ground floor) and -2; the
stair stands where the ground floor's does, so the flights stack as on the
storeys above. Nothing here is damaged: the building over it may be.
"""
import random
from dataclasses import dataclass, field

from . import dims, layouts

HEIGHT = 3.2          # Floor to floor.
HALL = 2.4            # Width of the hall the stair lets onto.
ROOM = 5.0            # Target width of a cellar room; a large basement's are wider.
ROOM_LARGE = 11.0
LEAST = 2.2           # Narrowest strip made into a room of its own.
LAYERS = {-1: 'basement_1', -2: 'basement_2'}


@dataclass
class Basement:
    levels: list                      # LevelPlans, nearest the ground first.
    rect: tuple                       # Interior rectangle, as the ground floor's.
    height: float = HEIGHT
    notes: list = field(default_factory=list)

    def z(self, index):
        """Floor height of storey ``index`` (-1, -2)."""
        return index * self.height

    @property
    def ceiling(self):
        """Clear height of a storey."""
        return self.height - dims.SLAB

    @property
    def depth(self):
        """Underside of the lowest floor slab."""
        return -len(self.levels) * self.height - dims.SLAB

    @property
    def ground_hole(self):
        """Opening in the ground floor over the stair down."""
        return layouts.stair_hole(self.levels[0].stair, self.height)


def _frame(rect, stair_rect, axis, entry):
    """Maps between plan coordinates and a frame where the stair's flights
    run along +v from its entry at the low end: returns (to, back) for
    rectangles."""
    def to(r):
        x0, y0, x1, y1 = r
        if axis == 'x':
            x0, y0, x1, y1 = y0, x0, y1, x1
        if entry > 0:
            y0, y1 = -y1, -y0
        return (x0, y0, x1, y1)

    def back(r):
        x0, y0, x1, y1 = r
        if entry > 0:
            y0, y1 = -y1, -y0
        if axis == 'x':
            x0, y0, x1, y1 = y0, x0, y1, x1
        return (x0, y0, x1, y1)
    return to, back


def _split(lo, hi, target):
    count = max(1, round((hi - lo) / target))
    return [(lo + (hi - lo) * k / count, lo + (hi - lo) * (k + 1) / count) for k in range(count)]


def _layout(rect, stair, index, large, rng):
    """A storey's rooms: a hall across the stair's entry, cellar rooms off it."""
    axis, entry = stair.stair[0], stair.stair[1]
    to, back = _frame(rect, stair.rect, axis, entry)
    x0, y0, x1, y1 = to(rect)
    sx0, sy0, sx1, sy1 = to(stair.rect)
    tiling = layouts.Tiling(rect, index)
    target = ROOM_LARGE if large else ROOM
    count = [0]

    def add(kind, r, parent='hall', **extra):
        if r[2] - r[0] < .3 or r[3] - r[1] < .3:
            return
        count[0] += 1
        tiling.add(f'{kind}{count[0]}' if kind != 'hall' else f'hall{count[0]}', kind, back(r),
                   None if kind == 'hall' else parent, **extra)

    def hall(r):
        if r[2] - r[0] < .3 or r[3] - r[1] < .3:
            return
        count[0] += 1
        tiling.add(f'hall{count[0]}', 'hall', back(r), None, group='hall')

    front = sy0 - y0
    if front < 2.0:
        return None
    wide = HALL if front - HALL >= LEAST else front
    hall((x0, sy0 - wide, x1, sy0))                           # count 1: 'hall1', the parent of the rest.
    first = tiling.rooms[0].name.rsplit('_', 1)[0]
    kinds = ('plant', 'storage', 'storage') if large else ('storage', 'storage', 'laundry')
    if front - wide >= LEAST:
        for a, b in _split(x0, x1, target * rng.uniform(.85, 1.2)):
            add(rng.choice(kinds), (a, y0, b, sy0 - wide), first)
    # Beside the stair, and behind it when it stands clear of the back wall.
    for a, b in ((x0, sx0), (sx1, x1)):
        if b - a < .3:
            continue
        if b - a < LEAST:
            hall((a, sy0, b, y1))
            continue
        for c, d in _split(sy0, y1, target * rng.uniform(.85, 1.2)):
            add(rng.choice(kinds), (a, c, b, d), first)
    hall((sx0, sy1, sx1, y1))
    tiling.add('stair', 'stair', stair.rect, None, wall=stair.wall, stair=stair.stair)
    return tiling.level()


def plan(spec, building_plan, params):
    """The basement of a planned building (``params['basement']`` storeys), or
    None: no stair on the ground floor to carry down, a compound footprint,
    or a layout that leaves a room cut off."""
    storeys = int(params.get('basement', 0) or 0)
    if storeys <= 0 or getattr(spec, 'compound', False) or not building_plan.levels:
        return None
    ground = building_plan.levels[0]
    stair = next((room for room in ground.rooms if room.kind == 'stair'), None)
    if ground.index != 0 or ground.stair is None or stair is None or not stair.stair:
        return None
    rect = spec.interior_rect(0)
    if any(abs(a - b) > 1e-6 for a, b in zip(rect, ground.rect)):
        return None
    rng = random.Random((spec.seed * 2654435761) ^ 0xBA5E)
    large = bool(params.get('basement_large'))
    levels = []
    for index in range(-1, -min(storeys, 2) - 1, -1):
        level = _layout(rect, stair, index, large, rng)
        if level is None:
            break
        root = next(room.name for room in level.rooms if room.kind == 'stair')
        layouts.resolve(level, [root])
        layouts.finish_level(level)
        if level.issues or level.stair is None or \
                layouts.reachable(level) != {room.name for room in level.rooms}:
            break
        levels.append(level)
    if not levels:
        return None
    for upper, lower in zip(levels, levels[1:]):
        upper.holes = [layouts.stair_hole(lower.stair, HEIGHT)]
    return Basement(levels, rect)
