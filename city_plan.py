# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic city growth, independent of Blender. Coordinates are metres."""
from dataclasses import asdict, dataclass
from collections import deque
import hashlib
import heapq
import json
import math
import random

VERSION = 2
ROAD_WIDTHS = {"HIGHWAY": 20.0, "ARTERIAL": 12.0, "COLLECTOR": 8.0, "LOCAL": 6.0}
ROAD_RANK = {name: i for i, name in enumerate(ROAD_WIDTHS)}
STYLES = ("OLD_TOWN", "RESIDENTIAL", "INDUSTRIAL", "BRUTALIST")


def stream(seed, *keys):
    """Stable independent streams; never consume Blender's global random state."""
    payload = json.dumps([seed, *keys], separators=(",", ":")).encode()
    return random.Random(int.from_bytes(hashlib.sha256(payload).digest()[:8], "big"))


@dataclass(frozen=True)
class CitySettings:
    seed: int = 42
    radius: int = 6  # Half-width in blocks.
    block_size: float = 56.0
    primary_count: int = 5
    secondary_count: int = 12
    driving_loop_count: int = 3
    core_radius: float = 0.3  # Fraction of city half-width.
    core_density: float = 0.95
    outskirts_density: float = 0.15
    road_density: float = 0.55
    setback: float = 2.0
    sidewalk_width: float = 2.0
    curb_height: float = 0.15
    damage: float = 0.35
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
                             ("road_density", 0, 1), ("damage", 0, 1), ("setback", 1, 8),
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


@dataclass
class CityPlan:
    settings: CitySettings
    locations: list
    roads: list
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
    Geometry remains orthogonal; bridges and banked/curved roads are separate work.
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


def generate_city(settings=CitySettings()):
    settings.validate()
    roads = {}
    center = (0, 0)
    locations = [Location("center", center, "CENTER",
                          "OLD_TOWN" if settings.style == "MIXED" else settings.style)]
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
        style = STYLES[index % len(STYLES)] if settings.style == "MIXED" else settings.style
        locations.append(Location(f"primary_{index}", node, "PRIMARY", style))
        connect(node, center, "ARTERIAL")

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
            chance = settings.road_density * (.2 + .8 * density_at(settings, x, y))
            if stream(settings.seed, "local", key).random() <= chance:
                roads[key] = "LOCAL"
                if other not in reached:
                    reached.add(other)
                    frontier.append(other)

    road_list = [Road(a, b, tier) for (a, b), tier in sorted(roads.items())]
    lots = _place_lots(settings, locations, roads)
    # Stable priority sampling avoids truncating one geographical side of the city.
    lots.sort(key=lambda lot: stream(settings.seed, "budget", lot.id).random())
    eligible = len(lots)
    lots = sorted(lots[:settings.max_buildings], key=lambda lot: lot.id)
    return CityPlan(settings, locations, road_list, lots, eligible, driving_loops)


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
            margins = {}
            for side, (a, b) in borders.items():
                half = max(nodes.get(a, 0), nodes.get(b, 0))
                margins[side] = half + settings.sidewalk_width + 2 + settings.setback + .5
            for ix in range(2):
                for iy in range(2):
                    ident = f"lot_{x}_{y}_{ix}_{iy}"
                    rng = stream(settings.seed, ident)
                    sides = [s for s in (("W" if ix == 0 else "E"), ("S" if iy == 0 else "N"))
                             if borders[s] in roads and roads[borders[s]] != "HIGHWAY"]
                    if not sides:
                        continue
                    cx, cy = (x + .25 + .5 * ix) * size, (y + .25 + .5 * iy) * size
                    if rng.random() > density_at(settings, cx, cy):
                        continue
                    side = rng.choice(sides)
                    # Disjoint sub-parcels guarantee no overlapping footprints.
                    low_x = x * size + (margins["W"] if ix == 0 else size / 2 + 1)
                    high_x = x * size + (size / 2 - 1 if ix == 0 else size - margins["E"])
                    low_y = y * size + (margins["S"] if iy == 0 else size / 2 + 1)
                    high_y = y * size + (size / 2 - 1 if iy == 0 else size - margins["N"])
                    sx, sy = (high_x - low_x) * rng.uniform(.8, 1), (high_y - low_y) * rng.uniform(.8, 1)
                    if min(sx, sy) < 5:
                        continue
                    cx, cy = (low_x + high_x) / 2, (low_y + high_y) / 2
                    # Align the front wall with the street-facing parcel line.
                    if side == "W":
                        cx = low_x + sx / 2
                    elif side == "E":
                        cx = high_x - sx / 2
                    elif side == "S":
                        cy = low_y + sy / 2
                    else:
                        cy = high_y - sy / 2
                    district = min((loc for loc in locations if loc.role != "SECONDARY"),
                                   key=lambda loc: math.dist((cx / size, cy / size), loc.node))
                    floors = rng.randint(*{"OLD_TOWN": (2, 4), "RESIDENTIAL": (2, 5),
                                          "INDUSTRIAL": (1, 2), "BRUTALIST": (4, 8)}[district.style])
                    width, depth = (sy, sx) if side in "WE" else (sx, sy)
                    rotation = {"S": 0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}[side]
                    lots.append(Lot(ident, (cx, cy), width, depth, rotation,
                                    district.style, district.id, floors,
                                    rng.randrange(2**31), borders[side]))
    return lots
