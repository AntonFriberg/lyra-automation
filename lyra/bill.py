"""Enter billing for guest-apartment bookings from bookings.csv into JM Home."""

import csv
import re
from pathlib import Path

from playwright.sync_api import Playwright, Page

from . import launch_browser
from .config import (
    JM_BILLING_URL,
    JM_EMAIL,
    JM_PASSWORD,
    BILLING_ACCOUNT,
    BILLING_AMOUNT,
    BILLING_AVITEXT,
    OUTPUT_CSV,
)


# ---------------------------------------------------------------------------
# Apartment matching
# ---------------------------------------------------------------------------

def _parse_lgh(lgh: str) -> tuple[str, str] | None:
    """Extract ``(prefix, last4)`` from a lagenhetsnummer like ``"8-1301"``.

    Returns ``None`` if no 4-digit number is present (e.g. ``"Styrelsen"``),
    which signals that this booking should be skipped.
    """
    digits = re.sub(r"[^0-9]", "", lgh)       # "8-1301" → "81301"
    if len(digits) < 4:
        return None
    last4 = digits[-4:]
    # Prefix = digit immediately before the last 4 (if any)
    prefix = ""
    if len(digits) >= 5:
        prefix = digits[-5]
    return prefix, last4


def _parse_option(option_text: str) -> tuple[str, str]:
    """Extract ``(opt_number, opt_names)`` from a dropdown option.

    *option_text* looks like:
      ``"Lund Pentagonen 3-81301, Street 57 (Firstname Lastname)"``

    Returns the apartment-number string and the parenthesised names.
    """
    # Pull the apartment number: pattern like "3-XXXXX" or "3-XXXX"
    m = re.search(r"(\d{1,2}-\d{4,5})\b", option_text)
    opt_number = m.group(1) if m else ""

    # Pull the names inside parentheses
    m = re.search(r"\(([^)]+)\)", option_text)
    opt_names = m.group(1).strip() if m else ""

    return opt_number, opt_names


def _levenshtein(a: str, b: str) -> int:
    """Levenshtein distance between two strings (case-insensitive)."""
    a, b = a.lower(), b.lower()
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        cur = [i + 1]
        for j, cb in enumerate(b):
            cur.append(min(
                prev[j + 1] + 1,     # deletion
                cur[j] + 1,           # insertion
                prev[j] + (0 if ca == cb else 1),  # substitution
            ))
        prev = cur
    return prev[-1]


def _find_best_match(
    page: Page, csv_name: str, csv_lgh: str,
) -> tuple[str, str] | None:
    """Return ``(option_value, option_text)`` of the best-matching apartment.

    Strategy:
    1. Filter by last 4 digits of the lagenhetsnummer (mandatory).
    2. If a prefix digit exists (e.g. "8" in "8-1301"), prefer matches
       where that digit appears before the last 4 in the option number.
    3. Among remaining candidates, pick the one with the smallest
       Levenshtein distance between the CSV name and the option's names.

    Prints debug info for each booking.
    Returns ``None`` if no match is found.
    """
    parsed = _parse_lgh(csv_lgh)
    if parsed is None:
        print(f"  Matching '{csv_name}' / '{csv_lgh}': NO 4-DIGIT NUMBER → SKIPPED")
        return None
    prefix, last4 = parsed

    options = page.locator('[data-test="form-select"] option').all()
    candidates: list[dict] = []  # [{value, text, number, names, dist, has_prefix}]

    for opt in options:
        value = opt.get_attribute("value") or ""
        text = opt.inner_text().strip()
        if value == "-1" or not text:
            continue
        opt_number, opt_names = _parse_option(text)
        if not opt_number or opt_number[-4:] != last4:
            continue
        candidates.append({
            "value": value,
            "text": text,
            "number": opt_number,
            "names": opt_names,
            "has_prefix": prefix and prefix == opt_number[-5:-4],
            "dist": _levenshtein(csv_name, opt_names),
        })

    print(f"  Matching '{csv_name}' / '{csv_lgh}'  (prefix={prefix!r} last4={last4}):")

    if not candidates:
        print(f"    NO MATCH — no option ending in {last4}")
        return None

    # Separate prefix matches from others
    with_prefix = [c for c in candidates if c["has_prefix"]]
    pool = with_prefix if with_prefix else candidates

    # Pick the one with smallest Levenshtein distance
    pool.sort(key=lambda c: c["dist"])
    best = pool[0]

    # Debug: show all candidates considered
    for c in candidates[:8]:
        flags = []
        if c["has_prefix"]:
            flags.append("PREFIX")
        if c is best:
            flags.append("← SELECTED")
        flag_str = " ".join(flags)
        print(
            f"    dist={c['dist']:2d}  "
            f"lgh={c['number']:>7s}  "
            f"'{c['names'][:50]}'  "
            f"{flag_str}"
        )
    if len(candidates) > 8:
        print(f"    ... and {len(candidates) - 8} more candidates")

    return best["value"], best["text"]


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def _latest_billed_date(page: Page) -> str:
    """Return the latest date from the global billing table (newest-first).

    Before any apartment is selected the table shows all recent billing
    entries across all apartments.  Since each date can only have one
    booking, the first Gästlägenhet row gives us the cutoff: any booking
    on or before this date has already been billed.

    Returns ``"0000-00-00"`` if the table has no Gästlägenhet entries.
    """
    rows = page.locator("table tr").all()
    for row in rows:
        cells = row.locator("td, th").all()
        if len(cells) < 2:
            continue
        rubric = cells[1].inner_text().strip()
        if rubric.startswith(BILLING_AVITEXT):
            return rubric[len(BILLING_AVITEXT):].strip()
    return "0000-00-00"


