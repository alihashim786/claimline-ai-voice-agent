<#
.SYNOPSIS
    End-to-end tests for the ClaimLine AI n8n workflows.

.DESCRIPTION
    Exercises every branch of both workflows without Retell being involved,
    and asserts on the responses instead of making you eyeball JSON.

    Why this is a .ps1 and not a list of curl commands: in PowerShell `curl`
    is an alias for Invoke-WebRequest, which takes completely different
    arguments from real curl, and PowerShell mangles the single-quoted JSON
    that bash curl examples rely on. Invoke-RestMethod builds the JSON from a
    hashtable, so there is no quoting to get wrong.

.PARAMETER BaseUrl
    Your n8n instance root, no trailing slash.

.PARAMETER Email
    A real inbox you can check. Test 7 sends an actual email here.

.PARAMETER SkipWrites
    Skip the tests that append rows to the Claims/Analytics tabs.

.EXAMPLE
    .\tests\test-workflows.ps1 -Email you@gmail.com

.EXAMPLE
    .\tests\test-workflows.ps1 -SkipWrites
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "https://alihashim.app.n8n.cloud",
    [string]$Email   = "you@example.com",
    [switch]$SkipWrites
)

# PowerShell 5.1 still negotiates TLS 1.0 by default on some builds, which
# n8n Cloud rejects outright. Force 1.2 before the first request.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ActionUrl   = "$BaseUrl/webhook/claimline-action"
$PostCallUrl = "$BaseUrl/webhook/claimline-post-call"

$script:Pass = 0
$script:Fail = 0

function Invoke-Case {
    param(
        [string]$Name,
        [string]$Url,
        [hashtable]$Body,
        [hashtable]$Expect,
        [string]$Note
    )

    Write-Host ""
    Write-Host "-> $Name" -ForegroundColor Cyan
    if ($Note) { Write-Host "   $Note" -ForegroundColor DarkGray }

    $json = $Body | ConvertTo-Json -Depth 10
    try {
        $resp = Invoke-RestMethod -Uri $Url -Method Post `
                                  -ContentType "application/json" `
                                  -Body $json -TimeoutSec 30
    }
    catch {
        Write-Host "   FAIL - request error: $($_.Exception.Message)" -ForegroundColor Red
        $script:Fail++
        return $null
    }

    Write-Host "   response: $($resp | ConvertTo-Json -Depth 5 -Compress)" -ForegroundColor DarkGray

    $ok = $true
    foreach ($key in $Expect.Keys) {
        $actual   = $resp.$key
        $expected = $Expect[$key]
        # Stringify both sides so a JSON boolean and a PowerShell $true compare
        # equal without special-casing types.
        if ("$actual" -ine "$expected") {
            Write-Host "   FAIL - $key : expected '$expected', got '$actual'" -ForegroundColor Red
            $ok = $false
        }
    }

    if ($ok) {
        Write-Host "   PASS" -ForegroundColor Green
        $script:Pass++
    }
    else {
        $script:Fail++
    }
    return $resp
}

Write-Host ""
Write-Host "=========================================================" -ForegroundColor White
Write-Host " ClaimLine AI - workflow tests" -ForegroundColor White
Write-Host " Workflow A: $ActionUrl"
Write-Host " Workflow B: $PostCallUrl"
Write-Host "=========================================================" -ForegroundColor White

# --- Workflow A : validate_policy ----------------------------------------
Invoke-Case -Name "1. Valid policy" -Url $ActionUrl `
    -Note "Should find Sara Ahmed's Auto policy in the Policies tab." `
    -Body  @{ args = @{ action = "validate_policy"; policy_number = "POL-10234" } } `
    -Expect @{ valid = $true; result = "valid"; holder_name = "Sara Ahmed"; coverage_type = "Auto" } | Out-Null

Invoke-Case -Name "2. Unknown policy" -Url $ActionUrl `
    -Note "Must return HTTP 200 with valid:false, NOT an HTTP error - an error code would make the agent say 'something went wrong' instead of 'I can't find that policy'." `
    -Body  @{ args = @{ action = "validate_policy"; policy_number = "POL-99999" } } `
    -Expect @{ valid = $false; result = "not_found" } | Out-Null

