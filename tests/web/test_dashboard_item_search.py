from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "app" / "web" / "dashboard.html"


def test_dashboard_item_selector_supports_search_by_name_variety_and_code() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")
    assert 'id="itemSearch"' in html
    assert 'placeholder="품목명·품종·코드 검색"' in html
    assert "function filterItemOptions()" in html
    assert "x.item_name" in html
    assert "x.variety" in html
    assert "x.item_code" in html
    assert "document.querySelector('#itemSearch').oninput=filterItemOptions" in html
