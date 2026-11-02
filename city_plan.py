# SPDX-License-Identifier: GPL-3.0-or-later
"""Deterministic city growth, independent of Blender. Coordinates are metres."""
from dataclasses import asdict, dataclass, field, replace
from collections import defaultdict, deque
from functools import lru_cache
import hashlib
import heapq
import json
import math
import random

VERSION = 13
ROAD_WIDTHS = {"HIGHWAY": 20.0, "ARTERIAL": 12.0, "COLLECTOR": 8.0, "LOCAL": 6.0}
ROAD_RANK = {name: i for i, name in enumerate(ROAD_WIDTHS)}
# Corner radius at a route bend, before the curve_radius multiplier and clamping.
BEND_RADII = {"HIGHWAY": 26.0, "ARTERIAL": 18.0, "COLLECTOR": 12.0, "LOCAL": 8.0}
# District character. `parcels` divides a block per axis, `footprint` is the
# fraction of the parcel the building may use (the rest is yard/plaza), `road`
# scales local street growth, `curve` scales corner fillets and `damage`
# scales the city damage setting. `tract`: the block is built out whole or
# left empty (the density times this is the chance it is built), with rows of
# houses along its streets instead of parcels.
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
    'SUBURBAN': dict(floors=(1, 2), parcels=2, footprint=(.85, 1.0), density=1.0,
                     setback=1, road=.5, curve=1.4, damage=.3, tract=1.6),
}
STYLES = tuple(STYLE_PROFILE)
# Points of interest (sites.py lays them out). ``blocks`` lists footprints in
# blocks (along the street, away from it), preferred first; ``count`` is the
# number per 100 built-up blocks and ``minimum`` how many any city gets when a
# block qualifies; ``front`` limits the road tiers a site may face (None: any
# but a highway); ``spacing`` is the least distance in blocks between two of a
# kind; ``districts`` weights district styles (styles left out only take a
# site when the minimum cannot be met otherwise). ``per_radius`` replaces the
# count with a number by map radius ((radius, count), ...). ``near`` pulls a
# kind toward sites placed before it: (kind, blocks, weight factor), and
# ``anchors`` toward district centres of given styles: (styles, blocks,
# factor). Kinds are placed in this order, so the mall comes first and the
# retail around it.
POI_RULES = {
    'MALL': dict(blocks=((2, 2),), count=0, minimum=0, per_radius=((6, 1), (12, 2)),
                 front=('ARTERIAL', 'COLLECTOR'), spacing=10,
                 districts={'SUBURBAN': 3, 'INDUSTRIAL': 1, 'RESIDENTIAL': .5}),
    'SHOPPING_PLAZA': dict(blocks=((2, 2),), count=.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                           spacing=8, districts={'SUBURBAN': 3, 'INDUSTRIAL': 1.5, 'RESIDENTIAL': 1},
                           near=('MALL', 5, 4.0)),
    'HOSPITAL': dict(blocks=((2, 1), (2, 2)), count=.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                     spacing=6, districts={'BRUTALIST': 3, 'DOWNTOWN': 2, 'RESIDENTIAL': 1.5,
                                           'OLD_TOWN': 1}),
    'SCHOOL': dict(blocks=((2, 1), (1, 1)), count=1, minimum=1, front=None, spacing=4,
                   districts={'RESIDENTIAL': 3, 'SUBURBAN': 2, 'BRUTALIST': 2, 'OLD_TOWN': 1}),
    'STRIP_MALL': dict(blocks=((1, 1), (2, 1)), count=1.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                       spacing=3, districts={'SUBURBAN': 3, 'RESIDENTIAL': 1.5, 'INDUSTRIAL': 1,
                                             'BRUTALIST': 1}, near=('MALL', 4, 3.0),
                       anchors=(('SUBURBAN', 'INDUSTRIAL'), 3, 2.0)),
    'PARK': dict(blocks=((1, 1), (2, 1)), count=2, minimum=1, front=None, spacing=2,
                 districts={'RESIDENTIAL': 3, 'OLD_TOWN': 2, 'BRUTALIST': 2, 'DOWNTOWN': 1.5,
                            'SUBURBAN': 1.5}, anchors=(('OLD_TOWN', 'DOWNTOWN'), 2, 2.5)),
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
                                            'INDUSTRIAL': 1, 'OLD_TOWN': 1}, near=('MALL', 3, 2.0)),
    'AUTO_REPAIR': dict(blocks=((1, 1),), count=1, minimum=1, front=None, spacing=3,
                        districts={'INDUSTRIAL': 3, 'SUBURBAN': 1.5, 'RESIDENTIAL': 1,
                                   'BRUTALIST': .5}),
    'HOTEL': dict(blocks=((1, 1),), count=.6, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                  spacing=4, districts={'OLD_TOWN': 2.5, 'DOWNTOWN': 2, 'BRUTALIST': 1,
                                        'RESIDENTIAL': .5}),
    'MOTEL': dict(blocks=((1, 1),), count=.8, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                  spacing=4, districts={'SUBURBAN': 2.5, 'INDUSTRIAL': 2, 'RESIDENTIAL': .5}),
    'CINEMA': dict(blocks=((1, 1), (2, 1)), count=.5, minimum=1, front=('ARTERIAL', 'COLLECTOR'),
                   spacing=6, districts={'OLD_TOWN': 2, 'DOWNTOWN': 1.5, 'SUBURBAN': 1.5,
                                         'RESIDENTIAL': 1}, near=('MALL', 4, 2.0)),
    'DRIVE_IN': dict(blocks=((2, 1), (2, 2)), count=.3, minimum=1, most=1, front=None,
                     spacing=12, districts={'SUBURBAN': 2, 'INDUSTRIAL': 1.5}),
}
# Smallest pad each kind is laid out for (mirrors sites.MIN_PAD).
POI_MIN_PAD = {'GAS_STATION': (24, 22), 'FAST_FOOD': (26, 24), 'SCHOOL': (40, 32),
               'HOSPITAL': (44, 32), 'POLICE': (28, 26), 'FIRE_STATION': (28, 26),
               'TRANSIT_STATION': (28, 24), 'PARK': (16, 16), 'PARKING_LOT': (20, 20),
               'PARKING_GARAGE': (30, 26), 'STRIP_MALL': (30, 26), 'SHOPPING_PLAZA': (80, 70),
               'AUTO_REPAIR': (30, 28), 'MALL': (90, 80), 'HOTEL': (30, 28),
               'MOTEL': (36, 28), 'CINEMA': (32, 30), 'DRIVE_IN': (80, 40)}
POI_VERGE = 1.0          # Unpaved strip between a site pad and the footway.
POI_MIN_DENSITY = .2     # Sites stay inside the built-up area.
MIDTOWN_STYLES = ('OLD_TOWN', 'RESIDENTIAL', 'BRUTALIST')

# Small town: an old-town main street in the middle, homes round it and an
# industrial edge; low buildings and only the sites a town has. Missing kinds
# (malls, plazas, hospitals, garages, hotels, transit stations) are not built.
PRESETS = ('CITY', 'SMALL_TOWN')
# Sizes and densities each preset starts from (the operator applies them when
# a preset is chosen; they stay editable).
PRESET_SETTINGS = {
    'CITY': dict(radius=6, primary_count=6, secondary_count=12, core_density=.95,
                 outskirts_density=.15, road_density=.55, driving_loop_count=3, max_buildings=600),
    'SMALL_TOWN': dict(radius=5, primary_count=5, secondary_count=6, core_density=.95,
                       outskirts_density=.45, road_density=.7, driving_loop_count=1,
                       max_buildings=250),
}
TOWN_STYLES = ('RESIDENTIAL', 'SUBURBAN')
TOWN_FLOORS = {'OLD_TOWN': (1, 3), 'RESIDENTIAL': (1, 3), 'SUBURBAN': (1, 2),
               'INDUSTRIAL': (1, 1), 'DOWNTOWN': (2, 4), 'BRUTALIST': (2, 3)}
TOWN_POIS = {
    'GAS_STATION': dict(count=1.5, districts={'SUBURBAN': 2, 'INDUSTRIAL': 2, 'RESIDENTIAL': 1,
                                              'OLD_TOWN': 1}),
    'FAST_FOOD': dict(count=1.5, districts={'SUBURBAN': 2, 'OLD_TOWN': 1.5, 'RESIDENTIAL': 1,
                                            'INDUSTRIAL': 1}),
    'AUTO_REPAIR': dict(districts={'INDUSTRIAL': 3, 'SUBURBAN': 1, 'RESIDENTIAL': 1}),
    'MOTEL': dict(count=1, districts={'SUBURBAN': 2, 'INDUSTRIAL': 2, 'RESIDENTIAL': .5,
                                     'OLD_TOWN': .5}),
    'SCHOOL': dict(blocks=((1, 1),), districts={'RESIDENTIAL': 3, 'SUBURBAN': 2}),
    'POLICE': dict(districts={'OLD_TOWN': 3, 'RESIDENTIAL': 1}),
    'FIRE_STATION': dict(districts={'OLD_TOWN': 2, 'RESIDENTIAL': 2, 'INDUSTRIAL': 1,
                                    'SUBURBAN': 1}),
    'PARK': dict(count=1.5, districts={'RESIDENTIAL': 2, 'OLD_TOWN': 2, 'SUBURBAN': 2}),
    'PARKING_LOT': dict(count=.8, districts={'OLD_TOWN': 3, 'INDUSTRIAL': 1}),
    'STRIP_MALL': dict(count=.8, near=None, districts={'SUBURBAN': 2, 'OLD_TOWN': 1,
                                                       'RESIDENTIAL': 1}),
    'CINEMA': dict(blocks=((1, 1),), near=None, districts={'OLD_TOWN': 3}),
    'DRIVE_IN': dict(minimum=0, count=1, districts={'SUBURBAN': 2, 'INDUSTRIAL': 2,
                                                    'RESIDENTIAL': 1}),
}