Invoke-Case -Name "3. Fuzzy policy number ('pol 10234')" -Url $ActionUrl `
    -Note "Speech-to-text mangles policy numbers. The Normalize node strips to digits and rebuilds POL-10234." `
    -Body  @{ args = @{ action = "validate_policy"; policy_number = "pol 10234" } } `
    -Expect @{ valid = $true; holder_name = "Sara Ahmed" } | Out-Null

Invoke-Case -Name "4. Bare digits ('10234')" -Url $ActionUrl `
    -Note "Same repair, caller said only the digits." `
    -Body  @{ args = @{ action = "validate_policy"; policy_number = "10234" } } `
    -Expect @{ valid = $true; holder_name = "Sara Ahmed" } | Out-Null

# --- Workflow A : create_claim -------------------------------------------
$newClaimId = $null
if (-not $SkipWrites) {
    $r = Invoke-Case -Name "5. Create claim - URGENCY OVERRIDE (the important one)" -Url $ActionUrl `
        -Note "Sends urgency='Standard' but the description mentions hospital + ambulance. n8n re-runs the keyword rule server-side and must escalate to Urgent. This single call proves the Switch routing, claim-ID generator, triage rule and Sheets append all work." `
        -Body @{ args = @{
            action        = "create_claim"
            policy_number = "POL-10234"
            holder_name   = "Sara Ahmed"
            incident_type = "Accident"
            incident_date = "2026-08-05"
            description   = "Rear-ended at a signal, my wife was taken to hospital by ambulance"
            email         = $Email
            urgency       = "Standard"
        } } `
        -Expect @{ success = $true; result = "urgent"; urgency = "Urgent"; status = "Filed" }

    if ($r -and $r.claim_id) {
        $newClaimId = $r.claim_id
        Write-Host "   -> generated claim_id: $newClaimId" -ForegroundColor Yellow
    }

    Invoke-Case -Name "6. Create claim - stays Standard" -Url $ActionUrl `
        -Note "No urgency keywords, so it must NOT be escalated." `
        -Body @{ args = @{
            action        = "create_claim"
            policy_number = "POL-10567"
            holder_name   = "Bilal Riaz"
            incident_type = "Theft"
            incident_date = "2026-08-04"
            description   = "My bicycle was stolen from outside the office, nobody was around"
            email         = $Email
            urgency       = "Standard"
        } } `
        -Expect @{ success = $true; result = "standard"; urgency = "Standard" } | Out-Null
}
else {
    Write-Host ""
    Write-Host "-> 5/6. Create-claim tests SKIPPED (-SkipWrites)" -ForegroundColor Yellow
}

# --- Workflow A : check_status -------------------------------------------
Invoke-Case -Name "7. Status of the seeded claim" -Url $ActionUrl `
    -Body  @{ args = @{ action = "check_status"; claim_id = "CLM-000001" } } `
    -Expect @{ found = $true; result = "found"; status = "Filed"; incident_type = "Accident" } | Out-Null

