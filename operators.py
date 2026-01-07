# SPDX-License-Identifier: GPL-3.0-or-later
# Operators for Procedural Building Shell Generator

import bpy
from bpy.props import (
    FloatProperty, IntProperty, BoolProperty, EnumProperty
)
from mathutils import Vector
import itertools

from . import mesh_builder
from . import damage
from . import util


def unwrap_object_uvs(obj):
    """Unwrap UVs for an object using the marked seams."""
    import bpy
    
    # Store current selection
    old_active = bpy.context.view_layer.objects.active
    old_selected = [o for o in bpy.context.selected_objects]
    
    # Select only this object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    
    # Enter edit mode and unwrap
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.02)
    bpy.ops.object.mode_set(mode='OBJECT')
    
    # Restore selection
    bpy.ops.object.select_all(action='DESELECT')
    for o in old_selected:
        if o:
            o.select_set(True)
    if old_active:
        bpy.context.view_layer.objects.active = old_active


class MESH_OT_procedural_building_shell(bpy.types.Operator):
    """Generate a procedural building shell with windows, doors, and optional damage"""
    bl_idname = "mesh.procedural_building_shell"
    bl_label = "Procedural Building Shell"
    bl_options = {'REGISTER', 'UNDO', 'PRESET'}
    
    # === Basic Settings ===
    width: FloatProperty(
        name="Width",
        description="Building width (X axis)",
        default=8.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    
    depth: FloatProperty(
        name="Depth",
        description="Building depth (Y axis)",
        default=6.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    
    floors: IntProperty(
        name="Floors",
        description="Number of floors",
        default=2,
        min=1,
        max=10
    )
    
    floor_height: FloatProperty(
        name="Floor Height",
        description="Height of each floor",
        default=3.5,
        min=2.5,
        max=6.0,
        unit='LENGTH'
    )
    
    wall_thickness: FloatProperty(
        name="Wall Thickness",
        description="Thickness of walls",
        default=0.25,
        min=0.1,
        max=1.0,
        unit='LENGTH'
    )
    
    # === Window Settings ===
    window_type: EnumProperty(
        name="Window Type",
        description="Style of windows",
        items=[
            ('RECTANGULAR', "Rectangular", "Standard rectangular windows"),
            ('TALL', "Tall", "Tall narrow windows"),
            ('SQUARE', "Square", "Square windows"),
        ],
        default='RECTANGULAR'
    )
    
    window_width: FloatProperty(
        name="Window Width",
        description="Width of windows",
        default=1.2,
        min=0.4,
        max=4.0,
        unit='LENGTH'
    )
    
    window_height: FloatProperty(
        name="Window Height",
        description="Height of upper floor windows",
        default=1.4,
        min=0.4,
        max=3.0,
        unit='LENGTH'
    )
    
    windows_per_floor: IntProperty(
        name="Windows Per Floor",
        description="Number of windows on front/back walls per floor",
        default=3,
        min=0,
        max=10
    )
    
    window_spacing: FloatProperty(
        name="Window Spacing",
        description="Space between windows",
        default=0.8,
        min=0.2,
        max=3.0,
        unit='LENGTH'
    )
    
    sill_height: FloatProperty(
        name="Sill Height",
        description="Height of window sill from floor",
        default=0.9,
        min=0.3,
        max=2.0,
        unit='LENGTH'
    )
    
    # === Window Sides ===
    window_sides: EnumProperty(
        name="Window Sides",
        description="Which sides of the building have windows",
        items=[
            ('ALL', "All Sides", "Windows on all four sides"),
            ('FRONT_BACK', "Front & Back", "Windows only on front and back walls"),
            ('FRONT_SIDES', "Front & Sides", "Windows on front, left, and right walls"),
            ('FRONT_ONLY', "Front Only", "Windows only on front wall"),
            ('FRONT_LEFT', "Front & Left", "Windows on front and left walls"),
            ('FRONT_RIGHT', "Front & Right", "Windows on front and right walls"),
            ('BACK_SIDES', "Back & Sides", "Windows on back, left, and right walls"),
            ('SIDES_ONLY', "Sides Only", "Windows only on left and right walls"),
            ('NONE', "No Windows", "No windows on any side"),
        ],
        default='ALL'
    )
    
    # === Ground Floor Window Settings ===
    ground_floor_windows: EnumProperty(
        name="Ground Floor Windows",
        description="Window style for the ground floor",
        items=[
            ('NONE', "No Windows", "No windows on ground floor"),
            ('REGULAR', "Regular", "Same windows as upper floors"),
            ('STOREFRONT', "Storefront", "Large storefront display windows"),
            ('STOREFRONT_WIDE', "Wide Storefront", "Extra-wide storefront windows"),
        ],
        default='STOREFRONT'
    )
    
    ground_floor_window_count: IntProperty(
        name="Ground Floor Windows",
        description="Number of windows on ground floor (for storefront modes)",
        default=2,
        min=1,
        max=6
    )
    
    storefront_window_height: FloatProperty(
        name="Storefront Window Height",
        description="Height of ground floor storefront windows",
        default=2.2,
        min=1.0,
        max=3.5,
        unit='LENGTH'
    )
    
    storefront_window_width: FloatProperty(
        name="Storefront Window Width",
        description="Width of each storefront window",
        default=2.0,
        min=1.0,
        max=5.0,
        unit='LENGTH'
    )
    
    storefront_sill_height: FloatProperty(
        name="Storefront Sill Height",
        description="Sill height for storefront windows",
        default=0.3,
        min=0.0,
        max=1.0,
        unit='LENGTH'
    )
    
    # === Door Settings ===
    door_width: FloatProperty(
        name="Door Width",
        description="Width of doors",
        default=1.2,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    
    door_height: FloatProperty(
        name="Door Height",
        description="Height of doors",
        default=2.4,
        min=2.0,
        max=3.5,
        unit='LENGTH'
    )
    
    front_door_offset: FloatProperty(
        name="Front Door Position",
        description="Position of front door along wall (0=left, 1=right)",
        default=0.1,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    back_exit: BoolProperty(
        name="Back Exit",
        description="Add a back exit door",
        default=True
    )
    
    back_door_offset: FloatProperty(
        name="Back Door Position",
        description="Position of back door along wall (0=left, 1=right)",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    # === Structure Options ===
    flat_roof: BoolProperty(
        name="Flat Roof",
        description="Generate a flat roof",
        default=True
    )
    
    floor_slabs: BoolProperty(
        name="Floor Slabs",
        description="Generate floor slabs between floors",
        default=True
    )
    
    # === Facade Decoration ===
    facade_pilasters: BoolProperty(
        name="Facade Pilasters",
        description="Add protruding pilaster columns on the facade",
        default=False
    )
    
    pilaster_width: FloatProperty(
        name="Pilaster Width",
        description="Width of pilaster columns",
        default=0.4,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    
    pilaster_depth: FloatProperty(
        name="Pilaster Depth",
        description="How far pilasters protrude from the wall",
        default=0.15,
        min=0.05,
        max=0.5,
        unit='LENGTH'
    )
    
    pilaster_style: EnumProperty(
        name="Pilaster Style",
        description="Where to place pilasters on the facade",
        items=[
            ('CORNERS', "Corners Only", "Pilasters only at building corners"),
            ('CORNERS_CENTER', "Corners + Center", "Pilasters at corners and center of facade"),
            ('BETWEEN_WINDOWS', "Between Windows", "Pilasters between each window"),
            ('FULL', "Full Coverage", "Corners, center, and between windows"),
        ],
        default='CORNERS'
    )
    
    pilaster_sides: EnumProperty(
        name="Pilaster Sides",
        description="Which sides of the building have pilasters",
        items=[
            ('FRONT', "Front Only", "Pilasters only on front facade"),
            ('FRONT_BACK', "Front & Back", "Pilasters on front and back"),
            ('ALL', "All Sides", "Pilasters on all four sides"),
        ],
        default='FRONT'
    )
    
    # === Roof Parapet ===
    roof_parapet: BoolProperty(
        name="Roof Parapet",
        description="Walls extend above roof creating a parapet lip",
        default=False
    )
    
    parapet_height: FloatProperty(
        name="Parapet Height",
        description="Height of parapet above roof",
        default=0.5,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    
    # === Patio Settings ===
    has_patio: BoolProperty(
        name="Has Patio",
        description="Top floor has an open patio area",
        default=False
    )
    
    patio_side: EnumProperty(
        name="Patio Side",
        description="Which side of the building has the patio",
        items=[
            ('FRONT', "Front", "Patio on front side"),
            ('BACK', "Back", "Patio on back side"),
            ('LEFT', "Left", "Patio on left side"),
            ('RIGHT', "Right", "Patio on right side"),
        ],
        default='BACK'
    )
    
    patio_size: FloatProperty(
        name="Patio Size",
        description="How much of the top floor is patio (0.3 = 30%)",
        default=0.4,
        min=0.2,
        max=0.6,
        subtype='FACTOR'
    )
    
    patio_door_width: FloatProperty(
        name="Patio Door Width",
        description="Width of door leading to patio",
        default=1.5,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    
    # === Building Profile ===
    building_profile: EnumProperty(
        name="Building Profile",
        description="Interior layout profile for the building",
        items=[
            ('NONE', "None", "No interior layout"),
            ('STOREFRONT', "Storefront", "Retail front with back room, residential above"),
            ('WAREHOUSE', "Warehouse", "Large open space with optional office"),
            ('RESIDENTIAL', "Residential", "Apartments with hallway"),
            ('BAR', "Bar/Entertainment", "Multiple connected rooms for entertainment"),
        ],
        default='NONE'
    )
    
    exterior_stairs: BoolProperty(
        name="External Stair Access",
        description="Add door for external staircase (stairs not generated, only door). Interior stairs still have floor openings",
        default=False
    )
    
    # === Interior Fill (Rubble) ===
    interior_fill: EnumProperty(
        name="Interior Fill",
        description="Fill interior with rubble (saves detail, simulates collapsed/abandoned building)",
        items=[
            ('NONE', "None", "Normal interior (walls, stairs if profile selected)"),
            ('FILLED', "Completely Filled", "Interior completely filled with rubble (no interior visible)"),
            ('PARTIAL', "Partially Filled", "Lower floors filled, upper floors accessible"),
            ('RUBBLE_PILES', "Rubble Piles", "Random rubble piles inside the building"),
        ],
        default='NONE'
    )
    
    fill_floors: IntProperty(
        name="Filled Floors",
        description="Number of floors filled with rubble (for Partial fill mode)",
        default=1,
        min=1,
        max=3
    )
    
    rubble_density: FloatProperty(
        name="Rubble Density",
        description="How much of the floor is covered in rubble piles",
        default=0.3,
        min=0.1,
        max=1.0,
        subtype='FACTOR'
    )
    
    exterior_rubble: BoolProperty(
        name="Exterior Rubble",
        description="Add rubble piles around the building exterior",
        default=False
    )
    
    exterior_rubble_piles: IntProperty(
        name="Exterior Piles",
        description="Number of rubble piles around the building",
        default=4,
        min=1,
        max=20
    )
    
    rubble_spread: FloatProperty(
        name="Rubble Spread",
        description="How far exterior rubble spreads from building",
        default=2.0,
        min=0.5,
        max=5.0,
        unit='LENGTH'
    )
    
    # === Damage Settings ===
    enable_damage: BoolProperty(
        name="Enable Damage",
        description="Apply post-apocalyptic damage to the building",
        default=False
    )
    
    damage_amount: FloatProperty(
        name="Damage Amount",
        description="How much of the building is destroyed from top down (0=pristine, 1=ruins)",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_pointiness: FloatProperty(
        name="Pointiness",
        description="Height variance of damaged edge (0 = smooth, 1 = very jagged)",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_resolution: FloatProperty(
        name="Resolution",
        description="Vertex density of damage (lower = better performance, higher = more detail)",
        default=1.0,
        min=0.2,
        max=3.0,
        subtype='FACTOR'
    )
    
    # === Generation Settings ===
    seed: IntProperty(
        name="Random Seed",
        description="Seed for random generation (same seed = same result)",
        default=0,
        min=0
    )
    
    auto_clean: BoolProperty(
        name="Auto Clean",
        description="Automatically remove doubles and recalculate normals",
        default=True
    )
    
    create_materials: BoolProperty(
        name="Create Material Slots",
        description="Create material slots for different building parts",
        default=True
    )
    
    mark_uv_seams: BoolProperty(
        name="Mark UV Seams",
        description="Mark seams for UV unwrapping",
        default=True
    )
    
    auto_unwrap: BoolProperty(
        name="Auto Unwrap UVs",
        description="Automatically unwrap UVs using marked seams",
        default=True
    )
    
    def invoke(self, context, event):
        """Show the operator dialog when invoked."""
        return context.window_manager.invoke_props_dialog(self, width=400)
    
    def execute(self, context):
        # Collect parameters
        params = self._get_params()
        
        # Build the mesh
        builder = mesh_builder.BuildingShellBuilder(params)
        bm = builder.build()
        
        # Note: Damage is now integrated into the mesh building process
        # No need to apply damage separately
        
        # Create mesh data and object
        mesh = bpy.data.meshes.new("BuildingShell")
        bm.to_mesh(mesh)
        bm.free()
        
        # Create object
        obj = bpy.data.objects.new("BuildingShell", mesh)
        
        # Create material slots if requested
        if self.create_materials:
            self._create_material_slots(obj)
        
        # Link to scene
        context.collection.objects.link(obj)
        
        # Select the new object
        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        # Position at cursor
        obj.location = context.scene.cursor.location
        
        # Auto unwrap UVs if enabled
        if self.auto_unwrap and self.mark_uv_seams:
            unwrap_object_uvs(obj)
        
        return {'FINISHED'}
    
    def _get_params(self) -> dict:
        """Collect all parameters into a dictionary."""
        return {
            'width': self.width,
            'depth': self.depth,
            'floors': self.floors,
            'floor_height': self.floor_height,
            'wall_thickness': self.wall_thickness,
            
            'window_type': self.window_type,
            'window_width': self.window_width,
            'window_height': self.window_height,
            'windows_per_floor': self.windows_per_floor,
            'window_spacing': self.window_spacing,
            'sill_height': self.sill_height,
            'window_sides': self.window_sides,
            
            'ground_floor_windows': self.ground_floor_windows,
            'ground_floor_window_count': self.ground_floor_window_count,
            'storefront_window_height': self.storefront_window_height,
            'storefront_window_width': self.storefront_window_width,
            'storefront_sill_height': self.storefront_sill_height,
            
            'door_width': self.door_width,
            'door_height': self.door_height,
            'front_door_offset': self.front_door_offset,
            'back_exit': self.back_exit,
            'back_door_offset': self.back_door_offset,
            
            'flat_roof': self.flat_roof,
            'floor_slabs': self.floor_slabs,
            
            'facade_pilasters': self.facade_pilasters,
            'pilaster_width': self.pilaster_width,
            'pilaster_depth': self.pilaster_depth,
            'pilaster_style': self.pilaster_style,
            'pilaster_sides': self.pilaster_sides,
            
            'roof_parapet': self.roof_parapet,
            'parapet_height': self.parapet_height,
            
            'has_patio': self.has_patio,
            'patio_side': self.patio_side,
            'patio_size': self.patio_size,
            'patio_door_width': self.patio_door_width,
            
            'building_profile': self.building_profile,
            'exterior_stairs': self.exterior_stairs,
            
            'interior_fill': self.interior_fill,
            'fill_floors': self.fill_floors,
            'rubble_density': self.rubble_density,
            'exterior_rubble': self.exterior_rubble,
            'exterior_rubble_piles': self.exterior_rubble_piles,
            'rubble_spread': self.rubble_spread,
            
            'enable_damage': self.enable_damage,
            'damage_amount': self.damage_amount,
            'damage_pointiness': self.damage_pointiness,
            'damage_resolution': self.damage_resolution,
            
            'seed': self.seed,
            'auto_clean': self.auto_clean,
            'mark_uv_seams': self.mark_uv_seams,
        }
    
    def _create_material_slots(self, obj):
        """Create material slots for different building parts."""
        material_names = [
            "Building_Walls",
            "Building_Floor",
            "Building_Roof",
            "Building_WindowFrame",
            "Building_DoorFrame",
            "Building_InteriorWall",
            "Building_Stairs",
            "Building_Rubble",
        ]
        
        for name in material_names:
            # Check if material already exists
            mat = bpy.data.materials.get(name)
            if mat is None:
                mat = bpy.data.materials.new(name=name)
                mat.use_nodes = True
                
                # Set a default color based on type
                if "Rubble" in name:
                    mat.diffuse_color = (0.35, 0.32, 0.28, 1.0)  # Dark brown/gray debris
                elif "InteriorWall" in name:
                    mat.diffuse_color = (0.85, 0.82, 0.78, 1.0)  # Off-white
                elif "Stairs" in name:
                    mat.diffuse_color = (0.45, 0.4, 0.35, 1.0)  # Wood brown
                elif "Walls" in name:
                    mat.diffuse_color = (0.7, 0.65, 0.6, 1.0)  # Concrete
                elif "Floor" in name:
                    mat.diffuse_color = (0.5, 0.5, 0.5, 1.0)  # Gray
                elif "Roof" in name:
                    mat.diffuse_color = (0.3, 0.3, 0.35, 1.0)  # Dark gray
                elif "Window" in name:
                    mat.diffuse_color = (0.4, 0.35, 0.3, 1.0)  # Brown frame
                elif "Door" in name:
                    mat.diffuse_color = (0.35, 0.25, 0.2, 1.0)  # Dark brown
            
            obj.data.materials.append(mat)
    
    def draw(self, context):
        layout = self.layout
        
        # Basic Settings
        box = layout.box()
        box.label(text="Basic Settings", icon='HOME')
        col = box.column(align=True)
        col.prop(self, "width")
        col.prop(self, "depth")
        col.prop(self, "floors")
        col.prop(self, "floor_height")
        col.prop(self, "wall_thickness")
        
        # Window Settings
        box = layout.box()
        box.label(text="Window Settings", icon='MOD_LATTICE')
        col = box.column(align=True)
        col.prop(self, "window_type")
        col.prop(self, "window_sides")
        col.prop(self, "window_width")
        col.prop(self, "window_height")
        col.prop(self, "windows_per_floor")
        col.prop(self, "window_spacing")
        col.prop(self, "sill_height")
        
        # Storefront Settings
        box = layout.box()
        box.label(text="Ground Floor Windows", icon='FUND')
        col = box.column(align=True)
        col.prop(self, "ground_floor_windows")
        if self.ground_floor_windows in ('STOREFRONT', 'STOREFRONT_WIDE'):
            col.prop(self, "ground_floor_window_count")
            col.prop(self, "storefront_window_width")
            col.prop(self, "storefront_window_height")
            col.prop(self, "storefront_sill_height")
        
        # Door Settings
        box = layout.box()
        box.label(text="Door Settings", icon='IMPORT')
        col = box.column(align=True)
        col.prop(self, "door_width")
        col.prop(self, "door_height")
        col.prop(self, "front_door_offset")
        col.separator()
        col.prop(self, "back_exit")
        if self.back_exit:
            col.prop(self, "back_door_offset")
        
        # Structure Options
        box = layout.box()
        box.label(text="Structure", icon='MESH_CUBE')
        col = box.column(align=True)
        col.prop(self, "flat_roof")
        col.prop(self, "floor_slabs")
        col.separator()
        col.prop(self, "roof_parapet")
        if self.roof_parapet:
            col.prop(self, "parapet_height")
        
        # Patio Settings
        if self.floors >= 2:  # Patios only make sense with 2+ floors
            col.separator()
            col.prop(self, "has_patio")
            if self.has_patio:
                col.prop(self, "patio_side")
                col.prop(self, "patio_size")
                col.prop(self, "patio_door_width")
        
        # Facade Decoration
        box = layout.box()
        box.label(text="Facade Decoration", icon='MOD_SOLIDIFY')
        col = box.column(align=True)
        col.prop(self, "facade_pilasters")
        if self.facade_pilasters:
            col.prop(self, "pilaster_style")
            col.prop(self, "pilaster_sides")
            col.prop(self, "pilaster_width")
            col.prop(self, "pilaster_depth")
        
        # Building Profile / Interior
        box = layout.box()
        box.label(text="Interior Layout", icon='OUTLINER_OB_LATTICE')
        col = box.column(align=True)
        col.prop(self, "building_profile")
        if self.building_profile != 'NONE' and self.floors > 1:
            col.prop(self, "exterior_stairs")
        
        # Interior Fill (Rubble)
        box = layout.box()
        box.label(text="Interior Fill / Rubble", icon='MESH_ICOSPHERE')
        col = box.column(align=True)
        col.prop(self, "interior_fill")
        if self.interior_fill == 'PARTIAL':
            col.prop(self, "fill_floors")
        elif self.interior_fill == 'RUBBLE_PILES':
            col.prop(self, "rubble_density")
        col.separator()
        col.prop(self, "exterior_rubble")
        if self.exterior_rubble:
            col.prop(self, "exterior_rubble_piles")
            col.prop(self, "rubble_spread")
        
        # Damage Settings
        box = layout.box()
        box.label(text="Damage Settings", icon='FORCE_TURBULENCE')
        col = box.column(align=True)
        col.prop(self, "enable_damage")
        if self.enable_damage:
            col.prop(self, "damage_amount")
            col.prop(self, "damage_pointiness")
            col.prop(self, "damage_resolution")
        
        # Generation Settings
        box = layout.box()
        box.label(text="Generation", icon='PREFERENCES')
        col = box.column(align=True)
        col.prop(self, "seed")
        col.prop(self, "auto_clean")
        col.prop(self, "create_materials")
        col.prop(self, "mark_uv_seams")
        if self.mark_uv_seams:
            col.prop(self, "auto_unwrap")


class MESH_OT_procedural_building_bulk(bpy.types.Operator):
    """Generate multiple procedural buildings with parameter ranges"""
    bl_idname = "mesh.procedural_building_bulk"
    bl_label = "Bulk Generate Buildings"
    bl_options = {'REGISTER', 'UNDO'}
    
    # === Bulk Generation Settings ===
    count: IntProperty(
        name="Building Count",
        description="Number of buildings to generate",
        default=5,
        min=1,
        max=50
    )
    
    spacing: FloatProperty(
        name="Spacing",
        description="Space between buildings",
        default=2.0,
        min=0.0,
        max=20.0,
        unit='LENGTH'
    )
    
    layout_mode: EnumProperty(
        name="Layout",
        description="How to arrange the buildings",
        items=[
            ('ROW', "Row", "Buildings in a row along X axis"),
            ('GRID', "Grid", "Buildings in a grid pattern"),
            ('RANDOM', "Random", "Random positions within an area"),
        ],
        default='ROW'
    )
    
    grid_columns: IntProperty(
        name="Grid Columns",
        description="Number of columns in grid layout",
        default=3,
        min=1,
        max=10
    )
    
    random_area_size: FloatProperty(
        name="Random Area Size",
        description="Size of area for random placement",
        default=50.0,
        min=10.0,
        max=200.0,
        unit='LENGTH'
    )
    
    # === Building Size Ranges ===
    width_min: FloatProperty(
        name="Width Min",
        default=6.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    width_max: FloatProperty(
        name="Width Max",
        default=12.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    
    depth_min: FloatProperty(
        name="Depth Min",
        default=5.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    depth_max: FloatProperty(
        name="Depth Max",
        default=10.0,
        min=2.0,
        max=50.0,
        unit='LENGTH'
    )
    
    floors_min: IntProperty(
        name="Floors Min",
        default=1,
        min=1,
        max=10
    )
    floors_max: IntProperty(
        name="Floors Max",
        default=4,
        min=1,
        max=10
    )
    
    floor_height_min: FloatProperty(
        name="Floor Height Min",
        default=3.0,
        min=2.5,
        max=6.0,
        unit='LENGTH'
    )
    floor_height_max: FloatProperty(
        name="Floor Height Max",
        default=4.0,
        min=2.5,
        max=6.0,
        unit='LENGTH'
    )
    
    wall_thickness_min: FloatProperty(
        name="Wall Thickness Min",
        default=0.2,
        min=0.1,
        max=1.0,
        unit='LENGTH'
    )
    wall_thickness_max: FloatProperty(
        name="Wall Thickness Max",
        default=0.35,
        min=0.1,
        max=1.0,
        unit='LENGTH'
    )
    
    # === Window Ranges ===
    window_width_min: FloatProperty(
        name="Window Width Min",
        default=0.8,
        min=0.4,
        max=4.0,
        unit='LENGTH'
    )
    window_width_max: FloatProperty(
        name="Window Width Max",
        default=1.8,
        min=0.4,
        max=4.0,
        unit='LENGTH'
    )
    
    window_height_min: FloatProperty(
        name="Window Height Min",
        default=1.0,
        min=0.4,
        max=3.0,
        unit='LENGTH'
    )
    window_height_max: FloatProperty(
        name="Window Height Max",
        default=1.8,
        min=0.4,
        max=3.0,
        unit='LENGTH'
    )
    
    windows_per_floor_min: IntProperty(
        name="Windows Min",
        default=2,
        min=0,
        max=10
    )
    windows_per_floor_max: IntProperty(
        name="Windows Max",
        default=5,
        min=0,
        max=10
    )
    
    window_spacing_min: FloatProperty(
        name="Window Spacing Min",
        default=0.5,
        min=0.2,
        max=3.0,
        unit='LENGTH'
    )
    window_spacing_max: FloatProperty(
        name="Window Spacing Max",
        default=1.2,
        min=0.2,
        max=3.0,
        unit='LENGTH'
    )
    
    sill_height_min: FloatProperty(
        name="Sill Height Min",
        default=0.6,
        min=0.3,
        max=2.0,
        unit='LENGTH'
    )
    sill_height_max: FloatProperty(
        name="Sill Height Max",
        default=1.2,
        min=0.3,
        max=2.0,
        unit='LENGTH'
    )
    
    # === Window Sides ===
    window_sides_mode: EnumProperty(
        name="Window Sides",
        description="Which sides have windows",
        items=[
            ('ALL', "All Sides", "Windows on all four sides"),
            ('FRONT_BACK', "Front & Back", "Windows only on front and back walls"),
            ('FRONT_SIDES', "Front & Sides", "Windows on front, left, and right walls"),
            ('FRONT_ONLY', "Front Only", "Windows only on front wall"),
            ('FRONT_LEFT', "Front & Left", "Windows on front and left walls"),
            ('FRONT_RIGHT', "Front & Right", "Windows on front and right walls"),
            ('BACK_SIDES', "Back & Sides", "Windows on back, left, and right walls"),
            ('SIDES_ONLY', "Sides Only", "Windows only on left and right walls"),
            ('NONE', "No Windows", "No windows on any side"),
            ('RANDOM', "Random", "Random window configuration per building"),
        ],
        default='ALL'
    )
    
    # === Storefront Ranges ===
    storefront_window_height_min: FloatProperty(
        name="Storefront Height Min",
        default=1.8,
        min=1.0,
        max=3.5,
        unit='LENGTH'
    )
    storefront_window_height_max: FloatProperty(
        name="Storefront Height Max",
        default=2.5,
        min=1.0,
        max=3.5,
        unit='LENGTH'
    )
    
    storefront_sill_height_min: FloatProperty(
        name="Storefront Sill Min",
        default=0.1,
        min=0.0,
        max=1.0,
        unit='LENGTH'
    )
    storefront_sill_height_max: FloatProperty(
        name="Storefront Sill Max",
        default=0.5,
        min=0.0,
        max=1.0,
        unit='LENGTH'
    )
    
    # === Door Ranges ===
    door_width_min: FloatProperty(
        name="Door Width Min",
        default=0.9,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    door_width_max: FloatProperty(
        name="Door Width Max",
        default=1.5,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    
    door_height_min: FloatProperty(
        name="Door Height Min",
        default=2.1,
        min=2.0,
        max=3.5,
        unit='LENGTH'
    )
    door_height_max: FloatProperty(
        name="Door Height Max",
        default=2.6,
        min=2.0,
        max=3.5,
        unit='LENGTH'
    )
    
    # === Ground Floor Windows Mode ===
    ground_floor_windows_mode: EnumProperty(
        name="Ground Floor Windows",
        description="Window style for ground floor",
        items=[
            ('NONE', "No Windows", "No windows on ground floor"),
            ('REGULAR', "Regular", "Same as upper floors"),
            ('STOREFRONT', "Storefront", "Large storefront windows"),
            ('STOREFRONT_WIDE', "Wide Storefront", "Extra-wide storefront windows"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='RANDOM'
    )
    
    ground_floor_window_count_min: IntProperty(
        name="GF Window Count Min",
        description="Minimum storefront windows",
        default=1,
        min=1,
        max=6
    )
    ground_floor_window_count_max: IntProperty(
        name="GF Window Count Max",
        description="Maximum storefront windows",
        default=3,
        min=1,
        max=6
    )
    
    storefront_window_width_min: FloatProperty(
        name="Storefront Width Min",
        default=1.5,
        min=1.0,
        max=5.0,
        unit='LENGTH'
    )
    storefront_window_width_max: FloatProperty(
        name="Storefront Width Max",
        default=2.5,
        min=1.0,
        max=5.0,
        unit='LENGTH'
    )
    
    back_exit_mode: EnumProperty(
        name="Back Exit",
        description="Back exit door",
        items=[
            ('ALWAYS', "Always", "All buildings have back exits"),
            ('NEVER', "Never", "No buildings have back exits"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='RANDOM'
    )
    
    flat_roof_mode: EnumProperty(
        name="Flat Roof",
        description="Flat roof generation",
        items=[
            ('ALWAYS', "Always", "All buildings have flat roofs"),
            ('NEVER', "Never", "No buildings have roofs (open top)"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='ALWAYS'
    )
    
    floor_slabs_mode: EnumProperty(
        name="Floor Slabs",
        description="Floor slab generation",
        items=[
            ('ALWAYS', "Always", "All buildings have floor slabs"),
            ('NEVER', "Never", "No buildings have floor slabs"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='ALWAYS'
    )
    
    # === Facade Decoration ===
    facade_pilasters_mode: EnumProperty(
        name="Facade Pilasters",
        description="Protruding pilaster columns on facade",
        items=[
            ('ALWAYS', "Always", "All buildings have pilasters"),
            ('NEVER', "Never", "No buildings have pilasters"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='NEVER'
    )
    
    pilaster_style: EnumProperty(
        name="Pilaster Style",
        description="Where to place pilasters",
        items=[
            ('CORNERS', "Corners Only", "Pilasters only at building corners"),
            ('CORNERS_CENTER', "Corners + Center", "Pilasters at corners and center"),
            ('BETWEEN_WINDOWS', "Between Windows", "Pilasters between each window"),
            ('FULL', "Full Coverage", "Corners, center, and between windows"),
            ('RANDOM', "Random", "Random style per building"),
        ],
        default='CORNERS'
    )
    
    pilaster_sides: EnumProperty(
        name="Pilaster Sides",
        description="Which sides have pilasters",
        items=[
            ('FRONT', "Front Only", "Pilasters only on front"),
            ('FRONT_BACK', "Front & Back", "Pilasters on front and back"),
            ('ALL', "All Sides", "Pilasters on all sides"),
            ('RANDOM', "Random", "Random sides per building"),
        ],
        default='FRONT'
    )
    
    pilaster_width_min: FloatProperty(
        name="Pilaster Width Min",
        default=0.3,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    pilaster_width_max: FloatProperty(
        name="Pilaster Width Max",
        default=0.6,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    
    pilaster_depth_min: FloatProperty(
        name="Pilaster Depth Min",
        default=0.1,
        min=0.05,
        max=0.5,
        unit='LENGTH'
    )
    pilaster_depth_max: FloatProperty(
        name="Pilaster Depth Max",
        default=0.2,
        min=0.05,
        max=0.5,
        unit='LENGTH'
    )
    
    # === Roof Parapet ===
    roof_parapet_mode: EnumProperty(
        name="Roof Parapet",
        description="Walls extending above roof",
        items=[
            ('ALWAYS', "Always", "All buildings have parapets"),
            ('NEVER', "Never", "No buildings have parapets"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='NEVER'
    )
    
    parapet_height_min: FloatProperty(
        name="Parapet Height Min",
        default=0.3,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    parapet_height_max: FloatProperty(
        name="Parapet Height Max",
        default=0.7,
        min=0.2,
        max=1.5,
        unit='LENGTH'
    )
    
    # === Patio ===
    patio_mode: EnumProperty(
        name="Patio",
        description="Roof-level patio settings",
        items=[
            ('NEVER', "Never", "No patios"),
            ('ALWAYS', "Always", "All buildings have patios"),
            ('RANDOM', "Random", "Random chance of patio per building"),
        ],
        default='NEVER'
    )
    
    patio_probability: FloatProperty(
        name="Patio Probability",
        description="Chance of building having a patio (for Random mode)",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    patio_side_mode: EnumProperty(
        name="Patio Side",
        description="Which side has the patio",
        items=[
            ('FRONT', "Front", "Patio on front"),
            ('BACK', "Back", "Patio on back"),
            ('LEFT', "Left", "Patio on left"),
            ('RIGHT', "Right", "Patio on right"),
            ('RANDOM', "Random", "Random side per building"),
        ],
        default='BACK'
    )
    
    patio_size_min: FloatProperty(
        name="Patio Size Min",
        default=0.25,
        min=0.2,
        max=0.6,
        subtype='FACTOR'
    )
    patio_size_max: FloatProperty(
        name="Patio Size Max",
        default=0.5,
        min=0.2,
        max=0.6,
        subtype='FACTOR'
    )
    
    patio_door_width_min: FloatProperty(
        name="Patio Door Width Min",
        default=1.2,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    patio_door_width_max: FloatProperty(
        name="Patio Door Width Max",
        default=2.0,
        min=0.8,
        max=3.0,
        unit='LENGTH'
    )
    
    # === Building Profile ===
    building_profile: EnumProperty(
        name="Building Profile",
        description="Interior layout profile for buildings",
        items=[
            ('NONE', "None", "No interior layout"),
            ('STOREFRONT', "Storefront", "Retail front with back room"),
            ('WAREHOUSE', "Warehouse", "Large open space"),
            ('RESIDENTIAL', "Residential", "Apartments with hallway"),
            ('BAR', "Bar/Entertainment", "Multiple connected rooms"),
            ('RANDOM', "Random", "Random profile per building"),
        ],
        default='NONE'
    )
    
    exterior_stairs_mode: EnumProperty(
        name="External Stair Access",
        description="Whether buildings have external stair access door (stairs not generated)",
        items=[
            ('INTERIOR', "Interior Only", "Interior stairs with floor openings"),
            ('EXTERIOR', "Add External Door", "Interior stairs + door for external access"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='INTERIOR'
    )
    
    # === Interior Fill / Rubble ===
    interior_fill_mode: EnumProperty(
        name="Interior Fill",
        description="Fill interior with rubble",
        items=[
            ('NONE', "None", "Normal interior"),
            ('FILLED', "Filled", "All buildings completely filled"),
            ('PARTIAL', "Partial", "All buildings partially filled"),
            ('RUBBLE_PILES', "Rubble Piles", "All buildings have rubble piles"),
            ('RANDOM', "Random", "Random fill per building"),
        ],
        default='NONE'
    )
    
    fill_floors_min: IntProperty(
        name="Fill Floors Min",
        description="Minimum floors filled (for Partial mode)",
        default=1,
        min=1,
        max=3
    )
    fill_floors_max: IntProperty(
        name="Fill Floors Max",
        description="Maximum floors filled (for Partial mode)",
        default=2,
        min=1,
        max=3
    )
    
    rubble_density_min: FloatProperty(
        name="Rubble Density Min",
        default=0.2,
        min=0.1,
        max=1.0,
        subtype='FACTOR'
    )
    rubble_density_max: FloatProperty(
        name="Rubble Density Max",
        default=0.5,
        min=0.1,
        max=1.0,
        subtype='FACTOR'
    )
    
    exterior_rubble_mode: EnumProperty(
        name="Exterior Rubble",
        description="Rubble piles around buildings",
        items=[
            ('NEVER', "Never", "No exterior rubble"),
            ('ALWAYS', "Always", "All buildings have exterior rubble"),
            ('RANDOM', "Random", "Random per building"),
        ],
        default='NEVER'
    )
    
    exterior_rubble_piles_min: IntProperty(
        name="Exterior Piles Min",
        default=2,
        min=1,
        max=20
    )
    exterior_rubble_piles_max: IntProperty(
        name="Exterior Piles Max",
        default=6,
        min=1,
        max=20
    )
    
    # === Damage Ranges ===
    damage_mode: EnumProperty(
        name="Damage Mode",
        description="Building damage",
        items=[
            ('ALWAYS', "Always", "All buildings have damage"),
            ('NEVER', "Never", "No buildings have damage"),
            ('RANDOM', "Random", "Randomly per building"),
        ],
        default='NEVER'
    )
    
    damage_probability: FloatProperty(
        name="Damage Probability",
        description="Probability of damage when mode is Random",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_amount_min: FloatProperty(
        name="Damage Amount Min",
        description="Minimum damage intensity",
        default=0.1,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_amount_max: FloatProperty(
        name="Damage Amount Max",
        description="Maximum damage intensity",
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_pointiness_min: FloatProperty(
        name="Pointiness Min",
        description="Minimum damage pointiness",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_pointiness_max: FloatProperty(
        name="Pointiness Max",
        description="Maximum damage pointiness",
        default=0.7,
        min=0.0,
        max=1.0,
        subtype='FACTOR'
    )
    
    damage_resolution_min: FloatProperty(
        name="Resolution Min",
        description="Minimum damage resolution",
        default=0.5,
        min=0.2,
        max=3.0,
        subtype='FACTOR'
    )
    
    damage_resolution_max: FloatProperty(
        name="Resolution Max",
        description="Maximum damage resolution",
        default=1.5,
        min=0.2,
        max=3.0,
        subtype='FACTOR'
    )
    
    # === Seed ===
    base_seed: IntProperty(
        name="Base Seed",
        description="Starting seed (each building gets seed + index)",
        default=0,
        min=0
    )
    
    create_materials: BoolProperty(
        name="Create Material Slots",
        default=True
    )
    
    collection_name: bpy.props.StringProperty(
        name="Collection Name",
        description="Name for the collection containing generated buildings",
        default="Generated_Buildings"
    )
    
    mark_uv_seams: BoolProperty(
        name="Mark UV Seams",
        description="Mark seams for UV unwrapping",
        default=True
    )
    
    auto_unwrap: BoolProperty(
        name="Auto Unwrap UVs",
        description="Automatically unwrap UVs using marked seams",
        default=True
    )
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=500)
    
    def execute(self, context):
        # Determine which features have RANDOM mode (need all combinations)
        # Build list of (feature_name, possible_values) tuples
        random_feature_values = []
        if self.ground_floor_windows_mode == 'RANDOM':
            # Enum with 4 possible values
            random_feature_values.append(('ground_floor_windows', ['NONE', 'REGULAR', 'STOREFRONT', 'STOREFRONT_WIDE']))
        if self.back_exit_mode == 'RANDOM':
            random_feature_values.append(('back_exit', [True, False]))
        if self.flat_roof_mode == 'RANDOM':
            random_feature_values.append(('flat_roof', [True, False]))
        if self.floor_slabs_mode == 'RANDOM':
            random_feature_values.append(('floor_slabs', [True, False]))
        
        # Generate all combinations of random features
        if random_feature_values:
            feature_names = [f[0] for f in random_feature_values]
            value_lists = [f[1] for f in random_feature_values]
            combinations = list(itertools.product(*value_lists))
        else:
            feature_names = []
            combinations = [()]  # Single empty combination
        
        # Create parent collection
        parent_collection = bpy.data.collections.get(self.collection_name)
        if parent_collection is None:
            parent_collection = bpy.data.collections.new(self.collection_name)
            context.scene.collection.children.link(parent_collection)
        
        generated_objects = []
        total_buildings = 0
        
        # Generate buildings for each combination
        for combo_idx, combo in enumerate(combinations):
            # Build feature dict for this combination
            feature_overrides = {}
            for i, feature_name in enumerate(feature_names):
                feature_overrides[feature_name] = combo[i]
            
            # Create sub-collection for this combination if we have multiple
            if len(combinations) > 1:
                combo_name = self._get_combo_name(feature_names, combo)
                sub_collection = bpy.data.collections.get(f"{self.collection_name}_{combo_name}")
                if sub_collection is None:
                    sub_collection = bpy.data.collections.new(f"{self.collection_name}_{combo_name}")
                    parent_collection.children.link(sub_collection)
                target_collection = sub_collection
            else:
                target_collection = parent_collection
            
            # Generate buildings for this combination
            for i in range(self.count):
                # Initialize random for this building
                util.seed_random(self.base_seed + i)
                
                # Calculate position (offset by combination index for visibility)
                position = self._calculate_position(i, combo_idx, len(combinations))
                
                # Generate parameters with feature overrides
                params = self._generate_params_with_overrides(i, feature_overrides)
                
                # Build the mesh
                builder = mesh_builder.BuildingShellBuilder(params)
                bm = builder.build()
                
                # Note: Damage is now integrated into the mesh building process
                
                # Create mesh and object
                mesh_name = f"BuildingShell_{i:03d}"
                obj_name = f"Building_{i:03d}"
                if len(combinations) > 1:
                    combo_suffix = self._get_combo_suffix(feature_names, combo)
                    mesh_name = f"BuildingShell_{i:03d}_{combo_suffix}"
                    obj_name = f"Building_{i:03d}_{combo_suffix}"
                
                mesh = bpy.data.meshes.new(mesh_name)
                bm.to_mesh(mesh)
                bm.free()
                
                obj = bpy.data.objects.new(obj_name, mesh)
                obj.location = position + context.scene.cursor.location
                
                # Create material slots
                if self.create_materials:
                    self._create_material_slots(obj)
                
                # Link to collection
                target_collection.objects.link(obj)
                generated_objects.append(obj)
                total_buildings += 1
        
        # UV unwrap all generated objects
        if self.auto_unwrap and self.mark_uv_seams:
            for obj in generated_objects:
                unwrap_object_uvs(obj)
        
        # Select all generated objects
        bpy.ops.object.select_all(action='DESELECT')
        for obj in generated_objects:
            obj.select_set(True)
        if generated_objects:
            context.view_layer.objects.active = generated_objects[0]
        
        combo_info = f" ({len(combinations)} variations)" if len(combinations) > 1 else ""
        self.report({'INFO'}, f"Generated {total_buildings} buildings{combo_info} in '{self.collection_name}'")
        return {'FINISHED'}
    
    def _get_combo_name(self, features: list, combo: tuple) -> str:
        """Get a readable name for a feature combination."""
        parts = []
        for i, feature in enumerate(features):
            value = combo[i]
            if isinstance(value, bool):
                if value:
                    parts.append(feature.replace('_', ''))
                else:
                    parts.append(f"no{feature.replace('_', '')}")
            else:
                # Enum value - use the value itself
                parts.append(str(value).lower().replace('_', ''))
        return "_".join(parts)
    
    def _get_combo_suffix(self, features: list, combo: tuple) -> str:
        """Get a short suffix for object naming."""
        parts = []
        abbrevs = {
            'ground_floor_windows': 'GF',
            'back_exit': 'BE', 
            'flat_roof': 'RF',
            'floor_slabs': 'FS'
        }
        gf_abbrevs = {
            'NONE': 'GFn',
            'REGULAR': 'GFr',
            'STOREFRONT': 'GFs',
            'STOREFRONT_WIDE': 'GFw'
        }
        for i, feature in enumerate(features):
            value = combo[i]
            if feature == 'ground_floor_windows':
                parts.append(gf_abbrevs.get(value, 'GF'))
            elif isinstance(value, bool):
                abbrev = abbrevs.get(feature, feature[:2].upper())
                if value:
                    parts.append(abbrev)
                else:
                    parts.append(f"no{abbrev}")
            else:
                parts.append(str(value)[:3].upper())
        return "_".join(parts)
    
    def _calculate_position(self, index: int, combo_idx: int = 0, total_combos: int = 1) -> Vector:
        """Calculate position for building based on layout mode and variation combo."""
        # Calculate base cell size
        cell_width = self.width_max + self.spacing
        cell_depth = self.depth_max + self.spacing
        
        # Calculate variation offset - each combo set is placed in a separate "block"
        # We offset along Y axis, with enough space for all buildings in that combo
        if total_combos > 1:
            if self.layout_mode == 'GRID':
                # For grid, calculate how many rows the base set needs
                rows_per_combo = (self.count + self.grid_columns - 1) // self.grid_columns
                combo_y_offset = combo_idx * (rows_per_combo * cell_depth + self.spacing * 2)
            else:
                # For row/random, offset each combo set along Y
                combo_y_offset = combo_idx * (cell_depth + self.spacing * 2)
        else:
            combo_y_offset = 0
        
        if self.layout_mode == 'ROW':
            x = index * cell_width
            y = combo_y_offset
            return Vector((x, y, 0))
        
        elif self.layout_mode == 'GRID':
            col = index % self.grid_columns
            row = index // self.grid_columns
            
            x = col * cell_width
            y = row * cell_depth + combo_y_offset
            return Vector((x, y, 0))
        
        elif self.layout_mode == 'RANDOM':
            # Use seed for this specific building to get consistent random position
            util.seed_random(self.base_seed + index + 5000)
            
            cols = max(1, int(self.random_area_size / cell_width))
            
            col = util.random_int(0, cols - 1)
            row = index // cols
            
            jitter_x = util.random_float(0, self.spacing * 0.5) if self.spacing > 0 else 0
            jitter_y = util.random_float(0, self.spacing * 0.5) if self.spacing > 0 else 0
            
            x = col * cell_width + jitter_x
            y = row * cell_depth + combo_y_offset + jitter_y
            return Vector((x, y, 0))
        
        return Vector((0, 0, 0))
    
    def _get_bool_value(self, mode: str) -> bool:
        """Get boolean value based on mode (ALWAYS/NEVER)."""
        return mode == 'ALWAYS'
    
    def _generate_params_with_overrides(self, index: int, feature_overrides: dict) -> dict:
        """
        Generate parameters with context-aware feature selection.
        
        Smart generation rules:
        - Larger buildings get more windows
        - Building profile influences storefront mode and window configuration
        - Multi-floor buildings prioritize floor slabs
        - Window count scales with wall length
        - Taller buildings get proportionally sized windows
        """
        # Use seed based on index for reproducibility
        util.seed_random(self.base_seed + index)
        
        # =====================================================================
        # STEP 1: Generate core building dimensions first
        # =====================================================================
        width = util.random_float(self.width_min, self.width_max)
        depth = util.random_float(self.depth_min, self.depth_max)
        floors = util.random_int(self.floors_min, self.floors_max)
        floor_height = util.random_float(self.floor_height_min, self.floor_height_max)
        wall_thickness = util.random_float(self.wall_thickness_min, self.wall_thickness_max)
        
        # Calculate building "size factor" (0-1 scale based on dimensions)
        width_range = max(0.1, self.width_max - self.width_min)
        depth_range = max(0.1, self.depth_max - self.depth_min)
        floors_range = max(1, self.floors_max - self.floors_min)
        
        width_factor = (width - self.width_min) / width_range
        depth_factor = (depth - self.depth_min) / depth_range
        floors_factor = (floors - self.floors_min) / floors_range if floors_range > 0 else 0.5
        
        # Overall building size factor (average of dimensions)
        size_factor = (width_factor + depth_factor + floors_factor) / 3
        # Footprint factor (just width and depth)
        footprint_factor = (width_factor + depth_factor) / 2
        
        # =====================================================================
        # STEP 2: Determine building profile based on dimensions
        # =====================================================================
        if self.building_profile == 'RANDOM':
            # Smart profile selection based on building shape
            if width > depth * 1.3 and width >= 8:
                # Wide buildings favor storefronts or warehouses
                profile_weights = {'STOREFRONT': 0.4, 'WAREHOUSE': 0.3, 'BAR': 0.2, 'RESIDENTIAL': 0.1, 'NONE': 0.0}
            elif depth > width * 1.3:
                # Deep buildings favor residential (hallway layout)
                profile_weights = {'RESIDENTIAL': 0.5, 'WAREHOUSE': 0.2, 'STOREFRONT': 0.15, 'BAR': 0.1, 'NONE': 0.05}
            elif width >= 10 and depth >= 10:
                # Large square buildings favor warehouses or bars
                profile_weights = {'WAREHOUSE': 0.35, 'BAR': 0.3, 'STOREFRONT': 0.2, 'RESIDENTIAL': 0.1, 'NONE': 0.05}
            elif floors == 1:
                # Single floor buildings favor warehouses or storefronts
                profile_weights = {'WAREHOUSE': 0.3, 'STOREFRONT': 0.3, 'BAR': 0.2, 'NONE': 0.2, 'RESIDENTIAL': 0.0}
            else:
                # Default distribution
                profile_weights = {'STOREFRONT': 0.25, 'RESIDENTIAL': 0.25, 'WAREHOUSE': 0.2, 'BAR': 0.15, 'NONE': 0.15}
            
            # Weighted random selection
            rand_val = util.random_float(0, 1)
            cumulative = 0
            building_profile = 'NONE'
            for profile, weight in profile_weights.items():
                cumulative += weight
                if rand_val <= cumulative:
                    building_profile = profile
                    break
        else:
            building_profile = self.building_profile
        
        # =====================================================================
        # STEP 3: Smart window count based on wall length
        # =====================================================================
        # Calculate ideal window count based on available wall space
        # Rule: approximately one window per 2-3 meters of wall
        ideal_front_windows = max(1, int(width / 2.5))
        
        # Clamp to user-defined range but bias toward appropriate count
        windows_range = self.windows_per_floor_max - self.windows_per_floor_min
        if windows_range > 0:
            # Bias toward ideal count within the allowed range
            ideal_normalized = (ideal_front_windows - self.windows_per_floor_min) / windows_range
            ideal_normalized = max(0, min(1, ideal_normalized))
            
            # Blend random with ideal (70% ideal, 30% random)
            random_normalized = util.random_float(0, 1)
            blended = ideal_normalized * 0.7 + random_normalized * 0.3
            
            windows_per_floor = self.windows_per_floor_min + int(blended * windows_range)
            windows_per_floor = max(self.windows_per_floor_min, min(self.windows_per_floor_max, windows_per_floor))
        else:
            windows_per_floor = self.windows_per_floor_min
        
        # Window dimensions - taller floors get taller windows
        floor_height_factor = (floor_height - self.floor_height_min) / max(0.1, self.floor_height_max - self.floor_height_min)
        
        window_height_range = self.window_height_max - self.window_height_min
        window_height = self.window_height_min + floor_height_factor * 0.6 * window_height_range + util.random_float(0, 0.4 * window_height_range)
        window_height = max(self.window_height_min, min(self.window_height_max, window_height))
        
        window_width = util.random_float(self.window_width_min, self.window_width_max)
        
        # Window spacing - more windows means tighter spacing
        if windows_per_floor > 3:
            # Tighter spacing for many windows
            window_spacing = util.random_float(self.window_spacing_min, (self.window_spacing_min + self.window_spacing_max) / 2)
        else:
            window_spacing = util.random_float(self.window_spacing_min, self.window_spacing_max)
        
        sill_height = util.random_float(self.sill_height_min, self.sill_height_max)
        
        # =====================================================================
        # STEP 4: Storefront settings based on profile and width
        # =====================================================================
        storefront_window_height = util.random_float(
            self.storefront_window_height_min, self.storefront_window_height_max
        )
        storefront_sill_height = util.random_float(
            self.storefront_sill_height_min, self.storefront_sill_height_max
        )
        
        # Storefront mode - influenced by profile and building width
        # Ground floor windows - style depends on building profile and size
        if 'ground_floor_windows' in feature_overrides:
            ground_floor_windows = feature_overrides['ground_floor_windows']
        elif self.ground_floor_windows_mode == 'RANDOM':
            # Choose ground floor window style based on profile
            if building_profile == 'STOREFRONT':
                ground_floor_windows = util.random_choice(['STOREFRONT', 'STOREFRONT_WIDE'])
            elif building_profile == 'WAREHOUSE':
                ground_floor_windows = util.random_choice(['NONE', 'NONE', 'REGULAR'])  # Mostly no windows
            elif building_profile == 'BAR':
                ground_floor_windows = util.random_choice(['STOREFRONT', 'STOREFRONT_WIDE', 'REGULAR'])
            elif building_profile == 'RESIDENTIAL':
                ground_floor_windows = util.random_choice(['REGULAR', 'REGULAR', 'STOREFRONT'])
            elif width >= 8:
                ground_floor_windows = util.random_choice(['STOREFRONT', 'STOREFRONT_WIDE', 'REGULAR'])
            else:
                ground_floor_windows = util.random_choice(['REGULAR', 'STOREFRONT', 'NONE'])
        else:
            ground_floor_windows = self.ground_floor_windows_mode
        
        # Ground floor window count - more for wider buildings
        if ground_floor_windows in ('STOREFRONT', 'STOREFRONT_WIDE'):
            ideal_count = max(1, int(width / 3))  # Roughly one window per 3m
            count_range = self.ground_floor_window_count_max - self.ground_floor_window_count_min
            if count_range > 0:
                ideal_normalized = (ideal_count - self.ground_floor_window_count_min) / count_range
                ideal_normalized = max(0, min(1, ideal_normalized))
                blended = ideal_normalized * 0.7 + util.random_float(0, 1) * 0.3
                ground_floor_window_count = self.ground_floor_window_count_min + int(blended * count_range)
            else:
                ground_floor_window_count = self.ground_floor_window_count_min
            
            storefront_window_width = util.random_float(
                self.storefront_window_width_min, self.storefront_window_width_max
            )
            # Wide storefront gets wider windows
            if ground_floor_windows == 'STOREFRONT_WIDE':
                storefront_window_width *= 1.3
        else:
            ground_floor_window_count = windows_per_floor
            storefront_window_width = window_width
        
        # =====================================================================
        # STEP 5: Door settings
        # =====================================================================
        door_width = util.random_float(self.door_width_min, self.door_width_max)
        door_height = util.random_float(self.door_height_min, self.door_height_max)
        front_door_offset = util.random_float(0.05, 0.95)
        
        # Back exit - larger/deeper buildings more likely to have back exits
        if 'back_exit' in feature_overrides:
            back_exit = feature_overrides['back_exit']
        elif self.back_exit_mode == 'RANDOM':
            back_exit_probability = 0.3 + footprint_factor * 0.4  # 30-70% based on size
            if building_profile in ('WAREHOUSE', 'BAR'):
                back_exit_probability += 0.2  # More likely for these types
            back_exit = util.random_bool(min(0.9, back_exit_probability))
        else:
            back_exit = self._get_bool_value(self.back_exit_mode)
        
        back_door_offset = util.random_float(0.2, 0.8)
        
        # =====================================================================
        # STEP 6: Structure options
        # =====================================================================
        if 'flat_roof' in feature_overrides:
            flat_roof = feature_overrides['flat_roof']
        else:
            flat_roof = self._get_bool_value(self.flat_roof_mode)
        
        # Floor slabs - multi-floor buildings should have floor slabs
        if 'floor_slabs' in feature_overrides:
            floor_slabs = feature_overrides['floor_slabs']
        elif self.floor_slabs_mode == 'RANDOM':
            if floors > 1:
                floor_slabs = util.random_bool(0.9)  # 90% for multi-floor
            else:
                floor_slabs = util.random_bool(0.4)  # 40% for single floor
        else:
            floor_slabs = self._get_bool_value(self.floor_slabs_mode)
        
        # =====================================================================
        # STEP 7: Facade Pilasters - larger/older style buildings more likely
        # =====================================================================
        if self.facade_pilasters_mode == 'RANDOM':
            # Higher chance for wider buildings and storefront profiles
            pilaster_chance = 0.2 + width_factor * 0.3  # 20-50% based on width
            if building_profile == 'STOREFRONT':
                pilaster_chance += 0.2
            facade_pilasters = util.random_bool(min(0.7, pilaster_chance))
        else:
            facade_pilasters = self._get_bool_value(self.facade_pilasters_mode)
        
        if facade_pilasters:
            pilaster_width = util.random_float(self.pilaster_width_min, self.pilaster_width_max)
            pilaster_depth = util.random_float(self.pilaster_depth_min, self.pilaster_depth_max)
            
            if self.pilaster_style == 'RANDOM':
                pilaster_styles = ['CORNERS', 'CORNERS_CENTER', 'BETWEEN_WINDOWS', 'FULL']
                pilaster_style = pilaster_styles[util.random_int(0, len(pilaster_styles) - 1)]
            else:
                pilaster_style = self.pilaster_style
            
            if self.pilaster_sides == 'RANDOM':
                pilaster_sides_options = ['FRONT', 'FRONT_BACK', 'ALL']
                pilaster_sides = pilaster_sides_options[util.random_int(0, len(pilaster_sides_options) - 1)]
            else:
                pilaster_sides = self.pilaster_sides
        else:
            pilaster_width = 0.4
            pilaster_depth = 0.15
            pilaster_style = 'CORNERS'
            pilaster_sides = 'FRONT'
        
        # =====================================================================
        # STEP 8: Roof Parapet - common on urban buildings
        # =====================================================================
        if self.roof_parapet_mode == 'RANDOM':
            # Higher chance for buildings with roofs
            if flat_roof:
                roof_parapet = util.random_bool(0.5 + floors_factor * 0.2)  # 50-70%
            else:
                roof_parapet = False
        else:
            roof_parapet = self._get_bool_value(self.roof_parapet_mode)
        
        if roof_parapet:
            parapet_height = util.random_float(self.parapet_height_min, self.parapet_height_max)
        else:
            parapet_height = 0.5
        
        # =====================================================================
        # STEP 8.5: Patio - outdoor area on top floor
        # =====================================================================
        has_patio = False
        patio_side = 'BACK'
        patio_size = 0.4
        patio_door_width = 1.5
        
        # Patios only make sense for buildings with 2+ floors
        if floors >= 2:
            if self.patio_mode == 'RANDOM':
                has_patio = util.random_bool(self.patio_probability)
            elif self.patio_mode == 'ALWAYS':
                has_patio = True
            # else NEVER -> has_patio stays False
            
            if has_patio:
                patio_size = util.random_float(self.patio_size_min, self.patio_size_max)
                patio_door_width = util.random_float(self.patio_door_width_min, self.patio_door_width_max)
                
                if self.patio_side_mode == 'RANDOM':
                    patio_sides = ['FRONT', 'BACK', 'LEFT', 'RIGHT']
                    patio_side = patio_sides[util.random_int(0, len(patio_sides) - 1)]
                else:
                    patio_side = self.patio_side_mode
        
        # =====================================================================
        # STEP 9: Exterior stairs
        # =====================================================================
        if self.exterior_stairs_mode == 'RANDOM':
            # Only makes sense for multi-floor buildings
            if floors > 1:
                exterior_stairs = util.random_bool(0.25)  # 25% chance
            else:
                exterior_stairs = False
        else:
            exterior_stairs = self.exterior_stairs_mode == 'EXTERIOR'
        
        # =====================================================================
        # STEP 10: Window sides - based on building size and context
        # =====================================================================
        if self.window_sides_mode == 'RANDOM':
            # Larger buildings more likely to have windows on all sides
            # Smaller buildings might be row houses (no side windows)
            if footprint_factor > 0.7:
                # Large buildings - mostly all sides
                window_sides_options = ['ALL', 'ALL', 'ALL', 'FRONT_BACK', 'FRONT_SIDES']
            elif footprint_factor > 0.4:
                # Medium buildings - mixed
                window_sides_options = ['ALL', 'FRONT_BACK', 'FRONT_BACK', 'FRONT_SIDES', 'FRONT_LEFT', 'FRONT_RIGHT']
            else:
                # Small buildings - often row houses
                window_sides_options = ['FRONT_BACK', 'FRONT_BACK', 'FRONT_ONLY', 'FRONT_LEFT', 'FRONT_RIGHT', 'ALL']
            
            window_sides = window_sides_options[util.random_int(0, len(window_sides_options) - 1)]
        else:
            window_sides = self.window_sides_mode
        
        # =====================================================================
        # STEP 11: Interior Fill / Rubble
        # =====================================================================
        if self.interior_fill_mode == 'RANDOM':
            fill_options = ['NONE', 'NONE', 'FILLED', 'PARTIAL', 'RUBBLE_PILES']
            interior_fill = fill_options[util.random_int(0, len(fill_options) - 1)]
        elif self.interior_fill_mode == 'NONE':
            interior_fill = 'NONE'
        else:
            interior_fill = self.interior_fill_mode
        
        fill_floors = util.random_int(self.fill_floors_min, self.fill_floors_max)
        rubble_density = util.random_float(self.rubble_density_min, self.rubble_density_max)
        
        if self.exterior_rubble_mode == 'RANDOM':
            exterior_rubble = util.random_bool(0.4)  # 40% chance
        else:
            exterior_rubble = self.exterior_rubble_mode == 'ALWAYS'
        
        exterior_rubble_piles = util.random_int(self.exterior_rubble_piles_min, self.exterior_rubble_piles_max)
        
        # =====================================================================
        # STEP 12: Damage parameters
        # =====================================================================
        enable_damage = False
        damage_amount = 0.0
        damage_pointiness = 0.5
        damage_resolution = 1.0
        
        if self.damage_mode == 'ALWAYS':
            enable_damage = True
        elif self.damage_mode == 'RANDOM':
            enable_damage = util.random_bool(self.damage_probability)
        # else NEVER - enable_damage stays False
        
        if enable_damage:
            damage_amount = util.random_float(self.damage_amount_min, self.damage_amount_max)
            damage_pointiness = util.random_float(self.damage_pointiness_min, self.damage_pointiness_max)
            damage_resolution = util.random_float(self.damage_resolution_min, self.damage_resolution_max)
        
        return {
            'width': width,
            'depth': depth,
            'floors': floors,
            'floor_height': floor_height,
            'wall_thickness': wall_thickness,
            
            'window_type': 'RECTANGULAR',
            'window_width': window_width,
            'window_height': window_height,
            'windows_per_floor': windows_per_floor,
            'window_spacing': window_spacing,
            'sill_height': sill_height,
            'window_sides': window_sides,
            
            'ground_floor_windows': ground_floor_windows,
            'ground_floor_window_count': ground_floor_window_count,
            'storefront_window_height': storefront_window_height,
            'storefront_window_width': storefront_window_width,
            'storefront_sill_height': storefront_sill_height,
            
            'door_width': door_width,
            'door_height': door_height,
            'front_door_offset': front_door_offset,
            'back_exit': back_exit,
            'back_door_offset': back_door_offset,
            
            'flat_roof': flat_roof,
            'floor_slabs': floor_slabs,
            
            'facade_pilasters': facade_pilasters,
            'pilaster_width': pilaster_width,
            'pilaster_depth': pilaster_depth,
            'pilaster_style': pilaster_style,
            'pilaster_sides': pilaster_sides,
            
            'roof_parapet': roof_parapet,
            'parapet_height': parapet_height,
            
            'has_patio': has_patio,
            'patio_side': patio_side,
            'patio_size': patio_size,
            'patio_door_width': patio_door_width,
            
            'building_profile': building_profile,
            'exterior_stairs': exterior_stairs,
            
            'interior_fill': interior_fill,
            'fill_floors': fill_floors,
            'rubble_density': rubble_density,
            'exterior_rubble': exterior_rubble,
            'exterior_rubble_piles': exterior_rubble_piles,
            'rubble_spread': 2.0,
            
            'enable_damage': enable_damage,
            'damage_amount': damage_amount,
            'damage_pointiness': damage_pointiness,
            'damage_resolution': damage_resolution,
            
            'seed': self.base_seed + index,
            'auto_clean': True,
            'mark_uv_seams': self.mark_uv_seams,
        }
    
    def _create_material_slots(self, obj):
        """Create material slots for different building parts."""
        material_names = [
            "Building_Walls",
            "Building_Floor",
            "Building_Roof",
            "Building_WindowFrame",
            "Building_DoorFrame",
            "Building_InteriorWall",
            "Building_Stairs",
            "Building_Rubble",
        ]
        
        for name in material_names:
            mat = bpy.data.materials.get(name)
            if mat is None:
                mat = bpy.data.materials.new(name=name)
                mat.use_nodes = True
                
                if "Rubble" in name:
                    mat.diffuse_color = (0.35, 0.32, 0.28, 1.0)  # Dark brown/gray debris
                elif "InteriorWall" in name:
                    mat.diffuse_color = (0.85, 0.82, 0.78, 1.0)
                elif "Stairs" in name:
                    mat.diffuse_color = (0.45, 0.4, 0.35, 1.0)
                elif "Walls" in name:
                    mat.diffuse_color = (0.7, 0.65, 0.6, 1.0)
                elif "Floor" in name:
                    mat.diffuse_color = (0.5, 0.5, 0.5, 1.0)
                elif "Roof" in name:
                    mat.diffuse_color = (0.3, 0.3, 0.35, 1.0)
                elif "Window" in name:
                    mat.diffuse_color = (0.4, 0.35, 0.3, 1.0)
                elif "Door" in name:
                    mat.diffuse_color = (0.35, 0.25, 0.2, 1.0)
            
            obj.data.materials.append(mat)
    
    def draw(self, context):
        layout = self.layout
        
        # Bulk Settings
        box = layout.box()
        box.label(text="Bulk Generation", icon='DUPLICATE')
        col = box.column(align=True)
        col.prop(self, "count")
        col.prop(self, "spacing")
        col.prop(self, "layout_mode")
        
        if self.layout_mode == 'GRID':
            col.prop(self, "grid_columns")
        elif self.layout_mode == 'RANDOM':
            col.prop(self, "random_area_size")
        
        col.separator()
        col.prop(self, "collection_name")
        
        # Building Size Ranges
        box = layout.box()
        box.label(text="Building Size Ranges", icon='ARROW_LEFTRIGHT')
        
        row = box.row(align=True)
        row.prop(self, "width_min", text="Width")
        row.prop(self, "width_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "depth_min", text="Depth")
        row.prop(self, "depth_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "floors_min", text="Floors")
        row.prop(self, "floors_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "floor_height_min", text="Floor Height")
        row.prop(self, "floor_height_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "wall_thickness_min", text="Wall Thickness")
        row.prop(self, "wall_thickness_max", text="")
        
        # Window Ranges
        box = layout.box()
        box.label(text="Window Ranges", icon='MOD_LATTICE')
        
        col = box.column(align=True)
        col.prop(self, "window_sides_mode", text="Sides")
        col.separator()
        
        row = box.row(align=True)
        row.prop(self, "window_width_min", text="Width")
        row.prop(self, "window_width_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "window_height_min", text="Height")
        row.prop(self, "window_height_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "windows_per_floor_min", text="Count")
        row.prop(self, "windows_per_floor_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "window_spacing_min", text="Spacing")
        row.prop(self, "window_spacing_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "sill_height_min", text="Sill Height")
        row.prop(self, "sill_height_max", text="")
        
        # Storefront Ranges
        box = layout.box()
        box.label(text="Ground Floor / Storefront Ranges", icon='FUND')
        
        row = box.row(align=True)
        row.prop(self, "ground_floor_window_count_min", text="Count")
        row.prop(self, "ground_floor_window_count_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "storefront_window_width_min", text="Width")
        row.prop(self, "storefront_window_width_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "storefront_window_height_min", text="Height")
        row.prop(self, "storefront_window_height_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "storefront_sill_height_min", text="Sill")
        row.prop(self, "storefront_sill_height_max", text="")
        
        # Door Ranges
        box = layout.box()
        box.label(text="Door Ranges", icon='IMPORT')
        
        row = box.row(align=True)
        row.prop(self, "door_width_min", text="Width")
        row.prop(self, "door_width_max", text="")
        
        row = box.row(align=True)
        row.prop(self, "door_height_min", text="Height")
        row.prop(self, "door_height_max", text="")
        
        # Boolean Options
        box = layout.box()
        box.label(text="Feature Variation", icon='OPTIONS')
        
        col = box.column(align=True)
        col.prop(self, "ground_floor_windows_mode", text="Ground Floor")
        col.prop(self, "back_exit_mode", text="Back Exit")
        col.prop(self, "flat_roof_mode", text="Flat Roof")
        col.prop(self, "floor_slabs_mode", text="Floor Slabs")
        
        # Count variations - ground_floor_windows has 4 options, others have 2
        variation_count = 1
        if self.ground_floor_windows_mode == 'RANDOM':
            variation_count *= 4  # NONE, REGULAR, STOREFRONT, STOREFRONT_WIDE
        if self.back_exit_mode == 'RANDOM':
            variation_count *= 2
        if self.flat_roof_mode == 'RANDOM':
            variation_count *= 2
        if self.floor_slabs_mode == 'RANDOM':
            variation_count *= 2
        
        if variation_count > 1:
            col.separator()
            col.label(text=f"Will generate {variation_count} variations per building", icon='INFO')
        
        # Facade Decoration
        box = layout.box()
        box.label(text="Facade Decoration", icon='MOD_SOLIDIFY')
        col = box.column(align=True)
        col.prop(self, "facade_pilasters_mode", text="Pilasters")
        if self.facade_pilasters_mode != 'NEVER':
            col.prop(self, "pilaster_style")
            col.prop(self, "pilaster_sides")
            row = col.row(align=True)
            row.prop(self, "pilaster_width_min", text="Width")
            row.prop(self, "pilaster_width_max", text="")
            row = col.row(align=True)
            row.prop(self, "pilaster_depth_min", text="Depth")
            row.prop(self, "pilaster_depth_max", text="")
        
        col.separator()
        col.prop(self, "roof_parapet_mode", text="Roof Parapet")
        if self.roof_parapet_mode != 'NEVER':
            row = col.row(align=True)
            row.prop(self, "parapet_height_min", text="Height")
            row.prop(self, "parapet_height_max", text="")
        
        col.separator()
        col.prop(self, "patio_mode", text="Patio")
        if self.patio_mode != 'NEVER':
            if self.patio_mode == 'RANDOM':
                col.prop(self, "patio_probability", text="Probability")
            col.prop(self, "patio_side_mode", text="Side")
            row = col.row(align=True)
            row.prop(self, "patio_size_min", text="Size")
            row.prop(self, "patio_size_max", text="")
            row = col.row(align=True)
            row.prop(self, "patio_door_width_min", text="Door Width")
            row.prop(self, "patio_door_width_max", text="")
        
        # Interior Layout
        box = layout.box()
        box.label(text="Interior Layout", icon='OUTLINER_OB_LATTICE')
        col = box.column(align=True)
        col.prop(self, "building_profile")
        col.prop(self, "exterior_stairs_mode")
        
        # Interior Fill / Rubble
        box = layout.box()
        box.label(text="Interior Fill / Rubble", icon='MESH_ICOSPHERE')
        col = box.column(align=True)
        col.prop(self, "interior_fill_mode", text="Fill Mode")
        
        if self.interior_fill_mode in ('PARTIAL', 'RANDOM'):
            row = col.row(align=True)
            row.prop(self, "fill_floors_min", text="Fill Floors")
            row.prop(self, "fill_floors_max", text="")
        
        if self.interior_fill_mode in ('RUBBLE_PILES', 'RANDOM'):
            row = col.row(align=True)
            row.prop(self, "rubble_density_min", text="Density")
            row.prop(self, "rubble_density_max", text="")
        
        col.separator()
        col.prop(self, "exterior_rubble_mode", text="Exterior Rubble")
        if self.exterior_rubble_mode != 'NEVER':
            row = col.row(align=True)
            row.prop(self, "exterior_rubble_piles_min", text="Piles")
            row.prop(self, "exterior_rubble_piles_max", text="")
        
        # Damage
        box = layout.box()
        box.label(text="Damage", icon='FORCE_TURBULENCE')
        col = box.column(align=True)
        col.prop(self, "damage_mode")
        if self.damage_mode != 'NEVER':
            if self.damage_mode == 'RANDOM':
                col.prop(self, "damage_probability")
            row = col.row(align=True)
            row.prop(self, "damage_amount_min", text="Amount")
            row.prop(self, "damage_amount_max", text="")
            row = col.row(align=True)
            row.prop(self, "damage_pointiness_min", text="Pointiness")
            row.prop(self, "damage_pointiness_max", text="")
            row = col.row(align=True)
            row.prop(self, "damage_resolution_min", text="Resolution")
            row.prop(self, "damage_resolution_max", text="")
        
        # Generation
        box = layout.box()
        box.label(text="Generation", icon='PREFERENCES')
        col = box.column(align=True)
        col.prop(self, "base_seed")
        col.prop(self, "create_materials")
        col.prop(self, "mark_uv_seams")
        if self.mark_uv_seams:
            col.prop(self, "auto_unwrap")
