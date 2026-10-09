"""Garde anti-fuite temporelle : « une feature connue à la date t ne doit jamais recouvrir la fenêtre du label de t ».

Cause d'un F1 de 1,0 observé sur SP500, VIXCLS, DGS2..DGS30 (taux du Trésor) et EURUSD=X
(`docs/research/fuite-f1-parfait-2026-10-09.md`) : le label d'une ligne est le rendement entre ses deux prochaines
valeurs de la cible. Pour une cible FRED, F01 (`data/publication_lag.py`) place chaque observation à sa date de
PUBLICATION (J+1 pour un taux quotidien) ; le label de la ligne J est donc le mouvement du jour J lui-même. Les séries
cotées (^GSPC, ^TNX, ^VIX...) étaient jointes à leur date de cotation, sans retard : la feature « rendement de ^GSPC en J »
reproduisait exactement le label (corrélation 1,000). Le modèle « prédisait » un chiffre déjà observé.

Deux protections, aucune ne dépend de la performance :

1. **Retard de publication** : pour une cible FRED, toute série cotée est retardée du délai de publication de la cible
   (`publication_lag.publication_delay_bars`) : à la ligne J, le marché n'est connu que jusqu'à la dernière date couverte
   par la dernière valeur publiée de la cible.
2. **Audit empirique** : toute série cotée dont le rendement du jour est corrélé (Spearman) au rendement futur de la cible
   au-delà de `AUDIT_CORR_THRESHOLD` est retardée d'une barre (puis retirée si cela ne suffit pas). Aucun actif ne prédit
   le lendemain d'un autre avec une corrélation de rang de 0,30 : c'est un horodatage décalé du fournisseur (cas observé :
   DX-Y.NYB daté J contient le mouvement d'EURUSD=X daté J+1, corrélation -0,40). Calculé sur les lignes AVANT le holdout
   uniquement, pour que le holdout ne serve jamais à décider d'un traitement.

La décision (`AlignmentSpec`) est écrite dans la config du run : la prédiction live, l'explication et la reprise rejouent
les mêmes décalages. Un run antérieur (`version == 0`) n'en a aucun et garde exactement ses entrées d'origine.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.clock import utc_today
from patrick.config.schema import AlignmentSpec, ObjectiveConfig, UniverseConfig
from patrick.data import publication_lag
from patrick.data.sources.yfinance_source import clean_symbol

ALIGNMENT_VERSION = 1
AUDIT_CORR_THRESHOLD = 0.30
AUDIT_MIN_ROWS = 250
AUDIT_MIN_DISTINCT = 20
MAX_EXTRA_LAG = 2


def drop_future_rows(raw: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Sans les lignes datées après `today`. Une cible FRED placée à sa date de PUBLICATION (F01) crée des lignes dans le
    futur : le dernier relevé de DCOILWTICO, publié avec 7 jours ouvrés de retard, est daté 10 jours après la dernière
    cotation. Aucune information n'existe à ces dates : le holdout et la prédiction « du jour » s'y calaient (prédictions
    datées 2026-10-12 et 2026-10-13 pour une base lue le 2026-10-09)."""
    if not isinstance(raw.index, pd.DatetimeIndex) or not len(raw):
        return raw
    limit = (pd.Timestamp(today) if today is not None else pd.Timestamp(utc_today())).normalize()
    if raw.index.max() <= limit:
        return raw
    out = raw.loc[raw.index <= limit]
    out.attrs = dict(raw.attrs)
    return out


def apply_spec(raw: pd.DataFrame, spec: AlignmentSpec | None) -> pd.DataFrame:
    """`raw` avec les retards et retraits de `spec` ; `raw` lui-même si `spec` est vide (version 0)."""
    if spec is None or (not spec.column_lags and not spec.dropped and not spec.drop_future):
        return raw
    out = raw.copy()
    for col, k in spec.column_lags.items():
        if col in out.columns and k:
            out[col] = out[col].shift(int(k))
    out = out.drop(columns=[c for c in spec.dropped if c in out.columns])
    out.attrs = dict(raw.attrs)
    return drop_future_rows(out) if spec.drop_future else out


def _forward_change(s: pd.Series) -> pd.Series:
    return s.shift(-1) - s


