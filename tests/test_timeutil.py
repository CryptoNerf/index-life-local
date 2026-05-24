"""Tests for the utcnow() helper that replaced datetime.utcnow().

The contract that matters: it must return a *naive* UTC datetime (same
as the old datetime.utcnow()), so it never mixes with the naive
timestamps stored in the DB and compared during sync.
"""
from datetime import datetime, timezone

from app.timeutil import utcnow


def test_utcnow_is_naive():
    assert utcnow().tzinfo is None


def test_utcnow_tracks_real_utc():
    # Within a couple of seconds of the timezone-aware reference.
    aware = datetime.now(timezone.utc).replace(tzinfo=None)
    assert abs((utcnow() - aware).total_seconds()) < 2


def test_utcnow_is_comparable_with_naive_datetimes():
    # The whole point: no "can't compare offset-naive and offset-aware".
    assert utcnow() >= datetime(2020, 1, 1)
