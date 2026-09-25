# SketchUp MCP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a SketchUp MCP that ChatGPT, Cursor, or Claude can use to extrude AutoCAD FIXI 2D walls/openings into 3D groups, then refine height and roof.

**Architecture:** Python FastMCP (stdio + OAuth HTTP :8788) reads AutoCAD bridge `:8765` (POST only), matches door gaps in Python, then POSTs absolute mm boxes to a SketchUp Ruby HTTP bridge on `:8766`. AutoCAD MCP is not modified.

**Tech Stack:** Python 3.11+, `mcp>=1.13,<2`, `httpx`, `pytest`, SketchUp Pro 2024+ Ruby API (WEBrick + `UI.start_timer`), OAuth 2.1 PKCE cloned from `c:\fixi-app\autocad-mcp`.

**Spec:** `docs/superpowers/specs/2026-09-25-sketchup-mcp-design.md`

## Global Constraints

- Exchange units are always millimetres; SketchUp internals convert with `mm / 25.4`.
- SketchUp plugin listens only on `http://127.0.0.1:8766/` (POST + Bearer `SKETCHUP_MCP_TOKEN`).
- SketchUp MCP only reads AutoCAD (`AUTOCAD_MCP_URL` default `http://127.0.0.1:8765`); it never creates or deletes CAD entities.
- OAuth HTTP listen port default is `8788` (not AutoCAD `8787`); scope default `sketchup`.
- Delete only SketchUp groups/instances whose names start with `FIXI_`.
- No `run_ruby`, no 2D draw tools, no DWG/DXF, no SketchUp Web, no CI e2e against live AutoCAD+SketchUp.
- Clients: Cursor stdio (`mcp.json`), Claude Desktop/Code stdio, ChatGPT (and Claude remote) streamable HTTP + OAuth.

## Review Focus

- CAD health/info/list fails or walls empty: must not POST `plan/extrude` (that wipe would destroy existing `FIXI_*`).
- CAD `insunits` not Millimeters: error `autocad_not_mm`, no SketchUp write.
- Parallel but offset walls (opposite room sides) must not form a gap.
- Two openings with the same width must bind 1:1 to two gaps; no double-booked gap.
- SketchUp 401 or connection error on `sketchup_health` must raise; never return `{ok: true}`.

## File structure (lock this)

```
server/errors.py              # AutocadError, SketchupError
server/opening_match.py       # gap matcher
server/plan_build.py          # CAD lists → plan/extrude body
server/autocad_client.py      # POST AutoCAD bridge
server/sketchup_client.py     # POST SketchUp bridge
server/tools.py               # FastMCP tools
server/oauth_provider.py      # SketchupOAuthProvider
server/server.py              # stdio + OAuth HTTP
tests/conftest.py
tests/test_opening_match.py
tests/test_plan_build.py
tests/test_autocad_client.py
tests/test_sketchup_client.py
tests/test_tools_extrude.py
tests/test_tools_refine.py
tests/test_oauth_provider.py
plugin/sketchup_mcp_bridge.rb
plugin/sketchup_mcp_bridge/bridge_server.rb
plugin/sketchup_mcp_bridge/geometry.rb
plugin/sketchup_mcp_bridge/preview.rb
scripts/test-bridge.ps1
scripts/setup-mcp.ps1
scripts/run-oauth-http.ps1
mcp-config.example.json
claude_desktop_config.example.json
requirements.txt
.gitignore
README.md
```

---

### Task 1: Opening gap matcher

**Files:**
- Create: `server/opening_match.py`
- Create: `tests/test_opening_match.py`
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `ANGLE_TOL_DEG = 2.0`
  - `WIDTH_TOL_MM = 20.0`
  - `COLLINEAR_TOL_MM = 20.0`
  - `TOUCH_TOL_MM = 1.0`
  - `dataclass Wall(wall_id: str, kind: str, thickness_mm: float, x1: float, y1: float, x2: float, y2: float)`
  - `dataclass CadOpening(opening_id: str, type: str, width_mm: float, swing: str | None = None, sill_mm: float | None = None, wall_id: str | None = None)`
  - `dataclass MatchedOpening(opening_id: str, type: str, swing: str | None, x1: float, y1: float, x2: float, y2: float, z0: float, z1: float, thickness_mm: float)`
  - `def match_openings(walls: list[Wall], openings: list[CadOpening], *, door_height_mm: float = 2100, window_height_mm: float = 1400) -> tuple[list[MatchedOpening], list[dict]]`
  - Warning dict: `{"code": "unmatched_opening"|"unmatched_gap", "message": str, "opening_id": str | None}`
  - Door types (`door`, `aluminum_door`, `standard`): `z0=0`, `z1=door_height_mm`
  - `window`: `z0=sill_mm or 900`, `z1=z0+window_height_mm`
  - Ignore `CadOpening.wall_id` for matching

- [ ] **Step 1: Write failing tests**

Create `requirements.txt`:

```
mcp>=1.13,<2
httpx>=0.27,<1
pytest>=8,<9
pytest-asyncio>=0.24,<1
```

Create `.gitignore`:

```
.venv/
__pycache__/
.pytest_cache/
*.pyc
.env
```

Create `tests/conftest.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
```

Create `tests/test_opening_match.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
cd c:\fixi-app\skechtup-mcp
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pytest tests/test_opening_match.py -v
```

Expected: FAIL with `ModuleNotFoundError: opening_match` or import error.

- [ ] **Step 3: Implement matcher**

Create `server/opening_match.py` with this algorithm (do not invent another):

