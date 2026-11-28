"""Timestamps: the one UTC stamp tools write, and the parser that also reads legacy local stamps.

The stamp format is shared by PROGRESS.md, locks and run records, so it lives once.
"""

from __future__ import annotations

from datetime import UTC, datetime

UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Local time, written before the UTC stamp (with seconds by tools, without by hand); read, never written.
LEGACY_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M")


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_stamp(moment: datetime | float | None = None) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` for `moment` (an aware datetime or epoch seconds), default now."""
    if moment is None:
        moment = utc_now()
    elif not isinstance(moment, datetime):
        moment = datetime.fromtimestamp(moment, UTC)
    return moment.astimezone(UTC).strftime(UTC_FORMAT)


def utc_iso() -> str:
    """Now as an ISO 8601 string with an offset, which `datetime.fromisoformat` reads on Python 3.9."""
    return utc_now().isoformat()


def utc_date() -> str:
    return utc_now().strftime("%Y-%m-%d")


def parse_stamp(text: str) -> datetime | None:
    """Aware UTC from a UTC stamp, a legacy local `YYYY-MM-DD HH:MM[:SS]` stamp, or an offset ISO string; else None."""
    text = text.strip()
    try:
        return datetime.strptime(text, UTC_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        pass
    for legacy in LEGACY_FORMATS:
        try:
            return datetime.strptime(text, legacy).astimezone(UTC)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None
