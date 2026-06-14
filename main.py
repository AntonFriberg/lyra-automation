import csv
import os
import re
from datetime import date
from pathlib import Path
from playwright.sync_api import Playwright, sync_playwright

SV_MONTHS = {
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
    """Convert '1 Juni 2026' → '2026-06-01'."""
    m = re.match(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text.strip())
    if not m:
        return text
    day, month_name, year = m.groups()
    month = SV_MONTHS.get(month_name.lower())
    if month is None:
        return text
    return f"{year}-{month:02d}-{int(day):02d}"


def load_dotenv(path: str | Path = ".env") -> None:
    path = Path(path)
    if not path.is_file():
        return
    with open(path) as f:
        for raw in f:
            line = raw.strip()
            # Lines are skipped if they are empty, start with '#', or lack '='.
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Values are stripped of surrounding quotes (single or double).
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ[key] = value


load_dotenv()

LYRA_EMAIL = os.environ["LYRA_EMAIL"]
LYRA_PASSWORD = os.environ["LYRA_PASSWORD"]


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(
        headless=False,
        executable_path=os.environ.get(
            "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH",
            "/home/antonfr/.nix-profile/bin/chromium",
        ),
    )
    context = browser.new_context()
    page = context.new_page()
    page.goto(
        "https://lyra-i-lund.smartbrf.se/att-bo-i-lyra/bokning-av-gemensamma-ytor/gastlagenheten#"
    )
    page.locator("#top_bar").get_by_role("link", name="Logga in").click()
    page.get_by_role("textbox", name="Din e-postadress").fill(LYRA_EMAIL)
    page.get_by_role("textbox", name="Din e-postadress").press("Tab")
    page.get_by_role("textbox", name="Ditt lösenord").fill(LYRA_PASSWORD)
    page.get_by_role("textbox", name="Ditt lösenord").press("Enter")

    # Dismiss cookie consent banner if present (may intercept clicks)
    cookie_btn = page.locator(".cc-dismiss")
    if cookie_btn.count():
        cookie_btn.click()

    all_results: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()  # (name, iso_date) dedup across months

    for month in range(12):
        # Navigate to previous month (skip first iteration — already on current)
        if month > 0:
            page.get_by_role("button", name="‹").click()
            page.wait_for_load_state("networkidle")

        # Ensure the FullCalendar has rendered its event elements.
        # FullCalendar loads events asynchronously after the grid appears,
        # so we poll until the count of unavailable elements stabilizes.
        page.wait_for_selector(
            ".fc-day-grid-event", state="attached", timeout=10_000
        )
        prev_count = -1
        for _ in range(10):
            page.wait_for_timeout(300)
            count = page.locator("a.unavailable").count()
            if count == prev_count:
                break
            prev_count = count

        # Collect booking names from unavailable slots.
        booking_names: list[str] = page.evaluate(
            """() => {
                const titles = document.querySelectorAll('a.unavailable .fc-title');
                return Array.from(titles)
                    .map(el => el.textContent.trim())
                    .filter(t => t);
            }"""
        )

        print(f"Month {month + 1}/12 — {len(booking_names)} bookings: {booking_names}")

        for i, name in enumerate(booking_names):
            # Click via JS — FullCalendar elements are often offscreen or
            # zero-height, which defeats Playwright's coordinate-based click
            # even with force=True.
            page.evaluate(
                """(idx) => {
                    document.querySelectorAll('a.unavailable')[idx].click();
                }""",
                i,
            )
            # Wait for the Remodal to fully open before reading fields
            page.wait_for_selector(
                ".remodal.remodal-is-opened", state="attached", timeout=5_000
            )

            telefon = page.get_by_role("textbox", name="Telefon").input_value()
            lagenhetsnummer = page.get_by_role(
                "textbox", name="Lägenhetsnummer"
            ).input_value()

            date_el = page.locator("span.date")
            date_text = (date_el.first.text_content() or "") if date_el.count() else ""
            iso_date = parse_swedish_date(date_text)

            # Close the modal before any skip logic so it doesn't stay open
            page.locator("[data-remodal-action='close']").click()
            page.wait_for_selector(
                ".remodal.remodal-is-closed", state="attached", timeout=5_000
            )

            # Skip future dates
            if iso_date > str(date.today()):
                continue

            key = (name, iso_date)
            if key not in seen:
                seen.add(key)
                all_results.append(
                    {
                        "name": name,
                        "telefon": telefon,
                        "lagenhetsnummer": lagenhetsnummer,
                        "datum": iso_date,
                    }
                )
                print(
                    f"  [{len(all_results)}] {name}: telefon={telefon}, "
                    f"lägenhet={lagenhetsnummer}, datum={iso_date}"
                )

    # Write results to CSV
    csv_path = Path("bookings.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["name", "telefon", "lagenhetsnummer", "datum"]
        )
        writer.writeheader()
        writer.writerows(all_results)
    print(f"Wrote {len(all_results)} rows to {csv_path}")

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