def poi_rules(settings):
    """The site rules a city uses (a small town keeps its own set)."""
    if settings.preset != 'SMALL_TOWN':
        return POI_RULES
    rules = {}
    for kind, rule in POI_RULES.items():
        if kind in TOWN_POIS:
            merged = dict(rule)
            for key, value in TOWN_POIS[kind].items():
                if value is None:
                    merged.pop(key, None)      # An override of None removes the rule.
                else:
                    merged[key] = value
            rules[kind] = merged
    return rules

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
    preset: str = "CITY"               # CITY, or SMALL_TOWN: no towers, no big sites.
    shape: str = "SQUARE"              # SQUARE fills the map; ORGANIC has an irregular edge.
    irregularity: float = .6           # How far an organic edge wanders.
    terrain: str = "FLAT"              # FLAT, ROLLING hills, or TERRACED (see TERRAINS).
    relief: float = 30.0               # Hills: metres from the lowest to the highest.
    plateau_height: float = 18.0       # Terraced: the plateau's rise (0: none).
    podiums: int = 1                   # Terraced: low podiums of a few blocks.

    def validate(self):
        for name, lo, hi in (("radius", 2, 25), ("primary_count", 1, 16),
                             ("secondary_count", 0, 100), ("max_buildings", 1, 10000),
                             ("driving_loop_count", 0, 8), ("podiums", 0, 3)):
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
                             ("irregularity", 0, 1), ("relief", 0, 40), ("plateau_height", 0, 30),
                             ("sidewalk_width", 1.2, 5), ("curb_height", 0, .25)):
            value = getattr(self, name)
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f"{name} must be finite and in [{lo}, {hi}]")
        if self.style not in ("MIXED", *STYLES):
            raise ValueError("Unknown architecture style")
        if self.preset not in PRESETS:
            raise ValueError("Unknown preset")
        if self.shape not in SHAPES:
            raise ValueError("Unknown city shape")
        if self.terrain not in TERRAINS:
            raise ValueError("Unknown terrain")


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
    bulb: tuple = ()          # Cul-de-sac node of the turning circle the house faces.
    level: float = 0.0        # Pad height above the flat city (road level at its front).


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
    level: float = 0.0   # Pad height above the flat city (road level at its front).


@dataclass(frozen=True)
class Shelter:
    """A transit stop on a footway; its back faces the block."""
    id: str
    position: tuple
    rotation: float
    variant: str         # SHELTER or STOP.
    road: tuple
    level: float = 0.0   # Road level where it stands, above the flat city.


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
    culdesacs: list = field(default_factory=list)    # [{'node': [x, y], 'radius': m}]
    heights: list = field(default_factory=list)      # [[x, y, z]] graded lattice nodes (z != 0)
    # Terraced terrain: {'regions': [{'cells', 'step'}], 'ramps': [{'nodes', 'raises'}],
    # 'stairs': [{'low', 'high', 'width'}], 'ground': [[x, y, z]] base node heights}.
    terraces: dict = field(default_factory=dict)

    def to_json(self):
        return json.dumps({"version": VERSION, **asdict(self)}, sort_keys=True, indent=2)

    def surface(self):
        """Road level anywhere on the street network (``Surface`` on hills,
        ``RoadSurface`` on terraces)."""
        heights = {(x, y): z for x, y, z in self.heights}
        if self.terraces:
            return RoadSurface(self.settings, heights, self.roads, self.terraces)
        return Surface(self.settings, heights)

    def ground_surface(self):
        """Natural ground level (before pads): the road-level surface on hills;
        on terraces the base hills plus each terrace's rise over its blocks."""
        if self.terraces:
            return TerraceGround(self.settings, self.terraces)
        return self.surface()


def edge(a, b):
    return tuple(sorted((a, b)))


# Terrain. FLAT keeps every height at zero. ROLLING lifts the lattice nodes on
# smooth seeded hills (``relief`` metres from the lowest to the highest), held
# at zero along the map's edge so the wasteland and the highways leaving the
# city stay level. The nodes are then graded: no street is steeper than its
# tier allows and site blocks are level. Between the nodes the ground is a
# smoothstep blend of the block's four corners (``Surface``), so a street's
# profile eases out flat at both junctions and is at most SMOOTHSTEP_PEAK times
# steeper than the straight grade between them.
TERRAINS = ('FLAT', 'ROLLING', 'TERRACED')
GRADE_LIMITS = {'HIGHWAY': .04, 'ARTERIAL': .05, 'COLLECTOR': .06, 'LOCAL': .08}
OPEN_GRADE = .12         # Lattice edges without a street.
SITE_DROP = .25          # Most a site block's corners may differ (m).
TERRAIN_WAVE = 7.0       # Blocks per noise cell of the hills (first octave).
TERRAIN_EDGE = 2.0       # Blocks over which the hills fade to the level edge.
SMOOTHSTEP_PEAK = 1.5    # Steepest slope of a smoothstep over its mean slope.


class Surface:
    """Road-level height of the graded city above the flat city (metres):
    the node heights blended across each block with smoothsteps; zero off the
    lattice and everywhere on a flat city."""

    def __init__(self, settings, heights):
        self.size = settings.block_size
        self.radius = settings.radius
        self.heights = heights

    def __call__(self, x, y):
        if not self.heights:
            return 0.0
        u, v = x / self.size, y / self.size
        i, j = math.floor(u), math.floor(v)
        if i < -self.radius or j < -self.radius or i >= self.radius or j >= self.radius:
            return 0.0
        fu, fv = u - i, v - j
        su, sv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)
        h = self.heights
        return ((h.get((i, j), 0.0) * (1 - su) + h.get((i + 1, j), 0.0) * su) * (1 - sv) +
                (h.get((i, j + 1), 0.0) * (1 - su) + h.get((i + 1, j + 1), 0.0) * su) * sv)


def _terrain_heights(settings):
    """Seeded hills on the lattice nodes, zero along the map's edge."""
    radius = settings.radius
    nodes = [(x, y) for x in range(-radius, radius + 1) for y in range(-radius, radius + 1)]
    seed = settings.seed

    def hills(x, y):
        return (_noise(seed, x / TERRAIN_WAVE, y / TERRAIN_WAVE, "terrain") +
                .35 * _noise(seed, x / (TERRAIN_WAVE / 2.3), y / (TERRAIN_WAVE / 2.3), "terrain2"))
    raw = {node: hills(*node) for node in nodes}
    low, high = min(raw.values()), max(raw.values())
    spread = max(high - low, 1e-9)
    heights = {}
    for node in nodes:
        edge_distance = min(radius - abs(node[0]), radius - abs(node[1])) / TERRAIN_EDGE
        t = max(0.0, min(1.0, edge_distance))
        fade = t * t * (3 - 2 * t)
        heights[node] = ((raw[node] - low) / spread - .5) * settings.relief * fade
    return heights


def _grade(settings, roads, pois, flat=(), benches=()):
    """Node heights graded so every lattice edge stays under its limit: a
    street's tier, open ground, or a site block kept level. The map's edge
    stays at zero."""
    radius, size = settings.radius, settings.block_size
    heights = _terrain_heights(settings)
    limits = {}
    for x in range(-radius, radius + 1):
        for y in range(-radius, radius + 1):
            for other in ((x + 1, y), (x, y + 1)):
                if max(map(abs, other)) <= radius:
                    key = edge((x, y), other)
                    grade = GRADE_LIMITS.get(roads.get(key), OPEN_GRADE)
                    limits[key] = grade * size / SMOOTHSTEP_PEAK
    for key in flat:
        limits[key] = min(limits[key], RAMP_FLAT)
    for key in benches:
        limits[key] = min(limits[key], TERRACE_BENCH)
    for poi in pois:
        # Every pair of a site's corners, so the whole pad is level.
        corners = sorted({(bx + dx, by + dy) for bx, by in poi.blocks
                          for dx in (0, 1) for dy in (0, 1)})
        for index, a in enumerate(corners):
            for b in corners[index + 1:]:
                limits[edge(a, b)] = min(limits.get(edge(a, b), math.inf), SITE_DROP)
    pinned = {node for node in heights if max(map(abs, node)) == radius}
    for node in pinned:
        heights[node] = 0.0
    order = sorted(limits.items())

    def worst():
        return max((abs(heights[a] - heights[b]) - most for (a, b), most in order), default=0.0)
    for _ in range(4000):
        moved = 0.0
        for (a, b), most in order:
            difference = heights[a] - heights[b]
            excess = abs(difference) - most
            if excess <= 1e-7:
                continue
            moved = max(moved, excess)
            step = excess if difference > 0 else -excess
            if a in pinned:
                heights[b] += step
            elif b in pinned:
                heights[a] -= step
            else:
                heights[a] -= step / 2
                heights[b] += step / 2
        if moved < 1e-5:
            break
    # Never leave a limit broken: flatten towards zero until all hold.
    while worst() > 1e-4:
        for node in heights:
            heights[node] *= .5
    return {node: round(z, 3) for node, z in heights.items() if abs(round(z, 3)) > 0}


# Terraced terrain (TERRACED): the base hills (``relief``) carry raised
# terraces of whole blocks behind retaining walls: one plateau
# (``plateau_height``) and a few low podiums. The streets inside a terrace
# rise with it; the streets round its foot stay below. A street crossing into
# a terrace becomes a ramp, straight out from the wall at no more than
# RAMP_GRADE (a podium's ramp fits one block; a plateau's reaches several,
# with the side streets along it closed), or a pedestrian stair.
PODIUM_STEP = 4.2
RAMP_GRADE = .10
RAMP_EASE = .15          # Share of a ramp edge eased flat at each end.
MAX_RAMPS = 2            # Vehicle ramps up to a plateau.
RAMP_FLAT = .05          # Most the base hills may change along a ramp edge (m).
TERRACE_BENCH = .4       # ...or along a lattice edge under a terrace.
STAIR_WIDTH = 6.0
PLATEAU_SHARE = .15      # Of the city's blocks.
PLATEAU_CELLS = (6, 40)
PODIUM_CELLS = (3, 6)
TERRACE_TRIES = 40
TERRACE_STREETS = .7     # Least chance of a local street across a terrace's top.


