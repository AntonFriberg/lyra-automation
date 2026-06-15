"""Enter billing for guest-apartment bookings from bookings.csv into JM Home.

Reads bookings.csv, matches each booking to the correct apartment in the JM
billing portal's "Välj lägenhet / lokal" dropdown, and creates a 350 SEK
billing entry with the date in the avitext field.
"""

import csv
import re
from pathlib import Path

from playwright.sync_api import Playwright, Page, sync_playwright

from config import (
    CHROMIUM_PATH,
    JM_BILLING_URL,
    JM_EMAIL,
    JM_PASSWORD,
    BILLING_AMOUNT,
    BILLING_AVITEXT,
    OUTPUT_CSV,
)


# ---------------------------------------------------------------------------
# Apartment matching
# ---------------------------------------------------------------------------

def _apartment_score(option_text: str, csv_name: str, csv_lgh: str) -> float:
    """Score how well a dropdown option matches a CSV booking entry.

    *option_text* looks like:
      ``"Lund, Streetname 3-61105 (Firstname Lastname)"``

    Returns a score where higher is better.  A score of 0 means no match.
    """
    score = 0.0
    text_lower = option_text.lower()
    csv_name_lower = csv_name.lower()

    # --- Name match (0–50 points) -----------------------------------------
    # The name is in parentheses at the end.  We check if the CSV name
    # appears as a substring anywhere in the option text (case-insensitive).
    if csv_name_lower in text_lower:
        score += 50

    # --- Apartment-number match (0–50 points) ------------------------------
    # Extract all digit groups from the CSV lagenhetsnummer.
    # The option always has a prefix like "3-XXXXX".  We compare the numeric
    # suffix of each against the CSV value.
    csv_digits = re.sub(r"[^0-9]", "", csv_lgh)            # e.g. "6-1002" → "61002"
    if not csv_digits:
        return score

    # Pull the apartment number from the option: "3-61105" → "61105"
    m = re.search(r"(\d{4,6})\b", option_text)
    if m:
        opt_digits = m.group(1)                            # e.g. "61105"
        # How many trailing digits match?
        common = 0
        for a, b in zip(reversed(csv_digits), reversed(opt_digits)):
            if a == b:
                common += 1
            else:
                break
        # Weight: up to 45 points if 4+ digits match
        score += min(common, 5) * 9

        # Bonus: exact suffix match (last 4 digits)
        if csv_digits[-4:] == opt_digits[-4:] and len(csv_digits[-4:]) >= 3:
            score += 5

    return score


def _find_best_match(
    page: Page, csv_name: str, csv_lgh: str
) -> tuple[str, str] | None:
    """Return ``(option_value, option_text)`` of the best-matching apartment.

    Prints debug info showing the top candidates considered.
    Returns ``None`` if no option scores above 0.
    """
    options = page.locator("select option").all()
    scored: list[tuple[float, str, str]] = []  # (score, value, text)

    for opt in options:
        value = opt.get_attribute("value") or ""
        text = opt.inner_text().strip()
        if value == "-1" or not text:           # skip the placeholder
            continue
        s = _apartment_score(text, csv_name, csv_lgh)
        if s > 0:
            scored.append((s, value, text))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Debug: show what we considered
    print(f"  Matching '{csv_name}' / '{csv_lgh}':")
    if not scored:
        print("    NO MATCH FOUND")
        return None
    for s, val, txt in scored[:5]:
        marker = "  ← SELECTED" if s == scored[0][0] else ""
        print(f"    score={s:5.1f}  value={val:>6s}  {txt[:90]}{marker}")

    return (scored[0][1], scored[0][2])


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------

def _login(page: Page) -> None:
    """Log in to the JM billing portal."""
    page.goto(JM_BILLING_URL)
    page.locator('[data-test="login-userpw"]').click()
    page.locator('[data-test="login-userpw-username"]').fill(JM_EMAIL)
    page.locator('[data-test="login-userpw-username"]').press("Tab")
    page.locator('[data-test="login-userpw-password"]').fill(JM_PASSWORD)
    page.locator('[data-test="login-userpw-submit"]').click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run(playwright: Playwright) -> None:  # noqa: C901
    # --- Read bookings ----------------------------------------------------
    csv_path = Path(OUTPUT_CSV)
    if not csv_path.is_file():
        print(f"ERROR: {csv_path} not found — run main.py first")
        return

    with open(csv_path, newline="", encoding="utf-8") as fh:
        bookings = list(csv.DictReader(fh))
    print(f"Read {len(bookings)} bookings from {csv_path}")

    # --- Launch browser & login ------------------------------------------
    launch_args: dict = {"headless": False}
    if CHROMIUM_PATH:
        launch_args["executable_path"] = CHROMIUM_PATH
    browser = playwright.chromium.launch(**launch_args)
    context = browser.new_context()
    page = context.new_page()

    _login(page)

    # --- Process each booking --------------------------------------------
    for idx, booking in enumerate(bookings):
        name = booking["name"]
        lgh = booking["lagenhetsnummer"]
        datum = booking["datum"]

        print(f"\n--- [{idx + 1}/{len(bookings)}] {name} / {lgh} / {datum} ---")

        # 1. Match and select apartment
        match = _find_best_match(page, name, lgh)
        if not match:
            print("  SKIPPED: no apartment match")
            continue
        option_value, _ = match

        # Select the apartment from the dropdown
        page.locator("select").select_option(value=option_value)
        page.wait_for_timeout(500)

        # 2. Create the billing entry
        #    (follow the codegen-verified flow from billing_example.py)
        page.get_by_role("button", name="+ Skapa nytt tillägg").click()
        page.wait_for_timeout(300)

        page.get_by_role("combobox").select_option("3250")
        page.wait_for_timeout(200)

        avitext = f"{BILLING_AVITEXT} {datum}"
        page.get_by_role("textbox", name="Ange avitext").fill(avitext)
        page.get_by_role("textbox", name="Ange avitext").press("Tab")
        page.get_by_role("textbox", name="Ange belopp").fill(BILLING_AMOUNT)

        print(f"  Creating: avitext='{avitext}' amount={BILLING_AMOUNT} SEK")
        page.get_by_role("button", name="Spara ").click()
        page.wait_for_timeout(500)

    print(f"\nDone — processed {len(bookings)} bookings")
    context.close()
    browser.close()


if __name__ == "__main__":
    with sync_playwright() as playwright:
        run(playwright)
