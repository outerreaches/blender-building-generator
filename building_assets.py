# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender material and shell creation services."""
import json
import math
import random

import bpy

from . import interior, metadata, rubble, sites
from .mesh_builder import (BuildingShellBuilder, generate_uvs, mark_seams_for_uvs,
                           merge_coplanar, to_bmesh)
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


# Site ground slots, in sites.S_* order.
SITE_MATERIALS = (
    ('Site_Asphalt', (.09, .09, .10, 1)),
    ('Site_Concrete', (.52, .51, .48, 1)),
    ('Site_Paint', (.80, .80, .76, 1)),
    ('Site_PaintYellow', (.78, .62, .16, 1)),
    ('Site_Grass', (.27, .29, .15, 1)),
    ('Site_Foliage', (.20, .26, .12, 1)),
    ('Site_Metal', (.36, .37, .38, 1)),
    ('Site_Sign', (.66, .20, .14, 1)),
    ('Site_Wood', (.36, .25, .16, 1)),
    ('Site_Rubble', (.35, .32, .28, 1)),
    ('Site_Glass', (.28, .36, .40, 1)),
    ('Site_Rubber', (.30, .16, .12, 1)),
    ('Site_Water', (.10, .16, .18, 1)),
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


def create_shell(name, params, collection, facts=None):
    """Building object centred on its footprint, linked into ``collection``.

    ``facts``, a dict, receives the building's interior facts (rooms, lifts,
    railings, fixtures; see interior.py) under 'interior'.
    """
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
        if facts is not None:
            facts['interior'] = interior.interior_facts(builder.building)
        return obj
    except Exception:
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        if builder.bm is not None and builder.bm.is_valid:
            builder.bm.free()


def addon_version():
    """Version of the add-on that generated an object (to spot stale installs)."""
    import importlib
    return importlib.import_module(__package__).version()


def _annotate(obj, building):
    """Facts the game side can use without re-deriving them from geometry."""
    spec, plan = building.spec, building.plan
    obj['addon_version'] = addon_version()
    # Street doors in object space: (x, y, outward normal x, y, width).
    obj['entrances'] = json.dumps(metadata.local_entrances(spec))
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


def mesh_object_from_data(name, data, collection, merge=True):
    """Object from a MeshData (material indices kept), merged and UV-mapped."""
    bm = to_bmesh(data)
    mesh = None
    try:
        bm.normal_update()
        if merge:
            merge_coplanar(bm)
            bm.normal_update()
        generate_uvs(bm)
        mark_seams_for_uvs(bm)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    except Exception:
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    return obj


def add_site_material_slots(obj):
    for name, color in SITE_MATERIALS:
        obj.data.materials.append(material(name, color))


def create_site(name, site, collection, facts=None):
    """Site grounds object with its buildings parented to it.

    The grounds origin is the pad centre at pad level; the front (street)
    faces -Y, like a building's. ``facts``, a dict, receives each building's
    interior facts under its object name.
    """
    grounds = mesh_object_from_data(f'{name}_Grounds', site.ground, collection)
    add_site_material_slots(grounds)
    grounds['site_kind'], grounds['site_variant'] = site.kind, site.variant
    grounds['site_size'] = (round(site.width, 3), round(site.depth, 3))
    grounds['surface_role'] = 'site'
    if site.notes:
        grounds['site_notes'] = '; '.join(site.notes)
    walls = material(f'Site_{site.kind.title()}_Walls', sites.WALL_COLORS[site.kind])
    names = []
    for building in site.buildings:
        made = {} if facts is not None else None
        obj = create_shell(f'{name}_{building.name}', building.params, collection, made)
        if made is not None:
            facts[obj.name] = made.get('interior')
        obj.parent = grounds
        obj.location = (building.x, building.y, 0.0)
        obj.rotation_euler.z = building.quarter * math.pi / 2
        obj.data.materials[0] = walls
        obj['site_role'] = building.role
        names.append(obj.name)
    grounds['building_objects'] = names    # In site.buildings order.
    return grounds


def create_site_preview(name, site, collection):
    """Fast stand-in: the pad and one box per building."""
    data = MeshData()
    x0, y0, x1, y1 = -site.width / 2, -site.depth / 2, site.width / 2, site.depth / 2
    from .solids import box
    box(data, x0, y0 - site.approach, -sites.PAD_THICKNESS, x1, y1, 0.0, sites.S_CONCRETE)
    for building in site.buildings:
        p = building.params
        height = p['ground_floor_height'] + (p['floors'] - 1) * p['floor_height']
        bx0, by0, bx1, by1 = building.footprint
        box(data, bx0, by0, 0.0, bx1, by1, height, sites.S_SIGN)
    obj = mesh_object_from_data(f'{name}_Preview', data, collection, merge=False)
    add_site_material_slots(obj)
    obj['site_kind'], obj['site_variant'] = site.kind, site.variant
    return obj


def create_shelter(name, variant, collection, meshes=None):
    """Transit stop; the road side is -Y. Pass one ``meshes`` dict per batch so
    stops of a variant share their mesh."""
    meshes = {} if meshes is None else meshes
    mesh = meshes.get(variant)
    if mesh is None:
        source = mesh_object_from_data(f'Shelter_{variant}', sites.shelter(variant), collection)
        add_site_material_slots(source)
        mesh = meshes[variant] = source.data
        bpy.data.objects.remove(source)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj['surface_role'] = 'prop'
    obj['shelter_variant'] = variant
    return obj
