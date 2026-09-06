[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$ErrorActionPreference = "Stop"

$base = "http://127.0.0.1:8888"
$scriptDir = Split-Path -Parent $PSCommandPath
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path

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
        [string]$Label,
        [string]$Method = "GET",
        [object]$Body = $null,
        [string]$ContentType = $null
    )

    $statusCode = 0
    try {
        $requestArgs = @{
            Uri = $Uri
            UseBasicParsing = $true
            ErrorAction = "Stop"
            Method = $Method
        }
        if ($null -ne $Body) {
            $requestArgs["Body"] = $Body
        }
        if ($ContentType) {
            $requestArgs["ContentType"] = $ContentType
        }
        $response = Invoke-WebRequest @requestArgs
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
        Write-Host "  [OK] $Label returned $statusCode" -ForegroundColor Green
        return
    }
    throw "[FAIL] $Label expected $ExpectedStatusCode, got $statusCode"
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

# Helper: Verify a value is one of an allowed set.
function Assert-In {
    param([string]$Value, [string[]]$Allowed, [string]$Label)
    if ($Allowed -notcontains $Value) {
        $msg = "${Label}: expected one of [$($Allowed -join ', ')], got '$Value'"
        throw $msg
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
    Write-Host "  [OK] Status 200, $resultCount result(s)" -ForegroundColor Green
    if ($resultCount -gt 0) {
        $firstResult = $lite.results[0]
        $expectedFields = @("title", "url", "content", "source")
        foreach ($field in $expectedFields) {
            if (-not ($firstResult.PSObject.Properties.Name -contains $field)) {
                throw "json_lite result missing required field: $field"
            }
        }
        Write-Host "  [OK] All required fields present (title, url, content, source)" -ForegroundColor Green
    }
    Write-Host "  Sample result keys: $(@($lite.results[0].PSObject.Properties.Name | Select-Object -First 3) -join ', ')" -ForegroundColor Gray
    Write-Host ""

    # Test 4: /scrape API (Form POST)
    Write-Host "Test 4: /scrape endpoint (Form POST)..." -ForegroundColor Cyan
    $scrapeForm = Invoke-RestMethod -Method Post -Uri "$base/scrape" -Body @{ url = "https://example.com" } -ErrorAction Stop
    Assert-JsonProperty -Value $scrapeForm -PropertyName "content" -Label "Scrape API (Form)"
    $contentLen = $scrapeForm.content.Length
    Write-Host "  [OK] Content extracted: $contentLen chars" -ForegroundColor Green
    Write-Host ""

    # Test 5: /scrape API (JSON POST)
    Write-Host "Test 5: /scrape endpoint (JSON POST)..." -ForegroundColor Cyan
    $scrapeJson = Invoke-RestMethod -Method Post -Uri "$base/scrape" `
        -Body (@{ url = "https://example.com" } | ConvertTo-Json) `
        -ContentType "application/json" -ErrorAction Stop
    Assert-JsonProperty -Value $scrapeJson -PropertyName "content" -Label "Scrape API (JSON)"
    Write-Host "  [OK] Content extracted: $($scrapeJson.content.Length) chars" -ForegroundColor Green
    Write-Host ""

    # Test 6: /scrape API (GET)
    Write-Host "Test 6: /scrape endpoint (GET query param)..." -ForegroundColor Cyan
    $scrapeGet = Invoke-RestMethod -Method Get -Uri "$base/scrape?url=https://example.com" -ErrorAction Stop
    Assert-JsonProperty -Value $scrapeGet -PropertyName "content" -Label "Scrape API (GET)"
    Write-Host "  [OK] Content extracted: $($scrapeGet.content.Length) chars" -ForegroundColor Green
    Write-Host ""

    # Test 7-16: SSRF Protection
    Write-Host "Test 7-16: SSRF Protection" -ForegroundColor Cyan
    Assert-Blocked -Uri "$base/scrape?url=http://127.0.0.1/" -Label "loopback IP (127.0.0.1)"
    Assert-Blocked -Uri "$base/scrape?url=http://192.168.1.1/" -Label "private range (192.168.x.x)"
    Assert-Blocked -Uri "$base/scrape?url=http://127.0.0.1.nip.io/" -Label "hostname to localhost (nip.io)"
    Assert-Blocked -Uri "$base/scrape?url=http://[::1]/" -Label "IPv6 loopback (::1)"
    Assert-Blocked -Uri "$base/scrape?url=http://[fe80::1]/" -Label "IPv6 link-local"
    Assert-Blocked -Uri "$base/scrape?url=file:///etc/passwd" -Label "file:// scheme"
    Assert-Blocked -Uri "$base/scrape?url=gopher://127.0.0.1:6379/" -Label "gopher:// scheme"
    Assert-Blocked -Uri "$base/scrape?url=ftp://example.com/test" -Label "ftp:// scheme"
    Assert-Blocked -Uri "$base/scrape?url=javascript:alert(1)" -Label "javascript: scheme"
    Assert-Blocked -Uri "$base/scrape?url=data:text/html,test" -Label "data: scheme"
    Write-Host ""

    # Test 17: Autocomplete endpoint
    Write-Host "Test 17: Autocomplete endpoint..." -ForegroundColor Cyan
    $acUri = "$base/autocompleter?q=python"
    $acResponse = Invoke-WebRequest -Uri $acUri -UseBasicParsing -ErrorAction Stop
    if ($acResponse.StatusCode -eq 200) {
        Write-Host "  [OK] Autocompleter returned 200" -ForegroundColor Green
    } else {
        throw "[FAIL] Autocompleter returned $($acResponse.StatusCode)"
    }
    Write-Host ""

    # Test 18: Scrape validation - missing, invalid-type, and malformed URL
    Write-Host "Test 18: /scrape error handling (missing, invalid-type, malformed URL)..." -ForegroundColor Cyan
    Assert-HttpStatusCode -Uri "$base/scrape" -ExpectedStatusCode 400 -Label "Scrape missing URL"
    Assert-HttpStatusCode -Uri "$base/scrape" -Method Post -Body '{"url": 12345}' -ContentType "application/json" -ExpectedStatusCode 400 -Label "Scrape invalid URL type"
    Assert-HttpStatusCode -Uri "$base/scrape?url=http%3A%2F%2F%5B%3A%3A1" -ExpectedStatusCode 400 -Label "Scrape malformed URL"
    Write-Host ""

    # Test 19: json_lite with empty query (server should reject with 400 "No query")
    Write-Host "Test 19: json_lite with empty query..." -ForegroundColor Cyan
    $emptyUri = "$base/search?q=&format=json_lite"
    Assert-HttpStatusCode -Uri $emptyUri -ExpectedStatusCode 400 -Label "json_lite rejects empty query"
    Write-Host ""

    # Test 20: Healthcheck endpoint
    Write-Host "Test 20: Healthcheck endpoint..." -ForegroundColor Cyan
    $hcResponse = Invoke-WebRequest -Uri "$base/healthz" -UseBasicParsing -ErrorAction Stop
    Assert-In -Value $hcResponse.Content.Trim() -Allowed @("OK") -Label "Healthcheck body"
    Write-Host "  [OK] /healthz returned OK" -ForegroundColor Green
    Write-Host ""

    Write-Host "=====================================" -ForegroundColor Green
    Write-Host "[OK] All smoke tests PASSED" -ForegroundColor Green
    Write-Host "=====================================" -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "================================" -ForegroundColor Red
    Write-Host "[FAIL] Smoke test FAILED" -ForegroundColor Red
    Write-Host "================================" -ForegroundColor Red
    Write-Host ""
    Write-Host $_ -ForegroundColor Red
    exit 1
}
