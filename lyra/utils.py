"""Pure helper functions with no side effects (except load_dotenv)."""

import os
import re
from pathlib import Path

SV_MONTHS: dict[str, int] = {
    "januari": 1,
    "februari": 2,
    "mars": 3,
    "april": 4,
    "maj": 5,
    "juni": 6,
    "juli": 7,
    "augusti": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "december": 12,
}


def load_dotenv(path: str | Path = ".env") -> None:
    """Parse KEY=VALUE lines from *path* into ``os.environ``.

    Skips empty lines, comments (``#``), and lines without ``=``.
    Strips surrounding single or double quotes from values.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return
    with open(env_path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ[key] = value


def parse_swedish_date(text: str) -> str:
    """Convert a Swedish date string like ``'1 Juni 2026'`` to ISO 8601.

    Returns the original string unchanged if parsing fails.
    """
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip())
    if not m:
        return text
    day, month_name, year = m.groups()
    month = SV_MONTHS.get(month_name.lower())
    if month is None:
        return text
    return f"{year}-{month:02d}-{int(day):02d}"
