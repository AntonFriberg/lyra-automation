"""Lyra Automation — extract and bill guest-apartment bookings."""

from playwright.sync_api import Playwright, Page, BrowserContext

# Load .env before any config reads so os.environ is populated.
# Must happen at import time because config reads env vars at module level.
from .utils import load_dotenv

load_dotenv()

from .config import CHROMIUM_PATH, HEADLESS


def launch_browser(playwright: Playwright) -> tuple[BrowserContext, Page]:
    """Launch Chromium and return ``(context, page)``."""
    launch_args: dict = {"headless": HEADLESS}
    if CHROMIUM_PATH:
        launch_args["executable_path"] = CHROMIUM_PATH
    browser = playwright.chromium.launch(**launch_args)
    context = browser.new_context()
    page = context.new_page()
    return context, page
