# SPDX-License-Identifier: GPL-3.0-or-later
"""Sewers under the streets. Pure Python.

Trunks run under arterials and collectors, laterals under a seeded share of
the local streets, grown out from the trunks so every lateral reaches one.
Each sewer runs straight under a street's centre line from one junction to
the next, at a fixed depth under the road, so it follows the street's grade.
A chamber stands under every junction a sewer reaches and the sewers enter
it through doorways in its walls. A lateral falls to the trunk's depth over
its last metres into a trunk chamber, so the network can be walked end to
end (a lateral at a crouch).

A chamber has a manhole where a shaft from its roof comes up wholly on the
street's paving (not on a curb): the shaft rises to a rim just proud of the
street, whose mesh (and the ground under it) is cut there. A seeded share
is open; the lids are the game's.

A seeded share of sections is collapsed: a plug fills the middle. None is
chosen that would split the network. Breaches join the sewers to the
buildings: a short passage from a second basement storey to the trunk
passing in front of it, through a gap in the trunk's wall.
"""
import math
from dataclasses import dataclass, field

from .city_plan import stream

SHELL = .25                # Floor, walls and roof of sewers and chambers.
TRUNK = (3.0, 2.6, 7.0)    # Clear width, clear height, floor depth under the street.
LATERAL = (1.6, 1.6, 5.5)
CHAMBER = {'trunk': 5.0, 'lateral': 2.8}   # Clear size of a chamber (square).
SLOPE = 1 / 8              # A lateral's fall into a trunk chamber.
STEP = 8.0                 # Longest straight piece along a sewer.
SHAFT = .9                 # A manhole's clear opening,
SHAFT_WALL = .15           # its walls,
RIM = .02                  # and how far its rim stands above the street.
OPEN = .25                 # Share of manholes that start open.
LATERAL_SHARE = .4         # Share of local streets with a lateral.
COLLAPSE = .12             # Share of sections collapsed.
PLUG = 3.0                 # Length of a collapse.
BREACH_SHARE = .5          # Share of breach candidates built,
BREACH_REACH = 12.0        # and the longest breach.
CLEAR = .5                 # Least distance to a basement.
TRUNK_TIERS = ('ARTERIAL', 'COLLECTOR')
PAVING = (0, 1)            # Street mesh materials a manhole may cut: road, footway.


@dataclass
class Chamber:
    id: str
    node: tuple
    x: float
    y: float
    kind: str
    floor: float
    doors: list = field(default_factory=list)    # (side, width, height); side '-x', '+x', '-y', '+y'.
    manhole: object = None

    @property
    def size(self):
        return CHAMBER[self.kind]

    @property
    def height(self):
        return (TRUNK if self.kind == 'trunk' else LATERAL)[1]

    @property
    def top(self):
        """Top of its roof."""
        return self.floor + self.height + SHELL

    def rect(self, grow=0.0):
        half = self.size / 2 + SHELL + grow
        return (self.x - half, self.y - half, self.x + half, self.y + half)


@dataclass
class Breach:
    id: str
    site: str
    room: str
    sewer: str
    tunnel: object        # A tunnels.Tunnel for the passage (``b`` is the sewer).
    along: float          # Where it meets the sewer, along the sewer's axis,
    side: int             # and on which side (+1: the side of greater ``line``).


