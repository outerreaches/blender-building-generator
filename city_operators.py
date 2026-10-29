# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender adapter for the pure city plan and architecture recipes."""
import math
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from .city_plan import CONDITIONS, VERSION, CitySettings, generate_city, stream
from .dims import GROUND_SLAB
from .spec import BuildingSpec
from .sites import KINDS as SITE_KINDS, VARIANTS as SITE_VARIANTS, compose as compose_site
from .streets import build_street_mesh, build_ground_mesh, junctions
from .styles import STYLE_ITEMS, STYLE_COLORS, building_recipe
from .building_assets import (create_rubble, create_shell, create_shelter, create_site,
                              create_site_preview, material)


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


def build_frontage(lot, plan, collection, sunken=None):
    """Level foundation and a clear concrete approach from sidewalk to entrance.

    ``sunken`` (x0, y0, x1, y1, centred on the lot) is the building's ground
    storey: the foundation drops there to the underside of its ground slab,
    so the two never share the floor plane.
    """
    h = plan.settings.curb_height
    vertices, faces = [], []
    def slab(x0, y0, x1, y1, top=h):
        offset = len(vertices)
        vertices.extend([(x, y, z) for z in (-.2, top)
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
    if sunken:
        xs = sorted({-half_w, half_w, sunken[0], sunken[2]})
        ys = sorted({-approach_end, half_d, sunken[1], sunken[3]})
        for x0, x1 in zip(xs, xs[1:]):
            for y0, y1 in zip(ys, ys[1:]):
                if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
                    continue
                inside = (sunken[0] <= (x0 + x1) / 2 <= sunken[2] and
                          sunken[1] <= (y0 + y1) / 2 <= sunken[3])
                slab(x0, y0, x1, y1, h - GROUND_SLAB if inside else h)
    else:
        slab(-half_w, -approach_end, half_w, half_d)
    obj = mesh_object(lot.id + '_Foundation', vertices, faces, collection,
                      material('City_Pavement', (.42, .41, .38, 1)))
    obj.rotation_euler.z = lot.rotation
    obj['surface_role'] = 'frontage'
    return obj


def polyline_sample(points, distance):
    """Point and unit tangent at an arc length along a polyline."""
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if length and distance <= length:
            t = distance / length
            return ((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t),
                    ((b[0] - a[0]) / length, (b[1] - a[1]) / length))
        distance -= length
    a, b = points[-2], points[-1]
    length = math.dist(a, b) or 1
    return (b[0], b[1]), ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def build_markings(plan, collection):
    vertices, faces = [], []
    size = plan.settings.block_size
    halves = junctions(plan)
    for path in plan.paths:
        if path['tier'] == 'LOCAL':
            continue
        points = [tuple(point) for point in path['points']]
        total = sum(math.dist(a, b) for a, b in zip(points, points[1:]))
        offsets = (0, -path['width'] / 4, path['width'] / 4) if path['width'] >= 12 else (0,)
        nodes = [(node[0] * size, node[1] * size) for node in path['nodes']]
        rng = stream(plan.settings.seed, 'paint', path['id'])
        start = 6
        while start + 3 < total - 6:
            middle, _ = polyline_sample(points, start + 1.5)
            clearance = min(math.dist(middle, node) - halves[node] -
                            plan.settings.sidewalk_width for node in path['nodes'])
            if clearance < 4 or rng.random() < .2:
                start += 7
                continue
            (x0, y0), t0 = polyline_sample(points, start)
            (x1, y1), t1 = polyline_sample(points, start + 3)
            normal0 = (-t0[1], t0[0])
            normal1 = (-t1[1], t1[0])
            base = len(vertices)
            for offset in offsets:
                for point, normal, side in (((x0, y0), normal0, -1), ((x1, y1), normal1, -1),
                                            ((x1, y1), normal1, 1), ((x0, y0), normal0, 1)):
                    vertices.append((point[0] + normal[0] * (offset + side * .06),
                                     point[1] + normal[1] * (offset + side * .06), .004))
                faces.append(tuple(range(base, base + 4)))
                base += 4
            start += 7
    if not faces:
        return None
    obj = mesh_object('City_LanePaint', vertices, faces, collection,
                      material('City_WornPaint', (.64, .60, .44, 1)))
    obj['surface_role'] = 'decoration_no_collision'
    return obj


def path_section(path, start, end):
    """Polyline between two nodes, projected onto the route centreline."""
    points = path['points']

    def projection(node):
        best_distance, best_length = math.inf, 0.0
        offset = 0.0
        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length:
                t = max(0.0, min(1.0, ((node[0] - a[0]) * dx +
                                       (node[1] - a[1]) * dy) / (length * length)))
                distance = math.dist(node, (a[0] + dx * t, a[1] + dy * t))
                if distance < best_distance:
                    best_distance, best_length = distance, offset + length * t
            offset += length
        return best_length

    start_length, end_length = projection(start), projection(end)
    low, high = sorted((start_length, end_length))
    section = [polyline_sample(points, low)[0]]
    offset = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if low < offset + length < high:
            section.append(b)
        offset += length
    section.append(polyline_sample(points, high)[0])
    if end_length < start_length:
        section.reverse()
    return section


def route_sections(plan):
    sections = {}
    for path in plan.paths:
        nodes = [tuple(node) for node in path['nodes']]
        for index in range(len(nodes) - 1):
            sections[tuple(sorted((nodes[index], nodes[index + 1])))] = path
    return sections


def build_route_guides(plan, collection, origin):
    colors = ((.95, .18, .08, 1), (.08, .45, 1, 1), (.1, .85, .3, 1))
    size = plan.settings.block_size
    sections = route_sections(plan)
    for index, route in enumerate(plan.driving_loops):
        nodes = [tuple(node) for node in route['nodes']]
        points = []
        for a, b in zip(nodes, nodes[1:]):
            path = sections.get(tuple(sorted((a, b))))
            if path is None:
                continue
            part = path_section(path, (a[0] * size, a[1] * size),
                                (b[0] * size, b[1] * size))
            if points and math.dist(points[-1], part[0]) < 1e-6:
                part = part[1:]
            points.extend(part)
        if len(points) < 2:
            points = [(node[0] * size, node[1] * size) for node in nodes]
        curve = bpy.data.curves.new(route['id'], 'CURVE')
        curve.dimensions = '3D'
        curve.bevel_depth = .18
        curve.bevel_resolution = 0
        spline = curve.splines.new('POLY')
        spline.points.add(len(points) - 1)
        for point, (x, y) in zip(spline.points, points):
            point.co = (x, y, .25 + index * .25, 1)
        obj = bpy.data.objects.new(route['id'], curve)
        collection.objects.link(obj)
        obj.location = origin
        obj['length_m'] = route['length_m']
        obj['purpose'] = 'Debug route guide; excluded from city FBX export'
        curve.materials.append(material('City_Route_' + str(index), colors[index % len(colors)]))


def build_sites(plan, root, origin, detail):
    """Points of interest (one object tree per site) and transit stops."""
    collection = bpy.data.collections.new('Sites')
    root.children.link(collection)
    h = plan.settings.curb_height
    for poi in plan.pois:
        site = compose_site(poi.kind, poi.width, poi.depth, poi.seed, None, poi.condition,
                            poi.damage, poi.approach)
        if detail == 'SHELLS':
            obj = create_site(poi.id, site, collection)
        else:
            obj = create_site_preview(poi.id, site, collection)
        obj.location = (origin.x + poi.center[0], origin.y + poi.center[1], origin.z + h)
        obj.rotation_euler.z = poi.rotation
        obj['condition'], obj['district'], obj['city_style'] = poi.condition, poi.district, poi.style
        obj['asset_seed'] = poi.seed
    meshes = {}
    for shelter in plan.shelters:
        obj = create_shelter(shelter.id, shelter.variant, collection, meshes)
        obj.location = (origin.x + shelter.position[0], origin.y + shelter.position[1], origin.z + h)
        obj.rotation_euler.z = shelter.rotation
    return collection


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
    primary_count: IntProperty(name='Primary Locations', default=6, min=1, max=16)
    secondary_count: IntProperty(name='Secondary Locations', default=12, min=0, max=100)
    driving_loop_count: IntProperty(name='Driving Circuits', default=3, min=0, max=8,
                                   description='Target highway-to-district loops, each at least six blocks long')
    core_radius: FloatProperty(name='Core Radius Fraction', default=.3, min=.05, max=1)
    core_density: FloatProperty(name='Core Density', default=.95, min=0, max=1)
    outskirts_density: FloatProperty(name='Outskirts Density', default=.15, min=0, max=1)
    road_density: FloatProperty(name='Local Road Density', default=.55, min=0, max=1)
    curve_radius: FloatProperty(name='Road Corner Radius', default=.6, min=0, max=1,
                                description='Fraction of the tier corner radius; 0 keeps square turns')
    setback: FloatProperty(name='Minimum Road Setback (m)', default=2, min=1, max=8)
    sidewalk_width: FloatProperty(name='Sidewalk Width (m)', default=2, min=1.2, max=5)
    curb_height: FloatProperty(name='Curb Height (m)', default=.15, min=0, max=.25)
    wasteland: FloatProperty(name='Wasteland Extent (m)', default=12000, min=0, max=20000,
                             description='Open ground beyond the city edge; the city itself stays inside the invisible walls')
    damage: FloatProperty(name='Building Damage', default=.35, min=0, max=1)
    max_buildings: IntProperty(name='Building Budget', default=600, min=1, max=10000)
    style: EnumProperty(name='Architecture', items=[('MIXED', 'Mixed Districts', 'Styles vary by primary location')] + STYLE_ITEMS)
    detail: EnumProperty(name='Output', items=[('PREVIEW', 'Layout Preview', 'Fast building masses for planning'),
                                               ('SHELLS', 'Detailed Shells', 'Generate windows, doors and damage')])
    interior_ratio: FloatProperty(name='Interior Ratio', default=.25, min=0, max=1,
                                 description='Fraction of enterable buildings that get full interior layouts')
    route_guides: BoolProperty(name='Show Driving Route Guides', default=False)
    points_of_interest: BoolProperty(name='Points of Interest', default=True,
                                     description='Gas stations, schools, hospitals, parks, parking, malls '
                                                 'and transit stops on reserved blocks')
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
            ('Density and Access', ('curve_radius', 'core_radius', 'core_density', 'outskirts_density', 'road_density', 'setback', 'sidewalk_width', 'curb_height', 'wasteland')),
            ('Buildings', ('style', 'damage', 'max_buildings', 'points_of_interest', 'detail')),
        ):
            group = layout.box()
            group.label(text=title)
            for name in names:
                group.prop(self, name)
        if self.detail == 'SHELLS':
            layout.prop(self, 'interior_ratio')
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
            root['interior_ratio'] = self.interior_ratio
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
                                         lot.seed, lot.damage, lot.interiors,
                                         lot.condition)
                if self.detail == 'SHELLS':
                    if lot.condition == 'COLLAPSED':
                        obj = create_rubble(lot.id, params, col)
                    else:
                        obj = create_shell(lot.id, params, col)
                    obj.data.materials[0] = material(f'City_{lot.style}', STYLE_COLORS[lot.style])
                else:
                    height = (2.2 if lot.condition == 'COLLAPSED'
                              else lot.floors * params['floor_height'])
                    obj = box(lot.id, lot.width, lot.depth, height,
                              col, material(f'City_{lot.style}', STYLE_COLORS[lot.style]))
                obj['condition'] = lot.condition
                obj['interiors'] = lot.interiors
                obj.location = (origin.x + lot.center[0], origin.y + lot.center[1], origin.z + self.curb_height)
                obj.rotation_euler.z = lot.rotation
                obj['city_style'], obj['asset_seed'], obj['district'] = lot.style, lot.seed, lot.district
                sunken = None
                if self.detail == 'SHELLS' and lot.condition != 'COLLAPSED':
                    x0, y0, x1, y1 = BuildingSpec(params).levels[0].rect
                    sunken = (x0 - lot.width / 2, y0 - lot.depth / 2,
                              x1 - lot.width / 2, y1 - lot.depth / 2)
                foundation = build_frontage(lot, plan, col, sunken)
                foundation.location = (origin.x + lot.center[0], origin.y + lot.center[1], origin.z)
                context.window_manager.progress_update(index + 1)
            if plan.pois or plan.shelters:
                build_sites(plan, root, origin, self.detail)
            plan_text = bpy.data.texts.new(f'{root.name}_plan.json')
            plan_text.write(plan.to_json())
            root['plan_text'] = plan_text.name
            root['origin'] = list(origin)
            root['driving_circuits'] = len(plan.driving_loops)
            message = (f'{len(plan.lots)} buildings, {len(plan.pois)} sites, '
                       f'{len(plan.roads)} road segments, {len(plan.driving_loops)} circuits')
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
    floors: IntProperty(name='Floors', default=3, min=1, max=40)
    seed: IntProperty(name='Seed', default=42)
    damage: FloatProperty(name='Damage', default=.35, min=0, max=1)
    interiors: BoolProperty(name='Interiors', default=False)
    lobby: EnumProperty(name='Lobby', items=[('AUTO', 'Auto', 'Chosen by the style and seed'),
                                             ('NONE', 'None', ''), ('GRAND', 'Grand Lobby', ''),
                                             ('RETAIL', 'Retail Podium', ''), ('ARCADE', 'Arcade', ''),
                                             ('PILOTIS', 'Pilotis', '')], default='AUTO')
    condition: EnumProperty(name='Condition',
                            items=[(condition, condition.replace('_', ' ').title(), '')
                                   for condition in CONDITIONS])

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
                                     self.seed, self.damage, self.interiors,
                                     self.condition)
            if self.lobby != 'AUTO' and self.condition != 'WALL_RING':
                params['lobby'] = self.lobby
                if self.lobby != 'NONE':
                    params['ground_floor_height'] = max(params['ground_floor_height'],
                                                        {'GRAND': 6.8}.get(self.lobby, 5.2))
            if self.condition == 'COLLAPSED':
                obj = create_rubble(self.style, params, collection)
            else:
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


