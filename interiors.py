# SPDX-License-Identifier: GPL-3.0-or-later
# Interior generation for Procedural Building Shell Generator
#
# Architectural Design Principles:
# 1. All floors must be accessible via stairs
# 2. Walls must have structural support (floor slab or wall below)
# 3. Stairs should not block windows or be blocked by walls
# 4. Interior walls connect to exterior walls at inside face
# 5. Every room needs at least one doorway
# 6. Stair zones are consistent across all floors (vertical alignment)

import bmesh
from mathutils import Vector
from . import util

# Material slot indices (matching mesh_builder)
MAT_WALLS = 0
MAT_FLOOR = 1
MAT_ROOF = 2
MAT_WINDOW_FRAME = 3
MAT_DOOR_FRAME = 4
MAT_INTERIOR_WALL = 5
MAT_STAIRS = 6
MAT_RUBBLE = 7


# =============================================================================
# Architectural Constants
# =============================================================================

# Standard dimensions (meters)
STAIR_WIDTH = 1.0           # Width of staircase
STAIR_DEPTH = 2.8           # Depth needed for a stair run
STAIR_LANDING = 1.0         # Landing depth at top/bottom
STAIR_ZONE_WIDTH = 1.2      # Total width including margins
STAIR_ZONE_DEPTH = 3.2      # Total depth including landing
MIN_ROOM_SIZE = 2.5         # Minimum room dimension for usability
MIN_ROOM_AREA = 6.0         # Minimum room area (sq meters)
MIN_WALL_OFFSET = 1.5       # Minimum distance of interior wall from exterior wall
DOOR_WIDTH = 0.9            # Standard interior door width
EXTERIOR_DOOR_WIDTH = 1.0   # Exterior door width
WALL_CLEARANCE = 0.3        # Minimum clearance from windows/doors for wall attachment


# =============================================================================
# Helper Functions
# =============================================================================

def get_interior_bounds(width: float, depth: float, wall_thickness: float) -> tuple:
    """
    Get the interior bounds of a building (inside the exterior walls).
    
    Returns:
        Tuple of (inner_x_min, inner_y_min, inner_x_max, inner_y_max)
    """
    return (
        wall_thickness,           # inner_x_min
        wall_thickness,           # inner_y_min
        width - wall_thickness,   # inner_x_max
        depth - wall_thickness    # inner_y_max
    )


