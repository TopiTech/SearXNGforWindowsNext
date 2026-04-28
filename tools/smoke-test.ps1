$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8888"

Write-Host "Checking root page..." -ForegroundColor Cyan
Invoke-WebRequest -Uri $base -UseBasicParsing | Out-Null

Write-Host "Checking JSON API..." -ForegroundColor Cyan
$result = Invoke-WebRequest -Uri "$base/search?q=test&format=json" -UseBasicParsing
if ($result.StatusCode -ne 200) {
    throw "JSON API check failed with status $($result.StatusCode)"
}

Write-Host "Smoke test passed." -ForegroundColor Green
``