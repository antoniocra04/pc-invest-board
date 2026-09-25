"""Check which browser engine DNS lets through, from the command line.

    docker compose exec pc-invest-board python -m app.probe <dns product url> [camoufox|chromium|all]

Prints the verdict for each engine and saves what the browser saw to data/debug/probe-<engine>.*
"""

import asyncio
import sys

from .config import Settings
from .scraper import ENGINES, fetch_page, open_browser, save_debug


async def probe(settings: Settings, url: str, engine: str) -> str:
    try:
        async with open_browser(settings, engine) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            result, ajax = await fetch_page(page, url)
            title = await page.title()
            if result.price is None:
                await save_debug(page, settings.debug_dir, f"probe-{engine}", ajax)
    except Exception as exc:
        return f"не запустился: {type(exc).__name__}: {exc}"[:500]
    if result.price is not None:
        price = f"{result.price:,.0f}".replace(",", " ")
        return f"OK, цена {price} ₽ — {result.name}"
    if result.forbidden:
        verdict = "403, DNS не пустил"
    elif result.blocked:
        verdict = "застрял на проверке антибота"
    elif result.available is False:
        verdict = "страница открылась, товара нет в наличии"
    else:
        verdict = "страница открылась, но цена не найдена"
    return f"{verdict} (заголовок: {title!r}, ответов с ценой: {len(ajax)}); снимок в debug/probe-{engine}.*"


async def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    url = argv[0]
    which = argv[1] if len(argv) > 1 else "all"
    engines = ENGINES if which == "all" else (which,)
    settings = Settings()
    for engine in engines:
        print(f"{engine}: проверяю…", flush=True)
        print(f"{engine}: {await probe(settings, url, engine)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
