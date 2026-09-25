from app.dns import parse_price, parse_product_page, product_code


def test_product_code():
    assert product_code("https://www.dns-shop.ru/product/4a2d61c8e1cded20/videokarta-palit/") == "4a2d61c8e1cded20"
    assert product_code("https://www.dns-shop.ru/product/4A2D61C8E1CDED20/?utm=1") == "4a2d61c8e1cded20"
    assert product_code("https://dns-shop.ru/product/abc123") == "abc123"
    assert product_code("https://www.dns-shop.ru/catalog/17a89aab16404e77/videokarty/") is None
    assert product_code("https://example.com/product/abc/") is None
    assert product_code(None) is None


def test_parse_price():
    assert parse_price("49 999 ₽") == 49999
    assert parse_price("49 999 ₽") == 49999
    assert parse_price("от 1 299,50 ₽") == 1299.5
    assert parse_price("₽") is None
    assert parse_price("") is None


PRODUCT_HTML = """
<html><head><title>Видеокарта</title></head><body>
<div class="product-card-top">
  <h1 class="product-card-top__title">Видеокарта Palit GeForce RTX 4070 Dual [NED4070019K9-1047D]</h1>
  <div class="product-buy">
    <div class="product-buy__price product-buy__price_active">52 999 ₽<span class="product-buy__prev">57 999</span></div>
  </div>
</div>
<div class="similar">Товара нет в наличии</div>
</body></html>
"""


def test_parse_product_page_with_discount():
    page = parse_product_page(PRODUCT_HTML)
    assert page.price == 52999
    assert page.name == "Видеокарта Palit GeForce RTX 4070 Dual [NED4070019K9-1047D]"
    assert page.available is True
    assert page.blocked is False


def test_parse_product_page_out_of_stock():
    html = """<h1 class="product-card-top__title">Процессор AMD Ryzen 7 7800X3D OEM</h1>
    <div class="product-buy"><div class="order-avail-wrap">Товара нет в наличии</div></div>"""
    page = parse_product_page(html)
    assert page.price is None
    assert page.available is False
    assert page.name == "Процессор AMD Ryzen 7 7800X3D OEM"


def test_parse_product_page_json_ld_fallback():
    html = """<h1>SSD</h1><script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Product", "name": "SSD",
     "offers": {"@type": "Offer", "price": "8499", "priceCurrency": "RUB"}}</script>"""
    assert parse_product_page(html).price == 8499


def test_parse_qrator_challenge():
    html = '<html><head><script src="/__qrator/qauth_utm_v2d_v9118.js"></script></head><body></body></html>'
    page = parse_product_page(html)
    assert page.blocked is True
    assert page.price is None


def test_price_from_ajax_fallback():
    ajax = [{"result": True, "data": {"states": [
        {"id": "as-1", "data": {"name": "RTX", "price": {"current": 64999, "previous": 69999}}}]}}]
    html = '<h1 class="product-card-top__title">RTX</h1><div class="product-buy"><div class="product-buy__price"></div></div>'
    page = parse_product_page(html, ajax)
    assert page.price == 64999
    assert page.available is True


def test_markup_price_wins_over_ajax():
    ajax = [{"data": {"price": {"current": 1}}}]
    assert parse_product_page(PRODUCT_HTML, ajax).price == 52999


def test_parse_qrator_403():
    html = """<html><head><title>HTTP 403</title></head><body>
    <div class="title">403 Error</div><div class="sub-title">Forbidden</div>
    <div class="descr">Доступ к сайту www.dns-shop.ru запрещен.</div></body></html>"""
    page = parse_product_page(html)
    assert page.blocked is True and page.forbidden is True
    assert page.price is None and page.name is None
