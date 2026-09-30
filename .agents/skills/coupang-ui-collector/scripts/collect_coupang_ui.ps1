param(
    [Parameter(Mandatory = $true)]
    [string]$ManifestPath
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName System.Windows.Forms

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

function Find-CoupangDocument {
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Document
    )
    foreach ($document in [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        if ($document.Current.Name -match '\uCFE0\uD321|Coupang') { return $document }
    }
    return $null
}

function Close-CoupangCollectionTab {
    try {
        $document = Find-CoupangDocument
        if ($null -eq $document) { return }
        $document.SetFocus()
        Start-Sleep -Milliseconds 150
        [System.Windows.Forms.SendKeys]::SendWait('^w')
        Start-Sleep -Milliseconds 150
    }
    catch {
        Write-Warning "Coupang cleanup failed: $($_.Exception.Message)"
    }
}

function Invoke-CoupangSearch {
    $document = Find-CoupangDocument
    if ($null -eq $document) { throw 'Coupang document not found' }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Button
    )
    foreach ($button in $document.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)) {
        if ($button.Current.Name -match '^\uAC80\uC0C9$') {
            $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
            return
        }
    }
    throw 'Coupang search button not found'
}

function Get-CoupangDisplayedPrice {
    param([string]$RawName)
    # Unit prices, delivery charges and rewards follow the sale price.
    $prefix = ($RawName -split '\([^)]*\uB2F9|\uBC30\uC1A1\uBE44|\uCD5C\uB300')[0]
    $prices = [regex]::Matches($prefix, '(?<![\d,])(\d[\d,]*)\s*\uC6D0')
    if ($prices.Count -eq 0) { return '' }
    return $prices[$prices.Count - 1].Groups[1].Value.Replace(',', '')
}

function Get-CoupangQuantity {
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
    if ($ComparisonUnit -match '\uAC1C' -and $weights.Count -gt 0 -and [decimal]$match.Groups[1].Value -le 1) { return $empty }
    return $match
}


function Find-CoupangSearchBox {
    $searchName = ([char]0xCFE0).ToString() + [char]0xD321 + ' ' + [char]0xC0C1 + [char]0xD488 + ' ' + [char]0xAC80 + [char]0xC0C9
    $root = Find-CoupangDocument
    if ($null -eq $root) { return $null }
    $editCondition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Edit
    )
    $edits = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $editCondition)
    foreach ($edit in $edits) {
        if ($edit.Current.Name -eq $searchName) { return $edit }
    }
    return $null
}

function Wait-CoupangSearchBox {
    param([int]$TimeoutSeconds)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        $box = Find-CoupangSearchBox
        if ($null -ne $box) { return $box }
        Start-Sleep -Milliseconds 500
    }
    throw 'Coupang accessible search box was not found before timeout'
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
    param([int]$Maximum, [string]$Query, [string]$ItemName)
    $root = Find-CoupangDocument
    if ($null -eq $root -or $root.Current.Name -notmatch [regex]::Escape($Query)) { return @() }
    $condition = New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::ListItem
    )
    $items = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
    $result = [System.Collections.Generic.List[object]]::new()
    foreach ($item in $items) {
        $name = $item.Current.Name
        if (-not [string]::IsNullOrWhiteSpace($name) -and $name -match '\d[\d,]*\s*\uC6D0') {
            if (-not (Test-ShoppingProduct -RawName $name -ItemName $ItemName)) { continue }
            $result.Add($item)
            if ($result.Count -ge $Maximum) { break }
        }
    }
    return $result
}

function Wait-AccessibleProductRows {
    param([int]$TimeoutSeconds, [int]$Maximum, [string]$Query, [string]$ItemName)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        $rows = @(Get-AccessibleProductRows -Maximum $Maximum -Query $Query -ItemName $ItemName)
        if ($rows.Count -gt 0) { return $rows }
        Start-Sleep -Milliseconds 500
    }
    throw 'Coupang accessible product results were not found before timeout'
}

function New-StableProductId {
    param([string]$RawName)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($RawName)
        $hash = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash).Replace('-', '').Substring(0, 24)).ToLowerInvariant()
    }
    finally { $sha.Dispose() }
}

