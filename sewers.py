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
CHAMFERS = {'trunk': (.4, .7), 'lateral': (.4, .4)}   # Lower and upper chamfers of the octagonal section.
TRENCH = {'trunk': (.6, .3), 'lateral': (.3, .12)}    # Width and depth of the trench along the floor,
TRENCH_END = .5            # which stops this far short of a chamber.
SHAFT = .9                 # A manhole's clear opening (an octagon, across the flats),
SHAFT_WALL = .15           # its walls,
RIM = .02                  # and how far its rim stands above the street.
OPEN = .25                 # Share of manholes that start open.
LATERAL_SHARE = .4         # Share of local streets with a lateral.
COLLAPSE = .12             # Share of sections collapsed.
PLUG = 3.0                 # Length of a collapse.
BREACH_SHARE = .5          # Share of breach candidates built,
BREACH_REACH = 12.0        # and the longest breach.
DROP_STYLES = ('OLD_TOWN', 'BRUTALIST')   # Their single basement storeys drop into the sewers by a ladder.
DROP = (1.2, .2)           # A drop's shaft: clear depth across the passage, walls.
OPENING = {'trunk': 2.2, 'lateral': 1.2}  # Height of a breach's gap in a sewer's wall.
CLEAR = .5                 # Least distance to a basement.
TRUNK_TIERS = ('ARTERIAL', 'COLLECTOR')
PAVING = (0, 1)            # Street mesh materials a manhole may cut: road, footway.
LINK_KINDS = (('rooms', .4), ('room', .35), ('none', .25))   # How a sewer ending by a station's hall reaches it.
LINK_ROOM = (3.0, 3.0, 2.6)  # A service room on the way: clear length (along the link), width, height.
LINK_SHELL = .25
LINK_CORRIDOR = 2.0        # Between two service rooms.
LINK_DOOR = (1.2, 2.1)     # A service doorway.


@dataclass
class Chamber:
    id: str
    node: tuple
    x: float
    y: float
    kind: str
    floor: float
    doors: list = field(default_factory=list)    # (side, kind); side '-x', '+x', '-y', '+y'.
    manhole: object = None
    extent: tuple = None  # Half sizes (x, y) when not a square of its kind's size.
    hall: bool = False    # (Before v0.32: a subway hall standing in for it. Always False now.)
    station: str = ''     # The subway station whose hall it ends beside, if any.

    def half(self, axis):
        if self.extent is not None:
            return self.extent[0 if axis == 'x' else 1]
        return self.size / 2

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
        hx, hy = self.half('x') + SHELL + grow, self.half('y') + SHELL + grow
        return (self.x - hx, self.y - hy, self.x + hx, self.y + hy)


@dataclass
class Breach:
    id: str
    site: str
    room: str
    sewer: str
    tunnel: object        # A tunnels.Tunnel for the passage (``b`` is the sewer).
    along: float          # Where it meets the sewer, along the sewer's axis,
    side: int             # and on which side (+1: the side of greater ``line``).
    storey: int = -2
    drop: tuple = None    # A ladder shaft beside the sewer: (sewer's wall, shaft's far side, its floor,
                          # the passage's floor, its roof's top), across and up.


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
        """Lowest point of its trench's shell and highest roof top."""
        floors = [f for _, f in self.sections]
        return min(floors) - TRENCH[self.kind][1] - SHELL, max(floors) + self.height + SHELL

    def trench(self, a0, a1):
        """Whether the trench runs from a0 to a1."""
        return (self.length > 2 * TRENCH_END + .5 and a0 >= self.start + TRENCH_END - 1e-6
                and a1 <= self.end - TRENCH_END + 1e-6)


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
class ServiceRoom:
    """A room between a sewer's end chamber and a station's hall: clear
    half sizes about (x, y), doors [(side, world coordinate along it)]."""
    id: str
    x: float
    y: float
    hx: float
    hy: float
    floor: float
    height: float
    doors: list = field(default_factory=list)

    def rect(self, grow=0.0):
        g = LINK_SHELL + grow
        return (self.x - self.hx - g, self.y - self.hy - g, self.x + self.hx + g, self.y + self.hy + g)