def _login(page: Page) -> None:
    """Log in to the JM billing portal."""
    page.goto(JM_BILLING_URL)
    page.locator('[data-test="login-userpw"]').click()
    page.locator('[data-test="login-userpw-username"]').fill(JM_EMAIL)
    page.locator('[data-test="login-userpw-username"]').press("Tab")
    page.locator('[data-test="login-userpw-password"]').fill(JM_PASSWORD)
    page.locator('[data-test="login-userpw-submit"]').click()
    page.wait_for_load_state("networkidle")

    # The apartment dropdown is populated asynchronously.  Wait until the
    # option count stabilises (the page has ~90 apartments, so >10 is a
    # safe signal that the list has finished loading).
    page.wait_for_function(
        "() => document.querySelectorAll('select option').length > 10",
        timeout=10_000,
    )
    page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_bill(playwright: Playwright) -> None:  # noqa: C901
    # --- Read bookings ----------------------------------------------------
    csv_path = Path(OUTPUT_CSV)
    if not csv_path.is_file():
        print(f"ERROR: {csv_path} not found — run main.py first")
        return

    with open(csv_path, newline="", encoding="utf-8") as fh:
        bookings = list(csv.DictReader(fh))

    # Process oldest first (ISO 8601 dates sort lexicographically)
    bookings.sort(key=lambda b: b["datum"])
    print(f"Read {len(bookings)} bookings from {csv_path} (oldest first)")

    # --- Launch browser & login ------------------------------------------
    context, page = launch_browser(playwright)

    _login(page)

    # --- Determine cutoff date from global table -------------------------
    # The table is newest-first and shows all apartments when unfiltered.
    # Any booking on or before this date has already been billed.
    cutoff_date = _latest_billed_date(page)
    print(f"Latest billed date in table: {cutoff_date}")

    # --- Process each booking --------------------------------------------
    for idx, booking in enumerate(bookings):
        name = booking["name"]
        lgh = booking["lagenhetsnummer"]
        datum = booking["datum"]

        print(f"\n--- [{idx + 1}/{len(bookings)}] {name} / {lgh} / {datum} ---")

        # Skip if already billed (cutoff from the global unfiltered table,
        # read once after login).  Check early to avoid wasted work.
        if datum <= cutoff_date:
            print(f"  SKIPPED: already billed (cutoff: {cutoff_date})")
            continue

        # 1. Match and select apartment
        match = _find_best_match(page, name, lgh)
        if not match:
            print("  SKIPPED: no apartment match")
            continue
        option_value, _ = match

        # Select the apartment from the dropdown (use data-test to avoid
        # matching the billing-form combobox which is also a <select>)
        page.locator('[data-test="form-select"]').select_option(value=option_value)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        # 2. Create the billing entry
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

        print(f"  Creating: avitext='{avitext}' amount={BILLING_AMOUNT} SEK")
        page.get_by_role("button", name="Spara ").click()

        # Wait for the save to complete and the form to close, so the
        # "+ Skapa nytt tillägg" button is available for the next booking.
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        # Advance the cutoff so a restart after a crash won't re-bill
        # this date, and same-date edge cases within this run are handled.
        cutoff_date = datum

    print(f"\nDone — processed {len(bookings)} bookings")
    context.close()
