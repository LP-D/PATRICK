"""Moteur d'event study (MacKinlay 1997) pour les résultats : une annonce -> un dictionnaire de mesures stockable en JSON.

Rendements SIMPLES (pas logarithmiques) partout : le BHAR se compose, le modèle à facteurs est défini en rendements simples, et
« +4,2 % » se lit tel quel. Les cours sont ajustés des splits et des dividendes (le détachement d'un dividende dans la fenêtre
n'est donc pas un faux rendement négatif) ; les ouvertures, plus hauts et plus bas sont ajustés de la même façon.

Par événement, sur la trajectoire [-10, +60] séances autour de J0 (jour de réaction, `exchanges.day_zero`) :
- rendement attendu par un modèle estimé sur [-250, -30] (défaut) en EXCLUANT les séances proches d'une autre annonce du
  titre (sinon la variance résiduelle est gonflée) : `market` (OLS sur l'indice local, défaut), `market_adjusted` (bêta = 1),
  `factor` (marché, taille, value, momentum : bibliothèque French, Europe / US / Japon) ou `sector` (ETF sectoriel ou panier de
  pairs). Repli sur `market` si le modèle demandé n'a pas ses données, avec `model_used` pour le dire ;
- rendement anormal AR_t = R_t - E_t, CAR = somme, BHAR = produit(1+R) - produit(1+E) ;
- décomposition overnight (clôture -> ouverture) / intraday (ouverture -> clôture) ;
- volume anormal, illiquidité d'Amihud, spread de Corwin-Schultz, volatilité de Parkinson ;
- de quoi recalculer la variance d'un CAR sur N'IMPORTE QUELLE fenêtre sans refaire l'estimation (`xtx_inv`, `x_path`, `sigma`)
  et les tests de rang (`resid_est`, aligné jour relatif par jour relatif).
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd

from patrick.earnings import exchanges
from patrick.earnings.config import PATH_HI, PATH_LO, EarningsConfig

REL = np.arange(PATH_LO, PATH_HI + 1)
N_PATH = len(REL)
FACTOR_COLS = ("Mkt_RF", "SMB", "HML", "MOM")
_CS_K = 3 - 2 * math.sqrt(2)


def _rounded(values, digits: int = 6) -> list:
    return [None if (v is None or not np.isfinite(v)) else round(float(v), digits) for v in np.asarray(values, dtype=float)]


def corwin_schultz(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Spread relatif estimé (Corwin & Schultz 2012) à partir des plus hauts / plus bas de deux jours consécutifs ; un résultat
    négatif est ramené à 0 (usage courant). Valeur du jour t = estimation sur (t, t+1)."""
    h, l_ = np.asarray(high, float), np.asarray(low, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        hl = np.log(h / l_)
        beta = hl ** 2 + np.roll(hl, -1) ** 2
        hh = np.maximum(h, np.roll(h, -1))
        ll = np.minimum(l_, np.roll(l_, -1))
        gamma = np.log(hh / ll) ** 2
        alpha = (np.sqrt(2 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
        spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    spread[-1] = np.nan
    spread[(h <= 0) | (l_ <= 0) | (l_ > h)] = np.nan
    return np.maximum(spread, 0.0)


class SymbolPrices:
    """Tout ce qui se calcule UNE fois par titre (rendements, matrice du modèle, liquidité) et se découpe ensuite par événement."""

    def __init__(self, px: pd.DataFrame, bench_close: pd.Series | None = None, bench_open: pd.Series | None = None,
                 sector_close: pd.Series | None = None, factors: pd.DataFrame | None = None):
        px = px[~px.index.duplicated(keep="last")].sort_index()
        px = px[px["Close"].notna() & (px["Close"] > 0)]
        self.px = px
        self.idx = pd.DatetimeIndex(px.index).normalize()
        n = len(self.idx)
        close = px["Close"].astype(float)
        self.close = close.to_numpy()
        self.open = px["Open"].astype(float).to_numpy() if "Open" in px else self.close.copy()
        self.high = px["High"].astype(float).to_numpy() if "High" in px else self.close.copy()
        self.low = px["Low"].astype(float).to_numpy() if "Low" in px else self.close.copy()
        self.volume = px["Volume"].astype(float).to_numpy() if "Volume" in px else np.full(n, np.nan)
        self.dividends = px["Dividends"].astype(float).to_numpy() if "Dividends" in px else np.zeros(n)
        self.splits = px["Stock Splits"].astype(float).to_numpy() if "Stock Splits" in px else np.zeros(n)
        self.r = close.pct_change().to_numpy()
        prev = np.concatenate([[np.nan], self.close[:-1]])
        self.on = self.open / prev - 1
        self.id = self.close / self.open - 1
        self.rm = self._aligned_returns(bench_close)
        self.rs = self._aligned_returns(sector_close)
        self.on_m = self._aligned_overnight(bench_open, bench_close)
        self.factors = None
        if factors is not None and len(factors):
            f = factors.reindex(self.idx)
            cols = [c for c in FACTOR_COLS if c in f.columns and f[c].notna().mean() > 0.5]
            if {"Mkt_RF", "SMB", "HML"} <= set(cols) and "RF" in f.columns:
                self.factors = f[cols + ["RF"]].to_numpy(dtype=float)
                self.factor_cols = cols
        # liquidité
        dollar = self.close * self.volume
        with np.errstate(divide="ignore", invalid="ignore"):
            self.amihud = np.where(dollar > 0, np.abs(self.r) / dollar * 1e6, np.nan)
        self.cs = corwin_schultz(self.high, self.low)
        with np.errstate(divide="ignore", invalid="ignore"):
            self.rv = np.where((self.high > 0) & (self.low > 0), np.log(self.high / self.low) ** 2 / (4 * math.log(2)), np.nan)
        self.dollar_vol = dollar
        self._design_cache: dict[str, tuple] = {}

    def _aligned_returns(self, series: pd.Series | None) -> np.ndarray | None:
        if series is None or len(series) < 30:
            return None
        s = pd.Series(series).astype(float)
        s.index = pd.DatetimeIndex(s.index).normalize()
        s = s[~s.index.duplicated(keep="last")].sort_index()
        level = s.reindex(self.idx.union(s.index)).ffill().reindex(self.idx)
        r = level.pct_change().to_numpy()
        return r if np.isfinite(r).mean() > 0.05 else None        # lacunes : les événements sans estimation valable sont écartés, pas lissés

    def _aligned_overnight(self, bench_open: pd.Series | None, bench_close: pd.Series | None) -> np.ndarray | None:
        if bench_open is None or bench_close is None:
            return None
        o = pd.Series(bench_open).astype(float)
        c = pd.Series(bench_close).astype(float)
        o.index, c.index = pd.DatetimeIndex(o.index).normalize(), pd.DatetimeIndex(c.index).normalize()
        o, c = o[~o.index.duplicated()], c[~c.index.duplicated()]
        on = (o / c.shift(1) - 1).reindex(self.idx)
        return on.to_numpy() if on.notna().mean() > 0.5 else None

    # ------------------------------------------------------------------------------------------------------- modèles
    def design(self, model: str) -> tuple[str, np.ndarray, np.ndarray | None]:
        """(modèle réellement utilisé, y, X) sur tout l'historique. `X` None = pas de régression (bêta = 1, sans constante)."""
        if model in self._design_cache:
            return self._design_cache[model]
        n = len(self.idx)
        ones = np.ones(n)
        used, y, X = "market", self.r, None
        if model == "market_adjusted" and self.rm is not None:
            used, y, X = "market_adjusted", self.r - self.rm, None
        elif model == "factor" and self.factors is not None:
            cols = self.factor_cols
            f = self.factors
            used = "factor"
            y = self.r - np.nan_to_num(f[:, -1], nan=0.0)
            X = np.column_stack([ones, *[f[:, i] for i in range(len(cols))]])
        elif model == "sector" and self.rs is not None:
            used, y, X = "sector", self.r, np.column_stack([ones, self.rs])
        elif self.rm is not None:
            used, y, X = "market", self.r, np.column_stack([ones, self.rm])
        else:
            used, y, X = "constant", self.r, ones.reshape(-1, 1)         # sans indice : moyenne constante, dit comme tel
        self._design_cache[model] = (used, y, X)
        return self._design_cache[model]


def _winsor_series(x: np.ndarray, q: float) -> np.ndarray:
    if q <= 0 or not np.isfinite(x).any():
        return x
    lo, hi = np.nanquantile(x, [q, 1 - q])
    return np.clip(x, lo, hi)


def compute_event(sp: SymbolPrices, *, symbol: str, ann_date, timing: str, uncertain: bool, cfg: EarningsConfig,
                  other_days: list[pd.Timestamp] | None = None, timing_source: str = "", eps: dict | None = None
                  ) -> tuple[dict | None, str]:
    """Mesures d'un événement ; `(None, raison)` si l'historique de prix ne permet pas de le traiter."""
    d0 = exchanges.day_zero(ann_date, timing, sp.idx)
    if d0 is None:
        return None, "annonce postérieure au dernier cours (événement à venir)"
    i0 = int(sp.idx.get_loc(d0))
    n = len(sp.idx)
    e_lo, e_hi = i0 + cfg.est_window[0], i0 + cfg.est_window[1]
    if e_hi < 5:
        return None, "historique de prix trop court avant l'annonce"
    e_lo = max(e_lo, 1)

    used, y, X = sp.design(cfg.model)
    mask = np.zeros(n, dtype=bool)
    mask[e_lo:e_hi + 1] = True
    for od in other_days or []:
        if od == d0 or od not in sp.idx:
            continue
        j = int(sp.idx.get_loc(od))
        mask[max(j - cfg.est_exclude, 0):j + cfg.est_exclude + 1] = False
    mask &= np.isfinite(y)
    if X is not None:
        mask &= np.isfinite(X).all(axis=1)
    n_est = int(mask.sum())
    if n_est < cfg.min_est_obs:
        return None, f"estimation insuffisante ({n_est} séances < {cfg.min_est_obs})"

    if X is None:
        beta, k = np.zeros(0), 0
        resid = y[mask]
        xtx_inv = np.zeros((0, 0))
        dof = n_est
    else:
        Xe, ye = X[mask], y[mask]
        beta, *_ = np.linalg.lstsq(Xe, ye, rcond=None)
        resid = ye - Xe @ beta
        k = Xe.shape[1]
        xtx_inv = np.linalg.pinv(Xe.T @ Xe)
        dof = max(n_est - k, 1)
    sigma = float(np.sqrt((resid ** 2).sum() / dof))

    pos = i0 + REL
    valid_pos = (pos >= 0) & (pos < n)
    p = np.where(valid_pos, pos, 0)
    ar = np.where(valid_pos, y[p] - (X[p] @ beta if X is not None else 0.0), np.nan)
    if not np.isfinite(ar[rel_index(0)]) and cfg.model != "market" and used != "market":
        # les facteurs French sont publiés avec 1 à 2 mois de retard : pour une annonce récente le modèle à facteurs n'a pas
        # ses données le jour J0. Repli sur le modèle de marché, signalé dans `model_used` / `model_fallback`.
        fallback, why = compute_event(sp, symbol=symbol, ann_date=ann_date, timing=timing, uncertain=uncertain,
                                      cfg=replace(cfg, model="market"), other_days=other_days, timing_source=timing_source, eps=eps)
        if fallback is not None:
            fallback["model_req"], fallback["model_fallback"] = cfg.model, True
        return fallback, why
    ret = np.where(valid_pos, sp.r[p], np.nan)
    er = ret - ar
    x_path = [None if (X is None or not valid_pos[j] or not np.isfinite(X[p[j]]).all()) else _rounded(X[p[j]], 6)
              for j in range(N_PATH)]

    # bêta de marché descriptif (même si le modèle est autre) : structure, bêta élevé = réaction plus ample
    beta_mkt = np.nan
    if sp.rm is not None:
        m2 = mask & np.isfinite(sp.rm) & np.isfinite(sp.r)
        if m2.sum() > 30 and np.nanvar(sp.rm[m2]) > 0:
            beta_mkt = float(np.cov(sp.r[m2], sp.rm[m2])[0, 1] / np.var(sp.rm[m2], ddof=1))

    vol_mean = np.nanmean(np.where(mask, sp.volume, np.nan)) if np.isfinite(sp.volume[mask]).any() else np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        vol_ratio = np.where(valid_pos & (vol_mean > 0), sp.volume[p] / vol_mean, np.nan)
    am_est = float(np.nanmean(np.where(mask, sp.amihud, np.nan))) if np.isfinite(sp.amihud[mask]).any() else np.nan
    cs_est = float(np.nanmean(np.where(mask, sp.cs, np.nan))) if np.isfinite(sp.cs[mask]).any() else np.nan
    rv_est = float(np.nanmean(np.where(mask, sp.rv, np.nan))) if np.isfinite(sp.rv[mask]).any() else np.nan
    dollar_est = float(np.nanmean(np.where(mask, sp.dollar_vol, np.nan))) if np.isfinite(sp.dollar_vol[mask]).any() else np.nan
    on = np.where(valid_pos, sp.on[p], np.nan)
    idr = np.where(valid_pos, sp.id[p], np.nan)
    on_abn = np.full(N_PATH, np.nan)
    if sp.on_m is not None and np.isfinite(beta_mkt):
        on_abn = np.where(valid_pos, sp.on[p] - beta_mkt * sp.on_m[p], np.nan)

    lo_hist = max(i0 - 250, 0)
    mom_pre = float(sp.close[max(e_hi, 0)] / sp.close[lo_hist] - 1) if e_hi > lo_hist else np.nan
    win_all = slice(max(i0 - 250, 0), min(i0 + PATH_HI + 1, n))
    win_div = slice(max(i0 + PATH_LO, 0), min(i0 + PATH_HI + 1, n))

    # diagnostic de timing (affichage seulement, jamais une règle de sélection : choisir le jour du plus gros mouvement
    # biaiserait la réaction vers le haut). Le jour alternatif est J+1 si l'annonce est dite avant l'ouverture, J-1 si après.
    alt_ratio, suspect = np.nan, False
    if timing in ("BMO", "AMC") and sigma > 0:
        alt = REL.tolist().index(1 if timing == "BMO" else -1)
        a0, a1 = abs(ar[REL.tolist().index(0)]), abs(ar[alt])
        if np.isfinite(a0) and np.isfinite(a1):
            alt_ratio = float(a1 / a0) if a0 > 0 else np.inf
            suspect = bool(a1 > 2 * a0 and a1 > 3 * sigma)

    resid_full = np.full(cfg.est_window[1] - cfg.est_window[0] + 1, np.nan)
    rel_est = np.arange(max(cfg.est_window[0], 1 - i0), cfg.est_window[1] + 1)
    full_pos = i0 + rel_est
    ok = (full_pos >= 0) & (full_pos < n)
    if ok.any():
        fp = full_pos[ok]
        res_all = np.full(n, np.nan)
        res_all[mask] = resid
        resid_full[rel_est[ok] - cfg.est_window[0]] = res_all[fp]

    react = (0, 1) if (uncertain or timing in ("DURING", "UNKNOWN")) else (0, 0)
    payload = {
        "symbol": symbol, "ann_date": str(pd.Timestamp(ann_date).date()), "timing": timing, "uncertain": bool(uncertain),
        "timing_source": timing_source, "day0": str(d0.date()), "react": list(react),
        "model_req": cfg.model, "model_used": used, "model_fallback": False, "factor_cols": getattr(sp, "factor_cols", None) if used == "factor" else None,
        "n_est": n_est, "k": k, "sigma": sigma, "beta_mkt": beta_mkt, "ret_vol_est": float(np.nanstd(sp.r[mask])),
        "mom_pre": mom_pre, "dollar_vol_est": dollar_est, "vol_mean_est": vol_mean, "amihud_est": am_est, "cs_est": cs_est,
        "rv_est": rv_est, "n_post": int(np.isfinite(ar[REL > 0]).sum()),
        "ar": _rounded(ar), "er": _rounded(er), "ret": _rounded(ret), "on": _rounded(on), "id": _rounded(idr),
        "on_abn": _rounded(on_abn), "vol_ratio": _rounded(vol_ratio, 4),
        "amihud": _rounded(np.where(valid_pos, sp.amihud[p], np.nan), 5), "cs": _rounded(np.where(valid_pos, sp.cs[p], np.nan), 5),
        "rv": _rounded(np.where(valid_pos, sp.rv[p], np.nan), 7),
        "xtx_inv": [] if k == 0 else _rounded(xtx_inv.reshape(-1), 8), "x_path": x_path, "resid_est": _rounded(resid_full, 5),
        "split_flag": bool(np.any(np.nan_to_num(sp.splits[win_all]) != 0)),
        "ex_div_flag": bool(np.any(sp.dividends[win_div] > 0)),
        "diag_alt_ratio": None if not np.isfinite(alt_ratio) else (round(alt_ratio, 3) if alt_ratio != np.inf else 999.0),
        "timing_suspect": suspect,
        "eps_estimate": (eps or {}).get("eps_estimate"), "eps_actual": (eps or {}).get("eps_actual"),
        "surprise_pct": (eps or {}).get("surprise_pct"),
    }
    return payload, ""


# ---------------------------------------------------------------------------------------------- lecture d'une trajectoire

def rel_index(rel: int) -> int:
    return rel - PATH_LO


def arr(payload: dict, key: str) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in payload[key]], dtype=float)


def window_sum(path: np.ndarray, a: int, b: int) -> float:
    """Somme d'une trajectoire sur les jours relatifs [a, b] ; NaN si un jour manque (fenêtre postérieure pas encore écoulée)."""
    if a < PATH_LO or b > PATH_HI or a > b:
        raise ValueError(f"fenêtre [{a}, {b}] hors de la trajectoire stockée [{PATH_LO}, {PATH_HI}]")
    seg = path[rel_index(a):rel_index(b) + 1]
    return float(seg.sum()) if np.isfinite(seg).all() else np.nan


def window_compound(path: np.ndarray, a: int, b: int) -> float:
    """Produit (1 + x) - 1 sur [a, b] (rendements composés) ; NaN si un jour manque."""
    seg = path[rel_index(a):rel_index(b) + 1]
    return float(np.prod(1 + seg) - 1) if np.isfinite(seg).all() else np.nan


def bhar(payload: dict, a: int, b: int) -> float:
    """BHAR = produit(1 + R) - produit(1 + E[R]) sur [a, b] : rendement composé du titre moins celui attendu par le modèle."""
    return window_compound(arr(payload, "ret"), a, b) - window_compound(arr(payload, "er"), a, b)


def car_variance(payload: dict, a: int, b: int) -> float:
    """Variance du CAR[a, b] avec la correction d'erreur de prévision : sigma^2 (L + s' (X'X)^-1 s), s = somme des lignes de X."""
    length = b - a + 1
    sigma2 = payload["sigma"] ** 2
    k = payload["k"]
    if k == 0:
        return sigma2 * length
    rows = payload["x_path"][rel_index(a):rel_index(b) + 1]
    if any(r is None for r in rows):
        return np.nan
    s = np.sum(np.array(rows, dtype=float), axis=0)
    xtx_inv = np.array(payload["xtx_inv"], dtype=float).reshape(k, k)
    return float(sigma2 * (length + s @ xtx_inv @ s))


def reaction_window(payload: dict, cfg: EarningsConfig) -> tuple[int, int]:
    if cfg.reaction == "d0":
        return (0, 0)
    if cfg.reaction == "d01":
        return (0, 1)
    return tuple(payload["react"])


def reaction_stats(payload: dict, cfg: EarningsConfig) -> dict:
    """Réaction immédiate d'un événement : CAR, mouvement absolu, exprimé en écarts-types quotidiens du titre (z)."""
    a, b = reaction_window(payload, cfg)
    ar = arr(payload, "ar")
    car = window_sum(ar, a, b)
    raw = window_compound(arr(payload, "ret"), a, b)
    sigma = payload["sigma"]
    var = car_variance(payload, a, b)
    return {"window": (a, b), "car": car, "raw": raw, "abs": abs(car) if np.isfinite(car) else np.nan,
            "z": car / math.sqrt(var) if np.isfinite(var) and var > 0 else np.nan,
            "z_abs_sigma": abs(car) / sigma if sigma > 0 and np.isfinite(car) else np.nan}


def winsorized(values, q: float) -> np.ndarray:
    return _winsor_series(np.asarray(values, dtype=float), q)
