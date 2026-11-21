"""Conditions de stratégie : « opérande opérateur opérande », regroupées en « toutes » (ET) ou « au moins une » (OU).

    {"all": [{"left": {"ind": "sma", "n": 50}, "op": ">", "right": {"ind": "sma", "n": 200}},
             {"left": {"ind": "price", "symbol": "^VIX"}, "op": "<", "right": {"value": 25}}]}

Opérateurs : `>` `<` `>=` `<=`, `crosses_above` / `crosses_below` (vrai le seul jour du croisement), `between` / `outside` (bornes `low` et
`high`, valeurs ou opérandes). Une valeur manquante (indicateur pas encore calculable) rend la condition fausse : on n'entre jamais sur un
indicateur incomplet. Un groupe peut contenir un sous-groupe (un niveau) : « (A et B) ou C ».
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.strategylab import indicators

OPS = (">", "<", ">=", "<=", "crosses_above", "crosses_below", "between", "outside")
MAX_CONDITIONS = 16


class RuleError(ValueError):
    """Règle mal formée : message en français."""


def operands(group: dict | None) -> list[dict]:
    """Tous les opérandes d'un groupe (pour savoir quels instruments auxiliaires charger)."""
    out: list[dict] = []
    if not group:
        return out
    for cond in group.get("all", []) + group.get("any", []):
        if "all" in cond or "any" in cond:
            out.extend(operands(cond))
            continue
        for side in ("left", "right", "low", "high"):
            v = cond.get(side)
            if isinstance(v, dict) and "ind" in v:
                out.append(v)
    return out


def _value(m: indicators.Market, operand) -> pd.DataFrame | float:
    if isinstance(operand, (int, float)) and not isinstance(operand, bool):
        return float(operand)
    if not isinstance(operand, dict):
        raise RuleError("Opérande manquant ou mal formé.")
    if "value" in operand:
        try:
            return float(operand["value"])
        except (TypeError, ValueError) as exc:
            raise RuleError("Valeur numérique attendue.") from exc
    try:
        return indicators.compute(m, operand)
    except indicators.IndicatorError as exc:
        raise RuleError(str(exc)) from exc


def _frame(x, like: pd.DataFrame) -> pd.DataFrame:
    if isinstance(x, pd.DataFrame):
        return x
    return pd.DataFrame(float(x), index=like.index, columns=like.columns)


def condition(m: indicators.Market, cond: dict) -> pd.DataFrame:
    if "all" in cond or "any" in cond:
        return group(m, cond, nested=True)
    op = cond.get("op")
    if op not in OPS:
        raise RuleError(f"Opérateur inconnu : {op}.")
    left = _frame(_value(m, cond.get("left")), m.close)
    if op in ("between", "outside"):
        low, high = _frame(_value(m, cond.get("low")), m.close), _frame(_value(m, cond.get("high")), m.close)
        known = left.notna() & low.notna() & high.notna()
        inside = (left >= low) & (left <= high)
        return (inside if op == "between" else ~inside) & known
    right = _frame(_value(m, cond.get("right")), m.close)
    known = left.notna() & right.notna()
    if op == ">":
        out = left > right
    elif op == "<":
        out = left < right
    elif op == ">=":
        out = left >= right
    elif op == "<=":
        out = left <= right
    else:
        diff = left - right
        prev = diff.shift(1)
        out = (diff > 0) & (prev <= 0) if op == "crosses_above" else (diff < 0) & (prev >= 0)
        known = known & prev.notna()
    return out & known


def group(m: indicators.Market, grp: dict | None, nested: bool = False) -> pd.DataFrame | None:
    """Booléens séances x instruments ; `None` si le groupe est vide (pas de règle)."""
    if not grp:
        return None
    items_all, items_any = grp.get("all") or [], grp.get("any") or []
    if not items_all and not items_any:
        return None
    if len(items_all) + len(items_any) > MAX_CONDITIONS:
        raise RuleError(f"Au plus {MAX_CONDITIONS} conditions par règle.")
    for item in items_all + items_any:
        if nested and ("all" in item or "any" in item):
            raise RuleError("Un seul niveau de sous-groupe est permis.")
    out = None
    if items_all:
        frames = [condition(m, c) for c in items_all]
        out = frames[0]
        for f in frames[1:]:
            out = out & f
    if items_any:
        frames = [condition(m, c) for c in items_any]
        any_ = frames[0]
        for f in frames[1:]:
            any_ = any_ | f
        out = any_ if out is None else out & any_
    return out.fillna(False).astype(bool)


def to_array(frame: pd.DataFrame | None, columns: list[str]) -> np.ndarray | None:
    return None if frame is None else frame[columns].to_numpy(dtype=bool)
