"""Score de robustesse d'un run (FO8 du 25/11) : une note sur 100 qui rassemble les preuves dispersées sur la page d'un run.

Chaque preuve rapporte des points, et la note dit d'abord ce qui MANQUE. Rien n'est recalculé : le score lit ce que la page affiche déjà.

| preuve | points | lu dans |
|---|---|---|
| Diebold-Mariano : le modèle bat sa référence (p unilatérale < 5 %) | 25 | `dm_result` |
| la cible survit à Benjamini-Hochberg (famille de cibles) | 15 | `target_fdr` |
| placebo : le score s'effondre quand les variables sont décalées d'un jour de plus (pas de fuite du jour même) | 20 | `placebo_verdict` |
| PBO (probabilité de surapprentissage du choix) sous 50 % et fiable | 15 | `pbo` |
| assez d'observations indépendantes au holdout (N_eff ≥ 30) | 15 | `sizes.holdout.n_eff` |
| aucune alerte « score suspect » ni alignement d'avant la correction | 10 | `suspect`, `alignment_reason` |

Lecture : 80 et plus = preuves convergentes ; 50-79 = à confirmer ; sous 50 = la performance affichée ne s'appuie pas sur grand-chose.
Le score n'est PAS une performance : un modèle sans avantage mais honnêtement mesuré peut avoir peu de points (il ne bat rien), un
modèle à F1 spectaculaire mais fuyant en a encore moins.
"""
from __future__ import annotations

import math

DM_ALPHA = 0.05
N_EFF_MIN = 30


def score(detail: dict | None, run_method: dict | None = None) -> dict | None:
    """`{score, max, grade, parts: [{key, points, max, ok, note}]}` ; None sans détail de run."""
    if not detail:
        return None
    run_method = run_method or {}
    parts = []

    def add(key: str, points_max: int, ok: bool | None, note: str) -> None:
        parts.append({"key": key, "max": points_max, "ok": ok, "points": points_max if ok else 0, "note": note})

    dm = detail.get("dm_result") or {}
    p = dm.get("p_value")
    if detail.get("is_cpcv"):
        add("dm", 25, None, "non calculé en CPCV")
    elif p is None:
        add("dm", 25, None, "Diebold-Mariano non testable")
    else:
        add("dm", 25, p < DM_ALPHA and not dm.get("worse"), f"p unilatérale = {p:.3f}")
    fdr = detail.get("target_fdr") or {}
    add("bh", 15, bool(fdr.get("significant")) if fdr else None,
        "cible retenue par Benjamini-Hochberg" if fdr.get("significant") else "cible non retenue par Benjamini-Hochberg")
    verdict = run_method.get("placebo_verdict")
    add("placebo", 20, None if verdict is None else verdict != "same_day",
        "pas de placebo pour ce run" if verdict is None else ("score stable quand on décale les variables : fuite du jour même possible"
                                                              if verdict == "same_day" else "le score s'effondre au placebo : pas de fuite"))
    pbo = detail.get("pbo") or {}
    value = pbo.get("pbo")
    reliable = bool((pbo.get("reliability") or {}).get("ok"))
    if value is None or math.isnan(float(value)):
        add("pbo", 15, None, "PBO non calculé")
    else:
        add("pbo", 15, reliable and value < 0.5, f"PBO = {value:.2f}{'' if reliable else ' (peu fiable)'}")
    n_eff = ((detail.get("sizes") or {}).get("holdout") or {}).get("n_eff")
    add("n_eff", 15, None if n_eff is None else n_eff >= N_EFF_MIN,
        "pas de holdout" if n_eff is None else f"N_eff = {n_eff} au holdout (seuil {N_EFF_MIN})")
    clean = not detail.get("suspect") and not run_method.get("alignment_reason")
    add("clean", 10, clean, "aucune alerte" if clean else "score suspect ou alignement d'avant la correction")

    total = sum(x["points"] for x in parts)
    grade = "solid" if total >= 80 else ("confirm" if total >= 50 else "weak")
    return {"score": total, "max": sum(x["max"] for x in parts), "grade": grade, "parts": parts}
