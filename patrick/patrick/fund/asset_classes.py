"""Fonds, pilote automatique : une stratégie par classe d'actifs, ou par preuve statistique, dans une gamme.

Une classe regroupe des groupes de l'univers (`config/universe_extension.all_target_groups`). `setup` crée (ou retrouve, par son
nom `<gamme> <classe>`) une stratégie par classe et y active le pilote automatique, borné à ces groupes et à un horizon
(1 jour par défaut) ; `setup_tiers` fait de même avec une stratégie par niveau de preuve (`<gamme> Diebold-Mariano`...). La série
macro FRED n'est dans aucune classe : elle n'est pas négociable.

Trois gammes (`FAMILIES`), dans deux catégories qui ne se mélangent pas (ADR 0029) :
- `Systematic` : fonds quant d'étude (catégorie `quant`) : CTO, vente à découvert en CFD, tout l'univers, capital virtuel de 10 M€, frais estimés ;
- `CTO` et `PEA` : fonds reproductibles par un particulier (catégorie `real`) : achat seulement, 5 000 € chacun, 1 € par ordre tout compris, position
  minimale de 200 € (un compte de cette taille ne finance pas tous les signaux). CTO : actions et ETF au comptant, le reste en CFD à l'achat ;
  PEA : au comptant, actions de l'UE/EEE cotées en euro (`fund/envelopes.py`).
Une gamme ne reprend jamais la stratégie d'une autre : le préfixe du nom les sépare. Une stratégie reprise sans ordre prend les conditions de sa
gamme (catégorie, frais, capital) ; avec des ordres, seule la catégorie suit (`store.set_terms`).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass

from patrick.fund import autopilot, envelopes, selection, service, store
from patrick.tracking import db as trackdb

UNTRADABLE_GROUP = "Macro (FRED)"

CLASSES: dict[str, tuple[str, ...]] = {
    "Future": ("Matières premières (futures)", "Matières premières (compléments)", "Taux US (futures)"),
    "Actions US": ("Actions US (grandes capitalisations)", "Actions US (méga-capitalisations)"),
    "Actions France": ("Actions France (CAC 40)", "Actions France (autres valeurs)"),
    "Actions Europe": ("Actions Allemagne", "Actions Royaume-Uni", "Actions Europe (autres pays)"),
    "Actions Asie": ("Actions Asie (locales & ADR)",),
    "Indices": ("Indices mondiaux", "Indices"),
    "ETF": ("ETFs sectoriels & thématiques", "Obligataire & taux (ETFs)", "International (ETFs pays)",
            "Matières premières & devises (ETFs)"),
    "Devises": ("Devises (majeures)", "Devises"),
    "Crypto": ("Crypto", "Crypto (majeures)"),
    "Volatilité": ("Volatilité",),
    "Taux": ("Taux US (indices CBOE)",),
}


# Réglages proposés partout (commande et page) : horizon 1 jour, niveau « strict » (cible qui survit à la correction pour tests multiples
# ET test de Diebold-Mariano de la cellule concluant), aucun plafond de modèles. Le niveau « large » (tous les signaux non suspects, sans preuve
# statistique) reste disponible mais n'est plus le défaut (critique du 28/10 : on tradait sans preuve, puis on classait les classes sur leur P&L
# fictif, une sélection non corrigée).
DEFAULTS = {"horizons": [1], "tier": "strict", "gross": 1.0, "capital": 10_000_000, "family": "systematic", "max_models": None}


# Stratégies globales par preuve statistique : le niveau de sélection -> la fin du nom de la stratégie (toutes les classes de la gamme réunies).
TIER_STRATEGIES = {"dm": "Diebold-Mariano", "bh": "Benjamini-Hochberg"}


@dataclass(frozen=True)
class Family:
    """Une gamme de fonds : préfixe des noms, enveloppe, vente à découvert, capital par défaut, classes proposées, périmètre des
    stratégies par preuve (`scope`, groupes de l'univers ; None : tout l'univers), catégorie (`quant` ou `real`), frais forfaitaires par ordre
    (None : frais estimés) et taille minimale d'une position (None : aucune)."""
    key: str
    prefix: str
    wrapper: str
    allow_short: bool
    capital: float
    classes: dict[str, tuple[str, ...]]
    scope: tuple[str, ...] | None
    category: str = "quant"
    fee_flat: float | None = None
    min_position: float | None = None