_VARIANT_ITEMS = {kind: [('AUTO', 'Auto', 'Chosen by the seed')] +
                  [(v, v.replace('_', ' ').title(), '') for v in variants]
                  for kind, variants in SITE_VARIANTS.items()}


def _variant_items(self, context):
    return _VARIANT_ITEMS.get(self.kind, _VARIANT_ITEMS['PARK'])


class MESH_OT_generate_site(bpy.types.Operator):
    bl_idname = 'mesh.generate_city_site'
    bl_label = 'Generate Site (Point of Interest)'
    bl_description = 'Gas station, fast food, school, hospital, police or fire station, transit, park, parking or mall on its own pad'
    bl_options = {'REGISTER', 'UNDO'}

    kind: EnumProperty(name='Site', items=[(k, k.replace('_', ' ').title(), '') for k in SITE_KINDS],
                       default='GAS_STATION')
    variant: EnumProperty(name='Layout', items=_variant_items)
    width: FloatProperty(name='Width (along street)', default=40, min=16, max=160)
    depth: FloatProperty(name='Depth', default=40, min=16, max=160)
    seed: IntProperty(name='Seed', default=42)
    condition: EnumProperty(name='Condition',
                            items=[(condition, condition.replace('_', ' ').title(), '')
                                   for condition in CONDITIONS])
    damage: FloatProperty(name='Damage', default=.35, min=0, max=1)
    approach: FloatProperty(name='Front Approach (m)', default=2, min=0, max=12)
    detail: EnumProperty(name='Output', items=[('SHELLS', 'Detailed Shells', ''),
                                               ('PREVIEW', 'Layout Preview', '')])

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT'

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def execute(self, context):
        collection = bpy.data.collections.new(f'Site_{self.kind.title()}')
        context.collection.children.link(collection)
        try:
            variant = None if self.variant == 'AUTO' else self.variant
            if variant not in (None, *SITE_VARIANTS[self.kind]):
                variant = None
            site = compose_site(self.kind, self.width, self.depth, self.seed, variant,
                                self.condition, self.damage if self.condition != 'INTACT' else 0.0,
                                self.approach)
            builder = create_site if self.detail == 'SHELLS' else create_site_preview
            obj = builder(f'{self.kind.title()}_{self.seed}', site, collection)
            obj.location = context.scene.cursor.location
            obj['condition'], obj['asset_seed'] = self.condition, self.seed
            for note in site.notes:
                self.report({'WARNING'}, note)
            self.report({'INFO'}, f'{site.kind.title()} ({site.variant.title()}), '
                                  f'{len(site.buildings)} buildings')
            return {'FINISHED'}
        except Exception as exc:
            remove_generated_collection(collection)
            self.report({'ERROR'}, f'Site generation failed: {exc}')
            return {'CANCELLED'}


CLASSES = (MESH_OT_building_style, MESH_OT_generate_city, MESH_OT_generate_site)