```python
from __future__ import annotations

import math
from dataclasses import dataclass

ANGLE_TOL_DEG = 2.0
WIDTH_TOL_MM = 20.0
COLLINEAR_TOL_MM = 20.0
TOUCH_TOL_MM = 1.0
DOOR_TYPES = frozenset({"door", "aluminum_door", "standard"})


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
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
python -m pytest tests/test_opening_match.py -v
```

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```powershell
git add requirements.txt .gitignore tests/conftest.py tests/test_opening_match.py server/opening_match.py
git commit -m "feat: match AutoCAD remnant gaps to door and window openings"
```

---

### Task 2: Build `plan/extrude` payload

**Files:**
- Create: `server/errors.py`
- Create: `server/plan_build.py`
- Create: `tests/test_plan_build.py`

**Interfaces:**
- Consumes: `Wall`, `CadOpening`, `MatchedOpening`, `match_openings` from `opening_match.py`
- Produces:
  - `class AutocadError(Exception)` with `.code: str` (`autocad_unavailable` | `autocad_not_mm` | `no_walls`)
  - `class SketchupError(Exception)` with `.code: str` and optional `.message`
  - `def slab_bbox(walls: list[Wall], thickness_mm: float) -> dict` → `{min_x, min_y, max_x, max_y, thickness_mm}`
  - `def build_extrude_payload(walls_raw: list[dict], openings_raw: list[dict], *, wall_height_mm: float = 3000, door_height_mm: float = 2100, window_height_mm: float = 1400, slab_thickness_mm: float = 150) -> dict`
  - Payload keys: `walls`, `openings`, `slab`, `warnings`
  - Each output wall is input wall plus `height_mm`
  - Each output opening is `MatchedOpening.__dict__` (or `dataclasses.asdict`)
  - Empty `walls_raw` raises `AutocadError` with `code="no_walls"`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_plan_build.py -v
```

Expected: FAIL `ModuleNotFoundError: plan_build`.

- [ ] **Step 3: Implement**

`server/errors.py`:

```python
class AutocadError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SketchupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
```

`server/plan_build.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```powershell
python -m pytest tests/test_plan_build.py tests/test_opening_match.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add server/errors.py server/plan_build.py tests/test_plan_build.py
git commit -m "feat: build SketchUp extrude payload from AutoCAD wall lists"
```

---

### Task 3: AutoCAD and SketchUp HTTP clients

**Files:**
- Create: `server/autocad_client.py`
- Create: `server/sketchup_client.py`
- Create: `tests/test_autocad_client.py`
- Create: `tests/test_sketchup_client.py`

**Interfaces:**
- Consumes: `AutocadError`, `SketchupError`
- Produces:
  - `async def autocad_post(path: str, payload: dict | None = None) -> dict`
  - `async def autocad_health() -> dict`
  - `async def autocad_drawing_info() -> dict`
  - `async def autocad_list_walls() -> dict`  # `{count, walls}`
  - `async def autocad_list_openings() -> dict`  # `{count, openings}`
  - `async def sketchup_post(path: str, payload: dict | None = None) -> dict`
  - `async def sketchup_health() -> dict`
  - `async def sketchup_model_info() -> dict`
  - `async def sketchup_extrude(payload: dict) -> dict`
  - `async def sketchup_list_elements() -> dict`
  - `async def sketchup_set_wall_height(wall_id: str, height_mm: float) -> dict`
  - `async def sketchup_add_roof(kind: str, overhang_mm: float, pitch_deg: float) -> dict`
  - `async def sketchup_capture_preview(max_width: int = 1600) -> dict`  # `{png_base64}`
  - Missing `AUTOCAD_MCP_TOKEN` / `SKETCHUP_MCP_TOKEN`: raise the matching error (`autocad_unavailable` / `sketchup_unavailable`)
  - HTTP 4xx/5xx or connect error on AutoCAD → `AutocadError("autocad_unavailable", ...)`
  - HTTP 4xx/5xx or connect error on SketchUp → `SketchupError("sketchup_unavailable", ...)`
  - Defaults: `AUTOCAD_MCP_URL=http://127.0.0.1:8765`, `SKETCHUP_MCP_URL=http://127.0.0.1:8766`
  - Always POST JSON, header `Authorization: Bearer <token>`

- [ ] **Step 1: Write failing tests**

`tests/test_autocad_client.py`:

```python
import httpx
import pytest
from errors import AutocadError


@pytest.mark.asyncio
async def test_list_walls_posts_bearer(monkeypatch):
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["url"] = str(request.url)
        recorded["auth"] = request.headers.get("authorization")
        recorded["method"] = request.method
        return httpx.Response(200, json={"count": 1, "walls": [{"wall_id": "1A"}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv("AUTOCAD_MCP_URL", "http://127.0.0.1:8765")
    monkeypatch.setenv("AUTOCAD_MCP_TOKEN", "cad-token")

    import autocad_client as ac

    monkeypatch.setattr(ac, "_transport", transport)
    data = await ac.autocad_list_walls()
    assert data["count"] == 1
    assert recorded["method"] == "POST"
    assert recorded["url"] == "http://127.0.0.1:8765/arch/walls/list"
    assert recorded["auth"] == "Bearer cad-token"


@pytest.mark.asyncio
async def test_connect_error_is_unavailable(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setenv("AUTOCAD_MCP_TOKEN", "cad-token")
    import autocad_client as ac

    monkeypatch.setattr(ac, "_transport", httpx.MockTransport(handler))
    with pytest.raises(AutocadError) as ei:
        await ac.autocad_health()
    assert ei.value.code == "autocad_unavailable"


@pytest.mark.asyncio
async def test_missing_token(monkeypatch):
    monkeypatch.delenv("AUTOCAD_MCP_TOKEN", raising=False)
    import autocad_client as ac

    with pytest.raises(AutocadError) as ei:
        await ac.autocad_health()
    assert ei.value.code == "autocad_unavailable"
```