@dataclass
class Sewer:
    id: str
    a: str                # Chamber ids, in the direction of the axis.
    b: str
    kind: str
    axis: str
    line: float
    start: float          # Along the axis: the outer faces of a's wall and b's.
    end: float
    sections: list        # [(along, floor)] from start to end.
    plug: tuple = None    # (from, to) along the axis: collapsed there.
    breaches: list = field(default_factory=list)

    @property
    def width(self):
        return (TRUNK if self.kind == 'trunk' else LATERAL)[0]

    @property
    def height(self):
        return (TRUNK if self.kind == 'trunk' else LATERAL)[1]

    @property
    def length(self):
        return self.end - self.start

    def rect(self, grow=0.0):
        half = self.width / 2 + SHELL + grow
        if self.axis == 'x':
            return (self.start - grow, self.line - half, self.end + grow, self.line + half)
        return (self.line - half, self.start - grow, self.line + half, self.end + grow)

    def floor_at(self, along):
        points = self.sections
        if along <= points[0][0]:
            return points[0][1]
        for (a0, f0), (a1, f1) in zip(points, points[1:]):
            if along <= a1:
                return f0 + (f1 - f0) * (along - a0) / max(1e-9, a1 - a0)
        return points[-1][1]

    def point(self, along, across=0.0):
        return (along, self.line + across) if self.axis == 'x' else (self.line + across, along)

    def span(self):
        """Lowest floor and highest roof top."""
        floors = [f for _, f in self.sections]
        return min(floors) - SHELL, max(floors) + self.height + SHELL


@dataclass
class Manhole:
    id: str
    chamber: str
    x: float
    y: float
    rim: float            # Height of its rim's top.
    base: float           # Top of the chamber's roof, where its shaft stands.
    open: bool

    @property
    def outer(self):
        return SHAFT + 2 * SHAFT_WALL

    def rect(self, grow=0.0):
        half = self.outer / 2 + grow
        return (self.x - half, self.y - half, self.x + half, self.y + half)


@dataclass
class Network:
    chambers: dict
    sewers: list
    manholes: list
    breaches: list = field(default_factory=list)

    def solids(self):
        """World boxes with their height ranges that nothing else may enter:
        (rect, low, high)."""
        found = []
        for chamber in self.chambers.values():
            found.append((chamber.rect(), chamber.floor - SHELL, chamber.top))
        for sewer in self.sewers:
            found.append((sewer.rect(), *sewer.span()))
        for manhole in self.manholes:
            found.append((manhole.rect(), manhole.base, manhole.rim))
        return found

    def openings(self):
        """Where the street and the ground are cut: (centre x, centre y, width,
        depth, rotation), as ``cutouts.cut`` takes them."""
        return [(m.x, m.y, m.outer, m.outer, 0.0) for m in self.manholes]


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _key(node):
    return f'{node[0]}_{node[1]}'


def _network_edges(city):
    """Street edges with a sewer: {edge: kind}."""
    seed = city.settings.seed
    rural = {tuple(sorted((tuple(a), tuple(b)))) for a, b in getattr(city, 'rural', ())}
    edges, local = {}, []
    for road in city.roads:
        a, b = tuple(road.a), tuple(road.b)
        if road.tier == 'HIGHWAY' or abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            continue
        key = tuple(sorted((a, b)))
        if key in rural:
            continue
        if road.tier in TRUNK_TIERS:
            edges[key] = 'trunk'
        else:
            local.append(key)
    # Laterals grow out from the trunks: a local street gets one, by its seed, once a sewer reaches either end.
    local.sort(key=lambda k: stream(seed, 'lateral-order', k).random())
    chosen = {k for k in local if stream(seed, 'lateral', k).random() < LATERAL_SHARE}
    reached = {n for k in edges for n in k}
    grown = True
    while grown:
        grown = False
        for key in local:
            if key in chosen and key not in edges and (key[0] in reached or key[1] in reached):
                edges[key] = 'lateral'
                reached.update(key)
                grown = True
    return edges


def _sections(start, end, line, axis, depth_at, surface, floor_a, floor_b, ramp_a, ramp_b, breaks=()):
    """Floor heights along a sewer: every STEP, at the ends of its ramps and at
    ``breaks``; the ends are the chambers' floors."""
    marks = {start, end}
    length = end - start
    count = max(1, math.ceil(length / STEP))
    marks.update(start + length * k / count for k in range(1, count))
    run = (TRUNK[2] - LATERAL[2]) / SLOPE
    if ramp_a and length > run:
        marks.add(start + run)
    if ramp_b and length > run:
        marks.add(end - run)
    marks.update(b for b in breaks if start < b < end)
    points = []
    for along in sorted(marks):
        if along == start:
            points.append((along, floor_a))
        elif along == end:
            points.append((along, floor_b))
        else:
            x, y = (along, line) if axis == 'x' else (line, along)
            depth = depth_at(along)
            points.append((along, surface(x, y) - depth))
    return _clean(points)


