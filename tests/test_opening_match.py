from opening_match import CadOpening, Wall, match_openings


def _room_with_south_door_gap() -> list[Wall]:
    # South wall split around a 900mm door at x=1500..2400
    return [
        Wall("a", "exterior", 200, 0, 0, 1500, 0),
        Wall("b", "exterior", 200, 2400, 0, 4000, 0),
        Wall("c", "exterior", 200, 4000, 0, 4000, 3000),
        Wall("d", "exterior", 200, 4000, 3000, 0, 3000),
        Wall("e", "exterior", 200, 0, 3000, 0, 0),
    ]


def test_matches_door_in_colinear_gap():
    openings = [CadOpening("d1", "door", 900, swing="left", wall_id="DELETED")]
    matched, warnings = match_openings(_room_with_south_door_gap(), openings)
    assert warnings == []
    assert len(matched) == 1
    m = matched[0]
    assert m.opening_id == "d1"
    assert m.type == "door"
    assert m.swing == "left"
    assert m.z0 == 0
    assert m.z1 == 2100
    assert m.thickness_mm == 200
    xs = sorted([m.x1, m.x2])
    ys = sorted([m.y1, m.y2])
    assert xs == [1500, 2400]
    assert ys == [0, 0]


def test_aluminum_opening_uses_door_height():
    openings = [CadOpening("d1", "aluminum", 900)]
    matched, warnings = match_openings(_room_with_south_door_gap(), openings)
    assert warnings == []
    assert len(matched) == 1
    assert matched[0].z0 == 0
    assert matched[0].z1 == 2100


def test_unmatched_opening_when_width_wrong():
    openings = [CadOpening("d1", "door", 1800, swing="left")]
    matched, warnings = match_openings(_room_with_south_door_gap(), openings)
    assert matched == []
    assert any(w["code"] == "unmatched_opening" and w["opening_id"] == "d1" for w in warnings)
    assert any(w["code"] == "unmatched_gap" for w in warnings)


def test_parallel_offset_walls_are_not_a_gap():
    walls = [
        Wall("s", "exterior", 200, 0, 0, 4000, 0),
        Wall("n", "exterior", 200, 0, 3000, 4000, 3000),
    ]
    openings = [CadOpening("d1", "door", 4000)]
    matched, warnings = match_openings(walls, openings)
    assert matched == []
    assert any(w["code"] == "unmatched_opening" for w in warnings)
    assert not any(w["code"] == "unmatched_gap" for w in warnings)


def test_two_same_width_doors_bind_one_to_one():
    walls = [
        Wall("a", "exterior", 200, 0, 0, 1000, 0),
        Wall("b", "exterior", 200, 1900, 0, 4000, 0),
        Wall("c", "exterior", 200, 4000, 0, 4000, 1000),
        Wall("d", "exterior", 200, 4000, 1900, 4000, 3000),
        Wall("e", "exterior", 200, 4000, 3000, 0, 3000),
        Wall("f", "exterior", 200, 0, 3000, 0, 0),
    ]
    openings = [
        CadOpening("d1", "door", 900, swing="left"),
        CadOpening("d2", "door", 900, swing="right"),
    ]
    matched, warnings = match_openings(walls, openings)
    assert warnings == []
    assert {m.opening_id for m in matched} == {"d1", "d2"}
    spans = {tuple(sorted([(m.x1, m.y1), (m.x2, m.y2)])) for m in matched}
    assert ((1000, 0), (1900, 0)) in spans
    assert ((4000, 1000), (4000, 1900)) in spans


def test_window_uses_sill_and_height():
    openings = [CadOpening("w1", "window", 900, sill_mm=900)]
    matched, warnings = match_openings(_room_with_south_door_gap(), openings, window_height_mm=1400)
    assert warnings == []
    assert matched[0].z0 == 900
    assert matched[0].z1 == 2300


def test_ignores_cad_wall_id():
    openings = [CadOpening("d1", "door", 900, wall_id="no-such-wall")]
    matched, _ = match_openings(_room_with_south_door_gap(), openings)
    assert len(matched) == 1
