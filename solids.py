# SPDX-License-Identifier: GPL-3.0-or-later
"""Closed solids for the geometry core.

Every function here emits a watertight, consistently wound solid: each edge is
shared by exactly two faces. Walls are built from their 2D outline (a top
profile minus openings) rather than cut and patched afterwards, so damage and
openings of any polygonal shape cannot leave holes.
"""
import math
from dataclasses import dataclass

from . import geom2d
from .meshdata import MAT_WALLS

EPS = 1e-6


@dataclass
class Opening:
    """A hole through a wall, x-monotone: bottom and top are polylines in (u, z).

    Rectangles are the common case; breaches use jagged polylines. ``frame``
    is the material of the reveal faces.
    """
    u0: float
    u1: float
    bottom: list
    top: list
    frame: int
    kind: str = 'window'

    @classmethod
    def rect(cls, u0, u1, z0, z1, frame, kind='window'):
        return cls(u0, u1, [(u0, z0), (u1, z0)], [(u0, z1), (u1, z1)], frame, kind)


class _Line:
    __slots__ = ('points', 'u0', 'u1', 'kind', 'material')

    def __init__(self, points, kind, material=None):
        self.points = points
        self.u0, self.u1 = points[0][0], points[-1][0]
        self.kind = kind
        self.material = material

    def at(self, u):
        return geom2d.interp(self.points, u)