# Le PEA ne détient que des actions de l'UE/EEE en euro : deux classes, la France et le reste de l'Europe éligible (sans le Royaume-Uni).
PEA_CLASSES = {"Actions France": CLASSES["Actions France"],
               "Actions Europe": tuple(g for g in envelopes.PEA_GROUPS if g not in CLASSES["Actions France"])}

# CTO et PEA : ce qu'un particulier peut reproduire (5 000 €, 1 € par ordre, 200 € au moins par position), comme les fonds « tous signaux »
# de `real_funds`. Systematic : le laboratoire quant (10 M€ virtuels, vente à découvert, frais estimés).
_RETAIL = {"category": "real", "fee_flat": envelopes.REAL_FLAT_FEE, "min_position": envelopes.REAL_MIN_POSITION}
FAMILIES = {
    "systematic": Family("systematic", "Systematic", "CTO", True, 10_000_000, CLASSES, None),
    "cto": Family("cto", "CTO", "CTO", False, envelopes.REAL_CAPITAL, CLASSES, None, **_RETAIL),
    "pea": Family("pea", "PEA", "PEA", False, envelopes.REAL_CAPITAL, PEA_CLASSES, envelopes.PEA_GROUPS, **_RETAIL),
}


def family_of(key: str) -> Family:
    if key not in FAMILIES:
        raise store.FundError(f"gamme inconnue : {key!r} ({', '.join(FAMILIES)})")
    return FAMILIES[key]


def strategy_name(asset_class: str, family: str = "systematic") -> str:
    return f"{family_of(family).prefix} {asset_class}"


def tier_strategy_name(tier: str, family: str = "systematic") -> str:
    return f"{family_of(family).prefix} {TIER_STRATEGIES[tier]}"


def class_rows(conn: sqlite3.Connection, family: str = "systematic") -> list[dict]:
    """Les classes de la gamme avec leurs groupes et la stratégie qui porte déjà leur nom (`strategy_id`, sinon None)."""
    existing = {s["name"]: s["strategy_id"] for s in store.list_strategies(conn)}
    return [{"name": name, "groups": list(groups), "strategy_id": existing.get(strategy_name(name, family))}
            for name, groups in family_of(family).classes.items()]


def setup(conn: sqlite3.Connection, *, today: dt.date | None = None, only: list[str] | None = None,
          horizons: tuple[int, ...] = (1,), tier: str = "strict", gross: float = 1.0, capital: float | None = None,
          family: str = "systematic", max_models: int | None = None, dry_run: bool = False) -> list[dict]:
    """Une stratégie en pilote automatique par classe de la gamme (toutes, ou `only`). Une stratégie qui porte déjà le nom
    `<gamme> <classe>` est reprise, jamais dupliquée ; ses réglages sont remplacés par ceux-ci. `dry_run` : rien n'est
    écrit, seul le nombre de modèles candidats est compté. `capital` : celui de la gamme par défaut. Une stratégie reprise sans ordre prend le capital
    demandé (`capital_changed`) ; avec des ordres elle garde le sien. Renvoie, par classe : `class`, `name`, `strategy_id`, `created`,
    `capital_changed`, `candidates`."""
    today = service._today(today)
    fam = family_of(family)
    unknown = [c for c in (only or []) if c not in fam.classes]
    if unknown:
        raise store.FundError(f"classe inconnue dans la gamme {fam.prefix} : {', '.join(unknown)} (classes : {', '.join(fam.classes)})")
    capital = fam.capital if capital is None else capital
    store._check_capital(capital, fam.wrapper)              # tout est validé AVANT la première écriture (le plafond du PEA compris)
    autopilot.Settings.from_dict({"tier": tier, "gross": gross, "max_models": max_models, "horizons": list(horizons),
                                  "groups": ["x"]})
    out = []
    for asset_class, groups in fam.classes.items():
        if only and asset_class not in only:
            continue
        settings = {"tier": tier, "gross": gross, "max_models": max_models, "allow_short": fam.allow_short,
                    "horizons": list(horizons), "groups": list(groups), "min_position": fam.min_position}
        row = _provision(conn, name=strategy_name(asset_class, family), settings=settings, capital=capital, wrapper=fam.wrapper,
                         today=today, dry_run=dry_run, category=fam.category, fee_flat=fam.fee_flat)
        out.append({"class": asset_class, **row})
    return out


