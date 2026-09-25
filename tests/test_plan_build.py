import pytest
from errors import AutocadError
from plan_build import build_extrude_payload, slab_bbox
from opening_match import Wall


def test_slab_bbox_from_wall_endpoints():
    walls = [
        Wall("a", "exterior", 200, 0, 0, 4000, 0),
        Wall("c", "exterior", 200, 4000, 0, 4000, 3000),
    ]
    box = slab_bbox(walls, 150)
    assert box == {"min_x": 0, "min_y": 0, "max_x": 4000, "max_y": 3000, "thickness_mm": 150}


def test_build_payload_adds_height_and_matched_door():
    walls = [
        {"wall_id": "a", "kind": "exterior", "thickness_mm": 200, "x1": 0, "y1": 0, "x2": 1500, "y2": 0},
        {"wall_id": "b", "kind": "exterior", "thickness_mm": 200, "x1": 2400, "y1": 0, "x2": 4000, "y2": 0},
        {"wall_id": "c", "kind": "exterior", "thickness_mm": 200, "x1": 4000, "y1": 0, "x2": 4000, "y2": 3000},
        {"wall_id": "d", "kind": "exterior", "thickness_mm": 200, "x1": 4000, "y1": 3000, "x2": 0, "y2": 3000},
        {"wall_id": "e", "kind": "exterior", "thickness_mm": 200, "x1": 0, "y1": 3000, "x2": 0, "y2": 0},
    ]
    openings = [{"opening_id": "d1", "type": "door", "width_mm": 900, "swing": "left", "wall_id": "GONE"}]
    payload = build_extrude_payload(walls, openings, wall_height_mm=3000)
    assert len(payload["walls"]) == 5
    assert all(w["height_mm"] == 3000 for w in payload["walls"])
    assert payload["walls"][0]["wall_id"] == "a"
    assert len(payload["openings"]) == 1
    assert payload["openings"][0]["opening_id"] == "d1"
    assert payload["slab"]["max_x"] == 4000
    assert payload["warnings"] == []


def test_empty_walls_raise_no_walls():
    with pytest.raises(AutocadError) as ei:
        build_extrude_payload([], [])
    assert ei.value.code == "no_walls"
