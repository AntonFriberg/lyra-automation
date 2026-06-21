# Code Review — lyra-automation (2026-06-21)

## Quick summary

Well-structured, single-purpose automation with clean module separation. The
highest-priority concerns: duplicated DOM-interaction logic in 3 places, no
login verification, print-based logging, and ~90% of code untested. The
packaging, README, and CI workflow are already solid.

---

## Findings by dimension

### 1. Error handling & resilience

**🔴 High — No login verification.**
Every `_login()` function navigates and fills forms but never checks whether
login succeeded. Wrong credentials or an error page cause confusing
Playwright timeouts much later.
- `extract.py:27` (Smart Brf)
- `bill.py:180` (JM Home)
- Fix: after login, wait for a known post-login element (e.g. the calendar
  grid, the apartment dropdown) and raise `RuntimeError("Login failed")` on
  timeout.

**🔴 High — No retry logic for Seam API calls.**
`keys.py:244` and `daily.py:244` wrap Seam access code creation in bare
`except Exception` that prints and silently continues. A transient network
failure or rate limit is never retried.
- Fix: retry 3× with exponential backoff (e.g. `tenacity` or manual loop).

**🟡 Medium — `_latest_billed_date` uses brittle string prefix stripping.**
`bill.py:175` assumes the table cell starts with `BILLING_AVITEXT` followed by
a space and date. If JM Home changes the format, the function silently
returns `"0000-00-00"`, causing every booking to be re-billed.
- Fix: use a regex to extract the date, log a warning if format is unexpected.

**🟡 Medium — Email delivery is fire-and-forget.**
`keys.py:147` calls `server.send_message(msg)` with no delivery check. A
soft bounce is silently treated as success.
- Fix: log the SMTP response code after send.

**🟢 Low — `run_upcoming` missing `# noqa: C901`.**
`extract.py:188` has similar complexity to `run_extract` (which has it).

### 2. Logging

**🟡 Medium — `print()` for everything, no log levels.**
No timestamps, no levels, all output to stdout. A silent failure at 7 AM
leaves no structured trail to diagnose.
- Fix: use `logging.getLogger(__name__)` with `INFO`/`WARNING`/`ERROR`.
  The `daily` pipeline especially benefits from knowing which phase failed.

**🟢 Low — Errors go to stdout.**
`bill.py:208` prints `ERROR:` to stdout. Should go to stderr.

### 3. Configuration & environment management

**🔴 High — Required env vars raise `KeyError` at import time.**
`config.py:6-7` uses `os.environ["LYRA_EMAIL"]`. Because `__init__.py`
imports config at module level, a missing env var breaks the entire package
on import — even for commands that don't need those vars (e.g. `keys` only
needs `SEAM_API_KEY`).
- Fix: use `os.environ.get("KEY")` for credentials, validate lazily in
  each command function, or print a helpful message on `KeyError`.

**🟡 Medium — Mixed hardcoded values and env-var sourcing.**
`NUM_MONTHS = 10`, `BILLING_AMOUNT = "350"`, `SENDER_NAME = "Anton Frost"`,
`LOCK_NAME = "guest_apartment"` are hardcoded. Cannot be changed without a
code deploy.
- Fix: source from env vars with sensible defaults.

**🟡 Medium — `HEADLESS` default is `False`.**
`config.py:10` defaults to `False`, but Dockerfile and CI both set it to
`true`. A local `uv run lyra daily` opens a visible browser.
- Fix: default to `True`; set `HEADLESS=false` locally when debugging.

### 4. Code quality & consistency

**🔴 High — Modal extraction logic duplicated in three places.**
The block that clicks a booking, reads modal fields, and closes the modal is
copy-pasted in:
1. `extract.py:116-148` (inside `run_extract`)
2. `extract.py:222-253` (inside `run_upcoming`)
3. `daily.py:56-90` (standalone `_extract_booking`)
A DOM fix must be applied in all three places.
- Fix: export one `_extract_booking(page, index) -> dict` from `extract.py`
  and call it from all three sites. Remove the inline copies.

**🟡 Medium — Billing in `daily.py` has no standalone `DRY_RUN` guard.**
`daily.py:195-198` exits before Phase 3 when `DRY_RUN` is set, so Phase 4
is never reached. But if the phases are ever reordered, billing could skip
the dry-run check.
- Fix: add an explicit `if DRY_RUN: return` guard before Phase 4.

**🟡 Medium — `_parse_lgh` edge case for short apartment numbers.**
`"6-102"` has 4 digits total, but the prefix extraction `digits[-5]` is out
of bounds. The function returns `("", "6102")` — likely unintended.
- Fix: document whether `6-102` is valid input; if not, return `None`.

