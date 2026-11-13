# SPDX-License-Identifier: GPL-3.0-or-later
"""What the open ground is made of, by district: paving downtown with the
odd strip of dirt or dry grass, patchier paving further out, grass round
apartment blocks, gravel yards in industry, bare dirt round suburban houses
and out in the wasteland. Pure Python: a seeded function of the plan.
"""
import math

from .city_plan import district_at, spread

# Material slots of the ground object, in this order.
MATERIALS = (
    ('City_Ground', (.23, .21, .17, 1)),             # Wasteland dirt.
    ('City_Ground_Concrete', (.44, .43, .40, 1)),    # Broken paving.
    ('City_Ground_Grass', (.33, .34, .20, 1)),       # Dry grass.
    ('City_Ground_Gravel', (.36, .33, .28, 1)),      # Gravel and packed earth.
)
DIRT, CONCRETE, GRASS, GRAVEL = range(4)

# By district style: (share of the ground that is hard, what the hard ground
# is, share of the rest that is grass rather than dirt).
COVER = {
    'DOWNTOWN': (.93, CONCRETE, .5),
    'OLD_TOWN': (.78, CONCRETE, .35),
    'BRUTALIST': (.62, CONCRETE, .55),
    'RESIDENTIAL': (.34, CONCRETE, .65),
    'INDUSTRIAL': (.66, GRAVEL, .15),
    'SUBURBAN': (0.0, CONCRETE, .3),
}
STRIPS = ('DOWNTOWN', 'OLD_TOWN')   # Fully paved districts get planting strips.
STRIP_SHARE = .1                    # Share of their paving taken by strips,
STRIP_WIDTH = 2.5                   # each about this wide
STRIP_LENGTH = 45.0                 # and this long.
FADE_FROM = .5      # Paving thins out from this far out (0 centre, 1 city edge)
FADE_LEFT = .2      # to this share of the district's at the edge.
PATCH = 24.0        # Size of the patches of paving and of grass,
CRUMB = 6.0         # and of the smaller breaks that take over further out.
BORDER = 12.0       # District borders wander by about this much.
CELL = 7.0          # District and distance are looked up once per cell.


def _hash(seed, ix, iy):
    n = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0


def _noise(seed, x, y):
    """Smooth value noise in [0, 1]."""
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a = _hash(seed, ix, iy) * (1 - fx) + _hash(seed, ix + 1, iy) * fx
    b = _hash(seed, ix, iy + 1) * (1 - fx) + _hash(seed, ix + 1, iy + 1) * fx
    return a * (1 - fy) + b * fy


def _smooth(lo, hi, value):
    t = min(1.0, max(0.0, (value - lo) / (hi - lo)))
    return t * t * (3 - 2 * t)


class Cover:
    """``cover.at(x, y)`` is the ground material's slot at a point (plan
    coordinates, metres from the city centre)."""

    def __init__(self, plan):
        self.settings = plan.settings
        self.locations = plan.locations
        self.seed = (plan.settings.seed * 7919 + 13) & 0x7FFFFFFF
        self.size = plan.settings.block_size
        self.reach = plan.settings.radius * plan.settings.block_size * 1.6
        self._cells = {}

    def _cell(self, x, y):
        key = (math.floor(x / CELL), math.floor(y / CELL))
        found = self._cells.get(key)
        if found is None:
            cx, cy = (key[0] + .5) * CELL, (key[1] + .5) * CELL
            out = spread(self.settings, cx, cy)
            style = district_at(self.settings, cx, cy, self.locations).style if out < 1.05 else None
            found = self._cells[key] = (out, style)
        return found

    def at(self, x, y):
        if abs(x) > self.reach or abs(y) > self.reach:
            return DIRT
        seed = self.seed
        # A wandering border between districts.
        bx = x + (_noise(seed + 1, x / 31.0, y / 31.0) - .5) * 2 * BORDER
        by = y + (_noise(seed + 2, x / 31.0, y / 31.0) - .5) * 2 * BORDER
        out, style = self._cell(bx, by)
        if style is None or out >= 1.0:
            return DIRT
        share, hard, grass = COVER[style]
        fade = _smooth(FADE_FROM, 1.0, out)
        share *= 1 - (1 - FADE_LEFT) * fade
        fine = .35 + .4 * fade                       # More broken up further out.
        patch = (1 - fine) * _noise(seed + 3, x / PATCH, y / PATCH) + \
            fine * _noise(seed + 4, x / CRUMB, y / CRUMB)
        # The blend of two noises bunches round .5: spread it back out.
        patch = min(1.0, max(0.0, .5 + (patch - .5) * 1.9))
        if patch < share:
            if style in STRIPS:
                # Long thin strips, along x or y by block.
                turned = _hash(seed + 5, math.floor(x / self.size), math.floor(y / self.size)) < .5
                u, v = (y, x) if turned else (x, y)
                if _noise(seed + 6, u / STRIP_WIDTH, v / STRIP_LENGTH) < STRIP_SHARE * 2.4 and \
                        _hash(seed + 7, math.floor(u / STRIP_WIDTH), math.floor(v / STRIP_LENGTH)) < .42:
                    return GRASS if _noise(seed + 8, x / 40.0, y / 40.0) < grass else DIRT
            return hard
        return GRASS if _noise(seed + 9, x / PATCH, y / PATCH) < grass else DIRT

    def faces(self, vertices, faces):
        """Slot per face of a ground mesh, by its middle."""
        result = []
        at = self.at
        for face in faces:
            count = len(face)
            x = sum(vertices[i][0] for i in face) / count
            y = sum(vertices[i][1] for i in face) / count
            result.append(at(x, y))
        return result

    def paved(self, x, y):
        """True where the ground is hard (a lot there gets a paved pad)."""
        return self.at(x, y) in (CONCRETE, GRAVEL)
