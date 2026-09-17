"""Keep the Smart Brf maximum booking date one year ahead of today.

The guest apartment carries a *fixed* maximum booking date ("Öppet för
bokning t.o.m.") in the Statamic admin panel, so the bookable window shrinks
every day unless it is moved forward.  This module logs into the admin panel,
reads the stored date, and rewrites it to ``today + MAX_BOOKING_YEARS``.

In steady state the stored value is already yesterday + 1 year, so the target
is one day further along.  The technique does not care about the size of the
delta, so a field that has fallen far behind — skipped runs, a failed run, or
someone resetting it — catches up in a single run.

Findings from the reconnaissance run (``recon_maxdate.py``):

* The admin panel has its own Grannskap SSO login.  It has two shapes: a
  fresh browser context gets the credential form, while one that already
  holds a Grannskap session — always the case in ``run_daily``, where Phase 1
  logged into the public site first — gets an account chooser instead.
* There are two scalar ``date`` fields, distinguished only by their label:
  "Öppet för bokning fr.o.m." (minimum) and "Öppet för bokning t.o.m."
  (maximum — the one this module moves).
* The value is displayed by a Baremetrics Calendar widget as a
  ``<div class="dr-date" contenteditable>`` in unpadded ``YYYY/M/D`` form.
  It has **no hidden input** — the widget's value is serialised by the form
  on save, so the display text is the only readable source.
* Typed text must be committed with Enter; Escape reverts to the stored
  value.  ``.dr-date`` must be clicked first, because the widget only
  populates its internal selection on click.
"""

import logging
from datetime import date

from dateutil.relativedelta import relativedelta
from playwright.sync_api import Dialog, Locator, Page, Playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from . import launch_browser
from .config import (
    ADMIN_LOGIN_URL,
    DRY_RUN,
    LYRA_EMAIL,
    LYRA_PASSWORD,
    MAX_BOOKING_YEARS,
    validate,
)

log = logging.getLogger(__name__)

# The maximum booking date.  Both date fields share the same markup, so the
# label is the only thing that tells them apart.
MAX_FIELD_LABEL = "Öppet för bokning t.o.m."

_FIELD_GROUP = ".form-group.date-fieldtype"

# Statamic's i18n key ``add_date``.  It renders only while a date field is
# empty, in which case the widget has to be created before it can be driven.
_ADD_DATE_LABEL = "Lägg till datum"

# Bounded so a stuck login or save fails inside the CI job's 15-minute budget
# with a diagnosable message, rather than on Playwright's 30 s default.
# Mirrors _SAVE_TIMEOUT_MS in bill.py.
_LOGIN_TIMEOUT_MS = 20_000
_SUBMIT_TIMEOUT_MS = 5_000
_SAVE_TIMEOUT_MS = 15_000


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _one_year_ahead(day: date) -> date:
    """Return *day* advanced by ``MAX_BOOKING_YEARS`` years.

    ``relativedelta`` clamps Feb 29 to Feb 28 when the target year is not a
    leap year, which is the behaviour we want — the horizon must never move
    backwards relative to the previous day's run.
    """
    return day + relativedelta(years=MAX_BOOKING_YEARS)


def _parse_picker_date(text: str) -> str | None:
    """Convert the widget's ``2027/9/17`` display to ISO 8601.

    Returns ``None`` if the text is not a real calendar date, so a blank or
    malformed field is treated as "no value" rather than crashing.
    """
    parts = text.strip().split("/")
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(p) for p in parts)
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _format_picker_date(iso: str) -> str:
    """Convert an ISO date to the widget's unpadded ``YYYY/M/D`` form."""
    year, month, day = iso.split("-")
    return f"{int(year)}/{int(month)}/{int(day)}"


def _needs_update(current: str | None, target: str) -> bool:
    """Return ``True`` when the stored value is missing or behind *target*.

    ISO 8601 strings compare lexicographically, as elsewhere in this project.
    A value *ahead* of the target is deliberately left alone: a wider booking
    window is harmless, whereas moving the date backwards could invalidate
    bookings residents have already made.
    """
    return current is None or current < target


# ---------------------------------------------------------------------------
# Page helpers
# ---------------------------------------------------------------------------