def ramp_profile(t):
    """Eased linear rise from 0 to 1 (flat at both ends; steepest at
    1 / (1 - RAMP_EASE) times the mean slope)."""
    e = RAMP_EASE
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    if t < e:
        return t * t / (2 * e * (1 - e))
    if t > 1 - e:
        return 1 - (1 - t) * (1 - t) / (2 * e * (1 - e))
    return (t - e / 2) / (1 - e)


def ramp_shape(t, ease_a=True, ease_b=True):
    """Rise from 0 to 1 along one ramp edge, eased flat at the ends that meet
    a street (``ease_a`` at t = 0, ``ease_b`` at t = 1) and straight through
    the ramp's own junctions."""
    if ease_a and ease_b:
        return ramp_profile(t)
    if not ease_a and not ease_b:
        return max(0.0, min(1.0, t))
    if ease_b:
        return 1 - ramp_shape(1 - t, True, False)
    e = RAMP_EASE
    t = max(0.0, min(1.0, t))
    if t < e:
        return t * t / (2 * e * (1 - e / 2))
    return (t - e / 2) / (1 - e / 2)


def ramp_ends(terraces):
    """{lattice edge: (eased at its first node, eased at its second)} for
    every ramp edge."""
    ends = {}
    for ramp in terraces.get('ramps', ()):
        nodes = [tuple(n) for n in ramp['nodes']]
        # Eased at its ends and where it turns; straight on through the rest.
        eased = {0, len(nodes) - 1} | {
            j for j in range(1, len(nodes) - 1)
            if (nodes[j][0] - nodes[j - 1][0], nodes[j][1] - nodes[j - 1][1]) !=
            (nodes[j + 1][0] - nodes[j][0], nodes[j + 1][1] - nodes[j][1])}
        for j, (a, b) in enumerate(zip(nodes, nodes[1:])):
            flags = (j in eased, j + 1 in eased)
            ends[edge(a, b)] = flags if edge(a, b)[0] == a else flags[::-1]
    return ends


def _cell_corners(cell):
    x, y = cell
    return [(x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)]


def ramp_reach(step, size):
    """Lattice edges a ramp needs beyond the terrace's edge block to climb
    ``step``, every edge eased at both ends (where it turns, too)."""
    for extra in range(12):
        if (step / (extra + 1) + RAMP_FLAT) / size / (1 - RAMP_EASE) <= RAMP_GRADE:
            return extra
    return 12


def _terraces(settings, locations, roads):
    """Choose the terraces and edit the street network for them: a ramp is a
    straight street out from the terrace (added where the lattice has none);
    stairs, the side streets along a ramp and streets through a terrace at its
    foot level leave ``roads``. Returns {'regions', 'ramps', 'stairs'}, or {}
    for other terrain or when no terrace fits."""
    if settings.terrain != 'TERRACED':
        return {}
    radius, size = settings.radius, settings.block_size
    highway = {n for key, tier in roads.items() if tier == 'HIGHWAY' for n in key}
    bulbs, looped = set(), set()
    city_cells = [(x, y) for x in range(-radius, radius) for y in range(-radius, radius)
                  if in_city(settings, (x + .5) * size, (y + .5) * size)]
    specs = []
    if settings.plateau_height > 0:
        specs.append(('plateau', settings.plateau_height))
    specs += [('podium', PODIUM_STEP)] * settings.podiums
    taken = set()          # Cells of earlier terraces and their ramps, with a ring round them.
    result = {'regions': [], 'ramps': [], 'stairs': []}
    for index, (kind, step) in enumerate(specs):
        rng = stream(settings.seed, 'terrace', index)
        reach = ramp_reach(step, size)

        def allowed(cell):
            corners = _cell_corners(cell)
            return (cell not in taken and
                    all(max(map(abs, c)) <= radius - 1 for c in corners) and
                    in_city(settings, (cell[0] + .5) * size, (cell[1] + .5) * size) and
                    not set(corners) & (highway | bulbs))
        if kind == 'plateau':
            target = max(PLATEAU_CELLS[0], min(PLATEAU_CELLS[1],
                                               round(PLATEAU_SHARE * len(city_cells))))
            prefer = {'DOWNTOWN': 3.0, 'OLD_TOWN': 2.0, 'BRUTALIST': 2.0, 'RESIDENTIAL': 1.0}
        else:
            target = rng.randint(*PODIUM_CELLS)
            prefer = {'OLD_TOWN': 3.0, 'RESIDENTIAL': 2.0, 'DOWNTOWN': 1.5, 'BRUTALIST': 1.0}
        seeds = []
        for cell in city_cells:
            if allowed(cell):
                style = district_at(settings, (cell[0] + .5) * size, (cell[1] + .5) * size,
                                    locations).style
                # Built-up districts first: the terrace is a district of its own.
                weight = prefer.get(style, .3) * density_at(
                    settings, (cell[0] + .5) * size, (cell[1] + .5) * size) ** 2
                seeds.append((rng.random() ** (1 / max(weight, .01)), cell))
        seeds.sort(reverse=True)
        for _, seed_cell in seeds[:TERRACE_TRIES]:
            cells = _grow_terrace(seed_cell, target, allowed, rng)
            if len(cells) < min(target, 4):
                continue
            found = _check_terrace(settings, roads, cells, step, reach, kind, highway, bulbs,
                                   looped, taken)
            if found is None:
                continue
            ramps, stairs, cuts, added = found
            for key in cuts:
                roads.pop(key, None)
            roads.update(added)
            result['regions'].append({'cells': sorted([list(c) for c in cells]), 'step': step,
                                      'kind': kind})
            result['ramps'] += ramps
            result['stairs'] += stairs
            ring = set()
            for x, y in cells | {tuple(n) for ramp in ramps for n in ramp['nodes']}:
                for dx in (-2, -1, 0, 1):
                    for dy in (-2, -1, 0, 1):
                        ring.add((x + dx, y + dy))
            taken |= ring
            break
    return result if result['regions'] else {}


def _grow_terrace(seed_cell, target, allowed, rng):
    """A compact blob of allowed cells grown from ``seed_cell`` (each step
    takes the outside cell with the most neighbours already in), holes filled."""
    cells = {seed_cell}

    def neighbours(cell):
        x, y = cell
        return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
    while len(cells) < target:
        options = sorted({n for c in cells for n in neighbours(c)
                          if n not in cells and allowed(n)})
        if not options:
            break
        cells.add(max(options, key=lambda n: sum(m in cells for m in neighbours(n)) +
                      1.5 * rng.random()))
    for cell in sorted({n for c in cells for n in neighbours(c)}):
        if cell not in cells and allowed(cell) and all(n in cells for n in neighbours(cell)):
            cells.add(cell)
    return cells


def _check_terrace(settings, roads, cells, step, reach, kind, highway, bulbs, looped, taken):
    """Ramps, stairs, street cuts and added ramp streets for a terrace over
    ``cells``, or None when it would cut a highway, a driving circuit or a
    cul-de-sac, leave the network in pieces, or have no ramp."""
    radius = settings.radius
    corners = {c for cell in cells for c in _cell_corners(cell)}
    inner = {n for n in corners if all(c in cells for c in _node_cells(n))}
    if not inner:
        return None
    rim = corners - inner
    # A street between two terrace blocks with both ends at the foot would run
    # in a trench through the terrace: it goes.
    cuts = []
    for a, b in roads:
        if a in rim and b in rim:
            if a[1] == b[1]:
                beside = ((min(a[0], b[0]), a[1] - 1), (min(a[0], b[0]), a[1]))
            else:
                beside = ((a[0] - 1, min(a[1], b[1])), (a[0], min(a[1], b[1])))
            if all(c in cells for c in beside):
                cuts.append(edge(a, b))
    crossing = sorted((a, b) if a in inner else (b, a) for (a, b) in roads
                      if (a in inner) != (b in inner))
    if any(roads[edge(a, b)] == 'HIGHWAY' for a, b in crossing):
        return None
    network = {n for key in roads for n in key}
    # A ramp may also climb where no street crosses yet (a new street).
    faces = sorted({(n, m) for n in inner for m in
                    ((n[0] + 1, n[1]), (n[0] - 1, n[1]), (n[0], n[1] + 1), (n[0], n[1] - 1))
                    if m in rim})
    options = []

    def free(n):
        return (max(map(abs, n)) <= radius - 1 and n not in highway and n not in bulbs and
                n not in corners and not any(c in taken for c in _node_cells(n)))
    for high, low in faces:
        tier = roads.get(edge(high, low), 'COLLECTOR')
        if any(c in taken for c in _node_cells(low)):
            continue
        for turns, chain in _ramp_chains(high, low, reach, free):
            nodes = [high] + chain
            keys = [edge(a, b) for a, b in zip(nodes, nodes[1:])]
            if any(roads.get(key) == 'HIGHWAY' for key in keys):
                continue
            # The ramp runs above the side streets at its raised junctions.
            these = sorted({key for n in chain[:-1] for key in _node_edges(n)
                            if key in roads and key not in keys})
            if any(roads[key] == 'HIGHWAY' or key in looped or set(key) & bulbs
                   for key in these):
                continue
            new = [key for key in keys if key not in roads]
            rank = {'ARTERIAL': 0, 'COLLECTOR': 1, 'LOCAL': 2}[tier]
            options.append((edge(high, low) not in roads, chain[-1] not in network, bool(new),
                            turns, rank, len(new), len(these), high, low, nodes, these,
                            {key: tier for key in new}))
    options.sort(key=lambda o: o[:9])
    ramps, used, added, ramp_keys = [], set(), {}, set()
    limit = len(crossing) if kind == 'podium' else MAX_RAMPS
    for *_, nodes, these, new in options:
        if len(ramps) >= limit:
            break
        keys = {edge(a, b) for a, b in zip(nodes, nodes[1:])}
        if set(nodes) & used or set(these) & ramp_keys or keys & set(cuts):
            continue
        span = len(nodes) - 1
        ramps.append({'nodes': [list(n) for n in nodes],
                      'raises': [round(step * (span - j) / span, 3) for j in range(len(nodes))]})
        cuts += these
        added.update(new)
        ramp_keys |= keys
        used |= set(nodes)
    if not ramps:
        return None
    stairs = []
    for high, low in crossing:
        key = edge(high, low)
        if key in ramp_keys or key in cuts:
            continue
        if key in looped:
            return None
        stairs.append({'low': list(low), 'high': list(high), 'width': STAIR_WIDTH})
    if any(key in looped or set(key) & bulbs for key in cuts):
        return None
    removed = set(cuts) | {edge(tuple(s['low']), tuple(s['high'])) for s in stairs}
    # Streets the cuts leave apart (and a ramp's foot off the network) are
    # joined back on with new streets clear of the terrace and its ramps.
    raised = inner | {tuple(n) for r in ramps for n in r['nodes'][1:-1]} | {
        n for c in taken for n in _cell_corners(c)}
    outside = {(x, y) for x in range(-radius, radius + 1)
               for y in range(-radius, radius + 1)} - inner
    main = (-radius, 0)
    for _ in range(12):
        keys = [key for key in roads if key not in removed] + list(added)
        pieces = _pieces(keys)
        home = next((piece for piece in pieces if main in piece), None)
        if home is None:
            return None
        islands = [piece for piece in pieces if piece is not home]
        # A ramp's foot with no other street: joined on like an island.
        degree = defaultdict(int)
        for a, b in keys:
            degree[a] += 1
            degree[b] += 1
        loose = [tuple(r['nodes'][-1]) for r in ramps if degree[tuple(r['nodes'][-1])] < 2]
        if not islands and not loose:
            break
        if islands:
            island = min(islands, key=lambda piece: (len(piece), min(piece)))
        else:
            island = {loose[0]}
            home = home - {tuple(n) for r in ramps for n in r['nodes']}
        # On the terrace through its own top, else at the foot.
        if island & inner and home & inner:
            starts, targets, blocked = island & inner, home & inner, outside
        else:
            starts, targets, blocked = island - raised, home - raised, corners | raised
        if not starts or not targets:
            return None
        start, target = min(((a, b) for a in sorted(starts) for b in sorted(targets)),
                            key=lambda pair: (math.dist(*pair), pair))
        merged = dict(roads)
        merged.update(added)
        path = _route(start, target, merged, settings, blocked - {start, target},
                      confine=True, closed=removed)
        if path is None:
            return None
        for a, b in zip(path, path[1:]):
            key = edge(a, b)
            if key not in roads and key not in added:
                added[key] = 'LOCAL'
            removed.discard(key)
    else:
        return None
    graph = {n for key in roads if key not in removed for n in key} | {n for key in added
                                                                        for n in key}
    # A stair needs a street at both ends.
    if any(tuple(s['high']) not in graph or tuple(s['low']) not in graph for s in stairs):
        return None
    return ramps, stairs, sorted(set(cuts)) + sorted(removed - set(cuts)), added


