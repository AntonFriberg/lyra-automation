"""Create Seam access codes for upcoming bookings and email them to guests."""

import csv
import smtplib
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Playwright
from seam import Seam

from .config import (
    DRY_RUN,
    GMAIL_APP_PASSWORD,
    GMAIL_USER,
    LOCK_NAME,
    SENDER_NAME,
    UPCOMING_OUTPUT_CSV,
)

TZ = ZoneInfo("Europe/Stockholm")

EMAIL_TEMPLATE = """\
Hej {first_name}!

Här kommer er kod till gästlägenheten på BRF Lyra för er bokning \
{start_date} kl 15:00 till {end_date} kl 12:00 ({nights_text}).

Kod: {entry_code}

För att öppna dörren så skriver ni er kod följt av upplåsningsknappen 🔓
För att låsa dörren så stänger ni dörren och klickar på låsknappen 🔒

För att låsa upp dörren från insidan se till att dörren är åtdragen och \
vrid låset medurs 90 grader och släpp. Grön signal och ljud indikerar \
att dörren är upplåst. 🔓

För att låsa dörren från insidan se till att dörren är åtdragen och \
vrid låset moturs 90 grader och släpp. Röd signal och ljud indikerar \
att dörren är låst. 🔒

Er kod aktiveras automatiskt vid incheckningstiden (15:00) och slutar \
fungera efter utcheckning (12:00).

Jag skickar också lite extra information med instruktioner om vad som \
gäller i övrigt. Säg till om ni har några frågor!

Det viktigaste är:
Incheckning kl 15:00
Utcheckning kl 12:00
Ansvarig för rummet, under vistelsen, är bostadsrättshavaren som bokat \
rummet. Är något trasigt eller inte fungerar, ska bostadsrättsinnehavaren \
göra en felanmälan till bostadsrättsföreningen.
Bostadsrättsinnehavaren som bokat rummet ansvarar för att det städas och \
kontrollerar detta innan rummet lämnas.
Kostnad 350 kr/natt.

MvH
{sender_name}
Ledamot BRF Lyra
"""


# ---------------------------------------------------------------------------
# Stay grouping
# ---------------------------------------------------------------------------

