# SPDX-License-Identifier: GPL-3.0-or-later
"""Tunnels between basements: through a shared wall, under the open ground
of a block, under a street. Pure Python.

A tunnel is straight, between two basement walls that face each other, on
one storey of both (-1 or -2: a two-storey basement can be joined on either
level, and its own stair is the passage between them). Its floor runs from
one basement's floor to the other's. Each end is a doorway through the
basement's wall into a room.
"""
import math
from dataclasses import dataclass, field

from .city_plan import stream

WIDTH = 2.0           # Clear width of a tunnel.
HEIGHT = 2.2          # Clear height: low, so a tunnel off a first basement stays under the street.
SHELL = .2            # Its floor, walls and roof.
DOOR = (1.6, 2.1)     # Doorway through a basement wall: width, height.
REACH = 26.0          # Longest tunnel under open ground,
REACH_STREET = 34.0   # and under a street.
SLOPE = 1 / 8         # Steepest floor.
COVER = .3            # Least ground over its roof.
CLEAR = .5            # Least distance to another basement or tunnel.
SHARE = .6            # Share of the candidates within a block that are built,
SHARE_STREET = .35    # and of those across a street.
NEAREST = 2           # Candidates a basement offers per storey.


@dataclass
class Site:
    """A building's basement in the city: ``outer`` and ``inner`` are the
    building's footprint and the basement's rooms' rectangle in building
    coordinates (0..width, 0..depth); ``base`` the height of its ground floor."""
    id: str
    center: tuple
    rotation: float
    width: float
    depth: float
    base: float
    under: object
    outer: tuple
    doors: list = field(default_factory=list)    # (storey index, side, centre, width, height)

    def quarter(self):
        turns = self.rotation / (math.pi / 2)
        return round(turns) % 4 if abs(turns - round(turns)) < 1e-6 else None

    def world(self, x, y):
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        x, y = x - self.width / 2, y - self.depth / 2
        return (self.center[0] + x * c - y * s, self.center[1] + x * s + y * c)

    def local(self, x, y):
        c, s = math.cos(self.rotation), math.sin(self.rotation)
        x, y = x - self.center[0], y - self.center[1]
        return (x * c + y * s + self.width / 2, -x * s + y * c + self.depth / 2)

    def box(self, rect):
        corners = [self.world(x, y) for x in (rect[0], rect[2]) for y in (rect[1], rect[3])]
        return (min(p[0] for p in corners), min(p[1] for p in corners),
                max(p[0] for p in corners), max(p[1] for p in corners))

    def floor(self, index):
        return self.base + self.under.z(index)

    def level(self, index):
        return next((lp for lp in self.under.levels if lp.index == index), None)


@dataclass
class Tunnel:
    id: str
    a: str
    b: str
    index: int            # Storey: -1 or -2.
    axis: str             # 'x' or 'y': the direction it runs in the world.
    line: float           # Its centre line's other coordinate.
    start: float          # Along the axis: the outer face of a's wall,
    end: float            # and of b's.
    za: float             # Floor heights at its two ends.
    zb: float
    room_a: str
    room_b: str
    street: bool

    @property
    def length(self):
        return self.end - self.start

    def rect(self, grow=0.0):
        half = WIDTH / 2 + SHELL + grow
        if self.axis == 'x':
            return (self.start - grow, self.line - half, self.end + grow, self.line + half)
        return (self.line - half, self.start - grow, self.line + half, self.end + grow)

    def middle(self):
        mid = (self.start + self.end) / 2
        return (mid, self.line) if self.axis == 'x' else (self.line, mid)


def site_of(lot, params, curb):
    """A lot's basement as a Site, planned as the shell will build it (None:
    no basement). ``params``: its building recipe."""
    from . import basement, layouts
    from .spec import BuildingSpec
    if not params.get('basement'):
        return None
    spec = BuildingSpec(dict(params))
    under = basement.plan(spec, layouts.plan_building(spec), params)
    if under is None:
        return None
    return Site(lot.id, lot.center, lot.rotation, lot.width, lot.depth, curb + lot.level, under,
                spec.levels[0].rect)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _crosses(rect, p, q):
    """Whether segment pq passes through a rectangle (Liang-Barsky)."""
    t0, t1 = 0.0, 1.0
    for d, lo, hi, start in ((q[0] - p[0], rect[0], rect[2], p[0]), (q[1] - p[1], rect[1], rect[3], p[1])):
        if abs(d) < 1e-12:
            if start < lo or start > hi:
                return False
            continue
        a, b = (lo - start) / d, (hi - start) / d
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return False
    return True


