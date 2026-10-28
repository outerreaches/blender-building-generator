# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared Blender material and shell creation services."""
import math
import random
from collections import Counter
import bmesh
import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree
from .mesh_builder import BuildingShellBuilder

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


def _face(bm, vertices, material):
    face = bm.faces.new(vertices)
    face.material_index = material
    face.smooth = False
    return face


def _delete_box(bm, x0, x1, y0, y1, z0, z1):
    """Remove walls, slabs and glazing inside a box; keep rubble fill visible."""
    doomed = []
    for face in bm.faces:
        if face.material_index == 7:
            continue
        centre = face.calc_center_median()
        if x0 < centre.x < x1 and y0 < centre.y < y1 and z0 < centre.z < z1:
            doomed.append(face)
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')


def _cap_wall_box(bm, params, x0, x1, y0, y1, z):
    """Close the wall thickness at a horizontal cut (chunk base)."""
    width, depth = params['width'], params['depth']
    thickness = params.get('wall_thickness', .25)
    caps = []
    if x0 <= .01:
        caps.append((0, max(y0, 0), thickness, min(y1, depth)))
    if x1 >= width - .01:
        caps.append((width - thickness, max(y0, 0), width, min(y1, depth)))
    if y0 <= .01:
        caps.append((max(x0 + (thickness if x0 <= .01 else 0), 0), 0, x1, thickness))
    if y1 >= depth - .01:
        caps.append((max(x0 + (thickness if x0 <= .01 else 0), 0), depth - thickness,
                      x1, depth))
    for cap in caps:
        cx0, cy0, cx1, cy1 = cap
        if cx1 <= cx0 or cy1 <= cy0:
            continue
        vertices = [bm.verts.new((x, y, z))
                    for x, y in ((cx0, cy0), (cx1, cy0), (cx1, cy1), (cx0, cy1))]
        _face(bm, vertices, 0)


def _bisect_plane(bm, axis, value):
    """Split faces exactly on an axis plane so cut caps can be built."""
    centre = [0.0, 0.0, 0.0]
    normal = [0.0, 0.0, 0.0]
    centre[axis] = value
    normal[axis] = 1.0
    bmesh.ops.bisect_plane(
        bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], dist=1e-6,
        plane_co=Vector(centre), plane_no=Vector(normal),
        clear_outer=False, clear_inner=False)


def _plane_cap_loops(bm, axis, value, low, high, max_thickness):
    """Boundary loops on an axis plane inside the given other-axis bounds."""
    eps = 1e-5
    edges = []
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        if any(abs(v.co[axis] - value) > eps for v in edge.verts):
            continue
        if any(not (low[i] - eps <= v.co[i] <= high[i] + eps)
               for v in edge.verts for i in range(3) if i != axis):
            continue
        edges.append(edge)
    if not edges:
        return []
    adjacency = {}
    for edge in edges:
        for vert in edge.verts:
            adjacency.setdefault(vert, []).append(edge)
    remaining = set(edges)
    loops = []
    while remaining:
        edge = remaining.pop()
        start = edge.verts[0]
        vert = edge.verts[1]
        loop = [edge]
        ordered = [start, vert]
        closed = False
        while True:
            candidates = [e for e in adjacency.get(vert, ()) if e in remaining]
            if not candidates:
                closed = vert == start
                break
            following = candidates[0]
            remaining.remove(following)
            loop.append(following)
            vert = following.verts[1] if following.verts[0] == vert else following.verts[0]
            if vert == start:
                closed = True
                break
            ordered.append(vert)
            if len(loop) > 10000:
                break
        if closed and len(ordered) >= 3:
            extents = []
            for i in range(3):
                if i == axis:
                    continue
                values = [v.co[i] for v in ordered]
                extents.append(max(values) - min(values))
            if not extents or min(extents) > max_thickness:
                continue
            materials = Counter()
            for item in loop:
                for face in item.link_faces:
                    materials[face.material_index] += 1
            if not materials:
                continue
            if any(index in (3, 4) for index in materials):
                continue
            material = materials.most_common(1)[0][0]
            if material == 0 and axis != 2:
                # Large wall cut/inside faces are legitimate caps; only frame
                # openings are excluded above. Horizontal caps stay thin.
                loops.append((ordered, material))
                continue
            if min(extents) > max_thickness:
                continue
            loops.append((ordered, material))
    return loops


