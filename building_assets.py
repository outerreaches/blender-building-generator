# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender material and shell creation services."""
import random
import bmesh
import bpy
from mathutils import Vector
from .mesh_builder import BuildingShellBuilder

MATERIALS = (
    ('Building_Walls', (.7, .65, .6, 1)),
    ('Building_Floor', (.5, .5, .5, 1)),
    ('Building_Roof', (.3, .3, .35, 1)),
    ('Building_WindowFrame', (.4, .35, .3, 1)),
    ('Building_DoorFrame', (.35, .25, .2, 1)),
    ('Building_InteriorWall', (.85, .82, .78, 1)),
    ('Building_Stairs', (.45, .4, .35, 1)),
    ('Building_Rubble', (.35, .32, .28, 1)),
)


def material(name, color):
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.diffuse_color = color
        shader = mat.node_tree.nodes.get('Principled BSDF')
        if shader:
            shader.inputs['Base Color'].default_value = color
            shader.inputs['Roughness'].default_value = .85
    return mat


def add_material_slots(obj):
    for name, color in MATERIALS:
        obj.data.materials.append(material(name, color))


def _face(bm, vertices, material):
    face = bm.faces.new(vertices)
    face.material_index = material
    face.smooth = False
    return face


def cut_corner(bm, params):
    """Remove the upper part of one footprint quadrant: a missing building corner.

    Vertices above a seeded base height in the chosen quadrant are deleted, so
    the remaining walls end in broken edges and the exposed slabs read as a
    collapse. Deleting by vertex (rather than a single bisect plane) keeps the
    lower storeys intact and produces the L-shaped plan a corner failure leaves.
    """
    rng = random.Random(params.get('seed', 0) ^ 0x9E3779B9)
    width, depth = params['width'], params['depth']
    total = params['floors'] * params['floor_height']
    sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
    base = total * rng.uniform(.3, .5)
    doomed = [vertex for vertex in bm.verts
              if vertex.co.z > base and
              sign_x * (vertex.co.x - width / 2) > 0 and
              sign_y * (vertex.co.y - depth / 2) > 0]
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='VERTS')
    return sign_x, sign_y


def _bm_box(bm, x0, y0, z0, x1, y1, z1, material):
    corner = [bm.verts.new((x, y, z)) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    for face in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                 (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)):
        _face(bm, tuple(corner[index] for index in face), material)


def add_collapse_debris(bm, params, sign_x, sign_y):
    """Larger debris around the sheared corner, beyond the standard rubble piles."""
    rng = random.Random(params.get('seed', 0) ^ 0xD3B715)
    width, depth = params['width'], params['depth']
    centre_x = width / 2 + sign_x * width * .32
    centre_y = depth / 2 + sign_y * depth * .32
    for _ in range(rng.randint(7, 12)):
        size_x = rng.uniform(.6, 2.6)
        size_y = rng.uniform(.6, 2.6)
        size_z = rng.uniform(.3, 1.6)
        x = centre_x + sign_x * rng.uniform(-2.5, 3.5)
        y = centre_y + sign_y * rng.uniform(-2.5, 3.5)
        _bm_box(bm, x - size_x / 2, y - size_y / 2, 0,
                x + size_x / 2, y + size_y / 2, size_z,
                rng.choice((7, 7, 2)))


def _box_geometry(vertices, faces, materials, x0, y0, z0, x1, y1, z1, material):
    base = len(vertices)
    vertices.extend((x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1))
    faces.extend(tuple(base + index for index in face) for face in
                 ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                  (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))
    materials.extend((material,) * 6)