def get_window_positions(width: float, depth: float, params: dict) -> dict:
    """
    Calculate window positions on each exterior wall.
    
    Returns:
        Dict with 'front', 'back', 'left', 'right' keys, each containing
        list of (start, end) tuples indicating window positions along that wall.
    """
    wall_thickness = params.get('wall_thickness', 0.25)
    window_width = params.get('window_width', 1.2)
    window_spacing = params.get('window_spacing', 0.8)
    windows_per_floor = params.get('windows_per_floor', 3)
    door_width = params.get('door_width', 1.2)
    front_door_offset = params.get('front_door_offset', 0.1)
    back_exit = params.get('back_exit', False)
    back_door_offset = params.get('back_door_offset', 0.5)
    
    # Determine which sides have windows
    window_sides = params.get('window_sides', 'ALL')
    has_front_windows = window_sides in ('ALL', 'FRONT_BACK', 'FRONT_SIDES', 'FRONT_ONLY', 'FRONT_LEFT', 'FRONT_RIGHT')
    has_back_windows = window_sides in ('ALL', 'FRONT_BACK', 'BACK_SIDES')
    has_left_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_LEFT', 'BACK_SIDES', 'SIDES_ONLY')
    has_right_windows = window_sides in ('ALL', 'FRONT_SIDES', 'FRONT_RIGHT', 'BACK_SIDES', 'SIDES_ONLY')
    
    positions = {
        'front': [],  # Along Y=0, positions are X coordinates
        'back': [],   # Along Y=depth, positions are X coordinates
        'left': [],   # Along X=0, positions are Y coordinates
        'right': []   # Along X=width, positions are Y coordinates
    }
    
    def calc_window_positions(wall_length: float, count: int) -> list:
        """Calculate evenly distributed window positions along a wall."""
        if count <= 0:
            return []
        
        edge_margin = max(0.3, window_spacing * 0.5)
        available_length = wall_length - (2 * edge_margin)
        
        if available_length < window_width:
            return []
        
        # Limit count based on available space
        min_spacing = 0.3
        max_windows = max(1, int((available_length + min_spacing) / (window_width + min_spacing)))
        count = min(count, max_windows)
        
        if count <= 0:
            return []
        
        # Calculate even spacing
        total_win_width = count * window_width
        remaining = available_length - total_win_width
        gap = remaining / (count + 1) if count >= 1 else remaining / 2
        
        result = []
        for i in range(count):
            x_start = edge_margin + gap + i * (window_width + gap)
            x_end = x_start + window_width
            result.append((x_start, x_end))
        
        return result
    
    # Calculate window positions for front/back walls (evenly distributed)
    if has_front_windows or has_back_windows:
        front_back_positions = calc_window_positions(width, windows_per_floor)
        if has_front_windows:
            positions['front'].extend(front_back_positions)
        if has_back_windows:
            positions['back'].extend(front_back_positions)
    
    # Add door positions (doors are always added regardless of window settings)
    door_x = front_door_offset * (width - door_width)
    positions['front'].append((door_x, door_x + door_width))
    
    if back_exit:
        back_door_x = back_door_offset * (width - door_width)
        positions['back'].append((back_door_x, back_door_x + door_width))
    
    # Side wall windows (fewer, evenly distributed)
    side_windows = max(1, windows_per_floor // 2)
    if has_left_windows or has_right_windows:
        side_positions = calc_window_positions(depth, side_windows)
        if has_left_windows:
            positions['left'].extend(side_positions)
        if has_right_windows:
            positions['right'].extend(side_positions)
    
    return positions


def is_position_blocked_by_opening(pos: float, wall: str, window_positions: dict) -> bool:
    """
    Check if a position on a wall is blocked by a window or door.
    
    Args:
        pos: Position along the wall (X for front/back, Y for left/right)
        wall: Which wall ('front', 'back', 'left', 'right')
        window_positions: Output from get_window_positions()
    
    Returns:
        True if position would block a window/door
    """
    openings = window_positions.get(wall, [])
    for start, end in openings:
        # Check if pos is within the opening (with clearance)
        if start - WALL_CLEARANCE <= pos <= end + WALL_CLEARANCE:
            return True
    return False


def find_safe_wall_attachment(target_pos: float, wall: str, window_positions: dict,
                               min_pos: float, max_pos: float) -> float:
    """
    Find a safe position to attach an interior wall that doesn't block openings.
    
    Args:
        target_pos: Desired position
        wall: Which exterior wall
        window_positions: Opening positions
        min_pos: Minimum allowed position
        max_pos: Maximum allowed position
    
    Returns:
        Safe position, or None if no safe position found
    """
    if not is_position_blocked_by_opening(target_pos, wall, window_positions):
        return target_pos
    
    openings = window_positions.get(wall, [])
    
    # Find gaps between openings where we can safely place walls
    safe_zones = []
    current_pos = min_pos
    
    sorted_openings = sorted(openings, key=lambda x: x[0])
    for start, end in sorted_openings:
        if current_pos < start - WALL_CLEARANCE:
            safe_zones.append((current_pos, start - WALL_CLEARANCE))
        current_pos = max(current_pos, end + WALL_CLEARANCE)
    
    if current_pos < max_pos:
        safe_zones.append((current_pos, max_pos))
    
    # Find the safe zone closest to target
    best_pos = None
    best_dist = float('inf')
    
    for zone_start, zone_end in safe_zones:
        # Check if target is in this zone
        if zone_start <= target_pos <= zone_end:
            return target_pos
        
        # Find closest edge of this zone
        for edge in [zone_start, zone_end]:
            dist = abs(edge - target_pos)
            if dist < best_dist:
                best_dist = dist
                best_pos = edge
    
    return best_pos


def validate_room_size(room_width: float, room_depth: float) -> bool:
    """
    Check if a room meets minimum size requirements.
    
    Args:
        room_width: Room width in meters
        room_depth: Room depth in meters
    
    Returns:
        True if room is large enough to be usable
    """
    # Check minimum dimensions
    if room_width < MIN_ROOM_SIZE or room_depth < MIN_ROOM_SIZE:
        return False
    
    # Check minimum area
    if room_width * room_depth < MIN_ROOM_AREA:
        return False
    
    return True


def validate_wall_placement(wall_pos: float, axis_min: float, axis_max: float,
                            interior_bounds: tuple) -> tuple:
    """
    Validate and adjust interior wall position to create usable rooms.
    
    Args:
        wall_pos: Proposed wall position
        axis_min: Minimum position on this axis (interior bound)
        axis_max: Maximum position on this axis (interior bound)
        interior_bounds: (ix_min, iy_min, ix_max, iy_max) interior bounds
    
    Returns:
        Tuple of (adjusted_pos, is_valid) where is_valid indicates if wall should be placed
    """
    axis_length = axis_max - axis_min
    
    # Room on either side of the wall must meet minimum size
    room1_size = wall_pos - axis_min
    room2_size = axis_max - wall_pos
    
    # If interior is too small for two rooms, don't place wall
    if axis_length < MIN_ROOM_SIZE * 2 + 0.5:  # Need space for 2 rooms + wall
        return wall_pos, False
    
    # Ensure wall isn't too close to exterior walls
    min_from_edge = max(MIN_WALL_OFFSET, MIN_ROOM_SIZE)
    
    if room1_size < min_from_edge:
        # Wall too close to min edge - move it
        wall_pos = axis_min + min_from_edge
        room1_size = min_from_edge
        room2_size = axis_max - wall_pos
    
    if room2_size < min_from_edge:
        # Wall too close to max edge - move it
        wall_pos = axis_max - min_from_edge
        room2_size = min_from_edge
        room1_size = wall_pos - axis_min
    
    # Final validation - both rooms must be usable
    if room1_size < MIN_ROOM_SIZE or room2_size < MIN_ROOM_SIZE:
        return wall_pos, False
    
    return wall_pos, True


def calculate_optimal_divider_position(axis_min: float, axis_max: float,
                                        target_ratio: float = 0.5,
                                        min_room_size: float = None) -> float:
    """
    Calculate optimal position for a divider wall.
    
    Args:
        axis_min: Start of available space
        axis_max: End of available space
        target_ratio: Desired ratio (0-1) for first room size
        min_room_size: Minimum room size (defaults to MIN_ROOM_SIZE)
    
    Returns:
        Optimal wall position, or None if space is too small
    """
    if min_room_size is None:
        min_room_size = MIN_ROOM_SIZE
    
    axis_length = axis_max - axis_min
    
    # Check if there's enough space for two rooms
    if axis_length < min_room_size * 2:
        return None
    
    # Calculate target position
    target_pos = axis_min + axis_length * target_ratio
    
    # Clamp to ensure both rooms meet minimum size
    min_pos = axis_min + min_room_size
    max_pos = axis_max - min_room_size
    
    return max(min_pos, min(max_pos, target_pos))


def is_wall_cardinal(wall_start: Vector, wall_end: Vector) -> bool:
    """Check if a wall runs in a cardinal direction (along X or Y axis)."""
    dx = abs(wall_end.x - wall_start.x)
    dy = abs(wall_end.y - wall_start.y)
    # Wall is cardinal if it's primarily along one axis (other axis movement < 1cm)
    return dx < 0.01 or dy < 0.01


def get_wall_direction(wall_start: Vector, wall_end: Vector) -> str:
    """Get the primary direction of a wall: 'x' (east-west) or 'y' (north-south)."""
    dx = abs(wall_end.x - wall_start.x)
    dy = abs(wall_end.y - wall_start.y)
    return 'x' if dx > dy else 'y'


def create_l_shaped_wall(corner: Vector, end_a: Vector, end_b: Vector,
                         height: float, thickness: float) -> list:
    """
    Create an L-shaped wall configuration as two separate cardinal wall segments.
    
    Args:
        corner: The corner point where both wall segments meet
        end_a: End point of first wall segment (must share X or Y with corner)
        end_b: End point of second wall segment (must share X or Y with corner)
        height: Wall height
        thickness: Wall thickness
    
    Returns:
        List of two wall definitions that form an L-shape
    """
    walls = []
    
    # First segment: corner to end_a
    walls.append({
        'start': corner.copy(),
        'end': end_a.copy(),
        'height': height,
        'thickness': thickness,
        'openings': []
    })
    
    # Second segment: corner to end_b
    walls.append({
        'start': corner.copy(),
        'end': end_b.copy(),
        'height': height,
        'thickness': thickness,
        'openings': []
    })
    
    return walls


def validate_and_adjust_cardinal_wall(wall_start: Vector, wall_end: Vector,
                                       width: float, depth: float,
                                       wall_thickness: float,
                                       window_positions: dict) -> tuple:
    """
    Validate a wall runs in cardinal direction and adjust endpoints if they block openings.
    
    Walls must run either:
    - Along X axis (constant Y) - east-west walls
    - Along Y axis (constant X) - north-south walls
    
    Non-cardinal (diagonal) walls are rejected.
    
    Returns:
        Tuple of (adjusted_start, adjusted_end) or (None, None) if wall can't be placed
    """
    dx = abs(wall_end.x - wall_start.x)
    dy = abs(wall_end.y - wall_start.y)
    
    # Check for truly diagonal walls (significant movement on both axes)
    if dx > 0.1 and dy > 0.1:
        # Wall is diagonal - reject it
        return None, None
    
    ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
    
    adjusted_start = wall_start.copy()
    adjusted_end = wall_end.copy()
    
    # Force wall to be perfectly cardinal
    if dx > dy:
        # Wall runs east-west (along X), Y should be constant
        wall_y = (wall_start.y + wall_end.y) / 2  # Average Y to straighten
        adjusted_start.y = wall_y
        adjusted_end.y = wall_y
        
        # Check if start.x touches left exterior wall
        if abs(wall_start.x - ix_min) < 0.01:
            if is_position_blocked_by_opening(wall_y, 'left', window_positions):
                # Can't attach to exterior wall here - skip this wall
                return None, None
        
        # Check if end.x touches right exterior wall
        if abs(wall_end.x - ix_max) < 0.01:
            if is_position_blocked_by_opening(wall_y, 'right', window_positions):
                return None, None
        
    else:
        # Wall runs north-south (along Y), X should be constant
        wall_x = (wall_start.x + wall_end.x) / 2  # Average X to straighten
        adjusted_start.x = wall_x
        adjusted_end.x = wall_x
        
        # Check if start.y touches front exterior wall
        if abs(wall_start.y - iy_min) < 0.01:
            if is_position_blocked_by_opening(wall_x, 'front', window_positions):
                return None, None
        
        # Check if end.y touches back exterior wall
        if abs(wall_end.y - iy_max) < 0.01:
            if is_position_blocked_by_opening(wall_x, 'back', window_positions):
                return None, None
    
    return adjusted_start, adjusted_end


def get_stair_zone(width: float, depth: float, wall_thickness: float, 
                   position: str = 'back_right') -> dict:
    """
    Calculate the stair zone - a reserved area for stairs that is consistent across all floors.
    
    Args:
        width: Building width
        depth: Building depth
        wall_thickness: Exterior wall thickness
        position: Where to place stairs ('back_right', 'back_left', 'back_center', 'front_right', etc.)
    
    Returns:
        Dict with 'x_min', 'y_min', 'x_max', 'y_max' defining the stair zone
    """
    ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
    interior_width = ix_max - ix_min
    interior_depth = iy_max - iy_min
    
    # Default stair zone dimensions
    zone_width = min(STAIR_ZONE_WIDTH, interior_width * 0.25)
    zone_depth = min(STAIR_ZONE_DEPTH, interior_depth * 0.4)
    
    # Minimum margin from walls to ensure floor slab extends to all walls
    wall_margin = 0.3
    
    # Position the stair zone (with margin from walls)
    if 'right' in position:
        x_max = ix_max - wall_margin
        x_min = x_max - zone_width
    elif 'left' in position:
        x_min = ix_min + wall_margin
        x_max = x_min + zone_width
    else:  # center
        x_min = ix_min + (interior_width - zone_width) / 2
        x_max = x_min + zone_width
    
    if 'front' in position:
        y_min = iy_min + wall_margin
        y_max = y_min + zone_depth
    else:  # back (default)
        y_max = iy_max - wall_margin
        y_min = y_max - zone_depth
    
    return {
        'x_min': x_min,
        'y_min': y_min,
        'x_max': x_max,
        'y_max': y_max
    }


def get_floor_opening(width: float, depth: float, wall_thickness: float,
                      stair_position: str = 'back_right') -> dict:
    """
    Get the floor slab opening for stair access. This is used for ALL multi-floor buildings.
    
    Returns:
        Dict with 'x_min', 'y_min', 'x_max', 'y_max' for the opening
    """
    stair_zone = get_stair_zone(width, depth, wall_thickness, stair_position)
    
    # Opening is slightly smaller than stair zone (allow for framing)
    margin = 0.1
    return {
        'x_min': stair_zone['x_min'] + margin,
        'y_min': stair_zone['y_min'] + margin,
        'x_max': stair_zone['x_max'] - margin,
        'y_max': stair_zone['y_max'] - margin
    }


def walls_overlap_zone(wall_start: Vector, wall_end: Vector, zone: dict) -> bool:
    """Check if a wall segment would pass through a zone (like stair zone)."""
    # Get wall bounding box
    wall_x_min = min(wall_start.x, wall_end.x)
    wall_x_max = max(wall_start.x, wall_end.x)
    wall_y_min = min(wall_start.y, wall_end.y)
    wall_y_max = max(wall_start.y, wall_end.y)
    
    # Check for overlap
    x_overlap = wall_x_min < zone['x_max'] and wall_x_max > zone['x_min']
    y_overlap = wall_y_min < zone['y_max'] and wall_y_max > zone['y_min']
    
    return x_overlap and y_overlap


def adjust_wall_for_stair_zone(wall_def: dict, stair_zone: dict) -> list:
    """
    Adjust a wall definition to avoid the stair zone.
    Returns a list of wall segments (may split the wall or shorten it).
    """
    start = wall_def['start']
    end = wall_def['end']
    
    if not walls_overlap_zone(start, end, stair_zone):
        return [wall_def]
    
    # Wall overlaps stair zone - need to split or shorten
    walls = []
    
    # Determine if wall is primarily horizontal (along X) or vertical (along Y)
    is_horizontal = abs(end.x - start.x) > abs(end.y - start.y)
    
    if is_horizontal:
        # Wall runs along X axis at some Y position
        wall_y = start.y
        # Check if wall Y is within stair zone Y range
        if stair_zone['y_min'] <= wall_y <= stair_zone['y_max']:
            # Need to split wall around stair zone
            if start.x < stair_zone['x_min']:
                # Left portion
                new_wall = wall_def.copy()
                new_wall['start'] = start.copy()
                new_wall['end'] = Vector((stair_zone['x_min'], wall_y, 0))
                if (new_wall['end'] - new_wall['start']).length > 0.3:
                    walls.append(new_wall)
            
            if end.x > stair_zone['x_max']:
                # Right portion
                new_wall = wall_def.copy()
                new_wall['start'] = Vector((stair_zone['x_max'], wall_y, 0))
                new_wall['end'] = end.copy()
                if (new_wall['end'] - new_wall['start']).length > 0.3:
                    walls.append(new_wall)
        else:
            walls.append(wall_def)
    else:
        # Wall runs along Y axis at some X position
        wall_x = start.x
        if stair_zone['x_min'] <= wall_x <= stair_zone['x_max']:
            # Need to split wall around stair zone
            if start.y < stair_zone['y_min']:
                new_wall = wall_def.copy()
                new_wall['start'] = start.copy()
                new_wall['end'] = Vector((wall_x, stair_zone['y_min'], 0))
                if (new_wall['end'] - new_wall['start']).length > 0.3:
                    walls.append(new_wall)
            
            if end.y > stair_zone['y_max']:
                new_wall = wall_def.copy()
                new_wall['start'] = Vector((wall_x, stair_zone['y_max'], 0))
                new_wall['end'] = end.copy()
                if (new_wall['end'] - new_wall['start']).length > 0.3:
                    walls.append(new_wall)
        else:
            walls.append(wall_def)
    
    return walls if walls else []


# =============================================================================
# Building Profiles
# =============================================================================

class BuildingProfile:
    """Base class for building profiles that define interior layouts."""
    
    name = "generic"
    description = "Generic building with no specific layout"
    stair_position = "back_right"  # Default stair position
    
    @classmethod
    def get_stair_zone(cls, width: float, depth: float, params: dict) -> dict:
        """Get the stair zone for this profile."""
        wall_thickness = params.get('wall_thickness', 0.25)
        return get_stair_zone(width, depth, wall_thickness, cls.stair_position)
    
    @classmethod
    def get_floor_opening(cls, width: float, depth: float, params: dict) -> dict:
        """Get the floor opening for stair access."""
        wall_thickness = params.get('wall_thickness', 0.25)
        return get_floor_opening(width, depth, wall_thickness, cls.stair_position)
    
    @classmethod
    def get_ground_floor_layout(cls, width: float, depth: float, params: dict) -> dict:
        """Define the ground floor room layout."""
        return {'rooms': [], 'walls': [], 'exterior_door': None}
    
    @classmethod
    def get_upper_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        """Define upper floor room layouts."""
        return {'rooms': [], 'walls': []}
    
    @classmethod
    def needs_exterior_stair_door(cls, params: dict) -> bool:
        """Check if building needs an exterior door for external stair access."""
        return params.get('exterior_stairs', False)
    
    @classmethod
    def get_exterior_stair_door(cls, width: float, depth: float, params: dict) -> dict:
        """
        Get exterior door position for external stair access.
        This is just a door on the exterior wall - external stairs are not generated.
        
        Returns:
            Dict with 'wall' ('front', 'back', 'left', 'right'), 'position' (0-1 along wall), 
            'width', 'height'
        """
        # Default: door on back wall, right side
        return {
            'wall': 'back',
            'position': 0.8,  # 80% along the wall from left
            'width': EXTERIOR_DOOR_WIDTH,
            'height': 2.4
        }


class StorefrontProfile(BuildingProfile):
    """
    Storefront building profile.
    Ground floor: Large open retail front + back storage room
    Upper floors: Residential-style rooms
    Stairs: In back room corner
    """
    
    name = "storefront"
    description = "Retail storefront with back room, residential above"
    stair_position = "back_right"
    
    @classmethod
    def get_ground_floor_layout(cls, width: float, depth: float, params: dict) -> dict:
        """Large front retail space with back room containing stairs."""
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        floors = params.get('floors', 1)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        interior_depth = iy_max - iy_min
        
        rooms = []
        walls = []
        
        # Check if interior is large enough for subdivision
        if not validate_room_size(interior_width, interior_depth):
            # Too small - just one open room
            rooms = [{'name': 'open_retail', 'bounds': (ix_min, iy_min, ix_max, iy_max), 'type': 'retail'}]
            exterior_door = cls.get_exterior_stair_door(width, depth, params) if cls.needs_exterior_stair_door(params) else None
            return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
        
        # Get stair zone to work around
        stair_zone = cls.get_stair_zone(width, depth, params) if floors > 1 else None
        
        # Calculate back room depth with validation
        target_back_depth = interior_depth * 0.35 if floors > 1 else interior_depth * 0.25
        if floors > 1:
            target_back_depth = max(target_back_depth, STAIR_ZONE_DEPTH + 1.0)
        
        # Use optimal divider calculation to ensure usable rooms
        divider_y = calculate_optimal_divider_position(iy_min, iy_max, 1.0 - (target_back_depth / interior_depth))
        
        # If no valid divider position, skip interior walls
        if divider_y is None:
            rooms = [{'name': 'open_retail', 'bounds': (ix_min, iy_min, ix_max, iy_max), 'type': 'retail'}]
            exterior_door = cls.get_exterior_stair_door(width, depth, params) if cls.needs_exterior_stair_door(params) else None
            return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
        
        # Validate both resulting rooms
        front_room_depth = divider_y - iy_min
        back_room_depth = iy_max - divider_y
        
        if not validate_room_size(interior_width, front_room_depth) or not validate_room_size(interior_width, back_room_depth):
            # Rooms too small - skip divider
            rooms = [{'name': 'open_retail', 'bounds': (ix_min, iy_min, ix_max, iy_max), 'type': 'retail'}]
            exterior_door = cls.get_exterior_stair_door(width, depth, params) if cls.needs_exterior_stair_door(params) else None
            return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
        
        rooms = [
            {'name': 'retail_front', 'bounds': (ix_min, iy_min, ix_max, divider_y), 'type': 'retail'},
            {'name': 'back_room', 'bounds': (ix_min, divider_y, ix_max, iy_max), 'type': 'storage'}
        ]
        
        # Divider wall with doorway (avoid stair zone)
        door_width = DOOR_WIDTH
        door_x = ix_min + interior_width * 0.3  # Door on left side, away from stairs
        
        # Left portion of divider wall
        if door_x > ix_min + MIN_WALL_OFFSET:
            walls.append({
                'start': Vector((ix_min, divider_y, 0)),
                'end': Vector((door_x, divider_y, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            })
        
        # Right portion of divider wall (may need to avoid stair zone)
        right_wall = {
            'start': Vector((door_x + door_width, divider_y, 0)),
            'end': Vector((ix_max, divider_y, 0)),
            'height': floor_height,
            'thickness': wall_thickness,
            'openings': []
        }
        
        if stair_zone:
            adjusted = adjust_wall_for_stair_zone(right_wall, stair_zone)
            walls.extend(adjusted)
        else:
            walls.append(right_wall)
        
        # Exterior door for external stairs if needed
        exterior_door = None
        if cls.needs_exterior_stair_door(params):
            exterior_door = cls.get_exterior_stair_door(width, depth, params)
        
        return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
    
    @classmethod
    def get_upper_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        """Upper floors with rooms arranged around stair zone."""
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        interior_depth = iy_max - iy_min
        stair_zone = cls.get_stair_zone(width, depth, params)
        
        rooms = []
        walls = []
        
        # Check if space is large enough for subdivision
        if not validate_room_size(interior_width, interior_depth):
            return {'rooms': rooms, 'walls': walls}
        
        # Simple layout: living area on left, bedroom/stair area on right
        # Only subdivide if width allows for two usable rooms
        if interior_width > MIN_ROOM_SIZE * 2 + 1.0:
            # Calculate divider position with validation
            # Position to give stair zone its own area, but ensure usable room sizes
            target_ratio = 0.6 if stair_zone['x_min'] > ix_min + MIN_ROOM_SIZE else 0.5
            divider_x = calculate_optimal_divider_position(ix_min, ix_max, target_ratio)
            
            if divider_x is None:
                return {'rooms': rooms, 'walls': walls}
            
            # Validate both resulting rooms
            left_room_width = divider_x - ix_min
            right_room_width = ix_max - divider_x
            
            if not validate_room_size(left_room_width, interior_depth) or \
               not validate_room_size(right_room_width, interior_depth):
                return {'rooms': rooms, 'walls': walls}
            
            rooms = [
                {'name': f'living_{floor_idx}', 'bounds': (ix_min, iy_min, divider_x, iy_max), 'type': 'living'},
                {'name': f'bedroom_{floor_idx}', 'bounds': (divider_x, iy_min, ix_max, iy_max), 'type': 'bedroom'}
            ]
            
            # Divider wall with door (positioned away from stair zone)
            door_y = iy_min + interior_depth * 0.4
            
            # Ensure door position creates usable wall segments
            if door_y - iy_min < MIN_WALL_OFFSET:
                door_y = iy_min + MIN_WALL_OFFSET
            if iy_max - (door_y + DOOR_WIDTH) < MIN_WALL_OFFSET:
                door_y = iy_max - DOOR_WIDTH - MIN_WALL_OFFSET
            
            # Wall segments avoiding stair zone
            wall_bottom = {
                'start': Vector((divider_x, iy_min, 0)),
                'end': Vector((divider_x, door_y, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            }
            
            wall_top = {
                'start': Vector((divider_x, door_y + DOOR_WIDTH, 0)),
                'end': Vector((divider_x, iy_max, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            }
            
            for wall in [wall_bottom, wall_top]:
                adjusted = adjust_wall_for_stair_zone(wall, stair_zone)
                walls.extend(adjusted)
        
        return {'rooms': rooms, 'walls': walls}


class WarehouseProfile(BuildingProfile):
    """
    Warehouse building profile.
    Large open floor plan with optional office corner.
    Stairs: Against back wall
    """
    
    name = "warehouse"
    description = "Large open warehouse with optional office"
    stair_position = "back_left"
    
    @classmethod
    def get_ground_floor_layout(cls, width: float, depth: float, params: dict) -> dict:
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        floors = params.get('floors', 1)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        interior_depth = iy_max - iy_min
        
        stair_zone = cls.get_stair_zone(width, depth, params) if floors > 1 else None
        
        rooms = []
        walls = []
        
        # Office in front-left corner if space permits (away from stairs in back-left)
        # Require minimum space for both office and remaining warehouse
        min_office_size = max(MIN_ROOM_SIZE, 2.5)
        remaining_width = interior_width - min_office_size
        remaining_depth = interior_depth - min_office_size
        
        if interior_width > min_office_size * 2 + 1.0 and interior_depth > min_office_size * 2 + 1.0 and \
           validate_room_size(remaining_width, interior_depth):
            office_width = max(min_office_size, min(3.5, interior_width * 0.3))
            office_depth = max(min_office_size, min(3.5, interior_depth * 0.3))
            
            office_x_max = ix_min + office_width
            office_y_max = iy_min + office_depth
            
            rooms = [
                {'name': 'warehouse_floor', 'bounds': (office_x_max, iy_min, ix_max, iy_max), 'type': 'warehouse'},
                {'name': 'office', 'bounds': (ix_min, iy_min, office_x_max, office_y_max), 'type': 'office'}
            ]
            
            # L-shaped office walls with door
            walls.append({
                'start': Vector((office_x_max, iy_min, 0)),
                'end': Vector((office_x_max, office_y_max - DOOR_WIDTH, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            })
            walls.append({
                'start': Vector((ix_min, office_y_max, 0)),
                'end': Vector((office_x_max, office_y_max, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            })
        else:
            rooms = [{'name': 'warehouse_floor', 'bounds': (ix_min, iy_min, ix_max, iy_max), 'type': 'warehouse'}]
        
        exterior_door = cls.get_exterior_stair_door(width, depth, params) if cls.needs_exterior_stair_door(params) else None
        
        return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
    
    @classmethod
    def get_upper_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        """Upper floors are open storage with stair access."""
        return {'rooms': [], 'walls': []}
    
    @classmethod
    def get_exterior_stair_door(cls, width: float, depth: float, params: dict) -> dict:
        # Warehouse: door on left side wall
        return {
            'wall': 'left',
            'position': 0.7,
            'width': EXTERIOR_DOOR_WIDTH,
            'height': 2.4
        }


class ResidentialProfile(BuildingProfile):
    """
    Residential apartment building profile.
    Central hallway with rooms on both sides.
    Stairs: At end of hallway
    """
    
    name = "residential"
    description = "Apartment building with rooms and hallway"
    stair_position = "back_center"
    hallway_width = 1.4
    
    @classmethod
    def get_ground_floor_layout(cls, width: float, depth: float, params: dict) -> dict:
        return cls._generate_floor_layout(width, depth, 0, params)
    
    @classmethod
    def get_upper_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        return cls._generate_floor_layout(width, depth, floor_idx, params)
    
    @classmethod
    def _generate_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        floors = params.get('floors', 1)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        interior_depth = iy_max - iy_min
        
        stair_zone = cls.get_stair_zone(width, depth, params) if floors > 1 else None
        
        rooms = []
        walls = []
        
        # Check if there's enough space for hallway + rooms on both sides
        min_room_width = MIN_ROOM_SIZE
        min_hallway_depth = MIN_ROOM_SIZE
        required_width = min_room_width * 2 + cls.hallway_width
        
        if interior_width < required_width or interior_depth < min_hallway_depth:
            # Too small for residential layout - return empty
            return {'rooms': rooms, 'walls': walls}
        
        # Central hallway - ensure rooms on sides are large enough
        room_width_each_side = (interior_width - cls.hallway_width) / 2
        
        # If rooms would be too narrow, widen hallway or skip layout
        if room_width_each_side < MIN_ROOM_SIZE:
            return {'rooms': rooms, 'walls': walls}
        
        hallway_x_left = ix_min + room_width_each_side
        hallway_x_right = hallway_x_left + cls.hallway_width
        
        # Hallway runs from front to stair zone at back
        hallway_y_max = stair_zone['y_min'] if stair_zone else iy_max
        hallway_depth = hallway_y_max - iy_min
        
        # Validate hallway length
        if hallway_depth < MIN_ROOM_SIZE:
            return {'rooms': rooms, 'walls': walls}
        
        rooms.append({
            'name': f'hallway_{floor_idx}',
            'bounds': (hallway_x_left, iy_min, hallway_x_right, hallway_y_max),
            'type': 'hallway'
        })
        
        # Calculate room depth - aim for 2 rooms per side if space permits
        # Each room must be at least MIN_ROOM_SIZE deep
        num_rooms = max(1, int(hallway_depth / MIN_ROOM_SIZE))
        num_rooms = min(num_rooms, 2)  # Max 2 rooms per side
        room_depth = hallway_depth / num_rooms
        
        # Only create rooms if they meet minimum size
        if not validate_room_size(room_width_each_side, room_depth):
            num_rooms = 1
            room_depth = hallway_depth
        
        # Rooms on left side of hallway
        for i in range(num_rooms):
            y_start = iy_min + i * room_depth
            y_end = y_start + room_depth
            if y_end <= hallway_y_max + 0.01 and validate_room_size(room_width_each_side, room_depth):
                rooms.append({
                    'name': f'apt_L{i}_{floor_idx}',
                    'bounds': (ix_min, y_start, hallway_x_left, y_end),
                    'type': 'apartment'
                })
        
        # Rooms on right side of hallway
        for i in range(num_rooms):
            y_start = iy_min + i * room_depth
            y_end = y_start + room_depth
            if y_end <= hallway_y_max + 0.01 and validate_room_size(room_width_each_side, room_depth):
                rooms.append({
                    'name': f'apt_R{i}_{floor_idx}',
                    'bounds': (hallway_x_right, y_start, ix_max, y_end),
                    'type': 'apartment'
                })
        
        # Hallway walls with doors to apartments
        for i in range(num_rooms):
            y_start = iy_min + i * room_depth
            y_end = min(y_start + room_depth, hallway_y_max)
            door_y = y_start + (y_end - y_start) * 0.5 - DOOR_WIDTH / 2
            
            # Ensure wall segments are long enough (at least MIN_WALL_OFFSET)
            wall_before_door = door_y - y_start
            wall_after_door = y_end - (door_y + DOOR_WIDTH)
            
            # Left wall segments
            if wall_before_door > MIN_WALL_OFFSET:
                walls.append({
                    'start': Vector((hallway_x_left, y_start, 0)),
                    'end': Vector((hallway_x_left, door_y, 0)),
                    'height': floor_height,
                    'thickness': wall_thickness,
                    'openings': []
                })
            if wall_after_door > MIN_WALL_OFFSET:
                walls.append({
                    'start': Vector((hallway_x_left, door_y + DOOR_WIDTH, 0)),
                    'end': Vector((hallway_x_left, y_end, 0)),
                    'height': floor_height,
                    'thickness': wall_thickness,
                    'openings': []
                })
            
            # Right wall segments
            if wall_before_door > MIN_WALL_OFFSET:
                walls.append({
                    'start': Vector((hallway_x_right, y_start, 0)),
                    'end': Vector((hallway_x_right, door_y, 0)),
                    'height': floor_height,
                    'thickness': wall_thickness,
                    'openings': []
                })
            if wall_after_door > MIN_WALL_OFFSET:
                walls.append({
                    'start': Vector((hallway_x_right, door_y + DOOR_WIDTH, 0)),
                    'end': Vector((hallway_x_right, y_end, 0)),
                    'height': floor_height,
                    'thickness': wall_thickness,
                    'openings': []
                })
        
        # Cross walls between apartments (only if multiple rooms)
        if num_rooms > 1:
            mid_y = iy_min + room_depth
            if mid_y < hallway_y_max - MIN_WALL_OFFSET:
                # Left side cross wall - ensure it's not too close to hallway
                left_wall_length = hallway_x_left - ix_min - DOOR_WIDTH
                if left_wall_length > MIN_WALL_OFFSET:
                    walls.append({
                        'start': Vector((ix_min, mid_y, 0)),
                        'end': Vector((hallway_x_left - DOOR_WIDTH, mid_y, 0)),
                        'height': floor_height,
                        'thickness': wall_thickness,
                        'openings': []
                    })
                
                # Right side cross wall
                right_wall_length = ix_max - hallway_x_right - DOOR_WIDTH
                if right_wall_length > MIN_WALL_OFFSET:
                    walls.append({
                        'start': Vector((hallway_x_right + DOOR_WIDTH, mid_y, 0)),
                        'end': Vector((ix_max, mid_y, 0)),
                        'height': floor_height,
                        'thickness': wall_thickness,
                        'openings': []
                    })
        
        exterior_door = None
        if floor_idx == 0 and cls.needs_exterior_stair_door(params):
            exterior_door = cls.get_exterior_stair_door(width, depth, params)
        
        return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
    
    @classmethod
    def get_exterior_stair_door(cls, width: float, depth: float, params: dict) -> dict:
        return {
            'wall': 'back',
            'position': 0.5,  # Center of back wall
            'width': EXTERIOR_DOOR_WIDTH,
            'height': 2.4
        }


class BarProfile(BuildingProfile):
    """
    Bar/Entertainment venue profile.
    Multiple connected rooms: seating, bar area, back rooms.
    Stairs: In back corner
    """
    
    name = "bar"
    description = "Bar/entertainment with multiple connected rooms"
    stair_position = "back_left"
    
    @classmethod
    def get_ground_floor_layout(cls, width: float, depth: float, params: dict) -> dict:
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        floors = params.get('floors', 1)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        interior_depth = iy_max - iy_min
        
        stair_zone = cls.get_stair_zone(width, depth, params) if floors > 1 else None
        
        # Layout: Seating (50%), Bar+Back (50%)
        bar_y = iy_min + interior_depth * 0.5
        
        # Back room for stairs if multi-floor
        back_room_x = stair_zone['x_max'] + 0.5 if stair_zone else ix_min + interior_width * 0.3
        
        rooms = [
            {'name': 'seating', 'bounds': (ix_min, iy_min, ix_max, bar_y), 'type': 'seating'},
            {'name': 'bar_area', 'bounds': (back_room_x, bar_y, ix_max, iy_max), 'type': 'bar'},
        ]
        
        if stair_zone:
            rooms.append({'name': 'back_room', 'bounds': (ix_min, bar_y, back_room_x, iy_max), 'type': 'storage'})
        
        walls = []
        
        # Partial wall between seating and bar (large opening in center)
        opening_width = interior_width * 0.5
        opening_start = ix_min + (interior_width - opening_width) / 2
        
        if opening_start > ix_min + 0.3:
            walls.append({
                'start': Vector((ix_min, bar_y, 0)),
                'end': Vector((opening_start, bar_y, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            })
        
        if opening_start + opening_width < ix_max - 0.3:
            walls.append({
                'start': Vector((opening_start + opening_width, bar_y, 0)),
                'end': Vector((ix_max, bar_y, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            })
        
        # Wall between bar and back room (with door)
        if stair_zone:
            wall_def = {
                'start': Vector((back_room_x, bar_y + DOOR_WIDTH, 0)),
                'end': Vector((back_room_x, iy_max, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            }
            adjusted = adjust_wall_for_stair_zone(wall_def, stair_zone)
            walls.extend(adjusted)
        
        exterior_door = cls.get_exterior_stair_door(width, depth, params) if cls.needs_exterior_stair_door(params) else None
        
        return {'rooms': rooms, 'walls': walls, 'exterior_door': exterior_door}
    
    @classmethod
    def get_upper_floor_layout(cls, width: float, depth: float, floor_idx: int, params: dict) -> dict:
        wall_thickness = params.get('wall_thickness', 0.25)
        floor_height = params.get('floor_height', 3.5)
        
        ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
        interior_width = ix_max - ix_min
        stair_zone = cls.get_stair_zone(width, depth, params)
        
        rooms = []
        walls = []
        
        # VIP rooms on upper floor
        if interior_width > 4.0:
            mid_x = ix_min + interior_width / 2
            rooms = [
                {'name': f'vip_left_{floor_idx}', 'bounds': (ix_min, iy_min, mid_x, iy_max), 'type': 'vip'},
                {'name': f'vip_right_{floor_idx}', 'bounds': (mid_x, iy_min, ix_max, iy_max), 'type': 'vip'}
            ]
            
            # Divider with door (positioned away from stairs)
            door_y = iy_min + 1.5
            
            wall_def = {
                'start': Vector((mid_x, iy_min, 0)),
                'end': Vector((mid_x, door_y, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            }
            adjusted = adjust_wall_for_stair_zone(wall_def, stair_zone)
            walls.extend(adjusted)
            
            wall_def2 = {
                'start': Vector((mid_x, door_y + DOOR_WIDTH, 0)),
                'end': Vector((mid_x, iy_max, 0)),
                'height': floor_height,
                'thickness': wall_thickness,
                'openings': []
            }
            adjusted2 = adjust_wall_for_stair_zone(wall_def2, stair_zone)
            walls.extend(adjusted2)
        
        return {'rooms': rooms, 'walls': walls}
    
    @classmethod
    def get_exterior_stair_door(cls, width: float, depth: float, params: dict) -> dict:
        return {
            'wall': 'back',
            'position': 0.2,  # Left side of back wall
            'width': EXTERIOR_DOOR_WIDTH,
            'height': 2.4
        }


# Profile registry
BUILDING_PROFILES = {
    'NONE': BuildingProfile,
    'STOREFRONT': StorefrontProfile,
    'WAREHOUSE': WarehouseProfile,
    'RESIDENTIAL': ResidentialProfile,
    'BAR': BarProfile,
}


# =============================================================================
# Interior Geometry Generation
# =============================================================================

def build_interior_wall(bm: bmesh.types.BMesh, wall_def: dict, base_z: float) -> list:
    """
    Build an interior wall segment.
    
    Walls are forced to be cardinal (along X or Y axis only).
    """
    faces = []
    
    start = wall_def['start'].copy()
    end = wall_def['end'].copy()
    height = wall_def['height']
    thickness = wall_def['thickness']
    
    # Skip very short walls
    if (end - start).length < 0.2:
        return faces
    
    # Force wall to be cardinal - determine primary direction
    dx = abs(end.x - start.x)
    dy = abs(end.y - start.y)
    half_thickness = thickness / 2
    
    # Track wall direction for correct face winding
    is_x_axis_wall = dx > dy
    
    if is_x_axis_wall:
        # Wall runs east-west (along X axis)
        # Force both endpoints to same Y value
        avg_y = (start.y + end.y) / 2
        start.y = avg_y
        end.y = avg_y
        # Normal points in Y direction
        offset = Vector((0, half_thickness, 0))
    else:
        # Wall runs north-south (along Y axis)
        # Force both endpoints to same X value
        avg_x = (start.x + end.x) / 2
        start.x = avg_x
        end.x = avg_x
        # Normal points in X direction
        offset = Vector((half_thickness, 0, 0))
    
    # Create wall box vertices
    # v0-v3: -offset side, v4-v7: +offset side
    v0 = bm.verts.new(start - offset + Vector((0, 0, base_z)))
    v1 = bm.verts.new(end - offset + Vector((0, 0, base_z)))
    v2 = bm.verts.new(end - offset + Vector((0, 0, base_z + height)))
    v3 = bm.verts.new(start - offset + Vector((0, 0, base_z + height)))
    
    v4 = bm.verts.new(start + offset + Vector((0, 0, base_z)))
    v5 = bm.verts.new(end + offset + Vector((0, 0, base_z)))
    v6 = bm.verts.new(end + offset + Vector((0, 0, base_z + height)))
    v7 = bm.verts.new(start + offset + Vector((0, 0, base_z + height)))
    
    # Face winding depends on wall direction
    # For X-axis walls: -offset side is at -Y, so front face should point -Y
    # For Y-axis walls: -offset side is at -X, so front face should point -X
    # The winding [v0, v1, v2, v3] gives -Y normal for X-axis walls but +X for Y-axis walls
    # So Y-axis walls need reversed winding
    
    if is_x_axis_wall:
        # Front face (points -Y)
        f = bm.faces.new([v0, v1, v2, v3])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Back face (points +Y)
        f = bm.faces.new([v5, v4, v7, v6])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Top cap (points +Z)
        f = bm.faces.new([v3, v2, v6, v7])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Start end cap (points -X)
        f = bm.faces.new([v4, v0, v3, v7])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # End end cap (points +X)
        f = bm.faces.new([v1, v5, v6, v2])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Bottom cap (points -Z)
        f = bm.faces.new([v0, v4, v5, v1])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
    else:
        # Y-axis wall - all faces need adjusted winding
        
        # Front face (points -X)
        f = bm.faces.new([v0, v3, v2, v1])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Back face (points +X)
        f = bm.faces.new([v5, v6, v7, v4])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Top cap (points +Z) - adjusted winding
        f = bm.faces.new([v3, v7, v6, v2])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Start end cap (points -Y) - adjusted winding
        f = bm.faces.new([v4, v7, v3, v0])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # End end cap (points +Y) - adjusted winding
        f = bm.faces.new([v1, v2, v6, v5])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
        
        # Bottom cap (points -Z) - adjusted winding
        f = bm.faces.new([v0, v1, v5, v4])
        f.material_index = MAT_INTERIOR_WALL
        faces.append(f)
    
    return faces


def build_interior_stairs(bm: bmesh.types.BMesh, stair_zone: dict, floor_height: float,
                          base_z: float) -> list:
    """
    Build interior stairs within the designated stair zone.
    Stairs go from base_z to base_z + floor_height.
    """
    faces = []
    
    x_min = stair_zone['x_min']
    y_min = stair_zone['y_min']
    x_max = stair_zone['x_max']
    y_max = stair_zone['y_max']
    
    stair_width = x_max - x_min
    stair_depth = y_max - y_min - STAIR_LANDING  # Reserve space for landing
    
    num_steps = max(1, int(floor_height / 0.2))
    step_height = floor_height / num_steps
    step_depth = stair_depth / num_steps
    step_thickness = 0.12
    
    # Build each step as a solid box
    for i in range(num_steps):
        step_top_z = base_z + (i + 1) * step_height
        step_bottom_z = step_top_z - step_thickness
        step_y = y_min + i * step_depth
        
        # Step vertices
        t0 = bm.verts.new(Vector((x_min, step_y, step_top_z)))
        t1 = bm.verts.new(Vector((x_max, step_y, step_top_z)))
        t2 = bm.verts.new(Vector((x_max, step_y + step_depth, step_top_z)))
        t3 = bm.verts.new(Vector((x_min, step_y + step_depth, step_top_z)))
        
        b0 = bm.verts.new(Vector((x_min, step_y, step_bottom_z)))
        b1 = bm.verts.new(Vector((x_max, step_y, step_bottom_z)))
        b2 = bm.verts.new(Vector((x_max, step_y + step_depth, step_bottom_z)))
        b3 = bm.verts.new(Vector((x_min, step_y + step_depth, step_bottom_z)))
        
        # Create all 6 faces
        f = bm.faces.new([t0, t1, t2, t3])  # Top
        f.material_index = MAT_STAIRS
        faces.append(f)
        
        f = bm.faces.new([b3, b2, b1, b0])  # Bottom
        f.material_index = MAT_STAIRS
        faces.append(f)
        
        f = bm.faces.new([b0, b1, t1, t0])  # Front
        f.material_index = MAT_STAIRS
        faces.append(f)
        
        f = bm.faces.new([b2, b3, t3, t2])  # Back
        f.material_index = MAT_STAIRS
        faces.append(f)
        
        f = bm.faces.new([b3, b0, t0, t3])  # Left
        f.material_index = MAT_STAIRS
        faces.append(f)
        
        f = bm.faces.new([b1, b2, t2, t1])  # Right
        f.material_index = MAT_STAIRS
        faces.append(f)
    
    # Top landing
    landing_z = base_z + floor_height
    landing_thickness = 0.15
    
    lt0 = bm.verts.new(Vector((x_min, y_max - STAIR_LANDING, landing_z)))
    lt1 = bm.verts.new(Vector((x_max, y_max - STAIR_LANDING, landing_z)))
    lt2 = bm.verts.new(Vector((x_max, y_max, landing_z)))
    lt3 = bm.verts.new(Vector((x_min, y_max, landing_z)))
    
    lb0 = bm.verts.new(Vector((x_min, y_max - STAIR_LANDING, landing_z - landing_thickness)))
    lb1 = bm.verts.new(Vector((x_max, y_max - STAIR_LANDING, landing_z - landing_thickness)))
    lb2 = bm.verts.new(Vector((x_max, y_max, landing_z - landing_thickness)))
    lb3 = bm.verts.new(Vector((x_min, y_max, landing_z - landing_thickness)))
    
    f = bm.faces.new([lt0, lt1, lt2, lt3])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    f = bm.faces.new([lb3, lb2, lb1, lb0])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    f = bm.faces.new([lb0, lb1, lt1, lt0])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    f = bm.faces.new([lb2, lb3, lt3, lt2])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    f = bm.faces.new([lb3, lb0, lt0, lt3])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    f = bm.faces.new([lb1, lb2, lt2, lt1])
    f.material_index = MAT_STAIRS
    faces.append(f)
    
    return faces


def generate_interior_layout(bm: bmesh.types.BMesh, params: dict) -> list:
    """
    Generate complete interior layout based on building profile.
    
    Architectural validations:
    - Interior walls only attach to solid exterior wall sections (not windows/doors)
    - Stairs only generated if floor_slabs are enabled (stairs need something to rest on)
    - Walls avoid stair zones
    - Upper floor walls ONLY generated if floor slabs exist (walls need floor to stand on)
    - Upper floor walls use same layout as ground floor for structural consistency
    - Damage-aware: walls and stairs only built below damage line
    """
    faces = []
    
    profile_name = params.get('building_profile', 'NONE')
    profile_class = BUILDING_PROFILES.get(profile_name, BuildingProfile)
    
    if profile_name == 'NONE':
        return faces
    
    width = params['width']
    depth = params['depth']
    floors = params['floors']
    floor_height = params['floor_height']
    wall_thickness = params.get('wall_thickness', 0.25)
    floor_slabs_enabled = params.get('floor_slabs', True)
    
    # Check for damage - limit interior elements to below damage line
    damage_min_height = params.get('damage_min_height', None)
    total_height = floors * floor_height
    
    # Calculate max floor index that is below damage
    if damage_min_height is not None and damage_min_height < total_height:
        # Only build interiors for floors completely below damage
        max_interior_floor = int(damage_min_height / floor_height)
    else:
        max_interior_floor = floors
    
    # Check for patio - don't generate interior walls on patio floor (top floor)
    has_patio = params.get('has_patio', False) and floors >= 2
    if has_patio:
        # Don't generate interior walls on the top floor (patio floor)
        max_interior_floor = min(max_interior_floor, floors - 1)
    
    # Get window/door positions for wall attachment validation
    window_positions = get_window_positions(width, depth, params)
    
    # Get stair zone (consistent across all floors)
    # Only create stair zone if we have floor slabs to support stairs
    stair_zone = None
    if floors > 1 and floor_slabs_enabled:
        stair_zone = profile_class.get_stair_zone(width, depth, params)
    
    # Get ground floor layout - used as the base for all floors
    ground_floor_layout = profile_class.get_ground_floor_layout(width, depth, params)
    
    # Build validated ground floor walls list (reused for upper floors for structural support)
    validated_ground_walls = []
    for wall_def in ground_floor_layout.get('walls', []):
        adjusted_start, adjusted_end = validate_and_adjust_cardinal_wall(
            wall_def['start'], wall_def['end'],
            width, depth, wall_thickness, window_positions
        )
        
        if adjusted_start is None or adjusted_end is None:
            continue
        
        adjusted_wall = wall_def.copy()
        adjusted_wall['start'] = adjusted_start
        adjusted_wall['end'] = adjusted_end
        
        if (adjusted_end - adjusted_start).length < 0.3:
            continue
        
        validated_ground_walls.append(adjusted_wall)
    
    # Generate interior walls for each floor (limited by damage)
    for floor_idx in range(min(floors, max_interior_floor)):
        floor_base_z = floor_idx * floor_height
        
        if floor_idx == 0:
            # Ground floor: use the validated ground floor walls
            for wall_def in validated_ground_walls:
                faces.extend(build_interior_wall(bm, wall_def, floor_base_z))
        else:
            # Upper floors: ONLY generate walls if floor slabs are enabled
            # (walls need floor slab to stand on)
            if not floor_slabs_enabled:
                continue  # Skip upper floor walls - nothing to support them
            
            # Upper floors use SAME wall layout as ground floor for structural consistency
            # This ensures walls are stacked directly on top of each other
            for wall_def in validated_ground_walls:
                faces.extend(build_interior_wall(bm, wall_def, floor_base_z))
    
    # Generate interior stairs ONLY if:
    # 1. Multi-floor building
    # 2. Floor slabs are enabled (stairs need floor to rest on)
    # 3. Not using exterior stairs only
    # 4. Below damage line (stairs can't go above damaged areas)
    if floors > 1 and stair_zone and floor_slabs_enabled and not params.get('exterior_stairs', False):
        # Calculate max stair floor - stairs can go up to patio even if interior walls don't
        # But stairs should still respect damage
        if damage_min_height is not None and damage_min_height < total_height:
            max_stair_floor = int(damage_min_height / floor_height) - 1
        else:
            max_stair_floor = floors - 1
        
        for floor_idx in range(max(0, max_stair_floor)):
            floor_base_z = floor_idx * floor_height
            faces.extend(build_interior_stairs(bm, stair_zone, floor_height, floor_base_z))
    
    return faces


def get_floor_slab_opening(params: dict) -> dict:
    """
    Get floor slab opening for stair access.
    Returns opening dict or None.
    
    Only returns opening if:
    - Building has multiple floors
    - Floor slabs are enabled
    """
    profile_name = params.get('building_profile', 'NONE')
    floors = params.get('floors', 1)
    floor_slabs_enabled = params.get('floor_slabs', True)
    
    # No opening needed if floor slabs are disabled (nothing to cut)
    if not floor_slabs_enabled:
        return None
    
    if floors <= 1:
        return None
    
    profile_class = BUILDING_PROFILES.get(profile_name, BuildingProfile)
    return profile_class.get_floor_opening(params['width'], params['depth'], params)


# =============================================================================
# Rubble and Fill Generation
# =============================================================================

def generate_rubble_fill(bm: bmesh.types.BMesh, params: dict) -> list:
    """
    Generate rubble fill inside a building.
    
    Fill modes:
    - FILLED: Entire interior is filled (solid block, no interior visible)
    - PARTIAL: Lower floors filled, upper floors open
    - RUBBLE_PILES: Random rubble piles inside the building
    """
    faces = []
    
    fill_mode = params.get('interior_fill', 'NONE')
    if fill_mode == 'NONE':
        return faces
    
    width = params['width']
    depth = params['depth']
    floors = params['floors']
    floor_height = params['floor_height']
    wall_thickness = params.get('wall_thickness', 0.25)
    
    ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
    
    # Check for damage - rubble shouldn't exceed the lowest damage point
    total_height = floors * floor_height
    max_rubble_height = total_height - 0.1
    
    # If damage is enabled, limit rubble to lowest damage height
    if params.get('enable_damage', False) and params.get('damage_amount', 0) > 0:
        # Get minimum damage height from params if available
        damage_min_height = params.get('damage_min_height', None)
        if damage_min_height is not None:
            max_rubble_height = min(max_rubble_height, damage_min_height - 0.1)
    
    # If patio is enabled, limit rubble to below the patio floor
    if params.get('has_patio', False) and floors >= 2:
        patio_floor_z = (floors - 1) * floor_height
        max_rubble_height = min(max_rubble_height, patio_floor_z - 0.1)
    
    if fill_mode == 'FILLED':
        # Completely filled - one solid block covering all interior space
        fill_height = max_rubble_height
        
        min_co = Vector((ix_min, iy_min, 0))
        max_co = Vector((ix_max, iy_max, fill_height))
        faces.extend(util.create_box(bm, min_co, max_co, MAT_RUBBLE))
        
    elif fill_mode == 'PARTIAL':
        # Partial fill - fill some floors, leave others open with slanted top
        fill_floors = params.get('fill_floors', max(1, floors // 2))
        fill_floors = min(fill_floors, floors - 1)  # Leave at least top floor open
        
        if fill_floors > 0:
            base_fill_height = fill_floors * floor_height - util.random_float(0.3, 0.6)
            # Limit to max rubble height (respects damage)
            base_fill_height = min(base_fill_height, max_rubble_height - 0.5)
            faces.extend(_create_slanted_fill(bm, ix_min, iy_min, ix_max, iy_max, base_fill_height, max_rubble_height))
    
    elif fill_mode == 'RUBBLE_PILES':
        # Random rubble piles inside the building (ground floor only)
        faces.extend(_generate_rubble_piles(bm, params))
    
    return faces


def _create_slanted_fill(bm: bmesh.types.BMesh, x_min: float, y_min: float, 
                          x_max: float, y_max: float, base_height: float,
                          max_height: float = None) -> list:
    """
    Create a rubble fill with a slanted/uneven top surface.
    Uses a simple mesh with randomized top vertices.
    
    Args:
        max_height: Maximum allowed height (to stay within building bounds)
    """
    faces = []
    
    # Random slant direction and amount
    slant_x = util.random_float(-0.3, 0.3)  # Height variation per meter in X
    slant_y = util.random_float(-0.3, 0.3)  # Height variation per meter in Y
    
    width = x_max - x_min
    depth = y_max - y_min
    
    # Calculate corner heights with slant
    h_00 = base_height  # Front-left corner (reference)
    h_10 = base_height + slant_x * width  # Front-right
    h_01 = base_height + slant_y * depth  # Back-left
    h_11 = base_height + slant_x * width + slant_y * depth  # Back-right
    
    # Add random variation to each corner
    h_00 += util.random_float(-0.2, 0.2)
    h_10 += util.random_float(-0.2, 0.2)
    h_01 += util.random_float(-0.2, 0.2)
    h_11 += util.random_float(-0.2, 0.2)
    
    # Ensure minimum height
    min_h = 0.3
    h_00 = max(min_h, h_00)
    h_10 = max(min_h, h_10)
    h_01 = max(min_h, h_01)
    h_11 = max(min_h, h_11)
    
    # Clamp to maximum height (stay within building bounds)
    if max_height is not None:
        h_00 = min(h_00, max_height)
        h_10 = min(h_10, max_height)
        h_01 = min(h_01, max_height)
        h_11 = min(h_11, max_height)
    
    # Create vertices
    # Bottom face (flat at z=0)
    v_b00 = bm.verts.new(Vector((x_min, y_min, 0)))
    v_b10 = bm.verts.new(Vector((x_max, y_min, 0)))
    v_b11 = bm.verts.new(Vector((x_max, y_max, 0)))
    v_b01 = bm.verts.new(Vector((x_min, y_max, 0)))
    
    # Top face (slanted)
    v_t00 = bm.verts.new(Vector((x_min, y_min, h_00)))
    v_t10 = bm.verts.new(Vector((x_max, y_min, h_10)))
    v_t11 = bm.verts.new(Vector((x_max, y_max, h_11)))
    v_t01 = bm.verts.new(Vector((x_min, y_max, h_01)))
    
    # Create faces
    # Bottom
    f = bm.faces.new([v_b00, v_b01, v_b11, v_b10])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    # Top (slanted)
    f = bm.faces.new([v_t00, v_t10, v_t11, v_t01])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    # Front
    f = bm.faces.new([v_b00, v_b10, v_t10, v_t00])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    # Back
    f = bm.faces.new([v_b11, v_b01, v_t01, v_t11])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    # Left
    f = bm.faces.new([v_b01, v_b00, v_t00, v_t01])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    # Right
    f = bm.faces.new([v_b10, v_b11, v_t11, v_t10])
    f.material_index = MAT_RUBBLE
    faces.append(f)
    
    return faces


def _create_organic_pile(bm: bmesh.types.BMesh, center_x: float, center_y: float,
                          base_z: float, radius: float, height: float) -> list:
    """
    Create an organic rubble pile shape using a low-poly cone/mound.
    Uses 8-12 vertices for an irregular blob shape.
    """
    faces = []
    
    # Number of sides for the base (6-8 for organic look)
    num_sides = util.random_int(5, 7)
    
    # Create base vertices (irregular polygon on ground)
    base_verts = []
    import math
    
    for i in range(num_sides):
        angle = (2 * math.pi * i / num_sides) + util.random_float(-0.3, 0.3)
        # Vary radius for each vertex
        r = radius * util.random_float(0.7, 1.0)
        x = center_x + r * math.cos(angle)
        y = center_y + r * math.sin(angle)
        base_verts.append(bm.verts.new(Vector((x, y, base_z))))
    
    # Create peak vertex (slightly off-center for natural look)
    peak_offset_x = util.random_float(-radius * 0.3, radius * 0.3)
    peak_offset_y = util.random_float(-radius * 0.3, radius * 0.3)
    peak_height = height * util.random_float(0.8, 1.0)
    peak_vert = bm.verts.new(Vector((center_x + peak_offset_x, center_y + peak_offset_y, base_z + peak_height)))
    
    # Create base face (n-gon)
    try:
        f = bm.faces.new(base_verts)
        f.material_index = MAT_RUBBLE
        faces.append(f)
    except:
        pass  # Skip if face creation fails
    
    # Create side faces (triangles from base to peak)
    for i in range(num_sides):
        next_i = (i + 1) % num_sides
        try:
            f = bm.faces.new([base_verts[i], base_verts[next_i], peak_vert])
            f.material_index = MAT_RUBBLE
            faces.append(f)
        except:
            pass
    
    return faces


def _generate_rubble_piles(bm: bmesh.types.BMesh, params: dict) -> list:
    """
    Generate organic rubble piles inside the building.
    Only on ground floor, 2-5 piles with blob/mound shapes.
    """
    faces = []
    
    width = params['width']
    depth = params['depth']
    wall_thickness = params.get('wall_thickness', 0.25)
    rubble_density = params.get('rubble_density', 0.3)
    
    ix_min, iy_min, ix_max, iy_max = get_interior_bounds(width, depth, wall_thickness)
    interior_width = ix_max - ix_min
    interior_depth = iy_max - iy_min
    
    # 2-5 piles based on density and floor area
    base_piles = 2
    extra_piles = int(rubble_density * 3)  # 0-3 extra based on density
    num_piles = min(5, base_piles + extra_piles)
    
    # Keep track of pile positions to avoid overlap
    pile_positions = []
    
    for _ in range(num_piles):
        # Try to find a non-overlapping position
        attempts = 0
        while attempts < 10:
            # Random position within interior (with margin)
            margin = 0.8
            pile_x = util.random_float(ix_min + margin, ix_max - margin)
            pile_y = util.random_float(iy_min + margin, iy_max - margin)
            
            # Random pile size
            pile_radius = util.random_float(0.4, min(1.2, min(interior_width, interior_depth) * 0.25))
            pile_height = util.random_float(0.3, 0.8)
            
            # Check for overlap with existing piles
            overlaps = False
            for px, py, pr in pile_positions:
                dist = ((pile_x - px) ** 2 + (pile_y - py) ** 2) ** 0.5
                if dist < (pile_radius + pr) * 0.8:  # Allow slight overlap
                    overlaps = True
                    break
            
            if not overlaps:
                pile_positions.append((pile_x, pile_y, pile_radius))
                # Create organic pile on ground floor (z=0)
                faces.extend(_create_organic_pile(bm, pile_x, pile_y, 0, pile_radius, pile_height))
                break
            
            attempts += 1
    
    return faces


def generate_exterior_rubble(bm: bmesh.types.BMesh, params: dict) -> list:
    """
    Generate organic rubble piles outside the building (collapsed debris).
    
    Creates debris piles near walls with mound/blob shapes.
    """
    faces = []
    
    if not params.get('exterior_rubble', False):
        return faces
    
    width = params['width']
    depth = params['depth']
    rubble_spread = params.get('rubble_spread', 2.0)
    
    # Generate rubble piles around the building perimeter
    num_piles = params.get('exterior_rubble_piles', 4)
    
    for i in range(num_piles):
        # Choose a side of the building randomly
        side = util.random_int(0, 3)
        
        if side == 0:  # Front (Y = 0)
            pile_x = util.random_float(0.5, width - 0.5)
            pile_y = util.random_float(-rubble_spread * 0.8, -0.3)
        elif side == 1:  # Back (Y = depth)
            pile_x = util.random_float(0.5, width - 0.5)
            pile_y = util.random_float(depth + 0.3, depth + rubble_spread * 0.8)
        elif side == 2:  # Left (X = 0)
            pile_x = util.random_float(-rubble_spread * 0.8, -0.3)
            pile_y = util.random_float(0.5, depth - 0.5)
        else:  # Right (X = width)
            pile_x = util.random_float(width + 0.3, width + rubble_spread * 0.8)
            pile_y = util.random_float(0.5, depth - 0.5)
        
        # Random pile size (exterior piles can be a bit larger)
        pile_radius = util.random_float(0.4, 1.0)
        pile_height = util.random_float(0.2, 0.6)
        
        # Use organic pile shape
        faces.extend(_create_organic_pile(bm, pile_x, pile_y, 0, pile_radius, pile_height))
    
    return faces
