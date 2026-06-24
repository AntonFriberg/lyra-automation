"""Unit tests for lyra.config — validation helper."""

import pytest

import lyra.config as config_module
from lyra.config import validate


def test_validate_passes_when_all_present(monkeypatch):
    """Should not raise when all required vars are non-empty."""
    monkeypatch.setattr(config_module, "LYRA_EMAIL", "test@ex.com")
    monkeypatch.setattr(config_module, "LYRA_PASSWORD", "secret")
    validate("LYRA_EMAIL", "LYRA_PASSWORD")


def test_validate_raises_when_missing():
    """Should raise RuntimeError with a clear message."""
    with pytest.raises(RuntimeError, match="Missing required env vars"):
        validate("THIS_VAR_DOES_NOT_EXIST")


def test_validate_lists_all_missing():
    with pytest.raises(RuntimeError) as exc:
        validate("MISSING_A", "MISSING_B")
    msg = str(exc.value)
    assert "MISSING_A" in msg
    assert "MISSING_B" in msg


def test_validate_only_checks_requested_keys(monkeypatch):
    """validate(…) should only check the keys it's given, nothing more."""
    monkeypatch.setattr(config_module, "GMAIL_USER", "sender@ex.com")
    validate("GMAIL_USER")  # no error


def test_validate_empty_string_counts_as_missing(monkeypatch):
    """An empty config value should trigger the error."""
    # Simulate an empty env var
    monkeypatch.setattr(config_module, "LYRA_EMAIL", "")
    with pytest.raises(RuntimeError, match="LYRA_EMAIL"):
        validate("LYRA_EMAIL")
