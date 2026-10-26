# SPDX-License-Identifier: GPL-3.0-or-later
# Procedural Building Shell Generator for Blender 4.5+

bl_info = {
    "name": "Procedural Building Shell Generator",
    "author": "Ares Project",
    "version": (0, 9, 6),
    "blender": (4, 5, 0),
    "location": "View3D > Add > Mesh > Procedural Building Shell",
    "description": "Generate customizable, game-ready building shells with windows, doors, and optional damage",
    "category": "Add Mesh",
}

import bpy

from . import operators, city_operators, city_export


def menu_func(self, context):
    self.layout.operator(operators.MESH_OT_procedural_building_shell.bl_idname, icon='HOME')
    self.layout.operator(operators.MESH_OT_procedural_building_bulk.bl_idname, icon='DUPLICATE')
    for cls in city_operators.CLASSES:
        self.layout.operator(cls.bl_idname, icon='HOME')


def register():
    bpy.utils.register_class(operators.MESH_OT_procedural_building_shell)
    bpy.utils.register_class(operators.MESH_OT_procedural_building_bulk)
    for cls in city_operators.CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_mesh_add.append(menu_func)
    bpy.utils.register_class(city_export.EXPORT_SCENE_OT_procedural_city)
    bpy.types.TOPBAR_MT_file_export.append(city_export.menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(city_export.menu_export)
    bpy.utils.unregister_class(city_export.EXPORT_SCENE_OT_procedural_city)
    bpy.types.VIEW3D_MT_mesh_add.remove(menu_func)
    for cls in reversed(city_operators.CLASSES):
        bpy.utils.unregister_class(cls)
    bpy.utils.unregister_class(operators.MESH_OT_procedural_building_bulk)
    bpy.utils.unregister_class(operators.MESH_OT_procedural_building_shell)


if __name__ == "__main__":
    register()

