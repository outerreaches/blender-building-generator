# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture recipes shared by city assets and the standalone style operator.

Each style is a district archetype, not only a palette: downtown towers are tall
and finely glazed, industrial sheds are wide with high windows and lorry doors,
and suburban houses are small with a pitched roof.
"""
import random

STYLE_ITEMS = [
    ('DOWNTOWN', 'Downtown Tower', 'Tall glazed offices with a rooftop plant box'),
    ('OLD_TOWN', 'Old Town / Masonry', 'Narrow tall windows, pilasters and parapets'),
    ('RESIDENTIAL', 'Residential', 'Regular apartment windows and modest parapets'),
    ('BRUTALIST', 'Brutalist', 'Tall concrete blocks with deep walls and square windows'),
    ('INDUSTRIAL', 'Industrial', 'Wide low sheds, high windows and large doors'),
    ('SUBURBAN', 'Suburban House', 'Small pitched-roof houses set back from the street'),
]
INTERIOR_PROFILE = {
    'DOWNTOWN': 'OFFICE',
    'OLD_TOWN': 'STOREFRONT',
    'RESIDENTIAL': 'RESIDENTIAL',
    'BRUTALIST': 'OFFICE',
    'INDUSTRIAL': 'WAREHOUSE',
    'SUBURBAN': 'HOUSE',
}
STYLE_CONDITIONS = ('INTACT', 'WEATHERED', 'SEMI_COLLAPSED', 'RUBBLE_FILLED',
                    'PARTIAL_FILLED', 'LOWER_FLOORS', 'SHELL', 'WALL_RING',
                    'COLLAPSED')
STYLE_COLORS = {'DOWNTOWN': (.42, .47, .52, 1), 'OLD_TOWN': (.48, .30, .20, 1),
                'RESIDENTIAL': (.62, .58, .44, 1), 'BRUTALIST': (.48, .48, .46, 1),
                'INDUSTRIAL': (.32, .39, .42, 1), 'SUBURBAN': (.66, .55, .42, 1)}


def building_recipe(style, width, depth, floors, seed, damage=0, interiors=False,
                    condition='INTACT'):
    if style not in STYLE_COLORS:
        raise ValueError(f'Unknown building style: {style}')
    profile = dict(
        width=width, depth=depth, floors=floors, floor_height=3.4,
        wall_thickness=.25, window_type='RECTANGULAR',
        window_width=1.4, window_height=1.4, window_spacing=.8, sill_height=.9,
        window_sides='ALL', ground_floor_windows='REGULAR',
        storefront_window_width=1.8, storefront_window_height=2.2, storefront_sill_height=.3,
        door_width=1.4, door_height=2.6, front_door_offset=.5,
        back_exit=True, back_door_offset=.5,
        flat_roof=True, floor_slabs=True,
        facade_pilasters=False, pilaster_width=.25, pilaster_depth=.15,
        pilaster_style='CORNERS', pilaster_sides='FRONT',
        roof_parapet=True, parapet_height=.35,
        has_patio=False,
        building_profile=INTERIOR_PROFILE.get(style, 'RESIDENTIAL') if interiors else 'NONE',
        exterior_stairs=False, interior_fill='NONE', exterior_rubble=False,
        enable_damage=damage > 0, damage_amount=damage,
        damage_pointiness=.4, damage_resolution=1.0,
        seed=seed, auto_clean=True, mark_uv_seams=True,
        roof_kind='FLAT', roof_height=0.0, roof_overhang=0.0, roof_box=None,
    )
    if style == 'DOWNTOWN':
        profile.update(floor_height=3.9, wall_thickness=.3, window_width=2.2,
                       window_height=1.5, window_spacing=.55, sill_height=.8,
                       ground_floor_windows='STOREFRONT', door_width=1.8, door_height=2.8,
                       parapet_height=.25, roof_box=(.4, .3, 3.0))
    elif style == 'OLD_TOWN':
        profile.update(window_width=1.0, window_height=1.9,
                       ground_floor_windows='STOREFRONT', facade_pilasters=True)
    elif style == 'BRUTALIST':
        profile.update(wall_thickness=.4, sill_height=1.2, parapet_height=.65,
                       window_width=1.5, window_height=1.4)
    elif style == 'INDUSTRIAL':
        profile.update(floor_height=5.5, wall_thickness=.3, window_width=2.4,
                       window_height=1.1, window_spacing=1.0, sill_height=2.8,
                       door_width=3.2, door_height=3.4, roof_parapet=False,
                       building_profile='WAREHOUSE' if interiors else 'NONE')
    elif style == 'SUBURBAN':
        profile.update(floor_height=3.0, wall_thickness=.2, window_width=1.1,
                       window_height=1.2, window_spacing=1.1, sill_height=.9,
                       door_width=1.1, door_height=2.4, roof_parapet=False,
                       flat_roof=False, roof_kind='GABLE', roof_height=2.2,
                       roof_overhang=.45)
    if condition == 'RUBBLE_FILLED':
        profile.update(interior_fill='FILLED', building_profile='NONE',
                       chunk_cut=True, expose_fill=True)
    elif condition == 'PARTIAL_FILLED':
        profile.update(interior_fill='PARTIAL',
                       fill_floors=max(1, min(3, floors // 3 + 1)),
                       building_profile='NONE', chunk_cut=True, expose_fill=True)
    elif condition == 'SHELL':
        profile.update(flat_roof=False, floor_slabs=True,
                       building_profile='NONE', roof_parapet=False, roof_box=None,
                       chunk_cut=True)
    elif condition == 'SEMI_COLLAPSED':
        profile.update(chunk_cut=True)
    elif condition == 'LOWER_FLOORS':
        profile.update(damage_amount=1.0, enable_damage=True,
                       damage_cap_height=profile['floor_height'] * 2.6)
    elif condition == 'COLLAPSED':
        profile.update(building_profile='NONE', interior_fill='NONE')
    elif condition == 'WALL_RING':
        profile.update(floors=min(floors, 4), flat_roof=False, floor_slabs=False,
                       roof_parapet=False, building_profile='NONE',
                       interior_mound=True, chunk_cut=False, roof_box=None)
    if condition in ('RUBBLE_FILLED', 'PARTIAL_FILLED', 'SHELL', 'WALL_RING',
                     'COLLAPSED'):
        profile['building_profile'] = 'NONE'
    if (condition == 'WEATHERED' and floors >= 10 and
            random.Random(seed ^ 0x5EED).random() < .55):
        profile['chunk_cut'] = True
    profile['windows_per_floor'] = max(
        1, int((width - 2) / (profile['window_width'] + 1)))
    profile['ground_floor_window_count'] = max(1, int((width - 3) / 3))
    return profile
