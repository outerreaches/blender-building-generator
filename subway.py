# SPDX-License-Identifier: GPL-3.0-or-later
"""The subway: a line under the arterials from one far district through
the city's centre to another. Pure Python.

The line is a twin-track tunnel, its upper corners vaulted, 14 m under the
street and following its grade, with an evacuation walkway along one side.
It turns at junctions in a turning box. Stations stand under junctions
where the line runs straight along arterials, and at its ends: a level box
with a side platform each side of the tracks (steps at the platform ends
down to the track bed), a ticket hall above at a second basement's depth,
a stair from each platform up into the hall, and up to two entrances from
the hall to the street, stairwells in the kerb lanes with a parapet round
their opening. The sewers that reach a station's junction end in its hall
(``halls`` for ``sewers.plan``); deep basements beside a hall get a
doorway into it (``connect``). Midway between stations a utility branch
leaves the line on its walkway's side: a short corridor and a room, half of
them with a ladder shaft up to a hatch in the footway.
"""
import math
from dataclasses import dataclass, field

from .city_plan import stream
from . import sewers as _sewers

TRACK_DEPTH = 14.0        # Track bed under the street.
LINE = (8.6, 5.0, 1.2)    # Clear width and height of the line's tunnel, and its vaulted upper corners.
SHELL = .4                # Floor, walls and roof of the line and its stations.
WALKWAY = (.9, .9)        # Evacuation walkway along the line's +across side: width, height.
STATION = 46.0            # A station's clear length,
PLATFORM = (3.5, 1.0)     # its side platforms' width and height over the track bed,
HEADROOM = 5.5            # and its clear height over the track bed.
END_STEPS = (5, .32)      # Steps at a platform's end down to the track bed: count, going.
HALL = (14.0, 3.5, 6.4)   # Ticket hall: half length along the line, clear height, floor under the footway.
HALL_SHELL = .25
HALL_SIDE = 7.5           # The hall's half width across the line, under an arterial's street.
SPACING = 4               # Junctions from one station to the next, about.
STAIR = (2.0, .17, .28)   # Stairs: clear width, rise and going of a step.
STAIR_TOP = 9.0           # Along the line from the junction, where a hall stair arrives.
HEADROOM_STAIR = 2.2
ENTRANCE = (1.4, .2, 2.4) # Street entrance: clear width, wall thickness, headroom.
KERB = .2                 # Room left between an entrance's parapet and the curb.
PARAPET = 1.0             # Height of the parapet round an entrance's opening.
UTILITY = 2.4             # Utility room, square, clear (as high).
UTILITY_SHELL = .25
EXIT_SHARE = .5           # Share of utility rooms with a ladder shaft up to the street.
ACCESS_REACH = 16.0       # Longest passage from a basement into a hall.
LINE_TIERS = {'ARTERIAL': 1.0, 'COLLECTOR': 2.5}
MIN_STOPS = 6             # Shortest line, in junctions.


def _key(node):
    return f'{node[0]}_{node[1]}'


@dataclass
class Stretch:
    """A straight piece of something along a lattice axis: the line between
    junctions, or a station's box. ``point(along, across)`` maps to plan."""
    axis: str
    line: float

    def point(self, along, across=0.0):
        return (along, self.line + across) if self.axis == 'x' else (self.line + across, along)


@dataclass
class Edge(Stretch):
    """The line between two junctions: from ``start`` to ``end`` along the
    axis, its track bed at ``sections`` [(along, level)]."""
    a: tuple = None
    b: tuple = None
    start: float = 0.0
    end: float = 0.0
    sections: list = field(default_factory=list)
    doors: list = field(default_factory=list)      # Utility doorways: centre along.
    arterial: bool = True

    @property
    def length(self):
        return self.end - self.start

    def floor_at(self, along):
        return _sewers.Sewer.floor_at(self, along)

    def rect(self, grow=0.0):
        half = LINE[0] / 2 + SHELL + grow
        if self.axis == 'x':
            return (self.start - grow, self.line - half, self.end + grow, self.line + half)
        return (self.line - half, self.start - grow, self.line + half, self.end + grow)

    def span(self):
        floors = [f for _, f in self.sections]
        return min(floors) - SHELL, max(floors) + LINE[1] + SHELL


@dataclass
class Entrance:
    id: str
    sign: int             # Which way along the line it climbs from the hall.
    side: int             # Which side of the line (its kerb lane).
    across: tuple         # Clear width across the line: (from, to).
    start: float          # Along the line: its foot at the hall's wall,
    run: float            # its length,
    open: float           # where its ceiling stops and the street is open over it,
    floor: float          # the hall's floor,
    top: float            # the street at its head (highest over the opening).
    steps: int
    buried: float = 0.0   # Lowest street over its covered part, less a little: its walls' top there.

    @property
    def rise(self):
        return (self.top - self.floor) / self.steps


@dataclass
class Access:
    id: str
    site: str
    room: str
    tunnel: object        # A tunnels.Tunnel from the basement's wall to the hall's.


