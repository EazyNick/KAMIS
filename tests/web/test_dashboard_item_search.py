from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[2] / "app" / "web" / "dashboard.html"


def test_dashboard_item_selector_uses_live_filtered_custom_dropdown() -> None:
    html = DASHBOARD.read_text(encoding="utf-8")

    assert 'id="itemSearch"' in html
    assert 'role="combobox"' in html
    assert 'aria-controls="itemDropdown"' in html
    assert 'aria-expanded="false"' in html
    assert 'placeholder="품목 선택 · 검색"' in html
    assert 'id="itemDropdown"' in html
    assert 'class="item-dropdown"' in html
    assert '<datalist id="itemOptions"></datalist>' not in html
    assert 'list="itemOptions"' not in html

    # Keep the hidden select as the selected item-code source used by existing
    # chart and correlation loading code.
    assert 'id="itemSelect"' in html
    assert 'hidden' in html

    # Every input event must immediately filter and re-render the visible menu.
    assert "function filteredItemChoices()" in html
    assert "function renderItemDropdown()" in html
    assert "function handleItemSearchInput()" in html
    assert "document.querySelector('#itemSearch').oninput=handleItemSearchInput" in html
    assert "itemLabel(x).toLowerCase().includes(query)" in html

    # Selecting a visible result updates the hidden item code and closes menu.
    assert "function selectItemChoice(itemCode)" in html
    assert "select.value=itemCode" in html
    assert "closeItemDropdown()" in html
