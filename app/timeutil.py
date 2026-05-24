"""Time helpers.

`utcnow()` is a drop-in replacement for the deprecated `datetime.utcnow()`
(removed in a future Python). It deliberately returns a **naive** datetime
in UTC — identical in value to the old `datetime.utcnow()` — rather than a
timezone-aware one.

Why naive: the SQLite columns and all stored timestamps in this app are
naive UTC, and the sync merge compares them directly (`remote <= local`).
Returning an aware datetime here would mix naive and aware values and raise
`TypeError: can't compare offset-naive and offset-aware datetimes`. Keeping
it naive preserves the existing behaviour exactly while dropping the
deprecation.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (tzinfo stripped)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