def create_rubble(name, params, collection):
    """Collapsed lot: rubble field, wall stumps and a few slab chunks."""
    rng = random.Random(params.get('seed', 0) ^ 0xC011A95E)
    width, depth = params['width'], params['depth']
    half_w, half_d = width / 2, depth / 2
    vertices, faces, materials = [], [], []

    # Standing wall stumps along the lot edges.
    for _ in range(rng.randint(1, 3)):
        side = rng.randrange(4)
        length = rng.uniform(.25, .6) * (width if side < 2 else depth)
        height = rng.uniform(1.0, 3.2)
        thickness = rng.uniform(.35, .6)
        offset = rng.uniform(-.5, .5) * ((width if side < 2 else depth) - length) / 2
        if side == 0:
            box = (offset - length / 2, -half_d, 0, offset + length / 2, -half_d + thickness, height)
        elif side == 1:
            box = (offset - length / 2, half_d - thickness, 0, offset + length / 2, half_d, height)
        elif side == 2:
            box = (-half_w, offset - length / 2, 0, -half_w + thickness, offset + length / 2, height)
        else:
            box = (half_w - thickness, offset - length / 2, 0, half_w, offset + length / 2, height)
        _box_geometry(vertices, faces, materials, *box, 0)

    # Debris mound: small blocks and a few slab chunks.
    for _ in range(rng.randint(10, 18)):
        size_x = rng.uniform(.5, max(1.0, width * .22))
        size_y = rng.uniform(.5, max(1.0, depth * .22))
        size_z = rng.uniform(.3, 1.6)
        x = rng.uniform(-half_w + size_x / 2, half_w - size_x / 2)
        y = rng.uniform(-half_d + size_y / 2, half_d - size_y / 2)
        material = rng.choice((7, 7, 7, 2, 0))
        _box_geometry(vertices, faces, materials,
                      x - size_x / 2, y - size_y / 2, 0,
                      x + size_x / 2, y + size_y / 2, size_z, material)

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    add_material_slots(obj)
    for polygon, material in zip(mesh.polygons, materials):
        polygon.material_index = material
    return obj


def add_gable_roof(bm, params, base):
    """Gable prism over the footprint; ridge runs along the frontage (X)."""
    width, depth = params['width'], params['depth']
    height = params.get('roof_height', 2.0)
    overhang = params.get('roof_overhang', .4)
    x0, x1 = -overhang, width + overhang
    y0, y1 = -overhang, depth + overhang
    ridge_y, ridge_z = depth / 2, base + height
    a = bm.verts.new((x0, y0, base))
    b = bm.verts.new((x1, y0, base))
    c = bm.verts.new((x1, y1, base))
    d = bm.verts.new((x0, y1, base))
    r0 = bm.verts.new((x0, ridge_y, ridge_z))
    r1 = bm.verts.new((x1, ridge_y, ridge_z))
    _face(bm, (a, b, r1, r0), 2)  # south slope
    _face(bm, (c, d, r0, r1), 2)  # north slope
    _face(bm, (a, r0, d), 2)      # west gable
    _face(bm, (b, c, r1), 2)      # east gable


def add_roof_box(bm, params, base):
    """Mechanical penthouse on a flat roof, sized as a fraction of the footprint."""
    width, depth = params['width'], params['depth']
    fraction_width, fraction_depth, height = params['roof_box']
    box_width, box_depth = width * fraction_width, depth * fraction_depth
    x0, x1 = (width - box_width) / 2, (width + box_width) / 2
    y0, y1 = (depth - box_depth) / 2, (depth + box_depth) / 2
    bottom = [bm.verts.new((x, y, base)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    top = [bm.verts.new((x, y, base + height)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    _face(bm, tuple(top), 2)
    for index in range(4):
        following = (index + 1) % 4
        _face(bm, (bottom[index], bottom[following], top[following], top[index]), 0)


def create_shell(name, params, collection):
    # Legacy geometry uses global random. Isolate it from caller state.
    state = random.getstate()
    builder = BuildingShellBuilder(dict(params))
    mesh = None
    try:
        bm = builder.build()
        if params.get('corner_cut'):
            add_collapse_debris(bm, params, *cut_corner(bm, params))
        # Roof extras only belong on an intact top; a damaged shell already has
        # an irregular silhouette where the upper floors were cut away.
        total_height = params['floors'] * params['floor_height']
        cut = builder.params.get('damage_min_height')
        if not params.get('corner_cut') and (cut is None or cut >= total_height - 1e-6):
            if params.get('roof_kind') == 'GABLE':
                add_gable_roof(bm, params, total_height)
            if params.get('roof_box'):
                add_roof_box(bm, params, total_height + .2)
        for vert in bm.verts:
            vert.co.x -= params['width'] / 2
            vert.co.y -= params['depth'] / 2
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        add_material_slots(obj)
        return obj
    except Exception:
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        if builder.bm is not None and builder.bm.is_valid:
            builder.bm.free()
        random.setstate(state)
