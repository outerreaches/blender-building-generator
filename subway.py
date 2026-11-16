# SPDX-License-Identifier: GPL-3.0-or-later
"""The subway: a line under the arterials from one far district through
the city's centre to another. Pure Python.

The line is a twin-track tunnel, its upper corners vaulted, 14 m under the
street and following its grade, with an evacuation walkway along its left
side (looking along the line). Where it turns at a junction it curves round
under the corner block, 84 m in radius (56 m where turns come closer), so a
train could take it; turns are at least two junctions apart.

Stations stand under junctions where the line runs straight along
arterials, of two kinds: side platforms either side of the tracks, or an
island platform between them, the tracks parting round it over the
station's ends. Above the platforms is a ticket hall at a second
basement's depth, a stair up into it from each platform (two from an
island), a fare line across each end that has an entrance (a fence with
gates either side of a ticket booth), and two bathrooms inside. Entrances
are stairwells from the hall's ends up into the open ground between the
footway and the buildings, a parapet round their opening.

The sewers of a station's junction end in chambers of their own outside the
hall, and a seeded share are joined to it by one or two service rooms
(planned by ``sewers.plan``). Access hallways leave the line's walkway at
seeded intervals: to a utility room (half with a ladder shaft up to a hatch
in the footway), to an emergency exit shaft up to one, or (``connect``) to a
ladder shaft up into the trunk sewer above the line. Deep basements beside a
hall get a doorway or a ladder drop into it (``connect``).
"""
import math
from dataclasses import dataclass, field

from .city_plan import district_at, stream
from . import sewers as _sewers
from .meshdata import (U_SERVICE_FLOOR, U_SERVICE_WALL, U_SEWER_SHAFT, U_STATION_BOOTH, U_STATION_CEILING,
                       U_STATION_EDGE, U_STATION_ENTRANCE, U_STATION_FLOOR, U_STATION_PLATFORM, U_STATION_STAIRS,
                       U_STATION_TILE, U_STATION_WALL, U_SUBWAY_TRACKBED, U_SUBWAY_WALKWAY, U_SUBWAY_WALL,
                       U_TUNNEL_CEILING, U_TUNNEL_FLOOR, U_TUNNEL_WALL)

TRACK_DEPTH = 14.0        # Track bed under the street,
LINE_GRADE = .05          # climbing or falling no more steeply than this away from a station's level.
SIDE_DEEPER = 3.0         # How much deeper than that a station may be set, to keep the line within that grade:
ISLAND_DEEPER = .5        # an island's two stairs from the middle of its platform would meet much deeper.
LINE = (8.6, 5.0, 1.2)    # Clear width and height of the line's tunnel, and its vaulted upper corners.
SHELL = .4                # Floor, walls and roof of the line and its stations.
WALKWAY = (.8, .9)        # Evacuation walkway along the line's left side: width, height,
WALKWAY_STEPS = (4, .3)   # with steps down to the track bed at a run's ends: count (the last at track level), going.
TRACK = 1.9               # Track centres either side of the line's centre.
TRAIN = 1.55              # Track centre to a platform's edge.
TRACK_WALL = 2.4          # Track centre to a station's wall.
CURVE = (84.0, 56.0)      # Radius of a curve where the line turns: wanted, and where turns come two junctions apart.
CURVE_STEP = math.pi / 48  # Angle of a curve's pieces.
TURN_GAP = 2              # Fewest junctions from a turn to the next (or to a station).
LOOP = (5.0, 5.0, 1.0)    # The turning loop past an end station: a single track's tunnel (width, height, vault),
LOOP_RADIUS = 50.0        # its curves' radius,
LOOP_TRACKS = 3.0         # its two ends either side of the line's centre,
SPLIT_LENGTH = 20.0       # beyond a box this long past the station where the tracks part.
TURN_COST = 4.0           # Routing: a turn costs as much as this many junctions of arterial.
STATION = 46.0            # A side platform's length,
ISLAND_LENGTH = 56.0      # an island's (its two stairs stand end to end along it).
SPLAY = 27.0              # Island stations: the tracks part round the platform over this much at each end.
SIDE_PLATFORM = 5.0       # Side platforms' width,
ISLAND = 8.0              # an island platform's,
PLATFORM_HEIGHT = 1.0     # their height over the track bed,
EDGE_STRIP = .5           # and the painted strip along their edges.
ISLAND_SHARE = .5         # Share of stations (not the ends of the line) with an island platform.
HEADROOM = 5.5            # A station's clear height over the track bed.
END_STEPS = (5, .32)      # Steps at a platform's end down to the track bed: count, going.
HALL = (20.0, 3.5, 6.4)   # Ticket hall: half length along the line, clear height, floor under the footway.
HALL_SHELL = .25
HALL_SIDE = 10.0          # Least half width of a hall across the line (wider to take its entrances).
SPACING = 4               # Junctions from one station to the next, about,
SPACING_DOWNTOWN = 2      # and downtown.
STAIR = (2.0, .17, .28)   # Stairs: clear width, rise and going of a step.
STAIR_TOP = {'side': 10.0, 'island': 3.0}    # Along the hall from its middle: where a platform stair arrives
                                              # (an island's two rise from the platform's ends towards the middle).
HEADROOM_STAIR = 2.2
ENTRANCE = (1.8, .2, 2.4) # Street entrance: clear width, wall thickness, headroom.
VERGE = .2                # Earth left between a footway and an entrance's wall.
FACADE = 1.8              # Least ground left between an entrance and a building.
FOOTWAY_ENTRANCE = 1.2    # Narrowest stair for an entrance in the footway (where there is no open ground),
FOOTWAY_EDGE = .1         # kept this far in from the footway's edges (clear of the curb's riser and the skirt).
PARAPET = 1.0             # Height of the parapet round an entrance's opening.
STAIR_PARAPET = 1.0       # and round a platform stair's opening in the hall's floor.
FARE = 4.5                # The fare line: this far in from a hall's end wall,
GATE = 1.4                # with a gate (a gap in the fence) either side of its booth.
FENCE = 2.0               # Height of the fare line's fence (a game prop).
BOOTH = (2.6, 2.0, 2.5, .1)   # Ticket booth: across the hall, along it, height, walls.
WINDOW = (1.4, .9, 1.9)   # Its window towards the entrance: width, sill, head.
SMALL_DOOR = (.8, 2.1)    # Doors of booths and bathrooms.
BATH = (4.2, 4.8)         # Each of the two bathrooms: along the hall, across it (clear).
PARTITION = .15           # Their walls.
STALL = (1.0, 1.6, 2.0, .05, .7)  # Stalls: width, depth, height, panels, door gap.
SERVICE_DOOR = (1.2, 2.1)  # Doors into service rooms, hallways and halls.
KIOSK = (3.0, 2.0, 2.6, .1)   # Kiosks against a hall's side wall: along it, deep, high, walls;
KIOSK_WINDOW = (2.0, .9, 2.0)  # their serving window: width, sill, head;
KIOSK_KINDS = ('newsstand', 'convenience')   # what they sell (one, sometimes two, per hall).
BENCH = (1.8, .5)         # Benches (game props): length, depth;
BENCH_EVERY = 7.0         # along a platform about this far apart,
BIN_SHARE = .5            # a bin beside about half of them.
UTILITY = 2.4             # Utility room off a hallway, square, clear (as high);
EXIT_ROOM = 2.4           # the room at the foot of an emergency exit (wider than the 2 m corridor and its walls).
UTILITY_SHELL = .25
EXIT_SHARE = .5           # Share of utility rooms with a ladder shaft up to the street.
HALLWAY_EVERY = 70.0      # Mean spacing of access hallways along the line,
HALLWAY_KINDS = (('utility', .45), ('sewer', .3), ('exit', .25))   # and what they lead to.
HALLWAY_CLEAR = 7.0       # Least distance from a hallway to a junction or a piece's end.
RISER = (1.2, .2)         # A hallway's ladder shaft up to a sewer: clear depth across the line, walls.
ACCESS_REACH = 16.0       # Longest passage from a basement into a hall,
ACCESS_ALONG = 32.0       # and how far past a hall's end a basement may be reached round a corner.
CORNER_ROOM = (2.4, 2.6)  # The room where such an access turns: clear size (square), height.
ACCESS_DROP_STYLES = ('DOWNTOWN', 'OLD_TOWN', 'BRUTALIST')   # Their first storeys drop into a hall by a ladder.
PAD_REACH = 6.0           # How far under a site's pad nothing may come (its pad is 0.35 m; the line is deeper).
LINE_TIERS = {'ARTERIAL': 1.0, 'COLLECTOR': 2.5, 'LOCAL': 4.0}   # Routing cost per junction of each street.
STATION_TIERS = ('ARTERIAL', 'COLLECTOR')
MIN_STOPS = 6             # Shortest line, in junctions.


def _key(node):
    return f'{node[0]}_{node[1]}'


def _overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@dataclass
class Stretch:
    """Something along a lattice axis: ``point(along, across)`` maps to plan."""
    axis: str
    line: float

    def point(self, along, across=0.0):
        return (along, self.line + across) if self.axis == 'x' else (self.line + across, along)


def _rect(stretch, a0, a1, c0, c1):
    """A plan rect from along and across ranges of a stretch."""
    (x0, y0), (x1, y1) = stretch.point(a0, c0), stretch.point(a1, c1)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _left(axis, heading):
    """The across sign of the left side, looking along ``heading`` (+1/-1) on ``axis``."""
    return heading if axis == 'x' else -heading


@dataclass
class Straight(Stretch):
    """A straight piece of the line along a lattice axis, from ``start`` to
    ``end`` (start < end), its track bed at ``sections`` [(along, level)]."""
    start: float = 0.0
    end: float = 0.0
    heading: int = 1          # +1: the line runs towards +along here.
    sections: list = field(default_factory=list)
    doors: list = field(default_factory=list)      # Hallway doorways in its left wall: centre along.
    steps: tuple = (False, False)                  # Walkway steps down at its start, at its end.
    spots: list = field(default_factory=list)      # Hallways to the sewer above, for ``connect``: along.
    halves: list = field(default_factory=list)     # Road half widths over it: [(from, to, half)].

    @property
    def length(self):
        return self.end - self.start

    @property
    def left(self):
        return _left(self.axis, self.heading)

    def floor_at(self, along):
        return _sewers.Sewer.floor_at(self, along)

    def road_half(self, along):
        return next((h for a0, a1, h in self.halves if a0 - 1e-6 <= along <= a1 + 1e-6), 0.0)

    def frame(self, along):
        """(x, y, track bed, left normal x, y) at ``along``."""
        x, y = self.point(along)
        nx, ny = (0.0, float(self.left)) if self.axis == 'x' else (float(self.left), 0.0)
        return (x, y, self.floor_at(along), nx, ny)

    def rect(self, grow=0.0):
        return _rect(self, self.start - grow, self.end + grow, -LINE[0] / 2 - SHELL - grow, LINE[0] / 2 + SHELL + grow)

    def span(self):
        floors = [f for _, f in self.sections]
        return min(floors) - SHELL, max(floors) + LINE[1] + SHELL

    def add_door(self, along):
        """A doorway in the left wall: the line is level across it, so the
        hallway meets the walkway flush."""
        from . import tunnels
        half = tunnels.WIDTH / 2
        level = self.floor_at(along)
        # (Samples just outside it go too, so no sliver of a slope is left beside the level part.)
        margin = half + .3
        kept = [(a, f) for a, f in self.sections if not along - margin - 1e-6 <= a <= along + margin + 1e-6
                or a in (self.start, self.end)]
        self.sections = sorted(kept + [(along - half, level), (along + half, level)])
        self.doors.append(along)


@dataclass
class Bend:
    """A curve of the line round a turn: an arc about (cx, cy) from angle
    ``a0`` to ``a1`` (of the radius to the line's centre), its track bed from
    ``z0`` to ``z1``."""
    id: str
    node: tuple
    cx: float
    cy: float
    radius: float
    a0: float
    a1: float
    z0: float
    z1: float
    width: float = LINE[0]    # The tunnel's clear width (a turning loop's is one track's).

    @property
    def length(self):
        return self.radius * abs(self.a1 - self.a0)

    @property
    def loop(self):
        return self.width < LINE[0] - 1e-6

    def frames(self):
        count = max(1, math.ceil(abs(self.a1 - self.a0) / CURVE_STEP - 1e-9))
        sense = 1.0 if self.a1 > self.a0 else -1.0
        found = []
        for k in range(count + 1):
            t = k / count
            a = self.a0 + (self.a1 - self.a0) * t
            rx, ry = math.cos(a), math.sin(a)
            # Turning left (anticlockwise) the centre is on the left.
            nx, ny = (-rx, -ry) if sense > 0 else (rx, ry)
            found.append((self.cx + self.radius * rx, self.cy + self.radius * ry,
                          self.z0 + (self.z1 - self.z0) * t, nx, ny))
        return found

    def pieces(self, grow=0.0):
        """Per chord a plan box round it and its height range: (rect, low, high)."""
        found = []
        frames = self.frames()
        half = self.width / 2 + SHELL + grow
        for f0, f1 in zip(frames, frames[1:]):
            xs = [f[0] + s * half * f[3] for f in (f0, f1) for s in (-1, 1)]
            ys = [f[1] + s * half * f[4] for f in (f0, f1) for s in (-1, 1)]
            found.append(((min(xs), min(ys), max(xs), max(ys)), min(f0[2], f1[2]) - SHELL,
                          max(f0[2], f1[2]) + LINE[1] + SHELL))
        return found


