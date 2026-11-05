# SPDX-License-Identifier: GPL-3.0-or-later
"""Rectilinear footprints made of rectangular wings (pure Python).

A footprint is a list of axis-aligned rectangles (x0, y0, x1, y1) that tile
the building's outline without overlapping. This module traces the outline
into edges (facade lines), says which corners are concave, gives each
facade's wall extent, and returns the interior region (the outline less the
walls) as rectangles; see docs/design/footprints.md.
"""
from dataclasses import dataclass

EPS = 1e-6
SIDE_OF_NORMAL = {(0, -1): 'front', (1, 0): 'right', (0, 1): 'back', (-1, 0): 'left'}


@dataclass
class Edge:
    side: str
    origin: tuple        # Start point; the facade runs along ``direction``.
    direction: tuple
    length: float
    concave: tuple       # (at start, at end): the outline turns in there.
    court: bool = False  # Faces into an enclosed court, not out to the street.

    @property
    def normal(self):
        return (self.direction[1], -self.direction[0])

    def point(self, u):
        return (self.origin[0] + self.direction[0] * u, self.origin[1] + self.direction[1] * u)


def bounds(wings):
    return (min(w[0] for w in wings), min(w[1] for w in wings),
            max(w[2] for w in wings), max(w[3] for w in wings))


def inside(wings, x, y):
    return any(w[0] - EPS < x < w[2] + EPS and w[1] - EPS < y < w[3] + EPS for w in wings)


def _strict_inside(wings, x, y):
    return any(w[0] < x < w[2] and w[1] < y < w[3] for w in wings)


