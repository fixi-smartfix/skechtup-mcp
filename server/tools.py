from __future__ import annotations

import base64
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


async def set_wall_height_impl(wall_id: str, height_mm: float) -> dict[str, Any]:
    try:
        return await sketchup_set_wall_height(wall_id, height_mm)
    except SketchupError as exc:
        _raise(exc)
        raise


async def add_roof_impl(
    kind: str = "flat", overhang_mm: float = 400, pitch_deg: float = 30
) -> dict[str, Any]:
    if kind not in ("flat", "gable"):
        raise RuntimeError("kind must be flat or gable")
    try:
        return await sketchup_add_roof(kind, overhang_mm, pitch_deg)
    except SketchupError as exc:
        _raise(exc)
        raise


def register_tools(mcp: FastMCP) -> None:
    extrude_from_autocad_impl = sketchup_extrude_from_autocad

    @mcp.tool()
    async def sketchup_health() -> dict[str, Any]:
        """Check SketchUp Ruby bridge and the active model."""
        try:
            return await globals()["sketchup_health"]()
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_model_info() -> dict[str, Any]:
        """Return the open model name, units, and FIXI_* counts."""
        try:
            return await globals()["sketchup_model_info"]()
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
        return await extrude_from_autocad_impl(
            wall_height_mm, door_height_mm, window_height_mm, slab_thickness_mm
        )

    @mcp.tool()
    async def sketchup_list_elements() -> dict[str, Any]:
        """List extruded FIXI walls, openings, slab, and roof."""
        try:
            return await globals()["sketchup_list_elements"]()
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_set_wall_height(wall_id: str, height_mm: float) -> dict[str, Any]:
        """Change one FIXI wall height, or pass wall_id='all'."""
        try:
            return await set_wall_height_impl(wall_id, height_mm)
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_add_roof(
        kind: str = "flat", overhang_mm: float = 400, pitch_deg: float = 30
    ) -> dict[str, Any]:
        """Add or replace FIXI_ROOF. kind: flat or gable."""
        try:
            return await add_roof_impl(kind, overhang_mm, pitch_deg)
        except SketchupError as exc:
            _raise(exc)
            raise

    @mcp.tool()
    async def sketchup_capture_preview(max_width: int = 1600) -> Image:
        """Zoom the SketchUp view and return a PNG."""
        try:
            data = await globals()["sketchup_capture_preview"](max_width)
        except SketchupError as exc:
            _raise(exc)
            raise
        b64 = data.get("png_base64")
        if not b64:
            raise RuntimeError(f"Preview failed: {data}")

        raw = base64.b64decode(b64)
        fd, path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        with open(path, "wb") as handle:
            handle.write(raw)
        return Image(path=path)
