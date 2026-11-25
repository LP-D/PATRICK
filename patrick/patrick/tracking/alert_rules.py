"""Alertes de prix et de signal (FO16 du 25/11) : des règles simples, vérifiées après les prédictions, notifiées par Windows.

Trois sortes de règle, gardées dans les réglages de ce PC (`alert_rules`, une liste) :

- `{"symbol": "^GSPC", "kind": "above", "level": 6000}` : la dernière clôture passe au-dessus du niveau ;
- `{"symbol": "EURUSD=X", "kind": "below", "level": 1.05}` : … en dessous ;
- `{"symbol": "GC=F", "kind": "flip", "horizon": 5}` : le champion de l'horizon change de direction par rapport à sa prédiction réelle
  précédente.

`patrick alerts check` (étape de la nuit après les prédictions) évalue chaque règle, notifie celles qui se déclenchent et retient la date
du dernier déclenchement (`last_fired`) : une règle ne sonne qu'une fois par séance. Lecture seule de la base ; aucune décision n'est prise.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable

from patrick.core import settings

KEY = "alert_rules"
KINDS = ("above", "below", "flip")


def load_rules() -> list[dict]:
    rules = settings.load().get(KEY) or []
    return [r for r in rules if isinstance(r, dict) and r.get("kind") in KINDS and isinstance(r.get("symbol"), str)]


def save_rules(rules: list[dict]) -> None:
    clean = []
    for r in rules:
        if not isinstance(r, dict) or r.get("kind") not in KINDS or not isinstance(r.get("symbol"), str):
            raise ValueError(f"règle d'alerte invalide : {r!r}")
        if r["kind"] in ("above", "below") and not isinstance(r.get("level"), (int, float)):
            raise ValueError(f"niveau manquant : {r!r}")
        clean.append(r)
    settings.save({KEY: clean})


def _direction(conn: sqlite3.Connection, symbol: str, horizon: int) -> list[tuple[str, int]]:
    """Deux dernières prédictions réelles du champion : `[(date, 1 hausse / -1 baisse), ...]`, la plus récente d'abord."""
    rows = conn.execute(
        "SELECT p.ts, p.y_pred FROM champion c JOIN prediction p ON p.trial_id = c.trial_id AND p.split = 'live' "
        "WHERE c.target = ? AND c.horizon = ? ORDER BY p.ts DESC LIMIT 2", (symbol, horizon)).fetchall()
    return [(str(ts)[:10], 1 if float(y) >= 2 else -1) for ts, y in rows]


def evaluate(conn: sqlite3.Connection, rules: list[dict], last_close: Callable[[str], tuple[str, float] | None]) -> list[dict]:
    """Règles déclenchées : `{rule, message, session}` ; `last_close(symbole) -> (date, clôture)` ou None."""
    fired = []
    for rule in rules:
        sym, kind = rule["symbol"], rule["kind"]
        if kind in ("above", "below"):
            quote = last_close(sym)
            if quote is None:
                continue
            day, close = quote
            hit = close > rule["level"] if kind == "above" else close < rule["level"]
            if hit and rule.get("last_fired") != day:
                side = "au-dessus" if kind == "above" else "en dessous"
                fired.append({"rule": rule, "session": day, "message": f"{sym} à {close:.4g}, {side} de {rule['level']:.4g}"})
        else:
            last = _direction(conn, sym, int(rule.get("horizon") or 1))
            if len(last) == 2 and last[0][1] != last[1][1] and rule.get("last_fired") != last[0][0]:
                arrow = "hausse" if last[0][1] > 0 else "baisse"
                fired.append({"rule": rule, "session": last[0][0],
                              "message": f"{sym} h{int(rule.get('horizon') or 1)} : le champion passe à la {arrow} ({last[0][0]})"})
    return fired


def check(conn: sqlite3.Connection, last_close: Callable[[str], tuple[str, float] | None], notify: Callable[[str, str], bool] | None = None,
          dry_run: bool = False) -> list[dict]:
    """Évalue les règles, notifie celles qui sonnent et retient leur séance (une seule fois par séance)."""
    rules = load_rules()
    fired = evaluate(conn, rules, last_close)
    if fired and not dry_run:
        if notify is None:
            from patrick.system.notify import toast as notify
        notify("PATRICK : alertes", "\n".join(f["message"] for f in fired)[:900])
        for f in fired:
            f["rule"]["last_fired"] = f["session"]
        save_rules(rules)
    return fired