def edges(wings):
    """The outline's edges, counter-clockwise round the outer ring (and round
    a court, facing into it); each is one straight facade line."""
    xs = sorted({v for w in wings for v in (w[0], w[2])})
    ys = sorted({v for w in wings for v in (w[1], w[3])})

    def cell(i, j):
        if i < 0 or j < 0 or i >= len(xs) - 1 or j >= len(ys) - 1:
            return False
        return _strict_inside(wings, (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2)
    # Unit boundary pieces keyed by their line, with the outward normal.
    pieces = {}
    for i in range(len(xs) - 1):
        for j in range(len(ys)):
            below, above = cell(i, j - 1), cell(i, j)
            if below != above:
                normal = (0, 1) if below else (0, -1)
                pieces.setdefault(('x', ys[j], normal), []).append((xs[i], xs[i + 1]))
    for j in range(len(ys) - 1):
        for i in range(len(xs)):
            left, right = cell(i - 1, j), cell(i, j)
            if left != right:
                normal = (1, 0) if left else (-1, 0)
                pieces.setdefault(('y', xs[i], normal), []).append((ys[j], ys[j + 1]))
    # Open ground reachable from beyond the bounding rectangle; the rest of
    # the ground inside it is a court.
    outside = set()
    pending = [(i, j) for i in range(-1, len(xs)) for j in (-1, len(ys) - 1)] + \
        [(i, j) for j in range(-1, len(ys)) for i in (-1, len(xs) - 1)]
    while pending:
        i, j = pending.pop()
        if (i, j) in outside or not (-1 <= i <= len(xs) - 1 and -1 <= j <= len(ys) - 1):
            continue
        if cell(i, j):
            continue
        outside.add((i, j))
        pending += [(i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)]

    def court_cell(x, y):
        i = next((k for k in range(len(xs) - 1) if xs[k] < x < xs[k + 1]), None)
        j = next((k for k in range(len(ys) - 1) if ys[k] < y < ys[k + 1]), None)
        return i is not None and j is not None and not cell(i, j) and (i, j) not in outside
    result = []
    for (axis, line, normal), spans in sorted(pieces.items()):
        spans.sort()
        merged = []
        for a, b in spans:
            if merged and abs(merged[-1][1] - a) < EPS:
                merged[-1] = (merged[-1][0], b)
            else:
                merged.append((a, b))
        for a, b in merged:
            direction = (-normal[1], normal[0])
            if axis == 'x':
                start = (a, line) if direction[0] > 0 else (b, line)
            else:
                start = (line, a) if direction[1] > 0 else (line, b)
            edge = Edge(SIDE_OF_NORMAL[normal], start, (float(direction[0]), float(direction[1])),
                        b - a, (False, False))
            edge.concave = (_concave(wings, edge, 0.0, -1), _concave(wings, edge, edge.length, 1))
            mx, my = edge.point(edge.length / 2)
            edge.court = court_cell(mx + normal[0] * 1e-3, my + normal[1] * 1e-3)
            result.append(edge)
    order = {'front': 0, 'right': 1, 'back': 2, 'left': 3}
    result.sort(key=lambda e: (order[e.side], -abs(_offset(e)), e.origin))
    return result


def _offset(edge):
    """How far out the edge stands on its side (for ordering: outermost first)."""
    nx, ny = edge.normal
    return edge.origin[0] * nx + edge.origin[1] * ny


def _concave(wings, edge, u, sign, eps=1e-3):
    """True when the outline turns in at this end: the edge's line carries on
    inside the footprint just past the end."""
    x, y = edge.point(u + sign * eps)
    nx, ny = edge.normal
    return _strict_inside(wings, x - nx * eps, y - ny * eps)


def wall_extent(edge, t):
    """(ua, ub) of the facade's wall solid along the edge.

    At a convex corner a front/back wall covers the corner square and a side
    wall stops ``t`` short of it; at a concave corner both end at the vertex.
    """
    along_x = edge.side in ('front', 'back')
    ua = 0.0 if (edge.concave[0] or along_x) else t
    ub = edge.length if (edge.concave[1] or along_x) else edge.length - t
    return ua, ub


def wall_rect(edge, t, ua=None, ub=None):
    """The wall solid's plan rectangle (outer face on the edge, ``t`` inward)."""
    if ua is None or ub is None:
        ua, ub = wall_extent(edge, t)
    (ax, ay), (bx, by) = edge.point(ua), edge.point(ub)
    nx, ny = edge.normal
    cx, cy = ax - nx * t, ay - ny * t
    xs = (ax, bx, cx + bx - ax, cx)
    ys = (ay, by, cy + by - ay, cy)
    return (min(xs), min(ys), max(xs), max(ys))


def interior(wings, t):
    """The interior region (the footprint less its walls) as rectangles."""
    walls = [wall_rect(edge, t) for edge in edges(wings)]
    xs = sorted({v for w in wings for v in (w[0], w[2])} | {v for r in walls for v in (r[0], r[2])})
    ys = sorted({v for w in wings for v in (w[1], w[3])} | {v for r in walls for v in (r[1], r[3])})
    xs, ys = _dedupe(xs), _dedupe(ys)

    def free(x, y):
        return _strict_inside(wings, x, y) and not any(
            r[0] < x < r[2] and r[1] < y < r[3] for r in walls)
    return _merge(xs, ys, free)


def complement(rect, rects):
    """``rect`` less ``rects``, as rectangles (slab holes round the interior)."""
    x0, y0, x1, y1 = rect
    xs = _dedupe(sorted({x0, x1} | {v for r in rects for v in (r[0], r[2]) if x0 < v < x1}))
    ys = _dedupe(sorted({y0, y1} | {v for r in rects for v in (r[1], r[3]) if y0 < v < y1}))

    def free(x, y):
        return not any(r[0] < x < r[2] and r[1] < y < r[3] for r in rects)
    return _merge(xs, ys, free)


def _dedupe(values):
    result = []
    for value in values:
        if not result or value - result[-1] > 1e-6:
            result.append(value)
    return result


def _merge(xs, ys, keep):
    """Grid cells where ``keep`` holds, merged into rectangles: runs along x,
    then runs with the same x extent stacked along y."""
    runs = []
    for j in range(len(ys) - 1):
        cy = (ys[j] + ys[j + 1]) / 2
        start = None
        for i in range(len(xs) - 1):
            on = keep((xs[i] + xs[i + 1]) / 2, cy)
            if on and start is None:
                start = i
            if not on and start is not None:
                runs.append((xs[start], ys[j], xs[i], ys[j + 1]))
                start = None
        if start is not None:
            runs.append((xs[start], ys[j], xs[-1], ys[j + 1]))
    merged = []
    for run in runs:
        for index, rect in enumerate(merged):
            if (abs(rect[0] - run[0]) < EPS and abs(rect[2] - run[2]) < EPS and
                    abs(rect[3] - run[1]) < EPS):
                merged[index] = (rect[0], rect[1], rect[2], run[3])
                break
        else:
            merged.append(run)
    return merged


# -- zones -------------------------------------------------------------------

@dataclass
class Zone:
    """A wing's share of the interior, for planning (see the design note)."""
    index: int
    rect: tuple
    axis: str            # 'x' or 'y': the way its corridor runs.
    joints: list         # (other zone, this zone's side, lo, hi) along the side.


def _shared(wings, k, side):
    """(other wing, lo, hi) spans where another wing touches wing ``k``
    across ``side``."""
    x0, y0, x1, y1 = wings[k]
    result = []
    for j, (a0, b0, a1, b1) in enumerate(wings):
        if j == k:
            continue
        if side == 'front' and abs(b1 - y0) < EPS:
            lo, hi = max(x0, a0), min(x1, a1)
        elif side == 'back' and abs(b0 - y1) < EPS:
            lo, hi = max(x0, a0), min(x1, a1)
        elif side == 'left' and abs(a1 - x0) < EPS:
            lo, hi = max(y0, b0), min(y1, b1)
        elif side == 'right' and abs(a0 - x1) < EPS:
            lo, hi = max(y0, b0), min(y1, b1)
        else:
            continue
        if hi - lo > EPS:
            result.append((j, lo, hi))
    return result


def _span(wing, side):
    x0, y0, x1, y1 = wing
    return (x0, x1) if side in ('front', 'back') else (y0, y1)


def _fully_joint(wings, k, side):
    lo, hi = _span(wings[k], side)
    cursor = lo
    for _, a, b in sorted(_shared(wings, k, side), key=lambda item: item[1]):
        if a > cursor + EPS:
            return False
        cursor = max(cursor, b)
    return cursor >= hi - EPS


OPPOSITE = {'front': 'back', 'back': 'front', 'left': 'right', 'right': 'left'}


def zones(wings, t):
    """Each wing's planning zone: its rectangle inset by ``t`` on any side
    that is (partly) exterior; a side wholly against other wings reaches
    across the joint to their zones (which are inset there)."""
    result = []
    for k, wing in enumerate(wings):
        x0, y0, x1, y1 = wing
        rect = {'front': y0, 'back': y1, 'left': x0, 'right': x1}
        sign = {'front': 1, 'back': -1, 'left': 1, 'right': -1}     # Inward.
        joints = []
        for side in ('front', 'right', 'back', 'left'):
            shared = _shared(wings, k, side)
            joints += [(j, side, a, b) for j, a, b in shared]
            if not _fully_joint(wings, k, side):
                rect[side] += sign[side] * t
            elif all(not _fully_joint(wings, j, OPPOSITE[side]) for j, _, _ in shared):
                rect[side] -= sign[side] * t
        zone = (rect['left'], rect['front'], rect['right'], rect['back'])
        width, depth = zone[2] - zone[0], zone[3] - zone[1]
        if k == 0:
            axis = 'x'
        else:
            sides = {side for _, side, _, _ in joints}
            if {'front', 'back'} <= sides:
                axis = 'y'
            elif {'left', 'right'} <= sides:
                axis = 'x'
            else:
                along = 'x' if sides & {'front', 'back'} else 'y'
                length, across = (width, depth) if along == 'x' else (depth, width)
                # A bar along the joint, else a wing off it.
                axis = along if length >= 2 * across else ('y' if along == 'x' else 'x')
        result.append(Zone(k, zone, axis, joints))
    return result


# -- shapes ------------------------------------------------------------------

SHAPES = ('RECT', 'L', 'T', 'U', 'O')


def wings_for(shape, width, depth, arm, main=None, mirror=False):
    """Wings for a ``shape`` over a ``width`` x ``depth`` lot: ``main`` is the
    front bar's depth, ``arm`` the width of the wings off it (and of a
    courtyard's back bar). ``mirror`` puts an L's wing on the right."""
    main = main or arm
    if shape == 'RECT' or arm >= width or main >= depth:
        return [(0.0, 0.0, width, depth)]
    if shape in ('U', 'O') and 2 * arm >= width - 4.0:
        return [(0.0, 0.0, width, depth)]        # No room for the gap between the arms.
    if shape == 'O' and main + arm >= depth - 4.0:
        return [(0.0, 0.0, width, depth)]        # No room for the court.
    if shape == 'L':
        x0, x1 = (width - arm, width) if mirror else (0.0, arm)
        return [(0.0, 0.0, width, main), (x0, main, x1, depth)]
    if shape == 'T':
        x0 = (width - arm) / 2
        return [(0.0, 0.0, width, main), (x0, main, x0 + arm, depth)]
    if shape == 'U':
        return [(0.0, 0.0, width, main), (0.0, main, arm, depth), (width - arm, main, width, depth)]
    if shape == 'O':
        back = depth - arm
        return [(0.0, 0.0, width, main), (0.0, back, width, depth),
                (0.0, main, arm, back), (width - arm, main, width, back)]
    raise ValueError(f'Unknown footprint shape: {shape}')
