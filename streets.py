# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure street surface tessellation for curved road paths.

The network is described by a scalar field ``A(p)``: the smallest distance from
``p`` to any centreline segment minus that road's half width. Carriageway is
``A <= 0``, footway is ``0 < A <= sidewalk_width``.

Both regions are extracted per sample cell by clipping its two triangles against
those two iso-levels. Interpolation is linear per triangle, so every crossing
vertex is shared by the neighbouring cell and by the adjacent region: no boolean
geometry, no cracks and no overlapping faces, while junctions become the natural
union of the curved corridors. Road corners are fillets, so their bend radius is
explicit in the centreline rather than an artefact of the grid.
"""
from collections import defaultdict
import math

SAMPLE = 1.5          # Metres per surface sample cell.
GROUND_CELL = 12.0    # Metres per terrain cell; a multiple of SAMPLE.
CURB_BOTTOM = -0.2
GROUND_Z = -0.02
FIELD_CELL = 40.0     # Metres per spatial-hash cell for centreline segments.
# On terrain: a finer ground grid (its error against the smooth road-level
# surface stays a few centimetres), set lower so it never shows through the
# asphalt, cut back round every building pad and held up under the curbs.
GROUND_CELL_TERRAIN = 3.0
GROUND_Z_TERRAIN = -0.06
CURB_BOTTOM_TERRAIN = -2.5   # Curb skirts on terrain: walls retaining the footway above lower pads.
PAD_CLEAR = .1        # Ground stays this far under a pad's top.
PAD_CUT_SLOPE = .6    # Cut slope back up from a pad to the natural ground.
PAD_FILL_SLOPE = .4   # Fill slope down from a pad to the natural ground.
PAD_SHOULDER = 1.5    # Level ground round a pad before its cut or fill slope.
PAD_REACH = 20.0      # How far round a pad its cut and fill slopes are looked for.
PAD_CELL = 24.0       # Metres per spatial-hash cell for pads.
# Terraced cities: stairs up a terrace's face, and the walls.
STAIR_RISE = .17      # Most a step rises.
STAIR_LANDING = 3.0   # Landing under each street's footway.
STAIR_INSET = .02     # Steps stand this far inside the stair's walls.
STAIR_BASE = .5       # Steps are solid this far below the stair's foot.
# Retaining walls stand back from the footway they face by a verge
# WALL_GAP wide, at the footway's level less CURB_DROP. Ground up to the
# first RETAIN figure above the verge slopes up to it across the verge; past
# the second it stands behind a wall; between, partly.
WALL_GAP = 2.5
CURB_DROP = .1
RETAIN = (1.0, 2.0)
PARAPET = (1.5, .3, 1.0)   # Walls dropping more than this get a parapet this thick and high.
# Ramps high enough over the ground run on a viaduct: a deck DECK_DEPTH deep
# with VIADUCT_CLEARANCE under it at least, for VIADUCT_SPAN or more, on
# piers about PIER_SPACING apart (the first PIER_END from each end).
DECK_DEPTH = 1.2
ABUTMENT_DROP = .02        # An abutment's wall stops this far under the road.
RAMP_REACH = 12.0          # A ramp's route stays this near its lattice edges.
VIADUCT_CLEARANCE = 4.5
VIADUCT_SPAN = 20.0
PIER_SPACING = 18.0
PIER_END = 6.0
PIER_SIZE = (1.4, 2.2)     # Along the deck, across it.
PIER_CAP = (1.8, 1.0)      # Cap beam: along the deck, depth.
OUTER_STUB = 60.0     # Field segment past the map edge so a highway runs straight out.
OUTER_CUT = 40.0      # The street mesh hands over to the outer road this far out.
OUTER_RAMP = 2.0      # Footways ramp down to the shoulders over this length.
OUTER_SOLID_ROW = 30.0  # Metres between cross-sections of an outer road...
OUTER_FADE_ROW = 4.0    # ...and where it breaks up.


def junctions(plan):
    result = {}
    for road in plan.roads:
        for node in (road.a, road.b):
            result[node] = max(result.get(node, 0), road.width / 2)
    return result


def flush_junctions(plan):
    """Junctions whose footways come down flush with the carriageway: every
    street node but a ramp's own raised junctions (no street crosses there)."""
    nodes = junctions(plan)
    for ramp in (getattr(plan, 'terraces', None) or {}).get('ramps', ()):
        for node in ramp['nodes'][1:-1]:
            nodes.pop(tuple(node), None)
    return nodes


def pavement_height(plan, x, y, nodes=None):
    """Flush corners with a 2 m transition to the raised footway on each approach."""
    size = plan.settings.block_size
    nodes = flush_junctions(plan) if nodes is None else nodes
    node = (round(x / size), round(y / size))
    if node not in nodes:
        return plan.settings.curb_height
    distance = max(abs(x - node[0] * size), abs(y - node[1] * size))
    ramp_start = nodes[node] + plan.settings.sidewalk_width
    return plan.settings.curb_height * min(1, max(0, (distance - ramp_start) / 2))


def lot_approach(lot, plan):
    """Distance from a lot's centre, along its facing, to the back of the
    footway it fronts (a turning circle's for a house round one)."""
    size = plan.settings.block_size
    if lot.bulb:
        radius = next(b['radius'] for b in plan.culdesacs if tuple(b['node']) == tuple(lot.bulb))
        centre = (lot.bulb[0] * size, lot.bulb[1] * size)
        return math.dist(centre, lot.center) - radius - plan.settings.sidewalk_width
    road = next(r for r in plan.roads if (r.a, r.b) == lot.frontage)
    mid = ((road.a[0] + road.b[0]) * size / 2, (road.a[1] + road.b[1]) * size / 2)
    facing = (math.sin(lot.rotation), -math.cos(lot.rotation))
    distance = sum((mid[i] - lot.center[i]) * facing[i] for i in range(2))
    return distance - road.width / 2 - plan.settings.sidewalk_width


def lot_yard(lot, plan):
    """World corners of a lot's foundation: the building and its approach
    out to the footway."""
    end = lot_approach(lot, plan)
    depth = lot.depth / 2 + end
    c, s = math.cos(lot.rotation), math.sin(lot.rotation)
    shift = (lot.depth / 2 - end) / 2          # Local y of the combined centre.
    centre = (lot.center[0] - shift * s, lot.center[1] + shift * c)
    return footprint(centre, lot.width, depth, lot.rotation)


def frontage_rectangle(lot, plan):
    """World XY foundation/approach envelope, used to cut the underlying terrain."""
    roads = {(r.a, r.b): r for r in plan.roads}
    road = roads[lot.frontage]
    size = plan.settings.block_size
    mid = ((road.a[0] + road.b[0]) * size / 2, (road.a[1] + road.b[1]) * size / 2)
    sin, cos = math.sin(lot.rotation), math.cos(lot.rotation)
    distance = (mid[0] - lot.center[0]) * sin - (mid[1] - lot.center[1]) * cos
    end = distance - road.width / 2 - plan.settings.sidewalk_width
    corners = [(lot.center[0] + x * cos - y * sin, lot.center[1] + x * sin + y * cos)
               for x in (-lot.width / 2, lot.width / 2) for y in (-end, lot.depth / 2)]
    return (min(p[0] for p in corners), min(p[1] for p in corners),
            max(p[0] for p in corners), max(p[1] for p in corners))


def _polyline_pieces(points, spans):
    """The parts of a polyline outside the arc-length intervals ``spans``."""
    pieces, current, along = [], [tuple(points[0])], 0.0
    cuts = sorted(spans)

    def inside(s):
        return any(s0 < s < s1 for s0, s1 in cuts)
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        marks = sorted({0.0, length} | {c - along for s0, s1 in cuts for c in (s0, s1)
                                        if 0 < c - along < length})
        for m0, m1 in zip(marks, marks[1:]):
            t0, t1 = m0 / length, m1 / length
            p0 = (a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0)
            p1 = (a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1)
            if inside(along + (m0 + m1) / 2):
                if len(current) > 1:
                    pieces.append(current)
                current = [p1]
            else:
                if not current:
                    current = [p0]
                current.append(p1)
        along += length
    if len(current) > 1:
        pieces.append(current)
    return pieces


def _point_at(points, target):
    along = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length and target <= along + length:
            t = (target - along) / length
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        along += length
    return tuple(points[-1])


def _segments(plan, cut=None):
    """Field rows for every street; ``cut`` ({path id: spans}) leaves the
    viaducts out (the ground runs on under them). The street then ends
    square under each end of the deck (a flat-ended row), so the abutment
    there is a flat wall."""
    rows = []
    walk = plan.settings.sidewalk_width
    for path in plan.paths:
        half = path['width'] / 2
        spans = cut.get(path['id']) if cut else None
        if not spans:
            for a, b in zip(path['points'], path['points'][1:]):
                rows.append((a[0], a[1], b[0], b[1], half))
            continue
        reach = half + walk
        total = sum(math.dist(a, b) for a, b in zip(path['points'], path['points'][1:]))
        trimmed = [(max(0.0, s0 - reach), min(total, s1 + reach)) for s0, s1 in spans]
        for points in _polyline_pieces(path['points'], trimmed):
            for a, b in zip(points, points[1:]):
                rows.append((a[0], a[1], b[0], b[1], half))
        for s0, s1 in spans:
            for a, b in ((s0 - reach - 1.0, s0 - walk), (s1 + walk, s1 + reach + 1.0)):
                if b > a and a >= 0 and b <= total:
                    pa, pb = _point_at(path['points'], a), _point_at(path['points'], b)
                    rows.append((pa[0], pa[1], pb[0], pb[1], half, 'square'))
    for road in getattr(plan, 'outer_roads', ()):
        if road.get('deck'):
            continue
        (x, y), (dx, dy) = road['start'], road['direction']
        rows.append((x, y, x + dx * OUTER_STUB, y + dy * OUTER_STUB, road['width'] / 2))
    freeway = getattr(plan, 'freeway', None) or {}
    for ramp in freeway.get('ramps', ()):
        # A ramp's run at grade, from the cross street to its foot (square
        # there, where the ramp's deck takes over).
        (x0, y0), (x1, y1) = ramp['tail']
        rows.append((x0, y0, x1, y1, freeway['ramp_half'], 'square'))
    size = plan.settings.block_size
    for bulb in getattr(plan, 'culdesacs', ()):
        # A turning circle: a zero-length segment as wide as the circle.
        x, y = bulb['node'][0] * size, bulb['node'][1] * size
        rows.append((x, y, x, y, bulb['radius']))
    return rows


