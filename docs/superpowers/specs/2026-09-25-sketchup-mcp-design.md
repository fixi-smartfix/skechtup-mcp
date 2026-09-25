# SketchUp MCP — dựng 3D từ mặt bằng AutoCAD

Ngày: 2026-09-25  
Trạng thái: chờ duyệt spec  
Repo: `c:\fixi-app\skechtup-mcp`

## 1. Mục đích

**ChatGPT, Cursor, hoặc Claude** đọc **ảnh bản vẽ** hoặc **câu lệnh tự nhiên**, vẽ **mặt bằng 2D trên AutoCAD** bằng `autocad-mcp` hiện có, rồi **đùn khối 3D trong SketchUp desktop** từ đúng dữ liệu tường/cửa của bridge AutoCAD. User có thể mô tả thêm trên cùng client đó để chỉnh SketchUp (chiều cao, mái).

Ba client dùng chung một server, hai transport:

| Client | Transport |
|--------|-----------|
| Cursor | stdio (`mcp.json`) |
| Claude Desktop / Claude Code | stdio (`claude_desktop_config.json` hoặc `.mcp.json`) |
| ChatGPT | streamable HTTP + OAuth 2.1 (tunnel `/mcp`) |
| Claude (connector remote, nếu bật MCP HTTP) | cùng endpoint OAuth với ChatGPT |

Thành công v1: một phòng chữ nhật + một cửa trên CAD → extrude ra tường/sàn/cửa trong SketchUp, cùng mm, cùng gốc → đổi cao tường → thêm mái bằng → hai ảnh preview khớp.

## 2. Ngoài phạm vi v1

- Gộp AutoCAD và SketchUp thành một MCP
- Xuất/nhập DWG–DXF
- SketchUp Web
- Revit / BIM
- Nội thất, ban công, tầng lầu, lan can
- Chạy Ruby tùy ý từ model
- Tự e2e AutoCAD+SketchUp trên CI

## 3. Kiến trúc

Hai connector riêng. Không sửa hành vi `autocad-mcp` trừ khi thiếu field bắt buộc (v1 không cần sửa).

```
ChatGPT / Cursor / Claude
  ├─ autocad MCP  → Python :8787 (OAuth) hoặc stdio → HTTP 127.0.0.1:8765 → plugin .NET AutoCAD
  └─ sketchup MCP → Python :8788 (OAuth) hoặc stdio → HTTP 127.0.0.1:8766 → plugin Ruby SketchUp
                                                              │
                                                              └─ đọc POST AutoCAD :8765
                                                                 arch/walls/list
                                                                 arch/openings/list
                                                                 drawing/info
                                                                 health
```

Thành phần mới trong repo này:

| Đơn vị | Việc | Phụ thuộc |
|--------|------|-----------|
| Plugin Ruby | HTTP localhost + token; đùn/xóa group `FIXI_*`; preview | SketchUp Pro desktop 2024+ (Ruby API, không Web) |
| `server/autocad_client.py` | Gọi bridge AutoCAD bằng token sẵn có | `AUTOCAD_MCP_URL`, `AUTOCAD_MCP_TOKEN` |
| `server/tools.py` | Đăng ký tool MCP | client AutoCAD + client SketchUp |
| `server/server.py` | stdio hoặc streamable-http + OAuth 2.1 | Clone `autocad-mcp/server/server.py` |
| `server/oauth_provider.py` | Auth Code + PKCE S256, DCR | Clone AutoCAD; scope `sketchup` |

SketchUp MCP **chỉ đọc** AutoCAD. Không tạo/xóa entity CAD.

## 4. Cấu hình