@dataclass
class Link:
    """Service rooms and corridors from a sewer's end chamber into a
    station's hall, through a doorway in the hall's ``wall`` ('a+', 'a-',
    'c+', 'c-') at world coordinate ``door`` along it."""
    id: str
    station: str
    chamber: str
    kind: str             # 'rooms' (two) or 'room' (one).
    wall: str
    door: float
    coordinate: float = 0.0   # The doorway along the hall's wall, in hall coordinates.
    toward: str = ''      # The chamber's wall it leaves by: '-x', '+x', '-y', '+y'.
    rooms: list = field(default_factory=list)
    corridors: list = field(default_factory=list)

    def solids(self):
        from . import tunnels
        found = [(r.rect(), r.floor - LINK_SHELL, r.floor + r.height + LINK_SHELL) for r in self.rooms]
        found += [(c.rect(), min(c.za, c.zb) - tunnels.SHELL, max(c.za, c.zb) + tunnels.HEIGHT + tunnels.SHELL)
                  for c in self.corridors]
        return found


@dataclass
class Network:
    chambers: dict
    sewers: list
    manholes: list
    breaches: list = field(default_factory=list)
    links: list = field(default_factory=list)

    def solids(self):
        """World boxes with their height ranges that nothing else may enter:
        (rect, low, high)."""
        found = []
        for chamber in self.chambers.values():
            if not chamber.hall:
                found.append((chamber.rect(), chamber.floor - SHELL, chamber.top))
        for sewer in self.sewers:
            found.append((sewer.rect(), *sewer.span()))
        for manhole in self.manholes:
            found.append((manhole.rect(), manhole.base, manhole.rim))
        for link in self.links:
            found += link.solids()
        return found

    def openings(self):
        """Where the street, the ground and the lane paint are cut: each
        shaft's outer octagon, a polygon as ``cutouts.cut`` takes it."""
        return [octagon(m.x, m.y, m.outer) for m in self.manholes]


def octagon(x, y, across):
    """A regular octagon, CCW, flats facing the axes; ``across`` the flats."""
    r = across / 2 / math.cos(math.pi / 8)
    return [(x + r * math.cos(math.pi / 8 + k * math.pi / 4), y + r * math.sin(math.pi / 8 + k * math.pi / 4))
            for k in range(8)]


def section(kind, trench=True):
    """A sewer's clear section, CCW in (across, up) from the walkways' level:
    an octagon, its lower chamfers small to keep the walkways wide, with a
    trench down the middle of the floor."""
    width, height, _ = TRUNK if kind == 'trunk' else LATERAL
    low, high = CHAMFERS[kind]
    half = width / 2
    points = [(-half + low, 0.0)]
    if trench:
        tw, td = TRENCH[kind]
        points += [(-tw / 2, 0.0), (-tw / 2, -td), (tw / 2, -td), (tw / 2, 0.0)]
    return points + [(half - low, 0.0), (half, low), (half, height - high), (half - high, height),
                     (-half + high, height), (-half, height - high), (-half, low)]


def _ring(points, thickness):
    """The shell round a CCW section: per edge a quad (the inner edge, then
    the outer edge back), mitred at the corners."""
    count = len(points)
    lines = []
    for i in range(count):
        (x0, y0), (x1, y1) = points[i], points[(i + 1) % count]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        lines.append(((x0 + dy / length * thickness, y0 - dx / length * thickness), (dx, dy)))
    outer = []
    for i in range(count):
        (px, py), (dx, dy) = lines[i - 1]
        (qx, qy), (ex, ey) = lines[i]
        a = ((qx - px) * ey - (qy - py) * ex) / (dx * ey - dy * ex)
        outer.append((px + a * dx, py + a * dy))
    return [(points[i], points[(i + 1) % count], outer[(i + 1) % count], outer[i]) for i in range(count)]


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


