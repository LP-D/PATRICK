"""Explication des p-values et des résultats statistiques, adossée à UN run de référence (bandeau d'aide en bas de page).

`build` transforme le détail d'un run (`tracking/history.py::run_detail`) en une liste d'éléments prêts à afficher : pour
chaque résultat statistique, sa valeur sur CE run, ce qu'elle signifie et la réserve à garder en tête ; puis la procédure
réellement appliquée (données, validation, holdout, test, correction). Aucun texte ici : seulement des clés de traduction
(`i18n_pages.py`) et leurs arguments."""
from __future__ import annotations

DEFAULT_DM_ALPHA = 0.05
DEFAULT_FDR_ALPHA = 0.10


def _fmt(value, digits: int = 4) -> str | None:
    return None if value is None else f"{value:.{digits}f}"


def pvalue_items(detail: dict, dm_alpha: float = DEFAULT_DM_ALPHA, fdr_alpha: float = DEFAULT_FDR_ALPHA) -> list[dict]:
    """Un élément par résultat statistique : `{key, state, value, reading, args}`. `state` : ok | warning | neutral | disabled."""
    items: list[dict] = []
    dm = detail.get("dm_result")
    if detail.get("is_cpcv"):
        items.append({"key": "dm", "state": "disabled", "value": None, "reading": "sh_dm_cpcv", "args": {}})
    elif dm:
        biased = dm.get("sample") == "last_wf_fold"
        p = dm["p_value"]
        items.append({
            "key": "dm", "state": "warning" if biased or p >= dm_alpha else "ok", "value": _fmt(p),
            "reading": "sh_dm_biased" if biased else ("sh_dm_significant" if p < dm_alpha else "sh_dm_not_significant"),
            "args": {"p": _fmt(p), "alpha": f"{dm_alpha:g}", "baseline": dm.get("baseline"), "n": dm.get("n_obs") or "—"}})
    else:
        items.append({"key": "dm", "state": "disabled", "value": None, "reading": "sh_dm_missing", "args": {}})

    fdr = detail.get("target_fdr")
    fdr_all = detail.get("fdr_result") or {}
    if fdr:
        items.append({"key": "bh", "state": "ok" if fdr.get("significant") else "warning",
                      "value": _fmt(fdr.get("adjusted_p_value")),
                      "reading": "sh_bh_significant" if fdr.get("significant") else "sh_bh_not_significant",
                      "args": {"adj": _fmt(fdr.get("adjusted_p_value")), "rank": fdr.get("rank"),
                               "n": fdr_all.get("n_tested"), "alpha": f"{fdr_all.get('alpha', fdr_alpha):g}"}})
    else:
        items.append({"key": "bh", "state": "disabled", "value": None, "reading": "sh_bh_missing", "args": {}})

    diag = detail.get("holdout_diag") or {}
    if (diag.get("n_trials") or 0) >= 3 and diag.get("rho") is not None:
        items.append({"key": "spearman", "state": "neutral", "value": _fmt(diag["rho"], 3), "reading": "sh_spearman",
                      "args": {"rho": _fmt(diag["rho"], 3), "p": _fmt(diag.get("p_value")), "n": diag["n_trials"]}})
    else:
        items.append({"key": "spearman", "state": "disabled", "value": None, "reading": "sh_spearman_missing",
                      "args": {"n": diag.get("n_trials") or 0}})

    pbo = detail.get("pbo") or {}
    rel = pbo.get("reliability") or {}
    if rel.get("ok") and pbo.get("pbo") is not None:
        items.append({"key": "pbo", "state": "ok" if pbo["pbo"] < 0.5 else "warning", "value": _fmt(pbo["pbo"], 3),
                      "reading": "sh_pbo", "args": {"pbo": _fmt(pbo["pbo"], 3), "lo": _fmt(rel.get("ci_low"), 3),
                                                    "hi": _fmt(rel.get("ci_high"), 3), "n": rel.get("n_combinations")}})
    else:
        items.append({"key": "pbo", "state": "disabled", "value": None, "reading": "sh_pbo_missing", "args": {}})

    items.append({"key": "trials", "state": "neutral", "value": str(detail.get("cumulative_trials") or 0),
                  "reading": "sh_trials", "args": {"n": detail.get("cumulative_trials") or 0}})
    return items


def procedure_steps(detail: dict, dm_alpha: float = DEFAULT_DM_ALPHA, fdr_alpha: float = DEFAULT_FDR_ALPHA) -> list[dict]:
    """La procédure réellement appliquée à ce run, étape par étape : `{key, args}`."""
    cfg = detail.get("config") or {}
    val = cfg.get("validation") or {}
    obj = cfg.get("objective") or {}
    align = obj.get("alignment") or {}
    dm = detail.get("dm_result") or {}
    fdr_all = detail.get("fdr_result") or {}
    steps = [
        {"key": "data", "args": {"snapshot": (detail.get("run") or {}).get("snapshot_id") or "—",
                                  "shifted": len(align.get("column_lags") or {}), "dropped": len(align.get("dropped") or [])}},
        {"key": "scheme_cpcv" if detail.get("is_cpcv") else "scheme_wf",
         "args": {"folds": val.get("n_wf_folds", "—"), "train": f"{float(val.get('min_train_frac', 0)) * 100:.0f}",
                  "groups": val.get("n_groups", "—"), "k": val.get("k_test_groups", "—"),
                  "embargo": "oui" if val.get("embargo_enabled", True) else "non",
                  "purge": "oui" if val.get("purge") else "non"}},
        {"key": "selection", "args": {"run": len(detail.get("trials") or []), "all": detail.get("cumulative_trials") or 0}},
        {"key": "holdout_cpcv" if detail.get("is_cpcv") else "holdout",
         "args": {"months": val.get("holdout_months", "—")}},
    ]
    if dm:
        steps.append({"key": "dm_biased" if dm.get("sample") == "last_wf_fold" else "dm",
                      "args": {"baseline": dm.get("baseline"), "n": dm.get("n_obs") or "—", "alpha": f"{dm_alpha:g}"}})
    steps.append({"key": "bh", "args": {"alpha": f"{fdr_all.get('alpha', fdr_alpha):g}", "n": fdr_all.get("n_tested") or "—"}})
    return steps
