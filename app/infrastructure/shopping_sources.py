from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from time import monotonic, perf_counter, sleep
from typing import ClassVar, Protocol
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.core.errors import ShoppingAccessBlocked
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
from log.logger import StructuredLogger


class TextResponse(Protocol):
    text: str
    status_code: int

    def raise_for_status(self) -> None: ...


class ShoppingSession(Protocol):
    def get(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str],
        wait_selectors: tuple[str, ...] = (),
    ) -> TextResponse: ...

    def search_from_home(
        self,
        home_url: str,
        query: str,
        *,
        timeout: float,
        headers: dict[str, str],
        search_input_selectors: tuple[str, ...],
        wait_selectors: tuple[str, ...] = (),
    ) -> TextResponse: ...


class RequestRateLimiter:
    """Guarantee a minimum delay between browser navigations."""

    def __init__(
        self,
        minimum_interval_seconds: float,
        *,
        clock: Callable[[], float] = monotonic,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._minimum_interval_seconds = max(0.0, minimum_interval_seconds)
        self._clock = clock
        self._sleeper = sleeper
        self._last_request_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self._minimum_interval_seconds - (now - self._last_request_at)
            if remaining > 0:
                self._sleeper(remaining)
                now = self._clock()
        self._last_request_at = now


class BrowserResponse:
    _ACCESS_CHALLENGE_MARKERS = (
        "captcha",
        "access denied",
        "자동입력 방지",
        "로봇이 아닙니다",
        "비정상적인 접근",
    )

    def __init__(self, text: str, status_code: int) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code in {403, 418, 429}:
            raise ShoppingAccessBlocked(
                self.status_code,
                f"shopping page returned HTTP {self.status_code}",
            )
        if self.status_code >= 400:
            raise RuntimeError(f"shopping page returned HTTP {self.status_code}")
        normalized = self.text.casefold()
        if any(marker in normalized for marker in self._ACCESS_CHALLENGE_MARKERS):
            raise ShoppingAccessBlocked(None, "access challenge detected")


class PlaywrightShoppingSession:
    """Lazy browser session for JavaScript-rendered public shopping pages."""

    def __init__(
        self,
        *,
        user_data_dir: str | None = None,
        headless: bool = True,
        browser_channel: str | None = "chrome",
        minimum_interval_seconds: float = 5,
    ) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._user_data_dir = user_data_dir
        self._headless = headless
        self._browser_channel = browser_channel
        self._search_pages: dict[str, Page] = {}
        self._rate_limiter = RequestRateLimiter(minimum_interval_seconds)

    def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._playwright = sync_playwright().start()
            if self._user_data_dir:
                self._context = self._playwright.chromium.launch_persistent_context(
                    self._user_data_dir,
                    channel=self._browser_channel,
                    headless=self._headless,
                )
            else:
                self._browser = self._playwright.chromium.launch(
                    channel=self._browser_channel, headless=self._headless
                )
                self._context = self._browser.new_context()
        return self._context

    def get(
        self,
        url: str,
        *,
        timeout: float,
        headers: dict[str, str],
        wait_selectors: tuple[str, ...] = (),
    ) -> BrowserResponse:
        context = self._ensure_context()
        context.set_extra_http_headers(headers)
        page = context.new_page()
        try:
            self._rate_limiter.wait()
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=round(timeout * 1000),
            )
            status_code = response.status if response else 200
            if status_code < 400 and wait_selectors:
                try:
                    page.wait_for_function(
                        "selectors => selectors.some(s => document.querySelector(s))",
                        arg=list(wait_selectors),
                        timeout=round(timeout * 1000),
                    )
                except PlaywrightTimeoutError:
                    pass
            return BrowserResponse(page.content(), status_code)
        finally:
            page.close()

    def search_from_home(
        self,
        home_url: str,
        query: str,
        *,
        timeout: float,
        headers: dict[str, str],
        search_input_selectors: tuple[str, ...],
        wait_selectors: tuple[str, ...] = (),
    ) -> BrowserResponse:
        context = self._ensure_context()
        context.set_extra_http_headers(headers)
        page = self._search_pages.get(home_url)
        status_code = 200
        if page is None or page.is_closed():
            page = context.new_page()
            self._search_pages[home_url] = page
            self._rate_limiter.wait()
            response = page.goto(
                home_url,
                wait_until="domcontentloaded",
                timeout=round(timeout * 1000),
            )
            status_code = response.status if response else 200
            home_response = BrowserResponse(page.content(), status_code)
            home_response.raise_for_status()

        try:
            page.wait_for_function(
                "selectors => selectors.some(s => document.querySelector(s))",
                arg=list(search_input_selectors),
                timeout=round(timeout * 1000),
            )
        except PlaywrightTimeoutError:
            return BrowserResponse(page.content(), status_code)

        search_input = next(
            (
                locator
                for selector in search_input_selectors
                if (locator := page.locator(selector).first).count()
                and locator.is_visible()
            ),
            None,
        )
        if search_input is None:
            return BrowserResponse(page.content(), status_code)

        self._rate_limiter.wait()
        search_input.fill(query)
        search_input.press("Enter")
        try:
            page.wait_for_load_state(
                "domcontentloaded", timeout=round(timeout * 1000)
            )
            if wait_selectors:
                page.wait_for_function(
                    "selectors => selectors.some(s => document.querySelector(s))",
                    arg=list(wait_selectors),
                    timeout=round(timeout * 1000),
                )
        except PlaywrightTimeoutError:
            pass
        return BrowserResponse(page.content(), 200)

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
            self._search_pages.clear()
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None