| Biến | Mặc định | Vai trò |
|------|----------|---------|
| `SKETCHUP_MCP_URL` | `http://127.0.0.1:8766` | Bridge plugin |
| `SKETCHUP_MCP_TOKEN` | (bắt buộc khi gọi) | Bearer; plugin đọc cùng biến hoặc tự sinh khi `MCPSTART` |
| `AUTOCAD_MCP_URL` | `http://127.0.0.1:8765` | Bridge CAD (đọc) |
| `AUTOCAD_MCP_TOKEN` | (bắt buộc khi extrude) | Token CAD hiện có |
| `MCP_PUBLIC_URL` | — | Bắt buộc khi chạy OAuth HTTP |
| `MCP_HTTP_HOST` / `MCP_HTTP_PORT` | `127.0.0.1` / `8788` | Cổng MCP remote (ChatGPT / Claude HTTP; tránh đụng AutoCAD `8787`) |
| `MCP_OAUTH_USERNAME` / `MCP_OAUTH_PASSWORD` | — | Đăng nhập OAuth |
| `MCP_SCOPE` | `sketchup` | Scope OAuth |

Tunnel Cloudflare trỏ tới `:8788`, không tới `:8766`. Giữ Access Bypass cho path OAuth/MCP như AutoCAD.

Cấu hình client (stdio, cùng command Python):

- Cursor: khối `sketchup` trong `%USERPROFILE%\.cursor\mcp.json`, giữ khối `autocad`.
- Claude Desktop: cùng khối trong `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
- Claude Code: cùng khối trong `.mcp.json` của repo hoặc user.

File mẫu: `mcp-config.example.json` (Cursor) và `claude_desktop_config.example.json` (Claude). Command/args/env giống nhau.

## 5. Hình học

### 5.1 Đơn vị và gốc

- Tọa độ trao đổi luôn **millimet**.
- SketchUp nội bộ dùng inch: plugin đổi `mm / 25.4` khi tạo điểm; tool MCP không nhận inch.
- Khi extrude: nếu model chưa đặt LengthUnit = mm, plugin đặt mm và trả `units_changed: true`.
- XY CAD = XY SketchUp, Z lên, **chung gốc**, không xoay, không scale.

### 5.2 Tường

Nguồn: `POST http://127.0.0.1:8765/arch/walls/list` → `{ count, walls: [{ wall_id, kind, thickness_mm, x1, y1, x2, y2 }] }`.

Đây là các **đoạn remnant đã cắt lỗ**. Mỗi đoạn → một group `FIXI_WALL_{wall_id}`: hộp theo tim, dày `thickness_mm`, cao `wall_height_mm` (mặc định 3000), đáy Z = 0.

`kind`:

- `exterior` — màu xám đậm
- `interior` — xám nhạt
- `structural` — nâu

Không đùn tường gốc đã bị xóa trên CAD.

### 5.3 Cửa / cửa sổ

Nguồn: `POST .../arch/openings/list` → `{ count, openings: [{ opening_id, type, swing?, wall_id, width_mm, distance_along_wall_mm, sill_mm? }] }`.

`wall_id` trên opening có thể trỏ tường gốc đã xóa. **Không dùng field này để tìm entity.** Matcher khe chạy trên Python (`server/opening_match.py`) trước khi gọi plugin:

1. Với mỗi cặp remnant thẳng hàng (cùng hướng trong sai số 2°), khoảng cách đầu-đầu gần nhất trong `[width_mm ± 20]`.
2. Mỗi opening khớp tối đa một khe; mỗi khe tối đa một opening.
3. Opening khớp được gửi plugin dưới dạng hộp tuyệt đối: `{ opening_id, type, swing, x1, y1, x2, y2, z0, z1, thickness_mm }`.
4. Cửa (`door` / `aluminum_door` / `standard`): group `FIXI_DOOR_{opening_id}` — tấm dày 40 mm, `z0=0`, `z1=door_height_mm` (2100). `swing` chỉ attribute (v1 không vẽ cung mở 3D).
5. Cửa sổ (`window`): `z0=sill_mm`, `z1=sill_mm + window_height_mm` (1400).
6. Không khớp: không gửi hộp đó cho plugin; thêm `warnings` (`unmatched_opening` hoặc `unmatched_gap`); vẫn đùn tường.

`aluminum` và `standard` cùng hình 3D; khác nhau ở attribute `type`.

### 5.4 Sàn

Một group `FIXI_SLAB`: hộp axis-aligned từ min/max mọi `(x1,y1,x2,y2)` của tường, dày `slab_thickness_mm` (150), mặt trên Z = 0 (dày xuống âm Z). Nếu không có tường: không tạo sàn, trả lỗi `no_walls`.

