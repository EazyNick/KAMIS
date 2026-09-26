from pathlib import Path


def test_naver_skill_declares_manifest_and_csv_contract() -> None:
    root = Path(".agents/skills/naver-ui-collector")
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts/collect_naver_ui.ps1").is_file()
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    schema = (root / "references/csv-schema.md").read_text(encoding="utf-8")
    assert "-ManifestPath" in skill
    assert "raw_accessible_name" in schema
    assert "platform" in schema


def test_naver_ui_script_starts_at_home_and_uses_accessibility() -> None:
    script = Path(
        ".agents/skills/naver-ui-collector/scripts/collect_naver_ui.ps1"
    ).read_text(encoding="utf-8")
    assert "https://shopping.naver.com/" in script
    assert "ValuePattern" in script
    assert "SetCursorPos" not in script
    assert "mouse_event" not in script
    assert "search.shopping.naver.com/search" not in script


def test_naver_ui_script_collects_unique_hyperlinks_with_real_sale_data() -> None:
    script = Path(
        ".agents/skills/naver-ui-collector/scripts/collect_naver_ui.ps1"
    ).read_text(encoding="utf-8")

    assert "ControlType]::ListItem" not in script
    assert "ControlType]::Group" not in script
    assert "$seen.Add($url)" in script
    assert "$urlPattern.Current.Value" in script
    assert "New-StableProductId -RawName $url" in script
    assert "$discountedPriceMatch.Groups[2]" in script
    assert "$document.Current.Name -match [regex]::Escape($Query)" in script
    assert "-Query ([string]$target.query)" in script
