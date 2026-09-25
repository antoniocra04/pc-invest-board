"""Turns purchases + observed prices into portfolio numbers and daily series."""

from bisect import bisect_right
from datetime import date, timedelta


def _pct(value: float, cost: float) -> float | None:
    return (value - cost) / cost * 100 if cost else None


def _daily_prices(prices: list[dict]) -> list[tuple[str, float]]:
    """Last successful price of each day, sorted by date."""
    by_day: dict[str, float] = {}
    for p in sorted(prices, key=lambda p: (p["checked_at"], p["id"])):
        if p["price"] is not None:
            by_day[p["checked_at"][:10]] = p["price"]
    return sorted(by_day.items())


def component_series(component: dict, prices: list[dict]) -> list[tuple[str, float]]:
    """Unit price by day, starting with the purchase itself."""
    series = [(component["purchase_date"], component["purchase_price"])]
    for day, price in _daily_prices(prices):
        if day < component["purchase_date"]:
            continue
        if day == component["purchase_date"]:
            series[0] = (day, price)  # a check on the purchase day wins over the purchase price
        else:
            series.append((day, price))
    return series


def component_summary(component: dict, prices: list[dict]) -> dict:
    series = component_series(component, prices)
    qty = component["quantity"]
    current = series[-1][1]
    cost = component["purchase_price"] * qty
    value = current * qty
    last_check = prices[-1] if prices else None
    previous = series[-2][1] if len(series) > 1 else None
    return {
        **component,
        "current_price": current,
        "priced_at": series[-1][0] if len(series) > 1 else None,
        "cost": cost,
        "value": value,
        "change": value - cost,
        "change_pct": _pct(value, cost),
        "prev_change_pct": _pct(current, previous) if previous else None,
        "last_check": {
            "checked_at": last_check["checked_at"],
            "ok": last_check["price"] is not None,
            "available": None if last_check["available"] is None else bool(last_check["available"]),
            "error": last_check["error"],
            "source": last_check["source"],
        } if last_check else None,
        "sparkline": [price for _, price in series[-60:]],
    }


def portfolio_series(components: list[dict], prices_by_component: dict[int, list[dict]],
                     today: date) -> list[dict]:
    """Portfolio value and money spent for every day since the first purchase."""
    if not components:
        return []
    lines = []
    for c in components:
        series = component_series(c, prices_by_component.get(c["id"], []))
        lines.append((c, [d for d, _ in series], [p for _, p in series]))

    start = min(date.fromisoformat(c["purchase_date"]) for c in components)
    end = max(today, *(date.fromisoformat(days[-1]) for _, days, _ in lines))
    result = []
    day = start
    while day <= end:
        key = day.isoformat()
        value = cost = 0.0
        for c, days, values in lines:
            i = bisect_right(days, key)
            if i == 0:  # not bought yet
                continue
            value += values[i - 1] * c["quantity"]
            cost += c["purchase_price"] * c["quantity"]
        result.append({"date": key, "value": value, "cost": cost})
        day += timedelta(days=1)
    return result


def build(components: list[dict], prices: list[dict], today: date) -> dict:
    prices_by_component: dict[int, list[dict]] = {}
    for p in prices:
        prices_by_component.setdefault(p["component_id"], []).append(p)

    items = [component_summary(c, prices_by_component.get(c["id"], [])) for c in components]
    series = portfolio_series(components, prices_by_component, today)
    cost = sum(i["cost"] for i in items)
    value = sum(i["value"] for i in items)
    day_change = None
    if len(series) >= 2:
        prev = series[-2]
        # Only compare like with like: skip the day change on the day of a new purchase.
        if prev["cost"] == series[-1]["cost"]:
            day_change = series[-1]["value"] - prev["value"]
    return {
        "summary": {
            "cost": cost,
            "value": value,
            "change": value - cost,
            "change_pct": _pct(value, cost),
            "day_change": day_change,
            "day_change_pct": _pct(series[-1]["value"], series[-2]["value"]) if day_change is not None and series[-2]["value"] else None,
        },
        "series": series,
        "components": items,
    }
