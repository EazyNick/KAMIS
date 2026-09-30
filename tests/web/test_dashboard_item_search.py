from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "app" / "web" / "dashboard.html"


def test_dashboard_item_selector_is_searchable_combobox() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")

    assert 'id="itemSearch"' in html
    assert 'list="itemOptions"' in html
    assert 'role="combobox"' in html
    assert 'placeholder="품목 선택 · 검색"' in html
    assert '<datalist id="itemOptions"></datalist>' in html

    # Keep the existing hidden select as the selected item-code source used by
    # the chart/correlation loading code and by the existing dashboard tests.
    assert 'id="itemSelect"' in html
    assert 'hidden' in html

    # Suggestions contain item name, variety and code so the browser's native
    # datalist filtering works for every supported search term.
    assert "function itemLabel(x)" in html
    assert "x.item_name" in html
    assert "x.variety" in html
    assert "x.item_code" in html
    assert "function syncItemSelection()" in html
    assert "document.querySelector('#itemSearch').oninput=syncItemSelection" in html