def wall_solid(mesh, origin, direction, thickness, ua, ub, base, top, openings=(),
               material=MAT_WALLS, top_material=None):
    """Build one wall as a closed solid.

    ``origin`` (x, y) is the outer face at u = 0, ``direction`` the unit wall
    direction; the outward normal is direction x up. The outline is
    {ua <= u <= ub, base <= z <= top(u)} minus the openings. The outline is
    split into columns at every profile/opening vertex and every crossing, so
    within a column all boundary lines are straight and keep their order.
    Faces carry every vertex that lies on their sides, so neighbours meet
    without T-junctions.
    """
    if ub - ua < 1e-4:
        return
    top_material = material if top_material is None else top_material
    top_line = _Line(geom2d.clean_profile(
        [(ua, geom2d.interp(top, ua))] +
        [(u, z) for u, z in top if ua < u < ub] +
        [(ub, geom2d.interp(top, ub))]), 'top')
    base_line = _Line([(ua, base), (ub, base)], 'base')
    holes = []
    for opening in openings:
        u0, u1 = max(opening.u0, ua), min(opening.u1, ub)
        if u1 - u0 < 1e-4:
            continue

        def clip(line):
            inner = [(u, z) for u, z in line if u0 < u < u1]
            return geom2d.clean_profile(
                [(u0, geom2d.interp(line, u0))] + inner + [(u1, geom2d.interp(line, u1))])

        holes.append((_Line(clip(opening.bottom), 'open_bottom', opening.frame),
                      _Line(clip(opening.top), 'open_top', opening.frame)))

    breaks = {ua, ub}
    breaks.update(u for u, _ in top_line.points)
    for bottom, upper in holes:
        breaks.update(u for u, _ in bottom.points)
        breaks.update(u for u, _ in upper.points)
    us = _unique(sorted(breaks))
    # Crossings of the top profile with the base and with opening outlines.
    crossings = []
    for index in range(len(us) - 1):
        ul, ur = us[index], us[index + 1]
        others = [base_line] + [line for hole in holes for line in hole
                                if line.u0 <= ul + EPS and line.u1 >= ur - EPS]
        tl, tr = top_line.at(ul), top_line.at(ur)
        for line in others:
            dl, dr = tl - line.at(ul), tr - line.at(ur)
            if dl * dr < 0 and abs(dl) > EPS and abs(dr) > EPS:
                crossings.append(ul + (ur - ul) * dl / (dl - dr))
    if crossings:
        us = _unique(sorted(set(us) | set(crossings)))

    # Solid runs per column: (lower, upper), each bound = (zl, zr, kind, material).
    columns = []
    for index in range(len(us) - 1):
        ul, ur = us[index], us[index + 1]
        um = (ul + ur) / 2
        t_l, t_r, t_m = top_line.at(ul), top_line.at(ur), top_line.at(um)
        cuts = []
        for bottom, upper in holes:
            if bottom.u0 <= ul + EPS and bottom.u1 >= ur - EPS:
                cuts.append(((bottom.at(ul), bottom.at(ur), bottom.at(um)),
                             (upper.at(ul), upper.at(ur), upper.at(um)), bottom.material))
        cuts.sort(key=lambda cut: cut[0][2])
        runs = []
        lower = (base, base, base, 'base', None)
        finished = t_m <= base + EPS
        for low, high, frame in cuts:
            if finished:
                break
            if low[2] > lower[2] + EPS:
                if low[2] >= t_m - EPS:
                    runs.append((lower, (t_l, t_r, t_m, 'top', None)))
                    finished = True
                    break
                runs.append((lower, (low[0], low[1], low[2], 'open', frame)))
            if high[2] > lower[2]:
                lower = (high[0], high[1], high[2], 'open', frame)
            if lower[2] >= t_m - EPS:
                finished = True
        if not finished and lower[2] < t_m - EPS:
            runs.append((lower, (t_l, t_r, t_m, 'top', None)))
        cleaned = []
        for low, high in runs:
            zl0, zr0 = low[0], low[1]
            zl1, zr1 = max(high[0], zl0), max(high[1], zr0)
            if zl1 - zl0 < EPS and zr1 - zr0 < EPS:
                continue
            cleaned.append(((zl0, zr0, low[3], low[4]), (zl1, zr1, high[3], high[4])))
        columns.append((cleaned, cuts))

    # Canonical z values on each vertical line.
    lines = [[] for _ in us]
    for index, (runs, _) in enumerate(columns):
        for low, high in runs:
            lines[index].extend((low[0], high[0]))
            lines[index + 1].extend((low[1], high[1]))
    lines = [_unique(sorted(values)) for values in lines]

    ox, oy = origin
    dx, dy = direction
    nx, ny = dy, -dx
    registry = {}

    def canon(j, z):
        values = lines[j]
        low, high = 0, len(values) - 1
        while high - low > 1:
            middle = (low + high) // 2
            if values[middle] <= z:
                low = middle
            else:
                high = middle
        best = low if abs(values[low] - z) <= abs(values[high] - z) else high
        return best

    def vertex(j, k, inner):
        key = (j, k, inner)
        index = registry.get(key)
        if index is None:
            u, z = us[j], lines[j][k]
            x, y = ox + dx * u, oy + dy * u
            if inner:
                x -= nx * thickness
                y -= ny * thickness
            index = registry[key] = mesh.vert((x, y, z))
        return index

    def strip(a, b, frame):
        """Quad joining outline edge a->b (solid on its left) to the inner face."""
        mesh.face((vertex(*b, False), vertex(*a, False), vertex(*a, True), vertex(*b, True)),
                  frame)

    for index, (runs, cuts) in enumerate(columns):
        j0, j1 = index, index + 1
        for low, high in runs:
            bl = (j0, canon(j0, low[0]))
            br = (j1, canon(j1, low[1]))
            tr = (j1, canon(j1, high[1]))
            tl = (j0, canon(j0, high[0]))
            loop = [bl, br]
            loop.extend((j1, k) for k in range(br[1] + 1, tr[1]))
            loop.extend([tr, tl])
            loop.extend((j0, k) for k in range(tl[1] - 1, bl[1], -1))
            mesh.face([vertex(j, k, False) for j, k in loop], material)
            mesh.face([vertex(j, k, True) for j, k in reversed(loop)], material)
            strip(bl, br, material if low[2] == 'base' else low[3])
            strip(tr, tl, top_material if high[2] == 'top' else high[3])

    def solid_at(column, j, z_low, z_high, side):
        if column < 0 or column >= len(columns):
            return False
        for low, high in columns[column][0]:
            if side == 'left':
                lo, hi = low[0], high[0]
            else:
                lo, hi = low[1], high[1]
            if lo <= z_low + EPS and hi >= z_high - EPS:
                return True
        return False

    def frame_of(column, z):
        if column < 0 or column >= len(columns):
            return material
        for low, high, frame in columns[column][1]:
            if min(low[0], low[1]) - EPS <= z <= max(high[0], high[1]) + EPS:
                return frame
        return material

    for j in range(len(us)):
        values = lines[j]
        for k in range(len(values) - 1):
            z_low, z_high = values[k], values[k + 1]
            left = solid_at(j - 1, j, z_low, z_high, 'right')
            right = solid_at(j, j, z_low, z_high, 'left')
            if left == right:
                continue
            middle = (z_low + z_high) / 2
            if left:
                strip((j, k), (j, k + 1), frame_of(j, middle))
            else:
                strip((j, k + 1), (j, k), frame_of(j - 1, middle))


