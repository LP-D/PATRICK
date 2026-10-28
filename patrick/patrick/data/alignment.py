"""Garde anti-fuite temporelle : « une feature connue à la date t ne doit jamais recouvrir la fenêtre du label de t ».

Cause d'un F1 de 1,0 observé sur SP500, VIXCLS, DGS2..DGS30 (taux du Trésor) et EURUSD=X
(`docs/research/fuite-f1-parfait-2026-10-09.md`) : le label d'une ligne est le rendement entre ses deux prochaines
valeurs de la cible. Pour une cible FRED, F01 (`data/publication_lag.py`) place chaque observation à sa date de
PUBLICATION (J+1 pour un taux quotidien) ; le label de la ligne J est donc le mouvement du jour J lui-même. Les séries
cotées (^GSPC, ^TNX, ^VIX...) étaient jointes à leur date de cotation, sans retard : la feature « rendement de ^GSPC en J »
reproduisait exactement le label (corrélation 1,000). Le modèle « prédisait » un chiffre déjà observé.

Trois protections, aucune ne dépend de la performance :

1. **Retard de publication** : pour une cible FRED, toute série cotée est retardée du délai de publication de la cible
   (`publication_lag.publication_delay_bars`) : à la ligne J, le marché n'est connu que jusqu'à la dernière date couverte
   par la dernière valeur publiée de la cible.
2. **Audit empirique** : toute série dont le rendement du jour est corrélé (Spearman) au rendement futur de la cible
   au-delà de `audit_threshold(n)` est retardée d'une barre (puis retirée si cela ne suffit pas). Aucun actif ne prédit
   le lendemain d'un autre avec une telle corrélation de rang : c'est un horodatage décalé (cas observé : DX-Y.NYB daté J contient
   le mouvement d'EURUSD=X daté J+1, corrélation -0,40). Calculé sur les lignes AVANT le holdout uniquement, pour que le holdout
   ne serve jamais à décider d'un traitement.
3. **Règle des séances** (`data/session_calendar.py`, appliquée à l'ingestion) pour les séries Yahoo.

Version 2 de l'audit (ADR 0007) : le seuil fixe de 0,30 laissait passer les fuites plus faibles (devises : or, argent, S&P 500 à 0,17-0,30 ;
actions asiatiques : VIX, VXN, écarts de crédit FRED à 0,20-0,30) ; le seuil est maintenant statistique, `max(0,10 ; 5 / racine(n))`
(cinq écarts-types d'un bruit de corrélation de rang, soit 0,08 pour 4 000 lignes), et l'audit couvre aussi les séries FRED d'une cible cotée.

La décision (`AlignmentSpec`) est écrite dans la config du run : la prédiction live, l'explication et la reprise rejouent
les mêmes décalages. Un run antérieur (`version == 0`) n'en a aucun et garde exactement ses entrées d'origine.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from patrick.clock import utc_today
from patrick.config.schema import AlignmentSpec, ObjectiveConfig, UniverseConfig
from patrick.data import publication_lag
from patrick.data.freshness import fred_periodicity
from patrick.data.session_calendar import FRED_MARKET_CLOSE_UTC_HOUR, target_close_hour
from patrick.data.sources.yfinance_source import clean_symbol

ALIGNMENT_VERSION = 2
AUDIT_CORR_THRESHOLD = 0.30        # seuil fixe de la version 1, conservé pour mémoire et pour les appels qui le passent
AUDIT_CORR_FLOOR = 0.10
AUDIT_Z = 5.0
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


def audit_threshold(n_pairs: int) -> float:
    """Corrélation de rang au-delà de laquelle une série est jugée recouvrir le label : cinq écarts-types du bruit
    (1 / racine(n)), jamais moins de `AUDIT_CORR_FLOOR`. 0,30 pour 250 paires (séries en escalier), 0,10 dès 2 500."""
    return max(AUDIT_CORR_FLOOR, AUDIT_Z / math.sqrt(max(int(n_pairs), 1)))


def leaking_columns(df: pd.DataFrame, target_col: str, columns: list[str], cutoff: pd.Timestamp | None = None,
                    threshold: float | None = None) -> dict[str, float]:
    """{colonne: corrélation de rang} des séries de `columns` dont la variation du jour (colonne en t moins en t-1)
    est corrélée à la variation FUTURE de la cible (cible en t+1 moins en t) au-delà de `threshold` (`None` : le seuil
    statistique `audit_threshold(n)` de chaque série). Premières différences : valables aussi pour une série qui change
    de signe (spread de taux)."""
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
        limit = audit_threshold(len(pair)) if threshold is None else threshold
        if corr is not None and np.isfinite(corr) and abs(corr) >= limit:
            out[col] = float(corr)
    return out


def market_columns(raw: pd.DataFrame, universe: UniverseConfig, protected: set[str]) -> list[str]:
    """Colonnes de séries cotées (yfinance) présentes dans `raw`, hors cible et benchmark."""
    cols = [clean_symbol(t) for t in universe.yf_tickers]
    return [c for c in dict.fromkeys(cols) if c in raw.columns and c not in protected]


def fred_columns(raw: pd.DataFrame, universe: UniverseConfig, protected: set[str]) -> list[str]:
    """Colonnes FRED de `universe` présentes dans `raw`, hors cible : auditées elles aussi pour une cible cotée (un VIX ou un écart
    de crédit FRED daté du jour recouvre le label d'une cible qui clôture avant les États-Unis)."""
    return [c for c in dict.fromkeys(universe.fred_series) if c in raw.columns and c not in protected]


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
    audited = market + (fred_columns(raw, universe, protected) if objective.target_source == "yfinance" else [])
    base: dict[str, int] = {}
    reasons: dict[str, list[str]] = {}

    if objective.target_source == "fred" and universe.fred_point_in_time != "reference_date":
        delay = publication_lag.publication_delay_bars(objective.target_symbol, raw.index)
        if delay > 0:
            for col in market:
                base[col] = delay
                reasons[col] = [f"cible FRED publiée avec {delay} barre(s) de retard : le marché est connu jusque-là"]

    if objective.target_source == "yfinance" and universe.fred_point_in_time == "alfred":
        # Une cible qui clôture avant les États-Unis (Asie, Europe, changes) : la valeur FRED quotidienne du jour d, publiée le
        # soir même par ALFRED, est connue APRÈS sa décision. Les écarts de crédit n'ont que 3 ans d'historique : l'audit
        # statistique n'a pas la puissance pour les voir, d'où cette règle structurelle (Asie : corrélation -0,20 à -0,30).
        hour = target_close_hour(objective.target_symbol, objective.target_source, getattr(objective, "session_rule", 1))
        if hour < FRED_MARKET_CLOSE_UTC_HOUR:
            for col in fred_columns(raw, universe, protected):
                if fred_periodicity(universe.fred_series.get(col, col)) == "daily":
                    base[col] = base.get(col, 0) + 1
                    reasons.setdefault(col, []).append(
                        f"série FRED quotidienne du jour (ALFRED) connue après la clôture de la cible ({hour:g} h UTC)")

    cutoff = None
    if len(raw) and holdout_months > 0:
        cutoff = pd.Timestamp(raw.index.max()) - pd.DateOffset(months=holdout_months)
    extra: dict[str, int] = {}
    dropped: list[str] = []
    for _ in range(MAX_EXTRA_LAG + 1):
        lags = {c: base.get(c, 0) + extra.get(c, 0) for c in set(base) | set(extra)}
        current = apply_spec(raw, AlignmentSpec(column_lags=lags, dropped=dropped))
        flagged = leaking_columns(current, target_col, [c for c in audited if c not in dropped], cutoff)
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
