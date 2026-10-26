# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender material and shell creation services."""
import random
import bpy
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
        # Roof extras only belong on an intact top; a damaged shell already has
        # an irregular silhouette where the upper floors were cut away.
        total_height = params['floors'] * params['floor_height']
        cut = builder.params.get('damage_min_height')
        if cut is None or cut >= total_height - 1e-6:
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
