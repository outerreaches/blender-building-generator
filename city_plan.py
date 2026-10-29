# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic city growth, independent of Blender. Coordinates are metres."""
from dataclasses import asdict, dataclass, field
from collections import deque
import hashlib
import heapq
import json
import math
import random

VERSION = 7
ROAD_WIDTHS = {"HIGHWAY": 20.0, "ARTERIAL": 12.0, "COLLECTOR": 8.0, "LOCAL": 6.0}
ROAD_RANK = {name: i for i, name in enumerate(ROAD_WIDTHS)}
# Corner radius at a route bend, before the curve_radius multiplier and clamping.
BEND_RADII = {"HIGHWAY": 26.0, "ARTERIAL": 18.0, "COLLECTOR": 12.0, "LOCAL": 8.0}
# District character. `parcels` divides a block per axis, `footprint` is the
# fraction of the parcel the building may use (the rest is yard/plaza), `road`
# scales local street growth, `curve` scales corner fillets and `damage`
# scales the city damage setting.
STYLE_PROFILE = {
    'DOWNTOWN': dict(floors=(8, 24), parcels=1, footprint=(.72, .92), density=1.25,
                     setback=2, road=1.2, curve=.5, damage=1.0),
    'OLD_TOWN': dict(floors=(2, 4), parcels=2, footprint=(.8, 1.0), density=1.0,
                     setback=0, road=1.0, curve=1.0, damage=1.0),
    'RESIDENTIAL': dict(floors=(2, 5), parcels=2, footprint=(.8, 1.0), density=1.0,
                        setback=0, road=1.0, curve=1.0, damage=.9),
    'BRUTALIST': dict(floors=(4, 8), parcels=2, footprint=(.85, 1.0), density=.95,
                      setback=.5, road=.85, curve=.8, damage=.8),
    'INDUSTRIAL': dict(floors=(1, 2), parcels=1, footprint=(.75, .95), density=.8,
                       setback=2, road=.6, curve=1.3, damage=1.2),
    'SUBURBAN': dict(floors=(1, 2), parcels=2, footprint=(.45, .65), density=1.0,
                     setback=3, road=.5, curve=1.4, damage=.3),
}
STYLES = tuple(STYLE_PROFILE)
# Points of interest (sites.py lays them out). ``blocks`` lists footprints in
# blocks (along the street, away from it), preferred first; ``count`` is the
# number per 100 built-up blocks and ``minimum`` how many any city gets when a
# block qualifies; ``front`` limits the road tiers a site may face (None: any
# but a highway); ``spacing`` is the least distance in blocks between two of a
# kind; ``districts`` weights district styles (styles left out only take a
# site when the minimum cannot be met otherwise).
POI_RULES = {
    'SHOPPING_PLAZA': dict(blocks=((2, 2),), count=.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                           spacing=8, districts={'SUBURBAN': 3, 'INDUSTRIAL': 1.5, 'RESIDENTIAL': 1}),
    'HOSPITAL': dict(blocks=((2, 1), (2, 2)), count=.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                     spacing=6, districts={'BRUTALIST': 3, 'DOWNTOWN': 2, 'RESIDENTIAL': 1.5,
                                           'OLD_TOWN': 1}),
    'SCHOOL': dict(blocks=((2, 1), (1, 1)), count=1, minimum=1, front=None, spacing=4,
                   districts={'RESIDENTIAL': 3, 'SUBURBAN': 2, 'BRUTALIST': 2, 'OLD_TOWN': 1}),
    'STRIP_MALL': dict(blocks=((1, 1), (2, 1)), count=1, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                       spacing=3, districts={'SUBURBAN': 3, 'RESIDENTIAL': 1.5, 'INDUSTRIAL': 1,
                                             'BRUTALIST': 1}),
    'PARK': dict(blocks=((1, 1), (2, 1)), count=2, minimum=1, front=None, spacing=2,
                 districts={'RESIDENTIAL': 3, 'OLD_TOWN': 2, 'BRUTALIST': 2, 'DOWNTOWN': 1.5,
                            'SUBURBAN': 1.5}),
    'TRANSIT_STATION': dict(blocks=((1, 1),), count=1, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                            spacing=4, districts={'DOWNTOWN': 3, 'BRUTALIST': 2, 'OLD_TOWN': 1.5,
                                                  'RESIDENTIAL': 1, 'INDUSTRIAL': 1}),
    'POLICE': dict(blocks=((1, 1),), count=.7, minimum=1, front=None, spacing=5,
                   districts={'DOWNTOWN': 2, 'OLD_TOWN': 2, 'BRUTALIST': 2, 'RESIDENTIAL': 1,
                              'SUBURBAN': 1}),
    'FIRE_STATION': dict(blocks=((1, 1),), count=1, minimum=1, front=None, spacing=4,
                         districts={'RESIDENTIAL': 2, 'OLD_TOWN': 2, 'INDUSTRIAL': 2, 'SUBURBAN': 1.5,
                                    'BRUTALIST': 1.5, 'DOWNTOWN': 1}),
    'PARKING_GARAGE': dict(blocks=((1, 1),), count=1.2, minimum=1, front=None, spacing=2,
                           districts={'DOWNTOWN': 4, 'BRUTALIST': 1, 'OLD_TOWN': .5}),
    'PARKING_LOT': dict(blocks=((1, 1),), count=1.2, minimum=1, front=None, spacing=2,
                        districts={'DOWNTOWN': 2, 'OLD_TOWN': 2, 'INDUSTRIAL': 1.5, 'BRUTALIST': 1}),
    'GAS_STATION': dict(blocks=((1, 1),), count=2, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                        spacing=3, districts={'SUBURBAN': 3, 'INDUSTRIAL': 2.5, 'RESIDENTIAL': 1.5,
                                              'BRUTALIST': 1, 'OLD_TOWN': .5}),
    'FAST_FOOD': dict(blocks=((1, 1),), count=2, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                      spacing=2, districts={'SUBURBAN': 3, 'RESIDENTIAL': 2, 'BRUTALIST': 1.5,
                                            'INDUSTRIAL': 1, 'OLD_TOWN': 1}),
}
# Smallest pad each kind is laid out for (mirrors sites.MIN_PAD).
POI_MIN_PAD = {'GAS_STATION': (24, 22), 'FAST_FOOD': (26, 24), 'SCHOOL': (40, 32),
               'HOSPITAL': (44, 32), 'POLICE': (28, 26), 'FIRE_STATION': (28, 26),
               'TRANSIT_STATION': (28, 24), 'PARK': (16, 16), 'PARKING_LOT': (20, 20),
               'PARKING_GARAGE': (30, 26), 'STRIP_MALL': (30, 26), 'SHOPPING_PLAZA': (80, 70)}
POI_VERGE = 1.0          # Unpaved strip between a site pad and the footway.
POI_MIN_DENSITY = .2     # Sites stay inside the built-up area.
MIDTOWN_STYLES = ('OLD_TOWN', 'RESIDENTIAL', 'BRUTALIST')