def _clean(points):
    out = []
    for along, floor in points:
        if out and along - out[-1][0] < 1e-6:
            continue
        out.append((along, floor))
    return out


class _StreetIndex:
    """The street mesh's faces by grid cell, for manholes."""

    CELL = 4.0

    def __init__(self, vertices, faces, materials):
        self.vertices, self.faces, self.materials = vertices, faces, materials
        self.grid = {}
        for number, face in enumerate(faces):
            xs = [vertices[i][0] for i in face]
            ys = [vertices[i][1] for i in face]
            for i in range(math.floor(min(xs) / self.CELL), math.floor(max(xs) / self.CELL) + 1):
                for j in range(math.floor(min(ys) / self.CELL), math.floor(max(ys) / self.CELL) + 1):
                    self.grid.setdefault((i, j), []).append(number)

    def near(self, rect):
        found = set()
        for i in range(math.floor(rect[0] / self.CELL), math.floor(rect[2] / self.CELL) + 1):
            for j in range(math.floor(rect[1] / self.CELL), math.floor(rect[3] / self.CELL) + 1):
                found.update(self.grid.get((i, j), ()))
        return sorted(found)

    def paved(self, rect):
        """The highest street height over a square if the street mesh covers
        all of it with road or footway and no curb or shoulder touches it,
        else None."""
        area, top = 0.0, None
        want = (rect[2] - rect[0]) * (rect[3] - rect[1])
        for number in self.near(rect):
            polygon = [self.vertices[i] for i in self.faces[number]]
            part = _clip_rect(polygon, rect)
            if len(part) < 3:
                continue
            piece = _area(part)
            if piece < 1e-6:
                # A vertical face (a curb's riser) touching the square.
                if self.materials[number] not in PAVING:
                    return None
                continue
            if self.materials[number] not in PAVING:
                return None
            area += piece
            high = max(z for _, _, z in part)
            top = high if top is None else max(top, high)
        if top is None or area < want - 1e-3 or area > want * 1.02:
            # Not wholly covered, or covered twice (a bridge over another street).
            return None
        return top


def _clip_rect(polygon, rect):
    points = [(x, y, z) for x, y, z in polygon]
    for axis, limit, keep_below in ((0, rect[0], False), (0, rect[2], True), (1, rect[1], False), (1, rect[3], True)):
        result = []
        for i in range(len(points)):
            a, b = points[i], points[(i + 1) % len(points)]
            da, db = a[axis] - limit, b[axis] - limit
            ina = da <= 0 if keep_below else da >= 0
            inb = db <= 0 if keep_below else db >= 0
            if ina:
                result.append(a)
            if ina != inb:
                t = da / (da - db)
                result.append(tuple(a[k] + (b[k] - a[k]) * t for k in range(3)))
        points = result
        if len(points) < 3:
            return []
    return points


def _area(polygon):
    return abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] -
                   polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                   for i in range(len(polygon)))) / 2


def _connected(chambers, sewers, without=None):
    """Whether removing ``without`` leaves its two chambers joined."""
    links = {}
    for sewer in sewers:
        if sewer is without or sewer.plug is not None:
            continue
        links.setdefault(sewer.a, []).append(sewer.b)
        links.setdefault(sewer.b, []).append(sewer.a)
    seen, todo = {without.a}, [without.a]
    while todo:
        for other in links.get(todo.pop(), ()):
            if other == without.b:
                return True
            if other not in seen:
                seen.add(other)
                todo.append(other)
    return False