@dataclass
class Loop:
    """A turning loop past ``station``'s ``sign`` end: a level box from its
    end wall where the tracks part (along ``split``), then single-track
    ``bends`` from the box's left opening round and back into its right."""
    station: object
    sign: int
    split: tuple
    bends: list

    def rect(self):
        s = self.station
        half = LOOP_TRACKS + LOOP[0] / 2 + SHELL
        return _rect(s, min(self.split), max(self.split), -half, half)


@dataclass
class Run:
    """The line between two stations: straights and bends in the line's
    direction, from ``a``'s end wall to ``b``'s."""
    id: str
    a: object
    b: object
    pieces: list = field(default_factory=list)

    @property
    def straights(self):
        return [p for p in self.pieces if isinstance(p, Straight)]

    @property
    def length(self):
        return sum(p.length for p in self.pieces)

    def frames(self):
        """The centre line's frames from end to end, in the line's direction."""
        found = []
        for p in self.pieces:
            if isinstance(p, Bend):
                frames = p.frames()
            else:
                alongs = [a for a, _ in p.sections]
                frames = [p.frame(a) for a in (alongs if p.heading > 0 else alongs[::-1])]
            for f in frames:
                if found and math.hypot(f[0] - found[-1][0], f[1] - found[-1][1]) < 1e-6:
                    continue
                found.append(f)
        return found


@dataclass
class Entrance:
    id: str
    sign: int             # Which way along the line it climbs from the hall.
    side: int             # Which side of the line.
    across: tuple         # Clear width across the line: (from, to).
    start: float          # Along the line: its foot at the hall's wall,
    run: float            # its length,
    open: float           # where its ceiling stops and the ground is open over it,
    floor: float          # the hall's floor,
    top: float            # the ground at its head.
    steps: int
    buried: float = 0.0   # Lowest ground over its covered part, less a little: its walls' top there.
    place: str = 'ground'  # 'ground' (beside the footway) or 'footway' (in it, where there is no open ground).

    @property
    def rise(self):
        return (self.top - self.floor) / self.steps


@dataclass
class Access:
    id: str
    site: str
    room: str
    tunnel: object        # A tunnels.Tunnel from the basement's wall to the hall's (or to a drop's shaft).
    along: float = 0.0    # Along the line,
    side: int = 1         # on which side of the hall.
    storey: int = -2
    drop: tuple = None    # A ladder shaft beside the hall, as sewers.drop_shaft takes it.
    lead: object = None   # Round a corner: a tunnels.Tunnel along the street from the hall's end wall,
    corner: object = None  # a sewers.ServiceRoom where it turns (``tunnel`` then runs on to the basement),
    wall: str = ''        # and the hall's end wall it comes through ('a+', 'a-'),
    door: float = 0.0     # at this world coordinate along it.

    @property
    def route(self):
        return 'corner' if self.corner is not None else 'straight'


@dataclass
class FareLine:
    """Across a hall, ``at`` from its middle (hall coordinates): fence pieces
    and gates as (from, to) across, and the booth's middle across."""
    sign: int
    at: float
    fences: list
    gates: list
    booth: float


@dataclass
class Bathrooms:
    """Two bathrooms side by side against one of a hall's side walls (hall
    coordinates): along ``a0``..``a1``, across from ``c0`` to the wall."""
    side: int
    a0: float
    a1: float
    c0: float

    def rooms(self):
        """Each room's clear range along: [(from, to)]."""
        t = PARTITION
        mid = (self.a0 + self.a1) / 2
        return [(self.a0 + t, mid - t / 2), (mid + t / 2, self.a1 - t)]


@dataclass
class Kiosk:
    """A kiosk against one of a hall's side walls (hall coordinates): along
    ``a0``..``a1``, its front (with the serving window) at ``c0``."""
    id: str
    kind: str
    side: int
    a0: float
    a1: float
    c0: float


@dataclass
class Station(Stretch):
    id: str = ''
    node: tuple = None
    x: float = 0.0
    y: float = 0.0
    track: float = 0.0
    hall_floor: float = 0.0
    ends: tuple = (True, True)     # Whether the line leaves the -along and +along ends.
    kind: str = 'side'             # 'side' or 'island' platforms.
    heading: int = 1               # The line's direction through it.
    road_half: float = 6.0
    walk: float = 2.0
    side_half: float = HALL_SIDE   # The hall's clear half width.
    entrances: list = field(default_factory=list)
    accesses: list = field(default_factory=list)
    links: list = field(default_factory=list)      # sewers.Link: service rooms from the sewers.
    fares: list = field(default_factory=list)
    baths: object = None
    kiosks: list = field(default_factory=list)
    loop_sign: int = 0             # The end (along its axis) a turning loop leaves from, if it has one.
    furniture: list = field(default_factory=list)  # (type, along from the middle, across, level, facing (along, across)).
    taken: list = field(default_factory=list)      # Hall floor in use: (a0, a1, c0, c1) in hall coordinates.

    @property
    def centre(self):
        return self.x if self.axis == 'x' else self.y

    @property
    def platform_length(self):
        return ISLAND_LENGTH if self.kind == 'island' else STATION

    @property
    def half_length(self):
        return self.platform_length / 2 + (SPLAY if self.kind == 'island' else 0.0)

    @property
    def half_across(self):
        if self.kind == 'island':
            return ISLAND / 2 + TRAIN + TRACK_WALL
        return TRACK + TRAIN + SIDE_PLATFORM

    @property
    def track_offset(self):
        """Track centres from the middle along the platforms."""
        return ISLAND / 2 + TRAIN if self.kind == 'island' else TRACK

    @property
    def roof(self):
        return self.track + HEADROOM + SHELL

    def box(self, grow=0.0):
        return _rect(self, self.centre - self.half_length - SHELL - grow, self.centre + self.half_length + SHELL + grow,
                     -self.half_across - SHELL - grow, self.half_across + SHELL + grow)

    def hall(self, grow=0.0):
        return _rect(self, self.centre - HALL[0] - HALL_SHELL - grow, self.centre + HALL[0] + HALL_SHELL + grow,
                     -self.side_half - HALL_SHELL - grow, self.side_half + HALL_SHELL + grow)

    def hall_span(self):
        return self.hall_floor - HALL_SHELL, self.hall_floor + HALL[1] + HALL_SHELL

    def hall_rect(self, a0, a1, c0, c1):
        """A plan rect from hall coordinates (along from the middle, across)."""
        return _rect(self, self.centre + min(a0, a1), self.centre + max(a0, a1), min(c0, c1), max(c0, c1))

    def platforms(self):
        """Across ranges of the platforms' tops."""
        if self.kind == 'island':
            return [(-ISLAND / 2, ISLAND / 2)]
        edge = TRACK + TRAIN
        return [(edge, edge + SIDE_PLATFORM), (-edge - SIDE_PLATFORM, -edge)]

    def stairs(self):
        """The stairs from the platforms up into the hall: (sign along, across
        centre, bottom along, steps, rise)."""
        rise_total = self.hall_floor - (self.track + PLATFORM_HEIGHT)
        steps = math.ceil(rise_total / STAIR[1] - 1e-9)
        run = steps * STAIR[2]
        found = []
        for sign in (1, -1):
            top = self.centre + sign * STAIR_TOP[self.kind]
            if self.kind == 'island':
                # Down the middle of the island, its foot towards the platform's end: it climbs back towards the
                # middle, the two stairs' heads apart.
                found.append((-sign, 0.0, top + sign * run, steps, rise_total / steps))
            else:
                # Against the platform's back wall, leaving its front free.
                across = sign * (self.half_across - .1 - STAIR[0] / 2)
                found.append((sign, across, top - sign * run, steps, rise_total / steps))
        return found

    def stair_holes(self):
        """Where each stair comes up through the hall's floor (hall coordinates)."""
        found = []
        for sign, across, bottom, steps, rise in self.stairs():
            slope = rise / STAIR[2]
            opening = max(0.0, (self.hall_floor - HALL_SHELL - HEADROOM_STAIR - (self.track + PLATFORM_HEIGHT))
                          / slope - STAIR[2])
            top = bottom + sign * steps * STAIR[2]
            a0, a1 = sorted((bottom + sign * opening - self.centre, top - self.centre))
            found.append((a0, a1, across - STAIR[0] / 2, across + STAIR[0] / 2))
        return found

    def stair_openings(self):
        """Each stair's opening in the hall's floor: (along from, to (world),
        across from, to, climbing direction)."""
        found = []
        for sign, across, bottom, steps, rise in self.stairs():
            slope = rise / STAIR[2]
            opening = max(0.0, (self.hall_floor - HALL_SHELL - HEADROOM_STAIR - (self.track + PLATFORM_HEIGHT))
                          / slope - STAIR[2])
            top = bottom + sign * steps * STAIR[2]
            a0, a1 = sorted((bottom + sign * opening, top))
            found.append((a0, a1, across - STAIR[0] / 2, across + STAIR[0] / 2, sign))
        return found

    def clear(self, a0, a1, c0, c1):
        """Whether a piece of the hall's floor (hall coordinates) is free."""
        a0, a1 = sorted((a0, a1))
        c0, c1 = sorted((c0, c1))
        if a0 < -HALL[0] - 1e-6 or a1 > HALL[0] + 1e-6 or c0 < -self.side_half - 1e-6 or c1 > self.side_half + 1e-6:
            return False
        return not any(a0 < t1 and t0 < a1 and c0 < u1 and u0 < c1 for t0, t1, u0, u1 in self.taken)

    def wall_spot(self, wall, coordinate, width=SERVICE_DOOR[0]):
        """The floor inside a doorway in the hall's wall: ``wall`` 'a+',
        'a-' (ends) or 'c+', 'c-' (sides), at ``coordinate`` along it (hall
        coordinates)."""
        depth, w = 1.5, width / 2 + .3
        if wall[0] == 'a':
            s = 1 if wall[1] == '+' else -1
            return (s * (HALL[0] - depth), s * HALL[0], coordinate - w, coordinate + w)
        s = 1 if wall[1] == '+' else -1
        return (coordinate - w, coordinate + w, s * (self.side_half - depth), s * self.side_half)

    def take(self, a0, a1, c0, c1):
        self.taken.append((min(a0, a1), max(a0, a1), min(c0, c1), max(c0, c1)))


@dataclass
class Utility:
    """A room at the end of a hallway off the line: under the footway on the
    line's left, ``size`` clear; an emergency exit's is small."""
    id: str
    piece: object
    along: float
    floor: float
    across: float         # Centre of its room.
    corridor: object      # tunnels.Tunnel from the line's wall to the room's.
    kind: str = 'utility'  # Or 'exit'.
    exit: object = None   # A sewers.Manhole up to the street, if it has one.

    @property
    def size(self):
        return EXIT_ROOM if self.kind == 'exit' else UTILITY

    def room(self, grow=0.0):
        half = self.size / 2 + UTILITY_SHELL + grow
        return _rect(self.piece, self.along - half, self.along + half, self.across - half, self.across + half)


@dataclass
class Riser:
    """A hallway's ladder shaft from the walkway up beside the line, and a
    passage over the line's roof into the trunk sewer above it."""
    id: str
    piece: object
    along: float
    sewer: str
    side: int             # Across sign of the shaft (the line's left).
    floor: float          # The walkway's level,
    top_floor: float      # the passage's (the sewer's floor).
    passage: object       # tunnels.Tunnel from the sewer's wall to the shaft.

    @property
    def near(self):
        return self.side * (LINE[0] / 2 + SHELL)

    @property
    def far(self):
        return self.near + self.side * (2 * RISER[1] + RISER[0])

    @property
    def top(self):
        from . import tunnels
        return self.top_floor + tunnels.HEIGHT + tunnels.SHELL

    def rect(self):
        from . import tunnels
        half = tunnels.WIDTH / 2 + RISER[1]
        lo, hi = sorted((self.near, self.far))
        return _rect(self.piece, self.along - half, self.along + half, lo, hi)


@dataclass
class Subway:
    path: list
    stations: list
    runs: list
    utilities: list = field(default_factory=list)
    risers: list = field(default_factory=list)
    size: float = 56.0        # The lattice's block size.
    loops: list = field(default_factory=list)

    @property
    def exits(self):
        return [u.exit for u in self.utilities if u.exit is not None]

    @property
    def straights(self):
        return [p for r in self.runs for p in r.straights]

    @property
    def bends(self):
        return [p for r in self.runs for p in r.pieces if isinstance(p, Bend)]

    def halls(self):
        """Stations by junction, for ``sewers.plan``."""
        return {s.node: s for s in self.stations}

    def solids(self, halls=True):
        """World boxes with their height ranges nothing else may enter: (rect,
        low, high)."""
        from . import tunnels
        found = [(p.rect(), *p.span()) for p in self.straights if p.length > 1e-6]
        for b in self.bends:
            found += b.pieces()
        for loop in self.loops:
            found.append((loop.rect(), loop.station.track - SHELL, loop.station.track + LINE[1] + SHELL))
            for b in loop.bends:
                found += b.pieces()
        for s in self.stations:
            found.append((s.box(), s.track - SHELL, s.roof))
            if halls:
                found.append((s.hall(), *s.hall_span()))
            for e in s.entrances:
                found.append((_entrance_rect(s, e), e.floor - HALL_SHELL, e.top + PARAPET))
            for a in s.accesses:
                if a.drop is not None:
                    wall, far, zs, _, top = a.drop
                    lo, hi = sorted((wall, far))
                    found.append((_rect(s, a.along - 1.2, a.along + 1.2, lo - s.line, hi - s.line), zs - .2, top))
                if a.lead is not None:
                    t, r = a.lead, a.corner
                    found.append((t.rect(), min(t.za, t.zb) - tunnels.SHELL, max(t.za, t.zb) + tunnels.HEIGHT + tunnels.SHELL))
                    found.append((r.rect(), r.floor - UTILITY_SHELL, r.floor + r.height + UTILITY_SHELL))
        for u in self.utilities:
            found.append((u.room(), u.floor - UTILITY_SHELL, u.floor + u.size + UTILITY_SHELL))
            found.append((u.corridor.rect(), u.floor - .2, u.floor + 2.4))
            if u.exit is not None:
                found.append((u.exit.rect(), u.exit.base, u.exit.rim))
        for r in self.risers:
            found.append((r.rect(), r.floor - RISER[1], r.top))
            found.append((r.passage.rect(), r.top_floor - tunnels.SHELL, r.top))
        return found

    def lifts(self):
        """Where the footways' skirts must stop short: over the ladder shafts
        of drops into halls (rect, top)."""
        found = []
        for s in self.stations:
            for a in s.accesses:
                if a.drop is not None:
                    wall, far, _, _, top = a.drop
                    lo, hi = sorted((wall, far))
                    found.append((_rect(s, a.along - 1.2, a.along + 1.2, lo - s.line, hi - s.line), top))
        return found

    def openings(self):
        """Ground (and street and paint) cuts: entrances' open stairwells (as
        rectangles) and exit shafts (octagons)."""
        found = []
        for s in self.stations:
            for e in s.entrances:
                found.append(_entrance_opening(s, e))
        found += [_sewers.octagon(m.x, m.y, m.outer) for m in self.exits]
        return found

    def surface(self):
        """Plan rects at ground level that the entrances' stairwells and
        parapets take (props keep off them)."""
        return [_entrance_surface(s, e) for s in self.stations for e in s.entrances]


