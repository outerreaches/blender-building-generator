# SPDX-License-Identifier: GPL-3.0-or-later
"""Architecture recipes shared by city assets and the standalone style operator."""
STYLE_ITEMS = [
    ('OLD_TOWN', 'Old Town / Masonry', 'Narrow tall windows, pilasters and parapets'),
    ('RESIDENTIAL', 'Residential', 'Regular apartment windows and modest parapets'),
    ('INDUSTRIAL', 'Industrial', 'Low warehouse shells with wide openings'),
    ('BRUTALIST', 'Brutalist', 'Tall concrete blocks with deep walls and square windows'),
]
STYLE_COLORS = {'OLD_TOWN': (.48, .30, .20, 1), 'RESIDENTIAL': (.62, .58, .44, 1),
                'INDUSTRIAL': (.32, .39, .42, 1), 'BRUTALIST': (.48, .48, .46, 1)}


def building_recipe(style, width, depth, floors, seed, damage=0, interiors=False):
    if style not in STYLE_COLORS:
        raise ValueError(f'Unknown building style: {style}')
    industrial = style == 'INDUSTRIAL'
    old = style == 'OLD_TOWN'
    brutal = style == 'BRUTALIST'
    window_width = 1.0 if old else (1.8 if industrial else 1.4)
    return dict(
        width=width, depth=depth, floors=floors, floor_height=4.2 if industrial else 3.4,
        wall_thickness=.4 if brutal else .25,
        window_type='RECTANGULAR', window_width=window_width,
        window_height=1.9 if old else 1.4, window_spacing=.8, sill_height=.9,
        windows_per_floor=max(1, int((width - 2) / (window_width + 1))),
        window_sides='ALL', ground_floor_windows='STOREFRONT' if old else 'REGULAR',
        ground_floor_window_count=max(1, int((width - 3) / 3)),
        storefront_window_width=1.8, storefront_window_height=2.2, storefront_sill_height=.3,
        door_width=2.4 if industrial else 1.4, door_height=2.6,
        front_door_offset=.5, back_exit=True, back_door_offset=.5,
        flat_roof=True, floor_slabs=True,
        facade_pilasters=old, pilaster_width=.25, pilaster_depth=.15,
        pilaster_style='CORNERS', pilaster_sides='FRONT',
        roof_parapet=not industrial, parapet_height=.65 if brutal else .35,
        has_patio=False, building_profile=('WAREHOUSE' if industrial else 'RESIDENTIAL') if interiors else 'NONE',
        exterior_stairs=False, interior_fill='NONE', exterior_rubble=False,
        enable_damage=damage > 0, damage_amount=damage,
        damage_pointiness=.4, damage_resolution=1.0,
        seed=seed, auto_clean=True, mark_uv_seams=True,
    )
