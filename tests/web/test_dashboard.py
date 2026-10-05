from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Route, sync_playwright

DASHBOARD = Path(__file__).resolve().parents[2] / "app" / "web" / "dashboard.html"


@pytest.mark.parametrize("has_kamis_commodities", [True, False])
def test_dashboard_defaults_to_kamis_futures_and_preserves_manual_selection(
    has_kamis_commodities: bool,
) -> None:
    requested_urls: list[str] = []
    page_errors: list[str] = []
    catalog_item = {
        "category_code": "100",
        "category_name": "식량작물",
        "item_code": "222",
        "item_name": "감자",
        "kind_code": "01",
        "variety": "수미",
        "wholesale_rank_codes": "04",
        "retail_rank_codes": "04",
    }
    chart_payload = {
        "comparison_kinds": {"111": "10"},
        "item_code": "222",
        "mode": "base100",
        "dates": ["2026-09-24", "2026-09-25"],
        "series": {
            "kamis_retail": [100.0, 100.0],
            "kamis_wholesale": [100.0, 100.0],
            "online_naver": [100.0, 100.0],
            "online_coupang": [100.0, 100.0],
            "online_combined": [100.0, 100.0],
            "kospi": [100.0, 100.0],
            "kosdaq": [100.0, 100.0],
            "sp500": [100.0, 100.0],
            "nasdaq": [100.0, 100.0],
            "dow_jones": [100.0, 100.0],
            "rough_rice_futures": [100.0, 100.0],
            "soybean_futures": [100.0, 100.0],
            "wheat_futures": [100.0, 100.0],
            "coffee_futures": [100.0, 100.0],
            "orange_juice_futures": [100.0, 100.0],
        },
        "raw_series": {
            "kamis_retail": [2350.0, 2400.0],
            "coffee_futures": [200.0, 260.0],
            "orange_juice_futures": [100.0, 200.0],
        },
    }
    responses = {
        "/health": {
            "status": "ok",
            "collection_running": False,
            "latest_run": {"requested_end": "2026-09-24", "status": "success"},
        },
        "/api/v1/catalog": {
            "items": [catalog_item] + ([
                {**catalog_item, "item_code": "111", "item_name": "쌀", "kind_code": "01", "variety": "20kg"},
                {**catalog_item, "item_code": "111", "item_name": "쌀", "kind_code": "10", "variety": "10kg"},
                {**catalog_item, "item_code": "141", "item_name": "콩"},
            ] if has_kamis_commodities else []),
            "total": 3 if has_kamis_commodities else 1,
        },
        "/api/v1/online/summaries": {"items": [], "total": 0},
        "/api/v1/market": {
            "items": [
                {
                    "observed_date": "2026-09-24",
                    "series_id": "kospi",
                    "ticker": "^KS11",
                    "close": 2600,
                    "currency": "index",
                    "unit": "index points",
                }
            ],
            "total": 150,
            "limit": 100,
            "offset": 0,
        },
        "/api/v1/dashboard/defaults": {
            "item_code": "222",
            "start_date": "2026-06-27",
            "end_date": "2026-09-24",
            "mode": "base100",
        },
        "/api/v1/dashboard/bootstrap": {
            "defaults": {
                "item_code": "222",
                "start_date": "2026-06-27",
                "end_date": "2026-09-24",
                "mode": "base100",
            },
            "chart": chart_payload,
        },
        "/api/v1/comparison": chart_payload,
        "/api/v1/correlations": [],
    }

    def handle(route: Route) -> None:
        requested_urls.append(route.request.url)
        parsed = urlparse(route.request.url)
        if parsed.path == "/":
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=DASHBOARD.read_text(encoding="utf-8"),
            )
            return
        payload = responses.get(parsed.path)
        if payload is None:
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 2000, "height": 1200})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.add_init_script(
            """
            window.__arcCount = 0;
            const originalGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (...args) {
              const context = originalGetContext.apply(this, args);
              const originalArc = context.arc.bind(context);
              context.arc = function (...arcArgs) {
                window.__arcCount += 1;
                return originalArc(...arcArgs);
              };
              return context;
            };
            """
        )
        page.route("**/*", handle)
        page.goto("http://dashboard.test/")
        page.wait_for_timeout(300)

        assert page_errors == []
        assert page.locator("#itemSelect").input_value() == "222"
        if has_kamis_commodities:
            assert page.locator('#itemSelect option[value="111"]').inner_text() == "쌀 · 10kg"
        assert page.locator("#startDate").input_value() == "2026-06-27"
        assert page.locator("#endDate").input_value() == "2026-09-24"
        assert page.locator("#periodPreset").input_value() == "20"
        assert page.locator("#comparisonChart").evaluate("canvas => canvas.width") > 0
        assert not any("/api/v1/comparison?" in url for url in requested_urls)

        page.locator("#periodPreset").select_option("5")
        page.wait_for_timeout(50)
        assert page.locator("#startDate").input_value() == "2021-09-24"

        page.locator("#tableDataset").select_option("market")
        page.wait_for_timeout(50)
        assert "1-100 / 150건" in page.locator("#tablePageInfo").inner_text()
        page.locator("#tableNext").click()
        page.wait_for_timeout(50)
        assert any(
            "/api/v1/market?" in url and "offset=100" in url and "order=desc" in url
            for url in requested_urls
        )
        assert any("/api/v1/dashboard/bootstrap" in url for url in requested_urls)
        assert page.get_by_role("navigation").is_visible()
        dashboard_box = page.locator("#dashboard").bounding_box()
        overview_box = page.locator("#overview").bounding_box()
        chart_box = page.locator("#comparisonChart").bounding_box()
        assert dashboard_box is not None
        assert overview_box is not None
        assert chart_box is not None
        assert dashboard_box["y"] < overview_box["y"]
        assert dashboard_box["width"] >= 1800
        assert chart_box["height"] >= 560
        assert page.locator(".featured-badge").count() == 0
        for key in ("rough_rice_futures", "soybean_futures"):
            is_off = "off" in page.locator(f'[data-key="{key}"]').get_attribute("class")
            assert is_off
        for key in ("orange_juice_futures", "coffee_futures", "wheat_futures"):
            assert "off" in page.locator(f'[data-key="{key}"]').get_attribute("class")
        orange = page.locator('[data-key="orange_juice_futures"]')
        orange.click()
        assert "off" not in orange.get_attribute("class")
        page.evaluate("applyBootstrap", responses["/api/v1/dashboard/bootstrap"])
        assert "off" not in orange.get_attribute("class")
        page.locator("#legend .chip:not(.off)").evaluate_all("chips => chips.forEach(chip => chip.click())")
        page.evaluate("applyBootstrap", responses["/api/v1/dashboard/bootstrap"])
        assert page.locator("#legend .chip:not(.off)").count() == 0
        page.locator('[data-key="kamis_retail"]').click()
        page.mouse.move(chart_box["x"] + 74, chart_box["y"] + chart_box["height"] / 2)
        tooltip = page.locator("#chartTooltip")
        assert tooltip.is_visible()
        assert "2026-09-24" in tooltip.inner_text()
        assert "KAMIS 소매" in tooltip.inner_text()
        assert "시가 대비 100" in tooltip.inner_text()
        assert "실제값 2,350" in tooltip.inner_text()
        page.mouse.move(0, 0)
        assert not tooltip.is_visible()
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(100)
        mobile_chart_box = page.locator("#comparisonChart").bounding_box()
        assert page.get_by_role("navigation").is_visible()
        assert mobile_chart_box is not None
        assert mobile_chart_box["height"] >= 400
        browser.close()


