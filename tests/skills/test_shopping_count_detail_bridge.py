import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("option,expected", [("고등어 2마리 × 3팩", "6"), ("고등어 8~10미", None)])
def test_powershell_detail_bridge_preserves_korean_evidence(option, expected):
    command = r'''
    $ErrorActionPreference = 'Stop'
    $data = [Console]::In.ReadToEnd() | ConvertFrom-Json
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($data.path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
    . $data.path
    ConvertTo-ShoppingCountEvidence -Snapshot $data.snapshot -ProjectRoot $data.root | ConvertTo-Json -Compress
    '''
    root = Path.cwd()
    snapshot = dict(selected_options=[option], text=f"{option}\n판매가 12,000원\n무료배송", order_quantity="1", comparison_unit="1마리", url="https://www.coupang.com/vp/products/1")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], input=json.dumps(dict(path=str(root / "scripts/collectors/shopping_count_detail.ps1"), root=str(root), snapshot=snapshot)), text=True, encoding="utf-8", capture_output=True)
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["verified"] is (expected is not None)
    if expected:
        assert evidence["quantity"] == expected
        assert evidence["selected_option"] == option
        assert evidence["displayed_price"] == "12000"


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("ids,expected", [([1, 2], ""), ([1, 2, 3], "3"), ([1, 2, 3, 4], "")])
def test_tab_ownership_never_adopts_preexisting_or_ambiguous_tabs(ids, expected):
    command = r'''
    $ErrorActionPreference = 'Stop'
    $data = [Console]::In.ReadToEnd() | ConvertFrom-Json
    . $data.path
    $tabs = @($data.ids | ForEach-Object {
        $tab = [pscustomobject]@{Id=$_}
        $tab | Add-Member ScriptMethod GetRuntimeId { return @($this.Id) }
        $tab
    })
    $owned = Find-ShoppingNewTab -PreviousIds @('1', '2') -Tabs $tabs
    if ($null -ne $owned) { $owned.Id }
    '''
    process = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], input=json.dumps(dict(path=str(Path("scripts/collectors/shopping_count_detail.ps1").resolve()), ids=ids)), text=True, capture_output=True)
    assert process.returncode == 0, process.stderr
    assert process.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("platform", ["naver", "coupang"])
def test_detail_cleanup_failure_aborts_collection_instead_of_reporting_success(platform):
    command = r'''
    $ErrorActionPreference = 'Stop'
    $path = [Console]::In.ReadToEnd()
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    $catch = $ast.Find({param($node) $node -is [System.Management.Automation.Language.CatchClauseAst] -and $node.Body.Extent.Text.Contains('$failedKeys.Add($key)')}, $true)
    $failedKeys = [System.Collections.Generic.List[string]]::new()
    $key = '411:05'
    $failure = [System.Exception]::new('cleanup failed')
    $failure.Data['DetailCleanupFailed'] = $true
    try {
        Invoke-Expression ('try { throw $failure } catch ' + $catch.Body.Extent.Text)
        'incorrect-success'
    } catch {
        if (-not $_.Exception.Data['DetailCleanupFailed']) { throw }
        'cleanup-aborted'
    }
    '''
    path = Path(f".agents/skills/{platform}-ui-collector/scripts/collect_{platform}_ui.ps1").resolve()
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], input=str(path), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "cleanup-aborted"