def _entrance_rect(station, e):
    a0, a1 = sorted((e.start, e.start + e.sign * e.run))
    return _rect(station, a0, a1, e.across[0] - ENTRANCE[1], e.across[1] + ENTRANCE[1])


def _entrance_surface(station, e):
    a0, a1 = sorted((e.start + e.sign * e.open, e.start + e.sign * e.run))
    return _rect(station, a0, a1, e.across[0] - ENTRANCE[1], e.across[1] + ENTRANCE[1])


def _entrance_opening(station, e):
    x0, y0, x1, y1 = _entrance_surface(station, e)
    return ((x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0, 0.0)


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


def _route(graph, start, goal, banned=(), state=None, settle=0, no_turn=()):
    """Cheapest path on which the line turns at least TURN_GAP junctions
    after its start and its last turn, never at ``no_turn``, never back on
    itself; ``state`` (heading, since) carries on from a previous leg and the
    path must end ``settle`` junctions after its last turn. Returns (path,
    end state) or None; deterministic on ties."""
    import heapq
    heading, since = state if state is not None else ((0, 0), 0)
    first = (start, heading, since)
    best = {first: 0.0}
    back = {}
    heap = [(0.0, start, heading, since)]
    while heap:
        cost, node, h, s = heapq.heappop(heap)
        key = (node, h, s)
        if node == goal and s >= settle:
            path = [key]
            while path[-1] != first:
                path.append(back[path[-1]])
            return [k[0] for k in path[::-1]], (h, s)
        if cost > best.get(key, math.inf):
            continue
        for other, weight, _ in sorted(graph.get(node, ())):
            if other in banned and other != goal:
                continue
            d = (other[0] - node[0], other[1] - node[1])
            if h != (0, 0) and d == (-h[0], -h[1]):
                continue
            turning = h != (0, 0) and d != h
            if turning and (s < TURN_GAP or node in no_turn):
                continue
            ns = 1 if turning else min(TURN_GAP + 1, s + 1)
            total = cost + weight + (TURN_COST if turning else 0.0)
            nkey = (other, d, ns)
            if total < best.get(nkey, math.inf) - 1e-9:
                best[nkey] = total
                back[nkey] = key
                heapq.heappush(heap, (total, other, d, ns))
    return None


def _nearest(graph, node):
    return min(graph, key=lambda n: (abs(n[0] - node[0]) + abs(n[1] - node[1]), n)) if graph else None


def _line_path(city, graph, no_turn=()):
    """From a far district through the centre to another, on the far side."""
    centre = next((tuple(loc.node) for loc in city.locations if loc.role == 'CENTER'), (0, 0))
    c = _nearest(graph, centre)
    ends = sorted({_nearest(graph, tuple(loc.node)) for loc in city.locations if loc.role == 'PRIMARY'} - {c})
    pairs = []
    for i, p in enumerate(ends):
        for q in ends[i + 1:]:
            ux, uy = p[0] - c[0], p[1] - c[1]
            vx, vy = q[0] - c[0], q[1] - c[1]
            lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
            if lu < 3 or lv < 3 or (ux * vx + uy * vy) / (lu * lv) > -.5:
                continue
            pairs.append((-(lu + lv), p, q))
    # The farthest pair that can be routed (a diagonal pair may only be reached by streets that turn at
    # every junction, which a train cannot take).
    for _, p, q in sorted(pairs):
        for a, b in ((p, q), (q, p)):
            first = _route(graph, a, c, no_turn=no_turn)
            if first is None:
                continue
            second = _route(graph, c, b, banned=set(first[0]), state=first[1], settle=TURN_GAP, no_turn=no_turn)
            if second is None:
                continue
            path = first[0] + second[0][1:]
            if len(path) >= MIN_STOPS:
                return path
    return None


def _axis(a, b):
    return 'x' if a[1] == b[1] else 'y'


def plan(city, surface=None, sites=(), street=None, avoid=(), below=()):
    """The subway of a city, or None. ``surface(x, y)``: road level;
    ``sites``: basements to keep clear of; ``street``: the street mesh as
    (vertices, faces, materials), for entrances and exits (None: none);
    ``avoid``: world boxes nothing may pass under (site pads); ``below``:
    other solids it must keep out of, (rect, low, high) (deep foundations)."""
    seed = city.settings.seed
    level = surface or (lambda x, y: 0.0)
    graph = _graph(city)
    boxes = [(site.box(site.outer), site.base + site.under.depth, site.base) for site in sites]

    def blocked(rect, low, high, pads=True):
        # Nothing comes up under a site's pad; the line and its stations, deep, pass under it, and a hall's
        # edge may (a pad lies on the graded ground: the hall's roof is 2.5 m under it).
        if pads and any(_overlap(rect, box) for box in avoid) and \
                high > level((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2) - PAD_REACH:
            return True
        if any(_overlap(rect, box) and low < top and bottom < high for box, bottom, top in below):
            return True
        return any(_overlap(rect, box) and low < top + .3 and bottom - .3 < high for box, bottom, top in boxes)

    no_turn = set()
    subway = None
    for _ in range(8):
        path = _line_path(city, graph, no_turn)
        if path is None:
            return None
        result = _layout(city, graph, path, level, blocked)
        if isinstance(result, tuple):
            no_turn.add(result[1])      # A curve there cannot be built: route round it.
            continue
        subway = result
        break
    if subway is None:
        return None
    index = _sewers._StreetIndex(*street) if street is not None else None
    lots = _lot_shapes(city)
    yards = _yard_shapes(city)
    for station in subway.stations:
        _plan_entrances(station, level, index, blocked, lots, avoid, yards)
        _plan_hall(station, seed)
        _plan_furniture(station, seed)
    _plan_hallways(subway, level, index, blocked, seed)
    return subway


def _layout(city, graph, path, level, blocked):
    """Stations, runs and curves along a path: a Subway, None if it has no
    two stations, or ('turn', node) if a curve cannot be built there."""
    size = city.settings.block_size
    seed = city.settings.seed
    curb = city.settings.curb_height
    walk = city.settings.sidewalk_width
    tiers, widths = {}, {}
    for node, links in graph.items():
        for other, _, tier in links:
            tiers[tuple(sorted((node, other)))] = tier
    for road in city.roads:
        widths[tuple(sorted((tuple(road.a), tuple(road.b))))] = road.width

    count = len(path)
    turns = [k for k in range(1, count - 1) if _axis(path[k - 1], path[k]) != _axis(path[k], path[k + 1])]

    def turn_gap(k):
        return min((abs(k - t) for t in turns), default=99)

    # Stations: at both ends and every few junctions where the line runs straight (along arterials or
    # collectors: the hall takes the street's width), clear of its curves.
    candidates = []
    for k, node in enumerate(path):
        before = path[k - 1] if k > 0 else None
        after = path[k + 1] if k + 1 < count else None
        if before is not None and after is not None and _axis(before, node) != _axis(node, after):
            continue
        if turn_gap(k) < TURN_GAP:
            continue
        # Stations on main streets only (the line may take a local street between them).
        if any(other is not None and tiers.get(tuple(sorted((node, other)))) not in STATION_TIERS
               for other in (before, after)):
            continue
        candidates.append(k)

    def spacing(k):
        x, y = path[k][0] * size, path[k][1] * size
        downtown = district_at(city.settings, x, y, city.locations).style == 'DOWNTOWN'
        return SPACING_DOWNTOWN if downtown else SPACING

    chosen = []
    for k in candidates:
        if k in (0, count - 1) or not chosen or k - chosen[-1] >= spacing(k):
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
        i = 0 if axis == 'x' else 1
        nxt = path[k + 1] if k + 1 < count else None
        heading = (1 if nxt[i] > node[i] else -1) if nxt is not None else (1 if node[i] > path[k - 1][i] else -1)
        line = y if axis == 'x' else x
        ident = f'subway_station_{_key(node)}'
        width = widths.get(tuple(sorted((node, other))), 12.0)
        middle = 0 < k < count - 1
        kinds = ['island', 'side'] if (middle and turn_gap(k) >= TURN_GAP + 1 and
                                       stream(seed, 'station-kind', ident).random() < ISLAND_SHARE) else ['side']
        entrance_outer = width / 2 + walk + VERGE + 2 * ENTRANCE[1] + ENTRANCE[0]
        for kind in kinds:
            station = Station(axis, line, ident, node, x, y, level(x, y) - TRACK_DEPTH, level(x, y) + curb - HALL[2],
                              _station_ends(path, k, axis), kind, heading, width / 2, walk,
                              max(HALL_SIDE, entrance_outer - ENTRANCE[1]))
            if blocked(station.hall(), *station.hall_span(), pads=False) or blocked(station.box(), station.track - SHELL,
                                                                       station.roof):
                continue
            stations.append(station)
            at[k] = station
            break
    if len(stations) < 2:
        return None
    first, last = min(at), max(at)
    path_k = list(range(first, last + 1))
    # Curves: as wide as the turns either side allow.
    radius = {}
    for t in turns:
        if not first < t < last:
            continue
        others = [abs(t - u) for u in turns if u != t and first < u < last]
        near = min(others, default=99)
        radius[t] = CURVE[0] if near >= TURN_GAP + 1 else CURVE[1]
        for k, s in at.items():
            room = abs(t - k) * size - s.half_length - SHELL - 2 * WALKWAY_STEPS[0] * WALKWAY_STEPS[1]
            radius[t] = min(radius[t], room)
        if radius[t] < CURVE[1] - 1e-6:
            return ('turn', path[t])
    order = sorted(at)
    _settle_stations(order, at, path, radius, size)
    runs = []
    for ka, kb in zip(order, order[1:]):
        run = _run(path, ka, kb, at[ka], at[kb], radius, level, size, widths)
        for bend in (p for p in run.pieces if isinstance(p, Bend)):
            if any(blocked(*piece) for piece in bend.pieces()):
                if bend.radius > CURVE[1] + 1e-6:
                    # Try the tighter curve before routing round the turn.
                    t = next(k for k in radius if path[k] == bend.node)
                    radius[t] = CURVE[1]
                    run = _run(path, ka, kb, at[ka], at[kb], radius, level, size, widths)
                    tight = next(p for p in run.pieces if isinstance(p, Bend) and p.node == bend.node)
                    if not any(blocked(*piece) for piece in tight.pieces()):
                        continue
                return ('turn', bend.node)
        if any(blocked(p.rect(), *p.span()) for p in run.straights if p.length > 1e-6):
            return None
        runs.append(run)
    subway = Subway([path[k] for k in path_k], stations, runs, size=size)
    ends = [(runs[0].a, -runs[0].a.heading), (runs[-1].b, runs[-1].b.heading)]
    for station, sign in ends:
        loop = _plan_loop(station, sign, level, blocked)
        if loop is not None:
            subway.loops.append(loop)
    return subway


def _plan_loop(station, sign, level, blocked):
    """A turning loop past an end station's ``sign`` end (along its axis),
    turning left first or (if that is blocked) right first; None if neither
    can be built (the line then ends at the station's wall)."""
    s = station
    face = s.centre + sign * (s.half_length + SHELL)
    far = face + sign * SPLIT_LENGTH
    split = (face, far)
    box = _rect(s, min(split), max(split), -LOOP_TRACKS - LOOP[0] / 2 - SHELL, LOOP_TRACKS + LOOP[0] / 2 + SHELL)
    if blocked(box, s.track - SHELL, s.track + LINE[1] + SHELL):
        return None
    ex, ey = s.point(far)
    hx, hy = (float(sign), 0.0) if s.axis == 'x' else (0.0, float(sign))
    for hand in (1, -1):
        bends = _loop_bends(s, (ex, ey), (hx, hy), hand, level)
        if bends is None:
            continue
        if not any(blocked(*piece) for b in bends for piece in b.pieces()):
            s.loop_sign = sign
            return Loop(s, sign, split, bends)
    return None


def _loop_bends(s, end, heading, hand, level):
    """Three arcs from the splitter's ``hand`` opening (+1: the left one,
    looking out) round and back into the other: out by alpha towards that
    side, round by 180 degrees and twice alpha the other way, back by alpha.
    Alpha is what brings it back exactly."""
    r, t = LOOP_RADIUS, LOOP_TRACKS
    cos_a = (t + r) / (2 * r)
    if not -1 < cos_a < 1:
        return None
    alpha = math.acos(cos_a)
    hx, hy = heading
    nx, ny = -hy, hx                          # Left of the heading.
    px, py = end[0] + hand * t * nx, end[1] + hand * t * ny
    arcs = []
    for turn, angle in ((hand, alpha), (-hand, math.pi + 2 * alpha), (hand, alpha)):
        lx, ly = -hy, hx
        cx, cy = px + turn * r * lx, py + turn * r * ly
        a0 = math.atan2(py - cy, px - cx)
        a1 = a0 + turn * angle
        arcs.append((cx, cy, a0, a1))
        px, py = cx + r * math.cos(a1), cy + r * math.sin(a1)
        c, sn = math.cos(turn * angle), math.sin(turn * angle)
        hx, hy = hx * c - hy * sn, hx * sn + hy * c
    # It must come back to the other opening, heading home.
    qx, qy = end[0] - hand * t * nx, end[1] - hand * t * ny
    if math.hypot(px - qx, py - qy) > 1e-6 or hx * heading[0] + hy * heading[1] > -1 + 1e-6:
        return None
    total = sum(r * abs(a1 - a0) for _, _, a0, a1 in arcs)

    def bed(at, x, y):
        ideal = level(x, y) - TRACK_DEPTH
        upper = min(ideal, s.track + LINE_GRADE * at, s.track + LINE_GRADE * (total - at))
        return max(upper, s.track - LINE_GRADE * at, s.track - LINE_GRADE * (total - at))

    bends, run = [], 0.0
    for k, (cx, cy, a0, a1) in enumerate(arcs):
        length = r * abs(a1 - a0)
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        z0 = s.track if k == 0 else bed(run, x0, y0)
        z1 = s.track if k == len(arcs) - 1 else bed(run + length, x1, y1)
        bends.append(Bend(f'{s.id}_loop_{k}', s.node, cx, cy, r, a0, a1, z0, z1, LOOP[0]))
        run += length
    return bends


def _run(path, ka, kb, a, b, radius, level, size, widths):
    """The line from station ``a`` (at path[ka]) to ``b``: straights from
    end wall to tangent point to tangent point, bends between."""
    pieces = []
    node = path[ka]
    axis, heading = a.axis, a.heading
    i = 0 if axis == 'x' else 1
    pos = [node[0] * size, node[1] * size]
    pos[i] += heading * a.half_length + heading * SHELL
    pos_level = a.track
    for k in range(ka + 1, kb):
        if k not in radius:
            continue
        j = (path[k][0] * size, path[k][1] * size)
        r = radius[k]
        nxt = path[k + 1]
        out = (nxt[0] - path[k][0], nxt[1] - path[k][1])
        h_in = (heading, 0) if axis == 'x' else (0, heading)
        tin = (j[0] - r * h_in[0], j[1] - r * h_in[1])
        tout = (j[0] + r * out[0], j[1] + r * out[1])
        tin_level = level(*tin) - TRACK_DEPTH
        pieces.append(_straight(axis, heading, pos, tin, pos_level, tin_level, level, size, widths))
        centre = (tin[0] + r * out[0], tin[1] + r * out[1])
        a0 = math.atan2(tin[1] - centre[1], tin[0] - centre[0])
        a1 = math.atan2(tout[1] - centre[1], tout[0] - centre[0])
        turn = h_in[0] * out[1] - h_in[1] * out[0]          # +1: a left turn (anticlockwise).
        if turn > 0 and a1 < a0:
            a1 += 2 * math.pi
        elif turn < 0 and a1 > a0:
            a1 -= 2 * math.pi
        pieces.append(Bend(f'subway_curve_{_key(path[k])}', path[k], centre[0], centre[1], r, a0, a1, tin_level,
                           level(*tout) - TRACK_DEPTH))
        axis = _axis(path[k], nxt)
        heading = out[0] + out[1]
        pos, pos_level = [tout[0], tout[1]], level(*tout) - TRACK_DEPTH
    i = 0 if axis == 'x' else 1
    end = [path[kb][0] * size, path[kb][1] * size]
    end[i] -= heading * (b.half_length + SHELL)
    pieces.append(_straight(axis, heading, pos, end, pos_level, b.track, level, size, widths))
    straights = [p for p in pieces if isinstance(p, Straight)]
    first, last = straights[0], straights[-1]
    # The walkway steps down to the track bed at the stations' end walls.
    first.steps = (heading_start(first), not heading_start(first)) if first is not last else (True, True)
    if first is not last:
        last.steps = (not heading_start(last), heading_start(last))
    # The track bed: TRACK_DEPTH under the street or deeper, leaving and reaching the stations' levels at their end
    # walls (a station is level, set from its junction; on a slope the street at its ends is higher or lower), and
    # never climbing or falling more steeply than LINE_GRADE away from them.
    offsets, total = [], 0.0
    for piece in pieces:
        offsets.append(total)
        total += piece.length

    def bed(at, ideal):
        upper = min(ideal, a.track + LINE_GRADE * at, b.track + LINE_GRADE * (total - at))
        return max(upper, a.track - LINE_GRADE * at, b.track - LINE_GRADE * (total - at))

    for piece, offset in zip(pieces, offsets):
        if isinstance(piece, Bend):
            frames = piece.frames()
            x0, y0, x1, y1 = frames[0][0], frames[0][1], frames[-1][0], frames[-1][1]
            piece.z0 = bed(offset, level(x0, y0) - TRACK_DEPTH)
            piece.z1 = bed(offset + piece.length, level(x1, y1) - TRACK_DEPTH)
            continue

        def run_at(along, piece=piece, offset=offset):
            return offset + (along - piece.start if piece.heading > 0 else piece.end - along)

        def depth_at(along, piece=piece, run_at=run_at):
            ground = level(*piece.point(along))
            return ground - bed(run_at(along), ground - TRACK_DEPTH)

        # Sample it densely enough near the stations to follow the grade's kinks.
        marks = [a for a in (_along_at(piece, offset, d) for d in [4.0 * k for k in range(1, 26)] +
                             [total - 4.0 * k for k in range(1, 26)]) if a is not None]
        _sections_of(piece, level, depth_at, marks)
    return Run(f'subway_run_{_key(path[ka])}__{_key(path[kb])}', a, b, pieces)


def _settle_stations(order, at, path, radius, size):
    """Set stations deeper where the line could not climb from one to the
    next within LINE_GRADE over the run between them (their boxes are long
    and level; on a hill the street at two neighbours differs a lot). Deeper
    only, and an island at most ISLAND_DEEPER (its two stairs would meet)."""
    def run_length(ka, kb):
        # The lattice distance less the boxes, less what each curve cuts off its corner.
        total = (kb - ka) * size - at[ka].half_length - at[kb].half_length - 2 * SHELL
        return total - sum((2 - math.pi / 2) * r for k, r in radius.items() if ka < k < kb)

    original = {k: at[k].track for k in order}
    for _ in range(3):
        for ka, kb in zip(order, order[1:]):
            room = LINE_GRADE * max(1.0, run_length(ka, kb))
            for k, other in ((kb, ka), (ka, kb)):
                s = at[k]
                cap = ISLAND_DEEPER if s.kind == 'island' else SIDE_DEEPER
                want = min(s.track, at[other].track + room)
                s.track = max(want, original[k] - cap)


def _along_at(piece, offset, at):
    """The along of a straight at run distance ``at``, if it is on it."""
    d = at - offset
    if not 1e-6 < d < piece.length - 1e-6:
        return None
    return piece.start + d if piece.heading > 0 else piece.end - d


def heading_start(piece):
    """Whether the line enters a straight at its start (the lesser along)."""
    return piece.heading > 0


def _straight(axis, heading, p0, p1, z0, z1, level, size, widths):
    i = 0 if axis == 'x' else 1
    line = p0[1] if axis == 'x' else p0[0]
    a0, a1 = p0[i], p1[i]
    start, end = sorted((a0, a1))
    f_start, f_end = (z0, z1) if a0 <= a1 else (z1, z0)
    piece = Straight(axis, line, start, end, heading, [(start, f_start), (end, f_end)])
    # Road half widths over it, per lattice edge.
    k0, k1 = math.floor(start / size), math.ceil(end / size)
    cross = round(line / size)
    for k in range(k0, k1):
        a, b = ((k, cross), (k + 1, cross)) if axis == 'x' else ((cross, k), (cross, k + 1))
        w = widths.get(tuple(sorted((a, b))))
        if w is not None:
            piece.halves.append((max(start, k * size), min(end, (k + 1) * size), w / 2))
    return piece


def _sections_of(piece, level, depth_at=None, marks=()):
    """The track bed along a straight: ``depth_at(along)`` under the street
    (TRACK_DEPTH unless given), level where the walkway steps."""
    depth_at = depth_at or (lambda along: TRACK_DEPTH)
    run = WALKWAY_STEPS[0] * WALKWAY_STEPS[1]
    breaks = list(marks)
    if piece.length > 3 * run:
        if piece.steps[0]:
            breaks.append(piece.start + run)
        if piece.steps[1]:
            breaks.append(piece.end - run)
    else:
        piece.steps = (False, False)
    f0 = level(*piece.point(piece.start)) - depth_at(piece.start)
    f1 = level(*piece.point(piece.end)) - depth_at(piece.end)
    if piece.length > 1e-6:
        piece.sections = _sewers._sections(piece.start, piece.end, piece.line, piece.axis, depth_at,
                                           level, f0, f1, False, False, breaks)
    else:
        piece.sections = [(piece.start, f0), (piece.end, f1)]


def _station_ends(path, k, axis):
    """Whether the line leaves a station's -along and +along ends."""
    i = 0 if axis == 'x' else 1
    ends = [False, False]
    for other in (path[k - 1] if k > 0 else None, path[k + 1] if k + 1 < len(path) else None):
        if other is not None:
            ends[0 if other[i] < path[k][i] else 1] = True
    return tuple(ends)


def _lot_shapes(city):
    """Every building's footprint, grown by FACADE: (outline, bounding rect)."""
    found = []
    for lot in city.lots:
        if lot.kind not in ('BUILDING',) and lot.condition == 'COLLAPSED':
            continue
        cx, cy = lot.center
        hw, hd = lot.width / 2 + FACADE, lot.depth / 2 + FACADE
        c, s = math.cos(lot.rotation), math.sin(lot.rotation)
        outline = [(cx + x * c - y * s, cy + x * s + y * c) for x, y in ((-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd))]
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        found.append((outline, (min(xs), min(ys), max(xs), max(ys))))
    return found


def _yard_shapes(city):
    """Every lot's yard (its building and the forecourt in front of it, the
    lot's own foundation): (outline, bounding rect)."""
    from .streets import lot_yard
    found = []
    for lot in city.lots:
        outline = [tuple(p[:2]) for p in lot_yard(lot, city)]
        xs, ys = [p[0] for p in outline], [p[1] for p in outline]
        found.append((outline, (min(xs), min(ys), max(xs), max(ys))))
    return found


def _convex_overlap(a, b):
    """Whether two convex outlines overlap (separating axes)."""
    for poly in (a, b):
        for i in range(len(poly)):
            (x0, y0), (x1, y1) = poly[i], poly[(i + 1) % len(poly)]
            nx, ny = y1 - y0, x0 - x1
            pa = [nx * x + ny * y for x, y in a]
            pb = [nx * x + ny * y for x, y in b]
            if max(pa) <= min(pb) + 1e-6 or max(pb) <= min(pa) + 1e-6:
                return False
    return True


def _on_street(index, rect):
    """Whether any of the street mesh lies over a plan rect."""
    for number in index.near(rect):
        polygon = [index.vertices[i] for i in index.faces[number]]
        part = _sewers._clip_rect(polygon, rect)
        if len(part) >= 3 and _sewers._area(part) > 1e-4:
            return True
    return False


def _plan_entrances(station, level, index, blocked, lots, pads, yards=()):
    """Up to two entrances, one from each of the hall's ends, up into the
    open ground between the footway and the buildings: outside every lot's
    yard (a forecourt is the lot's own foundation) and clear of the
    buildings. A station with no such ground gets them in the footway
    itself, narrower."""
    clear, wall, headroom = ENTRANCE
    places = [('ground', station.road_half + station.walk + VERGE + wall, clear)]
    narrow = station.walk - 2 * wall - 2 * FOOTWAY_EDGE
    if narrow >= FOOTWAY_ENTRANCE - 1e-6:
        places.append(('footway', station.road_half + FOOTWAY_EDGE + wall, narrow))
    for place, inner, width in places:
        if station.entrances:
            break
        for sign in (1, -1):
            for side in (sign, -sign):
                entrance = _entrance_at(station, level, index, place, inner, width, sign, side)
                if entrance is None:
                    continue
                surface = _entrance_surface(station, entrance)
                outline = [(surface[0], surface[1]), (surface[2], surface[1]), (surface[2], surface[3]),
                           (surface[0], surface[3])]
                if place == 'ground':
                    if index is not None and _on_street(index, surface):
                        continue
                    if any(_overlap(surface, box) and _convex_overlap(outline, shape) for shape, box in yards):
                        continue
                if any(_overlap(surface, box) and _convex_overlap(outline, shape) for shape, box in lots):
                    continue
                if any(_overlap(surface, pad) for pad in pads):
                    continue
                if blocked(_entrance_rect(station, entrance), entrance.floor - HALL_SHELL, entrance.top + PARAPET):
                    continue
                station.entrances.append(entrance)
                break
    for e in station.entrances:
        # The floor in front of its foot stays free.
        a = e.sign * HALL[0]
        station.take(a, a - e.sign * 3.0, e.across[0] - .3, e.across[1] + .3)


def _entrance_at(station, level, index, place, inner, width, sign, side):
    """An entrance's stair from the hall's ``sign`` end on its ``side``,
    ``width`` clear from ``inner`` across; None if it cannot climb there.
    In the footway its head is the footway's (all of its opening paved)."""
    clear, wall, headroom = ENTRANCE
    across = (inner, inner + width)
    span = across if side > 0 else (-across[1], -across[0])
    middle = sum(span) / 2
    start = station.centre + sign * (HALL[0] + HALL_SHELL)
    head = level(*station.point(start + sign * 11.0, middle))
    entrance = None
    for _ in range(3):
        steps = max(1, math.ceil((head - station.hall_floor) / STAIR[1] - 1e-9))
        run = steps * STAIR[2]
        slope = (head - station.hall_floor) / run
        # The ceiling stops where its top would come within 0.1 m of the ground.
        opening = None
        for k in range(steps + 1):
            ground = level(*station.point(start + sign * k * STAIR[2], middle))
            if station.hall_floor + slope * k * STAIR[2] + headroom + HALL_SHELL >= ground - .1:
                opening = k * STAIR[2]
                break
        if opening is None or run - opening < 1.5:
            return None
        buried = min(level(*station.point(start + sign * k * STAIR[2], u))
                     for k in range(int(opening / STAIR[2]) + 1) for u in span) - .05
        entrance = Entrance(f'{station.id}_entrance_{len(station.entrances)}', sign, side, span, start,
                            run, opening, station.hall_floor, head, steps, buried, place)
        if place == 'footway':
            if index is None:
                return None
            x0, y0, x1, y1 = _entrance_surface(station, entrance)
            tip = index.paved((x0, y0, x1, y1))
            if tip is None:
                return None
        else:
            tip = level(*station.point(start + sign * run, middle))
        if abs(tip - head) < 1e-6:
            return entrance
        head = tip
    return entrance


def _plan_hall(station, seed):
    """The hall's fittings: a fare line across each end with an entrance
    (a booth in the middle, a gate either side, fences to the walls), and
    two bathrooms against a side wall inside them."""
    for a0, a1, c0, c1 in station.stair_holes():
        station.take(a0 - .3, a1 + .3, c0 - .3, c1 + .3)
    width = station.side_half
    for sign in sorted({e.sign for e in station.entrances}, reverse=True):
        at = sign * (HALL[0] - FARE)
        half = BOOTH[0] / 2
        gates = [(-half - GATE, -half), (half, half + GATE)]
        fences = [(-width, -half - GATE), (half + GATE, width)]
        station.fares.append(FareLine(sign, at, fences, gates, 0.0))
        station.take(at - BOOTH[1] / 2 - .4, at + BOOTH[1] / 2 + .4, -half - .4, half + .4)
        station.take(at - .15, at + .15, -width, width)
    # Bathrooms: against a side wall, inside the fare lines, clear of the stairs.
    length = 2 * BATH[0] + 3 * PARTITION
    depth = BATH[1] + PARTITION
    limit = HALL[0] - FARE - .6
    sides = (1, -1) if stream(seed, 'subway-baths', station.id).random() < .5 else (-1, 1)
    for side in sides:
        c0 = side * (width - depth)
        found = None
        for k in range(int((2 * limit - length) / .5) + 1):
            for a0 in (-limit + .5 * k, limit - length - .5 * k):
                if station.clear(a0, a0 + length, c0 - 1.2 * side, side * width):
                    found = a0
                    break
            if found is not None:
                break
        if found is not None:
            station.baths = Bathrooms(side, found, found + length, c0)
            station.take(found, found + length, c0 - 1.2 * side, side * width)
            break


def _plan_furniture(station, seed):
    """A kiosk or two against the hall's side walls inside the fare lines;
    benches (a bin by about half) along the platforms, clear of the stairs
    and the end steps, and two in the hall."""
    rng = stream(seed, 'subway-furniture', station.id)
    s = station
    width = s.side_half
    # Keep the middle of each wall free: the sewers' service rooms come in there (planned after this).
    reserved = []
    for wall in ('a+', 'a-', 'c+', 'c-'):
        a0, a1, c0, c1 = s.wall_spot(wall, 0.0, SERVICE_DOOR[0] + 1.0)
        reserved.append((min(a0, a1), max(a0, a1), min(c0, c1), max(c0, c1)))
    s.taken.extend(reserved)
    limit = HALL[0] - FARE - 1.0
    w, d, h, t = KIOSK
    sides = (1, -1) if rng.random() < .5 else (-1, 1)
    count = 1 + (rng.random() < .5)
    for k in range(count):
        made = False
        for side in sides:
            c0 = side * (width - d)
            for j in range(int((2 * limit - w) / .5) + 1):
                a0 = (-limit + .5 * j) if (j + k) % 2 == 0 else (limit - w - .5 * j)
                if not s.clear(a0 - .3, a0 + w + .3, c0 - side * 1.2, side * width):
                    continue
                kind = KIOSK_KINDS[int(rng.random() * len(KIOSK_KINDS))]
                s.kiosks.append(Kiosk(f'{s.id}_kiosk_{k}', kind, side, a0, a0 + w, c0))
                s.take(a0 - .3, a0 + w + .3, c0 - side * 1.2, side * width)
                made = True
                break
            if made:
                break
    # Benches in the hall, against the side walls, facing the middle.
    length, depth = BENCH
    for k in range(2):
        for side in (sides if k == 0 else sides[::-1]):
            c = side * (width - depth / 2 - .05)
            spot = None
            for j in range(int(2 * limit)):
                a = (j // 2 + .5) * (1 if j % 2 else -1)
                if s.clear(a - length / 2 - .3, a + length / 2 + .3, c - side * (depth / 2 + .9), side * width):
                    spot = a
                    break
            if spot is not None:
                s.furniture.append(('bench', spot, c, 'hall', (0.0, -float(side))))
                s.take(spot - length / 2 - .3, spot + length / 2 + .3, c - side * (depth / 2 + .9), side * width)
                bin_at = spot + length / 2 + .5
                if s.clear(bin_at - .3, bin_at + .3, c - side * .3, side * width):
                    s.furniture.append(('trash_bin', bin_at, c, 'hall', (0.0, -float(side))))
                    s.take(bin_at - .3, bin_at + .3, c - side * .3, side * width)
                break
    # (The service doors' places are free again for the sewers' plan.)
    s.taken = [t for t in s.taken if t not in reserved]
    # Benches along the platforms.
    count_steps, going = END_STEPS
    stop = s.platform_length / 2 - count_steps * going - 1.0
    stairs = [(min(bottom, bottom + sign * steps * STAIR[2]) - s.centre - 1.0,
               max(bottom, bottom + sign * steps * STAIR[2]) - s.centre + 1.0, across)
              for sign, across, bottom, steps, rise in s.stairs()]
    rows = []
    if s.kind == 'island':
        rows = [(depth / 2 + .02, 1.0), (-depth / 2 - .02, -1.0)]       # Back to back down the middle.
    else:
        for c0, c1 in s.platforms():
            back = c1 if c0 > 0 else c0
            sign = 1.0 if c0 > 0 else -1.0
            rows.append((back - sign * (depth / 2 + .05), -sign))       # Against the back wall, facing the track.
    for across, facing in rows:
        a = -stop + length / 2 + BENCH_EVERY * rng.random() * .5
        while a + length / 2 <= stop:
            free = not any(a0 - length / 2 < a < a1 + length / 2 and abs(c - across) < STAIR[0] / 2 + depth
                           for a0, a1, c in stairs)
            if free:
                s.furniture.append(('bench', a, across, 'platform', (0.0, facing)))
                bin_at = a + length / 2 + .5
                if rng.random() < BIN_SHARE and bin_at < stop and not any(
                        a0 < bin_at < a1 and abs(c - across) < STAIR[0] / 2 + depth for a0, a1, c in stairs):
                    s.furniture.append(('trash_bin', bin_at, across, 'platform', (0.0, facing)))
            a += BENCH_EVERY


def _plan_hallways(subway, level, index, blocked, seed):
    """Access hallways off the walkway at seeded intervals along each
    straight: utility rooms and emergency exits now, the sewer's for
    ``connect``."""
    from . import tunnels
    size = subway.size
    for run in subway.runs:
        for piece in run.straights:
            rng = stream(seed, 'subway-hallways', f'{run.id}:{piece.start:.1f}')
            lo, hi = piece.start + HALLWAY_CLEAR, piece.end - HALLWAY_CLEAR
            along = lo + HALLWAY_EVERY * (.2 + .6 * rng.random())
            while along <= hi:
                spot = along
                along += HALLWAY_EVERY * (.6 + .8 * rng.random())
                if min(spot % size, size - spot % size) < HALLWAY_CLEAR:
                    continue
                half = piece.road_half(spot)
                if half <= 0:
                    continue
                pick = rng.random()
                kinds = [k for k, _ in HALLWAY_KINDS]
                total = 0.0
                for k, share in HALLWAY_KINDS:
                    total += share
                    if pick < total:
                        kinds.remove(k)
                        kinds.insert(0, k)
                        break
                for kind in kinds:
                    if kind == 'sewer':
                        piece.spots.append(spot)
                        break
                    if _plan_room(subway, piece, spot, kind, half, level, index, blocked, seed, tunnels):
                        break


def _plan_room(subway, piece, along, kind, half, level, index, blocked, seed, tunnels):
    """A utility room, or an emergency exit's, under the footway on the
    line's left at ``along``; False if it does not fit."""
    walk = subway.stations[0].walk
    size = EXIT_ROOM if kind == 'exit' else UTILITY
    side = piece.left
    room_half = size / 2 + UTILITY_SHELL
    # Under the footway; under a narrower street, out past it far enough to clear the line.
    room = side * max(half + walk / 2, LINE[0] / 2 + SHELL + .85 + room_half)
    floor = piece.floor_at(along) + WALKWAY[1]
    ident = f'subway_{kind}_{piece.axis}{piece.line:.0f}_{along:.0f}'
    line_face = side * (LINE[0] / 2 + SHELL)
    a, b = sorted((line_face, room - side * room_half))
    if (b - a) < .05 or (room - side * room_half - line_face) * side < .05:
        return False
    corridor = tunnels.Tunnel(ident + '_corridor', ident, ident, -1, 'y' if piece.axis == 'x' else 'x', along,
                              piece.line + a, piece.line + b, floor, floor, '', '', False)
    utility = Utility(ident, piece, along, floor, room, corridor, kind)
    if blocked(utility.room(), floor - UTILITY_SHELL, floor + size + UTILITY_SHELL):
        return False
    if blocked(corridor.rect(), floor - .2, floor + 2.4):
        return False
    wants_exit = kind == 'exit' or stream(seed, 'subway-exit', ident).random() < EXIT_SHARE
    if wants_exit and index is not None:
        x, y = piece.point(along, room)
        h = _sewers.SHAFT / 2 + _sewers.SHAFT_WALL
        top = index.paved((x - h, y - h, x + h, y + h))
        if top is not None:
            exit_id = f'exit_{ident[7:]}'
            utility.exit = _sewers.Manhole(exit_id, ident, x, y, top + _sewers.RIM, floor + size + UTILITY_SHELL,
                                           stream(seed, 'manhole', exit_id).random() < _sewers.OPEN)
    if kind == 'exit' and utility.exit is None:
        return False
    piece.add_door(along)
    subway.utilities.append(utility)
    return True


def connect(subway, sites, network=None, avoid=()):
    """After the sewers and tunnels: the service rooms the sewers planned
    into the halls; doorways and ladder drops from deep basements into the
    halls (the sites' ``doors`` are filled in); hallways from the line up
    into the trunk sewer above it. ``avoid``: other solids (rect, low,
    high)."""
    from . import tunnels
    by_id = {s.id: s for s in subway.stations}
    if network is not None:
        for link in getattr(network, 'links', ()):
            station = by_id.get(link.station)
            if station is not None:
                station.links.append(link)
    have = [s for s in sites if s.quarter() is not None and
            (s.level(-2) is not None or (s.style in ACCESS_DROP_STYLES and s.level(-1) is not None))]
    boxes = {s.id: s.box(s.outer) for s in sites}
    taken = set()
    shaft = 2 * _sewers.DROP[1] + _sewers.DROP[0]
    for station in subway.stations:
        hall = station.hall()
        m = 0 if station.axis == 'x' else 1           # Along the line.
        n = 1 - m
        axis = 'y' if station.axis == 'x' else 'x'
        for site in have:
            if site.id in taken:
                continue
            box = boxes[site.id]
            if not (box[m] < hall[m + 2] and hall[m] < box[m + 2]):
                continue
            made = None
            for side in (1, -1):
                wall = station.line + side * (station.side_half + HALL_SHELL)
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
                modes = []
                if site.level(-2) is not None:
                    modes.append((-2, False))
                if site.style in ACCESS_DROP_STYLES and site.level(-1) is not None and gap >= shaft + .3:
                    modes.append((-1, True))
                for storey, drop in modes:
                    zb = site.floor(storey)
                    if drop:
                        if zb - station.hall_floor < 1.0:
                            continue
                    elif abs(zb - station.hall_floor) > .05 + max(gap, .25) * tunnels.SLOPE:
                        continue
                    for k in range(int((hi - lo) / .5) + 1):
                        along = (lo + hi) / 2 + .5 * ((k + 1) // 2) * (1 if k % 2 else -1)
                        if not lo - 1e-6 <= along <= hi + 1e-6:
                            continue
                        width = tunnels.WIDTH if drop else SERVICE_DOOR[0] + .4
                        if not station.clear(*station.wall_spot('c+' if side > 0 else 'c-', along - station.centre,
                                                                width)):
                            continue
                        probe = face + side * .6
                        px, py = (along, probe) if station.axis == 'x' else (probe, along)
                        room = tunnels._room_behind(site, storey, px, py, axis)
                        if room is None:
                            continue
                        ident = f'access_{site.id}__{station.id}'
                        if drop:
                            far = wall + side * shaft
                            top = zb + tunnels.HEIGHT + tunnels.SHELL
                            start, end = sorted((far, face))
                            passage = tunnels.Tunnel(ident, site.id, station.id, storey, axis, along, start, end,
                                                     zb, zb, room.name, '', True)
                            lo_s, hi_s = sorted((wall, far))
                            parts = [(passage.rect(tunnels.CLEAR), zb - tunnels.SHELL, top),
                                     (_rect(station, along - tunnels.WIDTH / 2 - _sewers.DROP[1],
                                            along + tunnels.WIDTH / 2 + _sewers.DROP[1],
                                            lo_s - station.line, hi_s - station.line),
                                      station.hall_floor - _sewers.DROP[1], top)]
                            shape = (wall, far, station.hall_floor, zb, top)
                        else:
                            start, end, z0, z1 = ((wall, face, station.hall_floor, zb) if side > 0
                                                  else (face, wall, zb, station.hall_floor))
                            passage = tunnels.Tunnel(ident, site.id, station.id, storey, axis, along, start, end,
                                                     z0, z1, room.name, '', True)
                            parts = [] if passage.length <= .05 else [
                                (passage.rect(tunnels.CLEAR), min(z0, z1) - tunnels.SHELL,
                                 max(z0, z1) + tunnels.HEIGHT + tunnels.SHELL)]
                            shape = None
                        if any(_overlap(r, b) for r, _, _ in parts for i, b in boxes.items() if i != site.id):
                            continue
                        if any(_overlap(r, r2) and lo2 < high and low < hi2
                               for r, low, high in parts for r2, lo2, hi2 in avoid):
                            continue
                        if any(_overlap(r, other.tunnel.rect()) for r, _, _ in parts
                               for st in subway.stations for other in st.accesses):
                            continue
                        made = Access(ident, site.id, room.name, passage, along, side, storey, shape)
                        point = (along, face) if station.axis == 'x' else (face, along)
                        door_side, door_centre = tunnels._side(site, *point)
                        site.doors.append((storey, door_side, door_centre, tunnels.DOOR[0], tunnels.DOOR[1]))
                        station.take(*station.wall_spot('c+' if side > 0 else 'c-', along - station.centre, width))
                        break
                    if made is not None:
                        break
                if made is not None:
                    break
            if made is not None:
                station.accesses.append(made)
                taken.add(site.id)
    _plan_corner_accesses(subway, sites, have, boxes, taken, avoid)
    if network is not None:
        _plan_risers(subway, network, avoid)


def _plan_corner_accesses(subway, sites, have, boxes, taken, avoid):
    """Second basement storeys beside the street just past a hall's end:
    a corridor from a doorway in the hall's end wall along the street (under
    the road's edge, clear of the trunk and the entrances, ramping 1 in 8 at
    most), a small room where it turns, and a passage across to the
    basement's wall."""
    from . import tunnels
    own = subway.solids()
    need = tunnels.WIDTH / 2 + tunnels.SHELL + .4
    for station in subway.stations:
        m = 0 if station.axis == 'x' else 1
        n = 1 - m
        across_axis = 'y' if station.axis == 'x' else 'x'
        for sign in (1, -1):
            if any(a.wall == ('a+' if sign > 0 else 'a-') for a in station.accesses):
                continue
            end_face = station.centre + sign * (HALL[0] + HALL_SHELL)
            for side in (1, -1):
                made = None
                # The corridor runs under the road's edge: clear of the trunk (on the centre line) and of the
                # entrances (beside the footway).
                c = side * max(station.road_half - 1.2, LINE[0] / 2 - 1.0)
                wall = 'a+' if sign > 0 else 'a-'
                if not station.clear(*station.wall_spot(wall, c, SERVICE_DOOR[0] + .4)):
                    continue
                line = station.line + c
                half = CORNER_ROOM[0] / 2 + UTILITY_SHELL
                for site in have:
                    if site.id in taken or site.level(-2) is None:
                        continue
                    box = boxes[site.id]
                    face = box[n] if side > 0 else box[n + 2]
                    gap = (face - (line + side * half)) * side
                    if gap < 1.0 or gap > ACCESS_REACH:
                        continue
                    inner = site.box(site.under.rect)
                    near_end, far_end = end_face + sign * (half + 2.0), end_face + sign * ACCESS_ALONG
                    lo = max(min(near_end, far_end), inner[m] + need)
                    hi = min(max(near_end, far_end), inner[m + 2] - need)
                    if hi < lo:
                        continue
                    zb = site.floor(-2)
                    alongs = sorted((lo + .5 * k for k in range(int((hi - lo) / .5) + 1)),
                                    key=lambda a: abs(a - end_face))
                    for along in alongs:
                        run = abs(along - end_face) - half
                        if abs(zb - station.hall_floor) > run * tunnels.SLOPE:
                            continue
                        probe = face + side * .6
                        px, py = (along, probe) if station.axis == 'x' else (probe, along)
                        room = tunnels._room_behind(site, -2, px, py, across_axis)
                        if room is None:
                            continue
                        ident = f'access_{site.id}__{station.id}'
                        a0, a1 = sorted((end_face, along - sign * half))
                        za, zc = (station.hall_floor, zb) if sign > 0 else (zb, station.hall_floor)
                        lead = tunnels.Tunnel(ident + '_lead', station.id, ident + '_corner', -2, station.axis, line,
                                              a0, a1, za, zc, '', '', True)
                        cx, cy = station.point(along, c)
                        hx, hy = (CORNER_ROOM[0] / 2,) * 2
                        toward_hall = ('-' if sign > 0 else '+') + station.axis
                        toward_site = ('+' if side > 0 else '-') + across_axis
                        corner = _sewers.ServiceRoom(ident + '_corner', cx, cy, hx, hy, zb, CORNER_ROOM[1],
                                                     [(toward_hall, line), (toward_site, along)])
                        s0, s1 = sorted((line + side * half, face))
                        passage = tunnels.Tunnel(ident, site.id, station.id, -2, across_axis, along, s0, s1, zb, zb,
                                                 room.name, '', True)
                        parts = [(lead.rect(tunnels.CLEAR), min(za, zc) - tunnels.SHELL,
                                  max(za, zc) + tunnels.HEIGHT + tunnels.SHELL),
                                 (corner.rect(), zb - UTILITY_SHELL, zb + CORNER_ROOM[1] + UTILITY_SHELL),
                                 (passage.rect(tunnels.CLEAR), zb - tunnels.SHELL, zb + tunnels.HEIGHT + tunnels.SHELL)]
                        if any(_overlap(r, b) for r, _, _ in parts for i, b in boxes.items() if i != site.id):
                            continue
                        # (Not its own hall: the corridor comes through its wall.)
                        if any(_overlap(r, r2) and lo2 < high and low < hi2 for r, low, high in parts
                               for r2, lo2, hi2 in list(avoid) + own if r2 != station.hall()):
                            continue
                        if any(_overlap(r, piece) for r, _, _ in parts for st in subway.stations for other in st.accesses
                               for piece in [other.tunnel.rect()] + ([other.lead.rect()] if other.lead else [])):
                            continue
                        made = Access(ident, site.id, room.name, passage, along, side, -2, None, lead, corner, wall, line)
                        point = (along, face) if station.axis == 'x' else (face, along)
                        door_side, door_centre = tunnels._side(site, *point)
                        site.doors.append((-2, door_side, door_centre, tunnels.DOOR[0], tunnels.DOOR[1]))
                        station.take(*station.wall_spot(wall, c, SERVICE_DOOR[0] + .4))
                        break
                    if made is not None:
                        break
                if made is not None:
                    station.accesses.append(made)
                    taken.add(made.site)
                    break


def _plan_risers(subway, network, avoid):
    """At the hallway spots the plan left: a ladder shaft beside the line up
    to the trunk running over it, and a passage over the line's roof
    through a gap in the trunk's wall."""
    from . import tunnels
    trunks = [s for s in network.sewers if s.kind == 'trunk']
    for piece in subway.straights:
        for along in piece.spots:
            sewer = next((s for s in trunks if s.axis == piece.axis and abs(s.line - piece.line) < 1e-6
                          and s.start + 3.0 < along < s.end - 3.0), None)
            if sewer is None or not sewer.trench(along - 1.5, along + 1.5):
                continue
            if sewer.plug is not None and sewer.plug[0] - 2.5 < along < sewer.plug[1] + 2.5:
                continue
            if any(abs(b.along - along) < tunnels.WIDTH + 1.0 for b in sewer.breaches):
                continue
            side = piece.left
            outer = side * (sewer.width / 2 + _sewers.SHELL)
            zs = sewer.floor_at(along)
            ident = f'subway_riser_{piece.axis}{piece.line:.0f}_{along:.0f}'
            near = side * (LINE[0] / 2 + SHELL)
            a, b = sorted((piece.line + outer, piece.line + near))
            passage = tunnels.Tunnel(ident + '_passage', ident, sewer.id, -2, 'y' if piece.axis == 'x' else 'x', along,
                                     a, b, zs, zs, '', '', True)
            riser = Riser(ident, piece, along, sewer.id, side, piece.floor_at(along) + WALKWAY[1], zs, passage)
            if riser.top_floor - tunnels.SHELL < piece.floor_at(along) + LINE[1] + SHELL + .1:
                continue                        # The passage must pass over the line's roof.
            parts = [(riser.rect(), riser.floor - RISER[1], riser.top),
                     (passage.rect(), zs - tunnels.SHELL, riser.top)]
            if any(_overlap(r, r2) and lo2 < high and low < hi2 for r, low, high in parts for r2, lo2, hi2 in avoid):
                continue
            # The sewer is level across the gap in its wall, as for a breach.
            gap = _sewers.Breach(ident, '', '', sewer.id, passage, along, side)
            sewer.breaches.append(gap)
            half = tunnels.WIDTH / 2
            kept = [(x, f) for x, f in sewer.sections if not along - half - 1e-6 <= x <= along + half + 1e-6]
            sewer.sections = sorted(kept + [(along - half, zs), (along + half, zs)])
            piece.add_door(along)
            subway.risers.append(riser)


# -- geometry ------------------------------------------------------------------


def _profile(width=None, vault=None):
    width = LINE[0] if width is None else width
    height, vault = LINE[1], LINE[2] if vault is None else vault
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
          floor_holes=(), roof_holes=(), shaft=None, ceiling_material=None):
    """A box's shell round a clear room centred at (x, y): floor, four walls
    with ``openings`` {side: [(world coordinate along the wall, factory)]},
    roof; rect holes in floor and roof, and an octagonal one in the roof
    for ``shaft`` (a sewers.Manhole)."""
    from . import solids
    ceiling_material = floor_material if ceiling_material is None else ceiling_material
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
    _slab(mesh, (x0, y0, x1, y1), top, top + s, ceiling_material, holes)
    for triangle in corners:
        _sewers._flat(mesh, triangle, top, top + s, ceiling_material)


def _hall_wall_side(station, wall):
    """The `_room` side name of a hall wall: 'a+', 'a-' (ends), 'c+', 'c-'."""
    sign = wall[1]
    if wall[0] == 'a':
        return sign + station.axis
    return sign + ('y' if station.axis == 'x' else 'x')


def build(mesh, subway):
    """The subway's solids in plan coordinates, in its materials."""
    from . import tunnels
    for run in subway.runs:
        for piece in run.pieces:
            if isinstance(piece, Bend):
                _bend(mesh, piece)
            else:
                _straight_solids(mesh, piece)
    for loop in subway.loops:
        _splitter(mesh, loop)
        for bend in loop.bends:
            _bend(mesh, bend)
    for station in subway.stations:
        _station(mesh, station)
        for access in station.accesses:
            tunnels.build(mesh, access.tunnel)
            if access.lead is not None:
                tunnels.build(mesh, access.lead)
                r = access.corner
                _room(mesh, r.x, r.y, r.hx, r.hy, r.floor, r.height, UTILITY_SHELL,
                      {side: [(c, lambda u, f=r.floor: _rect_opening(u, tunnels.WIDTH, f, tunnels.HEIGHT,
                                                                     U_TUNNEL_WALL))] for side, c in r.doors},
                      U_TUNNEL_WALL, U_TUNNEL_FLOOR, ceiling_material=U_TUNNEL_CEILING)
            if access.drop is not None:
                _sewers.drop_shaft(mesh, station, access.along, access.side, access.drop, _sewers.OPENING['trunk'],
                                   U_SERVICE_WALL, U_SERVICE_FLOOR)
        for link in station.links:
            _link(mesh, link)
    for utility in subway.utilities:
        tunnels.build(mesh, utility.corridor, U_SERVICE_WALL, U_SERVICE_FLOOR, U_SERVICE_WALL)
        _utility(mesh, utility)
        if utility.exit is not None:
            _sewers._shaft(mesh, utility.exit, U_SEWER_SHAFT)
    for riser in subway.risers:
        tunnels.build(mesh, riser.passage, U_SERVICE_WALL, U_SERVICE_FLOOR, U_SERVICE_WALL)
        _riser(mesh, riser)


def _frame_point(frame, u, v):
    x, y, z, nx, ny = frame
    return (x + u * nx, y + u * ny, z + v)


def _sweep(mesh, polygon, f0, f1, material):
    _sewers._solid(mesh, [_frame_point(f0, u, v) for u, v in polygon],
                   [_frame_point(f1, u, v) for u, v in polygon], material)


def _line_pieces():
    """The line's shell as (polygon, material) in (left, up) coordinates,
    its walkway on the left, and the left wall split round a doorway."""
    from . import tunnels
    ring = _sewers._ring(_profile(), SHELL)
    half = LINE[0] / 2
    door_top = WALKWAY[1] + tunnels.HEIGHT
    shell = [(quad, U_SUBWAY_TRACKBED if i == 0 else U_SUBWAY_WALL) for i, quad in enumerate(ring)]
    lower = [ring[1][0], (half, WALKWAY[1]), (half + SHELL, WALKWAY[1]), ring[1][3]]
    upper = [(half, door_top), ring[1][1], ring[1][2], (half + SHELL, door_top)]
    walkway = [(half - WALKWAY[0], 0.0), (half, 0.0), (half, WALKWAY[1]), (half - WALKWAY[0], WALKWAY[1])]
    return shell, lower, upper, walkway


def _bend(mesh, bend):
    if bend.loop:
        # A turning loop: one track's tunnel, no walkway.
        ring = _sewers._ring(_profile(bend.width, LOOP[2]), SHELL)
        shell = [(quad, U_SUBWAY_TRACKBED if i == 0 else U_SUBWAY_WALL) for i, quad in enumerate(ring)]
        walkway = None
    else:
        shell, _, _, walkway = _line_pieces()
    frames = bend.frames()
    for f0, f1 in zip(frames, frames[1:]):
        for polygon, material in shell:
            _sweep(mesh, polygon, f0, f1, material)
        if walkway is not None:
            _sweep(mesh, walkway, f0, f1, U_SUBWAY_WALKWAY)


def _splitter(mesh, loop):
    """The level box past an end station where the tracks part: floor,
    side walls and roof from the station's end wall, and a wall across its
    far end with an opening for each end of the loop."""
    from . import solids
    s, track = loop.station, loop.station.track
    half = LOOP_TRACKS + LOOP[0] / 2
    face, far = loop.split
    top = track + LINE[1]
    a0, a1 = sorted((face, far))
    w0, w1 = sorted((far, far - loop.sign * SHELL))
    for c0, c1, z0, z1, mat in ((-half - SHELL, half + SHELL, track - SHELL, track, U_SUBWAY_TRACKBED),
                                (-half - SHELL, half + SHELL, top, top + SHELL, U_SUBWAY_WALL),
                                (-half - SHELL, -half, track, top, U_SUBWAY_WALL),
                                (half, half + SHELL, track, top, U_SUBWAY_WALL)):
        r = _rect(s, a0, a1, c0, c1)
        solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, mat)
    # The far wall, between the side walls; its thickness towards the station.
    reverse = (loop.sign > 0) == (s.axis == 'y')
    c_start, c_end = (half, -half) if reverse else (-half, half)
    ox, oy = s.point(far, c_start)
    qx, qy = s.point(far, c_end)
    length = math.hypot(qx - ox, qy - oy)
    direction = ((qx - ox) / length, (qy - oy) / length)
    lw, lh, lv = LOOP
    openings = []
    for c in sorted((-LOOP_TRACKS, LOOP_TRACKS), key=lambda c: abs(c - c_start)):
        u = abs(c - c_start)
        openings.append(solids.Opening(u - lw / 2, u + lw / 2, [(u - lw / 2, track), (u + lw / 2, track)],
                                       [(u - lw / 2, track + lh - lv), (u - lw / 2 + lv, track + lh),
                                        (u + lw / 2 - lv, track + lh), (u + lw / 2, track + lh - lv)],
                                       U_SUBWAY_WALL, 'door'))
    solids.wall_solid(mesh, (ox, oy), direction, SHELL, 0.0, length, track, [(0.0, top), (length, top)],
                      openings, U_SUBWAY_WALL)


def _straight_solids(mesh, piece):
    from . import tunnels
    if piece.length < 1e-4:
        return
    shell, lower, upper, walkway = _line_pieces()
    half = LINE[0] / 2
    gaps = [(a - tunnels.WIDTH / 2, a + tunnels.WIDTH / 2) for a in piece.doors]
    count, going = WALKWAY_STEPS
    run = count * going
    for (a0, _), (a1, _) in zip(piece.sections, piece.sections[1:]):
        if a1 - a0 < 1e-4:
            continue
        f0, f1 = piece.frame(a0), piece.frame(a1)
        door = any(g0 - 1e-6 <= a0 and a1 <= g1 + 1e-6 for g0, g1 in gaps)
        for i, (polygon, material) in enumerate(shell):
            if door and i == 1:
                _sweep(mesh, lower, f0, f1, U_SUBWAY_WALL)
                _sweep(mesh, upper, f0, f1, U_SUBWAY_WALL)
                continue
            _sweep(mesh, polygon, f0, f1, material)
        # The walkway, stepping down to the track bed at a station's end wall.
        if piece.steps[0] and a1 <= piece.start + run + 1e-6:
            ends = [(piece.start, 1)]
        elif piece.steps[1] and a0 >= piece.end - run - 1e-6:
            ends = [(piece.end, -1)]
        else:
            _sweep(mesh, walkway, f0, f1, U_SUBWAY_WALKWAY)
            continue
        for at, sense in ends:
            for j in range(1, count):
                b0, b1 = sorted((at + sense * j * going, at + sense * (j + 1) * going))
                height = WALKWAY[1] * j / count
                block = [(half - WALKWAY[0], 0.0), (half, 0.0), (half, height), (half - WALKWAY[0], height)]
                _sweep(mesh, block, piece.frame(b0), piece.frame(b1), U_SUBWAY_WALKWAY)


def _station(mesh, station):
    from . import solids
    s, track = station, station.track
    half = s.half_across
    L = s.half_length
    hx, hy = (L, half) if s.axis == 'x' else (half, L)
    end_sides = ('-x', '+x') if s.axis == 'x' else ('-y', '+y')
    openings = {}
    for side, leaves, sign in zip(end_sides, s.ends, (-1, 1)):
        if leaves:
            openings[side] = [(s.line, lambda u, f=track: _line_opening(u, f, U_STATION_WALL))]
        elif s.loop_sign == sign:
            # Into the box past it where the tracks part for the turning loop.
            openings[side] = [(s.line, lambda u, f=track: _rect_opening(u, 2 * LOOP_TRACKS + LOOP[0], f, LINE[1],
                                                                          U_STATION_WALL))]
    roof_holes, hall_holes = [], []
    for sign, across, bottom, steps, rise in s.stairs():
        slope = rise / STAIR[2]
        ceiling = track + HEADROOM
        open_roof = max(0.0, (ceiling - HEADROOM_STAIR - (track + PLATFORM_HEIGHT)) / slope - STAIR[2])
        open_hall = max(0.0, (s.hall_floor - HALL_SHELL - HEADROOM_STAIR - (track + PLATFORM_HEIGHT)) / slope
                        - STAIR[2])
        top = bottom + sign * steps * STAIR[2]
        c0, c1 = across - STAIR[0] / 2, across + STAIR[0] / 2
        roof_holes.append(_rect(s, *sorted((bottom + sign * open_roof, top)), c0, c1))
        hall_holes.append(_rect(s, *sorted((bottom + sign * open_hall, top)), c0, c1))
        for k in range(steps):
            a0, a1 = sorted((bottom + sign * k * STAIR[2], bottom + sign * (k + 1) * STAIR[2]))
            r = _rect(s, a0, a1, c0, c1)
            solids.box(mesh, r[0], r[1], track + PLATFORM_HEIGHT, r[2], r[3],
                       track + PLATFORM_HEIGHT + (k + 1) * rise, U_STATION_STAIRS)
        # Walls round the stair between the station's roof and the hall's floor.
        z0, z1 = s.roof, s.hall_floor - HALL_SHELL
        lo, hi = sorted((bottom + sign * open_roof, top))
        w = .2
        for r in (_rect(s, lo - w, hi + w, c0 - w, c0), _rect(s, lo - w, hi + w, c1, c1 + w),
                  _rect(s, lo - w, lo, c0, c1), _rect(s, hi, hi + w, c0, c1)):
            solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, U_STATION_WALL)
    _room(mesh, s.x, s.y, hx, hy, track, HEADROOM, SHELL, openings, U_STATION_WALL, U_SUBWAY_TRACKBED,
          roof_holes=roof_holes, ceiling_material=U_STATION_CEILING)
    _platforms(mesh, s)
    _hall(mesh, s, hall_holes)
    _stair_parapets(mesh, s)
    for e in s.entrances:
        _entrance(mesh, s, e)


def _stair_parapets(mesh, s):
    """A parapet round each stair's opening in the hall's floor, as round an
    entrance's at the street: along both sides and across its low end, the
    head (where the stair arrives) open."""
    if STAIR_PARAPET <= 0:
        return
    w = ENTRANCE[1]
    f = s.hall_floor
    for a0, a1, c0, c1, climb in s.stair_openings():
        lo, hi = a0 - s.centre, a1 - s.centre
        low_end = lo if climb > 0 else hi
        for b0, b1, u0, u1 in ((lo, hi, c0 - w, c0), (lo, hi, c1, c1 + w)):
            r = s.hall_rect(b0, b1, u0, u1)
            mesh_box(mesh, r, f, f + STAIR_PARAPET)
        e0, e1 = sorted((low_end, low_end - climb * w))
        r = s.hall_rect(e0, e1, c0 - w, c1 + w)
        mesh_box(mesh, r, f, f + STAIR_PARAPET)


def mesh_box(mesh, r, z0, z1):
    from . import solids
    solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, U_STATION_ENTRANCE)


