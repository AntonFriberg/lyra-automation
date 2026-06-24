"""Daily production pipeline — extract, keys, and billing in one run.

Run once a day (9 AM CET) via Cloud Scheduler → Cloud Run Job.
Extracts tomorrow's booking window, creates Seam access codes, sends
emails, and enters billing — all with a single shared browser session.
"""

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Playwright, Page
from seam import Seam

from . import launch_browser
from .config import (
    BILLING_ACCOUNT,
    BILLING_AMOUNT,
    BILLING_AVITEXT,
    DAILY_LOOKAHEAD,
    DRY_RUN,
    LOCK_NAME,
    SENDER_NAME,
    UPCOMING_OUTPUT_CSV,
)
from .extract import (
    _login as _login_smartbrf,
    _wait_for_calendar,
    _collect_names,
)
from .bill import (
    _login as _login_jmhome,
    _find_best_match,
    _latest_billed_date,
)
from .keys import (
    _group_stays,
    _compute_times,
    _create_access_code,
    _send_email,
    EMAIL_TEMPLATE,
)
from .utils import parse_swedish_date


# ---------------------------------------------------------------------------
# Modal extraction helper (mirrors extract.py's inline block)
# ---------------------------------------------------------------------------

def _extract_booking(page: Page, index: int) -> dict[str, str]:
    """Click a calendar booking, read the modal fields, close it.

    Returns a dict with *name*, *telefon*, *epost*, *lagenhetsnummer*,
    and *datum* (ISO 8601).  The *name* comes from ``_collect_names``
    and is passed in separately — we re-read it here for consistency.
    """
    # Click via JS (FullCalendar elements are often offscreen)
    page.evaluate(
        """(idx) => {
            document.querySelectorAll('a.unavailable')[idx].click();
        }""",
        index,
    )
    page.wait_for_selector(
        ".remodal.remodal-is-opened", state="attached", timeout=5_000,
    )

    telefon = page.get_by_role("textbox", name="Telefon").input_value()
    lagenhetsnummer = page.get_by_role(
        "textbox", name="Lägenhetsnummer",
    ).input_value()
    epost = page.locator("#booking_user span.email").text_content() or ""

    date_el = page.locator("span.date")
    date_text = (
        (date_el.first.text_content() or "") if date_el.count() else ""
    )
    iso_date = parse_swedish_date(date_text)

    # Close modal
    page.locator("[data-remodal-action='close']").click()
    page.wait_for_selector(
        ".remodal.remodal-is-closed", state="attached", timeout=5_000,
    )

    return {
        "telefon": telefon,
        "epost": epost,
        "lagenhetsnummer": lagenhetsnummer,
        "datum": iso_date,
    }


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_daily(playwright: Playwright) -> None:  # noqa: C901
    """Run the full daily pipeline: extract → keys → bill.

    Window: tomorrow through tomorrow + ``DAILY_LOOKAHEAD - 1`` days.
    Only stays that **start** tomorrow get codes and billing.
    """
    today = date.today()
    tomorrow = today + timedelta(days=1)
    window_end = tomorrow + timedelta(days=DAILY_LOOKAHEAD - 1)
    print(f"Daily run {today.isoformat()}  "
          f"window: {tomorrow.isoformat()} → {window_end.isoformat()}")

    # --- Shared browser ---------------------------------------------------
    context, page = launch_browser(playwright)

    # ==================================================================
    # Phase 1 — Extract tomorrow's window from Smart Brf
    # ==================================================================
    print("\n--- Phase 1: Extract ---")
    _login_smartbrf(page)

    all_bookings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for month_idx in range(2):  # current month + optionally next
        if month_idx > 0:
            page.get_by_role("button", name="›").click()
            page.wait_for_load_state("networkidle")

        _wait_for_calendar(page)
        names = _collect_names(page)

        print(f"  Month {month_idx + 1}: {len(names)} booking(s)")

        for i, name in enumerate(names):
            fields = _extract_booking(page, i)
            iso_date = fields["datum"]

            # Window filter
            if iso_date < str(tomorrow) or iso_date > str(window_end):
                continue

            key = (name, iso_date)
            if key not in seen:
                seen.add(key)
                all_bookings.append({
                    "name": name,
                    "telefon": fields["telefon"],
                    "epost": fields["epost"],
                    "lagenhetsnummer": fields["lagenhetsnummer"],
                    "datum": iso_date,
                })

        # Stop if the window doesn't spill into next month
        if (window_end.month == today.month
                and window_end.year == today.year):
            break

    print(f"  Extracted {len(all_bookings)} booking(s) in window")

    if not all_bookings:
        print("  Nothing to do — exiting.")
        context.close()
        return

    # Write daily CSV (handy for debugging; reused by billing)
    csv_path = Path(UPCOMING_OUTPUT_CSV)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["name", "telefon", "epost",
                        "lagenhetsnummer", "datum"],
        )
        writer.writeheader()
        writer.writerows(all_bookings)

    # ==================================================================
    # Phase 2 — Group stays & filter to tomorrow-starting
    # ==================================================================
    print("\n--- Phase 2: Group stays ---")
    stays = _group_stays(all_bookings)
    tomorrow_stays = [s for s in stays if s["start_date"] == str(tomorrow)]

    if not tomorrow_stays:
        print("  No stay starts tomorrow — exiting.")
        context.close()
        return

    for s in tomorrow_stays:
        start_dt, end_dt = _compute_times(s)
        checkout = end_dt.strftime("%Y-%m-%d")
        print(
            f"  {s['first_name']} ({s['epost']}): "
            f"{s['start_date']} → {checkout}  "
            f"({s['nights']} night(s))  "
            f"lgh={s['lagenhetsnummer']}",
        )

    if DRY_RUN:
        print("\n=== DRY RUN: no codes, emails, or billing ===")
        context.close()
        return

    # ==================================================================
    # Phase 3 — Seam access codes + emails
    # ==================================================================
    print("\n--- Phase 3: Access codes + email ---")

    seam = Seam()
    devices = seam.devices.list(search=LOCK_NAME)
    if not devices:
        print(f"  ERROR: no device matching '{LOCK_NAME}'")
        context.close()
        return
    device = devices[0]
    print(f"  Lock: {device.display_name} ({device.device_id})")

    try:
        existing_codes = seam.access_codes.list(device_id=device.device_id)
        # Keep only codes with populated date fields
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
        print("  WARNING: could not list existing codes")
        existing_ranges = []

    for idx, stay in enumerate(tomorrow_stays):
        print(
            f"\n  [{idx + 1}/{len(tomorrow_stays)}] "
            f"{stay['first_name']} ({stay['start_date']})",
        )

        start_dt, end_dt = _compute_times(stay)
        code_name = (
            f"Gästlägenhet: {stay['name']} ({stay['start_date']})"
        )

        # Skip if this stay's time window overlaps any existing code.
        # The lock only serves one apartment, so any overlap means the
        # date is already covered — no need to match by guest name.
        overlapping = any(
            s < end_dt and start_dt < e for s, e in existing_ranges
        )
        if overlapping:
            print(f"    SKIP: date range already covered by existing code")
            continue

        # Create code
        print(f"    Creating: {code_name}")
        print(f"    Window:   {start_dt.isoformat()} → {end_dt.isoformat()}")

        try:
            entry_code = _create_access_code(
                seam,
                device.device_id,
                code_name,
                start_dt.isoformat(),
                end_dt.isoformat(),
            )
        except Exception as exc:
            print(f"    ERROR creating code after retries: {exc}")
            continue

        print(f"    Code:     {entry_code}")
        existing_ranges.append((start_dt, end_dt))

        # Send email
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
            print(f"    Sending email to {stay['epost']} …")
            _send_email(stay["epost"], subject, body)
            print(f"    Email sent.")
        except Exception as exc:
            print(f"    ERROR sending email: {exc}")

    # ==================================================================
    # Phase 4 — Billing in JM Home (one entry per night)
    # ==================================================================
    print("\n--- Phase 4: Billing ---")

    # Only bill nights belonging to the same stays we created codes for.
    # Build a set of (name, lgh, datum) tuples from tomorrow_stays.
    stay_nights: set[tuple[str, str, str]] = set()
    for s in tomorrow_stays:
        start = s["start_date"]
        for offset in range(s["nights"]):
            night = (
                datetime.strptime(start, "%Y-%m-%d") + timedelta(days=offset)
            ).strftime("%Y-%m-%d")
            stay_nights.add((s["name"], s["lagenhetsnummer"], night))

    # Filter window-bookings to only those nights
    bookings_to_bill = [
        b for b in all_bookings
        if (b["name"], b["lagenhetsnummer"], b["datum"]) in stay_nights
    ]
    bookings_to_bill.sort(key=lambda b: b["datum"])

    _login_jmhome(page)

    cutoff_date = _latest_billed_date(page)
    print(f"  Latest billed date: {cutoff_date}")
    print(f"  Nights to bill: {len(bookings_to_bill)} "
          f"(from {len(tomorrow_stays)} stay(s) starting tomorrow)")

    billed = 0
    for idx, booking in enumerate(bookings_to_bill):
        name = booking["name"]
        lgh = booking["lagenhetsnummer"]
        datum = booking["datum"]

        print(
            f"\n  [{idx + 1}/{len(bookings_to_bill)}] "
            f"{name} / {lgh} / {datum}",
        )

        if datum <= cutoff_date:
            print(f"    SKIP: already billed (cutoff: {cutoff_date})")
            continue

        match = _find_best_match(page, name, lgh)
        if not match:
            print("    SKIP: no apartment match")
            continue
        option_value, _ = match

        page.locator('[data-test="form-select"]').select_option(
            value=option_value,
        )
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        add_btn = page.get_by_role("button", name="Skapa nytt tillägg")
        add_btn.wait_for(state="visible")
        add_btn.click()
        page.wait_for_timeout(300)

        page.get_by_role("combobox").select_option(BILLING_ACCOUNT)
        page.wait_for_timeout(200)

        avitext = f"{BILLING_AVITEXT} {datum}"
        page.get_by_role("textbox", name="Ange avitext").fill(avitext)
        page.get_by_role("textbox", name="Ange avitext").press("Tab")
        page.get_by_role("textbox", name="Ange belopp").fill(BILLING_AMOUNT)

        page.get_by_role("button", name="Spara ").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        cutoff_date = datum
        billed += 1
        print(f"    Billed: '{avitext}' {BILLING_AMOUNT} SEK")

    # ==================================================================
    # Done
    # ==================================================================
    print(
        f"\nDone — {len(tomorrow_stays)} stay(s) processed, "
        f"{billed} billing entr(ies) created",
    )
    context.close()
