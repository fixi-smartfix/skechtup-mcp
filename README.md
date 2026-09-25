# SketchUp MCP Bridge

## 1. What it does

This project lets ChatGPT, Cursor, or Claude turn an AutoCAD 2D FIXI floor plan into SketchUp 3D geometry. The normal flow is: use the existing AutoCAD MCP connector to draw walls, doors, and windows in millimeters, then use this SketchUp MCP connector to extrude those CAD wall remnants into SketchUp walls, slab, openings, and roof helpers.

Cursor and Claude Desktop/Code use stdio MCP. ChatGPT uses the same server through streamable HTTP with OAuth.

## 2. Requirements

- Windows.
- SketchUp Pro 2024+ desktop.
- AutoCAD MCP already running on `http://127.0.0.1:8765`.
- Python 3.11+.
- Two tokens: `SKETCHUP_MCP_TOKEN` for the SketchUp Ruby bridge and `AUTOCAD_MCP_TOKEN` for the AutoCAD bridge.

## 3. Install Ruby plugin

Copy both plugin items into your SketchUp Plugins folder:

- `plugin/sketchup_mcp_bridge.rb`
- `plugin/sketchup_mcp_bridge/`

For SketchUp 2024 on Windows, the folder is usually:

```powershell
%APPDATA%\SketchUp\SketchUp 2024\SketchUp\Plugins
```

Restart SketchUp. In SketchUp, open the Ruby Console and run:

```ruby
MCPSTART
```

The bridge listens on `http://127.0.0.1:8766` and prints `SKETCHUP_MCP_TOKEN=...`. Use that value in your MCP client config or set `SKETCHUP_MCP_TOKEN` before starting SketchUp if you want a fixed token. Stop the bridge with:

```ruby
MCPSTOP
```

## 4. Python server setup

From this repo:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The stdio entrypoint is:

```powershell
.\.venv\Scripts\python.exe .\server\server.py
```

## 5. Cursor and Claude configs

Keep your existing `autocad` MCP server entry. Add `sketchup` beside it; do not replace the whole file.

Cursor config lives at:

```powershell
%USERPROFILE%\.cursor\mcp.json
```

Claude Desktop config lives at:

```powershell
%APPDATA%\Claude\claude_desktop_config.json
```

Claude Code can use the same `mcpServers.sketchup` block in a repo or user `.mcp.json`.

Example files are included:

- `mcp-config.example.json`
- `claude_desktop_config.example.json`

You can also set user environment variables `SKETCHUP_MCP_TOKEN` and `AUTOCAD_MCP_TOKEN`, then run:

```powershell
.\scripts\setup-mcp.ps1
```

That script merges only `mcpServers.sketchup` and preserves existing servers such as `autocad`.

## 6. ChatGPT remote

For ChatGPT, run the MCP server in OAuth HTTP mode:

```powershell
$env:MCP_PUBLIC_URL = "https://your-tunnel.example.com"
$env:MCP_OAUTH_PASSWORD = "use-a-strong-password"
$env:SKETCHUP_MCP_TOKEN = "your-sketchup-token"
$env:AUTOCAD_MCP_TOKEN = "your-autocad-token"
.\scripts\run-oauth-http.ps1
```

The script sets:

- `MCP_TRANSPORT=streamable-http`
- `MCP_HTTP_PORT=8788`
- `MCP_SCOPE=sketchup`

Point your Cloudflare Tunnel origin to `http://127.0.0.1:8788`, not the SketchUp bridge on `:8766`. In ChatGPT, add the connector at:

```text
https://your-tunnel.example.com/mcp
```

Use the same Cloudflare Access Bypass paths as the AutoCAD MCP remote setup, including `/mcp`, `/login`, `/login/callback`, `/.well-known/oauth-authorization-server`, and `/.well-known/oauth-protected-resource`.

## 7. Workflow

1. Start AutoCAD MCP and confirm the drawing units are Millimeters.
2. Start SketchUp and run `MCPSTART`.
3. In Cursor, Claude, or ChatGPT, draw the plan with AutoCAD tools.
4. Preview the 2D plan with AutoCAD `capture_preview`.
5. Run `sketchup_extrude_from_autocad`.
6. Preview the 3D model with `sketchup_capture_preview`.
7. Refine with `sketchup_set_wall_height` or `sketchup_add_roof`.

If the CAD plan changes, run `sketchup_extrude_from_autocad` again. It replaces only SketchUp groups/components named `FIXI_*`.

## 8. Manual test

Create a simple rectangular room in AutoCAD, in millimeters:

1. Use `ensure_arch_layers`.
2. Draw four walls for a 4000 mm by 3000 mm room.
3. Add one door on one wall.
4. Confirm AutoCAD `drawing_info` reports `Millimeters`.
5. Run `sketchup_health`.
6. Run `sketchup_extrude_from_autocad`.
7. Run `sketchup_capture_preview` and verify the slab, four walls, and door appear in SketchUp.

For a direct Ruby bridge smoke test after `MCPSTART`, set `SKETCHUP_MCP_TOKEN` and run:

```powershell
.\scripts\test-bridge.ps1
```
