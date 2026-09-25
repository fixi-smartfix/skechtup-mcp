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
