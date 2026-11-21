"""Modèles de stratégies : chacun se COMPILE en règles du moteur général (`backtest.Strategy`), que la page peut ensuite afficher et modifier
dans le constructeur de règles. Rien n'est câblé en dur dans le moteur : un modèle n'est qu'un raccourci vers un jeu de règles.

Chaque modèle déclare ses paramètres (`params` : défaut, bornes, pas, type) pour que la page génère son formulaire et sa grille de
sensibilité, et sa famille (tendance, retour à la moyenne, rotation…) pour la galerie.
"""
from __future__ import annotations

from collections.abc import Callable

FAMILIES = ("allocation", "trend", "reversion", "rotation", "calendar", "event", "pair", "regime", "custom")


def _p(default, lo=None, hi=None, step=None, kind="int", options=None) -> dict:
    out = {"default": default, "type": kind}
    if lo is not None:
        out.update({"min": lo, "max": hi, "step": step or (1 if kind == "int" else 0.01)})
    if options is not None:
        out["options"] = list(options)
    return out


def c(left, op, right=None, **kw) -> dict:
    """Condition : `c(ind("sma", n=50), ">", ind("sma", n=200))` ; un nombre à droite devient une valeur."""
    out = {"left": left, "op": op}
    if right is not None:
        out["right"] = right if isinstance(right, dict) else {"value": right}
    for k, v in kw.items():
        out[k] = v if isinstance(v, dict) else {"value": v}
    return out


def ind(name: str, **params) -> dict:
    return {"ind": name, **params}


PRICE = ind("price")
REB = ("never", "monthly", "quarterly", "annual", "weekly")
DEC = ("daily", "weekly", "monthly")


def _side_rules(long_entry, long_exit, short_entry, short_exit, side: str) -> dict:
    out = {"long_entry": long_entry, "long_exit": long_exit}
    if side == "long_short":
        out.update({"short_entry": short_entry, "short_exit": short_exit})
    elif side == "short":
        out = {"short_entry": short_entry, "short_exit": short_exit}
    return out


def _all(*conds) -> dict:
    return {"all": [x for x in conds if x]}


def b_buy_hold(p):
    return {"rebalance": p["rebalance"], "sizing": {"method": "equal", "allocation": "sleeves"}}


def b_fixed_mix(p):
    return {"rebalance": p["rebalance"], "sizing": {"method": "fixed", "weights": {}, "allocation": "sleeves"}}


def b_sma_cross(p):
    up = _all(c(ind("sma", n=p["fast"]), ">", ind("sma", n=p["slow"])))
    down = _all(c(ind("sma", n=p["fast"]), "<", ind("sma", n=p["slow"])))
    return {**_side_rules(up, None, down, None, p["side"]), "decision": p["decision"], "rebalance": "monthly"}


def b_price_sma(p):
    up = _all(c(PRICE, ">", ind("sma", n=p["n"])))
    down = _all(c(PRICE, "<", ind("sma", n=p["n"])))
    return {**_side_rules(up, None, down, None, p["side"]), "decision": p["decision"], "rebalance": "monthly"}


def b_ts_momentum(p):
    up = _all(c(ind("mom", n=p["n"], skip=p["skip"]), ">", 0))
    down = _all(c(ind("mom", n=p["n"], skip=p["skip"]), "<", 0))
    return {**_side_rules(up, None, down, None, p["side"]), "decision": p["decision"], "rebalance": "monthly"}


def b_xs_momentum(p):
    out = {"selection": {"rank_by": ind("mom", n=p["n"], skip=p["skip"]), "order": "desc", "top": p["top"], "bottom": p["bottom"]},
           "decision": p["decision"], "rebalance": p["decision"], "sizing": {"method": "equal", "allocation": "sleeves"}}
    if p["absolute"]:
        out["long_entry"] = _all(c(ind("mom", n=p["n"], skip=p["skip"]), ">", 0))
    return out


def b_dual_momentum(p):
    return {"long_entry": _all(c(ind("ret", n=p["n"]), ">", p["hurdle"] / 100)), "selection": {"rank_by": ind("ret", n=p["n"]), "order": "desc", "top": p["top"], "bottom": 0},
            "decision": "monthly", "rebalance": "monthly", "sizing": {"method": "equal", "allocation": "sleeves"}}


def b_rsi(p):
    entry = _all(c(ind("rsi", n=p["n"]), "<", p["low"]), c(PRICE, ">", ind("sma", n=p["trend"])) if p["trend"] else None)
    exit_ = _all(c(ind("rsi", n=p["n"]), ">", p["high"]))
    s_entry = _all(c(ind("rsi", n=p["n"]), ">", 100 - p["low"]), c(PRICE, "<", ind("sma", n=p["trend"])) if p["trend"] else None)
    s_exit = _all(c(ind("rsi", n=p["n"]), "<", 100 - p["high"]))
    return {**_side_rules(entry, exit_, s_entry, s_exit, p["side"]), "decision": "daily", "rebalance": "never"}


