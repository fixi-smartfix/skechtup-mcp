from __future__ import annotations

import math
from dataclasses import dataclass

ANGLE_TOL_DEG = 2.0
WIDTH_TOL_MM = 20.0
COLLINEAR_TOL_MM = 20.0
TOUCH_TOL_MM = 1.0
DOOR_TYPES = frozenset({"door", "aluminum", "aluminum_door", "standard"})


@dataclass
class Wall:
    wall_id: str
    kind: str
    thickness_mm: float
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class CadOpening:
    opening_id: str
    type: str
    width_mm: float
    swing: str | None = None
    sill_mm: float | None = None
    wall_id: str | None = None


@dataclass
class MatchedOpening:
    opening_id: str
    type: str
    swing: str | None
    x1: float
    y1: float
    x2: float
    y2: float
    z0: float
    z1: float
    thickness_mm: float


def _hypot(x: float, y: float) -> float:
    return math.hypot(x, y)


def _unit(x: float, y: float) -> tuple[float, float]:
    n = _hypot(x, y)
    if n < 1e-9:
        return (1.0, 0.0)
    return (x / n, y / n)


def _dir(w: Wall) -> tuple[float, float]:
    return (w.x2 - w.x1, w.y2 - w.y1)


def _nearly_parallel(a: Wall, b: Wall) -> bool:
    ua = _unit(*_dir(a))
    ub = _unit(*_dir(b))
    dot = abs(ua[0] * ub[0] + ua[1] * ub[1])
    return dot >= math.cos(math.radians(ANGLE_TOL_DEG))


def _colinear(a: Wall, b: Wall) -> bool:
    if not _nearly_parallel(a, b):
        return False
    ux, uy = _unit(*_dir(a))
    dx, dy = b.x1 - a.x1, b.y1 - a.y1
    return abs(ux * dy - uy * dx) <= COLLINEAR_TOL_MM


def _endpoints(w: Wall) -> list[tuple[float, float]]:
    return [(w.x1, w.y1), (w.x2, w.y2)]


def _gaps(walls: list[Wall]) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    gaps: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    for i, a in enumerate(walls):
        for b in walls[i + 1 :]:
            if not _colinear(a, b):
                continue
            best_d = 1e18
            best_pair: tuple[tuple[float, float], tuple[float, float]] | None = None
            for p in _endpoints(a):
                for q in _endpoints(b):
                    d = _hypot(p[0] - q[0], p[1] - q[1])
                    if d < best_d:
                        best_d = d
                        best_pair = (p, q)
            if best_pair is None or best_d < TOUCH_TOL_MM:
                continue
            gaps.append((best_pair[0], best_pair[1], max(a.thickness_mm, b.thickness_mm)))
    return gaps


def _is_door(typ: str) -> bool:
    return typ in DOOR_TYPES or typ != "window"


def match_openings(
    walls: list[Wall],
    openings: list[CadOpening],
    *,
    door_height_mm: float = 2100,
    window_height_mm: float = 1400,
) -> tuple[list[MatchedOpening], list[dict]]:
    gaps = _gaps(walls)
    used: set[int] = set()
    matched: list[MatchedOpening] = []
    warnings: list[dict] = []

    for op in openings:
        best_i = -1
        best_err = 1e18
        for i, (p, q, _th) in enumerate(gaps):
            if i in used:
                continue
            length = _hypot(p[0] - q[0], p[1] - q[1])
            err = abs(length - op.width_mm)
            if err <= WIDTH_TOL_MM and err < best_err:
                best_err = err
                best_i = i
        if best_i < 0:
            warnings.append(
                {
                    "code": "unmatched_opening",
                    "message": f"No remnant gap within {WIDTH_TOL_MM}mm of width {op.width_mm}",
                    "opening_id": op.opening_id,
                }
            )
            continue
        used.add(best_i)
        p, q, th = gaps[best_i]
        if _is_door(op.type):
            z0, z1 = 0.0, float(door_height_mm)
        else:
            z0 = float(op.sill_mm if op.sill_mm is not None else 900)
            z1 = z0 + float(window_height_mm)
        matched.append(
            MatchedOpening(
                opening_id=op.opening_id,
                type=op.type,
                swing=op.swing,
                x1=p[0],
                y1=p[1],
                x2=q[0],
                y2=q[1],
                z0=z0,
                z1=z1,
                thickness_mm=th,
            )
        )

    for i, (p, q, _th) in enumerate(gaps):
        if i in used:
            continue
        warnings.append(
            {
                "code": "unmatched_gap",
                "message": f"Unused gap {p}->{q}",
                "opening_id": None,
            }
        )
    return matched, warnings
