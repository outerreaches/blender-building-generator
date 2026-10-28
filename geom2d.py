# SPDX-License-Identifier: GPL-3.0-or-later
"""2D helpers for the geometry core: profiles, polygons and contouring."""
import math

EPS = 1e-6


def interp(profile, u):
    """Height of a piecewise-linear profile [(u, z), ...] sorted by u."""
    if u <= profile[0][0]:
        return profile[0][1]
    if u >= profile[-1][0]:
        return profile[-1][1]
    low, high = 0, len(profile) - 1
    while high - low > 1:
        middle = (low + high) // 2
        if profile[middle][0] <= u:
            low = middle
        else:
            high = middle
    (u0, z0), (u1, z1) = profile[low], profile[high]
    if u1 - u0 < EPS:
        return min(z0, z1)
    return z0 + (z1 - z0) * (u - u0) / (u1 - u0)


def clean_profile(profile):
    """Sort a profile and merge points that share a position (keep the lower)."""
    points = sorted(profile)
    result = []
    for u, z in points:
        if result and abs(result[-1][0] - u) < EPS:
            result[-1] = (result[-1][0], min(result[-1][1], z))
        else:
            result.append((u, z))
    return result


def profile_min(a, b):
    """Pointwise minimum of two profiles, exact at their crossings."""
    us = sorted({u for u, _ in a} | {u for u, _ in b})
    lo = max(a[0][0], b[0][0])
    hi = min(a[-1][0], b[-1][0])
    us = [u for u in us if lo - EPS <= u <= hi + EPS]
    points = []
    for index, u in enumerate(us):
        za, zb = interp(a, u), interp(b, u)
        points.append((u, min(za, zb)))
        if index + 1 < len(us):
            u1 = us[index + 1]
            da = za - zb
            db = interp(a, u1) - interp(b, u1)
            if da * db < 0 and abs(da) > EPS and abs(db) > EPS:
                t = da / (da - db)
                uc = u + (u1 - u) * t
                points.append((uc, interp(a, uc)))
    return clean_profile(points)


def simplify(points, tolerance):
    """Douglas-Peucker on a polyline; endpoints are kept."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x0, y0), (x1, y1) = points[first], points[last]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or EPS
        worst, worst_index = -1.0, None
        for index in range(first + 1, last):
            x, y = points[index]
            distance = abs(dy * (x - x0) - dx * (y - y0)) / length
            if distance > worst:
                worst, worst_index = distance, index
        if worst_index is not None and worst > tolerance:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))
    return [point for point, flag in zip(points, keep) if flag]


def point_in_polygon(x, y, polygon):
    inside = False
    count = len(polygon)
    for index in range(count):
        x0, y0 = polygon[index]
        x1, y1 = polygon[(index + 1) % count]
        if (y0 > y) != (y1 > y):
            cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x < cross:
                inside = not inside
    return inside


def distance_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length = dx * dx + dy * dy
    t = 0.0 if length < EPS else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length))
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def distance_outside(x, y, polygon):
    """Distance from a point to a polygon; zero inside it."""
    if point_in_polygon(x, y, polygon):
        return 0.0
    count = len(polygon)
    return min(distance_to_segment(x, y, *polygon[index], *polygon[(index + 1) % count])
               for index in range(count))


def segment_crossings(ax, ay, bx, by, polygon):
    """Parameters t in (0, 1) where segment a-b crosses the polygon outline."""
    result = []
    count = len(polygon)
    rx, ry = bx - ax, by - ay
    for index in range(count):
        cx, cy = polygon[index]
        dx, dy = polygon[(index + 1) % count]
        sx, sy = dx - cx, dy - cy
        denominator = rx * sy - ry * sx
        if abs(denominator) < EPS:
            continue
        t = ((cx - ax) * sy - (cy - ay) * sx) / denominator
        s = ((cx - ax) * ry - (cy - ay) * rx) / denominator
        if EPS < t < 1 - EPS and -EPS <= s <= 1 + EPS:
            result.append(t)
    return sorted(result)


def marching_squares(xs, ys, values, masked=None):
    """Contour the region ``values >= 0`` over a rectilinear grid.

    ``values[i][j]`` is sampled at (xs[i], ys[j]); ``masked(i, j)`` removes a
    whole cell (holes). Returns (points, polygons): points maps vertex keys to
    (x, y), polygons are CCW lists of keys. Neighbouring cells derive shared
    crossings from the same grid edge, so the result tiles without cracks.
    """
    nx, ny = len(xs), len(ys)
    points = {}

    def value(i, j):
        v = values[i][j]
        return EPS if abs(v) < EPS else v

    def corner(i, j):
        key = ('c', i, j)
        if key not in points:
            points[key] = (xs[i], ys[j])
        return key

    def crossing(kind, i, j):
        key = (kind, i, j)
        if key not in points:
            if kind == 'h':
                v0, v1, a, b = value(i, j), value(i + 1, j), xs[i], xs[i + 1]
            else:
                v0, v1, a, b = value(i, j), value(i, j + 1), ys[j], ys[j + 1]
            t = max(.02, min(.98, v0 / (v0 - v1)))
            position = a + (b - a) * t
            points[key] = (position, ys[j]) if kind == 'h' else (xs[i], position)
        return key

    polygons = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            if masked is not None and masked(i, j):
                continue
            corners = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
            inside = [value(*c) >= 0 for c in corners]
            if not any(inside):
                continue
            if all(inside):
                polygons.append([corner(*c) for c in corners])
                continue
            edges = (('h', i, j), ('v', i + 1, j), ('h', i, j + 1), ('v', i, j))
            sequence = []
            for k in range(4):
                if inside[k]:
                    sequence.append(corner(*corners[k]))
                if inside[k] != inside[(k + 1) % 4]:
                    sequence.append(crossing(*edges[k]))
            saddle = inside == [True, False, True, False] or inside == [False, True, False, True]
            centre = sum(value(*c) for c in corners) / 4
            if saddle and centre < 0:
                # Two separate corners: split at the inside corners.
                for k in range(4):
                    if inside[k]:
                        before = crossing(*edges[(k - 1) % 4])
                        after = crossing(*edges[k])
                        polygons.append([before, corner(*corners[k]), after])
            else:
                polygons.append(sequence)
    return points, polygons