def _cut_box_with_caps(bm, params, x0, x1, y0, y1, z0):
    """Remove an upper box and cap every solid cross-section on the cut.

    Bisecting at the box planes makes the removal exact; filling the resulting
    boundary loops leaves wall thickness, floor-slab edges and interior walls
    capped instead of showing their hollow interiors.
    """
    width, depth = params['width'], params['depth']
    top = params['floors'] * params['floor_height'] + 1.0
    eps = 1e-5

    # Split only interior planes; outer planes are already the building skin.
    if eps < x0 < width - eps:
        _bisect_plane(bm, 0, x0)
    if eps < x1 < width - eps:
        _bisect_plane(bm, 0, x1)
    if eps < y0 < depth - eps:
        _bisect_plane(bm, 1, y0)
    if eps < y1 < depth - eps:
        _bisect_plane(bm, 1, y1)
    _bisect_plane(bm, 2, z0)

    doomed = []
    for face in bm.faces:
        centre = face.calc_center_median()
        if (x0 + eps < centre.x < x1 - eps and
                y0 + eps < centre.y < y1 - eps and centre.z > z0 + eps):
            doomed.append(face)
    if doomed:
        bmesh.ops.delete(bm, geom=doomed, context='FACES')

    plane_specs = []
    if eps < x0 < width - eps:
        plane_specs.append((0, x0, (y0, y1, z0), (y0, y1, top), Vector((1, 0, 0))))
    if eps < x1 < width - eps:
        plane_specs.append((0, x1, (y0, y1, z0), (y0, y1, top), Vector((-1, 0, 0))))
    if eps < y0 < depth - eps:
        plane_specs.append((1, y0, (x0, x1, z0), (x0, x1, top), Vector((0, 1, 0))))
    if eps < y1 < depth - eps:
        plane_specs.append((1, y1, (x0, x1, z0), (x0, x1, top), Vector((0, -1, 0))))
    plane_specs.append((2, z0, (x0, y0, 0), (x1, y1, top), Vector((0, 0, 1))))

    max_thickness = max(params.get('wall_thickness', .25), .2) + .1
    caps = []
    for axis, value, low, high, outward in plane_specs:
        for vertices, material in _plane_cap_loops(
                bm, axis, value, low, high, max_thickness):
            caps.append((vertices, material, outward))

    for vertices, material, outward in caps:
        try:
            face = bm.faces.new(vertices)
        except ValueError:
            continue
        face.material_index = material
        face.normal_update()
        if face.normal.dot(outward) < 0:
            face.normal_flip()


def _repair_wall_shell(bm, params):
    """Restore missing inner facade faces and wall-top caps after damage.

    Damage/chunk removal can leave the outer wall face in place while deleting
    its inner counterpart. Duplicate each outer wall face inward when no inner
    face exists, then pair the remaining top edges into caps.
    """
    thickness = params.get('wall_thickness', .25)
    bm.normal_update()
    outer_faces = [f for f in bm.faces if f.material_index == 0]
    if not outer_faces:
        return
    tree = KDTree(len(outer_faces))
    for index, face in enumerate(outer_faces):
        tree.insert(face.calc_center_median(), index)
    tree.balance()
    added = 0
    for face in list(outer_faces):
        normal = face.normal.copy()
        centre = face.calc_center_median()
        if abs(normal.z) > .3 or abs(normal.x) + abs(normal.y) < .7:
            continue
        if normal.x * centre.x + normal.y * centre.y <= 0:
            continue
        target = centre - normal * thickness
        hit = tree.find(target)
        if hit is not None and hit[2] < .08 and outer_faces[hit[1]].normal.dot(-normal) > .8:
            continue
        vertices = [bm.verts.new(v.co - normal * thickness) for v in face.verts]
        try:
            inner = bm.faces.new(list(reversed(vertices)))
        except ValueError:
            continue
        inner.material_index = 0
        inner.normal_update()
        added += 1
    bm.normal_update()

    boundary = []
    for edge in bm.edges:
        if not edge.is_boundary or not edge.link_faces:
            continue
        if any(face.material_index != 0 for face in edge.link_faces):
            continue
        a, b = edge.verts
        if abs(a.co.z - b.co.z) > 1e-4 or a.co.z < .5:
            continue
        boundary.append(edge)
    used = set()
    caps = 0
    for index, edge in enumerate(boundary):
        if edge in used:
            continue
        a, b = edge.verts
        for other in boundary[index + 1:]:
            if other in used:
                continue
            c, d = other.verts
            for p, q in ((c, d), (d, c)):
                offset_a = p.co - a.co
                offset_b = q.co - b.co
                if (abs(offset_a.z) < 1e-4 and abs(offset_b.z) < 1e-4 and
                        abs(offset_a.length - thickness) < .03 and
                        abs(offset_b.length - thickness) < .03 and
                        (offset_a - offset_b).length < .03):
                    try:
                        cap = bm.faces.new((a, b, q, p))
                    except ValueError:
                        continue
                    cap.material_index = 0
                    cap.normal_update()
                    if cap.normal.z < 0:
                        cap.normal_flip()
                    used.add(edge)
                    used.add(other)
                    caps += 1
                    break
            if edge in used:
                break


