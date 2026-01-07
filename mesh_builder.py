# SPDX-License-Identifier: GPL-3.0-or-later
# Mesh building functions for Procedural Building Shell Generator

import bmesh
from mathutils import Vector
from . import util
from . import interiors
from . import damage as damage_module


# Material slot indices
MAT_WALLS = 0
MAT_FLOOR = 1
MAT_ROOF = 2
MAT_WINDOW_FRAME = 3
MAT_DOOR_FRAME = 4


def generate_uvs(bm: bmesh.types.BMesh):
    """
    Generate UV coordinates for all faces using box projection.
    
    This creates basic UV coordinates that can be refined later.
    Uses world-space projection based on face normal direction.
    """
    # Ensure UV layer exists
    uv_layer = bm.loops.layers.uv.verify()
    
    for face in bm.faces:
        # Determine projection axis based on face normal
        normal = face.normal
        abs_normal = (abs(normal.x), abs(normal.y), abs(normal.z))
        
        # Choose projection plane based on dominant normal axis
        if abs_normal[2] >= abs_normal[0] and abs_normal[2] >= abs_normal[1]:
            # Face mostly points up/down - project onto XY plane
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x, co.y)
        elif abs_normal[0] >= abs_normal[1]:
            # Face mostly points left/right - project onto YZ plane
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.y, co.z)
        else:
            # Face mostly points front/back - project onto XZ plane
            for loop in face.loops:
                co = loop.vert.co
                loop[uv_layer].uv = (co.x, co.z)


def mark_seams_for_uvs(bm: bmesh.types.BMesh):
    """
    Mark UV seams on the mesh for proper unwrapping.
    
    Marks seams on:
    - Vertical edges at building corners
    - Edges around window/door openings (material boundaries)
    - Edges between different materials
    - Edges on damaged wall tops (irregular geometry)
    - All boundary edges
    """
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    
    for edge in bm.edges:
        should_mark = False
        
        # Mark edges between faces with different materials
        if len(edge.link_faces) == 2:
            f1, f2 = edge.link_faces
            if f1.material_index != f2.material_index:
                should_mark = True
        
        # Mark boundary edges (edges with only 1 face) - important for damage
        if len(edge.link_faces) == 1:
            should_mark = True
        
        # Mark edges with no faces (isolated edges that shouldn't exist but mark anyway)
        if len(edge.link_faces) == 0:
            should_mark = True
        
        # Mark vertical edges at corners (edges where face normals differ significantly)
        if len(edge.link_faces) == 2:
            f1, f2 = edge.link_faces
            v1, v2 = edge.verts
            
            # Check if edge is vertical
            is_vertical = (abs(v1.co.x - v2.co.x) < 0.01 and 
                          abs(v1.co.y - v2.co.y) < 0.01 and
                          abs(v1.co.z - v2.co.z) > 0.1)
            
            if is_vertical:
                # Check if normals are perpendicular (corner edge)
                dot = abs(f1.normal.dot(f2.normal))
                if dot < 0.1:  # Normals are roughly perpendicular
                    should_mark = True
            
            # Mark edges where wall meets top cap (one face vertical, one horizontal)
            f1_vertical = abs(f1.normal.z) < 0.5
            f2_vertical = abs(f2.normal.z) < 0.5
            if f1_vertical != f2_vertical:  # One vertical, one horizontal
                should_mark = True
        
        # Mark horizontal edges at floor boundaries
        if len(edge.link_faces) >= 2:
            v1, v2 = edge.verts
            is_horizontal = abs(v1.co.z - v2.co.z) < 0.01
            if is_horizontal:
                # Check if this is at a floor height transition
                for face in edge.link_faces:
                    # Floor/ceiling faces have vertical normals
                    if abs(face.normal.z) > 0.9:
                        should_mark = True
                        break
        
        # Mark edges on irregular damage top surfaces
        # These are edges where connected faces have different Z heights at their centers
        if len(edge.link_faces) == 2:
            f1, f2 = edge.link_faces
            # Check if both faces are top caps (facing up)
            if abs(f1.normal.z) > 0.5 and abs(f2.normal.z) > 0.5:
                # Check if face centers are at different heights (stepped damage)
                c1 = f1.calc_center_median()
                c2 = f2.calc_center_median()
                if abs(c1.z - c2.z) > 0.1:
                    should_mark = True
        
        if should_mark:
            edge.seam = True


class WallSegment:
    """Represents a wall segment with potential openings."""
    
    def __init__(self, start: Vector, end: Vector, height: float, base_z: float = 0.0,
                 normal: Vector = None):
        self.start = start.copy()
        self.end = end.copy()
        self.height = height
        self.base_z = base_z
        self.openings = []  # List of opening dicts
        
        # Calculate direction and normal
        self.direction = (self.end - self.start).normalized()
        if normal is not None:
            self.normal = normal.copy()
        else:
            # Default normal perpendicular to wall direction (pointing outward)
            self.normal = Vector((-self.direction.y, self.direction.x, 0))
    
    def add_opening(self, x_start: float, x_end: float, z_start: float, z_end: float, 
                    opening_type: str = 'window'):
        """Add an opening (window or door) to this wall segment."""
        self.openings.append({
            'x_start': x_start,
            'x_end': x_end,
            'z_start': z_start,
            'z_end': z_end,
            'type': opening_type
        })
    
    @property
    def length(self) -> float:
        return (self.end - self.start).length


def build_wall_with_openings(bm: bmesh.types.BMesh, segment: WallSegment, 
                              thickness: float, add_top_cap: bool = False) -> list:
    """
    Build a wall segment with thickness and openings cut out.
    
    Creates outer face, inner face, top/bottom caps, and opening frames.
    
    Args:
        bm: BMesh to add geometry to
        segment: WallSegment defining the wall
        thickness: Wall thickness
        add_top_cap: Whether to add a cap on top of the wall
    
    Returns:
        List of created faces
    """
    faces = []
    wall_length = segment.length
    wall_height = segment.height
    direction = segment.direction
    normal = segment.normal
    base_z = segment.base_z
    
    # Offset for inner wall (inward from normal)
    inner_offset = -normal * thickness
    
    # Sort openings by x position
    openings = sorted(segment.openings, key=lambda o: o['x_start'])
    
    if not openings:
        # No openings - create a solid wall box
        faces.extend(_create_solid_wall_segment(
            bm, segment.start, segment.end, wall_height, base_z, 
            thickness, normal, direction, add_top_cap
        ))
    else:
        # Create wall with openings
        faces.extend(_create_wall_with_openings_thick(
            bm, segment, openings, thickness, add_top_cap
        ))
    
    return faces


def _create_solid_wall_segment(bm: bmesh.types.BMesh, start: Vector, end: Vector,
                                height: float, base_z: float, thickness: float,
                                normal: Vector, direction: Vector,
                                add_top_cap: bool = False) -> list:
    """Create a solid wall segment (no openings) with thickness."""
    faces = []
    
    inner_offset = -normal * thickness
    
    # 8 corners of the wall box
    # Outer face corners
    o_bl = start + Vector((0, 0, base_z))  # outer bottom-left
    o_br = end + Vector((0, 0, base_z))    # outer bottom-right
    o_tl = start + Vector((0, 0, base_z + height))
    o_tr = end + Vector((0, 0, base_z + height))
    
    # Inner face corners
    i_bl = o_bl + inner_offset
    i_br = o_br + inner_offset
    i_tl = o_tl + inner_offset
    i_tr = o_tr + inner_offset
    
    verts = [
        bm.verts.new(o_bl),  # 0
        bm.verts.new(o_br),  # 1
        bm.verts.new(o_tr),  # 2
        bm.verts.new(o_tl),  # 3
        bm.verts.new(i_bl),  # 4
        bm.verts.new(i_br),  # 5
        bm.verts.new(i_tr),  # 6
        bm.verts.new(i_tl),  # 7
    ]
    
    # Create all faces with consistent winding
    # Outer face - should point in normal direction
    f = bm.faces.new([verts[0], verts[1], verts[2], verts[3]])
    f.material_index = MAT_WALLS
    # Check if face normal aligns with expected normal, flip if not
    if f.normal.dot(normal) < 0:
        f.normal_flip()
    faces.append(f)
    
    # Inner face - should point opposite to normal direction
    f = bm.faces.new([verts[5], verts[4], verts[7], verts[6]])
    f.material_index = MAT_WALLS
    # Inner face should point opposite to outer normal
    if f.normal.dot(normal) > 0:
        f.normal_flip()
    faces.append(f)
    
    # Top cap - ensure it faces upward
    if add_top_cap:
        f = bm.faces.new([verts[3], verts[2], verts[6], verts[7]])
        f.material_index = MAT_WALLS
        # Check actual normal and flip if pointing down
        if f.normal.z < 0:
            f.normal_flip()
        faces.append(f)
    
    # Bottom face - should face downward
    f = bm.faces.new([verts[4], verts[5], verts[1], verts[0]])
    f.material_index = MAT_WALLS
    if f.normal.z > 0:
        f.normal_flip()
    faces.append(f)
    
    # Left end cap - should face in negative direction along wall
    f = bm.faces.new([verts[4], verts[0], verts[3], verts[7]])
    f.material_index = MAT_WALLS
    # Check if face normal points away from wall (opposite to direction)
    if f.normal.dot(direction) > 0:
        f.normal_flip()
    faces.append(f)
    
    # Right end cap - should face in positive direction along wall
    f = bm.faces.new([verts[1], verts[5], verts[6], verts[2]])
    f.material_index = MAT_WALLS
    # Check if face normal points in direction
    if f.normal.dot(direction) < 0:
        f.normal_flip()
    faces.append(f)
    
    return faces


