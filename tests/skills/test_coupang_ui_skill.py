import json
import shutil
import subprocess
from pathlib import Path

import pytest


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
