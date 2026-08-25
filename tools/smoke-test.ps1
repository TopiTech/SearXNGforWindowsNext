[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8888"

Write-Host "Smoke Test: SearXNG for Windows" -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Target: $base" -ForegroundColor Gray
Write-Host ""

# Helper: Verify an expected HTTP status code, including WebException responses.
function Assert-HttpStatusCode {
    param(
        [string]$Uri,
        [int]$ExpectedStatusCode,
        [string]$Label
    )

    $statusCode = 0
    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -ErrorAction Stop
        $statusCode = [int]$response.StatusCode
    }
    catch {
        if ($_.Exception -and $_.Exception.Response) {
            $statusCode = [int]$_.Exception.Response.StatusCode
        }
        else {
            throw "FAIL: $Label failed before an HTTP response was received: $($_.Exception.Message)"
        }
    }

    if ($statusCode -eq $ExpectedStatusCode) {
        Write-Host "  ✓ $Label returned $statusCode" -ForegroundColor Green
        return
    }
    throw "FAIL: $Label expected $ExpectedStatusCode, got $statusCode"
}

# Helper: Verify HTTP 400 (SSRF blocked).
function Assert-Blocked {
    param([string]$Uri, [string]$Label)
    Write-Host "Testing SSRF block ($Label)..." -ForegroundColor Yellow
    Assert-HttpStatusCode -Uri $Uri -ExpectedStatusCode 400 -Label $Label
}

# Helper: Verify a JSON-like object has a non-empty property.
function Assert-JsonProperty {
    param([object]$Value, [string]$PropertyName, [string]$Label)
    if (-not $Value.$PropertyName) {
        throw "$Label returned no '$PropertyName'"
    }
}

try {
    # Test 1: Root page
    Write-Host "Test 1: Root page..." -ForegroundColor Cyan
    Assert-HttpStatusCode -Uri $base -ExpectedStatusCode 200 -Label "Root page"
    Write-Host ""

    # Test 2: Standard JSON API
    Write-Host "Test 2: Standard JSON API..." -ForegroundColor Cyan
    $jsonUri = "$base/search?q=test&format=json"
    Assert-HttpStatusCode -Uri $jsonUri -ExpectedStatusCode 200 -Label "Standard JSON API"
    Write-Host ""

    # Test 3: json_lite API (GenAI optimized)
    Write-Host "Test 3: json_lite API (GenAI optimized)..." -ForegroundColor Cyan
    $liteUri = "$base/search?q=SearXNG&format=json_lite"
    $liteResponse = (Invoke-WebRequest -Uri $liteUri -UseBasicParsing -ErrorAction Stop).Content
    $lite = $liteResponse | ConvertFrom-Json
    Assert-JsonProperty -Value $lite -PropertyName "results" -Label "json_lite API"
    $resultCount = @($lite.results).Count
    Write-Host "  ✓ Status 200, $resultCount result(s)" -ForegroundColor Green
    Write-Host "  Sample result keys: $(@($lite.results[0].PSObject.Properties.Name | Select-Object -First 3) -join ', ')" -ForegroundColor Gray
    Write-Host ""

    # Test 4: /scrape API (Form POST)
    Write-Host "Test 4: /scrape endpoint (Form POST)..." -ForegroundColor Cyan
    $scrapeForm = Invoke-RestMethod -Method Post -Uri "$base/scrape" -Body @{ url = "https://example.com" } -ErrorAction Stop
    Assert-JsonProperty -Value $scrapeForm -PropertyName "content" -Label "Scrape API (Form)"
    $contentLen = $scrapeForm.content.Length
    Write-Host "  ✓ Content extracted: $contentLen chars" -ForegroundColor Green
    Write-Host ""

    # Test 5: /scrape API (JSON POST)
    Write-Host "Test 5: /scrape endpoint (JSON POST)..." -ForegroundColor Cyan
    $scrapeJson = Invoke-RestMethod -Method Post -Uri "$base/scrape" `
        -Body (@{ url = "https://example.com" } | ConvertTo-Json) `
        -ContentType "application/json" -ErrorAction Stop
    Assert-JsonProperty -Value $scrapeJson -PropertyName "content" -Label "Scrape API (JSON)"
    Write-Host "  ✓ Content extracted: $($scrapeJson.content.Length) chars" -ForegroundColor Green
    Write-Host ""

    # Test 6-13: SSRF Protection
    Write-Host "Test 6-13: SSRF Protection" -ForegroundColor Cyan
    Assert-Blocked -Uri "$base/scrape?url=http://127.0.0.1/" -Label "loopback IP (127.0.0.1)"
    Assert-Blocked -Uri "$base/scrape?url=http://192.168.1.1/" -Label "private range (192.168.x.x)"
    Assert-Blocked -Uri "$base/scrape?url=http://127.0.0.1.nip.io/" -Label "hostname to localhost (nip.io)"
    Assert-Blocked -Uri "$base/scrape?url=http://[::1]/" -Label "IPv6 loopback (::1)"
    Assert-Blocked -Uri "$base/scrape?url=http://[fe80::1]/" -Label "IPv6 link-local"
    Assert-Blocked -Uri "$base/scrape?url=file:///etc/passwd" -Label "file:// scheme"
    Assert-Blocked -Uri "$base/scrape?url=gopher://127.0.0.1:6379/" -Label "gopher:// scheme"
    Assert-Blocked -Uri "$base/scrape?url=ftp://example.com/test" -Label "ftp:// scheme"
    Write-Host ""

    # Test 14: Autocomplete endpoint
    Write-Host "Test 14: Autocomplete endpoint..." -ForegroundColor Cyan
    $acUri = "$base/autocompleter?q=python"
    $acResponse = Invoke-WebRequest -Uri $acUri -UseBasicParsing -ErrorAction Stop
    if ($acResponse.StatusCode -eq 200) {
        Write-Host "  ✓ Autocompleter returned 200" -ForegroundColor Green
    } else {
        throw "FAIL: Autocompleter returned $($acResponse.StatusCode)"
    }
    Write-Host ""

    # Test 15: Scrape validation - missing URL
    Write-Host "Test 15: /scrape error handling (missing URL)..." -ForegroundColor Cyan
    Assert-HttpStatusCode -Uri "$base/scrape" -ExpectedStatusCode 400 -Label "Scrape missing URL"
    Write-Host ""

    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "✓ All smoke tests PASSED" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "================================" -ForegroundColor Red
    Write-Host "✗ Smoke test FAILED" -ForegroundColor Red
    Write-Host "================================" -ForegroundColor Red
    Write-Host ""
    Write-Host $_ -ForegroundColor Red
    exit 1
}
