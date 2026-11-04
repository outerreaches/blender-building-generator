# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender adapter for the pure city plan and architecture recipes."""
import json
import math
import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from .city_plan import (CONDITIONS, PRESET_SETTINGS, VERSION, CitySettings, generate_city,
                        stream)
from .dims import GROUND_SLAB
from .metadata import SPACES as METADATA_SPACES, CityMetadata
from .spec import BuildingSpec
from .sites import (KINDS as SITE_KINDS, PAD_THICKNESS, VARIANTS as SITE_VARIANTS,
                    compose as compose_site)
from .streets import (Grading, build_freeway_mesh, build_ground_mesh, build_outer_road_mesh,
                      build_stair_mesh, build_street_mesh, build_viaduct_mesh, build_wall_mesh,
                      footprint, freeway_markings, junctions, lot_approach, lot_yard,
                      outer_road_dashes, pavement_height, site_footprint)
from .styles import NO_STRUCTURE, STYLE_ITEMS, STYLE_COLORS, building_recipe
from .city_export import store_city_metadata
from .building_assets import (addon_version, create_rubble, create_shell, create_shelter,
                              create_site, create_site_preview, material)


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


def box_between(name, low, high, collection, mat):
    """A box from corner ``low`` (x, y, z) to corner ``high``."""
    (x0, y0, z0), (x1, y1, z1) = low, high
    vertices = [(x, y, z) for z in (z0, z1) for y in (y0, y1) for x in (x0, x1)]
    faces = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4),
             (1, 3, 7, 5), (3, 2, 6, 7), (2, 0, 4, 6)]
    return mesh_object(name, vertices, faces, collection, mat)


def build_roads(plan, collection):
    """City streets, plus the highways running on out into the wasteland."""
    vertices, faces, indices = build_street_mesh(plan)
    obj = mesh_object('City_Streets', vertices, faces, collection,
                      material('City_Asphalt', (.085, .09, .10, 1)))
    obj.data.materials.append(material('City_Pavement', (.42, .41, .38, 1)))
    obj.data.materials.append(material('City_Curb', (.52, .50, .46, 1)))
    for poly, index in zip(obj.data.polygons, indices):
        poly.material_index = index
    obj['surface_role'] = 'streets'
    outer_vertices, outer_faces, outer_indices = build_outer_road_mesh(plan, vertices)
    if outer_faces:
        outer = mesh_object('City_Highway_Outskirts', outer_vertices, outer_faces, collection,
                            material('City_Asphalt', (.085, .09, .10, 1)))
        for name, color in (('City_Pavement', (.42, .41, .38, 1)), ('City_Curb', (.52, .50, .46, 1)),
                            ('City_Ground', (.23, .21, .17, 1))):
            outer.data.materials.append(material(name, color))
        for poly, index in zip(outer.data.polygons, outer_indices):
            poly.material_index = index
        outer['surface_role'] = 'streets_outskirts'
        outer['reach_m'] = [road['length'] for road in plan.outer_roads]
        outer.parent = obj
    return obj


def build_terrace_works(plan, collection, origin):
    """Retaining walls (with their parapets), stairs and viaducts of a
    terraced city."""
    concrete = material('City_Retaining_Wall', (.46, .45, .42, 1))
    vertices, faces = build_wall_mesh(plan)
    if faces:
        walls = mesh_object('City_Retaining_Walls', vertices, faces, collection, concrete)
        walls['surface_role'] = 'retaining_walls'
        walls.location = origin
    vertices, faces = build_stair_mesh(plan)
    if faces:
        stairs = mesh_object('City_Stairs', vertices, faces, collection,
                             material('City_Pavement', (.42, .41, .38, 1)))
        stairs['surface_role'] = 'stairs'
        stairs['stair_count'] = len(plan.terraces['stairs'])
        stairs.location = origin
    vertices, faces = build_viaduct_mesh(plan)
    if faces:
        decks = mesh_object('City_Viaducts', vertices, faces, collection, concrete)
        decks['surface_role'] = 'viaducts'
        decks.location = origin


