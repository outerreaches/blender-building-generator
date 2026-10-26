# SPDX-License-Identifier: GPL-3.0-or-later
# Damage system for Procedural Building Shell Generator
# Creates realistic top-down weathering with irregular top edges

import bmesh
from mathutils import Vector
import math
from . import util


def generate_damage_profile(width: float, depth: float, total_height: float,
                            damage_amount: float, min_intact_height: float = 0,
                            pointiness: float = 0.5, resolution: float = 1.0,
                            seed: int = None, max_height: float = None,
                            floor_height: float = None) -> dict:
    """Fine irregular wall tops, median-smoothed and slope-clamped.

    The original high-frequency profile gives the facade detail that reads on
    tall buildings. Isolated needles are removed with a 3-tap median filter and
    a per-sample step limit; adjoining walls share their corner heights so the
    strips meet without slivers. ``max_height`` caps the remaining wall top.
    """
    if seed is not None:
        util.seed_random(seed)

    walls = (('front', width), ('back', width), ('left', depth), ('right', depth))
    if damage_amount <= 0 or total_height <= 0:
        profiles = {name: [(0, total_height), (length, total_height)]
                    for name, length in walls}
        profiles['min_height'] = total_height
        profiles['intact_height'] = min_intact_height
        return profiles

    # Keep most of the tower standing; whole-chunk cuts do the heavy damage.
    base_loss = total_height * 0.55 * damage_amount
    variance = base_loss * pointiness * 1.5
    absolute_min = max(min_intact_height, total_height * 0.1)
    low = max(min_intact_height, total_height - base_loss)
    if max_height is not None:
        low = min(low, max_height)
    collapsed = {name: util.random_bool(damage_amount * 0.4) for name, _ in walls}
    intensity = {name: (util.random_float(1.0, 1.25) if collapsed[name] else 1.0)
                 for name, _ in walls}

    raw = {}
    for name, length in walls:
        samples = max(3, int(round(length / 1.2 * max(resolution, 0.25))))
        offsets = [util.random_float(0, 1) for _ in range(samples + 1)]
        heights = []
        for offset in offsets:
            loss = base_loss * intensity[name] + (offset - 0.5) * variance * intensity[name]
            height = max(absolute_min, min(total_height, total_height - max(0.0, loss)))
            heights.append(height)
        if len(heights) >= 3:
            median = heights[:]
            for index in range(1, len(heights) - 1):
                median[index] = sorted(heights[index - 1:index + 2])[1]
            heights = median
        if len(heights) >= 3:
            averaged = heights[:]
            for index in range(1, len(heights) - 1):
                averaged[index] = (0.25 * heights[index - 1] +
                                   0.5 * heights[index] +
                                   0.25 * heights[index + 1])
            heights = averaged
        # No isolated peak: a point may not rise more than one step above both
        # neighbours. Broad variation survives; needles do not.
        max_step = max(1.5, total_height * 0.06)
        for index in range(1, len(heights) - 1):
            heights[index] = min(heights[index],
                                 max(heights[index - 1], heights[index + 1]) + max_step)
        heights = [min(total_height, max(absolute_min, height)) for height in heights]
        raw[name] = heights

    # Shared corners: average the adjoining ends so neither wall keeps a fin.
    corner_pairs = {
        'FL': (('front', 0), ('left', 0)),
        'FR': (('front', -1), ('right', 0)),
        'BR': (('right', -1), ('back', 0)),
        'BL': (('back', -1), ('left', -1)),
    }
    for corner, ((wall_a, index_a), (wall_b, index_b)) in corner_pairs.items():
        shared = (raw[wall_a][index_a] + raw[wall_b][index_b]) / 2
        neighbour_a = raw[wall_a][index_a + 1 if index_a == 0 else index_a - 1]
        neighbour_b = raw[wall_b][index_b + 1 if index_b == 0 else index_b - 1]
        shared = min(shared, neighbour_a + max_step, neighbour_b + max_step)
        raw[wall_a][index_a] = shared
        raw[wall_b][index_b] = shared

    # Keep the broken top to a one-floor ragged parapet above the break line.
    # The intact floors below keep their windows; deeper missing walls come from
    # the whole-chunk cuts, not from tall blank fins.
    break_base = None
    if floor_height:
        break_floor = max(1, int(low / floor_height))
        break_base = break_floor * floor_height
        ceiling = break_base + floor_height
        if max_height is not None:
            ceiling = min(ceiling, max_height)
        if ceiling <= break_base:
            ceiling = break_base + .05

    profiles = {}
    minimum = total_height
    for name, length in walls:
        heights = raw[name]
        if break_base is not None:
            heights = [min(max(height, break_base + .05), ceiling)
                       for height in heights]
        elif max_height is not None:
            heights = [min(height, max_height) for height in heights]
        if min_intact_height:
            heights = [max(height, min_intact_height) for height in heights]
        positions = [index * length / (len(heights) - 1)
                     for index in range(len(heights))]
        profiles[name] = list(zip(positions, heights))
        minimum = min(minimum, min(heights))
    if break_base is not None:
        profiles['min_height'] = max(min_intact_height, break_base)
    else:
        profiles['min_height'] = max(min_intact_height,
                                     min(minimum, max_height or total_height))
    profiles['intact_height'] = min_intact_height
    return profiles