class HtmlShoppingSource:
    platform: ClassVar[str]
    search_url: ClassVar[str]
    card_selector: ClassVar[str]
    link_selector: ClassVar[str]
    price_selector: ClassVar[str]
    shipping_selector: ClassVar[str]
    member_selector: ClassVar[str]
    no_result_selector: ClassVar[str]

    def __init__(
        self,
        session: ShoppingSession | None,
        logger: StructuredLogger,
        *,
        timeout: float = 30,
    ) -> None:
        self._session = session
        self._logger = logger
        self._timeout = timeout

    def search(
        self, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
        if self._session is None:
            raise RuntimeError(f"{self.platform} shopping session is not configured")
        query = f"{entry.item_name} {entry.variety}".strip()
        url = self.search_url.format(query=quote_plus(query))
        started = perf_counter()
        try:
            response = self._request(query, url)
            response.raise_for_status()
            rows = self.parse_html(response.text, entry, observed_date)
            self._logger.info(  # noqa: PLE1205 - custom structured logger
                "shopping.search.succeeded",
                "Shopping search completed",
                source=self.platform,
                item_code=entry.item_code,
                kind_code=entry.kind_code,
                record_count=len(rows),
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return rows
        except Exception as error:
            self._logger.exception(  # noqa: PLE1205 - custom structured logger
                "shopping.search.failed",
                "Shopping search failed",
                error,  # noqa: TRY401 - custom logger records explicit error metadata
                source=self.platform,
                item_code=entry.item_code,
                kind_code=entry.kind_code,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            raise

    def _request(self, query: str, url: str) -> TextResponse:
        if self._session is None:
            raise RuntimeError(f"{self.platform} shopping session is not configured")
        return self._session.get(
            url,
            timeout=self._timeout,
            headers={},
            wait_selectors=(self.card_selector, self.no_result_selector),
        )

    def parse_html(
        self, html: str, entry: ProductCatalogEntry, observed_date: date
    ) -> list[ShoppingOffer]:
        soup = BeautifulSoup(html, "html.parser")
        result: list[ShoppingOffer] = []
        for index, card in enumerate(soup.select(self.card_selector)):
            if not isinstance(card, Tag):
                continue
            link = card.select_one(self.link_selector)
            price_node = card.select_one(self.price_selector)
            if not isinstance(link, Tag) or not isinstance(price_node, Tag):
                continue
            title = link.get_text(" ", strip=True) or str(link.get("title", ""))
            base_price = self._money(price_node.get_text(" ", strip=True))
            if base_price is None or not title:
                continue
            shipping_node = card.select_one(self.shipping_selector)
            shipping = (
                self._money(shipping_node.get_text(" ", strip=True))
                if isinstance(shipping_node, Tag)
                else Decimal(0)
            )
            member_node = card.select_one(self.member_selector)
            member_price = (
                self._money(member_node.get_text(" ", strip=True))
                if isinstance(member_node, Tag)
                else None
            )
            scope = (
                str(member_node.get("data-scope", "")) or None
                if isinstance(member_node, Tag)
                else None
            )
            if isinstance(member_node, Tag) and scope is None:
                scope = self._discount_scope(
                    member_node.get_text(" ", strip=True),
                    card.get_text(" ", strip=True),
                )
            quantity, unit = self._quantity(title)
            match_status = self._match_status(title, entry)
            product_id = str(card.get("data-id", "")) or f"{entry.item_code}-{index}"
            result.append(
                ShoppingOffer(
                    platform=self.platform,
                    product_id=product_id,
                    title=title,
                    url=str(link.get("href", "")),
                    item_code=entry.item_code,
                    kind_code=entry.kind_code,
                    match_status=match_status,
                    base_price=base_price,
                    member_price=member_price,
                    member_discount_scope=scope,
                    shipping_fee=shipping or Decimal(0),
                    quantity=quantity,
                    unit=unit,
                    available=True,
                    observed_date=observed_date,
                    collected_at=datetime.now(ZoneInfo("Asia/Seoul")),
                )
            )
        return result

    @staticmethod
    def _money(text: str) -> Decimal | None:
        digits = re.sub(r"[^0-9]", "", text)
        return Decimal(digits) if digits else None

    @staticmethod
    def _quantity(title: str) -> tuple[Decimal, str]:
        match = re.search(
            r"(\d+(?:\.\d+)?)\s*(kg|g|개|마리|L|ml)", title, re.IGNORECASE
        )
        if not match:
            return Decimal(1), "unit"
        value = Decimal(match.group(1))
        unit = match.group(2).lower()
        if unit == "g":
            return value / Decimal(1000), "kg"
        if unit == "ml":
            return value / Decimal(1000), "l"
        return value, unit

    @staticmethod
    def _match_status(title: str, entry: ProductCatalogEntry) -> MatchStatus:
        normalized = re.sub(r"\s+", "", title).casefold()
        item = re.sub(r"\s+", "", entry.item_name).casefold()
        variety = re.sub(r"\s+", "", entry.variety).casefold()
        if item not in normalized:
            return MatchStatus.REJECTED
        if variety and variety not in normalized:
            return MatchStatus.COMPATIBLE
        return MatchStatus.EXACT

    @staticmethod
    def _discount_scope(label: str, context: str) -> str | None:
        text = f"{label} {context}".casefold()
        restricted = ("카드", "쿠폰", "첫구매", "결제", "와우", "멤버십", "유료")
        if "회원" in text and not any(keyword in text for keyword in restricted):
            return "all_members"
        return "restricted"


class NaverShoppingSource(HtmlShoppingSource):
    platform = "naver"
    search_url = "https://search.shopping.naver.com/search/all?query={query}"
    card_selector = "[class*='product_item']"
    link_selector = "[class*='product_link']"
    price_selector = "[class*='price_num'], .price"
    shipping_selector = "[class*='delivery'], .shipping"
    member_selector = "[class*='member-price']"
    no_result_selector = "[class*='noResult'], [class*='no_result']"


class CoupangShoppingSource(HtmlShoppingSource):
    platform = "coupang"
    search_url = "https://www.coupang.com/np/search?q={query}"
    home_url = "https://www.coupang.com/"
    search_input_selectors = (
        "#headerSearchKeyword",
        "input[name='q']",
        "input[type='search']",
    )
    card_selector = "li.search-product, [data-product-id]"
    link_selector = "a.search-product-link, a[href*='/vp/products/']"
    price_selector = ".price-value, [class*='price-value']"
    shipping_selector = ".delivery-fee"
    member_selector = ".member-price"
    no_result_selector = ".no-result, .search-no-result"

    def _request(self, query: str, url: str) -> TextResponse:
        if self._session is None:
            raise RuntimeError("coupang shopping session is not configured")
        return self._session.search_from_home(
            self.home_url,
            query,
            timeout=self._timeout,
            headers={},
            search_input_selectors=self.search_input_selectors,
            wait_selectors=(self.card_selector, self.no_result_selector),
        )