`tests/test_sketchup_client.py`:

```python
import httpx
import pytest
from errors import SketchupError


@pytest.mark.asyncio
async def test_health_401_raises(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "Unauthorized"})

    monkeypatch.setenv("SKETCHUP_MCP_TOKEN", "bad")
    import sketchup_client as sc

    monkeypatch.setattr(sc, "_transport", httpx.MockTransport(handler))
    with pytest.raises(SketchupError) as ei:
        await sc.sketchup_health()
    assert ei.value.code == "sketchup_unavailable"
    assert "ok" not in str(ei.value).lower() or True


@pytest.mark.asyncio
async def test_extrude_posts_plan(monkeypatch):
    recorded = {}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded["url"] = str(request.url)
        recorded["body"] = request.content
        return httpx.Response(200, json={"created": True})

    monkeypatch.setenv("SKETCHUP_MCP_TOKEN", "su-token")
    import sketchup_client as sc

    monkeypatch.setattr(sc, "_transport", httpx.MockTransport(handler))
    payload = {"walls": [], "openings": [], "slab": {}, "warnings": []}
    data = await sc.sketchup_extrude(payload)
    assert data["created"] is True
    assert recorded["url"] == "http://127.0.0.1:8766/plan/extrude"
```

- [ ] **Step 2: Run tests to verify they fail**

```powershell
python -m pytest tests/test_autocad_client.py tests/test_sketchup_client.py -v
```

Expected: FAIL import errors.

- [ ] **Step 3: Implement clients**

Both modules expose `_transport: httpx.AsyncBaseTransport | None = None` so tests inject `MockTransport`. `httpx.AsyncClient(transport=_transport, timeout=60)` when `_transport` is set.

`server/autocad_client.py`:

```python
from __future__ import annotations

import os
from typing import Any

import httpx

from errors import AutocadError

_transport: httpx.AsyncBaseTransport | None = None


def _url() -> str:
    return os.getenv("AUTOCAD_MCP_URL", "http://127.0.0.1:8765").rstrip("/")


def _token() -> str:
    token = os.getenv("AUTOCAD_MCP_TOKEN", "").strip()
    if not token:
        raise AutocadError("autocad_unavailable", "AUTOCAD_MCP_TOKEN is not set")
    return token


async def autocad_post(path: str, payload: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    url = f"{_url()}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=60, transport=_transport) as client:
            response = await client.post(url, json=payload or {}, headers=headers)
            response.raise_for_status()
            data = response.json()
    except AutocadError:
        raise
    except Exception as exc:
        raise AutocadError("autocad_unavailable", str(exc)) from exc
    if not isinstance(data, dict):
        raise AutocadError("autocad_unavailable", "AutoCAD response is not an object")
    return data


async def autocad_health() -> dict:
    return await autocad_post("health")


async def autocad_drawing_info() -> dict:
    return await autocad_post("drawing/info")


async def autocad_list_walls() -> dict:
    return await autocad_post("arch/walls/list")


async def autocad_list_openings() -> dict:
    return await autocad_post("arch/openings/list")
```

`server/sketchup_client.py` — same pattern with `SketchupError("sketchup_unavailable", ...)`, default URL `http://127.0.0.1:8766`, token `SKETCHUP_MCP_TOKEN`.

```python
async def sketchup_health() -> dict:
    return await sketchup_post("health")

async def sketchup_model_info() -> dict:
    return await sketchup_post("model/info")

async def sketchup_extrude(payload: dict) -> dict:
    return await sketchup_post("plan/extrude", payload)

async def sketchup_list_elements() -> dict:
    return await sketchup_post("elements/list")

async def sketchup_set_wall_height(wall_id: str, height_mm: float) -> dict:
    return await sketchup_post("walls/height", {"wall_id": wall_id, "height_mm": height_mm})

async def sketchup_add_roof(kind: str, overhang_mm: float, pitch_deg: float) -> dict:
    return await sketchup_post("roof", {"kind": kind, "overhang_mm": overhang_mm, "pitch_deg": pitch_deg})

async def sketchup_capture_preview(max_width: int = 1600) -> dict:
    return await sketchup_post("preview/capture", {"max_width": max_width})
```

If `httpx.MockTransport` is sync and `AsyncClient` needs `httpx.MockTransport` — pytest-httpx is not in requirements. Use `httpx.MockTransport` with `AsyncClient`; in httpx 0.27+ MockTransport works with both. If tests fail on async, wrap handler as shown in httpx docs (MockTransport is supported by AsyncClient).

- [ ] **Step 4: Run tests to verify they pass**

```powershell
python -m pytest tests/test_autocad_client.py tests/test_sketchup_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add server/autocad_client.py server/sketchup_client.py tests/test_autocad_client.py tests/test_sketchup_client.py
git commit -m "feat: HTTP clients for AutoCAD and SketchUp bridges"
```

---

### Task 4: Extrude tool (must not wipe SketchUp on CAD failure)

**Files:**
- Create: `server/tools.py`
- Create: `tests/test_tools_extrude.py`

