"""SQLite storage: components (what was bought) and prices (every observed price)."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS components (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT    NOT NULL,
    name_auto      INTEGER NOT NULL DEFAULT 0,  -- 1: name is a placeholder, take it from the DNS page
    category       TEXT    NOT NULL DEFAULT '',
    url            TEXT,
    product_code   TEXT,
    purchase_price REAL    NOT NULL,            -- per unit
    purchase_date  TEXT    NOT NULL,            -- YYYY-MM-DD
    quantity       INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    checked_at   TEXT    NOT NULL,              -- local time, YYYY-MM-DDTHH:MM:SS
    price        REAL,                          -- NULL when the check failed or item is out of stock
    available    INTEGER,                       -- 1 / 0 / NULL (unknown)
    source       TEXT    NOT NULL,              -- auto | manual | bookmarklet
    error        TEXT
);

CREATE INDEX IF NOT EXISTS prices_by_component ON prices (component_id, checked_at);
"""

COMPONENT_FIELDS = ("name", "name_auto", "category", "url", "product_code",
                    "purchase_price", "purchase_date", "quantity")


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- components -------------------------------------------------------

    def list_components(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM components ORDER BY purchase_date, id").fetchall()
        return [dict(r) for r in rows]

    def get_component(self, component_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM components WHERE id = ?", (component_id,)).fetchone()
        return dict(row) if row else None

    def find_by_product_code(self, code: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM components WHERE product_code = ? ORDER BY id LIMIT 1",
                               (code,)).fetchone()
        return dict(row) if row else None

    def add_component(self, data: dict, created_at: str) -> int:
        cols = [c for c in COMPONENT_FIELDS if c in data]
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO components ({', '.join(cols)}, created_at) "
                f"VALUES ({', '.join('?' for _ in cols)}, ?)",
                [data[c] for c in cols] + [created_at],
            )
            return cur.lastrowid

    def update_component(self, component_id: int, data: dict) -> None:
        cols = [c for c in COMPONENT_FIELDS if c in data]
        if not cols:
            return
        with self.connect() as conn:
            conn.execute(
                f"UPDATE components SET {', '.join(f'{c} = ?' for c in cols)} WHERE id = ?",
                [data[c] for c in cols] + [component_id],
            )

    def delete_component(self, component_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM components WHERE id = ?", (component_id,))
            return cur.rowcount > 0

    # --- prices -----------------------------------------------------------

    def add_price(self, component_id: int, checked_at: str, price: float | None,
                  available: bool | None, source: str, error: str | None = None) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO prices (component_id, checked_at, price, available, source, error) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (component_id, checked_at, price,
                 None if available is None else int(available), source, error),
            )
            return cur.lastrowid

    def list_prices(self, component_id: int | None = None) -> list[dict]:
        with self.connect() as conn:
            if component_id is None:
                rows = conn.execute("SELECT * FROM prices ORDER BY checked_at, id").fetchall()
            else:
                rows = conn.execute("SELECT * FROM prices WHERE component_id = ? ORDER BY checked_at, id",
                                    (component_id,)).fetchall()
        return [dict(r) for r in rows]

    def delete_price(self, price_id: int) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM prices WHERE id = ?", (price_id,))
            return cur.rowcount > 0

    def last_auto_check(self) -> str | None:
        """Time of the latest automatic check, successful or not."""
        with self.connect() as conn:
            row = conn.execute("SELECT MAX(checked_at) FROM prices WHERE source = 'auto'").fetchone()
        return row[0] if row else None
