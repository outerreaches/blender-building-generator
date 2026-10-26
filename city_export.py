# SPDX-License-Identifier: GPL-3.0-or-later
"""Export only a generated city's static meshes, preserving editable source objects."""
import bpy
from bpy.props import StringProperty
from bpy_extras.io_utils import ExportHelper


class EXPORT_SCENE_OT_procedural_city(bpy.types.Operator, ExportHelper):
    bl_idname = 'export_scene.procedural_city'
    bl_label = 'Generated City for Unity (.fbx)'
    filename_ext = '.fbx'
    filter_glob: StringProperty(default='*.fbx', options={'HIDDEN'})
    city_collection: StringProperty(name='City Collection')

    def invoke(self, context, event):
        candidates = [c for c in bpy.data.collections if 'generator_version' in c]
        if not candidates:
            self.report({'ERROR'}, 'Generate a city first')
            return {'CANCELLED'}
        if not self.city_collection:
            self.city_collection = candidates[-1].name
        return ExportHelper.invoke(self, context, event)

    def draw(self, context):
        self.layout.prop_search(self, 'city_collection', bpy.data, 'collections')
        self.layout.label(text='Meshes only; metres; triangulated; materials and UVs.')

    def execute(self, context):
        collection = bpy.data.collections.get(self.city_collection)
        if collection is None or 'generator_version' not in collection:
            self.report({'ERROR'}, 'Choose a generated city collection')
            return {'CANCELLED'}
        objects = [obj for obj in collection.all_objects if obj.type == 'MESH']
        if context.mode != 'OBJECT' or not objects or not self.filepath:
            self.report({'ERROR'}, 'Use Object Mode, a nonempty city, and an output path')
            return {'CANCELLED'}
        if any(obj.name not in context.view_layer.objects or not obj.visible_get() for obj in objects):
            self.report({'ERROR'}, 'Unhide the city and include it in the active view layer before exporting')
            return {'CANCELLED'}
        if abs(context.scene.unit_settings.scale_length - 1) > 1e-6:
            self.report({'ERROR'}, 'City export expects scene Unit Scale 1.0 (one unit per metre)')
            return {'CANCELLED'}
        selected = list(context.selected_objects)
        active = context.view_layer.objects.active
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in objects:
                obj.select_set(True)
            context.view_layer.objects.active = objects[0]
            result = bpy.ops.export_scene.fbx(
                filepath=bpy.path.ensure_ext(self.filepath, '.fbx'), use_selection=True,
                object_types={'MESH'}, axis_forward='-Z', axis_up='Y',
                global_scale=1, apply_unit_scale=True, use_mesh_modifiers=True,
                use_triangles=True, mesh_smooth_type='FACE', bake_anim=False,
                use_custom_props=True, path_mode='AUTO')
            if result != {'FINISHED'}:
                raise RuntimeError('FBX exporter did not finish')
            self.report({'INFO'}, f'Exported {len(objects)} static mesh objects for Unity')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'City export failed: {exc}')
            return {'CANCELLED'}
        finally:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                obj.select_set(True)
            context.view_layer.objects.active = active


def menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_procedural_city.bl_idname)
