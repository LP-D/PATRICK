"""Socle des cartes d'étude : registre, contexte, constructeurs de blocs de restitution, outils statistiques communs.

Une carte = une fonction `run(ctx, params) -> dict` enregistrée par `@study(...)`. Son résultat est un dictionnaire JSON :
`status` (ok | insufficient | unavailable | error), `n`, `reliability`, `blocks` (table, kv, line, bars, note), `pvalues`
(alimentent le registre FDR), `flags`. Les textes du résultat sont des données du domaine (français), comme les messages de
`i18n_server` ; les titres et explications de carte sont des clés i18n.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from patrick.earnings import pipeline
from patrick.earnings.config import EarningsConfig
from patrick.earnings.panel import Panel, Scope
from patrick.earnings.reliability import reliability

GROUPS = ("core", "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M", "P")
GROUP_TITLES = {
    "core": "Event study (cœur)", "A": "Anatomie de la réaction", "B": "Volatilité autour de l'événement",
    "C": "Liquidité et microstructure", "D": "Surprise et dérive post-annonce", "E": "Anticipation et fuite d'information",
    "F": "Sentiment : news, analystes, texte", "G": "Transmission entre titres et vers l'indice", "H": "Régimes",
    "I": "Facteurs, style et structure", "J": "Calendrier, biais et timing", "K": "Tradabilité et stratégies",
    "L": "Estimation probabiliste et petit échantillon", "M": "Robustesse méthodologique", "P": "Modèle prédictif",
}


@dataclass(frozen=True)
class Param:
    key: str
    kind: str                       # int | float | choice | bool
    default: object
    label: str
    choices: tuple = ()
    lo: float | None = None
    hi: float | None = None

    def coerce(self, raw):
        if raw is None or raw == "":
            return self.default
        if self.kind == "int":
            val = int(raw)
        elif self.kind == "float":
            val = float(raw)
        elif self.kind == "bool":
            val = raw in (True, "1", "true", "on", "yes", 1)
        else:
            val = str(raw)
            if self.choices and val not in self.choices:
                raise ValueError(f"{self.key} : {val!r} n'est pas parmi {self.choices}")
            return val
        if self.lo is not None and val < self.lo or self.hi is not None and val > self.hi:
            raise ValueError(f"{self.key} : {val} hors de [{self.lo}, {self.hi}]")
        return val


@dataclass(frozen=True)
class Study:
    id: str
    group: str
    title: str
    blurb: str
    run: Callable
    params: tuple[Param, ...] = ()
    needs: tuple[str, ...] = ()     # prices | news | snapshots | analysts (ce que l'étude lit hors du panel)
    heavy: bool = False
    default_on: bool = True

    def resolve_params(self, given: dict | None) -> dict:
        given = given or {}
        return {p.key: p.coerce(given.get(p.key)) for p in self.params}


REGISTRY: dict[str, Study] = {}


def study(id: str, group: str, title: str, blurb: str, params: tuple[Param, ...] = (), needs: tuple[str, ...] = (),
          heavy: bool = False, default_on: bool = True):
    def deco(fn):
        if id in REGISTRY:
            raise ValueError(f"étude déjà enregistrée : {id}")
        REGISTRY[id] = Study(id, group, title, blurb, fn, params, needs, heavy, default_on)
        return fn
    return deco


# --------------------------------------------------------------------------------------------------------------- contexte

class PriceBook:
    """Prix bruts et `SymbolPrices` à la demande (cache du fournisseur) pour les études qui doivent recalculer ou lire des séries."""

    def __init__(self, conn, provider, cfg: EarningsConfig):
        from patrick.earnings.engine import SymbolPrices
        self._SymbolPrices = SymbolPrices
        self.conn, self.provider, self.cfg = conn, provider, cfg
        self.shared = pipeline.SharedData(provider, cfg)
        self._sp: dict[tuple, object] = {}

    def raw(self, symbol: str) -> pd.DataFrame | None:
        return self.shared.frame(symbol)

    def benchmark(self, symbol: str) -> tuple[str, pd.DataFrame | None]:
        px = self.raw(symbol)
        return self.shared.benchmark(symbol, px.index if px is not None else None)

    def prices(self, symbol: str, model: str | None = None):
        model = model or self.cfg.model
        key = (symbol, model)
        if key not in self._sp:
            from patrick.earnings import exchanges, store
            px = self.raw(symbol)
            if px is None:
                self._sp[key] = None
            else:
                _, bench = self.benchmark(symbol)
                info = store.get_instrument(self.conn, symbol) or {}
                sector = pipeline.sector_series(self.shared, self.conn, symbol, info) if model == "sector" else None
                region = exchanges.venue_for(symbol).region
                factors = self.provider.factors(region) if model == "factor" and region in ("US", "EU", "JP") else None
                self._sp[key] = self._SymbolPrices(px, bench["Close"] if bench is not None else None,
                                                   bench["Open"] if bench is not None else None, sector, factors)
        return self._sp[key]


@dataclass
class Ctx:
    panel: Panel                    # périmètre demandé
    full: Panel                     # tout l'univers (références sectorielles, régimes)
    conn: object
    provider: object
    cfg: EarningsConfig
    scope: Scope = field(default_factory=Scope)
    batch_symbols: list[str] = field(default_factory=list)
    now: pd.Timestamp = field(default_factory=pd.Timestamp.now)
    prices: PriceBook | None = None
    memo: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.prices is None:
            self.prices = PriceBook(self.conn, self.provider, self.cfg)

    @property
    def df(self) -> pd.DataFrame:
        return self.panel.frame


# ------------------------------------------------------------------------------------------------------ résultats et blocs

def ok(blocks: list[dict], n: int, *, pvalues: dict | None = None, rel: dict | None = None, flags: list[str] | None = None) -> dict:
    return {"status": "ok", "n": int(n), "blocks": blocks, "pvalues": {k: float(v) for k, v in (pvalues or {}).items()
                                                                       if v is not None and np.isfinite(v)},
            "reliability": rel, "flags": flags or []}


def insufficient(n: int, needed: int, what: str = "événements") -> dict:
    return {"status": "insufficient", "n": int(n), "blocks": [], "pvalues": {}, "reliability": None, "flags": [],
            "reason": f"N insuffisant : {n} {what} pour {needed} requis"}


def unavailable(reason: str, needs: str = "") -> dict:
    return {"status": "unavailable", "n": 0, "blocks": [], "pvalues": {}, "reliability": None, "flags": [], "reason": reason,
            "needs": needs}


def table(title: str, columns: list[str], rows: list[list], kinds: list[str] | None = None, n_col: int | None = None,
          note: str = "") -> dict:
    return {"type": "table", "title": title, "columns": columns, "rows": rows, "kinds": kinds or ["str"] * len(columns),
            "n_col": n_col, "note": note}


def kv(title: str, items: list[tuple[str, object, str]]) -> dict:
    """items : (libellé, valeur, nature de format)."""
    return {"type": "kv", "title": title, "items": [{"label": a, "value": b, "kind": c} for a, b, c in items]}


def line(title: str, x: list, series: list[dict], x_label: str = "", y_kind: str = "pct", band: dict | None = None) -> dict:
    """series : [{"name", "y": [...]}] ; band : {"lo": [...], "hi": [...]} autour de la première série."""
    return {"type": "line", "title": title, "x": list(x), "series": series, "x_label": x_label, "y_kind": y_kind, "band": band}


def bars(title: str, labels: list[str], values: list[float], kind: str = "pct") -> dict:
    return {"type": "bars", "title": title, "labels": labels, "values": [None if v is None or not np.isfinite(v) else float(v)
                                                                          for v in values], "kind": kind}


def note(text: str, level: str = "info") -> dict:
    return {"type": "note", "text": text, "level": level}


# ---------------------------------------------------------------------------------------------------------- outils communs

def describe(x) -> dict:
    a = np.asarray(x, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) == 0:
        return {"n": 0}
    q = np.quantile(a, [0.05, 0.25, 0.5, 0.75, 0.95])
    return {"n": len(a), "mean": float(a.mean()), "median": float(q[2]), "sd": float(a.std(ddof=1)) if len(a) > 1 else np.nan,
            "skew": float(stats.skew(a)) if len(a) > 2 else np.nan, "kurt": float(stats.kurtosis(a)) if len(a) > 3 else np.nan,
            "q05": float(q[0]), "q25": float(q[1]), "q75": float(q[3]), "q95": float(q[4])}


def spearman(x, y) -> tuple[float, float, int]:
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    ok_ = np.isfinite(a) & np.isfinite(b)
    if ok_.sum() < 5 or np.nanstd(a[ok_]) == 0 or np.nanstd(b[ok_]) == 0:
        return np.nan, np.nan, int(ok_.sum())
    rho, p = stats.spearmanr(a[ok_], b[ok_])
    return float(rho), float(p), int(ok_.sum())


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return np.nan, np.nan
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return float(c - h), float(c + h)


def mann_whitney(a, b) -> float:
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 3 or len(b) < 3:
        return np.nan
    return float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)


def kruskal(groups: list[np.ndarray]) -> float:
    groups = [np.asarray(g, dtype=float)[np.isfinite(g)] for g in groups]
    groups = [g for g in groups if len(g) >= 3]
    if len(groups) < 2:
        return np.nan
    try:
        return float(stats.kruskal(*groups).pvalue)
    except ValueError:
        return np.nan


def cluster_ols(y, X, clusters, names: list[str]) -> dict:
    """MCO avec écarts-types robustes groupés (par semaine de J0 : les annonces d'une même semaine ne sont pas indépendantes).
    Renvoie coefficients, t, p, R², N. Sans statsmodels : formule sandwich directe."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    if X.ndim == 1:
        X = X.reshape(-1, 1)
    ok_ = np.isfinite(y) & np.isfinite(X).all(axis=1)
    y, X, cl = y[ok_], X[ok_], np.asarray(clusters)[ok_]
    n, k = X.shape
    if n <= k + 2:
        return {"n": n, "coef": {}, "t": {}, "p": {}, "r2": np.nan}
    xtx_inv = np.linalg.pinv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    meat = np.zeros((k, k))
    groups = pd.Series(range(n)).groupby(cl).indices
    for idx in groups.values():
        s = X[idx].T @ resid[idx]
        meat += np.outer(s, s)
    g = len(groups)
    corr = (g / max(g - 1, 1)) * ((n - 1) / max(n - k, 1))
    cov = corr * xtx_inv @ meat @ xtx_inv
    se = np.sqrt(np.clip(np.diag(cov), 1e-300, None))
    t = beta / se
    dof = max(g - 1, 1)
    p = 2 * stats.t.sf(np.abs(t), dof)
    ss_tot = ((y - y.mean()) ** 2).sum()
    return {"n": n, "coef": dict(zip(names, beta.tolist())), "t": dict(zip(names, t.tolist())), "p": dict(zip(names, p.tolist())),
            "r2": float(1 - (resid ** 2).sum() / ss_tot) if ss_tot > 0 else np.nan, "n_clusters": g}


def group_rows(df: pd.DataFrame, by: str, value_cols: list[str], min_n: int = 1) -> list[list]:
    """Une ligne par modalité de `by` : N puis moyenne de chaque colonne de valeurs, triées par N décroissant."""
    out = []
    for key, part in df.groupby(by, dropna=False):
        if len(part) >= min_n:
            out.append([str(key), len(part), *[float(part[c].mean()) for c in value_cols]])
    return sorted(out, key=lambda r: -r[1])


def rel_for(ctx: Ctx, df: pd.DataFrame, col: str) -> dict:
    return reliability(df[col].to_numpy() if col in df else None, n=len(df), day0=df["day0"] if "day0" in df and len(df) else None,
                       min_events=ctx.cfg.min_events)


def need(ctx: Ctx, minimum: int, df: pd.DataFrame | None = None) -> dict | None:
    d = ctx.df if df is None else df
    return insufficient(len(d), minimum) if len(d) < minimum else None


GROUP_BY_CHOICES = ("all", "symbol", "sector", "country", "year", "timing", "regime", "vix_t")


def groups_of(df: pd.DataFrame, by: str, max_groups: int = 60) -> list[tuple[str, pd.DataFrame]]:
    """Découpage d'un panel par modalité (« all » = un seul groupe), du plus gros groupe au plus petit."""
    if by == "all" or by not in df.columns:
        return [("Tous", df)]
    parts = [("inconnu" if pd.isna(k) else str(k), g) for k, g in df.groupby(by, dropna=False)]
    return sorted(parts, key=lambda kg: -len(kg[1]))[:max_groups]


def prepare(ctx: Ctx, df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Ajoute la colonne de régime HMM (`regime`) ou de tercile du VIX (`vix_t`) quand on groupe par elle : toutes les statistiques des
    cartes se conditionnent ainsi au régime, comme demandé (§3.H), avec le régime connu AVANT la réaction."""
    if by in ("regime", "vix_t"):
        from patrick.earnings.studies.cross import market_state
        return df.assign(**{by: df["i"].map(market_state(ctx)[by])})
    return df


def fmt_ci(lo: float, hi: float) -> str:
    return "—" if not (np.isfinite(lo) and np.isfinite(hi)) else f"[{lo * 100:.0f} ; {hi * 100:.0f}] %"
