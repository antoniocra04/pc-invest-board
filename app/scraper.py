"""Opens DNS product pages in a real browser and reads the price.

dns-shop.ru sits behind the Qrator anti-bot: plain HTTP requests get a 401 with a JS
challenge, and a browser that the challenge flags as automated gets "HTTP 403 Доступ
запрещён". Plain Playwright Chromium on a Raspberry Pi is flagged, so there are two
stealthier engines:

- camoufox: Firefox build that spoofs a regular desktop fingerprint (default);
- chromium: Chromium driven through patchright, a Playwright fork that hides the
  DevTools traces anti-bots look for.

The persistent profile keeps the anti-bot cookies between runs.
"""

import asyncio
import json
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from .config import Settings
from .dns import PRICE_AJAX_MARKER, PRICE_SELECTOR, TITLE_SELECTOR, ProductPage, parse_product_page

log = logging.getLogger(__name__)

ENGINES = ("camoufox", "chromium")

# The price block exists (empty) before the price arrives, so wait for digits in it.
_PRICE_READY_JS = f"""() => {{
    const el = document.querySelector('{PRICE_SELECTOR}');
    return !!el && /\\d/.test(el.textContent);
}}"""

BLOCKED_ERROR = "DNS не пустил браузер: антибот Qrator ответил «Доступ запрещён» (403)"


@dataclass
class FetchResult:
    component_id: int
    page: ProductPage | None
    error: str | None = None


@asynccontextmanager
async def open_browser(settings: Settings, engine: str | None = None):
    """A persistent browser context of the chosen engine."""
    engine = engine or settings.browser
    if engine not in ENGINES:
        raise ValueError(f"Unknown BROWSER={engine!r}, expected one of {ENGINES}")
    profile = settings.data_dir / f"browser-{engine}"
    profile.mkdir(parents=True, exist_ok=True)
    # Left behind if the container was killed mid-run; the browser refuses to open the profile then.
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lock", ".parentlock"):
        (profile / name).unlink(missing_ok=True)

    if engine == "camoufox":
        from camoufox.async_api import AsyncCamoufox

        async with AsyncCamoufox(
            persistent_context=True,
            user_data_dir=str(profile),
            headless=settings.headless,
            os="windows",
            locale="ru-RU",
            # No timezone override: Firefox takes it from the container's TZ, and Camoufox warns
            # that a manual timezone can give the browser away.
            humanize=True,
        ) as context:
            yield context
    else:
        from patchright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                str(profile),
                headless=settings.headless,
                executable_path=settings.chromium_path,
                no_viewport=True,
                locale="ru-RU",
                timezone_id=settings.tz_name,
            )
            try:
                yield context
            finally:
                await context.close()


async def fetch_prices(
    settings: Settings,
    items: list[tuple[int, str]],
    on_result: Callable[[FetchResult], Awaitable[None]],
) -> None:
    """Visit every (component_id, url) one by one, calling on_result after each page."""
    async with open_browser(settings) as context:
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
                result, ajax = await fetch_page(page, url)
                if result.blocked and not result.forbidden:
                    # The JS challenge sometimes needs a second attempt.
                    await asyncio.sleep(random.uniform(15, 30))
                    result, ajax = await fetch_page(page, url)
                error = None
                if result.blocked:
                    error = BLOCKED_ERROR if result.forbidden else "DNS не пропустил проверку антибота (Qrator)"
                elif result.price is None and result.available is not False:
                    error = "Цена на странице не найдена"
                if error:
                    await save_debug(page, settings.debug_dir, component_id, ajax)
                await on_result(FetchResult(component_id, result, error))
                if result.forbidden:
                    # Knocking again only extends the ban; skip the rest of this run.
                    for skipped_id, _ in items[index + 1:]:
                        await on_result(FetchResult(skipped_id, None, BLOCKED_ERROR + ", проверка остановлена"))
                    return
            except Exception as exc:  # one bad page must not stop the whole run
                log.exception("Failed to fetch %s", url)
                await on_result(FetchResult(component_id, None, f"{type(exc).__name__}: {exc}"[:300]))


async def fetch_page(page, url: str) -> tuple[ProductPage, list[dict]]:
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
        except Exception as exc:
            # Playwright and patchright each have their own TimeoutError class.
            if type(exc).__name__ != "TimeoutError":
                raise
        await page.wait_for_timeout(1_500)
        html = await page.content()
    finally:
        page.remove_listener("response", on_response)
    return parse_product_page(html, [a["body"] for a in ajax if a["body"] is not None]), ajax


async def save_debug(page, debug_dir: Path, component_id: int | str, ajax: list[dict]) -> None:
    """Keep what the browser saw on a failed check, to see what DNS changed."""
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(debug_dir / f"{component_id}.png"))
        (debug_dir / f"{component_id}.html").write_text(await page.content(), encoding="utf-8")
        (debug_dir / f"{component_id}.json").write_text(
            json.dumps({"page_url": page.url, "ajax": ajax}, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        log.exception("Could not save debug snapshot for component %s", component_id)