def plan(city, surface=None, sites=(), street=None, avoid=(), halls=None, below=()):
    """The sewer network of a city, before breaches. ``surface(x, y)``: road
    level (None: flat at 0); ``sites``: basements to keep clear of;
    ``street``: the street mesh as (vertices, faces, materials) in the same
    coordinates, for manholes (None: none); ``avoid``: world boxes nothing may
    pass under (site pads); ``halls``: subway halls standing in for the
    chambers of their junctions, {node: (id, x, y, floor, half x, half y)};
    ``below``: other solids underground, (rect, low, high)."""
    size = city.settings.block_size
    seed = city.settings.seed
    level = surface or (lambda x, y: 0.0)
    edges = _network_edges(city)
    boxes = [(site.box(site.outer), site.base + site.under.depth, site.base) for site in sites]

    def blocked(rect, low, high):
        if any(_overlap(rect, box) for box in avoid):
            return True
        if any(_overlap(rect, box) and low < top and bottom < high for box, bottom, top in below):
            return True
        return any(_overlap(rect, box) and low < top + CLEAR and bottom - CLEAR < high
                   for box, bottom, top in boxes)

    # Chambers: under every junction a sewer reaches, trunk-sized where a trunk does; none where a station's
    # hall stands (the sewers end short of it, each in a chamber of its own).
    stations = halls or {}
    kinds = {}
    for key, kind in edges.items():
        for node in key:
            if kinds.get(node) != 'trunk':
                kinds[node] = kind
    chambers = {}
    for node, kind in sorted(kinds.items()):
        if node in stations:
            continue
        x, y = node[0] * size, node[1] * size
        depth = (TRUNK if kind == 'trunk' else LATERAL)[2]
        chamber = Chamber(f'sewer_c_{_key(node)}', node, x, y, kind, level(x, y) - depth)
        if blocked(chamber.rect(CLEAR), chamber.floor - SHELL, chamber.top):
            continue
        chambers[node] = chamber
    links = []
    ends = {}
    for (a, b), kind in sorted(edges.items()):
        for this, other in ((a, b), (b, a)):
            if this in stations and (this, other) not in ends:
                ends[(this, other)] = _station_end(stations[this], this, other, kind, size, seed, level, blocked, links)
    sewers = []
    for (a, b), kind in sorted(edges.items()):
        ca = ends.get((a, b)) if a in stations else chambers.get(a)
        cb = ends.get((b, a)) if b in stations else chambers.get(b)
        if ca is None or cb is None:
            continue
        axis = 'x' if a[1] == b[1] else 'y'
        k = 0 if axis == 'x' else 1
        if (a[k] > b[k]):
            ca, cb = cb, ca
        line = ca.y if axis == 'x' else ca.x
        start = (ca.x if axis == 'x' else ca.y) + ca.half(axis) + SHELL
        end = (cb.x if axis == 'x' else cb.y) - cb.half(axis) - SHELL
        if end - start < 2.0:
            continue
        own = (TRUNK if kind == 'trunk' else LATERAL)[2]
        # At either end the floor ramps (1 in 8) to the chamber's own depth.
        targets = [(level(c.x, c.y) - c.floor, start if c is ca else end, 1 if c is ca else -1) for c in (ca, cb)]
        ramps = [(t, at, sense, abs(t - own) / SLOPE) for t, at, sense in targets if abs(t - own) > 1e-6]

        def depth_at(along, own=own, ramps=ramps):
            depth = own
            for target, at, sense, run in ramps:
                weight = max(0.0, 1.0 - (along - at) * sense / run)
                depth += (target - own) * weight
            return depth

        marks = [start + TRENCH_END, end - TRENCH_END] + [at + sense * run for _, at, sense, run in ramps
                                                           if 0 < run < end - start]
        sections = _sections(start, end, line, axis, depth_at, level, ca.floor, cb.floor, False, False, marks)
        sewer = Sewer(f'sewer_{_key(ca.node)}__{_key(cb.node)}', ca.id, cb.id, kind, axis, line, start, end, sections)
        if blocked(sewer.rect(CLEAR), *sewer.span()):
            continue
        sewers.append(sewer)
        for c in (ca, cb):
            chambers.setdefault(('end', c.id), c)
    # Chambers no sewer reaches any more are not built.
    used = {s.a for s in sewers} | {s.b for s in sewers}
    chambers = {c.id: c for c in chambers.values() if c.id in used}
    # Links into halls whose chamber no sewer reaches are not built either.
    links = [link for link in links if link.chamber in chambers]
    for link in links:
        chambers[link.chamber].doors.append((link.toward, 'service'))
        station = next(st for st in stations.values() if st.id == link.station)
        station.take(*station.wall_spot(link.wall, link.coordinate))
    for sewer in sewers:
        ca, cb = chambers[sewer.a], chambers[sewer.b]
        sign = '+x' if sewer.axis == 'x' else '+y'
        ca.doors.append((sign, sewer.kind))
        cb.doors.append((sign.replace('+', '-'), sewer.kind))
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
        if chamber.hall:
            continue
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
    return Network(chambers, sewers, manholes, links=links)