def _pieces(keys):
    """The connected pieces (node sets) of a street network."""
    graph = {}
    for a, b in keys:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, []).append(a)
    pieces, seen = [], set()
    for start in sorted(graph):
        if start in seen:
            continue
        piece, pending = {start}, [start]
        while pending:
            node = pending.pop()
            for other in graph[node]:
                if other not in piece:
                    piece.add(other)
                    pending.append(other)
        seen |= piece
        pieces.append(piece)
    return pieces


def _ramp_chains(high, low, reach, free):
    """(turns, nodes) for every way a ramp can run ``reach`` edges on from
    ``low`` (away from ``high``) over ``free`` nodes, turning at most twice."""
    found = []

    def walk(path, direction, turns):
        if len(path) == reach + 1:
            found.append((turns, path))
            return
        x, y = path[-1]
        for d in (direction, (direction[1], -direction[0]), (-direction[1], direction[0])):
            n = (x + d[0], y + d[1])
            bend = turns + (d != direction)
            if bend <= 2 and n not in path and free(n):
                walk(path + [n], d, bend)
    walk([low], (low[0] - high[0], low[1] - high[1]), 0)
    return found


def _node_cells(node):
    x, y = node
    return ((x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y))


def _node_edges(node):
    x, y = node
    return [edge(node, other) for other in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))]


def _terrace_guard(terraces):
    """What the later street passes must leave alone: ``nodes`` a driving
    circuit may not pass (terrace tops and ramps), ``edges`` no street may
    take (beside a raised ramp junction, or through a terrace at its foot),
    ``stairs`` the lattice edges up a terrace's face (a street there is a
    stair) and ``keep`` the ramps."""
    guard = {'nodes': set(), 'edges': set(), 'stairs': set(), 'keep': set(), 'avoid': set(),
             'top': set()}
    for region in terraces.get('regions', ()):
        cells = {tuple(c) for c in region['cells']}
        corners = {n for c in cells for n in _cell_corners(c)}
        inner = {n for n in corners if all(c in cells for c in _node_cells(n))}
        guard['nodes'] |= inner
        guard['avoid'] |= corners
        for node in corners:
            for key in _node_edges(node):
                a, b = key
                if (a in inner) != (b in inner):
                    guard['stairs'].add(key)
                elif a in inner and b in inner:
                    guard['top'].add(key)
                elif a in corners and b in corners and a not in inner and b not in inner:
                    beside = (((min(a[0], b[0]), a[1] - 1), (min(a[0], b[0]), a[1]))
                              if a[1] == b[1] else
                              ((a[0] - 1, min(a[1], b[1])), (a[0], min(a[1], b[1]))))
                    if all(c in cells for c in beside):
                        guard['edges'].add(key)
    for ramp in terraces.get('ramps', ()):
        nodes = [tuple(n) for n in ramp['nodes']]
        keys = {edge(a, b) for a, b in zip(nodes, nodes[1:])}
        guard['keep'] |= keys
        guard['stairs'] -= keys
        for node in nodes[1:-1]:
            guard['nodes'].add(node)
            guard['avoid'].add(node)
            guard['edges'] |= set(_node_edges(node)) - keys
    guard['stairs'] -= guard['edges']
    guard['top'] -= guard['edges']
    return guard


def _finish_terraces(terraces, roads, stairs):
    """Add the stairs the local streets asked for, where both ends have a street."""
    if not terraces:
        return
    have = {n for key in roads for n in key}
    known = {edge(tuple(s['low']), tuple(s['high'])) for s in terraces['stairs']}
    inner = set(_terrace_raises(terraces))
    for a, b in sorted(stairs - known):
        if a in have and b in have:
            high, low = (a, b) if a in inner else (b, a)
            terraces['stairs'].append({'low': list(low), 'high': list(high),
                                       'width': STAIR_WIDTH})
    terraces['stairs'].sort(key=lambda s: (s['low'], s['high']))


def _terrace_benches(terraces):
    """Lattice edges among a terrace's corners: the hills under it are
    graded nearly level, so it stands its full height all round."""
    keys = set()
    for region in terraces.get('regions', ()):
        corners = {n for c in region['cells'] for n in _cell_corners(tuple(c))}
        keys |= {key for n in corners for key in _node_edges(n)
                 if key[0] in corners and key[1] in corners}
    return sorted(keys)


def _terrace_raises(terraces):
    """{node: metres above the base hills}: a terrace's inner junctions rise
    by its step; a ramp's junctions part of the way."""
    raised = {}
    for region in terraces['regions']:
        cells = {tuple(c) for c in region['cells']}
        for cell in cells:
            for node in _cell_corners(cell):
                x, y = node
                if all(c in cells for c in ((x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y))):
                    raised[node] = region['step']
    for ramp in terraces['ramps']:
        for node, rise in zip(ramp['nodes'], ramp['raises']):
            raised[tuple(node)] = max(raised.get(tuple(node), 0.0), rise)
    return {node: z for node, z in raised.items() if z}


def terrace_obstacles(terraces):
    """What placement needs to know of the terraces: the walled frontages
    (``terrace_walls``), each block's terrace (None off them), the stair
    edges, and the stairs as carriageway rows (as ``_path_rows``)."""
    terraces = terraces or {}
    region = {tuple(c): index for index, r in enumerate(terraces.get('regions', ()))
              for c in r['cells']}
    stairs = {edge(tuple(s['low']), tuple(s['high'])): s for s in terraces.get('stairs', ())}
    rows = [(s['low'], s['high'], s['width'] / 2) for s in stairs.values()]
    return terrace_walls(terraces), region, set(stairs), rows


def _stair_rows(settings, stairs):
    size = settings.block_size
    return [(a[0] * size, a[1] * size, b[0] * size, b[1] * size, half) for a, b, half in stairs]


def terrace_walls(terraces):
    """{cell: lattice edges its buildings may not face}: a terrace's foot
    streets for its own blocks, and every ramp for all."""
    walls = {}
    ramp_edges = {edge(tuple(a), tuple(b)) for ramp in terraces.get('ramps', ())
                  for a, b in zip(ramp['nodes'], ramp['nodes'][1:])}
    for region in terraces.get('regions', ()):
        cells = {tuple(c) for c in region['cells']}
        for x, y in cells:
            sides = {((x, y), (x + 1, y)): (x, y - 1), ((x, y + 1), (x + 1, y + 1)): (x, y + 1),
                     ((x, y), (x, y + 1)): (x - 1, y), ((x + 1, y), (x + 1, y + 1)): (x + 1, y)}
            for (a, b), neighbour in sides.items():
                if neighbour not in cells:
                    walls.setdefault((x, y), set()).add(edge(a, b))
    blocked = defaultdict(set, {cell: set(edges) for cell, edges in walls.items()})
    for key in ramp_edges:
        (ax, ay), (bx, by) = key
        if ay == by:
            beside = [(min(ax, bx), ay - 1), (min(ax, bx), ay)]
        else:
            beside = [(ax - 1, min(ay, by)), (ax, min(ay, by))]
        for cell in beside:
            blocked[cell].add(key)
    return dict(blocked)