def _cap_vertical_wall_ends(bm, params):
    """Cap vertical wall ends where a spike or cut left the thickness open."""
    thickness = params.get('wall_thickness', .25)
    edges = []
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        faces = edge.link_faces
        if not faces or any(face.material_index in (3, 4) for face in faces):
            continue
        if any(face.material_index != 0 for face in faces):
            continue
        a, b = edge.verts
        if abs(a.co.x - b.co.x) > 1e-4 or abs(a.co.y - b.co.y) > 1e-4:
            continue
        if abs(a.co.z - b.co.z) < .05:
            continue
        edges.append(edge)
    used = set()
    for index, edge in enumerate(edges):
        if edge in used:
            continue
        a, b = edge.verts
        za, zb = sorted((a.co.z, b.co.z))
        for other in edges[index + 1:]:
            if other in used:
                continue
            c, d = other.verts
            zc, zd = sorted((c.co.z, d.co.z))
            if abs(za - zc) > .02 or abs(zb - zd) > .02:
                continue
            dx = c.co.x - a.co.x
            dy = c.co.y - a.co.y
            if abs((dx * dx + dy * dy) ** .5 - thickness) > .03:
                continue
            if abs((d.co.x - b.co.x) - dx) > .03 or abs((d.co.y - b.co.y) - dy) > .03:
                continue
            low_a, high_a = (a, b) if a.co.z < b.co.z else (b, a)
            low_c, high_c = (c, d) if c.co.z < d.co.z else (d, c)
            try:
                face = bm.faces.new((low_a, low_c, high_c, high_a))
            except ValueError:
                continue
            face.material_index = 0
            face.normal_update()
            adjacent = [f.calc_center_median() for e in (edge, other)
                        for f in e.link_faces if f.is_valid]
            if adjacent:
                centre = sum(adjacent, Vector()) / len(adjacent)
                away = centre - face.calc_center_median()
                if away.length > 1e-5 and face.normal.dot(away) > 0:
                    face.normal_flip()
            used.add(edge)
            used.add(other)
            break


def _cap_floor_edges(bm):
    """Add missing vertical sides where floor slabs were cut or opened."""
    edges = []
    for edge in bm.edges:
        if not edge.is_boundary or len(edge.link_faces) != 1:
            continue
        if edge.link_faces[0].material_index != 1:
            continue
        a, b = edge.verts
        if abs(a.co.z - b.co.z) > 1e-4:
            continue
        edges.append(edge)
    used = set()
    for index, edge in enumerate(edges):
        if edge in used:
            continue
        a, b = edge.verts
        for other in edges[index + 1:]:
            if other in used:
                continue
            c, d = other.verts
            dz = abs(a.co.z - c.co.z)
            if not (.03 <= dz <= .5):
                continue
            for p, q in ((c, d), (d, c)):
                if ((p.co - a.co).xy.length < .02 and
                        (q.co - b.co).xy.length < .02):
                    first, second = (edge, other) if a.co.z > c.co.z else (other, edge)
                    top = first
                    bottom = second
                    t0, t1 = top.verts
                    b0, b1 = bottom.verts
                    if (t0.co - b0.co).xy.length < .02:
                        quad = [t0, t1, b1, b0]
                    else:
                        quad = [t0, t1, b0, b1]
                    try:
                        face = bm.faces.new(quad)
                    except ValueError:
                        continue
                    face.material_index = 1
                    face.normal_update()
                    source = top.link_faces[0] if top.link_faces else None
                    if source is not None:
                        edge_mid = (t0.co + t1.co) / 2
                        centre = source.calc_center_median()
                        radial = Vector((edge_mid.x - centre.x,
                                         edge_mid.y - centre.y, 0.0))
                        if radial.length > 1e-5 and face.normal.dot(radial) < 0:
                            face.normal_flip()
                    used.add(edge)
                    used.add(other)
                    break
            if edge in used:
                break