def leaking_columns(df: pd.DataFrame, target_col: str, columns: list[str], cutoff: pd.Timestamp | None = None,
                    threshold: float = AUDIT_CORR_THRESHOLD) -> dict[str, float]:
    """{colonne: corrélation de rang} des séries de `columns` dont la variation du jour (colonne en t moins en t-1)
    est corrélée à la variation FUTURE de la cible (cible en t+1 moins en t) au-delà de `threshold`.
    Premières différences : valables aussi pour une série qui change de signe (spread de taux)."""
    if target_col not in df.columns:
        return {}
    work = df if cutoff is None else df.loc[:cutoff]
    fwd = _forward_change(work[target_col].astype(float))
    out: dict[str, float] = {}
    for col in columns:
        if col not in work.columns or col == target_col:
            continue
        x = work[col].astype(float)
        if x.nunique() < AUDIT_MIN_DISTINCT:
            continue
        pair = pd.concat([fwd, x.diff()], axis=1, keys=["fwd", "x"]).replace([np.inf, -np.inf], np.nan).dropna()
        pair = pair[(pair["fwd"] != 0) & (pair["x"] != 0)]   # séries en escalier : seules les dates de changement parlent
        if len(pair) < AUDIT_MIN_ROWS:
            continue
        corr = pair["fwd"].rank().corr(pair["x"].rank())
        if corr is not None and np.isfinite(corr) and abs(corr) >= threshold:
            out[col] = float(corr)
    return out


def market_columns(raw: pd.DataFrame, universe: UniverseConfig, protected: set[str]) -> list[str]:
    """Colonnes de séries cotées (yfinance) présentes dans `raw`, hors cible et benchmark."""
    cols = [clean_symbol(t) for t in universe.yf_tickers]
    return [c for c in dict.fromkeys(cols) if c in raw.columns and c not in protected]


def decide(raw: pd.DataFrame, objective: ObjectiveConfig, universe: UniverseConfig,
           holdout_months: int) -> AlignmentSpec:
    """Décalages à appliquer à `raw` pour ce run (voir le docstring du module). `raw` est la table jointe de l'ingestion."""
    target_col = clean_symbol(objective.target_symbol)
    if not isinstance(raw.index, pd.DatetimeIndex):
        return AlignmentSpec(version=ALIGNMENT_VERSION)      # pas de calendrier : rien à aligner (ni à rogner)
    protected = {target_col}
    if objective.target_kind == "alpha" and objective.benchmark:
        protected.add(clean_symbol(objective.benchmark))   # le benchmark garde son calendrier : `features/alpha_target.py`
    market = market_columns(raw, universe, protected)
    base: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}

    if objective.target_source == "fred" and universe.fred_point_in_time != "reference_date":
        delay = publication_lag.publication_delay_bars(objective.target_symbol, raw.index)
        if delay > 0:
            for col in market:
                base[col] = delay
                reasons[col] = [f"cible FRED publiée avec {delay} barre(s) de retard : le marché est connu jusque-là"]

    cutoff = None
    if len(raw) and holdout_months > 0:
        cutoff = pd.Timestamp(raw.index.max()) - pd.DateOffset(months=holdout_months)
    extra: dict[str, int] = {}
    dropped: list[str] = []
    for _ in range(MAX_EXTRA_LAG + 1):
        lags = {c: base.get(c, 0) + extra.get(c, 0) for c in set(base) | set(extra)}
        current = apply_spec(raw, AlignmentSpec(column_lags=lags, dropped=dropped))
        flagged = leaking_columns(current, target_col, [c for c in market if c not in dropped], cutoff)
        if not flagged:
            break
        for col, corr in flagged.items():
            if extra.get(col, 0) >= MAX_EXTRA_LAG:
                dropped.append(col)
                reasons.setdefault(col, []).append(
                    f"retirée : corrélation de rang {corr:+.2f} avec le label malgré {extra.get(col, 0)} retard(s) d'audit")
            else:
                extra[col] = extra.get(col, 0) + 1
                reasons.setdefault(col, []).append(
                    f"audit : corrélation de rang {corr:+.2f} avec le rendement futur de la cible")
    lags = {c: base.get(c, 0) + extra.get(c, 0) for c in set(base) | set(extra)}
    lags = {c: k for c, k in lags.items() if k and c not in dropped}
    return AlignmentSpec(version=ALIGNMENT_VERSION, column_lags=lags, dropped=dropped, drop_future=True,
                         reasons={c: " ; ".join(r) for c, r in reasons.items()})


def describe(spec: AlignmentSpec) -> list[dict]:
    """Une ligne par colonne touchée, au format de `data_quality_issue` (`series`, `reason`, `detail`)."""
    rows = []
    for col in sorted(set(spec.column_lags) | set(spec.dropped)):
        action = "retirée" if col in spec.dropped else f"retardée de {spec.column_lags.get(col, 0)} barre(s)"
        rows.append({"series": col, "reason": "alignement_temporel", "detail": f"{action} : {spec.reasons.get(col, '')}"})
    return rows
