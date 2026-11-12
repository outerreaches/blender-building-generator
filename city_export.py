# SPDX-License-Identifier: GPL-3.0-or-later
"""Export only a generated city's static meshes, preserving editable source objects."""
import json
import os
import sys
import zlib
from array import array

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
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
    write_heightmap: BoolProperty(name='Write Heightmap (.heightmap.raw)', default=True,
                                  description='The graded ground as a 16-bit RAW heightmap (with a '
                                              '.heightmap.json describing it), next to the FBX')
    heightmap_resolution: EnumProperty(name='Heightmap Resolution', default='1025',
                                       items=[('513', '513', 'Samples per side'),
                                              ('1025', '1025', 'Samples per side'),
                                              ('2049', '2049', 'Samples per side')])
    levels_of_detail: BoolProperty(name='Levels of Detail', default=True,
                                   description='Also export every building as <name>_shell '
                                               '(walls, roof and outside rubble only) and '
                                               '<name>_mass (solid walls without openings), '
                                               'as its children, for the engine to show at a '
                                               'distance')
    tile_size: EnumProperty(name='Ground Tiles', default='256',
                            description='Split the ground, streets and other city-wide meshes '
                                        'into square tiles (<name>_t<column>_<row>) so the '
                                        'engine can cull them',
                            items=[('0', 'Off', 'One mesh each, as generated'),
                                   ('128', '128 m', 'Tile side'),
                                   ('256', '256 m', 'Tile side'),
                                   ('512', '512 m', 'Tile side')])
    merge_flat: BoolProperty(name='Merge Flat Ground', default=True,
                             description='In each tile, merge faces lying in one plane (flat '
                                         'streets, pads, terraces and facets); the surface '
                                         'is the same, with far fewer triangles')

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
        self.layout.prop(self, 'write_heightmap')
        if self.write_heightmap:
            self.layout.prop(self, 'heightmap_resolution')
        self.layout.prop(self, 'levels_of_detail')
        self.layout.prop(self, 'tile_size')
        if int(self.tile_size):
            self.layout.prop(self, 'merge_flat')
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
        delivery = Delivery()
        try:
            if self.levels_of_detail:
                delivery.add_lods(objects)
            if int(self.tile_size):
                delivery.add_tiles(objects, float(self.tile_size), self.merge_flat)
            context.view_layer.update()
            bpy.ops.object.select_all(action='DESELECT')
            exported = [obj for obj in objects if obj not in delivery.replaced] + delivery.made
            for obj in exported:
                obj.select_set(True)
            context.view_layer.objects.active = exported[0]
            result = bpy.ops.export_scene.fbx(
                filepath=bpy.path.ensure_ext(self.filepath, '.fbx'), use_selection=True,
                object_types={'MESH'}, axis_forward='-Z', axis_up='Y',
                global_scale=1, apply_unit_scale=True, use_mesh_modifiers=True,
                use_triangles=True, mesh_smooth_type='FACE', bake_anim=False,
                use_custom_props=True, path_mode='AUTO')
            if result != {'FINISHED'}:
                raise RuntimeError('FBX exporter did not finish')
            message = f'Exported {len(exported)} static mesh objects for Unity'
            if delivery.lods:
                message += f' ({delivery.lods} buildings with levels of detail)'
            if self.write_metadata:
                path = write_city_metadata(collection, bpy.path.ensure_ext(self.filepath, '.fbx'),
                                           delivery.facts())
                if path:
                    message += f' and {os.path.basename(path)}'
                else:
                    self.report({'WARNING'}, 'This city has no metadata; regenerate it to get one')
            if self.write_heightmap:
                path = write_city_heightmap(collection, bpy.path.ensure_ext(self.filepath, '.fbx'),
                                            int(self.heightmap_resolution))
                if path:
                    message += f' and {os.path.basename(path)}'
                else:
                    self.report({'WARNING'}, 'No heightmap: this city was made by another version '
                                             'of the add-on; regenerate it to get one')
            self.report({'INFO'}, message)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f'City export failed: {exc}')
            return {'CANCELLED'}
        finally:
            delivery.discard()
            bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                obj.select_set(True)
            context.view_layer.objects.active = active


