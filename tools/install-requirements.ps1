param(
  [switch]$Upgrade = $false
)

Write-Host "Installing Python packages into embedded Python..."
$py = Join-Path $PSScriptRoot "..\python\python.exe"
if (-not (Test-Path $py)) {
  Write-Error "Embedded python not found at $py"
  exit 1
}

& $py -m pip install --upgrade pip setuptools wheel
& $py -m pip install -r "$(Join-Path $PSScriptRoot "..\config\requirements.txt")"
if (Test-Path "$(Join-Path $PSScriptRoot "..\config\requirements-server.upstream.txt")") {
  & $py -m pip install -r "$(Join-Path $PSScriptRoot "..\config\requirements-server.upstream.txt")"
}

Write-Host "Done. Consider running '.\SearXNG for Windows.bat' to start the server."