def _group_stays(bookings: list[dict]) -> list[dict]:
    """Group consecutive dates that share the same email into stays.

    Sorts by *(epost, datum)*, then walks forward: when the current row has
    the same email as the previous stay and the date is exactly one day after
    that stay's last date, the stay is extended.  Otherwise a new stay begins.
    """
    bookings.sort(key=lambda b: (b["epost"], b["datum"]))

    stays: list[dict] = []
    for b in bookings:
        epost = b["epost"]
        datum = b["datum"]
        name = b["name"]
        first_name = name.split()[0] if name else ""

        if stays and stays[-1]["epost"] == epost:
            last_end = datetime.strptime(
                stays[-1]["end_date"], "%Y-%m-%d",
            ).date()
            current = datetime.strptime(datum, "%Y-%m-%d").date()
            if current == last_end + timedelta(days=1):
                stays[-1]["end_date"] = datum
                stays[-1]["nights"] += 1
                continue

        stays.append({
            "first_name": first_name,
            "epost": epost,
            "start_date": datum,
            "end_date": datum,
            "nights": 1,
            "name": name,
            "lagenhetsnummer": b.get("lagenhetsnummer", ""),
        })

    return stays


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _compute_times(stay: dict) -> tuple[datetime, datetime]:
    """Return *(starts_at, ends_at)* as timezone-aware datetimes.

    Check-in is 15:00 on the first night, check-out is 12:00 on the day
    **after** the last night.  Both use ``Europe/Stockholm`` (CET/CEST).
    """
    start_date = datetime.strptime(stay["start_date"], "%Y-%m-%d").date()
    end_date = datetime.strptime(stay["end_date"], "%Y-%m-%d").date()

    start_dt = datetime.combine(
        start_date, datetime.strptime("15:00", "%H:%M").time(),
    ).replace(tzinfo=TZ)

    end_dt = datetime.combine(
        end_date + timedelta(days=1),
        datetime.strptime("12:00", "%H:%M").time(),
    ).replace(tzinfo=TZ)

    return start_dt, end_dt


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def _send_email(to_email: str, subject: str, body: str) -> None:
    """Send a plain-text email via Gmail SMTP (STARTTLS on port 587)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr((SENDER_NAME, GMAIL_USER))
    msg["To"] = to_email
    msg["Subject"] = subject

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.send_message(msg)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_keys(playwright: Playwright) -> None:  # noqa: C901
    """Create Seam access codes for upcoming bookings and email them.

    Reads *upcoming_bookings.csv*, groups consecutive nights that share
    the same email into stays, creates a time-bound access code for each
    stay via the Seam API, and emails the code to the guest.
    """
    # --- Read CSV ---------------------------------------------------------
    csv_path = Path(UPCOMING_OUTPUT_CSV)
    if not csv_path.is_file():
        print(f"ERROR: {csv_path} not found — run 'lyra upcoming' first")
        return

    with open(csv_path, newline="", encoding="utf-8") as fh:
        bookings = list(csv.DictReader(fh))

    if not bookings:
        print("No upcoming bookings — nothing to do.")
        return

    stays = _group_stays(bookings)
    print(
        f"Grouped {len(bookings)} booking(s) into {len(stays)} stay(s):\n",
    )
    for s in stays:
        print(
            f"  {s['first_name']} ({s['epost']}): "
            f"{s['start_date']} → {s['end_date']}  "
            f"({s['nights']} night(s))",
        )

    if DRY_RUN:
        print("\n=== DRY RUN: no codes created, no emails sent ===")
        return

    # --- Seam: find the lock ----------------------------------------------
    seam = Seam()  # reads SEAM_API_KEY from env

    devices = seam.devices.list(search=LOCK_NAME)
    if not devices:
        print(f"ERROR: no device found matching '{LOCK_NAME}'")
        return

    device = devices[0]
    print(f"\nLock: {device.display_name} ({device.device_id})")

    # Fetch existing codes so we can skip stays already covered.
    # Compare date ranges, not names — the lock only serves one
    # apartment, so any overlap means the date is already covered.
    try:
        existing_codes = seam.access_codes.list(device_id=device.device_id)
        existing_ranges: list[tuple[datetime, datetime]] = []
        for ac in existing_codes:
            if ac.starts_at and ac.ends_at:
                try:
                    s = datetime.fromisoformat(ac.starts_at)
                    e = datetime.fromisoformat(ac.ends_at)
                    existing_ranges.append((s, e))
                except ValueError:
                    pass
    except Exception:
        print("WARNING: could not list existing codes — will not skip any")
        existing_ranges = []

    # --- Process each stay ------------------------------------------------
    for idx, stay in enumerate(stays):
        print(
            f"\n--- [{idx + 1}/{len(stays)}] "
            f"{stay['first_name']}  "
            f"({stay['start_date']} → {stay['end_date']}) ---",
        )

        start_dt, end_dt = _compute_times(stay)
        code_name = (
            f"Gästlägenhet: {stay['name']} ({stay['start_date']})"
        )

        # Skip if this stay's window overlaps any existing code
        overlapping = any(
            s < end_dt and start_dt < e for s, e in existing_ranges
        )
        if overlapping:
            print(f"  SKIP: date range already covered by existing code")
            continue

        # --- Create access code via Seam ---------------------------------
        print(f"  Creating: {code_name}")
        print(f"  Window:   {start_dt.isoformat()} → {end_dt.isoformat()}")

        try:
            result = seam.access_codes.create(
                device_id=device.device_id,
                name=code_name,
                starts_at=start_dt.isoformat(),
                ends_at=end_dt.isoformat(),
            )
        except Exception as exc:
            print(f"  ERROR creating code: {exc}")
            continue

        entry_code = result.code
        if not entry_code:
            print("  ERROR: Seam returned no code — skipping email")
            continue

        print(f"  Code:     {entry_code}")
        existing_ranges.append((start_dt, end_dt))

        # --- Send email ---------------------------------------------------
        # The email shows the check-*out* date, which is the day after the
        # last night (already computed in end_dt by _compute_times).
        checkout_date = end_dt.strftime("%Y-%m-%d")
        subject = (
            f"Kod till gästlägenheten "
            f"{stay['start_date']} - {checkout_date}"
        )
        nights = stay["nights"]
        nights_text = f"{nights} natt" if nights == 1 else f"{nights} nätter"
        body = EMAIL_TEMPLATE.format(
            first_name=stay["first_name"],
            start_date=stay["start_date"],
            end_date=checkout_date,
            nights_text=nights_text,
            entry_code=entry_code,
            sender_name=SENDER_NAME,
        )

        try:
            print(f"  Sending email to {stay['epost']} …")
            _send_email(stay["epost"], subject, body)
            print(f"  Email sent.")
        except Exception as exc:
            print(f"  ERROR sending email: {exc}")

    print(f"\nDone — processed {len(stays)} stay(s)")
