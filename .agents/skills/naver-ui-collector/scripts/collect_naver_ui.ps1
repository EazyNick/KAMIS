param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms
. (Join-Path $PSScriptRoot '../../../../scripts/collectors/shopping_count_detail.ps1')
$detailProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))

function Resolve-ChildPath {
    param([string]$Candidate, [string]$Parent, [string]$Label)
    $parentFull = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $candidateFull = [System.IO.Path]::GetFullPath($Candidate)
    if (-not $candidateFull.StartsWith($parentFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must be below run_dir"
    }
    return $candidateFull
}

function Escape-SpreadsheetValue {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) { return '' }
    $text = [string]$Value
    if ($text -match '^[=+\-@]') { return "'$text" }
    return $text
}

function Find-NaverDocument {
    $root = [System.Windows.Automation.AutomationElement]::RootElement
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document
    )
    $documents = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    foreach ($document in $documents) {
        if ($document.Current.Name -match '\uB124\uC774\uBC84|NAVER') { return $document }
    }
    return $null
}

function Close-NaverCollectionTab {
    try {
        $document = Find-NaverDocument
        if ($null -eq $document) { return }
        $document.SetFocus()
        Start-Sleep -Milliseconds 150
        [System.Windows.Forms.SendKeys]::SendWait('^w')
        Start-Sleep -Milliseconds 150
    }
    catch {
        Write-Warning "Naver cleanup failed: $($_.Exception.Message)"
    }
}

function Find-NaverSearchBox {
    $document = Find-NaverDocument
    if ($null -eq $document) { return $null }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $edits = $document.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    foreach ($edit in $edits) {
        $name = [string]$edit.Current.Name
        if ($name -match '\uC8FC\uC18C') { continue }
        if ($name -match '\uAC80\uC0C9|\uC785\uB825') {
            try {
                $null = $edit.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                return $edit
            }
            catch { continue }
        }
    }
    return $null
}

function Wait-NaverSearchBox {
    param([int]$TimeoutSeconds)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        $box = Find-NaverSearchBox
        if ($null -ne $box) { return $box }
        Start-Sleep -Milliseconds 500
    }
    throw 'Naver Shopping accessible search box was not found before timeout'
}