def _station_end(station, node, other, kind, size, seed, level, blocked, links):
    """The chamber a sewer ends in beside a station's hall, on the street
    towards ``other``, and the service rooms joining it to the hall (added
    to ``links``); None if it cannot be built."""
    from . import tunnels
    d = (other[0] - node[0], other[1] - node[1])
    axis = 'x' if d[1] == 0 else 'y'
    sign = d[0] + d[1]
    x0, y0 = node[0] * size, node[1] * size
    hall_l, hall_shell = 20.0, .25
    try:
        from .subway import HALL, HALL_SHELL
        hall_l, hall_shell = HALL[0], HALL_SHELL
    except ImportError:
        pass
    lengthwise = axis == station.axis
    face = (hall_l if lengthwise else station.side_half) + hall_shell
    wall = ('a' if lengthwise else 'c') + ('+' if sign > 0 else '-')
    depth = (TRUNK if kind == 'trunk' else LATERAL)[2]
    half = CHAMBER[kind] / 2
    ident = f'sewer_c_{_key(node)}_{"xy"[axis == "y"]}{"+" if sign > 0 else "-"}'
    pick = stream(seed, 'station-link', ident).random()
    total, variant = 0.0, 'none'
    for name, share in LINK_KINDS:
        total += share
        if pick < total:
            variant = name
            break
    if variant != 'none' and not station.clear(*station.wall_spot(wall, 0.0)):
        variant = 'none'

    def at(distance):
        return (x0 + sign * distance, y0) if axis == 'x' else (x0, y0 + sign * distance)

    toward = ('-' if sign > 0 else '+') + axis
    line = y0 if axis == 'x' else x0
    length, width, height = LINK_ROOM
    for attempt in ((variant, 'none') if variant != 'none' else ('none',)):
        # Outwards from the hall's wall: rooms with corridors between them, a ramp, the chamber.
        count = {'rooms': 2, 'room': 1, 'none': 0}[attempt]
        reach, rooms, spans = face, [], []
        for k in range(count):
            if k:
                spans.append((reach, reach + LINK_CORRIDOR))
                reach += LINK_CORRIDOR
            cx, cy = at(reach + LINK_SHELL + length / 2)
            hx, hy = (length / 2, width / 2) if axis == 'x' else (width / 2, length / 2)
            rooms.append(ServiceRoom(f'{ident}_room_{k}', cx, cy, hx, hy, station.hall_floor, height,
                                     [(toward, line), (('+' if sign > 0 else '-') + axis, line)]))
            reach += length + 2 * LINK_SHELL
        if count:
            # The last corridor ramps, 1 in 8 at most, from the rooms' floor to the chamber's.
            run = 2.0
            for _ in range(4):
                cx, cy = at(reach + run + SHELL + half)
                need = max(2.0, abs(level(cx, cy) - depth - station.hall_floor) / tunnels.SLOPE + .2)
                if need <= run + 1e-6:
                    break
                run = need
            spans.append((reach, reach + run))
        else:
            cx, cy = at(reach + CLEAR + SHELL + half)
        chamber = Chamber(ident, node, cx, cy, kind, level(cx, cy) - depth, station=station.id)
        corridors = []
        base = x0 if axis == 'x' else y0
        for j, (d0, d1) in enumerate(spans):
            last = j == len(spans) - 1
            ends = sorted((base + sign * d0, base + sign * d1))
            z_near, z_far = station.hall_floor, chamber.floor if last else station.hall_floor
            za, zb = (z_near, z_far) if sign > 0 else (z_far, z_near)
            corridors.append(tunnels.Tunnel(f'{ident}_corridor_{j}', rooms[j].id, ident if last else rooms[j + 1].id,
                                            -2, axis, line, ends[0], ends[1], za, zb, '', '', True))
        parts = [(chamber.rect(CLEAR), chamber.floor - SHELL, chamber.top)]
        parts += [(r.rect(CLEAR), r.floor - LINK_SHELL, r.floor + r.height + LINK_SHELL) for r in rooms]
        parts += [(c.rect(), min(c.za, c.zb) - tunnels.SHELL, max(c.za, c.zb) + tunnels.HEIGHT + tunnels.SHELL)
                  for c in corridors]
        if any(blocked(*part) for part in parts):
            continue
        if count:
            links.append(Link(f'{ident}_link', station.id, ident, attempt, wall, line, 0.0, toward, rooms, corridors))
        return chamber
    return None


