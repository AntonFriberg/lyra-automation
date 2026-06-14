# Lyra Automation

Extract guest-apartment bookings from the [Lyra i Lund](https://lyra-i-lund.smartbrf.se/) Smart Brf calendar and write them to CSV.

Built to quickly pull the source of truth for historic bookings so they can
be entered as correct billing in another system.  Smart Brf has no public
API, and the calendar requires JavaScript rendering and browser interaction
to expose booking details, so a traditional HTTP scraper won't work.

## Setup

```bash
# 1. Install dependencies
uv sync

# 2. Install Playwright browsers
uv run playwright install chromium

# 3. Create a .env file with your credentials
cp .env.example .env
# Edit .env , add your email and password
```

> **Chromium not working?**  If the Playwright-bundled Chromium doesn't
> launch on your system, install Chromium through your package manager
> and set `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` in your environment (or
> edit `CHROMIUM_PATH` in `config.py`).

## Usage

```bash
uv run main.py
```

### Configuration

Edit **`config.py`** , all settings are at the top of that file:

| Setting | Default | Description |
|---|---|---|
| `NUM_MONTHS` | `1` | How many calendar months to scan backward |
| `TEST_MODE` | `False` | When `True`: scan 1 month, extract 1 booking (fast smoke-test) |
| `OUTPUT_CSV` | `"bookings.csv"` | Where to write results |
| `BASE_URL` | Lyra gästlägenhet | The calendar page URL |

### Output

**`bookings.csv`** with columns:

| Column | Example |
|---|---|
| `name` | `Firstname Lastname` |
| `telefon` | `0701234567` |
| `lagenhetsnummer` | `7-1002` |
| `datum` | `2026-06-04` (ISO 8601) |

Future dates (after today) are automatically excluded.

## How it works

The script uses [Playwright](https://playwright.dev/python/) to drive a
headful Chromium browser.  Playwright provides high-level APIs for
navigation (`page.goto`), interaction (`click`, `fill`, `press`), and
DOM introspection (`page.evaluate`, `page.locator`) , making it a good
fit for sites that rely on JavaScript-rendered calendars and modal
dialogs where a simple HTTP request wouldn't work.

1. **Login**: navigates to the gästlägenhet page, which redirects to an
   Auth0 login form if unauthenticated.
2. **Scan months**: iterates backward through the FullCalendar, clicking
   the `‹` (previous month) button.
3. **Extract bookings**: for each unavailable calendar slot, clicks the
   element (via JS, since FullCalendar elements are often offscreen),
   reads the detail view inside a Remodal popup, and closes it.
4. **Write CSV**: deduplicates by `(name, date)` and excludes future dates.

## Project structure

```
lyra-automation/
├── config.py     # All settings — the only file you normally edit
├── utils.py      # Helpers: .env loading, Swedish date parsing
├── main.py       # Orchestration — reads top-to-bottom
├── README.md
└── pyproject.toml
```
