from app.services.comparison_units import comparable_kamis_rows


def catalog(item="111", kind="10", unit="kg", size="10"):
    return [{"item_code": item, "kind_code": kind, "retail_unit": unit, "retail_unit_size": size}]


def row(kind="01", price="3000", variety="20kg(1kg)", **extra):
    return dict(observed_date="2026-09-29", kind_code=kind, price_type="retail", price_krw=price, variety=variety, requested_convert_kg="True", region="??", **extra)


def test_rice_converts_kg_to_10kg_without_changing_source():
    source = row()
    rows, notes = comparable_kamis_rows([source], "111", "10", catalog())
    assert rows[0]["price_krw"] == 30000
    assert source["price_krw"] == "3000"
    assert any("20kg" in note for note in notes)


def test_exact_rice_package_preferred_and_not_multiplied_twice():
    rows, _ = comparable_kamis_rows([row(), dict(row("10", "40000", "10kg"), requested_convert_kg="False")], "111", "10", catalog())
    assert len(rows) == 1
    assert rows[0]["price_krw"] == 40000


def test_count_prices_not_treated_as_kg_despite_request_flag():
    rows, notes = comparable_kamis_rows([row("01", "20000", "신고(10개)"), row("01", "3000", "신고(1kg)")], "412", "01", catalog("412", "01", "개", "10"))
    assert [r["price_krw"] for r in rows] == [20000]
    assert notes


def test_different_variety_not_substituted():
    rows, notes = comparable_kamis_rows([row("02", "4000", "여름(1포기)")], "211", "03", catalog("211", "03", "포기", "1"))
    assert not rows
    assert notes


def test_normal_year_reference_is_excluded():
    source = row(); source["region"] = "평년"
    rows, _ = comparable_kamis_rows([source], "111", "10", catalog())
    assert not rows


def test_unconverted_twenty_kg_price_is_halved():
    entries = catalog() + [dict(catalog(kind="01", size="20")[0])]
    source = dict(row(price="60000", variety="20kg"), requested_convert_kg="False")
    rows, _ = comparable_kamis_rows([source], "111", "10", entries)
    assert rows[0]["price_krw"] == 30000


def test_chart_exposes_converted_price_and_explanation():
    from types import SimpleNamespace

    from app.services.analytics import AnalyticsService
    from app.services.comparison import ComparisonService

    prices = SimpleNamespace(search=lambda filters: [row()])
    online = SimpleNamespace(search_summaries=lambda **kw: [])
    market = SimpleNamespace(search=lambda **kw: [])
    entries = SimpleNamespace(entries=lambda: [SimpleNamespace(to_dict=lambda: catalog()[0])])
    service = ComparisonService(prices, online, market, AnalyticsService(),
                                target_keys={("111", "10")}, catalog_repository=entries)
    chart = service.chart("111", None, None, "raw")
    assert chart["series"]["kamis_retail"] == [30000]
    assert chart["raw_series"]["kamis_retail"] == [30000]
    assert chart["comparison_notes"]
