"""Enter billing for guest-apartment bookings from bookings.csv into JM Home."""

import csv
import logging
import re
from pathlib import Path

from playwright.sync_api import Page, Playwright

from . import launch_browser
from .config import (
    BILLING_ACCOUNT,
    BILLING_AMOUNT,
    BILLING_AVITEXT,
    DRY_RUN,
    JM_BILLING_URL,
    JM_EMAIL,
    JM_PASSWORD,
    OUTPUT_CSV,
    validate,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Apartment matching
# ---------------------------------------------------------------------------


def _is_board_booking(lgh: str) -> bool:
    """Return ``True`` if the apartment number indicates a board booking.

    Board members may book the guest apartment without a regular apartment
    number (e.g. ``"Styrelsen"``).  These stays should *not* be billed.
    Matching is case-insensitive and matches anywhere in the string so
    variants like ``"styrelsen"``, ``"Styrelsen "``, or ``"Brf Styrelsen"``
    all work.
    """
    return "styrelse" in lgh.lower()


def _parse_lgh(lgh: str) -> tuple[str | None, str] | None:
    """Extract ``(prefix, digits)`` from a lagenhetsnummer.

    Returns:
    - ``(prefix, all_digits)`` for 5+ digits (e.g. ``"8-1301"`` → ``("8", "81301")``)
    - ``(None, last4)`` for exactly 4 digits (e.g. ``"1005"`` → ``(None, "1005")``)
    - ``None`` for <4 digits or non-numeric — caller falls back to name-only matching
    """
    digits = re.sub(r"[^0-9]", "", lgh)  # "8-1301" → "81301"
    if len(digits) < 4:
        return None
    prefix = digits[-5] if len(digits) >= 5 else None
    return prefix, digits


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
            cur.append(
                min(
                    prev[j + 1] + 1,  # deletion
                    cur[j] + 1,  # insertion
                    prev[j] + (0 if ca == cb else 1),  # substitution
                )
            )
        prev = cur
    return prev[-1]


# ---------------------------------------------------------------------------
# Name-distance helper
# ---------------------------------------------------------------------------


def _name_distance(csv_name: str, opt_names: str) -> int:
    """Minimum Levenshtein distance from *csv_name* to any occupant name.

    *opt_names* may be a comma-separated list like ``"Alice A, Bob B"``.
    Matching against individual names avoids penalising multi-occupant
    apartments where the CSV only carries one guest.
    """
    if not opt_names:
        return 999
    names = [n.strip() for n in opt_names.split(",")]
    return min(_levenshtein(csv_name, n) for n in names)


# Threshold for name-only matching (mode C — no apartment number).
_NAME_ONLY_MAX_DIST = 5


# ---------------------------------------------------------------------------
# Apartment matching
# ---------------------------------------------------------------------------


def _find_best_match(
    page: Page,
    csv_name: str,
    csv_lgh: str,
) -> tuple[str, str] | None:
    """Return ``(option_value, option_text)`` of the best-matching apartment.

    Three matching modes, depending on what *_parse_lgh* returns:

    * **Full** (5+ digits) — filter by *all* digits, prefer prefix match,
      pick smallest name distance.
    * **Partial** (4 digits) — filter by the 4 digits, pick smallest name
      distance (no prefix preference available).
    * **Name-only** (<4 digits or non-numeric) — match against every option
      by name alone; requires distance ≤ *_NAME_ONLY_MAX_DIST*.

    Returns ``None`` if no match is found.
    """
    parsed = _parse_lgh(csv_lgh)

    # --- Name-only fallback (no usable apartment number) -----------------
    if parsed is None:
        log.info(
            "  Matching '%s' / '%s': no apartment number — name-only fallback",
            csv_name,
            csv_lgh,
        )
        if not csv_name:
            log.warning("    SKIP: no name to match on")
            return None

        options = page.locator('[data-test="form-select"] option').all()
        candidates: list[dict] = []
        for opt in options:
            value = opt.get_attribute("value") or ""
            text = opt.inner_text().strip()
            if value == "-1" or not text:
                continue
            _opt_num, opt_names = _parse_option(text)
            if not opt_names:
                continue
            candidates.append(
                {
                    "value": value,
                    "text": text,
                    "names": opt_names,
                    "dist": _name_distance(csv_name, opt_names),
                }
            )

        if not candidates:
            log.warning("    SKIP: no options with names found")
            return None

        candidates.sort(key=lambda c: c["dist"])
        best = candidates[0]

        if best["dist"] <= _NAME_ONLY_MAX_DIST:
            log.warning(
                "    NAME-ONLY MATCH: '%s' (dist=%d) — verify manually",
                best["text"],
                best["dist"],
            )
            return best["value"], best["text"]

        log.warning(
            "    SKIP: no name match within threshold (best dist=%d, "
            "threshold=%d)",
            best["dist"],
            _NAME_ONLY_MAX_DIST,
        )
        return None

    # --- Digit-based matching -------------------------------------------
    prefix, digits = parsed

    options = page.locator('[data-test="form-select"] option').all()
    candidates: list[dict] = []  # [{value, text, number, names, dist, has_prefix}]

    for opt in options:
        value = opt.get_attribute("value") or ""
        text = opt.inner_text().strip()
        if value == "-1" or not text:
            continue
        opt_number, opt_names = _parse_option(text)
        # Filter by the FULL digit string — more precise than last-4 only.
        if not opt_number or not opt_number.endswith(digits):
            continue
        candidates.append(
            {
                "value": value,
                "text": text,
                "number": opt_number,
                "names": opt_names,
                "has_prefix": prefix is not None
                and prefix == opt_number[-5:-4],
                "dist": _name_distance(csv_name, opt_names),
            }
        )

    log.info(
        "  Matching '%s' / '%s'  (prefix=%r digits=%s):",
        csv_name,
        csv_lgh,
        prefix,
        digits,
    )

    if not candidates:
        log.info("    NO MATCH — no option ending in %s", digits)
        return None

    # Separate prefix matches from others (only meaningful for 5+ digits)
    with_prefix = [c for c in candidates if c["has_prefix"]]
    pool = with_prefix if with_prefix else candidates

    # Pick the one with smallest name distance
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
        log.debug(
            "    dist=%2d  lgh=%7s  '%s'  %s",
            c["dist"],
            c["number"],
            c["names"][:50],
            flag_str,
        )
    if len(candidates) > 8:
        log.debug("    ... and %d more candidates", len(candidates) - 8)

    return best["value"], best["text"]


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def _latest_billed_date(page: Page) -> str:
    """Return the latest billed date from the global billing table.

    Scans the entire visible table for ``Gästlägenhet`` entries and
    returns the maximum (most recent) date.  Because ISO 8601 dates
    (``YYYY-MM-DD``) sort lexicographically, ``max()`` works directly.

    The table is rendered newest-creation-first by the JM portal, but
    a manual entry for an old stay date can appear before newer entries.
    Taking the max across all rows is robust to this — manual entries
    never drag the cutoff backwards.

    Returns ``"0000-00-00"`` if the table has no Gästlägenhet entries,
    which causes every booking to be billed (safe default).
    """
    date_pattern = re.compile(
        rf"{re.escape(BILLING_AVITEXT)}\s+(\d{{4}}-\d{{2}}-\d{{2}})",
    )
    latest = "0000-00-00"
    rows = page.locator("table tr").all()
    for row in rows:
        cells = row.locator("td, th").all()
        if len(cells) < 2:
            continue
        rubric = cells[1].inner_text().strip()
        m = date_pattern.search(rubric)
        if m:
            latest = max(latest, m.group(1))
    if latest == "0000-00-00":
        log.warning("no %s entries found in billing table", BILLING_AVITEXT)
    return latest


def _login_jmhome(page: Page) -> None:
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
    # safe signal that the list has finished loading).  Also acts as a
    # login-verification check — if we never see >10 options, login failed.
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('select option').length > 10",
            timeout=10_000,
        )
    except Exception as exc:
        raise RuntimeError(
            "Login to JM Home failed — apartment dropdown not populated. "
            "Check JM_EMAIL / JM_PASSWORD in .env."
        ) from exc
    page.wait_for_timeout(300)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def run_bill(playwright: Playwright) -> None:  # noqa: C901
    validate("JM_EMAIL", "JM_PASSWORD")
    # --- Read bookings ----------------------------------------------------
    csv_path = Path(OUTPUT_CSV)
    if not csv_path.is_file():
        log.error("%s not found — run 'lyra extract' first", csv_path)
        return

    with open(csv_path, newline="", encoding="utf-8") as fh:
        bookings = list(csv.DictReader(fh))

    # Process oldest first (ISO 8601 dates sort lexicographically)
    bookings.sort(key=lambda b: b["datum"])
    log.info("Read %d bookings from %s (oldest first)", len(bookings), csv_path)

    # --- Launch browser & login ------------------------------------------
    context, page = launch_browser(playwright)

    _login_jmhome(page)

    if DRY_RUN:
        log.warning("=== DRY RUN: nothing will be saved ===")

    # --- Determine cutoff date from global table -------------------------
    # The table is newest-first and shows all apartments when unfiltered.
    # Any booking on or before this date has already been billed.
    cutoff_date = _latest_billed_date(page)
    log.info("Latest billed date in table: %s", cutoff_date)

    # --- Process each booking --------------------------------------------
    for idx, booking in enumerate(bookings):
        name = booking["name"]
        lgh = booking["lagenhetsnummer"]
        datum = booking["datum"]

        log.info(
            "--- [%d/%d] %s / %s / %s ---",
            idx + 1,
            len(bookings),
            name,
            lgh,
            datum,
        )

        # Skip if already billed (cutoff from the global unfiltered table,
        # read once after login).  Check early to avoid wasted work.
        if datum <= cutoff_date:
            log.info("  SKIPPED: already billed (cutoff: %s)", cutoff_date)
            continue

        # Skip board bookings — these should never be billed.
        if _is_board_booking(lgh):
            log.info("  SKIPPED: board booking (lgh=%r) — no billing", lgh)
            continue

        # 1. Match and select apartment
        match = _find_best_match(page, name, lgh)
        if not match:
            log.info("  SKIPPED: no reliable apartment match (see details above)")
            continue
        option_value, _ = match

        # Select the apartment from the dropdown (use data-test to avoid
        # matching the billing-form combobox which is also a <select>)
        page.locator('[data-test="form-select"]').select_option(value=option_value)
        page.wait_for_load_state("networkidle")

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

        log.info("  Creating: avitext='%s' amount=%s SEK", avitext, BILLING_AMOUNT)
        if DRY_RUN:
            page.get_by_role("button", name="Avbryt").click()
            page.wait_for_timeout(300)
        else:
            page.get_by_role("button", name="Spara ").click()
            page.wait_for_load_state("networkidle")
            cutoff_date = datum  # advance so a restart won't re-bill

    log.info("Done — processed %d bookings", len(bookings))
    context.close()
