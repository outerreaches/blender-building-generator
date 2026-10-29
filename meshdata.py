# SPDX-License-Identifier: GPL-3.0-or-later
"""Plain-Python mesh container shared by the geometry core.

The generator builds every building as a list of closed solids in this
container and converts it to a BMesh once at the end. Keeping the core free of
``bpy``/``bmesh`` means watertightness and layout rules can be unit-tested
without Blender.
"""
from collections import Counter

# Material slot indices (match building_assets.MATERIALS).
MAT_WALLS = 0
MAT_FLOOR = 1
MAT_ROOF = 2
MAT_WINDOW_FRAME = 3
MAT_DOOR_FRAME = 4
MAT_INTERIOR_WALL = 5
MAT_STAIRS = 6
MAT_RUBBLE = 7


class MeshData:
    """Vertices and polygon faces; faces are (vertex indices, material)."""

    def __init__(self):
        self.verts = []
        self.faces = []

    def vert(self, co):
        self.verts.append((float(co[0]), float(co[1]), float(co[2])))
        return len(self.verts) - 1

    def face(self, indices, material):
        indices = tuple(indices)
        # Drop repeated consecutive vertices (degenerate corners of triangles
        # cut from quads); a face needs three distinct corners.
        cleaned = [index for position, index in enumerate(indices)
                   if index != indices[position - 1]]
        if len(cleaned) >= 3 and len(set(cleaned)) == len(cleaned):
            self.faces.append((tuple(cleaned), material))

    def extend(self, other):
        offset = len(self.verts)
        self.verts.extend(other.verts)
        self.faces.extend((tuple(index + offset for index in face), material)
                          for face, material in other.faces)

    def directed_edges(self):
        counts = Counter()
        for face, _ in self.faces:
            for position, index in enumerate(face):
                counts[(index, face[(position + 1) % len(face)])] += 1
        return counts

    def open_edges(self, ignore_materials=()):
        """Directed edges with no opposite partner (holes or flipped faces)."""
        counts = Counter()
        for face, material in self.faces:
            if material in ignore_materials:
                continue
            for position, index in enumerate(face):
                counts[(index, face[(position + 1) % len(face)])] += 1
        return [edge for edge, count in counts.items()
                if count != 1 or counts.get((edge[1], edge[0]), 0) != 1]

    def face_normal(self, face):
        """Newell normal (unnormalised) of a polygon."""
        nx = ny = nz = 0.0
        for position, index in enumerate(face):
            x0, y0, z0 = self.verts[index]
            x1, y1, z1 = self.verts[face[(position + 1) % len(face)]]
            nx += (y0 - y1) * (z0 + z1)
            ny += (z0 - z1) * (x0 + x1)
            nz += (x0 - x1) * (y0 + y1)
        return nx, ny, nz

    def bounds(self):
        xs = [v[0] for v in self.verts]
        ys = [v[1] for v in self.verts]
        zs = [v[2] for v in self.verts]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def translate(self, dx, dy, dz=0.0):
        self.verts = [(x + dx, y + dy, z + dz) for x, y, z in self.verts]

    def place(self, other, dx=0.0, dy=0.0, quarter=0, dz=0.0, material_map=None):
        """Append ``other`` turned by quarter turns about its origin, then moved."""
        quarter %= 4
        offset = len(self.verts)
        for x, y, z in other.verts:
            for _ in range(quarter):
                x, y = -y, x
            self.verts.append((x + dx, y + dy, z + dz))
        for face, material in other.faces:
            mapped = material if material_map is None else material_map.get(material, material)
            self.faces.append((tuple(index + offset for index in face), mapped))
