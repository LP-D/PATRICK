"""Page de comparaison de runs de reinforcement learning (`/compare-runs` quand tous les runs choisis sont des runs RL).

Fonction pure : elle reçoit les runs lus par `rl_routes.get_rl_run` et un traducteur, et renvoie ce que le gabarit `compare_rl.html`
affiche -- un tableau de mesures (une colonne par run, la meilleure valeur de chaque ligne repérée, les lignes qui diffèrent d'un run à
l'autre marquées), des avertissements quand la comparaison n'est pas à armes égales, et les courbes de capital sur une grille de dates
commune. Rien n'est calculé ici qui ne soit déjà dans le résultat du run.
"""
from __future__ import annotations

import math
from collections.abc import Callable

from patrick.rl import reading as rl_reading

COLORS = ("var(--ra-c1)", "var(--ra-c2)", "var(--ra-c3)", "var(--ra-c4)")   # une couleur par colonne (4 runs au plus) : séries catégorielles du design system, jamais les couleurs de sens
_DASH = "—"


def _f2(v): return f"{v:.2f}"
def _sf2(v): return f"{v:+.2f}"
def _p0(v): return f"{v * 100:.0f} %"
def _p1(v): return f"{v * 100:.1f} %"
def _p3(v): return f"{v:.3f}"
def _sp1(v): return f"{v * 100:+.1f} %"
def _int(v): return str(int(v))
def _g(v): return f"{v:g}"
def _text(v): return str(v)


def _dig(d, *path):
    for key in path:
        d = d.get(key) if isinstance(d, dict) else None
    return d


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isnan(v) else None


def _minutes(v):
    v = _num(v)
    return None if v is None else f"{int(v // 60)} min {int(v % 60):02d} s"


