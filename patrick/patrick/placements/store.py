"""Jeux de données de VL importés, rangés sous `<racine de données>/placements/<id>/`.

    meta.json        nom, montant, fonds monétaire, taux sans risque de repli, enveloppe, versements, avoirs actuels, contraintes,
                     un bloc par support (libellé, source, type des valeurs, fréquence, catégorie, rôle, bornes, notes de lecture, contrôles)
    series/<clé>.csv niveaux d'un support (`date,nav` : cours, VL ou indice reconstruit)
    raw/<clé>.csv    valeurs telles que lues (`date,value`) : permettent de corriger le type (« c'étaient des performances ») sans réimporter
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
from patrick.placements import envelopes, loader
from patrick.tabular import detect

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
    meta = {"id": dataset_id, "name": name, "created": _now(), "amount": float(amount), "cash": None, "rf_annual": DEFAULT_RF, "funds": {},
            **default_profile(amount)}
    _write_atomic(_dir(dataset_id) / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1))
    return dataset_id


def default_profile(amount: float = DEFAULT_AMOUNT) -> dict:
    return {"envelope": {"kind": "none", "overrides": {}}, "contributions": {**envelopes.CONTRIB_DEFAULTS, "initial": float(amount)},
            "holdings": {}, "groups": [], "couple": False}


def get_meta(dataset_id: str) -> dict:
    path = _dir(dataset_id) / "meta.json"
    if not path.is_file():
        raise StoreError("Jeu de données introuvable.")
    meta = json.loads(path.read_text(encoding="utf-8"))
    for k, v in default_profile(meta.get("amount", DEFAULT_AMOUNT)).items():      # jeux de données créés avant les enveloppes
        meta.setdefault(k, v)
    return meta


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
    """Le support monétaire probable : un support de rôle « monétaire », sinon le premier dont la clé évoque un monétaire."""
    for key, f in funds.items():
        if f.get("role") == "money":
            return key
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


def _write_series(dataset_id: str, folder: str, key: str, series: pd.Series, column: str) -> None:
    out = series.rename(column).rename_axis("date").reset_index()
    out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d")
    _write_atomic(_dir(dataset_id) / folder / f"{key}.csv", out.to_csv(index=False))


def _read_series(dataset_id: str, folder: str, key: str, column: str) -> pd.Series | None:
    path = _dir(dataset_id) / folder / f"{key}.csv"
    if not path.is_file():
        return None
    return pd.read_csv(path, parse_dates=["date"]).set_index("date")[column].rename(key)


def _unique_key(meta: dict, base: str, kind: str) -> str:
    key = (base or "support")[:70]
    if key not in meta["funds"] or meta["funds"][key].get("kind", "price") == kind:
        return key
    i = 2
    while f"{key}_{i}" in meta["funds"]:
        i += 1
    return f"{key}_{i}"


def add_found(dataset_id: str, found: detect.Found, source: str) -> tuple[str, dict]:
    """Ajoute (ou complète) un support trouvé par le lecteur universel. Les valeurs brutes et leur type sont gardés à côté des niveaux."""
    meta = get_meta(dataset_id)
    key = _unique_key(meta, loader.slugify(found.isin or found.name) or loader.slugify(source), found.kind)
    if not loader.KEY_RE.match(key):
        raise StoreError(f"{source} : nom de support inexploitable.")
    old_raw = _read_series(dataset_id, "raw", key, "value")
    raw = found.raw.rename(key)
    check = {"points_communs": 0, "ecart_max": 0.0, "nouveaux_points": len(raw)}
    if old_raw is not None:
        raw, check = loader.merge_series(old_raw, raw)
    levels = detect.levels(raw, found.kind)
    _write_series(dataset_id, "raw", key, raw, "value")
    _write_series(dataset_id, "series", key, levels, "nav")
    previous = meta["funds"].get(key, {})
    monthly = levels.resample("ME").last().pct_change().dropna()
    vol = float(monthly.std() * (12 ** 0.5)) if len(monthly) > 6 else None
    category = previous.get("category") or ("euro" if found.kind == "annual_rate" else envelopes.guess_category(found.name, vol))
    entry = {"label": previous.get("label") or found.name, "source": source, "kind": found.kind, "frequency": found.frequency, "isin": found.isin,
             "sheet": found.sheet, "column": found.column, "notes": found.notes, "confidence": round(float(found.confidence), 2),
             "category": category, "role": previous.get("role") or envelopes.role_of(category), "min": previous.get("min"), "max": previous.get("max"),
             "start": levels.index[0].date().isoformat(), "end": levels.index[-1].date().isoformat(), "points": len(levels),
             "excluded": bool(previous.get("excluded", False)), "checks": (previous.get("checks", []) + [{"fichier": source, **check}])[-5:]}
    meta["funds"][key] = entry
    if meta.get("cash") is None:
        meta["cash"] = guess_cash(meta["funds"])
    save_meta(meta)
    return key, entry


def add_rates(dataset_id: str, name: str, text: str, category: str = "euro") -> tuple[str, dict]:
    """Un support à taux annuels (fonds en euros, livret, compte à terme) à partir de lignes « année taux » : `2023 2,5` / `2024;2,6 %`."""
    import re as _re
    rows = {}
    for line in (text or "").splitlines():
        m = _re.match(r"^\s*(\d{4})\s*[;:,=\t ]\s*([-+]?\d+(?:[.,]\d+)?)\s*%?\s*$", line)
        if not m:
            continue
        year, rate = int(m.group(1)), float(m.group(2).replace(",", "."))
        if 1950 <= year <= 2100 and -10 <= rate <= 30:
            rows[pd.Timestamp(year=year, month=12, day=31)] = rate
    if len(rows) < 1:
        raise StoreError("Indiquez au moins une ligne « année taux » (par exemple « 2024 2,5 »).")
    raw = pd.Series(rows).sort_index()
    found = detect.Found(name=(name or "Fonds en euros").strip()[:80], raw=raw, kind="annual_rate", frequency="annual", sheet="saisie", column="taux",
                         notes=["taux annuels saisis, capitalisés mois par mois"], confidence=1.0)
    key, _entry = add_found(dataset_id, found, "saisie manuelle")
    if category in envelopes.CATEGORIES:
        update_fund(dataset_id, key, category=category, role=envelopes.role_of(category))
    return key, get_meta(dataset_id)["funds"][key]


def update_fund(dataset_id: str, key: str, *, label: str | None = None, kind: str | None = None, category: str | None = None,
                role: str | None = None, min_w: float | None | bool = False, max_w: float | None | bool = False, excluded: bool | None = None) -> dict:
    """Corrige un support : libellé, type des valeurs (recalcule les niveaux depuis les valeurs brutes), catégorie, rôle, bornes de poids."""
    meta = get_meta(dataset_id)
    if key not in meta["funds"] or not loader.KEY_RE.match(key):
        raise StoreError("Fonds introuvable.")
    f = meta["funds"][key]
    if label is not None:
        f["label"] = label.strip()[:120] or f["label"]
    if kind is not None and kind != f.get("kind", "price"):
        if kind not in detect.KINDS:
            raise StoreError("Type de valeurs inconnu.")
        raw = _read_series(dataset_id, "raw", key, "value")
        if raw is None:
            raise StoreError("Valeurs brutes indisponibles pour ce support (importé avant la lecture universelle) : réimportez le fichier.")
        levels = detect.levels(raw, kind)
        if (levels <= 0).any() or not levels.notna().all():
            raise StoreError("Avec ce type, l'indice devient négatif ou nul : ce n'est sans doute pas le bon type.")
        _write_series(dataset_id, "series", key, levels, "nav")
        f.update({"kind": kind, "start": levels.index[0].date().isoformat(), "end": levels.index[-1].date().isoformat(), "points": len(levels)})
    if category is not None:
        if category not in envelopes.CATEGORIES:
            raise StoreError("Catégorie inconnue.")
        f["category"] = category
    if role is not None:
        if role not in envelopes.ROLES:
            raise StoreError("Rôle inconnu.")
        f["role"] = role
    for name, value in (("min", min_w), ("max", max_w)):
        if value is False:
            continue
        if value is not None and not 0 <= float(value) <= 1:
            raise StoreError("Une borne de poids doit être comprise entre 0 et 100 %.")
        f[name] = None if value is None else float(value)
    if f.get("min") is not None and f.get("max") is not None and f["min"] > f["max"]:
        raise StoreError("Le poids minimal dépasse le poids maximal.")
    if excluded is not None:
        f["excluded"] = bool(excluded)
    save_meta(meta)
    return f


def update_profile(dataset_id: str, *, envelope: dict | None = None, contributions: dict | None = None, holdings: dict | None = None,
                   groups: list | None = None, couple: bool | None = None) -> dict:
    """Enveloppe (type + paramètres modifiés), versements, avoirs actuels par support (montants), contraintes de groupe."""
    meta = get_meta(dataset_id)
    if envelope is not None:
        kind = envelope.get("kind", "none")
        overrides = {k: v for k, v in (envelope.get("overrides") or {}).items() if v not in (None, "")}
        try:
            envelopes.normalise(kind, overrides)
        except envelopes.EnvelopeError as exc:
            raise StoreError(str(exc)) from exc
        meta["envelope"] = {"kind": kind, "overrides": overrides}
    if contributions is not None:
        try:
            meta["contributions"] = envelopes.contributions(contributions)
        except envelopes.EnvelopeError as exc:
            raise StoreError(str(exc)) from exc
        meta["amount"] = max(meta["contributions"]["initial"], 1.0)
    if holdings is not None:
        clean = {}
        for k, v in holdings.items():
            if k in meta["funds"] and v not in (None, ""):
                if float(v) < 0:
                    raise StoreError("Un montant détenu ne peut pas être négatif.")
                if float(v) > 0:
                    clean[k] = float(v)
        meta["holdings"] = clean
    if groups is not None:
        clean_groups = []
        for g in groups[:12]:
            members = [k for k in (g.get("keys") or []) if k in meta["funds"]] if g.get("keys") else []
            cat = g.get("category")
            if cat and cat not in envelopes.CATEGORIES:
                raise StoreError("Catégorie inconnue dans une contrainte.")
            lo, hi = float(g.get("min") or 0), float(g.get("max") if g.get("max") not in (None, "") else 1)
            if not 0 <= lo <= hi <= 1:
                raise StoreError("Une contrainte de groupe doit avoir 0 ≤ minimum ≤ maximum ≤ 100 %.")
            if not members and not cat:
                continue
            clean_groups.append({"category": cat, "keys": members, "min": lo, "max": hi})
        meta["groups"] = clean_groups
    if couple is not None:
        meta["couple"] = bool(couple)
    save_meta(meta)
    return meta


def remove_fund(dataset_id: str, key: str) -> None:
    meta = get_meta(dataset_id)
    if key not in meta["funds"] or not loader.KEY_RE.match(key):
        raise StoreError("Fonds introuvable.")
    (_dir(dataset_id) / "series" / f"{key}.csv").unlink(missing_ok=True)
    (_dir(dataset_id) / "raw" / f"{key}.csv").unlink(missing_ok=True)
    del meta["funds"][key]
    meta["holdings"].pop(key, None)
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