@dataclass
class Station(Stretch):
    id: str = ''
    node: tuple = None
    x: float = 0.0
    y: float = 0.0
    track: float = 0.0
    hall_floor: float = 0.0
    ends: tuple = (True, True)     # Whether the line leaves the -along and +along ends.
    entrances: list = field(default_factory=list)
    accesses: list = field(default_factory=list)
    doors: list = field(default_factory=list)     # Sewers into the hall: (side, kind).

    @property
    def centre(self):
        return self.x if self.axis == 'x' else self.y

    @property
    def half_across(self):
        return LINE[0] / 2 + PLATFORM[0]

    @property
    def roof(self):
        return self.track + HEADROOM + SHELL

    def box(self, grow=0.0):
        return _rect(self, self.centre - STATION / 2 - SHELL - grow, self.centre + STATION / 2 + SHELL + grow,
                     -self.half_across - SHELL - grow, self.half_across + SHELL + grow)

    def hall(self, grow=0.0):
        return _rect(self, self.centre - HALL[0] - HALL_SHELL - grow, self.centre + HALL[0] + HALL_SHELL + grow,
                     -HALL_SIDE - HALL_SHELL - grow, HALL_SIDE + HALL_SHELL + grow)

    def hall_span(self):
        return self.hall_floor - HALL_SHELL, self.hall_floor + HALL[1] + HALL_SHELL

    def stairs(self):
        """The two stairs from the platforms up into the hall: (sign along,
        across centre, bottom along, steps, rise)."""
        rise_total = self.hall_floor - (self.track + PLATFORM[1])
        steps = math.ceil(rise_total / STAIR[1] - 1e-9)
        run = steps * STAIR[2]
        found = []
        for sign in (1, -1):
            across = sign * (LINE[0] / 2 + PLATFORM[0] / 2)
            top = self.centre + sign * STAIR_TOP
            found.append((sign, across, top - sign * run, steps, rise_total / steps))
        return found


@dataclass
class Turn:
    id: str
    node: tuple
    x: float
    y: float
    track: float
    sides: list           # Where the line comes in: '-x', '+x', '-y', '+y'.

    def rect(self, grow=0.0):
        half = LINE[0] / 2 + SHELL + grow
        return (self.x - half, self.y - half, self.x + half, self.y + half)


@dataclass
class Utility:
    id: str
    edge: object
    along: float
    floor: float
    across: float         # Centre of its room.
    corridor: object      # tunnels.Tunnel from the line's wall to the room's.
    exit: object = None   # A sewers.Manhole up to the street, if it has one.

    def room(self, grow=0.0):
        half = UTILITY / 2 + UTILITY_SHELL + grow
        return _rect(self.edge, self.along - half, self.along + half, self.across - half, self.across + half)


@dataclass
class Subway:
    path: list
    stations: list
    turns: list
    edges: list
    utilities: list = field(default_factory=list)

    @property
    def exits(self):
        return [u.exit for u in self.utilities if u.exit is not None]

    def halls(self):
        """Station halls by junction, as ``sewers.plan`` takes them: (id,
        x, y, floor, half x, half y)."""
        found = {}
        for s in self.stations:
            hx, hy = (HALL[0], HALL_SIDE) if s.axis == 'x' else (HALL_SIDE, HALL[0])
            found[s.node] = (f'subway_hall_{_key(s.node)}', s.x, s.y, s.hall_floor, hx, hy)
        return found

    def solids(self, halls=True):
        """World boxes with their height ranges nothing else may enter: (rect,
        low, high)."""
        found = [(e.rect(), *e.span()) for e in self.edges if e.length > 1e-6]
        for s in self.stations:
            found.append((s.box(), s.track - SHELL, s.roof))
            if halls:
                found.append((s.hall(), *s.hall_span()))
            for e in s.entrances:
                found.append((_entrance_rect(s, e), e.floor - HALL_SHELL, e.top + PARAPET))
        for t in self.turns:
            found.append((t.rect(), t.track - SHELL, t.track + LINE[1] + SHELL))
        for u in self.utilities:
            found.append((u.room(), u.floor - UTILITY_SHELL, u.floor + UTILITY + UTILITY_SHELL))
            found.append((u.corridor.rect(), u.floor - .2, u.floor + 2.4))
            if u.exit is not None:
                found.append((u.exit.rect(), u.exit.base, u.exit.rim))
        return found

    def openings(self):
        """Street, ground and paint cuts: entrances' open stairwells (as
        rectangles) and exit shafts (octagons)."""
        found = []
        for s in self.stations:
            for e in s.entrances:
                found.append(_entrance_opening(s, e))
        found += [_sewers.octagon(m.x, m.y, m.outer) for m in self.exits]
        return found


def _rect(stretch, a0, a1, c0, c1):
    """A plan rect from along and across ranges of a stretch."""
    (x0, y0), (x1, y1) = stretch.point(a0, c0), stretch.point(a1, c1)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _entrance_rect(station, e):
    a0, a1 = sorted((e.start, e.start + e.sign * e.run))
    return _rect(station, a0, a1, e.across[0] - ENTRANCE[1], e.across[1] + ENTRANCE[1])