### 5.5 Đùn lại

`sketchup_extrude_from_autocad` xóa **chỉ** group (và component instance) có tên bắt đầu `FIXI_`, rồi dựng lại. Geometry user vẽ tay giữ nguyên.

### 5.6 Đổi cao tường

`sketchup_set_wall_height`:

- `wall_id` cụ thể: xóa group `FIXI_WALL_{id}`, đùn lại cùng tim/dày, cao mới. Lỗi nếu không có group.
- `wall_id = "all"`: mọi `FIXI_WALL_*`.
- Không tự sửa mái. Client gọi lại `sketchup_add_roof` nếu cần.

### 5.7 Mái

`sketchup_add_roof` xóa `FIXI_ROOF` cũ rồi tạo mới, phủ bbox sàn + `overhang_mm` mỗi cạnh.

- `kind=flat`: mặt phẳng tại `max(chiều cao tường hiện có)`, dày 100 mm.
- `kind=gable`: ridge dọc cạnh dài hơn của bbox; `pitch_deg` là góc mái so với mặt ngang (mặc định 30).

Không có tường `FIXI_WALL_*`: lỗi `no_walls`.

## 6. HTTP plugin SketchUp

Prefix: `http://127.0.0.1:8766/`. Chỉ POST. Header `Authorization: Bearer <token>`. Lệnh SketchUp API chạy trên main thread (hàng đợi + `UI.start_timer`), không gọi API model từ thread HTTP.

| Path | Body | Kết quả |
|------|------|---------|
| `health` | `{}` | `{ ok, product, model, units }` |
| `model/info` | `{}` | `{ name, path, units, fixi_counts }` |
| `plan/extrude` | `{ walls, openings, slab, warnings }` — walls từ CAD; openings đã khớp tọa độ tuyệt đối bởi Python; slab bbox do Python tính | `{ created, walls, openings, slab, warnings }` |
| `elements/list` | `{}` | `{ walls, openings, slab, roof }` |
| `walls/height` | `{ wall_id, height_mm }` | `{ updated, wall_ids }` |
| `roof` | `{ kind, overhang_mm, pitch_deg }` | `{ created, kind }` |
| `preview/capture` | `{ max_width }` | `{ png_base64 }` |

Plugin **không** gọi AutoCAD. MCP Python lấy walls/openings, chạy matcher, tính slab bbox, rồi POST `plan/extrude`.

Ví dụ body `plan/extrude` (rút gọn):

```json
{
  "walls": [
    {
      "wall_id": "1A",
      "kind": "exterior",
      "thickness_mm": 200,
      "x1": 0, "y1": 0, "x2": 4000, "y2": 0,
      "height_mm": 3000
    }
  ],
  "openings": [
    {
      "opening_id": "2B",
      "type": "door",
      "swing": "left",
      "x1": 1500, "y1": 0, "x2": 2400, "y2": 0,
      "z0": 0, "z1": 2100,
      "thickness_mm": 200
    }
  ],
  "slab": { "min_x": 0, "min_y": 0, "max_x": 4000, "max_y": 3000, "thickness_mm": 150 },
  "warnings": []
}
```

Lệnh SketchUp: `MCPSTART` / `MCPSTOP` (in URL + token ra Ruby Console).

## 7. Tool MCP

Hướng dẫn hệ thống (instructions):

> SketchUp 3D from an AutoCAD 2D FIXI plan (mm). Always call sketchup_health first. Always call autocad_health and drawing_info (Millimeters) before sketchup_extrude_from_autocad. Workflow: draw the plan with AutoCAD tools → capture_preview → sketchup_extrude_from_autocad → sketchup_capture_preview. Further edits use sketchup_set_wall_height / sketchup_add_roof only. If the CAD plan changes, extrude again (replaces FIXI_* groups). Coordinates are millimeters. Do not invent Ruby. Do not write to AutoCAD from this server.

