import os
from pathlib import Path
from playwright.sync_api import Playwright, sync_playwright


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
    page.goto("https://lyra-i-lund.smartbrf.se/")
    page.get_by_role("link", name="Logga in").click()
    page.get_by_role("textbox", name="Din e-postadress").fill(LYRA_EMAIL)
    page.get_by_role("textbox", name="Din e-postadress").press("Tab")
    page.get_by_role("textbox", name="Ditt lösenord").fill(LYRA_PASSWORD)
    page.get_by_role("button", name="Logga in").click()
    page.get_by_role("link", name="Att bo i Lyra").click()
    page.get_by_role("link", name="+").nth(3).click()
    page.get_by_role("link", name="Gästlägenhet").click()
    # Wait for the FullCalendar to render its event elements
    page.wait_for_selector(".fc-day-grid-event", state="attached", timeout=10_000)

    # Collect booking names from unavailable slots.
    # The <a> elements report empty innerText (CSS hides text at the anchor level),
    # so we query the DOM directly.  Available slots have &nbsp; in fc-title — skip those.
    booking_names: list[str] = page.evaluate(
        """() => {
            const titles = document.querySelectorAll('a.unavailable .fc-title');
            return Array.from(titles)
                .map(el => el.textContent.trim())
                .filter(t => t);
        }"""
    )

    print(f"Found {len(booking_names)} bookings: {booking_names}")

    # Snapshot the calendar URL so we can return here after each detail view
    calendar_url = page.url

    for i, name in enumerate(booking_names):
        # Force-click the i-th unavailable <a> — FullCalendar's CSS clips event
        # elements so Playwright considers them "not visible", but they work fine.
        page.locator("a.unavailable").nth(i).click(force=True)

        # Extract the information that appears after clicking
        telefon = page.get_by_role("textbox", name="Telefon").input_value()
        lagenhetsnummer = page.get_by_role("textbox", name="Lägenhetsnummer").input_value()

        date_el = page.locator("span.date")
        date_text = date_el.first.text_content() if date_el.count() else ""

        print(f"[{i}] {name}: telefon={telefon}, lägenhet={lagenhetsnummer}, datum={date_text}")

        # Return to the calendar (detail view is in-page JS, not a history entry)
        page.goto(calendar_url)
        page.wait_for_selector(".fc-day-grid-event", state="attached", timeout=10_000)

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
