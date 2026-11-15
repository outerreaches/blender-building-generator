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


def lift(vertices, faces, materials, boxes, material, gap=.02):
    """Shorten the vertical faces of one material (street skirts) where they
    hang into something underground: over each box (world rect, top) a
    face's bottom is raised to ``gap`` above ``top``, and a piece left with
    nothing to show is dropped. A face is split where it crosses a box's
    side. New vertices are appended to ``vertices``; returns the new faces
    and their materials."""
    if not boxes:
        return list(faces), list(materials)
    kept, kinds = [], []
    for face, kind in zip(faces, materials):
        corners = _skirt(vertices, face) if kind == material else None
        hit = []
        if corners is not None:
            top_p, top_q = vertices[corners[0]], vertices[corners[1]]
            for rect, top in boxes:
                span = _segment_span(top_p, top_q, rect)
                if span is not None:
                    hit.append((span, top))
        if not hit:
            kept.append(face)
            kinds.append(kind)
            continue
        tp, tq, bq, bp = corners
        cuts = sorted({0.0, 1.0} | {t for span, _ in hit for t in span})

        def at(i, j, t):
            a, b = vertices[i], vertices[j]
            return tuple(a[k] + (b[k] - a[k]) * t for k in range(3))

        for u0, u1 in zip(cuts, cuts[1:]):
            if u1 - u0 < 1e-9:
                continue
            mid = (u0 + u1) / 2
            floor = max((top + gap for (s0, s1), top in hit if s0 <= mid <= s1), default=None)
            a_top, b_top = at(tp, tq, u0), at(tp, tq, u1)
            a_low, b_low = at(bp, bq, u0), at(bp, bq, u1)
            if floor is not None:
                a_low = (a_low[0], a_low[1], max(floor, a_low[2]))
                b_low = (b_low[0], b_low[1], max(floor, b_low[2]))
                if a_low[2] >= a_top[2] - 1e-3 or b_low[2] >= b_top[2] - 1e-3:
                    continue
            piece = []
            for co, original in ((a_top, tp if u0 == 0.0 else None), (b_top, tq if u1 == 1.0 else None),
                                 (b_low, bq if u1 == 1.0 and floor is None else None),
                                 (a_low, bp if u0 == 0.0 and floor is None else None)):
                if original is None:
                    vertices.append(co)
                    original = len(vertices) - 1
                piece.append(original)
            kept.append(tuple(piece))
            kinds.append(kind)
    return kept, kinds


def _skirt(vertices, face):
    """A vertical quad's corners as (top p, top q, bottom under q, bottom
    under p) in the face's own winding, else None."""
    if len(face) != 4:
        return None
    for k in range(4):
        a, b, c, d = (vertices[face[(k + i) % 4]] for i in range(4))
        if (abs(b[0] - c[0]) < 1e-6 and abs(b[1] - c[1]) < 1e-6 and
                abs(a[0] - d[0]) < 1e-6 and abs(a[1] - d[1]) < 1e-6 and
                b[2] > c[2] + 1e-6 and a[2] > d[2] + 1e-6 and math.dist(a[:2], b[:2]) > 1e-6):
            return tuple(face[(k + i) % 4] for i in range(4))
    return None


def _segment_span(p, q, rect):
    """Where segment pq (in plan) lies inside a rectangle, as (t0, t1), else None."""
    t0, t1 = 0.0, 1.0
    for d, lo, hi, start in ((q[0] - p[0], rect[0], rect[2], p[0]), (q[1] - p[1], rect[1], rect[3], p[1])):
        if abs(d) < 1e-12:
            if start <= lo or start >= hi:
                return None
            continue
        a, b = (lo - start) / d, (hi - start) / d
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 >= t1:
            return None
    return (t0, t1)
