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
