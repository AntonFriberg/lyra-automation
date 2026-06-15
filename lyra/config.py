"""All configuration in one place — edit this file, not the script logic."""

import os

from .utils import load_dotenv

# Load secrets from .env so they're available via os.environ
load_dotenv()

# --- Credentials (set in .env — see README) ---
LYRA_EMAIL = os.environ["LYRA_EMAIL"]
LYRA_PASSWORD = os.environ["LYRA_PASSWORD"]

# --- Path to Chromium -------------------------------------------------------
# Leave empty to use the Playwright-bundled Chromium (works on most systems).
# Set to a custom path if the bundled browser is incompatible with your setup,
# e.g. on NixOS:  "/home/your-user/.nix-profile/bin/chromium"
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
BILLING_AMOUNT = "350"            # SEK per guest-apartment night
BILLING_AVITEXT = "Gästlägenhet"  # prefix for the invoice line item text
