$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
$server = Join-Path $repoRoot "server\server.py"

$sketchupToken = [Environment]::GetEnvironmentVariable("SKETCHUP_MCP_TOKEN", "User")
$autocadToken = [Environment]::GetEnvironmentVariable("AUTOCAD_MCP_TOKEN", "User")
$sketchupUrl = [Environment]::GetEnvironmentVariable("SKETCHUP_MCP_URL", "User")
$autocadUrl = [Environment]::GetEnvironmentVariable("AUTOCAD_MCP_URL", "User")

if ([string]::IsNullOrWhiteSpace($sketchupToken)) {
    throw "User environment variable SKETCHUP_MCP_TOKEN is required."
}
if ([string]::IsNullOrWhiteSpace($autocadToken)) {
    throw "User environment variable AUTOCAD_MCP_TOKEN is required."
}
if ([string]::IsNullOrWhiteSpace($sketchupUrl)) {
    $sketchupUrl = "http://127.0.0.1:8766"
}
if ([string]::IsNullOrWhiteSpace($autocadUrl)) {
    $autocadUrl = "http://127.0.0.1:8765"
}

$sketchupBlock = [ordered]@{
    command = $python
    args = @($server)
    env = [ordered]@{
        SKETCHUP_MCP_URL = $sketchupUrl
        SKETCHUP_MCP_TOKEN = $sketchupToken
        AUTOCAD_MCP_URL = $autocadUrl
        AUTOCAD_MCP_TOKEN = $autocadToken
    }
}

function Read-JsonObject {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path $Path) {
        $content = Get-Content -LiteralPath $Path -Raw
        if (-not [string]::IsNullOrWhiteSpace($content)) {
            return $content | ConvertFrom-Json
        }
    }

    return [pscustomobject]@{}
}

function Merge-SketchupServer {
    param([Parameter(Mandatory = $true)][string]$Path)

    $parent = Split-Path -Parent $Path
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent | Out-Null
    }

    $config = Read-JsonObject -Path $Path
    if (-not $config.PSObject.Properties["mcpServers"]) {
        $config | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([pscustomobject]@{})
    }

    $servers = $config.mcpServers
    if (-not $servers.PSObject.Properties["sketchup"]) {
        $servers | Add-Member -MemberType NoteProperty -Name "sketchup" -Value ([pscustomobject]$sketchupBlock)
    } else {
        $servers.PSObject.Properties["sketchup"].Value = [pscustomobject]$sketchupBlock
    }

    $config | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
    Write-Host "Merged sketchup MCP server into $Path"
}

$cursorConfig = Join-Path $env:USERPROFILE ".cursor\mcp.json"
Merge-SketchupServer -Path $cursorConfig

$claudeDir = Join-Path $env:APPDATA "Claude"
$claudeConfig = Join-Path $claudeDir "claude_desktop_config.json"
if ((Test-Path $claudeConfig) -or (Test-Path $claudeDir)) {
    Merge-SketchupServer -Path $claudeConfig
} else {
    Write-Host "Skipped Claude Desktop config; $claudeDir does not exist."
}

Write-Host "Done. Existing MCP servers such as autocad were preserved."
