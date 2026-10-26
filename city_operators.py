# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender adapter for the pure city plan and architecture recipes."""
import math
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from .city_plan import VERSION, CitySettings, generate_city, stream
from .streets import build_street_mesh, build_ground_mesh, junctions
from .styles import STYLE_ITEMS, STYLE_COLORS, building_recipe
from .building_assets import create_shell, material


def mesh_object(name, vertices, faces, collection, mat):
    mesh = bpy.data.meshes.new(name)
    try:
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        uv = mesh.uv_layers.new(name='UVMap')
        for poly in mesh.polygons:
            axis = max(range(3), key=lambda i: abs(poly.normal[i]))
            axes = ((1, 2), (0, 2), (0, 1))[axis]
            for loop_id in poly.loop_indices:
                co = mesh.vertices[mesh.loops[loop_id].vertex_index].co
                uv.data[loop_id].uv = (co[axes[0]], co[axes[1]])
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        mesh.materials.append(mat)
        return obj
    except Exception:
        if mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise


def box(name, width, depth, height, collection, mat):
    vertices = [(x * width / 2, y * depth / 2, z * height)
                for z in (0, 1) for y in (-1, 1) for x in (-1, 1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
             (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)]
    return mesh_object(name, vertices, faces, collection, mat)


def build_roads(plan, collection):
    vertices, faces, indices = build_street_mesh(plan)
    obj = mesh_object('City_Streets', vertices, faces, collection,
                      material('City_Asphalt', (.085, .09, .10, 1)))
    obj.data.materials.append(material('City_Pavement', (.42, .41, .38, 1)))
    obj.data.materials.append(material('City_Curb', (.52, .50, .46, 1)))
    for poly, index in zip(obj.data.polygons, indices):
        poly.material_index = index
    obj['surface_role'] = 'streets'
    return obj


def build_frontage(lot, plan, collection):
    """Level foundation and a clear concrete approach from sidewalk to entrance."""
    h = plan.settings.curb_height
    vertices, faces = [], []
    def slab(x0, y0, x1, y1):
        offset = len(vertices)
        vertices.extend([(x, y, z) for z in (-.2, h)
                         for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
        faces.extend(tuple(offset + i for i in f) for f in
                     ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                      (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))
    # Local building coordinates: door faces -Y.
    half_w, half_d = lot.width / 2, lot.depth / 2
    road = next(r for r in plan.roads if (r.a, r.b) == lot.frontage)
    size = plan.settings.block_size
    mid = ((road.a[0] + road.b[0]) * size / 2, (road.a[1] + road.b[1]) * size / 2)
    facing = (math.sin(lot.rotation), -math.cos(lot.rotation))
    distance = sum((mid[i] - lot.center[i]) * facing[i] for i in range(2))
    approach_end = distance - road.width / 2 - plan.settings.sidewalk_width
    slab(-half_w, -approach_end, half_w, half_d)
    obj = mesh_object(lot.id + '_Foundation', vertices, faces, collection,
                      material('City_Pavement', (.42, .41, .38, 1)))
    obj.rotation_euler.z = lot.rotation
    obj['surface_role'] = 'frontage'
    return obj


def build_markings(plan, collection):
    vertices, faces = [], []
    nodes = junctions(plan)
    for road in plan.roads:
        if road.tier == 'LOCAL':
            continue
        size = plan.settings.block_size
        length = size - nodes[road.a] - nodes[road.b] - 4
        rng = stream(plan.settings.seed, 'paint', road.a, road.b)
        offsets = (0, -road.width / 4, road.width / 4) if road.width >= 12 else (0,)
        for offset in offsets:
            for index in range(int(length / 7)):
                if rng.random() < .2:
                    continue
                start = nodes[road.a] + 2 + index * 7
                points = [(start, offset - .06), (start + 3, offset - .06),
                          (start + 3, offset + .06), (start, offset + .06)]
                base = len(vertices)
                for u, v in points:
                    if road.a[1] == road.b[1]:
                        vertices.append((road.a[0] * size + u, road.a[1] * size + v, .004))
                    else:
                        vertices.append((road.a[0] * size - v, road.a[1] * size + u, .004))
                faces.append(tuple(range(base, base + 4)))
    if not faces:
        return None
    obj = mesh_object('City_LanePaint', vertices, faces, collection,
                      material('City_WornPaint', (.64, .60, .44, 1)))
    obj['surface_role'] = 'decoration_no_collision'
    return obj


def build_route_guides(plan, collection, origin):
    colors = ((.95, .18, .08, 1), (.08, .45, 1, 1), (.1, .85, .3, 1))
    for index, route in enumerate(plan.driving_loops):
        curve = bpy.data.curves.new(route['id'], 'CURVE')
        curve.dimensions = '3D'
        curve.bevel_depth = .18
        curve.bevel_resolution = 0
        spline = curve.splines.new('POLY')
        spline.points.add(len(route['nodes']) - 1)
        for point, node in zip(spline.points, route['nodes']):
            point.co = (node[0] * plan.settings.block_size,
                        node[1] * plan.settings.block_size, .25 + index * .25, 1)
        obj = bpy.data.objects.new(route['id'], curve)
        collection.objects.link(obj)
        obj.location = origin
        obj['length_m'] = route['length_m']
        obj['purpose'] = 'Debug route guide; excluded from city FBX export'
        curve.materials.append(material('City_Route_' + str(index), colors[index % len(colors)]))


def remove_generated_collection(collection):
    for child in list(collection.children):
        remove_generated_collection(child)
    for obj in list(collection.objects):
        data = obj.data
        bpy.data.objects.remove(obj, do_unlink=True)
        if isinstance(data, bpy.types.Mesh) and data.users == 0:
            bpy.data.meshes.remove(data)
        elif isinstance(data, bpy.types.Curve) and data.users == 0:
            bpy.data.curves.remove(data)
    bpy.data.collections.remove(collection)


class MESH_OT_generate_city(bpy.types.Operator):
    bl_idname = 'mesh.generate_procedural_city'
    bl_label = 'Generate City'
    bl_description = 'Grow a seeded city with connected roads and district building styles'
    bl_options = {'REGISTER', 'UNDO'}

    seed: IntProperty(name='City Seed', default=42)
    radius: IntProperty(name='Radius (Blocks)', default=6, min=2, max=25)
    block_size: FloatProperty(name='Block Size (m)', default=56, min=48, max=120)
    primary_count: IntProperty(name='Primary Locations', default=5, min=1, max=16)
    secondary_count: IntProperty(name='Secondary Locations', default=12, min=0, max=100)
    driving_loop_count: IntProperty(name='Driving Circuits', default=3, min=0, max=8,
                                   description='Target highway-to-district loops, each at least six blocks long')
    core_radius: FloatProperty(name='Core Radius Fraction', default=.3, min=.05, max=1)
    core_density: FloatProperty(name='Core Density', default=.95, min=0, max=1)
    outskirts_density: FloatProperty(name='Outskirts Density', default=.15, min=0, max=1)
    road_density: FloatProperty(name='Local Road Density', default=.55, min=0, max=1)
    setback: FloatProperty(name='Minimum Road Setback (m)', default=2, min=1, max=8)
    sidewalk_width: FloatProperty(name='Sidewalk Width (m)', default=2, min=1.2, max=5)
    curb_height: FloatProperty(name='Curb Height (m)', default=.15, min=0, max=.25)
    damage: FloatProperty(name='Building Damage', default=.35, min=0, max=1)
    max_buildings: IntProperty(name='Building Budget', default=600, min=1, max=10000)
    style: EnumProperty(name='Architecture', items=[('MIXED', 'Mixed Districts', 'Styles vary by primary location')] + STYLE_ITEMS)
    detail: EnumProperty(name='Output', items=[('PREVIEW', 'Layout Preview', 'Fast building masses for planning'),
                                               ('SHELLS', 'Detailed Shells', 'Generate windows, doors and damage')])
    interiors: BoolProperty(name='Generate Interiors', default=False)
    route_guides: BoolProperty(name='Show Driving Route Guides', default=False)
    lane_markings: BoolProperty(name='Worn Lane Markings', default=True)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        layout = self.layout
        for title, names in (
            ('City Growth', ('seed', 'radius', 'block_size', 'primary_count', 'secondary_count', 'driving_loop_count')),
            ('Density and Access', ('core_radius', 'core_density', 'outskirts_density', 'road_density', 'setback', 'sidewalk_width', 'curb_height')),
            ('Buildings', ('style', 'damage', 'max_buildings', 'detail')),
        ):
            group = layout.box()
            group.label(text=title)
            for name in names:
                group.prop(self, name)
        if self.detail == 'SHELLS':
            layout.prop(self, 'interiors')
        layout.prop(self, 'lane_markings')
        layout.prop(self, 'route_guides')
        layout.label(text='Flat terrain; at-grade road junctions.', icon='INFO')
        layout.label(text='Preview first; large shell batches can take time.')

    def execute(self, context):
        settings = CitySettings(**{key: getattr(self, key) for key in CitySettings.__dataclass_fields__})
        root = None
        plan_text = None
        try:
            plan = generate_city(settings)
            root = bpy.data.collections.new(f'City_{self.seed}_{self.detail}')
            context.collection.children.link(root)
            root['city_seed'] = self.seed
            root['generator_version'] = VERSION
            root['output_detail'] = self.detail
            root['interiors'] = self.interiors
            root['lane_markings'] = self.lane_markings
            root['route_guides'] = self.route_guides
            origin = context.scene.cursor.location.copy()
            districts = {}
            for loc in plan.locations:
                if loc.role != 'SECONDARY':
                    col = bpy.data.collections.new(f'{loc.id}_{loc.style}')
                    root.children.link(col)
                    districts[loc.id] = col
                marker = bpy.data.objects.new(f'Location_{loc.id}', None)
                root.objects.link(marker)
                marker.location = (origin.x + loc.node[0] * self.block_size,
                                   origin.y + loc.node[1] * self.block_size, origin.z)
                marker.empty_display_type = 'CIRCLE'
                marker.empty_display_size = 5 if loc.role == 'SECONDARY' else 10
                marker['role'], marker['style'] = loc.role, loc.style
            roads = build_roads(plan, root)
            roads.location = origin
            if self.lane_markings:
                markings = build_markings(plan, root)
                if markings is not None:
                    markings.location = origin
            if self.route_guides:
                build_route_guides(plan, root, origin)
            ground_vertices, ground_faces = build_ground_mesh(plan)
            ground = mesh_object('City_Ground', ground_vertices, ground_faces,
                                 root, material('City_Ground', (.23, .21, .17, 1)))
            ground['surface_role'] = 'terrain'
            ground.location = origin
            context.window_manager.progress_begin(0, max(1, len(plan.lots)))
            for index, lot in enumerate(plan.lots):
                col = districts[lot.district]
                params = building_recipe(lot.style, lot.width, lot.depth, lot.floors,
                                         lot.seed, self.damage, self.interiors)
                if self.detail == 'SHELLS':
                    obj = create_shell(lot.id, params, col)
                    obj.data.materials[0] = material(f'City_{lot.style}', STYLE_COLORS[lot.style])
                else:
                    obj = box(lot.id, lot.width, lot.depth, lot.floors * params['floor_height'],
                              col, material(f'City_{lot.style}', STYLE_COLORS[lot.style]))
                obj.location = (origin.x + lot.center[0], origin.y + lot.center[1], origin.z + self.curb_height)
                obj.rotation_euler.z = lot.rotation
                obj['city_style'], obj['asset_seed'], obj['district'] = lot.style, lot.seed, lot.district
                foundation = build_frontage(lot, plan, col)
                foundation.location = (origin.x + lot.center[0], origin.y + lot.center[1], origin.z)
                context.window_manager.progress_update(index + 1)
            plan_text = bpy.data.texts.new(f'{root.name}_plan.json')
            plan_text.write(plan.to_json())
            root['plan_text'] = plan_text.name
            root['origin'] = list(origin)
            root['driving_circuits'] = len(plan.driving_loops)
            message = f'{len(plan.lots)} buildings, {len(plan.roads)} road segments, {len(plan.driving_loops)} circuits'
            if plan.eligible_lots > len(plan.lots):
                message += f' (budget limited from {plan.eligible_lots})'
            self.report({'INFO'}, message)
            if len(plan.driving_loops) < self.driving_loop_count:
                self.report({'WARNING'}, 'Map could not fit all requested circuits; increase its radius')
            return {'FINISHED'}
        except Exception as exc:
            if root is not None:
                remove_generated_collection(root)
            if plan_text is not None:
                bpy.data.texts.remove(plan_text)
            self.report({'ERROR'}, f'City generation failed: {exc}')
            return {'CANCELLED'}
        finally:
            context.window_manager.progress_end()


class MESH_OT_building_style(bpy.types.Operator):
    bl_idname = 'mesh.generate_building_style'
    bl_label = 'Generate Building by Style'
    bl_options = {'REGISTER', 'UNDO'}

    style: EnumProperty(name='Architecture', items=STYLE_ITEMS)
    width: FloatProperty(name='Width', default=14, min=6, max=100)
    depth: FloatProperty(name='Depth', default=12, min=6, max=100)
    floors: IntProperty(name='Floors', default=3, min=1, max=10)
    seed: IntProperty(name='Seed', default=42)
    damage: FloatProperty(name='Damage', default=.35, min=0, max=1)
    interiors: BoolProperty(name='Interiors', default=False)

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        collection = bpy.data.collections.new('Styled_Building')
        context.collection.children.link(collection)
        try:
            params = building_recipe(self.style, self.width, self.depth, self.floors,
                                     self.seed, self.damage, self.interiors)
            obj = create_shell(self.style, params, collection)
            obj.location = context.scene.cursor.location
            obj.data.materials[0] = material(f'City_{self.style}', STYLE_COLORS[self.style])
            obj['architecture_style'] = self.style
            obj['asset_seed'] = self.seed
            return {'FINISHED'}
        except Exception as exc:
            remove_generated_collection(collection)
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


CLASSES = (MESH_OT_building_style, MESH_OT_generate_city)