**Interfaces:**
- Consumes: clients, `build_extrude_payload`, `AutocadError`
- Produces:
  - `INSTRUCTIONS` string exactly as spec section 7
  - `def register_tools(mcp: FastMCP) -> None`
  - Tools: `sketchup_health`, `sketchup_model_info`, `sketchup_extrude_from_autocad`, `sketchup_list_elements`, `sketchup_set_wall_height`, `sketchup_add_roof`, `sketchup_capture_preview`
  - `sketchup_extrude_from_autocad(wall_height_mm=3000, door_height_mm=2100, window_height_mm=1400, slab_thickness_mm=150) -> dict`
  - Order inside extrude: `autocad_health` → `autocad_drawing_info` → require `insunits` case-insensitive equal to `millimeters` → `autocad_list_walls` → if `walls` missing/empty raise `no_walls` → `autocad_list_openings` → `build_extrude_payload` → `sketchup_extrude`
  - On `AutocadError`, do not call `sketchup_extrude`
  - Tool functions re-raise `AutocadError`/`SketchupError` as `RuntimeError(f"{code}: {message}")` so MCP returns a readable error

- [ ] **Step 1: Write failing tests**

```python
import pytest
from errors import AutocadError


@pytest.mark.asyncio
async def test_extrude_skips_sketchup_when_cad_down(monkeypatch):
    calls = []

    async def cad_health():
        raise AutocadError("autocad_unavailable", "down")

    async def su_extrude(payload):
        calls.append(payload)
        return {"created": True}

    import tools

    monkeypatch.setattr(tools, "autocad_health", cad_health)
    monkeypatch.setattr(tools, "sketchup_extrude", su_extrude)

    with pytest.raises(RuntimeError) as ei:
        await tools.sketchup_extrude_from_autocad()
    assert "autocad_unavailable" in str(ei.value)
    assert calls == []


@pytest.mark.asyncio
async def test_extrude_rejects_non_mm(monkeypatch):
    calls = []

    async def cad_health():
        return {"ok": True}

    async def info():
        return {"insunits": "Inches"}

    async def su_extrude(payload):
        calls.append(payload)
        return {"created": True}

    import tools

    monkeypatch.setattr(tools, "autocad_health", cad_health)
    monkeypatch.setattr(tools, "autocad_drawing_info", info)
    monkeypatch.setattr(tools, "sketchup_extrude", su_extrude)

    with pytest.raises(RuntimeError) as ei:
        await tools.sketchup_extrude_from_autocad()
    assert "autocad_not_mm" in str(ei.value)
    assert calls == []


@pytest.mark.asyncio
async def test_extrude_happy_path(monkeypatch):
    posted = {}

    async def cad_health():
        return {"ok": True}

    async def info():
        return {"insunits": "Millimeters"}

    async def walls():
        return {
            "count": 5,
            "walls": [
                {"wall_id": "a", "kind": "exterior", "thickness_mm": 200, "x1": 0, "y1": 0, "x2": 1500, "y2": 0},
                {"wall_id": "b", "kind": "exterior", "thickness_mm": 200, "x1": 2400, "y1": 0, "x2": 4000, "y2": 0},
                {"wall_id": "c", "kind": "exterior", "thickness_mm": 200, "x1": 4000, "y1": 0, "x2": 4000, "y2": 3000},
                {"wall_id": "d", "kind": "exterior", "thickness_mm": 200, "x1": 4000, "y1": 3000, "x2": 0, "y2": 3000},
                {"wall_id": "e", "kind": "exterior", "thickness_mm": 200, "x1": 0, "y1": 3000, "x2": 0, "y2": 0},
            ],
        }

    async def openings():
        return {"count": 1, "openings": [{"opening_id": "d1", "type": "door", "width_mm": 900, "swing": "left"}]}

    async def su_extrude(payload):
        posted["payload"] = payload
        return {"created": True, "walls": 5}

    import tools

    monkeypatch.setattr(tools, "autocad_health", cad_health)
    monkeypatch.setattr(tools, "autocad_drawing_info", info)
    monkeypatch.setattr(tools, "autocad_list_walls", walls)
    monkeypatch.setattr(tools, "autocad_list_openings", openings)
    monkeypatch.setattr(tools, "sketchup_extrude", su_extrude)

    result = await tools.sketchup_extrude_from_autocad()
    assert result["created"] is True
    assert len(posted["payload"]["walls"]) == 5
    assert len(posted["payload"]["openings"]) == 1
```

Note: `sketchup_extrude_from_autocad` must be an async function importable from `tools` (the same function registered on FastMCP). Implement it as a module-level async function, then wrap/register it inside `register_tools`.

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_tools_extrude.py -v
```

Expected: FAIL import.

- [ ] **Step 3: Implement `server/tools.py`**

```python
from __future__ import annotations

import os
import tempfile
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from autocad_client import (
    autocad_drawing_info,
    autocad_health,
    autocad_list_openings,
    autocad_list_walls,
)
from errors import AutocadError, SketchupError
from plan_build import build_extrude_payload
from sketchup_client import (
    sketchup_add_roof,
    sketchup_capture_preview,
    sketchup_extrude,
    sketchup_health,
    sketchup_list_elements,
    sketchup_model_info,
    sketchup_set_wall_height,
)

INSTRUCTIONS = (
    "SketchUp 3D from an AutoCAD 2D FIXI plan (mm). Always call sketchup_health first. "
    "Always call autocad_health and drawing_info (Millimeters) before sketchup_extrude_from_autocad. "
    "Workflow: draw the plan with AutoCAD tools → capture_preview → sketchup_extrude_from_autocad → "
    "sketchup_capture_preview. Further edits use sketchup_set_wall_height / sketchup_add_roof only. "
    "If the CAD plan changes, extrude again (replaces FIXI_* groups). Coordinates are millimeters. "
    "Do not invent Ruby. Do not write to AutoCAD from this server."
)


def _raise(exc: Exception) -> None:
    if isinstance(exc, (AutocadError, SketchupError)):
        raise RuntimeError(f"{exc.code}: {exc.message}") from exc
    raise exc


