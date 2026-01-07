# SPDX-License-Identifier: GPL-3.0-or-later
# Utility functions for Procedural Building Shell Generator

import random
import bmesh
import mathutils
from mathutils import Vector


def seed_random(seed: int):
    """Initialize random with a seed for reproducible generation."""
    random.seed(seed)


def random_float(min_val: float, max_val: float) -> float:
    """Return a random float between min_val and max_val."""
    return random.uniform(min_val, max_val)


def random_int(min_val: int, max_val: int) -> int:
    """Return a random integer between min_val and max_val (inclusive)."""
    return random.randint(min_val, max_val)


def random_bool(probability: float = 0.5) -> bool:
    """Return True with given probability (0.0 to 1.0)."""
    return random.random() < probability


def random_choice(items: list):
    """Return a random item from the list."""
    return random.choice(items)


def create_bmesh() -> bmesh.types.BMesh:
    """Create and return a new BMesh."""
    return bmesh.new()


def bmesh_to_mesh(bm: bmesh.types.BMesh, mesh):
    """Convert BMesh to Blender mesh data."""
    bm.to_mesh(mesh)
    bm.free()


def create_quad(bm: bmesh.types.BMesh, corners: list, material_index: int = 0) -> bmesh.types.BMFace:
    """
    Create a quad face from 4 corner positions.
    
    Args:
        bm: BMesh to add the quad to
        corners: List of 4 Vector positions (bottom-left, bottom-right, top-right, top-left)
        material_index: Material slot index for the face
    
    Returns:
        The created BMFace
    """
    verts = [bm.verts.new(co) for co in corners]
    face = bm.faces.new(verts)
    face.material_index = material_index
    return face


def create_box(bm: bmesh.types.BMesh, min_co: Vector, max_co: Vector, material_index: int = 0) -> list:
    """
    Create a box (6 faces) from min and max coordinates.
    
    Args:
        bm: BMesh to add the box to
        min_co: Minimum corner (x, y, z)
        max_co: Maximum corner (x, y, z)
        material_index: Material slot index for faces
    
    Returns:
        List of created BMFaces
    """
    x0, y0, z0 = min_co
    x1, y1, z1 = max_co
    
    # 8 corners of the box
    verts = [
        bm.verts.new((x0, y0, z0)),  # 0: front-bottom-left
        bm.verts.new((x1, y0, z0)),  # 1: front-bottom-right
        bm.verts.new((x1, y1, z0)),  # 2: back-bottom-right
        bm.verts.new((x0, y1, z0)),  # 3: back-bottom-left
        bm.verts.new((x0, y0, z1)),  # 4: front-top-left
        bm.verts.new((x1, y0, z1)),  # 5: front-top-right
        bm.verts.new((x1, y1, z1)),  # 6: back-top-right
        bm.verts.new((x0, y1, z1)),  # 7: back-top-left
    ]
    
    faces = []
    # Front face (Y-)
    faces.append(bm.faces.new([verts[0], verts[1], verts[5], verts[4]]))
    # Back face (Y+)
    faces.append(bm.faces.new([verts[2], verts[3], verts[7], verts[6]]))
    # Left face (X-)
    faces.append(bm.faces.new([verts[3], verts[0], verts[4], verts[7]]))
    # Right face (X+)
    faces.append(bm.faces.new([verts[1], verts[2], verts[6], verts[5]]))
    # Bottom face (Z-)
    faces.append(bm.faces.new([verts[3], verts[2], verts[1], verts[0]]))
    # Top face (Z+)
    faces.append(bm.faces.new([verts[4], verts[5], verts[6], verts[7]]))
    
    for f in faces:
        f.material_index = material_index
    
    return faces


def subdivide_face_for_opening(bm: bmesh.types.BMesh, face: bmesh.types.BMFace, 
                                opening_min: Vector, opening_max: Vector) -> bmesh.types.BMFace:
    """
    Subdivide a face to create an opening (window/door) and delete the center.
    
    This creates a frame of faces around the opening by subdividing the original face.
    
    Args:
        bm: BMesh containing the face
        face: The face to subdivide
        opening_min: Bottom-left corner of opening in face's local 2D space
        opening_max: Top-right corner of opening in face's local 2D space
    
    Returns:
        None (the opening face is deleted)
    """
    # This is a simplified version - actual implementation in mesh_builder
    pass


def remove_doubles(bm: bmesh.types.BMesh, dist: float = 0.0001):
    """Merge vertices that are very close together."""
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=dist)


def recalc_normals(bm: bmesh.types.BMesh, face_influence: bool = True):
    """Recalculate normals to face outward."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])


def cleanup_mesh(bm: bmesh.types.BMesh, merge_dist: float = 0.001):
    """
    Comprehensive mesh cleanup.
    
    Args:
        bm: BMesh to clean
        merge_dist: Distance for merging close vertices
    """
    # Merge close vertices
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=merge_dist)
    
    # Remove loose vertices
    loose_verts = [v for v in bm.verts if not v.link_faces]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context='VERTS')
    
    # Remove degenerate faces
    degen_faces = [f for f in bm.faces if f.calc_area() < 0.0001]
    if degen_faces:
        bmesh.ops.delete(bm, geom=degen_faces, context='FACES')
    
    # Recalculate normals
    recalc_normals(bm)


def get_face_normal(face: bmesh.types.BMFace) -> Vector:
    """Get the normal vector of a face."""
    return face.normal.copy()


def get_face_center(face: bmesh.types.BMFace) -> Vector:
    """Get the center point of a face."""
    return face.calc_center_median()


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between a and b."""
    return a + (b - a) * t


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))

