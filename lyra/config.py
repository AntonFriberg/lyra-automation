"""All configuration in one place — edit this file, not the script logic."""

import os

# --- Credentials (set in .env — see README) ---
LYRA_EMAIL = os.environ["LYRA_EMAIL"]
LYRA_PASSWORD = os.environ["LYRA_PASSWORD"]

# --- Browser -----------------------------------------------------------------
HEADLESS = os.environ.get("HEADLESS", "false").lower() == "true"  # no visible window
# Custom Chromium path (leave empty for Playwright-bundled, set for NixOS etc.)
CHROMIUM_PATH = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

# --- Booking extraction settings ---------------------------------------------
NUM_MONTHS = 10       # how many calendar months to scan backward from today
TEST_MODE = False    # True → 1 month + 1 booking only (fast iteration)
DRY_RUN = False      # True → print what would be billed, don't actually save
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

# --- Upcoming bookings extraction ---------------------------------------------
UPCOMING_DAYS = 13               # how many days ahead to scan (including today)
UPCOMING_OUTPUT_CSV = "upcoming_bookings.csv"

# --- Access code keys via Seam ------------------------------------------------
SEAM_API_KEY = os.environ.get("SEAM_API_KEY", "")
LOCK_NAME = "guest_apartment"   # name of the Yale smart lock in Seam

# --- Email sending via Gmail SMTP ---------------------------------------------
GMAIL_USER = os.environ.get("GMAIL_USER", "")              # sender email address
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")  # Gmail app password
SENDER_NAME = "Anton Frost"

# --- Daily production pipeline ------------------------------------------------
DAILY_LOOKAHEAD = 6    # tomorrow + 5 days = max booking length (6 nights)