function Invoke-NaverSearch {
    $document = Find-NaverDocument
    if ($null -eq $document) { throw 'Naver Shopping document not found' }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    foreach ($button in $document.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        if ($button.Current.Name -match '^(\uAC80\uC0C9|\uAC80\uC0C9\uD558\uAE30)$') {
            $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
            return
        }
    }
    [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
}

function Get-NaverQuantity {
    param([string]$RawName, [string]$ComparisonUnit)
    $empty = [regex]::Match('', 'a')
    $prefix = ($RawName -split '\([^)]*\uB2F9')[0]
    $prefix = ($prefix -split '\d[\d,]*\s*\uC6D0')[0]
    if ($prefix -match '\d\s*[~\-\u2013]\s*\d|\d\s*(kg|g|\uAC1C|\uACFC|\uBBF8|\uB9C8\uB9AC|\uD3EC\uAE30)\s*[xX*\u00D7]') { return $empty }
    $prefix = $prefix -replace '(\d)\s*\uACFC(?=\s|[,)]|$)', ('$1' + [char]0xAC1C)
    $prefix = $prefix -replace '(\d)\s*\uBBF8(?=\s|[,)]|$)', ('$1' + [char]0xB9C8 + [char]0xB9AC)
    # A bare per-unit quote is not a package, even without parentheses.
    $prefix = ($prefix -split '(?i)\d+(?:\.\d+)?\s*(kg|g|\uAC1C|\uB9C8\uB9AC|\uD3EC\uAE30)\s*\uB2F9')[0]
    $packs = [regex]::Matches($prefix, '(\d+)\s*(\uBD09|\uD329|\uBC15\uC2A4|\uC138\uD2B8)')
    foreach ($pack in $packs) { if ([decimal]$pack.Groups[1].Value -gt 1) { return $empty } }
    if ($ComparisonUnit -match '(?i)kg|g') {
        $counts = [regex]::Matches($prefix, '(\d+)\s*\uAC1C')
        foreach ($count in $counts) { if ([decimal]$count.Groups[1].Value -gt 1) { return $empty } }
    }
    # Whole melon may genuinely be sold as one fruit with its weight.
    $wholeMelon = $prefix -match '\uBA5C\uB860|\uBA54\uB860'
    if ($wholeMelon -and $prefix -match '\uBC15\uC2A4|\uC138\uD2B8|\uBB36\uC74C|\uD329|\uCEF7\uD305|\uCEE4\uD305|\uC870\uAC01|\uC190\uC9C8|\uD050\uBE0C|\uBC18\uD1B5|\uBC18\uCABD|\uACFC\uC721|\uC0D0\uB7EC\uB4DC|\uC808\uB2E8') { return $empty }
    if ($wholeMelon -and $prefix -notmatch '\d\s*\uAC1C') {
        $prefix = $prefix -replace '(\d+)\s*\uD1B5', ('$1' + [char]0xAC1C)
    }
    $weights = [regex]::Matches($prefix, '(?i)(\d+(?:\.\d+)?)\s*(kg|g)')
    if ($weights.Count -gt 1) { return $empty }
    $unit = if ($ComparisonUnit -match '(?i)kg|g') { 'kg|g' }
            elseif ($ComparisonUnit -match '\uB9C8\uB9AC') { '\uB9C8\uB9AC' }
            elseif ($ComparisonUnit -match '\uD3EC\uAE30') { '\uD3EC\uAE30' }
            elseif ($ComparisonUnit -match '\uAC1C') { '\uAC1C' }
            else { return $empty }
    $candidates = [regex]::Matches($prefix, '(?i)(?<![\d.])(\d+(?:\.\d+)?)\s*(' + $unit + ')')
    if ($candidates.Count -ne 1) { return $empty }
    $match = $candidates[0]
    if ([decimal]$match.Groups[1].Value -le 0) { return $empty }
    if ($ComparisonUnit -match '\uAC1C' -and $weights.Count -gt 0 -and [decimal]$match.Groups[1].Value -le 1 -and -not $wholeMelon) { return $empty }
    return $match
}


function Test-ShoppingProduct {
    param([string]$RawName, [string]$ItemName)
    if ($null -eq $script:ShoppingFilterRules) {
        $rulesPath = Join-Path $PSScriptRoot '../../../../app/domain/shopping_filter_rules.json'
        $script:ShoppingFilterRules = Get-Content -LiteralPath $rulesPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $rules = $script:ShoppingFilterRules
    if ($RawName -match $rules.advertisement -or $RawName -match $rules.excluded) { return $false }
    if ([string]::IsNullOrWhiteSpace($ItemName)) { return $false }
    $wrong = $rules.wrong_items.PSObject.Properties[$ItemName]
    if ($null -ne $wrong -and $RawName -match $wrong.Value) { return $false }
    $required = $rules.required_names.PSObject.Properties[$ItemName]
    if ($null -ne $required -and $RawName -notmatch $required.Value) { return $false }
    $name = $ItemName -replace '\(\uAD6D\uC0B0\)', ''
    if ($ItemName -match '\(\uAD6D\uC0B0\)' -and $RawName -notmatch '(?<![\uAC00-\uD7A3])(?:\uAD6D\uC0B0|\uAD6D\uB0B4\uC0B0)') { return $false }
    return ($RawName -replace '\s+', '') -match [regex]::Escape(($name -replace '\s+', ''))
}

function Get-AccessibleProductRows {
    param([int]$Maximum, [string]$ItemName)
    $document = Find-NaverDocument
    if ($null -eq $document) { return @() }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Hyperlink
    )
    $items = $document.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $result = [System.Collections.Generic.List[object]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($item in $items) {
        $name = [string]$item.Current.Name
        if ([string]::IsNullOrWhiteSpace($name) -or $name -notmatch '\d[\d,]*\s*\uC6D0') { continue }
        try {
            $urlPattern = $item.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            $url = [string]$urlPattern.Current.Value
        }
        catch { continue }
        if ($url -notmatch '^https://[^/]*\.naver\.com/') { continue }
        if (-not $seen.Add($url)) { continue }
        if (-not (Test-ShoppingProduct -RawName $name -ItemName $ItemName)) { continue }
        $result.Add($item)
        if ($result.Count -ge $Maximum) { break }
    }
    return $result
}

function Wait-AccessibleProductRows {
    param([int]$TimeoutSeconds, [int]$Maximum, [string]$PreviousDocumentName, [string]$Query, [string]$ItemName)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        $document = Find-NaverDocument
        $rows = @(Get-AccessibleProductRows -Maximum $Maximum -ItemName $ItemName)
        $titleMatchesQuery = $null -ne $document -and $document.Current.Name -match [regex]::Escape($Query)
        if ($rows.Count -gt 0 -and $titleMatchesQuery) {
            return $rows
        }
        Start-Sleep -Milliseconds 500
    }
    throw 'Naver Shopping accessible product results were not found before timeout'
}

function New-StableProductId {
    param([string]$RawName)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hash = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($RawName))
        return ([System.BitConverter]::ToString($hash).Replace('-', '').Substring(0, 24)).ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

$manifestFull = [System.IO.Path]::GetFullPath($ManifestPath)
if (-not [System.IO.File]::Exists($manifestFull)) { throw "Manifest not found: $manifestFull" }
$manifest = Get-Content -LiteralPath $manifestFull -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace([string]$manifest.run_dir)) { throw 'Manifest run_dir is required' }
$runDir = [System.IO.Path]::GetFullPath([string]$manifest.run_dir)
$null = Resolve-ChildPath -Candidate $manifestFull -Parent $runDir -Label 'ManifestPath'
$outputCsv = Resolve-ChildPath -Candidate ([string]$manifest.output_csv) -Parent $runDir -Label 'output_csv'
$targets = @($manifest.targets)
if ($targets.Count -eq 0 -or $targets.Count -gt 10) { throw 'Manifest targets must contain 1 to 10 entries' }

