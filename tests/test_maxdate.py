"""Unit tests for lyra.maxdate — date arithmetic and picker parsing."""

from datetime import date

import pytest

from lyra.maxdate import (
    _format_picker_date,
    _needs_update,
    _one_year_ahead,
    _parse_picker_date,
    _read_current,
)

# ---------------------------------------------------------------------------
# _one_year_ahead
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 9, 17), date(2027, 9, 17)),
        (date(2026, 1, 1), date(2027, 1, 1)),
        (date(2026, 12, 31), date(2027, 12, 31)),
        (date(2027, 2, 28), date(2028, 2, 28)),
        (date(2027, 3, 1), date(2028, 3, 1)),
        # relativedelta clamps Feb 29 to Feb 28 in a non-leap target year.
        # Pinned here so a dependency bump that changed the behaviour would
        # fail the suite rather than silently shift the booking horizon.
        (date(2028, 2, 29), date(2029, 2, 28)),
        (date(2096, 2, 29), date(2097, 2, 28)),  # century rule
    ],
)
def test_one_year_ahead(today, expected):
    assert _one_year_ahead(today) == expected


# ---------------------------------------------------------------------------
# _parse_picker_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2027/9/17", "2027-09-17"),
        ("2027/09/17", "2027-09-17"),
        (" 2027/9/17 ", "2027-09-17"),
        ("2027/12/1", "2027-12-01"),
        # Unparseable — treated as "no value" rather than crashing
        ("", None),
        ("garbage", None),
        ("2027", None),
        ("17/9/2027", None),  # year 17, day 2027 — out of range
        ("2027/2/30", None),
        ("2027/13/1", None),
    ],
)
def test_parse_picker_date(text, expected):
    assert _parse_picker_date(text) == expected


# ---------------------------------------------------------------------------
# _format_picker_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "iso, expected",
    [
        ("2027-09-17", "2027/9/17"),  # the widget's own format is unpadded
        ("2027-12-01", "2027/12/1"),
        ("2027-01-09", "2027/1/9"),
    ],
)
def test_format_picker_date(iso, expected):
    assert _format_picker_date(iso) == expected


def test_format_and_parse_round_trip():
    """The widget's format must survive a parse/format round trip."""
    for iso in ("2027-09-17", "2027-12-01", "2027-01-09"):
        assert _parse_picker_date(_format_picker_date(iso)) == iso


# ---------------------------------------------------------------------------
# _needs_update — the "never move backwards" contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "current, target, expected",
    [
        (None, "2027-09-17", True),  # empty field
        ("2027-09-16", "2027-09-17", True),  # one day behind
        ("2026-09-17", "2027-09-17", True),  # a year behind (catch-up)
        ("2027-09-17", "2027-09-17", False),  # already correct
        ("2027-09-18", "2027-09-17", False),  # ahead — left alone
        ("2029-01-01", "2027-09-17", False),  # far ahead — left alone
    ],
)
def test_needs_update(current, target, expected):
    assert _needs_update(current, target) is expected


# ---------------------------------------------------------------------------
# _read_current — stub field, no browser
# ---------------------------------------------------------------------------


class _FakeElement:
    def __init__(self, text):
        self._text = text

    def text_content(self):
        return self._text


class _FakeField:
    """Stands in for the ``.form-group.date-fieldtype`` locator.

    ``_read_current`` only ever calls ``locator(".dr-date")`` on it, so the
    stub returns itself for that selector.
    """

    def __init__(self, texts: list[str | None]):
        self._texts = texts

    def locator(self, selector: str):
        assert selector == ".dr-date"
        return self

    def count(self) -> int:
        return len(self._texts)

    @property
    def first(self):
        return _FakeElement(self._texts[0])


def test_read_current_parses_displayed_value():
    assert _read_current(_FakeField(["2027/9/17"])) == "2027-09-17"


def test_read_current_none_when_widget_absent():
    """An empty date field renders no .dr-date at all."""
    assert _read_current(_FakeField([])) is None


def test_read_current_none_when_display_is_blank():
    assert _read_current(_FakeField([""])) is None


def test_read_current_none_when_display_is_unparseable():
    assert _read_current(_FakeField(["not a date"])) is None


def test_read_current_ignores_none_text():
    assert _read_current(_FakeField([None])) is None