SHELL_SUFFIX, MASS_SUFFIX = '_shell', '_mass'


class _Faces:
    """A mesh's faces as arrays, to cut new meshes out of it quickly."""

    def __init__(self, mesh):
        import numpy as np
        self.np, self.mesh = np, mesh
        count = len(mesh.polygons)
        self.starts = np.empty(count, dtype=np.int32)
        self.totals = np.empty(count, dtype=np.int32)
        self.materials = np.empty(count, dtype=np.int32)
        self.smooth = np.empty(count, dtype=bool)
        mesh.polygons.foreach_get('loop_start', self.starts)
        mesh.polygons.foreach_get('loop_total', self.totals)
        mesh.polygons.foreach_get('material_index', self.materials)
        mesh.polygons.foreach_get('use_smooth', self.smooth)
        self.corners = np.empty(len(mesh.loops), dtype=np.int32)
        mesh.loops.foreach_get('vertex_index', self.corners)
        self.points = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
        mesh.vertices.foreach_get('co', self.points)
        self.points = self.points.reshape(-1, 3)
        self.uvs = []
        for layer in mesh.uv_layers:
            values = np.empty(len(mesh.loops) * 2, dtype=np.float32)
            layer.data.foreach_get('uv', values)
            self.uvs.append((layer.name, values.reshape(-1, 2)))

    def centres(self):
        """Face centres (mean of the corners), one row per face."""
        np = self.np
        sums = np.add.reduceat(self.points[self.corners], self.starts, axis=0)
        return sums / self.totals[:, None]

    def cut(self, name, keep):
        """New mesh of the faces whose index is in ``keep`` (ascending)."""
        np = self.np
        totals = self.totals[keep]
        starts = np.zeros(len(keep), dtype=np.int32)
        if len(keep) > 1:
            np.cumsum(totals[:-1], out=starts[1:])
        corners = np.repeat(self.starts[keep] - starts, totals) + np.arange(int(totals.sum()))
        used, mapped = np.unique(self.corners[corners], return_inverse=True)
        mesh = bpy.data.meshes.new(name)
        mesh.vertices.add(len(used))
        mesh.vertices.foreach_set('co', self.points[used].ravel())
        mesh.loops.add(len(corners))
        mesh.loops.foreach_set('vertex_index', mapped.astype(np.int32))
        mesh.polygons.add(len(keep))
        mesh.polygons.foreach_set('loop_start', starts)
        mesh.polygons.foreach_set('material_index', self.materials[keep])
        mesh.polygons.foreach_set('use_smooth', self.smooth[keep])
        for layer_name, values in self.uvs:
            mesh.uv_layers.new(name=layer_name).data.foreach_set('uv', values[corners].ravel())
        for slot in self.mesh.materials:
            mesh.materials.append(slot)
        mesh.update(calc_edges=True)
        return mesh


def _merge_flat(mesh):
    """One face per flat region of one material, in place. Vertices on the
    mesh's border stay, so what met it still does."""
    import bmesh
    from .mesh_builder import merge_coplanar
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        # The buildings' limit: measured on a hilly city it moves the
        # surface by under a millimetre.
        merge_coplanar(bm)
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.update()


