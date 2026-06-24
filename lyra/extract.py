"""Extract guest-apartment bookings from Lyra's Smart Brf calendar."""

import csv
import logging
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

from playwright.sync_api import Playwright, Page

from . import launch_browser
from .config import (
    BASE_URL,
    LYRA_EMAIL,
    LYRA_PASSWORD,
    NUM_MONTHS,
    OUTPUT_CSV,
    TEST_MODE,
    UPCOMING_DAYS,
    UPCOMING_OUTPUT_CSV,
)
from .utils import parse_swedish_date


# ---------------------------------------------------------------------------
# Small helpers — named actions that keep run() readable
# ---------------------------------------------------------------------------

def _login(page: Page) -> None:
    """Log in via the Auth0 form that appears on unauthenticated visits."""
    page.goto(BASE_URL)
    page.locator("#top_bar").get_by_role("link", name="Logga in").click()
    page.get_by_role("textbox", name="Din e-postadress").fill(LYRA_EMAIL)
    page.get_by_role("textbox", name="Din e-postadress").press("Tab")
    page.get_by_role("textbox", name="Ditt lösenord").fill(LYRA_PASSWORD)
    page.get_by_role("textbox", name="Ditt lösenord").press("Enter")

    # Dismiss cookie consent banner if it appeared during login
    cookie_btn = page.locator(".cc-dismiss")
    if cookie_btn.count():
        cookie_btn.click()

    # Verify login succeeded — calendar grid must appear
    try:
        page.wait_for_selector(
            ".fc-day-grid-event", state="attached", timeout=10_000,
        )
    except Exception:
        raise RuntimeError(
            "Login to Smart Brf failed — calendar grid not found. "
            "Check LYRA_EMAIL / LYRA_PASSWORD in .env."
        )


def _wait_for_calendar(page: Page) -> None:
    """Wait until the FullCalendar grid has finished rendering all events.

    FullCalendar renders events asynchronously — the grid skeleton appears
    first, then individual event elements are added one by one.  We poll the
    count of ``a.unavailable`` elements until it stops growing.
    """
    page.wait_for_selector(".fc-day-grid-event", state="attached", timeout=10_000)
    prev = -1
    for _ in range(10):
        page.wait_for_timeout(300)
        cur = page.locator("a.unavailable").count()
        if cur == prev:
            return
        prev = cur


def _collect_names(page: Page) -> list[str]:
    """Return the visible text of every ``.fc-title`` inside an unavailable slot.

    We use ``page.evaluate`` because Playwright's ``inner_text()`` reports
    empty strings for these elements (FullCalendar's CSS clips the text at
    the anchor level and the text only lives in a child span).
    """
    return page.evaluate(
        """() => {
            const titles = document.querySelectorAll('a.unavailable .fc-title');
            return Array.from(titles)
                .map(el => el.textContent.trim())
                .filter(t => t);
        }"""
    )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_extract(playwright: Playwright) -> None:  # noqa: C901
    context, page = launch_browser(playwright)

    _login(page)

    if TEST_MODE:
        log.warning("=== TEST MODE: 1 month, 1 booking ===")

    all_results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()          # (name, iso_date) dedup
    months_to_scan = 1 if TEST_MODE else NUM_MONTHS

    # --- Scan each month ------------------------------------------------
    for month_idx in range(months_to_scan):

        # Navigate to previous month (skip the very first — we're already there)
        if month_idx > 0:
            page.get_by_role("button", name="‹").click()
            page.wait_for_load_state("networkidle")

        _wait_for_calendar(page)
        booking_names = _collect_names(page)

        log.info(
            "Month %d/%d — %d bookings: %s",
            month_idx + 1, months_to_scan,
            len(booking_names), booking_names,
        )

        # --- Extract each booking in the current month ------------------
        for i, name in enumerate(booking_names):
            if TEST_MODE and i > 0:
                break

            # Click the booking element via JS.  FullCalendar elements
            # are often offscreen / zero-height, which defeats Playwright's
            # coordinate-based click even with force=True.
            page.evaluate(
                """(idx) => {
                    document.querySelectorAll('a.unavailable')[idx].click();
                }""",
                i,
            )
            page.wait_for_selector(
                ".remodal.remodal-is-opened", state="attached", timeout=5_000,
            )

            # Read the detail-view fields
            telefon = page.get_by_role(
                "textbox", name="Telefon",
            ).input_value()
            lagenhetsnummer = page.get_by_role(
                "textbox", name="Lägenhetsnummer",
            ).input_value()
            epost = (
                page.locator("#booking_user span.email").text_content() or ""
            )

            date_el = page.locator("span.date")
            date_text = (
                (date_el.first.text_content() or "") if date_el.count() else ""
            )
            iso_date = parse_swedish_date(date_text)

            # Close the modal *before* any skip-logic so it never stays open
            page.locator("[data-remodal-action='close']").click()
            page.wait_for_selector(
                ".remodal.remodal-is-closed", state="attached", timeout=5_000,
            )

            # --- Filter & deduplicate -----------------------------------
            if iso_date > str(date.today()):
                continue            # skip future bookings

            key = (name, iso_date)
            if key not in seen:
                seen.add(key)
                all_results.append({
                    "name": name,
                    "telefon": telefon,
                    "epost": epost,
                    "lagenhetsnummer": lagenhetsnummer,
                    "datum": iso_date,
                })
                log.debug(
                    "  [%d] %s: telefon=%s epost=%s lägenhet=%s datum=%s",
                    len(all_results), name, telefon, epost,
                    lagenhetsnummer, iso_date,
                )

    # --- Write CSV ------------------------------------------------------
    csv_path = Path(OUTPUT_CSV)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["name", "telefon", "epost", "lagenhetsnummer", "datum"],
        )
        writer.writeheader()
        writer.writerows(all_results)
    log.info("Wrote %d rows to %s", len(all_results), csv_path)

    context.close()