class _Outer:
    """An outer road in its own frame: ``along`` from the city edge, ``lateral``
    to the left of the direction of travel."""

    def __init__(self, plan, road):
        self.road = road
        (self.x, self.y), (self.dx, self.dy) = road['start'], road['direction']
        self.axis = 0 if abs(self.dx) > .5 else 1
        self.sign = (self.dx, self.dy)[self.axis]
        self.half = road['width'] / 2
        self.band = self.half + plan.settings.sidewalk_width
        start = (self.x, self.y)[self.axis]
        centre = (self.y, self.x)[self.axis]
        # The street mesh carries the highway, footways and all, OUTER_CUT
        # metres past the end node (clear of any junction there) and stops on a
        # sample-grid line; the outer road takes over across its band.
        handover = start + self.sign * OUTER_CUT
        self.cut = (math.ceil(handover / SAMPLE - 1e-9) if self.sign > 0
                    else math.floor(handover / SAMPLE + 1e-9)) * SAMPLE
        # Coming down off a raised highway's deck: no street mesh to meet.
        self.deck = bool(road.get('deck'))
        if self.deck:
            self.cut = start
        self.lo = math.floor((centre - self.band) / SAMPLE + 1e-9) * SAMPLE
        self.hi = math.ceil((centre + self.band) / SAMPLE - 1e-9) * SAMPLE
        self.centre = centre
        self.start = start
        self.end = start + self.sign * road['length']

    def drops(self, x0, y0):
        """True for street-mesh cells the outer road replaces."""
        if self.deck:
            return False
        a, b = (x0, y0) if self.axis == 0 else (y0, x0)
        beyond = a >= self.cut - 1e-9 if self.sign > 0 else a + SAMPLE <= self.cut + 1e-9
        return beyond and self.lo - 1e-9 <= b and b + SAMPLE <= self.hi + 1e-9

    def world(self, along, lateral, z):
        """Point at ``along`` metres past the cut and absolute ``lateral`` coordinate."""
        a = self.cut + self.sign * along
        return (a, lateral, z) if self.axis == 0 else (lateral, a, z)

    @property
    def length(self):
        return abs(self.end - self.cut)

    def rect(self, start):
        """Axis-aligned world rectangle of the road band from ``start`` (absolute)."""
        a0, a1 = sorted((start, self.end))
        b0, b1 = self.centre - self.band, self.centre + self.band
        return (a0, b0, a1, b1) if self.axis == 0 else (b0, a0, b1, a1)


def outer_roads(plan):
    return [_Outer(plan, road) for road in getattr(plan, 'outer_roads', ())]


def _hash01(seed, i, j):
    h = (i * 374761393 + j * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0x1000000)


def _value_noise(seed, x, y, scale):
    gx, gy = x / scale, y / scale
    i, j = math.floor(gx), math.floor(gy)
    fx, fy = gx - i, gy - j
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash01(seed, i, j), _hash01(seed, i + 1, j)
    c, d = _hash01(seed, i, j + 1), _hash01(seed, i + 1, j + 1)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def outer_asphalt(outer, seed, along, lateral):
    """Whether the road surface survives here; it breaks up over the fade,
    from the edges inward, into patches that thin out to nothing."""
    fade = outer.road['fade']
    start = outer.length - fade
    if along <= start or fade <= 0:
        return True
    f = (along - start) / fade
    if f >= .97:
        return False
    x, y, _ = outer.world(along, lateral, 0.0)
    n = .7 * _value_noise(seed, x, y, 16.0) + .3 * _value_noise(seed + 1, x, y, 5.0)
    edge = min(1.0, abs(lateral - outer.centre) / outer.band) ** 2
    return n - .25 * edge > .15 + .7 * f


def _square_distance(px, py, row):
    """Signed distance from a point to a flat-ended row's strip (a box)."""
    x0, y0, x1, y1, half = row[:5]
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    along = (px - x0) * ux + (py - y0) * uy
    across = abs((px - x0) * uy - (py - y0) * ux)
    ex, ey = abs(along - length / 2) - length / 2, across - half
    return math.hypot(max(ex, 0.0), max(ey, 0.0)) + min(max(ex, ey), 0.0)


def _distance(px, py, segment):
    x, y, qx, qy, _ = segment
    dx, dy = qx - x, qy - y
    length = dx * dx + dy * dy
    if length:
        t = max(0.0, min(1.0, ((px - x) * dx + (py - y) * dy) / length))
    else:
        t = 0.0
    return math.hypot(px - x - dx * t, py - y - dy * t)


class Field:
    """Distance to the carriageway, indexed so sample points touch few segments."""

    def __init__(self, plan, extra=(), cut=None):
        self.segments = _segments(plan, cut) + list(extra)
        self.walk = plan.settings.sidewalk_width
        self.grid = defaultdict(list)
        for segment in self.segments:
            x0, y0, x1, y1, half = segment[:5]
            padding = half + self.walk + 2
            for i in range(math.floor((min(x0, x1) - padding) / FIELD_CELL),
                           math.floor((max(x0, x1) + padding) / FIELD_CELL) + 1):
                for j in range(math.floor((min(y0, y1) - padding) / FIELD_CELL),
                               math.floor((max(y0, y1) + padding) / FIELD_CELL) + 1):
                    self.grid[i, j].append(segment)
        self.cache = {}

    def value(self, x, y):
        index = (round(x, 8), round(y, 8))
        cached = self.cache.get(index)
        if cached is not None:
            return cached
        i, j = math.floor(x / FIELD_CELL), math.floor(y / FIELD_CELL)
        best = math.inf
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for segment in self.grid.get((i + di, j + dj), ()):
                    candidate = (_square_distance(x, y, segment) if len(segment) > 5 else
                                 _distance(x, y, segment) - segment[4])
                    if candidate < best:
                        best = candidate
        self.cache[index] = best
        return best

    def covered_cells(self):
        """Sample cells wholly inside the carriageway or footway envelope."""
        covered = set()
        for i, j in self.active_cells():
            if all(self.value((i + di) * SAMPLE, (j + dj) * SAMPLE) <= self.walk
                   for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1))):
                covered.add((i, j))
        return covered

    def active_cells(self):
        cells = set()
        for x0, y0, x1, y1, half, *_ in self.segments:
            padding = half + self.walk + 2 + SAMPLE
            for i in range(math.floor((min(x0, x1) - padding) / SAMPLE),
                           math.floor((max(x0, x1) + padding) / SAMPLE) + 1):
                for j in range(math.floor((min(y0, y1) - padding) / SAMPLE),
                               math.floor((max(y0, y1) + padding) / SAMPLE) + 1):
                    cells.add((i, j))
        return cells


def _clip(polygon, threshold, keep_below):
    """Sutherland-Hodgman clip of a triangle against one iso-level.

    Vertices are ``(x, y, field)``; crossings are inserted at exactly the
    threshold so the shared iso-edge can be recognised afterwards.
    """
    result = []
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        inside = current[2] <= threshold if keep_below else current[2] >= threshold
        next_inside = following[2] <= threshold if keep_below else following[2] >= threshold
        if inside:
            result.append(current)
        if inside != next_inside:
            span = following[2] - current[2]
            factor = 0.0 if span == 0 else (threshold - current[2]) / span
            result.append((current[0] + (following[0] - current[0]) * factor,
                           current[1] + (following[1] - current[1]) * factor,
                           threshold))
    return result


def _clean(polygon):
    result = []
    for point in polygon:
        if not result or math.dist(result[-1][:2], point[:2]) > 1e-9:
            result.append(point)
    if len(result) > 1 and math.dist(result[0][:2], result[-1][:2]) <= 1e-9:
        result.pop()
    return result


def _cell_triangles(corners, field, walk):
    """Split a sample cell into two triangles, refining one that lies flat on
    an iso-level.

    Three corners of equal value cannot distinguish the region inside the
    triangle: a triangle whose corners all sit exactly on the carriageway
    edge is empty asphalt, but linear interpolation would fill it. A centre
    sample (and three sub-triangles) resolves it; this only happens where a
    road edge coincides with the sample grid.
    """
    for selection in ((0, 1, 2), (0, 2, 3)):
        triangle = [corners[index] for index in selection]
        values = [point[2] for point in triangle]
        flat = max(values) - min(values) <= 1e-9
        if flat and (abs(values[0]) <= 1e-9 or abs(values[0] - walk) <= 1e-9):
            x = sum(point[0] for point in triangle) / 3
            y = sum(point[1] for point in triangle) / 3
            triangle.append((x, y, field.value(x, y)))
            for index in range(3):
                yield [triangle[index], triangle[(index + 1) % 3], triangle[3]]
        else:
            yield triangle


def build_street_mesh(plan):
    """Return vertices, faces, material indices for road/footway/curb (0/1/2)."""
    walk = plan.settings.sidewalk_width
    nodes = flush_junctions(plan)
    field = Field(plan)
    vertices, faces, materials = [], [], []
    ids = {}
    curbs = set()
    surface = plan.surface() if getattr(plan, 'heights', None) else None
    # On terraces the walls (``build_wall_mesh``) close the footways' outer
    # edges inside the city ground; past it the skirts stay.
    walled = (plan.settings.radius * plan.settings.block_size + 20
              if getattr(plan, 'terraces', None) else None)

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, material):
        face_ids = list(dict.fromkeys(vertex(point) for point in points))
        if len(face_ids) >= 3:
            faces.append(tuple(face_ids))
            materials.append(material)

    def emit(polygon, material, height):
        polygon = _clean(polygon)
        if len(polygon) < 3:
            return
        if surface is None:
            top = [(x, y, height(x, y) if material == 1 else 0.0)
                   for x, y, _ in polygon]
            base = [0.0] * len(top)
        else:
            # On terrain everything rides on the road-level surface.
            base = [surface(x, y) for x, y, _ in polygon]
            top = [(x, y, z + (height(x, y) if material == 1 else 0.0))
                   for (x, y, _), z in zip(polygon, base)]
        for index in range(1, len(top) - 1):
            face((top[0], top[index], top[index + 1]), material)
        if material != 1:
            return
        # Curbs: iso-edges of the footway polygon. Both sides share these
        # vertices, so the skirt closes the surface without cracks. An iso edge
        # that runs exactly along a sample grid line would otherwise be emitted
        # once per adjacent cell, so each curb is keyed and emitted once.
        for index, current in enumerate(polygon):
            following = polygon[(index + 1) % len(polygon)]
            a, b = top[index], top[(index + 1) % len(top)]
            za, zb = base[index], base[(index + 1) % len(top)]
            if current[2] <= 1e-9 and following[2] <= 1e-9:
                bottom = 0.0
            elif current[2] >= walk - 1e-9 and following[2] >= walk - 1e-9:
                bottom = CURB_BOTTOM
            else:
                continue
            if bottom == 0.0 and a[2] - za <= 1e-9 and b[2] - zb <= 1e-9:
                continue
            if bottom == CURB_BOTTOM and walled is not None and max(
                    abs(a[0]), abs(a[1]), abs(b[0]), abs(b[1])) < walled - 1e-6:
                continue
            key = (tuple(sorted((vertex(b), vertex(a)))), bottom)
            if key in curbs:
                continue
            curbs.add(key)
            if surface is not None and bottom != 0.0:
                bottom = CURB_BOTTOM_TERRAIN
            face(((b[0], b[1], b[2]), (a[0], a[1], a[2]),
                  (a[0], a[1], za + bottom if surface is not None else bottom),
                  (b[0], b[1], zb + bottom if surface is not None else bottom)), 2)

    outers = outer_roads(plan)
    for i, j in sorted(field.active_cells()):
        x0, y0 = i * SAMPLE, j * SAMPLE
        if any(outer.drops(x0, y0) for outer in outers):
            continue
        corners = ((x0, y0, field.value(x0, y0)),
                   (x0 + SAMPLE, y0, field.value(x0 + SAMPLE, y0)),
                   (x0 + SAMPLE, y0 + SAMPLE, field.value(x0 + SAMPLE, y0 + SAMPLE)),
                   (x0, y0 + SAMPLE, field.value(x0, y0 + SAMPLE)))
        for polygon in _cell_triangles(corners, field, walk):
            emit(_clip(polygon, 0.0, True), 0, None)
            emit(_clip(_clip(polygon, walk, True), 0.0, False), 1,
                 lambda x, y: pavement_height(plan, x, y, nodes))
    return vertices, faces, materials


