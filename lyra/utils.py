"""Pure helper functions."""

import re

from dotenv import load_dotenv  # noqa: F401 — re-exported

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
