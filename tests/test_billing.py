"""Unit tests for billing.py utility functions."""

import pytest

from lyra.bill import (
    _find_best_match,
    _is_board_booking,
    _levenshtein,
    _name_distance,
    _parse_lgh,
    _parse_option,
)

# ---------------------------------------------------------------------------
# _parse_lgh
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lgh, expected",
    [
        # 5+ digits — returns (prefix, ALL digits) for precise matching
        ("8-1301", ("8", "81301")),
        ("7-1002", ("7", "71002")),
        ("07-1501", ("7", "071501")),
        ("81201", ("8", "81201")),
        ("51305", ("5", "51305")),
        ("71105", ("7", "71105")),
        # Exactly 4 digits — returns (None, last4), no prefix available
        ("1302", (None, "1302")),
        ("1105", (None, "1105")),
        ("1005", (None, "1005")),
        ("6-102", (None, "6102")),  # 4 digits after stripping, no prefix
        # <4 digits or non-numeric — name-only fallback
        ("Styrelsen", None),
        ("", None),
        ("123", None),
    ],
)
def test_parse_lgh(lgh, expected):
    assert _parse_lgh(lgh) == expected


# ---------------------------------------------------------------------------
# _parse_option
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected_number, expected_names",
    [
        (
            "Lund Pentagonen 3-51001, Street 57 (Alice Andersson)",
            "3-51001",
            "Alice Andersson",
        ),
        (
            "Lund Pentagonen 3-61002, Street 55 (Bob Builder, Carol Cool)",
            "3-61002",
            "Bob Builder, Carol Cool",
        ),
        (
            "Lund Pentagonen 3-51003, Street 57 (Dave Dev, Eve Edge, Frank Foo)",
            "3-51003",
            "Dave Dev, Eve Edge, Frank Foo",
        ),
        (
            "Lund Pentagonen 3-51104, Street 57",
            "3-51104",
            "",
        ),
        (
            "Lund Pentagonen 3-61105, Street 55 (Grace Green)",
            "3-61105",
            "Grace Green",
        ),
        (
            "Town Centrum 4-71202, Other Street 10 (Henry Hill)",
            "4-71202",
            "Henry Hill",
        ),
    ],
)
def test_parse_option(text, expected_number, expected_names):
    assert _parse_option(text) == (expected_number, expected_names)


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_identical_strings(self):
        assert _levenshtein("Alice Andersson", "Alice Andersson") == 0

    def test_case_insensitive(self):
        assert _levenshtein("Alice Andersson", "alice andersson") == 0

    def test_name_change_last_name(self):
        """Last name changed (e.g. marriage) — should have small distance."""
        dist = _levenshtein("First Frost", "First Friberg")
        assert 0 < dist < 10

    def test_completely_different(self):
        assert _levenshtein("Foo", "Bar") == 3

    def test_empty_vs_string(self):
        assert _levenshtein("", "abc") == 3

    def test_string_vs_empty(self):
        assert _levenshtein("abc", "") == 3

    def test_both_empty(self):
        assert _levenshtein("", "") == 0

    @pytest.mark.parametrize(
        "a, b, expected",
        [
            ("cat", "cats", 1),
            ("cats", "cat", 1),
            ("cat", "cut", 1),
        ],
    )
    def test_single_edit(self, a, b, expected):
        assert _levenshtein(a, b) == expected

    def test_realistic_name_variation(self):
        """Distance between two plausible name variants."""
        dist = _levenshtein("Eva Martensson", "Eva Maartensson")
        assert dist > 0

    def test_shorter_vs_longer(self):
        assert _levenshtein("Foo Bar", "Foo Bar Baz") == 4


# ---------------------------------------------------------------------------
# _name_distance
# ---------------------------------------------------------------------------


class TestNameDistance:
    def test_single_name_exact_match(self):
        assert _name_distance("Alice Andersson", "Alice Andersson") == 0

    def test_single_name_close(self):
        assert _name_distance("Alice Andersson", "Alice Anderrson") == 1

    def test_multi_occupant_first_matches(self):
        """CSV name matches the first occupant exactly."""
        assert _name_distance("Alice A", "Alice A, Bob B") == 0

    def test_multi_occupant_second_matches(self):
        """CSV name matches the second occupant exactly."""
        assert _name_distance("Bob B", "Alice A, Bob B") == 0

    def test_multi_occupant_neither_matches(self):
        """CSV name doesn't match any occupant — returns min distance."""
        dist = _name_distance("Carol C", "Alice A, Bob B")
        assert dist >= 5  # far from both names

    def test_empty_names_returns_large_value(self):
        assert _name_distance("Alice", "") == 999

    def test_case_insensitive(self):
        assert _name_distance("alice andersson", "Alice Andersson") == 0


# ---------------------------------------------------------------------------
# _find_best_match (mocked page)
# ---------------------------------------------------------------------------