def _entrance_opening(station, e):
    a0, a1 = sorted((e.start + e.sign * e.open, e.start + e.sign * e.run))
    x0, y0, x1, y1 = _rect(station, a0, a1, e.across[0] - ENTRANCE[1], e.across[1] + ENTRANCE[1])
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0)


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# -- planning ------------------------------------------------------------------


def _graph(city):
    """Arterials (and collectors, at a cost) between lattice neighbours: {node: [(other, weight, tier)]}."""
    rural = {tuple(sorted((tuple(a), tuple(b)))) for a, b in getattr(city, 'rural', ())}
    graph = {}
    for road in city.roads:
        a, b = tuple(road.a), tuple(road.b)
        if road.tier not in LINE_TIERS or abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
            continue
        if tuple(sorted((a, b))) in rural:
            continue
        graph.setdefault(a, []).append((b, LINE_TIERS[road.tier], road.tier))
        graph.setdefault(b, []).append((a, LINE_TIERS[road.tier], road.tier))
    return graph


def _route(graph, start, goal, banned=()):
    """Cheapest path, deterministic on ties; None if there is none."""
    import heapq
    best = {start: 0.0}
    back = {}
    heap = [(0.0, start)]
    while heap:
        cost, node = heapq.heappop(heap)
        if node == goal:
            path = [node]
            while path[-1] != start:
                path.append(back[path[-1]])
            return path[::-1]
        if cost > best.get(node, math.inf):
            continue
        for other, weight, _ in sorted(graph.get(node, ())):
            if other in banned and other != goal:
                continue
            total = cost + weight
            if total < best.get(other, math.inf) - 1e-9:
                best[other] = total
                back[other] = node
                heapq.heappush(heap, (total, other))
    return None


def _nearest(graph, node):
    return min(graph, key=lambda n: (abs(n[0] - node[0]) + abs(n[1] - node[1]), n)) if graph else None


def _line_path(city, graph):
    """From a far district through the centre to another, on the far side."""
    centre = next((tuple(loc.node) for loc in city.locations if loc.role == 'CENTER'), (0, 0))
    c = _nearest(graph, centre)
    ends = sorted({_nearest(graph, tuple(loc.node)) for loc in city.locations if loc.role == 'PRIMARY'} - {c})
    best = None
    for i, p in enumerate(ends):
        for q in ends[i + 1:]:
            ux, uy = p[0] - c[0], p[1] - c[1]
            vx, vy = q[0] - c[0], q[1] - c[1]
            lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
            if lu < 3 or lv < 3 or (ux * vx + uy * vy) / (lu * lv) > -.5:
                continue
            score = lu + lv
            if best is None or score > best[0] + 1e-9:
                best = (score, p, q)
    if best is None:
        return None
    _, p, q = best
    first = _route(graph, p, c)
    if first is None:
        return None
    second = _route(graph, c, q, banned=set(first))
    if second is None:
        return None
    path = first + second[1:]
    return path if len(path) >= MIN_STOPS else None


def _axis(a, b):
    return 'x' if a[1] == b[1] else 'y'