def plan(city, surface=None, sites=(), street=None, avoid=()):
    """The sewer network of a city, before breaches. ``surface(x, y)``: road
    level (None: flat at 0); ``sites``: basements to keep clear of;
    ``street``: the street mesh as (vertices, faces, materials) in the same
    coordinates, for manholes (None: none); ``avoid``: world boxes nothing may
    pass under (site pads)."""
    size = city.settings.block_size
    seed = city.settings.seed
    level = surface or (lambda x, y: 0.0)
    edges = _network_edges(city)
    boxes = [(site.box(site.outer), site.base + site.under.depth, site.base) for site in sites]

    def blocked(rect, low, high):
        if any(_overlap(rect, box) for box in avoid):
            return True
        return any(_overlap(rect, box) and low < top + CLEAR and bottom - CLEAR < high
                   for box, bottom, top in boxes)

    # Chambers: under every junction a sewer reaches, trunk-sized where a trunk does.
    kinds = {}
    for key, kind in edges.items():
        for node in key:
            if kinds.get(node) != 'trunk':
                kinds[node] = kind
    chambers = {}
    for node, kind in sorted(kinds.items()):
        x, y = node[0] * size, node[1] * size
        depth = (TRUNK if kind == 'trunk' else LATERAL)[2]
        chamber = Chamber(f'sewer_c_{_key(node)}', node, x, y, kind, level(x, y) - depth)
        if blocked(chamber.rect(CLEAR), chamber.floor - SHELL, chamber.top):
            continue
        chambers[node] = chamber
    sewers = []
    for (a, b), kind in sorted(edges.items()):
        if a not in chambers or b not in chambers:
            continue
        ca, cb = chambers[a], chambers[b]
        axis = 'x' if a[1] == b[1] else 'y'
        k = 0 if axis == 'x' else 1
        if (a[k] > b[k]):
            ca, cb = cb, ca
        line = ca.y if axis == 'x' else ca.x
        start = (ca.x if axis == 'x' else ca.y) + ca.size / 2 + SHELL
        end = (cb.x if axis == 'x' else cb.y) - cb.size / 2 - SHELL
        if end - start < 2.0:
            continue
        lateral_into_a = kind == 'lateral' and ca.kind == 'trunk'
        lateral_into_b = kind == 'lateral' and cb.kind == 'trunk'
        own = (TRUNK if kind == 'trunk' else LATERAL)[2]
        run = (TRUNK[2] - LATERAL[2]) / SLOPE

        def depth_at(along, start=start, end=end, own=own, ra=lateral_into_a, rb=lateral_into_b):
            depth = own
            for ramp, distance in ((ra, along - start), (rb, end - along)):
                if ramp:
                    depth = max(depth, TRUNK[2] - (TRUNK[2] - LATERAL[2]) * min(1.0, distance / run))
            return depth

        sections = _sections(start, end, line, axis, depth_at, level, ca.floor, cb.floor,
                             lateral_into_a, lateral_into_b)
        sewer = Sewer(f'sewer_{_key(ca.node)}__{_key(cb.node)}', ca.id, cb.id, kind, axis, line,
                      start, end, sections)
        if blocked(sewer.rect(CLEAR), *sewer.span()):
            continue
        sewers.append(sewer)
    # Chambers no sewer reaches any more are not built.
    used = {s.a for s in sewers} | {s.b for s in sewers}
    chambers = {c.id: c for c in chambers.values() if c.id in used}
    for sewer in sewers:
        ca, cb = chambers[sewer.a], chambers[sewer.b]
        sign = '+x' if sewer.axis == 'x' else '+y'
        ca.doors.append((sign, sewer.width, sewer.height))
        cb.doors.append((sign.replace('+', '-'), sewer.width, sewer.height))
    # Collapses: a plug in the middle of a seeded share of sections, never one the network needs.
    for sewer in sorted(sewers, key=lambda s: stream(seed, 'collapse-order', s.id).random()):
        if sewer.length < PLUG + 6.0 or stream(seed, 'collapse', sewer.id).random() >= COLLAPSE:
            continue
        if not _connected(chambers, sewers, sewer):
            continue
        middle = (sewer.start + sewer.end) / 2
        sewer.plug = (middle - PLUG / 2, middle + PLUG / 2)
        sewer.sections = _clean(sorted(sewer.sections + [(a, sewer.floor_at(a)) for a in sewer.plug
                                                         if all(abs(a - s) > 1e-6 for s, _ in sewer.sections)]))
    # Manholes: one per chamber, where its shaft comes up wholly on the paving.
    manholes = []
    index = _StreetIndex(*street) if street is not None else None
    for chamber in sorted(chambers.values(), key=lambda c: c.id):
        reach = chamber.size / 2 - SHAFT / 2 - .05
        half = SHAFT / 2 + SHAFT_WALL
        offsets = [(0.0, 0.0)]
        for step in (.5, 1.0, 1.5, 2.0):
            if step > reach + 1e-6:
                break
            for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)):
                offsets.append((dx * step, dy * step))
        for dx, dy in offsets:
            x, y = chamber.x + dx, chamber.y + dy
            rect = (x - half, y - half, x + half, y + half)
            if index is not None:
                top = index.paved(rect)
                if top is None:
                    continue
            else:
                top = level(x, y)
            ident = f'manhole_{_key(chamber.node)}'
            manhole = Manhole(ident, chamber.id, x, y, top + RIM, chamber.top,
                              stream(seed, 'manhole', ident).random() < OPEN)
            chamber.manhole = manhole
            manholes.append(manhole)
            break
    return Network(chambers, sewers, manholes)