if ($newClaimId) {
    Invoke-Case -Name "8. Status of the claim just created" -Url $ActionUrl `
        -Note "Round-trip: the row written in test 5 is readable back by ID." `
        -Body  @{ args = @{ action = "check_status"; claim_id = $newClaimId } } `
        -Expect @{ found = $true; urgency = "Urgent" } | Out-Null
}

Invoke-Case -Name "9. Unknown claim ID" -Url $ActionUrl `
    -Note "Relies on 'Always Output Data' on the lookup node. Without it the branch dies silently and the caller hears dead air." `
    -Body  @{ args = @{ action = "check_status"; claim_id = "CLM-999999" } } `
    -Expect @{ found = $false; result = "not_found" } | Out-Null

Invoke-Case -Name "10. Unknown action (fallback branch)" -Url $ActionUrl `
    -Note "A typo in the action value must still get a reply, never a hung call." `
    -Body  @{ args = @{ action = "do_something_weird" } } `
    -Expect @{ error = "unknown_action" } | Out-Null

# --- Workflow B ----------------------------------------------------------
if (-not $SkipWrites) {
    Write-Host ""
    Write-Host "--- Workflow B (post-call) ------------------------------" -ForegroundColor White
    Write-Host "These return an empty 200 by design (the webhook responds"
    Write-Host "immediately so Retell never waits on Gmail). Verify by"
    Write-Host "checking your inbox and the Analytics tab, not the response."

    $claimForEmail = if ($newClaimId) { $newClaimId } else { "CLM-000001" }

    Write-Host ""
    Write-Host "-> 11. claim_filed = true  (expect an email + an Analytics row)" -ForegroundColor Cyan
    try {
        Invoke-RestMethod -Uri $PostCallUrl -Method Post -ContentType "application/json" -TimeoutSec 30 -Body (@{
            event = "call_analyzed"
            call  = @{
                call_id       = "test_$(Get-Random)"
                call_analysis = @{
                    call_summary         = "Caller filed a new claim after an accident."
                    custom_analysis_data = @{
                        claim_filed   = $true
                        claim_id      = $claimForEmail
                        urgency       = "Urgent"
                        name          = "Sara Ahmed"
                        email         = $Email
                        incident_type = "Accident"
                    }
                }
            }
        } | ConvertTo-Json -Depth 10) | Out-Null
        Write-Host "   SENT - now check $Email and the Analytics tab" -ForegroundColor Green
        $script:Pass++
    }
    catch {
        Write-Host "   FAIL - $($_.Exception.Message)" -ForegroundColor Red
        $script:Fail++
    }

    Write-Host ""
    Write-Host "-> 12. claim_filed = false (expect NO email, but an Analytics row)" -ForegroundColor Cyan
    try {
        Invoke-RestMethod -Uri $PostCallUrl -Method Post -ContentType "application/json" -TimeoutSec 30 -Body (@{
            event = "call_analyzed"
            call  = @{
                call_id       = "test_$(Get-Random)"
                call_analysis = @{
                    call_summary         = "Caller only asked about required documents."
                    custom_analysis_data = @{
                        claim_filed = $false
                        claim_id    = ""
                        urgency     = "n/a"
                        name        = ""
                        email       = ""
                    }
                }
            }
        } | ConvertTo-Json -Depth 10) | Out-Null
        Write-Host "   SENT - you should get NO email for this one" -ForegroundColor Green
        $script:Pass++
    }
    catch {
        Write-Host "   FAIL - $($_.Exception.Message)" -ForegroundColor Red
        $script:Fail++
    }
}

# --- Summary --------------------------------------------------------------
Write-Host ""
Write-Host "=========================================================" -ForegroundColor White
Write-Host " Passed: $script:Pass    Failed: $script:Fail" -ForegroundColor $(if ($script:Fail -eq 0) { "Green" } else { "Red" })
Write-Host "========================================================="
Write-Host ""
Write-Host "Then confirm by hand:" -ForegroundColor White
Write-Host "  - n8n Executions tab   : every run green"
Write-Host "  - Google Sheet 'Claims': 2 new rows, one Urgent one Standard"
Write-Host "  - Google Sheet 'Analytics': 2 new rows (true and false)"
Write-Host "  - $Email : exactly ONE new email, for test 11 only"
Write-Host "  - https://claimline-ai.streamlit.app : hit Refresh, new claims appear"
Write-Host ""
if ($script:Fail -gt 0) { exit 1 }