class Delivery:
    """Temporary export-only objects: buildings' lower levels of detail and
    the tiles of city-wide meshes. The source objects are left as they are."""

    def __init__(self):
        self.made = []          # Objects to export besides the city's own.
        self.replaced = set()   # City objects exported as tiles instead.
        self.lods = 0
        self.tile = 0.0
        self.merged = False
        self.tiled = []         # (object name, [tile names]).

    def _twin(self, obj, name, mesh, child=False):
        """Export-only object with ``mesh`` where ``obj`` stands: its child
        (a level of detail) or beside it with its properties (a tile)."""
        from mathutils import Matrix
        twin = obj.copy()       # Same transform and parent.
        twin.name, twin.data = name, mesh
        if child:
            for key in list(twin.keys()):
                del twin[key]
            twin.parent = obj
            twin.matrix_parent_inverse = Matrix.Identity(4)
            twin.matrix_basis = Matrix.Identity(4)
        (obj.users_collection[0] if obj.users_collection
         else bpy.context.scene.collection).objects.link(twin)
        self.made.append(twin)
        return twin

    def add_lods(self, objects):
        from .building_assets import MASS_PROPERTY
        from .mesh_builder import SHELL_ATTRIBUTE
        import numpy as np
        for obj in objects:
            mesh = obj.data
            flags = mesh.attributes.get(SHELL_ATTRIBUTE)
            mass = mesh.get(MASS_PROPERTY)
            if flags is None or flags.domain != 'FACE' or mass is None:
                continue
            values = np.empty(len(mesh.polygons), dtype=np.int32)
            flags.data.foreach_get('value', values)
            keep = np.flatnonzero(values)
            if not len(keep):
                continue
            self._twin(obj, obj.name + SHELL_SUFFIX,
                       _Faces(mesh).cut(obj.name + SHELL_SUFFIX, keep), child=True)
            far = mass.copy()
            far.name = obj.name + MASS_SUFFIX
            for slot in mesh.materials:
                far.materials.append(slot)
            self._twin(obj, obj.name + MASS_SUFFIX, far, child=True)
            self.lods += 1

    def add_tiles(self, objects, size, merge=False):
        """Cut every object much longer than a tile into tiles, by face centre
        (no face is split, so neighbouring tiles still meet). Tiles past the
        rest of the city are gathered into the outermost ring. ``merge``
        joins each tile's faces that lie in one plane; a tile's border keeps
        its vertices, so tiles and neighbouring objects still meet."""
        from mathutils import Vector
        from .mesh_builder import SHELL_ATTRIBUTE
        import numpy as np
        self.tile, self.merged = size, bool(merge)
        boxes = {}
        for obj in objects:
            corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            boxes[obj] = (min(c.x for c in corners), min(c.y for c in corners),
                          max(c.x for c in corners), max(c.y for c in corners))
        wide = [obj for obj in objects
                if max(boxes[obj][2] - boxes[obj][0], boxes[obj][3] - boxes[obj][1]) > size * 1.5
                and obj.data.attributes.get(SHELL_ATTRIBUTE) is None
                and len(obj.data.polygons) > 1
                # A site's grounds stay whole: its buildings hang from it.
                and not any(child.type == 'MESH' and
                            child.data.attributes.get(SHELL_ATTRIBUTE) is not None
                            for child in obj.children)]
        rest = [boxes[obj] for obj in objects if obj not in wide]
        if not wide:
            return
        if rest:
            low = (np.floor(min(b[0] for b in rest) / size) - 1, np.floor(min(b[1] for b in rest) / size) - 1)
            high = (np.floor(max(b[2] for b in rest) / size) + 1, np.floor(max(b[3] for b in rest) / size) + 1)
        for obj in wide:
            faces = _Faces(obj.data)
            matrix = np.array(obj.matrix_world, dtype=np.float64)
            centres = faces.centres() @ matrix[:3, :3].T + matrix[:3, 3]
            cells = np.floor(centres[:, :2] / size).astype(np.int64)
            if rest:
                cells[:, 0] = np.clip(cells[:, 0], low[0], high[0])
                cells[:, 1] = np.clip(cells[:, 1], low[1], high[1])
            order = np.lexsort((np.arange(len(cells)), cells[:, 1], cells[:, 0]))
            ordered = cells[order]
            breaks = np.flatnonzero(np.any(ordered[1:] != ordered[:-1], axis=1)) + 1
            names = []
            for group in np.split(order, breaks):
                column, row = (int(v) for v in cells[group[0]])
                name = f'{obj.name}_t{column}_{row}'
                tile = faces.cut(name, np.sort(group))
                if merge:
                    _merge_flat(tile)
                self._twin(obj, name, tile)
                names.append(name)
            self.replaced.add(obj)
            self.tiled.append((obj.name, names))

    def facts(self):
        """What the metadata says about the export (plain lists for JsonUtility)."""
        return {'lod_suffixes': ['', SHELL_SUFFIX, MASS_SUFFIX] if self.lods else [''],
                'lod_buildings': self.lods, 'tile_size': self.tile, 'tiles_merged': self.merged,
                'tiled': [{'object': name, 'tiles': tiles} for name, tiles in self.tiled]}

    def discard(self):
        for obj in self.made:
            mesh = obj.data
            bpy.data.objects.remove(obj)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        self.made = []


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


