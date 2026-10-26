# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic city growth, independent of Blender. Coordinates are metres."""
from dataclasses import asdict, dataclass
from collections import deque
import hashlib
import heapq
import json
import math
import random

VERSION = 4
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
CONDITION_MIN_DAMAGE = {'INTACT': 0.0, 'WEATHERED': 0.0, 'SEMI_COLLAPSED': .72,
                        'RUBBLE_FILLED': .35, 'PARTIAL_FILLED': .5,
                        'LOWER_FLOORS': 1.0, 'SHELL': .65, 'WALL_RING': .5,
                        'COLLAPSED': 0.0}
INTERIOR_CONDITIONS = ('INTACT', 'WEATHERED', 'SEMI_COLLAPSED', 'LOWER_FLOORS')
CONDITION_WEIGHTS = {
    'DOWNTOWN': (('INTACT', 16), ('WEATHERED', 24), ('SEMI_COLLAPSED', 20),
                 ('RUBBLE_FILLED', 10), ('PARTIAL_FILLED', 10), ('LOWER_FLOORS', 6),
                 ('SHELL', 8), ('WALL_RING', 3), ('COLLAPSED', 3)),
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


@dataclass
class CityPlan:
    settings: CitySettings
    locations: list
    roads: list
    paths: list
    lots: list
    eligible_lots: int
    driving_loops: list

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

    road_list = [Road(a, b, tier) for (a, b), tier in sorted(roads.items())]
    paths = _build_paths(settings, roads, locations)
    lots = _place_lots(settings, locations, roads)
    # Stable priority sampling avoids truncating one geographical side of the city.
    lots.sort(key=lambda lot: stream(settings.seed, "budget", lot.id).random())
    eligible = len(lots)
    lots = sorted(lots[:settings.max_buildings], key=lambda lot: lot.id)
    return CityPlan(settings, locations, road_list, paths, lots, eligible, driving_loops)


def _pick_condition(style, rng):
    roll = rng.uniform(0, 100)
    for condition, weight in CONDITION_WEIGHTS[style]:
        roll -= weight
        if roll <= 0:
            return condition
    return 'INTACT'


def _place_lots(settings, locations, roads):
    lots = []
    size = settings.block_size
    # Use actual adjacent street envelopes rather than the widest road citywide.
    nodes = {}
    for (a, b), tier in roads.items():
        for node in (a, b):
            nodes[node] = max(nodes.get(node, 0), ROAD_WIDTHS[tier] / 2)
    for x in range(-settings.radius, settings.radius):
        for y in range(-settings.radius, settings.radius):
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
                    interiors = (condition in INTERIOR_CONDITIONS and
                                 condition_rng.random() < settings.interior_ratio)
                    lots.append(Lot(ident, (cx, cy), width, depth, rotation,
                                    district.style, district.id, floors,
                                    rng.randrange(2**31), borders[side],
                                    condition=condition, interiors=interiors,
                                    damage=damage))
    return lots