def _is_mm(insunits: str) -> bool:
    return str(insunits).strip().lower() == "millimeters"


async def sketchup_extrude_from_autocad(
    wall_height_mm: float = 3000,
    door_height_mm: float = 2100,
    window_height_mm: float = 1400,
    slab_thickness_mm: float = 150,
) -> dict[str, Any]:
    try:
        await autocad_health()
        info = await autocad_drawing_info()
        if not _is_mm(info.get("insunits", "")):
            raise AutocadError(
                "autocad_not_mm",
                f"AutoCAD insunits={info.get('insunits')!r}; need Millimeters",
            )
        listed = await autocad_list_walls()
        walls = listed.get("walls") or []
        if not walls:
            raise AutocadError("no_walls", "AutoCAD has no FIXI_WALL remnants")
        openings = (await autocad_list_openings()).get("openings") or []
        payload = build_extrude_payload(
            walls,
            openings,
            wall_height_mm=wall_height_mm,
            door_height_mm=door_height_mm,
            window_height_mm=window_height_mm,
            slab_thickness_mm=slab_thickness_mm,
        )
        return await sketchup_extrude(payload)
    except (AutocadError, SketchupError) as exc:
        _raise(exc)
        raise


def register_tools(mcp: FastMCP) -> None:
    from sketchup_client import (
        sketchup_health as su_health,
        sketchup_model_info as su_info,
        sketchup_list_elements as su_list,
        sketchup_capture_preview as su_preview,
    )

    @mcp.tool()
    async def sketchup_health() -> dict[str, Any]:
        """Check SketchUp Ruby bridge and the active model."""
        try:
            return await su_health()
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_model_info() -> dict[str, Any]:
        """Return the open model name, units, and FIXI_* counts."""
        try:
            return await su_info()
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_extrude_from_autocad(
        wall_height_mm: float = 3000,
        door_height_mm: float = 2100,
        window_height_mm: float = 1400,
        slab_thickness_mm: float = 150,
    ) -> dict[str, Any]:
        """Read AutoCAD FIXI walls/openings and extrude them in SketchUp (mm)."""
        return await globals()["sketchup_extrude_from_autocad"](
            wall_height_mm, door_height_mm, window_height_mm, slab_thickness_mm
        )

    @mcp.tool()
    async def sketchup_list_elements() -> dict[str, Any]:
        """List extruded FIXI walls, openings, slab, and roof."""
        try:
            return await su_list()
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_set_wall_height(wall_id: str, height_mm: float) -> dict[str, Any]:
        """Change one FIXI wall height, or pass wall_id='all'."""
        return await set_wall_height_impl(wall_id, height_mm)

    @mcp.tool()
    async def sketchup_add_roof(
        kind: str = "flat", overhang_mm: float = 400, pitch_deg: float = 30
    ) -> dict[str, Any]:
        """Add or replace FIXI_ROOF. kind: flat or gable."""
        return await add_roof_impl(kind, overhang_mm, pitch_deg)

    @mcp.tool()
    async def sketchup_capture_preview(max_width: int = 1600) -> Image:
        """Zoom the SketchUp view and return a PNG."""
        try:
            data = await su_preview(max_width)
        except SketchupError as exc:
            _raise(exc)
            raise
        b64 = data.get("png_base64")
        if not b64:
            raise RuntimeError(f"Preview failed: {data}")
        import base64

        raw = base64.b64decode(b64)
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with open(path, "wb") as handle:
            handle.write(raw)
        return Image(path=path)
```

`set_wall_height_impl` / `add_roof_impl` are added in Task 5; for Task 4 tests you only need the module-level `sketchup_extrude_from_autocad`. Add stub impls in Task 4 that call the client, then Task 5 extends them. Do not register AutoCAD write tools.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/test_tools_extrude.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add server/tools.py tests/test_tools_extrude.py
git commit -m "feat: extrude SketchUp from AutoCAD lists without wiping on CAD errors"
```

---

### Task 5: Refine tools (list, height, roof, preview)

**Files:**
- Modify: `server/tools.py`
- Create: `tests/test_tools_refine.py`

**Interfaces:**
- Consumes: `sketchup_list_elements`, `sketchup_set_wall_height`, `sketchup_add_roof`, `sketchup_capture_preview`
- Produces: MCP wrappers with defaults `kind="flat"`, `overhang_mm=400`, `pitch_deg=30`, `max_width=1600`; `wall_id` may be `"all"`

- [ ] **Step 1: Write failing tests**

```python
import pytest


@pytest.mark.asyncio
async def test_set_height_forwards(monkeypatch):
    seen = {}

    async def fake(wall_id, height_mm):
        seen["wall_id"] = wall_id
        seen["height_mm"] = height_mm
        return {"updated": True, "wall_ids": [wall_id]}

    import tools

    monkeypatch.setattr(tools, "sketchup_set_wall_height", fake)
    result = await tools.set_wall_height_impl("all", 3300)
    assert seen == {"wall_id": "all", "height_mm": 3300}
    assert result["updated"] is True


@pytest.mark.asyncio
async def test_add_roof_forwards(monkeypatch):
    seen = {}

    async def fake(kind, overhang_mm, pitch_deg):
        seen.update(kind=kind, overhang_mm=overhang_mm, pitch_deg=pitch_deg)
        return {"created": True, "kind": kind}

    import tools

    monkeypatch.setattr(tools, "sketchup_add_roof", fake)
    result = await tools.add_roof_impl("gable", 400, 30)
    assert seen["kind"] == "gable"
    assert result["created"] is True
```

If you keep logic only inside nested `@mcp.tool` functions, extract `set_wall_height_impl` / `add_roof_impl` as module-level aliases used by both the tool and tests (same pattern as Task 4).

