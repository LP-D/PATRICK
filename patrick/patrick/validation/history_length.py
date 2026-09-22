"""CHANTIER (feature/equity-asset-class, suite) -- controle, a la SOUMISSION
du formulaire `/launch` et du CLI, de la regle d'anciennete minimale
d'historique (`data/ingest.py::ingest`, `config.schema.DataQualityConfig.
min_history_years`) -- AVANT de lancer l'ingestion, uniquement quand
l'historique de la cible est deja connu localement (`data/store.py`).

Meme philosophie que `validation/feasibility.py` : lecture EXCLUSIVE du data
lake local (jamais de reseau), et `feasible=True, source="unknown"` pour une
cible jamais mise en cache -- une cible jamais verifiee n'est pas presumee en
echec (voir ce module pour la justification complete de ce principe)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from patrick.data.store import DataStore


@dataclass(frozen=True)
class HistoryLengthResult:
    symbol: str
    feasible: bool
    min_history_years: int
    earliest: str | None  # None si jamais mis en cache
    source: str  # "store" | "unknown"
    reason: str


def check_min_history(symbol: str, min_history_years: int,
                       store: DataStore | None = None) -> HistoryLengthResult:
    store = store or DataStore()
    cache_key = f"raw_{symbol}"

    if not store.exists(cache_key):
        return HistoryLengthResult(
            symbol=symbol, feasible=True, min_history_years=min_history_years,
            earliest=None, source="unknown",
            reason=(f"Historique non encore mis en cache pour {symbol} "
                    "-- anciennete non verifiee avant lancement."),
        )

    df = store.load(cache_key)
    earliest = df.index.min() if len(df) else pd.Timestamp.today()
    threshold = pd.Timestamp.today() - pd.Timedelta(days=min_history_years * 365.25)
    feasible = earliest <= threshold

    if feasible:
        reason = f"Historique suffisant pour {symbol} : disponible depuis {earliest.date()}."
    else:
        reason = (f"Historique insuffisant pour {symbol} : disponible depuis {earliest.date()}, "
                   f"{min_history_years} ans requis (seuil {threshold.date()}).")
    return HistoryLengthResult(
        symbol=symbol, feasible=feasible, min_history_years=min_history_years,
        earliest=str(earliest.date()), source="store", reason=reason,
    )
