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
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.core.errors import ShoppingAccessBlocked
from app.domain.models import ProductCatalogEntry
from app.domain.online_models import MatchStatus, ShoppingOffer
from log.context_logger import ContextLogger


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
        minimum_interval_seconds: float = 5,
    ) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._user_data_dir = user_data_dir
        self._headless = headless
        self._rate_limiter = RequestRateLimiter(minimum_interval_seconds)

    def _ensure_context(self) -> BrowserContext:
        if self._context is None:
            self._playwright = sync_playwright().start()
            if self._user_data_dir:
                self._context = self._playwright.chromium.launch_persistent_context(
                    self._user_data_dir, headless=self._headless
                )
            else:
                self._browser = self._playwright.chromium.launch(
                    headless=self._headless
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

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
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
        logger: ContextLogger,
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
            response = self._session.get(
                url,
                timeout=self._timeout,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
                    )
                },
                wait_selectors=(self.card_selector, self.no_result_selector),
            )
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
    card_selector = "li.search-product"
    link_selector = "a.search-product-link"
    price_selector = ".price-value"
    shipping_selector = ".delivery-fee"
    member_selector = ".member-price"
    no_result_selector = ".no-result, .search-no-result"
