import json
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize("platform", ["naver", "coupang"])
def test_collection_filters_ads_and_wrong_products_before_limit(platform):
    script = Path(f".agents/skills/{platform}-ui-collector/scripts/collect_{platform}_ui.ps1").resolve()
    cases = [
        ["광고 국산 쌀 10kg 30,000원", "쌀", False],
        ["AD 국산 쌀 10kg 30,000원", "쌀", False],
        ["쌀국수 10kg 30,000원", "쌀", False],
        ["감자 10kg 30,000원", "쌀", False],
        ["양배추 1포기 3,000원", "배추", False],
        ["배추김치 1포기 3,000원", "배추", False],
        ["국산 쌀 10kg 30,000원", "쌀", True],
        ["해남 배추 1포기 3,000원", "배추", True],
        ["국내산 깐마늘 1kg 9,000원", "깐마늘(국산)", True],
        ["중국산 깐마늘 1kg 9,000원", "깐마늘(국산)", False],
    ]
    command = r'''
    $ErrorActionPreference = 'Stop'
    $data = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $PSScriptRoot = Split-Path $data.path
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($data.path, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'PowerShell syntax error' }
    $function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-ShoppingProduct'}, $true)
    # AST extraction loses the original script scope; restore its directory.
    Invoke-Expression ($function.Extent.Text.Replace('$PSScriptRoot', "'" + (Split-Path $data.path).Replace("'", "''") + "'"))
    foreach ($case in $data.cases) {
        if ((Test-ShoppingProduct -RawName $case[0] -ItemName $case[1]) -ne $case[2]) { throw 'Product filtering mismatch' }
    }
    '''
    result = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command], input=json.dumps({"path": str(script), "cases": cases}), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    source = script.read_text(encoding="utf-8-sig")
    assert source.index("Test-ShoppingProduct -RawName $name") < source.index("$result.Add($item)")


def test_coupang_skill_declares_explicit_manifest_and_csv_contract() -> None:
    root = Path(".agents/skills/coupang-ui-collector")
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts/collect_coupang_ui.ps1").is_file()
    assert "-ManifestPath" in (root / "SKILL.md").read_text(encoding="utf-8")
    assert "raw_accessible_name" in (
        root / "references/csv-schema.md"
    ).read_text(encoding="utf-8")


def test_ui_script_uses_accessibility_value_pattern_not_screen_coordinates() -> None:
    script = Path(
        ".agents/skills/coupang-ui-collector/scripts/collect_coupang_ui.ps1"
    ).read_text(encoding="utf-8")
    assert "ValuePattern" in script
    assert "SetCursorPos" not in script
    assert "mouse_event" not in script


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("쌀 10kg 42,800원15%35,990원(100g당 360원)최대 1,800원 적립", "35990"),
        ("쌀 10kg 34,900원(100g당 349원)무료배송", "34900"),
    ],
)
def test_coupang_displayed_price_excludes_list_unit_and_reward_prices(raw, expected):
    script = Path(".agents/skills/coupang-ui-collector/scripts/collect_coupang_ui.ps1")
    command = """
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$tokens, [ref]$errors)
    $function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CoupangDisplayedPrice'}, $true)
    if ($null -eq $function) { throw 'Missing price extractor' }
    Invoke-Expression $function.Extent.Text
    Get-CoupangDisplayedPrice -RawName $args[1]
    """
    # Pass data through stdin as JSON, keeping Korean text out of shell quoting.
    command = "$inputData = [Console]::In.ReadToEnd() | ConvertFrom-Json; & {" + command + "} $inputData.path $inputData.raw"
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=json.dumps({"path": str(script.resolve()), "raw": raw}),
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
def test_coupang_homepage_rows_are_not_treated_as_search_results():
    script = Path(".agents/skills/coupang-ui-collector/scripts/collect_coupang_ui.ps1")
    command = """
    $ErrorActionPreference = 'Stop'
    $path = [Console]::In.ReadToEnd()
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$errors)
    $function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-AccessibleProductRows'}, $true)
    Invoke-Expression $function.Extent.Text
    function Find-CoupangDocument { return [pscustomobject]@{Current=[pscustomobject]@{Name='Coupang homepage'}} }
    @(Get-AccessibleProductRows -Maximum 8 -Query 'rice 10kg').Count
    """
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=str(script.resolve()), text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0"


@pytest.mark.skipif(shutil.which("powershell.exe") is None, reason="Windows PowerShell required")
@pytest.mark.parametrize(
    ("raw", "unit", "expected"),
    [
        ("깐마늘, 1개, 5kg56,800원(100g당 1,136원)", "1kg", "5kg"),
        ("사과 10KG 21,590원(100g당 216원)", "1kg", "10KG"),
        ("사과, 1개, 5kg56,800원(100g당 1,136원)", "10개", ""),
        ("신고배 7.5kg, 10개86,900원(1세트당 8,690원)", "10개", "10개"),
        ("사과 10개 39,000원(1개당 3,900원)", "10개", "10개"),
        ("고등어 4kg 3kg 2kg 1kg 8,900원", "1마리", ""),
        ("쌀 5kg 10kg 20kg 30,000원", "10kg", ""),
        ("사과 5kg 10kg 10개 30,000원", "10개", ""),
        ("사과 8~10개 30,000원", "10개", ""),
        ("사과 8-10과 30,000원", "10개", ""),
        ("사과 5kg 10과 30,000원", "10개", "10개"),
        ("고등어 900g 3미 12,000원", "1마리", "3마리"),
        ("고등어 3마리 12,000원", "1마리", "3마리"),
        ("고등어 1kg 12,000원", "1마리", ""),
        ("사과 10개 x 2박스 30,000원", "10개", ""),
        ("사과 100g당 500원", "1kg", ""),
        ("쌀 1kg 2개 10,000원", "1kg", ""),
        ("쌀 1kg 2봉 10,000원", "1kg", ""),
        ("사과 10개 2박스 50,000원", "10개", ""),
        ("곰곰 머스크 멜론, 1.5kg, 1개6,900원(100g당 460원)", "1개", "1개"),
        ("머스크 멜론, 1개, 2.5kg12,370원", "1개", "1개"),
        ("멜론 1통(1kg 내외) 6,900원", "1개", "1개"),
        ("멜론 1개 1박스 8kg 30,000원", "1개", ""),
        ("컷팅 멜론 1개 850g 11,090원", "1개", ""),
        ("멜론 반통 1개 500g 7,480원", "1개", ""),
        ("멜론 1개 1.5kg 2kg 9,000원", "1개", ""),
    ],
)
@pytest.mark.parametrize("platform", ["coupang", "naver"])
def test_shopping_quantity_uses_package_measure_not_unit_price(raw, unit, expected, platform):
    script = Path(f".agents/skills/{platform}-ui-collector/scripts/collect_{platform}_ui.ps1")
    command = """
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $data = [Console]::In.ReadToEnd() | ConvertFrom-Json
    $tokens = $null; $errors = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile($data.path, [ref]$tokens, [ref]$errors)
    $function = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-CoupangQuantity'}, $true)
    Invoke-Expression $function.Extent.Text
    $match = Get-CoupangQuantity -RawName $data.raw -ComparisonUnit $data.unit
    if ($match.Success) { $match.Groups[1].Value + $match.Groups[2].Value }
    """
    command = command.replace("Get-CoupangQuantity", f"Get-{platform.title()}Quantity")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        input=json.dumps({"path": str(script.resolve()), "raw": raw, "unit": unit}),
        text=True, encoding="utf-8", capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == expected