**🔴 High — No linting or formatting configuration.**
No `[tool.ruff]` in `pyproject.toml`. Inconsistent formatting across modules.
- Fix: add `ruff` as dev dependency, configure `[tool.ruff]`, run once.

### 5. Testing

**🔴 High — 90% of codebase untested.**
Only `_parse_lgh`, `_parse_option`, and `_levenshtein` have tests. Zero
coverage for: `parse_swedish_date`, `_group_stays`, `_compute_times`,
`_send_email`, any Playwright logic, `run_daily`, `run_keys`, `run_extract`.

**🔴 High — No mocking fixtures.**
`conftest.py` only adds to `sys.path`. No fixtures for mock Playwright
pages, Seam client, SMTP, or temp CSV files.
- Fix: add `pytest-mock`, provide mock `Page` fixture, use `tmp_path` for CSVs.

**🟡 Medium — `parse_swedish_date` untested despite critical path.**
- Fix: parametrized tests for all 12 months, edge cases, invalid input.

### 6. Idempotency & safety

**🟡 Medium — Seam code name could collide.**
`keys.py:232` uses `f"Gästlägenhet: {name} ({start_date})"`. Same person,
same date, different apartment → name collision → second code skipped.
- Fix: include `lagenhetsnummer` in the code name.

**🟢 Low — Billing cutoff updated optimistically.** Safe — the entry is
saved before `cutoff_date` advances, so a crash after save is fine.

### 7. Playwright-specific patterns

**🟡 Medium — Brittle `wait_for_timeout(300)` used everywhere.**
`extract.py`, `bill.py`, `daily.py` all use fixed waits. These slow down
runs and fail under load.
- Fix: replace with `expect(locator).to_be_visible()` or explicit
  `wait_for(state="visible")` where possible.

**🟡 Medium — JS evaluation selectors are fragile.**
`document.querySelectorAll('a.unavailable')[idx]` returns `undefined`
silently if FullCalendar changes class names.
- Fix: check result of `page.evaluate(...)` and raise if None.

### 8. Docker & deployment

**🟡 Medium — No non-root user.** Container runs as root.
- Fix: `RUN useradd -m lyra && USER lyra`.

**🟡 Medium — COPY order workaround.** `touch lyra/__init__.py` trick is
fragile. Consider `UV_PROJECT_ENVIRONMENT` for decoupling.

### 9. GitHub Actions workflow

**🟡 Medium — Timeout may be tight.** `timeout-minutes: 10` could be
exceeded on cold cache with a slow portal.
- Fix: raise to 15 and add a comment.

**🟢 Low — No failure notification.** Only a red checkmark in Actions tab.
- Fix: add `if: failure()` step with email/webhook.

### 10. Developer experience

**🟡 Medium — `load_dotenv` reimplements python-dotenv.**
20 lines of custom parsing vs. `dotenv.load_dotenv()`. The custom version
fails on multi-line values and variable expansion.
- Fix: add `python-dotenv` as a dep.

**🟡 Medium — `_login` exported from two modules with same name.**
`daily.py` imports `_login as _login_smartbrf` and `_login as _login_jmhome`.
- Fix: rename at source to avoid confusion.

**🟢 Low — README says `NUM_MONTHS` default is `1`, code says `10`.**
**🟢 Low — `requires-python >= 3.13` is unnecessarily strict.**
The code only needs Python 3.9+ features. Could widen to `>=3.11`.

---

## Top 5 improvements

| # | What | Effort | Impact |
|---|---|---|---|
| 1 | Export shared `_extract_booking` from extract.py, remove duplicates | Small | Eliminates main source of copy-paste bugs |
| 2 | Add login verification after each `_login()` call | Small | Turns confusing timeouts into clear errors |
| 3 | Replace `print()` with `logging` | Medium | Parseable logs for diagnosing 7 AM failures |
| 4 | Add tests for `parse_swedish_date`, `_group_stays`, `_compute_times` + mock fixtures | Medium | Foundation for testing the rest |
| 5 | Source hardcoded constants from env vars | Small | Tunable without code deploy |

---

## What's already done well

- Clean module structure: `config` / `utils` / `extract` / `bill` / `keys` / `daily`
- `daily.py` shares one browser session across phases
- Idempotent by design: code name check, billing cutoff, CSV dedup
- Comprehensive README documents every subcommand and config entry
- Deterministic deps via `uv.lock` + `uv sync --frozen` in CI
- `DRY_RUN` mode for safe testing
- Parameterized pytest tests for billing helpers
- Docker layer caching + CI caching (uv + Playwright Chromium)
