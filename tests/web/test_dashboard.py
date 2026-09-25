from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Route, sync_playwright

DASHBOARD = Path(__file__).resolve().parents[2] / "app" / "web" / "dashboard.html"


def test_dashboard_applies_defaults_and_draws_single_observation() -> None:
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
    responses = {
        "/health": {
            "status": "ok",
            "collection_running": False,
            "latest_run": {"requested_end": "2026-09-24", "status": "success"},
        },
        "/api/v1/catalog": {"items": [catalog_item], "total": 1},
        "/api/v1/online/summaries": {"items": [], "total": 0},
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
            "chart": {
                "item_code": "222",
                "mode": "base100",
                "dates": ["2026-09-24"],
                "series": {"kamis_retail": [100.0]},
            },
        },
        "/api/v1/comparison": {
            "item_code": "222",
            "mode": "base100",
            "dates": ["2026-09-24"],
            "series": {"kamis_retail": [100.0]},
        },
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
        page = browser.new_page()
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
        assert page.locator("#startDate").input_value() == "2026-06-27"
        assert page.locator("#endDate").input_value() == "2026-09-24"
        assert page.evaluate("window.__arcCount") > 0
        assert any("/api/v1/dashboard/bootstrap" in url for url in requested_urls)
        assert not any("/api/v1/comparison?" in url for url in requested_urls)
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