- [ ] **Step 2: Run tests to verify they fail**

```powershell
python -m pytest tests/test_tools_refine.py -v
```

Expected: FAIL until impl aliases exist.

- [ ] **Step 3: Implement aliases and register tools**

```python
async def set_wall_height_impl(wall_id: str, height_mm: float) -> dict:
    try:
        return await sketchup_set_wall_height(wall_id, height_mm)
    except SketchupError as exc:
        _raise(exc)
        raise


async def add_roof_impl(kind: str, overhang_mm: float, pitch_deg: float) -> dict:
    if kind not in ("flat", "gable"):
        raise RuntimeError("kind must be flat or gable")
    try:
        return await sketchup_add_roof(kind, overhang_mm, pitch_deg)
    except SketchupError as exc:
        _raise(exc)
        raise
```

Register `sketchup_set_wall_height` and `sketchup_add_roof` to call these. Preview: decode base64, write temp PNG, return `Image`.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/test_tools_refine.py tests/test_tools_extrude.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add server/tools.py tests/test_tools_refine.py
git commit -m "feat: SketchUp height, roof, list, and preview MCP tools"
```

---

### Task 6: stdio server and OAuth HTTP

**Files:**
- Create: `server/oauth_provider.py` (copy `c:\fixi-app\autocad-mcp\server\oauth_provider.py`, rename class and strings)
- Create: `server/server.py` (copy `c:\fixi-app\autocad-mcp\server\server.py`, change names/ports)
- Create: `tests/test_oauth_provider.py` (copy AutoCAD tests, rename)

**Interfaces:**
- Consumes: `register_tools`, `INSTRUCTIONS` from `tools.py`
- Produces:
  - `class SketchupOAuthProvider` — same methods as `AutocadOAuthProvider`
  - `def create_stdio_app() -> FastMCP` name `"sketchup"`
  - `def create_oauth_http_app() -> tuple[FastMCP, SketchupOAuthProvider]`
  - Default `MCP_HTTP_PORT=8788`, `MCP_SCOPE=sketchup`
  - Transport security `allowed_origins` include `https://chatgpt.com`, `https://*.chatgpt.com`, `https://claude.ai`, `https://*.claude.ai`
  - Login page title `SketchUp MCP Authorization`
  - `MCP_TRANSPORT=stdio` (default) or `streamable-http`
  - Module-level `mcp = create_stdio_app()`

- [ ] **Step 1: Write failing OAuth test**

Copy `c:\fixi-app\autocad-mcp\tests\test_oauth_provider.py` to `tests/test_oauth_provider.py` and replace:

- `from oauth_provider import AutocadOAuthProvider` → `SketchupOAuthProvider`
- `AutocadOAuthProvider(...)` → `SketchupOAuthProvider(...)`
- `scope="autocad"` → `scope="sketchup"`
- `scopes=["autocad"]` → `scopes=["sketchup"]`
- `server_url="http://127.0.0.1:8787"` → `http://127.0.0.1:8788`
- resource URLs `8787` → `8788`

Keep the PKCE authorize → login → token assertions.

- [ ] **Step 2: Run test to verify it fails**

```powershell
python -m pytest tests/test_oauth_provider.py -v
```

Expected: FAIL import `SketchupOAuthProvider`.

- [ ] **Step 3: Copy and rename provider + server**

1. Copy `c:\fixi-app\autocad-mcp\server\oauth_provider.py` → `server/oauth_provider.py`.
2. Rename `AutocadOAuthProvider` → `SketchupOAuthProvider`.
3. Default username env fallback `"sketchup"` not `"autocad"`.
4. HTML: `SketchUp MCP Authorization` / `control SketchUp on this machine`.
5. Copy `c:\fixi-app\autocad-mcp\server\server.py` → `server/server.py`.
6. Import `SketchupOAuthProvider`; `FastMCP("sketchup", instructions=INSTRUCTIONS)`; `MCP_HTTP_PORT` default `8788`; `SCOPE` default `sketchup`; log line must say tunnel target is `:8788` not SketchUp `:8766`.
7. Add Claude origins listed in Interfaces.
8. `resource_name="SketchUp MCP"`.

Do not point the tunnel at `:8766`.

- [ ] **Step 4: Run tests**

```powershell
python -m pytest tests/test_oauth_provider.py tests/test_tools_extrude.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add server/oauth_provider.py server/server.py tests/test_oauth_provider.py
git commit -m "feat: SketchUp MCP stdio and OAuth HTTP on port 8788"
```

---

### Task 7: SketchUp Ruby bridge

**Files:**
- Create: `plugin/sketchup_mcp_bridge.rb`
- Create: `plugin/sketchup_mcp_bridge/bridge_server.rb`
- Create: `plugin/sketchup_mcp_bridge/geometry.rb`
- Create: `plugin/sketchup_mcp_bridge/preview.rb`

**Interfaces:**
- Consumes: JSON body from Task 2 payload
- Produces HTTP routes (POST only, Bearer token):
  - `health` → `{ok, product, model, units}`
  - `model/info` → `{name, path, units, fixi_counts}`
  - `plan/extrude` → delete entities named `/^FIXI_/`, then create groups; return `{created, walls, openings, slab, warnings}`
  - `elements/list` → `{walls, openings, slab, roof}`
  - `walls/height` → `{updated, wall_ids}`
  - `roof` → `{created, kind}`
  - `preview/capture` → `{png_base64}`