def _rows(t: Callable[[str], str]):
    """(groupe, clé de libellé, extracteur, formateur, meilleure valeur : « max », « min » ou None)."""
    def bool_(path):
        return lambda m: None if _dig(m["cfg"], *path) is None else t("adv_yes" if _dig(m["cfg"], *path) else "adv_no")

    def option(prefix, path):
        return lambda m: None if _dig(m["cfg"], *path) is None else t(f"{prefix}_{_dig(m['cfg'], *path)}")

    def cfg(path):
        return lambda m: _dig(m["cfg"], *path)

    def effective(key):
        """Réglage du moteur 2 : absent d'une configuration du moteur 1, il vaut sa valeur d'alors (`RL_LEGACY_SETTINGS`)."""
        from patrick.config.defaults import RL_LEGACY_SETTINGS

        def get(m):
            rl = _dig(m["cfg"], "rl")
            if not isinstance(rl, dict):
                return None
            value = rl.get(key, RL_LEGACY_SETTINGS.get(key))
            return t("adv_yes" if value else "adv_no") if isinstance(value, bool) else value
        return get

    def verdict(m):
        v = m["reading"].get("verdict")
        return t(f"rlp_rd_{v}") if v else None

    def gated(m):
        folds = [f for f in m["result"].get("folds") or [] if isinstance(f, dict)]
        return sum(1 for f in folds if f.get("gated")) if any("gated" in f for f in folds) else None

    def delay(m):
        d = m["reading"].get("delay")                   # enregistré (moteur 2) ou rejoué sur le fichier hors échantillon (moteur 1)
        if not isinstance(d, dict) or _num(d.get("gross_sharpe")) is None or _num(d.get("lagged_sharpe")) is None:
            return None
        return t("rlp_delay", g=f"{d['gross_sharpe']:.2f}", l=f"{d['lagged_sharpe']:.2f}")

    return (
        ("rlh_g_reading", "rlp_rd_title", verdict, _text, None),
        ("rlh_g_reading", "rlh_col_engine", lambda m: t("rlp_rd_engine", n=m["reading"]["engine"]), _text, None),
        ("rlh_g_reading", "rlh_col_excess", lambda m: m["reading"].get("excess"), _sp1, "max"),
        ("rlh_g_reading", "rlh_c_p_bh", lambda m: m["reading"].get("p_vs_buy_hold"), _p3, "min"),
        ("rlh_g_reading", "rlh_col_share", lambda m: m["reading"].get("agent_share"), _p0, None),
        ("rlh_g_reading", "rlh_col_cost", lambda m: m["reading"].get("cost_ann"), _p1, "min"),
        ("rlh_g_reading", "rlh_p_folds_gated", gated, _int, None),
        ("rlh_g_reading", "rlp_stat_delay", delay, _text, None),
        ("rlh_g_result", "rlp_k_sharpe", lambda m: _dig(m["strategy"], "sharpe"), _f2, "max"),
        ("rlh_g_result", "rlh_c_sharpe_bh", lambda m: _dig(m["baselines"], "buy_hold", "sharpe"), _f2, None),
        ("rlh_g_result", "hist_gap", lambda m: _dig(m["stats"], "vs_buy_hold", "diff"), _sf2, "max"),
        ("rlh_g_result", "rlh_c_gap_ci", lambda m: _ci(m), _text, None),
        ("rlh_g_result", "rlh_c_sharpe_trend", lambda m: _dig(m["baselines"], "trend", "sharpe"), _f2, None),
        ("rlh_g_result", "rlp_stat_vs_trend", lambda m: _dig(m["stats"], "vs_trend", "diff"), _sf2, "max"),
        ("rlh_g_result", "rlp_k_total", lambda m: _dig(m["strategy"], "total_return"), _sp1, "max"),
        ("rlh_g_result", "rlp_k_cagr", lambda m: _dig(m["strategy"], "cagr"), _sp1, "max"),
        ("rlh_g_result", "rlp_k_maxdd", lambda m: _dig(m["strategy"], "max_drawdown"), _p1, "max"),
        ("rlh_g_result", "rlh_c_turnover", lambda m: _dig(m["strategy"], "turnover"), _f2, None),
        ("rlh_g_result", "rlh_c_trades", lambda m: _dig(m["strategy"], "n_trades"), _int, None),
        ("rlh_g_result", "rlp_k_gross", lambda m: _dig(m["strategy"], "gross_return_ann"), _sp1, "max"),
        ("rlh_g_result", "rlp_k_long", lambda m: _dig(m["strategy"], "long_contrib_ann"), _sp1, None),
        ("rlh_g_result", "rlp_k_short", lambda m: _dig(m["strategy"], "short_contrib_ann"), _sp1, None),
        ("rlh_g_stats", "rlp_stat_psr", lambda m: _dig(m["stats"], "psr"), _p1, "max"),
        ("rlh_g_stats", "rlp_stat_dsr", lambda m: _dig(m["stats"], "dsr", "dsr"), _p1, "max"),
        ("rlh_g_stats", "rlh_p_trials", lambda m: _dig(m["stats"], "n_trials"), _int, None),
        ("rlh_g_run", "rlp_f_algo", lambda m: m["row"].get("algo"), _text, None),
        ("rlh_g_run", "dq_col_target", lambda m: m["row"].get("target"), _text, None),
        ("rlh_g_run", "rlh_p_period", lambda m: _period(m), _text, None),
        ("rlh_g_run", "rlp_f_n_folds", lambda m: m["result"].get("n_folds"), _int, None),
        ("rlh_g_run", "rlp_f_n_seeds", lambda m: len(m["result"].get("seeds") or []) or None, _int, None),
        ("rlh_g_run", "rp_duration", lambda m: _minutes(m["result"].get("elapsed_s")), _text, None),
        ("rlh_g_run", "dq_col_status", lambda m: m["row"].get("status"), _text, None),
        ("rlh_g_run", "hist_started", lambda m: m["row"].get("started_at") or m["row"].get("created_at"), _text, None),
        ("rlh_g_settings", "rlp_f_action_space", option("rlp_o_action_space", ("rl", "action_space")), _text, None),
        ("rlh_g_settings", "rlp_f_n_levels", cfg(("rl", "n_levels")), _int, None),
        ("rlh_g_settings", "rlp_f_allow_short", bool_(("rl", "allow_short")), _text, None),
        ("rlh_g_settings", "rlp_f_max_leverage", cfg(("rl", "max_leverage")), _g, None),
        ("rlh_g_settings", "rlp_f_reward", option("rlp_o_reward", ("rl", "reward")), _text, None),
        ("rlh_g_settings", "rlp_f_rebalance_every", effective("rebalance_every"), _int, None),
        ("rlh_g_settings", "rlp_f_train_cost_mult", effective("train_cost_mult"), _g, None),
        ("rlh_g_settings", "rlp_f_val_frac", effective("val_frac"), _g, None),
        ("rlh_g_settings", "rlp_f_gate", effective("gate"), _text, None),
        ("rlh_g_settings", "rlp_f_cost_bps", cfg(("rl", "cost_bps")), _g, None),
        ("rlh_g_settings", "rlp_f_slippage_bps", cfg(("rl", "slippage_bps")), _g, None),
        ("rlh_g_settings", "rlp_f_policy_layers", lambda m: _policy(m), _text, None),
        ("rlh_g_settings", "rlp_f_learning_rate", cfg(("rl", "learning_rate")), _g, None),
        ("rlh_g_settings", "rlp_f_gamma", cfg(("rl", "gamma")), _g, None),
        ("rlh_g_settings", "rlp_f_total_timesteps", cfg(("rl", "total_timesteps")), _int, None),
        ("rlh_g_settings", "rlp_f_obs_lookback", cfg(("rl", "obs_lookback")), _int, None),
        ("rlh_g_settings", "rlp_f_max_features", cfg(("rl", "max_features")), _int, None),
        ("rlh_g_settings", "rlp_f_retrain", option("rlp_o_retrain", ("rl", "retrain")), _text, None),
        ("rlh_g_settings", "rlp_f_min_train_frac", cfg(("rl", "min_train_frac")), _g, None),
    )


