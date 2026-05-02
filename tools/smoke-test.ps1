$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8888"

Write-Host "Smoke Test: SearXNG for Windows" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target: $base" -ForegroundColor Gray
Write-Host ""

# Helper: Verify HTTP 400 (SSRF blocked)
function Assert-Blocked {
    param([string]$Uri, [string]$Label)
    Write-Host "Testing SSRF block ($Label)..." -ForegroundColor Yellow
    
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -ErrorAction Stop
        throw "FAIL: Expected 400 Blocked, got $($response.StatusCode)"
    }
    catch [System.Net.WebException] {
        $statusCode = [int]$_.Exception.Response.StatusCode
        if ($statusCode -eq 400) {
            Write-Host "  ✓ Blocked (400)" -ForegroundColor Green
            return
        }
        throw "FAIL: Expected 400, got $statusCode"
    }
    catch {
        if ($_ -match "400") {
            Write-Host "  ✓ Blocked (400)" -ForegroundColor Green
            return
        }
        throw $_
    }
}

try {
    # Test 1: Root page
    Write-Host "Test 1: Root page..." -ForegroundColor Cyan
    $root = Invoke-WebRequest -Uri $base -UseBasicParsing
    Write-Host "  ✓ Status $($root.StatusCode)" -ForegroundColor Green
    Write-Host ""

    # Test 2: Standard JSON API
    Write-Host "Test 2: Standard JSON API..." -ForegroundColor Cyan
    $json = Invoke-WebRequest -Uri "$base/search?q=test&format=json" -UseBasicParsing
    if ($json.StatusCode -ne 200) {
        throw "JSON API failed with code $($json.StatusCode)"
    }
    Write-Host "  ✓ Status 200" -ForegroundColor Green
    Write-Host ""

    # Test 3: json_lite API (GenAI optimized)
    Write-Host "Test 3: json_lite API (GenAI optimized)..." -ForegroundColor Cyan
    $liteResponse = (Invoke-WebRequest -Uri "$base/search?q=SearXNG&format=json_lite" -UseBasicParsing).Content
    $lite = $liteResponse | ConvertFrom-Json
    if (-not $lite.results) {
        throw "json_lite API returned no results"
    }
    $resultCount = @($lite.results).Count
    Write-Host "  ✓ Status 200, $resultCount result(s)" -ForegroundColor Green
    Write-Host "  Sample result keys: $(@($lite.results[0].PSObject.Properties.Name | Select-Object -First 3) -join ', ')" -ForegroundColor Gray
    Write-Host ""

    # Test 4: /scrape API (Form POST)
    Write-Host "Test 4: /scrape endpoint (Form POST)..." -ForegroundColor Cyan
    $scrapeForm = Invoke-RestMethod -Method Post -Uri "$base/scrape" -Body @{ url = "https://example.com" }
    if (-not $scrapeForm.content) {
        throw "Scrape API (Form) returned no content"
    }
    $contentLen = $scrapeForm.content.Length
    Write-Host "  ✓ Content extracted: $contentLen chars" -ForegroundColor Green
    Write-Host ""

    # Test 5: /scrape API (JSON POST)
    Write-Host "Test 5: /scrape endpoint (JSON POST)..." -ForegroundColor Cyan
    $scrapeJson = Invoke-RestMethod -Method Post -Uri "$base/scrape" `
        -Body (@{ url = "https://example.com" } | ConvertTo-Json) `
        -ContentType "application/json"
    if (-not $scrapeJson.content) {
        throw "Scrape API (JSON) returned no content"
    }
    Write-Host "  ✓ Content extracted: $($scrapeJson.content.Length) chars" -ForegroundColor Green
    Write-Host ""

    # Test 6-8: SSRF Protection
    Write-Host "Test 6-8: SSRF Protection" -ForegroundColor Cyan
    Assert-Blocked -Uri "$base/scrape?url=http://127.0.0.1/" -Label "loopback IP (127.0.0.1)"
    Assert-Blocked -Uri "$base/scrape?url=http://192.168.1.1/" -Label "private range (192.168.x.x)"
    Assert-Blocked -Uri "$base/scrape?url=file:///etc/passwd" -Label "file:// scheme"
    Write-Host ""

    Write-Host "====================================="-ForegroundColor Green
    Write-Host "✓ All smoke tests PASSED" -ForegroundColor Green
    Write-Host "====================================="-ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "====================================" -ForegroundColor Red
    Write-Host "✗ Smoke test FAILED" -ForegroundColor Red
    Write-Host "====================================" -ForegroundColor Red
    Write-Host ""
    Write-Host $_ -ForegroundColor Red
    exit 1
}