def build_ground_mesh(plan):
    """Unpaved terrain under and around the city, out to the wasteland edge."""
    if getattr(plan, 'terraces', None):
        return _terraced_ground(plan)[0]
    if getattr(plan, 'heights', None):
        return _terrain_ground_mesh(plan)
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    covered = Field(plan).covered_cells()
    per = int(round(GROUND_CELL / SAMPLE))
    vertices, faces, ids = [], [], {}

    def vertex(x, y):
        co = (round(x, 8), round(y, 8), GROUND_Z)
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    for i in range(math.floor(-extent / GROUND_CELL), math.ceil(extent / GROUND_CELL)):
        for j in range(math.floor(-extent / GROUND_CELL), math.ceil(extent / GROUND_CELL)):
            if all((i * per + di, j * per + dj) in covered
                   for di in range(per) for dj in range(per)):
                continue
            x0 = max(-extent, i * GROUND_CELL)
            y0 = max(-extent, j * GROUND_CELL)
            x1 = min(extent, (i + 1) * GROUND_CELL)
            y1 = min(extent, (j + 1) * GROUND_CELL)
            if x1 <= x0 or y1 <= y0:
                continue
            faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    if settings.wasteland > 0:
        # Flat framing quads far outside the detailed city ground; the game
        # keeps the player in with invisible walls while the horizon stays
        # open. Outer highways run through gaps cut in them.
        holes = []
        for outer in outer_roads(plan):
            a0 = max(extent, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        for rect in ((-far, -far, -extent, far), (extent, -far, far, far),
                     (-extent, extent, extent, far), (-extent, -far, extent, -extent)):
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    return vertices, faces


def _terrain_ground_mesh(plan):
    """The graded ground (``Grading``) on a finer grid; the wasteland beyond the
    map's edge stays level, as the edge of the graded city is."""
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    grading = Grading(plan)
    covered = grading.field.covered_cells()
    per = int(round(GROUND_CELL_TERRAIN / SAMPLE))
    vertices, faces, ids = [], [], {}
    cell = GROUND_CELL_TERRAIN
    # A cell that overlaps a pad keeps all four corners under the pad's top,
    # so no triangle across the pad's edge lifts the ground into the building.
    caps = {}
    for polygon, top in grading.pads:
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        for i in range(math.floor(min(xs) / cell), math.floor(max(xs) / cell) + 1):
            for j in range(math.floor(min(ys) / cell), math.floor(max(ys) / cell) + 1):
                caps[i, j] = min(caps.get((i, j), math.inf), top)

    def vertex(x, y, z=None):
        key = (round(x, 8), round(y, 8))
        if key not in ids:
            if z is None:
                i, j = round(x / cell), round(y / cell)
                cap = min(caps.get((i + di, j + dj), math.inf) for di in (-1, 0) for dj in (-1, 0))
                z = grading.ground(x, y, cap)
            ids[key] = len(vertices)
            vertices.append(key + (round(z, 8),))
        return ids[key]

    for i in range(math.floor(-extent / cell), math.ceil(extent / cell)):
        for j in range(math.floor(-extent / cell), math.ceil(extent / cell)):
            if all((i * per + di, j * per + dj) in covered
                   for di in range(per) for dj in range(per)):
                continue
            x0, y0 = max(-extent, i * cell), max(-extent, j * cell)
            x1, y1 = min(extent, (i + 1) * cell), min(extent, (j + 1) * cell)
            if x1 <= x0 or y1 <= y0:
                continue
            faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    if settings.wasteland > 0:
        holes = []
        for outer in outer_roads(plan):
            a0 = max(extent, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        for rect in ((-far, -far, -extent, far), (extent, -far, far, far),
                     (-extent, extent, extent, far), (-extent, -far, extent, -extent)):
            # The city's last 20 m are level (the surface is zero off the
            # lattice), so the framing quads meet the city ground flush.
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append((vertex(x0, y0, GROUND_Z_TERRAIN), vertex(x1, y0, GROUND_Z_TERRAIN),
                              vertex(x1, y1, GROUND_Z_TERRAIN), vertex(x0, y1, GROUND_Z_TERRAIN)))
    return vertices, faces


def build_wall_mesh(plan):
    """Retaining walls of a terraced city: along the terraces' edges, and
    wherever the ground meets a footway or a stair at another height (a ramp
    on its embankment, a street at a terrace's foot)."""
    if not getattr(plan, 'terraces', None):
        return [], []
    return _terraced_ground(plan)[1]


def _halfplane(polygon, axis, value, keep_below):
    """Clip a convex polygon of (x, y, field) points at x or y = ``value``."""
    result = []
    for index, current in enumerate(polygon):
        following = polygon[(index + 1) % len(polygon)]
        inside = current[axis] <= value if keep_below else current[axis] >= value
        next_inside = following[axis] <= value if keep_below else following[axis] >= value
        if inside:
            result.append(current)
        if inside != next_inside:
            factor = (value - current[axis]) / (following[axis] - current[axis])
            point = [current[k] + (following[k] - current[k]) * factor for k in range(3)]
            point[axis] = value
            result.append(tuple(point))
    return result


def _terraced_ground(plan):
    """Ground and retaining walls of a terraced city, built together so the
    walls use the ground's own edge vertices.

    Near the streets the ground is cut at the footways' outer edge on the
    street mesh's sample grid (so it shares those vertices' positions) and
    round each stair; elsewhere it is a coarser grid, whose cells take the
    finer grid's vertices along their shared sides (no T-junctions). The
    ground splits along the terraces' edges into one sheet per level.

    A verge WALL_GAP wide runs beside every footway at its level: ground
    much higher than the footway stands behind a wall at the verge's far
    edge, never at the footway itself. Walls dropping more than PARAPET[0]
    carry a parapet on their upper side.
    Returns ((vertices, faces), (wall vertices, wall faces)).
    """
    cached = plan.__dict__.get('_terraced_ground')
    if cached is not None:
        return cached
    settings = plan.settings
    walk = settings.sidewalk_width
    verge = walk + WALL_GAP
    extent = settings.radius * settings.block_size + 20
    far = extent + settings.wasteland
    grading = Grading(plan)
    field = grading.field
    cell = 2 * SAMPLE
    FAR = 1e9            # Field value of the coarse cells, far from any street.
    reach = math.ceil((WALL_GAP + SAMPLE) / cell)
    active = {(i // 2, j // 2) for i, j in field.active_cells()}
    fine = {(i + di, j + dj) for i, j in active
            for di in range(-reach, reach + 1) for dj in range(-reach, reach + 1)}
    radius = settings.radius
    lines = {round(grading.line(k), 8) for k in range(-radius, radius + 1)}
    middles = {v for v in lines if round(v / SAMPLE) % 2}
    caps = defaultdict(list)
    for polygon, top in grading.pads:
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        level = grading.level_at(sum(xs) / len(xs), sum(ys) / len(ys))
        for i in range(math.floor(min(xs) / cell), math.floor(max(xs) / cell) + 1):
            for j in range(math.floor(min(ys) / cell), math.floor(max(ys) / cell) + 1):
                caps[i, j].append((top, level))
    vertices, faces, ids = [], [], {}
    iso_edges, verge_edges, line_edges = [], defaultdict(list), defaultdict(list)

    def cap_at(x, y, level):
        cells = {(math.floor((x + dx) / cell), math.floor((y + dy) / cell))
                 for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7)}
        return min((top for c in cells for top, pad in caps.get(c, ()) if pad == level),
                   default=math.inf)

    def paving(point):
        """Just under the road over a point beneath a street's own paving
        (where the ground runs on under a viaduct), else None."""
        x, y = point[0], point[1]
        if grading.streets.value(x, y) < walk - .25 and grading.stair_at(x, y) is None:
            return grading.paved(x, y) - ABUTMENT_DROP
        return None

    def strip_height(x, y, f, natural):
        """The verge between a footway and the ground beyond it."""
        if grading.stair_at(x, y) is not None:
            return natural
        low = min(natural, grading.wall_foot(x, y) - CURB_DROP)
        rise = natural - low
        retained = (0.0 if rise <= RETAIN[0] else rise if rise >= RETAIN[1] else
                    (rise - RETAIN[0]) / (RETAIN[1] - RETAIN[0]) * RETAIN[1])
        share = max(0.0, min(1.0, (f - walk) / WALL_GAP))
        return low + (rise - retained) * share

    def vertex(x, y, level, part, f, z=None):
        key = (round(x, 8), round(y, 8), level, part)
        if key not in ids:
            if z is None:
                z = grading.ground(x, y, cap_at(x, y, level), level)
                if part == 'verge':
                    z = strip_height(x, y, f, z)
                # Under a viaduct's start the ground stays beneath its road.
                road = paving((x, y))
                if road is not None:
                    z = min(z, road)
            ids[key] = len(vertices)
            vertices.append((key[0], key[1], round(z, 8)))
        return ids[key]

    def z_of(point, level, part):
        return vertices[ids[(round(point[0], 8), round(point[1], 8), level, part)]][2]

    def on_line(a, b):
        for axis in (0, 1):
            value = round(a[axis], 8)
            if value == round(b[axis], 8) and value in lines:
                return axis, value
        return None

    def emit(polygon, part):
        polygon = _clean(polygon) if polygon else polygon
        for axis in (0, 1):
            polygon = _halfplane(polygon, axis, -extent, False) if polygon else polygon
            polygon = _halfplane(polygon, axis, extent, True) if polygon else polygon
        polygon = _clean(polygon) if polygon else polygon
        if not polygon or len(polygon) < 3:
            return
        cx = sum(p[0] for p in polygon) / len(polygon)
        cy = sum(p[1] for p in polygon) / len(polygon)
        level = grading.level_at(cx, cy)
        face_ids = list(dict.fromkeys(vertex(x, y, level, part, f) for x, y, f in polygon))
        if len(face_ids) < 3:
            return
        faces.append(tuple(face_ids))
        for index, a in enumerate(polygon):
            b = polygon[(index + 1) % len(polygon)]
            if part == 'verge' and abs(a[2] - walk) <= 1e-6 and abs(b[2] - walk) <= 1e-6:
                iso_edges.append((a, b, level))
            if abs(a[2] - verge) <= 1e-6 and abs(b[2] - verge) <= 1e-6:
                verge_edges[tuple(sorted(((round(a[0], 6), round(a[1], 6)),
                                          (round(b[0], 6), round(b[1], 6)))))].append(
                    (level, part, a, b))
            line = on_line(a, b)
            if line is not None:
                along = 1 - line[0]
                span = tuple(sorted((round(a[along], 8), round(b[along], 8))))
                line_edges[line + span].append((level, part, a, b))

    count = math.ceil(extent / cell)
    for i in range(-count, count):
        for j in range(-count, count):
            if (i, j) in fine:
                for fi in (2 * i, 2 * i + 1):
                    for fj in (2 * j, 2 * j + 1):
                        x0, y0 = fi * SAMPLE, fj * SAMPLE
                        corners = ((x0, y0, field.value(x0, y0)),
                                   (x0 + SAMPLE, y0, field.value(x0 + SAMPLE, y0)),
                                   (x0 + SAMPLE, y0 + SAMPLE,
                                    field.value(x0 + SAMPLE, y0 + SAMPLE)),
                                   (x0, y0 + SAMPLE, field.value(x0, y0 + SAMPLE)))
                        if all(c[2] <= walk for c in corners):
                            continue
                        for triangle in _cell_triangles(corners, field, walk):
                            ground = _clip(triangle, walk, False)
                            emit(_clip(ground, verge, True), 'verge')
                            emit(_clip(ground, verge, False), 'ground')
                continue
            x0, y0 = i * cell, j * cell
            x1, y1, xm, ym = x0 + cell, y0 + cell, x0 + SAMPLE, y0 + SAMPLE
            split_x, split_y = round(xm, 8) in middles, round(ym, 8) in middles
            polygon = [(x0, y0, FAR)]
            if (i, j - 1) in fine or split_x:
                polygon.append((xm, y0, FAR))
            polygon.append((x1, y0, FAR))
            if (i + 1, j) in fine or split_y:
                polygon.append((x1, ym, FAR))
            polygon.append((x1, y1, FAR))
            if (i, j + 1) in fine or split_x:
                polygon.append((xm, y1, FAR))
            polygon.append((x0, y1, FAR))
            if (i - 1, j) in fine or split_y:
                polygon.append((x0, ym, FAR))
            pieces = [polygon]
            if split_x:
                pieces = [_halfplane(q, 0, xm, keep) for q in pieces for keep in (True, False)]
            if split_y:
                pieces = [_halfplane(q, 1, ym, keep) for q in pieces for keep in (True, False)]
            for piece in pieces:
                emit(piece, 'ground')

    walls, wall_faces, wall_ids = [], [], {}

    def wall_vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in wall_ids:
            wall_ids[co] = len(walls)
            walls.append(co)
        return wall_ids[co]

    def solid(points):
        """A closed box from four base corners and their tops (8 points)."""
        bottom, top = points[:4], points[4:]
        area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(bottom, bottom[1:] + bottom[:1]))
        if area < 0:
            bottom, top = bottom[::-1], top[::-1]
        ids = [wall_vertex(p) for p in bottom + top]
        for face in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6),
                     (3, 0, 4, 7)):
            wall_faces.append(tuple(ids[k] for k in face))

    def wall(a, b, a_low, a_high, b_low, b_high, toward_left, parapet=True):
        """A wall over edge a-b of a ground sheet between two height profiles,
        facing the sheet's side (left of a-b) or the other, with a parapet on
        its upper side where it drops far enough."""
        da, db = a_high - a_low, b_high - b_low
        if abs(da) < 1e-6 and abs(db) < 1e-6:
            return
        if da < -1e-9 or db < -1e-9:
            if da * db < 0:
                # The profiles cross: two triangles either side.
                t = da / (da - db)
                m = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                zm = a_low + (b_low - a_low) * t
                wall(a, m, a_low, a_high, zm, zm, toward_left, False)
                wall(m, b, zm, zm, b_low, b_high, toward_left, False)
                return
            a_low, a_high, b_low, b_high = a_high, a_low, b_high, b_low
            toward_left = not toward_left
        points = [(a[0], a[1], a_high), (b[0], b[1], b_high), (b[0], b[1], b_low),
                  (a[0], a[1], a_low)]
        if not toward_left:
            points = [points[1], points[0], points[3], points[2]]
        face_ids = list(dict.fromkeys(wall_vertex(point) for point in points))
        if len(face_ids) >= 3:
            wall_faces.append(tuple(face_ids))
        length = math.dist(a[:2], b[:2])
        if parapet and length > 1e-6 and min(a_high - a_low, b_high - b_low) >= PARAPET[0]:
            # Behind the face, on the upper side.
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            side = -1 if toward_left else 1
            ox, oy = -uy * side * PARAPET[1], ux * side * PARAPET[1]
            base = [(a[0], a[1], a_high), (b[0], b[1], b_high),
                    (b[0] + ox, b[1] + oy, b_high), (a[0] + ox, a[1] + oy, a_high)]
            solid(base + [(x, y, z + PARAPET[2]) for x, y, z in base])

    def under_road(a, b, a_low, a_high, b_low, b_high, toward_left):
        """A wall that stops just beneath the road where it runs under a
        street's paving (a viaduct's abutment), with no parapet there."""
        cap_a, cap_b = paving(a), paving(b)
        if cap_a is not None:
            a_low, a_high = min(a_low, cap_a), min(a_high, cap_a)
        if cap_b is not None:
            b_low, b_high = min(b_low, cap_b), min(b_high, cap_b)
        wall(a, b, a_low, a_high, b_low, b_high, toward_left,
             cap_a is None and cap_b is None)

    # Verge against the paving: the wall (a curb's face, or an embankment's
    # side) faces the street where the verge is higher, the verge where the
    # paving is.
    def foot(point):
        # Under a street's own paving (a viaduct's abutment) the wall stops
        # just beneath it, so nothing stands proud of the road.
        road = paving(point)
        if road is not None:
            return road, True
        return grading.wall_foot(point[0], point[1]), False
    for a, b, level in iso_edges:
        (fa, under_a), (fb, under_b) = foot(a), foot(b)
        wall(a, b, fa, z_of(a, level, 'verge'), fb, z_of(b, level, 'verge'), False,
             not (under_a or under_b))
    # Verge against the ground beyond it: the retaining wall.
    for key in sorted(verge_edges):
        entries = verge_edges[key]
        strip = [e for e in entries if e[1] == 'verge']
        ground = [e for e in entries if e[1] == 'ground']
        if not strip or not ground:
            continue
        level, _, a, b = strip[0]
        other = ground[0][0]
        under_road(a, b, z_of(a, level, 'verge'), z_of(a, other, 'ground'),
                   z_of(b, level, 'verge'), z_of(b, other, 'ground'), True)
    # Ground against ground along a terrace's edge, facing the lower side.
    for key in sorted(line_edges):
        entries = line_edges[key]
        if len({(level, part) for level, part, _, _ in entries}) < 2:
            continue
        (level, part, a, b), (other, other_part, _, _) = entries[0], entries[1]
        under_road(a, b, z_of(a, level, part), z_of(a, other, other_part),
                   z_of(b, level, part), z_of(b, other, other_part), True)

    # The wild land round the city, out to where it levels off: its own
    # facets (each block two triangles), outside the city ground.
    wild = grading.wild
    edge_line = grading.line(radius + wild) if wild else extent
    if wild and settings.wasteland > 0:
        for i in range(-radius - wild, radius + wild):
            for j in range(-radius - wild, radius + wild):
                x0, x1 = grading.line(i), grading.line(i + 1)
                y0, y1 = grading.line(j), grading.line(j + 1)
                if max(abs(x0), abs(x1)) <= extent and max(abs(y0), abs(y1)) <= extent:
                    continue
                for triangle in ([(x0, y0, FAR), (x1, y0, FAR), (x1, y1, FAR)],
                                 [(x0, y0, FAR), (x1, y1, FAR), (x0, y1, FAR)]):
                    # Outside the city ground: four pieces round its square.
                    for piece in (_halfplane(triangle, 0, -extent, True),
                                  _halfplane(triangle, 0, extent, False),
                                  _halfplane(_halfplane(_halfplane(triangle, 0, -extent, False),
                                                        0, extent, True), 1, -extent, True),
                                  _halfplane(_halfplane(_halfplane(triangle, 0, -extent, False),
                                                        0, extent, True), 1, extent, False)):
                        piece = _clean(piece) if piece else piece
                        if piece and len(piece) >= 3:
                            face_ids = list(dict.fromkeys(
                                vertex(x, y, 0, 'wild', FAR,
                                       grading.natural(x, y, 0)) for x, y, _ in piece))
                            if len(face_ids) >= 3:
                                faces.append(tuple(face_ids))
    if settings.wasteland > 0:
        holes = []
        for outer in outer_roads(plan):
            a0 = max(edge_line, abs(outer.start)) * (1 if outer.sign > 0 else -1)
            holes.append(outer.rect(a0))
        far = max(far, edge_line + 1.0)
        for rect in ((-far, -far, -edge_line, far), (edge_line, -far, far, far),
                     (-edge_line, edge_line, edge_line, far),
                     (-edge_line, -far, edge_line, -edge_line)):
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append(tuple(vertex(x, y, 0, 'wild', FAR, GROUND_Z_TERRAIN)
                                   for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))))
    result = ((vertices, faces), (walls, wall_faces))
    plan.__dict__['_terraced_ground'] = result
    return result


