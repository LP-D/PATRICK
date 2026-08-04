"""Phase 6.5 -- portes de qualité de données à l'ingestion : chaque série
candidate (yfinance ou FRED) passe une batterie de contrôles AVANT d'entrer
dans l'univers de features. Toute exclusion est motivée explicitement et
persistée (jamais un `[WARN]` perdu dans les logs, comme l'était le repli
FRED avant sa correction -- même classe de défaut, cf. rapport de session).

Seuils par défaut -- MESURÉS, pas choisis par convention (cf. rapport de
correction P6.5 pour le détail des simulations) :

- `DEFAULT_MAX_FROZEN_RUN = 4` (clôtures identiques consécutives) : simulation
  de 500 séries x 4000 jours (prix ~100, vol quotidienne 1.5%, arrondi 2
  décimales -- cotation typique) -- AUCUNE série propre n'atteint un run de 4
  clôtures identiques (maximum observé : 3). Un run de 4+ n'arrive quasiment
  jamais par hasard sur une série activement cotée.
- `DEFAULT_MAX_GAP_BDAYS = 10` (trou de cotation) : les plus longs clusters de
  jours fériés de marché connus (Noël/Nouvel An avec jours fériés se
  chevauchant selon les juridictions) atteignent ~5 jours ouvrés consécutifs
  -- 10 jours ouvrés (2 semaines) donne une marge de sécurité x2 par rapport à
  ce maximum plausible, tout en détectant une vraie suspension de cotation.
  Réutilisé tel quel pour `check_stale_tail` (fin de série précoce = un trou
  de cotation qui n'a jamais été comblé).
- `DEFAULT_MAX_ROBUST_Z = 40.0` (rendement aberrant) : simulation de 500
  séries x 4000 jours de rendements Student-t (df=5, queues épaisses
  réalistes pour un actif liquide) -- z-score robuste (MAD globale x 1.4826,
  résistant aux valeurs aberrantes qui biaiseraient un écart-type classique)
  maximal observé sur l'ensemble des séries PROPRES : 35.5 (0/500 dépassent
  40). Un split non ajusté (2:1, cas le plus doux testé) produit un z ≈ 40 ;
  des cas plus francs (10:1, erreur de décimale) donnent 60-700+ -- séparation
  nette entre bruit de marché propre et corruption de données.
- `DEFAULT_MIN_COVERAGE = 0.85` : réutilise `UniverseConfig.yf_coverage`
  (déjà en place, Phase 0), pas un nouveau seuil inventé.
- `DEFAULT_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30` : au-delà, la perte porte sur
  des séries ENTIÈRES (pas une couverture partielle déjà tolérée par
  `yf_coverage`) -- un tiers de l'univers demandé disparu signale un problème
  systémique (mauvais tickers/start_date/panne fournisseur), pas quelques
  séries isolément défaillantes ; en dessous, la sélection de features
  (`pool_prefilter`, déjà agressive) reste opérable sur ce qui reste.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

DEFAULT_MAX_FROZEN_RUN = 4
DEFAULT_MAX_GAP_BDAYS = 10
DEFAULT_MAX_ROBUST_Z = 40.0
DEFAULT_MIN_COVERAGE = 0.85
DEFAULT_MAX_UNIVERSE_EXCLUSION_FRAC = 0.30


@dataclass
class QualityIssue:
    series: str
    reason: str
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def robust_z_scores(returns: pd.Series) -> pd.Series:
    """MAD (médiane des écarts absolus à la médiane) redimensionnée par 1.4826
    pour être un estimateur cohérent de l'écart-type sous normalité --
    résistant aux queues épaisses (une valeur aberrante ne gonfle pas le
    dénominateur, contrairement à un écart-type classique)."""
    med = returns.median()
    mad = (returns - med).abs().median()
    robust_sigma = mad * 1.4826
    if robust_sigma < 1e-12:
        return pd.Series(0.0, index=returns.index)
    return (returns - med) / robust_sigma


def check_frozen_prices(s: pd.Series, max_run: int = DEFAULT_MAX_FROZEN_RUN) -> QualityIssue | None:
    """`max_run` : nombre de clôtures consécutives identiques à partir duquel
    la série est considérée figée (cf. justification module)."""
    vals = s.dropna().values
    if len(vals) < max_run:
        return None
    same = np.diff(vals) == 0
    run = 1
    best = 1
    for is_same in same:
        run = run + 1 if is_same else 1
        best = max(best, run)
    if best >= max_run:
        return QualityIssue(s.name, "prix_figes", f"{best} clôtures consécutives identiques (seuil {max_run})")
    return None


def check_quote_gaps(s: pd.Series, max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS) -> QualityIssue | None:
    """Plus long trou (en jours ouvrés) entre deux observations non-NaN
    consécutives de `s`, sur l'index business-day complet fourni par l'appelant
    (`s.index` doit déjà être le calendrier jours ouvrés attendu)."""
    valid_dates = s.dropna().index
    if len(valid_dates) < 2:
        return None
    gaps = valid_dates.to_series().diff().dt.days.dropna()
    # Grille jours ouvrés (pas de samedi/dimanche) : un trou "normal" d'un jour
    # ouvré vaut ~1-3 jours calendaires selon position dans la semaine -- on
    # convertit en jours ouvrés approximatifs via le ratio 7/5 (5 jours ouvrés
    # par semaine calendaire de 7 jours), cohérent avec `pd.bdate_range`.
    gaps_bdays = gaps * 5 / 7
    max_gap = gaps_bdays.max() if len(gaps_bdays) else 0.0
    if max_gap > max_gap_bdays:
        worst_idx = gaps_bdays.idxmax()
        return QualityIssue(s.name, "trou_de_cotation",
                             f"trou de {max_gap:.0f} jours ouvrés estimés se terminant {worst_idx.date()} "
                             f"(seuil {max_gap_bdays})")
    return None


def check_aberrant_returns(s: pd.Series, max_robust_z: float = DEFAULT_MAX_ROBUST_Z) -> QualityIssue | None:
    ret = s.dropna().pct_change().dropna()
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
    if len(ret) < 30:
        return None
    z = robust_z_scores(ret)
    max_abs_z = z.abs().max()
    if max_abs_z > max_robust_z:
        worst_idx = z.abs().idxmax()
        return QualityIssue(s.name, "rendement_aberrant",
                             f"rendement de {ret.loc[worst_idx]:.1%} le {worst_idx.date()} "
                             f"(z robuste={max_abs_z:.1f}, seuil {max_robust_z})")
    return None


def check_stale_tail(s: pd.Series, requested_end: pd.Timestamp,
                      max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS) -> QualityIssue | None:
    valid_dates = s.dropna().index
    if len(valid_dates) == 0:
        return None
    last_date = valid_dates.max()
    gap_days = (requested_end - last_date).days
    gap_bdays = gap_days * 5 / 7
    if gap_bdays > max_gap_bdays:
        return QualityIssue(s.name, "fin_de_serie_precoce",
                             f"dernière observation {last_date.date()}, "
                             f"~{gap_bdays:.0f} jours ouvrés avant la fin demandée "
                             f"({requested_end.date()}, seuil {max_gap_bdays}) -- probablement délistée")
    return None


def check_fred_missing(name: str, s: pd.Series | None) -> QualityIssue | None:
    if s is None or s.dropna().empty:
        return QualityIssue(name, "fred_absent_ou_discontinue",
                             "aucune observation renvoyée (série discontinuée, identifiant invalide, "
                             "ou échec de récupération)")
    return None


def check_coverage(s: pd.Series, full_index: pd.DatetimeIndex,
                    min_coverage: float = DEFAULT_MIN_COVERAGE) -> QualityIssue | None:
    if len(full_index) == 0:
        return None
    coverage = s.reindex(full_index).notna().mean()
    if coverage < min_coverage:
        return QualityIssue(s.name, "couverture_insuffisante",
                             f"{coverage:.1%} de jours ouvrés renseignés (seuil {min_coverage:.0%})")
    return None


def evaluate_yfinance_series(name: str, s: pd.Series, full_index: pd.DatetimeIndex,
                              requested_end: pd.Timestamp, *, max_frozen_run: int = DEFAULT_MAX_FROZEN_RUN,
                              max_gap_bdays: int = DEFAULT_MAX_GAP_BDAYS,
                              max_robust_z: float = DEFAULT_MAX_ROBUST_Z,
                              min_coverage: float = DEFAULT_MIN_COVERAGE) -> QualityIssue | None:
    """Renvoie le PREMIER problème détecté (une série exclue l'est pour un
    motif, pas cumulativement) -- ordre : couverture, trou de cotation, fin
    précoce, prix figés, rendement aberrant (du plus "structurel" au plus
    fin)."""
    s = s.rename(name) if s.name != name else s
    for check, kwargs in (
        (check_coverage, {"full_index": full_index, "min_coverage": min_coverage}),
        (check_quote_gaps, {"max_gap_bdays": max_gap_bdays}),
        (check_stale_tail, {"requested_end": requested_end, "max_gap_bdays": max_gap_bdays}),
        (check_frozen_prices, {"max_run": max_frozen_run}),
        (check_aberrant_returns, {"max_robust_z": max_robust_z}),
    ):
        issue = check(s, **kwargs)
        if issue is not None:
            return issue
    return None
