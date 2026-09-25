import asyncio

from mcp.server.fastmcp import FastMCP


def test_register_tools_includes_extrude_from_autocad():
    from tools import register_tools

    app = FastMCP("test")
    register_tools(app)

    names = {tool.name for tool in asyncio.run(app.list_tools())}
    assert "sketchup_extrude_from_autocad" in names