def plan(city, surface=None, sites=(), street=None, avoid=()):
    """The subway of a city, or None. ``surface(x, y)``: road level;
    ``sites``: basements to keep clear of; ``street``: the street mesh as
    (vertices, faces, materials), for entrances and exits (None: none);
    ``avoid``: world boxes nothing may pass under (site pads)."""
    size = city.settings.block_size
    seed = city.settings.seed
    curb = city.settings.curb_height
    walk = city.settings.sidewalk_width
    level = surface or (lambda x, y: 0.0)
    graph = _graph(city)
    path = _line_path(city, graph)
    if path is None:
        return None
    tiers = {}
    for node, links in graph.items():
        for other, _, tier in links:
            tiers[tuple(sorted((node, other)))] = tier
    boxes = [(site.box(site.outer), site.base + site.under.depth, site.base) for site in sites]

    def blocked(rect, low, high):
        return any(_overlap(rect, box) for box in avoid) or any(
            _overlap(rect, box) and low < top + .3 and bottom - .3 < high for box, bottom, top in boxes)

    def arterial(a, b):
        return tiers.get(tuple(sorted((a, b)))) == 'ARTERIAL'

    # Stations: at both ends and every few junctions where the line runs straight along arterials.
    count = len(path)
    candidates = []
    for k, node in enumerate(path):
        before = path[k - 1] if k > 0 else None
        after = path[k + 1] if k + 1 < count else None
        if before is not None and after is not None and _axis(before, node) != _axis(node, after):
            continue
        if any(other is not None and not arterial(node, other) for other in (before, after)):
            continue
        candidates.append(k)
    chosen = []
    for k in candidates:
        if k in (0, count - 1) or not chosen or k - chosen[-1] >= SPACING:
            if chosen and k - chosen[-1] < 2:
                continue
            chosen.append(k)
    if chosen and chosen[-1] != count - 1 and count - 1 in candidates and count - 1 - chosen[-1] < 2:
        chosen.pop()
    stations, at = [], {}
    for k in chosen:
        node = path[k]
        x, y = node[0] * size, node[1] * size
        other = path[k + 1] if k + 1 < count else path[k - 1]
        axis = _axis(node, other)
        line = y if axis == 'x' else x
        ends = _station_ends(path, k, axis)
        station = Station(axis, line, f'subway_station_{_key(node)}', node, x, y, level(x, y) - TRACK_DEPTH,
                          level(x, y) + curb - HALL[2], ends)
        if blocked(station.hall(), *station.hall_span()):
            continue
        stations.append(station)
        at[k] = station
    if len(stations) < 2:
        return None
    # Turns, and the line between junctions.
    turns, turn_at = [], {}
    for k in range(1, count - 1):
        if _axis(path[k - 1], path[k]) != _axis(path[k], path[k + 1]) and k not in at:
            node = path[k]
            sides = [_side(node, path[k - 1]), _side(node, path[k + 1])]
            turn = Turn(f'subway_turn_{_key(node)}', node, node[0] * size, node[1] * size,
                        level(node[0] * size, node[1] * size) - TRACK_DEPTH, sides)
            turns.append(turn)
            turn_at[k] = turn
    edges = []
    for k in range(count - 1):
        a, b = path[k], path[k + 1]
        axis = _axis(a, b)
        i = 0 if axis == 'x' else 1
        lo, hi = (k, k + 1) if a[i] < b[i] else (k + 1, k)
        line = a[1] * size if axis == 'x' else a[0] * size

        def trim(index):
            if index in at:
                return STATION / 2 + SHELL, at[index].track
            if index in turn_at:
                return LINE[0] / 2 + SHELL, turn_at[index].track
            node = path[index]
            return 0.0, level(node[0] * size, node[1] * size) - TRACK_DEPTH

        (t0, f0), (t1, f1) = trim(lo), trim(hi)
        start, end = path[lo][i] * size + t0, path[hi][i] * size - t1
        edge = Edge(axis, line, path[lo], path[hi], start, end, [], [], arterial(a, b))
        if end - start > 1e-6:
            edge.sections = _sewers._sections(start, end, line, axis, lambda along: TRACK_DEPTH, level, f0, f1,
                                              False, False)
        else:
            edge.sections = [(start, f0), (end, f1)]
        edges.append(edge)
    subway = Subway(path, stations, turns, edges)
    index = _sewers._StreetIndex(*street) if street is not None else None
    for station in stations:
        _plan_entrances(station, city, level, index, blocked, curb)
    _plan_utilities(subway, city, level, index, blocked, seed, walk)
    return subway


def _station_ends(path, k, axis):
    """Whether the line leaves a station's -along and +along ends."""
    i = 0 if axis == 'x' else 1
    ends = [False, False]
    for other in (path[k - 1] if k > 0 else None, path[k + 1] if k + 1 < len(path) else None):
        if other is not None:
            ends[0 if other[i] < path[k][i] else 1] = True
    return tuple(ends)


def _side(node, other):
    if other[0] != node[0]:
        return '+x' if other[0] > node[0] else '-x'
    return '+y' if other[1] > node[1] else '-y'


def _plan_entrances(station, city, level, index, blocked, curb):
    """Up to two entrances, from the hall's ends up to the kerb lanes."""
    width = 12.0
    for road in city.roads:
        if tuple(station.node) in (tuple(road.a), tuple(road.b)) and _axis(tuple(road.a), tuple(road.b)) == station.axis:
            width = road.width
            break
    clear, wall, headroom = ENTRANCE
    outer = width / 2 - KERB
    across = (outer - wall - clear, outer - wall)
    for sign in (1, -1):
        for side in (sign, -sign):
            span = across if side > 0 else (-across[1], -across[0])
            middle = sum(span) / 2
            start = station.centre + sign * (HALL[0] + HALL_SHELL)
            head = level(*station.point(start + sign * 11.0, middle))
            entrance = None
            for _ in range(3):
                steps = max(1, math.ceil((head - station.hall_floor) / STAIR[1] - 1e-9))
                run = steps * STAIR[2]
                slope = (head - station.hall_floor) / run
                # The ceiling stops where its top would come within 0.1 m of the street.
                opening = None
                for k in range(steps + 1):
                    street = level(*station.point(start + sign * k * STAIR[2], middle))
                    if station.hall_floor + slope * k * STAIR[2] + headroom + HALL_SHELL >= street - .1:
                        opening = k * STAIR[2]
                        break
                if opening is None or run - opening < 1.5:
                    entrance = None
                    break
                buried = min(level(*station.point(start + sign * k * STAIR[2], u))
                             for k in range(int(opening / STAIR[2]) + 1) for u in span) - .05
                entrance = Entrance(f'{station.id}_entrance_{len(station.entrances)}', sign, side, span, start,
                                    run, opening, station.hall_floor, head, steps, buried)
                if index is None:
                    break
                cx, cy, w, d, _ = _entrance_opening(station, entrance)
                top = index.paved((cx - w / 2, cy - d / 2, cx + w / 2, cy + d / 2))
                if top is None:
                    entrance = None
                    break
                if abs(top - head) < 1e-6:
                    break
                head = top
            if entrance is None:
                continue
            if blocked(_entrance_rect(station, entrance), entrance.floor - HALL_SHELL, entrance.top + PARAPET):
                continue
            station.entrances.append(entrance)
            break


