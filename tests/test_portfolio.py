from datetime import date

from app import portfolio

GPU = {"id": 1, "name": "GPU", "purchase_price": 50000, "purchase_date": "2026-01-10", "quantity": 1}
RAM = {"id": 2, "name": "RAM", "purchase_price": 5000, "purchase_date": "2026-01-12", "quantity": 2}


def price(pid, component_id, checked_at, value, source="auto"):
    return {"id": pid, "component_id": component_id, "checked_at": checked_at, "price": value,
            "available": None if value is None else 1, "source": source, "error": None}


def test_component_series_uses_last_price_of_day_and_skips_failures():
    prices = [
        price(1, 1, "2026-01-11T10:00:00", 51000),
        price(2, 1, "2026-01-11T22:00:00", 52000),
        price(3, 1, "2026-01-12T10:00:00", None),
        price(4, 1, "2026-01-13T10:00:00", 60000),
    ]
    assert portfolio.component_series(GPU, prices) == [
        ("2026-01-10", 50000), ("2026-01-11", 52000), ("2026-01-13", 60000),
    ]


def test_component_summary():
    s = portfolio.component_summary(GPU, [price(1, 1, "2026-01-13T10:00:00", 60000)])
    assert s["current_price"] == 60000
    assert s["change"] == 10000
    assert s["change_pct"] == 20
    assert s["last_check"]["ok"] is True


def test_component_without_prices_is_worth_purchase_price():
    s = portfolio.component_summary(RAM, [])
    assert s["value"] == 10000 and s["change"] == 0 and s["priced_at"] is None


def test_portfolio_series_carries_prices_forward():
    prices = [price(1, 1, "2026-01-11T10:00:00", 55000), price(2, 2, "2026-01-13T10:00:00", 6000)]
    series = portfolio.portfolio_series([GPU, RAM], {1: [prices[0]], 2: [prices[1]]}, date(2026, 1, 14))
    assert series == [
        {"date": "2026-01-10", "value": 50000, "cost": 50000},
        {"date": "2026-01-11", "value": 55000, "cost": 50000},
        {"date": "2026-01-12", "value": 65000, "cost": 60000},
        {"date": "2026-01-13", "value": 67000, "cost": 60000},
        {"date": "2026-01-14", "value": 67000, "cost": 60000},
    ]


def test_build_summary():
    prices = [price(1, 1, "2026-01-13T10:00:00", 55000), price(2, 1, "2026-01-14T10:00:00", 60000)]
    result = portfolio.build([GPU, RAM], prices, date(2026, 1, 14))
    assert result["summary"]["cost"] == 60000
    assert result["summary"]["value"] == 70000
    assert result["summary"]["day_change"] == 5000
    assert round(result["summary"]["change_pct"], 2) == 16.67


def test_build_empty():
    result = portfolio.build([], [], date(2026, 1, 14))
    assert result["series"] == [] and result["summary"]["change_pct"] is None
