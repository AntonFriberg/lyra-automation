import re
import os
from pathlib import Path
from playwright.sync_api import Playwright, sync_playwright, expect


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
    browser = playwright.chromium.launch(headless=False)
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
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.get_by_role("button", name="‹").click()
    page.locator("a").filter(has_text="Example Name").click()
    page.get_by_role("textbox", name="Telefon").click()
    page.get_by_role("textbox", name="Lägenhetsnummer").click()
    page.get_by_role("textbox", name="Kommentar").click()

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
