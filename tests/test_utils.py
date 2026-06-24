"""Unit tests for lyra.utils — pure helper functions."""

import os

import pytest

from lyra.utils import SV_MONTHS, load_dotenv, parse_swedish_date

# ---------------------------------------------------------------------------
# parse_swedish_date
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        # All 12 Swedish months
        ("1 januari 2026", "2026-01-01"),
        ("15 februari 2026", "2026-02-15"),
        ("31 mars 2026", "2026-03-31"),
        ("10 april 2026", "2026-04-10"),
        ("5 maj 2026", "2026-05-05"),
        ("20 juni 2026", "2026-06-20"),
        ("3 juli 2026", "2026-07-03"),
        ("12 augusti 2026", "2026-08-12"),
        ("25 september 2026", "2026-09-25"),
        ("7 oktober 2026", "2026-10-07"),
        ("14 november 2026", "2026-11-14"),
        ("24 december 2026", "2026-12-24"),
        # Single-digit days
        ("1 Juni 2026", "2026-06-01"),
        # Case insensitivity
        ("1 JUNI 2026", "2026-06-01"),
        ("1 juni 2026", "2026-06-01"),
        # Extra whitespace
        ("  1  Juni  2026  ", "2026-06-01"),
    ],
)
def test_parse_swedish_date_valid(text, expected):
    assert parse_swedish_date(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",  # empty
        "garbage",  # not a date
        "1 Smarch 2026",  # invalid month
        "2026-06-01",  # ISO format (not supported)
        "1",  # incomplete
        "Juni 2026",  # no day
    ],
)
def test_parse_swedish_date_invalid(text):
    assert parse_swedish_date(text) == text  # returns unchanged on failure


# ---------------------------------------------------------------------------
# load_dotenv
# ---------------------------------------------------------------------------


def test_load_dotenv_basic(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("KEY1=value1\nKEY2=value2\n")
    load_dotenv(dotenv)
    assert os.environ["KEY1"] == "value1"
    assert os.environ["KEY2"] == "value2"


def test_load_dotenv_skips_comments_and_blank(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("# comment\nKEY=value\n\n  \nANOTHER=123\n")
    load_dotenv(dotenv)
    assert os.environ["KEY"] == "value"
    assert os.environ["ANOTHER"] == "123"
    assert "comment" not in os.environ


def test_load_dotenv_strips_quotes(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("DOUBLE=\"hello\"\nSINGLE='world'\nNONE=plain\n")
    load_dotenv(dotenv)
    assert os.environ["DOUBLE"] == "hello"
    assert os.environ["SINGLE"] == "world"
    assert os.environ["NONE"] == "plain"


def test_load_dotenv_missing_file():
    """Should not raise if file doesn't exist."""
    load_dotenv("/nonexistent/path/.env")


def test_load_dotenv_skips_no_equals(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("NOEQUALS\nKEY=value\n")
    load_dotenv(dotenv)
    assert "NOEQUALS" not in os.environ
    assert os.environ["KEY"] == "value"


# ---------------------------------------------------------------------------
# SV_MONTHS (bundle check — ensures the dict is complete)
# ---------------------------------------------------------------------------


def test_sv_months_has_all_twelve():
    assert len(SV_MONTHS) == 12
    assert SV_MONTHS["januari"] == 1
    assert SV_MONTHS["december"] == 12
