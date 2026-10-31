# SPDX-License-Identifier: GPL-3.0-or-later
"""City sites (points of interest): gas stations, fast food, schools, hospitals,
police and fire stations, transit, parks, parking, strip malls and shopping
plazas.

Pure Python. ``compose(kind, width, depth, seed)`` lays out a pad of
``width x depth`` metres in site coordinates: centred on the origin, the street
along the front edge (y = -depth / 2), z = 0 at pad level (curb height in the
city). The result is a list of buildings (generator parameters plus a
position and quarter-turn) and a ground mesh of closed solids: pads, paint,
curbs, canopies, pumps, benches, signs, and bases where the game places
fences and flagpoles (trees, fences and flagpoles are game assets).

Rules shared with the buildings: every prop is a closed solid; props touch
only with opposite-facing faces; stacked surface layers use distinct heights
(``LAYER``) so nothing shares a plane and z-fights.
"""
import math
import random
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import dims, layouts, rubble, solids, styles
from .meshdata import MeshData
from .spec import BuildingSpec

# Site material slots (see building_assets.SITE_MATERIALS).
S_ASPHALT, S_CONCRETE, S_PAINT, S_YELLOW, S_GRASS, S_FOLIAGE, S_METAL, S_SIGN, \
    S_WOOD, S_RUBBLE, S_GLASS, S_RUBBER, S_WATER = range(13)

# Heights of stacked surface layers above the pad (top faces).
LAYER = {'paint': .010, 'paint_cross': .012, 'paint_mark': .014, 'paint_mark2': .016,
         'apron': .025,
         'lawn': .04, 'path': .055, 'path_cross': .065, 'rubber': .07,
         'plaza': .08, 'island': .15, 'walk': .15, 'platform': .2}
PAD_THICKNESS = .35
KINDS = ('GAS_STATION', 'FAST_FOOD', 'SCHOOL', 'HOSPITAL', 'POLICE', 'FIRE_STATION',
         'TRANSIT_STATION', 'PARK', 'PARKING_LOT', 'PARKING_GARAGE', 'STRIP_MALL',
         'SHOPPING_PLAZA', 'AUTO_REPAIR', 'MALL', 'HOTEL', 'MOTEL', 'CINEMA', 'DRIVE_IN')
VARIANTS = {
    'GAS_STATION': ('BACK', 'SIDE'),
    'FAST_FOOD': ('MANSARD', 'BOX', 'DINER'),
    'SCHOOL': ('BAR', 'WING'),
    'HOSPITAL': ('TOWER', 'SLAB'),
    'POLICE': ('CIVIC', 'MODERN'),
    'FIRE_STATION': ('CLASSIC', 'MODERN'),
    'TRANSIT_STATION': ('TERMINAL', 'HUB'),
    'PARK': ('GREEN', 'PLAYGROUND', 'PLAZA', 'SPORTS'),
    'PARKING_LOT': ('ROWS', 'ANGLED'),
    'PARKING_GARAGE': ('DECKS', 'TALL'),
    'STRIP_MALL': ('ROW', 'L'),
    'SHOPPING_PLAZA': ('PAIR', 'ANCHOR'),
    'AUTO_REPAIR': ('BAYS', 'YARD'),
    'MALL': ('DUMBBELL', 'JUNIOR'),
    'HOTEL': ('GRAND', 'BUDGET'),
    'MOTEL': ('STRIP', 'COURT'),
    'CINEMA': ('PALACE', 'MULTIPLEX'),
    'DRIVE_IN': ('SINGLE', 'TWIN'),
}
# Layouts that suit a district style better (when no variant is asked for).
STYLE_VARIANTS = {'CINEMA': {'OLD_TOWN': 'PALACE', 'DOWNTOWN': 'PALACE', 'BRUTALIST': 'PALACE',
                             'SUBURBAN': 'MULTIPLEX', 'INDUSTRIAL': 'MULTIPLEX'},
                  'HOTEL': {'OLD_TOWN': 'GRAND', 'DOWNTOWN': 'GRAND', 'SUBURBAN': 'BUDGET',
                            'INDUSTRIAL': 'BUDGET'},
                  'PARK': {'OLD_TOWN': 'PLAZA', 'DOWNTOWN': 'PLAZA'}}
# Smallest pad (width, depth) each kind is laid out for.
MIN_PAD = {'GAS_STATION': (24, 22), 'FAST_FOOD': (26, 24), 'SCHOOL': (40, 32),
           'HOSPITAL': (44, 32), 'POLICE': (28, 26), 'FIRE_STATION': (28, 26),
           'TRANSIT_STATION': (28, 24), 'PARK': (16, 16), 'PARKING_LOT': (20, 20),
           'PARKING_GARAGE': (30, 26), 'STRIP_MALL': (30, 26), 'SHOPPING_PLAZA': (80, 70),
           'AUTO_REPAIR': (30, 28), 'MALL': (90, 80), 'HOTEL': (30, 28), 'MOTEL': (36, 28),
           'CINEMA': (32, 30), 'DRIVE_IN': (80, 40)}
WALL_COLORS = {'GAS_STATION': (.86, .86, .83, 1), 'FAST_FOOD': (.74, .30, .20, 1),
               'SCHOOL': (.60, .35, .26, 1), 'HOSPITAL': (.85, .86, .87, 1),
               'POLICE': (.44, .47, .54, 1), 'FIRE_STATION': (.64, .23, .19, 1),
               'TRANSIT_STATION': (.68, .70, .68, 1), 'PARKING_GARAGE': (.58, .58, .56, 1),
               'STRIP_MALL': (.80, .74, .64, 1), 'SHOPPING_PLAZA': (.72, .73, .75, 1),
               'PARK': (.66, .64, .60, 1), 'PARKING_LOT': (.62, .62, .60, 1),
               'AUTO_REPAIR': (.70, .67, .58, 1), 'MALL': (.78, .75, .70, 1),
               'HOTEL': (.80, .76, .68, 1), 'MOTEL': (.86, .80, .66, 1),
               'CINEMA': (.56, .31, .28, 1), 'DRIVE_IN': (.84, .82, .78, 1)}


@dataclass
class SiteBuilding:
    name: str
    params: dict
    x: float           # Footprint centre in site coordinates.
    y: float
    quarter: int = 0   # Quarter turns; 0 = front facade faces the street (-y).
    role: str = ''

    @property
    def footprint(self):
        w, d = self.params['width'], self.params['depth']
        if self.quarter % 2:
            w, d = d, w
        return (self.x - w / 2, self.y - d / 2, self.x + w / 2, self.y + d / 2)


@dataclass
class Site:
    kind: str
    variant: str
    width: float
    depth: float
    approach: float
    ground: MeshData
    buildings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    markers: list = field(default_factory=list)    # Placements for game assets (Ground.mark).


def designed(width, depth, floors, floor_height, seed, profile='NONE', **extra):
    """Generator parameters for a purpose-built (non-district) building."""
    params = dict(
        width=width, depth=depth, floors=floors, floor_height=floor_height,
        ground_floor_height=floor_height, wall_thickness=.3, window_type='RECTANGULAR',
        window_width=1.6, window_height=1.6, window_spacing=1.0, sill_height=.9,
        window_sides='ALL', ground_floor_windows='REGULAR', storefront_window_width=2.6,
        storefront_window_height=2.8, storefront_sill_height=.4, door_width=1.8,
        door_height=2.5, front_door_offset=.5, back_exit=False, back_door_offset=.5,
        flat_roof=True, floor_slabs=True, facade_pilasters=False, pilaster_width=.35,
        pilaster_depth=.15, pilaster_style='CORNERS', pilaster_sides='FRONT',
        roof_parapet=True, parapet_height=.9, has_patio=False, building_profile=profile,
        skyscraper=False, exterior_stairs=False, interior_fill='NONE', exterior_rubble=False,
        enable_damage=False, damage_amount=0.0, damage_pointiness=.4, damage_resolution=1.0,
        seed=seed, auto_clean=True, mark_uv_seams=True, roof_kind='FLAT', roof_height=0.0,
        roof_overhang=0.0, roof_box=None, lobby='NONE', facade_system='PUNCHED',
        cornice=False)
    params.update(extra)
    return params


# Small props the game replaces with destructible assets: with ``props`` off
# they are only recorded as markers.
SMALL_PROPS = ('bench', 'lamp', 'bollard', 'gas_pump', 'dumpster', 'table', 'booth',
               'play_structure', 'swings', 'goal', 'trash_bin', 'air_pump', 'hydrant',
               'cart_corral', 'tyre_stack', 'speaker_post')


def _turn(quarter, fx, fy):
    for _ in range(quarter % 4):
        fx, fy = -fy, fx
    return fx, fy