CONDITIONS = ('INTACT', 'WEATHERED', 'SEMI_COLLAPSED', 'RUBBLE_FILLED',
              'PARTIAL_FILLED', 'LOWER_FLOORS', 'SHELL', 'WALL_RING', 'COLLAPSED')
# Multipliers on the city damage setting; the minimums make the rarer states
# read even on a low-damage map. LOWER_FLOORS deliberately uses full damage so
# the cut lands in the first few storeys.
CONDITION_DAMAGE = {'INTACT': 1.0, 'WEATHERED': 1.3, 'SEMI_COLLAPSED': 1.7,
                    'RUBBLE_FILLED': 1.0, 'PARTIAL_FILLED': 1.2,
                    'LOWER_FLOORS': 1.0, 'SHELL': 1.5, 'WALL_RING': 1.2,
                    'COLLAPSED': 1.0}
CONDITION_MIN_DAMAGE = {'INTACT': 0.0, 'WEATHERED': 0.0, 'SEMI_COLLAPSED': .78,
                        'RUBBLE_FILLED': .35, 'PARTIAL_FILLED': .5,
                        'LOWER_FLOORS': 1.0, 'SHELL': .7, 'WALL_RING': .5,
                        'COLLAPSED': 0.0}
INTERIOR_CONDITIONS = ('INTACT', 'WEATHERED', 'SEMI_COLLAPSED', 'LOWER_FLOORS')
CONDITION_WEIGHTS = {
    'DOWNTOWN': (('INTACT', 8), ('WEATHERED', 20), ('SEMI_COLLAPSED', 28),
                 ('RUBBLE_FILLED', 10), ('PARTIAL_FILLED', 10), ('LOWER_FLOORS', 6),
                 ('SHELL', 12), ('WALL_RING', 3), ('COLLAPSED', 3)),
    'OLD_TOWN': (('INTACT', 36), ('WEATHERED', 28), ('SEMI_COLLAPSED', 10),
                 ('RUBBLE_FILLED', 8), ('PARTIAL_FILLED', 8), ('LOWER_FLOORS', 4),
                 ('SHELL', 3), ('WALL_RING', 2), ('COLLAPSED', 1)),
    'RESIDENTIAL': (('INTACT', 42), ('WEATHERED', 28), ('SEMI_COLLAPSED', 8),
                    ('RUBBLE_FILLED', 7), ('PARTIAL_FILLED', 7), ('LOWER_FLOORS', 4),
                    ('SHELL', 2), ('WALL_RING', 1), ('COLLAPSED', 1)),
    'BRUTALIST': (('INTACT', 28), ('WEATHERED', 28), ('SEMI_COLLAPSED', 14),
                  ('RUBBLE_FILLED', 9), ('PARTIAL_FILLED', 8), ('LOWER_FLOORS', 6),
                  ('SHELL', 5), ('WALL_RING', 1), ('COLLAPSED', 1)),
    'INDUSTRIAL': (('INTACT', 32), ('WEATHERED', 24), ('SEMI_COLLAPSED', 8),
                   ('RUBBLE_FILLED', 8), ('PARTIAL_FILLED', 8), ('LOWER_FLOORS', 4),
                   ('SHELL', 10), ('WALL_RING', 4), ('COLLAPSED', 2)),
    'SUBURBAN': (('INTACT', 58), ('WEATHERED', 24), ('SEMI_COLLAPSED', 5),
                 ('RUBBLE_FILLED', 4), ('PARTIAL_FILLED', 4), ('LOWER_FLOORS', 2),
                 ('SHELL', 1), ('WALL_RING', 1), ('COLLAPSED', 1)),
}


def stream(seed, *keys):
    """Stable independent streams; never consume Blender's global random state."""
    payload = json.dumps([seed, *keys], separators=(",", ":")).encode()
    return random.Random(int.from_bytes(hashlib.sha256(payload).digest()[:8], "big"))


@dataclass(frozen=True)
class CitySettings:
    seed: int = 42
    radius: int = 6  # Half-width in blocks.
    block_size: float = 56.0
    primary_count: int = 6
    secondary_count: int = 12
    driving_loop_count: int = 3
    core_radius: float = 0.3  # Fraction of city half-width.
    core_density: float = 0.95
    outskirts_density: float = 0.15
    road_density: float = 0.55
    curve_radius: float = 0.6  # Fraction of the tier bend radius; 0 keeps square corners.
    setback: float = 2.0
    wasteland: float = 12000.0  # Metres of open ground beyond the city edge.
    sidewalk_width: float = 2.0
    curb_height: float = 0.15
    damage: float = 0.35
    interior_ratio: float = .25
    max_buildings: int = 600
    style: str = "MIXED"
    points_of_interest: bool = True   # Sites (sites.py) and transit stops.
    highway_reach: float = 3000.0     # Highway beyond the city edge (m), fading out at its end.
    downtown_superblocks: float = .35  # Share of downtown local streets closed to join blocks.

    def validate(self):
        for name, lo, hi in (("radius", 2, 25), ("primary_count", 1, 16),
                             ("secondary_count", 0, 100), ("max_buildings", 1, 10000),
                             ("driving_loop_count", 0, 8)):
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} must be an integer in [{lo}, {hi}]")
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
        for name, lo, hi in (("block_size", 48, 120), ("core_radius", .05, 1),
                             ("core_density", 0, 1), ("outskirts_density", 0, 1),
                             ("road_density", 0, 1), ("curve_radius", 0, 1),
                             ("damage", 0, 1), ("interior_ratio", 0, 1),
                             ("setback", 1, 8), ("wasteland", 0, 20000),
                             ("highway_reach", 0, 20000), ("downtown_superblocks", 0, 1),
                             ("sidewalk_width", 1.2, 5), ("curb_height", 0, .25)):
            value = getattr(self, name)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name} must be finite and in [{lo}, {hi}]")
        if self.style not in ("MIXED", *STYLES):
            raise ValueError("Unknown architecture style")


@dataclass(frozen=True)
class Location:
    id: str
    node: tuple
    role: str
    style: str


@dataclass(frozen=True)
class Road:
    a: tuple
    b: tuple
    tier: str

    @property
    def width(self):
        return ROAD_WIDTHS[self.tier]


@dataclass(frozen=True)
class Lot:
    id: str
    center: tuple
    width: float
    depth: float
    rotation: float
    style: str
    district: str
    floors: int
    seed: int
    frontage: tuple
    kind: str = 'BUILDING'
    condition: str = 'INTACT'
    interiors: bool = False
    damage: float = 0.0
    party_walls: tuple = ()   # Sides (front/back/left/right) built against a neighbour.
    group: str = ''           # Buildings of one downtown block share a budget draw.


@dataclass(frozen=True)
class Poi:
    """A point-of-interest site over one or more whole blocks."""
    id: str
    kind: str
    center: tuple
    width: float         # Along the frontage.
    depth: float
    rotation: float      # Same convention as Lot: the front faces (sin r, -cos r).
    frontage: tuple
    blocks: tuple
    style: str
    district: str
    seed: int
    approach: float      # Pad front to the back of the footway.
    condition: str = 'INTACT'
    damage: float = 0.0


