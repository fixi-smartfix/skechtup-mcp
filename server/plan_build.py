from __future__ import annotations

from dataclasses import asdict

from errors import AutocadError
from opening_match import CadOpening, Wall, match_openings


def slab_bbox(walls: list[Wall], thickness_mm: float) -> dict:
    xs = [c for w in walls for c in (w.x1, w.x2)]
    ys = [c for w in walls for c in (w.y1, w.y2)]
    return {
        "min_x": min(xs),
        "min_y": min(ys),
        "max_x": max(xs),
        "max_y": max(ys),
        "thickness_mm": thickness_mm,
    }


def _wall(raw: dict) -> Wall:
    return Wall(
        wall_id=str(raw["wall_id"]),
        kind=str(raw.get("kind", "exterior")),
        thickness_mm=float(raw["thickness_mm"]),
        x1=float(raw["x1"]),
        y1=float(raw["y1"]),
        x2=float(raw["x2"]),
        y2=float(raw["y2"]),
    )


def _opening(raw: dict) -> CadOpening:
    return CadOpening(
        opening_id=str(raw["opening_id"]),
        type=str(raw.get("type", "door")),
        width_mm=float(raw["width_mm"]),
        swing=raw.get("swing"),
        sill_mm=raw.get("sill_mm"),
        wall_id=raw.get("wall_id"),
    )


def build_extrude_payload(
    walls_raw: list[dict],
    openings_raw: list[dict],
    *,
    wall_height_mm: float = 3000,
    door_height_mm: float = 2100,
    window_height_mm: float = 1400,
    slab_thickness_mm: float = 150,
) -> dict:
    if not walls_raw:
        raise AutocadError("no_walls", "AutoCAD has no FIXI_WALL remnants")
    walls = [_wall(w) for w in walls_raw]
    openings = [_opening(o) for o in openings_raw]
    matched, warnings = match_openings(
        walls, openings, door_height_mm=door_height_mm, window_height_mm=window_height_mm
    )
    out_walls = []
    for w in walls:
        item = asdict(w)
        item["height_mm"] = wall_height_mm
        out_walls.append(item)
    return {
        "walls": out_walls,
        "openings": [asdict(m) for m in matched],
        "slab": slab_bbox(walls, slab_thickness_mm),
        "warnings": warnings,
    }