class Ground:
    """Closed-solid site props in site coordinates, plus markers: where the game
    places its own assets (small props, trees, fences, flagpoles, parked cars,
    water). With ``water`` off, basins are modelled dry."""

    def __init__(self, props=True, water=False):
        self.mesh = MeshData()
        self.props = props
        self.water = water
        self.markers = []

    def mark(self, kind, x, y, z=0.0, facing=(0.0, -1.0), **extra):
        """Record a placement; ``facing`` is the direction its front looks."""
        marker = dict(type=kind, x=round(x, 3), y=round(y, 3), z=round(z, 3),
                      facing=(round(facing[0], 6), round(facing[1], 6)))
        marker.update(extra)
        self.markers.append(marker)
        return self.props or kind not in SMALL_PROPS

    # -- surfaces --------------------------------------------------------
    def pad(self, rect, material):
        x0, y0, x1, y1 = rect
        solids.box(self.mesh, x0, y0, -PAD_THICKNESS, x1, y1, 0.0, material)

    def layer(self, rect, material, name):
        x0, y0, x1, y1 = rect
        if x1 - x0 > .05 and y1 - y0 > .05:
            solids.box(self.mesh, x0, y0, 0.0, x1, y1, LAYER[name], material)

    def poly(self, outline, material, z0, z1):
        solids.prism(self.mesh, _ccw(outline), z0, z1, material)

    def strip(self, a, b, width, material, name='paint', z0=0.0):
        """Straight band from a to b (paint lines, paths)."""
        (ax, ay), (bx, by) = a, b
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-3:
            return
        nx, ny = -(by - ay) / length * width / 2, (bx - ax) / length * width / 2
        self.poly([(ax + nx, ay + ny), (ax - nx, ay - ny), (bx - nx, by - ny), (bx + nx, by + ny)],
                  material, z0, LAYER[name] if isinstance(name, str) else name)

    def box(self, x0, y0, z0, x1, y1, z1, material):
        solids.box(self.mesh, x0, y0, z0, x1, y1, z1, material)

    def boxc(self, cx, cy, w, d, z0, z1, material):
        solids.box(self.mesh, cx - w / 2, cy - d / 2, z0, cx + w / 2, cy + d / 2, z1, material)

    def cylinder(self, cx, cy, radius, z0, z1, material, segments=8):
        solids.cylinder(self.mesh, cx, cy, radius, z0, z1, material, segments)

    def fountain_basin(self, cx, cy, radius, base, column=0.0, rim=.65, bed=.3, level=.62,
                       segments=14):
        """Round basin: a rim wall ``rim`` high around a bed at ``bed``, filled
        to ``level`` when water is on (dry otherwise), with an optional central
        column of radius ``column`` standing on the bed. The water is always a
        marker: surface height, size (diameter twice, depth)."""
        wall = .3
        self.mark('water', cx, cy, level, shape='circle',
                  size=(2 * (radius - wall), 2 * (radius - wall), level - bed))
        solids.ring(self.mesh, cx, cy, radius - wall, radius, base, rim, S_CONCRETE, segments)
        solids.cylinder(self.mesh, cx, cy, radius - wall, base, bed, S_CONCRETE, segments)
        if self.water:
            if column > 0:
                solids.ring(self.mesh, cx, cy, column, radius - wall, bed, level, S_WATER, segments)
            else:
                solids.cylinder(self.mesh, cx, cy, radius - wall, bed, level, S_WATER, segments)
        return bed

    # -- props -----------------------------------------------------------
    def bench(self, x, y, quarter=0, base=0.0):
        if not self.mark('bench', x, y, base, _turn(quarter, 0.0, -1.0), size=(1.6, .5, .95)):
            return
        part = Ground()
        part.box(-.8, -.22, base + .42, .8, .22, base + .5, S_WOOD)
        part.box(-.8, .17, base + .5, .8, .25, base + .95, S_WOOD)
        for side in (-.7, .7):
            part.box(side - .05, -.18, base, side + .05, .18, base + .42, S_METAL)
        self.mesh.place(part.mesh, x, y, quarter)

    def lamp(self, x, y, height=6.0, base=0.0):
        if not self.mark('lamp', x, y, base, height=height):
            return
        self.cylinder(x, y, .08, base, base + height, S_METAL, 6)
        self.box(x - .2, y - .5, base + height, x + .2, y + .5, base + height + .18, S_METAL)

    def bollard(self, x, y, base=0.0):
        if not self.mark('bollard', x, y, base, size=(.24, .24, .9)):
            return
        self.cylinder(x, y, .12, base, base + .9, S_METAL, 6)

    def trash_bin(self, x, y, base=0.0):
        if not self.mark('trash_bin', x, y, base, size=(.6, .6, .9)):
            return
        self.cylinder(x, y, .3, base, base + .9, S_METAL)

    def speaker_post(self, x, y, base=0.0):
        if not self.mark('speaker_post', x, y, base, size=(.4, .4, 1.4)):
            return
        self.boxc(x, y, .12, .12, base, base + 1.2, S_METAL)
        self.boxc(x, y, .4, .25, base + 1.2, base + 1.45, S_METAL)

    def pool_basin(self, rect, base, rim=.5, bed=-.8, level=.35):
        """Rectangular pool: a coping rim ``rim`` high round a bed sunk to
        ``bed`` (below the pad: the pad is cut round it), filled to ``level``
        when water is on. The water is always a marker."""
        x0, y0, x1, y1 = rect
        wall = .35
        self.mark('water', (x0 + x1) / 2, (y0 + y1) / 2, level, shape='rect',
                  size=(x1 - x0 - 2 * wall, y1 - y0 - 2 * wall, level - max(bed, base)))
        for bx0, by0, bx1, by1 in ((x0, y0, x1, y0 + wall), (x0, y1 - wall, x1, y1),
                                   (x0, y0 + wall, x0 + wall, y1 - wall),
                                   (x1 - wall, y0 + wall, x1, y1 - wall)):
            solids.box(self.mesh, bx0, by0, base, bx1, by1, rim, S_CONCRETE)
        floor = max(bed, base)
        solids.box(self.mesh, x0 + wall, y0 + wall, base, x1 - wall, y1 - wall, floor + .05, S_CONCRETE)
        if self.water:
            solids.box(self.mesh, x0 + wall, y0 + wall, floor + .05, x1 - wall, y1 - wall, level,
                       S_WATER)

    def tyre_stack(self, x, y, base=0.0):
        if not self.mark('tyre_stack', x, y, base, size=(.7, .7, .9)):
            return
        self.cylinder(x, y, .35, base, base + .9, S_RUBBER, 10)

    def air_pump(self, x, y, quarter=0):
        if not self.mark('air_pump', x, y, 0.0, _turn(quarter, 0.0, -1.0), size=(.5, .5, 1.4)):
            return
        self.boxc(x, y, .5, .5, 0.0, 1.4, S_METAL)

    def hydrant(self, x, y):
        if not self.mark('hydrant', x, y, 0.0, size=(.36, .36, .8)):
            return
        self.cylinder(x, y, .18, 0.0, .8, S_SIGN)

    def cart_corral(self, x, y, quarter=0):
        if not self.mark('cart_corral', x, y, 0.0, _turn(quarter, 0.0, -1.0), size=(3.2, .1, 1.0)):
            return
        self.boxc(x, y, 3.2, .1, 0.0, 1.0, S_METAL)

    def tree(self, x, y, size=1.0, base=0.0):
        """Tree spot (trees are game assets)."""
        self.mark('tree', x, y, base, scale=round(size, 3))

    def sign(self, x, y, width, height, top, quarter=0, two_posts=True, base=0.0):
        """Pylon sign: posts with a sign box on top."""
        part = Ground()
        panel_bottom = base + top - height
        if two_posts:
            for side in (-width * .3, width * .3):
                part.boxc(side, 0, .25, .25, base, panel_bottom, S_METAL)
        else:
            part.boxc(0, 0, .35, .35, base, panel_bottom, S_METAL)
        part.boxc(0, 0, width, .4, panel_bottom, base + top, S_SIGN)
        self.mesh.place(part.mesh, x, y, quarter)

    def fence_bases(self, points, base=0.0, closed=False, height=2.0):
        """Post footings along a fence line (the fence itself is a game asset)."""
        pts = list(points) + ([points[0]] if closed else [])
        self.markers.append(dict(type='fence', points=[(round(px, 3), round(py, 3)) for px, py in pts],
                                 z=round(base + .15, 3), height=height))
        placed = set()
        for a, b in zip(pts, pts[1:]):
            length = math.dist(a, b)
            if length < .3:
                continue
            count = max(1, int(math.ceil(length / 2.5)))
            for k in range(count + 1):
                px = a[0] + (b[0] - a[0]) * k / count
                py = a[1] + (b[1] - a[1]) * k / count
                key = (round(px, 3), round(py, 3))
                if key not in placed:
                    placed.add(key)
                    self.boxc(px, py, .3, .3, base, base + .15, S_CONCRETE)

    def canopy(self, rect, z0, z1, columns, column_size=.4, base=0.0, fascia=S_SIGN):
        """Flat canopy: columns up to a slab whose edge reads as a fascia band."""
        x0, y0, x1, y1 = rect
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        solids.hexahedron(self.mesh, [(x, y, z0) for x, y in corners] +
                          [(x, y, z1) for x, y in corners], S_METAL,
                          materials=(S_METAL, S_METAL, fascia, fascia, fascia, fascia))
        for cx, cy in columns:
            self.boxc(cx, cy, column_size, column_size, base, z0, S_METAL)

    def pump(self, x, y, base, quarter=0):
        if not self.mark('gas_pump', x, y, base, _turn(quarter, 0.0, -1.0), size=(.55, .9, 1.85)):
            return
        part = Ground()
        part.boxc(0, 0, .55, .9, base, base + 1.6, S_METAL)
        part.boxc(0, 0, .5, .85, base + 1.6, base + 1.85, S_SIGN)
        self.mesh.place(part.mesh, x, y, quarter)

    def dumpster(self, x, y, quarter=0):
        if not self.mark('dumpster', x, y, 0.0, _turn(quarter, 0.0, -1.0), size=(1.95, 1.15, 1.25)):
            return
        part = Ground()
        part.boxc(0, 0, 1.9, 1.1, 0.0, 1.15, S_METAL)
        part.boxc(0, 0, 1.95, 1.15, 1.15, 1.25, S_METAL)
        self.mesh.place(part.mesh, x, y, quarter)

    def table(self, x, y, umbrella=True):
        if not self.mark('table', x, y, 0.0, umbrella=umbrella):
            return
        self.cylinder(x, y, .06, 0.0, .72, S_METAL, 6)
        self.cylinder(x, y, .5, .72, .78, S_WOOD, 10)
        if umbrella:
            self.cylinder(x, y, .03, .78, 2.1, S_METAL, 6)
            solids.frustum(self.mesh, solids.circle(x, y, 1.3, 8), solids.circle(x, y, .08, 8),
                           2.1, 2.55, S_SIGN)

    def flagpole_base(self, x, y, height=9.0):
        """Plinth where a flagpole (a game asset) stands."""
        self.mark('flagpole', x, y, .3, height=height)
        self.boxc(x, y, .7, .7, 0.0, .3, S_CONCRETE)

    def booth(self, x, y, quarter=0):
        # Barrier arm reaches out along the booth's local +x.
        if not self.mark('booth', x, y, 0.0, _turn(quarter, 0.0, -1.0), size=(2.2, 2.2, 2.8),
                         barrier=_turn(quarter, 1.0, 0.0)):
            return
        part = Ground()
        part.boxc(0, 0, 1.8, 1.8, 0.0, 2.6, S_METAL)
        part.boxc(0, 0, 2.2, 2.2, 2.6, 2.8, S_METAL)
        part.box(1.0, -.08, .95, 4.2, .08, 1.08, S_SIGN)
        part.boxc(1.0 + .07, 0, .14, .3, 0.0, .95, S_METAL)
        self.mesh.place(part.mesh, x, y, quarter)

    def play_structure(self, x, y, rng, base=0.0):
        side = rng.choice((-1, 1))      # Slide side, drawn either way to keep the layout.
        if not self.mark('play_structure', x, y, base, (float(side), 0.0), size=(8.0, 2.7, 4.1)):
            return
        h = 1.5
        for dx in (-1.1, 1.1):
            for dy in (-1.1, 1.1):
                self.boxc(x + dx, y + dy, .12, .12, base, base + h, S_METAL)
        self.boxc(x, y, 2.5, 2.5, base + h, base + h + .12, S_WOOD)
        solids.frustum(self.mesh, [(x - 1.35, y - 1.35), (x + 1.35, y - 1.35), (x + 1.35, y + 1.35),
                                   (x - 1.35, y + 1.35)],
                       [(x - .05, y - .05), (x + .05, y - .05), (x + .05, y + .05), (x - .05, y + .05)],
                       base + h + 1.6, base + h + 2.6, S_SIGN)
        for dx in (-1.1, 1.1):
            for dy in (-1.1, 1.1):
                self.boxc(x + dx, y + dy, .1, .1, base + h + .12, base + h + 1.6, S_METAL)
        # Slide: a sloped slab from the deck to the ground.
        x0 = x + side * 1.25
        x1 = x + side * 4.0
        lo, hi = (x0, x1) if side > 0 else (x1, x0)
        heights = (base + h, base + .05) if side > 0 else (base + .05, base + h)
        corners = [(lo, y - .35), (hi, y - .35), (hi, y + .35), (lo, y + .35)]
        zb = [heights[0], heights[1], heights[1], heights[0]]
        solids.hexahedron(self.mesh, [(cx, cy, max(base, z - .1)) for (cx, cy), z in zip(corners, zb)] +
                          [(cx, cy, z) for (cx, cy), z in zip(corners, zb)], S_SIGN)

    def swings(self, x, y, base=0.0):
        if not self.mark('swings', x, y, base, size=(4.2, .4, 2.5)):
            return
        for dx in (-2.0, 2.0):
            self.boxc(x + dx, y, .12, .12, base, base + 2.4, S_METAL)
        self.box(x - 2.06, y - .05, base + 2.4, x + 2.06, y + .05, base + 2.5, S_METAL)
        for dx in (-.9, .9):
            self.box(x + dx - .3, y - .12, base + .45, x + dx + .3, y + .12, base + .5, S_RUBBER)

    def goal(self, x, y, width=5.0, height=2.2, quarter=0):
        if not self.mark('goal', x, y, 0.0, _turn(quarter, 0.0, 1.0), size=(width, .5, height)):
            return
        part = Ground()
        for side in (-width / 2, width / 2):
            part.boxc(side, 0, .12, .12, 0.0, height, S_METAL)
        part.box(-width / 2 + .06, -.06, height - .12, width / 2 - .06, .06, height, S_METAL)
        self.mesh.place(part.mesh, x, y, quarter)

    def stalls(self, x0, x1, y_edge, depth, facing, width=2.6, name='paint'):
        """A row of parking stalls along x; ``facing`` +1 means stalls extend toward +y."""
        count = int((x1 - x0) // width)
        if count < 1:
            return
        start = x0 + ((x1 - x0) - count * width) / 2
        for index in range(count + 1):
            x = start + index * width
            self.strip((x, y_edge + facing * .2), (x, y_edge + facing * (depth - .2)), .12,
                       S_PAINT, name)
        for index in range(count):
            # A car parked nose-in faces away from the aisle line.
            self.mark('parking_stall', start + (index + .5) * width, y_edge + facing * depth / 2,
                      0.0, (0.0, float(facing)), size=(width, depth))

    def court_lines(self, rect, material=S_PAINT, base=0.0):
        """Court outline, centre line and circle; crossing lines on separate
        layers. ``base`` lifts them onto a surface (a lawn pitch)."""
        x0, y0, x1, y1 = rect
        w = .1

        def line(a, b, layer):
            self.strip(a, b, w, material, base + LAYER[layer], z0=base)
        line((x0, y0 + w / 2), (x1, y0 + w / 2), 'paint')
        line((x0, y1 - w / 2), (x1, y1 - w / 2), 'paint')
        line((x0 + w / 2, y0 + w), (x0 + w / 2, y1 - w), 'paint_cross')
        line((x1 - w / 2, y0 + w), (x1 - w / 2, y1 - w), 'paint_cross')
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        if x1 - x0 > y1 - y0:
            line((cx, y0 + w), (cx, y1 - w), 'paint_cross')
        else:
            line((x0 + w, cy), (x1 - w, cy), 'paint_cross')
        radius = min(x1 - x0, y1 - y0) * .18
        ring = solids.circle(cx, cy, radius, 14)
        for index, (a, b) in enumerate(zip(ring, ring[1:] + ring[:1])):
            # Neighbouring segments overlap at their joints: alternate layers.
            line(a, b, 'paint_mark' if index % 2 else 'paint_mark2')

    def arrow(self, x, y, quarter=0):
        part = Ground()
        part.poly([(-.18, -1.2), (.18, -1.2), (.18, .2), (.55, .2), (0, 1.2), (-.55, .2), (-.18, .2)],
                  S_PAINT, 0.0, LAYER['paint'])
        self.mesh.place(part.mesh, x, y, quarter)


class Composer:
    """Shared state while one site is laid out."""

    def __init__(self, kind, width, depth, seed, variant, condition, damage, approach, props=True,
                 water=False, style=None):
        self.kind = kind
        self.W, self.D = width, depth
        self.seed = seed
        self.rng = random.Random((seed * 1000003) ^ zlib.crc32(kind.encode()))
        choice = self.rng.choice(VARIANTS[kind])
        self.variant = variant or STYLE_VARIANTS.get(kind, {}).get(style) or choice
        self.condition = condition
        self.damage = damage
        self.approach = approach
        self.g = Ground(props, water)
        self.buildings = []
        self.notes = []
        self.pad_material = S_ASPHALT
        self.front_material = S_ASPHALT
        self._planned = {}
        self._attached = []

    @contextmanager
    def attached(self, building):
        """Props fixed to a building (canopies, signs, roof items) go with it:
        dropped when it collapses, and where its walls broke below them."""
        saved = self.g.mesh
        data = MeshData()
        self._attached.append((building, data))
        self.g.mesh = data
        try:
            yield self.g
        finally:
            self.g.mesh = saved

    def settle_attached(self):
        from . import shell
        for building, data in self._attached:
            if not any(b is building for b in self.buildings):
                continue                       # Came down as rubble.
            if self.condition == 'INTACT':
                self.g.mesh.extend(data)
                continue
            spec = self.spec(building)
            field_ = shell.make_field(spec, building.params)
            w, d = building.params['width'], building.params['depth']
            inset = spec.t / 2
            for box, part in _split(data):
                x0, y0, z0, x1, y1, z1 = box
                lx, ly = _to_local(building, (x0 + x1) / 2, (y0 + y1) / 2)
                lx, ly = min(max(lx, inset), w - inset), min(max(ly, inset), d - inset)
                if field_.height(lx, ly) >= z0 + .05:
                    self.g.mesh.extend(part)

    @property
    def rect(self):
        return (-self.W / 2, -self.D / 2, self.W / 2, self.D / 2)

    def building(self, name, params, x, y, quarter=0, role=''):
        number = len(self.buildings)
        params = dict(params)
        params['seed'] = (self.seed * 31 + number * 7919) & 0x7FFFFFFF
        if self.damage > 0 and self.condition != 'INTACT':
            params.update(enable_damage=True, damage_amount=self.damage)
        styles.apply_condition(params, self.condition, params['floors'], params['seed'])
        if not params.get('floor_slabs', True):
            params.pop('ramps', None)   # Garage ramps need their decks.
        item = SiteBuilding(name, params, x, y, quarter, role)
        self.buildings.append(item)
        return item

    def ground(self, material=S_ASPHALT, front_material=None):
        """Pad over the whole site plus the approach to the sidewalk (built last,
        once the building footprints are known)."""
        self.pad_material = material
        self.front_material = front_material or material

    def emit_pad(self):
        """The pad drops to the buildings' ground-slab underside inside their
        footprints, so it never shares the plane of a ground floor."""
        x0, y0, x1, y1 = self.rect
        holes = [_local_rect(self, b, *self.spec(b).levels[0].rect) for b in self.buildings]
        xs = sorted({x0, x1, *(h[0] for h in holes), *(h[2] for h in holes)})
        ys = sorted({y0, y1, *(h[1] for h in holes), *(h[3] for h in holes)})
        solids.slab_solid(self.g.mesh, xs, ys, -PAD_THICKNESS, 0.0, lambda x, y: 1.0,
                          self.pad_material, holes)
        for hx0, hy0, hx1, hy1 in holes:
            solids.box(self.g.mesh, hx0, hy0, -PAD_THICKNESS, hx1, hy1, -dims.GROUND_SLAB,
                       self.pad_material)
        if self.approach > .05:
            self.g.pad((x0, y0 - self.approach, x1, y0), self.front_material)

    def to_site(self, building, x, y):
        """Building-local (x, y from its footprint corner) to site coordinates."""
        w, d = building.params['width'], building.params['depth']
        lx, ly = x - w / 2, y - d / 2
        for _ in range(building.quarter % 4):
            lx, ly = -ly, lx
        return building.x + lx, building.y + ly

    def spec(self, building):
        return self.planned(building)[0]

    def planned(self, building):
        """(spec, plan) with the planned street doors cut, as the shell builds them."""
        cached = self._planned.get(id(building))
        if cached is None:
            spec = BuildingSpec(building.params)
            plan = layouts.plan_building(spec)
            spec.build_openings(plan.doors)
            cached = self._planned[id(building)] = (spec, plan)
        return cached


def compose(kind, width, depth, seed=0, variant=None, condition='INTACT', damage=0.0,
            approach=0.0, props=True, water=False, style=None):
    """Lay out one site; see the module docstring for coordinates. With
    ``props`` off, small props (``SMALL_PROPS``) are left to the game: they
    appear only in ``Site.markers``. With ``water`` off, fountains and other
    basins are dry; their water is always a ``water`` marker. ``style`` (the
    district) picks the layout that suits it when no ``variant`` is given."""
    if kind not in KINDS:
        raise ValueError(f'Unknown site kind: {kind}')
    composer = Composer(kind, width, depth, seed, variant, condition, damage, approach, props,
                        water, style)
    if composer.variant not in VARIANTS[kind]:
        raise ValueError(f'Unknown {kind} variant: {composer.variant}')
    min_w, min_d = MIN_PAD[kind]
    if width < min_w or depth < min_d:
        composer.notes.append(f'pad {width:.0f}x{depth:.0f} below {min_w}x{min_d}; laid out as a park')
        composer.kind, composer.variant = 'PARK', 'GREEN'
        _park(composer)
    else:
        LAYOUTS[kind](composer)
    if condition == 'COLLAPSED':
        _collapse_buildings(composer)
    composer.settle_attached()
    composer.emit_pad()
    return Site(composer.kind, composer.variant, width, depth, approach, composer.g.mesh,
                composer.buildings, composer.notes, composer.g.markers)


def _collapse_buildings(c):
    """A collapsed site keeps its pad and props; its buildings are rubble heaps."""
    for building in c.buildings:
        x0, y0, x1, y1 = building.footprint
        heap = MeshData()
        rubble.collapsed_lot(heap, random.Random(building.params['seed']), x1 - x0, y1 - y0)
        # Taller buildings leave higher heaps.
        rise = min(3.0, max(1.0, building.params['floors'] * .3))
        heap.verts = [(x, y, z * rise) for x, y, z in heap.verts]
        c.g.mesh.place(heap, building.x, building.y, material_map={7: S_RUBBLE})
    c.buildings = []


def building_mesh(site_building, center=True):
    """Generate one site building and return (mesh in site coordinates, Building)."""
    from . import shell
    built = shell.build_building(site_building.params)
    mesh = built.mesh
    if center:
        mesh.translate(-site_building.params['width'] / 2, -site_building.params['depth'] / 2)
    placed = MeshData()
    placed.place(mesh, site_building.x, site_building.y, site_building.quarter)
    return placed, built


def _split(data):
    """Connected solids of a MeshData: [(bounding box, MeshData)]."""
    parent = list(range(len(data.verts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for face, _ in data.faces:
        root = find(face[0])
        for index in face[1:]:
            other = find(index)
            if other != root:
                parent[other] = root
    groups = {}
    for face, material in data.faces:
        groups.setdefault(find(face[0]), []).append((face, material))
    result = []
    for faces in groups.values():
        part = MeshData()
        remap = {}
        for face, material in faces:
            for index in face:
                if index not in remap:
                    remap[index] = part.vert(data.verts[index])
            part.faces.append((tuple(remap[i] for i in face), material))
        xs, ys, zs = zip(*part.verts)
        result.append(((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)), part))
    return result


def _ccw(points):
    area = 0.0
    for index, (x0, y0) in enumerate(points):
        x1, y1 = points[(index + 1) % len(points)]
        area += x0 * y1 - x1 * y0
    return points if area > 0 else list(reversed(points))


# -- layout helpers ------------------------------------------------------------

STRIP = 1.5   # Landscaping strip along pad edges.


def _lawn_edges(c, sides=('left', 'right', 'back'), width=STRIP, front_gap=0.0):
    """Lawn strips along pad edges (side strips run full depth, back strip between)."""
    x0, y0, x1, y1 = c.rect
    start = y0 + front_gap
    if 'left' in sides:
        c.g.layer((x0, start, x0 + width, y1), S_GRASS, 'lawn')
    if 'right' in sides:
        c.g.layer((x1 - width, start, x1, y1), S_GRASS, 'lawn')
    if 'back' in sides:
        c.g.layer((x0 + (width if 'left' in sides else 0), y1 - width,
                   x1 - (width if 'right' in sides else 0), y1), S_GRASS, 'lawn')


def _front_lawn(c, y1, gaps, inset=0.0):
    """Lawn along the front between driveway gaps [(x0, x1), ...]; ``inset``
    keeps it clear of side strips."""
    x0, y0, x1, _ = c.rect
    x0, x1 = x0 + inset, x1 - inset
    cursor = x0
    for a, b in sorted(gaps):
        if a - cursor > .6:
            c.g.layer((cursor, y0, a, y1), S_GRASS, 'lawn')
        cursor = max(cursor, b)
    if x1 - cursor > .6:
        c.g.layer((cursor, y0, x1, y1), S_GRASS, 'lawn')


def _local_rect(c, building, x0, y0, x1, y1):
    """Building-local rect (from its footprint corner) as an axis-aligned site rect."""
    corners = [c.to_site(building, x, y) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    return min(xs), min(ys), max(xs), max(ys)


def _parking_field(c, rect, angled=False, islands=True, trees=True, lights=True):
    """Fill a rect with double-loaded stall rows along x, planted islands at row ends.

    ``trees`` leaves the islands bare for the game's tree assets; otherwise
    they carry lamps."""
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = rect
    stall, aisle, gap = 5.0, 6.5, .4
    end = 2.2 if islands else 0.0
    rx0, rx1 = x0 + end, x1 - end
    if rx1 - rx0 < 6 or y1 - y0 < stall + aisle:
        return
    y = y1
    rows = []
    while y - y0 >= stall + aisle:
        rows.append((y, -1))                 # Stalls below a line at y.
        y -= stall + aisle
        if y - y0 >= stall:
            rows.append((y, 1))              # Stalls above a line at y.
            y -= stall + gap
    for edge, facing in rows:
        if angled:
            _angled_stalls(g, rx0, rx1, edge, stall, facing)
        else:
            g.stalls(rx0, rx1, edge, stall, facing)
        if islands:
            near, far = sorted((edge, edge + facing * stall))
            for ix0, ix1 in ((x0, x0 + end - .2), (x1 - end + .2, x1)):
                g.poly([(ix0, near), (ix1, near), (ix1, far), (ix0, far)], S_GRASS, 0.0, LAYER['island'])
                if trees:
                    g.tree((ix0 + ix1) / 2, (near + far) / 2, .8, base=LAYER['island'])
                elif lights:
                    g.lamp((ix0 + ix1) / 2, (near + far) / 2, 7.0, base=LAYER['island'])


def _angled_stalls(g, x0, x1, edge, depth, facing, width=2.6):
    """Stalls at 60 degrees: parallel slanted lines."""
    run = depth / math.tan(math.radians(60))
    pitch = width / math.sin(math.radians(60))
    x = x0
    length = math.hypot(run, depth)
    first = True
    while x + run + pitch <= x1:
        g.strip((x, edge + facing * .2), (x + run, edge + facing * (depth - .2)), .12, S_PAINT, 'paint')
        if not first:
            # Between this line and the last: slanted like the lines.
            g.mark('parking_stall', x - pitch / 2 + run / 2, edge + facing * depth / 2, 0.0,
                   (run / length, facing * depth / length), size=(width, depth))
        first = False
        x += pitch


def _stalls_y(g, y0, y1, x_edge, depth, facing, width=2.6):
    """A column of stalls along y; ``facing`` +1 extends toward +x."""
    count = int((y1 - y0) // width)
    start = y0 + ((y1 - y0) - count * width) / 2
    for index in range(count + 1):
        y = start + index * width
        g.strip((x_edge + facing * .2, y), (x_edge + facing * (depth - .2), y), .12, S_PAINT, 'paint')
    for index in range(count):
        g.mark('parking_stall', x_edge + facing * depth / 2, start + (index + .5) * width, 0.0,
               (float(facing), 0.0), size=(width, depth))


def _openings(c, building, side):
    """Openings on a side of every tier: (a, b, bottom, top, kind), a/b in
    building coordinates (x on front/back, y on the sides)."""
    spec = c.spec(building)
    axis = 0 if side in ('front', 'back') else 1
    result = []
    for tier in spec.tiers:
        facade = next(f for f in tier.facades if f.side == side)
        for o in facade.openings:
            a, b = sorted((facade.point(o.u0)[axis], facade.point(o.u1)[axis]))
            result.append((a, b, min(z for _, z in o.bottom), max(z for _, z in o.top), o.kind))
    return result


def _band(c, building, side, a, b):
    """Clear wall band (low, high) above the ground-storey openings in [a, b]."""
    spec = c.spec(building)
    ceiling = spec.levels[0].ceiling
    low, high = 0.0, spec.top + spec.parapet
    for oa, ob, z0, z1, _ in _openings(c, building, side):
        if min(ob, b) - max(oa, a) <= 0:
            continue
        if z0 < ceiling - 1e-6:
            low = max(low, z1)
        else:
            high = min(high, z0)
    return low, high


def _main_door(c, building, side='front'):
    """Centre and width of the widest street door on a side (nearest the middle)."""
    spec = c.spec(building)
    axis_len = building.params['width'] if side in ('front', 'back') else building.params['depth']
    doors = [(a, b) for a, b, z0, _, kind in _openings(c, building, side)
             if kind == 'door' and z0 <= 1e-6]
    if not doors:
        return None
    a, b = max(doors, key=lambda d: (round(d[1] - d[0], 2), -abs((d[0] + d[1]) / 2 - axis_len / 2)))
    return (a + b) / 2, b - a


def _solid_spot(c, building, side, width, near):
    """Centre of a stretch ``width`` long on a facade with no openings at any
    height, nearest ``near``; None when there is none."""
    best = None
    for a, b in c.spec(building).solid_spans(side):
        if b - a < width + .1:
            continue
        u = min(max(near, a + width / 2 + .05), b - width / 2 - .05)
        if best is None or abs(u - near) < abs(best - near):
            best = u
    return best


def _entrance_canopy(c, building, width=5.0, depth=2.6):
    """Canopy on two posts over the main front door, in the clear band above it."""
    door = _main_door(c, building)
    if door is None:
        return
    u, _ = door
    low, high = _band(c, building, 'front', u - width / 2, u + width / 2)
    z0 = low + .3
    if z0 + .35 > high - .05:
        return
    x0, y0, x1, y1 = _local_rect(c, building, u - width / 2, -depth, u + width / 2, .05)
    posts = {0: [(x0 + .3, y0 + .3), (x1 - .3, y0 + .3)],
             1: [(x1 - .3, y0 + .3), (x1 - .3, y1 - .3)],
             3: [(x0 + .3, y0 + .3), (x0 + .3, y1 - .3)]}.get(building.quarter % 4, [])
    with c.attached(building) as g:
        g.canopy((x0, y0, x1, y1), z0, z0 + .35, posts, column_size=.3)


def _covered_walk(c, a, b, x0, x1, y0, y1):
    """Canopy between the back of ``a`` and the facing side of ``b`` (y0 < y1),
    in the band clear of both walls' openings; posts along both edges."""
    g = c.g
    lows, highs = [], []
    for building, y in ((a, y0), (b, y1)):
        corners = [_to_local(building, x, y) for x in (x0, x1)]
        side = _side_at(building, (x0 + x1) / 2, y)
        axis = 0 if side in ('front', 'back') else 1
        lo = min(p[axis] for p in corners)
        hi = max(p[axis] for p in corners)
        low, high = _band(c, building, side, lo, hi)
        lows.append(low)
        highs.append(high)
    z0 = max(max(lows) + .3, 2.6)
    z1 = z0 + .3
    if z1 > min(highs) - .05:
        return
    g.layer((x0 + .4, y0, x1 - .4, y1), S_CONCRETE, 'path')
    with c.attached(a) as g:
        g.canopy((x0, y0 - .05, x1, y1 + .05), z0, z1,
                 [(x, y) for x in (x0 + .25, x1 - .25) for y in _spaced(y0 + .6, y1 - .6, 3.0)],
                 column_size=.2, base=LAYER['path'])


def _to_local(building, x, y):
    dx, dy = x - building.x, y - building.y
    for _ in range(building.quarter % 4):
        dx, dy = dy, -dx
    return dx + building.params['width'] / 2, dy + building.params['depth'] / 2


def _side_at(building, x, y):
    """Facade of ``building`` nearest the site point (x, y)."""
    lx, ly = _to_local(building, x, y)
    w, d = building.params['width'], building.params['depth']
    return min((abs(ly), 'front'), (abs(ly - d), 'back'), (abs(lx), 'left'), (abs(lx - w), 'right'))[1]


# -- kinds ---------------------------------------------------------------------

def _gas_station(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, front_gap=5.0)
    side = c.variant == 'SIDE'
    kw, kd = min(16.0, c.W * .42), 9.5
    ky = y1 - STRIP - .5 - kd / 2
    kx = (x0 + STRIP + 1 + kw / 2) if side else rng.uniform(-.2, .2) * (c.W - kw - 2 * STRIP) / 2
    kiosk = c.building('kiosk', designed(kw, kd, 1, 4.2, c.seed, 'SHOP', window_sides='FRONT_ONLY',
                                         ground_floor_windows='STOREFRONT_WIDE', parapet_height=1.0,
                                         door_height=2.5), kx, ky, role='kiosk')
    walk_y = ky - kd / 2 - 2.4
    g.layer((kx - kw / 2 - .8, walk_y, kx + kw / 2 + .8, ky - kd / 2), S_CONCRETE, 'walk')
    for dx in (-kw / 2 + 1.0, kw / 2 - 1.0):
        g.trash_bin(kx + dx, walk_y + .6, base=LAYER['walk'])
    fronts = [walk_y]
    if side:
        cw, cd = 6.5, min(15.0, c.D - 10)
        cx, cy = x1 - STRIP - 1 - cw / 2, y1 - STRIP - .5 - cd / 2
        c.building('car_wash', designed(cw, cd, 1, 4.6, c.seed, 'BAY', window_sides='NONE',
                                        ground_floor_windows='NONE', parapet_height=.6,
                                        doors=[('front', cw / 2, 3.4, 3.6), ('back', cw / 2, 3.4, 3.6)]),
                   cx, cy, role='car wash')
        fronts.append(cy - cd / 2)
    # Pump islands under the canopy in front of the buildings.
    area_y0, area_y1 = y0 + 3.0, min(fronts) - 1.5
    islands = max(1, min(4, int((c.W - 2 * STRIP - 8) // 7.5)))
    span = islands * 7.5
    mid = (area_y0 + area_y1) / 2
    half = min(3.2, (area_y1 - area_y0) / 2 - 1.0)
    canopy_y0 = max(y0 + .8, mid - half - 2.2)
    canopy_y1 = min(min(fronts) - .6, mid + half + 2.2)
    xs = [-span / 2 + 7.5 * (k + .5) for k in range(islands)]
    for x in xs:
        g.poly([(x - .7, mid - half), (x + .7, mid - half), (x + .7, mid + half), (x - .7, mid + half)],
               S_CONCRETE, 0.0, LAYER['island'])
        for dy in (-1.2, 1.2):
            g.pump(x, mid + dy, LAYER['island'])
        for dy in (-half + .2, half - .2):
            g.bollard(x, mid + dy, base=LAYER['island'])
    columns = [(x, mid + dy) for x in xs for dy in (-(half - .75), half - .75)] if half > 2.2 else \
        [(x, mid) for x in xs]
    g.canopy((-span / 2 - 1.5, canopy_y0, span / 2 + 1.5, canopy_y1), 4.8, 5.6,
             columns, column_size=.4, base=LAYER['island'])
    corner = x1 - 2.6 if rng.random() < .5 else x0 + 2.6
    g.sign(corner, y0 + 1.6, 2.4, 2.2, 6.5)
    # Stalls beside the kiosk and a dumpster behind it.
    if not side and x1 - STRIP - (kx + kw / 2) > 8:
        g.stalls(kx + kw / 2 + 1.5, x1 - STRIP - .5, y1 - STRIP, 5.0, -1)
    elif side:
        g.stalls(kx + kw / 2 + 1.5, cx - cw / 2 - 1.0, y1 - STRIP, 5.0, -1)
    g.air_pump(x0 + STRIP + .6, y0 + 5.5, quarter=1)
    for tx in (x0 + STRIP / 2, x1 - STRIP / 2):
        g.tree(tx, y0 + 6.5, .8, base=LAYER['lawn'])


def _fast_food(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, front_gap=4.0)
    v = c.variant
    bw, bd = (min(21.0, c.W * .6), 10.0) if v == 'DINER' else (min(17.0, c.W * .5), 12.0)
    lane = 4.0
    bx1 = x1 - STRIP - lane - .5
    by1 = y1 - STRIP - lane - .5
    bx, by = bx1 - bw / 2, by1 - bd / 2
    window_y = bd * .72
    roof = {'MANSARD': dict(roof_kind='MANSARD', roof_height=2.2, roof_overhang=.5, roof_parapet=False),
            'DINER': dict(roof_kind='HIP', roof_height=1.8, roof_overhang=.6, roof_parapet=False),
            'BOX': dict(parapet_height=1.2)}[v]
    building = c.building('restaurant', designed(
        bw, bd, 1, 4.2, c.seed, 'RESTAURANT', window_sides='FRONT_LEFT',
        ground_floor_windows='STOREFRONT_WIDE', storefront_window_height=2.4,
        doors=[('front', bw * .3, 2.0), ('back', bw * .8, 1.2)],
        extra_openings=[{'side': 'right', 'centre': window_y, 'z0': 1.0, 'width': 1.4,
                         'height': 1.2}], **roof), bx, by, role='restaurant')
    front = by - bd / 2
    # Drive-thru lane hugging the back and right walls, curbed on the outside.
    lane_x = bx1 + lane / 2
    island = LAYER['island']
    g.poly([(x0 + STRIP + 6, by1 + lane), (bx1 + lane, by1 + lane), (bx1 + lane, y1 - STRIP),
            (x0 + STRIP + 6, y1 - STRIP)], S_CONCRETE, 0.0, island)
    g.poly([(bx1 + lane, front - 1.5), (x1 - STRIP, front - 1.5), (x1 - STRIP, y1 - STRIP),
            (bx1 + lane, y1 - STRIP)], S_CONCRETE, 0.0, island)
    for t in (.3, .65):
        g.arrow(x0 + STRIP + 6 + (bx1 - x0 - STRIP - 6) * t, by1 + lane / 2, quarter=3)
    for y in (by1 - 2.0, front + 2.0):
        g.arrow(lane_x, y, quarter=2)
    g.sign(bx1 + lane + .25, by1 - 1.0, 1.6, 1.4, 2.4, quarter=1, base=island)   # Menu board.
    wx, wy = bx1, by - bd / 2 + window_y
    with c.attached(building):
        g.box(wx - .05, wy - 1.2, 2.5, wx + 1.0, wy + 1.2, 2.7, S_SIGN)            # Window hood.
    # Walk along the front and left; patio; parking.
    g.layer((bx - bw / 2 - 1.6, front - 1.8, bx1, front), S_CONCRETE, 'walk')
    g.layer((bx - bw / 2 - 1.6, front, bx - bw / 2, by1), S_CONCRETE, 'walk')
    patio = (bx - bw / 2 - 1.6 - 5.0, front - 1.8, bx - bw / 2 - 1.6, front + 4.0)
    if patio[0] > x0 + STRIP + .5:
        g.layer(patio, S_CONCRETE, 'apron')
        for k in range(2):
            g.table(patio[0] + 1.3 + k * 2.4, patio[1] + 2.6)
        parking_x1 = patio[0] - .5
    else:
        parking_x1 = bx - bw / 2 - 1.8
    if parking_x1 - (x0 + STRIP) > 5.5:
        _stalls_y(g, y0 + 5.0, by1, x0 + STRIP + .2, 5.0, 1)
    if front - y0 > 12:
        g.stalls(bx - bw / 2, bx1, front - 1.8, 5.0, -1)
    if v == 'BOX':
        # Raised sign box on the roof over the entrance.
        door = _main_door(c, building)
        u = min(max(door[0] if door else bw * .3, 2.6), bw - 2.6)
        top = c.spec(building).top
        with c.attached(building):
            g.box(bx - bw / 2 + u - 2.2, front + .45, top, bx - bw / 2 + u + 2.2, front + 3.4,
                  top + 2.6, S_SIGN)
    # Dumpster enclosure behind, before the lane starts.
    ex0, ey0 = x0 + STRIP + .4, by1 + .4
    g.box(ex0, ey0, 0.0, ex0 + 3.6, ey0 + .2, 1.8, S_CONCRETE)
    g.box(ex0, ey0 + .2, 0.0, ex0 + .2, ey0 + 3.0, 1.8, S_CONCRETE)
    g.box(ex0 + 3.4, ey0 + .2, 0.0, ex0 + 3.6, ey0 + 3.0, 1.8, S_CONCRETE)
    g.dumpster(ex0 + 1.8, ey0 + 1.4)
    g.sign(x0 + 2.2, y0 + 1.8, 3.0, 2.2, 9.0, two_posts=False)


# Real sizes (m) for school grounds: a hard court, a play pad, the longest
# classroom block, and the pitch's length limits and length:width range.
SCHOOL_COURT = (28.0, 15.0)
SCHOOL_HALF_COURT = (15.0, 14.0)
SCHOOL_PLAY = (14.0, 10.0)
SCHOOL_BLOCK_MAX = 54.0
PITCH_LENGTH = (30.0, 90.0)
PITCH_ASPECT = (1.45, 1.7)


def _school(c):
    if c.variant == 'WING' and c.D < 56:
        if c.W >= 70:
            return _school_court(c)
        c.variant = 'BAR'                    # Too small for a wing.
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    floors = 2 if c.D < 44 or rng.random() < .5 else 3
    cd = 16.0
    lawn_d = 6.0
    gym_w, gym_d = min(24.0, c.W * .32), 18.0
    wing = c.variant == 'WING' and c.D >= 56
    usable = c.W - 2 * STRIP - 2
    cy = y0 + lawn_d + cd / 2
    side = 0.0
    if not wing:
        # Classrooms and gym side by side on the street. When the strip behind
        # them is too shallow for sport, the grounds take the end of the lot
        # instead; otherwise a wide pad's spare frontage becomes a car park
        # rather than a longer block.
        behind = c.D - 2 * STRIP - 1 - lawn_d - max(cd, gym_d) - 2
        if behind < SCHOOL_COURT[1] + 3 and usable - gym_w - 1 - 26 >= 30:
            side = min(36.0, usable - gym_w - 1 - 26 - 2)
        cl = min(SCHOOL_BLOCK_MAX, usable - gym_w - 1 - (side + 2 if side else 0))
        spare = usable - gym_w - 1 - cl - (side + 2 if side else 0)
        cx = x1 - STRIP - 1 - gym_w - 1 - cl / 2
        gx, gy = x1 - STRIP - 1 - gym_w / 2, y0 + lawn_d + gym_d / 2
    else:
        cl = min(SCHOOL_BLOCK_MAX, usable)
        spare = usable - cl
        cx = x1 - STRIP - 1 - cl / 2
        gx, gy = x0 + STRIP + 1 + gym_w / 2, y1 - STRIP - 1 - gym_d / 2
    classroom = c.building('classrooms', designed(
        cl, cd, floors, 3.8, c.seed, 'SCHOOL', ground_floor_height=4.0, facade_system='RIBBON',
        window_width=2.6, window_spacing=.7, window_height=1.8, sill_height=.9,
        wall_thickness=.35, door_width=2.4, door_height=2.6), cx, cy, role='classrooms')
    c.building('gym', designed(gym_w, gym_d, 1, 7.5, c.seed, 'BAY', sill_height=4.6,
                               window_height=1.6, window_width=3.0, window_spacing=1.5,
                               parapet_height=.6, doors=[('front', gym_w / 2, 2.4)]),
               gx, gy, role='gym')
    front_back = y0 + lawn_d + max(cd, gym_d if not wing else 0)
    left = x0 + STRIP + 1 + (side + 2 if side else 0)
    if spare >= 14:
        _parking_field(c, (left - 1, y0 + 1.0, left + spare - 1.0, front_back),
                       islands=False, trees=False, lights=False)
    yard_x1 = x1 - STRIP - 1
    yard_y1 = y1 - STRIP - 1
    if wing:
        # A separate wing behind the main block, joined by a covered walk.
        ww, gap = 14.0, 4.0
        wy0 = cy + cd / 2 + gap
        wl = min(42.0, y1 - STRIP - 1 - wy0)
        if wl > 16:
            wx = x1 - STRIP - 1 - ww / 2
            annex = c.building('wing', designed(
                wl, ww, floors, 3.8, c.seed, 'SCHOOL', ground_floor_height=4.0,
                facade_system='RIBBON', window_width=2.6, window_spacing=.7, window_height=1.8,
                wall_thickness=.35), wx, wy0 + wl / 2, quarter=3, role='wing')
            _covered_walk(c, classroom, annex, wx - 1.6, wx + 1.6, cy + cd / 2, wy0)
            yard_x1 = x1 - STRIP - 1 - ww - 1.5
        # The gym stands in the back corner: the grounds lie in front of it.
        yard_y1 = gy - gym_d / 2 - 2.0
        front_back = cy + cd / 2
    # Front lawn with an entrance plaza and a flagpole base.
    door = _main_door(c, classroom)
    door_x = cx - cl / 2 + (door[0] if door else cl / 2)
    lawn_x0 = left - 1 + spare if spare >= 14 else (left - 1 if side else x0)
    g.layer((door_x - 4, y0 - c.approach, door_x + 4, y0 + lawn_d), S_CONCRETE, 'apron')
    for a, b in ((lawn_x0, door_x - 4), (door_x + 4, x1)):
        if b - a > .6:
            g.layer((a, y0, b, y0 + lawn_d - .3), S_GRASS, 'lawn')
    g.flagpole_base(door_x - 6.0, y0 + 2.5)
    for tx in _spaced(lawn_x0 + 4, x1 - 4, 9.0):
        if abs(tx - door_x) > 7:
            g.tree(tx, y0 + 2.6, .9, base=LAYER['lawn'])
    _entrance_canopy(c, classroom, width=7.0)
    fence_back = y1 - STRIP - .5
    if side:
        grounds = (x0 + STRIP + 1, y0 + 1.0, x0 + STRIP + 1 + side, y1 - STRIP - 1)
        _school_grounds(c, grounds)
        g.fence_bases([(grounds[2] + .5, y0 + .5), (grounds[0] - .5, y0 + .5),
                       (grounds[0] - .5, fence_back), (grounds[2] + .5, fence_back),
                       (grounds[2] + .5, front_back + 2.0)])
        yard = (grounds[2] + 2.5, front_back + 2.0, yard_x1, yard_y1)
        if yard[3] - yard[1] > 6:
            _play_pad(c, (yard[0], yard[1] + .5, yard[0] + SCHOOL_PLAY[0],
                          yard[1] + .5 + min(SCHOOL_PLAY[1], yard[3] - yard[1] - 1)))
        return
    yard = (x0 + STRIP + 1, front_back + 2.0, yard_x1, yard_y1)
    _school_grounds(c, yard)
    g.fence_bases([(yard[0] - .5, yard[1]), (yard[0] - .5, fence_back), (yard[2] + .5, fence_back),
                   (yard[2] + .5, yard[1])])


def _school_grounds(c, yard, play=True):
    """Hard court, play pad and pitch at real sizes inside ``yard``, laid out
    along its long side from the front; whatever is left stays open
    playground instead of stretching them to fit."""
    g = c.g
    x0, y0, x1, y1 = yard
    if min(x1 - x0, y1 - y0) < 12 or max(x1 - x0, y1 - y0) < 16:
        return
    portrait = (y1 - y0) > (x1 - x0)
    length, across = (y1 - y0, x1 - x0) if portrait else (x1 - x0, y1 - y0)

    def world(u0, v0, u1, v1):
        return (x0 + v0, y0 + u0, x0 + v1, y0 + u1) if portrait else (x0 + u0, y0 + v0, x0 + u1, y0 + v1)
    cursor = 1.5
    for size in (SCHOOL_COURT, SCHOOL_HALF_COURT):
        cl, cw = size
        if length - cursor - 1.5 >= cl and across - 3 >= cw:
            g.court_lines(world(cursor, 1.5, cursor + cl, 1.5 + cw))
            if play and across - cw - 3 - 2 >= SCHOOL_PLAY[1] + 1:
                pw, pd = SCHOOL_PLAY
                _play_pad(c, world(cursor, cw + 3.5, cursor + min(pw, cl), cw + 3.5 + pd))
                play = False
            cursor += cl + 3.0
            break
    if play and length - cursor - 1.5 >= SCHOOL_PLAY[0] + 10 and across - 3 >= SCHOOL_PLAY[1]:
        pw, pd = SCHOOL_PLAY
        _play_pad(c, world(cursor, 1.5, cursor + pw, 1.5 + pd))
        cursor += pw + 3.0
    _pitch(c, world(cursor, 1.0, length - 1.0, across - 1.0))


def _play_pad(c, pad):
    """Rubber pad with a play structure (and swings when it is long enough);
    equipment runs along the pad's longer side."""
    g, rng = c.g, c.rng
    g.layer(pad, S_RUBBER, 'rubber')
    x0, y0, x1, y1 = pad
    if x1 - x0 >= y1 - y0:
        py = (y0 + y1) / 2
        if x1 - x0 >= 9:
            g.play_structure(x0 + 4.2, py, rng, base=LAYER['rubber'])
        if x1 - x0 >= 13:
            g.swings(x1 - 3.4, py, base=LAYER['rubber'])
    elif y1 - y0 >= 9:
        g.play_structure((x0 + x1) / 2, y0 + 4.2, rng, base=LAYER['rubber'])


def _pitch(c, area):
    """The largest pitch of real proportions that fits ``area``, centred in it."""
    g = c.g
    x0, y0, x1, y1 = area
    aw, ad = x1 - x0, y1 - y0
    along_x = aw >= ad
    long_side, short_side = (aw, ad) if along_x else (ad, aw)
    lo, hi = PITCH_ASPECT
    length = min(long_side, short_side * hi, PITCH_LENGTH[1])
    width = min(short_side, length / lo)
    length = min(length, width * hi)
    if length < PITCH_LENGTH[0] or length / width < lo - 1e-6:
        return
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hx, hy = (length / 2, width / 2) if along_x else (width / 2, length / 2)
    rect = (cx - hx, cy - hy, cx + hx, cy + hy)
    g.layer(rect, S_GRASS, 'lawn')
    inner = (rect[0] + 1.0, rect[1] + 1.0, rect[2] - 1.0, rect[3] - 1.0)
    g.court_lines(inner, base=LAYER['lawn'])
    goal = min(7.3, width * .2)
    if along_x:
        g.goal(inner[0] + .4, cy, width=goal, quarter=1)
        g.goal(inner[2] - .4, cy, width=goal, quarter=3)
    else:
        g.goal(cx, inner[1] + .4, width=goal)
        g.goal(cx, inner[3] - .4, width=goal, quarter=2)


def _school_court(c):
    """Shallow wide pads: gym on the street, a classroom wing down one side
    facing the yard between them."""
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    lawn_d = 6.0
    gym_w, gym_d = min(24.0, c.W * .28), 18.0
    gx, gy = x0 + STRIP + 1 + gym_w / 2, y0 + lawn_d + gym_d / 2
    gym = c.building('gym', designed(gym_w, gym_d, 1, 7.5, c.seed, 'BAY', sill_height=4.6,
                                     window_height=1.6, window_width=3.0, window_spacing=1.5,
                                     parapet_height=.6, doors=[('front', gym_w / 2, 2.4)]),
                     gx, gy, role='gym')
    wd = 15.0
    wy0 = y0 + lawn_d
    wy1 = min(y1 - STRIP - 1, wy0 + SCHOOL_BLOCK_MAX)
    wx = x1 - STRIP - 1 - wd / 2
    wing = c.building('classrooms', designed(
        wy1 - wy0, wd, 2, 3.8, c.seed, 'SCHOOL', ground_floor_height=4.0, facade_system='RIBBON',
        window_width=2.6, window_spacing=.7, window_height=1.8, sill_height=.9,
        wall_thickness=.35, door_width=2.4, door_height=2.6), wx, (wy0 + wy1) / 2, quarter=3,
        role='classrooms')
    _entrance_canopy(c, wing, width=6.0)
    _entrance_canopy(c, gym, width=6.0)
    # Front lawn, a path to the yard gate and a flagpole base.
    gate = (gx + gym_w / 2 + 2.0 + wx - wd / 2) / 2
    _front_lawn(c, y0 + lawn_d - .3, [(gate - 2.5, gate + 2.5), (gx - 3.0, gx + 3.0)])
    g.layer((gate - 2.5, y0 - c.approach, gate + 2.5, y0 + lawn_d + 2.0), S_CONCRETE, 'apron')
    g.layer((gx - 3.0, y0 - c.approach, gx + 3.0, gy - gym_d / 2), S_CONCRETE, 'apron')
    g.flagpole_base(gate + 4.5, y0 + 2.5)
    for tx in _spaced(x0 + 4, x1 - 4, 9.0):
        if abs(tx - gate) > 5.5 and abs(tx - gx) > 5.5:
            g.tree(tx, y0 + 2.6, .9, base=LAYER['lawn'])
    # Grounds between the gym and the wing; play area behind the gym.
    yard = (gx + gym_w / 2 + 2.0, y0 + lawn_d + 2.0, wx - wd / 2 - 3.5, y1 - STRIP - 1)
    behind = (x0 + STRIP + 1, gy + gym_d / 2 + 2.0, gx + gym_w / 2, y1 - STRIP - 1)
    has_play = behind[3] - behind[1] > 7 and behind[2] - behind[0] > 12
    _school_grounds(c, yard, play=not has_play)
    if has_play:
        pw = min(SCHOOL_PLAY[0], behind[2] - behind[0])
        pd = min(SCHOOL_PLAY[1], behind[3] - behind[1])
        _play_pad(c, (behind[0], behind[1], behind[0] + pw, behind[1] + pd))
    # Fenced on the gym side and the back; the wing closes the yard.
    g.fence_bases([(yard[0] - .5, yard[1]), (yard[0] - .5, yard[3] + .5),
                   (wx - wd / 2 - .4, yard[3] + .5)])


def _hospital(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, front_gap=3.0)
    if c.variant == 'TOWER':
        wp = min(c.W - 2 * STRIP - 16, 62.0)
        dp = max(20.0, min(c.D - 2 * STRIP - 14, 36.0))
        floors = rng.randint(8, 12) if c.D >= 48 else rng.randint(6, 8)
        podium = rng.randint(2, 3)
        inset = max(2.0, min(6.0, (min(wp, dp) - 18) / 2))
        setbacks = [(podium, (inset, inset, inset, inset))]
    else:
        wp = c.W - 2 * STRIP - 16
        dp = max(18.0, min(20.0, c.D - 2 * STRIP - 12))
        floors = rng.randint(5, 7)
        setbacks = []
    mx = x0 + STRIP + 2 + wp / 2
    my = y0 + 10 + dp / 2
    main = c.building('hospital', designed(
        wp, dp, floors, 4.0, c.seed, 'OFFICE', ground_floor_height=5.0, facade_system='RIBBON',
        window_width=2.4, window_spacing=.7, window_height=1.6, parapet_height=1.1,
        skyscraper=True, setbacks=setbacks, lobby='GRAND', entrance_width=3.2,
        doors=[('front', wp / 2, 3.2, 2.8), ('right', dp * .35, 3.6, 3.4),
               ('right', dp * .65, 3.6, 3.4)]), mx, my, role='hospital')
    # Emergency: drive-under canopy at the ambulance doors, sign on its fascia.
    bays = [(a, b) for a, b, z0, _, kind in _openings(c, main, 'right') if kind == 'door' and z0 <= 1e-6]
    ex0, ex1 = mx + wp / 2, min(x1 - STRIP - .5, mx + wp / 2 + 9.0)
    if bays:
        lo, hi = min(a for a, _ in bays) - 1.5, max(b for _, b in bays) + 1.5
    else:
        lo, hi = dp * .2, dp * .8
    ey0, ey1 = my - dp / 2 + lo, my - dp / 2 + hi
    low, high = _band(c, main, 'right', lo, hi)
    z0 = max(low + .3, 3.9)
    fixed = z0 + .5 <= high - .05
    with c.attached(main):
        g.canopy((ex0 - (.05 if fixed else -.1), ey0, ex1, ey1), z0, z0 + .5,
                 [(ex1 - .4, ey0 + .4), (ex1 - .4, ey1 - .4)] + ([] if fixed else
                                                                [(ex0 + .4, ey0 + .4), (ex0 + .4, ey1 - .4)]))
        g.box(ex1 - .3, (ey0 + ey1) / 2 - 2.5, z0 + .5, ex1, (ey0 + ey1) / 2 + 2.5, z0 + 1.4, S_SIGN)
    g.layer((ex0, ey0 - 2, ex1, ey1 + 2), S_CONCRETE, 'apron')
    if c.variant == 'SLAB' and y1 - STRIP - 1 - (my + dp / 2) > 22:
        # Low outpatient block behind the slab, joined by a covered walk.
        ow = min(wp * .6, 34.0)
        od = min(16.0, y1 - STRIP - 1 - (my + dp / 2) - 6)
        ox, oy = mx - wp / 2 + ow / 2, y1 - STRIP - 1 - od / 2
        clinic = c.building('outpatient', designed(
            ow, od, 2, 3.8, c.seed, 'OFFICE', ground_floor_height=4.4, facade_system='RIBBON',
            window_width=2.4, window_spacing=.7, window_height=1.6, parapet_height=1.0),
            ox, oy, role='outpatient')
        _covered_walk(c, main, clinic, ox - 1.6, ox + 1.6, my + dp / 2, oy - od / 2)
    # Drop-off loop round a planted island in front of the entrance.
    g.poly([(mx - 7, y0 + 3.0), (mx + 7, y0 + 3.0), (mx + 7, y0 + 6.0), (mx - 7, y0 + 6.0)],
           S_GRASS, 0.0, LAYER['island'])
    for k in range(3):
        g.tree(mx - 5 + k * 5, y0 + 4.5, .8, base=LAYER['island'])
    g.layer((mx - 9, y0 + 7.0, mx + 9, my - dp / 2), S_CONCRETE, 'walk')
    # Parking beyond the emergency drive.
    if x1 - STRIP - ex1 > 14:
        _parking_field(c, (ex1 + 2.0, y0 + 2.0, x1 - STRIP, y1 - STRIP), trees=True)
    if c.condition == 'INTACT':
        spec = c.spec(main)
        tier = spec.tiers[-1]
        tx0, ty0, tx1, ty1 = tier.rect
        hx, hy = c.to_site(main, (tx0 + tx1) / 2, (ty0 + ty1) / 2)
        radius = min(6.5, (min(tx1 - tx0, ty1 - ty0) / 2) - 1.5)
        if radius > 4:
            top = spec.top
            g.cylinder(hx, hy, radius, top, top + .3, S_CONCRETE, 16)
            for a, b, w in (((hx - 1.4, hy - 2.2), (hx - 1.4, hy + 2.2), .6),
                            ((hx + 1.4, hy - 2.2), (hx + 1.4, hy + 2.2), .6)):
                g.strip(a, b, w, S_PAINT, top + .31, z0=top + .3)
            g.strip((hx - 1.1, hy), (hx + 1.1, hy), .6, S_PAINT, top + .32, z0=top + .3)


def _police(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, front_gap=7.0)
    civic = c.variant == 'CIVIC'
    # The station keeps a driveway to the back lot on its right.
    bw = min(c.W - 2 * STRIP - 8, 32.0)
    bd = min(16.0, c.D * .42)
    floors = 2 if civic else rng.randint(2, 3)
    bx = x0 + STRIP + 1 + bw / 2
    by = y0 + 7.0 + bd / 2
    station = c.building('police', designed(
        bw, bd, floors, 3.6, c.seed, 'CIVIC', ground_floor_height=4.2, wall_thickness=.45,
        window_width=1.4, window_height=1.8, window_spacing=1.4, cornice=civic,
        parapet_height=.8, doors=[('front', bw / 2, 2.2, 2.7), ('back', bw / 2, 1.6)]),
        bx, by, role='station')
    front = by - bd / 2
    door = _main_door(c, station)
    dx_ = bx - bw / 2 + (door[0] if door else bw / 2)
    drive = (x0 + STRIP + 1 + bw + .5, x1 - STRIP)
    _front_lawn(c, front - .2, [(dx_ - 3.5, dx_ + 3.5), drive])
    g.layer((dx_ - 3.5, y0 - c.approach, dx_ + 3.5, front), S_CONCRETE, 'apron')
    portico = False
    if civic:
        # Portico: four columns, a deck with a sign band, a low pediment, all
        # in the wall band between the ground-floor openings and the next sill.
        u0, u1 = dx_ - 4.5 - (bx - bw / 2), dx_ + 4.5 - (bx - bw / 2)
        low, high = _band(c, station, 'front', u0, u1)
        z0 = max(low + .5, 3.1)
        if z0 + 1.3 <= high - .1:
            portico = True
            px0, px1 = dx_ - 4.5, dx_ + 4.5
            py0 = front - 3.4
            top = min(high - .1, z0 + 2.0)
            with c.attached(station):
                g.box(px0, py0, z0, px1, front + .05, z0 + .45, S_CONCRETE)
                for k in range(4):
                    g.cylinder(px0 + .6 + k * (px1 - px0 - 1.2) / 3, py0 + .5, .32, LAYER['apron'],
                               z0, S_CONCRETE)
                g.box(px0 + .5, py0 - .05, z0 + .05, px1 - .5, py0 + .2, z0 + .4, S_SIGN)
                solids.frustum(g.mesh, [(px0, py0 + .25), (px1, py0 + .25), (px1, front + .05),
                                        (px0, front + .05)],
                               [(px0 + 1, py0 + 1.6), (px1 - 1, py0 + 1.6), (px1 - 1, py0 + 1.7),
                                (px0 + 1, py0 + 1.7)], z0 + .45, top, S_CONCRETE)
    if not portico:
        _entrance_canopy(c, station, width=6.0)
        g.sign(drive[0] - 3.0, y0 + 1.6, 2.6, 1.2, 2.4)
    for offset in (-6.5, 6.5):
        g.flagpole_base(dx_ + offset, y0 + 2.5)
    for k in range(5):
        g.bollard(dx_ - 3.0 + k * 1.5, y0 + .8, base=LAYER['apron'])
    # Fenced back lot with a sally port garage.
    lot = (x0 + STRIP + .5, by + bd / 2 + 1.0, x1 - STRIP - .5, y1 - STRIP - .5)
    if lot[3] - lot[1] > 8:
        gw, gd = 8.0, min(10.0, lot[3] - lot[1] - 1)
        c.building('sally_port', designed(gw, gd, 1, 4.5, c.seed, 'BAY', window_sides='NONE',
                                          ground_floor_windows='NONE', parapet_height=.5,
                                          doors=[('front', gw / 2, 3.4, 3.4)]),
                   lot[2] - gd / 2 - .5, lot[3] - gw / 2 - .5, quarter=3, role='sally port')
        g.stalls(lot[0] + 1.0, lot[2] - gd - 3.0, lot[3], 5.0, -1)
        g.fence_bases([(lot[0], lot[1]), (lot[0], lot[3]), (lot[2], lot[3]), (lot[2], lot[1] + 6.0)],
                      height=2.4)
    if c.condition == 'INTACT':
        spec = c.spec(station)
        ax, ay = c.to_site(station, bw * .8, bd * .7)
        g.boxc(ax, ay, .3, .3, spec.top, spec.top + 7.0, S_METAL)


def _fire_station(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=9.0)
    bays = 3 if c.variant == 'CLASSIC' else 4
    while bays > 1 and bays * 5.0 + 1.0 + 10 > c.W - 2 * STRIP:
        bays -= 1
    hw, hd = bays * 5.0 + 1.0, min(20.0, c.D - 14)
    hx, hy = x0 + STRIP + 1 + hw / 2, y0 + 9.0 + hd / 2
    centres = [.5 + 5.0 * (k + .5) for k in range(bays)]
    hall = c.building('apparatus', designed(
        hw, hd, 1, 6.0, c.seed, 'BAY', wall_thickness=.35, window_width=3.8, window_spacing=1.2,
        window_sides=('left',), sill_height=3.2, window_height=1.4, parapet_height=1.0,
        doors=[('front', u, 3.8, 4.4) for u in centres] + [('back', u, 3.8, 4.4) for u in centres]),
        hx, hy, role='apparatus bay')
    # Living quarters abut the hall (no windows or cornices on the shared wall).
    ww = min(12.0, c.W - 2 * STRIP - hw - 2)
    if ww > 6:
        c.building('quarters', designed(ww, hd, 2, 3.2, c.seed, 'CIVIC', window_width=1.4,
                                        window_spacing=1.2, window_sides=('front', 'back', 'right'),
                                        doors=[('front', ww / 2, 1.6)]),
                   hx + hw / 2 + ww / 2, hy, role='quarters')
    stalls_x1 = x1 - STRIP - 1.0
    if c.variant == 'CLASSIC' and y1 - STRIP - (hy + hd / 2) > 9.0:
        # Free-standing drill tower in the back lot.
        tx = x1 - STRIP - 1.5 - 2.25
        c.building('hose_tower', designed(4.5, 4.5, 5, 3.2, c.seed, 'NONE', window_width=.8,
                                          window_height=1.0, window_spacing=1.0,
                                          parapet_height=.4, doors=[('front', 2.25, 1.4)]),
                   tx, y1 - STRIP - 1.5 - 2.25, role='drill tower')
        stalls_x1 = tx - 2.25 - 1.5
    front = hy - hd / 2
    g.layer((hx - hw / 2, y0 - c.approach, hx + hw / 2, front), S_CONCRETE, 'apron')
    for u in centres:
        g.strip((hx - hw / 2 + u - 1.9, y0 + .5), (hx - hw / 2 + u - 1.9, front - .3), .12, S_YELLOW,
                LAYER['apron'] + .01, z0=LAYER['apron'])
    with c.attached(hall):
        g.box(hx - hw / 2 + .8, front - .3, 6.1, hx + hw / 2 - .8, front + .04, 6.9, S_SIGN)
    g.flagpole_base(x1 - STRIP - 2.0, y0 + 3.0)
    g.hydrant(x0 + STRIP + .6, y0 + 7.0)
    back = hy + hd / 2 + 1.0
    if y1 - STRIP - back > 6:
        g.stalls(hx + hw / 2 + 1.0, stalls_x1, y1 - STRIP, 5.0, -1)


def _transit_station(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .5)
    hub = c.variant == 'HUB'
    bw, bd = min(30.0, c.W * .6), 10.0
    bx, by = 0.0, y1 - STRIP - bd / 2
    hall = c.building('station', designed(
        bw, bd, 1, 5.0, c.seed, 'BAY', ground_floor_windows='STOREFRONT_WIDE',
        window_sides='FRONT_ONLY', storefront_window_height=3.2, parapet_height=1.0,
        doors=[('front', bw * .3, 2.4), ('front', bw * .7, 2.4), ('back', bw / 2, 1.6)]),
        bx, by, role='station hall')
    front = by - bd / 2
    if hub and bw / 2 + 5.5 <= c.W / 2 - STRIP:
        tower = c.building('clock_tower', designed(
            5.0, 5.0, 5, 3.5, c.seed, 'NONE', window_width=1.0, window_height=1.4,
            window_spacing=1.2, parapet_height=.6, window_sides=('front', 'back', 'right'),
            doors=[('front', 2.5, 1.4)]), bx + bw / 2 + 2.5, by + bd / 2 - 2.5, role='clock tower')
        if c.condition == 'INTACT':
            top = c.spec(tower).top
            g.boxc(tower.x, tower.y, 2.2, 2.2, top, top + 2.4, S_SIGN)          # Clock stage.
            solids.frustum(g.mesh, [(tower.x - 1.4, tower.y - 1.4), (tower.x + 1.4, tower.y - 1.4),
                                    (tower.x + 1.4, tower.y + 1.4), (tower.x - 1.4, tower.y + 1.4)],
                           [(tower.x - .1, tower.y - .1), (tower.x + .1, tower.y - .1),
                            (tower.x + .1, tower.y + .1), (tower.x - .1, tower.y + .1)],
                           top + 2.4, top + 4.2, S_METAL)
    g.layer((x0 + STRIP, front - 3.0, x1 - STRIP, front), S_CONCRETE, 'walk')
    low, high = _band(c, hall, 'front', 0.0, bw)
    z0 = max(low + .25, 3.4)
    if z0 + .3 <= high - .05:
        with c.attached(hall):
            g.canopy((bx - bw / 2, front - 2.8, bx + bw / 2, front + .05), z0, z0 + .3,
                     [(x, front - 2.4) for x in _spaced(bx - bw / 2 + 1, bx + bw / 2 - 1, 6.0)],
                     base=LAYER['walk'])
    for x in _spaced(x0 + STRIP + 6, x1 - STRIP - 6, 9.0):
        g.bench(x, front - 1.0, quarter=0, base=LAYER["walk"])
    if hub:
        # Bus island down the middle of the forecourt: shelter canopy, benches,
        # route signs; bays painted along both sides.
        iy = (y0 + front - 3.0) / 2
        ix0, ix1 = x0 + STRIP + 6, x1 - STRIP - 6
        if ix1 - ix0 > 10 and front - 3.0 - y0 > 16:
            g.poly([(ix0, iy - 1.5), (ix1, iy - 1.5), (ix1, iy + 1.5), (ix0, iy + 1.5)], S_CONCRETE,
                   0.0, LAYER['island'])
            g.canopy((ix0 + 1, iy - 1.9, ix1 - 1, iy + 1.9), 3.2, 3.45,
                     [(x, iy) for x in _spaced(ix0 + 2, ix1 - 2, 6.0)], column_size=.3,
                     base=LAYER['island'])
            for x in _spaced(ix0 + 4.5, ix1 - 4.5, 6.0):
                g.bench(x, iy - .9, quarter=0, base=LAYER['island'])
                g.bench(x, iy + .9, quarter=2, base=LAYER['island'])
            for x in (ix0 + .6, ix1 - .6):
                g.sign(x, iy, .9, .6, 2.6, two_posts=False, base=LAYER['island'])
            for side in (-1, 1):
                edge = iy + side * 4.9
                g.strip((ix0, edge), (ix1, edge), .15, S_YELLOW, 'paint')
                for x in _spaced(ix0, ix1, 13.0):
                    g.strip((x, iy + side * 1.7), (x, edge), .15, S_YELLOW, 'paint_cross')
        return
    platforms = max(1, min(3, int((front - 3.0 - y0 - 2) // 10)))
    for k in range(platforms):
        py = front - 3.0 - 7.0 - k * 10.0
        p0, p1 = x0 + STRIP + 3, x1 - STRIP - 3
        g.poly([(p0, py - 1.6), (p1, py - 1.6), (p1, py + 1.6), (p0, py + 1.6)], S_CONCRETE, 0.0,
               LAYER['platform'])
        g.canopy((p0, py - 2.0, p1, py + 2.0), 3.6, 3.9,
                 [(x, py) for x in _spaced(p0 + 1.5, p1 - 1.5, 6.0)], column_size=.35,
                 base=LAYER['platform'])
        for x in _spaced(p0 + 4.5, p1 - 4.5, 6.0):
            g.bench(x, py - .9, quarter=0, base=LAYER['platform'])
        g.sign(p0 + .6, py + 1.0, .9, .6, 2.6, two_posts=False, base=LAYER['platform'])
        for side in (-1, 1):
            edge = py + side * 1.6 + side * 3.2
            g.strip((p0 + 2, edge), (p1 - 2, edge), .15, S_YELLOW, 'paint')


def _spaced(a, b, pitch):
    count = max(1, int((b - a) // pitch))
    step = (b - a) / count
    return [a + step * k for k in range(count + 1)]


def _park(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    v = c.variant
    if v == 'PLAZA':
        c.ground(S_CONCRETE)
        cx, cy = 0.0, 0.0
        g.box(cx - 1.6, cy - 1.6, 0.0, cx + 1.6, cy + 1.6, 1.2, S_CONCRETE)
        g.box(cx - 1.0, cy - 1.0, 1.2, cx + 1.0, cy + 1.0, 2.0, S_CONCRETE)
        g.cylinder(cx, cy, .45, 2.0, 4.2, S_METAL, 8)
        for k, (dx, dy) in enumerate(((0, -5.5), (0, 5.5), (-5.5, 0), (5.5, 0))):
            g.bench(cx + dx, cy + dy, quarter=(0, 2, 3, 1)[k])
        for x in _spaced(x0 + 3, x1 - 3, 8.0):
            for y in _spaced(y0 + 3, y1 - 3, 8.0):
                if abs(x - cx) < 8 and abs(y - cy) < 8:
                    continue
                g.box(x - .9, y - .9, 0.0, x + .9, y + .9, .6, S_CONCRETE)    # Planter.
                g.tree(x, y, .85, base=.6)
        g.boxc(x1 - 4.0, y1 - 4.0, 3.0, 3.0, 0.0, 2.8, S_METAL)
        solids.frustum(g.mesh, [(x1 - 5.8, y1 - 5.8), (x1 - 2.2, y1 - 5.8), (x1 - 2.2, y1 - 2.2),
                                (x1 - 5.8, y1 - 2.2)],
                       [(x1 - 4.1, y1 - 4.1), (x1 - 3.9, y1 - 4.1), (x1 - 3.9, y1 - 3.9),
                        (x1 - 4.1, y1 - 3.9)], 2.8, 3.8, S_SIGN)
        return
    c.ground(S_GRASS, S_CONCRETE)
    if v == 'SPORTS':
        field = (x0 + 4, y0 + 5, x1 - 4, y1 - 6)
        g.court_lines(field)
        long_x = field[2] - field[0] > field[3] - field[1]
        if long_x:
            g.goal(field[0] + .6, (field[1] + field[3]) / 2, width=6.0, quarter=1)
            g.goal(field[2] - .6, (field[1] + field[3]) / 2, width=6.0, quarter=3)
        else:
            g.goal((field[0] + field[2]) / 2, field[1] + .6, width=6.0)
            g.goal((field[0] + field[2]) / 2, field[3] - .6, width=6.0, quarter=2)
        for step in range(3):
            g.box(x0 + 4, y1 - 4.5 + step * .9, 0.0, x1 - 4, y1 - 3.6 + step * .9,
                  .45 * (step + 1), S_CONCRETE)
        for x, y in ((x0 + 2, y0 + 2), (x1 - 2, y0 + 2), (x0 + 2, y1 - 2), (x1 - 2, y1 - 2)):
            g.lamp(x, y, 12.0)
        return
    if v == 'PLAYGROUND':
        inset = 3.0
        ring = (x0 + inset, y0 + inset, x1 - inset, y1 - inset)
        w = 2.2
        g.layer((ring[0], ring[1], ring[2], ring[1] + w), S_CONCRETE, 'path')
        g.layer((ring[0], ring[3] - w, ring[2], ring[3]), S_CONCRETE, 'path')
        g.layer((ring[0], ring[1] + w, ring[0] + w, ring[3] - w), S_CONCRETE, 'path')
        g.layer((ring[2] - w, ring[1] + w, ring[2], ring[3] - w), S_CONCRETE, 'path')
        g.layer((0 - w / 2, y0, 0 + w / 2, ring[1]), S_CONCRETE, 'path')
        inner = (ring[0] + w, ring[1] + w, ring[2] - w, ring[3] - w)
        iw, idp = inner[2] - inner[0], inner[3] - inner[1]
        # Rubber play pad in the middle, lawn round it with tables.
        pw, pd = min(18.0, iw - 6), min(12.0, idp - 5)
        if pw > 7 and pd > 6:
            pad = (-pw / 2, (inner[1] + inner[3]) / 2 - pd / 2, pw / 2, (inner[1] + inner[3]) / 2 + pd / 2)
            g.layer(pad, S_RUBBER, 'rubber')
            py = (pad[1] + pad[3]) / 2
            g.play_structure(pad[0] + 4.2, py, rng, base=LAYER['rubber'])
            if pw > 14:
                g.swings(pad[2] - 3.4, py, base=LAYER['rubber'])
            if pw > 17 and pd > 9:
                g.play_structure(0.0, pad[3] - 2.0, rng, base=LAYER['rubber'])
            for x in (pad[0] - 1.2, pad[2] + 1.2):
                if inner[0] + 1 < x < inner[2] - 1:
                    g.bench(x, py, quarter=3 if x < 0 else 1)
            for k, x in enumerate(_spaced(inner[0] + 2.5, inner[2] - 2.5, 7.0)):
                if pad[3] + 3.0 < inner[3] - 1.5:
                    g.table(x, inner[3] - 2.0, umbrella=k % 2 == 0)
        for x, y in ((inner[0] + 2.5, inner[1] + 2.5), (inner[2] - 2.5, inner[1] + 2.5),
                     (x0 + 1.5, y0 + 1.5), (x1 - 1.5, y0 + 1.5), (x0 + 1.5, y1 - 1.5),
                     (x1 - 1.5, y1 - 1.5)):
            g.tree(x, y, 1.0)
        return
    # GREEN: diagonal paths to a fountain plaza.
    radius = min(c.W, c.D) * .12 + 2.6
    g.poly(solids.circle(0, 0, radius, 16), S_CONCRETE, 0.0, LAYER['plaza'])
    paths = []
    for cx, cy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        length = math.hypot(cx, cy)
        ux, uy = cx / length, cy / length
        start = (ux * (radius - .3), uy * (radius - .3))
        end = (cx - ux * .1, cy - uy * .1)
        g.strip(start, end, 2.4, S_CONCRETE, 'path')
        paths.append((start, end))
    bed = g.fountain_basin(0, 0, 2.4, LAYER['plaza'], column=.3)
    g.cylinder(0, 0, .3, bed, 1.9, S_CONCRETE, 14)
    solids.frustum(g.mesh, solids.circle(0, 0, .35, 8), solids.circle(0, 0, .9, 8), 1.9, 2.3,
                   S_CONCRETE)
    for k in range(4):
        angle = math.pi / 4 + k * math.pi / 2 + math.pi / 4
        g.bench(math.cos(angle) * (radius - .9), math.sin(angle) * (radius - .9),
                quarter=round(angle / (math.pi / 2)) % 4, base=LAYER['plaza'])
    for x in _spaced(x0 + 3, x1 - 3, 7.5):
        for y in _spaced(y0 + 3, y1 - 3, 7.5):
            jx, jy = x + rng.uniform(-1.2, 1.2), y + rng.uniform(-1.2, 1.2)
            if math.hypot(jx, jy) < radius + 2.5:
                continue
            if any(_segment_distance((jx, jy), a, b) < 3.2 for a, b in paths):
                continue
            g.tree(jx, jy, rng.uniform(.8, 1.15))
    for a, b in paths:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        length = math.dist(a, b) or 1
        nx, ny = -(b[1] - a[1]) / length, (b[0] - a[0]) / length
        g.lamp(mx + nx * 1.8, my + ny * 1.8, 4.5)


def _segment_distance(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length < 1e-9 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length))
    return math.hypot(p[0] - (ax + dx * t), p[1] - (ay + dy * t))


def _parking_lot(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c)
    _front_lawn(c, y0 + 1.5, [(-4.0, 4.0)], inset=STRIP)
    _parking_field(c, (x0 + STRIP, y0 + 2.5, x1 - STRIP, y1 - STRIP),
                   angled=c.variant == 'ANGLED', trees=rng.random() < .6)
    g.booth(-5.5, y0 + 3.0)


def _parking_garage(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    floors = rng.randint(4, 6) if c.variant == 'DECKS' else rng.randint(7, 9)
    gw, gd = c.W - 4.0, c.D - 6.0
    t = .3
    run = min(3.1 * 7.5, gw - 2 * t - 6)
    width = 3.6
    ramps = []
    for level in range(floors - 1):
        if level % 2 == 0:
            rect = (t + 2.0, gd - t - .8 - width, t + 2.0 + run, gd - t - .8)
            rise = '+x'
        else:
            rect = (gw - t - 2.0 - run, t + .8, gw - t - 2.0, t + .8 + width)
            rise = '-x'
        ramps.append({'level': level, 'rect': rect, 'rise': rise})
    garage = c.building('garage', designed(
        gw, gd, floors, 3.1, c.seed, 'NONE', ground_floor_height=3.4, facade_system='OPEN',
        ground_floor_windows='OPEN', window_width=4.0, window_spacing=.6, parapet_height=1.1,
        doors=[('front', gw * .3, 3.6, 2.4), ('front', gw * .7, 3.6, 2.4)], ramps=ramps),
        0.0, y0 + 5.0 + gd / 2, role='parking garage')
    g.booth(-gw * .2 - 3.0, y0 + 2.5)
    g.sign(gw * .2, y0 + 1.0, 2.0, 1.0, 3.2)
    if c.condition == 'INTACT':
        top = c.spec(garage).top
        for lx, ly in ((gw * .25, gd * .25), (gw * .75, gd * .25), (gw * .25, gd * .75),
                       (gw * .75, gd * .75)):
            sx, sy = c.to_site(garage, lx, ly)
            g.lamp(sx, sy, 6.0, base=top)


def _strip_mall(c):
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .5)
    bd, walk = 16.0, 3.4
    back = y1 - STRIP - 4.0                     # Service lane behind.
    wing_w = 14.0
    wing_y0 = y0 + 10.0
    wing = c.variant == 'L' and back - wing_y0 >= 18 and c.W >= 60
    if c.variant == 'L' and not wing:
        c.variant = 'ROW'                    # No room for the wing.
    right = x1 - STRIP - 2
    if wing:
        # The wing runs forward along the right side, facing the lot; the
        # row stops short of the wing's walk.
        wx = right - wing_w / 2
        right = right - wing_w - walk
    bw = right - (x0 + STRIP + 2)
    bx, by = x0 + STRIP + 2 + bw / 2, back - bd / 2
    buildings = [c.building('strip', _strip_params(bw, bd, c.seed), bx, by, role='strip mall')]
    if wing:
        wl = back - wing_y0
        buildings.append(c.building('strip_wing', _strip_params(wl, wing_w, c.seed), wx,
                                    wing_y0 + wl / 2, quarter=3, role='strip mall'))
    for building in buildings:
        _arcade(c, building)
    front = by - bd / 2 - walk
    _parking_field(c, (x0 + STRIP, y0 + 2.5, right + (0 if wing else STRIP + 2) - 1.0, front - 1.0),
                   trees=rng.random() < .5)
    g.sign(x0 + 3.0, y0 + 1.5, 3.2, 4.0, 8.0)
    for k in range(2):
        g.dumpster(bx - bw / 4 + k * bw / 2, y1 - STRIP - 1.6)


def _strip_params(width, depth, seed):
    return designed(width, depth, 1, 4.8, seed, 'STRIP', ground_floor_windows='STOREFRONT_WIDE',
                    window_sides='FRONT_ONLY', storefront_window_height=3.0,
                    storefront_sill_height=.4, window_width=3.2, window_spacing=.8,
                    parapet_height=1.8)


def _arcade(c, building):
    """Covered walk along a strip front: columns on the piers, signs per unit."""
    g = c.g
    spec = c.spec(building)
    front = spec.ground_facade('front')
    w = building.params['width']
    walk = _local_rect(c, building, 0.0, -3.2, w, 0.0)
    g.layer(walk, S_CONCRETE, 'walk')
    canopy = _local_rect(c, building, 0.0, -3.0, w, .05)
    columns = [c.to_site(building, u, -2.7) for u in front.bays[1:-1]]
    plan = c.planned(building)[1]
    with c.attached(building):
        g.canopy(canopy, 3.7, 4.1, columns, column_size=.35, base=LAYER['walk'])
        for room in (plan.levels[0].rooms if plan.levels else ()):
            if room.kind != 'shop':
                continue
            u0, u1 = room.rect[0], room.rect[2]
            mid = (u0 + u1) / 2
            half = min(u1 - u0 - 1.0, 6.0) / 2
            sign = _local_rect(c, building, mid - half, -.3, mid + half, .04)
            g.box(sign[0], sign[1], 4.8 + .2, sign[2], sign[3], 4.8 + 1.5, S_SIGN)


def _shopping_plaza(c):
    """Big boxes and shop rows along the back, a parking field in front, an
    outparcel restaurant at a front corner on deep pads."""
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .5)
    xa, xb = x0 + STRIP + 2, x1 - STRIP - 2
    usable = xb - xa
    bd = min(36.0, c.D * .4)
    back = y1 - STRIP - 8.0                  # Service road and loading behind.
    by = back - bd / 2
    front = back - bd
    gap = 3.0
    walk = 3.4
    wing = None
    if c.variant == 'ANCHOR' and back - (y0 + 14.0) >= 30 and usable >= 80:
        # L plan: anchor and junior box along the back, a shop wing down the
        # right side facing the lot.
        wing_d = 16.0
        wing_len = min(60.0, back - (y0 + 14.0))
        wing = (xb - wing_d / 2, back - wing_len / 2, wing_len, wing_d)
        xb = xb - wing_d - walk - gap
        usable = xb - xa
    elif c.variant == 'ANCHOR':
        c.variant = 'PAIR'
    if c.variant == 'PAIR':
        bw = min(40.0, usable * .3)
        row = [('big_box_0', 'BOX', bw), ('shops', 'STRIP', usable - 2 * bw - 2 * gap),
               ('big_box_1', 'BOX', bw)]
    else:
        anchor = min(48.0, usable * .55)
        junior = usable - anchor - gap
        if junior > 36:
            junior, shops = 28.0, junior - 28.0 - gap
        else:
            shops = 0.0
        row = [('anchor', 'BOX', anchor), ('junior', 'BOX', junior)]
        if shops >= 12:
            row.insert(1, ('shops', 'STRIP', shops))
    cursor = xa
    boxes = []
    for name, kind, width in row:
        if kind == 'STRIP' and width < 12:
            cursor += width + gap
            continue
        if kind == 'BOX':
            boxes.append(c.building(name, _bigbox_params(width, bd, c.seed), cursor + width / 2, by,
                                    role='big box'))
        else:
            shops_row = c.building(name, _strip_params(width, 16.0, c.seed), cursor + width / 2,
                                   front + 8.0, role='strip mall')
            _arcade(c, shops_row)
        cursor += width + gap
    if wing is not None:
        wx, wy, wing_len, wing_d = wing
        _arcade(c, c.building('shop_wing', _strip_params(wing_len, wing_d, c.seed), wx, wy,
                              quarter=3, role='strip mall'))
    for building in boxes:
        _bigbox_front(c, building)
        bw_ = building.params['width']
        g.layer((building.x - bw_ / 2, building.y + bd / 2, building.x + bw_ / 2, y1 - STRIP),
                S_CONCRETE, 'apron')
    front_line = front - 4.0
    field_x0 = x0 + STRIP
    if front_line - y0 > 40 and c.W > 70:
        # Outparcel: a drive-in restaurant pad at the front-left corner.
        ow, od = 16.0, 12.0
        ox, oy = x0 + STRIP + 2 + ow / 2, y0 + 5 + od / 2
        c.building('outparcel', designed(
            ow, od, 1, 4.2, c.seed, 'RESTAURANT', window_sides=('front', 'left'),
            ground_floor_windows='STOREFRONT_WIDE', storefront_window_height=2.4,
            roof_kind='MANSARD', roof_height=1.8, roof_overhang=.4, roof_parapet=False),
            ox, oy, role='outparcel')
        g.layer((ox - ow / 2 - 1.5, oy - od / 2 - 2.0, ox + ow / 2 + 1.5, oy - od / 2), S_CONCRETE, 'walk')
        _parking_field(c, (x0 + STRIP, oy + od / 2 + 3, ox + ow / 2 + 3, front_line), trees=True)
        field_x0 = ox + ow / 2 + 3
    field_x1 = x1 - STRIP if wing is None else wing[0] - wing[3] / 2 - walk - 1.0
    _parking_field(c, (field_x0, y0 + 3.0, field_x1, front_line), trees=True)
    for x in _spaced(field_x0 + 14, field_x1 - 12, 22.0):
        g.cart_corral(x, front_line - 1.15)
    g.sign(x1 - 4.0, y0 + 1.6, 4.0, 6.0, 12.0)


def _bigbox_front(c, building):
    """Entrance portal round the main door and a sign band on the parapet."""
    with c.attached(building):
        _bigbox_portal(c, building)


def _bigbox_portal(c, building):
    g = c.g
    spec = c.spec(building)
    bw = building.params['width']
    front = building.y - building.params['depth'] / 2
    door = _main_door(c, building)
    if door is not None:
        _portal(c, building, *door)
    sign_z = spec.top + .2
    if spec.parapet > 1.0:
        g.box(building.x - bw * .3, front - .3, sign_z, building.x + bw * .3, front + .04,
              spec.top + spec.parapet - .2, S_SIGN)


def _portal(c, building, u, width):
    """Entrance portal round a front door at ``u``: two posts out of the wall
    and a sign lintel on them where the band above the door allows."""
    g = c.g
    spec = c.spec(building)
    bw = building.params['width']
    front = building.y - building.params['depth'] / 2
    left = building.x - bw / 2
    half = width / 2 + .9
    spans = spec.solid_spans('front')
    solid = all(any(a <= post - .35 and post + .35 <= b for a, b in spans)
                for post in (u - half, u + half))
    embed = .05 if solid else -.1
    low, high = _band(c, building, 'front', u - half - .3, u + half + .3)
    top = min(high - .1, max(low + 1.6, 5.6))
    for post in (u - half, u + half):
        g.box(left + post - .3, front - 3.0, 0.0, left + post + .3, front + embed, top, S_METAL)
    if top + 1.0 <= high - .05 or not solid:
        g.box(left + u - half - .3, front - 3.0, top, left + u + half + .3, front + embed, top + 1.0,
              S_SIGN)


def _bigbox_params(width, depth, seed):
    return designed(width, depth, 1, 8.5, seed, 'BIGBOX', wall_thickness=.35,
                    window_sides='FRONT_ONLY', ground_floor_windows='STOREFRONT',
                    ground_floor_window_count=2, storefront_window_height=3.2,
                    window_width=4.0, window_spacing=1.0, parapet_height=1.6,
                    doors=[('front', width / 2, 3.2, 3.0), ('back', width * .25, 3.6, 4.2),
                           ('back', width * .75, 3.6, 4.2)])


AUTO_BAY = 4.6          # Workshop bay pitch.


def _auto_repair(c):
    """Workshop with roll-up bay doors and a reception counter beside it, a
    concrete apron in front of the bays, customer stalls, tyres and an air
    pump. BAYS: the bays face the street. YARD: they face a side forecourt,
    with a fenced yard of cars waiting for parts at the back."""
    g, rng = c.g, c.rng
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .6)
    ow, od = 7.0, 7.0
    reception = designed(ow, od, 1, 3.6, c.seed, 'SHOP', window_sides=('front', 'right'),
                         ground_floor_windows='STOREFRONT', storefront_window_width=2.2,
                         doors=[('front', ow / 2, 1.6)])

    def workshop(bays, hw, hd, windows):
        centres = [.5 + AUTO_BAY * (k + .5) for k in range(bays)]
        # Window width plus spacing is the bay pitch, so each door fills one bay.
        return designed(hw, hd, 1, 5.6, c.seed, 'BAY', wall_thickness=.3, window_sides=windows,
                        sill_height=3.0, window_height=1.2, window_width=AUTO_BAY - 1.2,
                        window_spacing=1.2, parapet_height=.9,
                        doors=[('front', u, 3.8, 4.2) for u in centres] +
                              [('back', hw / 2, 1.2)])
    if c.variant == 'YARD' and c.D - 2 * STRIP - 10 >= 3 * AUTO_BAY + 1 and c.W >= 34:
        bays = 3
        while bays < 4 and (bays + 1) * AUTO_BAY + 1 <= c.D - 2 * STRIP - 12:
            bays += 1
        hw, hd = bays * AUTO_BAY + 1.0, 14.0
        hx, hy = x0 + STRIP + 1 + hd / 2, y0 + 10.0 + hw / 2
        hall = c.building('workshop', workshop(bays, hw, hd, ('back',)), hx, hy, quarter=1,
                          role='workshop')
        c.building('reception', reception, x0 + STRIP + 1 + ow / 2, y0 + 2.5 + od / 2,
                   role='reception')
        face = hx + hd / 2
        apron_x1 = min(x1 - STRIP - 1, face + 10.0)
        g.layer((face, hy - hw / 2, apron_x1, hy + hw / 2), S_CONCRETE, 'apron')
        with c.attached(hall):
            g.box(face - .04, hy - hw / 2 + .8, 4.5, face + .3, hy + hw / 2 - .8, 5.3, S_SIGN)
        # Fenced yard behind the forecourt, open toward it through a gate.
        gx0, gx1 = apron_x1 + 2.0, x1 - STRIP - 1.0
        gy0, gy1 = y0 + c.D * .45, y1 - STRIP - 1.0
        if gx1 - gx0 > 8 and gy1 - gy0 > 8:
            g.fence_bases([(gx0, gy0 + 4.5), (gx0, gy1), (gx1, gy1), (gx1, gy0), (gx0, gy0)])
            g.stalls(gx0 + 1, gx1 - 1, gy1 - .5, 5.0, -1)
            if gy1 - gy0 > 16:
                g.stalls(gx0 + 1, gx1 - 1, gy0 + .5, 5.0, 1)
        g.stalls(x0 + STRIP + ow + 3, x1 - STRIP - 1, y0 + 1.5, 5.0, 1)
        g.air_pump(face + 1.0, hy - hw / 2 - 1.0)
        for k in range(3):
            g.tyre_stack(x0 + STRIP + .8 + k * .8, hy + hw / 2 + 1.5)
        g.dumpster(x0 + STRIP + 2.0, y1 - STRIP - 1.2)
        g.sign(x1 - 3.0, y0 + 1.5, 2.6, 2.2, 6.0)
        return
    c.variant = 'BAYS'
    bays = 4
    while bays > 2 and bays * AUTO_BAY + 1.0 + ow + 2 * STRIP + 4 > c.W:
        bays -= 1
    hw = bays * AUTO_BAY + 1.0
    hd = max(10.0, min(16.0, c.D - 2 * STRIP - 9.0 - 6.0))
    hx, hy = x0 + STRIP + 2 + hw / 2, y0 + 9.0 + hd / 2
    hall = c.building('workshop', workshop(bays, hw, hd, ('left',)), hx, hy, role='workshop')
    # Reception abuts the workshop's right side (no windows on the shared wall).
    rx, ry = hx + hw / 2 + ow / 2, y0 + 9.0 + od / 2
    c.building('reception', reception, rx, ry, role='reception')
    front = hy - hd / 2
    g.layer((hx - hw / 2, y0 - c.approach, hx + hw / 2, front), S_CONCRETE, 'apron')
    for k in range(bays + 1):
        u = .5 + AUTO_BAY * k - .25
        g.strip((hx - hw / 2 + u, y0 + .5), (hx - hw / 2 + u, front - .3), .12, S_YELLOW,
                LAYER['apron'] + .01, z0=LAYER['apron'])
    with c.attached(hall):
        g.box(hx - hw / 2 + .8, front - .3, 4.5, hx + hw / 2 - .8, front + .04, 5.3, S_SIGN)
    if x1 - STRIP - 1 - (rx + ow / 2 + 1) >= 2.6:
        g.stalls(rx + ow / 2 + 1, x1 - STRIP - 1, y0 + 1.5, 5.0, 1)
    back = hy + hd / 2 + 1.0
    if y1 - STRIP - back > 6:
        g.stalls(x0 + STRIP + 1, x1 - STRIP - 1, y1 - STRIP, 5.0, -1)
    g.air_pump(hx + hw / 2 + .8, y0 + 3.0)
    for k in range(3):
        g.tyre_stack(rx + ow / 2 - .6 - k * .8, ry + od / 2 + 1.2)
    g.dumpster(hx, min(y1 - STRIP - 1.2, back + 1.0))
    g.sign(x0 + 2.5, y0 + 1.5, 2.6, 2.2, 6.0)


def _mall(c):
    """Enclosed mall: anchors at the ends, a concourse of shops between them,
    parking in front (and along the sides on wide pads), loading and a
    service road behind. DUMBBELL: two equal anchors; JUNIOR: a big anchor
    and a junior one."""
    g = c.g
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .5)
    side = 18.0 if c.W - 2 * STRIP - 2 * 18.0 >= 84 else 0.0
    bw = min(130.0, c.W - 2 * STRIP - 2 * side - 4)
    service = 9.0
    bd = max(30.0, min(40.0, c.D - 2 * STRIP - service - 30.0))
    back = y1 - STRIP - service
    bx, by = (x0 + x1) / 2, back - bd / 2
    if c.variant == 'DUMBBELL':
        anchors = (min(30.0, bw * .24),) * 2
    else:
        anchors = (min(36.0, bw * .3), min(22.0, bw * .18))
    left, right = anchors
    entrance = bw / 2
    mall = c.building('mall', designed(
        bw, bd, 1, 7.0, c.seed, 'MALL', wall_thickness=.35, window_sides='NONE',
        ground_floor_windows='NONE', parapet_height=2.0, anchors=anchors,
        doors=[('front', entrance, 6.0, 3.6), ('front', left / 2, 3.6, 3.2),
               ('front', bw - right / 2, 3.6, 3.2), ('back', left / 2, 3.6, 4.2),
               ('back', bw - right / 2, 3.6, 4.2), ('back', entrance, 1.4)]),
        bx, by, role='mall')
    spec = c.spec(mall)
    front = by - bd / 2
    with c.attached(mall):
        for door in spec.door_bays('front'):
            _portal(c, mall, spec.door_centre('front', door), door[2])
        # Name bands on the parapet over the anchors and the entrance.
        for centre, half in ((left / 2, left * .3), (bw - right / 2, right * .3), (entrance, 7.0)):
            g.box(bx - bw / 2 + centre - half, front - .3, spec.top + .2,
                  bx - bw / 2 + centre + half, front + .04, spec.top + spec.parapet - .2, S_SIGN)
    _entrance_canopy(c, mall, width=12.0, depth=4.0)
    g.layer((bx - bw / 2, front - 4.0, bx + bw / 2, front), S_CONCRETE, 'walk')
    front_line = front - 10.0
    _parking_field(c, (x0 + STRIP, y0 + 3.0, x1 - STRIP, front_line), trees=True)
    for x in _spaced(x0 + STRIP + 14, x1 - STRIP - 12, 24.0):
        g.cart_corral(x, front_line - 1.15)
    if side:
        for sx0 in (x0 + STRIP, x1 - STRIP - side):
            _parking_field(c, (sx0, front_line + 1.0, sx0 + side, back - 1.0), trees=False)
    g.layer((bx - bw / 2, back, bx + bw / 2, y1 - STRIP), S_CONCRETE, 'apron')
    for centre in (left / 2, bw - right / 2):
        g.dumpster(bx - bw / 2 + centre + 4.5, back + 2.0)
    g.sign(x1 - 5.0, y0 + 1.8, 5.0, 7.0, 14.0)


def _walkway(c, building, depth=2.4, z0=2.6, z1=2.85):
    """Covered walk along a building's front: a paved strip and a canopy on
    posts at every other pier (motel rooms are two bays wide)."""
    g = c.g
    front = c.spec(building).ground_facade('front')
    w = building.params['width']
    g.layer(_local_rect(c, building, 0.0, -depth, w, 0.0), S_CONCRETE, 'walk')
    canopy = _local_rect(c, building, 0.0, -depth, w, .05)
    posts = [c.to_site(building, u, -depth + .25) for u in front.bays[2:-1:2]]
    with c.attached(building):
        g.canopy(canopy, z0, z1, posts, column_size=.2, base=LAYER['walk'])


def _parapet_sign(c, building, share=.3):
    """Sign band on the front parapet (where it is tall enough)."""
    spec = c.spec(building)
    # Below a crowning cornice, whose face would share the sign's plane.
    top = spec.top + spec.parapet - (.5 if building.params.get('cornice') else .1)
    if top - (spec.top + .1) < .4:
        return
    bw = building.params['width']
    front = building.y - building.params['depth'] / 2
    with c.attached(building) as g:
        g.box(building.x - bw * share, front - .3, spec.top + .1, building.x + bw * share, front + .04,
              top, S_SIGN)


def _hotel(c):
    """City hotel: guest-room floors over a lobby, a dining room and offices;
    a canopy over the main door, flags, a sign on the parapet and parking
    behind. GRAND: taller and corniced; BUDGET: plainer, with more parking."""
    g = c.g
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT, S_CONCRETE)
    _lawn_edges(c, ('left', 'right'))
    grand = c.variant == 'GRAND'
    bw = min(40.0 if grand else 34.0, c.W - 2 * STRIP - 4)
    fore = 8.0
    bd = max(12.0, min(17.0, c.D - 2 * STRIP - fore - 2))
    bx, by = (x0 + x1) / 2, y0 + fore + bd / 2
    hotel = c.building('hotel', designed(
        bw, bd, 7 if grand else 4, 3.3, c.seed, 'HOTEL', ground_floor_height=4.5,
        window_width=1.4, window_spacing=1.0, window_sides='ALL',
        ground_floor_windows='STOREFRONT', storefront_window_width=2.0,
        storefront_window_height=2.6, door_width=2.4, door_height=2.8, front_door_offset=.5,
        cornice=grand, parapet_height=1.2 if grand else .8, facade_pilasters=grand,
        pilaster_style='CORNERS', pilaster_sides='FRONT'), bx, by, role='hotel')
    front = by - bd / 2
    g.layer((x0 + STRIP, y0, x1 - STRIP, front), S_CONCRETE, 'plaza')
    _entrance_canopy(c, hotel, width=7.0, depth=5.0)
    _parapet_sign(c, hotel)
    for k in (-1, 0, 1):
        g.flagpole_base(bx + bw * .3 + k * 1.6, y0 + 2.0)
    if y1 - STRIP - (by + bd / 2) > 14:
        _parking_field(c, (x0 + STRIP, by + bd / 2 + 2.0, x1 - STRIP, y1 - STRIP), trees=False)
    g.dumpster(x1 - STRIP - 2.0, by + bd / 2 + 1.0)


def _motel(c):
    """Motel: one-storey rooms behind a covered walk, each with its own door
    onto the parking; the office at one end and a tall sign by the road.
    COURT adds a wing of rooms down the side and a pool (dry unless water is
    on) in a fenced corner of the court."""
    g = c.g
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right', 'back'))
    bd, walk = 9.0, 2.4

    def rooms(width, office=True, side='left'):
        return designed(width, bd, 1, 3.2, c.seed, 'MOTEL', window_width=1.2, window_spacing=1.0,
                        window_sides='FRONT_ONLY', ground_floor_windows='REGULAR', sill_height=1.0,
                        window_height=1.3, door_height=2.2, parapet_height=.6,
                        motel_office=office, office_side=side)
    back = y1 - STRIP - 1.0
    by = back - bd / 2
    court = (c.variant == 'COURT' and c.W >= 44 and
             back - bd - walk - (y0 + 8.0) >= 16)
    if not court:
        c.variant = 'STRIP'
        bw = c.W - 2 * STRIP - 2
        row = c.building('rooms', rooms(bw), (x0 + x1) / 2, by, role='motel')
        _walkway(c, row)
        walk_front = by - bd / 2 - walk
        if walk_front - 1.0 - (y0 + 3.0) >= 11.5:
            _parking_field(c, (x0 + STRIP, y0 + 3.0, x1 - STRIP, walk_front - 1.0), trees=False)
        else:
            g.stalls(x0 + STRIP + 1, x1 - STRIP - 1, walk_front - .3, 5.0, -1)
    else:
        wing_x = x1 - STRIP - 1.0 - bd / 2
        bw = c.W - 2 * STRIP - 2 - bd - walk
        row = c.building('rooms', rooms(bw), x0 + STRIP + 1 + bw / 2, by, role='motel')
        _walkway(c, row)
        wl = back - bd - walk - (y0 + 8.0)
        wing = c.building('wing', rooms(wl, office=False), wing_x, y0 + 8.0 + wl / 2, quarter=3,
                          role='motel')
        _walkway(c, wing)
        # Pool in a fenced corner at the front of the court, parking round it.
        px0, py0 = x0 + STRIP + 2.0, y0 + 4.0
        px1, py1 = px0 + 11.0, py0 + 7.0
        g.fence_bases([(px0 - 1.0, py1 + 1.0), (px0 - 1.0, py0 - 1.0), (px1 + 1.0, py0 - 1.0),
                       (px1 + 1.0, py1 + 1.0), (px0 + 2.0, py1 + 1.0)], height=1.4)
        g.pool_basin((px0, py0, px1, py1), 0.0)
        field_x0 = px1 + 3.0
        _parking_field(c, (field_x0, y0 + 3.0, wing_x - bd / 2 - walk - 1.0, by - bd / 2 - walk - 1.0),
                       trees=False)
    g.sign(x1 - 3.5, y0 + 1.6, 3.2, 3.0, 10.0)


def _cinema(c):
    """Cinema. PALACE: a tall single-screen hall on the street, a marquee over
    the doors and a blade sign above it. MULTIPLEX: a box of screens behind a
    glazed lobby, an entrance canopy and parking in front."""
    g = c.g
    x0, y0, x1, y1 = c.rect
    if c.variant == 'PALACE':
        c.ground(S_CONCRETE)
        bw = min(26.0, c.W - 2 * STRIP - 4)
        bd = min(36.0, c.D - 2 * STRIP - 5)
        bx, by = (x0 + x1) / 2, y0 + 3.0 + bd / 2
        hall = c.building('cinema', designed(
            bw, bd, 1, 10.0, c.seed, 'CINEMA', cinema='PALACE', wall_thickness=.4,
            window_sides='FRONT_ONLY', ground_floor_windows='STOREFRONT',
            storefront_window_height=2.4, window_width=2.0, window_spacing=1.2, cornice=True,
            parapet_height=1.4, facade_pilasters=True, pilaster_style='CORNERS',
            pilaster_sides='FRONT'), bx, by, role='cinema')
        front = by - bd / 2
        marquee = min(7.0, bw / 2 - 1.5)
        with c.attached(hall):
            g.box(bx - marquee, front - 3.2, 4.0, bx + marquee, front + .05, 5.3, S_SIGN)
            g.box(bx + marquee - .9, front - 1.4, 5.8, bx + marquee - .4, front + .05, 10.6, S_SIGN)
        g.layer((x0 + STRIP, y0, x1 - STRIP, front), S_CONCRETE, 'plaza')
        if y1 - STRIP - (by + bd / 2) > 12:
            _parking_field(c, (x0 + STRIP, by + bd / 2 + 1.5, x1 - STRIP, y1 - STRIP), trees=False)
        return
    if c.D - 2 * STRIP < 42 or c.W < 40:
        c.variant = 'PALACE'               # No room for a box of screens and its parking.
        _cinema(c)
        return
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right'), front_gap=c.D * .5)
    bw = min(64.0, c.W - 2 * STRIP - 4)
    bd = max(26.0, min(40.0, c.D - 2 * STRIP - 16))
    back = y1 - STRIP - 2.0
    bx, by = (x0 + x1) / 2, back - bd / 2
    box = c.building('cinema', designed(
        bw, bd, 1, 9.0, c.seed, 'CINEMA', cinema='MULTIPLEX', wall_thickness=.35,
        window_sides='FRONT_ONLY', ground_floor_windows='STOREFRONT_WIDE',
        storefront_window_height=3.2, window_width=3.2, window_spacing=1.0, parapet_height=1.6),
        bx, by, role='cinema')
    front = by - bd / 2
    _entrance_canopy(c, box, width=10.0, depth=4.0)
    _parapet_sign(c, box, .25)
    g.layer((bx - bw / 2, front - 4.0, bx + bw / 2, front), S_CONCRETE, 'walk')
    _parking_field(c, (x0 + STRIP, y0 + 3.0, x1 - STRIP, front - 5.0), trees=True)
    g.sign(x1 - 4.0, y0 + 1.6, 4.0, 5.0, 11.0)


def _screen_part(width, height):
    """Drive-in screen facing -y at the origin: a panel on legs, braced behind."""
    part = Ground()
    base = 3.0
    part.box(-width / 2, -.3, base, width / 2, .3, base + height, S_CONCRETE)
    for k in range(5):
        x = -width / 2 + .6 + (width - 1.2) * k / 4
        part.boxc(x, 0, .5, .5, 0.0, base, S_METAL)
        part.boxc(x, 1.6, .4, .4, 0.0, base + height - .5, S_METAL)
    return part


def _drive_in(c):
    """Drive-in cinema: a big screen at the far end (TWIN: two side by side),
    curved rows of stalls facing it with speaker posts between the cars, a
    concession stand in a back corner, a ticket booth at the gate and a fence
    round the lot."""
    g = c.g
    x0, y0, x1, y1 = c.rect
    c.ground(S_ASPHALT)
    _lawn_edges(c, ('left', 'right', 'back'))
    deep = c.D >= 60
    m = STRIP + 2.0
    if deep:
        # Screen at the back facing the street; u runs along x, v toward the street.
        sx, sy = (x0 + x1) / 2, y1 - m - 1.0
        length, half = sy - (y0 + m + 8.0), (x1 - x0) / 2 - m

        def at(u, v):
            return sx + u, sy - v

        def heading(du, dv):
            return du, -dv
        quarter = 0
    else:
        # Screen at the left end facing along the lot; u runs along y.
        sx, sy = x0 + m + 1.0, (y0 + y1) / 2 + 2.0
        length, half = x1 - m - sx, (y1 - y0) / 2 - m - 2.0

        def at(u, v):
            return sx + v, sy + u

        def heading(du, dv):
            return dv, du
        quarter = 1
    # Concession stand in a back corner, away from the gate: beside the screen
    # in a deep lot (the screens keep clear of it), at the far end of the
    # field in a shallow one (the screen fills its own end).
    kw, kd = 14.0, 9.0
    if deep:
        kx, ky, kq = x0 + m + 1.0 + kw / 2, y1 - m - 1.0 - kd / 2, 0
        low = kx + kw / 2 + 3.0 - sx      # Screens keep 3 m from it.
    else:
        kx, ky, kq = x1 - m - 1.0 - kd / 2, y1 - m - 1.0 - kw / 2, 3
        low = -half
    extent = (half - low) / 4             # Half the field each twin screen serves.
    twin = c.variant == 'TWIN' and extent >= 13
    if c.variant == 'TWIN' and not twin:
        c.variant = 'SINGLE'
    if twin:
        screens = [(low + extent, extent - 1.5), (low + 3 * extent, extent - 1.5)]
        width = min(26.0, 1.8 * extent)
    else:
        screens = [(0.0, half)]
        width = min(26.0, half * 1.2, 2 * min(half, -low))
    for us, _ in screens:
        x, y = at(us, 0.0)
        g.mesh.place(_screen_part(width, 10.0).mesh, x, y, quarter)
    kiosk = c.building('concession', designed(
        kw, kd, 1, 3.8, c.seed, 'RESTAURANT', window_sides=('front', 'left', 'right'),
        ground_floor_windows='STOREFRONT', storefront_window_height=2.2), kx, ky, quarter=kq,
        role='concession')
    kx0, ky0, kx1, ky1 = kiosk.footprint
    for us, reach in screens:
        radius = 14.0
        while radius + 3.0 <= length:
            count = int(radius * math.radians(90) / 3.0)
            for j in range(count):
                theta = math.radians(-45) + math.radians(90) * (j + .5) / count
                u = us + radius * math.sin(theta)
                v = -4.0 + radius * math.cos(theta)
                if abs(u - us) > reach - 2.5 or v < 6.0 or v > length - 2.0:
                    continue
                x, y = at(u, v)
                if kx0 - 4 < x < kx1 + 4 and ky0 - 4 < y < ky1 + 4:
                    continue
                fx, fy = heading(-math.sin(theta), -math.cos(theta))
                g.mark('parking_stall', x, y, 0.0, (round(fx, 6), round(fy, 6)), size=(3.0, 5.0))
                if j % 2 == 0:
                    side = theta - math.radians(90) / count / 2
                    px, py = at(us + (radius - 2.9) * math.sin(side), -4.0 + (radius - 2.9) * math.cos(side))
                    g.speaker_post(px, py)
            radius += 9.0
    # Gate, ticket booth and fence (posts only; the fence is a game asset).
    gx = x1 - m - 6.0
    g.layer((gx - 3.0, y0 - c.approach, gx + 3.0, y0 + m), S_CONCRETE, 'apron')
    # Beside the way in, facing into the lot, its barrier across the inbound lane.
    g.booth(gx + 4.5, y0 + m + 2.0, quarter=2)
    fx0, fy0, fx1, fy1 = x0 + STRIP + .6, y0 + STRIP + .6, x1 - STRIP - .6, y1 - STRIP - .6
    g.fence_bases([(gx + 3.5, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1), (fx0, fy0), (gx - 3.5, fy0)],
                  height=2.4)
    g.sign(x0 + 4.0, y0 + 1.6, 6.0, 4.0, 10.0)


LAYOUTS = {
    'GAS_STATION': _gas_station,
    'FAST_FOOD': _fast_food,
    'SCHOOL': _school,
    'HOSPITAL': _hospital,
    'POLICE': _police,
    'FIRE_STATION': _fire_station,
    'TRANSIT_STATION': _transit_station,
    'PARK': _park,
    'PARKING_LOT': _parking_lot,
    'PARKING_GARAGE': _parking_garage,
    'STRIP_MALL': _strip_mall,
    'SHOPPING_PLAZA': _shopping_plaza,
    'AUTO_REPAIR': _auto_repair,
    'MALL': _mall,
    'HOTEL': _hotel,
    'MOTEL': _motel,
    'CINEMA': _cinema,
    'DRIVE_IN': _drive_in,
}


def shelter(variant='SHELTER'):
    """Transit stop on a footway, in local coordinates: the road side is -y."""
    g = Ground()
    if variant == 'STOP':
        g.sign(1.2, -.4, .8, .5, 2.8, two_posts=False)
        g.bench(-.6, 0.0)
        return g.mesh
    for x in (-1.9, 1.9):
        g.boxc(x, .45, .1, .1, 0.0, 2.5, S_METAL)
    g.box(-1.85, .4, .1, 1.85, .48, 2.3, S_GLASS)
    g.box(-2.1, -.7, 2.5, 2.1, .7, 2.62, S_METAL)
    for x in (-1.9, 1.9):
        g.boxc(x, -.55, .1, .1, 0.0, 2.5, S_METAL)
    g.bench(0.0, .1)
    g.sign(2.6, -.5, .7, .45, 2.7, two_posts=False)
    return g.mesh