def _platforms(mesh, s):
    """Platforms with a painted strip along each edge over the tracks, and
    steps at their ends down to the track bed."""
    from . import solids
    track = s.track
    count, going = END_STEPS
    stop = s.platform_length / 2 - count * going
    for c0, c1 in s.platforms():
        # The edges over a track: a side platform's inner one, both of an island's.
        edges = [c0, c1] if s.kind == 'island' else ([c0] if c0 > 0 else [c1])
        cuts = sorted({c0, c1} | {c0 + EDGE_STRIP if e == c0 else c1 - EDGE_STRIP for e in edges})
        for u0, u1 in zip(cuts, cuts[1:]):
            strip = (c0 in edges and abs(u0 - c0) < 1e-6) or (c1 in edges and abs(u1 - c1) < 1e-6)
            r = _rect(s, s.centre - stop, s.centre + stop, u0, u1)
            solids.box(mesh, r[0], r[1], track, r[2], r[3], track + PLATFORM_HEIGHT,
                       U_STATION_EDGE if strip else U_STATION_PLATFORM)
        for end in (1, -1):
            for k in range(count - 1):
                a0, a1 = sorted((s.centre + end * (stop + k * going), s.centre + end * (stop + (k + 1) * going)))
                r = _rect(s, a0, a1, c0, c1)
                solids.box(mesh, r[0], r[1], track, r[2], r[3], track + PLATFORM_HEIGHT * (count - 1 - k) / count,
                           U_STATION_PLATFORM)


