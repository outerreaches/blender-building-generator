# SPDX-License-Identifier: GPL-3.0-or-later
"""Export only a generated city's static meshes, preserving editable source objects."""
import json
import os
import zlib

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ExportHelper


class EXPORT_SCENE_OT_procedural_city(bpy.types.Operator, ExportHelper):
    bl_idname = 'export_scene.procedural_city'
    bl_label = 'Generated City for Unity (.fbx)'
    filename_ext = '.fbx'
    filter_glob: StringProperty(default='*.fbx', options={'HIDDEN'})
    city_collection: StringProperty(name='City Collection')
    write_metadata: BoolProperty(name='Write City Metadata (.city.json)', default=True,
                                 description='Roads, buildings and entrances, sites and markers '
                                             'for game-side placement, next to the FBX')

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
        self.layout.prop(self, 'write_metadata')
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
            message = f'Exported {len(objects)} static mesh objects for Unity'
            if self.write_metadata:
                path = write_city_metadata(collection, bpy.path.ensure_ext(self.filepath, '.fbx'))
                if path:
                    message += f' and {os.path.basename(path)}'
                else:
                    self.report({'WARNING'}, 'This city has no metadata; regenerate it to get one')
            self.report({'INFO'}, message)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'City export failed: {exc}')
            return {'CANCELLED'}
        finally:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                obj.select_set(True)
            context.view_layer.objects.active = active


# The metadata lives on the city collection, compressed: with interiors it runs
# to megabytes, and Blender writes Text datablocks that large very slowly. The
# leading underscore keeps it out of the Custom Properties panel.
METADATA_PROPERTY = '_metadata_json_zlib'


def store_city_metadata(collection, data):
    collection[METADATA_PROPERTY] = zlib.compress(
        json.dumps(data, separators=(',', ':')).encode('utf-8'), 6)


def city_metadata(collection):
    """The metadata stored with a generated city, or None."""
    packed = collection.get(METADATA_PROPERTY)
    if packed is not None:
        return json.loads(zlib.decompress(bytes(packed)).decode('utf-8'))
    text = bpy.data.texts.get(collection.get('metadata_text', ''))     # Cities before v0.14.
    return json.loads(text.as_string()) if text is not None else None


def write_city_metadata(collection, fbx_path):
    """Write the city's metadata as ``<name>.city.json`` beside the FBX.

    Object names in the metadata are checked against the collection, so a
    renamed or deleted object shows up as a missing entry rather than silently.
    """
    data = city_metadata(collection)
    if data is None:
        return None
    names = {obj.name for obj in collection.all_objects}
    missing = []
    for group in ('buildings', 'sites', 'transit_stops'):
        for entry in data.get(group, ()):
            if entry.get('object') not in names:
                missing.append(entry.get('object'))
            for building in entry.get('buildings', ()):
                if building.get('object') not in names:
                    missing.append(building.get('object'))
    data['missing_objects'] = missing
    path = os.path.splitext(fbx_path)[0] + '.city.json'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, separators=(',', ':'))
    return path


def menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_procedural_city.bl_idname)
