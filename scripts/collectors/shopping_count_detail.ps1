# Shared, bounded, read-only product-detail collection for piece/fish targets.
# Dot-source from the platform collector after loading UIAutomation assemblies.

function Get-ShoppingControlValue {
    param($Element)
    try { return [string]$Element.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value }
    catch { return '' }
}

function Get-ShoppingSelectedOption {
    param($Element)
    if ($Element.Current.IsOffscreen -or $Element.Current.Name -match '\uC218\uB7C9|quantity') { return '' }
    try {
        $selection = $Element.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern)
        if ($selection.Current.IsSelected) { return [string]$Element.Current.Name }
    } catch { }
    if ($Element.Current.ControlType -eq [System.Windows.Automation.ControlType]::ComboBox) {
        return Get-ShoppingControlValue $Element
    }
    return ''
}

function ConvertTo-ShoppingCountEvidence {
    param($Snapshot, [string]$ProjectRoot)
    $python = Join-Path $ProjectRoot '.venv/Scripts/python.exe'
    $previousEncoding = $OutputEncoding
    try {
        $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
        Push-Location $ProjectRoot
        try {
            $json = ($Snapshot | ConvertTo-Json -Depth 5 -Compress) | & $python -m app.infrastructure.shopping_count_detail
            if ($LASTEXITCODE -ne 0) { throw 'Detail evidence validation failed' }
            return ($json | ConvertFrom-Json)
        } finally { Pop-Location }
    } finally { $OutputEncoding = $previousEncoding }
}

function Get-ShoppingDetailSnapshot {
    param($Document, [string]$Url, [string]$ComparisonUnit, [string]$ProjectRoot)
    $tree = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $nodes = $Document.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
    if ($nodes.Count -gt 5000) { return $null }
    $attempts = 0
    foreach ($node in $nodes) {
        $selected = Get-ShoppingSelectedOption $node
        if ($selected -notmatch '\d+\s*(\uAC1C|\uACFC|\uBBF8|\uB9C8\uB9AC)') { continue }
        $scope = $node
        # A local option/purchase container, never the entire document (recommendations).
        for ($depth = 0; $depth -lt 5; $depth++) {
            $scope = $tree.GetParent($scope)
            if ($null -eq $scope -or $scope.Current.ControlType -eq [System.Windows.Automation.ControlType]::Document) { break }
            $children = $scope.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
            if ($children.Count -gt 300) { break }
            $texts = [System.Collections.Generic.List[string]]::new()
            $options = [System.Collections.Generic.HashSet[string]]::new()
            $orderCounts = [System.Collections.Generic.HashSet[string]]::new()
            foreach ($child in $children) {
                if ($child.Current.IsOffscreen) { continue }
                $name = [string]$child.Current.Name
                if ($name) { $texts.Add($name) }
                $option = Get-ShoppingSelectedOption $child
                if ($option -match '\d+\s*(\uAC1C|\uACFC|\uBBF8|\uB9C8\uB9AC)') {
                    $null = $options.Add($option)
                    $texts.Add($option)
                }
                if ($name -match '\uC218\uB7C9|quantity') {
                    $value = Get-ShoppingControlValue $child
                    if (-not $value) {
                        try { $value = [string]$child.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern).Current.Value } catch { }
                    }
                    if ($value) { $null = $orderCounts.Add($value) }
                }
            }
            $snapshot = @{
                selected_options = @($options | ForEach-Object { $_ })
                text = $texts -join "`n"
                order_quantity = $(if ($orderCounts.Count -eq 1) { @($orderCounts)[0] } else { '' })
                url = $Url
                comparison_unit = $ComparisonUnit
                product_title = [string]$Document.Current.Name
            }
            if ($snapshot.order_quantity -eq '' -or $snapshot.text -notmatch '\uD310\uB9E4\s*\uAC00|\uD310\uB9E4\s*\uAC00\uACA9|\uCD1D\s*\uC0C1\uD488\s*\uAE08\uC561') { continue }
            $attempts += 1
            if ($attempts -gt 10) { return $null }
            $evidence = ConvertTo-ShoppingCountEvidence -Snapshot $snapshot -ProjectRoot $ProjectRoot
            if ($evidence.verified) { return $evidence }
        }
    }
    return $null
}

function Get-ShoppingTabs {
    param($Window)
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::TabItem)
    return $Window.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
}

function Find-ShoppingNewTab {
    param([string[]]$PreviousIds, [object[]]$Tabs)
    $newTabs = @($Tabs | Where-Object { ($_.GetRuntimeId() -join '.') -notin $PreviousIds })
    if ($newTabs.Count -eq 1) { return $newTabs[0] }
    return $null
}

function Get-ShoppingSelectedTab {
    param($Window)
    foreach ($tab in (Get-ShoppingTabs $Window)) {
        try {
            if ($tab.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected) { return $tab }
        } catch { }
    }
    return $null
}

