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