def _cap_small_wall_loops(bm, params):
    """Close small open wall loops left on spikes and wall-top gaps."""
    seeds = []
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        faces = edge.link_faces
        if not faces or any(face.material_index in (3, 4) for face in faces):
            continue
        if any(face.material_index != 0 for face in faces):
            continue
        seeds.append(edge)
    remaining = set(seeds)
    components = []
    while remaining:
        edge = remaining.pop()
        stack = [edge]
        component = [edge]
        verts = set(edge.verts)
        while stack:
            current = stack.pop()
            for vert in current.verts:
                for candidate in vert.link_edges:
                    if candidate in remaining:
                        remaining.remove(candidate)
                        stack.append(candidate)
                        component.append(candidate)
                        verts.add(candidate.verts[0])
                        verts.add(candidate.verts[1])
        components.append(component)
    for component in components:
        old_faces = set(bm.faces)
        result = bmesh.ops.holes_fill(bm, edges=component, sides=0)
        new_faces = [face for face in result.get('faces', []) if face.is_valid]
        for face in new_faces:
            xs = [v.co.x for v in face.verts]
            ys = [v.co.y for v in face.verts]
            zs = [v.co.z for v in face.verts]
            if max(max(xs) - min(xs), max(ys) - min(ys),
                   max(zs) - min(zs)) > 4.0:
                bmesh.ops.delete(bm, geom=[face], context='FACES')
                continue
            face.material_index = 0
            face.normal_update()
            adjacent = [f.calc_center_median() for e in component
                        for f in e.link_faces if f.is_valid]
            if adjacent:
                centre = sum(adjacent, Vector()) / len(adjacent)
                away = centre - face.calc_center_median()
                if away.length > 1e-5 and face.normal.dot(away) > 0:
                    face.normal_flip()


def _cap_horizontal_wall_loops(bm):
    """Fill small horizontal wall loops such as spike tops and floor-line caps."""
    groups = {}
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        faces = edge.link_faces
        if not faces or any(face.material_index in (3, 4) for face in faces):
            continue
        if any(face.material_index != 0 for face in faces):
            continue
        a, b = edge.verts
        if abs(a.co.z - b.co.z) > 1e-4:
            continue
        groups.setdefault(round(a.co.z, 2), []).append(edge)
    for edges in groups.values():
        result = bmesh.ops.holes_fill(bm, edges=edges, sides=0)
        for face in result.get('faces', []):
            if not face.is_valid:
                continue
            xs = [v.co.x for v in face.verts]
            ys = [v.co.y for v in face.verts]
            zs = [v.co.z for v in face.verts]
            if max(max(xs) - min(xs), max(ys) - min(ys),
                   max(zs) - min(zs)) > 3.0:
                bmesh.ops.delete(bm, geom=[face], context='FACES')
                continue
            face.material_index = 0
            face.normal_update()
            if face.normal.z < 0:
                face.normal_flip()


