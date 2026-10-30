"""Features de contexte de marché d'une action (`FeaturesConfig.enable_equity_context_features`).

Le pipeline standard calcule les mêmes familles pour chaque série (technique, pics, volatilité, macro) : il ne dit rien de la position
d'une action face à SON marché. Ces features-ci la comparent à des références, toutes causales (fenêtres glissantes se terminant à la
date courante) et calculées sur les séries déjà décalées par la garde anti-fuite (`data/alignment.py`) :

- références : l'indice de sa place de cotation (CAC 40 pour `MC.PA`, DAX pour `SAP.DE`, S&P 500 pour une action américaine...), un indice
  composite de la zone euro pour les actions européennes (moyenne des rendements des indices nationaux en euros, `config/equity_context.py`),
  et le S&P 500 quand il diffère de l'indice de la place ;
- contre chaque référence : rendement relatif (5, 22, 66, 252 séances), bêta et corrélation glissants (66 et 252), volatilité propre (écart-type
  du résidu de la régression sur la référence, annualisé, mêmes fenêtres) et force relative (écart du rapport de prix à sa moyenne, en écarts-types) ;
- actions de la zone euro seulement : écarts de rendement des emprunts d'État (Italie et France contre Allemagne) en niveau et variation, et
  taux directeur de la BCE contre celui de la Fed, quand ces séries FRED sont dans l'univers du run.

Une référence absente de l'univers (série exclue par le filtre de couverture, ancienne configuration) est simplement sautée : jamais de
colonne inventée, et un DataFrame vide si aucune référence n'est disponible ou si la cible n'est pas une action.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config import equity_context as EC
from patrick.config.equity_universe import is_equity_symbol
from patrick.data.sources.yfinance_source import clean_symbol
from patrick.features._utils import safe_pct_change
from patrick.features.guida import rolling_ols_residual_std

REL_WINDOWS: tuple[int, ...] = (5, 22, 66, 252)
BETA_WINDOWS: tuple[int, ...] = (66, 252)
STRENGTH_WINDOWS: tuple[int, ...] = (66, 252)
SPREAD_WINDOWS: tuple[int, ...] = (22, 66)
EURO_COMPOSITE_NAME = "EURO_COMPOSITE"
_ANNUALIZE = np.sqrt(252)

# Colonnes FRED de l'univers (`config/defaults.py`) : rendements à 10 ans, taux directeurs.
_YIELD_DE, _YIELD_FR, _YIELD_IT = "Germany_10Y_Yield", "France_10Y_Yield", "Italy_10Y_Yield"
_ECB_RATE, _FED_RATE = "EUR_DFR_Rate", "DFF"


def euro_composite(raw: pd.DataFrame) -> pd.Series | None:
    """Indice composite de la zone euro (base 1) : moyenne des rendements journaliers des indices nationaux présents dans `raw` ;
    None s'il y en a moins de `EURO_COMPOSITE_MIN_MEMBERS`."""
    cols = [c for c in (clean_symbol(t) for t in EC.EURO_COMPOSITE) if c in raw.columns]
    if len(cols) < EC.EURO_COMPOSITE_MIN_MEMBERS:
        return None
    rets = pd.concat([safe_pct_change(raw[c]) for c in cols], axis=1).mean(axis=1)
    return (1.0 + rets.fillna(0.0)).cumprod().rename(EURO_COMPOSITE_NAME)


def references(raw: pd.DataFrame, target_symbol: str) -> dict[str, pd.Series]:
    """{nom de la référence: série de niveaux} disponibles pour cette action, dans l'ordre indice de la place, zone euro, monde."""
    out: dict[str, pd.Series] = {}
    home = EC.home_index(target_symbol)
    if home and clean_symbol(home) in raw.columns:
        out[clean_symbol(home)] = raw[clean_symbol(home)]
    if EC.uses_euro_composite(target_symbol):
        composite = euro_composite(raw)
        if composite is not None:
            out[EURO_COMPOSITE_NAME] = composite
    world = clean_symbol(EC.GLOBAL_BENCHMARK)
    if world in raw.columns and world not in out:
        out[world] = raw[world]
    return out


def _versus(target: pd.Series, bench: pd.Series, name: str, prefix: str) -> dict[str, pd.Series]:
    tr, br = safe_pct_change(target), safe_pct_change(bench)
    out: dict[str, pd.Series] = {}
    for w in REL_WINDOWS:
        out[f"{prefix}_rel_{name}_ret_{w}d"] = safe_pct_change(target, w) - safe_pct_change(bench, w)
    for w in BETA_WINDOWS:
        var = br.rolling(w).var().replace(0, np.nan)
        out[f"{prefix}_beta_{name}_{w}d"] = tr.rolling(w).cov(br) / var
        out[f"{prefix}_corr_{name}_{w}d"] = tr.rolling(w).corr(br)
        out[f"{prefix}_idio_vol_{name}_{w}d"] = rolling_ols_residual_std(tr, br, w) * _ANNUALIZE
    ratio = np.log(target.where(target > 0) / bench.where(bench > 0))
    for w in STRENGTH_WINDOWS:
        sd = ratio.rolling(w).std().replace(0, np.nan)
        out[f"{prefix}_rel_strength_z_{name}_{w}d"] = (ratio - ratio.rolling(w).mean()) / sd
    return out


def _euro_stress(raw: pd.DataFrame, prefix: str) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if _YIELD_DE in raw.columns:
        for other, tag in ((_YIELD_IT, "it_de"), (_YIELD_FR, "fr_de")):
            if other in raw.columns:
                spread = raw[other] - raw[_YIELD_DE]
                out[f"{prefix}_spread_{tag}_level"] = spread
                for w in SPREAD_WINDOWS:
                    out[f"{prefix}_spread_{tag}_chg_{w}d"] = spread.diff(w)
    if _ECB_RATE in raw.columns and _FED_RATE in raw.columns:
        diff = raw[_ECB_RATE] - raw[_FED_RATE]
        out[f"{prefix}_policy_gap_ecb_fed_level"] = diff
        for w in SPREAD_WINDOWS:
            out[f"{prefix}_policy_gap_ecb_fed_chg_{w}d"] = diff.diff(w)
    return out


def build_equity_context_features(raw: pd.DataFrame, target_symbol: str) -> pd.DataFrame:
    """Colonnes `<cible>_ctx_*` ; DataFrame vide (jamais d'exception) si la cible n'est pas une action ou si aucune référence n'est dans `raw`."""
    target_col = clean_symbol(target_symbol)
    if not is_equity_symbol(target_symbol) or target_col not in raw.columns:
        return pd.DataFrame(index=raw.index)
    prefix = f"{target_col}_ctx"
    target = raw[target_col]
    cols: dict[str, pd.Series] = {}
    for name, bench in references(raw, target_symbol).items():
        cols.update(_versus(target, bench, name, prefix))
    if cols and EC.region_of(target_symbol) == "euro":
        cols.update(_euro_stress(raw, prefix))
    return pd.DataFrame(cols, index=raw.index) if cols else pd.DataFrame(index=raw.index)


# Pour la page Equity : (clé de texte, famille) de ce que reçoit une action ; les textes sont dans `webapp/i18n_pages.py` (`eq_ctx_<clé>`).
def describe() -> list[str]:
    return ["relative", "beta", "idio", "strength", "euro_stress"]
