from __future__ import annotations

from datetime import UTC, datetime


def ensure_aware(value: datetime) -> datetime:
    """Coerce a possibly-naive datetime to a UTC-aware one.

    SQLite returns naive datetimes for ``DateTime(timezone=True)`` columns,
    whereas values produced in code use ``datetime.now(UTC)`` and are aware.
    Comparing the two raises ``TypeError: can't compare offset-naive and
    offset-aware datetimes``. Normalising naive values to UTC keeps datetime
    comparisons total and matches the Postgres ``timestamptz`` semantics the
    schema targets.
    """

    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