def _cap_small_top_hulls(bm):
    """Cap small open top boundaries, including damage spikes.

    These loops can be open chains rather than closed holes, so a convex
    fan over the boundary vertices is used instead of holes_fill.
    """
    groups = {}
    for edge in bm.edges:
        if not edge.is_boundary:
            continue
        faces = edge.link_faces
        if not faces or any(face.material_index in (3, 4) for face in faces):
            continue
        if any(face.material_index != 0 for face in faces):
            continue
        a, b = edge.verts
        if abs(a.co.z - b.co.z) > 1e-4:
            continue
        groups.setdefault(round(a.co.z, 2), []).append(edge)
    for z, edges in groups.items():
        remaining = set(edges)
        while remaining:
            edge = remaining.pop()
            component = [edge]
            verts = set(edge.verts)
            stack = [edge]
            while stack:
                current = stack.pop()
                for vert in current.verts:
                    for candidate in vert.link_edges:
                        if candidate in remaining:
                            remaining.remove(candidate)
                            stack.append(candidate)
                            component.append(candidate)
                            verts.add(candidate.verts[0])
                            verts.add(candidate.verts[1])
            unique = []
            seen = set()
            for vert in verts:
                key = (round(vert.co.x, 3), round(vert.co.y, 3), round(vert.co.z, 3))
                if key not in seen:
                    seen.add(key)
                    unique.append(vert)
            if len(unique) < 3:
                continue
            xs = [v.co.x for v in unique]
            ys = [v.co.y for v in unique]
            if max(max(xs) - min(xs), max(ys) - min(ys)) > 3.0:
                continue
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            unique.sort(key=lambda v: math.atan2(v.co.y - cy, v.co.x - cx))
            try:
                face = bm.faces.new(unique)
            except ValueError:
                continue
            face.material_index = 0
            face.normal_update()
            if face.normal.z < 0:
                face.normal_flip()


def expose_fill_bay(bm, params):
    """Open a ground-floor bay so a solid or half-filled interior is visible."""
    rng = random.Random(params.get('seed', 0) ^ 0x3F11)
    width, depth = params['width'], params['depth']
    floor_height = params['floor_height']
    bay_width = width * rng.uniform(.22, .38)
    bay_depth = depth * rng.uniform(.35, .6)
    height = floor_height * rng.uniform(1.6, 2.4)
    side = rng.randrange(4)
    if side == 0:
        _delete_box(bm, width * .08, width * .08 + bay_width, 0, bay_depth, 0, height)
    elif side == 1:
        _delete_box(bm, width * .08, width * .08 + bay_width,
                    depth - bay_depth, depth, 0, height)
    elif side == 2:
        _delete_box(bm, 0, bay_depth, depth * .08, depth * .08 + bay_width, 0, height)
    else:
        _delete_box(bm, width - bay_depth, width,
                    depth * .08, depth * .08 + bay_width, 0, height)


def subtract_chunks(bm, params):
    """Remove whole upper chunks from a standing shell.

    A corner chunk plus, on taller buildings, a mid-height facade bite. The
    removed volume takes walls, slabs and glass with it, leaving open polygonal
    cuts; debris is added at the corner afterwards. The ground floors are never
    touched, so the building stays enterable.
    """
    rng = random.Random(params.get('seed', 0) ^ 0xB10C)
    width, depth = params['width'], params['depth']
    floor_height = params['floor_height']
    total = params['floors'] * floor_height
    sign_x, sign_y = rng.choice((-1, 1)), rng.choice((-1, 1))
    aggressive = params['floors'] >= 8
    very_tall = params['floors'] >= 12

    chunk_width = (width * rng.uniform(.45, .7) if very_tall else
                   width * rng.uniform(.38, .6) if aggressive else
                   width * rng.uniform(.32, .52))
    chunk_depth = (depth * rng.uniform(.45, .7) if very_tall else
                   depth * rng.uniform(.38, .6) if aggressive else
                   depth * rng.uniform(.32, .52))
    chunk_base = total * (rng.uniform(.28, .5) if very_tall else
                          rng.uniform(.3, .52) if aggressive else
                          rng.uniform(.45, .68))
    x0, x1 = ((0, chunk_width) if sign_x < 0 else (width - chunk_width, width))
    y0, y1 = ((0, chunk_depth) if sign_y < 0 else (depth - chunk_depth, depth))
    cuts = [(x0, x1, y0, y1, chunk_base)]

    if params['floors'] >= 4 and (aggressive or rng.random() < .6):
        # A second failure is a vertical bay removal that runs out through the
        # top, not a floating hole: lost slices take their support above with them.
        side = rng.randrange(4)
        bite = rng.uniform(.3, .5) if aggressive else rng.uniform(.25, .4)
        base = total * (rng.uniform(.18, .42) if aggressive else rng.uniform(.25, .5))
        if side == 0:
            bx0 = width * rng.uniform(.05, .3)
            box = (bx0, bx0 + width * bite, 0, depth * rng.uniform(.2, .45))
        elif side == 1:
            bx0 = width * rng.uniform(.05, .3)
            box = (bx0, bx0 + width * bite, depth * rng.uniform(.55, .8), depth)
        elif side == 2:
            by0 = depth * rng.uniform(.05, .3)
            box = (0, width * rng.uniform(.2, .45), by0, by0 + depth * bite)
        else:
            by0 = depth * rng.uniform(.05, .3)
            box = (width * rng.uniform(.55, .8), width, by0, by0 + depth * bite)
        cuts.append((box[0], box[1], box[2], box[3], base))
    for xa, xb, ya, yb, z in cuts:
        _cut_box_with_caps(bm, params, xa, xb, ya, yb, z)
        _cap_wall_box(bm, params, xa, xb, ya, yb, z)
    return sign_x, sign_y


