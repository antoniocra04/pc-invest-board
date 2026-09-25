import time

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dns import ProductPage
from app.main import create_app
from app.scraper import FetchResult

URL = "https://www.dns-shop.ru/product/4a2d61c8e1cded20/videokarta-palit/"


@pytest.fixture
def client(tmp_path):
    fetched = []

    async def fake_fetch(settings, items, on_result):
        for component_id, url in items:
            fetched.append(url)
            await on_result(FetchResult(component_id, ProductPage(price=60000, name="RTX 4070", available=True)))

    settings = Settings(data_dir=tmp_path, scheduler_enabled=False)
    with TestClient(create_app(settings, fetch=fake_fetch)) as c:
        c.fetched = fetched
        yield c


def wait_idle(client):
    for _ in range(50):
        if not client.get("/api/status").json()["running"]:
            return
        time.sleep(0.02)


def test_add_component_fetches_price_and_name(client):
    res = client.post("/api/components", json={"url": URL, "purchase_price": 50000, "purchase_date": "2026-01-10"})
    assert res.status_code == 201
    assert res.json()["name_auto"] == 1
    wait_idle(client)

    data = client.get("/api/portfolio").json()
    item = data["components"][0]
    assert item["name"] == "RTX 4070"
    assert item["current_price"] == 60000
    assert item["change_pct"] == 20
    assert data["summary"]["value"] == 60000
    assert client.fetched == [URL]


def test_rejects_non_dns_url(client):
    res = client.post("/api/components", json={"url": "https://example.com/x", "purchase_price": 100})
    assert res.status_code == 422


def test_manual_component_and_price(client):
    cid = client.post("/api/components", json={"name": "Корпус", "purchase_price": 7000,
                                               "purchase_date": "2026-01-10"}).json()["id"]
    assert client.post(f"/api/components/{cid}/prices", json={"price": 8000, "date": "2026-02-01"}).status_code == 201
    details = client.get(f"/api/components/{cid}").json()
    assert details["current_price"] == 8000
    assert details["series"] == [{"date": "2026-01-10", "price": 7000}, {"date": "2026-02-01", "price": 8000}]

    price_id = details["history"][0]["id"]
    assert client.delete(f"/api/prices/{price_id}").status_code == 204
    assert client.get(f"/api/components/{cid}").json()["current_price"] == 7000

    assert client.post("/api/refresh", json={"component_id": cid}).status_code == 422


def test_update_and_delete(client):
    cid = client.post("/api/components", json={"name": "SSD", "purchase_price": 9000}).json()["id"]
    res = client.put(f"/api/components/{cid}", json={"purchase_price": 8500, "quantity": 2})
    assert res.json()["purchase_price"] == 8500 and res.json()["quantity"] == 2
    assert client.delete(f"/api/components/{cid}").status_code == 204
    assert client.get(f"/api/components/{cid}").status_code == 404


def test_capture_from_bookmarklet(client):
    client.post("/api/components", json={"url": URL, "purchase_price": 50000})
    wait_idle(client)
    res = client.post("/api/capture", json={"url": URL + "?utm_source=x", "price": 61000, "name": "RTX 4070"})
    assert res.json()["matched"] is True
    assert client.get("/api/portfolio").json()["components"][0]["current_price"] == 61000

    other = "https://www.dns-shop.ru/product/ffff0000/ssd/"
    assert client.post("/api/capture", json={"url": other, "price": 1}).json()["matched"] is False


def test_import_is_all_or_nothing(client):
    bad = {"components": [{"name": "A", "purchase_price": 1}, {"url": "https://example.com", "purchase_price": 1}]}
    assert client.post("/api/import", json=bad).status_code == 422
    assert client.get("/api/portfolio").json()["components"] == []

    good = {"components": [{"name": "A", "purchase_price": 1000}, {"url": URL, "purchase_price": 50000}]}
    assert client.post("/api/import", json=good).json() == {"created": 2}


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200 and "ПК-портфель" in res.text


def test_debug_snapshot(client, tmp_path):
    cid = client.post("/api/components", json={"name": "SSD", "purchase_price": 9000}).json()["id"]
    assert client.get(f"/api/components/{cid}").json()["debug"] is False
    assert client.get(f"/api/components/{cid}/debug.png").status_code == 404

    (tmp_path / "debug").mkdir()
    (tmp_path / "debug" / f"{cid}.png").write_bytes(b"png")
    (tmp_path / "debug" / f"{cid}.html").write_text("<script>alert(1)</script>")
    assert client.get(f"/api/components/{cid}").json()["debug"] is True
    html = client.get(f"/api/components/{cid}/debug.html")
    assert html.headers["content-type"].startswith("text/plain")
    assert client.get(f"/api/components/{cid}/debug.sqlite3").status_code == 404
