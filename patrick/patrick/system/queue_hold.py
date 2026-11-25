"""File d'attente retenue jusqu'à une heure donnée (FO26 du 25/11) : « ces runs partiront à 23 h », pas tout de suite.

Réglage de ce PC `queue_hold_until` (date et heure locales ISO, `AAAA-MM-JJTHH:MM`). Tant que l'heure n'est pas passée, le worker ne prend
aucun job (les jobs restent en file, réordonnables) et son délai d'inactivité ne court pas ; à l'heure dite, la file part dans l'ordre.
Un réglage passé ou illisible ne retient rien.
"""
from __future__ import annotations

import datetime as dt

from patrick.core import settings

KEY = "queue_hold_until"


def hold_until() -> dt.datetime | None:
    raw = settings.load().get(KEY)
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def held(now: dt.datetime | None = None) -> bool:
    until = hold_until()
    now = now or dt.datetime.now()  # noqa: DTZ005 -- heure locale, comme celle saisie par l'utilisateur
    return until is not None and now < until


def set_hold(until: dt.datetime | None) -> None:
    settings.save({KEY: until.isoformat(timespec="minutes") if until else None})
