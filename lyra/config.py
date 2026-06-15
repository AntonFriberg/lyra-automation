"""All configuration in one place — edit this file, not the script logic."""

import os

from .utils import load_dotenv

# Load secrets from .env so they're available via os.environ
load_dotenv()

# --- Credentials (set in .env — see README) ---
LYRA_EMAIL = os.environ["LYRA_EMAIL"]
LYRA_PASSWORD = os.environ["LYRA_PASSWORD"]

# --- Browser -----------------------------------------------------------------
HEADLESS = False       # True → run Chromium without a visible window
# Custom Chromium path (leave empty for Playwright-bundled, set for NixOS etc.)
CHROMIUM_PATH = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

# --- Booking extraction settings ---------------------------------------------
NUM_MONTHS = 10       # how many calendar months to scan backward from today
TEST_MODE = False    # True → 1 month + 1 booking only (fast iteration)
OUTPUT_CSV = "bookings.csv"

# --- Site URL ----------------------------------------------------------------
BASE_URL = (
    "https://lyra-i-lund.smartbrf.se"
    "/att-bo-i-lyra/bokning-av-gemensamma-ytor/gastlagenheten#"
)

# --- Billing settings ---------------------------------------------------------
JM_EMAIL = os.environ["JM_EMAIL"]
JM_PASSWORD = os.environ["JM_PASSWORD"]
JM_BILLING_URL = (
    "https://portal.jmathome.se/kundportal/customer-invoices/billing/extra-costs"
)
BILLING_AMOUNT = "350"                # SEK per guest-apartment night
BILLING_AVITEXT = "Gästlägenhet"      # prefix for the invoice line item text
BILLING_ACCOUNT = "3250"              # JM account code for "Guest apartment" area