@dataclass(frozen=True)
class Shelter:
    """A transit stop on a footway; its back faces the block."""
    id: str
    position: tuple
    rotation: float
    variant: str         # SHELTER or STOP.
    road: tuple


@dataclass
class CityPlan:
    settings: CitySettings
    locations: list
    roads: list
    paths: list
    lots: list
    eligible_lots: int
    driving_loops: list
    pois: list = field(default_factory=list)
    shelters: list = field(default_factory=list)
    outer_roads: list = field(default_factory=list)

    def to_json(self):
        return json.dumps({"version": VERSION, **asdict(self)}, sort_keys=True, indent=2)


def edge(a, b):
    return tuple(sorted((a, b)))


def density_at(settings, x, y):
    distance = math.hypot(x, y) / (settings.radius * settings.block_size)
    blend = min(1.0, max(0.0, (distance - settings.core_radius) /
                         max(.001, 1 - settings.core_radius)))
    blend = blend * blend * (3 - 2 * blend)
    return settings.core_density * (1 - blend) + settings.outskirts_density * blend


def district_at(settings, x, y, locations):
    """Nearest centre/primary location in world metres; defines the district."""
    size = settings.block_size
    return min((loc for loc in locations if loc.role != 'SECONDARY'),
               key=lambda loc: math.dist((x, y), (loc.node[0] * size, loc.node[1] * size)))


def _assign_districts(primaries):
    """Downtown core, midtown ring, industrial and suburban edges by sector."""
    order = sorted(primaries, key=lambda loc: (math.hypot(*loc.node), loc.node))
    edge_count = 2 if len(order) >= 5 else (1 if len(order) >= 3 else 0)
    core_count = 1 if len(order) >= 3 else 0
    assigned = {loc.id: 'DOWNTOWN' for loc in order[:core_count]}
    remaining = order[core_count:]
    # The outermost primary anchors the industrial edge; the location farthest
    # from it (roughly the opposite side of the map) anchors the suburbs.
    edge = []
    if edge_count and remaining:
        edge.append(remaining.pop())
    if edge_count > 1 and remaining:
        edge.append(max(remaining, key=lambda loc: (math.dist(loc.node, edge[0].node), loc.node)))
        remaining.remove(edge[-1])
    if edge:
        edge = sorted(edge, key=lambda loc: (loc.node[0], loc.node[1]))
        if len(edge) == 1:
            assigned[edge[0].id] = 'INDUSTRIAL' if edge[0].node[0] < 0 else 'SUBURBAN'
        else:
            assigned[edge[0].id] = 'INDUSTRIAL'
            assigned[edge[-1].id] = 'SUBURBAN'
    for index, loc in enumerate(remaining):
        assigned[loc.id] = MIDTOWN_STYLES[index % len(MIDTOWN_STYLES)]
    return assigned


def _route(start, target, roads, settings, blocked=frozenset()):
    """Dijkstra routing: favour existing streets, with stable corridor variation."""
    queue = [(0.0, start)]
    cost = {start: 0.0}
    parent = {}
    while queue:
        distance, node = heapq.heappop(queue)
        if distance != cost[node]:
            continue
        if node == target:
            path = [node]
            while node != start:
                node = parent[node]
                path.append(node)
            return list(reversed(path))
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            other = (node[0] + dx, node[1] + dy)
            if max(map(abs, other)) > settings.radius or other in blocked:
                continue
            key = edge(node, other)
            step = .65 if key in roads else 1 + stream(settings.seed, "route", key).random() * .4
            candidate = distance + step
            if candidate < cost.get(other, math.inf):
                cost[other], parent[other] = candidate, node
                heapq.heappush(queue, (candidate, other))
    return None


def _network_path(start, target, roads):
    graph = {}
    for a, b in roads:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    queue, parent = deque([start]), {start: None}
    while queue:
        node = queue.popleft()
        if node == target:
            path = []
            while node is not None:
                path.append(node)
                node = parent[node]
            return list(reversed(path))
        for other in sorted(graph.get(node, ())):
            if other not in parent:
                parent[other] = node
                queue.append(other)
    return None