def _hall(mesh, s, hall_holes):
    """The ticket hall: its shell with the doorways into it, then the fare
    lines' booths and the bathrooms."""
    from . import tunnels
    hhx, hhy = (HALL[0], s.side_half) if s.axis == 'x' else (s.side_half, HALL[0])
    openings = {}
    end_sides = ('-x', '+x') if s.axis == 'x' else ('-y', '+y')
    for e in s.entrances:
        side = end_sides[1] if e.sign > 0 else end_sides[0]
        centre = s.line + (e.across[0] + e.across[1]) / 2
        openings.setdefault(side, []).append(
            (centre, lambda u, f=s.hall_floor, w=e.across[1] - e.across[0]: _rect_opening(u, w, f, ENTRANCE[2],
                                                                                       U_STATION_WALL)))
    for access in s.accesses:
        t = access.tunnel
        if access.lead is not None:
            openings.setdefault(_hall_wall_side(s, access.wall), []).append(
                (access.door, lambda u, f=s.hall_floor: _rect_opening(u, 1.6, f, 2.1, U_STATION_WALL)))
            continue
        hall_side = ('+' if access.side > 0 else '-') + ('y' if s.axis == 'x' else 'x')
        if access.drop is not None:
            factory = lambda u, f=s.hall_floor: _rect_opening(u, tunnels.WIDTH, f, _sewers.OPENING['trunk'],  # noqa: E731
                                                              U_STATION_WALL)
        else:
            factory = lambda u, f=s.hall_floor: _rect_opening(u, 1.6, f, 2.1, U_STATION_WALL)  # noqa: E731
        openings.setdefault(hall_side, []).append((t.line, factory))
    for link in s.links:
        side = _hall_wall_side(s, link.wall)
        openings.setdefault(side, []).append(
            (link.door, lambda u, f=s.hall_floor: _rect_opening(u, SERVICE_DOOR[0], f, SERVICE_DOOR[1], U_STATION_WALL)))
    _room(mesh, s.x, s.y, hhx, hhy, s.hall_floor, HALL[1], HALL_SHELL, openings, U_STATION_WALL, U_STATION_FLOOR,
          floor_holes=hall_holes, ceiling_material=U_STATION_CEILING)
    for fare in s.fares:
        _booth(mesh, s, fare)
    if s.baths is not None:
        _bathrooms(mesh, s, s.baths)
    for kiosk in s.kiosks:
        _kiosk(mesh, s, kiosk)