def _plan_utilities(subway, city, level, index, blocked, seed, walk):
    """A utility branch on the arterial edge in the middle of each run
    between stations."""
    from . import tunnels
    order = {node: k for k, node in enumerate(subway.path)}
    station_k = sorted(order[s.node] for s in subway.stations)
    for k0, k1 in zip(station_k, station_k[1:]):
        if k1 - k0 < 2:
            continue
        middle = (k0 + k1) // 2
        options = [e for e in subway.edges if e.arterial and {order[e.a], order[e.b]} == {middle, middle + 1}]
        options += [e for e in subway.edges if e.arterial and {order[e.a], order[e.b]} == {middle - 1, middle}]
        for edge in options:
            if edge.length < 12:
                continue
            along = (edge.start + edge.end) / 2
            road_half = 6.0
            room = road_half + walk / 2
            room_half = UTILITY / 2 + UTILITY_SHELL
            floor = edge.floor_at(along) + WALKWAY[1]
            ident = f'subway_utility_{_key(edge.a)}__{_key(edge.b)}'
            line_face = LINE[0] / 2 + SHELL
            start, end = line_face, room - room_half
            if end - start < .05:
                continue
            corridor = tunnels.Tunnel(ident + '_corridor', ident, ident, -1, 'y' if edge.axis == 'x' else 'x',
                                      along, edge.line + start, edge.line + end, floor, floor, '', '', False)
            utility = Utility(ident, edge, along, floor, room, corridor)
            if blocked(utility.room(), floor - UTILITY_SHELL, floor + UTILITY + UTILITY_SHELL):
                continue
            if stream(seed, 'subway-exit', ident).random() < EXIT_SHARE and index is not None:
                x, y = edge.point(along, room)
                half = _sewers.SHAFT / 2 + _sewers.SHAFT_WALL
                top = index.paved((x - half, y - half, x + half, y + half))
                if top is not None:
                    exit_id = f'exit_{_key(edge.a)}__{_key(edge.b)}'
                    utility.exit = _sewers.Manhole(exit_id, ident, x, y, top + _sewers.RIM,
                                                   floor + UTILITY + UTILITY_SHELL,
                                                   stream(seed, 'manhole', exit_id).random() < _sewers.OPEN)
            # The line is level across the doorway, so the corridor meets it flush.
            half = tunnels.WIDTH / 2
            line_level = edge.floor_at(along)
            kept = [(a, f) for a, f in edge.sections if not along - half - 1e-6 <= a <= along + half + 1e-6]
            edge.sections = sorted(kept + [(along - half, line_level), (along + half, line_level)])
            edge.doors.append(along)
            subway.utilities.append(utility)
            break