def terrace_cells(terraces):
    """{cell: rise} over every terrace's blocks."""
    return {tuple(c): region['step'] for region in terraces.get('regions', ())
            for c in region['cells']}


class RoadSurface:
    """Road level on a terraced city: each street's own profile between its
    junction heights (smoothstep, or an eased ramp), blended only where two
    streets are about as near (junctions)."""
    BLEND = 3.0

    def __init__(self, settings, heights, roads, terraces):
        self.size = settings.block_size
        self.heights = heights
        self.ramps = ramp_ends(terraces)
        self.adjacent = defaultdict(list)
        for road in roads:
            a, b = (road.a, road.b) if hasattr(road, 'a') else road
            self.adjacent[tuple(a)].append((tuple(a), tuple(b)))
            self.adjacent[tuple(b)].append((tuple(b), tuple(a)))
        self.ground = TerraceGround(settings, terraces)

    def __call__(self, x, y):
        size = self.size
        node = (round(x / size), round(y / size))
        found, beyond = [], []
        for a, b in self.adjacent.get(node, ()):
            ax, ay, bx, by = a[0] * size, a[1] * size, b[0] * size, b[1] * size
            dx, dy = bx - ax, by - ay
            raw = ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)
            t = max(0.0, min(1.0, raw))
            distance = math.hypot(x - ax - dx * t, y - ay - dy * t)
            # A street the point is not abreast of (it lies past the street's
            # end) only counts when no street is abreast of it.
            (found if t == raw else beyond).append((distance, self._level(a, b, t)))
        found = found or beyond
        if not found:
            return self.ground(x, y)
        nearest = min(d for d, _ in found)
        weights = [(max(0.0, self.BLEND - (d - nearest)), z) for d, z in found]
        total = sum(w for w, _ in weights)
        return sum(w * z for w, z in weights) / total

    def along(self, key, x, y):
        """Level of one street (lattice edge ``key``) abreast of (x, y)."""
        size = self.size
        a, b = (tuple(n) for n in key)
        ax, ay, bx, by = a[0] * size, a[1] * size, b[0] * size, b[1] * size
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return self._level(a, b, t)

    def _level(self, a, b, t):
        za, zb = self.heights.get(a, 0.0), self.heights.get(b, 0.0)
        key = edge(a, b)
        if key in self.ramps:
            ease = self.ramps[key] if key[0] == a else self.ramps[key][::-1]
            shape = ramp_shape(t, *ease)
        else:
            shape = t * t * (3 - 2 * t)
        return za + (zb - za) * shape


class TerraceGround:
    """Natural ground on a terraced city: the base hills blended across each
    block, plus the rise of the terrace the block belongs to."""

    def __init__(self, settings, terraces):
        self.base = Surface(settings, {(x, y): z for x, y, z in terraces.get('ground', ())})
        self.size = settings.block_size
        self.rise = terrace_cells(terraces)

    def __call__(self, x, y):
        cell = (math.floor(x / self.size), math.floor(y / self.size))
        return self.base(x, y) + self.rise.get(cell, 0.0)

    def rise_at(self, x, y):
        return self.rise.get((math.floor(x / self.size), math.floor(y / self.size)), 0.0)


# City shape. SQUARE fills the map. ORGANIC has an edge that wanders with the
# bearing: a base reach (a fraction of the map's half-width) plus a few seeded
# harmonics, fingers and a stretch along the highway (towns grow along their
# roads), all scaled by the irregularity, and value noise that frays it block
# by block.
SHAPES = ('SQUARE', 'ORGANIC')
OUTLINE_BASE = .74
OUTLINE_HARMONICS = (2, 3, 4, 5, 7)
OUTLINE_SWING = .45      # Harmonic k swings up to this / k**0.7 at irregularity 1.
OUTLINE_STRETCH = .16    # Extra reach along the highway at irregularity 1.
OUTLINE_FRAY = .14       # Edge noise at irregularity 1 (fraction of the reach).
OUTLINE_FRAY_SCALE = 2.0  # Blocks per noise cell.
OUTLINE_LEAST = .3       # The edge never comes nearer than this.
# Fingers: narrow lobes where the town has grown out along a road (count,
# reach at irregularity 1, half-width in radians).
OUTLINE_FINGERS = (2, 4)
OUTLINE_FINGER_REACH = (.2, .4)
OUTLINE_FINGER_WIDTH = (.15, .3)


@lru_cache(maxsize=64)
def _outline_terms(settings):
    rng = stream(settings.seed, "outline")
    harmonics = [(k, settings.irregularity * OUTLINE_SWING / k ** .7 * rng.uniform(.5, 1.0),
                  rng.uniform(0, 2 * math.pi)) for k in OUTLINE_HARMONICS]
    fingers = [(rng.uniform(-math.pi, math.pi),
                settings.irregularity * rng.uniform(*OUTLINE_FINGER_REACH),
                rng.uniform(*OUTLINE_FINGER_WIDTH))
               for _ in range(rng.randint(*OUTLINE_FINGERS))]
    return harmonics, fingers


def _noise(seed, x, y, key="fray"):
    """Smooth value noise in [0, 1] on a unit lattice."""
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    def corner(i, j):
        return _fray(seed, ix + i, iy + j, key)
    top = corner(0, 0) * (1 - fx) + corner(1, 0) * fx
    bottom = corner(0, 1) * (1 - fx) + corner(1, 1) * fx
    return top * (1 - fy) + bottom * fy


@lru_cache(maxsize=65536)
def _fray(seed, i, j, key="fray"):
    return stream(seed, key, i, j).random()


@lru_cache(maxsize=64)
def _outside(settings):
    """Lattice nodes, and edges by their midpoint, past an organic city's edge."""
    size, radius = settings.block_size, settings.radius
    nodes = frozenset((x, y) for x in range(-radius, radius + 1)
                      for y in range(-radius, radius + 1)
                      if not in_city(settings, x * size, y * size))
    edges = frozenset(edge((x, y), (x + dx, y + dy))
                      for x in range(-radius, radius + 1) for y in range(-radius, radius + 1)
                      for dx, dy in ((1, 0), (0, 1))
                      if not in_city(settings, (x + dx / 2) * size, (y + dy / 2) * size))
    return nodes, edges


def organic_edge(settings, bearing):
    """Reach of an organic city's edge along a bearing, as a fraction of the
    map's half-width (before fraying); never past the map."""
    harmonics, fingers = _outline_terms(settings)
    reach = OUTLINE_BASE + sum(a * math.cos(k * bearing + phase) for k, a, phase in harmonics)
    for centre, length, width in fingers:
        off = math.atan2(math.sin(bearing - centre), math.cos(bearing - centre))
        reach += length * math.exp(-(off / width) ** 2)
    reach += settings.irregularity * OUTLINE_STRETCH * math.cos(bearing) ** 4
    square = .98 / max(abs(math.cos(bearing)), abs(math.sin(bearing)))
    return min(square, max(OUTLINE_LEAST, reach))


def spread(settings, x, y):
    """How far out a point (metres from the centre) lies: 0 at the centre, 1
    at the city's edge. A square city's edge is the inscribed circle (its
    corners lie past 1); an organic city's is its outline."""
    half = settings.radius * settings.block_size
    distance = math.hypot(x, y) / half
    if settings.shape != 'ORGANIC' or distance == 0:
        return distance
    fray = OUTLINE_FRAY * settings.irregularity * (
        2 * _noise(settings.seed, x / (settings.block_size * OUTLINE_FRAY_SCALE),
                   y / (settings.block_size * OUTLINE_FRAY_SCALE)) - 1)
    return distance / organic_edge(settings, math.atan2(y, x)) + fray


def in_city(settings, x, y):
    """Inside the city's edge (every point of a square city is)."""
    return settings.shape != 'ORGANIC' or spread(settings, x, y) <= 1.0


def density_at(settings, x, y):
    distance = spread(settings, x, y)
    if distance > 1.0 and settings.shape == 'ORGANIC':
        return 0.0
    blend = min(1.0, max(0.0, (distance - settings.core_radius) /
                         max(.001, 1 - settings.core_radius)))
    blend = blend * blend * (3 - 2 * blend)
    return settings.core_density * (1 - blend) + settings.outskirts_density * blend


# In a small town the centre's district (its old-town main street) reaches
# less far than the others.
TOWN_CENTRE_WEIGHT = 1.7


def district_at(settings, x, y, locations):
    """Nearest centre/primary location in world metres; defines the district."""
    size = settings.block_size
    centre = TOWN_CENTRE_WEIGHT if settings.preset == 'SMALL_TOWN' else 1.0
    return min((loc for loc in locations if loc.role != 'SECONDARY'),
               key=lambda loc: math.dist((x, y), (loc.node[0] * size, loc.node[1] * size)) *
               (centre if loc.role == 'CENTER' else 1.0))


def _assign_districts(primaries, town=False):
    """Downtown core, midtown ring, industrial and suburban edges by sector
    (a town: homes round the old-town centre, industrial and suburban edges)."""
    order = sorted(primaries, key=lambda loc: (math.hypot(*loc.node), loc.node))
    edge_count = 2 if len(order) >= 5 else (1 if len(order) >= 3 else 0)
    core_count = 1 if len(order) >= 3 else 0
    # A town's old-town main street is the centre alone; homes surround it.
    assigned = {loc.id: 'RESIDENTIAL' if town else 'DOWNTOWN' for loc in order[:core_count]}
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
    ring = TOWN_STYLES if town else MIDTOWN_STYLES
    for index, loc in enumerate(remaining):
        assigned[loc.id] = ring[index % len(ring)]
    return assigned