def _show(value, fmt) -> str:
    """Texte d'une cellule : une chaîne telle quelle, un nombre mis en forme, un tiret si la mesure manque (ou n'est pas un nombre fini)."""
    if isinstance(value, str):
        return value
    number = _num(value)
    return _DASH if number is None else fmt(number)


def _ci(m):
    low, high = _num(_dig(m["stats"], "vs_buy_hold", "ci_low")), _num(_dig(m["stats"], "vs_buy_hold", "ci_high"))
    return None if low is None or high is None else f"[{low:+.2f} ; {high:+.2f}]"


def _period(m):
    dates = _dig(m["result"], "curves", "dates") or []
    return f"{dates[0]} → {dates[-1]}" if dates else None


def _policy(m):
    layers, units = _dig(m["cfg"], "rl", "policy_layers"), _dig(m["cfg"], "rl", "policy_units")
    return None if layers is None or units is None else f"{layers} × {units}"


def _chart(models: list[dict]) -> dict | None:
    """Courbes de capital (base 1) de chaque run sur l'union de leurs dates ; une valeur est reportée jusqu'à la date suivante du run, et
    vide avant son début et après sa fin."""
    curves = []
    for index, m in enumerate(models):
        dates, values = _dig(m["result"], "curves", "dates"), _dig(m["result"], "curves", "strategy")
        if isinstance(dates, list) and isinstance(values, list) and dates and len(dates) == len(values):
            curves.append((index, m, dates, values))
    if not curves:
        return None
    grid = sorted({d for _i, _m, dates, _v in curves for d in dates})
    series = []
    for index, m, dates, values in curves:
        by_date = dict(zip(dates, values, strict=True))
        first, last, current, out = dates[0], dates[-1], None, []
        for d in grid:
            if d in by_date:
                current = _num(by_date[d])
            out.append(current if first <= d <= last else None)
        series.append({"name": m["row"].get("name") or m["row"]["run_id"], "color": COLORS[index % len(COLORS)], "index": index, "values": out})
    return {"dates": grid, "series": series}


def build(runs: list[dict], t: Callable[[str], str]) -> dict:
    """`runs` : sorties de `rl_routes.get_rl_run`, dans l'ordre choisi par l'utilisateur."""
    models = [{"row": r["row"], "result": r["result"], "config": r["config"], "cfg": r["config"] if isinstance(r["config"], dict) else {},
               "strategy": r["result"].get("strategy") or {}, "baselines": r["result"].get("baselines") or {},
               "stats": r["result"].get("stats") or {}, "reading": rl_reading.of_result(r["result"], r["row"].get("target"))} for r in runs]
    rows = []
    for group, label, extract, fmt, best in _rows(t):
        values = [extract(m) for m in models]
        texts = [_show(v, fmt) for v in values]
        top = None
        numeric = [_num(v) for v in values]
        known = [v for v in numeric if v is not None]
        if best in ("max", "min") and len(known) > 1 and max(known) > min(known):      # valeurs toutes égales : pas de gagnant à signaler
            top = max(known) if best == "max" else min(known)
        cells = [{"text": text, "best": top is not None and num == top} for text, num in zip(texts, numeric, strict=True)]
        rows.append({"group": group, "label": label, "cells": cells, "differs": len(set(texts)) > 1})
    targets = {m["row"].get("target") for m in models}
    periods = {_period(m) for m in models if _period(m)}
    return {
        "runs": [{"run_id": m["row"]["run_id"], "name": m["row"].get("name") or m["row"]["run_id"], "color": COLORS[i % len(COLORS)]}
                 for i, m in enumerate(models)],
        "rows": rows,
        "warn_target": len(targets) > 1,
        "warn_period": len(periods) > 1,
        "chart": _chart(models),
    }
