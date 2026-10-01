"""Rendu de `benchmark_reference.md` à partir du JSON. Les sections « mesuré »
sont produites mécaniquement ; les hypothèses/recommandations viennent d'un
fichier de notes rédigé à la main (`--notes`), rendu sous un titre séparé."""
from __future__ import annotations


def _pct(x: float, total: float) -> str:
    return f"{100 * x / total:.1f}%" if total else "n/a"


def _table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def _scenario_md(name: str, sc: dict) -> str:
    ref = sc["reference_run"]
    pdata = ref["profile_data"]
    total = pdata["total_wall_s"]
    L: list[str] = [f"### Scénario `{name}`", ""]
    rep = sc["reproducibility"]
    L.append(_table(["Indicateur", "Valeur"], [
        ["Durée totale (instrumentée, run de référence)", f"{total:.1f} s"],
        ["Temps CPU process (somme threads)", f"{pdata['total_cpu_s']:.1f} s (CPU/mural = {pdata['total_cpu_s'] / total:.2f})"],
        ["Pic mémoire RSS (process + enfants)", f"{pdata['peak_rss_mb']:.0f} MB"],
        ["Temps hors phases instrumentées", f"{pdata['unaccounted_wall_s']:.1f} s ({_pct(pdata['unaccounted_wall_s'], total)})"],
        ["Durées des répétitions instrumentées", ", ".join(f"{d:.1f} s" for d in sc["repeat_walls_s"])],
        ["Run non instrumenté", (f"{sc['plain_wall_s']:.1f} s -> surcoût instrumentation "
                                 + (f"{sc['instrumentation_overhead_pct']:+.1f}%" if sc.get("instrumentation_overhead_pct") is not None
                                    else "non mesurable (bruit >> surcoût, voir note)"))
         if sc.get("plain_wall_s") is not None else "non exécuté"],
        ["Run de référence des phases", sc.get("reference_run_label") or "rep1"],
    ]))
    L += ["", "**Durée par phase**", ""]
    rows = []
    for pname, p in sorted(pdata["phases"].items(), key=lambda kv: -kv[1]["wall_s"]):
        rows.append([pname, f"{p['wall_s']:.2f}", _pct(p["wall_s"], total), f"{p['cpu_s']:.2f}", f"{p['peak_rss_mb']:.0f}", p["count"]])
    L.append(_table(["Phase", "Mural (s)", "% total", "CPU (s)", "Pic RSS (MB)", "Occurrences"], rows))
    L += ["", "**Compteurs (totaux du run)**", ""]
    ct = pdata["counter_totals"]
    L.append(_table(["Compteur", "Valeur"], [[k, v] for k, v in ct.items()]))
    L += ["", "**Composants (temps exclusif cumulé, toutes phases)**", ""]
    comps = sorted(pdata["component_totals"].items(), key=lambda kv: -kv[1]["self_s"])[:18]
    L.append(_table(["Composant", "Appels", "Exclusif (s)", "% total", "Inclusif (s)"],
                    [[c, a["count"], f"{a['self_s']:.2f}", _pct(a["self_s"], total), f"{a['inclusive_s']:.2f}"] for c, a in comps]))
    L += ["", "**Composants par phase (top 6 par phase, exclusif)**", ""]
    for pname, p in sorted(pdata["phases"].items(), key=lambda kv: -kv[1]["wall_s"]):
        if p["wall_s"] < 0.02 * total:
            continue
        top = sorted(p["components"].items(), key=lambda kv: -kv[1]["self_s"])[:6]
        L.append(f"- `{pname}` ({p['wall_s']:.1f} s): " + "; ".join(
            f"{c} {a['self_s']:.1f}s (x{a['count']})" for c, a in top))
    L += ["", "**Recalculs observés** (appels vs clés distinctes)", ""]
    dk = pdata["distinct_keys"]
    L.append(_table(["Quantité", "Appels", "Clés distinctes", "Redondance"],
                    [[k, v["calls"], v["distinct"], f"{v['calls'] - v['distinct']} appels répétés"] for k, v in dk.items()]))
    L += ["", "**Résultats du run**", ""]
    r = ref["results"]
    L.append(_table(["Élément", "Valeur"], [
        ["Lignes leaderboard", r["leaderboard_rows"]], ["Lignes Optuna re-évaluées (tuned)", r["tuned_rows"]],
        ["Trials SQLite (grille + configs tunées)", r["trials_db"]], ["Lignes fold_metric", r["fold_metric_rows"]],
        ["Lignes prediction", r["prediction_rows"]], ["Features distinctes retenues (leaderboard)", r["features_retained_distinct"]],
        ["Colonnes base pool", pdata["values"].get("base_pool.columns", "n/a")],
        ["Colonnes pool du dernier fold (base+param+interactions)", pdata["values"].get("fold_pool.columns_last", "n/a")],
        ["Champion", r["final_best"]]]))
    L += ["", "**Reproductibilité**", "",
          f"- même `data_hash`: {rep['same_data_hash']} ; même config: {rep['same_config_digest']} ; même seed: {rep['same_seed']}",
          f"- digests des artefacts identiques entre répétitions: {rep['digests_identical_across_repeats']}",
          f"- compteurs (calls/hit/miss/trials) identiques entre répétitions: {rep['counters_identical_across_repeats']}",
          f"- résultats identiques avec/sans instrumentation: {rep['instrumentation_leaves_results_unchanged']}"]
    if rep.get("differences"):
        L.append(f"- différences détectées: `{rep['differences']}`")
    if sc.get("warm_run"):
        w = sc["warm_run"]
        L += ["", f"**Run « cache de features tiède »** (même snapshot, cache disque des pools conservé, base SQLite neuve): "
              f"{w['wall_s']:.1f} s (vs {total:.1f} s à froid). Cache de pools : "
              + ", ".join(f"{k}={v}" for k, v in w["profile_data"]["counter_totals"].items() if k.startswith("feature_pool_cache"))]
    return "\n".join(L)


