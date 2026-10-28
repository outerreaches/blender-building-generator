# SPDX-License-Identifier: GPL-3.0-or-later
"""Rubble as closed solids: mounds, piles, fills and the collapsed-lot heap."""
import math

from . import solids
from .meshdata import MAT_RUBBLE


def mound(mesh, rng, cx, cy, rx, ry, peak, segments=10, rings=3, base=0.0):
    """Jittered rubble mound with a flat underside."""
    angles = [math.tau * index / segments for index in range(segments)]
    jitter = [rng.uniform(.82, 1.15) for _ in range(segments)]
    apex = mesh.vert((cx + rng.uniform(-.15, .15) * rx, cy + rng.uniform(-.15, .15) * ry,
                      base + peak))
    rows = []
    for ring in range(1, rings + 1):
        t = ring / rings
        height = 0.0 if ring == rings else peak * (1 - t) ** 1.3 * rng.uniform(.9, 1.08)
        rows.append([mesh.vert((cx + math.cos(a) * rx * t * jitter[i],
                                cy + math.sin(a) * ry * t * jitter[i], base + max(0.0, height)))
                     for i, a in enumerate(angles)])
    for index in range(segments):
        following = (index + 1) % segments
        mesh.face((apex, rows[0][index], rows[0][following]), MAT_RUBBLE)
    for ring in range(1, rings):
        inner, outer = rows[ring - 1], rows[ring]
        for index in range(segments):
            following = (index + 1) % segments
            mesh.face((inner[index], outer[index], outer[following], inner[following]), MAT_RUBBLE)
    mesh.face(list(reversed(rows[-1])), MAT_RUBBLE)


def pile(mesh, rng, cx, cy, radius, height, base=0.0):
    """Small irregular cone of debris."""
    sides = rng.randint(5, 7)
    ring = []
    for index in range(sides):
        angle = math.tau * index / sides + rng.uniform(-.3, .3) / sides * 3
        r = radius * rng.uniform(.7, 1.0)
        ring.append(mesh.vert((cx + r * math.cos(angle), cy + r * math.sin(angle), base)))
    apex = mesh.vert((cx + rng.uniform(-.3, .3) * radius, cy + rng.uniform(-.3, .3) * radius,
                      base + height * rng.uniform(.8, 1.0)))
    mesh.face(list(reversed(ring)), MAT_RUBBLE)
    for index in range(sides):
        mesh.face((ring[index], ring[(index + 1) % sides], apex), MAT_RUBBLE)


def slanted_fill(mesh, rng, rect, height, cap):
    """Box of rubble with a tilted, uneven top (partially filled storeys)."""
    x0, y0, x1, y1 = rect
    sx, sy = rng.uniform(-.3, .3), rng.uniform(-.3, .3)
    heights = []
    for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        h = height + sx * (x - x0) + sy * (y - y0) + rng.uniform(-.2, .2)
        heights.append(min(cap, max(.3, h)))
    corners = [(x0, y0, 0.0), (x1, y0, 0.0), (x1, y1, 0.0), (x0, y1, 0.0)]
    corners += [(x, y, h) for (x, y, _), h in zip(corners, heights)]
    solids.hexahedron(mesh, corners, MAT_RUBBLE)