def _room_behind(site, index, x, y, axis):
    """The room behind a basement wall where a doorway would stand: the room
    at the world point (a little inside the wall), provided the whole
    doorway and a margin lie in it and it is not the stair."""
    level = site.level(index)
    half = DOOR[0] / 2 + .35
    found = None
    for offset in (-half, 0.0, half):
        px, py = (x, y + offset) if axis == 'x' else (x + offset, y)
        lx, ly = site.local(px, py)
        room = next((r for r in level.rooms if r.rect[0] + 1e-6 < lx < r.rect[2] - 1e-6 and
                     r.rect[1] + 1e-6 < ly < r.rect[3] - 1e-6), None)
        if room is None or room.kind == 'stair' or (found is not None and room is not found):
            return None
        found = room
    return found


def _side(site, x, y):
    """Which wall of the building a world point on its footprint's edge is on,
    and where along it: (side, centre) in building coordinates."""
    lx, ly = site.local(x, y)
    x0, y0, x1, y1 = site.outer
    choices = (('front', abs(ly - y0), lx), ('back', abs(ly - y1), lx),
               ('left', abs(lx - x0), ly), ('right', abs(lx - x1), ly))
    side, _, centre = min(choices, key=lambda c: c[1])
    return side, centre


def candidates(sites, index):
    """Straight tunnels possible on a storey between pairs of basements whose
    walls face each other, nearest first: (gap, a, b, axis, lines)."""
    found = []
    have = [s for s in sites if s.level(index) is not None and s.quarter() is not None]
    boxes = {s.id: (s.box(s.outer), s.box(s.under.rect)) for s in have}
    need = WIDTH + 2 * SHELL + .6
    for i, a in enumerate(have):
        for b in have[i + 1:]:
            oa, ob = boxes[a.id][0], boxes[b.id][0]
            for axis in ('x', 'y'):
                k, m = (0, 1) if axis == 'x' else (1, 0)
                first, second = (a, b) if oa[k] <= ob[k] else (b, a)
                o1, o2 = boxes[first.id][0], boxes[second.id][0]
                gap = o2[k] - o1[k + 2]
                if gap < -1e-6 or gap > REACH_STREET:
                    continue
                i1, i2 = boxes[first.id][1], boxes[second.id][1]
                lo, hi = max(i1[m], i2[m]) + need / 2, min(i1[m + 2], i2[m + 2]) - need / 2
                if hi < lo:
                    continue
                found.append((gap, first, second, axis, (lo, hi)))
    found.sort(key=lambda c: (c[0], c[1].id, c[2].id, c[3]))
    return found