def _bm_mound(bm, centre_x, centre_y, radius_x, radius_y, peak, rng,
              segments=10, rings=3):
    angles = [2 * math.pi * index / segments for index in range(segments)]
    jitter = [rng.uniform(.82, 1.15) for _ in range(segments)]
    apex = bm.verts.new((centre_x, centre_y, peak))
    ring_verts = []
    for ring in range(1, rings + 1):
        t = ring / rings
        height = peak * (1 - t) ** 1.3
        ring_verts.append([bm.verts.new(
            (centre_x + math.cos(angle) * radius_x * t * jitter[index],
             centre_y + math.sin(angle) * radius_y * t * jitter[index],
             max(0.0, height + rng.uniform(-.08, .08) * peak)))
            for index, angle in enumerate(angles)])
    for index in range(segments):
        following = (index + 1) % segments
        _face(bm, (apex, ring_verts[0][index], ring_verts[0][following]), 7)
    for ring in range(1, rings):
        inner, outer = ring_verts[ring - 1], ring_verts[ring]
        for index in range(segments):
            following = (index + 1) % segments
            _face(bm, (inner[index], outer[index], outer[following],
                       inner[following]), 7)


def add_interior_mound(bm, params):
    """Rubble mound inside a standing wall ring, visible from above."""
    rng = random.Random(params.get('seed', 0) ^ 0x1A0D)
    width, depth = params['width'], params['depth']
    wall = params.get('wall_thickness', .25)
    radius_x = max(1.5, width / 2 - wall - .5)
    radius_y = max(1.5, depth / 2 - wall - .5)
    peak = min(params['floors'] * params['floor_height'] * .55,
               rng.uniform(1.8, 3.6))
    _bm_mound(bm, width / 2, depth / 2, radius_x, radius_y, peak, rng)


def add_corner_mound(bm, params, sign_x, sign_y):
    """Mound at the base of a removed corner/bay; replaces scattered debris."""
    rng = random.Random(params.get('seed', 0) ^ 0x5EED)
    width, depth = params['width'], params['depth']
    centre_x = (0 if sign_x < 0 else width) - sign_x * width * .12
    centre_y = (0 if sign_y < 0 else depth) - sign_y * depth * .12
    radius_x = width * rng.uniform(.2, .34)
    radius_y = depth * rng.uniform(.2, .34)
    peak = rng.uniform(1.4, 3.0)
    _bm_mound(bm, centre_x, centre_y, radius_x, radius_y, peak, rng,
              segments=9, rings=3)


def create_rubble(name, params, collection):
    """Collapsed lot: overlapping low mounds of rubble on the pad."""
    rng = random.Random(params.get('seed', 0) ^ 0xC011A95E)
    width, depth = params['width'], params['depth']
    vertices, faces = [], []

    def mound(centre_x, centre_y, radius_x, radius_y, peak, segments=12, rings=3):
        jitter = [rng.uniform(.82, 1.18) for _ in range(segments)]
        angles = [2 * math.pi * index / segments for index in range(segments)]
        apex = len(vertices)
        vertices.append((centre_x + rng.uniform(-.15, .15),
                         centre_y + rng.uniform(-.15, .15), peak))
        ring_start = len(vertices)
        for ring in range(1, rings + 1):
            t = ring / rings
            height = peak * (1 - t) ** 1.35
            for index, angle in enumerate(angles):
                radius = t * jitter[index]
                vertices.append((centre_x + math.cos(angle) * radius_x * radius,
                                 centre_y + math.sin(angle) * radius_y * radius,
                                 max(0.0, height + rng.uniform(-.08, .08) * peak)))
        for index in range(segments):
            following = (index + 1) % segments
            faces.append((apex, ring_start + index, ring_start + following))
        for ring in range(1, rings):
            inner = ring_start + (ring - 1) * segments
            outer = inner + segments
            for index in range(segments):
                following = (index + 1) % segments
                faces.append((inner + index, outer + index,
                              outer + following, inner + following))

    radius_scale = rng.uniform(.38, .5)
    mound(rng.uniform(-.06, .06) * width, rng.uniform(-.06, .06) * depth,
          width * radius_scale, depth * radius_scale, rng.uniform(2.0, 3.4))
    mound(rng.uniform(-.2, .2) * width, rng.uniform(-.2, .2) * depth,
          width * radius_scale * rng.uniform(.45, .65),
          depth * radius_scale * rng.uniform(.45, .65), rng.uniform(.8, 1.6))
    if rng.random() < .6:
        mound(rng.uniform(-.24, .24) * width, rng.uniform(-.24, .24) * depth,
              width * radius_scale * rng.uniform(.3, .5),
              depth * radius_scale * rng.uniform(.3, .5), rng.uniform(.5, 1.1))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    add_material_slots(obj)
    for polygon in mesh.polygons:
        polygon.material_index = 7
    return obj


