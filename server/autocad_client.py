from __future__ import annotations

import os

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