| Tool | Tham số | Việc |
|------|---------|------|
| `sketchup_health` | — | Bridge SketchUp |
| `sketchup_model_info` | — | Tên, đơn vị, đếm `FIXI_*` |
| `sketchup_extrude_from_autocad` | `wall_height_mm=3000`, `door_height_mm=2100`, `window_height_mm=1400`, `slab_thickness_mm=150` | `drawing/info` CAD phải mm; `health` CAD ok; `walls/list` không rỗng; gọi plugin `plan/extrude` |
| `sketchup_list_elements` | — | Group đã đùn |
| `sketchup_set_wall_height` | `wall_id` (hoặc `"all"`), `height_mm` | Đổi cao |
| `sketchup_add_roof` | `kind=flat\|gable`, `overhang_mm=400`, `pitch_deg=30` | Mái |
| `sketchup_capture_preview` | `max_width=1600` | Ảnh PNG (MCP Image) |

Không có tool vẽ 2D, không `run_ruby`.

## 8. Luồng trên ChatGPT, Cursor, hoặc Claude

Cùng một kịch bản tool; khác nhau chỉ ở chỗ gắn MCP.

1. `autocad_health` + `drawing_info` (bắt buộc Millimeters).
2. `sketchup_health`.
3. Ảnh hoặc NL → AutoCAD: `ensure_arch_layers` → `create_wall` → cửa/cửa sổ → `capture_preview`.
4. User xác nhận mặt bằng → `sketchup_extrude_from_autocad` → `sketchup_capture_preview`.
5. Mô tả thêm → chỉ tool SketchUp.
6. Sửa mặt bằng CAD → extrude lại.

Mỗi client gắn **hai** server (`autocad` + `sketchup`). Không viết adapter riêng cho từng model.

## 9. Lỗi và an toàn

- Plugin tắt / sai token: `sketchup_health` fail; tool khác không giả thành công.
- CAD tắt, không mm, hoặc `walls.count = 0`: **không** xóa group SketchUp; trả lỗi (`autocad_unavailable` / `autocad_not_mm` / `no_walls`).
- Khe không khớp: đùn tường + `warnings[]`.
- HTTP chỉ `127.0.0.1`. Không No-Auth trên connector remote (ChatGPT / Claude HTTP).
- Token CAD và token SketchUp là hai secret khác nhau.

## 10. Bố cục repo

```
plugin/sketchup_mcp_bridge/   # extension Ruby (loader, HTTP, geometry, preview)
server/                       # server.py, tools.py, oauth_provider.py, autocad_client.py, sketchup_client.py
scripts/                      # test-bridge.ps1, setup-mcp.ps1, run-oauth-http.ps1
tests/                        # test client + khớp khe + OAuth (mock HTTP)
mcp-config.example.json
claude_desktop_config.example.json
requirements.txt
README.md
```

## 11. Kiểm thử

**Tự động (không cần SketchUp/AutoCAD):**

- `autocad_client` + `sketchup_client` với HTTP mock.
- Extrude khi CAD trống → lỗi, không gọi xóa phía SketchUp.
- Extrude 4 tường + 1 cửa (remnant + opening width khớp khe) → payload `plan/extrude` đúng.
- Opening không khớp → `opening_match.py` trả `warnings`; plugin không nhận opening đó.
- `set_wall_height` / `add_roof` forward đúng path/body.
- OAuth: metadata + từ chối request không Bearer (clone test AutoCAD).

Quyết định khóa: **matcher khe chạy trên Python** (`server/opening_match.py`). Plugin chỉ nhận opening đã có `x1,y1,x2,y2,z0,z1` tuyệt đối. Test matcher không cần Ruby.

**Thủ công:** `scripts/test-bridge.ps1` khi SketchUp đã `MCPSTART`. Kịch bản phòng chữ nhật + 1 cửa như mục 1.

## 12. Tiêu chí xong v1

- Cursor và Claude (stdio) gọi được 7 tool khi SketchUp + AutoCAD đang mở.
- ChatGPT (và Claude remote nếu dùng) thêm được connector `https://<tunnel>/mcp` (cổng 8788).
- Một mặt bằng FIXI trên CAD đùn ra group `FIXI_*` đúng mm.
- Đùn lần 2 thay `FIXI_*`, không xóa group khác.
- README đủ bước cài plugin, token, Cursor, Claude Desktop/Code, OAuth ChatGPT.
