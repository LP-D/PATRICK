"""Exécution des cartes avec cache, et registre FDR de toutes les études testées.

Chaque carte se calcule une fois : le résultat est mis en cache sous (étude, périmètre, paramètres + réglages d'affichage,
version des données). La version des données change dès qu'un événement est ajouté ou recalculé (et, pour les cartes qui lisent
des instantanés ou des news, dès qu'un instantané ou une nouvelle arrive), si bien qu'un cache ne sert jamais un résultat périmé.

Registre FDR : une bibliothèque de plusieurs dizaines d'études, de fenêtres et de sous-groupes produit mécaniquement des « résultats
significatifs » qui sont du bruit. Toutes les p-values des cartes calculées (clé `pvalues`) sont rassemblées et corrigées par
Benjamini-Hochberg ; c'est CE tableau, pas le p brut d'une carte, qui dit ce qui survit.
"""
from __future__ import annotations

import hashlib
import json
import logging
import traceback
from datetime import UTC, datetime

from patrick.earnings import store
from patrick.earnings.studies import base
from patrick.earnings.studies.base import REGISTRY, Ctx
from patrick.validation.fdr import benjamini_hochberg

log = logging.getLogger(__name__)


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:10]


def data_version(ctx: Ctx, study: base.Study) -> str:
    version = f"{ctx.panel.signature}|{ctx.full.signature}"
    if "snapshots" in study.needs or "analysts" in study.needs:
        version += f"|snap{sum(store.snapshot_counts(ctx.conn).values())}"
    if "news" in study.needs:
        try:
            version += f"|news{ctx.conn.execute('SELECT COUNT(*) FROM news_item').fetchone()[0]}"
        except Exception:  # noqa: BLE001 -- base sans table de news : version sans elle
            version += "|news0"
    return version


def run_study(ctx: Ctx, study_id: str, params: dict | None = None, force: bool = False) -> dict:
    if study_id not in REGISTRY:
        raise KeyError(f"étude inconnue : {study_id}")
    study = REGISTRY[study_id]
    resolved = study.resolve_params(params)
    params_hash = _digest({"p": resolved, "cfg": ctx.cfg.to_dict()})
    version = data_version(ctx, study)
    scope_key = ctx.scope.key
    if not force:
        hit = store.get_study(ctx.conn, study_id, scope_key, params_hash, version)
        if hit is not None:
            return {**hit, "cached": True}
    try:
        result = study.run(ctx, resolved)
    except Exception as exc:  # noqa: BLE001 -- une carte en échec n'arrête pas les autres ; l'erreur est montrée, jamais cachée
        log.warning("étude %s en échec : %s", study_id, traceback.format_exc())
        return {"study_id": study_id, "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "n": 0, "blocks": [],
                "pvalues": {}, "reliability": None, "flags": [], "params": resolved, "cached": False}
    result = {**result, "study_id": study_id, "params": resolved, "computed_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M"),
              "cached": False}
    store.put_study(ctx.conn, study_id, scope_key, params_hash, version, result)
    return result


def run_many(ctx: Ctx, study_ids: list[str], params_by_id: dict | None = None, force: bool = False, progress=None) -> dict[str, dict]:
    out = {}
    for i, sid in enumerate(study_ids):
        out[sid] = run_study(ctx, sid, (params_by_id or {}).get(sid), force)
        if progress:
            progress(i + 1, len(study_ids), sid)
    return out


def fdr_ledger(results: dict[str, dict], alpha: float = 0.10) -> dict:
    """Corrige par Benjamini-Hochberg l'ensemble des p-values des cartes passées en argument."""
    pvals: dict[str, float] = {}
    for sid, res in results.items():
        for name, p in (res.get("pvalues") or {}).items():
            if p is not None:
                pvals[f"{sid} · {name}"] = float(p)
    bh = benjamini_hochberg(pvals, alpha=alpha)
    rows = [{"key": k, "study": k.split(" · ", 1)[0], "p": v["p_value"], "q": v["adjusted_p_value"], "raw": v["p_value"] <= alpha,
             "survives": bool(v["significant"])} for k, v in bh["results"].items()]
    return {"alpha": alpha, "n_tested": bh["n_tested"], "n_raw": bh["n_raw_significant"], "n_bh": bh["n_bh_significant"],
            "rows": sorted(rows, key=lambda r: r["q"])}


def ledger_inputs(ctx: Ctx) -> dict[str, dict]:
    """Toutes les cartes déjà calculées pour ce périmètre (quelles que soient leurs variantes de paramètres) : le registre FDR doit
    compter TOUS les tests essayés, pas seulement les réglages par défaut, sinon explorer des variantes ferait croire à moins de tests."""
    versions = {sid: data_version(ctx, st) for sid, st in REGISTRY.items()}
    out = {}
    for row in store.cached_study_rows(ctx.conn, ctx.scope.key, versions):
        out[f"{row['study_id']}#{row['params_hash'][:4]}"] = row["payload"]
    return out
