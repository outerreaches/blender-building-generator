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
    return rows


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

    for i, j in sorted(field.active_cells()):
        x0, y0 = i * SAMPLE, j * SAMPLE
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
        # Flat framing quads far outside the detailed city ground. Four faces are
        # enough because nothing is cut out there; the game keeps the player in
        # with invisible walls while the horizon stays open.
        for corners in (
                ((-far, -far), (-extent, -far), (-extent, far), (-far, far)),
                ((extent, -far), (far, -far), (far, far), (extent, far)),
                ((-extent, extent), (extent, extent), (extent, far), (-extent, far)),
                ((-extent, -far), (extent, -far), (extent, -extent), (-extent, -extent))):
            faces.append(tuple(vertex(x, y) for x, y in corners))
    return vertices, faces