def breach(network, sites, seed, avoid=()):
    """Passages from basements to the sewers in front of them: from a second
    storey down a gentle slope to a trunk; from an old town or brutalist
    building's first storey along a short level passage to a ladder shaft
    beside a trunk or a lateral, which opens into it at its floor. Fills in
    the sites' ``doors`` and the network's ``breaches``. ``avoid``: other
    solids as (rect, low, high), the tunnels' among them."""
    from . import tunnels
    taken = set()
    have = [s for s in sites if s.quarter() is not None and
            (s.level(-2) is not None or (s.style in DROP_STYLES and s.level(-1) is not None))]
    boxes = {s.id: s.box(s.outer) for s in sites}
    per_sewer = {}
    found = []
    shaft = 2 * DROP[1] + DROP[0]
    for sewer in sorted(network.sewers, key=lambda s: s.id):
        m = 0 if sewer.axis == 'x' else 1     # Along the sewer.
        n = 1 - m                              # Across it.
        outer = sewer.width / 2 + SHELL
        axis = 'y' if sewer.axis == 'x' else 'x'
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
            if gap > BREACH_REACH:
                continue
            modes = []
            if sewer.kind == 'trunk' and site.level(-2) is not None and gap >= .5:
                modes.append((-2, False))
            if site.style in DROP_STYLES and gap >= shaft + .3:
                modes.append((-1, True))
            if not modes:
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
            choice = None
            for storey, drop in modes:
                for k in range(int((hi - lo) / .5) + 1):
                    along = centre + .5 * ((k + 1) // 2) * (1 if k % 2 else -1)
                    if not lo - 1e-6 <= along <= hi + 1e-6:
                        continue
                    probe = face + side * .6
                    px, py = (along, probe) if sewer.axis == 'x' else (probe, along)
                    room = tunnels._room_behind(site, storey, px, py, axis)
                    if room is None:
                        continue
                    za = sewer.floor_at(along)
                    zb = site.floor(storey)
                    ident = f'breach_{site.id}__{sewer.id}'
                    if drop:
                        if zb - za < 1.0:
                            continue
                        far = wall + side * shaft
                        top = zb + tunnels.HEIGHT + tunnels.SHELL
                        start, end = sorted((far, face))
                        passage = tunnels.Tunnel(ident, site.id, sewer.id, storey, axis, along, start, end, zb, zb,
                                                 room.name, '', True)
                        lo_s, hi_s = sorted((wall, far))
                        parts = [(passage.rect(tunnels.CLEAR), zb - tunnels.SHELL, top),
                                 (_rect_across(sewer, along - tunnels.WIDTH / 2 - DROP[1],
                                               along + tunnels.WIDTH / 2 + DROP[1], lo_s, hi_s), za - DROP[1], top)]
                        shape = (wall, far, za, zb, top)
                    else:
                        if abs(za - zb) > gap * tunnels.SLOPE:
                            continue
                        if side > 0:
                            start, end, z0, z1 = wall, face, za, zb
                        else:
                            start, end, z0, z1 = face, wall, zb, za
                        passage = tunnels.Tunnel(ident, site.id, sewer.id, storey, axis, along, start, end, z0, z1,
                                                 room.name, '', True)
                        parts = [(passage.rect(tunnels.CLEAR), min(z0, z1) - tunnels.SHELL,
                                  max(z0, z1) + tunnels.HEIGHT + tunnels.SHELL)]
                        shape = None
                    if any(_overlap(r, b) for r, _, _ in parts for ident2, b in boxes.items() if ident2 != site.id):
                        continue
                    if any(_overlap(r, r2) and lo3 < high and low < hi3
                           for r, low, high in parts for r2, lo3, hi3 in avoid):
                        continue
                    if any(_overlap(r, other.tunnel.rect()) for r, _, _ in parts for other in found):
                        continue
                    choice = (passage, room, along, za, storey, shape)
                    break
                if choice is not None:
                    break
            if choice is None:
                continue
            if stream(seed, 'breach', choice[0].id).random() >= BREACH_SHARE:
                continue
            if per_sewer.get(sewer.id, 0) >= 2:
                continue
            passage, room, along, za, storey, shape = choice
            per_sewer[sewer.id] = per_sewer.get(sewer.id, 0) + 1
            taken.add(site.id)
            made = Breach(passage.id, site.id, room.name, sewer.id, passage, along, side, storey, shape)
            found.append(made)
            sewer.breaches.append(made)
            # The sewer is level across the gap in its wall, so the passage or shaft meets it flush.
            half = tunnels.WIDTH / 2
            kept = [(a, f) for a, f in sewer.sections if not along - half - 1e-6 <= a <= along + half + 1e-6]
            sewer.sections = sorted(kept + [(along - half, za), (along + half, za)])
            point = (along, face) if sewer.axis == 'x' else (face, along)
            door_side, door_centre = tunnels._side(site, *point)
            site.doors.append((storey, door_side, door_centre, tunnels.DOOR[0], tunnels.DOOR[1]))
    network.breaches = found
    return found


def _rect_across(sewer, a0, a1, c0, c1):
    """A plan rect from along and absolute across ranges of a sewer."""
    (x0, y0), (x1, y1) = sewer.point(a0, c0 - sewer.line), sewer.point(a1, c1 - sewer.line)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _drop(mesh, sewer, b, material, floor_material):
    drop_shaft(mesh, sewer, b.along, b.side, b.drop, OPENING[sewer.kind], material, floor_material)


def drop_shaft(mesh, stretch, along, side, drop, opening, material, floor_material):
    """A drop's ladder shaft beside ``stretch`` (a sewer, or a subway
    station's hall: anything with a ``line`` and a ``point``): its floor at
    the stretch's, open into it below ``opening``, open to the passage above
    the passage's floor, roofed. ``drop``: (the stretch's wall, the shaft's
    far side, its floor, the passage's floor, its roof's top)."""
    from . import solids, tunnels
    wall, far, zs, zb, top = drop
    t = DROP[1]
    half = tunnels.WIDTH / 2
    lo, hi = sorted((wall, far))

    def box(c0, c1, a0, a1, z0, z1, mat):
        if z1 - z0 < 1e-4:
            return
        r = _rect_across(stretch, a0, a1, c0, c1)
        solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, mat)

    a = along
    box(lo, hi, a - half - t, a + half + t, zs - t, zs, floor_material)
    for a0, a1 in ((a - half - t, a - half), (a + half, a + half + t)):
        box(lo, hi, a0, a1, zs, top - t, material)
    near = sorted((wall, wall + side * t))
    box(near[0], near[1], a - half, a + half, zs + opening, top - t, material)
    back = sorted((far - side * t, far))
    box(back[0], back[1], a - half, a + half, zs, zb, material)
    box(lo, hi, a - half - t, a + half + t, top - t, top, floor_material)