def add_gable_roof(bm, params, base):
    """Gable prism over the footprint; ridge runs along the frontage (X)."""
    width, depth = params['width'], params['depth']
    height = params.get('roof_height', 2.0)
    overhang = params.get('roof_overhang', .4)
    x0, x1 = -overhang, width + overhang
    y0, y1 = -overhang, depth + overhang
    ridge_y, ridge_z = depth / 2, base + height
    a = bm.verts.new((x0, y0, base))
    b = bm.verts.new((x1, y0, base))
    c = bm.verts.new((x1, y1, base))
    d = bm.verts.new((x0, y1, base))
    r0 = bm.verts.new((x0, ridge_y, ridge_z))
    r1 = bm.verts.new((x1, ridge_y, ridge_z))
    _face(bm, (a, b, r1, r0), 2)
    _face(bm, (c, d, r0, r1), 2)
    _face(bm, (a, r0, d), 2)
    _face(bm, (b, c, r1), 2)


def add_roof_box(bm, params, base):
    """Mechanical penthouse on a flat roof, sized as a fraction of the footprint."""
    width, depth = params['width'], params['depth']
    fraction_width, fraction_depth, height = params['roof_box']
    box_width, box_depth = width * fraction_width, depth * fraction_depth
    x0, x1 = (width - box_width) / 2, (width + box_width) / 2
    y0, y1 = (depth - box_depth) / 2, (depth + box_depth) / 2
    bottom = [bm.verts.new((x, y, base)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    top = [bm.verts.new((x, y, base + height)) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    _face(bm, tuple(top), 2)
    for index in range(4):
        following = (index + 1) % 4
        _face(bm, (bottom[index], bottom[following], top[following], top[index]), 0)


def create_shell(name, params, collection):
    # Legacy geometry uses global random. Isolate it from caller state.
    state = random.getstate()
    builder = BuildingShellBuilder(dict(params))
    mesh = None
    try:
        bm = builder.build()
        if params.get('chunk_cut'):
            add_corner_mound(bm, params, *subtract_chunks(bm, params))
        if params.get('expose_fill'):
            expose_fill_bay(bm, params)
        if params.get('interior_mound'):
            add_interior_mound(bm, params)
        # Roof extras only belong on an intact top; a damaged shell already has
        # an irregular silhouette where the upper floors were cut away.
        total_height = params['floors'] * params['floor_height']
        cut = builder.params.get('damage_min_height')
        if not params.get('chunk_cut') and (cut is None or cut >= total_height - 1e-6):
            if params.get('roof_kind') == 'GABLE':
                add_gable_roof(bm, params, total_height)
            if params.get('roof_box'):
                add_roof_box(bm, params, total_height + .2)
        for vert in bm.verts:
            vert.co.x -= params['width'] / 2
            vert.co.y -= params['depth'] / 2
        _repair_wall_shell(bm, params)
        _cap_vertical_wall_ends(bm, params)
        _cap_small_wall_loops(bm, params)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
        obj = bpy.data.objects.new(name, mesh)
        collection.objects.link(obj)
        add_material_slots(obj)
        return obj
    except Exception:
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
    finally:
        if builder.bm is not None and builder.bm.is_valid:
            builder.bm.free()
        random.setstate(state)
