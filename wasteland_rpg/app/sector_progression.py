from __future__ import annotations


SECTOR_PREVIOUS = {
    "rust_belt": None,
    "plant_12": "rust_belt",
    "black_contour": "plant_12",
    "quarry": None,
    "north_mine": "quarry",
    "freight_yard": None,
    "depot_6": "freight_yard",
    "foundry": None,
    "dead_substation": "foundry",
    "reactor_yard": "dead_substation",
}

SECTOR_NEXT = {
    previous: sector
    for sector, previous in SECTOR_PREVIOUS.items()
    if previous is not None
}