def _add_driving_loops(settings, locations, roads):
    """Connect highway entry/exit pairs through districts without retracing a road.

    These are explicit multi-tier circuits, not merely a count of tiny grid cells.
    Only topology is built here; corner geometry comes from the route fillets,
    and bridges or banked roads are separate work.
    """
    if settings.driving_loop_count == 0:
        return []
    highway = {key: tier for key, tier in roads.items() if tier == 'HIGHWAY'}
    spine = _network_path((-settings.radius, 0), (settings.radius, 0), highway)
    highway_nodes = {node for key in highway for node in key}
    anchors = [loc.node for loc in locations if loc.node not in highway_nodes]
    fallback = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                for y in range(-settings.radius + 1, settings.radius)
                if (x, y) not in highway_nodes and (x, y) not in anchors]
    stream(settings.seed, 'loop_anchors').shuffle(fallback)
    anchors.extend(fallback)
    circuits, signatures = [], set()
    for anchor in anchors:
        nearest = min(range(len(spine)), key=lambda i: math.dist(anchor, spine[i]))
        span = max(2, settings.radius // 2)
        left, right = max(0, nearest - span), min(len(spine) - 1, nearest + span)
        if right - left < 2:
            continue
        start, end = spine[left], spine[right]
        # Keep the outward leg from touching any other highway node or the exit.
        outward = _route(start, anchor, roads, settings, highway_nodes - {start})
        if outward is None:
            continue
        returning = _route(anchor, end, roads, settings,
                           (highway_nodes - {end}) | set(outward[:-1]))
        if returning is None:
            continue
        street_path = outward + returning[1:]
        nodes = street_path + list(reversed(spine[left:right]))
        keys = [edge(a, b) for a, b in zip(nodes, nodes[1:])]
        signature = frozenset(keys)
        if len(keys) < 6 or signature in signatures:
            continue
        signatures.add(signature)
        for a, b in zip(street_path, street_path[1:]):
            key = edge(a, b)
            if key not in roads:
                roads[key] = 'COLLECTOR'
        circuits.append({'id': f'driving_loop_{len(circuits)}', 'nodes': nodes,
                         'length_m': len(keys) * settings.block_size,
                         'tiers': sorted({roads[key] for key in keys})})
        if len(circuits) == settings.driving_loop_count:
            break
    return circuits


def _unit(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (0.0, 0.0)


def _fillet_points(nodes, size, tier, curve_radius, scales=None):
    """Flatten corner arcs into a metre-space centreline for one route.

    Tangent length is capped at 45% of each adjacent edge, so two bends on one
    block never meet. The route therefore keeps its lattice topology while every
    interior corner becomes an arc of ``BEND_RADII[tier] * curve_radius``.
    """
    base = [(n[0] * size, n[1] * size) for n in nodes]
    base_radius = BEND_RADII[tier] * curve_radius
    if base_radius <= 0:
        points = list(base)
    else:
        points = [base[0]]
        for index in range(1, len(base) - 1):
            radius = base_radius * (scales[index] if scales else 1.0)
            if radius <= 0:
                continue
            previous, corner, following = base[index - 1], base[index], base[index + 1]
            ux, uy = _unit(previous, corner)
            vx, vy = _unit(corner, following)
            turn = math.acos(max(-1.0, min(1.0, ux * vx + uy * vy)))
            cross = ux * vy - uy * vx
            if turn < 1e-4 or abs(cross) < 1e-9:
                continue
            tangent = radius * math.tan(turn / 2)
            limit = 0.45 * min(math.dist(previous, corner), math.dist(corner, following))
            if tangent > limit:
                tangent = limit
                arc_radius = tangent / math.tan(turn / 2)
            else:
                arc_radius = radius
            sign = 1 if cross > 0 else -1
            start = (corner[0] - ux * tangent, corner[1] - uy * tangent)
            end = (corner[0] + vx * tangent, corner[1] + vy * tangent)
            centre = (start[0] - uy * arc_radius * sign,
                      start[1] + ux * arc_radius * sign)
            angle = math.atan2(start[1] - centre[1], start[0] - centre[0])
            steps = max(2, math.ceil(turn / math.radians(12)))
            points.append(start)
            for step in range(1, steps):
                theta = angle + sign * turn * step / steps
                points.append((centre[0] + arc_radius * math.cos(theta),
                               centre[1] + arc_radius * math.sin(theta)))
            points.append(end)
        points.append(base[-1])
    return points


def _build_paths(settings, roads, locations):
    """Group lattice edges into continuous same-tier routes, then round corners."""
    adjacency = {}
    for (a, b), tier in roads.items():
        adjacency.setdefault(a, []).append((b, tier))
        adjacency.setdefault(b, []).append((a, tier))
    for node in adjacency:
        adjacency[node].sort()
    used = set()
    paths = []

    def continuation(path, tier, forward):
        end, inner = (path[-1], path[-2]) if forward else (path[0], path[1])
        ux, uy = _unit(inner, end)
        options = [(other, other_tier) for other, other_tier in adjacency[end]
                   if other_tier == tier and edge(end, other) not in used]
        if not options:
            return None
        # Straightest continuation wins; coordinates break exact ties.
        return min(options, key=lambda item: (-(ux * _unit(end, item[0])[0] +
                                                uy * _unit(end, item[0])[1]), item[0]))

    for a, b in sorted(roads):
        key = edge(a, b)
        if key in used:
            continue
        tier = roads[key]
        used.add(key)
        nodes = [a, b]
        while True:
            option = continuation(nodes, tier, True)
            if option is None:
                break
            used.add(edge(nodes[-1], option[0]))
            nodes.append(option[0])
        while True:
            option = continuation(nodes, tier, False)
            if option is None:
                break
            used.add(edge(nodes[0], option[0]))
            nodes.insert(0, option[0])
        scales = [STYLE_PROFILE[district_at(settings, node[0] * settings.block_size,
                                            node[1] * settings.block_size,
                                            locations).style]['curve'] for node in nodes]
        points = _fillet_points(nodes, settings.block_size, tier, settings.curve_radius,
                                scales)
        paths.append({'id': f'road_path_{len(paths)}', 'tier': tier,
                      'width': ROAD_WIDTHS[tier], 'nodes': nodes,
                      'points': points})
    return paths


def generate_city(settings=CitySettings()):
    settings.validate()
    roads = {}
    center = (0, 0)
    locations = [Location("center", center, "CENTER",
                          "DOWNTOWN" if settings.style == "MIXED" else settings.style)]
    occupied = {center}

    def connect(a, b, tier):
        path = _route(a, b, roads, settings)
        if path is None:
            raise ValueError('Unable to connect location')
        for u, v in zip(path, path[1:]):
            key = edge(u, v)
            if key not in roads or ROAD_RANK[tier] < ROAD_RANK[roads[key]]:
                roads[key] = tier

    # Major destinations grow around the center before neighbourhood infill.
    candidates = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                  for y in range(-settings.radius + 1, settings.radius)
                  if .3 * settings.radius <= math.hypot(x, y) <= .85 * settings.radius]
    rng = stream(settings.seed, "locations")
    rng.shuffle(candidates)
    for index in range(min(settings.primary_count, len(candidates))):
        # Farthest-point sampling spreads primary destinations across districts.
        node = max(candidates, key=lambda p: min(math.dist(p, q) for q in occupied))
        candidates.remove(node)
        occupied.add(node)
        locations.append(Location(f"primary_{index}", node, "PRIMARY", settings.style))
        connect(node, center, "ARTERIAL")

    # MIXED gives each district a role: downtown core, midtown ring, and
    # industrial/suburban edges on opposite sides of the map.
    if settings.style == "MIXED":
        assigned = _assign_districts(locations[1:])
        locations = [Location(loc.id, loc.node, loc.role, assigned.get(loc.id, loc.style))
                     for loc in locations]

    # Regional links extend to opposite map boundaries; these are at-grade prototypes.
    for end in ((-settings.radius, 0), (settings.radius, 0)):
        connect(end, center, "HIGHWAY")

    candidates = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                  for y in range(-settings.radius + 1, settings.radius) if (x, y) not in occupied]
    rng.shuffle(candidates)
    for index, node in enumerate(candidates[:settings.secondary_count]):
        district = min((loc for loc in locations if loc.role != 'SECONDARY'),
                       key=lambda loc: math.dist(node, loc.node))
        network = {n for road in roads for n in road}
        target = min(sorted(network), key=lambda n: math.dist(node, n))
        connect(node, target, "COLLECTOR")
        # A node already on a road needs no extra edge.
        locations.append(Location(f"secondary_{index}", node, "SECONDARY", district.style))

    driving_loops = _add_driving_loops(settings, locations, roads)

    # Local growth starts from connected nodes only; loops naturally meet old streets.
    reached = {n for road in roads for n in road}
    frontier = sorted(reached, key=lambda p: (math.hypot(*p), p))
    tested = set(roads)
    for node in frontier:
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            other = (node[0] + dx, node[1] + dy)
            key = edge(node, other)
            if key in tested or max(map(abs, other)) > settings.radius:
                continue
            tested.add(key)
            x, y = ((node[i] + other[i]) * settings.block_size / 2 for i in range(2))
            profile = STYLE_PROFILE[district_at(settings, x, y, locations).style]
            chance = (settings.road_density * profile['road'] *
                      (.2 + .8 * density_at(settings, x, y)))
            if stream(settings.seed, "local", key).random() <= chance:
                roads[key] = "LOCAL"
                if other not in reached:
                    reached.add(other)
                    frontier.append(other)

    _close_downtown_streets(settings, locations, roads)
    road_list = [Road(a, b, tier) for (a, b), tier in sorted(roads.items())]
    paths = _build_paths(settings, roads, locations)
    pois = _place_pois(settings, locations, roads, paths) if settings.points_of_interest else []
    reserved = {block for poi in pois for block in poi.blocks}
    downtown, dense = _place_downtown(settings, locations, roads, paths, reserved)
    lots = downtown + _place_lots(settings, locations, roads, reserved | dense)
    # Stable priority sampling avoids truncating one geographical side of the
    # city; the buildings of one downtown block are kept or dropped together.
    lots.sort(key=lambda lot: (stream(settings.seed, "budget", lot.group or lot.id).random(), lot.id))
    eligible = len(lots)
    lots = sorted(lots[:settings.max_buildings], key=lambda lot: lot.id)
    shelters = _place_shelters(settings, roads, lots, pois) if settings.points_of_interest else []
    return CityPlan(settings, locations, road_list, paths, lots, eligible, driving_loops,
                    pois, shelters, _outer_roads(settings, paths))