def interior_fill(mesh, rng, spec, field, params):
    """FILLED / PARTIAL / RUBBLE_PILES interiors, kept below the damage line."""
    mode = params.get('interior_fill', 'NONE')
    if mode == 'NONE':
        return
    x0, y0, x1, y1 = spec.interior_rect(0)
    # Inset so the fill never shares a plane with slab edges or wall faces.
    rect = (x0 + .03, y0 + .03, x1 - .03, y1 - .03)
    cap = min(spec.top - .1, field.lowest() - .1)
    if params.get('has_patio') and len(spec.levels) >= 2:
        cap = min(cap, spec.levels[-1].z - .1)
    if mode == 'FILLED':
        solids.box(mesh, rect[0], rect[1], 0.0, rect[2], rect[3], max(.3, cap), MAT_RUBBLE)
    elif mode == 'PARTIAL':
        floors = len(spec.levels)
        fill = min(int(params.get('fill_floors', max(1, floors // 2))), floors - 1)
        if fill > 0:
            height = min(spec.levels[fill].z - rng.uniform(.3, .6), cap - .5)
            slanted_fill(mesh, rng, rect, height, cap)
    elif mode == 'RUBBLE_PILES':
        x0, y0, x1, y1 = rect
        density = float(params.get('rubble_density', .3))
        placed = []
        for _ in range(min(5, 2 + int(density * 3))):
            for _attempt in range(10):
                cx, cy = rng.uniform(x0 + .8, x1 - .8), rng.uniform(y0 + .8, y1 - .8)
                radius = rng.uniform(.4, min(1.2, min(x1 - x0, y1 - y0) * .25))
                if all(math.hypot(cx - px, cy - py) >= (radius + pr) * .8 for px, py, pr in placed):
                    placed.append((cx, cy, radius))
                    pile(mesh, rng, cx, cy, radius, rng.uniform(.3, .8))
                    break


def exterior_piles(mesh, rng, spec, params):
    if not params.get('exterior_rubble', False):
        return
    width, depth = spec.width, spec.depth
    spread = float(params.get('rubble_spread', 2.0))
    for _ in range(int(params.get('exterior_rubble_piles', 4))):
        side = rng.randrange(4)
        if side == 0:
            x, y = rng.uniform(.5, width - .5), rng.uniform(-spread * .8, -.3)
        elif side == 1:
            x, y = rng.uniform(.5, width - .5), rng.uniform(depth + .3, depth + spread * .8)
        elif side == 2:
            x, y = rng.uniform(-spread * .8, -.3), rng.uniform(.5, depth - .5)
        else:
            x, y = rng.uniform(width + .3, width + spread * .8), rng.uniform(.5, depth - .5)
        pile(mesh, rng, x, y, rng.uniform(.4, 1.0), rng.uniform(.2, .6))


def corner_mound(mesh, rng, spec, corner):
    """Debris at the foot of a collapsed corner."""
    sign_x, sign_y = corner
    width, depth = spec.width, spec.depth
    cx = (0 if sign_x < 0 else width) - sign_x * width * .12
    cy = (0 if sign_y < 0 else depth) - sign_y * depth * .12
    mound(mesh, rng, cx, cy, width * rng.uniform(.2, .34), depth * rng.uniform(.2, .34),
          rng.uniform(1.4, 3.0), segments=9)


def interior_mound(mesh, rng, spec):
    """Mound inside a standing wall ring, visible from above."""
    x0, y0, x1, y1 = spec.interior_rect(0)
    peak = min(spec.top * .55, rng.uniform(1.8, 3.6))
    mound(mesh, rng, (x0 + x1) / 2, (y0 + y1) / 2, max(1.5, (x1 - x0) / 2 - .5),
          max(1.5, (y1 - y0) / 2 - .5), peak)


def collapsed_lot(mesh, rng, width, depth):
    """Overlapping low mounds where a building came down (centred on the lot)."""
    scale = rng.uniform(.38, .5)
    mound(mesh, rng, rng.uniform(-.06, .06) * width, rng.uniform(-.06, .06) * depth,
          width * scale, depth * scale, rng.uniform(2.0, 3.4), segments=12)
    mound(mesh, rng, rng.uniform(-.2, .2) * width, rng.uniform(-.2, .2) * depth,
          width * scale * rng.uniform(.45, .65), depth * scale * rng.uniform(.45, .65),
          rng.uniform(.8, 1.6), segments=12)
    if rng.random() < .6:
        mound(mesh, rng, rng.uniform(-.24, .24) * width, rng.uniform(-.24, .24) * depth,
              width * scale * rng.uniform(.3, .5), depth * scale * rng.uniform(.3, .5),
              rng.uniform(.5, 1.1), segments=12)
