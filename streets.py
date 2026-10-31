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


def pavement_height(plan, x, y, nodes=None):
    """Flush corners with a 2 m transition to the raised footway on each approach."""
    size = plan.settings.block_size
    nodes = junctions(plan) if nodes is None else nodes
    node = (round(x / size), round(y / size))
    if node not in nodes:
        return plan.settings.curb_height
    distance = max(abs(x - node[0] * size), abs(y - node[1] * size))
    ramp_start = nodes[node] + plan.settings.sidewalk_width
    return plan.settings.curb_height * min(1, max(0, (distance - ramp_start) / 2))


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


def _segments(plan):
    rows = []
    for path in plan.paths:
        half = path['width'] / 2
        points = path['points']
        for a, b in zip(points, points[1:]):
            rows.append((a[0], a[1], b[0], b[1], half))
    for road in getattr(plan, 'outer_roads', ()):
        (x, y), (dx, dy) = road['start'], road['direction']
        rows.append((x, y, x + dx * OUTER_STUB, y + dy * OUTER_STUB, road['width'] / 2))
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
        self.lo = math.floor((centre - self.band) / SAMPLE + 1e-9) * SAMPLE
        self.hi = math.ceil((centre + self.band) / SAMPLE - 1e-9) * SAMPLE
        self.centre = centre
        self.start = start
        self.end = start + self.sign * road['length']

    def drops(self, x0, y0):
        """True for street-mesh cells the outer road replaces."""
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

    def __init__(self, plan):
        self.segments = _segments(plan)
        self.walk = plan.settings.sidewalk_width
        self.grid = defaultdict(list)
        for segment in self.segments:
            x0, y0, x1, y1, half = segment
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
                    candidate = _distance(x, y, segment) - segment[4]
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
        for x0, y0, x1, y1, half in self.segments:
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


def build_street_mesh(plan):
    """Return vertices, faces, material indices for road/footway/curb (0/1/2)."""
    walk = plan.settings.sidewalk_width
    nodes = junctions(plan)
    field = Field(plan)
    vertices, faces, materials = [], [], []
    ids = {}
    curbs = set()

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
        top = [(x, y, height(x, y) if material == 1 else 0.0)
               for x, y, _ in polygon]
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
            if current[2] <= 1e-9 and following[2] <= 1e-9:
                bottom = 0.0
            elif current[2] >= walk - 1e-9 and following[2] >= walk - 1e-9:
                bottom = CURB_BOTTOM
            else:
                continue
            if bottom == 0.0 and a[2] <= 1e-9 and b[2] <= 1e-9:
                continue
            key = (tuple(sorted((vertex(b), vertex(a)))), bottom)
            if key in curbs:
                continue
            curbs.add(key)
            face(((b[0], b[1], b[2]), (a[0], a[1], a[2]),
                  (a[0], a[1], bottom), (b[0], b[1], bottom)), 2)

    def triangles(corners):
        """Split a cell into two triangles, refining one that lies flat on an iso-level.

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

    outers = outer_roads(plan)
    for i, j in sorted(field.active_cells()):
        x0, y0 = i * SAMPLE, j * SAMPLE
        if any(outer.drops(x0, y0) for outer in outers):
            continue
        corners = ((x0, y0, field.value(x0, y0)),
                   (x0 + SAMPLE, y0, field.value(x0 + SAMPLE, y0)),
                   (x0 + SAMPLE, y0 + SAMPLE, field.value(x0 + SAMPLE, y0 + SAMPLE)),
                   (x0, y0 + SAMPLE, field.value(x0, y0 + SAMPLE)))
        for polygon in triangles(corners):
            emit(_clip(polygon, 0.0, True), 0, None)
            emit(_clip(_clip(polygon, walk, True), 0.0, False), 1,
                 lambda x, y: pavement_height(plan, x, y, nodes))
    return vertices, faces, materials


def build_ground_mesh(plan):
    """Unpaved terrain under and around the city, out to the wasteland edge."""
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
            a0 = extent if outer.sign > 0 else -extent
            holes.append(outer.rect(a0))
        for rect in ((-far, -far, -extent, far), (extent, -far, far, far),
                     (-extent, extent, extent, far), (-extent, -far, extent, -extent)):
            for x0, y0, x1, y1 in _subtract(rect, holes):
                faces.append((vertex(x0, y0), vertex(x1, y0), vertex(x1, y1), vertex(x0, y1)))
    return vertices, faces


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
