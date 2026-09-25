"""Opens DNS product pages in a real Chromium and reads the price.

dns-shop.ru sits behind the Qrator anti-bot: plain HTTP requests get a 401 with a JS
challenge. A real browser solves the challenge by itself; the persistent profile keeps the
cookies between runs so the challenge is not repeated for every page.
"""

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import Settings
from .dns import PRICE_SELECTOR, TITLE_SELECTOR, ProductPage, parse_product_page

log = logging.getLogger(__name__)

_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"


@dataclass
class FetchResult:
    component_id: int
    page: ProductPage | None
    error: str | None = None


async def fetch_prices(
    settings: Settings,
    items: list[tuple[int, str]],
    on_result: Callable[[FetchResult], Awaitable[None]],
) -> None:
    """Visit every (component_id, url) one by one, calling on_result after each page."""
    from playwright.async_api import async_playwright

    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    # Left behind if the container was killed mid-run; Chromium refuses to open the profile then.
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (settings.browser_profile_dir / name).unlink(missing_ok=True)
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            str(settings.browser_profile_dir),
            headless=settings.headless,
            executable_path=settings.chromium_path,
            locale="ru-RU",
            timezone_id=settings.tz_name,
            viewport={"width": 1366, "height": 800},
            args=["--disable-blink-features=AutomationControlled", "--no-first-run"],
        )
        try:
            await context.add_init_script(_STEALTH_JS)
            if settings.dns_city:
                await context.add_cookies([{
                    "name": "city_path", "value": settings.dns_city,
                    "domain": ".dns-shop.ru", "path": "/",
                }])
            page = context.pages[0] if context.pages else await context.new_page()

            for index, (component_id, url) in enumerate(items):
                if index:
                    await asyncio.sleep(random.uniform(settings.delay_min, settings.delay_max))
                try:
                    result = await _fetch_one(page, url)
                    if result.blocked:
                        # The challenge sometimes needs a second attempt.
                        await asyncio.sleep(random.uniform(15, 30))
                        result = await _fetch_one(page, url)
                    error = None
                    if result.blocked:
                        error = "DNS показал проверку антибота (Qrator) и не пустил"
                    elif result.price is None and result.available is not False:
                        error = "Цена на странице не найдена"
                    await on_result(FetchResult(component_id, result, error))
                except Exception as exc:  # one bad page must not stop the whole run
                    log.exception("Failed to fetch %s", url)
                    await on_result(FetchResult(component_id, None, f"{type(exc).__name__}: {exc}"[:300]))
        finally:
            await context.close()


async def _fetch_one(page, url: str) -> ProductPage:
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        # Either the product page is there, or the anti-bot challenge is still running
        # (it reloads the page by itself when solved).
        await page.wait_for_selector(f"{PRICE_SELECTOR}, {TITLE_SELECTOR}", timeout=45_000)
        # The price block is loaded by a separate request after the title.
        await page.wait_for_selector(PRICE_SELECTOR, timeout=15_000)
    except PlaywrightTimeout:
        pass
    await page.wait_for_timeout(1_000)
    return parse_product_page(await page.content())