def breach(network, sites, seed, avoid=()):
    """Passages from second basement storeys to the trunks in front of them.
    Fills in the sites' ``doors`` and the network's ``breaches``. ``avoid``:
    other solids as (rect, low, high), the tunnels' among them."""
    from . import tunnels
    taken = set()
    have = [s for s in sites if s.level(-2) is not None and s.quarter() is not None]
    boxes = {s.id: s.box(s.outer) for s in sites}
    per_sewer = {}
    found = []
    for sewer in sorted(network.sewers, key=lambda s: s.id):
        if sewer.kind != 'trunk':
            continue
        m = 0 if sewer.axis == 'x' else 1     # Along the sewer.
        n = 1 - m                              # Across it.
        outer = sewer.width / 2 + SHELL
        for site in have:
            if site.id in taken:
                continue
            box = boxes[site.id]
            if box[n] > sewer.line:
                side, face, wall = 1, box[n], sewer.line + outer
            elif box[n + 2] < sewer.line:
                side, face, wall = -1, box[n + 2], sewer.line - outer
            else:
                continue
            gap = (face - wall) * side
            if gap < .5 or gap > BREACH_REACH:
                continue
            inner = site.box(site.under.rect)
            need = tunnels.WIDTH / 2 + tunnels.SHELL + .4
            lo = max(inner[m] + need, sewer.start + 1.5 + need)
            hi = min(inner[m + 2] - need, sewer.end - 1.5 - need)
            if sewer.plug is not None:
                # Keep to one side of a plug: the longer.
                if sewer.plug[0] - lo >= hi - sewer.plug[1]:
                    hi = min(hi, sewer.plug[0] - need)
                else:
                    lo = max(lo, sewer.plug[1] + need)
            if hi < lo:
                continue
            centre = (lo + hi) / 2
            axis = 'y' if sewer.axis == 'x' else 'x'
            choice = None
            for k in range(int((hi - lo) / .5) + 1):
                along = centre + .5 * ((k + 1) // 2) * (1 if k % 2 else -1)
                if not lo - 1e-6 <= along <= hi + 1e-6:
                    continue
                inside = .6
                probe = face + side * inside
                px, py = (along, probe) if sewer.axis == 'x' else (probe, along)
                room = tunnels._room_behind(site, -2, px, py, axis)
                if room is None:
                    continue
                za = sewer.floor_at(along)
                zb = site.floor(-2)
                if abs(za - zb) > gap * tunnels.SLOPE:
                    continue
                if side > 0:
                    start, end, z0, z1 = wall, face, za, zb
                else:
                    start, end, z0, z1 = face, wall, zb, za
                ident = f'breach_{site.id}__{sewer.id}'
                passage = tunnels.Tunnel(ident, site.id, sewer.id, -2, axis, along, start, end, z0, z1,
                                         room.name, '', True)
                rect = passage.rect(tunnels.CLEAR)
                low = min(z0, z1) - tunnels.SHELL
                high = max(z0, z1) + tunnels.HEIGHT + tunnels.SHELL
                if any(_overlap(rect, b) for ident2, b in boxes.items() if ident2 != site.id):
                    continue
                if any(_overlap(rect, r) and lo3 < high and low < hi3 for r, lo3, hi3 in avoid):
                    continue
                if any(_overlap(rect, other.tunnel.rect()) for other in found):
                    continue
                choice = (passage, room, along, za)
                break
            if choice is None:
                continue
            if stream(seed, 'breach', choice[0].id).random() >= BREACH_SHARE:
                continue
            if per_sewer.get(sewer.id, 0) >= 2:
                continue
            passage, room, along, za = choice
            per_sewer[sewer.id] = per_sewer.get(sewer.id, 0) + 1
            taken.add(site.id)
            made = Breach(passage.id, site.id, room.name, sewer.id, passage, along, side)
            found.append(made)
            sewer.breaches.append(made)
            # The trunk is level across the gap in its wall, so the passage meets it flush.
            half = tunnels.WIDTH / 2
            kept = [(a, f) for a, f in sewer.sections if not along - half - 1e-6 <= a <= along + half + 1e-6]
            sewer.sections = sorted(kept + [(along - half, za), (along + half, za)])
            point = (along, face) if sewer.axis == 'x' else (face, along)
            door_side, door_centre = tunnels._side(site, *point)
            site.doors.append((-2, door_side, door_centre, tunnels.DOOR[0], tunnels.DOOR[1]))
    network.breaches = found
    return found


def build(mesh, network, material, floor_material, plug_material=None):
    """The network's solids in world coordinates."""
    from . import tunnels
    plug_material = floor_material if plug_material is None else plug_material
    for chamber in network.chambers.values():
        _chamber(mesh, chamber, material, floor_material)
    for sewer in network.sewers:
        _sewer(mesh, sewer, material, floor_material, plug_material)
    for item in network.breaches:
        tunnels.build(mesh, item.tunnel, material, floor_material)
    for manhole in network.manholes:
        _shaft(mesh, manhole, material)


def _chamber(mesh, chamber, material, floor_material):
    from . import solids
    h, s = chamber.size / 2, SHELL
    x0, y0, x1, y1 = chamber.x - h - s, chamber.y - h - s, chamber.x + h + s, chamber.y + h + s
    f, top = chamber.floor, chamber.floor + chamber.height
    solids.box(mesh, x0, y0, f - s, x1, y1, f, floor_material)
    # Walls: south and north full width, west and east between them.
    walls = {'-y': ((x0, y0), (1.0, 0.0), x1 - x0, h + s),
             '+y': ((x1, y1), (-1.0, 0.0), x1 - x0, h + s),
             '-x': ((x0, chamber.y + h), (0.0, -1.0), 2 * h, h),
             '+x': ((x1, chamber.y - h), (0.0, 1.0), 2 * h, h)}
    boxes = {'-y': (x0, y0, x1, y0 + s), '+y': (x0, y1 - s, x1, y1),
             '-x': (x0, chamber.y - h, x0 + s, chamber.y + h), '+x': (x1 - s, chamber.y - h, x1, chamber.y + h)}
    for side, (origin, direction, length, centre) in walls.items():
        doors = [(w, d) for door_side, w, d in chamber.doors if door_side == side]
        if doors:
            width, height = max(doors)
            opening = solids.Opening.rect(centre - width / 2, centre + width / 2, f, f + height,
                                          floor_material, 'door')
            solids.wall_solid(mesh, origin, direction, s, 0.0, length, f, [(0.0, top), (length, top)],
                              [opening], material)
        else:
            b = boxes[side]
            solids.box(mesh, b[0], b[1], f, b[2], b[3], top, material)
    # The roof, round the shaft's opening if it has a manhole.
    m = chamber.manhole
    if m is None:
        solids.box(mesh, x0, y0, top, x1, y1, top + s, floor_material)
        return
    hx0, hy0, hx1, hy1 = m.x - SHAFT / 2, m.y - SHAFT / 2, m.x + SHAFT / 2, m.y + SHAFT / 2
    solids.box(mesh, x0, y0, top, x1, hy0, top + s, floor_material)
    solids.box(mesh, x0, hy1, top, x1, y1, top + s, floor_material)
    solids.box(mesh, x0, hy0, top, hx0, hy1, top + s, floor_material)
    solids.box(mesh, hx1, hy0, top, x1, hy1, top + s, floor_material)


def _shaft(mesh, manhole, material):
    from . import solids
    c, t = SHAFT / 2, SHAFT_WALL
    x, y, z0, z1 = manhole.x, manhole.y, manhole.base, manhole.rim
    if z1 - z0 < .05:
        return
    solids.box(mesh, x - c - t, y - c - t, z0, x + c + t, y - c, z1, material)
    solids.box(mesh, x - c - t, y + c, z0, x + c + t, y + c + t, z1, material)
    solids.box(mesh, x - c - t, y - c, z0, x - c, y + c, z1, material)
    solids.box(mesh, x + c, y - c, z0, x + c + t, y + c, z1, material)


def _sewer(mesh, sewer, material, floor_material, plug_material):
    from . import solids, tunnels
    half, s, height = sewer.width / 2, SHELL, sewer.height
    line = sewer.line
    gaps = [(b.along - tunnels.WIDTH / 2, b.along + tunnels.WIDTH / 2, b.side) for b in sewer.breaches]

    def piece(a0, a1, c0, c1, bottom, top, mat):
        f0, f1 = sewer.floor_at(a0), sewer.floor_at(a1)
        corners = []
        for z in (bottom, top):
            for along, across, floor in ((a0, c0, f0), (a1, c0, f1), (a1, c1, f1), (a0, c1, f0)):
                x, y = (along, across) if sewer.axis == 'x' else (across, along)
                corners.append((x, y, floor + z))
        if sewer.axis == 'y':
            corners = [corners[i] for i in (3, 2, 1, 0, 7, 6, 5, 4)]
        solids.hexahedron(mesh, corners, mat)

    for (a0, _), (a1, _) in zip(sewer.sections, sewer.sections[1:]):
        if a1 - a0 < 1e-4:
            continue
        piece(a0, a1, line - half - s, line + half + s, -s, 0.0, floor_material)
        for sign, c0, c1 in ((-1, line - half - s, line - half), (1, line + half, line + half + s)):
            gap = any(g0 - 1e-6 <= a0 and a1 <= g1 + 1e-6 and side == sign for g0, g1, side in gaps)
            # A breach leaves a lintel over the passage.
            piece(a0, a1, c0, c1, tunnels.HEIGHT if gap else 0.0, height, material)
        piece(a0, a1, line - half - s, line + half + s, height, height + s, floor_material)
        if sewer.plug is not None and sewer.plug[0] - 1e-6 <= a0 and a1 <= sewer.plug[1] + 1e-6:
            piece(a0, a1, line - half, line + half, 0.0, height, plug_material)