class _FakeOption:
    """Minimal stub of a Playwright Locator element."""

    def __init__(self, value: str, text: str):
        self._value = value
        self._text = text

    def get_attribute(self, _name: str) -> str:
        return self._value

    def inner_text(self) -> str:
        return self._text


def _page_with_options(mocker, options: list[tuple[str, str]]):
    """Return a mocked Playwright ``page`` whose ``[data-test="form-select"]
    option`` locator yields *options* as ``(value, text)`` tuples."""
    fake_opts = [_FakeOption(v, t) for v, t in options]
    locator = mocker.Mock()
    locator.all.return_value = fake_opts
    page = mocker.Mock()
    page.locator.return_value = locator
    return page


class TestFindBestMatch:
    """Tests for _find_best_match using a mocked Playwright page."""

    # Mode A — full digit match with prefix --------------------------------

    def test_prefix_match_preferred(self, mocker):
        """When two options share the same digits, the one with matching
        prefix is selected even if its name distance is slightly worse."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice A)"),
                ("2", "Area 3-71301, Street 55 (Alice Andersson)"),
            ],
        )
        # "8-1301" → digits "81301", prefix "8"
        result = _find_best_match(page, "Alice Andersson", "8-1301")
        assert result is not None
        value, _text = result
        # "3-81301" has prefix "8" at position -5, should be selected
        assert value == "1"

    def test_full_digits_filter_out_wrong_building(self, mocker):
        """An option whose last 4 match but full digits don't is excluded."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-71301, Street 55 (Alice A)"),
            ],
        )
        # "8-1301" → digits "81301".  "3-71301" ends with "1301" but
        # not "81301" — should be excluded by the full-digit filter.
        result = _find_best_match(page, "Alice A", "8-1301")
        assert result is None

    # Mode B — 4-digit match (no prefix) ----------------------------------

    def test_four_digit_single_candidate(self, mocker):
        """A 4-digit number with exactly one matching option is selected."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-1005, Street 42 (Rebecka af Forselles)"),
            ],
        )
        result = _find_best_match(page, "Rebecka af Forselles", "1005")
        assert result is not None
        value, _text = result
        assert value == "1"

    def test_four_digit_multiple_candidates_picks_best_name(self, mocker):
        """With multiple last4 matches, the best name distance wins."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-1005, Street 42 (Some Other)"),
                ("2", "Area 3-1005, Street 43 (Rebecka af Forselles)"),
            ],
        )
        result = _find_best_match(page, "Rebecka af Forselles", "1005")
        assert result is not None
        value, _text = result
        assert value == "2"

    def test_four_digit_no_candidate(self, mocker):
        """No option ends with the 4-digit number."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-9999, Street 42 (Alice A)"),
            ],
        )
        result = _find_best_match(page, "Alice A", "1005")
        assert result is None

    # Mode C — name-only fallback -----------------------------------------

    def test_name_only_exact_match(self, mocker):
        """Exact name match finds the right apartment."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice Andersson)"),
            ],
        )
        result = _find_best_match(page, "Alice Andersson", "Styrelsen")
        assert result is not None
        value, _text = result
        assert value == "1"

    def test_name_only_within_threshold(self, mocker):
        """A name with a small typo (dist ≤ 5) is still matched."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice Andersson)"),
            ],
        )
        # "Alice Anderrson" has dist 1 from "Alice Andersson"
        result = _find_best_match(page, "Alice Anderrson", "Styrelsen")
        assert result is not None

    def test_name_only_exceeds_threshold(self, mocker):
        """A completely different name (dist > 5) is rejected."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice Andersson)"),
            ],
        )
        result = _find_best_match(page, "Bob Builder", "Styrelsen")
        assert result is None

    def test_name_only_no_name_in_csv(self, mocker):
        """Empty CSV name cannot be matched."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice Andersson)"),
            ],
        )
        result = _find_best_match(page, "", "Styrelsen")
        assert result is None

    def test_name_only_multi_occupant(self, mocker):
        """Match against one of multiple occupants in the option."""
        page = _page_with_options(
            mocker,
            [
                ("1", "Area 3-81301, Street 57 (Alice A, Bob B)"),
            ],
        )
        result = _find_best_match(page, "Bob B", "Styrelsen")
        assert result is not None
        value, _text = result
        assert value == "1"


# ---------------------------------------------------------------------------
# _is_board_booking
# ---------------------------------------------------------------------------


class TestIsBoardBooking:
    @pytest.mark.parametrize(
        "lgh",
        [
            "Styrelsen",
            "styrelsen",
            "STYRELSEN",
            "Styrelsen ",
            "Brf Styrelsen",
            "styrelsen 123",
            "Ordförande Styrelsen",
        ],
    )
    def test_board_booking_detected(self, lgh):
        assert _is_board_booking(lgh) is True

    @pytest.mark.parametrize(
        "lgh",
        [
            "8-1301",
            "1005",
            "6102",
            "",
            "1301",
        ],
    )
    def test_normal_booking_not_board(self, lgh):
        assert _is_board_booking(lgh) is False
