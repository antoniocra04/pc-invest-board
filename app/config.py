"""Settings read from environment variables (see docker-compose.yml)."""

import os
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _times(raw: str) -> list[time]:
    result = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        hours, minutes = part.split(":")
        result.append(time(int(hours), int(minutes)))
    return sorted(result) or [time(10, 0)]


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "./data")))
    tz_name: str = field(default_factory=lambda: os.environ.get("TZ", "Europe/Moscow"))
    # Daily check times, local time, comma separated: "10:00,22:00".
    check_times: list[time] = field(default_factory=lambda: _times(os.environ.get("CHECK_TIMES", "10:00")))
    # Run the scheduler at all (tests switch it off).
    scheduler_enabled: bool = field(default_factory=lambda: _bool("SCHEDULER_ENABLED", True))
    # Headed Chromium under Xvfb passes the DNS anti-bot check more often than headless.
    headless: bool = field(default_factory=lambda: _bool("HEADLESS", False))
    # Optional DNS city slug (city_path cookie), e.g. "moscow", "spb". Prices differ by city.
    dns_city: str = field(default_factory=lambda: os.environ.get("DNS_CITY", "").strip())
    # Pause between product pages, seconds — do not hammer the shop.
    delay_min: float = field(default_factory=lambda: float(os.environ.get("SCRAPE_DELAY_MIN", "8")))
    delay_max: float = field(default_factory=lambda: float(os.environ.get("SCRAPE_DELAY_MAX", "20")))
    chromium_path: str | None = field(default_factory=lambda: os.environ.get("CHROMIUM_PATH") or None)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.tz_name)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "board.sqlite3"

    @property
    def browser_profile_dir(self) -> Path:
        return self.data_dir / "browser-profile"

    @property
    def debug_dir(self) -> Path:
        return self.data_dir / "debug"

    def now(self) -> datetime:
        return datetime.now(self.tz).replace(tzinfo=None, microsecond=0)