$manifestFull = [System.IO.Path]::GetFullPath($ManifestPath)
if (-not [System.IO.File]::Exists($manifestFull)) { throw "Manifest not found: $manifestFull" }
$manifest = Get-Content -LiteralPath $manifestFull -Raw -Encoding UTF8 | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace([string]$manifest.run_dir)) { throw 'Manifest run_dir is required' }
$runDir = [System.IO.Path]::GetFullPath([string]$manifest.run_dir)
$manifestValidated = Resolve-ChildPath -Candidate $manifestFull -Parent $runDir -Label 'ManifestPath'
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
    $searchBox = Find-CoupangSearchBox
    if ($null -eq $searchBox) {
        Start-Process 'chrome.exe' -ArgumentList 'https://www.coupang.com/' | Out-Null
        $openedChromeForRun = $true
        $searchBox = Wait-CoupangSearchBox -TimeoutSeconds 30
    }

    foreach ($target in $targets) {
        $key = "$($target.item_code):$($target.kind_code)"
        try {
            $searchBox = Wait-CoupangSearchBox -TimeoutSeconds 15
            $valuePattern = $searchBox.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
            $searchBox.SetFocus()
            $valuePattern.SetValue([string]$target.query)
            Invoke-CoupangSearch
            Start-Sleep -Milliseconds ([Math]::Max(500, [int]$manifest.minimum_delay_ms))
            $accessibleRows = @(Wait-AccessibleProductRows -TimeoutSeconds 25 -Maximum ([Math]::Min(40, [Math]::Max(1, [int]$manifest.max_offers_per_target) * 4)) -Query ([string]$target.query) -ItemName ([string]$target.item_name))

            $acceptedCount = 0
            foreach ($accessibleRow in $accessibleRows) {
                $raw = [string]$accessibleRow.Current.Name
                $lines = @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
                $displayedPrice = Get-CoupangDisplayedPrice -RawName $raw
                $quantityMatch = Get-CoupangQuantity -RawName $raw -ComparisonUnit ([string]$target.comparison_unit)
                $unitPriceMatch = [regex]::Match($raw, '\([^\r\n]*?\d[\d,]*\s*\uC6D0[^\r\n]*?\)')
                $shippingMatch = [regex]::Match($raw, '\uBC30\uC1A1\uBE44\s*(\d[\d,]*)\s*\uC6D0')
                $freeShipping = $raw -match '\uBB34\uB8CC\s*\uBC30\uC1A1'
                $allRows.Add([pscustomobject][ordered]@{
                    run_id = Escape-SpreadsheetValue $manifest.run_id
                    observed_date = Escape-SpreadsheetValue $manifest.observed_date
                    collected_at = [DateTimeOffset]::Now.ToString('o')
                    platform = 'coupang'
                    item_code = Escape-SpreadsheetValue $target.item_code
                    kind_code = Escape-SpreadsheetValue $target.kind_code
                    query = Escape-SpreadsheetValue $target.query
                    product_id = New-StableProductId -RawName $raw
                    title = Escape-SpreadsheetValue $(if ($lines.Count -gt 0) { $lines[0] } else { '' })
                    url = ''
                    displayed_price = $displayedPrice
                    shipping_fee = $(if ($shippingMatch.Success) { $shippingMatch.Groups[1].Value.Replace(',', '') } elseif ($freeShipping) { '0' } else { '' })
                    member_price = ''
                    member_discount_scope = $(if ($raw -match '\uC640\uC6B0\uD68C\uC6D0|\uCFE0\uD398\uC774|\uCE74\uB4DC\uD560\uC778|\uCFE0\uD3F0') { 'restricted' } else { 'unknown' })
                    quantity = $(if ($quantityMatch.Success) { $quantityMatch.Groups[1].Value } else { '' })
                    unit = $(if ($quantityMatch.Success) { $quantityMatch.Groups[2].Value } else { '' })
                    unit_price_text = Escape-SpreadsheetValue $(if ($unitPriceMatch.Success) { $unitPriceMatch.Value } else { '' })
                    advertisement = ($raw -match '(^|\s)\uAD11\uACE0($|\s)')
                    availability = $(if ($raw -match '\uD488\uC808') { 'sold_out' } else { 'available' })
                    raw_accessible_name = Escape-SpreadsheetValue $raw
                })
                # Invalid candidates stay in the raw evidence but do not consume the offer quota.
                if ($quantityMatch.Success -and $displayedPrice -and ($shippingMatch.Success -or $freeShipping) -and $raw -notmatch '\uD488\uC808') {
                    $acceptedCount += 1
                    if ($acceptedCount -ge [Math]::Max(1, [int]$manifest.max_offers_per_target)) { break }
                }
            }
            if ($accessibleRows.Count -gt 0) { $completedCount += 1 }
        }
        catch {
            Write-Warning "Coupang target ${key}: $($_.Exception.Message)"
            $failedKeys.Add($key)
        }
    }

    if ($allRows.Count -gt 0) {
        $allRows | Export-Csv -LiteralPath $temporaryCsv -NoTypeInformation -Encoding UTF8
    }
    else {
        $headers = 'run_id,observed_date,collected_at,platform,item_code,kind_code,query,product_id,title,url,displayed_price,shipping_fee,member_price,member_discount_scope,quantity,unit,unit_price_text,advertisement,availability,raw_accessible_name'
        [System.IO.File]::WriteAllText($temporaryCsv, $headers + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($true))
    }
    Move-Item -LiteralPath $temporaryCsv -Destination $outputCsv -Force
}
finally {
    if (Test-Path -LiteralPath $temporaryCsv) { Remove-Item -LiteralPath $temporaryCsv -Force }
    if ($openedChromeForRun) { Close-CoupangCollectionTab }
}

# Final completion is based on ingestion validation, not visible card counts.
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
$python = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Repository .venv Python is required for final validation' }
Push-Location $projectRoot
try {
    & $python -m app.infrastructure.shopping_agent_validation --manifest $manifestFull --platform coupang
    if ($LASTEXITCODE -ne 0) { throw 'Collected CSV validation failed; do not report success' }
}
finally { Pop-Location }
