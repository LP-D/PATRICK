"""Jeux de données de VL importés, rangés sous `<racine de données>/placements/<id>/`.

    meta.json        nom, montant, fonds monétaire, taux sans risque de repli, un bloc par fonds (libellé, source, début, fin, contrôles)
    series/<clé>.csv VL d'un fonds (`date,nav`)
    result.json      dernier résultat d'analyse (écrit par `service.analyse` via `jobs`)

L'identifiant d'un jeu de données et la clé d'un fonds servent de noms de fichiers : ils sont validés contre une expression stricte avant
tout accès disque (jamais de `..`, de séparateur ou de nom réservé). Écritures atomiques (fichier temporaire puis remplacement).
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from patrick import paths
from patrick.placements import loader

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
DEFAULT_AMOUNT = 10_000.0
DEFAULT_RF = 0.02
CASH_HINTS = ("monetaire", "money_market", "moneymarket", "cash", "tresorerie", "liquidite")


class StoreError(ValueError):
    """Opération impossible (jeu de données ou fonds inconnu, identifiant invalide) : message en français pour l'utilisateur."""


def root() -> Path:
    return paths.data_root() / "placements"


def _dir(dataset_id: str) -> Path:
    if not ID_RE.match(dataset_id or ""):
        raise StoreError("Identifiant de jeu de données invalide.")
    return root() / dataset_id


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{secrets.token_hex(3)}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_dataset(name: str, amount: float = DEFAULT_AMOUNT) -> str:
    name = (name or "").strip()[:80] or "Jeu de données"
    slug = loader.slugify(name)[:40] or "jeu"
    dataset_id = f"{slug}-{secrets.token_hex(3)}"
    meta = {"id": dataset_id, "name": name, "created": _now(), "amount": float(amount), "cash": None, "rf_annual": DEFAULT_RF, "funds": {}}
    _write_atomic(_dir(dataset_id) / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return dataset_id


def get_meta(dataset_id: str) -> dict:
    path = _dir(dataset_id) / "meta.json"
    if not path.is_file():
        raise StoreError("Jeu de données introuvable.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_meta(meta: dict) -> None:
    _write_atomic(_dir(meta["id"]) / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))


def list_datasets() -> list[dict]:
    """Les jeux de données, le plus récent d'abord : `{id, name, created, n_funds, amount, has_result}`."""
    base = root()
    out = []
    if base.is_dir():
        for child in base.iterdir():
            try:
                meta = get_meta(child.name)
            except (StoreError, json.JSONDecodeError, OSError):
                continue
            out.append({"id": meta["id"], "name": meta["name"], "created": meta["created"], "n_funds": len(meta["funds"]),
                        "amount": meta["amount"], "has_result": (child / "result.json").is_file()})
    return sorted(out, key=lambda d: d["created"], reverse=True)


def guess_cash(funds: dict) -> str | None:
    """Le support monétaire probable : le premier dont la clé évoque un monétaire (« Groupama Monétaire », « money market »…)."""
    for key in funds:
        if any(h in key for h in CASH_HINTS):
            return key
    return None


def add_fund(dataset_id: str, parsed: loader.ParsedFund) -> dict:
    """Ajoute (ou complète) un fonds. Retourne son bloc de méta, avec le contrôle de cohérence si la série fusionne avec une plus ancienne."""
    meta = get_meta(dataset_id)
    path = _dir(dataset_id) / "series" / f"{parsed.key}.csv"
    old = None
    if path.is_file():
        old = pd.read_csv(path, parse_dates=["date"]).set_index("date")["nav"].rename(parsed.key)
    merged, check = loader.merge_series(old, parsed.series)
    out = merged.rename("nav").rename_axis("date").reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    _write_atomic(path, out.to_csv(index=False))
    previous = meta["funds"].get(parsed.key, {})
    entry = {"label": previous.get("label") or parsed.label, "source": parsed.source, "kind": parsed.kind,
             "start": merged.index[0].date().isoformat(), "end": merged.index[-1].date().isoformat(), "points": len(merged),
             "excluded": bool(previous.get("excluded", False)), "checks": (previous.get("checks", []) + [{"fichier": parsed.source, **check}])[-5:]}
    meta["funds"][parsed.key] = entry
    if meta.get("cash") is None:
        meta["cash"] = guess_cash(meta["funds"])
    save_meta(meta)
    return entry


def update_settings(dataset_id: str, *, name: str | None = None, amount: float | None = None, cash: str | None | bool = False,
                    rf_annual: float | None = None, excluded: dict[str, bool] | None = None) -> dict:
    """Modifie les réglages d'un jeu de données. `cash=False` = inchangé, `None` = aucun fonds monétaire (taux fixe), sinon la clé d'un fonds."""
    meta = get_meta(dataset_id)
    if name is not None:
        meta["name"] = name.strip()[:80] or meta["name"]
    if amount is not None:
        if not 0 < amount < 1e9:
            raise StoreError("Le montant doit être strictement positif.")
        meta["amount"] = float(amount)
    if rf_annual is not None:
        if not -0.05 <= rf_annual <= 0.30:
            raise StoreError("Le taux sans risque doit être compris entre -5 % et 30 % par an.")
        meta["rf_annual"] = float(rf_annual)
    if cash is not False:
        if cash is not None and cash not in meta["funds"]:
            raise StoreError("Fonds monétaire inconnu.")
        meta["cash"] = cash
    for key, flag in (excluded or {}).items():
        if key in meta["funds"]:
            meta["funds"][key]["excluded"] = bool(flag)
    save_meta(meta)
    return meta


def remove_fund(dataset_id: str, key: str) -> None:
    meta = get_meta(dataset_id)
    if key not in meta["funds"] or not loader.KEY_RE.match(key):
        raise StoreError("Fonds introuvable.")
    (_dir(dataset_id) / "series" / f"{key}.csv").unlink(missing_ok=True)
    del meta["funds"][key]
    if meta.get("cash") == key:
        meta["cash"] = guess_cash(meta["funds"])
    save_meta(meta)


def delete_dataset(dataset_id: str) -> None:
    path = _dir(dataset_id)
    if not (path / "meta.json").is_file():
        raise StoreError("Jeu de données introuvable.")
    shutil.rmtree(path)


def load_navs(dataset_id: str, include_excluded: bool = False) -> tuple[pd.DataFrame, dict]:
    """`(VL de tous les fonds en colonnes, méta)` ; les fonds exclus par l'utilisateur sont écartés (sauf le monétaire)."""
    meta = get_meta(dataset_id)
    columns = {}
    for key, fund in meta["funds"].items():
        if fund.get("excluded") and not include_excluded and key != meta.get("cash"):
            continue
        path = _dir(dataset_id) / "series" / f"{key}.csv"
        if path.is_file():
            columns[key] = pd.read_csv(path, parse_dates=["date"]).set_index("date")["nav"].rename(key)
    if not columns:
        raise StoreError("Ce jeu de données ne contient aucune série.")
    return pd.concat(columns.values(), axis=1, sort=True).sort_index(), meta


def save_result(dataset_id: str, result: dict) -> None:
    _write_atomic(_dir(dataset_id) / "result.json", json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")))


def load_result(dataset_id: str) -> dict | None:
    path = _dir(dataset_id) / "result.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