function Get-ShoppingProductUrl {
    param($Element)
    $url = Get-ShoppingControlValue $Element
    if ($url -match '^https://') { return $url }
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
        [System.Windows.Automation.ControlType]::Hyperlink)
    $urls = @($Element.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition) | ForEach-Object {
        $value = Get-ShoppingControlValue $_
        if ($value -match '^https://(?:www\.)?coupang\.com/vp/products/') { $value }
    } | Select-Object -Unique)
    if ($urls.Count -eq 1) { return $urls[0] }
    return ''
}

function Read-ShoppingCountDetail {
    param($SearchDocument, [string]$Url, [string]$ComparisonUnit, [string]$ProjectRoot)
    if ($Url -notmatch '^https://(?:[a-z0-9-]+\.)*(?:naver\.com|coupang\.com)/') { return $null }
    $tree = [System.Windows.Automation.TreeWalker]::ControlViewWalker
    $window = $SearchDocument
    while ($null -ne $window -and $window.Current.ControlType -ne [System.Windows.Automation.ControlType]::Window) { $window = $tree.GetParent($window) }
    if ($null -eq $window) { return $null }
    $originalTab = Get-ShoppingSelectedTab $window
    if ($null -eq $originalTab) { return $null }
    $previousIds = @(Get-ShoppingTabs $window | ForEach-Object { $_.GetRuntimeId() -join '.' })
    $ownedTab = $null
    try {
        $SearchDocument.SetFocus()
        [System.Windows.Forms.SendKeys]::SendWait('^t')
        Start-Sleep -Milliseconds 400
        $candidate = Find-ShoppingNewTab -PreviousIds $previousIds -Tabs @(Get-ShoppingTabs $window)
        if ($null -eq $candidate) { throw 'Detail tab ownership could not be established' }
        $ownedTab = $candidate
        $active = Get-ShoppingSelectedTab $window
        if ($null -eq $active -or ($active.GetRuntimeId() -join '.') -ne ($ownedTab.GetRuntimeId() -join '.')) { throw 'New detail tab is no longer active' }
        $edits = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
            [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Edit))
        $address = $null
        foreach ($edit in $edits) {
            if ($edit.Current.Name -match '\uC8FC\uC18C|Address' -and -not $edit.Current.IsOffscreen) { $address = $edit; break }
        }
        if ($null -eq $address) { throw 'Chrome address control unavailable' }
        $active = Get-ShoppingSelectedTab $window
        if ($null -eq $active -or ($active.GetRuntimeId() -join '.') -ne ($ownedTab.GetRuntimeId() -join '.')) { throw 'Active tab changed before navigation' }
        $address.SetFocus()
        $address.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($Url)
        [System.Windows.Forms.SendKeys]::SendWait('{ENTER}')
        $deadline = [DateTimeOffset]::Now.AddSeconds(10)
        while ([DateTimeOffset]::Now -lt $deadline) {
            Start-Sleep -Milliseconds 500
            $active = Get-ShoppingSelectedTab $window
            if ($null -eq $active -or ($active.GetRuntimeId() -join '.') -ne ($ownedTab.GetRuntimeId() -join '.')) { throw 'Active tab changed during detail read' }
            $currentUrl = Get-ShoppingControlValue $address
            # Require an actual product URL, not a search/listing/login or arbitrary redirect.
            if ($currentUrl -notmatch '^https://(?:(?:www\.)?coupang\.com/vp/products/\d+|(?:smartstore|brand)\.naver\.com/[^/]+/products/\d+|shopping\.naver\.com/(?:window-products|products)/[^/?]+)') { continue }
            $documents = $window.FindAll([System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Document))
            foreach ($document in $documents) {
                if ($document.Current.IsOffscreen) { continue }
                $result = Get-ShoppingDetailSnapshot -Document $document -Url $currentUrl -ComparisonUnit $ComparisonUnit -ProjectRoot $ProjectRoot
                if ($null -ne $result) { return $result }
            }
        }
        return $null
    }
    catch {
        Write-Warning "Product detail not verified: $($_.Exception.Message)"
        return $null
    }
    finally {
        try {
            if ($null -ne $ownedTab) {
                # Invoke the owned tab's close button, never Ctrl+W on an arbitrary active tab.
                $live = @(Get-ShoppingTabs $window | Where-Object { ($_.GetRuntimeId() -join '.') -eq ($ownedTab.GetRuntimeId() -join '.') })
                if ($live.Count -eq 1) {
                    $buttons = $live[0].FindAll([System.Windows.Automation.TreeScope]::Descendants,
                        [System.Windows.Automation.PropertyCondition]::new([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Button))
                    $closed = $false
                    foreach ($button in $buttons) {
                        if ($button.Current.Name -match '\uB2EB\uAE30|Close') {
                            $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
                            $closed = $true
                            break
                        }
                    }
                    if (-not $closed) { throw 'Owned detail tab cleanup failed: close button unavailable' }
                }
            }
        }
        catch {
            $_.Exception.Data['DetailCleanupFailed'] = $true
            throw
        }
    }
}