def _route(start, target, roads, settings, blocked=frozenset(), confine=False,
           closed=frozenset()):
    """Dijkstra routing: favour existing streets, with stable corridor variation.
    ``confine``: an organic city's streets stay inside its edge (start and
    target excepted); without a way inside, the route may leave it, unless
    ``confine`` is 'strict'. ``closed``: edges the route may not use."""
    if confine and settings.shape == 'ORGANIC':
        nodes, edges = _outside(settings)
        path = _route(start, target, roads, settings, set(blocked) | (nodes - {start, target}),
                      closed=set(edges) | set(closed))
        if path is not None or confine == 'strict':
            return path
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
            if key in closed:
                continue
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


def _add_driving_loops(settings, locations, roads, blocked=frozenset(), closed=frozenset()):
    """Connect highway entry/exit pairs through districts without retracing a road.

    These are explicit multi-tier circuits, not merely a count of tiny grid cells.
    Only topology is built here; corner geometry comes from the route fillets,
    and bridges or banked roads are separate work.
    """
    if settings.driving_loop_count == 0:
        return []
    highway = {key: tier for key, tier in roads.items() if tier == 'HIGHWAY'}
    spine = _network_path((-settings.radius, 0), (settings.radius, 0), highway)
    # Circuits leave and rejoin the highway inside the city: the unbroken run
    # of the highway nearest the centre that lies within its edge.
    inside = [in_city(settings, n[0] * settings.block_size, n[1] * settings.block_size)
              for n in spine]
    low = high = min(range(len(spine)), key=lambda i: (math.hypot(*spine[i]), i))
    while low > 0 and inside[low - 1]:
        low -= 1
    while high < len(spine) - 1 and inside[high + 1]:
        high += 1
    spine = spine[low:high + 1]
    highway_nodes = {node for key in highway for node in key}
    anchors = [loc.node for loc in locations if loc.node not in highway_nodes and
               loc.node not in blocked]
    fallback = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                for y in range(-settings.radius + 1, settings.radius)
                if (x, y) not in highway_nodes and (x, y) not in anchors and
                (x, y) not in blocked and
                in_city(settings, x * settings.block_size, y * settings.block_size)]
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
        outward = _route(start, anchor, roads, settings, (highway_nodes - {start}) | blocked,
                         confine='strict', closed=closed)
        if outward is None:
            continue
        returning = _route(anchor, end, roads, settings,
                           (highway_nodes - {end}) | set(outward[:-1]) | blocked,
                           confine='strict', closed=closed)
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
    town = settings.preset == 'SMALL_TOWN'
    core = 'OLD_TOWN' if town else 'DOWNTOWN'
    locations = [Location("center", center, "CENTER",
                          core if settings.style == "MIXED" else settings.style)]
    occupied = {center}

    def connect(a, b, tier):
        path = _route(a, b, roads, settings, confine=tier != "HIGHWAY")
        if path is None:
            raise ValueError('Unable to connect location')
        for u, v in zip(path, path[1:]):
            key = edge(u, v)
            if key not in roads or ROAD_RANK[tier] < ROAD_RANK[roads[key]]:
                roads[key] = tier

    # Major destinations grow around the center before neighbourhood infill.
    size = settings.block_size
    candidates = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                  for y in range(-settings.radius + 1, settings.radius)
                  if .3 <= spread(settings, x * size, y * size) <= .85]
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
        assigned = _assign_districts(locations[1:], town)
        locations = [Location(loc.id, loc.node, loc.role, assigned.get(loc.id, loc.style))
                     for loc in locations]

    # Regional links extend to opposite map boundaries; these are at-grade prototypes.
    for end in ((-settings.radius, 0), (settings.radius, 0)):
        connect(end, center, "HIGHWAY")

    candidates = [(x, y) for x in range(-settings.radius + 1, settings.radius)
                  for y in range(-settings.radius + 1, settings.radius)
                  if (x, y) not in occupied and (settings.shape != 'ORGANIC' or
                                                 spread(settings, x * size, y * size) <= .9)]
    rng.shuffle(candidates)
    for index, node in enumerate(candidates[:settings.secondary_count]):
        district = min((loc for loc in locations if loc.role != 'SECONDARY'),
                       key=lambda loc: math.dist(node, loc.node))
        network = {n for road in roads for n in road
                   if in_city(settings, n[0] * size, n[1] * size)} or {center}
        target = min(sorted(network), key=lambda n: math.dist(node, n))
        connect(node, target, "COLLECTOR")
        # A node already on a road needs no extra edge.
        locations.append(Location(f"secondary_{index}", node, "SECONDARY", district.style))

    # Terraces are laid out on the main streets, before the circuits and the
    # local streets, which then keep to them (``guard``).
    terraces = _terraces(settings, locations, roads)
    guard = _terrace_guard(terraces)
    driving_loops = _add_driving_loops(settings, locations, roads, guard['nodes'],
                                       guard['edges'] | guard['stairs'])

    # Local growth starts from connected nodes only; loops naturally meet old streets.
    reached = {n for road in roads for n in road}
    frontier = sorted(reached, key=lambda p: (math.hypot(*p), p))
    tested = set(roads)
    stairs = set()
    for node in frontier:
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            other = (node[0] + dx, node[1] + dy)
            key = edge(node, other)
            if key in tested or max(map(abs, other)) > settings.radius:
                continue
            tested.add(key)
            if key in guard['edges']:
                continue
            x, y = ((node[i] + other[i]) * settings.block_size / 2 for i in range(2))
            if not in_city(settings, x, y):
                continue
            profile = STYLE_PROFILE[district_at(settings, x, y, locations).style]
            chance = (settings.road_density * profile['road'] *
                      (.2 + .8 * density_at(settings, x, y)))
            if key in guard['top']:
                chance = max(chance, TERRACE_STREETS)
            if stream(settings.seed, "local", key).random() <= chance:
                if key in guard['stairs']:
                    # A street up a terrace's face is a stair.
                    stairs.add(key)
                    continue
                roads[key] = "LOCAL"
                if other not in reached:
                    reached.add(other)
                    frontier.append(other)

    _close_downtown_streets(settings, locations, roads, guard['keep'])
    culdesacs = _add_culdesacs(settings, locations, roads, guard)
    _finish_terraces(terraces, roads, stairs)
    road_list = [Road(a, b, tier) for (a, b), tier in sorted(roads.items())]
    paths = _build_paths(settings, roads, locations)
    pois = (_place_pois(settings, locations, roads, paths, culdesacs, terraces)
            if settings.points_of_interest else [])
    reserved = {block for poi in pois for block in poi.blocks}
    downtown, dense = _place_downtown(settings, locations, roads, paths, reserved, terraces)
    lots = downtown + _place_lots(settings, locations, roads, reserved | dense, culdesacs,
                                  terraces)
    # Stable priority sampling avoids truncating one geographical side of the
    # city; the buildings of one downtown block are kept or dropped together.
    lots.sort(key=lambda lot: (stream(settings.seed, "budget", lot.group or lot.id).random(), lot.id))
    eligible = len(lots)
    lots = sorted(lots[:settings.max_buildings], key=lambda lot: lot.id)
    shelters = _place_shelters(settings, roads, lots, pois) if settings.points_of_interest else []
    heights = {}
    if settings.terrain != 'FLAT':
        ramps = [edge(tuple(a), tuple(b)) for ramp in terraces.get('ramps', ())
                 for a, b in zip(ramp['nodes'], ramp['nodes'][1:])]
        heights = _grade(settings, roads, pois, ramps, _terrace_benches(terraces))
        surface = Surface(settings, heights)

        def front_point(item):
            # The middle of the front (the pad's street side).
            reach = item.depth / 2
            return (item.center[0] + math.sin(item.rotation) * reach,
                    item.center[1] - math.cos(item.rotation) * reach)

        def front(item):
            return surface(*front_point(item))
        if terraces:
            terraces['ground'] = [[x, y, z] for (x, y), z in sorted(heights.items())]
            raised = _terrace_raises(terraces)
            heights = {node: round(heights.get(node, 0.0) + raised.get(node, 0.0), 3)
                       for node in sorted(set(heights) | set(raised))}
            heights = {node: z for node, z in heights.items() if z}
            surface = RoadSurface(settings, heights, roads, terraces)

            def front(item):
                # Level with the street the item faces (a ring house: the
                # circle), where it faces it: a superblock's frontage names
                # one edge of a longer side.
                point = front_point(item)
                if getattr(item, 'bulb', ()):
                    return surface(*point)
                (ax, ay), (bx, by) = item.frontage
                if ay == by:
                    k = math.floor(point[0] / size)
                    key = edge((k, ay), (k + 1, ay))
                else:
                    k = math.floor(point[1] / size)
                    key = edge((ax, k), (ax, k + 1))
                if key in roads:
                    return surface.along(key, *point)
                # Abreast of a gap in the street: on its own block's ground.
                return surface.ground.base(*point) + surface.ground.rise_at(*item.center)
        lots = [replace(lot, level=round(front(lot), 3)) for lot in lots]
        pois = [replace(poi, level=round(front(poi), 3)) for poi in pois]
        shelters = [replace(shelter, level=round(
            surface.along(shelter.road, *shelter.position) if terraces else
            surface(*shelter.position), 3)) for shelter in shelters]
    return CityPlan(settings, locations, road_list, paths, lots, eligible, driving_loops,
                    pois, shelters, _outer_roads(settings, paths), culdesacs,
                    [[x, y, z] for (x, y), z in sorted(heights.items())], terraces)


# Suburban cul-de-sacs: a short street from the network to an inner lattice
# node with no road, ending in a turning circle of this radius (carriageway).
CULDESAC_RADIUS = 10.0
CULDESAC_CHANCE = .7
# Houses ring the turning circle, facing it across a front yard this deep, at
# least BULB_GAP apart; their size range (along the circle, away from it).
BULB_YARD = 4.0
BULB_GAP = 2.0
BULB_HOUSE = ((9.0, 11.0), (8.5, 10.5))
# Share of a developed tract's plots that get a house (a ring round a
# turning circle is always built in full).
TRACT_FILL = .9
# Tract rows: plot width along the street, the gap between houses, and the
# deepest house.
TRACT_PLOT = 10.0
TRACT_GAP = 3.0
TRACT_DEPTH = 11.0


