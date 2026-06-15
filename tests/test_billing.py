"""Unit tests for billing.py utility functions."""

import pytest
from billing import _parse_lgh, _parse_option, _levenshtein


# ---------------------------------------------------------------------------
# _parse_lgh
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lgh, expected", [
    ("8-1301",   ("8", "1301")),
    ("7-1002",   ("7", "1002")),
    ("07-1501",  ("7", "1501")),
    ("81201",    ("8", "1201")),
    ("1302",     ("", "1302")),
    ("1105",     ("", "1105")),
    ("51305",    ("5", "1305")),
    ("71105",    ("7", "1105")),
    ("6-102",    ("", "6102")),
    ("Styrelsen", None),
    ("",          None),
    ("123",       None),
])
def test_parse_lgh(lgh, expected):
    assert _parse_lgh(lgh) == expected


# ---------------------------------------------------------------------------
# _parse_option
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected_number, expected_names", [
    (
        "Lund Pentagonen 3-51001, Street 57 (Alice Andersson)",
        "3-51001", "Alice Andersson",
    ),
    (
        "Lund Pentagonen 3-61002, Street 55 (Bob Builder, Carol Cool)",
        "3-61002", "Bob Builder, Carol Cool",
    ),
    (
        "Lund Pentagonen 3-51003, Street 57 (Dave Dev, Eve Edge, Frank Foo)",
        "3-51003", "Dave Dev, Eve Edge, Frank Foo",
    ),
    (
        "Lund Pentagonen 3-51104, Street 57",
        "3-51104", "",
    ),
    (
        "Lund Pentagonen 3-61105, Street 55 (Grace Green)",
        "3-61105", "Grace Green",
    ),
    (
        "Town Centrum 4-71202, Other Street 10 (Henry Hill)",
        "4-71202", "Henry Hill",
    ),
])
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

    @pytest.mark.parametrize("a, b, expected", [
        ("cat",  "cats", 1),
        ("cats", "cat",  1),
        ("cat",  "cut",  1),
    ])
    def test_single_edit(self, a, b, expected):
        assert _levenshtein(a, b) == expected

    def test_realistic_name_variation(self):
        """Distance between two plausible name variants."""
        dist = _levenshtein("Eva Martensson", "Eva Maartensson")
        assert dist > 0

    def test_shorter_vs_longer(self):
        assert _levenshtein("Foo Bar", "Foo Bar Baz") == 4
