"""Garde-fou contre la fuite temporelle des LLM.

Un modèle de langage qui note une dépêche de 2020 connaît la suite (le krach de mars, la reprise) : sa note « directionnelle »
en zero-shot mélange la lecture du texte et la mémoire de ce qui est arrivé. Dans un backtest, seules les dates **postérieures
à la date limite de connaissance du modèle** (plus une marge, car la limite est floue et les données récentes mal
représentées) sont propres. Avant, le score est contaminé et ne doit pas servir à évaluer une stratégie.

Règle : un modèle sans date limite connue est REFUSÉ (jamais présumé propre). Les dates limites ci-dessous viennent de la
documentation du fournisseur ; `register_cutoff` ajoute un modèle (pour un modèle ouvert ajusté, la fin des données
d'ajustement fait foi, pas celle du modèle de départ).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

KNOWN_CUTOFFS: dict[str, str] = {
    "claude-sonnet-5-5": "2026-06-30",     # « knowledge cutoff: June 2026 » (invite système du modèle)
}
DEFAULT_MARGIN_DAYS = 90


class UnknownModelError(KeyError):
    """Date limite de connaissance inconnue : le modèle est refusé."""


class LeakageError(ValueError):
    """Des dates antérieures à la limite de connaissance du modèle ont été demandées."""


def register_cutoff(model_id: str, cutoff) -> None:
    KNOWN_CUTOFFS[model_id] = str(pd.Timestamp(cutoff).date())


def knowledge_cutoff(model_id: str) -> pd.Timestamp:
    try:
        return pd.Timestamp(KNOWN_CUTOFFS[model_id])
    except KeyError:
        raise UnknownModelError(
            f"date limite de connaissance inconnue pour {model_id!r} : refusé (enregistrer avec register_cutoff)") from None


def _as_dates(dates) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(pd.to_datetime(list(dates)))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx.normalize()


def clean_mask(model_id: str, dates, margin_days: int = DEFAULT_MARGIN_DAYS) -> np.ndarray:
    """Vrai pour les dates strictement postérieures à `limite + marge` : les seules où la note du modèle n'a pas pu
    s'appuyer sur la mémoire de ce qui a suivi."""
    limit = knowledge_cutoff(model_id) + pd.Timedelta(days=margin_days)
    return np.asarray(_as_dates(dates) > limit)


def assert_clean(model_id: str, dates, margin_days: int = DEFAULT_MARGIN_DAYS) -> None:
    idx = _as_dates(dates)
    bad = idx[~clean_mask(model_id, idx, margin_days)]
    if len(bad):
        shown = ", ".join(str(d.date()) for d in bad[:5]) + (" …" if len(bad) > 5 else "")
        raise LeakageError(
            f"{len(bad)} date(s) antérieure(s) à la limite de connaissance de {model_id} "
            f"({knowledge_cutoff(model_id).date()} + {margin_days} j) : {shown}")