def build(mesh, network):
    """The network's solids in world coordinates, in the sewers' materials
    (meshdata.U_SEWER_*; breach passages in the tunnels')."""
    from . import tunnels
    from .meshdata import U_SEWER_SHAFT, U_SEWER_WALKWAY, U_SEWER_WALL
    for chamber in network.chambers.values():
        if not chamber.hall:
            _chamber(mesh, chamber, U_SEWER_WALL, U_SEWER_WALKWAY, U_SEWER_WALKWAY)
    for sewer in network.sewers:
        _sewer(mesh, sewer)
    for item in network.breaches:
        tunnels.build(mesh, item.tunnel)
        if item.drop is not None:
            sewer = next(x for x in network.sewers if x.id == item.sewer)
            _drop(mesh, sewer, item, U_SEWER_SHAFT, U_SEWER_WALKWAY)
    for manhole in network.manholes:
        _shaft(mesh, manhole, U_SEWER_SHAFT)


def _volume(first, second):
    count = len(first)
    faces = [list(reversed(first)), list(second)] + [
        [first[i], first[(i + 1) % count], second[(i + 1) % count], second[i]] for i in range(count)]
    total = 0.0
    for face in faces:
        o = face[0]
        for k in range(1, len(face) - 1):
            b, c = face[k], face[k + 1]
            total += (o[0] * (b[1] * c[2] - b[2] * c[1]) - o[1] * (b[0] * c[2] - b[2] * c[0])
                      + o[2] * (b[0] * c[1] - b[1] * c[0]))
    return total / 6


