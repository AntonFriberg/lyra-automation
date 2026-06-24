"""All configuration in one place.

Every value can be overridden via environment variable (``.env`` or CI
secrets).  Sensible defaults are provided for everything except secrets,
which default to the empty string and are validated lazily by each
``run_*`` function via :func:`validate`.
"""

import os


def validate(*keys: str) -> None:
    """Raise ``RuntimeError`` if any named config value is empty.

    Call this at the top of each ``run_*`` function with only the keys
    that subcommand actually needs.  This way a missing ``LYRA_EMAIL``
    doesn't block ``lyra keys``, which only needs Seam + Gmail creds.
    """
    missing = [k for k in keys if not globals().get(k)]
    if missing:
        raise RuntimeError(
            f"Missing required env vars: {', '.join(missing)}. "
            f"Set them in .env — see .env.example."
        )


# --- Credentials (set in .env — see README) ----------------------------------
LYRA_EMAIL    = os.environ.get("LYRA_EMAIL", "")
LYRA_PASSWORD = os.environ.get("LYRA_PASSWORD", "")
JM_EMAIL      = os.environ.get("JM_EMAIL", "")
JM_PASSWORD   = os.environ.get("JM_PASSWORD", "")

# --- Browser -----------------------------------------------------------------
# Default to headless — production is the common case.  Set HEADLESS=false
# locally in .env when you need to watch the browser.
HEADLESS = os.environ.get("HEADLESS", "true").lower() == "true"
# Custom Chromium path (leave empty for Playwright-bundled, set for NixOS etc.)
CHROMIUM_PATH = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "")

# --- Booking extraction settings ---------------------------------------------
NUM_MONTHS  = int(os.environ.get("NUM_MONTHS", "10"))
TEST_MODE   = os.environ.get("TEST_MODE", "false").lower() == "true"
DRY_RUN     = os.environ.get("DRY_RUN", "false").lower() == "true"
OUTPUT_CSV  = os.environ.get("OUTPUT_CSV", "bookings.csv")

# --- Site URL ----------------------------------------------------------------
BASE_URL = (
    "https://lyra-i-lund.smartbrf.se"
    "/att-bo-i-lyra/bokning-av-gemensamma-ytor/gastlagenheten#"
)

# --- Billing settings ---------------------------------------------------------
JM_BILLING_URL = (
    "https://portal.jmathome.se/kundportal/customer-invoices/billing/extra-costs"
)
BILLING_AMOUNT  = os.environ.get("BILLING_AMOUNT", "350")
BILLING_AVITEXT = os.environ.get("BILLING_AVITEXT", "Gästlägenhet")
BILLING_ACCOUNT = os.environ.get("BILLING_ACCOUNT", "3250")

# --- Upcoming bookings extraction ---------------------------------------------
UPCOMING_DAYS      = int(os.environ.get("UPCOMING_DAYS", "13"))
UPCOMING_OUTPUT_CSV = os.environ.get("UPCOMING_OUTPUT_CSV", "upcoming_bookings.csv")

# --- Access code keys via Seam ------------------------------------------------
SEAM_API_KEY = os.environ.get("SEAM_API_KEY", "")
LOCK_NAME    = os.environ.get("LOCK_NAME", "guest_apartment")

# --- Email sending via Gmail SMTP ---------------------------------------------
GMAIL_USER         = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SENDER_NAME        = os.environ.get("SENDER_NAME", "Anton Frost")

# --- Daily production pipeline ------------------------------------------------
DAILY_LOOKAHEAD = int(os.environ.get("DAILY_LOOKAHEAD", "6"))
