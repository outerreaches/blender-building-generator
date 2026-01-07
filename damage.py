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
                            seed: int = None) -> dict:
    """
    Generate a damage height profile for the building perimeter.
    """
    if seed is not None:
        util.seed_random(seed)
    
    if damage_amount <= 0:
        return {
            'front': [(0, total_height), (width, total_height)],
            'back': [(0, total_height), (width, total_height)],
            'left': [(0, total_height), (depth, total_height)],
            'right': [(0, total_height), (depth, total_height)],
            'min_height': total_height,
            'intact_height': total_height,
        }
    
    profiles = {}
    min_height = total_height
    
    # Calculate the range of damage based on pointiness
    base_damage_depth = total_height * 0.85 * damage_amount
    variance_range = base_damage_depth * pointiness
    absolute_min = max(min_intact_height, total_height * 0.1)
    
    # Asymmetric damage - wall collapses
    wall_collapse = {
        'front': util.random_bool(damage_amount * 0.4),
        'back': util.random_bool(damage_amount * 0.4),
        'left': util.random_bool(damage_amount * 0.35),
        'right': util.random_bool(damage_amount * 0.35),
    }
    
    wall_collapse_intensity = {
        'front': util.random_float(1.3, 2.0) if wall_collapse['front'] else 1.0,
        'back': util.random_float(1.3, 2.0) if wall_collapse['back'] else 1.0,
        'left': util.random_float(1.3, 2.0) if wall_collapse['left'] else 1.0,
        'right': util.random_float(1.3, 2.0) if wall_collapse['right'] else 1.0,
    }
    
    # Corner collapses
    corner_collapse = [util.random_bool(damage_amount * 0.25) for _ in range(4)]
    corner_collapse_zones = []
    
    if corner_collapse[0]:  # Front-left
        corner_collapse_zones.append(('front', 0, width * 0.3, util.random_float(1.5, 2.5)))
        corner_collapse_zones.append(('left', 0, depth * 0.3, util.random_float(1.5, 2.5)))
    if corner_collapse[1]:  # Front-right
        corner_collapse_zones.append(('front', width * 0.7, width, util.random_float(1.5, 2.5)))
        corner_collapse_zones.append(('right', 0, depth * 0.3, util.random_float(1.5, 2.5)))
    if corner_collapse[2]:  # Back-left
        corner_collapse_zones.append(('back', width * 0.7, width, util.random_float(1.5, 2.5)))
        corner_collapse_zones.append(('left', depth * 0.7, depth, util.random_float(1.5, 2.5)))
    if corner_collapse[3]:  # Back-right
        corner_collapse_zones.append(('back', 0, width * 0.3, util.random_float(1.5, 2.5)))
        corner_collapse_zones.append(('right', depth * 0.7, depth, util.random_float(1.5, 2.5)))
    
    # Generate profile for each wall
    for wall_name, wall_length in [('front', width), ('back', width), 
                                    ('left', depth), ('right', depth)]:
        profile = []
        base_points = max(3, int(wall_length / 0.8))
        num_points = max(3, int(base_points * resolution))
        wall_multiplier = wall_collapse_intensity[wall_name]
        random_offsets = [util.random_float(0, 1) for _ in range(num_points + 1)]
        
        for i in range(num_points + 1):
            pos = (i / num_points) * wall_length
            
            collapse_multiplier = 1.0
            for zone_wall, zone_start, zone_end, zone_intensity in corner_collapse_zones:
                if zone_wall == wall_name and zone_start <= pos <= zone_end:
                    zone_center = (zone_start + zone_end) / 2
                    zone_dist = abs(pos - zone_center) / ((zone_end - zone_start) / 2 + 0.01)
                    zone_factor = 1.0 - zone_dist * 0.5
                    collapse_multiplier = max(collapse_multiplier, 1.0 + (zone_intensity - 1.0) * zone_factor)
            
            base_loss = base_damage_depth * wall_multiplier * collapse_multiplier
            variance_offset = (random_offsets[i] - 0.5) * variance_range * wall_multiplier
            
            height_loss = max(0, base_loss + variance_offset)
            height = max(absolute_min, min(total_height, total_height - height_loss))
            
            profile.append((pos, height))
            min_height = min(min_height, height)
        
        profiles[wall_name] = profile
    
    min_height = max(min_height, min_intact_height)
    profiles['min_height'] = min_height
    profiles['intact_height'] = min_intact_height
    
    return profiles


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
    """
    Build the damaged top portion of a wall with an irregular top edge.
    Creates smooth continuous geometry following the damage profile.
    
    Faces are created with consistent winding - normals will be fixed
    by the post-processing step in mesh_builder.
    """
    if not profile or len(profile) < 2:
        return
    
    # Filter profile to only include points above base_z
    valid_profile = []
    for pos, height in profile:
        if height > base_z + 0.05:
            valid_profile.append((pos, height))
    
    if len(valid_profile) < 2:
        return
    
    inner_offset = -normal * thickness
    
    # Build vertices for outer and inner faces
    outer_bottom_verts = []
    outer_top_verts = []
    inner_bottom_verts = []
    inner_top_verts = []
    
    for pos, height in valid_profile:
        top_z = max(height, base_z + 0.05)
        
        outer_pos = start_pos + direction * pos
        outer_bottom = outer_pos + Vector((0, 0, base_z))
        outer_top = outer_pos + Vector((0, 0, top_z))
        
        inner_pos = outer_pos + inner_offset
        inner_bottom = inner_pos + Vector((0, 0, base_z))
        inner_top = inner_pos + Vector((0, 0, top_z))
        
        outer_bottom_verts.append(bm.verts.new(outer_bottom))
        outer_top_verts.append(bm.verts.new(outer_top))
        inner_bottom_verts.append(bm.verts.new(inner_bottom))
        inner_top_verts.append(bm.verts.new(inner_top))
    
    # Create faces between adjacent vertices
    for i in range(len(valid_profile) - 1):
        # Outer face - should point in 'normal' direction (outward)
        try:
            v0 = outer_bottom_verts[i]
            v1 = outer_bottom_verts[i+1]
            v2 = outer_top_verts[i+1]
            v3 = outer_top_verts[i]
            
            edge1 = v1.co - v0.co
            edge2 = v3.co - v0.co
            cross = edge1.cross(edge2)
            
            # Outer face should point in 'normal' direction
            if cross.dot(normal) >= 0:
                f = bm.faces.new([v0, v1, v2, v3])
            else:
                f = bm.faces.new([v0, v3, v2, v1])
            f.material_index = mat_index
        except: pass
        
        # Inner face - should point in '-normal' direction (inward)
        try:
            v0 = inner_bottom_verts[i]
            v1 = inner_bottom_verts[i+1]
            v2 = inner_top_verts[i+1]
            v3 = inner_top_verts[i]
            
            edge1 = v1.co - v0.co
            edge2 = v3.co - v0.co
            cross = edge1.cross(edge2)
            
            # Inner face should point opposite to 'normal' (into building)
            if cross.dot(normal) <= 0:
                f = bm.faces.new([v0, v1, v2, v3])
            else:
                f = bm.faces.new([v0, v3, v2, v1])
            f.material_index = mat_index
        except: pass
        
        # Top face - should point up (+Z)
        try:
            v0 = outer_top_verts[i]
            v1 = outer_top_verts[i+1]
            v2 = inner_top_verts[i+1]
            v3 = inner_top_verts[i]
            
            edge1 = v1.co - v0.co
            edge2 = v3.co - v0.co
            cross = edge1.cross(edge2)
            
            # Top face should point up (+Z)
            if cross.z >= 0:
                f = bm.faces.new([v0, v1, v2, v3])
            else:
                f = bm.faces.new([v0, v3, v2, v1])
            f.material_index = mat_index
        except: pass
    
    # End caps
    if len(outer_bottom_verts) >= 1:
        # Left end cap - should point in -direction
        try:
            v0 = inner_bottom_verts[0]
            v1 = outer_bottom_verts[0]
            v2 = outer_top_verts[0]
            v3 = inner_top_verts[0]
            
            edge1 = v1.co - v0.co
            edge2 = v3.co - v0.co
            cross = edge1.cross(edge2)
            
            # Left end should point opposite to direction
            if cross.dot(direction) <= 0:
                f = bm.faces.new([v0, v1, v2, v3])
            else:
                f = bm.faces.new([v0, v3, v2, v1])
            f.material_index = mat_index
        except: pass
        
        # Right end cap - should point in +direction
        try:
            v0 = outer_bottom_verts[-1]
            v1 = inner_bottom_verts[-1]
            v2 = inner_top_verts[-1]
            v3 = outer_top_verts[-1]
            
            edge1 = v1.co - v0.co
            edge2 = v3.co - v0.co
            cross = edge1.cross(edge2)
            
            # Right end should point in direction
            if cross.dot(direction) >= 0:
                f = bm.faces.new([v0, v1, v2, v3])
            else:
                f = bm.faces.new([v0, v3, v2, v1])
            f.material_index = mat_index
        except: pass