def b_bollinger(p):
    entry = _all(c(PRICE, "<", ind("bb_low", n=p["n"], k=p["k"])))
    exit_ = _all(c(PRICE, ">", ind("sma", n=p["n"])))
    s_entry = _all(c(PRICE, ">", ind("bb_up", n=p["n"], k=p["k"])))
    s_exit = _all(c(PRICE, "<", ind("sma", n=p["n"])))
    return {**_side_rules(entry, exit_, s_entry, s_exit, p["side"]), "decision": "daily", "rebalance": "never"}


def b_donchian(p):
    entry = _all(c(PRICE, ">", ind("high", n=p["entry"])))
    exit_ = _all(c(PRICE, "<", ind("low", n=p["exit"])))
    s_entry = _all(c(PRICE, "<", ind("low", n=p["entry"])))
    s_exit = _all(c(PRICE, ">", ind("high", n=p["exit"])))
    return {**_side_rules(entry, exit_, s_entry, s_exit, p["side"]), "decision": "daily", "rebalance": "never",
            "sizing": {"method": "inverse_vol", "n": 60, "allocation": "sleeves"}}


def b_low_vol(p):
    return {"selection": {"rank_by": ind("vol", n=p["n"]), "order": "asc", "top": p["top"], "bottom": 0}, "decision": "monthly", "rebalance": "monthly",
            "sizing": {"method": "equal", "allocation": "sleeves"}}


def b_inverse_vol(p):
    return {"rebalance": p["rebalance"], "sizing": {"method": "inverse_vol", "n": p["n"], "allocation": "active"}}


def b_vol_target(p):
    return {"rebalance": "weekly", "sizing": {"method": "equal", "allocation": "active", "leverage": p["leverage"]},
            "overlay": {"target_vol": p["target"] / 100, "n": p["n"]}}


def b_turn_of_month(p):
    entry = {"any": [c(ind("dte"), "<", p["before"]), c(ind("dom"), "<=", p["after"])]}
    return {"long_entry": entry, "decision": "daily", "rebalance": "never"}


def b_halloween(p):
    start, end = p["start"], p["end"]
    if start <= end:
        entry = {"all": [c(ind("month"), ">=", start), c(ind("month"), "<=", end)]}
    else:
        entry = {"any": [c(ind("month"), ">=", start), c(ind("month"), "<=", end)]}
    return {"long_entry": entry, "decision": "daily", "rebalance": "never"}


def b_pairs(p):
    z = ind("zscore", n=p["n"])
    return {"long_entry": _all(c(z, "<", -p["z_in"])), "long_exit": _all(c(z, ">", -p["z_out"])),
            "short_entry": _all(c(z, ">", p["z_in"])), "short_exit": _all(c(z, "<", p["z_out"])),
            "decision": "daily", "rebalance": "never", "pair": True, "sizing": {"method": "equal", "allocation": "active"}}


def b_event(p):
    entry = _all(c(ind("event"), "between", None, low=-p["before"], high=p["after"]))
    return {"long_entry": entry, "decision": "daily", "rebalance": "never", "events": True,
            "sizing": {"method": "equal", "allocation": "active" if p["concentrate"] else "sleeves"}}


def b_regime(p):
    op = "<" if p["direction"] == "below" else ">"
    return {"long_entry": _all(c(ind("price", symbol=p["symbol"]), op, p["threshold"])), "decision": "daily", "rebalance": "monthly"}


def b_custom(p):
    return {}


