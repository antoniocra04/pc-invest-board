"""Price update runs: on schedule, on the "update now" button, and right after adding a component."""

import asyncio
import logging
from datetime import datetime, timedelta

from . import scraper
from .config import Settings
from .db import Database

log = logging.getLogger(__name__)


class Updater:
    def __init__(self, settings: Settings, db: Database, fetch=scraper.fetch_prices):
        self.settings = settings
        self.db = db
        self._fetch = fetch
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self.status = {
            "running": False,
            "done": 0,
            "total": 0,
            "current": None,
            "last_run_started": None,
            "last_run_finished": None,
            "last_run_ok": 0,
            "last_run_failed": 0,
            "next_run": None,
        }

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def start(self, component_ids: list[int] | None = None) -> bool:
        """Start a run in the background. False if one is already running."""
        if self.running:
            return False
        task = asyncio.get_running_loop().create_task(self.run(component_ids))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def run(self, component_ids: list[int] | None = None) -> None:
        async with self._lock:
            components = [c for c in self.db.list_components() if c["url"] and c["product_code"]]
            if component_ids is not None:
                components = [c for c in components if c["id"] in component_ids]
            if not components:
                return
            by_id = {c["id"]: c for c in components}
            st = self.status
            st.update(running=True, done=0, total=len(components), current=None,
                      last_run_started=self.settings.now().isoformat(), last_run_ok=0, last_run_failed=0)
            st["current"] = components[0]["name"]

            async def on_result(result: scraper.FetchResult) -> None:
                page = result.page
                self.db.add_price(
                    result.component_id, self.settings.now().isoformat(),
                    page.price if page else None,
                    page.available if page else None,
                    "auto", result.error,
                )
                component = by_id[result.component_id]
                if page and page.name and component["name_auto"]:
                    self.db.update_component(component["id"], {"name": page.name, "name_auto": 0})
                if page and page.price is not None:
                    st["last_run_ok"] += 1
                else:
                    st["last_run_failed"] += 1
                st["done"] += 1
                if st["done"] < len(components):
                    st["current"] = components[st["done"]]["name"]

            try:
                await self._fetch(self.settings, [(c["id"], c["url"]) for c in components], on_result)
            except Exception:
                log.exception("Price update failed")
                st["last_run_failed"] += st["total"] - st["done"]
            finally:
                st.update(running=False, current=None, last_run_finished=self.settings.now().isoformat())

    # --- schedule ---------------------------------------------------------

    def next_run_after(self, moment: datetime) -> datetime:
        for day in range(2):
            date = (moment + timedelta(days=day)).date()
            for t in self.settings.check_times:
                candidate = datetime.combine(date, t)
                if candidate > moment:
                    return candidate
        raise AssertionError("check_times is never empty")

    def previous_run_before(self, moment: datetime) -> datetime:
        for day in range(2):
            date = (moment - timedelta(days=day)).date()
            for t in reversed(self.settings.check_times):
                candidate = datetime.combine(date, t)
                if candidate <= moment:
                    return candidate
        raise AssertionError("check_times is never empty")

    def missed_run(self) -> bool:
        """True when the last scheduled check did not happen (the Pi was off, the container restarted)."""
        last = self.db.last_auto_check()
        return last is None or datetime.fromisoformat(last) < self.previous_run_before(self.settings.now())

    async def schedule_forever(self) -> None:
        self.status["next_run"] = self.next_run_after(self.settings.now()).isoformat()
        await asyncio.sleep(90)
        if self.missed_run():
            await self.run()
        while True:
            now = self.settings.now()
            next_run = self.next_run_after(now)
            self.status["next_run"] = next_run.isoformat()
            await asyncio.sleep((next_run - now).total_seconds())
            await self.run()
