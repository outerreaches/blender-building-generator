# SPDX-License-Identifier: GPL-3.0-or-later
# Procedural Building Shell Generator for Blender 4.5+

bl_info = {
    "name": "Procedural Building Shell Generator",
    "author": "Ares Project",
    "version": (0, 2, 0),
    "blender": (4, 5, 0),
    "location": "View3D > Add > Mesh > Procedural Building Shell",
    "description": "Generate customizable, game-ready building shells with windows, doors, and optional damage",
    "category": "Add Mesh",
}

import bpy

from . import operators


def menu_func(self, context):
    self.layout.operator(operators.MESH_OT_procedural_building_shell.bl_idname, icon='HOME')
    self.layout.operator(operators.MESH_OT_procedural_building_bulk.bl_idname, icon='DUPLICATE')


def register():
    bpy.utils.register_class(operators.MESH_OT_procedural_building_shell)
    bpy.utils.register_class(operators.MESH_OT_procedural_building_bulk)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)


def unregister():
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)
    bpy.utils.unregister_class(operators.MESH_OT_procedural_building_bulk)
    bpy.utils.unregister_class(operators.MESH_OT_procedural_building_shell)


if __name__ == "__main__":
    register()