def _wall(mesh, s, a0, a1, c0, c1, z0, z1, material, holes=()):
    """A wall in hall coordinates (a box along ``a`` or ``c``) with
    rectangular ``holes`` (from, to, bottom, top) along its length."""
    from . import solids
    a0, a1 = sorted((a0, a1))
    c0, c1 = sorted((c0, c1))
    along = (a1 - a0) >= (c1 - c0)
    lo, hi = (a0, a1) if along else (c0, c1)
    marks = sorted({lo, hi} | {v for h in holes for v in h[:2]})
    for u0, u1 in zip(marks, marks[1:]):
        if u1 - u0 < 1e-5:
            continue
        hole = next((h for h in holes if h[0] - 1e-6 <= u0 and u1 <= h[1] + 1e-6), None)
        levels = [(z0, z1)] if hole is None else [(z0, hole[2]), (hole[3], z1)]
        for b, t in levels:
            if t - b < 1e-5:
                continue
            r = s.hall_rect(u0, u1, c0, c1) if along else s.hall_rect(a0, a1, u0, u1)
            solids.box(mesh, r[0], r[1], b, r[2], r[3], t, material)


def _booth(mesh, s, fare):
    """A ticket booth straddling the fare line: its window towards the
    entrance, its door on the platforms' side."""
    from . import solids
    w, d, h, t = BOOTH
    f, z = s.hall_floor, fare.at
    c0, c1 = fare.booth - w / 2, fare.booth + w / 2
    near, far = z + fare.sign * d / 2, z - fare.sign * d / 2       # Towards the entrance; towards the platforms.
    win = (fare.booth - WINDOW[0] / 2, fare.booth + WINDOW[0] / 2, f + WINDOW[1], f + WINDOW[2])
    door = (fare.booth - SMALL_DOOR[0] / 2, fare.booth + SMALL_DOOR[0] / 2, f, f + SMALL_DOOR[1])
    _wall(mesh, s, near - fare.sign * t, near, c0, c1, f, f + h - t, U_STATION_BOOTH, [win])
    _wall(mesh, s, far, far + fare.sign * t, c0, c1, f, f + h - t, U_STATION_BOOTH, [door])
    a0, a1 = sorted((near - fare.sign * t, far + fare.sign * t))
    for u0, u1 in ((c0, c0 + t), (c1 - t, c1)):
        _wall(mesh, s, a0, a1, u0, u1, f, f + h - t, U_STATION_BOOTH)
    a0, a1 = sorted((near, far))
    r = s.hall_rect(a0, a1, c0, c1)
    solids.box(mesh, r[0], r[1], f + h - t, r[2], r[3], f + h, U_STATION_BOOTH)


