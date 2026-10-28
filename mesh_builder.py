# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender adapter: run the geometry core and hand back a BMesh.

All building logic lives in pure-Python modules (spec, layouts, damage,
solids, shell). This module only converts the result, merges coplanar faces
and adds UVs/seams for texturing.
"""
import bmesh
import bpy

from . import shell
from .meshdata import (MAT_DOOR_FRAME, MAT_FLOOR, MAT_INTERIOR_WALL, MAT_ROOF,  # noqa: F401
                       MAT_RUBBLE, MAT_STAIRS, MAT_WALLS, MAT_WINDOW_FRAME)


def generate_uvs(bm: bmesh.types.BMesh):
    """Box-projected world-space UVs (1 UV unit = 1 m)."""
    uv_layer = bm.loops.layers.uv.verify()
    for face in bm.faces:
        normal = face.normal
        ax, ay, az = abs(normal.x), abs(normal.y), abs(normal.z)
        if az >= ax and az >= ay:
            axes = (0, 1)
        elif ax >= ay:
            axes = (1, 2)
        else:
            axes = (0, 2)
        for loop in face.loops:
            co = loop.vert.co
            loop[uv_layer].uv = (co[axes[0]], co[axes[1]])


def mark_seams_for_uvs(bm: bmesh.types.BMesh):
    """Seams on material borders, sharp corners and open edges, for unwrapping."""
    for edge in bm.edges:
        faces = edge.link_faces
        if len(faces) != 2:
            edge.seam = True
            continue
        a, b = faces
        if a.material_index != b.material_index or a.normal.dot(b.normal) < .5:
            edge.seam = True


def to_bmesh(mesh_data):
    """Convert a MeshData to a BMesh through a temporary mesh (fast C path)."""
    temp = bpy.data.meshes.new('_pbs_building')
    try:
        temp.from_pydata(mesh_data.verts, [], [face for face, _ in mesh_data.faces])
        temp.polygons.foreach_set('material_index', [m for _, m in mesh_data.faces])
        bm = bmesh.new()
        bm.from_mesh(temp)
    finally:
        bpy.data.meshes.remove(temp)
    return bm


def merge_coplanar(bm):
    """Limited dissolve: one n-gon per flat region of one material.

    Every solid is closed, so this only merges faces inside a plane; the
    result stays watertight and is far lighter for the engine.
    """
    bmesh.ops.dissolve_limit(bm, angle_limit=.0005, use_dissolve_boundaries=False,
                             verts=bm.verts[:], edges=bm.edges[:], delimit={'MATERIAL'})


class BuildingShellBuilder:
    """Builds one building. ``center`` puts the footprint centre at the origin."""

    def __init__(self, params: dict, center: bool = False):
        self.params = params
        self.center = center
        self.bm = None
        self.building = None

    def build(self) -> bmesh.types.BMesh:
        building = shell.build_building(self.params)
        self.building = building
        # Older callers read the damage line from params.
        self.params['damage_min_height'] = building.damage_min_height
        mesh = building.mesh
        if self.center:
            mesh.translate(-building.spec.width / 2, -building.spec.depth / 2)
        bm = to_bmesh(mesh)
        bm.normal_update()
        if self.params.get('auto_clean', True):
            merge_coplanar(bm)
            bm.normal_update()
        if self.params.get('mark_uv_seams', True):
            generate_uvs(bm)
            mark_seams_for_uvs(bm)
        self.bm = bm
        return bm