def _create_wall_with_openings_thick(bm: bmesh.types.BMesh, segment: WallSegment,
                                      openings: list, thickness: float,
                                      add_top_cap: bool = False) -> list:
    """
    Create a wall with rectangular openings, with proper thickness.
    
    Uses a grid-based approach to create wall sections around openings,
    then adds frame faces for the opening sides.
    """
    faces = []
    wall_length = segment.length
    wall_height = segment.height
    direction = segment.direction
    normal = segment.normal
    base_z = segment.base_z
    start = segment.start
    
    inner_offset = -normal * thickness
    
    # Collect X coordinates for grid (only where openings exist)
    x_coords = [0.0, wall_length]
    z_coords = [0.0, wall_height]
    
    for op in openings:
        x_coords.extend([op['x_start'], op['x_end']])
        z_coords.extend([op['z_start'], op['z_end']])
    
    # Remove duplicates, clamp, and sort
    x_coords = sorted(set(max(0, min(wall_length, x)) for x in x_coords))
    z_coords = sorted(set(max(0, min(wall_height, z)) for z in z_coords))
    
    # Create grid of cells
    for i in range(len(x_coords) - 1):
        for j in range(len(z_coords) - 1):
            x0, x1 = x_coords[i], x_coords[i + 1]
            z0, z1 = z_coords[j], z_coords[j + 1]
            
            # Skip zero-size cells
            if abs(x1 - x0) < 0.001 or abs(z1 - z0) < 0.001:
                continue
            
            # Check if this cell is inside any opening
            cell_center_x = (x0 + x1) / 2
            cell_center_z = (z0 + z1) / 2
            
            is_opening = False
            for op in openings:
                if (op['x_start'] <= cell_center_x <= op['x_end'] and
                    op['z_start'] <= cell_center_z <= op['z_end']):
                    is_opening = True
                    break
            
            if not is_opening:
                # Create a solid wall section for this cell
                cell_start = start + direction * x0
                cell_end = start + direction * x1
                
                # Only add top cap to topmost cells
                is_top_cell = (z1 >= wall_height - 0.001)
                
                faces.extend(_create_wall_cell(
                    bm, cell_start, cell_end, z0, z1, base_z,
                    thickness, normal, direction,
                    add_top_cap=(add_top_cap and is_top_cell)
                ))
    
    # Create opening frames (the sides of the openings that show wall thickness)
    for op in openings:
        faces.extend(_create_opening_frame(
            bm, segment, op, thickness
        ))
    
    # Add end caps at both ends of the wall (left and right extremities)
    # These close off the wall thickness at the ends
    
    # Left end cap (at x = 0)
    left_outer_bottom = start + Vector((0, 0, base_z))
    left_outer_top = start + Vector((0, 0, base_z + wall_height))
    left_inner_bottom = left_outer_bottom + inner_offset
    left_inner_top = left_outer_top + inner_offset
    
    v_lob = bm.verts.new(left_outer_bottom)
    v_lot = bm.verts.new(left_outer_top)
    v_lib = bm.verts.new(left_inner_bottom)
    v_lit = bm.verts.new(left_inner_top)
    
    f = bm.faces.new([v_lib, v_lob, v_lot, v_lit])
    f.material_index = MAT_WALLS
    faces.append(f)
    
    # Right end cap (at x = wall_length)
    right_outer_bottom = start + direction * wall_length + Vector((0, 0, base_z))
    right_outer_top = start + direction * wall_length + Vector((0, 0, base_z + wall_height))
    right_inner_bottom = right_outer_bottom + inner_offset
    right_inner_top = right_outer_top + inner_offset
    
    v_rob = bm.verts.new(right_outer_bottom)
    v_rot = bm.verts.new(right_outer_top)
    v_rib = bm.verts.new(right_inner_bottom)
    v_rit = bm.verts.new(right_inner_top)
    
    f = bm.faces.new([v_rob, v_rib, v_rit, v_rot])
    f.material_index = MAT_WALLS
    faces.append(f)
    
    return faces


def _create_wall_cell(bm: bmesh.types.BMesh, start: Vector, end: Vector,
                       z0: float, z1: float, base_z: float, thickness: float,
                       normal: Vector, direction: Vector,
                       add_top_cap: bool = False) -> list:
    """Create a single wall cell (part of the grid) with thickness."""
    faces = []
    
    inner_offset = -normal * thickness
    
    # Outer face corners
    o_bl = start + Vector((0, 0, base_z + z0))
    o_br = end + Vector((0, 0, base_z + z0))
    o_tl = start + Vector((0, 0, base_z + z1))
    o_tr = end + Vector((0, 0, base_z + z1))
    
    # Inner face corners
    i_bl = o_bl + inner_offset
    i_br = o_br + inner_offset
    i_tl = o_tl + inner_offset
    i_tr = o_tr + inner_offset
    
    verts = [
        bm.verts.new(o_bl),  # 0
        bm.verts.new(o_br),  # 1
        bm.verts.new(o_tr),  # 2
        bm.verts.new(o_tl),  # 3
        bm.verts.new(i_bl),  # 4
        bm.verts.new(i_br),  # 5
        bm.verts.new(i_tr),  # 6
        bm.verts.new(i_tl),  # 7
    ]
    
    # Outer face - should point in normal direction
    f = bm.faces.new([verts[0], verts[1], verts[2], verts[3]])
    f.material_index = MAT_WALLS
    if f.normal.dot(normal) < 0:
        f.normal_flip()
    faces.append(f)
    
    # Inner face - should point opposite to normal direction
    f = bm.faces.new([verts[5], verts[4], verts[7], verts[6]])
    f.material_index = MAT_WALLS
    if f.normal.dot(normal) > 0:
        f.normal_flip()
    faces.append(f)
    
    # Top cap if requested - ensure it faces upward
    if add_top_cap:
        f = bm.faces.new([verts[3], verts[2], verts[6], verts[7]])
        f.material_index = MAT_WALLS
        # Check actual normal and flip if pointing down
        if f.normal.z < 0:
            f.normal_flip()
        faces.append(f)
    
    # Bottom face (for ground level cells) - should face downward
    if z0 < 0.001:  # At ground level
        f = bm.faces.new([verts[4], verts[5], verts[1], verts[0]])
        f.material_index = MAT_WALLS
        if f.normal.z > 0:
            f.normal_flip()
        faces.append(f)
    
    return faces


def _create_opening_frame(bm: bmesh.types.BMesh, segment: WallSegment,
                           opening: dict, thickness: float) -> list:
    """
    Create the frame faces around an opening (the sides that show wall thickness).
    
    Creates 4 faces: top, bottom, left, right of the opening.
    """
    faces = []
    
    direction = segment.direction
    normal = segment.normal
    base_z = segment.base_z
    start = segment.start
    inner_offset = -normal * thickness
    
    x0, x1 = opening['x_start'], opening['x_end']
    z0, z1 = opening['z_start'], opening['z_end']
    opening_type = opening['type']
    
    mat_idx = MAT_DOOR_FRAME if opening_type == 'door' else MAT_WINDOW_FRAME
    
    # Calculate corner positions
    # Outer corners
    o_bl = start + direction * x0 + Vector((0, 0, base_z + z0))
    o_br = start + direction * x1 + Vector((0, 0, base_z + z0))
    o_tl = start + direction * x0 + Vector((0, 0, base_z + z1))
    o_tr = start + direction * x1 + Vector((0, 0, base_z + z1))
    
    # Inner corners
    i_bl = o_bl + inner_offset
    i_br = o_br + inner_offset
    i_tl = o_tl + inner_offset
    i_tr = o_tr + inner_offset
    
    # Bottom frame (only if not at ground level, or for windows)
    # Should face downward (into the opening)
    if z0 > 0.01:
        verts = [
            bm.verts.new(o_bl),
            bm.verts.new(o_br),
            bm.verts.new(i_br),
            bm.verts.new(i_bl),
        ]
        f = bm.faces.new(verts)
        f.material_index = mat_idx
        if f.normal.z > 0:
            f.normal_flip()
        faces.append(f)
    
    # Top frame - should face upward (into the opening)
    verts = [
        bm.verts.new(o_tr),
        bm.verts.new(o_tl),
        bm.verts.new(i_tl),
        bm.verts.new(i_tr),
    ]
    f = bm.faces.new(verts)
    f.material_index = mat_idx
    if f.normal.z < 0:
        f.normal_flip()
    faces.append(f)
    
    # Left frame - should face in negative direction (left into opening)
    verts = [
        bm.verts.new(o_tl),
        bm.verts.new(o_bl),
        bm.verts.new(i_bl),
        bm.verts.new(i_tl),
    ]
    f = bm.faces.new(verts)
    f.material_index = mat_idx
    if f.normal.dot(direction) > 0:
        f.normal_flip()
    faces.append(f)
    
    # Right frame - should face in positive direction (right into opening)
    verts = [
        bm.verts.new(o_br),
        bm.verts.new(o_tr),
        bm.verts.new(i_tr),
        bm.verts.new(i_br),
    ]
    f = bm.faces.new(verts)
    f.material_index = mat_idx
    if f.normal.dot(direction) < 0:
        f.normal_flip()
    faces.append(f)
    
    return faces


def build_floor_slab(bm: bmesh.types.BMesh, width: float, depth: float, 
                     z_height: float, thickness: float = 0.15,
                     wall_thickness: float = 0.25,
                     opening: dict = None) -> list:
    """
    Build a floor slab with optional opening for stairs.
    
    Args:
        bm: BMesh to add geometry to
        width: Building width (X)
        depth: Building depth (Y)
        z_height: Height of the floor slab bottom
        thickness: Slab thickness
        wall_thickness: Wall thickness (to inset slab properly)
        opening: Optional dict with 'x_min', 'y_min', 'x_max', 'y_max' for stair opening
    
    Returns:
        List of created faces
    """
    faces = []
    
    # Slab is inset to sit within the interior walls (not through them)
    slab_x_min = wall_thickness
    slab_y_min = wall_thickness
    slab_x_max = width - wall_thickness
    slab_y_max = depth - wall_thickness
    slab_z_bottom = z_height
    slab_z_top = z_height + thickness
    
    if opening is None:
        # Simple solid slab
        min_co = Vector((slab_x_min, slab_y_min, slab_z_bottom))
        max_co = Vector((slab_x_max, slab_y_max, slab_z_top))
        return util.create_box(bm, min_co, max_co, MAT_FLOOR)
    
    # Slab with opening - create as multiple sections around the hole
    # Clamp opening to slab bounds with minimum margin from edges
    min_margin = 0.05  # Minimum edge from opening to slab edge
    
    ox_min = max(opening['x_min'], slab_x_min + min_margin)
    oy_min = max(opening['y_min'], slab_y_min + min_margin)
    ox_max = min(opening['x_max'], slab_x_max - min_margin)
    oy_max = min(opening['y_max'], slab_y_max - min_margin)
    
    # Minimum dimension threshold for creating a section
    min_dim = 0.05
    
    # Create sections around the opening using an "frame" approach:
    # We create up to 4 sections that together form a frame around the opening
    
    # Section 1: Front strip (full width, from slab front to opening front)
    front_depth = oy_min - slab_y_min
    if front_depth > min_dim:
        min_co = Vector((slab_x_min, slab_y_min, slab_z_bottom))
        max_co = Vector((slab_x_max, oy_min, slab_z_top))
        faces.extend(util.create_box(bm, min_co, max_co, MAT_FLOOR))
    
    # Section 2: Back strip (full width, from opening back to slab back)
    back_depth = slab_y_max - oy_max
    if back_depth > min_dim:
        min_co = Vector((slab_x_min, oy_max, slab_z_bottom))
        max_co = Vector((slab_x_max, slab_y_max, slab_z_top))
        faces.extend(util.create_box(bm, min_co, max_co, MAT_FLOOR))
    
    # Section 3: Left strip (between opening Y bounds, from slab left to opening left)
    left_width = ox_min - slab_x_min
    if left_width > min_dim:
        min_co = Vector((slab_x_min, oy_min, slab_z_bottom))
        max_co = Vector((ox_min, oy_max, slab_z_top))
        faces.extend(util.create_box(bm, min_co, max_co, MAT_FLOOR))
    
    # Section 4: Right strip (between opening Y bounds, from opening right to slab right)
    right_width = slab_x_max - ox_max
    if right_width > min_dim:
        min_co = Vector((ox_max, oy_min, slab_z_bottom))
        max_co = Vector((slab_x_max, oy_max, slab_z_top))
        faces.extend(util.create_box(bm, min_co, max_co, MAT_FLOOR))
    
    return faces