def _pick_condition(style, rng):
    roll = rng.uniform(0, 100)
    for condition, weight in CONDITION_WEIGHTS[style]:
        roll -= weight
        if roll <= 0:
            return condition
    return 'INTACT'


def _place_lots(settings, locations, roads, reserved=frozenset()):
    lots = []
    size = settings.block_size
    # Use actual adjacent street envelopes rather than the widest road citywide.
    nodes = {}
    for (a, b), tier in roads.items():
        for node in (a, b):
            nodes[node] = max(nodes.get(node, 0), ROAD_WIDTHS[tier] / 2)
    for x in range(-settings.radius, settings.radius):
        for y in range(-settings.radius, settings.radius):
            if (x, y) in reserved:
                continue
            borders = {"S": edge((x, y), (x + 1, y)),
                       "N": edge((x, y + 1), (x + 1, y + 1)),
                       "W": edge((x, y), (x, y + 1)),
                       "E": edge((x + 1, y), (x + 1, y + 1))}
            district = district_at(settings, (x + .5) * size, (y + .5) * size, locations)
            profile = STYLE_PROFILE[district.style]
            cells = profile['parcels']
            margins = {}
            for side, (a, b) in borders.items():
                half = max(nodes.get(a, 0), nodes.get(b, 0))
                # District setback adds the front yard, plaza or hardstanding.
                margins[side] = (half + settings.sidewalk_width + 2 + settings.setback +
                                 profile['setback'] + .5)
            low_x = x * size + margins["W"]
            high_x = (x + 1) * size - margins["E"]
            low_y = y * size + margins["S"]
            high_y = (y + 1) * size - margins["N"]
            cell_x = (high_x - low_x - 2 * (cells - 1)) / cells
            cell_y = (high_y - low_y - 2 * (cells - 1)) / cells
            if min(cell_x, cell_y) < 5:
                continue
            for ix in range(cells):
                for iy in range(cells):
                    ident = f"lot_{x}_{y}_{ix}_{iy}"
                    rng = stream(settings.seed, ident)
                    sides = []
                    for side, available in (("W", ix == 0), ("E", ix == cells - 1),
                                            ("S", iy == 0), ("N", iy == cells - 1)):
                        if available and borders[side] in roads and roads[borders[side]] != "HIGHWAY":
                            sides.append(side)
                    if not sides:
                        continue
                    cell_low_x = low_x + ix * (cell_x + 2)
                    cell_low_y = low_y + iy * (cell_y + 2)
                    cell_high_x = cell_low_x + cell_x
                    cell_high_y = cell_low_y + cell_y
                    cx, cy = (cell_low_x + cell_high_x) / 2, (cell_low_y + cell_high_y) / 2
                    density = min(1.0, density_at(settings, cx, cy) * profile['density'])
                    if rng.random() > density:
                        continue
                    side = rng.choice(sides)
                    # The unused part of the parcel is the yard, plaza or hardstanding.
                    sx = cell_x * rng.uniform(*profile['footprint'])
                    sy = cell_y * rng.uniform(*profile['footprint'])
                    if min(sx, sy) < 5:
                        continue
                    # Align the front wall with the street-facing parcel line.
                    if side == "W":
                        cx = cell_low_x + sx / 2
                    elif side == "E":
                        cx = cell_high_x - sx / 2
                    elif side == "S":
                        cy = cell_low_y + sy / 2
                    else:
                        cy = cell_high_y - sy / 2
                    condition_rng = stream(settings.seed, "condition", ident)
                    condition = _pick_condition(district.style, condition_rng)
                    floors = rng.randint(*profile['floors'])
                    if condition == 'WALL_RING':
                        floors = min(floors, rng.randint(2, 4))
                    width, depth = (sy, sx) if side in "WE" else (sx, sy)
                    rotation = {"S": 0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}[side]
                    damage = min(1.0, max(
                        settings.damage * profile['damage'] * CONDITION_DAMAGE[condition],
                        CONDITION_MIN_DAMAGE[condition]))
                    if floors > 8:
                        # Tall towers carry more visible damage than low-rise blocks.
                        damage = min(1.0, damage * (1 + min(.5, (floors - 8) * .045)))
                    interiors = (condition in INTERIOR_CONDITIONS and
                                 condition_rng.random() < settings.interior_ratio)
                    lots.append(Lot(ident, (cx, cy), width, depth, rotation,
                                    district.style, district.id, floors,
                                    rng.randrange(2**31), borders[side],
                                    condition=condition, interiors=interiors,
                                    damage=damage))
    return lots


# -- points of interest ------------------------------------------------------

SIDE_ROTATION = {"S": 0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}


def _side_edges(x, y, wx, wy):
    """Lattice edges along each outer side of a wx x wy block group at (x, y)."""
    return {"S": [edge((x + i, y), (x + i + 1, y)) for i in range(wx)],
            "N": [edge((x + i, y + wy), (x + i + 1, y + wy)) for i in range(wx)],
            "W": [edge((x, y + j), (x, y + j + 1)) for j in range(wy)],
            "E": [edge((x + wx, y + j), (x + wx, y + j + 1)) for j in range(wy)]}


def _inner_edges(x, y, wx, wy):
    inner = [edge((x + i, y + j), (x + i, y + j + 1)) for i in range(1, wx) for j in range(wy)]
    inner += [edge((x + i, y + j), (x + i + 1, y + j)) for j in range(1, wy) for i in range(wx)]
    return inner


def _best_front(rule, sides, roads, along):
    """The side a site faces: best road tier, most road along it, required length."""
    best = None
    for side, edges in sides.items():
        if len(edges) != along:
            continue
        tiers = [roads.get(e) for e in edges]
        if "HIGHWAY" in tiers:
            continue
        allowed = [e for e, t in zip(edges, tiers)
                   if t is not None and (rule['front'] is None or t in rule['front'])]
        if not allowed:
            continue
        frontage = min(allowed, key=lambda e: (ROAD_RANK[roads[e]], e))
        key = (ROAD_RANK[roads[frontage]], -sum(t is not None for t in tiers), side)
        if best is None or key < best[0]:
            best = (key, side, frontage)
    return None if best is None else best[1:]