# ---------------------------------------------------------------------------
# Upcoming bookings — next N days
# ---------------------------------------------------------------------------

def run_upcoming(playwright: Playwright) -> None:  # noqa: C901
    """Extract bookings for the next ``UPCOMING_DAYS`` from the calendar.

    Starts from the current month and navigates forward one month if the
    date window spills across a month boundary.  Writes a separate CSV so
    the historic ``bookings.csv`` is never overwritten.
    """
    context, page = launch_browser(playwright)

    _login(page)

    today = date.today()
    cutoff = today + timedelta(days=UPCOMING_DAYS)
    log.info("Scanning %s → %s (%d days)", today, cutoff, UPCOMING_DAYS)

    all_results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    # At most 2 months: current + next (if the window spills over)
    for month_idx in range(2):
        if month_idx > 0:
            page.get_by_role("button", name="›").click()
            page.wait_for_load_state("networkidle")

        _wait_for_calendar(page)
        booking_names = _collect_names(page)

        log.info(
            "Month %d: %d bookings: %s",
            month_idx + 1, len(booking_names), booking_names,
        )

        for i, name in enumerate(booking_names):
            # Click the booking element via JS
            page.evaluate(
                """(idx) => {
                    document.querySelectorAll('a.unavailable')[idx].click();
                }""",
                i,
            )
            page.wait_for_selector(
                ".remodal.remodal-is-opened", state="attached", timeout=5_000,
            )

            # Read the detail-view fields
            telefon = page.get_by_role(
                "textbox", name="Telefon",
            ).input_value()
            lagenhetsnummer = page.get_by_role(
                "textbox", name="Lägenhetsnummer",
            ).input_value()
            epost = (
                page.locator("#booking_user span.email").text_content() or ""
            )

            date_el = page.locator("span.date")
            date_text = (
                (date_el.first.text_content() or "") if date_el.count() else ""
            )
            iso_date = parse_swedish_date(date_text)

            # Close the modal *before* any skip-logic
            page.locator("[data-remodal-action='close']").click()
            page.wait_for_selector(
                ".remodal.remodal-is-closed", state="attached", timeout=5_000,
            )

            # Only keep dates within [today, cutoff]
            if iso_date < str(today) or iso_date > str(cutoff):
                continue

            key = (name, iso_date)
            if key not in seen:
                seen.add(key)
                all_results.append({
                    "name": name,
                    "telefon": telefon,
                    "epost": epost,
                    "lagenhetsnummer": lagenhetsnummer,
                    "datum": iso_date,
                })
                log.debug(
                    "  [%d] %s: telefon=%s epost=%s lägenhet=%s datum=%s",
                    len(all_results), name, telefon, epost,
                    lagenhetsnummer, iso_date,
                )

        # If the cutoff is still within the current calendar month we're done
        if month_idx == 0 and (
            cutoff.month == today.month and cutoff.year == today.year
        ):
            break

    # --- Write CSV ------------------------------------------------------
    csv_path = Path(UPCOMING_OUTPUT_CSV)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["name", "telefon", "epost", "lagenhetsnummer", "datum"],
        )
        writer.writeheader()
        writer.writerows(all_results)
    log.info("Wrote %d rows to %s", len(all_results), csv_path)

    context.close()