def _add_culdesacs(settings, locations, roads, guard=None):
    """Dead-end stubs into suburban blocks. A node no street reaches, with
    suburban blocks on all four sides, gets one local street from a
    neighbouring road node; the houses either side face it and its end is a
    turning circle (``culdesacs``). Sites keep out of those four blocks."""
    size = settings.block_size
    degree = {}
    for a, b in roads:
        for node in (a, b):
            degree[node] = degree.get(node, 0) + 1
    radius = settings.radius
    added = []
    for x in range(-radius + 1, radius):
        for y in range(-radius + 1, radius):
            node = (x, y)
            if degree.get(node) or any(math.dist(node, end) < 1.5 for end in added):
                continue
            if guard and node in guard['avoid']:
                continue
            cells = [(x - 1, y - 1), (x, y - 1), (x - 1, y), (x, y)]
            centres = [((cx + .5) * size, (cy + .5) * size) for cx, cy in cells]
            # Only houses stand round a turning circle: all four blocks are
            # suburban (and inside an organic city's edge).
            if any(district_at(settings, *c, locations).style != 'SUBURBAN' or
                   not in_city(settings, *c) for c in centres):
                continue
            if density_at(settings, x * size, y * size) < .2:
                continue
            neighbours = [(x + dx, y + dy) for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1))
                          if degree.get((x + dx, y + dy)) and
                          roads.get(edge(node, (x + dx, y + dy))) is None]
            neighbours = [n for n in neighbours if all(
                roads.get(edge(n, m)) != 'HIGHWAY' for m in
                ((n[0] + 1, n[1]), (n[0] - 1, n[1]), (n[0], n[1] + 1), (n[0], n[1] - 1)))]
            if guard:
                neighbours = [n for n in neighbours if edge(node, n) not in guard['edges']]
            rng = stream(settings.seed, 'culdesac', node)
            if not neighbours or rng.random() > CULDESAC_CHANCE:
                continue
            start = rng.choice(sorted(neighbours))
            roads[edge(start, node)] = 'LOCAL'
            degree[start] = degree.get(start, 0) + 1
            degree[node] = 1
            added.append(node)
    return [{'node': [x, y], 'radius': CULDESAC_RADIUS} for x, y in added]


def _pick_condition(style, rng):
    roll = rng.uniform(0, 100)
    for condition, weight in CONDITION_WEIGHTS[style]:
        roll -= weight
        if roll <= 0:
            return condition
    return 'INTACT'


def _corners(center, width, depth, rotation):
    """World corners of a footprint (width along its front, depth away)."""
    c, s = math.cos(rotation), math.sin(rotation)
    return [(center[0] + x * c - y * s, center[1] + x * s + y * c)
            for x, y in ((-width / 2, -depth / 2), (width / 2, -depth / 2),
                         (width / 2, depth / 2), (-width / 2, depth / 2))]


def _apart(a, b, gap):
    """Two convex polygons are at least ``gap`` apart along some edge normal."""
    for polygon in (a, b):
        for (x0, y0), (x1, y1) in zip(polygon, polygon[1:] + polygon[:1]):
            nx, ny = y1 - y0, x0 - x1
            length = math.hypot(nx, ny)
            nx, ny = nx / length, ny / length
            pa = [x * nx + y * ny for x, y in a]
            pb = [x * nx + y * ny for x, y in b]
            if min(pb) - max(pa) >= gap or min(pa) - max(pb) >= gap:
                return True
    return False


def _clear_of_bulbs(corners, bulbs):
    """No turning circle (centre x, y; clearance) reaches the footprint."""
    for bx, by, clear in bulbs:
        inside = all((x1 - x0) * (by - y0) - (y1 - y0) * (bx - x0) >= 0
                     for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]))
        if inside or min(_point_segment(bx, by, a, b)
                         for a, b in zip(corners, corners[1:] + corners[:1])) < clear:
            return False
    return True