def _provision(conn: sqlite3.Connection, *, name: str, settings: dict, capital: float, wrapper: str, today: dt.date,
               dry_run: bool, category: str = "quant", fee_flat: float | None = None) -> dict:
    """Retrouve (par son nom) ou crée la stratégie `name` et y active le pilote avec `settings` ; `dry_run` : rien n'est écrit.
    Une stratégie reprise SANS ordre prend la catégorie, les frais (`fee_flat`) et le capital demandés (une gamme qui change de conditions, ADR 0029) ;
    avec des ordres, elle garde frais et capital, et une catégorie différente est refusée (ce n'est pas une stratégie de cette gamme).
    Renvoie `name`, `strategy_id` (None si elle n'existe pas encore), `created`, `capital_changed`, `candidates`."""
    existing = {s["name"]: s["strategy_id"] for s in store.list_strategies(conn)}
    if name in existing:
        current = store.get_strategy(conn, existing[name])
        has_orders = conn.execute("SELECT 1 FROM fund_order WHERE strategy_id = ? LIMIT 1", (current["strategy_id"],)).fetchone() is not None
        if current["category"] != category and has_orders:
            raise store.FundError(f"une stratégie « {name} » existe déjà et n'est pas de la catégorie {category!r} : la renommer ou la supprimer d'abord")
    policy = autopilot.Settings.from_dict(settings)
    chosen = selection.select_models(conn, policy.selection, today)["selected"]
    row = {"name": name, "strategy_id": existing.get(name), "created": False, "capital_changed": False,
           "candidates": len(chosen)}
    if not dry_run:
        # Choisir ces modèles pour une stratégie est un usage de plus des mêmes données : chaque (cible, horizon) retenu compte un essai de
        # plus dans le registre (source `simulation`, détail `fund_selection:<stratégie>` : la table n'accepte que les sources connues), comme une simulation. Compté ici, à la mise en place, jamais à chaque réévaluation
        # quotidienne du pilote (ADR 0010).
        for model in chosen:
            trackdb.register_trials(conn, model["target"], model["horizon"], "simulation", 1, detail=f"fund_selection:{name}")
        if row["strategy_id"] is None:
            row["strategy_id"] = store.create_strategy(conn, name, wrapper, capital, today.isoformat(), category=category, fee_flat=fee_flat)
            row["created"] = True
        else:
            before = float(store.get_strategy(conn, row["strategy_id"])["initial_capital"])
            try:                                  # une stratégie reprise sans ordre prend les conditions de sa gamme
                store.set_terms(conn, row["strategy_id"], category=category, fee_flat=fee_flat, initial_capital=capital)
            except store.FundError:
                pass                              # avec des ordres, frais et capital restent ceux qu'elle a (la catégorie est déjà la bonne)
            row["capital_changed"] = abs(float(store.get_strategy(conn, row["strategy_id"])["initial_capital"]) - before) > 0.005
        autopilot.configure(conn, row["strategy_id"], settings)
    return row


def setup_tiers(conn: sqlite3.Connection, *, today: dt.date | None = None, tiers: tuple[str, ...] = tuple(TIER_STRATEGIES),
                horizons: tuple[int, ...] = (1,), gross: float = 1.0, capital: float | None = None, family: str = "systematic",
                max_models: int | None = None, dry_run: bool = False) -> list[dict]:
    """Une stratégie globale (toutes les classes de la gamme) par niveau de preuve statistique : `dm` (test de Diebold-Mariano seul)
    et `bh` (correction de Benjamini-Hochberg seule). Même logique que `setup` : reprise par le nom, jamais dupliquée, essais comptés,
    tout validé avant la première écriture. Renvoie, par niveau : `tier`, `name`, `strategy_id`, `created`, `capital_changed`, `candidates`."""
    today = service._today(today)
    fam = family_of(family)
    unknown = [t for t in tiers if t not in TIER_STRATEGIES]
    if unknown:
        raise store.FundError(f"niveau inconnu : {', '.join(unknown)} (niveaux : {', '.join(TIER_STRATEGIES)})")
    capital = fam.capital if capital is None else capital
    store._check_capital(capital, fam.wrapper)              # tout est validé AVANT la première écriture (le plafond du PEA compris)
    out = []
    for tier in tiers:
        settings = {"tier": tier, "gross": gross, "max_models": max_models, "allow_short": fam.allow_short,
                    "horizons": list(horizons), "groups": list(fam.scope) if fam.scope else None, "min_position": fam.min_position}
        row = _provision(conn, name=tier_strategy_name(tier, family), settings=settings, capital=capital, wrapper=fam.wrapper,
                         today=today, dry_run=dry_run, category=fam.category, fee_flat=fam.fee_flat)
        out.append({"tier": tier, **row})
    return out