def render_markdown(data: dict, notes: str | None) -> str:
    spec = data["profile_spec"]
    ds = spec["dataset"]
    L = ["# Benchmark de référence PATRICK — Sprint 1 (mesure, aucune optimisation)", "",
         (f"Généré le {data['generated_at']} — commit `{data['git']['sha'][:10]}`"
          f"{' (working tree modifié)' if data['git']['dirty'] else ''}."), "",
         "> Sections 1-3 : **mesuré / observé**. Section 4 : **hypothèses / recommandations** (non mesurées).", "",
         "## 1. Configuration utilisée", "",
         (f"Profil `{spec['name']}` — dataset **synthétique** (graine {ds['seed']}) : {ds['n_days']} jours ouvrés, "
          f"{ds['n_tickers']} tickers + {ds['n_fred']} séries macro + cible, `data_hash` = `{data['data_hash']}`."), "",
         _table(["Paramètre", "Valeur"], [
             ["Horizons", spec["horizons"]], ["Folds walk-forward", spec["n_wf_folds"]],
             ["Grille N features", spec["n_features_grid"]], ["Algos", spec["algos"]], ["Samplers", spec["samplers"]],
             ["Modèles de vol (paramétriques)", spec["vol_models"]], ["shap_sample / pool_prefilter", f"{spec['shap_sample']} / {spec['pool_prefilter']}"],
             ["Holdout (mois)", spec["holdout_months"]],
             ["Optuna", f"top_k={spec['tuning_top_k']} par horizon, n_trials={spec['tuning_n_trials']}, cv_splits={spec['tuning_cv_splits']}"],
             ["CPCV", f"n_groups={spec['cpcv_n_groups']}, k_test_groups={spec['cpcv_k_test_groups']}"],
             ["Seed pipeline", data["seed"]], ["Répétitions instrumentées", data["repeats"]],
             ["Threads (OMP/OPENBLAS/MKL/NUMEXPR)", data["threads"]],
             ["Départ", "à froid : snapshot, base SQLite, cache de features et dossier Optuna neufs à chaque run"]]), "",
         ("Snapshot rejoué via `run_pipeline(snapshot_id=...)` (chemin `patrick resume`) : aucun réseau. "
          "`download_ohlc` (Yahoo) remplacé par un no-op déterministe, comme le golden master."), "",
         "## 2. Environnement", "",
         _table(["Élément", "Valeur"], [["Plateforme", data["environment"]["platform"]], ["CPU", data["environment"]["processor"]],
                                        ["Cœurs logiques", data["environment"]["cpu_count_logical"]], ["Python", data["environment"]["python"]],
                                        ["Env threads", data["environment"]["thread_env"]], ["Pools BLAS/OpenMP", data["environment"]["threadpools"]],
                                        ["Paquets", ", ".join(f"{k} {v}" for k, v in data["environment"]["packages"].items())]]), "",
         "## 3. Mesures", ""]
    if data.get("timing_noise_note"):
        L += [f"> **Bruit de mesure** : {data['timing_noise_note']}", ""]
    for name, sc in data["scenarios"].items():
        L += [_scenario_md(name, sc), ""]
    L += ["## 3b. Non-régression : artefacts sauvegardés", "",
          "Répertoire `benchmarks/baseline/<schéma>/` (pleine précision, digests arrondis à 10 décimales dans `digests.json`) : "
          + ", ".join(f"`{a}`" for a in data["baseline_artifacts"]) + ".", "",
          "**Absent / non disponible** (non reconstruit, le pipeline ne le persiste pas) :", ""]
    L += [f"- {m}" for m in data["not_available"]]
    L += ["", "## 3c. Impossible à mesurer / limites", ""] + [f"- {m}" for m in data["limits"]]
    L += ["", "## 4. Hypothèses et recommandations (non mesuré)", "", notes.strip() if notes else "_(aucune note fournie)_", ""]
    return "\n".join(L)