def _path_rows(paths):
    rows = []
    for path in paths:
        half = path['width'] / 2
        for a, b in zip(path['points'], path['points'][1:]):
            rows.append((a[0], a[1], b[0], b[1], half))
    return rows


def _gap(px, py, rows):
    best = math.inf
    for x0, y0, x1, y1, half in rows:
        dx, dy = x1 - x0, y1 - y0
        length = dx * dx + dy * dy
        t = 0.0 if not length else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length))
        best = min(best, math.hypot(px - x0 - dx * t, py - y0 - dy * t) - half)
    return best


def _poi_pad(settings, x, y, wx, wy, nodes, rows, verge=POI_VERGE):
    """Pad rectangle inside a block group, ``verge`` metres back from every
    footway (fillets too)."""
    size = settings.block_size
    walk = settings.sidewalk_width
    rect = [x * size, y * size, (x + wx) * size, (y + wy) * size]
    for side, edges in _side_edges(x, y, wx, wy).items():
        half = max(max(nodes.get(a, 0), nodes.get(b, 0)) for a, b in edges)
        margin = half + walk + verge if half > 0 else verge
        index, sign = {"W": (0, 1), "S": (1, 1), "E": (2, -1), "N": (3, -1)}[side]
        rect[index] += sign * margin
    near = [r for r in rows
            if min(r[0], r[2]) - r[4] - 40 < rect[2] and max(r[0], r[2]) + r[4] + 40 > rect[0]
            and min(r[1], r[3]) - r[4] - 40 < rect[3] and max(r[1], r[3]) + r[4] + 40 > rect[1]]
    need = walk + min(.5, verge)
    for _ in range(8):
        x0, y0, x1, y1 = rect
        if x1 - x0 < 10 or y1 - y0 < 10:
            return None
        lines = {"S": ((x0, y0), (x1, y0)), "N": ((x0, y1), (x1, y1)),
                 "W": ((x0, y0), (x0, y1)), "E": ((x1, y0), (x1, y1))}
        worst = {}
        for side, ((ax, ay), (bx, by)) in lines.items():
            length = math.hypot(bx - ax, by - ay)
            count = max(2, int(length / 2))
            for k in range(count + 1):
                t = (.4 + (length - .8) * k / count) / length
                value = _gap(ax + (bx - ax) * t, ay + (by - ay) * t, near) - need
                if value < worst.get(side, 0.0):
                    worst[side] = value
        if not worst:
            return tuple(rect)
        for side, value in worst.items():
            index, sign = {"W": (0, 1), "S": (1, 1), "E": (2, -1), "N": (3, -1)}[side]
            rect[index] += sign * (.1 - value)
    return None


def _place_pois(settings, locations, roads, paths):
    size = settings.block_size
    nodes = {}
    for (a, b), tier in roads.items():
        for node in (a, b):
            nodes[node] = max(nodes.get(node, 0), ROAD_WIDTHS[tier] / 2)
    rows = _path_rows(paths)
    radius = settings.radius
    urban = sum(1 for x in range(-radius, radius) for y in range(-radius, radius)
                if density_at(settings, (x + .5) * size, (y + .5) * size) >= POI_MIN_DENSITY and
                any(e in roads for e in _side_edges(x, y, 1, 1)["S"] + _side_edges(x, y, 1, 1)["N"] +
                    _side_edges(x, y, 1, 1)["W"] + _side_edges(x, y, 1, 1)["E"]))
    taken = set()
    pois = []
    for kind, rule in POI_RULES.items():
        rng = stream(settings.seed, "poi", kind)
        expected = rule['count'] * urban / 100
        quota = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        quota = max(quota, rule['minimum'])
        candidates = []
        for along, away in rule['blocks']:
            for wx, wy, fronts in ((along, away, "SN"), (away, along, "WE")):
                for x in range(-radius, radius - wx + 1):
                    for y in range(-radius, radius - wy + 1):
                        group = tuple((x + i, y + j) for i in range(wx) for j in range(wy))
                        if any(b in taken for b in group):
                            continue
                        if any(e in roads for e in _inner_edges(x, y, wx, wy)):
                            continue
                        sides = {k: v for k, v in _side_edges(x, y, wx, wy).items() if k in fronts}
                        front = _best_front(rule, sides, roads, along)
                        if front is None:
                            continue
                        cx, cy = (x + wx / 2) * size, (y + wy / 2) * size
                        density = density_at(settings, cx, cy)
                        if density < POI_MIN_DENSITY:
                            continue
                        district = district_at(settings, cx, cy, locations)
                        # Sites favour blocks the lot pass would leave sparse.
                        occupancy = min(1.0, density * STYLE_PROFILE[district.style]['density'])
                        weight = rule['districts'].get(district.style, 0.0) * (1.25 - occupancy)
                        # Bigger shapes first in the rule's list are preferred.
                        weight *= 1.0 if (along, away) == rule['blocks'][0] else .5
                        key = stream(settings.seed, "poi", kind, x, y, wx, wy).random()
                        candidates.append((weight > 0, key ** (1 / max(weight, .02)),
                                           (x, y, wx, wy), group, front, district))
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        placed = []
        for preferred, _, (x, y, wx, wy), group, (side, frontage), district in candidates:
            if len(placed) >= quota or (not preferred and len(placed) >= rule['minimum']):
                break
            if any(b in taken for b in group):
                continue
            cx, cy = (x + wx / 2) * size, (y + wy / 2) * size
            if any(math.dist((cx, cy), p.center) < rule['spacing'] * size for p in placed):
                continue
            pad = _poi_pad(settings, x, y, wx, wy, nodes, rows)
            if pad is None:
                continue
            x0, y0, x1, y1 = pad
            width, depth = (x1 - x0, y1 - y0) if side in "SN" else (y1 - y0, x1 - x0)
            min_w, min_d = POI_MIN_PAD[kind]
            if width < min_w or depth < min_d:
                continue
            (ax, ay), (bx, by) = frontage
            mid = ((ax + bx) * size / 2, (ay + by) * size / 2)
            to_front = {"S": y0 - mid[1], "N": mid[1] - y1, "W": x0 - mid[0], "E": mid[0] - x1}[side]
            approach = to_front - ROAD_WIDTHS[roads[frontage]] / 2 - settings.sidewalk_width
            ident = f"poi_{kind.lower()}_{x}_{y}"
            seed_rng = stream(settings.seed, ident)
            condition = _pick_condition(district.style, stream(settings.seed, "condition", ident))
            profile = STYLE_PROFILE[district.style]
            damage = min(1.0, max(settings.damage * profile['damage'] * CONDITION_DAMAGE[condition],
                                  CONDITION_MIN_DAMAGE[condition]))
            poi = Poi(ident, kind, ((x0 + x1) / 2, (y0 + y1) / 2), round(width, 3), round(depth, 3),
                      SIDE_ROTATION[side], frontage, group, district.style, district.id,
                      seed_rng.randrange(2**31), round(approach, 3), condition, damage)
            placed.append(poi)
            taken.update(group)
        pois.extend(placed)
    return pois