def build_freeway(plan, collection, origin):
    """The raised highway: its decks and ramps (asphalt), with their fascias,
    parapets, median barrier and piers (concrete)."""
    vertices, faces, indices = build_freeway_mesh(plan)
    if not faces:
        return None
    obj = mesh_object('City_Freeway', vertices, faces, collection,
                      material('City_Asphalt', (.085, .09, .10, 1)))
    obj.data.materials.append(material('City_Retaining_Wall', (.46, .45, .42, 1)))
    for poly, index in zip(obj.data.polygons, indices):
        poly.material_index = index
    obj['surface_role'] = 'freeway'
    obj['interchanges'] = len(plan.freeway['interchanges'])
    obj.location = origin
    return obj


BULB_PATH = 3.0   # Width of the path from a house round a turning circle to its footway.


def build_frontage(lot, plan, collection, sunken=None, grading=None):
    """Level foundation and a clear concrete approach from sidewalk to entrance.

    ``sunken`` (x0, y0, x1, y1, centred on the lot) is the building's ground
    storey: the foundation drops there to the underside of its ground slab,
    so the two never share the floor plane. On terrain (``grading``) the
    foundation is the lot's level pad: a plinth down to the lowest graded
    ground under it, and an approach sloping from the footway to the pad.
    """
    h = plan.settings.curb_height + lot.level
    vertices, faces = [], []
    floor = -.2
    if grading is not None:
        floor = grading.lowest(footprint_with_approach(lot, plan)) - .2

    def slab(x0, y0, x1, y1, top=h):
        offset = len(vertices)
        vertices.extend([(x, y, z) for z in (floor, top)
                         for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
        faces.extend(tuple(offset + i for i in f) for f in
                     ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
                      (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))

    def ramp(x0, y0, x1, y1, front):
        """A slab whose top runs from the footway (front corners, y0) to the
        pad (back corners, y1); the top is two triangles."""
        offset = len(vertices)
        vertices.extend([(x0, y0, floor), (x1, y0, floor), (x1, y1, floor), (x0, y1, floor),
                         (x0, y0, front[0]), (x1, y0, front[1]), (x1, y1, h), (x0, y1, h)])
        faces.extend(tuple(offset + i for i in f) for f in
                     ((0, 3, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5, 4),
                      (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)))

    def footway(x, y):
        """Footway top at a lot-local point (relative to the city origin)."""
        c, s = math.cos(lot.rotation), math.sin(lot.rotation)
        wx, wy = lot.center[0] + x * c - y * s, lot.center[1] + x * s + y * c
        return grading.surface(wx, wy) + pavement_height(plan, wx, wy)
    # Local building coordinates: door faces -Y.
    half_w, half_d = lot.width / 2, lot.depth / 2
    size = plan.settings.block_size
    # A house round a turning circle gets a path to the circle's footway (a
    # full-width approach would square off against its curve).
    path = BULB_PATH / 2 if lot.bulb else None
    approach_end = lot_approach(lot, plan)
    front = half_d if path else approach_end
    if grading is not None:
        # The approach slopes from the footway's height to the pad's.
        reach = path if path else half_w
        if approach_end > half_d + .05:
            ramp(-reach, -approach_end, reach, -half_d,
                 (footway(-reach, -approach_end), footway(reach, -approach_end)))
        front = half_d
    elif path:
        slab(-path, -approach_end, path, -half_d)
    if sunken:
        xs = sorted({-half_w, half_w, sunken[0], sunken[2]})
        ys = sorted({-front, half_d, sunken[1], sunken[3]})
        for x0, x1 in zip(xs, xs[1:]):
            for y0, y1 in zip(ys, ys[1:]):
                if x1 - x0 < 1e-4 or y1 - y0 < 1e-4:
                    continue
                inside = (sunken[0] <= (x0 + x1) / 2 <= sunken[2] and
                          sunken[1] <= (y0 + y1) / 2 <= sunken[3])
                slab(x0, y0, x1, y1, h - GROUND_SLAB if inside else h)
    else:
        slab(-half_w, -front, half_w, half_d)
    obj = mesh_object(lot.id + '_Foundation', vertices, faces, collection,
                      material('City_Pavement', (.42, .41, .38, 1)))
    obj.rotation_euler.z = lot.rotation
    obj['surface_role'] = 'frontage'
    return obj


def footprint_with_approach(lot, plan):
    """World corners of a lot's foundation: the building and its approach."""
    return lot_yard(lot, plan)


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
    surface = plan.surface()
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
                    x = point[0] + normal[0] * (offset + side * .06)
                    y = point[1] + normal[1] * (offset + side * .06)
                    vertices.append((x, y, surface(x, y) + .004 if plan.heights else .004))
                faces.append(tuple(range(base, base + 4)))
                base += 4
            start += 7
    # Outer highways: worn dashes that thin out and stop where the road breaks up.
    for quad in outer_road_dashes(plan):
        base = len(vertices)
        vertices.extend((x, y, .004) for x, y in quad)
        faces.append(tuple(range(base, base + 4)))
    # The raised highway's lanes, on its deck.
    for quad in freeway_markings(plan):
        base = len(vertices)
        vertices.extend(quad)
        faces.append(tuple(range(base, base + 4)))
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
        surface = plan.surface()
        for point, (x, y) in zip(spline.points, points):
            point.co = (x, y, surface(x, y) + .25 + index * .25, 1)
        obj = bpy.data.objects.new(route['id'], curve)
        collection.objects.link(obj)
        obj.location = origin
        obj['length_m'] = route['length_m']
        obj['purpose'] = 'Debug route guide; excluded from city FBX export'
        curve.materials.append(material('City_Route_' + str(index), colors[index % len(colors)]))


def _object_facts(obj):
    """Entrances, height and enterable floors recorded on a building object."""
    if obj is None or 'entrances' not in obj:
        return (), None, None
    return ([tuple(e) for e in json.loads(obj['entrances'])], obj.get('height'),
            obj.get('enterable_floors'))


def build_sites(plan, root, origin, detail, props=True, meta=None, water=False, grading=None):
    """Points of interest (one object tree per site) and transit stops. On
    terrain (``grading``) every site's pad stands on a plinth down to the
    lowest graded ground under it."""
    collection = bpy.data.collections.new('Sites')
    root.children.link(collection)
    h = plan.settings.curb_height
    for poi in plan.pois:
        site = compose_site(poi.kind, poi.width, poi.depth, poi.seed, None, poi.condition,
                            poi.damage, poi.approach, props, water, poi.style)
        interiors = {}
        if detail == 'SHELLS':
            obj = create_site(poi.id, site, collection, interiors)
        else:
            obj = create_site_preview(poi.id, site, collection)
        obj.location = (origin.x + poi.center[0], origin.y + poi.center[1], origin.z + h + poi.level)
        obj.rotation_euler.z = poi.rotation
        if grading is not None:
            top = h + poi.level
            bottom = grading.lowest(site_footprint(poi)) - .2 - top
            x0, x1 = -poi.width / 2, poi.width / 2
            y0, y1 = -poi.depth / 2 - poi.approach, poi.depth / 2
            plinth = box_between(f'{poi.id}_Plinth', (x0, y0, bottom), (x1, y1, -PAD_THICKNESS),
                                 collection, material('City_Pavement', (.42, .41, .38, 1)))
            plinth.parent = obj
            plinth['surface_role'] = 'site_plinth'
        obj['condition'], obj['district'], obj['city_style'] = poi.condition, poi.district, poi.style
        obj['asset_seed'] = poi.seed
        if meta is not None:
            names = list(obj.get('building_objects', []))
            made = []
            for building, name in zip(site.buildings, names):
                made.append((building, name) + _object_facts(bpy.data.objects.get(name)) +
                            (interiors.get(name),))
            meta.add_site(poi, site, obj.name, made)
    meshes = {}
    for shelter in plan.shelters:
        obj = create_shelter(shelter.id, shelter.variant, collection, meshes)
        obj.location = (origin.x + shelter.position[0], origin.y + shelter.position[1],
                        origin.z + h + shelter.level)
        obj.rotation_euler.z = shelter.rotation
        if meta is not None:
            meta.add_shelter(shelter, obj.name)
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


def _apply_preset(self, context):
    """Choosing a preset sets the sizes and densities that suit it (still editable)."""
    for key, value in PRESET_SETTINGS[self.preset].items():
        setattr(self, key, value)


class MESH_OT_generate_city(bpy.types.Operator):
    bl_idname = 'mesh.generate_procedural_city'
    bl_label = 'Generate City'
    bl_description = 'Grow a seeded city with connected roads and district building styles'
    bl_options = {'REGISTER', 'UNDO'}

    preset: EnumProperty(name='Preset', default='CITY', update=_apply_preset,
                         items=[('CITY', 'City', 'Districts round a downtown of towers, every kind '
                                 'of site'),
                                ('SMALL_TOWN', 'Small Town', 'An old-town main street with homes '
                                 'round it and an industrial edge: low buildings, only the sites '
                                 'a town has')])
    seed: IntProperty(name='City Seed', default=42)
    radius: IntProperty(name='Radius (Blocks)', default=6, min=2, max=25)
    shape: EnumProperty(name='City Shape', default='SQUARE',
                        items=[('SQUARE', 'Square', 'Streets and buildings fill the whole map'),
                               ('ORGANIC', 'Organic', 'An irregular edge with lobes, notches and '
                                'fingers along the roads; the city fills less of the map')])
    irregularity: FloatProperty(name='Irregularity', default=.6, min=0, max=1,
                                description='How far an organic edge wanders (0: round)')
    terrain: EnumProperty(name='Terrain', default='FLAT',
                          items=[('FLAT', 'Flat', 'Everything on one level'),
                                 ('ROLLING', 'Rolling Hills', 'Gentle seeded hills; streets are '
                                  'graded to their limits and buildings stand on level pads'),
                                 ('TERRACED', 'Terraced', 'Rolling hills carrying a plateau and '
                                  'low podiums of whole blocks behind retaining walls, reached '
                                  'by ramps and stairs')])
    relief: FloatProperty(name='Relief (m)', default=30.0, min=0, max=40,
                          description='Hills: metres from the lowest ground to the '
                                      'highest (the map\'s edge stays level, which holds small '
                                      'maps lower)')
    plateau_height: FloatProperty(name='Plateau Height (m)', default=9.0, min=0, max=30,
                                  description='Terraced: how far the plateau rises above the '
                                              'streets round it (0: no plateau)')
    podiums: IntProperty(name='Podiums', default=1, min=0, max=3,
                         description='Terraced: low raised compounds of a few blocks, '
                                     'one storey up')
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
    highway: EnumProperty(name='Highway', default='RAISED',
                          items=[('RAISED', 'Raised', 'A viaduct straight across the city, the '
                                  'streets passing under it, joined to them at diamond '
                                  'interchanges; at grade again out in the wasteland'),
                                 ('GRADE', 'At Grade', 'A street like the others, crossing the '
                                  'city through its junctions')])
    highway_reach: FloatProperty(name='Highway Reach (m)', default=3000, min=0, max=20000,
                                 description='How far the highways run on beyond the city edge, '
                                             'breaking up into the ground over the last 40%; '
                                             'never past the wasteland')
    damage: FloatProperty(name='Building Damage', default=.35, min=0, max=1)
    max_buildings: IntProperty(name='Building Budget', default=600, min=1, max=10000)
    style: EnumProperty(name='Architecture', items=[('MIXED', 'Mixed Districts', 'Styles vary by primary location')] + STYLE_ITEMS)
    detail: EnumProperty(name='Output', items=[('PREVIEW', 'Layout Preview', 'Fast building masses for planning'),
                                               ('SHELLS', 'Detailed Shells', 'Generate windows, doors and damage')])
    interior_ratio: FloatProperty(name='Interior Ratio', default=.25, min=0, max=1,
                                 description='Fraction of enterable buildings that get full interior layouts')
    route_guides: BoolProperty(name='Show Driving Route Guides', default=False)
    downtown_superblocks: FloatProperty(name='Downtown Superblocks', default=.35, min=0, max=1,
                                        description='Share of downtown local streets closed so '
                                                    'blocks join into towers on 2x1 and 2x2 superblocks')
    district_superblocks: FloatProperty(name='District Superblocks', default=.5, min=0, max=1,
                                        description='Chance that blocks of an old town, residential, '
                                                    'brutalist or industrial district join into a 2x1 '
                                                    'or 2x2 superblock (perimeter rows round a courtyard, '
                                                    'estate slabs, a compound); 0 keeps every street')
    small_props: BoolProperty(name='Small Props', default=True,
                              description='Model benches, gas pumps, lamps, bollards, bins, dumpsters, tables, '
                                          'play equipment, goals, booths, hydrants and cart corrals. Off: the game '
                                          'places them from the city metadata')
    water: BoolProperty(name='Water', default=False,
                        description='Model water in fountains and other basins. Off: they are '
                                    'dry and the game fills them from the water markers')
    metadata_space: EnumProperty(name='Metadata Space',
                                 items=[('UNITY', 'Unity', 'Unity world space as the exported FBX imports'),
                                        ('BLENDER', 'Blender', 'Blender world space, Z up')],
                                 description='Coordinate space of the city metadata JSON')
    interior_metadata: BoolProperty(name='Interior Metadata', default=True,
                                    description='List every building\'s rooms (to furnish), lifts and '
                                                'railings in the city metadata; these are game assets and are '
                                                'not modelled. Off: a much smaller file')
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
            ('City Growth', ('preset', 'seed', 'radius', 'shape', 'irregularity', 'block_size', 'primary_count', 'secondary_count', 'driving_loop_count')),
            ('Terrain', ('terrain', 'relief', 'plateau_height', 'podiums')),
            ('Density and Access', ('curve_radius', 'core_radius', 'core_density', 'outskirts_density', 'road_density', 'setback', 'sidewalk_width', 'curb_height', 'wasteland', 'highway', 'highway_reach')),
            ('Buildings', ('style', 'damage', 'max_buildings', 'downtown_superblocks',
                           'district_superblocks', 'points_of_interest', 'small_props', 'water',
                           'detail')),
            ('Game Data', ('metadata_space', 'interior_metadata')),
        ):
            group = layout.box()
            group.label(text=title)
            for name in names:
                if name == 'irregularity' and self.shape != 'ORGANIC':
                    continue
                if name == 'relief' and self.terrain == 'FLAT':
                    continue
                if name in ('plateau_height', 'podiums') and self.terrain != 'TERRACED':
                    continue
                group.prop(self, name)
        if self.detail == 'SHELLS':
            layout.prop(self, 'interior_ratio')
        layout.prop(self, 'lane_markings')
        layout.prop(self, 'route_guides')
        layout.label(text='Streets meet at grade; only the raised highway bridges them.',
                     icon='INFO')
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
            root['city_preset'] = self.preset
            root['city_shape'] = self.shape
            root['city_terrain'] = self.terrain
            root['city_highway'] = self.highway
            root['generator_version'] = VERSION
            root['addon_version'] = addon_version()
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
            if plan.terraces:
                build_terrace_works(plan, root, origin)
            if plan.freeway:
                build_freeway(plan, root, origin)
            grading = Grading(plan) if plan.heights else None
            context.window_manager.progress_begin(0, max(1, len(plan.lots)))
            meta = CityMetadata(plan, tuple(origin), self.metadata_space, self.small_props,
                                addon_version(), root.name, self.interior_metadata, self.water)
            for index, lot in enumerate(plan.lots):
                col = districts[lot.district]
                params = building_recipe(lot.style, lot.width, lot.depth, lot.floors,
                                         lot.seed, lot.damage, lot.interiors,
                                         lot.condition, lot.party_walls)
                facts = {}
                if self.detail == 'SHELLS':
                    if lot.condition == 'COLLAPSED':
                        obj = create_rubble(lot.id, params, col)
                    else:
                        obj = create_shell(lot.id, params, col, facts)
                    obj.data.materials[0] = material(f'City_{lot.style}', STYLE_COLORS[lot.style])
                else:
                    height = (2.2 if lot.condition == 'COLLAPSED'
                              else lot.floors * params['floor_height'])
                    obj = box(lot.id, lot.width, lot.depth, height,
                              col, material(f'City_{lot.style}', STYLE_COLORS[lot.style]))
                obj['condition'] = lot.condition
                obj['interiors'] = lot.interiors
                obj['structure'] = 'FITTED' if lot.interiors else params.get('structure', 'NONE')
                obj.location = (origin.x + lot.center[0], origin.y + lot.center[1],
                                origin.z + self.curb_height + lot.level)
                obj.rotation_euler.z = lot.rotation
                obj['city_style'], obj['asset_seed'], obj['district'] = lot.style, lot.seed, lot.district
                if lot.party_walls:
                    obj['party_walls'] = ','.join(lot.party_walls)
                sunken = None
                if self.detail == 'SHELLS' and lot.condition != 'COLLAPSED':
                    x0, y0, x1, y1 = BuildingSpec(params).levels[0].rect
                    sunken = (x0 - lot.width / 2, y0 - lot.depth / 2,
                              x1 - lot.width / 2, y1 - lot.depth / 2)
                foundation = build_frontage(lot, plan, col, sunken, grading)
                foundation.location = (origin.x + lot.center[0], origin.y + lot.center[1], origin.z)
                entrances, height, floors = _object_facts(obj)
                if height is None:
                    height = (2.2 if lot.condition == 'COLLAPSED'
                              else lot.floors * params['floor_height'])
                meta.add_lot(lot, obj.name, entrances, height, floors, facts.get('interior'),
                             params.get('structure', 'NONE'))
                context.window_manager.progress_update(index + 1)
            if plan.pois or plan.shelters:
                build_sites(plan, root, origin, self.detail, self.small_props, meta, self.water,
                            grading)
            store_city_metadata(root, meta.as_dict())
            root['small_props'] = self.small_props
            root['water'] = self.water
            root['interior_metadata'] = self.interior_metadata
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
    structure: EnumProperty(
        name='Structure', description='Stairs and walls of a building without interiors',
        items=[('AUTO', 'Auto', 'Chosen by the condition and seed'),
               ('PARTITIONS', 'Partitions', "Stairs and the program's walls"),
               ('BEARING', 'Bearing Walls', 'Gutted to its cores, corridors and the walls '
                'between flats, with rubble on the floors'),
               ('NONE', 'None', 'Empty floors with no stairs')],
        default='AUTO')
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
            if (self.structure != 'AUTO' and not self.interiors and
                    self.condition not in NO_STRUCTURE):
                params.update(structure=self.structure, floor_rubble=self.structure == 'BEARING')
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
            obj['structure'] = 'FITTED' if self.interiors else params.get('structure', 'NONE')
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
    small_props: BoolProperty(name='Small Props', default=True,
                              description='Model benches, pumps, lamps and other small props '
                                          '(off: only their markers, in the site metadata)')
    water: BoolProperty(name='Water', default=False,
                        description='Model water in fountains and other basins. Off: they are '
                                    'dry and the game fills them from the water markers')
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
                                self.approach, self.small_props, self.water)
            builder = create_site if self.detail == 'SHELLS' else create_site_preview
            obj = builder(f'{self.kind.title()}_{self.seed}', site, collection)
            obj.location = context.scene.cursor.location
            obj['condition'], obj['asset_seed'] = self.condition, self.seed
            # Placements for game assets, in the site's object space.
            obj['markers'] = json.dumps(site.markers)
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
