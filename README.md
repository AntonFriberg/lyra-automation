# Lyra Automation

A set of scripts that together eliminate manual work for guest-apartment
bookings — scraping the calendar, entering billing, and delivering door
codes — saving hours of repetitive data entry every month.

- **`extract`** — pulls historic bookings from the [Lyra i Lund](https://lyra-i-lund.smartbrf.se/)
  Smart Brf calendar and writes them to CSV.
- **`upcoming`** — scans the next 13 days for bookings (navigating forward
  one month if needed) and writes them to a separate CSV.
- **`bill`** — reads that CSV, matches each booking to the correct apartment
  in the JM billing portal, and creates the 350 SEK invoice line items —
  skipping any that were already billed.
- **`keys`** — reads upcoming bookings, groups consecutive nights by email,
  creates time-bound access codes via the [Seam](https://seam.co) API on a
  Yale smart lock, and emails the code to each guest.
- **`daily`** — production pipeline that runs extract + keys + bill in one
  shot, focused on tomorrow's booking window.  Designed to run as a daily
  Cloud Run Job triggered by Cloud Scheduler at 9 AM CET.

Smart Brf and JM@Home Portal have no public API and require JavaScript
rendering, so the extract and bill scripts use
[Playwright](https://playwright.dev/python/) to drive a real Chromium
browser.  The keys script is pure API — Seam for access codes, Gmail SMTP
for delivery.

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
uv run python -m lyra extract   # pull historic bookings → bookings.csv
uv run python -m lyra upcoming  # pull next 13 days → upcoming_bookings.csv
uv run python -m lyra keys      # create access codes & email guests
uv run python -m lyra daily     # production: extract + keys + bill in one run
uv run python -m lyra bill      # enter billing from bookings.csv → JM portal
```

Or with the console script:

```bash
uv run lyra extract
uv run lyra upcoming
uv run lyra keys
uv run lyra daily
uv run lyra bill
```

### Configuration

Edit **`lyra/config.py`** — all settings are at the top of that file:

| Setting | Default | Description |
|---|---|---|
| `NUM_MONTHS` | `1` | How many calendar months to scan backward |
| `TEST_MODE` | `False` | Extract: scan 1 month and 1 booking only (fast smoke test) |
| `DRY_RUN` | `False` | Bill & keys: preview only, don't save codes or send emails |
| `OUTPUT_CSV` | `"bookings.csv"` | Where extract writes and bill reads |
| `HEADLESS` | `False` | Run Chromium without a visible window |
| `BILLING_AMOUNT` | `"350"` | SEK per guest-apartment night |
| `BILLING_AVITEXT` | `"Gästlägenhet"` | Prefix for the invoice line item text |
| `UPCOMING_DAYS` | `13` | How many days ahead `upcoming` scans |
| `UPCOMING_OUTPUT_CSV` | `"upcoming_bookings.csv"` | Where `upcoming` writes and `keys` reads |
| `LOCK_NAME` | `"guest_apartment"` | Yale smart lock name in Seam |
| `SEAM_API_KEY` | (from `.env`) | Seam API key for access code creation |
| `GMAIL_USER` | (from `.env`) | Gmail address that sends the codes |
| `GMAIL_APP_PASSWORD` | (from `.env`) | Gmail app password for SMTP |
| `SENDER_NAME` | `"Anton Frost"` | Name shown in the email From field |
| `DAILY_LOOKAHEAD` | `6` | Days to scan (tomorrow + 5 = max booking length) |

### Output

**`bookings.csv`** and **`upcoming_bookings.csv`** share the same columns:

| Column | Example |
|---|---|
| `name` | `Firstname Lastname` |
| `telefon` | `0701234567` |
| `epost` | `firstname.lastname@example.com` |
| `lagenhetsnummer` | `7-1002` |
| `datum` | `2026-06-04` (ISO 8601) |

Future dates are automatically excluded.  Billing entries for dates already
present in the JM portal are skipped.

## How it works

The extract and bill scripts use [Playwright](https://playwright.dev/python/)
to drive a headful Chromium browser.  Playwright provides high-level APIs
for navigation (`page.goto`), interaction (`click`, `fill`, `press`), and
DOM introspection (`page.evaluate`, `page.locator`), making it a good fit
for sites that rely on JavaScript-rendered interfaces where a simple HTTP
request wouldn't work.  The keys script uses the [Seam](https://seam.co)
Python SDK and Gmail SMTP instead.

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

### Upcoming (`lyra upcoming`)

1. **Login** — same Auth0 login flow as `extract`.
2. **Scan current month** — waits for FullCalendar to stabilise, then opens
   each booking's detail view to read the date.
3. **Next month (if needed)** — when the 13-day window spills into the next
   calendar month, clicks `›` to navigate forward and repeats step 2.
4. **Filter** — keeps only bookings whose date falls within [today, today +
   ``UPCOMING_DAYS``]; skips past dates and dates beyond the cutoff.
5. **Write CSV** — writes ``upcoming_bookings.csv`` (separate from the
   historic ``bookings.csv`` used by `extract`).

### Keys (`lyra keys`)

1. **Read CSV** — loads `upcoming_bookings.csv`.
2. **Group stays** — sorts by email then date, merging consecutive nights
   that share the same email into a single stay.
3. **Create access code** — for each stay, calls the Seam API to create a
   time-bound PIN on the Yale lock, active from 15:00 on check-in day to
   12:00 the day after check-out (Europe/Stockholm timezone).
4. **Skip duplicates** — checks existing codes on the lock and skips stays
   that already have one.
5. **Send email** — delivers a Swedish email with the PIN, dates, and
   instructions to the guest via Gmail SMTP.
6. **DRY_RUN** — when enabled, prints the grouped stays and exits before
   touching Seam or sending any email.

### Daily (`lyra daily`)

The daily pipeline combines extract, keys, and bill into a single run
sharing one browser session.  It extracts bookings for tomorrow through
tomorrow + ``DAILY_LOOKAHEAD - 1`` days, groups consecutive nights into
stays, creates access codes and sends emails only for stays that **start**
tomorrow, then enters billing for each night.

Idempotent by design — re-running the same day skips already-created
codes and already-billed dates.

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

## Deployment tools (Nix flake)

A dev shell with Docker for building and testing the container locally:

```bash
nix develop              # bash
nix develop --command fish  # fish (if fish is your login shell)
```

The shell prints available tool versions and first-time setup commands.

## Deployment (Docker)

The `daily` subcommand is packaged as a Docker container.  Playwright's
own Chromium is used inside the image, so no system browser is needed.

```bash
# Build the image
docker build -t lyra-daily .

# Run locally with your .env file
docker run --rm --env-file .env lyra-daily
```

```bash
# Run other subcommands
docker run --rm --env-file .env lyra-daily uv run python -m lyra upcoming
docker run --rm --env-file .env lyra-daily uv run python -m lyra keys
```

## Deployment (GitHub Actions)

A single scheduled workflow (`.github/workflows/daily.yml`) runs the
pipeline every morning.  Python packages and Playwright Chromium are
cached between runs, so only new versions trigger downloads.

### 1. Add secrets

Go to your repo → Settings → Secrets and variables → Actions → New
repository secret.  Add every key from your `.env` file.

### 2. Dependency freezing

- **Python packages** — locked by `uv.lock` (commit it; `uv sync --frozen`
  refuses to run if the lockfile is out of date).
- **Chromium** — locked by the pinned `playwright` version in `uv.lock`.
  Playwright ships a specific Chromium build per release.

This means the pipeline won't silently pick up new package or browser
versions — updates are intentional, via `uv lock --upgrade-package`.

### 3. How it works

`.github/workflows/daily.yml` runs at 7:00 UTC daily:
1. Checkout the repo
2. Restore uv package cache via `setup-uv` (built-in, keyed on `uv.lock`)
3. Run `uv sync` (fast with cache hit) + `playwright install chromium`
4. Run `lyra daily`

Playwright browsers are not cached (per Playwright's own recommendation —
cache restore time is comparable to download time).

That's it — no billing, no cloud console, no Docker registry.  Use the
Actions tab to trigger a daily run manually.

## Project structure

```
lyra-automation/
├── lyra/
│   ├── __init__.py    # shared browser launcher
│   ├── __main__.py    # CLI entry point (5 subcommands)
│   ├── config.py      # all settings — the only file you normally edit
│   ├── utils.py       # helpers: .env loading, Swedish date parsing
│   ├── extract.py     # calendar extraction logic
│   ├── bill.py        # billing entry logic
│   ├── keys.py        # Seam access codes + email delivery
│   └── daily.py       # production pipeline orchestrator
├── tests/
│   └── test_billing.py
├── Dockerfile
├── README.md
└── pyproject.toml
```