def plan(sites, city, ground=None, avoid=()):
    """Tunnels of a city. ``sites``: its basements (their ``doors`` are
    filled in); ``city``: the plan (roads, seed); ``ground(rect)``: the
    lowest ground over a world box (None: level ground at 0); ``avoid``:
    world boxes nothing may pass under (site pads)."""
    size = city.settings.block_size
    seed = city.settings.seed
    roads = [((r.a[0] * size, r.a[1] * size), (r.b[0] * size, r.b[1] * size), r.tier, (r.a, r.b))
             for r in city.roads]
    rural = {tuple(sorted((tuple(a), tuple(b)))) for a, b in getattr(city, 'rural', ())}
    solid = {s.id: s.box(s.outer) for s in sites}
    built = []
    for index in (-1, -2):
        offered = {}
        for gap, a, b, axis, (lo, hi) in candidates(sites, index):
            if offered.get(a.id, 0) >= NEAREST or offered.get(b.id, 0) >= NEAREST:
                continue
            k = 0 if axis == 'x' else 1
            start, end = solid[a.id][k + 2], solid[b.id][k]
            za, zb = a.floor(index), b.floor(index)
            if abs(za - zb) > max(.02, gap * SLOPE):
                continue
            # The centre line: the first, from the middle outward, with a room behind both walls.
            centre = (lo + hi) / 2
            steps = int((hi - lo) / 2 / .5) + 1
            tunnel = None
            for n in range(steps * 2 + 1):
                line = centre + (.5 * ((n + 1) // 2)) * (1 if n % 2 else -1)
                if not lo - 1e-6 <= line <= hi + 1e-6:
                    continue
                inside = .6
                pa = (start - inside, line) if axis == 'x' else (line, start - inside)
                pb = (end + inside, line) if axis == 'x' else (line, end + inside)
                room_a = _room_behind(a, index, pa[0], pa[1], axis)
                room_b = _room_behind(b, index, pb[0], pb[1], axis)
                if room_a is None or room_b is None:
                    continue
                trial = Tunnel(f'tunnel_{min(a.id, b.id)}__{max(a.id, b.id)}_{-index}', a.id, b.id, index,
                               axis, line, start, end, za, zb, room_a.name, room_b.name, False)
                rect = trial.rect(CLEAR)
                if any(_overlap(rect, box) for ident, box in solid.items() if ident not in (a.id, b.id)):
                    continue
                if any(_overlap(rect, box) for box in avoid):
                    continue
                if any(_overlap(rect, other.rect()) and abs(min(other.za, other.zb) - min(za, zb)) < HEIGHT + 2 * SHELL + .3
                       for other in built):
                    continue
                crossed = [road for road in roads if _crosses(trial.rect(), road[0], road[1])]
                if any(road[2] == 'HIGHWAY' or tuple(sorted(road[3])) in rural for road in crossed):
                    continue
                trial.street = bool(crossed)
                if gap > (REACH_STREET if trial.street else REACH):
                    continue
                if gap > .05:
                    low = ground(trial.rect()) if ground is not None else 0.0
                    if low - (max(za, zb) + HEIGHT + SHELL) < COVER:
                        continue
                tunnel = trial
                break
            if tunnel is None:
                continue
            offered[a.id] = offered.get(a.id, 0) + 1
            offered[b.id] = offered.get(b.id, 0) + 1
            share = SHARE_STREET if tunnel.street else SHARE
            if stream(seed, 'tunnel', tunnel.id).random() >= share:
                continue
            built.append(tunnel)
            for site, along in ((a, start), (b, end)):
                point = (along, tunnel.line) if axis == 'x' else (tunnel.line, along)
                side, centre_local = _side(site, *point)
                site.doors.append((index, side, centre_local, DOOR[0], DOOR[1]))
    return built


def build(mesh, tunnel, material, floor_material):
    """A tunnel's solids, in world coordinates: floor, two walls and roof from
    wall face to wall face, following the floor's slope. Nothing for a
    doorway straight through two walls that touch."""
    from . import solids
    if tunnel.length < .05:
        return
    half = WIDTH / 2

    def piece(c0, c1, bottom, top, mat):
        """Box across the tunnel from c0 to c1, between two heights above the floor line."""
        corners = []
        for z in (bottom, top):
            for along, across, floor in ((tunnel.start, c0, tunnel.za), (tunnel.end, c0, tunnel.zb),
                                         (tunnel.end, c1, tunnel.zb), (tunnel.start, c1, tunnel.za)):
                x, y = (along, across) if tunnel.axis == 'x' else (across, along)
                corners.append((x, y, floor + z))
        if tunnel.axis == 'y':
            # Keep the outline counter-clockwise seen from above.
            corners = [corners[i] for i in (3, 2, 1, 0, 7, 6, 5, 4)]
        solids.hexahedron(mesh, corners, mat)

    line = tunnel.line
    piece(line - half - SHELL, line + half + SHELL, -SHELL, 0.0, floor_material)
    piece(line - half - SHELL, line - half, 0.0, HEIGHT, material)
    piece(line + half, line + half + SHELL, 0.0, HEIGHT, material)
    piece(line - half - SHELL, line + half + SHELL, HEIGHT, HEIGHT + SHELL, floor_material)