def _unique(values, tolerance=1e-6):
    result = []
    for value in values:
        if not result or value - result[-1] > tolerance:
            result.append(value)
    return result


def slab_solid(mesh, xs, ys, z_bottom, z_top, field, material, holes=()):
    """Floor plate over a rectilinear grid where ``field(x, y) >= 0``.

    ``holes`` are (x0, y0, x1, y1) rectangles aligned to grid lines. Broken
    edges follow the contour of the field, so damaged slabs end in polygonal
    (diagonal) edges rather than grid steps.
    """
    if z_top - z_bottom < 1e-4 or len(xs) < 2 or len(ys) < 2:
        return
    values = [[field(x, y) for y in ys] for x in xs]

    def masked(i, j):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2
        return any(x0 < cx < x1 and y0 < cy < y1 for x0, y0, x1, y1 in holes)

    points, polygons = geom2d.marching_squares(xs, ys, values, masked)
    top, bottom = {}, {}

    def vertex(key, upper):
        table = top if upper else bottom
        index = table.get(key)
        if index is None:
            x, y = points[key]
            index = table[key] = mesh.vert((x, y, z_top if upper else z_bottom))
        return index

    used = {}
    for polygon in polygons:
        for position, key in enumerate(polygon):
            following = polygon[(position + 1) % len(polygon)]
            edge = (key, following) if key < following else (following, key)
            used[edge] = used.get(edge, 0) + 1
    for polygon in polygons:
        mesh.face([vertex(key, True) for key in polygon], material)
        mesh.face([vertex(key, False) for key in reversed(polygon)], material)
        for position, key in enumerate(polygon):
            following = polygon[(position + 1) % len(polygon)]
            edge = (key, following) if key < following else (following, key)
            if used[edge] == 1:
                mesh.face((vertex(following, True), vertex(key, True),
                           vertex(key, False), vertex(following, False)), material)


def box(mesh, x0, y0, z0, x1, y1, z1, material):
    if x1 - x0 < 1e-5 or y1 - y0 < 1e-5 or z1 - z0 < 1e-5:
        return
    hexahedron(mesh, [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
                      (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)], material)


def hexahedron(mesh, corners, material, materials=None):
    """Closed six-sided solid: corners 0-3 bottom CCW from above, 4-7 above them.

    ``materials`` optionally overrides per face: bottom, top, front, right,
    back, left.
    """
    v = [mesh.vert(co) for co in corners]
    faces = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7))
    for index, face in enumerate(faces):
        mesh.face([v[i] for i in face], material if materials is None else materials[index])


def prism(mesh, outline, z0, z1, material, top_material=None):
    """Vertical prism over a CCW polygon outline."""
    if z1 - z0 < 1e-5 or len(outline) < 3:
        return
    bottom = [mesh.vert((x, y, z0)) for x, y in outline]
    upper = [mesh.vert((x, y, z1)) for x, y in outline]
    mesh.face(list(reversed(bottom)), material)
    mesh.face(upper, material if top_material is None else top_material)
    count = len(outline)
    for index in range(count):
        following = (index + 1) % count
        mesh.face((bottom[index], bottom[following], upper[following], upper[index]), material)


def frustum(mesh, bottom, top, z0, z1, material, top_material=None):
    """Closed solid between two CCW outlines with the same vertex count."""
    if z1 - z0 < 1e-5 or len(bottom) < 3 or len(bottom) != len(top):
        return
    lower = [mesh.vert((x, y, z0)) for x, y in bottom]
    upper = [mesh.vert((x, y, z1)) for x, y in top]
    mesh.face(list(reversed(lower)), material)
    mesh.face(upper, material if top_material is None else top_material)
    count = len(bottom)
    for index in range(count):
        following = (index + 1) % count
        mesh.face((lower[index], lower[following], upper[following], upper[index]), material)


def circle(cx, cy, radius, segments=8, phase=0.0):
    """CCW polygon approximating a circle."""
    return [(cx + math.cos(phase + math.tau * k / segments) * radius,
             cy + math.sin(phase + math.tau * k / segments) * radius) for k in range(segments)]


def cylinder(mesh, cx, cy, radius, z0, z1, material, segments=8):
    prism(mesh, circle(cx, cy, radius, segments), z0, z1, material)