def viaducts(plan, grading=None):
    """Each viaduct as built: its path, arc-length span, deck edges and piers.
    Returns [{'path', 'start', 'end', 'stations': [(along, centre, tangent,
    left top, right top, soffit)], 'piers': [(centre, tangent, foot, soffit)]}]."""
    if not getattr(plan, 'terraces', None):
        return []
    grading = grading or Grading(plan)
    walk = plan.settings.sidewalk_width
    found = []
    for path in plan.paths:
        for start, end in grading.spans.get(path['id'], ()):
            half = path['width'] / 2 + walk
            stations = []
            for along, (x, y), (tx, ty) in _walk_polyline(path['points'], 2.0):
                if start - 1e-6 <= along <= end + 1e-6:
                    nx, ny = -ty, tx
                    left, right = (x + nx * half, y + ny * half), (x - nx * half, y - ny * half)
                    stations.append((along, (x, y), (tx, ty),
                                     left + (grading.wall_foot(*left),),
                                     right + (grading.wall_foot(*right),),
                                     grading.surface(x, y) - DECK_DEPTH))
            if len(stations) < 2:
                continue
            length = end - start
            count = 1 if length < 2 * PIER_END else max(
                1, math.floor((length - 2 * PIER_END) / PIER_SPACING) + 1)
            spots = ([start + length / 2] if count == 1 else
                     [start + PIER_END + (length - 2 * PIER_END) * k / (count - 1)
                      for k in range(count)])
            # No pier in another street's paving (where a ramp leaves the
            # junction on a terrace's top): the next spot along that is clear.
            total = sum(math.dist(a, b) for a, b in zip(path['points'], path['points'][1:]))
            others = Field(plan, (), {path['id']: [(0.0, total)]})
            line = _walk_polyline(path['points'], 1.0)
            piers = []
            for spot in spots:
                clear = [item for item in line if start <= item[0] <= end and
                         others.value(*item[1]) >= walk + PIER_SIZE[1]]
                if not clear:
                    continue
                along, (x, y), (tx, ty) = min(clear, key=lambda item: abs(item[0] - spot))
                if abs(along - spot) > PIER_SPACING / 2:
                    continue
                nx, ny = -ty, tx
                foot = min(grading.natural(x + tx * a + nx * c, y + ty * a + ny * c)
                           for a in (-PIER_CAP[0] / 2, PIER_CAP[0] / 2)
                           for c in (-half, 0.0, half)) - .5
                piers.append(((x, y), (tx, ty), foot, grading.surface(x, y) - DECK_DEPTH))
            found.append({'path': path['id'], 'start': start, 'end': end, 'half': half,
                          'stations': stations, 'piers': piers})
    return found