def _face_oriented(bm, vertices, direction, material):
    """Create a face whose normal points along ``direction`` (if possible)."""
    if len(vertices) < 3:
        return
    edge_a = vertices[1].co - vertices[0].co
    edge_b = vertices[2].co - vertices[0].co
    normal = edge_a.cross(edge_b)
    if normal.dot(direction) < 0:
        vertices = list(reversed(vertices))
    try:
        face = bm.faces.new(vertices)
        face.material_index = material
    except ValueError:
        pass


def get_height_at_position(profile: list, position: float) -> float:
    """Interpolate the height at a given position along the wall."""
    if not profile:
        return 0
    
    if position <= profile[0][0]:
        return profile[0][1]
    if position >= profile[-1][0]:
        return profile[-1][1]
    
    for i in range(len(profile) - 1):
        pos1, h1 = profile[i]
        pos2, h2 = profile[i + 1]
        
        if pos1 <= position <= pos2:
            if abs(pos2 - pos1) < 0.001:
                return h1
            t = (position - pos1) / (pos2 - pos1)
            return h1 + t * (h2 - h1)
    
    return profile[-1][1]


def get_intact_floor_count(min_height: float, floor_height: float) -> int:
    """Calculate how many complete floors are below the damage line."""
    if floor_height <= 0:
        return 0
    return int(min_height / floor_height)


def build_damaged_top_section(bm: bmesh.types.BMesh, profile: list,
                               start_pos: Vector, direction: Vector, normal: Vector,
                               base_z: float, thickness: float, mat_index: int = 0):
    """Wall strip between the intact floors and a coarse collapsed top edge.

    Every face is oriented explicitly: outer faces along ``normal``, inner faces
    against it, top strips up and end caps along ``direction``. Quads that can be
    non-planar (tops and caps) are split into triangles, so Blender cannot pick
    an arbitrary winding for them.
    """
    valid_profile = [(pos, height) for pos, height in profile
                     if height > base_z + 0.05]
    if len(valid_profile) < 2:
        return
    inner_offset = -normal * thickness
    outer_bottom, outer_top, inner_bottom, inner_top = [], [], [], []
    for pos, height in valid_profile:
        top_z = max(height, base_z + 0.05)
        outer_pos = start_pos + direction * pos
        inner_pos = outer_pos + inner_offset
        outer_bottom.append(bm.verts.new(outer_pos + Vector((0, 0, base_z))))
        outer_top.append(bm.verts.new(outer_pos + Vector((0, 0, top_z))))
        inner_bottom.append(bm.verts.new(inner_pos + Vector((0, 0, base_z))))
        inner_top.append(bm.verts.new(inner_pos + Vector((0, 0, top_z))))

    up = Vector((0, 0, 1))
    for i in range(len(valid_profile) - 1):
        _face_oriented(bm, [outer_bottom[i], outer_bottom[i + 1], outer_top[i + 1]],
                       normal, mat_index)
        _face_oriented(bm, [outer_bottom[i], outer_top[i + 1], outer_top[i]],
                       normal, mat_index)
        _face_oriented(bm, [inner_bottom[i], inner_bottom[i + 1], inner_top[i + 1]],
                       -normal, mat_index)
        _face_oriented(bm, [inner_bottom[i], inner_top[i + 1], inner_top[i]],
                       -normal, mat_index)
        _face_oriented(bm, [outer_top[i], outer_top[i + 1], inner_top[i + 1]],
                       up, mat_index)
        _face_oriented(bm, [outer_top[i], inner_top[i + 1], inner_top[i]],
                       up, mat_index)

    _face_oriented(bm, [inner_bottom[0], outer_bottom[0], outer_top[0]],
                   -direction, mat_index)
    _face_oriented(bm, [inner_bottom[0], outer_top[0], inner_top[0]],
                   -direction, mat_index)
    _face_oriented(bm, [outer_bottom[-1], inner_bottom[-1], inner_top[-1]],
                   direction, mat_index)
    _face_oriented(bm, [outer_bottom[-1], inner_top[-1], outer_top[-1]],
                   direction, mat_index)