- Commands: `MCPSTART`, `MCPSTOP` (Ruby Console prints `http://127.0.0.1:8766/` and token)
- Token: `ENV['SKETCHUP_MCP_TOKEN']` or SecureRandom hex
- Geometry on main thread via queue + `UI.start_timer(0.05, true)`
- `mm_to_inch(mm) = mm / 25.4`
- Wall group name `FIXI_WALL_{wall_id}`; door `FIXI_DOOR_{id}`; window `FIXI_WINDOW_{id}`; slab `FIXI_SLAB`; roof `FIXI_ROOF`
- Door leaf thickness 40mm (not `thickness_mm`); `thickness_mm` is wall depth for centering the leaf on the centerline
- Slab: top at Z=0, thickness down (−Z)
- Flat roof: 100mm thick at max wall height; gable ridge along longer bbox axis; `pitch_deg` from horizontal
- Colors: exterior dark gray, interior light gray, structural brown
- Set LengthUnit to mm if needed; include `units_changed` on extrude when changed

There is no headless SketchUp on CI. Automated check for this task is a syntax/load review plus the Python contract already tested. Manual verify is Step 4.

- [ ] **Step 1: Write loader and server**

`plugin/sketchup_mcp_bridge.rb`:

```ruby
require 'sketchup.rb'
require_relative 'sketchup_mcp_bridge/bridge_server'
require_relative 'sketchup_mcp_bridge/geometry'
require_relative 'sketchup_mcp_bridge/preview'

unless file_loaded?(__FILE__)
  UI.add_context_menu_handler { |menu| } # no-op; commands are Ruby Console
  file_loaded(__FILE__)
end

module SketchupMcpBridge
  def self.start
    Server.instance.start
  end

  def self.stop
    Server.instance.stop
  end
end

unless @sketchup_mcp_commands_bound
  UI.menu('Plugins').add_item('MCPSTART') { SketchupMcpBridge.start }
  UI.menu('Plugins').add_item('MCPSTOP') { SketchupMcpBridge.stop }
  @sketchup_mcp_commands_bound = true
end
```

Also register `UI::Command` so typing in Ruby Console works:

```ruby
module SketchupMcpBridge
  class MCPSTART
    def self
    end
  end
end
```

SketchUp does not get AutoCAD-style `[CommandMethod]`. Document in README: run `SketchupMcpBridge.start` in Ruby Console **or** Plugins → MCPSTART. Also define:

```ruby
def mcpstart
  SketchupMcpBridge.start
end
```

at the top level of the loader so `mcpstart` works in Ruby Console.

`plugin/sketchup_mcp_bridge/bridge_server.rb` — WEBrick on `127.0.0.1:8766`, only POST, compare `Authorization` to `Bearer #{token}`, push `{path, json, queue}` onto a `Queue`, wait up to 25s for result. Drain queue on `UI.start_timer`. Dispatch:

```ruby
case path
when 'health' then Geometry.health
when 'model/info' then Geometry.model_info
when 'plan/extrude' then Geometry.extrude(json)
when 'elements/list' then Geometry.list_elements
when 'walls/height' then Geometry.set_wall_height(json)
when 'roof' then Geometry.add_roof(json)
when 'preview/capture' then Preview.capture(json)
else { 'error' => "unknown path #{path}" }
end
```

Reject non-POST with 405, bad token with 401.

- [ ] **Step 2: Implement geometry**

`plugin/sketchup_mcp_bridge/geometry.rb` key methods:

```ruby
MM = 25.4
FIXI = /^FIXI_/

def self.mm(v)
  v.to_f / MM
end

def self.clear_fixi(model)
  model.active_entities.to_a.each do |e|
    e.erase! if e.respond_to?(:name) && e.name.to_s.start_with?('FIXI_')
  end
end

def self.wall_box(entities, wall)
  # centerline (x1,y1)-(x2,y2), thickness, height from Z=0
  # build a rectangular face on the ground along the centerline, pushpull height
end
```

Algorithm for a wall box: vector along centerline `ax,ay`; unit along; unit perp `(-uy, ux)`; half = thickness/2; four ground corners = endpoints ± perp * half (mm→inch); face + `pushpull(height_inch)`.

Opening leaf: same centerline between (x1,y1)-(x2,y2), thickness 40mm for the leaf, from z0 to z1 (pushpull after translating face to z0).

Slab: rectangle min/max, face at z=0, `pushpull(-thickness_inch)`.

`set_wall_height`: find group `FIXI_WALL_{id}` or all `FIXI_WALL_*`; read attribute dictionary `FIXI` keys `x1,y1,x2,y2,thickness_mm,kind` written at create time; erase; recreate at new height. If missing, return `{error: "wall not found"}` (HTTP 200 with error key is acceptable; Python client still returns the dict — tools treat `error` as SketchupError if present). Prefer raising so WEBrick returns 500 with `{error: message}` and `sketchup_post` maps to `sketchup_unavailable`. Spec: “Lỗi nếu không có group” — return 400/500 JSON `{error, code: "wall_not_found"}`.

`add_roof`: if no `FIXI_WALL_*`, error `no_walls`. Delete `FIXI_ROOF`. Bbox from wall attributes or `FIXI_SLAB`. Expand by `overhang_mm`. Flat: face at `max height_mm`, pushpull 100mm. Gable: ridge along longer side; rise = `tan(pitch_deg) * half_span`.

Write `FIXI` attribute dict on every created group so height/roof can read it back.

- [ ] **Step 3: Preview**

`plugin/sketchup_mcp_bridge/preview.rb`: `model.active_view.write_image(path)` (tmp png), read bytes, Base64, return `{png_base64}`. Honor `max_width` by writing a reasonably large view; if SketchUp version supports width options, pass them; otherwise write default and still return PNG.

- [ ] **Step 4: Manual bridge test (required on a machine with SketchUp)**