def _login_admin(page: Page) -> None:
    """Log in to the Statamic admin panel via its Grannskap SSO.

    Two shapes have to be handled, because the panel is reached from
    different starting states:

    * a *fresh* browser context gets the Grannskap credential form;
    * a context that already holds a Grannskap session — which is always the
      case in ``run_daily``, where Phase 1 logged into the public site first —
      gets an account chooser instead, listing the account as a button.

    Both paths end on ``/admin``, which is the only thing verified here.
    """
    page.goto(ADMIN_LOGIN_URL)
    page.wait_for_load_state("networkidle")

    login_link = page.get_by_role("link", name="Logga in med Grannskap")
    if login_link.count():
        login_link.first.click()
        page.wait_for_load_state("networkidle")

        # The Grannskap page settles into one of the two shapes above.  Poll
        # for either rather than guessing which, since the redirect chain
        # gives no reliable completion signal.
        email = page.get_by_role("textbox", name="Din e-postadress")
        account = page.locator("button", has_text="@")
        for _ in range(20):
            if email.count() or account.count():
                break
            page.wait_for_timeout(500)

        if email.count():
            email.first.fill(LYRA_EMAIL)
            email.first.press("Tab")
            page.get_by_role("textbox", name="Ditt lösenord").first.fill(LYRA_PASSWORD)
            page.get_by_role("textbox", name="Ditt lösenord").first.press("Enter")

            submit = page.get_by_role("button", name="Logga in")
            if submit.count():
                try:
                    # Pressing Enter usually submits already, which navigates
                    # away and detaches the button.  The redirect check below
                    # is the real verification, so a failure here is not fatal.
                    submit.first.click(timeout=_SUBMIT_TIMEOUT_MS)
                except PlaywrightTimeoutError:
                    log.debug("  'Logga in' click was not needed")
        elif account.count():
            # Log which account, so an unexpected one is visible in the log.
            # text_content(), not inner_text() — the latter returns "" for
            # these clipped elements (same quirk as extract.py's calendar).
            log.info(
                "  Grannskap session already exists — picking %r",
                (account.first.text_content() or "").strip(),
            )
            account.first.click()
        else:
            raise RuntimeError(
                "Login to the Smart Brf admin panel failed — neither the "
                "Grannskap credential form nor an account chooser appeared."
            )

    try:
        page.wait_for_url("**/admin/**", timeout=_LOGIN_TIMEOUT_MS)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(
            "Login to the Smart Brf admin panel failed — did not return to "
            "/admin. Check LYRA_EMAIL / LYRA_PASSWORD in .env."
        ) from exc
    page.wait_for_load_state("networkidle")
    log.info("  Admin session ready (%s)", page.url)


def _accept_beforeunload(dialog: Dialog) -> None:
    """Accept the beforeunload prompt raised by an edited admin form.

    Navigating away from a dirty form raises one, and without a handler the
    verification re-read could stall until its timeout.
    """
    log.debug("  dialog: type=%s message=%r", dialog.type, dialog.message)
    dialog.accept()


def _open_entry(page: Page) -> None:
    """Open the Gästlägenheten entry the way a user would.

    The CP deep link is not reliable, so navigate through the sidebar:
    Bokning → Gästlägenheten.  Note the ``Bokning`` link's accessible name
    really does begin with a space.
    """
    bokning = page.get_by_role("link", name=" Bokning")
    if not bokning.count():
        bokning = page.get_by_role("link", name="Bokning")
    if not bokning.count():
        raise RuntimeError(
            "Could not find the 'Bokning' link in the admin sidebar — "
            "the admin navigation may have changed."
        )
    bokning.first.click()
    page.wait_for_load_state("networkidle")

    gast = page.get_by_role("link", name="Gästlägenheten")
    if not gast.count():
        raise RuntimeError(
            "Could not find the 'Gästlägenheten' link under Bokning — "
            "the collection listing may have changed."
        )
    gast.first.click()
    page.wait_for_load_state("networkidle")


def _max_date_field(page: Page) -> Locator:
    """Return the ``Öppet för bokning t.o.m.`` field group.

    The two date fields share their markup, so the label is what identifies
    the right one.
    """
    field = page.locator(_FIELD_GROUP).filter(has_text=MAX_FIELD_LABEL)
    if not field.count():
        raise RuntimeError(
            f"Max booking date field {MAX_FIELD_LABEL!r} not found on the "
            f"Gästlägenheten entry ({page.url}) — the admin form may have "
            f"changed."
        )
    return field.first


