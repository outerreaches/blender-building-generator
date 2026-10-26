# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure street surface tessellation. Union first, then mesh: no overlapping junctions."""
from collections import defaultdict
import math


def junctions(plan):
    result = {}
    for road in plan.roads:
        for node in (road.a, road.b):
            result[node] = max(result.get(node, 0), road.width / 2)
    return result


def street_rectangles(plan):
    size = plan.settings.block_size
    halves = junctions(plan)
    rectangles = [(x * size - h, y * size - h, x * size + h, y * size + h)
                  for (x, y), h in sorted(halves.items())]
    for road in plan.roads:
        a, b, h = road.a, road.b, road.width / 2
        rectangles.append((a[0] * size - h, a[1] * size - h,
                           b[0] * size + h, b[1] * size + h))
    return rectangles


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


def build_ground_mesh(plan):
    """Unpaved ground only: no almost-coplanar terrain beneath road or floor faces."""
    size, walk = plan.settings.block_size, plan.settings.sidewalk_width
    extent = plan.settings.radius * size + 20
    obstacles = [(r[0] - walk, r[1] - walk, r[2] + walk, r[3] + walk)
                 for r in street_rectangles(plan)]
    obstacles.extend(frontage_rectangle(lot, plan) for lot in plan.lots)
    tiles = defaultdict(list)
    for rect in obstacles:
        for x in range(math.floor(rect[0] / size), math.floor(rect[2] / size) + 1):
            for y in range(math.floor(rect[1] / size), math.floor(rect[3] / size) + 1):
                tiles[x, y].append(rect)
    vertices, faces, ids = [], [], {}
    for tx in range(math.floor(-extent / size), math.ceil(extent / size)):
        for ty in range(math.floor(-extent / size), math.ceil(extent / size)):
            x0, x1 = max(-extent, tx * size), min(extent, (tx + 1) * size)
            y0, y1 = max(-extent, ty * size), min(extent, (ty + 1) * size)
            rects = tiles[tx, ty]
            xs = sorted({x0, x1, *(min(x1, max(x0, r[i])) for r in rects for i in (0, 2))})
            ys = sorted({y0, y1, *(min(y1, max(y0, r[i])) for r in rects for i in (1, 3))})
            for left, right in zip(xs, xs[1:]):
                for bottom, top in zip(ys, ys[1:]):
                    if right - left < 1e-7 or top - bottom < 1e-7:
                        continue
                    cx, cy = (left + right) / 2, (bottom + top) / 2
                    if any(r[0] < cx < r[2] and r[1] < cy < r[3] for r in rects):
                        continue
                    face = []
                    for x, y in ((left, bottom), (right, bottom), (right, top), (left, top)):
                        co = (round(x, 8), round(y, 8), -.02)
                        if co not in ids:
                            ids[co] = len(vertices)
                            vertices.append(co)
                        face.append(ids[co])
                    faces.append(tuple(face))
    return vertices, faces


def build_street_mesh(plan):
    """Return vertices, faces, material indices for road/footway/curb (0/1/2).

    Rectangle unions are partitioned in spatial tiles. Shared edges are split at
    all adjacent cell endpoints so the top surface has no T-junction cracks.
    The result is an open-bottom static surface, with exposed perimeter skirts.
    """
    settings = plan.settings
    size, walk = settings.block_size, settings.sidewalk_width
    nodes = junctions(plan)
    tiles = defaultdict(list)
    for rect in street_rectangles(plan):
        expanded = (rect[0] - walk, rect[1] - walk, rect[2] + walk, rect[3] + walk)
        for tx in range(math.floor(expanded[0] / size), math.floor(expanded[2] / size) + 1):
            for ty in range(math.floor(expanded[1] / size), math.floor(expanded[3] / size) + 1):
                tiles[tx, ty].append((rect, expanded))
    cells = []
    for (tx, ty), rectangles in sorted(tiles.items()):
        x0, y0, x1, y1 = tx * size, ty * size, (tx + 1) * size, (ty + 1) * size
        xs, ys = {x0, x1}, {y0, y1}
        for pair in rectangles:
            for rect in pair:
                xs.update(min(x1, max(x0, rect[i])) for i in (0, 2))
                ys.update(min(y1, max(y0, rect[i])) for i in (1, 3))
        # Insert the ramp start/end lines, so interpolation remains piecewise linear.
        for nx in (tx, tx + 1):
            for ny in (ty, ty + 1):
                if (nx, ny) in nodes:
                    for offset in (nodes[nx, ny] + walk, nodes[nx, ny] + walk + 2):
                        for sign in (-1, 1):
                            xs.add(min(x1, max(x0, nx * size + sign * offset)))
                            ys.add(min(y1, max(y0, ny * size + sign * offset)))
        xs, ys = sorted(xs), sorted(ys)
        for left, right in zip(xs, xs[1:]):
            for bottom, top in zip(ys, ys[1:]):
                cx, cy = (left + right) / 2, (bottom + top) / 2
                def inside(rect):
                    return rect[0] < cx < rect[2] and rect[1] < cy < rect[3]
                road = any(inside(pair[0]) for pair in rectangles)
                if road or any(inside(pair[1]) for pair in rectangles):
                    cells.append(((left, bottom, right, top), 0 if road else 1))

    horizontal, vertical = defaultdict(set), defaultdict(set)
    for (x0, y0, x1, y1), _ in cells:
        for y in (y0, y1):
            horizontal[y].update((x0, x1))
        for x in (x0, x1):
            vertical[x].update((y0, y1))
    vertices, faces, materials = [], [], []
    vertex_ids = {}
    boundaries = defaultdict(list)

    def vertex(co):
        co = tuple(round(v, 8) for v in co)
        if co not in vertex_ids:
            vertex_ids[co] = len(vertices)
            vertices.append(co)
        return vertex_ids[co]

    def face(points, mat):
        ids = list(dict.fromkeys(vertex(p) for p in points))
        if len(ids) >= 3:
            faces.append(tuple(ids))
            materials.append(mat)

    for (x0, y0, x1, y1), mat in cells:
        ring = ([(x, y0) for x in sorted(horizontal[y0]) if x0 <= x < x1] +
                [(x1, y) for y in sorted(vertical[x1]) if y0 <= y < y1] +
                [(x, y1) for x in sorted(horizontal[y1], reverse=True) if x0 < x <= x1] +
                [(x0, y) for y in sorted(vertical[x0], reverse=True) if y0 < y <= y1])
        points = [(x, y, 0 if mat == 0 else pavement_height(plan, x, y, nodes)) for x, y in ring]
        # A center fan preserves boundary splits when triangulated for Unity.
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        center = (cx, cy, 0 if mat == 0 else pavement_height(plan, cx, cy, nodes))
        for i, point in enumerate(points):
            next_point = points[(i + 1) % len(points)]
            face((center, point, next_point), mat)
            key = tuple(sorted((point[:2], next_point[:2])))
            boundaries[key].append((point, next_point))
    for edges in boundaries.values():
        if len(edges) == 1:
            a, b = edges[0]
            face((b, a, (a[0], a[1], -.2), (b[0], b[1], -.2)), 2)
        elif len(edges) == 2:
            (a, b), (c, d) = edges
            if a[2] > d[2] or b[2] > c[2]:
                face((b, a, d, c), 2)
            elif a[2] < d[2] or b[2] < c[2]:
                face((d, c, b, a), 2)
        else:
            raise ValueError('Overlapping street cells')
    return vertices, faces, materials