def connect(subway, sites, network=None, avoid=()):
    """After the sewers and tunnels: doorways from deep basements into the
    halls (the sites' ``doors`` are filled in), and the sewers' doorways
    into the halls from ``network``. ``avoid``: other solids (rect, low,
    high)."""
    from . import tunnels
    if network is not None:
        halls = {c.id: c for c in network.chambers.values() if getattr(c, 'hall', False)}
        for station in subway.stations:
            chamber = halls.get(f'subway_hall_{_key(station.node)}')
            if chamber is not None:
                station.doors = list(chamber.doors)
    have = [s for s in sites if s.level(-2) is not None and s.quarter() is not None]
    boxes = {s.id: s.box(s.outer) for s in sites}
    taken = set()
    for station in subway.stations:
        hall = station.hall()
        m = 0 if station.axis == 'x' else 1           # Along the line.
        n = 1 - m
        for site in have:
            if site.id in taken:
                continue
            box = boxes[site.id]
            for side in (1, -1):
                wall = station.line + side * (HALL_SIDE + HALL_SHELL)
                face = box[n] if side > 0 else box[n + 2]
                gap = (face - wall) * side
                if gap < -1e-6 or gap > ACCESS_REACH:
                    continue
                inner = site.box(site.under.rect)
                need = tunnels.WIDTH / 2 + tunnels.SHELL + .4
                lo = max(inner[m] + need, hall[m] + HALL_SHELL + need)
                hi = min(inner[m + 2] - need, hall[m + 2] - HALL_SHELL - need)
                if hi < lo:
                    continue
                zb = site.floor(-2)
                if abs(zb - station.hall_floor) > .05 + max(gap, .25) * tunnels.SLOPE:
                    continue
                along = None
                for k in range(int((hi - lo) / .5) + 1):
                    trial = (lo + hi) / 2 + .5 * ((k + 1) // 2) * (1 if k % 2 else -1)
                    if not lo - 1e-6 <= trial <= hi + 1e-6:
                        continue
                    probe = face + side * .6
                    px, py = (trial, probe) if station.axis == 'x' else (probe, trial)
                    room = tunnels._room_behind(site, -2, px, py, 'y' if station.axis == 'x' else 'x')
                    if room is not None:
                        along = trial
                        break
                if along is None:
                    continue
                ident = f'access_{site.id}__{station.id}'
                start, end, z0, z1 = (wall, face, station.hall_floor, zb) if side > 0 else (face, wall, zb, station.hall_floor)
                passage = tunnels.Tunnel(ident, site.id, station.id, -2, 'y' if station.axis == 'x' else 'x', along,
                                         start, end, z0, z1, room.name, '', True)
                if passage.length > .05:
                    rect = passage.rect(tunnels.CLEAR)
                    low = min(z0, z1) - tunnels.SHELL
                    high = max(z0, z1) + tunnels.HEIGHT + tunnels.SHELL
                    if any(_overlap(rect, b) for i, b in boxes.items() if i != site.id):
                        continue
                    if any(_overlap(rect, r) and lo2 < high and low < hi2 for r, lo2, hi2 in avoid):
                        continue
                point = (along, face) if station.axis == 'x' else (face, along)
                door_side, door_centre = tunnels._side(site, *point)
                site.doors.append((-2, door_side, door_centre, tunnels.DOOR[0], tunnels.DOOR[1]))
                station.accesses.append(Access(ident, site.id, room.name, passage))
                taken.add(site.id)
                break


# -- geometry ------------------------------------------------------------------


def _profile():
    width, height, vault = LINE
    half = width / 2
    return [(-half, 0.0), (half, 0.0), (half, height - vault), (half - vault, height), (-half + vault, height),
            (-half, height - vault)]


def _line_opening(centre, floor, frame):
    from . import solids
    width, height, vault = LINE
    half = width / 2
    return solids.Opening(centre - half, centre + half, [(centre - half, floor), (centre + half, floor)],
                          [(centre - half, floor + height - vault), (centre - half + vault, floor + height),
                           (centre + half - vault, floor + height), (centre + half, floor + height - vault)],
                          frame, 'door')


def _rect_opening(centre, width, floor, height, frame):
    from . import solids
    return solids.Opening.rect(centre - width / 2, centre + width / 2, floor, floor + height, frame, 'door')


def _slab(mesh, rect, z0, z1, material, holes=()):
    """A slab over a plan rect, round rect holes inside it."""
    from . import solids
    x0, y0, x1, y1 = rect
    holes = [h for h in holes if _overlap(h, rect)]
    xs = sorted({x0, x1} | {min(max(v, x0), x1) for h in holes for v in (h[0], h[2])})
    ys = sorted({y0, y1} | {min(max(v, y0), y1) for h in holes for v in (h[1], h[3])})
    for a0, a1 in zip(xs, xs[1:]):
        for b0, b1 in zip(ys, ys[1:]):
            if a1 - a0 < 1e-5 or b1 - b0 < 1e-5:
                continue
            cx, cy = (a0 + a1) / 2, (b0 + b1) / 2
            if any(h[0] < cx < h[2] and h[1] < cy < h[3] for h in holes):
                continue
            solids.box(mesh, a0, b0, z0, a1, b1, z1, material)


def _room(mesh, x, y, hx, hy, floor, height, shell, openings, material, floor_material,
          floor_holes=(), roof_holes=(), shaft=None):
    """A box's shell round a clear room centred at (x, y): floor, four walls
    with ``openings`` {side: [(world coordinate along the wall, factory)]},
    roof; rect holes in floor and roof, and an octagonal one in the roof
    for ``shaft`` (a sewers.Manhole)."""
    from . import solids
    s = shell
    x0, y0, x1, y1 = x - hx - s, y - hy - s, x + hx + s, y + hy + s
    top = floor + height
    _slab(mesh, (x0, y0, x1, y1), floor - s, floor, floor_material, floor_holes)
    walls = {'-y': ((x0, y0), (1.0, 0.0), x1 - x0, lambda c: c - x0),
             '+y': ((x1, y1), (-1.0, 0.0), x1 - x0, lambda c: x1 - c),
             '-x': ((x0, y + hy), (0.0, -1.0), 2 * hy, lambda c: y + hy - c),
             '+x': ((x1, y - hy), (0.0, 1.0), 2 * hy, lambda c: c - (y - hy))}
    boxes = {'-y': (x0, y0, x1, y0 + s), '+y': (x0, y1 - s, x1, y1),
             '-x': (x0, y - hy, x0 + s, y + hy), '+x': (x1 - s, y - hy, x1, y + hy)}
    for side, (origin, direction, length, local) in walls.items():
        holes = [factory(local(coordinate)) for coordinate, factory in openings.get(side, ())]
        if holes:
            solids.wall_solid(mesh, origin, direction, s, 0.0, length, floor, [(0.0, top), (length, top)],
                              sorted(holes, key=lambda o: o.u0), material)
        else:
            b = boxes[side]
            solids.box(mesh, b[0], b[1], floor, b[2], b[3], top, material)
    holes = list(roof_holes)
    corners = []
    if shaft is not None:
        c = _sewers.SHAFT / 2
        holes.append((shaft.x - c, shaft.y - c, shaft.x + c, shaft.y + c))
        ring = _sewers.octagon(shaft.x, shaft.y, _sewers.SHAFT)
        corners = [[ring[k], corner, ring[k + 1]] for k, corner in
                   zip((0, 2, 4, 6), ((shaft.x + c, shaft.y + c), (shaft.x - c, shaft.y + c),
                                      (shaft.x - c, shaft.y - c), (shaft.x + c, shaft.y - c)))]
    _slab(mesh, (x0, y0, x1, y1), top, top + s, floor_material, holes)
    for triangle in corners:
        _sewers._flat(mesh, triangle, top, top + s, floor_material)


def build(mesh, subway, material, floor_material):
    """The subway's solids in plan coordinates."""
    from . import tunnels
    for edge in subway.edges:
        _edge(mesh, edge, material, floor_material)
    for turn in subway.turns:
        openings = {side: [((turn.y if side[1] == 'x' else turn.x),
                            lambda u, f=turn.track: _line_opening(u, f, floor_material))] for side in turn.sides}
        _room(mesh, turn.x, turn.y, LINE[0] / 2, LINE[0] / 2, turn.track, LINE[1], SHELL, openings, material,
              floor_material)
    for station in subway.stations:
        _station(mesh, station, material, floor_material)
        for access in station.accesses:
            tunnels.build(mesh, access.tunnel, material, floor_material)
    for utility in subway.utilities:
        tunnels.build(mesh, utility.corridor, material, floor_material)
        _utility(mesh, utility, material, floor_material)
        if utility.exit is not None:
            _sewers._shaft(mesh, utility.exit, material)


def _edge(mesh, edge, material, floor_material):
    from . import tunnels
    if edge.length < 1e-4:
        return
    ring = _sewers._ring(_profile(), SHELL)
    width, height, vault = LINE
    half = width / 2
    door_top = WALKWAY[1] + tunnels.HEIGHT
    # The +across wall with a doorway at walkway level: below the sill and above the lintel.
    lower = [ring[1][0], (half, WALKWAY[1]), (half + SHELL, WALKWAY[1]), ring[1][3]]
    upper = [(half, door_top), ring[1][1], ring[1][2], (half + SHELL, door_top)]
    walkway = [(half - WALKWAY[0], 0.0), (half, 0.0), (half, WALKWAY[1]), (half - WALKWAY[0], WALKWAY[1])]
    gaps = [(a - tunnels.WIDTH / 2, a + tunnels.WIDTH / 2) for a in edge.doors]

    def extrude(polygon, a0, a1, mat):
        f0, f1 = edge.floor_at(a0), edge.floor_at(a1)
        _sewers._solid(mesh, [(*edge.point(a0, u), f0 + v) for u, v in polygon],
                       [(*edge.point(a1, u), f1 + v) for u, v in polygon], mat)

    for (a0, _), (a1, _) in zip(edge.sections, edge.sections[1:]):
        if a1 - a0 < 1e-4:
            continue
        door = any(g0 - 1e-6 <= a0 and a1 <= g1 + 1e-6 for g0, g1 in gaps)
        for i, quad in enumerate(ring):
            if door and i == 1:
                extrude(lower, a0, a1, material)
                extrude(upper, a0, a1, material)
                continue
            extrude(quad, a0, a1, floor_material if i == 0 else material)
        extrude(walkway, a0, a1, floor_material)


def _station(mesh, station, material, floor_material):
    from . import solids
    s, track = station, station.track
    half = s.half_across
    L = STATION / 2
    hx, hy = (L, half) if s.axis == 'x' else (half, L)
    end_sides = ('-x', '+x') if s.axis == 'x' else ('-y', '+y')
    openings = {}
    for side, leaves in zip(end_sides, s.ends):
        if leaves:
            openings[side] = [(s.line, lambda u, f=track: _line_opening(u, f, floor_material))]
    stairs = s.stairs()
    roof_holes, hall_holes = [], []
    for sign, across, bottom, steps, rise in stairs:
        slope = rise / STAIR[2]
        # Station roof open where the stair's headroom reaches it; the hall floor where it reaches that.
        ceiling = track + HEADROOM
        open_roof = max(0.0, (ceiling - HEADROOM_STAIR - (track + PLATFORM[1])) / slope - STAIR[2])
        open_hall = max(0.0, (s.hall_floor - HALL_SHELL - HEADROOM_STAIR - (track + PLATFORM[1])) / slope - STAIR[2])
        top = bottom + sign * steps * STAIR[2]
        c0, c1 = across - STAIR[0] / 2, across + STAIR[0] / 2
        roof_holes.append(_rect(s, *sorted((bottom + sign * open_roof, top)), c0, c1))
        hall_holes.append(_rect(s, *sorted((bottom + sign * open_hall, top)), c0, c1))
        # Steps from the platform up.
        for k in range(steps):
            a0, a1 = sorted((bottom + sign * k * STAIR[2], bottom + sign * (k + 1) * STAIR[2]))
            r = _rect(s, a0, a1, c0, c1)
            solids.box(mesh, r[0], r[1], track + PLATFORM[1], r[2], r[3], track + PLATFORM[1] + (k + 1) * rise,
                       floor_material)
        # Walls round the stair between the station's roof and the hall's floor.
        z0, z1 = s.roof, s.hall_floor - HALL_SHELL
        lo, hi = sorted((bottom + sign * open_roof, top))
        w = .2
        for r in (_rect(s, lo - w, hi + w, c0 - w, c0), _rect(s, lo - w, hi + w, c1, c1 + w),
                  _rect(s, lo - w, lo, c0, c1), _rect(s, hi, hi + w, c0, c1)):
            solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, material)
    _room(mesh, s.x, s.y, hx, hy, track, HEADROOM, SHELL, openings, material, floor_material,
          roof_holes=roof_holes)
    # Side platforms, with steps at their ends down to the track bed.
    count, going = END_STEPS
    stop = L - count * going
    for side in (1, -1):
        c0, c1 = sorted((side * LINE[0] / 2, side * half))
        r = _rect(s, s.centre - stop, s.centre + stop, c0, c1)
        solids.box(mesh, r[0], r[1], track, r[2], r[3], track + PLATFORM[1], floor_material)
        for end in (1, -1):
            for k in range(count - 1):
                a0, a1 = sorted((s.centre + end * (stop + k * going), s.centre + end * (stop + (k + 1) * going)))
                r = _rect(s, a0, a1, c0, c1)
                solids.box(mesh, r[0], r[1], track, r[2], r[3], track + PLATFORM[1] * (count - 1 - k) / count,
                           floor_material)
    # The hall above.
    hhx, hhy = (HALL[0], HALL_SIDE) if s.axis == 'x' else (HALL_SIDE, HALL[0])
    hall_openings = {}
    for side, kind in s.doors:
        coordinate = s.y if side[1] == 'x' else s.x
        hall_openings.setdefault(side, []).append(
            (coordinate, lambda u, f=s.hall_floor, k=kind: _sewers._doorway(k, u, f, floor_material)))
    for e in s.entrances:
        side = end_sides[1] if e.sign > 0 else end_sides[0]
        centre = s.line + (e.across[0] + e.across[1]) / 2
        hall_openings.setdefault(side, []).append(
            (centre, lambda u, f=s.hall_floor: _rect_opening(u, ENTRANCE[0], f, ENTRANCE[2], floor_material)))
    for access in s.accesses:
        t = access.tunnel
        hall_side = ('+' if (t.start + t.end) / 2 > s.line else '-') + ('y' if s.axis == 'x' else 'x')
        hall_openings.setdefault(hall_side, []).append(
            (t.line, lambda u, f=s.hall_floor: _rect_opening(u, 1.6, f, 2.1, floor_material)))
    _room(mesh, s.x, s.y, hhx, hhy, s.hall_floor, HALL[1], HALL_SHELL, hall_openings, material, floor_material,
          floor_holes=hall_holes)
    for e in s.entrances:
        _entrance(mesh, s, e, material, floor_material)