def test_dashboard_refreshes_chart_after_startup_collection_finishes() -> None:
    health_calls = 0
    bootstrap_calls = 0
    catalog_item = {
        "category_code": "100",
        "category_name": "식량작물",
        "item_code": "111",
        "item_name": "쌀",
        "kind_code": "01",
        "variety": "일반계",
        "wholesale_rank_codes": "04",
        "retail_rank_codes": "04",
    }

    def handle(route: Route) -> None:
        nonlocal health_calls, bootstrap_calls
        parsed = urlparse(route.request.url)
        if parsed.path == "/":
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=DASHBOARD.read_text(encoding="utf-8"),
            )
            return
        if parsed.path == "/health":
            health_calls += 1
            running = health_calls == 1
            payload = {
                "status": "ok",
                "collection_running": running,
                "latest_run": {
                    "requested_end": "2026-09-24",
                    "status": "running" if running else "success",
                },
            }
        elif parsed.path == "/api/v1/catalog":
            payload = {"items": [catalog_item], "total": 1}
        elif parsed.path == "/api/v1/online/summaries":
            payload = {"items": [], "total": 0}
        elif parsed.path == "/api/v1/dashboard/bootstrap":
            bootstrap_calls += 1
            payload = {
                "defaults": {
                    "item_code": "111",
                    "start_date": "2026-06-27",
                    "end_date": "2026-09-24",
                    "mode": "base100",
                },
                "chart": {
                    "item_code": "111",
                    "mode": "base100",
                    "dates": ["2026-09-24"],
                    "series": {
                        "kamis_retail": [100.0],
                        "kospi": [None if bootstrap_calls == 1 else 100.0],
                    },
                },
            }
        elif parsed.path == "/api/v1/correlations":
            payload = []
        else:
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(
            """
            const nativeSetTimeout = window.setTimeout.bind(window);
            window.setTimeout = (callback, delay, ...args) =>
              nativeSetTimeout(callback, Math.min(delay, 20), ...args);
            window.__arcCount = 0;
            const nativeGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (...args) {
              const context = nativeGetContext.apply(this, args);
              const nativeArc = context.arc.bind(context);
              context.arc = function (...arcArgs) {
                window.__arcCount += 1;
                return nativeArc(...arcArgs);
              };
              return context;
            };
            """
        )
        page.route("**/*", handle)
        page.goto("http://dashboard.test/")
        page.wait_for_function("window.__arcCount >= 3", timeout=1000)

        assert bootstrap_calls >= 2
        browser.close()


