"""Analyse complète et automatique d'un jeu de fonds : le notebook PEE rendu rejouable sur n'importe quelles VL importées.

`analyse(navs, labels, cash, params)` enchaîne :
1. contrôle des séries et choix des fenêtres d'étude (`choose_windows`) ;
2. statistiques de chaque fonds (12 mois, 5 ans, chaque fenêtre, historique complet), corrélations ;
3. pour chaque fenêtre x objectif x plafond : allocation optimale, indicateurs, validation walk-forward face au 1/N, scénarios à N ans ;
4. scénarios à N ans de chaque fonds pris seul ;
5. un classement des allocations (par défaut sur le Sharpe HORS ÉCHANTILLON : le seul critère qui ne récompense pas le sur-ajustement) ;
6. pour chaque allocation, l'épargne RÉELLE dans l'enveloppe choisie : versements programmés, abondement, frais, prélèvements sociaux et impôts
   de sortie, projetés (bootstrap des mois observés) et rejoués sur l'histoire (TRI) ; contribution de chaque support au risque ;
7. la frontière efficiente sous contraintes, l'allocation actuelle (avoirs saisis) placée sur la même carte, la même épargne comparée d'une
   enveloppe à l'autre ;
8. les mises en garde (historique court, fonds périmé, GARCH non fiable…).

Contraintes : bornes de poids par support, parts minimales ou maximales par catégorie (« fonds en euros au moins 30 % »), plafond général.

Le résultat est un dictionnaire JSON (nombres Python, NaN -> None). Rien ici ne recommande d'acheter ou de vendre : ce sont des allocations
historiquement optimales selon un critère, avec la façon dont elles se comportent hors échantillon.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from patrick.placements import envelopes, optimize, projection, scenarios, stats

CASH_FIXED = "cash_fixe"
MIN_RISKY = 2
MIN_WINDOW_MONTHS = 36
RECENT_MIN_MONTHS = 72         # fenêtre récente par défaut : 5 ans d'apprentissage + au moins 1 an de test
STALE_DAYS = 60
MAX_WINDOWS = 3
RESULT_VERSION = 2
MAX_HORIZON = 40
PROJECTION_PATHS = 3000


class AnalysisError(ValueError):
    """Analyse impossible avec ces données : le message (en français) dit quoi corriger."""


@dataclass
class Params:
    amount: float = 10_000.0
    horizon_years: int = 5
    objectives: tuple[str, ...] = optimize.DEFAULT_OBJECTIVES
    caps: tuple[float, ...] = (1.0, 0.4)
    methods: tuple[str, ...] = tuple(scenarios.METHODS)
    n_sims: int = scenarios.N_SIMS
    windows: tuple[str, ...] = ()              # débuts de fenêtre (ISO) ; vide = choix automatique
    min_months: int = 24                       # historique mensuel minimal d'un fonds pour entrer dans une fenêtre
    reopt_months: int = 12
    min_train: int = 60
    k_starts: int = optimize.N_STARTS
    daily_from: str = "2015-01-01"             # les VL hebdomadaires des premières années fausseraient le drawdown quotidien
    rf_annual: float = 0.02                    # taux sans risque de repli si aucun fonds monétaire n'est désigné
    labels: dict[str, str] = field(default_factory=dict)
    bounds: dict[str, tuple[float, float]] = field(default_factory=dict)     # bornes de poids par support
    groups: list[tuple[list[str], float, float, str]] = field(default_factory=list)   # (supports, min, max, libellé)
    envelope: dict = field(default_factory=lambda: envelopes.normalise("none"))
    contrib: dict | None = None                # versements ; None = un seul versement initial du montant
    euro_keys: tuple[str, ...] = ()
    holdings: dict[str, float] = field(default_factory=dict)
    couple: bool = False

    def validate(self) -> None:
        if not 1 <= self.horizon_years <= MAX_HORIZON:
            raise AnalysisError(f"L'horizon doit être compris entre 1 et {MAX_HORIZON} ans.")
        if not self.objectives or any(o not in optimize.OPTIMIZERS for o in self.objectives):
            raise AnalysisError("Objectif d'optimisation inconnu.")
        if not self.caps or any(not 0.05 <= c <= 1.0 for c in self.caps):
            raise AnalysisError("Un plafond par fonds doit être compris entre 5 % et 100 %.")
        if not self.methods or any(m not in scenarios.METHODS for m in self.methods):
            raise AnalysisError("Méthode de scénario inconnue.")
        if not 1000 <= self.n_sims <= 100_000:
            raise AnalysisError("Le nombre de simulations doit être compris entre 1 000 et 100 000.")
        if not 12 <= self.min_train <= 240 or not 1 <= self.reopt_months <= 60:
            raise AnalysisError("Fenêtre d'apprentissage ou fréquence de réoptimisation hors limites.")
        if len(self.windows) > MAX_WINDOWS:
            raise AnalysisError(f"Au plus {MAX_WINDOWS} fenêtres d'étude.")


def _num(x: Any) -> Any:
    """JSON : nombres Python, NaN et infinis -> None, tableaux et séries -> listes."""
    if isinstance(x, dict):
        return {str(k): _num(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_num(v) for v in x]
    if isinstance(x, (pd.Series, np.ndarray)):
        return [_num(v) for v in list(x)]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        f = float(x)
        return f if math.isfinite(f) else None
    if isinstance(x, (pd.Timestamp, datetime)):
        return x.date().isoformat()
    return x


def with_cash(navs: pd.DataFrame, cash: str | None, rf_annual: float) -> tuple[pd.DataFrame, str]:
    """Garantit une colonne de monétaire : celle désignée, sinon une VL synthétique qui croît au taux sans risque de repli."""
    if cash is not None and cash in navs.columns:
        return navs, cash
    days = (navs.index - navs.index[0]).days.to_numpy()
    out = navs.copy()
    out[CASH_FIXED] = (1 + rf_annual) ** (days / 365.25)
    return out, CASH_FIXED


def candidate_windows(r_all: pd.DataFrame, cash: str, min_months: int = 24) -> list[dict]:
    """Les débuts de fenêtre possibles : le premier mois de chaque fonds (et du monétaire), avec ce que la fenêtre contient."""
    starts = sorted({r_all[c].first_valid_index() for c in r_all.columns if r_all[c].first_valid_index() is not None})
    out = []
    for s in starts:
        panel = _panel(r_all, s, cash, min_months)
        if panel is None:
            continue
        risky = [c for c in panel.columns if c != cash]
        out.append({"start": s.date().isoformat(), "months": len(panel), "funds": len(risky), "excluded": sorted(set(r_all.columns) - set(panel.columns))})
    return out


def _panel(r_all: pd.DataFrame, start: pd.Timestamp, cash: str, min_months: int) -> pd.DataFrame | None:
    """Rendements mensuels depuis `start` : les fonds qui ont au moins `min_months` mois puis aucun trou (le monétaire est toujours requis)."""
    sub = r_all.loc[start:]
    if cash not in sub.columns or sub[cash].isna().any():
        return None
    available = sub.notna().sum()
    cols = [c for c in sub.columns if c == cash or available[c] >= min_months]
    panel = sub[cols].dropna(axis=1, how="any")
    if cash not in panel.columns or len([c for c in panel.columns if c != cash]) < MIN_RISKY or len(panel) < MIN_WINDOW_MONTHS:
        return None
    return panel


def choose_windows(r_all: pd.DataFrame, cash: str, requested: tuple[str, ...], min_months: int) -> list[tuple[str, pd.DataFrame]]:
    """Les fenêtres d'étude `(étiquette, panel)`.

    Par défaut : une fenêtre LONGUE, depuis le premier mois où le monétaire existe (le plus d'histoire commune possible), et une fenêtre
    RÉCENTE, la plus récente qui laisse au moins 6 ans de données (5 ans d'apprentissage + 1 an de test) pour inclure des fonds plus jeunes.
    `requested` impose les débuts (une date est ramenée à la fin de son mois)."""
    if requested:
        starts = [pd.Timestamp(s) + pd.offsets.MonthEnd(0) for s in requested]
    else:
        cash_start = r_all[cash].first_valid_index()
        if cash_start is None:
            raise AnalysisError("Le fonds monétaire n'a aucun rendement mensuel exploitable.")
        starts = [cash_start]
        recent = [pd.Timestamp(c["start"]) for c in candidate_windows(r_all, cash, min_months)
                  if c["months"] >= RECENT_MIN_MONTHS and pd.Timestamp(c["start"]) > cash_start + pd.offsets.MonthEnd(11)]
        if recent:
            starts.append(max(recent))
    out: list[tuple[str, pd.DataFrame]] = []
    for s in sorted(set(starts)):
        panel = _panel(r_all, s, cash, min_months)
        if panel is None:
            raise AnalysisError(f"La fenêtre depuis {s.date().isoformat()} ne contient pas assez de fonds ou de mois "
                                f"(au moins {MIN_RISKY} fonds risqués et {MIN_WINDOW_MONTHS} mois avec le monétaire).")
        out.append((f"{panel.index[0].date().isoformat()}", panel))
    if not out:
        raise AnalysisError("Aucune fenêtre d'étude exploitable.")
    return out


def _growth(returns: pd.Series) -> list[float]:
    return [100.0, *[float(v) for v in 100 * (1 + returns).cumprod()]]


def _weights_view(w: pd.Series, labels: dict[str, str], amount: float, threshold: float = 0.005) -> list[dict]:
    w = w[w > threshold].sort_values(ascending=False)
    return [{"key": k, "label": labels.get(k, k), "weight": float(v), "amount": float(v * amount)} for k, v in w.items()]


def analyse(navs: pd.DataFrame, labels: dict[str, str], cash: str | None, params: Params,
            progress: Callable[[float, str], None] | None = None) -> dict:
    """Analyse complète ; `progress(fraction, message)` est appelé au fil du calcul."""
    params.validate()
    say = progress or (lambda _f, _m: None)
    navs, cash = with_cash(navs.sort_index(), cash, params.rf_annual)
    labels = {**labels, CASH_FIXED: "Taux sans risque fixe"}
    risky_all = [c for c in navs.columns if c != cash]
    if len(risky_all) < MIN_RISKY:
        raise AnalysisError(f"Il faut au moins {MIN_RISKY} fonds en plus du monétaire (importés : {len(risky_all)}).")
    warnings_out: list[str] = []

    last_common = min(navs[c].dropna().index.max() for c in risky_all)
    priced = [c for c in risky_all if c not in params.euro_keys] or risky_all      # un fonds en euros saisi va jusqu'au mois courant
    newest = max(navs[c].dropna().index.max() for c in priced)
    stale = [labels.get(c, c) for c in priced if (newest - navs[c].dropna().index.max()).days > STALE_DAYS]
    if stale:
        warnings_out.append(f"Dernière VL ancienne (plus de {STALE_DAYS} jours avant la plus récente) : {', '.join(stale)}. Toute l'analyse s'arrête à la dernière "
                            f"date commune ({last_common.date().isoformat()}) ; retirez ces fonds pour étudier une période plus récente.")

    say(0.03, "Rendements mensuels et fenêtres d'étude")
    m_nav = stats.monthly_navs(navs, last_common)
    r_all = m_nav.pct_change(fill_method=None)
    windows = choose_windows(r_all, cash, params.windows, params.min_months)
    if len(windows) == 1:
        warnings_out.append("Une seule fenêtre d'étude exploitable : ajoutez un fonds plus récent ou choisissez une autre date de début pour comparer deux périodes.")

    daily = navs.ffill(limit=5).loc[params.daily_from:last_common].pct_change(fill_method=None)
    cash_nav = navs[cash].ffill()
    end = last_common

    # -- statistiques des fonds
    say(0.08, "Statistiques des fonds")
    stat_windows = {"12 mois": end - pd.DateOffset(years=1), "5 ans": end - pd.DateOffset(years=5)}
    for label, panel in windows:
        stat_windows[f"depuis {label}"] = pd.Timestamp(label)
    stat_windows["historique complet"] = pd.Timestamp("1990-01-01")
    fund_stats = []
    for c in risky_all:
        row = {"key": c, "label": labels.get(c, c), "windows": {}}
        for w_label, start in stat_windows.items():
            row["windows"][w_label] = stats.window_stats(navs[c], start, end, cash_nav)
        fund_stats.append(row)

    corr_panel = windows[-1][1]
    risky_corr = [c for c in corr_panel.columns if c != cash]
    corr = corr_panel[risky_corr].corr()

    # -- portefeuilles
    horizon = params.horizon_years * 12
    portfolios, curves, charts = [], {}, {}
    todo = [(wl, panel, obj, cap) for wl, panel in windows for obj in params.objectives for cap in params.caps]
    for i, (wl, panel, obj, cap) in enumerate(todo):
        cap_label = "aucun" if cap >= 1 else f"{round(cap * 100)} %"
        say(0.12 + 0.70 * i / len(todo), f"Portefeuille {i + 1}/{len(todo)} : {obj}, plafond {cap_label}, depuis {wl}")
        fn = optimize.OPTIMIZERS[obj]
        bounds, groups = _constraints_for(panel, params)
        try:
            w = optimize.clean_weights(fn(panel, cash, cap, k=params.k_starts, bounds=bounds, groups=groups))
        except ValueError as exc:
            raise AnalysisError(f"{obj}, plafond {cap_label}, depuis {wl} : {exc}") from exc
        p = (panel * w).sum(axis=1).rename(f"{wl}|{obj}|{cap_label}")
        metrics = optimize.evaluate(w, panel, cash, daily)
        rf = scenarios.rf_trailing(panel, cash)
        expected = scenarios.e_target(p, rf)
        try:
            wf = optimize.walk_forward(panel, cash, fn, cap, freq=params.reopt_months, min_train=params.min_train, k=min(params.k_starts, 25),
                                       bounds=bounds, groups=groups)
        except ValueError:
            wf = {"reoptimisation_mois": params.reopt_months, "apprentissage_min_mois": params.min_train, "mois_hors_echantillon": 0, "peu_fiable": True,
                  "rdt": None, "sharpe": None, "rdt_1n": None, "sharpe_1n": None, "se": None, "se_1n": None, "significatif": False}
        try:
            hist = scenarios.hist_windows(p, panel[cash], horizon)
        except ValueError:
            hist = None
        sims, garch = scenarios.run_methods(p, horizon, expected, list(params.methods), n=params.n_sims)
        portfolios.append({
            "id": f"{wl}|{obj}|{cap_label}", "window": wl, "objective": obj, "cap": None if cap >= 1 else float(cap), "cap_label": cap_label,
            "weights": _weights_view(w, labels, params.amount), "expected": expected, "metrics": metrics, "walk_forward": wf,
            "history": hist, "scenarios": sims, "garch": garch,
            "fan": {"historique": scenarios.fan(p, params.horizon_years, None, n=min(params.n_sims, 20000)),
                    "prudent": scenarios.fan(p, params.horizon_years, expected, n=min(params.n_sims, 20000))},
            **_savings(panel, w, expected, params),
        })
        curves[portfolios[-1]["id"]] = _growth(p)

    # -- allocation actuelle (avoirs saisis), frontière efficiente de chaque fenêtre
    say(0.80, "Allocation actuelle et frontière")
    current = []
    frontiers = {}
    for wl, panel in windows:
        bounds, groups = _constraints_for(panel, params)
        fr = projection.frontier(panel, cash, bounds, [(g[0], g[1], g[2]) for g in groups], cap=max(params.caps))
        for pf in portfolios:
            if pf["window"] == wl:
                pf["point"] = projection.point(panel, _weights_series(pf, panel))
        held = {k: v for k, v in params.holdings.items() if k in panel.columns and v > 0}
        cur = None
        if held:
            total = sum(held.values())
            w_cur = pd.Series({k: v / total for k, v in held.items()}).reindex(panel.columns).fillna(0.0)
            p_cur = (panel * w_cur).sum(axis=1)
            rf = scenarios.rf_trailing(panel, cash)
            cur = {"window": wl, "weights": _weights_view(w_cur, labels, total), "total": total,
                   "missing": sorted(set(params.holdings) - set(panel.columns)), "metrics": optimize.evaluate(w_cur, panel, cash, daily),
                   "point": projection.point(panel, w_cur), **_savings(panel, w_cur, scenarios.e_target(p_cur, rf), params)}
            current.append(cur)
            curves[f"{wl}|current"] = _growth(p_cur)
        frontiers[wl] = {**fr, "current": cur["point"] if cur else None}

    # -- la même épargne d'une enveloppe à l'autre (meilleure allocation hors échantillon de la fenêtre récente)
    say(0.82, "Comparaison des enveloppes")
    envelope_compare = []
    last_wl, last_panel = windows[-1]
    best_id = rank(portfolios).get(last_wl, {}).get("wf_sharpe")
    best = next((pf for pf in portfolios if pf["id"] == best_id), None)
    if best is not None:
        w_best = _weights_series(best, last_panel)
        for kind in envelopes.ENVELOPES:
            env = params.envelope if kind == params.envelope.get("kind") else envelopes.normalise(kind)
            pr = projection.project(last_panel, w_best, list(params.euro_keys), env, _contrib(params), params.horizon_years,
                                    target_annual=best["expected"], n=1500, couple=params.couple)
            envelope_compare.append({"kind": kind, "net": pr["net"], "taxes_median": pr["taxes_median"], "fees_median": pr["fees_median"],
                                     "abondement": pr["abondement"], "tax_saving_entry": pr["tax_saving_entry"], "prob_goal": pr["prob_goal"]})

    # -- courbes des fenêtres (base 100) : fonds, 1/N et portefeuilles
    say(0.84, "Courbes")
    for wl, panel in windows:
        risky = [c for c in panel.columns if c != cash]
        equal = (panel[risky].mean(axis=1)).rename("1/N")
        growth = {c: _growth(panel[c]) for c in panel.columns}
        dd = {}
        for c in risky:
            g = pd.Series(growth[c])
            dd[c] = [float(v) for v in (g / g.cummax() - 1)]
        charts[wl] = {"dates": [(panel.index[0] - pd.offsets.MonthEnd(1)).date().isoformat(), *[d.date().isoformat() for d in panel.index]],
                      "funds": growth, "drawdown": dd, "one_over_n": _growth(equal), "cash": cash,
                      "portfolios": {pid: curves[pid] for pid in curves if pid.startswith(f"{wl}|")}, "frontier": frontiers.get(wl)}

    # -- scénarios de chaque fonds pris seul
    say(0.90, "Scénarios de chaque fonds")
    cash_m = stats.monthly_returns(navs[cash].ffill(), last_common)
    fund_scenarios = []
    for c in risky_all:
        p = stats.monthly_returns(navs[c], last_common)
        if len(p) < horizon:
            continue
        frame = pd.concat([p.rename(c), cash_m.rename(cash)], axis=1, sort=True).dropna()
        expected = float(scenarios.expected_returns(frame, scenarios.rf_trailing(frame, cash))[c])
        sims = {name: {"historique": scenarios.summary(scenarios.METHODS[name](p, horizon, n=params.n_sims), horizon),
                       "prudent": scenarios.summary(scenarios.METHODS[name](p, horizon, n=params.n_sims, target_cagr=expected), horizon)}
                for name in params.methods if name == "bootstrap blocs 6 mois"}
        fund_scenarios.append({"key": c, "label": labels.get(c, c), "since": p.index[0].date().isoformat(), "expected": expected,
                               "history": scenarios.hist_windows(p, cash_m.reindex(p.index).fillna(0), horizon), "scenarios": sims})

    say(0.96, "Classement et mises en garde")
    ranking = rank(portfolios)
    for pf in portfolios:
        if pf["garch"] and not pf["garch"]["fiable"]:
            warnings_out.append(f"GARCH non fiable pour {pf['id']} ({pf['garch']['motif']}) : ses scénarios ne sont pas affichés.")
            break
    if any(pf["walk_forward"]["peu_fiable"] for pf in portfolios):
        warnings_out.append("Moins de 36 mois hors échantillon pour certaines fenêtres : leur walk-forward est peu fiable, lisez-le comme un ordre de grandeur.")
    short = [f"depuis {w}" for w, panel in windows if len(panel) < horizon + 12]
    if short:
        warnings_out.append(f"Historique court ({', '.join(short)}) : les scénarios à {params.horizon_years} ans reposent sur très peu d'années indépendantes.")

    result = {
        "version": RESULT_VERSION, "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "params": {"amount": params.amount, "horizon_years": params.horizon_years, "objectives": list(params.objectives), "caps": list(params.caps), "couple": params.couple,
                   "methods": list(params.methods), "n_sims": params.n_sims, "reopt_months": params.reopt_months, "min_train": params.min_train},
        "funds": [{"key": c, "label": labels.get(c, c), "start": navs[c].dropna().index[0].date().isoformat(),
                   "end": navs[c].dropna().index[-1].date().isoformat()} for c in risky_all],
        "cash": {"key": cash, "label": labels.get(cash, cash), "fixed": cash == CASH_FIXED, "rf_trailing": scenarios.rf_trailing(windows[-1][1], cash)},
        "last_common": last_common.date().isoformat(),
        "windows": [{"id": wl, "start": panel.index[0].date().isoformat(), "end": panel.index[-1].date().isoformat(), "months": len(panel),
                     "funds": [c for c in panel.columns if c != cash], "excluded": sorted(set(risky_all) - set(panel.columns))} for wl, panel in windows],
        "fund_stats": fund_stats, "stat_windows": list(stat_windows),
        "correlation": {"window": windows[-1][0], "keys": risky_corr, "matrix": corr.values.tolist()},
        "portfolios": portfolios, "fund_scenarios": fund_scenarios, "charts": charts, "ranking": ranking, "warnings": warnings_out,
        "envelope": params.envelope, "contributions": _contrib(params), "current": current, "envelope_compare": envelope_compare,
        "envelope_best": best_id, "constraints": {"bounds": {k: list(v) for k, v in params.bounds.items()},
                                                   "groups": [{"keys": g[0], "min": g[1], "max": g[2], "label": g[3]} for g in params.groups]},
        "euro_keys": list(params.euro_keys),
    }
    say(1.0, "Terminé")
    return _num(result)


def _contrib(params: Params) -> dict:
    return params.contrib or {**envelopes.CONTRIB_DEFAULTS, "initial": float(params.amount)}


def _constraints_for(panel: pd.DataFrame, params: Params) -> tuple[dict, list]:
    """Bornes et groupes restreints aux supports présents dans la fenêtre (un groupe vide est ignoré)."""
    bounds = {k: v for k, v in params.bounds.items() if k in panel.columns}
    groups = []
    for keys, lo, hi, _label in params.groups:
        present = [k for k in keys if k in panel.columns]
        if present:
            groups.append((present, lo, hi))
    return bounds, groups


def _weights_series(pf: dict, panel: pd.DataFrame) -> pd.Series:
    w = pd.Series({x["key"]: x["weight"] for x in pf["weights"]}).reindex(panel.columns).fillna(0.0)
    return w / w.sum() if w.sum() > 0 else w


def _savings(panel: pd.DataFrame, w: pd.Series, expected: float, params: Params) -> dict:
    """L'épargne réelle d'une allocation dans l'enveloppe : projection (historique et prudente), rejeu sur l'histoire, contributions au risque."""
    contrib = _contrib(params)
    euro = list(params.euro_keys)
    return {
        "projection": {"historique": projection.project(panel, w, euro, params.envelope, contrib, params.horizon_years, None, n=PROJECTION_PATHS, couple=params.couple),
                       "prudent": projection.project(panel, w, euro, params.envelope, contrib, params.horizon_years, expected, n=PROJECTION_PATHS, couple=params.couple)},
        "replay": projection.replay(panel, w, euro, params.envelope, contrib),
        "risk": projection.risk_contributions(panel, w),
    }


RANK_CRITERIA = ("wf_sharpe", "sharpe", "cagr", "vol")


def rank(portfolios: list[dict]) -> dict:
    """Le meilleur portefeuille de chaque fenêtre selon chaque critère (`{fenêtre: {critère: id}}`).

    `wf_sharpe` : Sharpe walk-forward (hors échantillon) ; `sharpe` : Sharpe sur tout l'historique (sur-ajusté) ; `cagr` : rendement annualisé ;
    `vol` : volatilité la plus faible. Un portefeuille dont le walk-forward manque n'est jamais retenu sur `wf_sharpe`."""
    keyers = {
        "wf_sharpe": lambda pf: pf["walk_forward"]["sharpe"] if pf["walk_forward"]["sharpe"] is not None else -math.inf,
        "sharpe": lambda pf: pf["metrics"]["sharpe"], "cagr": lambda pf: pf["metrics"]["cagr"], "vol": lambda pf: -pf["metrics"]["vol"],
    }
    out: dict[str, dict] = {}
    for window in sorted({pf["window"] for pf in portfolios}):
        group = [pf for pf in portfolios if pf["window"] == window]
        out[window] = {crit: max(group, key=keyers[crit])["id"] for crit in RANK_CRITERIA}
    return out