def _solid(mesh, first, second, material):
    """A closed solid between two sections whose corners correspond."""
    if _volume(first, second) < 0:
        first, second = first[::-1], second[::-1]
    a = [mesh.vert(co) for co in first]
    b = [mesh.vert(co) for co in second]
    mesh.face(list(reversed(a)), material)
    mesh.face(b, material)
    count = len(a)
    for i in range(count):
        j = (i + 1) % count
        mesh.face((a[i], a[j], b[j], b[i]), material)


def _flat(mesh, outline, z0, z1, material):
    _solid(mesh, [(x, y, z0) for x, y in outline], [(x, y, z1) for x, y in outline], material)


def _doorway(kind, centre, floor, frame):
    """A sewer's opening in a chamber's wall: its section without the trench."""
    from . import solids
    width, height, _ = TRUNK if kind == 'trunk' else LATERAL
    low, high = CHAMFERS[kind]
    half = width / 2
    bottom = [(centre - half, floor + low), (centre - half + low, floor), (centre + half - low, floor),
              (centre + half, floor + low)]
    top = [(centre - half, floor + height - high), (centre - half + high, floor + height),
           (centre + half - high, floor + height), (centre + half, floor + height - high)]
    return solids.Opening(centre - half, centre + half, bottom, top, frame, 'door')


def _chamber(mesh, chamber, material, floor_material, frame):
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
        kinds = [kind for door_side, kind in chamber.doors if door_side == side]
        if kinds:
            if 'service' in kinds:
                opening = solids.Opening.rect(centre - LINK_DOOR[0] / 2, centre + LINK_DOOR[0] / 2, f,
                                              f + LINK_DOOR[1], frame, 'door')
            else:
                opening = _doorway('trunk' if 'trunk' in kinds else 'lateral', centre, f, frame)
            solids.wall_solid(mesh, origin, direction, s, 0.0, length, f, [(0.0, top), (length, top)],
                              [opening], material)
        else:
            b = boxes[side]
            solids.box(mesh, b[0], b[1], f, b[2], b[3], top, material)
    # The roof, round the shaft's octagonal opening if it has a manhole.
    m = chamber.manhole
    if m is None:
        solids.box(mesh, x0, y0, top, x1, y1, top + s, material)
        return
    c = SHAFT / 2
    hx0, hy0, hx1, hy1 = m.x - c, m.y - c, m.x + c, m.y + c
    solids.box(mesh, x0, y0, top, x1, hy0, top + s, material)
    solids.box(mesh, x0, hy1, top, x1, y1, top + s, material)
    solids.box(mesh, x0, hy0, top, hx0, hy1, top + s, material)
    solids.box(mesh, hx1, hy0, top, x1, hy1, top + s, material)
    ring = octagon(m.x, m.y, SHAFT)
    for k, corner in zip((0, 2, 4, 6), ((hx1, hy1), (hx0, hy1), (hx0, hy0), (hx1, hy0))):
        _flat(mesh, [ring[k], corner, ring[k + 1]], top, top + s, material)


def _shaft(mesh, manhole, material):
    x, y, z0, z1 = manhole.x, manhole.y, manhole.base, manhole.rim
    if z1 - z0 < .05:
        return
    inner, outer = octagon(x, y, SHAFT), octagon(x, y, manhole.outer)
    for k in range(8):
        j = (k + 1) % 8
        _flat(mesh, [inner[k], inner[j], outer[j], outer[k]], z0, z1, material)