def _place_shelters(settings, roads, lots, pois):
    """Transit stops mid-block on arterial and collector footways, clear of
    building entrances and site fronts."""
    size = settings.block_size
    walk = settings.sidewalk_width
    fronts = {}
    for item in list(lots) + list(pois):
        (ax, ay), (bx, by) = item.frontage
        horizontal = ay == by
        axis = 0 if horizontal else 1
        line = ay * size if horizontal else ax * size
        side = 1 if item.center[1 - axis] > line else -1
        # A stop may stand in front of a building, just not across its entrance
        # (front doors sit mid-frontage); site fronts stay clear entirely.
        half = item.width / 2 + size if isinstance(item, Poi) else min(item.width / 2, 4.0)
        fronts.setdefault((item.frontage, side), []).append(
            (item.center[axis] - half, item.center[axis] + half))
    shelters = []
    for key in sorted(roads):
        tier = roads[key]
        if tier not in ("ARTERIAL", "COLLECTOR"):
            continue
        rng = stream(settings.seed, "shelter", key)
        if rng.random() > .35:
            continue
        (ax, ay), (bx, by) = key
        horizontal = ay == by
        side = rng.choice((-1, 1))
        offset = ROAD_WIDTHS[tier] / 2 + walk - .7
        a, b = (ax, bx) if horizontal else (ay, by)
        for t in (.5, .35, .65):
            along = (a + (b - a) * t) * size
            if any(lo - 1 < along + 2.6 and along - 2.6 < hi + 1
                   for lo, hi in fronts.get((key, side), ())):
                continue
            if horizontal:
                position = (along, ay * size + side * offset)
                rotation = 0.0 if side > 0 else math.pi
            else:
                position = (ax * size + side * offset, along)
                rotation = -math.pi / 2 if side > 0 else math.pi / 2
            variant = "SHELTER" if walk >= 1.8 and rng.random() < .75 else "STOP"
            shelters.append(Shelter(f"shelter_{len(shelters)}", position, rotation, variant, key))
            break
    return shelters


# Share of an outer road's length over which its asphalt breaks up and
# disappears under the ground.
OUTER_FADE = .4


def _outer_roads(settings, paths):
    """Highways continue straight out of the city across the wasteland.

    Each highway end on the map edge gets a road heading away from the city:
    ``length`` metres beyond the end node (never past the ground), the last
    ``fade`` metres breaking up into patches until only ground is left.
    """
    reach = min(settings.highway_reach, settings.wasteland)
    if reach < 1:
        return []
    radius = settings.radius
    roads = []
    for path in paths:
        if path['tier'] != 'HIGHWAY':
            continue
        for node in (path['nodes'][0], path['nodes'][-1]):
            x, y = node
            if abs(x) == radius:
                direction = (1.0 if x > 0 else -1.0, 0.0)
            elif abs(y) == radius:
                direction = (0.0, 1.0 if y > 0 else -1.0)
            else:
                continue
            if any(r['node'] == list(node) for r in roads):
                continue
            roads.append({'id': f'outer_{len(roads)}', 'node': list(node), 'tier': 'HIGHWAY',
                          'start': [x * settings.block_size, y * settings.block_size],
                          'direction': list(direction), 'width': ROAD_WIDTHS['HIGHWAY'],
                          'length': round(reach, 3), 'fade': round(reach * OUTER_FADE, 3)})
    return roads


# -- dense downtown ------------------------------------------------------------

DOWNTOWN_VERGE = .5          # Building line behind the footway, downtown.
DOWNTOWN_MIN_WIDTH = 12.0    # Narrowest downtown building frontage.
DOWNTOWN_MAX_WIDTH = 48.0    # Widest single tower.
# Local sides seen from a building facing each world side: front, back, left, right.
LOCAL_SIDES = {"S": {"S": "front", "N": "back", "W": "left", "E": "right"},
               "N": {"N": "front", "S": "back", "E": "left", "W": "right"},
               "E": {"E": "front", "W": "back", "S": "left", "N": "right"},
               "W": {"W": "front", "E": "back", "N": "left", "S": "right"}}
OPPOSITE = {"S": "N", "N": "S", "E": "W", "W": "E"}


def _downtown(settings, locations, block):
    x, y = block
    radius = settings.radius
    if not (-radius <= x < radius and -radius <= y < radius):
        return False
    size = settings.block_size
    return district_at(settings, (x + .5) * size, (y + .5) * size, locations).style == 'DOWNTOWN'


def _edge_blocks(key):
    """The two blocks either side of a lattice edge."""
    (ax, ay), (bx, by) = key
    if ax == bx:
        y = min(ay, by)
        return (ax - 1, y), (ax, y)
    x = min(ax, bx)
    return (x, ay - 1), (x, ay)


def _close_downtown_streets(settings, locations, roads):
    """Close some downtown local streets so blocks join into superblocks.

    A street closes only between two downtown blocks, only if the road network
    stays connected, and only while the joined blocks fit in 2 x 2.
    """
    share = settings.downtown_superblocks
    if share <= 0:
        return
    parent = {}

    def find(block):
        parent.setdefault(block, block)
        while parent[block] != block:
            parent[block] = parent[parent[block]]
            block = parent[block]
        return block

    def members(root):
        return [b for b in list(parent) if find(b) == root]

    radius = settings.radius
    # Blocks already joined across streetless edges.
    for x in range(-radius, radius):
        for y in range(-radius, radius):
            for key in (edge((x + 1, y), (x + 1, y + 1)), edge((x, y + 1), (x + 1, y + 1))):
                a, b = _edge_blocks(key)
                if key not in roads and _downtown(settings, locations, a) and \
                        _downtown(settings, locations, b):
                    parent[find(a)] = find(b)
    candidates = [key for key, tier in sorted(roads.items())
                  if tier == "LOCAL" and all(_downtown(settings, locations, b)
                                             for b in _edge_blocks(key))]
    rng = stream(settings.seed, "superblocks")
    rng.shuffle(candidates)
    budget = int(round(len(candidates) * share))
    for key in candidates:
        if budget <= 0:
            break
        a, b = _edge_blocks(key)
        joined = set(members(find(a))) | set(members(find(b))) | {a, b}
        xs = [blk[0] for blk in joined]
        ys = [blk[1] for blk in joined]
        if max(xs) - min(xs) > 1 or max(ys) - min(ys) > 1:
            continue
        tier = roads.pop(key)
        if not _connected(roads, key[0], key[1]):
            roads[key] = tier
            continue
        parent[find(a)] = find(b)
        budget -= 1


def _connected(roads, start, goal):
    adjacency = {}
    for a, b in roads:
        adjacency.setdefault(a, []).append(b)
        adjacency.setdefault(b, []).append(a)
    if start not in adjacency or goal not in adjacency:
        return False
    seen, pending = {start}, [start]
    while pending:
        node = pending.pop()
        if node == goal:
            return True
        for other in adjacency[node]:
            if other not in seen:
                seen.add(other)
                pending.append(other)
    return False