TEMPLATES: dict[str, dict] = {
    "buy_hold": {"family": "allocation", "build": b_buy_hold, "params": {"rebalance": _p("never", kind="select", options=REB)}},
    "fixed_mix": {"family": "allocation", "build": b_fixed_mix, "params": {"rebalance": _p("annual", kind="select", options=REB)}, "weights": True},
    "inverse_vol": {"family": "allocation", "build": b_inverse_vol, "params": {"n": _p(60, 10, 250, 5), "rebalance": _p("monthly", kind="select", options=REB)}},
    "vol_target": {"family": "allocation", "build": b_vol_target,
                   "params": {"target": _p(10.0, 2.0, 40.0, 0.5, "float"), "n": _p(60, 10, 250, 5), "leverage": _p(1.0, 0.5, 3.0, 0.1, "float")}},
    "sma_cross": {"family": "trend", "build": b_sma_cross,
                  "params": {"fast": _p(50, 5, 200, 5), "slow": _p(200, 20, 400, 10), "side": _p("long", kind="select", options=("long", "long_short")),
                             "decision": _p("daily", kind="select", options=DEC)}},
    "price_sma": {"family": "trend", "build": b_price_sma,
                  "params": {"n": _p(200, 10, 400, 10), "side": _p("long", kind="select", options=("long", "long_short")), "decision": _p("monthly", kind="select", options=DEC)}},
    "ts_momentum": {"family": "trend", "build": b_ts_momentum,
                    "params": {"n": _p(252, 21, 504, 21), "skip": _p(21, 0, 63, 1), "side": _p("long", kind="select", options=("long", "long_short")),
                               "decision": _p("monthly", kind="select", options=DEC)}},
    "donchian": {"family": "trend", "build": b_donchian,
                 "params": {"entry": _p(55, 10, 250, 5), "exit": _p(20, 5, 120, 5), "side": _p("long", kind="select", options=("long", "long_short"))}},
    "xs_momentum": {"family": "rotation", "build": b_xs_momentum,
                    "params": {"n": _p(252, 21, 504, 21), "skip": _p(21, 0, 63, 1), "top": _p(3, 1, 20, 1), "bottom": _p(0, 0, 20, 1),
                               "absolute": _p(False, kind="bool"), "decision": _p("monthly", kind="select", options=DEC)}},
    "dual_momentum": {"family": "rotation", "build": b_dual_momentum,
                      "params": {"n": _p(252, 21, 504, 21), "top": _p(1, 1, 10, 1), "hurdle": _p(0.0, -10.0, 20.0, 0.5, "float")}},
    "low_vol": {"family": "rotation", "build": b_low_vol, "params": {"n": _p(60, 10, 250, 5), "top": _p(3, 1, 20, 1)}},
    "rsi": {"family": "reversion", "build": b_rsi,
            "params": {"n": _p(2, 2, 30, 1), "low": _p(10, 1, 49, 1), "high": _p(70, 51, 99, 1), "trend": _p(200, 0, 400, 10),
                       "side": _p("long", kind="select", options=("long", "long_short"))}},
    "bollinger": {"family": "reversion", "build": b_bollinger,
                  "params": {"n": _p(20, 5, 120, 5), "k": _p(2.0, 0.5, 4.0, 0.25, "float"), "side": _p("long", kind="select", options=("long", "long_short"))}},
    "turn_of_month": {"family": "calendar", "build": b_turn_of_month, "params": {"before": _p(1, 0, 10, 1), "after": _p(3, 0, 10, 1)}},
    "halloween": {"family": "calendar", "build": b_halloween, "params": {"start": _p(11, 1, 12, 1), "end": _p(4, 1, 12, 1)}},
    "event": {"family": "event", "build": b_event, "params": {"before": _p(5, 0, 60, 1), "after": _p(1, 0, 60, 1), "concentrate": _p(True, kind="bool")},
              "events": True},
    "pairs": {"family": "pair", "build": b_pairs, "params": {"n": _p(60, 10, 250, 5), "z_in": _p(2.0, 0.5, 4.0, 0.25, "float"), "z_out": _p(0.5, 0.0, 2.0, 0.25, "float")},
              "pair": True},
    "regime": {"family": "regime", "build": b_regime,
               "params": {"symbol": _p("^VIX", kind="symbol"), "threshold": _p(25.0, -1e6, 1e6, 0.5, "float"),
                          "direction": _p("below", kind="select", options=("below", "above"))}},
    "custom": {"family": "custom", "build": b_custom, "params": {}},
}


class TemplateError(ValueError):
    """Modèle ou paramètre invalide : message en français."""


def resolve(key: str, given: dict | None) -> dict:
    """Paramètres complets et validés d'un modèle (défauts + valeurs fournies, bornes contrôlées)."""
    if key not in TEMPLATES:
        raise TemplateError(f"Modèle inconnu : {key}.")
    spec = TEMPLATES[key]["params"]
    given = given or {}
    unknown = sorted(set(given) - set(spec))
    if unknown:
        raise TemplateError(f"Paramètre inconnu pour ce modèle : {', '.join(unknown)}.")
    out = {}
    for name, meta in spec.items():
        v = given.get(name, meta["default"])
        kind = meta["type"]
        try:
            if kind == "int":
                v = round(float(v))
            elif kind == "float":
                v = float(v)
            elif kind == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "oui", "on")
            elif kind == "select":
                if v not in meta["options"]:
                    raise TemplateError(f"{name} : valeur non proposée ({v}).")
            elif kind == "symbol":
                v = str(v).strip().upper()
                if not v:
                    raise TemplateError(f"{name} : symbole manquant.")
        except (TypeError, ValueError) as exc:
            raise TemplateError(f"{name} : valeur invalide ({v}).") from exc
        if kind in ("int", "float") and "min" in meta and not meta["min"] <= v <= meta["max"]:
            raise TemplateError(f"{name} doit être compris entre {meta['min']} et {meta['max']}.")
        out[name] = v
    if key == "sma_cross" and out["fast"] >= out["slow"]:
        raise TemplateError("La moyenne rapide doit être plus courte que la lente.")
    return out


def compile_template(key: str, given: dict | None) -> dict:
    params = resolve(key, given)
    build: Callable[[dict], dict] = TEMPLATES[key]["build"]
    return {"template": key, "params": params, **build(params)}


def catalog() -> list[dict]:
    return [{"key": k, "family": v["family"], "params": v["params"], "weights": bool(v.get("weights")), "events": bool(v.get("events")),
             "pair": bool(v.get("pair"))} for k, v in TEMPLATES.items()]
