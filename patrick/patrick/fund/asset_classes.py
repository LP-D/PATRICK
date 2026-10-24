"""Fonds, pilote automatique : une stratégie par classe d'actifs.

Une classe regroupe des groupes de l'univers (`config/universe_extension.all_target_groups`). `setup` crée (ou retrouve, par son
nom `Systematic <classe>`) une stratégie par classe et y active le pilote automatique, borné à ces groupes et à un horizon
(1 jour par défaut). La série macro FRED n'est dans aucune classe : elle n'est pas négociable.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from patrick.fund import autopilot, selection, service, store

UNTRADABLE_GROUP = "Macro (FRED)"

CLASSES: dict[str, tuple[str, ...]] = {
    "Future": ("Matières premières (futures)", "Matières premières (compléments)", "Taux US (futures)"),
    "Actions US": ("Actions US (grandes capitalisations)", "Actions US (méga-capitalisations)"),
    "Actions France": ("Actions France (CAC 40)", "Actions France (autres valeurs)"),
    "Actions Europe": ("Actions Allemagne", "Actions Royaume-Uni", "Actions Europe (autres pays)"),
    "Actions Asie": ("Actions Asie (locales & ADR)",),
    "Actions individuelles": ("Actions individuelles",),
    "Indices": ("Indices mondiaux", "Indices"),
    "ETF": ("ETFs sectoriels & thématiques", "Obligataire & taux (ETFs)", "International (ETFs pays)",
            "Matières premières & devises (ETFs)"),
    "Devises": ("Devises (majeures)", "Devises"),
    "Crypto": ("Crypto", "Crypto (majeures)"),
    "Volatilité": ("Volatilité",),
    "Taux": ("Taux US (indices CBOE)",),
}


def strategy_name(asset_class: str) -> str:
    return f"Systematic {asset_class}"


def setup(conn: sqlite3.Connection, *, today: dt.date | None = None, only: list[str] | None = None,
          horizons: tuple[int, ...] = (1,), tier: str = "large", gross: float = 1.0, capital: float = 100_000,
          wrapper: str = "CTO", max_models: int = 40, dry_run: bool = False) -> list[dict]:
    """Une stratégie en pilote automatique par classe (toutes, ou `only`). Une stratégie qui porte déjà le nom
    `Systematic <classe>` est reprise, jamais dupliquée ; ses réglages sont remplacés par ceux-ci. `dry_run` : rien n'est
    écrit, seul le nombre de modèles candidats est compté. Renvoie, par classe : `class`, `name`, `strategy_id`, `created`, `candidates`."""
    today = service._today(today)
    unknown = [c for c in (only or []) if c not in CLASSES]
    if unknown:
        raise store.FundError(f"classe inconnue : {', '.join(unknown)} (classes : {', '.join(CLASSES)})")
    existing = {s["name"]: s["strategy_id"] for s in store.list_strategies(conn)}
    out = []
    for asset_class, groups in CLASSES.items():
        if only and asset_class not in only:
            continue
        settings = {"tier": tier, "gross": gross, "max_models": max_models, "allow_short": True,
                    "horizons": list(horizons), "groups": list(groups)}
        policy = autopilot.Settings.from_dict(settings)
        name = strategy_name(asset_class)
        row = {"class": asset_class, "name": name, "strategy_id": existing.get(name), "created": False,
               "candidates": len(selection.select_models(conn, policy.selection, today)["selected"])}
        if not dry_run:
            if row["strategy_id"] is None:
                row["strategy_id"] = store.create_strategy(conn, name, wrapper, capital, today.isoformat())
                row["created"] = True
            autopilot.configure(conn, row["strategy_id"], settings)
        out.append(row)
    return out