def write_city_metadata(collection, fbx_path, delivery=None):
    """Write the city's metadata as ``<name>.city.json`` beside the FBX.

    Object names in the metadata are checked against the collection, so a
    renamed or deleted object shows up as a missing entry rather than silently.
    ``delivery`` (``Delivery.facts``) records the levels of detail and tiles
    this export wrote.
    """
    data = city_metadata(collection)
    if data is None:
        return None
    names = {obj.name for obj in collection.all_objects}
    missing = []
    for group in ('buildings', 'sites', 'yards', 'transit_stops'):
        for entry in data.get(group, ()):
            if entry.get('object') not in names:
                missing.append(entry.get('object'))
            for building in entry.get('buildings', ()):
                if building.get('object') not in names:
                    missing.append(building.get('object'))
    data['missing_objects'] = missing
    data['delivery'] = delivery or Delivery().facts()
    path = os.path.splitext(fbx_path)[0] + '.city.json'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(data, handle, separators=(',', ':'))
    return path


def city_plan(collection):
    """The plan a city was made from, regenerated from its stored settings; None
    when this version of the add-on would make a different plan."""
    from .city_plan import CitySettings, generate_city
    text = bpy.data.texts.get(collection.get('plan_text', ''))
    if text is None:
        return None
    stored = json.loads(text.as_string())
    try:
        plan = generate_city(CitySettings(**stored['settings']))
    except (TypeError, ValueError):
        return None
    return plan if json.loads(plan.to_json()) == stored else None


def write_city_heightmap(collection, fbx_path, resolution=1025):
    """Write the city's graded ground as ``<name>.heightmap.raw`` (16-bit,
    little-endian, row by row) and ``<name>.heightmap.json`` beside the FBX.

    Laid out like the city metadata: in Unity space the columns run along +X
    and the rows along +Z, ready for a Unity Terrain (Import Raw, Windows byte
    order, no flip). Returns the RAW path, or None if the plan cannot be
    regenerated exactly.
    """
    from .metadata import Space
    from .streets import heightmap
    from . import version
    plan = city_plan(collection)
    if plan is None:
        return None
    data = city_metadata(collection) or {}
    space = Space(data.get('space', {}).get('name', 'UNITY'))
    unity = space.name == 'UNITY'
    # Unity's +X and +Z are Blender's -x and -y.
    sign = -1 if unity else 1
    rows, x0, y0, step = heightmap(plan, resolution, sign, sign)
    low = min(min(row) for row in rows)
    high = max(max(row) for row in rows)
    span = max(high - low, 1e-6)
    samples = array('H', (int(round((h - low) / span * 65535)) for row in rows for h in row))
    if sys.byteorder == 'big':
        samples.byteswap()
    base = os.path.splitext(fbx_path)[0]
    with open(base + '.heightmap.raw', 'wb') as handle:
        handle.write(samples.tobytes())
    ox, oy, oz = collection.get('origin', (0.0, 0.0, 0.0))
    origin = space.point((ox + x0, oy + y0, oz + low))
    size = (resolution - 1) * step
    info = {'format': 'ares.city.heightmap', 'schema': 1, 'addon_version': version(),
            'collection': collection.name, 'file': os.path.basename(base + '.heightmap.raw'),
            'space': space.name, 'resolution': resolution, 'spacing': step,
            'size': [size, size], 'columns': '+x', 'rows': '+z' if unity else '+y',
            'origin': origin, 'min_height': low, 'max_height': high,
            'encoding': 'uint16 little-endian, row by row from row 0; height = min_height + '
                        'value / 65535 * (max_height - min_height)',
            'terrain': plan.settings.terrain}
    if unity:
        info['unity_terrain'] = {'position': origin, 'size': [size, high - low, size],
                                 'heightmap_resolution': resolution}
    with open(base + '.heightmap.json', 'w', encoding='utf-8') as handle:
        json.dump(info, handle, indent=1)
    return base + '.heightmap.raw'


def menu_export(self, context):
    self.layout.operator(EXPORT_SCENE_OT_procedural_city.bl_idname)