def _gap_pieces(kind, sign, roof=None):
    """Where a breach comes in on a trunk: the section's shell on that side
    loses its chamfers and wall below the passage's roof, and gains a floor
    out to the passage and a lintel over it. Returns (edges dropped,
    polygons added)."""
    from . import tunnels
    width, height, _ = TRUNK if kind == 'trunk' else LATERAL
    low, high = CHAMFERS[kind]
    half = width / 2
    roof = OPENING[kind] if roof is None else roof
    points = section(kind)
    ring = _ring(points, SHELL)
    first = 5                                     # Right side: lower chamfer, wall, upper chamfer.
    assert points[first] == (half - low, 0.0)
    corner = ring[first][3]                       # Outer mitre under the walkway's edge.
    floor = [(half - low, 0.0), (half + SHELL, 0.0), (half + SHELL, -SHELL), corner]
    if roof > height - high + 1e-6:
        # Up into the upper chamfer: a lintel over the gap in its place.
        top_inner, top_outer = ring[first + 3][0], ring[first + 3][3]
        t = (roof - (height - high)) / high
        chamfer = (half - t * high, roof)
        lintel = [chamfer, (half + SHELL, roof), (half + SHELL, height + SHELL), top_outer, top_inner]
        dropped = {first, first + 1, first + 2}
    elif roof < height - high - 1e-6:
        # Within the wall: the wall's upper part stays.
        side_top, side_outer = ring[first + 1][1], ring[first + 1][2]
        lintel = [(half, roof), side_top, side_outer, (half + SHELL, roof)]
        dropped = {first, first + 1}
    else:
        lintel = None
        dropped = {first, first + 1}
    if sign < 0:
        # The section is symmetric: the mirror of edge i runs between the mirrors of its ends.
        count = len(points)
        mirror = {p: i for i, p in enumerate(points)}
        dropped = {mirror[(-points[(i + 1) % count][0], points[(i + 1) % count][1])] for i in dropped}
        floor = [(-u, v) for u, v in floor]
        lintel = [(-u, v) for u, v in lintel] if lintel else None
    return dropped, [p for p in (floor, lintel) if p]


def _sewer(mesh, sewer):
    from . import tunnels
    from .meshdata import U_SEWER_CHANNEL, U_SEWER_COLLAPSE, U_SEWER_WALKWAY, U_SEWER_WALL
    material, floor_material, plug_material = U_SEWER_WALL, U_SEWER_WALKWAY, U_SEWER_COLLAPSE
    kind = sewer.kind
    full, plain = _ring(section(kind), SHELL), _ring(section(kind, trench=False), SHELL)
    tw, td = TRENCH[kind]
    # Where the trench ends: a block under the trench-less floor closes it.
    filler = [(-tw / 2 - SHELL, -td - SHELL), (tw / 2 + SHELL, -td - SHELL), (tw / 2 + SHELL, -SHELL),
              (-tw / 2 - SHELL, -SHELL)]
    width, height, _ = TRUNK if kind == 'trunk' else LATERAL
    low, high = CHAMFERS[kind]
    half = width / 2
    void = [(-half + low, 0.0), (half - low, 0.0), (half, low), (half, height - high), (half - high, height),
            (-half + high, height), (-half, height - high), (-half, low)]
    trench_void = [(-tw / 2, -td), (tw / 2, -td), (tw / 2, 0.0), (-tw / 2, 0.0)]
    gaps = [(b.along - tunnels.WIDTH / 2, b.along + tunnels.WIDTH / 2, b.side) for b in sewer.breaches]

    def extrude(polygon, a0, a1, mat):
        f0, f1 = sewer.floor_at(a0), sewer.floor_at(a1)
        _solid(mesh, [(*sewer.point(a0, u), f0 + v) for u, v in polygon],
               [(*sewer.point(a1, u), f1 + v) for u, v in polygon], mat)

    for (a0, _), (a1, _) in zip(sewer.sections, sewer.sections[1:]):
        if a1 - a0 < 1e-4:
            continue
        trench = sewer.trench(a0, a1)
        quads = list(full if trench else plain)
        extra = [] if trench else [filler]
        for g0, g1, side in gaps:
            if g0 - 1e-6 <= a0 and a1 <= g1 + 1e-6:
                assert trench, sewer.id
                dropped, added = _gap_pieces(kind, side)
                quads = [q for i, q in enumerate(quads) if i not in dropped]
                extra += added
        for quad in quads:
            on_floor = quad[0][1] <= 1e-6 and quad[1][1] <= 1e-6
            in_trench = on_floor and min(quad[0][1], quad[1][1]) < -1e-6
            extrude(quad, a0, a1, U_SEWER_CHANNEL if in_trench else floor_material if on_floor else material)
        for polygon in extra:
            extrude(polygon, a0, a1, floor_material)
        if sewer.plug is not None and sewer.plug[0] - 1e-6 <= a0 and a1 <= sewer.plug[1] + 1e-6:
            extrude(void, a0, a1, plug_material)
            if trench:
                extrude(trench_void, a0, a1, plug_material)