def _entrance(mesh, station, e, material, floor_material):
    from . import solids
    clear, wall, headroom = ENTRANCE
    c0, c1 = e.across
    slope = e.rise / STAIR[2]

    def box(a0, a1, u0, u1, z0, z1, mat):
        lo, hi = sorted((e.start + e.sign * a0, e.start + e.sign * a1))
        r = _rect(station, lo, hi, u0, u1)
        solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, mat)

    for k in range(e.steps):
        box(k * STAIR[2], (k + 1) * STAIR[2], c0, c1, e.floor, e.floor + (k + 1) * e.rise, floor_material)
    # Walls: below the street where covered, rising to a parapet over the opening.
    low = e.floor - HALL_SHELL
    buried = e.buried
    for u0, u1 in ((c0 - wall, c0), (c1, c1 + wall)):
        box(0.0, e.open, u0, u1, low, buried, material)
        box(e.open, e.run, u0, u1, low, e.top + PARAPET, material)
    # The sloping ceiling over the covered part, and the parapet across its upper end.
    lo, hi = sorted((e.start, e.start + e.sign * e.open))
    a0, a1 = (lo, hi)
    corners = []
    for z in (headroom, headroom + HALL_SHELL):
        for along, u in ((a0, c0), (a1, c0), (a1, c1), (a0, c1)):
            s = abs(along - e.start)
            corners.append((*station.point(along, u), e.floor + slope * s + z))
    _sewers._solid(mesh, corners[:4], corners[4:], floor_material)
    ceiling_end = e.floor + slope * e.open + headroom
    box(e.open, e.open + wall, c0, c1, ceiling_end, e.top + PARAPET, material)


def _utility(mesh, utility, material, floor_material):
    edge = utility.edge
    x, y = edge.point(utility.along, utility.across)
    half = UTILITY / 2
    side = ('-y' if utility.across > 0 else '+y') if edge.axis == 'x' else ('-x' if utility.across > 0 else '+x')
    coordinate = utility.along
    from . import tunnels
    openings = {side: [(coordinate, lambda u, f=utility.floor: _rect_opening(u, tunnels.WIDTH, f, tunnels.HEIGHT,
                                                                              floor_material))]}
    _room(mesh, x, y, half, half, utility.floor, UTILITY, UTILITY_SHELL, openings, material, floor_material,
          shaft=utility.exit)
