# Maintainability Review — lyra-automation (2026-06-24)

Post-fix review after completing all 10 sections of the original REVIEW.md.
25 new findings across 6 dimensions.

---

## 1. Configuration & Secrets Management

**1.1 🟡 No validation of integer/boolean config values**
`lyra/config.py:41,43,75` — `NUM_MONTHS`, `DAILY_LOOKAHEAD`, `UPCOMING_DAYS` are cast from env vars without range validation. Negative or zero values produce silent no-op runs.
- Fix: add `_validate_ranges()` in `__init__.py` asserting min/max values.

**1.2 🟢 `BASE_URL` ends with `#` fragment**
`lyra/config.py:49` — Unclear if intentional for page routing or a copy-paste artifact. Add a comment.

**1.3 🟢 Config values lack type annotations**
`lyra/config.py:28-74` — Every constant is a bare assignment. Add `: str`, `: bool`, `: int`.

**1.4 🟢 `DRY_RUN` / `TEST_MODE` boolean semantics undocumented**
Only the literal string `true` (case-insensitive) activates them. Document in `.env.example`.

---

## 2. Code Structure & Module Responsibilities

**2.1 🔴 `daily.py` imports private functions from 3 modules**
`lyra/daily.py:17-45` — `_login_smartbrf`, `_collect_names`, `_extract_booking`, `_wait_for_calendar`, `_find_best_match`, `_latest_billed_date`, `_login_jmhome` are all underscore-prefixed (private) but imported across module boundaries. Changing any signature silently breaks the orchestrator.
- Fix: extract shared browser helpers into `lyra/_browser_actions.py` and import from there.

**2.2 🟡 Calendar-scanning loop duplicated in 3 places**
`lyra/extract.py:149-225`, `lyra/extract.py:233-315`, `lyra/daily.py:83-125` — near-identical month iteration, name collection, modal reading, dedup, and date filtering. Only navigation direction, month count, and date filter differ.
- Fix: extract `_scan_calendar(page, months, direction, date_filter)` into a shared helper.

**2.3 🟡 Billing entry creation duplicated between `bill.py` and `daily.py`**
`lyra/bill.py:297-321` and `lyra/daily.py:329-348` — ~25 lines of form-filling verbatim in both places.
- Fix: extract `_create_billing_entry(page, option_value, datum)` helper.

**2.4 🟡 Seam code listing + overlap check duplicated**
`lyra/keys.py:272-287` and `lyra/daily.py:187-201` — same `access_codes.list()` + date-range parsing + `except Exception` fallback.
- Fix: extract `_load_existing_code_ranges(seam, device_id)` helper in `keys.py`.

**2.5 🟡 `context.close()` never wrapped in `try/finally`**
All five `run_*` functions — if an exception is raised mid-body, the browser context is never closed. Chromium processes leak on errors.
- Fix: wrap each `run_*` body in `try: ... finally: context.close()`.

**2.6 🟢 `# noqa: C901` on all five orchestrator functions**
These suppress "too complex" linting rules. After extracting shared patterns, they can be removed.

---

## 3. Error Handling & Resilience

**3.1 🔴 No rollback when email fails after Seam code creation**
`lyra/keys.py:316-351`, `lyra/daily.py:230-264` — If SMTP fails, the code exists on the lock but the guest never receives it. Guest locked out unknowingly.
- Fix: send email first, then create code; or delete the code on email failure. At minimum, log an error-level message naming the affected guest.

**3.2 🟡 `parse_swedish_date` returns original string on failure**
`lyra/utils.py:23-35` — Unparseable dates are returned unchanged, causing downstream comparisons like `iso_date > str(date.today())` to produce wrong results silently.
- Fix: raise `ValueError` on parse failure, or return `""` and have callers skip the row.

**3.3 🟡 Seam `access_codes.list()` exceptions silently swallowed**
`lyra/keys.py:284-286`, `lyra/daily.py:199-201` — Any exception sets `existing_ranges = []`, causing all stays to be re-coded. Auth errors should be fatal.
- Fix: catch only transient network errors; re-raise on auth errors. Log full exception details.

**3.4 🟡 Dead `DRY_RUN` check before Phase 4 billing**
`lyra/daily.py:269-272` — Unreachable because Phase 3 already returns on DRY_RUN. Confusing to future readers.
- Fix: remove the dead block.

**3.5 🟢 `_latest_billed_date` sentinel `"0000-00-00"` undocumented**
`lyra/bill.py:203` — Relies on string comparison. Safe failure mode (over-bills rather than misses), but worth a comment.

---

## 4. Testability & CI

**4.1 🔴 ~70% of application code untested**
Zero tests for any Playwright-dependent function: `_login_smartbrf`, `_login_jmhome`, `_extract_booking`, `_wait_for_calendar`, `_collect_names`, `_find_best_match`, `_latest_billed_date`, `launch_browser`, and all five `run_*` orchestrators.
- Fix: add mock-based unit tests for `_find_best_match` (mock `page.locator(...).all()`), `_send_email` (mock `smtplib.SMTP`), and `_login_smartbrf` (verify sequence of Playwright calls).

**4.2 🟡 CI test workflow doesn't install Playwright Chromium**
`.github/workflows/test.yml` — Any test importing `launch_browser` breaks CI.
- Fix: add `uv run playwright install chromium` preemptively, or skip browser tests with `pytest.mark.playwright`.

**4.3 🟢 No pytest configuration in `pyproject.toml`**
Add `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and coverage settings.

---

## 5. Docker & Deployment

**5.1 🟢 Layer caching: source changes re-trigger `uv sync`**
`Dockerfile:16-20` — `COPY lyra/` before `uv sync` causes pip re-install on source changes even when deps are unchanged.
- Fix: split into dep-install step (with only `pyproject.toml` + `uv.lock`) then source-copy step.

**5.2 🟢 `.dockerignore` has redundant `*.md` exclusion**
Only `README.md` is copied; no other `.md` files exist. Simplify to explicit entries.

---

## 6. Developer Experience

**6.1 🟡 README describes Nix flake that doesn't exist**
`README.md:183-193` — "Deployment tools (Nix flake)" section references `nix develop` but `flake.nix` was removed.
- Fix: remove the section or re-add the flake.

**6.2 🟢 README caching docs are stale**
README says Chromium isn't cached, but `daily.yml` now caches it. Update to match.

**6.3 🟢 No "Testing" section in README**
Add: `uv sync --group dev && uv run pytest tests/ -q`.

**6.4 🟢 `_group_stays` parameter type is `list[dict]`**
`lyra/keys.py:76` — Should be `list[dict[str, str]]`.

---

## Summary

| Severity | Count |
|---|---|
| 🔴 High | 6 |
| 🟡 Medium | 9 |
| 🟢 Low | 10 |
| **Total** | **25** |

## Top 3 changes for best value/effort

1. **Extract shared browser patterns into `lyra/_browser_actions.py`** — addresses 6 findings (2.1–2.4, 2.6, 3.4) with one refactoring pass. The three calendar loops, billing entry creation, and Seam overlap check become shared helpers.

2. **`try/finally` for browser cleanup + `parse_swedish_date` hardening** — mechanical fix across 5 files (2.5, 3.2). Prevents process leaks and silent data corruption with zero risk.

3. **Add mock-based Playwright unit tests** — addresses 3 findings (4.1–4.3). Mock `Page`, `BrowserContext`, and `SMTP` to test `_find_best_match`, `_send_email`, and `_login` without a browser. Catches regressions from change #1.
