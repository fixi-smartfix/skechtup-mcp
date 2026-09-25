from __future__ import annotations

import os

import httpx

from errors import SketchupError

_transport: httpx.AsyncBaseTransport | None = None


def _url() -> str:
    return os.getenv("SKETCHUP_MCP_URL", "http://127.0.0.1:8766").rstrip("/")


def _token() -> str:
    token = os.getenv("SKETCHUP_MCP_TOKEN", "").strip()
    if not token:
        raise SketchupError("sketchup_unavailable", "SKETCHUP_MCP_TOKEN is not set")
    return token


async def sketchup_post(path: str, payload: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_token()}"}
    url = f"{_url()}/{path.lstrip('/')}"
    try:
        async with httpx.AsyncClient(timeout=60, transport=_transport) as client:
            response = await client.post(url, json=payload or {}, headers=headers)
            response.raise_for_status()
            data = response.json()
    except SketchupError:
        raise
    except Exception as exc:
        raise SketchupError("sketchup_unavailable", str(exc)) from exc
    if not isinstance(data, dict):
        raise SketchupError("sketchup_unavailable", "SketchUp response is not an object")
    return data


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
    return await sketchup_post(
        "roof",
        {"kind": kind, "overhang_mm": overhang_mm, "pitch_deg": pitch_deg},
    )


async def sketchup_capture_preview(max_width: int = 1600) -> dict:
    return await sketchup_post("preview/capture", {"max_width": max_width})