def build_viaduct_mesh(plan):
    """Viaduct decks (soffit and fascias; each end meets a flat abutment),
    their parapets and piers with cap beams, for the stretches of ramp
    standing clear of the ground."""
    vertices, faces = [], []
    ids = {}

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, outward):
        face_ids = list(dict.fromkeys(vertex(p) for p in _oriented(points, outward)))
        if len(face_ids) >= 3:
            faces.append(tuple(face_ids))

    def box(centre, tangent, along, across, bottom, top):
        (x, y), (tx, ty) = centre, tangent
        nx, ny = -ty, tx
        base = [(x + tx * a + nx * c, y + ty * a + ny * c)
                for a, c in ((-along / 2, -across / 2), (along / 2, -across / 2),
                             (along / 2, across / 2), (-along / 2, across / 2))]
        offset = len(vertices)
        for z in (bottom, top):
            for px, py in base:
                vertices.append((round(px, 8), round(py, 8), round(z, 8)))
        faces.extend(tuple(offset + i for i in f) for f in
                     ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6),
                      (3, 0, 4, 7)))

    for viaduct in viaducts(plan):
        stations = viaduct['stations']
        for (_, c0, t0, l0, r0, s0), (_, c1, t1, l1, r1, s1) in zip(stations, stations[1:]):
            n0, n1 = (-t0[1], t0[0], 0.0), (-t1[1], t1[0], 0.0)
            normal = ((n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2, 0.0)
            face([l0, l1, l1[:2] + (s1,), l0[:2] + (s0,)], normal)
            face([r0, r1, r1[:2] + (s1,), r0[:2] + (s0,)], tuple(-v for v in normal))
            face([l0[:2] + (s0,), l1[:2] + (s1,), r1[:2] + (s1,), r0[:2] + (s0,)],
                 (0.0, 0.0, -1.0))
            # Parapets on both edges, standing on the footway.
            for e0, e1, sign in ((l0, l1, -1), (r0, r1, 1)):
                o0 = (n0[0] * sign * PARAPET[1], n0[1] * sign * PARAPET[1])
                o1 = (n1[0] * sign * PARAPET[1], n1[1] * sign * PARAPET[1])
                base = [e0, e1, (e1[0] + o1[0], e1[1] + o1[1], e1[2]),
                        (e0[0] + o0[0], e0[1] + o0[1], e0[2])]
                top = [(x, y, z + PARAPET[2]) for x, y, z in base]
                area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(base, base[1:] + base[:1]))
                if area < 0:
                    base, top = base[::-1], top[::-1]
                offset = len(vertices)
                for x, y, z in base + top:
                    vertices.append((round(x, 8), round(y, 8), round(z, 8)))
                faces.extend(tuple(offset + i for i in f) for f in
                             ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
                              (2, 3, 7, 6), (3, 0, 4, 7)))
        width = 2 * viaduct['half']
        for centre, tangent, foot, soffit in viaduct['piers']:
            box(centre, tangent, PIER_CAP[0], width - 1.0, soffit - PIER_CAP[1], soffit)
            box(centre, tangent, PIER_SIZE[0], min(PIER_SIZE[1], width / 3), foot,
                soffit - PIER_CAP[1])
    return vertices, faces


# A raised highway (``plan.freeway``): the mainline deck on hammerhead piers,
# with a median barrier, parapets and lane markings, and its ramps on single
# columns. Where a deck runs too near the ground for open space under it, it
# stands on solid fill between its fascias instead (an embankment).
FREEWAY_DEPTH = 1.6        # Mainline deck: top to soffit.
FREEWAY_RAMP_DEPTH = 1.1   # As city_plan's.
FREEWAY_OPEN = 1.0         # Least clear height under a soffit; lower is fill.
FREEWAY_PIERS = 30.0       # Mainline pier spacing (m); ramp piers half that.
FREEWAY_PIER = (2.0, 3.2)  # Column along the deck, across it.
FREEWAY_CAP = (2.4, 1.3)   # Cap beam along the deck, depth (it spans the deck).
FREEWAY_PIER_CLEAR = 2.5   # Piers keep this far from a street's footway.
FREEWAY_MEDIAN = (.6, .85)  # Median barrier width, height.
FREEWAY_MERGE = .3         # A ramp within this of the deck's level runs into it.
FREEWAY_LINE = .15         # Paint width.
FREEWAY_DASH = (3.0, 9.0)  # Lane dash, gap.


def _freeway_ground(plan):
    """Natural ground under a raised highway (at the surface it rides on)."""
    if getattr(plan, 'terraces', None):
        grading = Grading(plan)
        return lambda x, y: grading.natural(x, y)
    if getattr(plan, 'heights', None):
        surface = plan.surface()
        return lambda x, y: surface(x, y)
    return lambda x, y: 0.0