def _point_segment(px, py, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def _make_lot(settings, ident, rng, district, profile, center, width, depth, rotation,
              frontage, bulb=()):
    """Condition, height and damage of an ordinary building (draws from ``rng``
    in the order the lot pass always has)."""
    condition_rng = stream(settings.seed, "condition", ident)
    condition = _pick_condition(district.style, condition_rng)
    floors = rng.randint(*(TOWN_FLOORS.get(district.style, profile['floors'])
                           if settings.preset == 'SMALL_TOWN' else profile['floors']))
    if condition == 'WALL_RING':
        floors = min(floors, rng.randint(2, 4))
    damage = min(1.0, max(
        settings.damage * profile['damage'] * CONDITION_DAMAGE[condition],
        CONDITION_MIN_DAMAGE[condition]))
    if floors > 8:
        # Tall towers carry more visible damage than low-rise blocks.
        damage = min(1.0, damage * (1 + min(.5, (floors - 8) * .045)))
    interiors = (condition in INTERIOR_CONDITIONS and
                 condition_rng.random() < settings.interior_ratio)
    return Lot(ident, center, width, depth, rotation, district.style, district.id, floors,
               rng.randrange(2**31), frontage, condition=condition, interiors=interiors,
               damage=damage, bulb=bulb)


def _bulb_lots(settings, locations, roads, reserved, culdesacs):
    """Suburban houses in a ring round each turning circle, facing it."""
    size, walk = settings.block_size, settings.sidewalk_width
    clear = [(c['node'][0] * size, c['node'][1] * size, c['radius'] + walk + 1.0)
             for c in culdesacs]
    (w_low, w_high), (d_low, d_high) = BULB_HOUSE
    lots = []
    for bulb in culdesacs:
        node = tuple(bulb['node'])
        stub = next(key for key in sorted(roads) if node in key)
        start = stub[0] if stub[1] == node else stub[1]
        heading = math.atan2(start[1] - node[1], start[0] - node[0])
        front = bulb['radius'] + walk + BULB_YARD
        # The first place round from the street keeps the widest house clear of
        # the street's footway (the houses along it face the street itself).
        corridor = ROAD_WIDTHS['LOCAL'] / 2 + walk + BULB_GAP
        first = next(math.radians(d) for d in range(10, 91)
                     if front * math.sin(math.radians(d)) -
                     w_high / 2 * math.cos(math.radians(d)) >= corridor)
        pitch = 2 * math.atan((w_high + BULB_GAP) / 2 / front)
        span = 2 * math.pi - 2 * first
        count = int(span / pitch) + 1
        step = span / (count - 1)
        for index in range(count):
            angle = heading + first + index * step
            # Named after the block it stands in, like every lot.
            spot = (node[0] + (front + d_high / 2) * math.cos(angle) / size,
                    node[1] + (front + d_high / 2) * math.sin(angle) / size)
            ident = f"lot_{math.floor(spot[0])}_{math.floor(spot[1])}_ring{index}"
            rng = stream(settings.seed, ident)
            width, depth = rng.uniform(w_low, w_high), rng.uniform(d_low, d_high)
            centre = (node[0] * size + (front + depth / 2) * math.cos(angle),
                      node[1] * size + (front + depth / 2) * math.sin(angle))
            # Local -y (the front) faces the circle.
            rotation = math.atan2(math.sin(angle - math.pi / 2), math.cos(angle - math.pi / 2))
            corners = _corners(centre, width, depth, rotation)
            district = district_at(settings, *centre, locations)
            if district.style != 'SUBURBAN' or not in_city(settings, *centre):
                continue
            if any((math.floor(x / size), math.floor(y / size)) in reserved for x, y in corners):
                continue
            others = [c for c in clear if math.dist(c[:2], (node[0] * size, node[1] * size)) > 1]
            if not _clear_of_bulbs(corners, others):
                continue
            if not all(_apart(corners, _corners(lot.center, lot.width, lot.depth, lot.rotation),
                              BULB_GAP) for lot in lots):
                continue
            lots.append(_make_lot(settings, ident, rng, district, STYLE_PROFILE['SUBURBAN'],
                                  centre, width, depth, rotation, stub, node))
    return lots


def _tract_rows(streets, low_x, high_x, low_y, high_y, profile, rng):
    """Houses in rows along a suburban block's streets: (side, index, centre,
    width along the street, depth). The rows on the south and north streets
    run the block's width; those on the west and east fit between them."""
    span_x, span_y = high_x - low_x, high_y - low_y
    def band(side, across):
        opposite = {"S": "N", "N": "S", "W": "E", "E": "W"}[side]
        room = (across - TRACT_GAP) / 2 if opposite in streets else across
        return min(TRACT_DEPTH, room)
    depths = {side: band(side, span_y if side in "SN" else span_x) for side in streets}
    houses = []
    for side in streets:
        if side in "SN":
            start, end = low_x, high_x
        else:
            start = low_y + (depths["S"] + TRACT_GAP if "S" in depths else 0)
            end = high_y - (depths["N"] + TRACT_GAP if "N" in depths else 0)
        length = end - start
        count = max(1, round((length + TRACT_GAP) / (TRACT_PLOT + TRACT_GAP)))
        plot = (length - (count - 1) * TRACT_GAP) / count
        if plot < 5 or depths[side] < 5:
            continue
        for index in range(count):
            width = plot * rng.uniform(*profile['footprint'])
            depth = depths[side] * rng.uniform(*profile['footprint'])
            if width < 5 or depth < 5:
                continue
            along = start + index * (plot + TRACT_GAP) + plot / 2
            # The front wall stands on the street-facing building line.
            if side == "S":
                center = (along, low_y + depth / 2)
            elif side == "N":
                center = (along, high_y - depth / 2)
            elif side == "W":
                center = (low_x + depth / 2, along)
            else:
                center = (high_x - depth / 2, along)
            houses.append((side, index, center, width, depth))
    return houses


def _place_lots(settings, locations, roads, reserved=frozenset(), culdesacs=(), terraces=None):
    walls = terrace_obstacles(terraces)[0]
    rings = _bulb_lots(settings, locations, roads, reserved, culdesacs)
    ring_corners = [_corners(lot.center, lot.width, lot.depth, lot.rotation) for lot in rings]
    lots = list(rings)
    size = settings.block_size
    bulbs = [(c['node'][0] * size, c['node'][1] * size,
              c['radius'] + settings.sidewalk_width + 1.0) for c in culdesacs]
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
            tract = profile.get('tract', 0)
            if tract and stream(settings.seed, "tract", x, y).random() > min(
                    1.0, density_at(settings, (x + .5) * size, (y + .5) * size) * tract):
                continue
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
            walled = walls.get((x, y), ())
            if tract:
                streets = [side for side in "SNWE" if borders[side] in roads and
                           roads[borders[side]] != "HIGHWAY" and borders[side] not in walled]
                for side, index, center, width, depth in _tract_rows(
                        streets, low_x, high_x, low_y, high_y, profile,
                        stream(settings.seed, "tract_rows", x, y)):
                    ident = f"lot_{x}_{y}_{side}{index}"
                    rng = stream(settings.seed, ident)
                    if rng.random() > TRACT_FILL:
                        continue
                    box = _corners(center, width, depth, SIDE_ROTATION[side])
                    if not _clear_of_bulbs(box, bulbs) or not all(
                            _apart(box, ring, BULB_GAP) for ring in ring_corners):
                        continue
                    lots.append(_make_lot(settings, ident, rng, district, profile, center,
                                          width, depth, SIDE_ROTATION[side], borders[side]))
                continue
            cells = profile['parcels']
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
                        if (available and borders[side] in roads and
                                roads[borders[side]] != "HIGHWAY" and borders[side] not in walled):
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
                    # Turning circles and their footway stay clear of the parcel,
                    # and so do the houses round them.
                    if any(math.hypot(max(cx - sx / 2 - bx, 0, bx - cx - sx / 2),
                                      max(cy - sy / 2 - by, 0, by - cy - sy / 2)) < clear
                           for bx, by, clear in bulbs):
                        continue
                    box = [(cx - sx / 2, cy - sy / 2), (cx + sx / 2, cy - sy / 2),
                           (cx + sx / 2, cy + sy / 2), (cx - sx / 2, cy + sy / 2)]
                    if not all(_apart(box, ring, BULB_GAP) for ring in ring_corners):
                        continue
                    width, depth = (sy, sx) if side in "WE" else (sx, sy)
                    rotation = {"S": 0, "E": math.pi / 2, "N": math.pi, "W": -math.pi / 2}[side]
                    lots.append(_make_lot(settings, ident, rng, district, profile, (cx, cy),
                                          width, depth, rotation, borders[side]))
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


def _best_front(rule, sides, roads, along, blocked=frozenset()):
    """The side a site faces: best road tier, most road along it, required
    length; never a ``blocked`` edge (a terrace wall or a ramp)."""
    best = None
    for side, edges in sides.items():
        if len(edges) != along:
            continue
        tiers = [roads.get(e) for e in edges]
        if "HIGHWAY" in tiers or any(e in blocked for e in edges):
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


def _place_pois(settings, locations, roads, paths, culdesacs=(), terraces=None):
    size = settings.block_size
    walls, region, stairs, stair_rows = terrace_obstacles(terraces)
    nodes = {}
    for (a, b), tier in roads.items():
        for node in (a, b):
            nodes[node] = max(nodes.get(node, 0), ROAD_WIDTHS[tier] / 2)
    rows = _path_rows(paths) + _stair_rows(settings, stair_rows)
    # Turning circles keep pads clear like any carriageway.
    rows += [(c['node'][0] * size, c['node'][1] * size, c['node'][0] * size, c['node'][1] * size,
              c['radius']) for c in culdesacs]
    radius = settings.radius
    urban = sum(1 for x in range(-radius, radius) for y in range(-radius, radius)
                if density_at(settings, (x + .5) * size, (y + .5) * size) >= POI_MIN_DENSITY and
                any(e in roads for e in _side_edges(x, y, 1, 1)["S"] + _side_edges(x, y, 1, 1)["N"] +
                    _side_edges(x, y, 1, 1)["W"] + _side_edges(x, y, 1, 1)["E"]))
    # The blocks round a turning circle are left to the houses facing it.
    taken = {(c['node'][0] + dx, c['node'][1] + dy) for c in culdesacs
             for dx in (-1, 0) for dy in (-1, 0)}
    pois = []
    for kind, rule in poi_rules(settings).items():
        rng = stream(settings.seed, "poi", kind)
        expected = rule['count'] * urban / 100
        quota = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        quota = max(quota, rule['minimum'])
        if 'most' in rule:
            quota = min(quota, rule['most'])
        if 'per_radius' in rule:
            quota = max([n for r, n in rule['per_radius'] if radius >= r] or [0])
        minimum = min(quota, rule['minimum']) if 'per_radius' not in rule else quota
        near = []
        if 'near' in rule:
            anchor, reach, factor = rule['near']
            near = [p.center for p in pois if p.kind == anchor]
        centres = []
        if 'anchors' in rule:
            styles, centre_reach, centre_factor = rule['anchors']
            centres = [(loc.node[0] * size, loc.node[1] * size) for loc in locations
                       if loc.style in styles]
        candidates = []
        for along, away in rule['blocks']:
            for wx, wy, fronts in ((along, away, "SN"), (away, along, "WE")):
                for x in range(-radius, radius - wx + 1):
                    for y in range(-radius, radius - wy + 1):
                        group = tuple((x + i, y + j) for i in range(wx) for j in range(wy))
                        if any(b in taken for b in group):
                            continue
                        if any(e in roads or e in stairs for e in _inner_edges(x, y, wx, wy)):
                            continue
                        # A site stands on one level.
                        if len({region.get(b) for b in group}) > 1:
                            continue
                        sides = {k: v for k, v in _side_edges(x, y, wx, wy).items() if k in fronts}
                        front = _best_front(rule, sides, roads, along,
                                            {e for b in group for e in walls.get(b, ())})
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
                        # Retail gathers round the mall.
                        if near and weight > 0 and any(math.dist((cx, cy), centre) <= reach * size
                                                       for centre in near):
                            weight *= factor
                        # Plazas and strip malls repeat round their district centres.
                        if centres and weight > 0 and any(
                                math.dist((cx, cy), centre) <= centre_reach * size
                                for centre in centres):
                            weight *= centre_factor
                        key = stream(settings.seed, "poi", kind, x, y, wx, wy).random()
                        candidates.append((weight > 0, key ** (1 / max(weight, .02)),
                                           (x, y, wx, wy), group, front, district))
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        placed = []
        for preferred, _, (x, y, wx, wy), group, (side, frontage), district in candidates:
            if len(placed) >= quota or (not preferred and len(placed) >= minimum):
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
DOWNTOWN_MAX_DEPTH = 40.0    # Deepest tower plot; deeper blocks keep a yard or courtyard.
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


def _close_downtown_streets(settings, locations, roads, keep=frozenset()):
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
                  if tier == "LOCAL" and key not in keep and
                  all(_downtown(settings, locations, b) for b in _edge_blocks(key))]
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


def _place_downtown(settings, locations, roads, paths, reserved, terraces=None):
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
    walls, region, stairs, stair_rows = terrace_obstacles(terraces)
    rows = _path_rows(paths) + _stair_rows(settings, stair_rows)
    verge = max(DOWNTOWN_VERGE, settings.setback - settings.sidewalk_width + .1)
    owned = {(x, y) for x in range(-radius, radius) for y in range(-radius, radius)
             if (x, y) not in reserved and _downtown(settings, locations, (x, y))}
    candidates = []
    for wx, wy in ((2, 2), (2, 1), (1, 2), (1, 1)):
        for x, y in sorted(owned):
            group = tuple((x + i, y + j) for i in range(wx) for j in range(wy))
            if any(b not in owned for b in group):
                continue
            if any(e in roads or e in stairs for e in _inner_edges(x, y, wx, wy)):
                continue
            if len({region.get(b) for b in group}) > 1:
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
        walled = {e for b in group for e in walls.get(b, ())}
        for side, edges in _side_edges(x, y, wx, wy).items():
            usable = [e for e in edges if roads.get(e) not in (None, "HIGHWAY")]
            # Towers line the whole side: none faces a terrace wall or ramp.
            if usable and not walled & set(edges):
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

    def priority(side):
        # Face a long side of the pad (a superblock's frontage), then the
        # best street, then the most street along it.
        length, other = ((x1 - x0), (y1 - y0)) if side in "SN" else ((y1 - y0), (x1 - x0))
        return (0 if length >= other - 1e-6 else 1, min(ROAD_RANK[roads[e]] for e in sides[side]),
                -len(sides[side]), side)
    main = min(sides, key=priority)
    horizontal = main in "SN"
    along = (x1 - x0) if horizontal else (y1 - y0)
    deep = (y1 - y0) if horizontal else (x1 - x0)
    alley = 0.0
    abut = False
    if OPPOSITE[main] in sides and deep >= 34 and rng.random() < .75:
        alley = 6.0 if rng.random() < .3 else 0.0
        if deep - alley > 2 * DOWNTOWN_MAX_DEPTH:
            # Too deep for two rows back to back: a courtyard between them.
            front = DOWNTOWN_MAX_DEPTH * rng.uniform(.75, 1.0)
            back = DOWNTOWN_MAX_DEPTH * rng.uniform(.75, 1.0)
            rows = [(0.0, front, main), (deep - back, deep, OPPOSITE[main])]
        else:
            split = (deep - alley) * rng.uniform(.42, .58)
            rows = [(0.0, split, main), (split + alley, deep, OPPOSITE[main])]
            abut = alley == 0.0
    else:
        # One row on the street; a deep block keeps a yard behind it.
        depth = deep if deep <= DOWNTOWN_MAX_DEPTH else DOWNTOWN_MAX_DEPTH * rng.uniform(.8, 1.0)
        rows = [(0.0, depth, main)]

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
            if abut:
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
            low, high = (TOWN_FLOORS['DOWNTOWN'] if settings.preset == 'SMALL_TOWN'
                         else profile['floors'])
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