def _bathrooms(mesh, s, baths):
    """Two bathrooms against a side wall: tiled walls to the ceiling, a door
    each from the hall, two stalls along the back wall."""
    t = PARTITION
    f, top = s.hall_floor, s.hall_floor + HALL[1]
    side = baths.side
    wall = side * s.side_half
    front = baths.c0
    rooms = baths.rooms()
    doors = [(r0 + .6, r0 + .6 + SMALL_DOOR[0], f, f + SMALL_DOOR[1]) for r0, _ in rooms]
    _wall(mesh, s, baths.a0, baths.a1, front, front + side * t, f, top, U_STATION_TILE, doors)
    mid = (baths.a0 + baths.a1) / 2
    for a0, a1 in ((baths.a0, baths.a0 + t), (mid - t / 2, mid + t / 2), (baths.a1 - t, baths.a1)):
        _wall(mesh, s, a0, a1, front + side * t, wall, f, top, U_STATION_TILE)
    width, depth, height, panel, gap = STALL
    for r0, r1 in rooms:
        back = wall - side * depth
        for k in range(2):
            b0 = r1 - (k + 1) * width
            # A panel between stalls (or on the open side), and a front with its door gap.
            _wall(mesh, s, b0 - panel, b0, back, wall, f, f + height, U_STATION_BOOTH)
            middle = b0 + width / 2
            _wall(mesh, s, b0, b0 + width, back - side * panel, back, f, f + height, U_STATION_BOOTH,
                  [(middle - gap / 2, middle + gap / 2, f, f + height)])


