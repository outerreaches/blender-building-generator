# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender material and shell creation services."""
import random

import bpy

from . import rubble
from .mesh_builder import BuildingShellBuilder
from .meshdata import MAT_RUBBLE, MeshData

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


def create_shell(name, params, collection):
    """Building object centred on its footprint, linked into ``collection``."""
    builder = BuildingShellBuilder(dict(params), center=True)
    mesh = None
    try:
        bm = builder.build()
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        add_material_slots(obj)
        _annotate(obj, builder.building)
        return obj
    except Exception:
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        if builder.bm is not None and builder.bm.is_valid:
            builder.bm.free()


def _annotate(obj, building):
    """Facts the game side can use without re-deriving them from geometry."""
    spec, plan = building.spec, building.plan
    obj['floors'] = len(spec.levels)
    obj['height'] = round(spec.top, 3)
    obj['enterable_floors'] = len(plan.levels)
    if plan.notes:
        obj['plan_notes'] = '; '.join(plan.notes)
    obj['lobby'] = spec.lobby


def create_rubble(name, params, collection):
    """Collapsed lot: overlapping low mounds of rubble on the pad."""
    rng = random.Random(params.get('seed', 0) ^ 0xC011A95E)
    data = MeshData()
    rubble.collapsed_lot(data, rng, params['width'], params['depth'])
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(data.verts, [], [face for face, _ in data.faces])
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        add_material_slots(obj)
        for polygon in mesh.polygons:
            polygon.material_index = MAT_RUBBLE
        return obj
    except Exception:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
