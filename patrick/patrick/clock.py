"""Single source of "now"/"today" for the package -- always timezone-explicit
(ruff DTZ family, lifted with the F01 point-in-time chantier).

Conventions:
- `utc_now()`/`utc_today()`: anything persisted or compared across processes
  (cache freshness, snapshot partitions, vintage dates, "days late"): the
  web process, the worker and scheduled jobs agree whatever the machine's
  timezone or DST state.
- `local_now()`: display only (an aware local time, e.g. "updated at").
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_today() -> date:
    return utc_now().date()


def local_now() -> datetime:
    return datetime.now().astimezone()


def parse_utc(iso: str) -> datetime:
    """ISO timestamp -> aware UTC datetime. Naive strings (written before
    this module existed, by `datetime.utcnow().isoformat()`) are UTC."""
    parsed = datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)
