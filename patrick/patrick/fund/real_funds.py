"""Fonds « réels » : un PEA et un CTO fictifs d'un particulier qui suivent tous les signaux (ADR 0026).

Deux stratégies en pilote automatique (`Systematic PEA`, `Systematic CTO`), de catégorie `real` : capital de 5 000 €, frais de 1 € par ordre
tout compris (`fee_flat`), niveau de sélection `auc` (tous les modèles dont l'AUC de direction du holdout dépasse le hasard, ceux qui passent
en plus la correction de Benjamini-Hochberg et le test de Diebold-Mariano en tête), taille minimale d'une position (`REAL_MIN_POSITION`) pour que
les frais forfaitaires ne rongent pas des positions de quelques euros. Le PEA est borné aux actions de l'UE/EEE en euro, à l'achat
(`fund/envelopes.py`) ; le CTO prend tout l'univers, à l'achat seulement (ADR 0028 : ni l'un ni l'autre ne vend à découvert ; actions et ETF
au comptant, le reste en CFD à l'achat).

Même logique que `asset_classes` : une stratégie qui porte déjà le nom est reprise, jamais dupliquée ; tout est validé avant la première écriture ;
`dry_run` n'écrit rien et compte les modèles candidats.
"""
from __future__ import annotations

import datetime as dt
import sqlite3

from patrick.fund import asset_classes, autopilot, envelopes, service, store

KINDS = ("PEA", "CTO")

DEFAULTS = {"capital": envelopes.REAL_CAPITAL, "fee_flat": envelopes.REAL_FLAT_FEE, "tier": "auc",
            "min_position": envelopes.REAL_MIN_POSITION, "max_models": envelopes.REAL_MAX_MODELS, "gross": 1.0}


def fund_name(kind: str) -> str:
    return f"Systematic {kind}"


def pilot_settings(kind: str, *, tier: str = "auc", gross: float = 1.0, max_models: int | None = envelopes.REAL_MAX_MODELS,
                   min_position: float | None = envelopes.REAL_MIN_POSITION) -> dict:
    """Réglages du pilote d'un fonds réel. Tous les horizons (un modèle par cellule cible x horizon). PEA : bornes d'enveloppe, achat seulement,
    groupes d'actions européennes ; CTO : tout l'univers, achat seulement (ADR 0028)."""
    return {"tier": tier, "gross": gross, "max_models": max_models, "min_position": min_position, "horizons": None,
            "allow_short": False, "groups": list(envelopes.PEA_GROUPS) if kind == "PEA" else None}


def setup(conn: sqlite3.Connection, *, today: dt.date | None = None, only: list[str] | None = None,
          capital: float = envelopes.REAL_CAPITAL, fee_flat: float | None = envelopes.REAL_FLAT_FEE, tier: str = "auc", gross: float = 1.0,
          max_models: int | None = envelopes.REAL_MAX_MODELS, min_position: float | None = envelopes.REAL_MIN_POSITION,
          dry_run: bool = False) -> list[dict]:
    """Le fonds PEA et le fonds CTO (ou `only`) : créés, ou repris par leur nom, avec leur pilote automatique. Renvoie, par fonds : `kind`, `name`,
    `strategy_id`, `created`, `capital_changed`, `candidates` (comme `asset_classes.setup`)."""
    today = service._today(today)
    unknown = [k for k in (only or []) if k not in KINDS]
    if unknown:
        raise store.FundError(f"fonds réel inconnu : {', '.join(unknown)} (fonds : {', '.join(KINDS)})")
    store.check_flat_fee(fee_flat)
    for kind in KINDS:
        store._check_capital(capital, kind)                  # tout est validé AVANT la première écriture (le plafond du PEA compris)
        autopilot.Settings.from_dict(pilot_settings(kind, tier=tier, gross=gross, max_models=max_models, min_position=min_position))
    out = []
    for kind in KINDS:
        if only and kind not in only:
            continue
        row = asset_classes._provision(
            conn, name=fund_name(kind), wrapper=kind, capital=capital, today=today, dry_run=dry_run, category="real", fee_flat=fee_flat,
            settings=pilot_settings(kind, tier=tier, gross=gross, max_models=max_models, min_position=min_position))
        out.append({"kind": kind, **row})
    return out
