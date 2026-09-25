param(
    [string]$SketchupUrl = $env:SKETCHUP_MCP_URL
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SketchupUrl)) {
    $SketchupUrl = "http://127.0.0.1:8766"
}
$SketchupUrl = $SketchupUrl.TrimEnd("/")

if ([string]::IsNullOrWhiteSpace($env:SKETCHUP_MCP_TOKEN)) {
    throw "SKETCHUP_MCP_TOKEN is required. Run MCPSTART in SketchUp and use the token printed in the Ruby Console."
}

$headers = @{
    Authorization = "Bearer $env:SKETCHUP_MCP_TOKEN"
}

function Invoke-SketchupBridge {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [hashtable]$Body = @{}
    )

    $json = $Body | ConvertTo-Json -Depth 10
    Invoke-RestMethod -Method Post -Uri "$SketchupUrl/$Path" -Headers $headers -ContentType "application/json" -Body $json
}

Write-Host "Testing SketchUp bridge at $SketchupUrl"

Write-Host "POST /health"
Invoke-SketchupBridge -Path "health" | ConvertTo-Json -Depth 10

Write-Host "POST /model/info"
Invoke-SketchupBridge -Path "model/info" | ConvertTo-Json -Depth 10

$payload = @{
    walls = @(
        @{
            wall_id = "manual_test_wall"
            kind = "exterior"
            thickness_mm = 200
            x1 = 0
            y1 = 0
            x2 = 4000
            y2 = 0
            height_mm = 3000
        }
    )
    openings = @()
    slab = @{
        min_x = 0
        min_y = -100
        max_x = 4000
        max_y = 100
        thickness_mm = 150
    }
    warnings = @()
}

Write-Host "POST /plan/extrude (one 4000mm wall, no openings)"
Invoke-SketchupBridge -Path "plan/extrude" -Body $payload | ConvertTo-Json -Depth 10
