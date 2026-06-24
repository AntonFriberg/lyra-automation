"""Unit tests for lyra.keys — grouping and time helpers."""

from datetime import datetime, timedelta

from lyra.keys import _compute_times, _group_stays

# ---------------------------------------------------------------------------
# _group_stays
# ---------------------------------------------------------------------------


def _booking(name, epost, datum, lgh="8-1301"):
    return {
        "name": name,
        "epost": epost,
        "datum": datum,
        "lagenhetsnummer": lgh,
        "telefon": "",
    }


def test_group_stays_single_night():
    bookings = [_booking("Alice Andersson", "alice@ex.com", "2026-06-20")]
    stays = _group_stays(bookings)
    assert len(stays) == 1
    assert stays[0]["start_date"] == "2026-06-20"
    assert stays[0]["end_date"] == "2026-06-20"
    assert stays[0]["nights"] == 1
    assert stays[0]["first_name"] == "Alice"


def test_group_stays_consecutive_nights_merged():
    bookings = [
        _booking("Bob Builder", "bob@ex.com", "2026-06-20"),
        _booking("Bob Builder", "bob@ex.com", "2026-06-21"),
        _booking("Bob Builder", "bob@ex.com", "2026-06-22"),
    ]
    stays = _group_stays(bookings)
    assert len(stays) == 1
    assert stays[0]["start_date"] == "2026-06-20"
    assert stays[0]["end_date"] == "2026-06-22"
    assert stays[0]["nights"] == 3


def test_group_stays_non_consecutive_not_merged():
    bookings = [
        _booking("Carol Cool", "carol@ex.com", "2026-06-20"),
        _booking("Carol Cool", "carol@ex.com", "2026-06-22"),
    ]
    stays = _group_stays(bookings)
    assert len(stays) == 2
    assert stays[0]["nights"] == 1
    assert stays[1]["nights"] == 1


def test_group_stays_different_emails_not_merged():
    bookings = [
        _booking("Dave Dev", "dave@ex.com", "2026-06-20"),
        _booking("Dave Dev", "eve@ex.com", "2026-06-21"),
    ]
    stays = _group_stays(bookings)
    assert len(stays) == 2


def test_group_stays_mixed_guests():
    bookings = [
        _booking("Alice", "alice@ex.com", "2026-06-20"),
        _booking("Bob", "bob@ex.com", "2026-06-20"),
        _booking("Alice", "alice@ex.com", "2026-06-21"),
    ]
    stays = _group_stays(bookings)
    assert len(stays) == 2
    # Alice has 2 nights
    alice = [s for s in stays if s["first_name"] == "Alice"][0]
    assert alice["nights"] == 2
    assert alice["start_date"] == "2026-06-20"
    assert alice["end_date"] == "2026-06-21"


def test_group_stays_sorted_input_respected():
    """Out-of-order input is sorted before grouping."""
    bookings = [
        _booking("Zelda", "z@ex.com", "2026-06-22"),
        _booking("Zelda", "z@ex.com", "2026-06-20"),
        _booking("Zelda", "z@ex.com", "2026-06-21"),
    ]
    stays = _group_stays(bookings)
    assert len(stays) == 1
    assert stays[0]["nights"] == 3


# ---------------------------------------------------------------------------
# _compute_times
# ---------------------------------------------------------------------------


def test_compute_times_single_night():
    stay = {"start_date": "2026-06-20", "end_date": "2026-06-20", "nights": 1}
    start, end = _compute_times(stay)
    assert start == datetime(2026, 6, 20, 15, 0).replace(tzinfo=start.tzinfo)
    assert end == datetime(2026, 6, 21, 12, 0).replace(tzinfo=end.tzinfo)


def test_compute_times_multi_night():
    stay = {"start_date": "2026-06-20", "end_date": "2026-06-22", "nights": 3}
    start, end = _compute_times(stay)
    assert start == datetime(2026, 6, 20, 15, 0).replace(tzinfo=start.tzinfo)
    # Checkout is the day after the last night
    assert end == datetime(2026, 6, 23, 12, 0).replace(tzinfo=end.tzinfo)


def test_compute_times_timezone_is_stockholm():
    stay = {"start_date": "2026-01-15", "end_date": "2026-01-15", "nights": 1}
    start, end = _compute_times(stay)
    assert start.tzinfo is not None
    assert end.tzinfo is not None
    assert str(start.tzinfo) == "Europe/Stockholm"
    assert str(end.tzinfo) == "Europe/Stockholm"


def test_compute_times_dst_transition():
    """Check-in/out times are outside the 02:00-03:00 DST window."""
    # Summer (CEST, UTC+2)
    stay = {"start_date": "2026-07-01", "end_date": "2026-07-01", "nights": 1}
    start, _ = _compute_times(stay)
    assert start.utcoffset() == timedelta(hours=2)

    # Winter (CET, UTC+1)
    stay = {"start_date": "2026-01-15", "end_date": "2026-01-15", "nights": 1}
    start, _ = _compute_times(stay)
    assert start.utcoffset() == timedelta(hours=1)