def _read_current(field: Locator) -> str | None:
    """Read the field's displayed date as ISO 8601, or ``None`` if empty."""
    dr_date = field.locator(".dr-date")
    if not dr_date.count():
        return None
    return _parse_picker_date(dr_date.first.text_content() or "")


def _set_date(field: Locator, target: str) -> str | None:
    """Type *target* into the picker and commit it with Enter.

    Returns what the widget shows afterwards, which the caller must compare
    against *target* before saving — the widget clamps to its own
    ``earliest_date``/``latest_date`` and can replace a value silently.
    """
    add = field.get_by_role("button", name=_ADD_DATE_LABEL)
    if add.count():
        log.info("    Field is empty — clicking %r first", _ADD_DATE_LABEL)
        add.first.click()
        created = field.locator(".dr-date").first
        created.wait_for(state="visible", timeout=_SAVE_TIMEOUT_MS)

    dr_date = field.locator(".dr-date").first
    # Click first: the widget only sets its internal selection on click, and
    # Enter without it would silently write today's date instead.
    dr_date.click()
    dr_date.fill(_format_picker_date(target))
    dr_date.press("Enter")
    return _read_current(field)


def _log_save_failure(page: Page, save: Locator) -> None:
    """Log why the *Spara* click could not proceed.

    There is no screenshot/trace capture anywhere in this project, so this is
    the only way to tell the failure modes apart from a CI log.
    """
    log.error(
        "    Spara click timed out — %d matching button(s), url=%s",
        save.count(),
        page.url,
    )
    for i in range(min(save.count(), 5)):
        btn = save.nth(i)
        log.error(
            "      [%d] text=%r visible=%s enabled=%s",
            i,
            btn.inner_text()[:40],
            btn.is_visible(),
            btn.is_enabled(),
        )


def _save(page: Page) -> None:
    """Click *Spara* and wait for the form to settle."""
    save = page.get_by_role("button", name="Spara")
    if not save.count():
        raise RuntimeError(
            "No 'Spara' button found — cannot save the max booking date. "
            "The admin form may have changed."
        )
    try:
        save.first.click(timeout=_SAVE_TIMEOUT_MS)
        page.wait_for_load_state("networkidle")
    except PlaywrightTimeoutError:
        _log_save_failure(page, save)
        raise


def _ensure_max_date(page: Page) -> None:
    """Read the maximum booking date and move it forward when it is behind.

    A no-op when the stored value already matches the target, so re-running
    the same day is safe.
    """
    # A dirty form raises a beforeunload prompt when navigating away; accept
    # it so the verification re-read below cannot hang.
    page.on("dialog", _accept_beforeunload)

    _login_admin(page)
    _open_entry(page)

    field = _max_date_field(page)
    current = _read_current(field)
    target = _one_year_ahead(date.today()).isoformat()
    log.info(
        "  Max booking date: %s  (target %s)",
        current or "<empty>",
        target,
    )

    if not _needs_update(current, target):
        if current == target:
            log.info("  SKIP: already %s", target)
        else:
            log.warning(
                "  SKIP: %s is ahead of the %d-year target — leaving it "
                "(the date is never moved backwards)",
                current,
                MAX_BOOKING_YEARS,
            )
        return

    if DRY_RUN:
        log.warning(
            "  DRY RUN: would set max booking date %s → %s",
            current or "<empty>",
            target,
        )
        return

    log.info("  Setting: %s → %s", current or "<empty>", target)
    shown = _set_date(field, target)
    if shown != target:
        raise RuntimeError(
            f"Max booking date did not take: typed {target}, but the picker "
            f"shows {shown!r}. Nothing was saved — the admin widget may have "
            f"changed."
        )

    _save(page)

    # Re-read from the server: navigating away and back is the only proof the
    # write persisted, and it needs no knowledge of any success indicator.
    _open_entry(page)
    persisted = _read_current(_max_date_field(page))
    if persisted != target:
        raise RuntimeError(
            f"Max booking date did not persist: expected {target}, but the "
            f"page shows {persisted!r} after saving."
        )
    log.info("  Saved — verified after reload: %s", persisted)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_maxdate(playwright: Playwright) -> None:
    """Move the Smart Brf maximum booking date ``MAX_BOOKING_YEARS`` ahead."""
    validate("LYRA_EMAIL", "LYRA_PASSWORD")
    context, page = launch_browser(playwright)
    try:
        _ensure_max_date(page)
    finally:
        context.close()
