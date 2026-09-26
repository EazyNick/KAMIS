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

function Get-AccessibleProductRows {
    param([int]$Maximum)
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
        $result.Add($item)
        if ($result.Count -ge $Maximum) { break }
    }
    return $result
}

function Wait-AccessibleProductRows {
    param([int]$TimeoutSeconds, [int]$Maximum, [string]$PreviousDocumentName, [string]$Query)
    $deadline = [DateTimeOffset]::Now.AddSeconds($TimeoutSeconds)
    while ([DateTimeOffset]::Now -lt $deadline) {
        $document = Find-NaverDocument
        $rows = @(Get-AccessibleProductRows -Maximum $Maximum)
        $titleMatchesQuery = $null -ne $document -and $document.Current.Name -match [regex]::Escape($Query)
        $documentChanged = $null -ne $document -and $document.Current.Name -ne $PreviousDocumentName
        if ($rows.Count -gt 0 -and ($documentChanged -or $titleMatchesQuery)) {
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

try {
    $searchBox = Find-NaverSearchBox
    if ($null -eq $searchBox) {
        Start-Process 'chrome.exe' -ArgumentList 'https://shopping.naver.com/' | Out-Null
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
            [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
            Start-Sleep -Milliseconds ([Math]::Max(500, [int]$manifest.minimum_delay_ms))
            $accessibleRows = @(Wait-AccessibleProductRows -TimeoutSeconds 25 -Maximum ([Math]::Max(1, [int]$manifest.max_offers_per_target)) -PreviousDocumentName $previousDocumentName -Query ([string]$target.query))

            foreach ($accessibleRow in $accessibleRows) {
                $raw = [string]$accessibleRow.Current.Name
                $urlPattern = $accessibleRow.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
                $url = [string]$urlPattern.Current.Value
                $lines = @($raw -split "`r?`n" | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
                $priceMatch = [regex]::Match($raw, '(?<![\d,])(\d[\d,]*)\s*\uC6D0')
                $discountedPriceMatch = [regex]::Match($raw, '\uD560\uC778\s*\uC804\s*\uD310\uB9E4\uAC00\s*(\d[\d,]*)\s*\uC6D0\s*\d+\s*%\s*\uD560\uC778\s*(\d[\d,]*)\s*\uC6D0')
                $quantityMatch = [regex]::Match($raw, '(\d+(?:\.\d+)?)\s*(kg|g|\uAC1C|\uBD09|\uD329|\uD3EC\uAE30|\uB9C8\uB9AC)')
                $unitPriceMatch = [regex]::Match($raw, '\([^\r\n]*?\d[\d,]*\s*\uC6D0[^\r\n]*?\)')
                $shippingMatch = [regex]::Match($raw, '\uBC30\uC1A1\uBE44\s*(\d[\d,]*)\s*\uC6D0')
                $freeShipping = $raw -match '\uBB34\uB8CC\s*\uBC30\uC1A1'
                $restricted = $raw -match '\uCE74\uB4DC|\uCFE0\uD3F0|Npay|\uBA64\uBC84\uC2ED|\uACB0\uC81C'
                $allMember = $raw -match '\uD68C\uC6D0\uAC00|\uAC00\uC785\s*\uD61C\uD0DD'
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
                    shipping_fee = $(if ($shippingMatch.Success) { $shippingMatch.Groups[1].Value.Replace(',', '') } elseif ($freeShipping) { '0' } else { '' })
                    member_price = ''
                    member_discount_scope = $(if ($restricted) { 'restricted' } elseif ($allMember) { 'all_members' } else { 'unknown' })
                    quantity = $(if ($quantityMatch.Success) { $quantityMatch.Groups[1].Value } else { '' })
                    unit = $(if ($quantityMatch.Success) { $quantityMatch.Groups[2].Value } else { '' })
                    unit_price_text = Escape-SpreadsheetValue $(if ($unitPriceMatch.Success) { $unitPriceMatch.Value } else { '' })
                    advertisement = ($raw -match '(^|\s)\uAD11\uACE0($|\s)')
                    availability = $(if ($raw -match '\uD488\uC808') { 'sold_out' } else { 'available' })
                    raw_accessible_name = Escape-SpreadsheetValue $raw
                })
            }
            if ($accessibleRows.Count -gt 0) { $completedCount += 1 }
        }
        catch { $failedKeys.Add($key) }
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
}

$status = if ($completedCount -eq $targets.Count) { 'success' } elseif ($completedCount -gt 0) { 'partial' } else { 'failed' }
[pscustomobject][ordered]@{
    status = $status
    target_count = $targets.Count
    completed_count = $completedCount
    failed_keys = @($failedKeys)
    csv_path = $outputCsv
} | ConvertTo-Json -Compress