def test_dashboard_draws_isolated_market_value_after_missing_date() -> None:
    chart_payload = {
        "item_code": "111",
        "mode": "base100",
        "dates": ["2026-09-21", "2026-09-22", "2026-09-23"],
        "series": {"sp500": [100.0, None, 102.0]},
        "raw_series": {"sp500": [6600.0, None, 6732.0]},
    }

    def handle(route: Route) -> None:
        parsed = urlparse(route.request.url)
        if parsed.path == "/":
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=DASHBOARD.read_text(encoding="utf-8"),
            )
            return
        responses = {
            "/health": {
                "status": "ok",
                "collection_running": False,
                "latest_run": {"requested_end": "2026-09-23", "status": "success"},
            },
            "/api/v1/catalog": {"items": [], "total": 0},
            "/api/v1/online/summaries": {"items": [], "total": 0},
            "/api/v1/dashboard/bootstrap": {
                "defaults": {
                    "item_code": "111",
                    "start_date": "2026-09-21",
                    "end_date": "2026-09-23",
                    "mode": "base100",
                },
                "chart": chart_payload,
            },
            "/api/v1/correlations": [],
        }
        payload = responses.get(parsed.path)
        if payload is None:
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        page.add_init_script(
            """
            window.__chartArcs = [];
            const nativeGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (...args) {
              const context = nativeGetContext.apply(this, args);
              const nativeArc = context.arc.bind(context);
              context.arc = function (x, y, radius, ...arcArgs) {
                window.__chartArcs.push({x, y, radius});
                return nativeArc(x, y, radius, ...arcArgs);
              };
              return context;
            };
            """
        )
        page.route("**/*", handle)
        page.goto("http://dashboard.test/")
        page.wait_for_timeout(200)

        arcs = page.evaluate("window.__chartArcs")
        assert any(arc["radius"] == 3.5 for arc in arcs)
        browser.close()



