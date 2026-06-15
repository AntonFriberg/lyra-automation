# Lyra Automation

Two scripts that together eliminate manual data entry for guest-apartment
bookings — saving multiple hours of clicking through calendar months and
copy-pasting into a billing portal, for every month of bookings.

- **`extract`** — pulls historic bookings from the [Lyra i Lund](https://lyra-i-lund.smartbrf.se/)
  Smart Brf calendar and writes them to CSV.
- **`bill`** — reads that CSV, matches each booking to the correct apartment
  in the JM billing portal, and creates the 350 SEK invoice line items —
  skipping any that were already billed.

Smart Brf and JM@Home Portal has no public API and the calendar requires JavaScript rendering
to expose booking details.  The JM portal likewise requires browser
interaction to select apartments and create billing entries.  Both scripts
use [Playwright](https://playwright.dev/python/) to drive a real Chromium
browser instead.

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Install Playwright browsers
uv run playwright install chromium

# 3. Create a .env file with your credentials
cp .env.example .env
# Edit .env — add both Lyra and JM credentials
```

> **Chromium not working?**  If the Playwright-bundled Chromium doesn't
> launch on your system, install Chromium through your package manager
> and set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` in your environment (or
> edit `CHROMIUM_PATH` in `lyra/config.py`).

## Usage

```bash
uv run python -m lyra extract   # pull bookings from calendar → bookings.csv
uv run python -m lyra bill      # enter billing from bookings.csv → JM portal
```

Or with the console script:

```bash
uv run lyra extract
uv run lyra bill
```

### Configuration

Edit **`lyra/config.py`** — all settings are at the top of that file:

| Setting | Default | Description |
|---|---|---|
| `NUM_MONTHS` | `1` | How many calendar months to scan backward |
| `TEST_MODE` | `False` | Extract: scan 1 month and 1 booking only (fast smoke test) |
| `DRY_RUN` | `False` | Bill: print what would be billed, don't actually save |
| `OUTPUT_CSV` | `"bookings.csv"` | Where extract writes and bill reads |
| `HEADLESS` | `False` | Run Chromium without a visible window |
| `BILLING_AMOUNT` | `"350"` | SEK per guest-apartment night |
| `BILLING_AVITEXT` | `"Gästlägenhet"` | Prefix for the invoice line item text |

### Output

**`bookings.csv`** with columns:

| Column | Example |
|---|---|
| `name` | `Firstname Lastname` |
| `telefon` | `0701234567` |
| `lagenhetsnummer` | `7-1002` |
| `datum` | `2026-06-04` (ISO 8601) |

Future dates are automatically excluded.  Billing entries for dates already
present in the JM portal are skipped.

## How it works

Both scripts use [Playwright](https://playwright.dev/python/) to drive a
headful Chromium browser.  Playwright provides high-level APIs for
navigation (`page.goto`), interaction (`click`, `fill`, `press`), and
DOM introspection (`page.evaluate`, `page.locator`), making it a good
fit for sites that rely on JavaScript-rendered interfaces where a simple
HTTP request wouldn't work.

### Extract (`lyra extract`)

1. **Login** — navigates to the gästlägenhet page, which redirects to an
   Auth0 login form if unauthenticated.
2. **Scan months** — iterates backward through the FullCalendar, clicking
   the `‹` (previous month) button.  Waits for event elements to stabilise
   since FullCalendar renders them asynchronously.
3. **Extract bookings** — for each unavailable calendar slot, clicks the
   element via JS (FullCalendar elements are often offscreen), reads the
   detail view inside a Remodal popup, and closes it.
4. **Write CSV** — deduplicates by `(name, date)`, excludes future dates,
   and converts Swedish dates to ISO 8601.

### Bill (`lyra bill`)

1. **Login** — navigates to the JM billing portal and waits for the
   apartment dropdown to fully populate (~90 apartments).
2. **Cutoff check** — reads the global billing table to find the latest
   already-billed date.  Skips every CSV booking on or before that date.
3. **Match apartment** — for each remaining booking, filters the dropdown
   by the last 4 digits of the lagenhetsnummer, refines by prefix digit,
   then picks the best name match using Levenshtein distance.
4. **Create entry** — selects the apartment, clicks *Skapa nytt tillägg*,
   fills the avitext (`Gästlägenhet <date>`), the amount (350 SEK), and
   clicks *Spara*.  Skips if already billed, prints debug output for every
   match decision.

## Project structure

```
lyra-automation/
├── lyra/
│   ├── __init__.py    # shared browser launcher
│   ├── __main__.py    # CLI entry point (extract / bill subcommands)
│   ├── config.py      # all settings — the only file you normally edit
│   ├── utils.py       # helpers: .env loading, Swedish date parsing
│   ├── extract.py     # calendar extraction logic
│   └── bill.py        # billing entry logic
├── tests/
│   └── test_billing.py
├── README.md
└── pyproject.toml
```
