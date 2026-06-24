"""Lyra Automation — extract and bill guest-apartment bookings."""

import logging
import sys

from playwright.sync_api import BrowserContext, Page, Playwright

# Load .env before any config reads so os.environ is populated.
# Must happen at import time because config reads env vars at module level.
from .utils import load_dotenv

load_dotenv()


def _setup_logging() -> None:
    """Configure root logger with timestamps and levels.

    Called once at import time.  Each module gets its own logger via
    ``logging.getLogger(__name__)`` and inherits this format.
    """
    logging.basicConfig(
        level=logging.DEBUG,  # modules use their own level
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stderr,
    )
    # Keep third-party loggers quiet unless something goes wrong
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("seam").setLevel(logging.WARNING)


_setup_logging()

from .config import CHROMIUM_PATH, HEADLESS  # noqa: E402


def launch_browser(playwright: Playwright) -> tuple[BrowserContext, Page]:
    """Launch Chromium and return ``(context, page)``."""
    launch_args: dict = {"headless": HEADLESS}
    if CHROMIUM_PATH:
        launch_args["executable_path"] = CHROMIUM_PATH
    browser = playwright.chromium.launch(**launch_args)
    context = browser.new_context()
    page = context.new_page()
    return context, page
