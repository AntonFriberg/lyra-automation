"""Daily production pipeline — extract, keys, and billing in one run.

Run once a day (9 AM CET) via Cloud Scheduler → Cloud Run Job.
Extracts tomorrow's booking window, creates Seam access codes, sends
emails, and enters billing — all with a single shared browser session.
"""

import csv
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from playwright.sync_api import Playwright
from seam import Seam

from . import launch_browser
from .bill import (
    _find_best_match,
    _latest_billed_date,
    _login_jmhome,
)
from .config import (
    BILLING_ACCOUNT,
    BILLING_AMOUNT,
    BILLING_AVITEXT,
    DAILY_LOOKAHEAD,
    DRY_RUN,
    LOCK_NAME,
    SENDER_NAME,
    UPCOMING_OUTPUT_CSV,
    validate,
)
from .extract import (
    _collect_names,
    _extract_booking,
    _login_smartbrf,
    _wait_for_calendar,
)
from .keys import (
    EMAIL_TEMPLATE,
    _compute_times,
    _create_access_code,
    _group_stays,
    _send_email,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------


def run_daily(playwright: Playwright) -> None:  # noqa: C901
    """Run the full daily pipeline: extract → keys → bill.

    Window: tomorrow through tomorrow + ``DAILY_LOOKAHEAD - 1`` days.
    Only stays that **start** tomorrow get codes and billing.
    """
    validate(
        "LYRA_EMAIL",
        "LYRA_PASSWORD",
        "JM_EMAIL",
        "JM_PASSWORD",
        "SEAM_API_KEY",
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
    )
    today = date.today()
    tomorrow = today + timedelta(days=1)
    window_end = tomorrow + timedelta(days=DAILY_LOOKAHEAD - 1)
    log.info(
        "Daily run %s  window: %s → %s",
        today.isoformat(),
        tomorrow.isoformat(),
        window_end.isoformat(),
    )

    # --- Shared browser ---------------------------------------------------
    context, page = launch_browser(playwright)

    # ==================================================================
    # Phase 1 — Extract tomorrow's window from Smart Brf
    # ==================================================================
    log.info("--- Phase 1: Extract ---")
    _login_smartbrf(page)

    all_bookings: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for month_idx in range(2):  # current month + optionally next
        if month_idx > 0:
            page.get_by_role("button", name="›").click()
            page.wait_for_load_state("networkidle")

        _wait_for_calendar(page)
        names = _collect_names(page)

        log.info("  Month %d: %d booking(s)", month_idx + 1, len(names))

        for i, name in enumerate(names):
            fields = _extract_booking(page, i)
            iso_date = fields["datum"]

            # Window filter
            if iso_date < str(tomorrow) or iso_date > str(window_end):
                continue

            key = (name, iso_date)
            if key not in seen:
                seen.add(key)
                all_bookings.append(
                    {
                        "name": name,
                        "telefon": fields["telefon"],
                        "epost": fields["epost"],
                        "lagenhetsnummer": fields["lagenhetsnummer"],
                        "datum": iso_date,
                    }
                )

        # Stop if the window doesn't spill into next month
        if window_end.month == today.month and window_end.year == today.year:
            break

    log.info("  Extracted %d booking(s) in window", len(all_bookings))

    if not all_bookings:
        log.info("  Nothing to do — exiting.")
        context.close()
        return

    # Write daily CSV (handy for debugging; reused by billing)
    csv_path = Path(UPCOMING_OUTPUT_CSV)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["name", "telefon", "epost", "lagenhetsnummer", "datum"],
        )
        writer.writeheader()
        writer.writerows(all_bookings)

    # ==================================================================
    # Phase 2 — Group stays & filter to tomorrow-starting
    # ==================================================================
    log.info("--- Phase 2: Group stays ---")
    stays = _group_stays(all_bookings)
    tomorrow_stays = [s for s in stays if s["start_date"] == str(tomorrow)]

    if not tomorrow_stays:
        log.info("  No stay starts tomorrow — exiting.")
        context.close()
        return

    for s in tomorrow_stays:
        start_dt, end_dt = _compute_times(s)
        checkout = end_dt.strftime("%Y-%m-%d")
        log.info(
            "  %s (%s): %s → %s  (%d night(s))  lgh=%s",
            s["first_name"],
            s["epost"],
            s["start_date"],
            checkout,
            s["nights"],
            s["lagenhetsnummer"],
        )

    if DRY_RUN:
        log.warning("=== DRY RUN: no codes, emails, or billing ===")
        context.close()
        return

    # ==================================================================
    # Phase 3 — Seam access codes + emails
    # ==================================================================
    log.info("--- Phase 3: Access codes + email ---")

    seam = Seam()
    devices = seam.devices.list(search=LOCK_NAME)
    if not devices:
        log.error("no device matching '%s'", LOCK_NAME)
        context.close()
        return
    device = devices[0]
    log.info("  Lock: %s (%s)", device.display_name, device.device_id)

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
        log.warning("could not list existing codes")
        existing_ranges = []

    for idx, stay in enumerate(tomorrow_stays):
        log.info(
            "  [%d/%d] %s (%s)",
            idx + 1,
            len(tomorrow_stays),
            stay["first_name"],
            stay["start_date"],
        )

        start_dt, end_dt = _compute_times(stay)
        code_name = (
            f"Gästlägenhet: {stay['name']} "
            f"({stay['lagenhetsnummer']}) {stay['start_date']}"
        )

        # Skip if this stay's time window overlaps any existing code.
        # The lock only serves one apartment, so any overlap means the
        # date is already covered — no need to match by guest name.
        overlapping = any(s < end_dt and start_dt < e for s, e in existing_ranges)
        if overlapping:
            log.info("    SKIP: date range already covered by existing code")
            continue

        # Create code
        log.info("    Creating: %s", code_name)
        log.info("    Window:   %s → %s", start_dt.isoformat(), end_dt.isoformat())

        try:
            entry_code = _create_access_code(
                seam,
                device.device_id,
                code_name,
                start_dt.isoformat(),
                end_dt.isoformat(),
            )
        except Exception as exc:
            log.error("    ERROR creating code after retries: %s", exc)
            continue

        log.info("    Code:     %s", entry_code)
        existing_ranges.append((start_dt, end_dt))

        # Send email
        checkout_date = end_dt.strftime("%Y-%m-%d")
        subject = f"Kod till gästlägenheten {stay['start_date']} - {checkout_date}"
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
            log.info("    Sending email to %s …", stay["epost"])
            _send_email(stay["epost"], subject, body)
            log.info("    Email sent.")
        except Exception as exc:
            log.error("    ERROR sending email: %s", exc)

    # ==================================================================
    # Phase 4 — Billing in JM Home (one entry per night)
    # ==================================================================
    if DRY_RUN:
        log.warning("=== DRY RUN: skipping billing ===")
        context.close()
        return
    log.info("--- Phase 4: Billing ---")

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
        b
        for b in all_bookings
        if (b["name"], b["lagenhetsnummer"], b["datum"]) in stay_nights
    ]
    bookings_to_bill.sort(key=lambda b: b["datum"])

    _login_jmhome(page)

    cutoff_date = _latest_billed_date(page)
    log.info("  Latest billed date: %s", cutoff_date)
    log.info(
        "  Nights to bill: %d (from %d stay(s) starting tomorrow)",
        len(bookings_to_bill),
        len(tomorrow_stays),
    )

    billed = 0
    for idx, booking in enumerate(bookings_to_bill):
        name = booking["name"]
        lgh = booking["lagenhetsnummer"]
        datum = booking["datum"]

        log.info(
            "  [%d/%d] %s / %s / %s",
            idx + 1,
            len(bookings_to_bill),
            name,
            lgh,
            datum,
        )

        if datum <= cutoff_date:
            log.info("    SKIP: already billed (cutoff: %s)", cutoff_date)
            continue

        match = _find_best_match(page, name, lgh)
        if not match:
            log.info("    SKIP: no apartment match")
            continue
        option_value, _ = match

        page.locator('[data-test="form-select"]').select_option(
            value=option_value,
        )
        page.wait_for_load_state("networkidle")

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

        cutoff_date = datum
        billed += 1
        log.info("    Billed: '%s' %s SEK", avitext, BILLING_AMOUNT)

    # ==================================================================
    # Done
    # ==================================================================
    log.info(
        "Done — %d stay(s) processed, %d billing entr(ies) created",
        len(tomorrow_stays),
        billed,
    )
    context.close()