def build_roof(bm: bmesh.types.BMesh, width: float, depth: float, 
               z_height: float, thickness: float = 0.2,
               wall_thickness: float = 0.25, has_parapet: bool = False) -> list:
    """
    Build a flat roof.
    
    Args:
        bm: BMesh to add geometry to
        width: Building width (X)
        depth: Building depth (Y)
        z_height: Height of the roof bottom
        thickness: Roof thickness
        wall_thickness: Wall thickness (to inset roof properly)
        has_parapet: If True, roof is inset; if False, extends to external bounds
    
    Returns:
        List of created faces
    """
    if has_parapet:
        # Roof is inset to sit within the parapet walls
        # Note: Parapet is thinner than main walls (0.8 * thickness)
        parapet_thickness = wall_thickness * 0.8
        min_co = Vector((parapet_thickness, parapet_thickness, z_height))
        max_co = Vector((width - parapet_thickness, depth - parapet_thickness, z_height + thickness))
    else:
        # Roof extends to external bounds to cap the walls
        min_co = Vector((0, 0, z_height))
        max_co = Vector((width, depth, z_height + thickness))
    
    faces = util.create_box(bm, min_co, max_co, MAT_ROOF)
    return faces


class BuildingShellBuilder:
    """Main builder class for creating building shells."""
    
    def __init__(self, params: dict):
        """
        Initialize the builder with generation parameters.
        
        Args:
            params: Dictionary of building parameters
        """
        self.params = params
        self.bm = None
    
    def build(self) -> bmesh.types.BMesh:
        """
        Build the complete building shell.
        
        Returns:
            BMesh containing the building geometry
        """
        # Initialize random seed
        util.seed_random(self.params.get('seed', 0))
        
        self.bm = util.create_bmesh()
        
        # Extract parameters
        width = self.params['width']
        depth = self.params['depth']
        floors = self.params['floors']
        floor_height = self.params['floor_height']
        wall_thickness = self.params['wall_thickness']
        
        # Window parameters
        window_width = self.params['window_width']
        window_height = self.params['window_height']
        window_spacing = self.params['window_spacing']
        sill_height = self.params['sill_height']
        windows_per_floor = self.params['windows_per_floor']
        
        # Ground floor parameters
        ground_floor_windows = self.params.get('ground_floor_windows', 'REGULAR')
        ground_floor_window_count = self.params.get('ground_floor_window_count', 2)
        storefront_window_height = self.params.get('storefront_window_height', 2.0)
        storefront_window_width = self.params.get('storefront_window_width', 2.0)
        storefront_sill_height = self.params.get('storefront_sill_height', 0.3)
        
        # Door parameters
        door_width = self.params['door_width']
        door_height = self.params['door_height']
        front_door_offset = self.params.get('front_door_offset', 0.5)
        back_exit = self.params['back_exit']
        back_door_offset = self.params.get('back_door_offset', 0.5)
        
        # Roof option
        has_roof = self.params.get('flat_roof', True)
        
        # Build each floor
        total_height = floors * floor_height
        
        # Check if damage is enabled
        enable_damage = self.params.get('enable_damage', False)
        damage_amount = self.params.get('damage_amount', 0.3)
        
        # Generate damage profile if damage enabled
        damage_profile = None
        intact_floors = floors  # All floors intact by default
        
        if enable_damage and damage_amount > 0:
            # Calculate minimum intact height - at least door height + margin
            # This ensures doors and ground floor windows are always visible
            min_intact_height = max(door_height + 0.5, floor_height * 0.8)
            
            # Get damage parameters
            pointiness = self.params.get('damage_pointiness', 0.5)
            resolution = self.params.get('damage_resolution', 1.0)
            
            damage_profile = damage_module.generate_damage_profile(
                width, depth, total_height, damage_amount,
                min_intact_height=min_intact_height,
                pointiness=pointiness,
                resolution=resolution,
                seed=self.params.get('seed', 0)
            )
            min_damage_height = damage_profile.get('min_height', total_height)
            intact_floors = damage_module.get_intact_floor_count(min_damage_height, floor_height)
            
            # Store damage min height for rubble generation to use
            self.params['damage_min_height'] = min_damage_height
            
            # Always build at least ground floor
            intact_floors = max(1, intact_floors)
        
        # === BUILD INTACT FLOORS NORMALLY ===
        # These get full features: windows, doors, etc.
        floors_to_build = min(intact_floors, floors)
        
        for floor_idx in range(floors_to_build):
            floor_base_z = floor_idx * floor_height
            is_ground_floor = (floor_idx == 0)
            # Top floor gets caps in these cases:
            # 1. No damage, no roof: cap the top floor
            # 2. Damage but doesn't cut into floors (intact_floors >= floors), no roof: cap top floor
            # 3. Damage cuts into floors: always cap last intact floor (damage builds on top)
            is_top_intact_floor = (floor_idx == floors_to_build - 1)
            
            if damage_profile is not None and intact_floors < floors:
                # Case 3: Damage cuts into upper floors - always cap for damage to build on
                is_top_floor = is_top_intact_floor
            else:
                # Cases 1 & 2: No damage or minimal damage - cap only if no roof
                is_top_floor = is_top_intact_floor and not has_roof
            
            # Determine window parameters for this floor
            if is_ground_floor:
                if ground_floor_windows == 'NONE':
                    current_window_height = 0
                    current_sill_height = sill_height
                    current_window_width = window_width
                    current_window_count = 0
                elif ground_floor_windows in ('STOREFRONT', 'STOREFRONT_WIDE'):
                    current_window_height = storefront_window_height
                    current_sill_height = storefront_sill_height
                    current_window_width = storefront_window_width
                    current_window_count = ground_floor_window_count
                else:  # REGULAR
                    current_window_height = window_height
                    current_sill_height = sill_height
                    current_window_width = window_width
                    current_window_count = windows_per_floor
            else:
                current_window_height = window_height
                current_sill_height = sill_height
                current_window_width = window_width
                current_window_count = windows_per_floor
            
            # Add wall caps on top floor:
            # - When damage cuts into floors: always cap (damage builds on top, no roof)
            # - Otherwise: cap only if no roof
            if damage_profile is not None and intact_floors < floors:
                add_wall_caps = is_top_floor  # Always cap when damage present
            else:
                add_wall_caps = is_top_floor and not has_roof
            
            # Check if this is the top floor with patio (need reduced walls)
            is_patio_floor = (is_top_intact_floor and 
                             self.params.get('has_patio', False) and 
                             floors >= 2 and
                             damage_profile is None)
            
            if is_patio_floor:
                # Build reduced walls for patio floor
                # Add top caps if there's no roof
                self._build_patio_floor_walls(
                    floor_base_z=floor_base_z,
                    floor_height=floor_height,
                    width=width,
                    depth=depth,
                    wall_thickness=wall_thickness,
                    window_width=current_window_width,
                    window_height=current_window_height,
                    window_spacing=window_spacing,
                    sill_height=current_sill_height,
                    windows_per_floor=current_window_count,
                    add_top_caps=not has_roof,
                )
            else:
                # Build normal walls for this floor
                self._build_floor_walls(
                    floor_idx=floor_idx,
                    floor_base_z=floor_base_z,
                    floor_height=floor_height,
                    width=width,
                    depth=depth,
                    wall_thickness=wall_thickness,
                    window_width=current_window_width,
                    window_height=current_window_height,
                    window_spacing=window_spacing,
                    sill_height=current_sill_height,
                    windows_per_floor=current_window_count,
                    is_ground_floor=is_ground_floor,
                    door_width=door_width,
                    door_height=door_height,
                    front_door_offset=front_door_offset,
                    back_exit=back_exit,
                    back_door_offset=back_door_offset,
                    add_wall_caps=add_wall_caps,
                )
            
            # Build floor slab (except for ground floor)
            if floor_idx > 0 and self.params.get('floor_slabs', True):
                stair_opening = self._get_stair_opening()
                
                if is_patio_floor:
                    # For patio floor, build a reduced slab covering only the interior portion
                    self._build_patio_interior_floor_slab(
                        floor_base_z, 0.15, width, depth, wall_thickness, stair_opening)
                else:
                    build_floor_slab(self.bm, width, depth, floor_base_z, 0.15, wall_thickness, stair_opening)
        
        # === BUILD ADDITIONAL FLOOR SLABS BELOW DAMAGE LINE ===
        # If damage cuts into upper floors, we still need to build their floor slabs
        # if the slab height is below the damage minimum
        if damage_profile is not None and self.params.get('floor_slabs', True):
            min_damage_height = damage_profile.get('min_height', total_height)
            for floor_idx in range(floors_to_build, floors):
                floor_base_z = floor_idx * floor_height
                # Only build slab if it's below the damage line
                if floor_base_z < min_damage_height - 0.1:
                    stair_opening = self._get_stair_opening()
                    build_floor_slab(self.bm, width, depth, floor_base_z, 0.15, wall_thickness, stair_opening)
        
        # === BUILD DAMAGED TOP PORTION ===
        if damage_profile is not None and intact_floors < floors:
            damaged_base_z = intact_floors * floor_height
            self._build_damaged_top(damage_profile, damaged_base_z, wall_thickness)
        
        # === BUILD FEATURES (only if no damage or damage doesn't affect top) ===
        build_roof_and_features = (damage_profile is None) or (intact_floors >= floors)
        
        # Check for patio on top floor
        has_patio = self.params.get('has_patio', False) and floors >= 2 and build_roof_and_features
        patio_info = None
        
        if build_roof_and_features:
            # Build facade pilasters if enabled
            if self.params.get('facade_pilasters', False):
                self._build_facade_pilasters(width, depth, total_height, wall_thickness)
            
            # Build patio if enabled
            if has_patio:
                patio_parapet_height = self.params.get('parapet_height', 0.5)
                patio_info = self._build_patio(
                    width, depth, floor_height, 
                    (floors - 1) * floor_height,  # top_floor_z
                    wall_thickness, patio_parapet_height)
            
            # Build roof parapet if enabled (on the non-patio portion)
            if self.params.get('roof_parapet', False):
                parapet_height = self.params.get('parapet_height', 0.5)
                if has_patio:
                    # Build parapet only on the interior (non-patio) portion
                    self._build_parapet_with_patio(width, depth, total_height, wall_thickness, 
                                                    parapet_height, patio_info)
                else:
                    self._build_parapet(width, depth, total_height, wall_thickness, parapet_height)
            
            # Build roof
            if has_roof:
                has_parapet = self.params.get('roof_parapet', False)
                if has_patio:
                    # Build roof only over the interior portion
                    self._build_roof_with_patio(width, depth, total_height, wall_thickness, 
                                                 has_parapet, patio_info)
                else:
                    build_roof(self.bm, width, depth, total_height, 0.2, wall_thickness, has_parapet)
        else:
            # Damaged building - might still have pilasters on intact portion
            if self.params.get('facade_pilasters', False) and intact_floors > 0:
                intact_height = intact_floors * floor_height
                self._build_facade_pilasters(width, depth, intact_height, wall_thickness)
        
        # Handle interior fill/rubble
        interior_fill = self.params.get('interior_fill', 'NONE')
        
        if interior_fill == 'FILLED':
            # Completely filled - no interior layout, just rubble
            interiors.generate_rubble_fill(self.bm, self.params)
        elif interior_fill == 'PARTIAL':
            # Partially filled - rubble on lower floors, interiors on upper
            interiors.generate_rubble_fill(self.bm, self.params)
            # Only generate interior for floors above fill level
            fill_floors = self.params.get('fill_floors', 1)
            if fill_floors < floors and self.params.get('building_profile', 'NONE') != 'NONE':
                # Create modified params for upper floors only
                upper_params = self.params.copy()
                upper_params['floors'] = floors - fill_floors
                # Note: Interior layout would need offset - for now skip
        elif interior_fill == 'RUBBLE_PILES':
            # Rubble piles alongside interior layout
            if self.params.get('building_profile', 'NONE') != 'NONE':
                interiors.generate_interior_layout(self.bm, self.params)
            interiors.generate_rubble_fill(self.bm, self.params)
        else:
            # Normal interior - generate layout if profile selected
            if self.params.get('building_profile', 'NONE') != 'NONE':
                interiors.generate_interior_layout(self.bm, self.params)
        
        # Generate exterior rubble if enabled
        if self.params.get('exterior_rubble', False):
            interiors.generate_exterior_rubble(self.bm, self.params)
        
        # Clean up mesh - comprehensive cleanup
        if self.params.get('auto_clean', True):
            self._cleanup_mesh()
        
        # Generate UVs and mark seams for easier texturing
        if self.params.get('mark_uv_seams', True):
            generate_uvs(self.bm)
            mark_seams_for_uvs(self.bm)
        
        return self.bm
    
    def _cleanup_mesh(self):
        """
        Conservative mesh cleanup - only remove truly problematic geometry.
        
        Steps:
        1. Remove duplicate vertices (merge by distance) - conservative threshold
        2. Remove loose vertices (not connected to any face)
        3. Remove degenerate geometry (zero-area faces)
        """
        # Step 1: Merge very close vertices - use small threshold to avoid merging window corners
        bmesh.ops.remove_doubles(self.bm, verts=self.bm.verts[:], dist=0.0005)
        
        # Step 2: Remove loose vertices (not part of any face)
        loose_verts = [v for v in self.bm.verts if not v.link_faces]
        if loose_verts:
            bmesh.ops.delete(self.bm, geom=loose_verts, context='VERTS')
        
        # Step 3: Remove degenerate geometry - only truly zero-area faces
        degenerate_faces = [f for f in self.bm.faces if f.calc_area() < 0.00001]
        if degenerate_faces:
            bmesh.ops.delete(self.bm, geom=degenerate_faces, context='FACES')
        
        # Step 4: Dissolve unnecessary edges on walls (reduces polygon count)
        # Only dissolve edges between coplanar wall faces with same material
        self._dissolve_wall_seams()
        
        # Note: We don't use recalc_face_normals because it can flip faces
        # that were correctly oriented during creation. All faces are created
        # with correct winding using cross-product checks.
    
    def _dissolve_wall_seams(self):
        """
        Dissolve unnecessary edges on walls to reduce polygon count.
        
        Only dissolves edges that:
        1. Connect exactly 2 faces
        2. Both faces are coplanar (same normal direction)
        3. Both faces have the same material
        4. The edge is not part of an opening frame (not near window/door edges)
        """
        edges_to_dissolve = []
        
        for edge in self.bm.edges:
            # Only consider edges with exactly 2 linked faces
            if len(edge.link_faces) != 2:
                continue
            
            f1, f2 = edge.link_faces
            
            # Both faces must have same material (wall material)
            if f1.material_index != f2.material_index:
                continue
            
            # Only dissolve wall faces (material index 0)
            if f1.material_index != MAT_WALLS:
                continue
            
            # Both faces must be coplanar (normals aligned)
            if f1.normal.dot(f2.normal) < 0.999:
                continue
            
            # Check if this edge is vertical (potential seam to remove)
            # Get edge direction
            edge_vec = edge.verts[1].co - edge.verts[0].co
            edge_len = edge_vec.length
            if edge_len < 0.001:
                continue
            
            edge_dir = edge_vec.normalized()
            
            # Check if edge is mostly vertical (Z-aligned)
            is_vertical = abs(edge_dir.z) > 0.9
            
            # For vertical edges, check if they span most of a floor height
            # (these are the seams we want to remove)
            floor_height = self.params.get('floor_height', 3.0)
            is_full_height_seam = is_vertical and edge_len > floor_height * 0.8
            
            if is_full_height_seam:
                edges_to_dissolve.append(edge)
        
        if edges_to_dissolve:
            try:
                bmesh.ops.dissolve_edges(self.bm, edges=edges_to_dissolve)
            except:
                pass  # Some edges might not be dissolvable
    
    def _build_damaged_top(self, damage_profile: dict, base_z: float, wall_thickness: float):
        """
        Build the damaged top portion of all walls with irregular top edges.
        
        This creates the ruined/weathered look above the intact floors.
        
        Args:
            damage_profile: Damage profile with height data for each wall
            base_z: Z height where the damaged portion starts (top of intact floors)
            wall_thickness: Wall thickness
        """
        width = self.params['width']
        depth = self.params['depth']
        
        # Front wall (Y = 0, facing -Y)
        front_profile = damage_profile.get('front', [])
        if front_profile:
            damage_module.build_damaged_top_section(
                self.bm, front_profile,
                start_pos=Vector((0, 0, 0)),
                direction=Vector((1, 0, 0)),
                normal=Vector((0, -1, 0)),
                base_z=base_z,
                thickness=wall_thickness,
                mat_index=MAT_WALLS
            )
        
        # Back wall (Y = depth, facing +Y)
        back_profile = damage_profile.get('back', [])
        if back_profile:
            # Reverse the profile for back wall
            reversed_profile = [(width - pos, height) for pos, height in reversed(back_profile)]
            damage_module.build_damaged_top_section(
                self.bm, reversed_profile,
                start_pos=Vector((0, depth, 0)),
                direction=Vector((1, 0, 0)),
                normal=Vector((0, 1, 0)),
                base_z=base_z,
                thickness=wall_thickness,
                mat_index=MAT_WALLS
            )
        
        # Left wall (X = 0, facing -X) - shortened to avoid corner overlap
        left_profile = damage_profile.get('left', [])
        if left_profile:
            # Adjust profile to fit between front/back walls
            adjusted_profile = []
            for pos, height in left_profile:
                # Scale position to fit shortened wall
                if depth > 2 * wall_thickness:
                    scaled_pos = wall_thickness + (pos / depth) * (depth - 2 * wall_thickness)
                else:
                    scaled_pos = pos
                adjusted_profile.append((scaled_pos - wall_thickness, height))
            
            damage_module.build_damaged_top_section(
                self.bm, adjusted_profile,
                start_pos=Vector((0, wall_thickness, 0)),
                direction=Vector((0, 1, 0)),
                normal=Vector((-1, 0, 0)),
                base_z=base_z,
                thickness=wall_thickness,
                mat_index=MAT_WALLS
            )
        
        # Right wall (X = width, facing +X) - shortened to avoid corner overlap
        right_profile = damage_profile.get('right', [])
        if right_profile:
            adjusted_profile = []
            for pos, height in right_profile:
                if depth > 2 * wall_thickness:
                    scaled_pos = wall_thickness + (pos / depth) * (depth - 2 * wall_thickness)
                else:
                    scaled_pos = pos
                adjusted_profile.append((scaled_pos - wall_thickness, height))
            
            damage_module.build_damaged_top_section(
                self.bm, adjusted_profile,
                start_pos=Vector((width, wall_thickness, 0)),
                direction=Vector((0, 1, 0)),
                normal=Vector((1, 0, 0)),
                base_z=base_z,
                thickness=wall_thickness,
                mat_index=MAT_WALLS
            )
    
    def _build_facade_pilasters(self, width: float, depth: float, total_height: float, 
                                 wall_thickness: float):
        """
        Build facade pilasters (protruding vertical columns) on building exterior.
        
        Pilasters add architectural detail and break up flat facades.
        Respects patio areas by stopping pilasters at patio floor level on affected sides.
        """
        pilaster_width = self.params.get('pilaster_width', 0.4)
        pilaster_depth = self.params.get('pilaster_depth', 0.15)
        style = self.params.get('pilaster_style', 'CORNERS')
        sides = self.params.get('pilaster_sides', 'FRONT')
        
        windows_per_floor = self.params.get('windows_per_floor', 3)
        window_width = self.params.get('window_width', 1.2)
        window_spacing = self.params.get('window_spacing', 0.8)
        
        # Determine which walls get pilasters
        has_front = sides in ('FRONT', 'FRONT_BACK', 'ALL')
        has_back = sides in ('FRONT_BACK', 'ALL')
        has_left = sides == 'ALL'
        has_right = sides == 'ALL'
        
        # Check for patio - pilasters on patio side stop at patio floor level
        has_patio = self.params.get('has_patio', False)
        patio_side = self.params.get('patio_side', 'BACK') if has_patio else None
        floors = self.params.get('floors', 2)
        floor_height = self.params.get('floor_height', 3.5)
        patio_floor_z = (floors - 1) * floor_height if has_patio else total_height
        
        # Calculate heights for each side based on patio
        front_height = patio_floor_z if patio_side == 'FRONT' else total_height
        back_height = patio_floor_z if patio_side == 'BACK' else total_height
        left_height = patio_floor_z if patio_side == 'LEFT' else total_height
        right_height = patio_floor_z if patio_side == 'RIGHT' else total_height
        
        # Calculate pilaster positions based on style
        def get_pilaster_positions(wall_length: float, is_front_back: bool) -> list:
            """Get X positions for pilasters along a wall."""
            positions = []
            half_width = pilaster_width / 2
            
            # Corner pilasters (slightly inset from actual corner)
            if style in ('CORNERS', 'CORNERS_CENTER', 'FULL'):
                positions.append(half_width)  # Left corner
                positions.append(wall_length - half_width)  # Right corner
            
            # Center pilaster
            if style in ('CORNERS_CENTER', 'FULL'):
                positions.append(wall_length / 2)
            
            # Pilasters between windows (for front/back walls)
            if style in ('BETWEEN_WINDOWS', 'FULL') and is_front_back:
                total_window_area = windows_per_floor * window_width + (windows_per_floor - 1) * window_spacing
                if total_window_area < wall_length * 0.9:
                    start_x = (wall_length - total_window_area) / 2
                    
                    # Add pilaster before first window
                    if start_x > pilaster_width * 1.5:
                        positions.append(start_x - pilaster_width)
                    
                    # Add pilasters between windows
                    for i in range(windows_per_floor - 1):
                        x = start_x + (i + 1) * window_width + (i + 0.5) * window_spacing
                        if x > pilaster_width and x < wall_length - pilaster_width:
                            positions.append(x)
                    
                    # Add pilaster after last window
                    end_x = start_x + total_window_area
                    if wall_length - end_x > pilaster_width * 1.5:
                        positions.append(end_x + pilaster_width)
            
            return sorted(set(positions))
        
        # Build pilasters on front wall (Y = 0, protruding in -Y direction)
        if has_front:
            positions = get_pilaster_positions(width, True)
            patio_size = self.params.get('patio_size', 0.4)
            divider_x_left = width * patio_size          # For LEFT patio
            divider_x_right = width * (1 - patio_size)   # For RIGHT patio
            
            for x in positions:
                # Determine height based on whether this pilaster is in the patio zone
                pilaster_height = front_height
                if patio_side == 'LEFT' and x < divider_x_left:
                    pilaster_height = patio_floor_z
                elif patio_side == 'RIGHT' and x > divider_x_right:
                    pilaster_height = patio_floor_z
                
                # Pilaster box: protruding outward from front wall
                min_co = Vector((x - pilaster_width/2, -pilaster_depth, 0))
                max_co = Vector((x + pilaster_width/2, 0, pilaster_height))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Build pilasters on back wall (Y = depth, protruding in +Y direction)
        if has_back:
            positions = get_pilaster_positions(width, True)
            patio_size = self.params.get('patio_size', 0.4)
            divider_x_left = width * patio_size          # For LEFT patio
            divider_x_right = width * (1 - patio_size)   # For RIGHT patio
            
            for x in positions:
                # Determine height based on whether this pilaster is in the patio zone
                pilaster_height = back_height
                if patio_side == 'LEFT' and x < divider_x_left:
                    pilaster_height = patio_floor_z
                elif patio_side == 'RIGHT' and x > divider_x_right:
                    pilaster_height = patio_floor_z
                
                min_co = Vector((x - pilaster_width/2, depth, 0))
                max_co = Vector((x + pilaster_width/2, depth + pilaster_depth, pilaster_height))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Build pilasters on left wall (X = 0, protruding in -X direction)
        if has_left:
            positions = get_pilaster_positions(depth, False)
            patio_size = self.params.get('patio_size', 0.4)
            divider_y_back = depth * (1 - patio_size)  # For BACK patio
            divider_y_front = depth * patio_size        # For FRONT patio
            
            for y in positions:
                # Determine height based on whether this pilaster is in the patio zone
                pilaster_height = left_height
                if patio_side == 'BACK' and y > divider_y_back:
                    pilaster_height = patio_floor_z
                elif patio_side == 'FRONT' and y < divider_y_front:
                    pilaster_height = patio_floor_z
                
                min_co = Vector((-pilaster_depth, y - pilaster_width/2, 0))
                max_co = Vector((0, y + pilaster_width/2, pilaster_height))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Build pilasters on right wall (X = width, protruding in +X direction)
        if has_right:
            positions = get_pilaster_positions(depth, False)
            patio_size = self.params.get('patio_size', 0.4)
            divider_y_back = depth * (1 - patio_size)  # For BACK patio
            divider_y_front = depth * patio_size        # For FRONT patio
            
            for y in positions:
                # Determine height based on whether this pilaster is in the patio zone
                pilaster_height = right_height
                if patio_side == 'BACK' and y > divider_y_back:
                    pilaster_height = patio_floor_z
                elif patio_side == 'FRONT' and y < divider_y_front:
                    pilaster_height = patio_floor_z
                
                min_co = Vector((width, y - pilaster_width/2, 0))
                max_co = Vector((width + pilaster_depth, y + pilaster_width/2, pilaster_height))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
    
    def _build_parapet(self, width: float, depth: float, roof_height: float,
                        wall_thickness: float, parapet_height: float):
        """
        Build roof parapet - walls that extend above the roof line.
        
        Creates a low wall around the perimeter of the roof.
        """
        # Parapet sits on top of existing walls, extends upward
        z_base = roof_height
        z_top = roof_height + parapet_height
        
        # Slightly thinner than main walls for visual interest
        parapet_thickness = wall_thickness * 0.8
        
        # Front parapet (Y = 0)
        min_co = Vector((0, 0, z_base))
        max_co = Vector((width, parapet_thickness, z_top))
        util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Back parapet (Y = depth)
        min_co = Vector((0, depth - parapet_thickness, z_base))
        max_co = Vector((width, depth, z_top))
        util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Left parapet (X = 0)
        min_co = Vector((0, parapet_thickness, z_base))
        max_co = Vector((parapet_thickness, depth - parapet_thickness, z_top))
        util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # Right parapet (X = width)
        min_co = Vector((width - parapet_thickness, parapet_thickness, z_base))
        max_co = Vector((width, depth - parapet_thickness, z_top))
        util.create_box(self.bm, min_co, max_co, MAT_WALLS)
        
        # If pilasters are enabled, extend them through the parapet
        if self.params.get('facade_pilasters', False):
            pilaster_width = self.params.get('pilaster_width', 0.4)
            pilaster_depth = self.params.get('pilaster_depth', 0.15)
            sides = self.params.get('pilaster_sides', 'FRONT')
            
            has_front = sides in ('FRONT', 'FRONT_BACK', 'ALL')
            has_back = sides in ('FRONT_BACK', 'ALL')
            
            # Front corner pilasters extended through parapet
            if has_front:
                # Left corner
                min_co = Vector((pilaster_width/2 - pilaster_width/2, -pilaster_depth, z_base))
                max_co = Vector((pilaster_width/2 + pilaster_width/2, 0, z_top))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
                # Right corner
                min_co = Vector((width - pilaster_width/2 - pilaster_width/2, -pilaster_depth, z_base))
                max_co = Vector((width - pilaster_width/2 + pilaster_width/2, 0, z_top))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
            
            if has_back:
                # Left corner
                min_co = Vector((pilaster_width/2 - pilaster_width/2, depth, z_base))
                max_co = Vector((pilaster_width/2 + pilaster_width/2, depth + pilaster_depth, z_top))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
                # Right corner
                min_co = Vector((width - pilaster_width/2 - pilaster_width/2, depth, z_base))
                max_co = Vector((width - pilaster_width/2 + pilaster_width/2, depth + pilaster_depth, z_top))
                util.create_box(self.bm, min_co, max_co, MAT_WALLS)
    
    def _build_parapet_with_patio(self, width: float, depth: float, roof_height: float,
                                    wall_thickness: float, parapet_height: float, patio_info: dict):
        """
        Build roof parapet, accounting for patio area.
        
        Only builds parapet on the interior (non-patio) portion of the building.
        """
        z_base = roof_height
        z_top = roof_height + parapet_height
        parapet_thickness = wall_thickness * 0.8
        
        patio_side = patio_info['side']
        
        if patio_side == 'BACK':
            divider_y = patio_info['divider_y']
            # Front parapet (full width)
            util.create_box(self.bm, Vector((0, 0, z_base)), 
                           Vector((width, parapet_thickness, z_top)), MAT_WALLS)
            # Left parapet (up to divider)
            util.create_box(self.bm, Vector((0, parapet_thickness, z_base)),
                           Vector((parapet_thickness, divider_y, z_top)), MAT_WALLS)
            # Right parapet (up to divider)
            util.create_box(self.bm, Vector((width - parapet_thickness, parapet_thickness, z_base)),
                           Vector((width, divider_y, z_top)), MAT_WALLS)
            # Back parapet at divider line
            util.create_box(self.bm, Vector((0, divider_y - parapet_thickness, z_base)),
                           Vector((width, divider_y, z_top)), MAT_WALLS)
                           
        elif patio_side == 'FRONT':
            divider_y = patio_info['divider_y']
            # Back parapet (full width)
            util.create_box(self.bm, Vector((0, depth - parapet_thickness, z_base)),
                           Vector((width, depth, z_top)), MAT_WALLS)
            # Left parapet (from divider to back)
            util.create_box(self.bm, Vector((0, divider_y, z_base)),
                           Vector((parapet_thickness, depth - parapet_thickness, z_top)), MAT_WALLS)
            # Right parapet (from divider to back)
            util.create_box(self.bm, Vector((width - parapet_thickness, divider_y, z_base)),
                           Vector((width, depth - parapet_thickness, z_top)), MAT_WALLS)
            # Front parapet at divider line
            util.create_box(self.bm, Vector((0, divider_y, z_base)),
                           Vector((width, divider_y + parapet_thickness, z_top)), MAT_WALLS)
                           
        elif patio_side == 'LEFT':
            divider_x = patio_info['divider_x']
            # Right parapet (full depth)
            util.create_box(self.bm, Vector((width - parapet_thickness, 0, z_base)),
                           Vector((width, depth, z_top)), MAT_WALLS)
            # Front parapet (from divider to right)
            util.create_box(self.bm, Vector((divider_x, 0, z_base)),
                           Vector((width - parapet_thickness, parapet_thickness, z_top)), MAT_WALLS)
            # Back parapet (from divider to right)
            util.create_box(self.bm, Vector((divider_x, depth - parapet_thickness, z_base)),
                           Vector((width - parapet_thickness, depth, z_top)), MAT_WALLS)
            # Left parapet at divider line
            util.create_box(self.bm, Vector((divider_x, 0, z_base)),
                           Vector((divider_x + parapet_thickness, depth, z_top)), MAT_WALLS)
                           
        else:  # RIGHT
            divider_x = patio_info['divider_x']
            # Left parapet (full depth)
            util.create_box(self.bm, Vector((0, 0, z_base)),
                           Vector((parapet_thickness, depth, z_top)), MAT_WALLS)
            # Front parapet (from left to divider)
            util.create_box(self.bm, Vector((parapet_thickness, 0, z_base)),
                           Vector((divider_x, parapet_thickness, z_top)), MAT_WALLS)
            # Back parapet (from left to divider)
            util.create_box(self.bm, Vector((parapet_thickness, depth - parapet_thickness, z_base)),
                           Vector((divider_x, depth, z_top)), MAT_WALLS)
            # Right parapet at divider line
            util.create_box(self.bm, Vector((divider_x - parapet_thickness, 0, z_base)),
                           Vector((divider_x, depth, z_top)), MAT_WALLS)
        
        # Extend pilasters through parapet (only on non-patio sides)
        if self.params.get('facade_pilasters', False):
            pilaster_width = self.params.get('pilaster_width', 0.4)
            pilaster_depth = self.params.get('pilaster_depth', 0.15)
            sides = self.params.get('pilaster_sides', 'FRONT')
            
            has_front = sides in ('FRONT', 'FRONT_BACK', 'ALL') and patio_side != 'FRONT'
            has_back = sides in ('FRONT_BACK', 'ALL') and patio_side != 'BACK'
            
            # Front corner pilasters extended through parapet
            if has_front:
                # Left corner
                util.create_box(self.bm, 
                    Vector((pilaster_width/2 - pilaster_width/2, -pilaster_depth, z_base)),
                    Vector((pilaster_width/2 + pilaster_width/2, 0, z_top)), MAT_WALLS)
                # Right corner
                util.create_box(self.bm,
                    Vector((width - pilaster_width/2 - pilaster_width/2, -pilaster_depth, z_base)),
                    Vector((width - pilaster_width/2 + pilaster_width/2, 0, z_top)), MAT_WALLS)
            
            if has_back:
                # Left corner
                util.create_box(self.bm,
                    Vector((pilaster_width/2 - pilaster_width/2, depth, z_base)),
                    Vector((pilaster_width/2 + pilaster_width/2, depth + pilaster_depth, z_top)), MAT_WALLS)
                # Right corner
                util.create_box(self.bm,
                    Vector((width - pilaster_width/2 - pilaster_width/2, depth, z_base)),
                    Vector((width - pilaster_width/2 + pilaster_width/2, depth + pilaster_depth, z_top)), MAT_WALLS)
    
    def _build_roof_with_patio(self, width: float, depth: float, roof_height: float,
                                wall_thickness: float, has_parapet: bool, patio_info: dict):
        """
        Build roof over the interior portion only (not the patio).
        """
        patio_side = patio_info['side']
        thickness = 0.2
        
        # Calculate roof bounds based on patio side
        # Calculate roof bounds based on patio side
        # Use parapet thickness for inset if parapet exists
        parapet_thickness = wall_thickness * 0.8 if has_parapet else 0.0
        
        if patio_side == 'BACK':
            divider_y = patio_info['divider_y']
            if has_parapet:
                min_co = Vector((parapet_thickness, parapet_thickness, roof_height))
                max_co = Vector((width - parapet_thickness, divider_y - parapet_thickness, roof_height + thickness))
            else:
                min_co = Vector((0, 0, roof_height))
                max_co = Vector((width, divider_y, roof_height + thickness))
                
        elif patio_side == 'FRONT':
            divider_y = patio_info['divider_y']
            if has_parapet:
                min_co = Vector((parapet_thickness, divider_y + parapet_thickness, roof_height))
                max_co = Vector((width - parapet_thickness, depth - parapet_thickness, roof_height + thickness))
            else:
                min_co = Vector((0, divider_y, roof_height))
                max_co = Vector((width, depth, roof_height + thickness))
                
        elif patio_side == 'LEFT':
            divider_x = patio_info['divider_x']
            if has_parapet:
                min_co = Vector((divider_x + parapet_thickness, parapet_thickness, roof_height))
                max_co = Vector((width - parapet_thickness, depth - parapet_thickness, roof_height + thickness))
            else:
                min_co = Vector((divider_x, 0, roof_height))
                max_co = Vector((width, depth, roof_height + thickness))
                
        else:  # RIGHT
            divider_x = patio_info['divider_x']
            if has_parapet:
                min_co = Vector((parapet_thickness, parapet_thickness, roof_height))
                max_co = Vector((divider_x - parapet_thickness, depth - parapet_thickness, roof_height + thickness))
            else:
                min_co = Vector((0, 0, roof_height))
                max_co = Vector((divider_x, depth, roof_height + thickness))
        
        util.create_box(self.bm, min_co, max_co, MAT_ROOF)
    
    def _build_patio(self, width: float, depth: float, floor_height: float,
                      top_floor_z: float, wall_thickness: float, parapet_height: float = 0.5):
        """
        Build a patio on the top floor.
        
        The patio is an open area with a parapet, with a door connecting to the interior.
        
        Args:
            width: Building width
            depth: Building depth
            floor_height: Height of the floor
            top_floor_z: Z height of the top floor base
            wall_thickness: Wall thickness
            parapet_height: Height of the patio parapet
        """
        patio_side = self.params.get('patio_side', 'BACK')
        patio_size = self.params.get('patio_size', 0.4)  # Fraction of building
        patio_door_width = self.params.get('patio_door_width', 1.5)
        
        # Calculate patio bounds based on side
        # Patio parapet is thinner than walls
        parapet_thickness = wall_thickness * 0.7
        
        # Calculate the dividing wall position and patio bounds
        if patio_side == 'BACK':
            # Patio at back (high Y)
            divider_y = depth * (1 - patio_size)
            patio_min = Vector((0, divider_y, top_floor_z))
            patio_max = Vector((width, depth, top_floor_z + floor_height))
            interior_depth = divider_y
            interior_width = width
            # Divider wall runs along X axis at Y = divider_y
            divider_horizontal = True
        elif patio_side == 'FRONT':
            # Patio at front (low Y)
            divider_y = depth * patio_size
            patio_min = Vector((0, 0, top_floor_z))
            patio_max = Vector((width, divider_y, top_floor_z + floor_height))
            interior_depth = depth - divider_y
            interior_width = width
            divider_horizontal = True
        elif patio_side == 'LEFT':
            # Patio at left (low X)
            divider_x = width * patio_size
            patio_min = Vector((0, 0, top_floor_z))
            patio_max = Vector((divider_x, depth, top_floor_z + floor_height))
            interior_width = width - divider_x
            interior_depth = depth
            divider_horizontal = False
        else:  # RIGHT
            # Patio at right (high X)
            divider_x = width * (1 - patio_size)
            patio_min = Vector((divider_x, 0, top_floor_z))
            patio_max = Vector((width, depth, top_floor_z + floor_height))
            interior_width = divider_x
            interior_depth = depth
            divider_horizontal = False
        
        # Build patio parapet (around the outer edges of the patio)
        # Parapet starts at patio floor level and goes up parapet_height
        z_base = top_floor_z
        z_top = z_base + parapet_height
        
        if patio_side == 'BACK':
            # Front of patio (divider line) - will have door, built separately
            # Back parapet
            util.create_box(self.bm, 
                Vector((0, depth - parapet_thickness, z_base)),
                Vector((width, depth, z_top)), MAT_WALLS)
            # Left side parapet (patio portion only)
            util.create_box(self.bm,
                Vector((0, divider_y, z_base)),
                Vector((parapet_thickness, depth - parapet_thickness, z_top)), MAT_WALLS)
            # Right side parapet (patio portion only)
            util.create_box(self.bm,
                Vector((width - parapet_thickness, divider_y, z_base)),
                Vector((width, depth - parapet_thickness, z_top)), MAT_WALLS)
            
            # Build divider wall with door opening
            self._build_patio_divider_wall(
                Vector((0, divider_y, 0)),
                Vector((width, divider_y, 0)),
                floor_height, wall_thickness, patio_door_width,
                normal=Vector((0, 1, 0)),  # Faces toward patio
                base_z=top_floor_z)
                
        elif patio_side == 'FRONT':
            # Back parapet (divider line) - will have door
            # Front parapet
            util.create_box(self.bm,
                Vector((0, 0, z_base)),
                Vector((width, parapet_thickness, z_top)), MAT_WALLS)
            # Left side parapet
            util.create_box(self.bm,
                Vector((0, parapet_thickness, z_base)),
                Vector((parapet_thickness, divider_y, z_top)), MAT_WALLS)
            # Right side parapet
            util.create_box(self.bm,
                Vector((width - parapet_thickness, parapet_thickness, z_base)),
                Vector((width, divider_y, z_top)), MAT_WALLS)
            
            # Build divider wall with door
            self._build_patio_divider_wall(
                Vector((0, divider_y, 0)),
                Vector((width, divider_y, 0)),
                floor_height, wall_thickness, patio_door_width,
                normal=Vector((0, -1, 0)),
                base_z=top_floor_z)
                
        elif patio_side == 'LEFT':
            # Left parapet
            util.create_box(self.bm,
                Vector((0, 0, z_base)),
                Vector((parapet_thickness, depth, z_top)), MAT_WALLS)
            # Front parapet (patio portion)
            util.create_box(self.bm,
                Vector((parapet_thickness, 0, z_base)),
                Vector((divider_x, parapet_thickness, z_top)), MAT_WALLS)
            # Back parapet (patio portion)
            util.create_box(self.bm,
                Vector((parapet_thickness, depth - parapet_thickness, z_base)),
                Vector((divider_x, depth, z_top)), MAT_WALLS)
            
            # Build divider wall with door
            self._build_patio_divider_wall(
                Vector((divider_x, 0, 0)),
                Vector((divider_x, depth, 0)),
                floor_height, wall_thickness, patio_door_width,
                normal=Vector((-1, 0, 0)),
                base_z=top_floor_z)
                
        else:  # RIGHT
            # Right parapet
            util.create_box(self.bm,
                Vector((width - parapet_thickness, 0, z_base)),
                Vector((width, depth, z_top)), MAT_WALLS)
            # Front parapet (patio portion)
            util.create_box(self.bm,
                Vector((divider_x, 0, z_base)),
                Vector((width - parapet_thickness, parapet_thickness, z_top)), MAT_WALLS)
            # Back parapet (patio portion)
            util.create_box(self.bm,
                Vector((divider_x, depth - parapet_thickness, z_base)),
                Vector((width - parapet_thickness, depth, z_top)), MAT_WALLS)
            
            # Build divider wall with door
            self._build_patio_divider_wall(
                Vector((divider_x, 0, 0)),
                Vector((divider_x, depth, 0)),
                floor_height, wall_thickness, patio_door_width,
                normal=Vector((1, 0, 0)),
                base_z=top_floor_z)
        
        # Build patio floor slab (exposed top of floor below becomes patio floor)
        # The slab should fill the patio area inside the parapets
        # Note: This slab is at floor level (top_floor_z), same as interior slab
        slab_thickness = 0.15
        
        # Calculate correct slab bounds based on patio side
        # The slab needs to go from the divider wall to inside the exterior walls/parapets
        if patio_side == 'BACK':
            slab_x_min = parapet_thickness
            slab_x_max = width - parapet_thickness
            slab_y_min = divider_y
            slab_y_max = depth - parapet_thickness
        elif patio_side == 'FRONT':
            slab_x_min = parapet_thickness
            slab_x_max = width - parapet_thickness
            slab_y_min = parapet_thickness
            slab_y_max = divider_y
        elif patio_side == 'LEFT':
            slab_x_min = parapet_thickness
            slab_x_max = divider_x
            slab_y_min = parapet_thickness
            slab_y_max = depth - parapet_thickness
        else:  # RIGHT
            slab_x_min = divider_x
            slab_x_max = width - parapet_thickness
            slab_y_min = parapet_thickness
            slab_y_max = depth - parapet_thickness
        
        slab_z_bottom = top_floor_z
        slab_z_top = top_floor_z + slab_thickness
        
        # Check if stair opening intersects with patio area
        stair_opening = self._get_stair_opening()
        
        if stair_opening is None:
            # No stair opening - build solid slab
            util.create_box(self.bm,
                Vector((slab_x_min, slab_y_min, slab_z_bottom)),
                Vector((slab_x_max, slab_y_max, slab_z_top)), MAT_FLOOR)
        else:
            # Check if opening intersects with patio slab bounds
            min_margin = 0.05
            ox_min = max(stair_opening['x_min'], slab_x_min + min_margin)
            oy_min = max(stair_opening['y_min'], slab_y_min + min_margin)
            ox_max = min(stair_opening['x_max'], slab_x_max - min_margin)
            oy_max = min(stair_opening['y_max'], slab_y_max - min_margin)
            
            if ox_min >= ox_max or oy_min >= oy_max:
                # Opening doesn't intersect patio - build solid slab
                util.create_box(self.bm,
                    Vector((slab_x_min, slab_y_min, slab_z_bottom)),
                    Vector((slab_x_max, slab_y_max, slab_z_top)), MAT_FLOOR)
            else:
                # Build slab sections around the opening
                # Front section
                if oy_min > slab_y_min + min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, slab_y_min, slab_z_bottom)),
                        Vector((slab_x_max, oy_min, slab_z_top)), MAT_FLOOR)
                # Back section
                if oy_max < slab_y_max - min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, oy_max, slab_z_bottom)),
                        Vector((slab_x_max, slab_y_max, slab_z_top)), MAT_FLOOR)
                # Left section
                if ox_min > slab_x_min + min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, oy_min, slab_z_bottom)),
                        Vector((ox_min, oy_max, slab_z_top)), MAT_FLOOR)
                # Right section
                if ox_max < slab_x_max - min_margin:
                    util.create_box(self.bm,
                        Vector((ox_max, oy_min, slab_z_bottom)),
                        Vector((slab_x_max, oy_max, slab_z_top)), MAT_FLOOR)
        
        # Return patio info for roof adjustment
        return {
            'side': patio_side,
            'size': patio_size,
            'divider_y': divider_y if patio_side in ('FRONT', 'BACK') else None,
            'divider_x': divider_x if patio_side in ('LEFT', 'RIGHT') else None,
        }
    
    def _build_patio_divider_wall(self, start: Vector, end: Vector, height: float,
                                   thickness: float, door_width: float, normal: Vector,
                                   base_z: float = 0.0):
        """
        Build the wall that separates interior from patio, with a door opening.
        
        Args:
            start: Start position (X, Y only, Z should be 0)
            end: End position (X, Y only, Z should be 0)
            height: Wall height
            thickness: Wall thickness
            door_width: Width of door opening
            normal: Wall normal direction
            base_z: Z height of wall base
        """
        wall_length = (end - start).length
        door_height = min(height - 0.3, 2.4)  # Standard door height or fit to floor
        
        # Door position - centered
        door_x = (wall_length - door_width) / 2
        
        # Create wall segment with door opening
        segment = WallSegment(
            start=start,
            end=end,
            height=height,
            base_z=base_z,
            normal=normal
        )
        segment.add_opening(door_x, door_x + door_width, 0, door_height, 'door')
        
        # Build wall with the door
        build_wall_with_openings(self.bm, segment, thickness, add_top_cap=True)
    
    def _get_stair_opening(self) -> dict:
        """Get stair opening bounds for floor slabs."""
        # Use the centralized function from interiors module
        return interiors.get_floor_slab_opening(self.params)
    
    def _build_patio_interior_floor_slab(self, z_height: float, thickness: float,
                                          width: float, depth: float, wall_thickness: float,
                                          stair_opening: dict = None):
        """
        Build floor slab for patio floor that only covers the interior portion.
        
        The patio area gets a separate slab built in _build_patio.
        """
        patio_side = self.params.get('patio_side', 'BACK')
        patio_size = self.params.get('patio_size', 0.4)
        
        # Calculate interior slab bounds based on patio side
        slab_x_min = wall_thickness
        slab_y_min = wall_thickness
        slab_x_max = width - wall_thickness
        slab_y_max = depth - wall_thickness
        
        if patio_side == 'BACK':
            divider_y = depth * (1 - patio_size)
            slab_y_max = divider_y  # Stop at divider
        elif patio_side == 'FRONT':
            divider_y = depth * patio_size
            slab_y_min = divider_y  # Start from divider
        elif patio_side == 'LEFT':
            divider_x = width * patio_size
            slab_x_min = divider_x  # Start from divider
        else:  # RIGHT
            divider_x = width * (1 - patio_size)
            slab_x_max = divider_x  # Stop at divider
        
        slab_z_bottom = z_height
        slab_z_top = z_height + thickness
        
        if stair_opening is None:
            # Simple solid slab
            min_co = Vector((slab_x_min, slab_y_min, slab_z_bottom))
            max_co = Vector((slab_x_max, slab_y_max, slab_z_top))
            util.create_box(self.bm, min_co, max_co, MAT_FLOOR)
        else:
            # Slab with opening - create sections around the hole
            min_margin = 0.05
            ox_min = max(stair_opening['x_min'], slab_x_min + min_margin)
            oy_min = max(stair_opening['y_min'], slab_y_min + min_margin)
            ox_max = min(stair_opening['x_max'], slab_x_max - min_margin)
            oy_max = min(stair_opening['y_max'], slab_y_max - min_margin)
            
            # Check if opening is within slab bounds
            if ox_min >= ox_max or oy_min >= oy_max:
                # Opening doesn't intersect - build solid slab
                min_co = Vector((slab_x_min, slab_y_min, slab_z_bottom))
                max_co = Vector((slab_x_max, slab_y_max, slab_z_top))
                util.create_box(self.bm, min_co, max_co, MAT_FLOOR)
            else:
                # Create 4 sections around the opening (L-shaped pieces)
                # Front section (Y from slab_y_min to oy_min)
                if oy_min > slab_y_min + min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, slab_y_min, slab_z_bottom)),
                        Vector((slab_x_max, oy_min, slab_z_top)), MAT_FLOOR)
                
                # Back section (Y from oy_max to slab_y_max)
                if oy_max < slab_y_max - min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, oy_max, slab_z_bottom)),
                        Vector((slab_x_max, slab_y_max, slab_z_top)), MAT_FLOOR)
                
                # Left section (X from slab_x_min to ox_min, Y from oy_min to oy_max)
                if ox_min > slab_x_min + min_margin:
                    util.create_box(self.bm,
                        Vector((slab_x_min, oy_min, slab_z_bottom)),
                        Vector((ox_min, oy_max, slab_z_top)), MAT_FLOOR)
                
                # Right section (X from ox_max to slab_x_max, Y from oy_min to oy_max)
                if ox_max < slab_x_max - min_margin:
                    util.create_box(self.bm,
                        Vector((ox_max, oy_min, slab_z_bottom)),
                        Vector((slab_x_max, oy_max, slab_z_top)), MAT_FLOOR)
    
    def _build_patio_floor_walls(self, floor_base_z: float, floor_height: float,
                                   width: float, depth: float, wall_thickness: float,
                                   window_width: float, window_height: float, window_spacing: float,
                                   sill_height: float, windows_per_floor: int,
                                   add_top_caps: bool = False):
        """
        Build walls for the top floor that has a patio.
        
        Only builds walls for the interior (non-patio) portion of the floor.
        The patio parapet and divider wall are built separately.
        
        Args:
            add_top_caps: Whether to add top caps to walls (should be True if no roof)
        """
        patio_side = self.params.get('patio_side', 'BACK')
        patio_size = self.params.get('patio_size', 0.4)
        
        # Calculate the interior bounds based on patio side
        if patio_side == 'BACK':
            divider_y = depth * (1 - patio_size)
            # Interior walls: full width, reduced depth
            front_wall = WallSegment(
                start=Vector((0, 0, 0)),
                end=Vector((width, 0, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, -1, 0))
            )
            # Left wall (shortened in Y)
            left_wall = WallSegment(
                start=Vector((0, divider_y - wall_thickness, 0)),
                end=Vector((0, wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((-1, 0, 0))
            )
            # Right wall (shortened in Y)
            right_wall = WallSegment(
                start=Vector((width, wall_thickness, 0)),
                end=Vector((width, divider_y - wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((1, 0, 0))
            )
            walls = [front_wall, left_wall, right_wall]
            
        elif patio_side == 'FRONT':
            divider_y = depth * patio_size
            # Back wall (full width)
            back_wall = WallSegment(
                start=Vector((width, depth, 0)),
                end=Vector((0, depth, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, 1, 0))
            )
            # Left wall (shortened in Y)
            left_wall = WallSegment(
                start=Vector((0, depth - wall_thickness, 0)),
                end=Vector((0, divider_y + wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((-1, 0, 0))
            )
            # Right wall (shortened in Y)
            right_wall = WallSegment(
                start=Vector((width, divider_y + wall_thickness, 0)),
                end=Vector((width, depth - wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((1, 0, 0))
            )
            walls = [back_wall, left_wall, right_wall]
            
        elif patio_side == 'LEFT':
            divider_x = width * patio_size
            # Right wall (full depth)
            right_wall = WallSegment(
                start=Vector((width, wall_thickness, 0)),
                end=Vector((width, depth - wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((1, 0, 0))
            )
            # Front wall (shortened in X)
            front_wall = WallSegment(
                start=Vector((divider_x + wall_thickness, 0, 0)),
                end=Vector((width, 0, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, -1, 0))
            )
            # Back wall (shortened in X)
            back_wall = WallSegment(
                start=Vector((width, depth, 0)),
                end=Vector((divider_x + wall_thickness, depth, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, 1, 0))
            )
            walls = [right_wall, front_wall, back_wall]
            
        else:  # RIGHT
            divider_x = width * (1 - patio_size)
            # Left wall (full depth)
            left_wall = WallSegment(
                start=Vector((0, depth - wall_thickness, 0)),
                end=Vector((0, wall_thickness, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((-1, 0, 0))
            )
            # Front wall (shortened in X)
            front_wall = WallSegment(
                start=Vector((0, 0, 0)),
                end=Vector((divider_x - wall_thickness, 0, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, -1, 0))
            )
            # Back wall (shortened in X)
            back_wall = WallSegment(
                start=Vector((divider_x - wall_thickness, depth, 0)),
                end=Vector((0, depth, 0)),
                height=floor_height,
                base_z=floor_base_z,
                normal=Vector((0, 1, 0))
            )
            walls = [left_wall, front_wall, back_wall]
        
        # Determine which sides should have windows
        window_sides = self.params.get('window_sides', 'ALL')
        has_front_windows = window_sides in ('ALL', 'FRONT_BACK', 'FRONT_SIDES', 'FRONT_ONLY', 'FRONT_LEFT', 'FRONT_RIGHT')
        has_back_windows = window_sides in ('ALL', 'FRONT_BACK', 'BACK_SIDES')
        has_left_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_LEFT', 'BACK_SIDES', 'SIDES_ONLY')
        has_right_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_RIGHT', 'BACK_SIDES', 'SIDES_ONLY')
        
        # Add windows to walls based on their direction
        for wall in walls:
            wall_normal = wall.normal
            is_front = wall_normal.y < -0.5
            is_back = wall_normal.y > 0.5
            is_left = wall_normal.x < -0.5
            is_right = wall_normal.x > 0.5
            
            should_add_windows = (
                (is_front and has_front_windows) or
                (is_back and has_back_windows) or
                (is_left and has_left_windows) or
                (is_right and has_right_windows)
            )
            
            if should_add_windows:
                # Fewer windows for side walls
                count = windows_per_floor if (is_front or is_back) else max(1, windows_per_floor // 2)
                self._add_windows_to_wall(wall, count, window_width, 
                                          window_height, window_spacing, sill_height)
        
        # Build all walls
        for wall in walls:
            build_wall_with_openings(self.bm, wall, wall_thickness, add_top_cap=add_top_caps)
    
    def _build_floor_walls(self, floor_idx: int, floor_base_z: float, floor_height: float,
                           width: float, depth: float, wall_thickness: float,
                           window_width: float, window_height: float, window_spacing: float,
                           sill_height: float, windows_per_floor: int, is_ground_floor: bool,
                           door_width: float, door_height: float, front_door_offset: float,
                           back_exit: bool, back_door_offset: float,
                           add_wall_caps: bool = False):
        """Build walls for a single floor with proper thickness."""
        
        # Define wall segments (exterior outline)
        # To prevent overlapping geometry at corners:
        # - Front and back walls span the full width (including corners)
        # - Left and right walls are shortened to fit between front/back walls
        
        # Front wall (Y = 0, facing -Y / outward) - full width
        front_wall = WallSegment(
            start=Vector((0, 0, 0)),
            end=Vector((width, 0, 0)),
            height=floor_height,
            base_z=floor_base_z,
            normal=Vector((0, -1, 0))  # Facing outward (-Y)
        )
        
        # Back wall (Y = depth, facing +Y / outward) - full width
        back_wall = WallSegment(
            start=Vector((width, depth, 0)),
            end=Vector((0, depth, 0)),
            height=floor_height,
            base_z=floor_base_z,
            normal=Vector((0, 1, 0))  # Facing outward (+Y)
        )
        
        # Left wall (X = 0, facing -X / outward) - shortened to avoid corner overlap
        # Starts after front wall thickness, ends before back wall thickness
        left_wall = WallSegment(
            start=Vector((0, depth - wall_thickness, 0)),
            end=Vector((0, wall_thickness, 0)),
            height=floor_height,
            base_z=floor_base_z,
            normal=Vector((-1, 0, 0))  # Facing outward (-X)
        )
        
        # Right wall (X = width, facing +X / outward) - shortened to avoid corner overlap
        right_wall = WallSegment(
            start=Vector((width, wall_thickness, 0)),
            end=Vector((width, depth - wall_thickness, 0)),
            height=floor_height,
            base_z=floor_base_z,
            normal=Vector((1, 0, 0))  # Facing outward (+X)
        )
        
        # Add doors on ground floor first (so windows can avoid them)
        if is_ground_floor:
            # Front door
            door_x = front_door_offset * (width - door_width)
            front_wall.add_opening(door_x, door_x + door_width, 0, door_height, 'door')
            
            # Back exit if enabled
            if back_exit:
                back_door_x = back_door_offset * (width - door_width)
                back_wall.add_opening(back_door_x, back_door_x + door_width, 0, door_height, 'door')
        
        # Determine which sides should have windows
        window_sides = self.params.get('window_sides', 'ALL')
        has_front_windows = window_sides in ('ALL', 'FRONT_BACK', 'FRONT_SIDES', 'FRONT_ONLY', 'FRONT_LEFT', 'FRONT_RIGHT')
        has_back_windows = window_sides in ('ALL', 'FRONT_BACK', 'BACK_SIDES')
        has_left_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_LEFT', 'BACK_SIDES', 'SIDES_ONLY')
        has_right_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_RIGHT', 'BACK_SIDES', 'SIDES_ONLY')
        
        # Add windows to front and back walls (avoiding doors)
        if has_front_windows:
            self._add_windows_to_wall(front_wall, windows_per_floor, window_width, 
                                       window_height, window_spacing, sill_height)
        if has_back_windows:
            self._add_windows_to_wall(back_wall, windows_per_floor, window_width,
                                       window_height, window_spacing, sill_height)
        
        # Add windows to side walls (fewer windows)
        side_windows = max(1, windows_per_floor // 2)
        if has_left_windows:
            self._add_windows_to_wall(left_wall, side_windows, window_width,
                                       window_height, window_spacing, sill_height)
        if has_right_windows:
            self._add_windows_to_wall(right_wall, side_windows, window_width,
                                       window_height, window_spacing, sill_height)
        
        # Build all walls with thickness
        for wall in [front_wall, back_wall, left_wall, right_wall]:
            build_wall_with_openings(self.bm, wall, wall_thickness, add_top_cap=add_wall_caps)
    
    def _add_windows_to_wall(self, wall: WallSegment, count: int, 
                              window_width: float, window_height: float,
                              spacing: float, sill_height: float):
        """Add evenly distributed windows across the full wall length."""
        wall_length = wall.length
        
        if count <= 0:
            return
        
        # Minimum margin from wall edges (for corners/pilasters)
        edge_margin = max(0.3, spacing * 0.5)
        
        # Available length for windows (excluding edge margins)
        available_length = wall_length - (2 * edge_margin)
        
        if available_length < window_width:
            return  # Wall too short for even one window
        
        # Calculate how many windows can fit
        # Each window needs: window_width + minimum_spacing (except last one)
        min_spacing = 0.3  # Minimum gap between windows
        max_windows = max(1, int((available_length + min_spacing) / (window_width + min_spacing)))
        count = min(count, max_windows)
        
        if count <= 0:
            return
        
        # Calculate even spacing:
        # total_window_width = count * window_width
        # remaining_space = available_length - total_window_width
        # This remaining space is divided into (count + 1) gaps (before first, between each, after last)
        total_window_width = count * window_width
        remaining_space = available_length - total_window_width
        
        if count == 1:
            # Single window: center it
            gap = remaining_space / 2
        else:
            # Multiple windows: distribute gaps evenly
            # We want equal gaps between windows and half-gaps at edges
            # So: half_gap + (count-1)*full_gap + half_gap = remaining_space
            # Which means: (count) * gap = remaining_space
            gap = remaining_space / (count + 1)
        
        z_start = sill_height
        z_end = sill_height + window_height
        
        # Make sure window fits within floor height
        if z_end > wall.height - 0.2:
            z_end = wall.height - 0.2
            if z_end <= z_start:
                return
        
        # Place windows evenly distributed
        for i in range(count):
            # Position: edge_margin + gap + i*(window_width + gap)
            x_start = edge_margin + gap + i * (window_width + gap)
            x_end = x_start + window_width
            
            # Check if this window overlaps with any existing opening (door)
            overlaps = False
            for existing in wall.openings:
                # Check horizontal overlap with some padding
                padding = 0.1
                if not (x_end + padding <= existing['x_start'] or x_start - padding >= existing['x_end']):
                    # Check vertical overlap
                    if not (z_end <= existing['z_start'] or z_start >= existing['z_end']):
                        overlaps = True
                        break
            
            if not overlaps:
                wall.add_opening(x_start, x_end, z_start, z_end, 'window')