[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputCsv)) | Out-Null
$temporaryCsv = "$outputCsv.$([Guid]::NewGuid().ToString('N')).tmp"
$allRows = [System.Collections.Generic.List[object]]::new()
$failedKeys = [System.Collections.Generic.List[string]]::new()
$completedCount = 0
$openedChromeForRun = $false

try {
    $searchBox = Find-NaverSearchBox
    if ($null -eq $searchBox) {
        Start-Process 'chrome.exe' -ArgumentList 'https://shopping.naver.com/' | Out-Null
        $openedChromeForRun = $true
        $searchBox = Wait-NaverSearchBox -TimeoutSeconds 30
    }
    foreach ($target in $targets) {
        $key = "$($target.item_code):$($target.kind_code)"
        try {
            $document = Find-NaverDocument
            $previousDocumentName = if ($null -ne $document) { [string]$document.Current.Name } else { '' }
            $searchBox = Wait-NaverSearchBox -TimeoutSeconds 15
            $valuePattern = $searchBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            $searchBox.SetFocus()
            $valuePattern.SetValue([string]$target.query)
            Invoke-NaverSearch
            Start-Sleep -Milliseconds ([Math]::Max(500, [int]$manifest.minimum_delay_ms))
            $accessibleRows = @(Wait-AccessibleProductRows -TimeoutSeconds 25 -Maximum ([Math]::Min(40, [Math]::Max(1, [int]$manifest.max_offers_per_target) * 4)) -PreviousDocumentName $previousDocumentName -Query ([string]$target.query) -ItemName ([string]$target.item_name))

            # Snapshot search cards before changing tabs; UIA handles can become stale.
            $candidateRows = @($accessibleRows | ForEach-Object {
                $urlPattern = $_.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                [pscustomobject]@{ raw = [string]$_.Current.Name; url = [string]$urlPattern.Current.Value }
            })
            $acceptedCount = 0
            foreach ($candidateRow in $candidateRows) {
                $raw = $candidateRow.raw
                $url = $candidateRow.url
                $detail = $null
                $countTarget = [string]$target.comparison_unit -match '\uAC1C|\uB9C8\uB9AC'
                if ($countTarget) {
                    $detail = Read-ShoppingCountDetail -SearchDocument (Find-NaverDocument) -Url $url -ComparisonUnit ([string]$target.comparison_unit) -ProjectRoot $detailProjectRoot
                }
                $lines = @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
                $priceMatch = [regex]::Match($raw, '(?<![\d,])(\d[\d,]*)\s*\uC6D0')
                $discountedPriceMatch = [regex]::Match($raw, '\uD560\uC778\s*\uC804\s*\uD310\uB9E4\uAC00\s*(\d[\d,]*)\s*\uC6D0\s*\d+\s*%\s*\uD560\uC778\s*(\d[\d,]*)\s*\uC6D0')
                $quantityMatch = Get-NaverQuantity -RawName $raw -ComparisonUnit ([string]$target.comparison_unit)
                $unitPriceMatch = [regex]::Match($raw, '\([^\r\n]*?\d[\d,]*\s*\uC6D0[^\r\n]*?\)')
                $shippingMatch = [regex]::Match($raw, '\uBC30\uC1A1\uBE44\s*(\d[\d,]*)\s*\uC6D0')
                $freeShipping = $raw -match '\uBB34\uB8CC\s*\uBC30\uC1A1'
                $restricted = $raw -match '\uCE74\uB4DC|\uCFE0\uD3F0|Npay|\uBA64\uBC84\uC2ED|\uACB0\uC81C'
                $allMember = $raw -match '\uD68C\uC6D0\uAC00|\uAC00\uC785\s*\uD61C\uD0DD'
                if ($countTarget) {
                    $quantityMatch = [regex]::Match('', 'a')
                    $priceMatch = [regex]::Match('', 'a')
                    $discountedPriceMatch = [regex]::Match('', 'a')
                    $shippingMatch = [regex]::Match('', 'a')
                    $freeShipping = $false
                    if ($null -ne $detail -and $detail.verified) {
                        $quantityMatch = [regex]::Match(($detail.quantity + $detail.unit), '^(\d+)(.+)$')
                        $priceMatch = [regex]::Match($detail.displayed_price, '^(\d+)$')
                        $url = $detail.url
                    }
                }
                $allRows.Add([pscustomobject][ordered]@{
                    run_id = Escape-SpreadsheetValue $manifest.run_id
                    observed_date = Escape-SpreadsheetValue $manifest.observed_date
                    collected_at = [DateTimeOffset]::Now.ToString('o')
                    platform = 'naver'
                    item_code = Escape-SpreadsheetValue $target.item_code
                    kind_code = Escape-SpreadsheetValue $target.kind_code
                    query = Escape-SpreadsheetValue $target.query
                    product_id = New-StableProductId -RawName $url
                    title = Escape-SpreadsheetValue $(if ($lines.Count -gt 0) { $lines[0] } else { '' })
                    url = Escape-SpreadsheetValue $url
                    displayed_price = $(if ($discountedPriceMatch.Success) { $discountedPriceMatch.Groups[2].Value.Replace(',', '') } elseif ($priceMatch.Success) { $priceMatch.Groups[1].Value.Replace(',', '') } else { '' })
                    shipping_fee = $(if ($countTarget) { [string]$detail.shipping_fee } elseif ($shippingMatch.Success) { $shippingMatch.Groups[1].Value.Replace(',', '') } elseif ($freeShipping) { '0' } else { '' })
                    member_price = ''
                    member_discount_scope = $(if ($restricted) { 'restricted' } elseif ($allMember) { 'all_members' } else { 'unknown' })
                    quantity = $(if ($quantityMatch.Success) { $quantityMatch.Groups[1].Value } else { '' })
                    unit = $(if ($quantityMatch.Success) { $quantityMatch.Groups[2].Value } else { '' })
                    unit_price_text = Escape-SpreadsheetValue $(if ($unitPriceMatch.Success) { $unitPriceMatch.Value } else { '' })
                    advertisement = ($raw -match '(^|\s)\uAD11\uACE0($|\s)')
                    availability = $(if ($raw -match '\uD488\uC808') { 'sold_out' } else { 'available' })
                    raw_accessible_name = Escape-SpreadsheetValue $raw
                    selected_option = Escape-SpreadsheetValue $detail.selected_option
                    quantity_evidence = Escape-SpreadsheetValue $detail.quantity_evidence
                    price_evidence = Escape-SpreadsheetValue $detail.price_evidence
                    detail_accessible_name = Escape-SpreadsheetValue $detail.detail_accessible_name
                    detail_product_title = Escape-SpreadsheetValue $detail.detail_product_title
                    evidence_source = Escape-SpreadsheetValue $detail.evidence_source
                    order_quantity = Escape-SpreadsheetValue $detail.order_quantity
                })
                # Invalid candidates stay in the raw evidence but do not consume the offer quota.
                if ($quantityMatch.Success -and ($discountedPriceMatch.Success -or $priceMatch.Success) -and ($shippingMatch.Success -or $freeShipping -or ($countTarget -and [string]$detail.shipping_fee -ne '')) -and $raw -notmatch '\uD488\uC808') {
                    $acceptedCount += 1
                    if ($acceptedCount -ge [Math]::Max(1, [int]$manifest.max_offers_per_target)) { break }
                }
            }
            if ($accessibleRows.Count -gt 0) { $completedCount += 1 }
        }
        catch {
            if ($_.Exception.Data['DetailCleanupFailed']) { throw }
            Write-Warning "Naver target ${key}: $($_.Exception.Message)"
            $failedKeys.Add($key)
        }
    }

    if ($allRows.Count -gt 0) {
        $allRows | Export-Csv -LiteralPath $temporaryCsv -NoTypeInformation -Encoding UTF8
    }
    else {
        $headers = 'run_id,observed_date,collected_at,platform,item_code,kind_code,query,product_id,title,url,displayed_price,shipping_fee,member_price,member_discount_scope,quantity,unit,unit_price_text,advertisement,availability,raw_accessible_name,selected_option,quantity_evidence,price_evidence,detail_accessible_name,detail_product_title,evidence_source,order_quantity'
        [System.IO.File]::WriteAllText($temporaryCsv, $headers + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($true))
    }
    Move-Item -LiteralPath $temporaryCsv -Destination $outputCsv -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryCsv) { Remove-Item -LiteralPath $temporaryCsv -Force }
    if ($openedChromeForRun) { Close-NaverCollectionTab }
}

# Final completion is based on ingestion validation, not visible card counts.
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Repository .venv Python is required for final validation' }
Push-Location $projectRoot
try {
    & $python -m app.infrastructure.shopping_agent_validation --manifest $manifestFull --platform naver
    if ($LASTEXITCODE -ne 0) { throw 'Collected CSV validation failed; do not report success' }
}
finally { Pop-Location }