def _place_downtown(settings, locations, roads, paths, reserved):
    """Downtown blocks built out to the footway, split into party-walled towers.

    Blocks joined across streetless edges (natural or closed) are laid out as
    one 2 x 1 or 2 x 2 superblock. Returns the lots and every downtown block
    this pass owns (the parcel pass skips them).
    """
    size = settings.block_size
    radius = settings.radius
    nodes = {}
    for (a, b), tier in roads.items():
        for node in (a, b):
            nodes[node] = max(nodes.get(node, 0), ROAD_WIDTHS[tier] / 2)
    rows = _path_rows(paths)
    verge = max(DOWNTOWN_VERGE, settings.setback - settings.sidewalk_width + .1)
    owned = {(x, y) for x in range(-radius, radius) for y in range(-radius, radius)
             if (x, y) not in reserved and _downtown(settings, locations, (x, y))}
    candidates = []
    for wx, wy in ((2, 2), (2, 1), (1, 2), (1, 1)):
        for x, y in sorted(owned):
            group = tuple((x + i, y + j) for i in range(wx) for j in range(wy))
            if any(b not in owned for b in group):
                continue
            if any(e in roads for e in _inner_edges(x, y, wx, wy)):
                continue
            key = stream(settings.seed, "downtown", x, y, wx, wy).random()
            candidates.append((-wx * wy, key, x, y, wx, wy, group))
    candidates.sort()
    taken = set()
    lots = []
    profile = STYLE_PROFILE['DOWNTOWN']
    for _, _, x, y, wx, wy, group in candidates:
        if any(b in taken for b in group):
            continue
        sides = {}
        for side, edges in _side_edges(x, y, wx, wy).items():
            usable = [e for e in edges if roads.get(e) not in (None, "HIGHWAY")]
            if usable:
                sides[side] = usable
        if not sides:
            continue
        pad = _poi_pad(settings, x, y, wx, wy, nodes, rows, verge)
        if pad is None:
            continue
        taken.update(group)
        rng = stream(settings.seed, "downtown", "group", x, y, wx, wy)
        cx, cy = (pad[0] + pad[2]) / 2, (pad[1] + pad[3]) / 2
        if rng.random() > min(1.0, density_at(settings, cx, cy) * profile['density']):
            continue
        district = district_at(settings, cx, cy, locations)
        lots.extend(_split_downtown(settings, roads, pad, sides, district, rng,
                                    f"dt_{x}_{y}_{wx}{wy}"))
    return lots, owned


def _split_downtown(settings, roads, pad, sides, district, rng, group):
    """Cut a downtown pad into towers: one or two rows (back to back, or across
    a service alley), each split into frontages along its street."""
    x0, y0, x1, y1 = pad
    main = min(sides, key=lambda side: (min(ROAD_RANK[roads[e]] for e in sides[side]),
                                        -len(sides[side]), side))
    horizontal = main in "SN"
    along = (x1 - x0) if horizontal else (y1 - y0)
    deep = (y1 - y0) if horizontal else (x1 - x0)
    rows = [(0.0, deep, main)]
    alley = 0.0
    if OPPOSITE[main] in sides and deep >= 34 and rng.random() < .75:
        alley = 6.0 if rng.random() < .3 else 0.0
        split = (deep - alley) * rng.uniform(.42, .58)
        rows = [(0.0, split, main), (split + alley, deep, OPPOSITE[main])]

    def world(a0, a1, b0, b1):
        """Block-frame rectangle (a along the main street, b back from it)."""
        if main == "S":
            return (x0 + a0, y0 + b0, x0 + a1, y0 + b1)
        if main == "N":
            return (x0 + a0, y1 - b1, x0 + a1, y1 - b0)
        if main == "W":
            return (x0 + b0, y0 + a0, x0 + b1, y0 + a1)
        return (x1 - b1, y0 + a0, x1 - b0, y0 + a1)

    # World sides of the block frame: a- and a+ ends, and the far side.
    a_low, a_high = ("W", "E") if horizontal else ("S", "N")
    profile = STYLE_PROFILE[district.style]
    lots = []
    size = settings.block_size
    for row, (b0, b1, front) in enumerate(rows):
        count = max(1, int(round(along / rng.uniform(18.0, 30.0))),
                    int(math.ceil(along / DOWNTOWN_MAX_WIDTH)))
        while count > 1 and along / count < DOWNTOWN_MIN_WIDTH:
            count -= 1
        weights = [rng.uniform(.7, 1.3) for _ in range(count)]
        cuts = [0.0]
        for weight in weights:
            cuts.append(cuts[-1] + along * weight / sum(weights))
        cuts = [round(c, 2) for c in cuts[:-1]] + [round(along, 2)]
        for index, (a0, a1) in enumerate(zip(cuts, cuts[1:])):
            # Centimetre grid: centres and widths round-trip to the same edges.
            rect = tuple(round(v, 2) for v in world(a0, a1, b0, b1))
            touching = set()
            if index > 0:
                touching.add(a_low)
            if index < count - 1:
                touching.add(a_high)
            if len(rows) == 2 and alley == 0.0:
                touching.add(OPPOSITE[front])
            local = LOCAL_SIDES[front]
            party = tuple(sorted(local[side] for side in touching))
            cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
            sx, sy = rect[2] - rect[0], rect[3] - rect[1]
            width, depth = (sx, sy) if front in "SN" else (sy, sx)
            axis = 0 if front in "SN" else 1
            frontage = min(sides[front], key=lambda e: (abs((e[0][axis] + e[1][axis]) * size / 2 -
                                                            (cx, cy)[axis]), e))
            ident = f"lot_{math.floor(cx / size)}_{math.floor(cy / size)}_{group}r{row}t{index}"
            item_rng = stream(settings.seed, ident)
            condition_rng = stream(settings.seed, "condition", ident)
            condition = _pick_condition(district.style, condition_rng)
            low, high = profile['floors']
            # Slender plots stay lower.
            floors = min(item_rng.randint(low, high), max(low, int(min(width, depth) * .9) + 4))
            if condition == 'WALL_RING':
                floors = min(floors, item_rng.randint(2, 4))
            damage = min(1.0, max(
                settings.damage * profile['damage'] * CONDITION_DAMAGE[condition],
                CONDITION_MIN_DAMAGE[condition]))
            if floors > 8:
                damage = min(1.0, damage * (1 + min(.5, (floors - 8) * .045)))
            interiors = (condition in INTERIOR_CONDITIONS and
                         condition_rng.random() < settings.interior_ratio)
            lots.append(Lot(ident, (round(cx, 3), round(cy, 3)), round(width, 3), round(depth, 3),
                            {"S": 0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}[front],
                            district.style, district.id, floors, item_rng.randrange(2**31),
                            frontage, condition=condition, interiors=interiors, damage=damage,
                            party_walls=party, group=group))
    return lots

