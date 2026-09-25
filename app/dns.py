"""Everything that knows about dns-shop.ru markup. Pure functions, no network."""

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_PRODUCT_RE = re.compile(r"dns-shop\.ru/product/([0-9a-zA-Z]+)(?:[/?#]|$)")
_NUMBER_RE = re.compile(r"\d[\d    ]*(?:[.,]\d{1,2})?")

# Product page elements. The price block is filled in by JS after the page loads.
PRICE_SELECTOR = ".product-buy__price"
TITLE_SELECTOR = ".product-card-top__title"
UNAVAILABLE_MARKERS = (
    "нет в наличии",
    "товара нет в наличии",
    "продажи прекращены",
    "снят с продажи",
    "нет в продаже",
)


@dataclass
class ProductPage:
    price: float | None = None
    name: str | None = None
    available: bool | None = None
    blocked: bool = False  # anti-bot challenge page instead of the product


def product_code(url: str | None) -> str | None:
    """The stable product id from a DNS URL: .../product/4a2d61c8e1cded20/some-slug/ -> 4a2d61c8e1cded20."""
    if not url:
        return None
    match = _PRODUCT_RE.search(url)
    return match.group(1).lower() if match else None


def parse_price(text: str | None) -> float | None:
    """First number in the text: '49 999 ₽' -> 49999.0."""
    if not text:
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    raw = re.sub(r"[    ]", "", match.group(0)).replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _own_text(element) -> str:
    # The active price element also contains the crossed-out old price in a child span;
    # the current price is the element's own text.
    return "".join(element.find_all(string=True, recursive=False))


def _price_from_json_ld(soup: BeautifulSoup) -> float | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                offers = item.get("offers")
                if isinstance(offers, dict):
                    price = parse_price(str(offers.get("price", "")))
                    if price:
                        return price
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
    return None


def parse_product_page(html: str) -> ProductPage:
    soup = BeautifulSoup(html, "html.parser")
    page = ProductPage()

    title = soup.select_one(TITLE_SELECTOR) or soup.find("h1")
    if title and title.get_text(strip=True):
        page.name = " ".join(title.get_text(" ", strip=True).split())
    else:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            page.name = og["content"].strip()

    price_el = soup.select_one(PRICE_SELECTOR)
    if price_el:
        page.price = parse_price(_own_text(price_el)) or parse_price(price_el.get_text(" "))
    if page.price is None:
        page.price = _price_from_json_ld(soup)
    if page.price is None:
        meta = soup.find(attrs={"itemprop": "price"})
        if meta:
            page.price = parse_price(meta.get("content") or meta.get_text(" "))

    if page.price is not None:
        page.available = True
    else:
        buy_block = soup.select_one(".product-buy") or soup.select_one(".product-card-top") or soup
        text = buy_block.get_text(" ", strip=True).lower()
        if any(marker in text for marker in UNAVAILABLE_MARKERS):
            page.available = False

    page.blocked = page.price is None and page.name is None and "__qrator" in html
    return page