@pytest.mark.parametrize("missing_middle", [False, True])
def test_dashboard_draws_all_19_series_as_continuous_paths(missing_middle: bool) -> None:
    page_errors: list[str] = []
    series_ids = [
        "kamis_wholesale",
        "kamis_retail",
        "online_naver",
        "online_coupang",
        "online_combined",
        "kospi",
        "kosdaq",
        "sp500",
        "nasdaq",
        "dow_jones",
        "usd_krw",
        "corn_futures",
        "wheat_futures",
        "soybean_futures",
        "rough_rice_futures",
        "coffee_futures",
        "sugar_futures",
        "cotton_futures",
        "orange_juice_futures",
    ]
    chart_payload = {
        "comparison_kinds": {"111": "10"},
        "item_code": "111",
        "mode": "base100",
        "dates": ["2026-09-25", "2026-09-26", "2026-09-27"],
        "series": {
            series_id: [100.0, None if missing_middle else 101.0, 102.0]
            for series_id in series_ids
        },
        "raw_series": {
            series_id: [1000.0, None if missing_middle else 1010.0, 1020.0]
            for series_id in series_ids
        },
    }
    catalog_item = {
        "category_code": "100",
        "category_name": "식량작물",
        "item_code": "111",
        "item_name": "쌀",
        "kind_code": "10",
        "variety": "10kg",
        "wholesale_rank_codes": "04",
        "retail_rank_codes": "04",
    }

    def handle(route: Route) -> None:
        parsed = urlparse(route.request.url)
        if parsed.path == "/":
            route.fulfill(
                status=200,
                content_type="text/html; charset=utf-8",
                body=DASHBOARD.read_text(encoding="utf-8"),
            )
            return
        responses = {
            "/health": {
                "status": "ok",
                "collection_running": False,
                "latest_run": {"requested_end": "2026-09-27", "status": "success"},
            },
            "/api/v1/catalog": {"items": [catalog_item], "total": 1},
            "/api/v1/online/summaries": {"items": [], "total": 0},
            "/api/v1/dashboard/bootstrap": {
                "defaults": {
                    "item_code": "111",
                    "start_date": "2026-09-25",
                    "end_date": "2026-09-27",
                    "mode": "base100",
                },
                "chart": chart_payload,
            },
            "/api/v1/correlations": [],
        }
        payload = responses.get(parsed.path)
        if payload is None:
            route.fulfill(status=404, body="not found")
            return
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(payload, ensure_ascii=False),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.add_init_script(
            """
            window.__seriesMoveToCount = 0;
            window.__seriesLineToCount = 0;
            const nativeGetContext = HTMLCanvasElement.prototype.getContext;
            HTMLCanvasElement.prototype.getContext = function (...args) {
              const context = nativeGetContext.apply(this, args);
              if (context.__continuityInstrumented) return context;
              context.__continuityInstrumented = true;
              const nativeMoveTo = context.moveTo.bind(context);
              const nativeLineTo = context.lineTo.bind(context);
              context.moveTo = function (...moveArgs) {
                if (context.lineWidth === 2) window.__seriesMoveToCount += 1;
                return nativeMoveTo(...moveArgs);
              };
              context.lineTo = function (...lineArgs) {
                if (context.lineWidth === 2) window.__seriesLineToCount += 1;
                return nativeLineTo(...lineArgs);
              };
              return context;
            };
            """
        )
        page.route("**/*", handle)
        page.goto("http://dashboard.test/")
        page.wait_for_timeout(200)

        assert page.locator("#legend .chip").count() == 19
        page.evaluate(
            """
            () => {
              Object.keys(chartData.series).forEach(key => enabled.add(key));
              renderLegend();
              window.__seriesMoveToCount = 0;
              window.__seriesLineToCount = 0;
              draw();
            }
            """
        )
        assert page.locator("#legend .chip:not(.off)").count() == 19
        assert page.evaluate("window.__seriesMoveToCount") == 19
        assert page.evaluate("window.__seriesLineToCount") == (19 if missing_middle else 38)
        assert page.evaluate("chartData.series") == chart_payload["series"]
        assert page.evaluate("chartData.raw_series") == chart_payload["raw_series"]
        assert page_errors == []
        browser.close()
