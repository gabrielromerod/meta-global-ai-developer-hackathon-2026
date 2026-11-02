<#
.SYNOPSIS
  Vigil task runner for Windows. Same targets as the Makefile (used by CI and Linux).
.EXAMPLE
  pwsh scripts/tasks.ps1 test        # PowerShell 7
  powershell -File scripts/tasks.ps1 test   # Windows PowerShell 5.1
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet('setup', 'lint', 'format', 'test', 'e2e', 'demo', 'eval', 'export', 'scan', 'help')]
    [string]$Task = 'help'
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)

# ffmpeg installed by winget lands here; new shells may not have it on PATH yet.
$wingetLinks = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links'
if ((Test-Path $wingetLinks) -and ($env:PATH -notlike "*$wingetLinks*")) {
    $env:PATH = "$wingetLinks;$env:PATH"
}

function Invoke-Step([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

switch ($Task) {
    'setup'  { Invoke-Step uv @('sync') }
    'lint'   { Invoke-Step uv @('run', 'ruff', 'check', '.'); Invoke-Step uv @('run', 'ruff', 'format', '--check', '.') }
    'format' { Invoke-Step uv @('run', 'ruff', 'format', '.'); Invoke-Step uv @('run', 'ruff', 'check', '--fix', '.') }
    'test'   { Invoke-Step uv @('run', 'pytest') }
    'e2e'    { Invoke-Step uv @('run', 'playwright', 'install', 'chromium'); Invoke-Step uv @('run', 'pytest', '-m', 'e2e', 'tests/e2e') }
    'demo'   { Invoke-Step uv @('run', 'vigil', 'serve', '--host', '127.0.0.1', '--port', '8000') }
    'eval'   { Invoke-Step uv @('run', 'vigil', 'eval') }
    'export' { Invoke-Step uv @('run', 'vigil', 'export') }
    'scan'   { Invoke-Step uv @('run', 'python', 'scripts/privacy_scan.py', 'demo'); Invoke-Step bash @('scripts/metadata_scan.sh', 'demo') }
    'help'   { Write-Output 'Targets: setup lint format test e2e demo eval export scan' }
}
