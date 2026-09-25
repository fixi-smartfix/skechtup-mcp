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


@pytest.mark.asyncio
async def test_add_roof_rejects_invalid_kind():
    import tools

    with pytest.raises(RuntimeError, match="kind must be flat or gable"):
        await tools.add_roof_impl("hip", 400, 30)