def freeway_stations(plan):
    """The raised highway as built: ('mainline' and each ramp) lists of
    stations (x, y centre, z top, inner edge |y|, outer edge |y|, bottom z,
    open), with open stations standing clear over the ground and the rest on
    fill. Returns {'mainline': [...], 'ramps': [[...]], 'piers': [(x, y, along,
    across, foot, cap bottom, cap top, cap across)]}."""
    freeway = getattr(plan, 'freeway', None) or {}
    if not freeway:
        return {}
    ground = _freeway_ground(plan)
    half, ramp_half = freeway['half'], freeway['ramp_half']
    walk = plan.settings.sidewalk_width
    size = plan.settings.block_size
    crossings = []
    for road in plan.roads:
        (ax, ay), (bx, by) = road.a, road.b
        if ax == bx and min(ay, by) <= 0 <= max(ay, by):
            crossings.append((ax * size, road.width / 2 + walk + FREEWAY_PIER_CLEAR))

    def under(x, y0, y1):
        samples = [ground(x, y0 + (y1 - y0) * k / 4) for k in range(5)]
        return min(samples), max(samples)
    mainline = []
    for x, z in freeway['mainline']:
        low, high = under(x, -half, half)
        bottom = z - FREEWAY_DEPTH
        open_ = bottom - high >= FREEWAY_OPEN
        mainline.append((x, 0.0, z, -half, half, bottom if open_ else low - .5, open_))
    ramps = []
    for ramp in freeway['ramps']:
        side, sign = ramp['side'], ramp['reach']
        climb, taper = ramp['length'], ramp['taper']
        stations = []
        for x, y, z in ramp['points']:
            along = abs(x - ramp['foot'])
            width = 2 * ramp_half * max(0.0, min(1.0, (climb + taper - along) / taper))
            inner, outer = side * half, side * (half + width)
            low, high = under(x, inner, side * (half + 2 * ramp_half))
            bottom = z - FREEWAY_RAMP_DEPTH
            open_ = bottom - high >= FREEWAY_OPEN
            stations.append((x, y, z, inner, outer, bottom if open_ else low - .5, open_))
        ramps.append(stations)

    def clear_of_streets(x, reach):
        return all(abs(x - cx) >= clear + reach for cx, clear in crossings)
    piers = []

    def deck_at(stations, x):
        for a, b in zip(stations, stations[1:]):
            if a[0] <= x <= b[0] or b[0] <= x <= a[0]:
                t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
                return a[2] + (b[2] - a[2]) * t, a[6] and b[6]
        return None, False
    # Mainline piers every FREEWAY_PIERS out from the middle both ways.
    xs = [st[0] for st in mainline]
    spots = []
    k = 0
    while True:
        moved = False
        for sign in ((1,) if k == 0 else (-1, 1)):
            x = sign * k * FREEWAY_PIERS
            if xs[0] < x < xs[-1]:
                spots.append(x)
                moved = True
        if not moved and k:
            break
        k += 1
    for x in sorted(spots):
        z, open_ = deck_at(mainline, x)
        if z is None or not open_:
            continue
        # Shift off a street under the deck (either way, the nearer free spot).
        for shift in (0.0, 3.0, -3.0, 6.0, -6.0, 9.0, -9.0, 12.0, -12.0):
            if clear_of_streets(x + shift, FREEWAY_CAP[0] / 2):
                break
        else:
            continue
        x += shift
        z, open_ = deck_at(mainline, x)
        if z is None or not open_:
            continue
        low, high = under(x, -half, half)
        soffit = z - FREEWAY_DEPTH
        if soffit - FREEWAY_CAP[1] - high < 2.0:
            continue
        piers.append((x, 0.0, FREEWAY_PIER[0], FREEWAY_PIER[1], min(
            ground(x + a, b) for a in (-1.0, 1.0) for b in (-2.0, 0.0, 2.0)) - .5,
            soffit - FREEWAY_CAP[1], soffit, 2 * half - 1.0))
    for ramp, stations in zip(freeway['ramps'], ramps):
        side = ramp['side']
        y = side * (half + ramp_half)
        start = ramp['foot']
        total = ramp['length'] + ramp['taper']
        count = max(1, int(total // (FREEWAY_PIERS / 2)))
        for j in range(1, count + 1):
            x = start + ramp['reach'] * total * j / (count + 1)
            if not clear_of_streets(x, 1.2):
                continue
            z, open_ = deck_at(stations, x)
            if z is None or not open_:
                continue
            soffit = z - FREEWAY_RAMP_DEPTH
            low, high = under(x, side * half, side * (half + 2 * ramp_half))
            if soffit - .8 - high < 2.0:
                continue
            # Under the narrowing lane, nearer the deck.
            width = 2 * ramp_half * max(0.0, min(1.0, (total - abs(x - start)) / ramp['taper']))
            if width < 4.0:
                continue
            centre = side * (half + width / 2)
            piers.append((x, centre, 1.4, 2.2, min(ground(x, centre + d) for d in (-1.5, 0.0, 1.5))
                          - .5, soffit - .8, soffit, width - 1.0))
    return {'mainline': mainline, 'ramps': ramps, 'piers': piers}


def build_freeway_mesh(plan):
    """Return vertices, faces, material indices (0 deck asphalt, 1 concrete)
    for a raised highway, or empty lists."""
    built = freeway_stations(plan)
    vertices, faces, materials = [], [], []
    if not built:
        return vertices, faces, materials
    ids = {}
    solid = [0]

    def vertex(co):
        # Each solid keeps its own vertices (parapets stand on the deck
        # without sharing its edges).
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        key = (solid[0], co)
        if key not in ids:
            ids[key] = len(vertices)
            vertices.append(co)
        return ids[key]

    def face(points, material, outward):
        indices = list(dict.fromkeys(vertex(p) for p in _oriented(points, outward)))
        if len(indices) >= 3:
            faces.append(tuple(indices))
            materials.append(material)

    def box(x, y, along, across, bottom, top):
        solid[0] += 1
        corners = [(x - along / 2, y - across / 2), (x + along / 2, y - across / 2),
                   (x + along / 2, y + across / 2), (x - along / 2, y + across / 2)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            mx, my = (ax + bx) / 2 - x, (ay + by) / 2 - y
            face([(ax, ay, bottom), (bx, by, bottom), (bx, by, top), (ax, ay, top)], 1, (mx, my, 0.0))
        face([(cx, cy, top) for cx, cy in corners], 1, (0.0, 0.0, 1.0))
        face([(cx, cy, bottom) for cx, cy in corners], 1, (0.0, 0.0, -1.0))

    def strip(stations, inner, outer, low, high, material):
        """A closed solid band along ``stations`` between two lateral edges
        (functions of a station) and two heights (offsets from the top, or
        None for the station's bottom): its top in ``material``, the rest
        concrete."""
        def level(st, offset):
            return st[5] if offset is None else st[2] + offset
        solid[0] += 1
        for a, b in zip(stations, stations[1:]):
            ia, ib, oa, ob = inner(a), inner(b), outer(a), outer(b)
            if abs(ia - oa) < 1e-6 and abs(ib - ob) < 1e-6:
                continue
            face([(a[0], ia, level(a, high)), (b[0], ib, level(b, high)),
                  (b[0], ob, level(b, high)), (a[0], oa, level(a, high))], material, (0.0, 0.0, 1.0))
            face([(a[0], ia, level(a, low)), (b[0], ib, level(b, low)),
                  (b[0], ob, level(b, low)), (a[0], oa, level(a, low))], 1, (0.0, 0.0, -1.0))
            for (ea, eb), sign in (((ia, ib), -1.0), ((oa, ob), 1.0)):
                side = sign * (1.0 if oa > ia else -1.0)
                face([(a[0], ea, level(a, low)), (b[0], eb, level(b, low)),
                      (b[0], eb, level(b, high)), (a[0], ea, level(a, high))], 1,
                     (0.0, side, 0.0))
        for st, sign in ((stations[0], -1.0), (stations[-1], 1.0)):
            direction = sign * (1.0 if stations[-1][0] > stations[0][0] else -1.0)
            i, o = inner(st), outer(st)
            face([(st[0], i, level(st, low)), (st[0], o, level(st, low)),
                  (st[0], o, level(st, high)), (st[0], i, level(st, high))], 1,
                 (direction, 0.0, 0.0))

    def runs(stations, keep):
        """Consecutive stretches of stations whose segments all pass ``keep``."""
        found, current = [], []
        for a, b in zip(stations, stations[1:]):
            if keep(a, b):
                current = current or [a]
                current.append(b)
            elif current:
                found.append(current)
                current = []
        if current:
            found.append(current)
        return found

    mainline, ramps = built['mainline'], built['ramps']
    freeway = plan.freeway
    half = freeway['half']
    # Mainline: deck (asphalt top; fascias and soffit or fill in concrete).
    strip(mainline, lambda st: -half, lambda st: half, None, 0.0, 0)
    # Where a ramp runs level with the deck, no parapet between them.
    merged = {-1: [], 1: []}
    for ramp, stations in zip(freeway['ramps'], ramps):
        for st in stations:
            near = min(mainline, key=lambda m: abs(m[0] - st[0]))
            if abs(near[2] - st[2]) <= FREEWAY_MERGE and abs(st[4]) > abs(st[3]) + 1e-6:
                merged[ramp['side']].append(st[0])
    for side in (-1, 1):
        spans = sorted(merged[side])

        def free(a, b, spans=spans):
            lo, hi = sorted((a[0], b[0]))
            return not any(lo - 4.0 <= x <= hi + 4.0 for x in spans)
        for run in runs(mainline, free):
            inner = side * (half - PARAPET[1])
            strip(run, lambda st, v=inner: v, lambda st, v=side * half: v, 0.0, PARAPET[2], 1)
    strip(mainline, lambda st: -FREEWAY_MEDIAN[0] / 2, lambda st: FREEWAY_MEDIAN[0] / 2,
          0.0, FREEWAY_MEDIAN[1], 1)
    # Ramps: deck, then a parapet along the outer edge where it stands up.
    ground = _freeway_ground(plan)
    for ramp, stations in zip(freeway['ramps'], ramps):
        side = ramp['side']
        inset = side * .05
        strip(stations, lambda st: st[3] + inset, lambda st: st[4], None, 0.0, 0)
        high = runs(stations, lambda a, b: min(a[2] - ground(a[0], a[4]), b[2] - ground(b[0], b[4]))
                    > .8 and abs(a[4] - a[3]) > PARAPET[1] + .05)
        for run in high:
            strip(run, lambda st: st[4] - side * PARAPET[1], lambda st: st[4], 0.0, PARAPET[2], 1)
    for x, y, along, across, foot, cap_bottom, cap_top, cap_across in built['piers']:
        box(x, y, along, across, foot, cap_bottom)
        box(x, y, FREEWAY_CAP[0], cap_across, cap_bottom, cap_top)
    return vertices, faces, materials


def freeway_markings(plan):
    """Lane paint on a raised highway's deck: quads (four xyz points) for
    the solid edge and median lines and the dashed lane lines."""
    freeway = getattr(plan, 'freeway', None) or {}
    if not freeway:
        return []
    mainline = [(x, 0.0, z) for x, z in freeway['mainline']]
    edge_line = freeway['half'] - 2.5
    quads = []

    def quad(x0, x1, y):
        z0, z1 = _interpolate(mainline, x0) + .004, _interpolate(mainline, x1) + .004
        w = FREEWAY_LINE / 2
        quads.append([(x0, y - w, z0), (x1, y - w, z1), (x1, y + w, z1), (x0, y + w, z0)])
    for y in (-edge_line, edge_line, -FREEWAY_MEDIAN[0] / 2 - .4, FREEWAY_MEDIAN[0] / 2 + .4):
        for (x0, _, _), (x1, _, _) in zip(mainline, mainline[1:]):
            quad(x0, x1, y)
    dash, gap = FREEWAY_DASH
    lane = (edge_line + FREEWAY_MEDIAN[0] / 2 + .4) / 2
    for y in (-lane, lane):
        x = math.ceil(mainline[0][0] / (dash + gap)) * (dash + gap)
        while x + dash < mainline[-1][0]:
            quad(x, x + dash, y)
            x += dash + gap
    return quads


def _interpolate(stations, x):
    """Deck top at ``x`` along a run of stations."""
    for a, b in zip(stations, stations[1:]):
        if a[0] <= x <= b[0]:
            t = (x - a[0]) / (b[0] - a[0]) if b[0] != a[0] else 0.0
            return a[2] + (b[2] - a[2]) * t
    return stations[0][2] if x < stations[0][0] else stations[-1][2]


def footprint(center, width, depth, rotation):
    """World corners (counter-clockwise) of a pad: width along its front."""
    c, s = math.cos(rotation), math.sin(rotation)
    return [(center[0] + x * c - y * s, center[1] + x * s + y * c)
            for x, y in ((-width / 2, -depth / 2), (width / 2, -depth / 2),
                         (width / 2, depth / 2), (-width / 2, depth / 2))]


def _polygon_distance(polygon, x, y):
    """Distance from (x, y) to a convex counter-clockwise polygon (0 inside)."""
    inside = True
    best = math.inf
    for (ax, ay), (bx, by) in zip(polygon, polygon[1:] + polygon[:1]):
        if (bx - ax) * (y - ay) - (by - ay) * (x - ax) < 0:
            inside = False
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - ax - dx * t, y - ay - dy * t))
    return 0.0 if inside else best


class Grading:
    """The graded ground of a terrain city: the natural ground, cut back round
    every building and site pad (the ground stays under the pad's top and
    rises from it no steeper than PAD_CUT_SLOPE) and, on hills, held up to the
    curbs' skirts along every footway. Heights are relative to the city origin.

    On terraces the natural ground is the base hills plus the rise of the
    terrace a point is on, falling away across a terrace's slope; the
    terraces' edges are snapped to the ground's sample grid (``line``), where
    the retaining walls stand. Each point belongs to a ``level`` (0 off the
    terraces, then a terrace's top and its slope). A pad shapes only the
    ground on its own level; stairs are holes in the ground, and the ground
    runs on under the viaducts (``spans``: {path id: arc-length intervals}).
    """

    def __init__(self, plan):
        settings = plan.settings
        self.surface = plan.surface()
        self.offset = GROUND_Z_TERRAIN if plan.heights else GROUND_Z
        self.walk = settings.sidewalk_width
        self.size = settings.block_size
        self.terraces = getattr(plan, 'terraces', None) or {}
        self.plan = plan
        self.nodes = flush_junctions(plan)
        self.streets = Field(plan)
        self.field = self.streets
        self.stairs, self.spans = [], {}
        self.wild = 0
        if self.terraces:
            self.wild = self.terraces.get('wild', 0)
            self.base = _Facets(settings.radius + self.wild,
                                {(x, y): z for x, y, z in self.terraces.get('ground', ())},
                                self.line, self._index)
            # Levels: 0 off the terraces; a terrace's top, and each of its
            # slopes and corners (sheets meeting where they agree, and
            # walled where they do not).
            self.levels, self.tops, self.slopes = {}, {}, {}
            for index, region in enumerate(self.terraces['regions']):
                top = ('top', index)
                self.tops[top] = region['step']
                for c in region['cells']:
                    self.levels[tuple(c)] = top
                rises = _slope_rises(region, self.line)
                parts = ([('slope', index, k, s['cells']) for k, s in
                          enumerate(region.get('slopes', ()))] +
                         [('corner', index, k, [c['cell']]) for k, c in
                          enumerate(region.get('corners', ()))])
                for kind, i, k, cells in parts:
                    level = (kind, i, k)
                    self.slopes[level] = {tuple(c): rises[tuple(c)] for c in cells}
                    for c in cells:
                        self.levels[tuple(c)] = level
            self.stairs = stair_layout(plan)
            self.spans = viaduct_spans(plan, self)
            self.field = Field(plan, [stair['segment'] for stair in self.stairs], self.spans)
        curb = settings.curb_height
        # The ground is graded up and down to each foundation (``_shaped``).
        self.pads = ([(footprint(lot.center, lot.width, lot.depth, lot.rotation),
                       curb + lot.level) for lot in plan.lots] +
                     [(site_footprint(poi), curb + poi.level) for poi in plan.pois])
        self.hash = defaultdict(list)
        for polygon, top in self.pads:
            xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
            rise = self.level_at(sum(xs) / len(xs), sum(ys) / len(ys))
            margin = PAD_REACH
            for i in range(math.floor((min(xs) - margin) / PAD_CELL),
                           math.floor((max(xs) + margin) / PAD_CELL) + 1):
                for j in range(math.floor((min(ys) - margin) / PAD_CELL),
                               math.floor((max(ys) + margin) / PAD_CELL) + 1):
                    self.hash[i, j].append((polygon, top, rise))

    def line(self, k):
        """The ground's line for lattice line ``k`` (a terrace's edge)."""
        return round(k * self.size / SAMPLE) * SAMPLE

    def _index(self, value):
        k = math.floor(value / self.size)
        while value < self.line(k):
            k -= 1
        while value >= self.line(k + 1):
            k += 1
        return k

    def level_at(self, x, y):
        """The level the ground at (x, y) belongs to: 0 off the terraces."""
        if not self.terraces:
            return 0
        return self.levels.get((self._index(x), self._index(y)), 0)

    def rise(self, x, y, level):
        """Metres the terrace ``level`` stands above the hills at (x, y)."""
        if not level:
            return 0.0
        if level in self.tops:
            return self.tops[level]
        rises = self.slopes[level]
        # On a block's edge any of its slope blocks will do: they agree there.
        for cell in sorted({(self._index(x + dx), self._index(y + dy))
                            for dx in (-1e-7, 1e-7) for dy in (-1e-7, 1e-7)}):
            if cell in rises:
                return rises[cell](x, y)
        return 0.0

    def natural(self, x, y, level=None):
        if not self.terraces:
            return self.surface(x, y) + self.offset
        if level is None:
            level = self.level_at(x, y)
        return self.base(x, y) + self.rise(x, y, level) + self.offset

    def ground(self, x, y, cap=math.inf, level=None):
        """Graded ground at (x, y); ``cap`` is a pad top it must also stay
        under; ``level`` the terrace level (on a terrace's edge, which side)."""
        if self.terraces:
            if level is None:
                level = self.level_at(x, y)
            height = self._shaped(x, y, self.natural(x, y, level), level)
            return min(height, cap - PAD_CLEAR)
        level = self.surface(x, y)
        height = min(self._shaped(x, y, level + self.offset, 0), cap - PAD_CLEAR)
        if self.field.value(x, y) <= self.walk + .5:
            height = max(height, level + CURB_BOTTOM_TERRAIN + .05)
        return height

    def _shaped(self, x, y, height, level):
        """Natural ``height`` blended into the foundations on ``level`` round
        (x, y), so a foundation stands in its ground rather than on a plinth
        over it: level with each for PAD_SHOULDER, then cut down at
        PAD_CUT_SLOPE or filled up at PAD_FILL_SLOPE to the natural ground.
        Near a foundation the ground also meets the footways, level with
        them for PAD_SHOULDER and rising or falling from them at the same
        slopes (so a front yard runs from the footway to the door, with no
        curb wall along it)."""
        ceiling, floor = math.inf, -math.inf
        nearest = (math.inf, math.inf, -math.inf)
        for polygon, top, pad_level in self.hash.get(
                (math.floor(x / PAD_CELL), math.floor(y / PAD_CELL)), ()):
            if pad_level != level:
                continue
            gap = _polygon_distance(polygon, x, y)
            distance = max(0.0, gap - PAD_SHOULDER)
            high = top - PAD_CLEAR + PAD_CUT_SLOPE * distance
            low = top - PAD_CLEAR - PAD_FILL_SLOPE * distance
            ceiling, floor = min(ceiling, high), max(floor, low)
            if gap < nearest[0]:
                nearest = (gap, high, low)
        if nearest[0] == math.inf:
            return height
        if floor > ceiling:
            # Between two foundations at different levels: the nearer one's.
            ceiling, floor = nearest[1], nearest[2]
        value = self.field.value(x, y)
        if value < self.walk - .3 or self.streets.value(x, y) < self.walk - .3:
            # Under the paving (a viaduct's too) the ground is never lifted
            # into it (its edge, cut on the sample grid, counts as outside).
            return min(height, ceiling)
        beyond = max(0.0, value - self.walk)
        if beyond < PAD_REACH:
            # The ground at a footway's edge: on terraces (cut at that edge)
            # just under the footway's top; on hills (whose cells reach under
            # the paving) at the street's own ground.
            footway = self.surface(x, y) + (self.plan.settings.curb_height - .05
                                            if self.terraces else self.offset)
            slope = max(0.0, beyond - PAD_SHOULDER)
            high = footway + PAD_CUT_SLOPE * slope
            low = footway - PAD_FILL_SLOPE * slope
            if max(floor, low) <= min(ceiling, high):
                ceiling, floor = min(ceiling, high), max(floor, low)
            else:
                # Where they cannot meet, the lower of the two: the ground
                # never stands above a footway or a foundation.
                ceiling = min(ceiling, high)
                floor = min(floor, low, ceiling)
        return min(max(height, floor), ceiling)

    def lowest(self, polygon, step=2.0):
        """Lowest ground over a convex polygon (sampled about ``step`` apart)."""
        xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
        nx = max(1, math.ceil((max(xs) - min(xs)) / step))
        ny = max(1, math.ceil((max(ys) - min(ys)) / step))
        low = math.inf
        for i in range(nx + 1):
            for j in range(ny + 1):
                x = min(xs) + (max(xs) - min(xs)) * i / nx
                y = min(ys) + (max(ys) - min(ys)) * j / ny
                if _polygon_distance(polygon, x, y) <= 1e-6:
                    low = min(low, self.ground(x, y))
        for x, y in polygon:
            low = min(low, self.ground(x, y))
        return low

    def stair_at(self, x, y):
        """The stair whose hole (x, y) is in, if a stair is nearer than any street."""
        best, value = None, self.streets.value(x, y)
        for stair in self.stairs:
            candidate = _distance(x, y, stair['segment']) - stair['segment'][4]
            if candidate < value:
                best, value = stair, candidate
        return best

    def paved(self, x, y):
        """The walking surface at a point of the street network or a stair:
        the carriageway, the footway's top, or a stair's pitch line."""
        stair = self.stair_at(x, y)
        if stair is not None:
            return stair_pitch(stair, x, y)
        level = self.surface(x, y)
        if self.streets.value(x, y) <= 0:
            return level
        return level + pavement_height(self.plan, x, y, self.nodes)

    def wall_foot(self, x, y):
        """Where a wall at the edge of the paving meets it: the footway's top,
        or a riser below a stair's pitch line (under every step)."""
        stair = self.stair_at(x, y)
        if stair is not None:
            return stair_pitch(stair, x, y) - stair['riser']
        return self.surface(x, y) + pavement_height(self.plan, x, y, self.nodes)


SLOPE_KNOTS = ((0.0, 1.0), (.2, .88), (.8, .12), (1.0, 0.0))   # As city_plan's.


def _slope_profile(t):
    """Share of a terrace's rise left a fraction ``t`` down its slope (as
    ``city_plan.slope_profile``): three flat facets."""
    t = max(0.0, min(1.0, t))
    for (t0, h0), (t1, h1) in zip(SLOPE_KNOTS, SLOPE_KNOTS[1:]):
        if t <= t1:
            return h0 + (h1 - h0) * (t - t0) / (t1 - t0)
    return 0.0


def _corner_distance(a, b):
    a, b = max(0.0, a), max(0.0, b)
    return max(a, b, (a + b) / math.sqrt(2))


class _Facets:
    """The hills as flat facets (as ``city_plan.Facets``), on the ground's
    snapped lines."""

    def __init__(self, radius, heights, line, index):
        self.radius, self.heights, self.line, self.index = radius, heights, line, index

    def __call__(self, x, y):
        if not self.heights:
            return 0.0
        i, j = self.index(x), self.index(y)
        if i < -self.radius or j < -self.radius or i >= self.radius or j >= self.radius:
            return 0.0
        x0, x1, y0, y1 = self.line(i), self.line(i + 1), self.line(j), self.line(j + 1)
        u, v = (x - x0) / (x1 - x0), (y - y0) / (y1 - y0)
        h = self.heights
        h00, h10 = h.get((i, j), 0.0), h.get((i + 1, j), 0.0)
        h01, h11 = h.get((i, j + 1), 0.0), h.get((i + 1, j + 1), 0.0)
        if u >= v:
            return h00 + (h10 - h00) * u + (h11 - h10) * v
        return h00 + (h01 - h00) * v + (h11 - h01) * u


def _slope_rises(region, line):
    """{cell: rise(x, y)} over a terrace's slopes and the corners joining
    them, with lattice line k standing at ``line(k)`` (as
    ``city_plan.slope_rises``)."""
    step = region['step']
    found = {}

    def down(value, crest, sign):
        a, b = line(crest), line(crest + sign)
        return (value - a) / (b - a)
    for slope in region.get('slopes', ()):
        axis, sign, crest = slope['axis'], slope['sign'], slope['line']
        for c in slope['cells']:
            found[tuple(c)] = (lambda x, y, axis=axis, sign=sign, crest=crest:
                               step * _slope_profile(down((x, y)[axis], crest, sign)))
    for corner in region.get('corners', ()):
        (cx, sx), (cy, sy) = corner['x'], corner['y']
        found[tuple(corner['cell'])] = (
            lambda x, y, cx=cx, sx=sx, cy=cy, sy=sy: step * _slope_profile(
                _corner_distance(down(x, cx, sx), down(y, cy, sy))))
    return found


def _ramp_rows(plan):
    """Every ramp edge as a world segment."""
    size = plan.settings.block_size
    return [(a[0] * size, a[1] * size, b[0] * size, b[1] * size, 0.0)
            for ramp in (getattr(plan, 'terraces', None) or {}).get('ramps', ())
            for a, b in zip(ramp['nodes'], ramp['nodes'][1:])]


def _walk_polyline(points, step):
    """(arc length, point, unit tangent) about every ``step`` metres, both ends included."""
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    total = sum(lengths)
    count = max(1, math.ceil(total / step))
    samples = []
    for k in range(count + 1):
        target = total * k / count
        along = 0.0
        for (a, b), length in zip(zip(points, points[1:]), lengths):
            if length and (target <= along + length or (a, b) == (points[-2], points[-1])):
                t = max(0.0, min(1.0, (target - along) / length))
                samples.append((target, (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                                ((b[0] - a[0]) / length, (b[1] - a[1]) / length)))
                break
            along += length
    return samples


def viaduct_spans(plan, grading):
    """{path id: [(start, end) arc lengths]}: the stretches of a ramp high
    enough over the ground on either side to stand on piers."""
    ramps = _ramp_rows(plan)
    if not ramps:
        return {}
    walk = plan.settings.sidewalk_width
    spans = {}
    for path in plan.paths:
        half = path['width'] / 2
        reach = half + walk + 1.0
        runs, start, previous = [], None, None
        for along, (x, y), (tx, ty) in _walk_polyline(path['points'], 1.0):
            # (A ramp's wide turns run up to about 10 m off the lattice.)
            high = min(_distance(x, y, r) for r in ramps) < RAMP_REACH
            if high:
                soffit = grading.surface(x, y) - DECK_DEPTH
                under = max(grading.natural(x - ty * o, y + tx * o) for o in (-reach, 0, reach))
                high = soffit - under >= VIADUCT_CLEARANCE
            if high and start is None:
                start = along
            elif not high and start is not None:
                runs.append((start, previous))
                start = None
            previous = along
        if start is not None:
            runs.append((start, previous))
        runs = [(a, b) for a, b in runs if b - a >= VIADUCT_SPAN]
        if runs:
            spans[path['id']] = runs
    return spans


def stair_layout(plan):
    """Each stair as built: from the upper street's footway (``top`` metres
    along from the upper junction, at ``z_top``) down to the lower street's
    (``bottom``, ``z_bottom``) in equal steps; ``segment`` is its hole in the
    ground, as a field row (``STAIR_WIDTH`` wide at the footways' edge)."""
    terraces = getattr(plan, 'terraces', None) or {}
    if not terraces.get('stairs'):
        return []
    settings = plan.settings
    size, walk = settings.block_size, settings.sidewalk_width
    field = Field(plan)
    surface = plan.surface()
    nodes = flush_junctions(plan)
    stairs = []
    for stair in terraces['stairs']:
        hx, hy = stair['high'][0] * size, stair['high'][1] * size
        lx, ly = stair['low'][0] * size, stair['low'][1] * size
        length = math.hypot(lx - hx, ly - hy)
        ux, uy = (lx - hx) / length, (ly - hy) / length

        def clear(sign):
            # The first point out from a junction past its street's footway.
            for k in range(int(length * 10)):
                along = k / 10 if sign > 0 else length - k / 10
                if field.value(hx + ux * along, hy + uy * along) > walk:
                    return along
            return length / 2
        top, bottom = clear(1), clear(-1)

        def level(along):
            x, y = hx + ux * along, hy + uy * along
            return surface(x, y) + pavement_height(plan, x, y, nodes)
        z_top, z_bottom = level(top), level(bottom)
        steps = max(1, math.ceil((z_top - z_bottom) / STAIR_RISE))
        half = stair['width'] / 2
        stairs.append({'origin': (hx, hy), 'direction': (ux, uy), 'length': length,
                       'top': top, 'bottom': bottom, 'z_top': z_top, 'z_bottom': z_bottom,
                       'steps': steps, 'riser': (z_top - z_bottom) / steps, 'half': half,
                       'segment': (hx, hy, lx, ly, half - walk)})
    return stairs


def stair_pitch(stair, x, y):
    """Height of a stair's pitch line (its step nosings) abreast of (x, y)."""
    (hx, hy), (ux, uy) = stair['origin'], stair['direction']
    along = (x - hx) * ux + (y - hy) * uy
    run = stair['bottom'] - stair['top']
    t = max(0.0, min(1.0, (along - stair['top']) / run)) if run > 0 else 0.0
    return stair['z_top'] + (stair['z_bottom'] - stair['z_top']) * t


def build_stair_mesh(plan):
    """Stairs up the terraces' faces: closed solid steps between the walls,
    with a landing under each street's footway."""
    vertices, faces = [], []
    for stair in stair_layout(plan):
        (hx, hy), (ux, uy) = stair['origin'], stair['direction']
        px, py = -uy, ux
        half = stair['half'] - STAIR_INSET
        base = stair['z_bottom'] - STAIR_BASE
        run = (stair['bottom'] - stair['top']) / stair['steps']
        pieces = [(stair['top'] - STAIR_LANDING, stair['top'], stair['z_top'] - .02)]
        for index in range(stair['steps']):
            top = stair['z_top'] - (index + 1) * stair['riser']
            pieces.append((stair['top'] + index * run, stair['top'] + (index + 1) * run,
                           top - (.02 if index == stair['steps'] - 1 else 0.0)))
        pieces.append((stair['bottom'], stair['bottom'] + STAIR_LANDING, stair['z_bottom'] - .02))
        for a0, a1, top in pieces:
            offset = len(vertices)
            for z in (base, top):
                for along, across in ((a0, -half), (a1, -half), (a1, half), (a0, half)):
                    vertices.append((round(hx + ux * along + px * across, 8),
                                     round(hy + uy * along + py * across, 8), round(z, 8)))
            # Counter-clockwise seen from outside (the frame is right-handed).
            faces.extend(tuple(offset + i for i in f) for f in
                         ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                          (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))
    return vertices, faces


def heightmap(plan, resolution, column_sign=1, row_sign=1):
    """The graded ground with every building and site pad at its top (streets
    at their road level, to within the ground's few centimetres) on a
    ``resolution`` x ``resolution`` grid over the city ground. Returns
    ``(rows, x0, y0, step)``: sample (row r, column c) lies at
    (x0 + column_sign * c * step, y0 + row_sign * r * step) from the city
    origin; columns run along x, rows along y."""
    settings = plan.settings
    extent = settings.radius * settings.block_size + 20
    step = 2 * extent / (resolution - 1)
    x0 = -extent if column_sign > 0 else extent
    y0 = -extent if row_sign > 0 else extent
    grading = Grading(plan)
    surface, offset = grading.surface, grading.offset
    terraced = bool(grading.terraces)
    rows = []
    for r in range(resolution):
        y = y0 + row_sign * r * step
        row = []
        for c in range(resolution):
            x = x0 + column_sign * c * step
            if terraced and grading.field.value(x, y) <= grading.walk:
                # Streets, ramps and stairs at their walking surface.
                row.append(grading.paved(x, y))
                continue
            here = grading.level_at(x, y)
            height = grading.natural(x, y, here) if terraced else surface(x, y) + offset
            tops = [top for polygon, top, level in grading.hash.get(
                (math.floor(x / PAD_CELL), math.floor(y / PAD_CELL)), ())
                if level == here and _polygon_distance(polygon, x, y) <= 0.0]
            row.append(tops[0] if tops else grading._shaped(x, y, height, here))
        rows.append(row)
    return rows, x0, y0, step


def site_footprint(poi):
    """World corners of a site's pad, its approach to the footway included."""
    width, depth = poi.width, poi.depth + poi.approach
    c, s = math.cos(poi.rotation), math.sin(poi.rotation)
    # The approach extends the pad toward the street (local -y).
    cx, cy = 0.0, -poi.approach / 2
    center = (poi.center[0] + cx * c - cy * s, poi.center[1] + cx * s + cy * c)
    return footprint(center, width, depth, poi.rotation)


def _subtract(rect, holes):
    """Axis-aligned rectangle minus rectangles, as disjoint rectangles."""
    pieces = [rect]
    for hx0, hy0, hx1, hy1 in holes:
        result = []
        for x0, y0, x1, y1 in pieces:
            if hx0 >= x1 or hx1 <= x0 or hy0 >= y1 or hy1 <= y0:
                result.append((x0, y0, x1, y1))
                continue
            cx0, cy0, cx1, cy1 = max(x0, hx0), max(y0, hy0), min(x1, hx1), min(y1, hy1)
            for piece in ((x0, y0, x1, cy0), (x0, cy1, x1, y1),
                          (x0, cy0, cx0, cy1), (cx1, cy0, x1, cy1)):
                if piece[2] - piece[0] > 1e-6 and piece[3] - piece[1] > 1e-6:
                    result.append(piece)
        pieces = result
    return pieces


def _oriented(points, outward):
    """Points ordered so the polygon's normal points along ``outward``."""
    nx = ny = nz = 0.0
    for index, (x0, y0, z0) in enumerate(points):
        x1, y1, z1 = points[(index + 1) % len(points)]
        nx += (y0 - y1) * (z0 + z1)
        ny += (z0 - z1) * (x0 + x1)
        nz += (x0 - x1) * (y0 + y1)
    if nx * outward[0] + ny * outward[1] + nz * outward[2] < 0:
        return list(reversed(points))
    return points


def build_outer_road_mesh(plan, street_vertices):
    """Highways continuing out of the city across the wasteland.

    Materials: 0 carriageway, 1 shoulder, 2 curbs and skirts (every vertical
    face), 3 ground (where the surface has broken up). The first cross-section is made of the
    street mesh's own vertices on the cut line (``street_vertices``), so the two
    meshes meet without cracks: the footways ramp down onto the shoulders, and
    the long edges and the far end drop to ``CURB_BOTTOM`` like the city curbs.
    """
    vertices, faces, materials = [], [], []
    ids = {}

    def vertex(co):
        co = (round(co[0], 8), round(co[1], 8), round(co[2], 8))
        if co not in ids:
            ids[co] = len(vertices)
            vertices.append(co)
        return ids[co]

    def face(points, material, outward=(0.0, 0.0, 1.0)):
        indices = list(dict.fromkeys(vertex(point) for point in _oriented(points, outward)))
        if len(indices) >= 3:
            faces.append(tuple(indices))
            materials.append(material)

    seed = plan.settings.seed
    for index, outer in enumerate(outer_roads(plan)):
        low, high = outer.centre - outer.band, outer.centre + outer.band
        heights = {}
        if outer.deck:
            # Off a raised highway's deck: shoulders flush with the carriageway.
            heights = {round(b, 8): 0.0 for b in (low, outer.centre - outer.half,
                                                   outer.centre + outer.half, high)}
            street_vertices = ()
        for x, y, z in street_vertices:
            a, b = (x, y) if outer.axis == 0 else (y, x)
            if abs(a - outer.cut) < 1e-6 and low - 1e-6 <= b <= high + 1e-6:
                key = round(b, 8)
                heights[key] = max(heights.get(key, z), z)
        laterals = sorted(heights)
        if len(laterals) < 2:
            continue
        length = outer.length
        fade_start = max(0.0, length - outer.road['fade'])
        alongs = [0.0, OUTER_RAMP / 2, OUTER_RAMP]
        while alongs[-1] < length - 1e-6:
            step = OUTER_SOLID_ROW if alongs[-1] < fade_start - 1e-6 else OUTER_FADE_ROW
            following = alongs[-1] + step
            if alongs[-1] < fade_start - 1e-6:
                following = min(following, fade_start)
            alongs.append(min(following, length))
        road_seed = seed * 31 + index

        def shoulder(lateral, along):
            """Footway height at the cut, ramping down to the shoulder level."""
            return heights.get(round(lateral, 8), 0.0) * max(0.0, 1 - along / OUTER_RAMP)

        def surface(lateral, along, carriageway):
            if carriageway:
                return 0.0
            return shoulder(lateral, along)

        for a0, a1 in zip(alongs, alongs[1:]):
            middle = (a0 + a1) / 2
            for l0, l1 in zip(laterals, laterals[1:]):
                lateral = (l0 + l1) / 2
                road = abs(lateral - outer.centre) <= outer.half
                if not outer_asphalt(outer, road_seed, middle, lateral):
                    material = 3
                else:
                    material = 0 if road else 1
                face([outer.world(a0, l0, surface(l0, a0, road)),
                      outer.world(a1, l0, surface(l0, a1, road)),
                      outer.world(a1, l1, surface(l1, a1, road)),
                      outer.world(a0, l1, surface(l1, a0, road))], material)
            # Curbs where the raised footways meet the carriageway, while they ramp.
            if a0 < OUTER_RAMP - 1e-9:
                for side in (-1, 1):
                    lateral = round(outer.centre + side * outer.half, 8)
                    if lateral not in heights:
                        continue
                    toward = (0.0, -side, 0.0) if outer.axis == 0 else (-side, 0.0, 0.0)
                    face([outer.world(a0, lateral, 0.0), outer.world(a1, lateral, 0.0),
                          outer.world(a1, lateral, shoulder(lateral, a1)),
                          outer.world(a0, lateral, shoulder(lateral, a0))], 2, toward)
            for side, lateral in ((-1, laterals[0]), (1, laterals[-1])):
                outward = (0.0, side, 0.0) if outer.axis == 0 else (side, 0.0, 0.0)
                face([outer.world(a0, lateral, shoulder(lateral, a0)),
                      outer.world(a1, lateral, shoulder(lateral, a1)),
                      outer.world(a1, lateral, CURB_BOTTOM), outer.world(a0, lateral, CURB_BOTTOM)],
                     2, outward)
        outward = (outer.sign, 0.0, 0.0) if outer.axis == 0 else (0.0, outer.sign, 0.0)
        for l0, l1 in zip(laterals, laterals[1:]):
            face([outer.world(length, l0, 0.0), outer.world(length, l1, 0.0),
                  outer.world(length, l1, CURB_BOTTOM), outer.world(length, l0, CURB_BOTTOM)],
                 2, outward)
    return vertices, faces, materials


def outer_road_dashes(plan):
    """Worn lane dashes on the outer highways: quads (four xy points) at the
    lane lines, thinning out and gone where the surface breaks up."""
    quads = []
    seed = plan.settings.seed
    for index, outer in enumerate(outer_roads(plan)):
        width = outer.road['width']
        offsets = (0.0, -width / 4, width / 4) if width >= 12 else (0.0,)
        road_seed = seed * 31 + index
        fade_start = outer.length - outer.road['fade']
        along = 6.0 - abs(outer.cut - outer.start)     # From just past the end node.
        step = 0
        while along + 3 < outer.length:
            step += 1
            middle = along + 1.5
            worn = .2 + (max(0.0, middle - fade_start) / max(1.0, outer.road['fade'])) * .6
            for lane, offset in enumerate(offsets):
                lateral = outer.centre + offset
                if _hash01(road_seed + 7, step, lane) < worn:
                    continue
                if not outer_asphalt(outer, road_seed, middle, lateral):
                    continue
                quad = [outer.world(along, lateral - .06, 0.0)[:2],
                        outer.world(along + 3, lateral - .06, 0.0)[:2],
                        outer.world(along + 3, lateral + .06, 0.0)[:2],
                        outer.world(along, lateral + .06, 0.0)[:2]]
                area = sum(ax * by - bx * ay for (ax, ay), (bx, by) in zip(quad, quad[1:] + quad[:1]))
                quads.append(quad if area > 0 else quad[::-1])
            along += 7.0
    return quads
