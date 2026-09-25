from pathlib import Path


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