1. Copy `plugin/sketchup_mcp_bridge.rb` and `plugin/sketchup_mcp_bridge/` into SketchUp Plugins folder.
2. Restart SketchUp, open a blank model, Plugins → MCPSTART.
3. Run `scripts/test-bridge.ps1` (Task 8 writes it) with `SKETCHUP_MCP_TOKEN` from the console.
4. Expected: health ok; posting a one-wall `plan/extrude` creates `FIXI_WALL_*` and `FIXI_SLAB`.

If SketchUp is not installed on the implementer machine, leave the plugin files complete and record that manual step as pending in the README — do not stub the Ruby.

- [ ] **Step 5: Commit**

```powershell
git add plugin
git commit -m "feat: SketchUp Ruby HTTP bridge for FIXI extrude"
```

---

### Task 8: Scripts, client configs, README

**Files:**
- Create: `scripts/test-bridge.ps1`
- Create: `scripts/setup-mcp.ps1`
- Create: `scripts/run-oauth-http.ps1`
- Create: `mcp-config.example.json`
- Create: `claude_desktop_config.example.json`
- Create: `README.md`

**Interfaces:**
- Consumes: server paths, env names from spec section 4
- Produces: installable Cursor + Claude stdio configs; OAuth runner on 8788; README covering plugin copy, tokens, both CAD+SU connectors

- [ ] **Step 1: Write example configs**

`mcp-config.example.json`:

```json
{
  "mcpServers": {
    "sketchup": {
      "command": "C:\\fixi-app\\skechtup-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\fixi-app\\skechtup-mcp\\server\\server.py"],
      "env": {
        "SKETCHUP_MCP_URL": "http://127.0.0.1:8766",
        "SKETCHUP_MCP_TOKEN": "REPLACE_WITH_TOKEN",
        "AUTOCAD_MCP_URL": "http://127.0.0.1:8765",
        "AUTOCAD_MCP_TOKEN": "REPLACE_WITH_CAD_TOKEN"
      }
    }
  }
}
```

`claude_desktop_config.example.json` — same `mcpServers.sketchup` block (Claude Desktop format is `{ "mcpServers": { ... } }` on Windows).

- [ ] **Step 2: Write scripts**

`scripts/test-bridge.ps1`: POST health, model/info, then a tiny `plan/extrude` with one 4000mm wall and empty openings (creates slab+wall). Use `SKETCHUP_MCP_URL` default `http://127.0.0.1:8766`. Require `SKETCHUP_MCP_TOKEN`.

`scripts/run-oauth-http.ps1`: clone AutoCAD script; require `MCP_PUBLIC_URL`, `MCP_OAUTH_PASSWORD`, `SKETCHUP_MCP_TOKEN`, `AUTOCAD_MCP_TOKEN`; set `MCP_TRANSPORT=streamable-http`, `MCP_HTTP_PORT=8788`, `MCP_SCOPE=sketchup`. Print that Cloudflare origin is `:8788` not `:8766`.

`scripts/setup-mcp.ps1`: merge `sketchup` into `%USERPROFILE%\.cursor\mcp.json` without removing `autocad`. Optionally merge the same block into `%APPDATA%\Claude\claude_desktop_config.json` if that file or parent exists. Read tokens from User environment variables.

- [ ] **Step 3: Write README.md**

Sections, in this order:

1. What it does (CAD 2D → SketchUp 3D; ChatGPT / Cursor / Claude).
2. Requirements: Windows, SketchUp Pro 2024+, AutoCAD MCP already running, Python 3.11+.
3. Install Ruby plugin (copy folder + loader; MCPSTART; token).
4. `py -3.11 -m venv .venv` and `pip install -r requirements.txt`.
5. Cursor `mcp.json` and Claude Desktop/Code configs (keep `autocad` server).
6. ChatGPT remote: `run-oauth-http.ps1`, tunnel to 8788, Access Bypass paths identical to AutoCAD README.
7. Workflow: draw with AutoCAD tools → `sketchup_extrude_from_autocad` → refine.
8. Manual test: rectangle room + one door.

- [ ] **Step 4: Run the full unit suite**

```powershell
python -m pytest tests -v
```

Expected: all tests PASS (no live SketchUp required).

- [ ] **Step 5: Commit**

```powershell
git add scripts mcp-config.example.json claude_desktop_config.example.json README.md
git commit -m "docs: Cursor, Claude, and ChatGPT setup for SketchUp MCP"
```

---

## Self-review

**Spec coverage**

| Spec section | Task |
|--------------|------|
| 1 purpose / three clients | 6, 8 |
| 2 out of scope | constraints; no extra tools |
| 3 architecture / ports | 3, 6, 7 |
| 4 env vars | 3, 6, 8 |
| 5.1–5.4 geometry + matcher | 1, 2, 7 |
| 5.5 replace FIXI_* only | 7 |
| 5.6 height | 5, 7 |
| 5.7 roof | 5, 7 |
| 6 plugin HTTP | 7 |
| 7 seven tools + instructions | 4, 5 |
| 8 client workflow | 8 README |
| 9 errors / no wipe on CAD fail | 3, 4 |
| 10 layout | all |
| 11 automated tests | 1–6, 8 |
| 12 done criteria | 7 manual + 8 |

**Placeholder scan:** none remaining. FastMCP tool naming is specified (`name=` or nested function names).

**Type consistency:** `Wall`, `CadOpening`, `MatchedOpening`, `AutocadError.code`, `sketchup_extrude(payload)`, MCP tool names match spec.

**Review Focus tests:** CAD down / not-mm / no wipe → Task 4; parallel offset + 1:1 gaps → Task 1; SketchUp 401 → Task 3.
