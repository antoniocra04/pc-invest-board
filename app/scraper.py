"""Opens DNS product pages in a real Chromium and reads the price.

dns-shop.ru sits behind the Qrator anti-bot: plain HTTP requests get a 401 with a JS
challenge. A real browser solves the challenge by itself; the persistent profile keeps the
cookies between runs so the challenge is not repeated for every page.
"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from .config import Settings
from .dns import PRICE_AJAX_MARKER, PRICE_SELECTOR, TITLE_SELECTOR, ProductPage, parse_product_page

log = logging.getLogger(__name__)

_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"

# The price block exists (empty) before the price arrives, so wait for digits in it.
_PRICE_READY_JS = f"""() => {{
    const el = document.querySelector('{PRICE_SELECTOR}');
    return !!el && /\\d/.test(el.textContent);
}}"""


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
                    result, ajax = await _fetch_one(page, url)
                    if result.blocked:
                        # The challenge sometimes needs a second attempt.
                        await asyncio.sleep(random.uniform(15, 30))
                        result, ajax = await _fetch_one(page, url)
                    error = None
                    if result.blocked:
                        error = "DNS показал проверку антибота (Qrator) и не пустил"
                    elif result.price is None and result.available is not False:
                        error = "Цена на странице не найдена"
                    if error:
                        await _save_debug(page, settings.debug_dir, component_id, ajax)
                    await on_result(FetchResult(component_id, result, error))
                except Exception as exc:  # one bad page must not stop the whole run
                    log.exception("Failed to fetch %s", url)
                    await on_result(FetchResult(component_id, None, f"{type(exc).__name__}: {exc}"[:300]))
        finally:
            await context.close()


async def _fetch_one(page, url: str) -> tuple[ProductPage, list[dict]]:
    from playwright.async_api import TimeoutError as PlaywrightTimeout

    ajax: list[dict] = []

    async def on_response(response):
        if PRICE_AJAX_MARKER in response.url:
            try:
                ajax.append({"url": response.url, "status": response.status, "body": await response.json()})
            except Exception:
                ajax.append({"url": response.url, "status": response.status, "body": None})

    page.on("response", on_response)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        try:
            # Either the product page is there, or the anti-bot challenge is still running
            # (it reloads the page by itself when solved).
            await page.wait_for_selector(f"{PRICE_SELECTOR}, {TITLE_SELECTOR}", state="attached", timeout=45_000)
            await page.wait_for_function(_PRICE_READY_JS, timeout=30_000)
        except PlaywrightTimeout:
            pass
        await page.wait_for_timeout(1_500)
        html = await page.content()
    finally:
        page.remove_listener("response", on_response)
    return parse_product_page(html, [a["body"] for a in ajax if a["body"] is not None]), ajax


async def _save_debug(page, debug_dir: Path, component_id: int, ajax: list[dict]) -> None:
    """Keep what the browser saw on a failed check, to see what DNS changed."""
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(debug_dir / f"{component_id}.png"))
        (debug_dir / f"{component_id}.html").write_text(await page.content(), encoding="utf-8")
        (debug_dir / f"{component_id}.json").write_text(
            json.dumps({"page_url": page.url, "ajax": ajax}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.exception("Could not save debug snapshot for component %s", component_id)
