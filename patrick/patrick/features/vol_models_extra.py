"""Modèles de volatilité supplémentaires pour les variables (A3) : GJR-GARCH, APARCH et HAR-RV.

Pourquoi un module à part : `vol_models.py` fait partie de l'empreinte du code des variables (`pool_cache.FEATURE_CODE_HASH`) ; le
modifier invaliderait TOUT le cache de variables (plus de 100 Go, réserve partagée comprise) pour trois modèles que seuls les runs qui
les choisissent utilisent. Ce module s'enregistre dans le registre de `vol_models` à l'import du paquet `patrick.features`, et son
empreinte (`CODE_HASH`) n'entre dans la clé du cache que pour un run qui choisit l'un de ses modèles (`engine._features_payload`).
Hors de `DEFAULT_VOL_MODELS` : aucune empreinte de run existante ne change.

Même protocole anti-fuite que l'EGARCH (`vol_models.egarch_conditional_vol`) : paramètres estimés sur le train du pli, partie train reprise
du fit train seul, partie test par `.fix()` sur une série tronquée à la fin du pli ; HAR : coefficients estimés sur les seules lignes dont
la CIBLE (le lendemain) tombe avant la coupure.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from patrick.features import vol_models
from patrick.features._utils import safe_pct_change

MODELS = ("gjr", "aparch", "har")
CODE_HASH = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]


def _arch_family_vol(series: pd.Series, vol: str, name: str, fit_end_idx: int | None, test_end_idx: int | None) -> pd.Series:
    """Volatilité conditionnelle GJR-GARCH(1,1,1) (`vol="GARCH"`, o=1) ou APARCH(1,1,1). GJR : effet de levier (une baisse augmente plus
    la variance qu'une hausse) ; APARCH : levier et puissance estimée."""
    from arch import arch_model

    ret = (safe_pct_change(series).dropna() * 100)
    cutoff = vol_models._fit_cutoff_date(series, fit_end_idx)
    fit_ret = ret[ret.index < cutoff] if cutoff is not None else ret
    try:
        res = arch_model(fit_ret, vol=vol, p=1, o=1, q=1, dist="normal").fit(disp="off")
        if cutoff is None:
            return (res.conditional_volatility / 100).reindex(series.index).rename(name)
        ret_for_fix = ret
        if test_end_idx is not None:
            ret_for_fix = ret[ret.index <= series.index[min(test_end_idx, len(series) - 1)]]
        cv = arch_model(ret_for_fix, vol=vol, p=1, o=1, q=1, dist="normal").fix(res.params).conditional_volatility.copy()
        cv.loc[res.conditional_volatility.index] = res.conditional_volatility.values
        return (cv / 100).reindex(series.index).rename(name)
    except Exception as e:  # noqa: BLE001 -- arch raises arbitrary numerical errors on degenerate series; feature -> NaN
        print(f"  [WARN] {vol}: {str(e)[:100]}")
        return pd.Series(np.nan, index=series.index, name=name)


def gjr_conditional_vol(series: pd.Series, fit_end_idx: int | None = None, test_end_idx: int | None = None) -> pd.Series:
    return _arch_family_vol(series, "GARCH", "gjr_vol", fit_end_idx, test_end_idx)


def aparch_conditional_vol(series: pd.Series, fit_end_idx: int | None = None, test_end_idx: int | None = None) -> pd.Series:
    return _arch_family_vol(series, "APARCH", "aparch_vol", fit_end_idx, test_end_idx)


def har_vol(series: pd.Series, fit_end_idx: int | None = None) -> pd.Series:
    """Volatilité du lendemain prévue par HAR-RV (Corsi 2009) sur les rendements au carré : RV(t+1) = b0 + b1 RV(t) + b2 RV moyenne 5 j
    + b3 RV moyenne 22 j, par moindres carrés ; la valeur au jour t n'utilise que des rendements jusqu'à t."""
    ret = safe_pct_change(series)
    rv = ret * ret
    X = pd.concat({"d": rv, "w": rv.rolling(5).mean(), "m": rv.rolling(22).mean()}, axis=1)
    y = rv.shift(-1)
    cutoff = vol_models._fit_cutoff_date(series, fit_end_idx)
    target_day = pd.Series(series.index, index=series.index).shift(-1)
    rows = X.notna().all(axis=1) & y.notna()
    if cutoff is not None:
        rows &= target_day < cutoff
    if rows.sum() < 60:
        return pd.Series(np.nan, index=series.index, name="har_vol")
    A = np.column_stack([np.ones(int(rows.sum())), X[rows].to_numpy()])
    beta, *_ = np.linalg.lstsq(A, y[rows].to_numpy(), rcond=None)
    pred = beta[0] + X.to_numpy() @ beta[1:]
    return pd.Series(np.sqrt(np.clip(pred, 1e-12, None)), index=series.index, name="har_vol").where(X.notna().all(axis=1))


_OUTPUT_COLUMN = {"gjr": "gjr_vol", "aparch": "aparch_vol", "har": "har_vol"}


def register() -> None:
    """Ajoute les trois modèles au registre de `vol_models` (idempotent)."""
    vol_models._PARAMETRIC_MODELS.update({
        "gjr": lambda s, fit_end_idx, test_end_idx: gjr_conditional_vol(s, fit_end_idx=fit_end_idx, test_end_idx=test_end_idx).to_frame(),
        "aparch": lambda s, fit_end_idx, test_end_idx: aparch_conditional_vol(s, fit_end_idx=fit_end_idx, test_end_idx=test_end_idx).to_frame(),
        "har": lambda s, fit_end_idx, test_end_idx: har_vol(s, fit_end_idx=fit_end_idx).to_frame(),
    })
    vol_models._MODEL_OUTPUT_COLUMN.update(_OUTPUT_COLUMN)
    vol_models.PARAMETRIC_VOL_MODELS = frozenset(vol_models._PARAMETRIC_MODELS)


register()