def _kiosk(mesh, s, k):
    """A kiosk against the hall's side wall (its back): a serving window
    in its front, a door in one end, a roof."""
    from . import solids
    w, d, h, t = KIOSK
    f = s.hall_floor
    wall = k.side * s.side_half
    mid = (k.a0 + k.a1) / 2
    window = (mid - KIOSK_WINDOW[0] / 2, mid + KIOSK_WINDOW[0] / 2, f + KIOSK_WINDOW[1], f + KIOSK_WINDOW[2])
    _wall(mesh, s, k.a0, k.a1, k.c0, k.c0 + k.side * t, f, f + h - t, U_STATION_BOOTH, [window])
    inner = k.c0 + k.side * t
    c_door = (inner + wall) / 2
    door = (c_door - SMALL_DOOR[0] / 2, c_door + SMALL_DOOR[0] / 2, f, f + SMALL_DOOR[1])
    _wall(mesh, s, k.a0, k.a0 + t, inner, wall, f, f + h - t, U_STATION_BOOTH, [door])
    _wall(mesh, s, k.a1 - t, k.a1, inner, wall, f, f + h - t, U_STATION_BOOTH)
    r = s.hall_rect(k.a0, k.a1, k.c0, wall)
    solids.box(mesh, r[0], r[1], f + h - t, r[2], r[3], f + h, U_STATION_BOOTH)


def furniture(s):
    """Every prop of a station as (type, x, y, z, facing x, facing y): its
    bathrooms' toilets and sinks, kiosks' counters, benches and bins."""
    found = []

    def put(kind, along, across, z, fa, fc):
        x, y = s.point(s.centre + along, across)
        fx, fy = (fa, fc) if s.axis == 'x' else (fc, fa)
        found.append((kind, x, y, z, fx, fy))

    for kind, a, c, facing in stall_fixtures(s):
        put(kind, a, c, s.hall_floor, 0.0, float(facing))
    for k in s.kiosks:
        put('shop_counter', (k.a0 + k.a1) / 2, k.c0 + k.side * (KIOSK[3] + .45), s.hall_floor, 0.0, -float(k.side))
    for kind, a, c, level, (fa, fc) in s.furniture:
        put(kind, a, c, s.hall_floor if level == 'hall' else s.track + PLATFORM_HEIGHT, fa, fc)
    return found


def stall_fixtures(s):
    """Toilets and sinks in a station's bathrooms (hall coordinates): (type,
    along, across, facing across sign)."""
    if s.baths is None:
        return []
    b = s.baths
    found = []
    width, depth = STALL[0], STALL[1]
    wall = b.side * s.side_half
    for r0, r1 in b.rooms():
        for k in range(2):
            found.append(('toilet', r1 - (k + .5) * width, wall - b.side * .4, -b.side))
        for k in range(2):
            found.append(('sink', r0 + 1.9 + .3 + .7 * k, b.c0 + b.side * (PARTITION + .3), b.side))
    return found


def _entrance(mesh, station, e):
    from . import solids
    clear, wall, headroom = ENTRANCE
    c0, c1 = e.across
    slope = e.rise / STAIR[2]

    def box(a0, a1, u0, u1, z0, z1, mat):
        lo, hi = sorted((e.start + e.sign * a0, e.start + e.sign * a1))
        r = _rect(station, lo, hi, u0, u1)
        solids.box(mesh, r[0], r[1], z0, r[2], r[3], z1, mat)

    for k in range(e.steps):
        box(k * STAIR[2], (k + 1) * STAIR[2], c0, c1, e.floor, e.floor + (k + 1) * e.rise, U_STATION_STAIRS)
    # Walls: below the ground where covered, rising to a parapet round the opening.
    low = e.floor - HALL_SHELL
    for u0, u1 in ((c0 - wall, c0), (c1, c1 + wall)):
        box(0.0, e.open, u0, u1, low, e.buried, U_STATION_ENTRANCE)
        box(e.open, e.run, u0, u1, low, e.top + PARAPET, U_STATION_ENTRANCE)
    # The sloping ceiling over the covered part, and the parapet across its upper end.
    lo, hi = sorted((e.start, e.start + e.sign * e.open))
    corners = []
    for z in (headroom, headroom + HALL_SHELL):
        for along, u in ((lo, c0), (hi, c0), (hi, c1), (lo, c1)):
            d = abs(along - e.start)
            corners.append((*station.point(along, u), e.floor + slope * d + z))
    _sewers._solid(mesh, corners[:4], corners[4:], U_STATION_ENTRANCE)
    ceiling_end = e.floor + slope * e.open + headroom
    box(e.open, e.open + wall, c0, c1, ceiling_end, e.top + PARAPET, U_STATION_ENTRANCE)


def _utility(mesh, utility):
    piece = utility.piece
    x, y = piece.point(utility.along, utility.across)
    half = utility.size / 2
    side = ('-y' if utility.across > 0 else '+y') if piece.axis == 'x' else ('-x' if utility.across > 0 else '+x')
    from . import tunnels
    openings = {side: [(utility.along, lambda u, f=utility.floor: _rect_opening(u, tunnels.WIDTH, f, tunnels.HEIGHT,
                                                                                 U_SERVICE_WALL))]}
    _room(mesh, x, y, half, half, utility.floor, utility.size, UTILITY_SHELL, openings, U_SERVICE_WALL,
          U_SERVICE_FLOOR, shaft=utility.exit, ceiling_material=U_SERVICE_WALL)


def _riser(mesh, riser):
    """The ladder shaft: open towards the line at the walkway and at the
    passage over the line's roof."""
    from . import solids, tunnels
    piece, a = riser.piece, riser.along
    t = RISER[1]
    half = tunnels.WIDTH / 2
    lo, hi = sorted((riser.near, riser.far))
    z0, top = riser.floor, riser.top

    def box(c0, c1, a0, a1, b, h, mat):
        if h - b < 1e-4:
            return
        r = _rect(piece, a0, a1, c0, c1)
        solids.box(mesh, r[0], r[1], b, r[2], r[3], h, mat)

    box(lo, hi, a - half - t, a + half + t, z0 - t, z0, U_SERVICE_FLOOR)
    for a0, a1 in ((a - half - t, a - half), (a + half, a + half + t)):
        box(lo, hi, a0, a1, z0, top - t, U_SERVICE_WALL)
    near = sorted((riser.near, riser.near + riser.side * t))
    box(near[0], near[1], a - half, a + half, z0 + tunnels.HEIGHT, riser.top_floor, U_SERVICE_WALL)
    back = sorted((riser.far - riser.side * t, riser.far))
    box(back[0], back[1], a - half, a + half, z0, top - t, U_SERVICE_WALL)
    box(lo, hi, a - half - t, a + half + t, top - t, top, U_SERVICE_WALL)


def _link(mesh, link):
    """Service rooms and corridors between a sewer's end chamber and a hall."""
    from . import tunnels
    for room in link.rooms:
        _room(mesh, room.x, room.y, room.hx, room.hy, room.floor, room.height, UTILITY_SHELL,
              {side: [(c, lambda u, f=room.floor: _rect_opening(u, SERVICE_DOOR[0], f, SERVICE_DOOR[1],
                                                                 U_SERVICE_WALL))] for side, c in room.doors},
              U_SERVICE_WALL, U_SERVICE_FLOOR, ceiling_material=U_SERVICE_WALL)
    for corridor in link.corridors:
        tunnels.build(mesh, corridor, U_SERVICE_WALL, U_SERVICE_FLOOR, U_SERVICE_WALL)


def tracks(subway):
    """The two tracks' centre lines from end to end at the track bed, in the
    line's direction: [left track points, right track points], each
    [(x, y, z)], parting round island platforms."""
    left, right = [], []

    def add(frame, offset):
        for points, sign in ((left, 1), (right, -1)):
            p = _frame_point(frame, sign * offset, 0.0)
            if points and math.dist(p, points[-1]) < 1e-6:
                continue
            points.append(p)

    order = []
    for k, run in enumerate(subway.runs):
        if k == 0:
            order.append(('station', run.a))
        order.append(('run', run))
        order.append(('station', run.b))
    for kind, item in order:
        if kind == 'run':
            for frame in item.frames():
                add(frame, TRACK)
            continue
        s = item
        nx, ny = (0.0, float(_left(s.axis, s.heading))) if s.axis == 'x' else (float(_left(s.axis, s.heading)), 0.0)
        L = s.half_length
        # Past an end station with a turning loop, on through the box where the tracks part to its openings.
        reach = SHELL + SPLIT_LENGTH
        lo = -L - (reach if s.loop_sign == -s.heading else 0.0)
        hi = L + (reach if s.loop_sign == s.heading else 0.0)
        count = max(2, int((hi - lo) / 2.0) + 1)
        for k in range(count):
            a = lo + (hi - lo) * k / (count - 1)
            along = s.centre + s.heading * a
            x, y = s.point(along)
            d = abs(a)
            if d > L:
                t = min(1.0, (d - L) / reach)
                offset = s.track_offset + (LOOP_TRACKS - s.track_offset) * (1 - math.cos(math.pi * t)) / 2
            elif s.kind == 'island' and d > s.platform_length / 2:
                t = min(1.0, (d - s.platform_length / 2) / SPLAY)
                offset = TRACK + (s.track_offset - TRACK) * (1 + math.cos(math.pi * t)) / 2
            else:
                offset = s.track_offset
            add((x, y, s.track, nx, ny), offset)
    return [left, right]


def loop_lines(subway):
    """Each turning loop's track centre line, from the box's opening it
    leaves by round to the one it comes back in by: [(station id, [(x, y,
    z)])]."""
    found = []
    for loop in subway.loops:
        points = []
        for bend in loop.bends:
            for x, y, z, _, _ in bend.frames():
                if points and math.dist((x, y, z), points[-1]) < 1e-6:
                    continue
                points.append((x, y, z))
        found.append((loop.station.id, points))
    return found
