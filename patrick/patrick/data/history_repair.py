"""Reprise de l'historique d'une série que le fournisseur ne sert plus en entier.

Le 2026-11-12 Yahoo s'est mis à ne renvoyer qu'UNE barre pour `OJ=F` (jus d'orange) : couverture 0,0 %, série exclue de l'univers,
et les quelque 300 modèles qui en lisaient une variable ne savaient plus prédire. L'historique n'avait pas disparu : il est dans les
instantanés du magasin (`DataStore`), téléchargé les jours d'avant. `restore` recolle cet historique aux barres que le fournisseur
sert encore.

Garde-fous :
- seules les séries perdues côté fournisseur (couverture effondrée, téléchargement vide) sont reprises, jamais celles qu'une porte de
  qualité a écartées pour leur contenu (prix figés, rendement aberrant, trou de cotation) ;
- la dernière observation RÉELLE de la série (`DataStore.series_observation`, tenue à chaque ingestion) borne la reprise : au-delà de
  `MAX_GAP_DAYS` jours sans barre réelle, la série reste exclue. Sans cela une série morte serait prolongée pour toujours, chaque
  instantané reportant la dernière valeur du précédent ;
- l'instantané repris doit avoir été construit sous la même règle point-in-time (`pit_version`).

La colonne d'un instantané est déjà décalée d'une barre quand sa séance ferme après celle de la cible (`ingest._apply_session_lag`) :
`lagged` dit d'appliquer le même décalage aux barres fraîches.
"""
from __future__ import annotations

import pandas as pd

MAX_GAP_DAYS = 10          # jours calendaires tolérés entre la dernière observation réelle et la barre suivante (ou la fin demandée)
MAX_SNAPSHOTS = 40         # instantanés remontés au plus, du plus récent au plus ancien
PROVIDER_REASONS = ("couverture_insuffisante", "echec_telechargement")


def _columns_of(path: str) -> set[str]:
    import pyarrow.parquet as pq

    return set(pq.read_schema(path).names)


def restore(store, cache_key: str, pit: str, symbols: dict[str, str], partial: dict[str, pd.Series], lagged: set[str],
            requested_end: pd.Timestamp) -> tuple[dict[str, pd.Series], dict[str, str]]:
    """`symbols` : {colonne perdue: symbole d'origine} ; `partial` : {colonne: clôtures encore servies par le fournisseur} ; `lagged` :
    colonnes décalées d'une barre. Renvoie `(reprises, dernières observations réelles)` : `{colonne: série recollée}` et
    `{symbole: date ISO}` pour les séries dont le fournisseur sert de nouvelles barres. Une série qui ne peut pas être reprise est
    simplement absente du résultat (elle reste exclue, comme avant)."""
    wanted = dict(symbols)
    restored: dict[str, pd.Series] = {}
    observed: dict[str, str] = {}
    entries = [e for e in reversed(store.list_snapshots(cache_key)) if e.get("pit_version") == pit][:MAX_SNAPSHOTS]
    for entry in entries:
        if not wanted:
            break
        try:
            present = [c for c in wanted if c in _columns_of(entry["path"])]
            frame = pd.read_parquet(entry["path"], columns=present) if present else None
        except (OSError, ValueError):                     # instantané retiré du disque ou illisible : on remonte au précédent
            continue
        for col in present:
            symbol = wanted.pop(col)
            stored = frame[col].dropna()
            known = store.series_observation(symbol) or {}
            if stored.empty or not known.get("date_max"):
                continue
            last_real = pd.Timestamp(known["date_max"])
            fresh = partial.get(col)
            fresh = fresh.dropna() if fresh is not None else pd.Series(dtype=float)
            fresh = fresh[~fresh.index.duplicated(keep="last")].sort_index()
            new_bars = fresh[fresh.index > last_real]
            next_real = new_bars.index.min() if len(new_bars) else pd.Timestamp(requested_end)
            if (next_real - last_real).days > MAX_GAP_DAYS:
                continue                                  # trop longtemps sans barre réelle : la série reste exclue
            tail = fresh.shift(1) if col in lagged else fresh
            tail = tail[tail.index > stored.index.max()].dropna()
            restored[col] = pd.concat([stored, tail]).rename(col)
            if len(new_bars):
                observed[symbol] = str(new_bars.index.max().date())
    return restored, observed
