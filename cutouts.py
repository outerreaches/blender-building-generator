# SPDX-License-Identifier: GPL-3.0-or-later
"""Cut rectangular openings out of a surface mesh (the ground over a
basement). Pure Python: works on vertex and face lists.

A face crossing an opening's edge is split along it; the new vertices take
their height from the face's own edges, so what is left of the surface is
where it was.
"""
import math


def _clip(polygon, axis, limit, keep_below):
    """Sutherland-Hodgman against one line of the opening's frame: points are
    (u, v, z, index); ``index`` is None for a point made by a cut."""
    result = []
    count = len(polygon)
    for i in range(count):
        a, b = polygon[i], polygon[(i + 1) % count]
        da, db = a[axis] - limit, b[axis] - limit
        ina = da <= 0 if keep_below else da >= 0
        inb = db <= 0 if keep_below else db >= 0
        if ina:
            result.append(a)
        if ina != inb:
            t = da / (da - db)
            result.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
                           a[2] + (b[2] - a[2]) * t, None))
    return result


def _area(polygon):
    return abs(sum(polygon[i][0] * polygon[(i + 1) % len(polygon)][1] -
                   polygon[(i + 1) % len(polygon)][0] * polygon[i][1]
                   for i in range(len(polygon)))) / 2


def cut(vertices, faces, openings, least=1e-4):
    """Faces of the mesh outside every opening; vertices made by the cuts are
    appended to ``vertices``. An opening is (centre x, centre y, width, depth,
    rotation): a rectangle turned about its centre. Returns the new face
    list and, for each, the index of the face it came from."""
    if not openings:
        return list(faces), list(range(len(faces)))
    frames = []
    for cx, cy, width, depth, rotation in openings:
        frames.append((cx, cy, width / 2, depth / 2, math.cos(rotation), math.sin(rotation),
                       math.hypot(width, depth) / 2))
    # Openings by coarse cell, to find the few a face may touch.
    cell = max(8.0, max(frame[6] for frame in frames) * 2)
    grid = {}
    for number, frame in enumerate(frames):
        cx, cy, reach = frame[0], frame[1], frame[6]
        for i in range(math.floor((cx - reach) / cell), math.floor((cx + reach) / cell) + 1):
            for j in range(math.floor((cy - reach) / cell), math.floor((cy + reach) / cell) + 1):
                grid.setdefault((i, j), []).append(number)
    kept, sources = [], []
    for source, face in enumerate(faces):
        xs = [vertices[i][0] for i in face]
        ys = [vertices[i][1] for i in face]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        near = set()
        for i in range(math.floor(x0 / cell), math.floor(x1 / cell) + 1):
            for j in range(math.floor(y0 / cell), math.floor(y1 / cell) + 1):
                near.update(grid.get((i, j), ()))
        if not near:
            kept.append(face)
            sources.append(source)
            continue
        pieces = [[(vertices[i][0], vertices[i][1], vertices[i][2], i) for i in face]]
        whole = True
        for number in sorted(near):
            cx, cy, hw, hd, c, s, reach = frames[number]
            if x0 > cx + reach or x1 < cx - reach or y0 > cy + reach or y1 < cy - reach:
                continue
            following = []
            for piece in pieces:
                local = [((x - cx) * c + (y - cy) * s, -(x - cx) * s + (y - cy) * c, z, index)
                         for x, y, z, index in piece]
                us = [p[0] for p in local]
                vs = [p[1] for p in local]
                if min(us) >= hw or max(us) <= -hw or min(vs) >= hd or max(vs) <= -hd:
                    following.append(piece)
                    continue
                whole = False
                parts = [_clip(local, 0, -hw, True)]
                rest = _clip(local, 0, -hw, False)
                parts.append(_clip(rest, 0, hw, False))
                rest = _clip(rest, 0, hw, True)
                parts.append(_clip(rest, 1, -hd, True))
                rest = _clip(rest, 1, -hd, False)
                parts.append(_clip(rest, 1, hd, False))
                for part in parts:
                    if len(part) >= 3 and _area(part) > least:
                        following.append([(cx + u * c - v * s, cy + u * s + v * c, z, index)
                                          for u, v, z, index in part])
            pieces = following
        if whole:
            kept.append(face)
            sources.append(source)
            continue
        for piece in pieces:
            indices = []
            for x, y, z, index in piece:
                if index is None:
                    vertices.append((x, y, z))
                    index = len(vertices) - 1
                indices.append(index)
            kept.append(tuple(indices))
            sources.append(source)
    return kept, sources
