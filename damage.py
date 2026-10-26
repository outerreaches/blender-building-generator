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
                            seed: int = None, max_height: float = None) -> dict:
    """Flat wall plateaus with wide notches: large polygonal chunks missing.

    Each wall keeps a remaining top level and loses one or two contiguous runs
    of chunks down to the damage line. Corner heights are the lower of the two
    adjoining walls, so neighbouring strips meet without thin fins. Chunks are
    at least ~4.5 m wide; the old per-0.8 m heights produced saw-tooth tops.
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

    loss = total_height * 0.85 * damage_amount
    low = max(min_intact_height, total_height - loss)
    span = max(0.0, total_height - low)
    if max_height is not None:
        low = min(low, max_height)

    wall_specs = {
        'front': (width, 'FL', 'FR'),
        'right': (depth, 'FR', 'BR'),
        'back': (width, 'BR', 'BL'),
        'left': (depth, 'BL', 'FL'),
    }
    generated = {}
    for name, (length, start_corner, end_corner) in wall_specs.items():
        chunk_width = max(4.5, 4.5 / max(resolution, .2))
        segments = max(2, min(5, int(round(length / chunk_width))))
        top_level = low + span * util.random_float(.45, .8)
        if max_height is not None:
            top_level = min(top_level, max_height)
        levels = [top_level] * segments
        for _ in range(util.random_int(1, 2)):
            start = util.random_int(0, max(0, segments - 2))
            run = util.random_int(2, max(2, segments - 1))
            for index in range(start, min(segments, start + run)):
                levels[index] = low
        generated[name] = [length, segments, levels, start_corner, end_corner]

    # Shared corners use the lower adjoining level; steps below make that a
    # clean notch rather than a ramp.
    corner_level = {}
    for length, segments, levels, start_corner, end_corner in generated.values():
        for corner, level in ((start_corner, levels[0]), (end_corner, levels[-1])):
            corner_level[corner] = min(corner_level.get(corner, level), level)
    for length, segments, levels, start_corner, end_corner in generated.values():
        levels[0] = corner_level[start_corner]
        levels[-1] = corner_level[end_corner]

    profiles = {}
    for name, (length, segments, levels, start_corner, end_corner) in generated.items():
        positions = [0.0]
        heights = [levels[0]]
        for index in range(segments):
            boundary = (index + 1) * length / segments
            if index + 1 < segments and levels[index + 1] != levels[index]:
                positions.extend((boundary - 0.7, boundary + 0.7))
                heights.extend((levels[index], levels[index + 1]))
            else:
                positions.append(boundary)
                heights.append(levels[index])
        profiles[name] = list(zip(positions, heights))

    profiles['min_height'] = low
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
