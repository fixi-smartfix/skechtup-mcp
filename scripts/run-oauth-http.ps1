$ErrorActionPreference = "Stop"

$required = @(
    "MCP_PUBLIC_URL",
    "MCP_OAUTH_PASSWORD",
    "SKETCHUP_MCP_TOKEN",
    "AUTOCAD_MCP_TOKEN"
)

foreach ($name in $required) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, "Process"))) {
        throw "$name is required for SketchUp MCP OAuth HTTP mode."
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$server = Join-Path $repoRoot "server\server.py"

if (-not (Test-Path $python)) {
    throw "Python venv not found at $python. Run: py -3.11 -m venv .venv"
}

$env:MCP_TRANSPORT = "streamable-http"
$env:MCP_HTTP_PORT = "8788"
$env:MCP_SCOPE = "sketchup"

if ([string]::IsNullOrWhiteSpace($env:SKETCHUP_MCP_URL)) {
    $env:SKETCHUP_MCP_URL = "http://127.0.0.1:8766"
}
if ([string]::IsNullOrWhiteSpace($env:AUTOCAD_MCP_URL)) {
    $env:AUTOCAD_MCP_URL = "http://127.0.0.1:8765"
}

Write-Host "Starting SketchUp MCP OAuth HTTP on port $env:MCP_HTTP_PORT."
Write-Host "Cloudflare Tunnel origin must be http://127.0.0.1:8788, not SketchUp bridge :8766."
Write-Host "Public MCP endpoint: $($env:MCP_PUBLIC_URL.TrimEnd('/'))/mcp"

& $python $server
