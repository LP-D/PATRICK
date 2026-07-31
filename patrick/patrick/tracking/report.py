"""Export HTML d'un run (Phase 3.3) — lit uniquement la base SQLite (jamais le
modèle/les données), donc disponible même longtemps après un run, sur une
machine qui n'a plus les artefacts CSV/joblib d'origine.

Autonome (CSS inline, pas de dépendance réseau), même charte visuelle sombre/or
que l'interface web (`webapp/static/style.css`) pour rester cohérent, mais
généré une fois en fichier statique — pas de gabarit Jinja2 vivant, ce rapport
n'est jamais re-servi par le process web.
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
from datetime import datetime, timezone

from patrick.selection import stability as stability_module
from patrick.tracking import db as trackdb
from patrick.tracking import holdout_diagnostic as trackholdout
from patrick.tracking import jobs as jobs_db

DEFAULT_REPORTS_DIR = os.path.expanduser("~/.patrick/reports")


def _fold_metrics_summary(conn: sqlite3.Connection, trial_id: int, split: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT metric, AVG(value) FROM fold_metric WHERE trial_id = ? AND split = ? GROUP BY metric",
        (trial_id, split),
    ).fetchall()
    return {metric: value for metric, value in rows}


def _trials_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT trial_id, regime, algo, sampler, n_features, selector, params_json, is_best "
        "FROM trial WHERE run_id = ? ORDER BY trial_id", (run_id,),
    ).fetchall()
    trials = []
    for trial_id, regime, algo, sampler, n_features, selector, params_json, is_best in rows:
        trials.append({
            "trial_id": trial_id, "regime": regime, "algo": algo, "sampler": sampler,
            "n_features": n_features, "selector": selector,
            "params": json.loads(params_json) if params_json else {},
            "is_best": bool(is_best),
            "test_metrics": _fold_metrics_summary(conn, trial_id, "test"),
            "holdout_metrics": _fold_metrics_summary(conn, trial_id, "holdout"),
        })
    return trials


def _baselines_for_run(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT baseline, metric, value FROM baseline_metric "
        "WHERE run_id = ? AND split = 'test' ORDER BY baseline, metric", (run_id,),
    ).fetchall()
    out: dict[str, dict[str, float]] = {}
    for baseline, metric, value in rows:
        out.setdefault(baseline, {})[metric] = value
    return [{"baseline": b, "metrics": m} for b, m in out.items()]


def _job_stats_for_run(conn: sqlite3.Connection, job_id: str | None) -> dict | None:
    """Holdout/DM/PBO/compteur d'essais cumulé (Phase 2) ne sont persistés que
    dans `job.result_json` (calculés une fois pour la config gagnante de tout
    l'appel `run_pipeline`, pas par run/horizon individuellement) — seuls les
    runs lancés depuis l'interface web ont un `job_id` ; un `patrick run`/
    `patrick resume` en CLI n'en a pas et ne peut donc pas les afficher ici
    (limite connue, cf. rapport de phase — pas de nouvelle table dédiée pour
    ça, hors scope Phase 3)."""
    if not job_id:
        return None
    job = jobs_db.get_job(conn, job_id)
    if job is None or not job.get("result_json"):
        return None
    result = json.loads(job["result_json"])
    return {
        "holdout": result.get("holdout"),
        "diebold_mariano": result.get("diebold_mariano"),
        "pbo": result.get("pbo"),
        "cumulative_trials": result.get("cumulative_trials"),
    }


def _fmt_metrics_table(metrics: dict[str, float]) -> str:
    if not metrics:
        return "<p class='hint'>—</p>"
    cells = "".join(
        f"<tr><td>{html.escape(k)}</td><td class='num'>{v:.4f}</td></tr>"
        for k, v in sorted(metrics.items())
    )
    return f"<table class='metrics'><tbody>{cells}</tbody></table>"


def _section(title: str, body: str) -> str:
    return f"<section class='card'><h2>{html.escape(title)}</h2>{body}</section>"


def _fmt_pbo_reliability(reliability: dict | None) -> str:
    """Rapport de correction, C5 -- un PBO ponctuel isolé n'est pas
    interprétable seul (audit : écart-type ~0.16 sur un tirage unique à
    n_blocks=16, pire à n_blocks=4). Affiche l'intervalle de confiance par
    bootstrap à côté du point, ou le message de refus explicite si trop peu
    de blocs -- jamais un chiffre nu sans ce contexte."""
    if not reliability:
        return ""
    if not reliability.get("ok"):
        return f"<br><span class='flag'>{html.escape(reliability.get('message', ''))}</span>"
    return (
        f"<br><span class='hint'>IC 90% (bootstrap, {reliability['n_combinations']} combinaisons) : "
        f"[{reliability['ci_low']:.3f}, {reliability['ci_high']:.3f}] "
        f"(écart-type bootstrap {reliability['bootstrap_std']:.3f}) -- "
        "<strong>un PBO issu d'un run unique n'est pas interprétable isolément</strong>, "
        "cf. rapport d'audit.</span>"
    )


def generate_report_html(run_id: str, db_path: str | None = None) -> str:
    conn = trackdb.connect(db_path)
    try:
        run = trackdb.get_run(conn, run_id)
        if run is None:
            raise ValueError(f"Run introuvable : {run_id}")
        trials = _trials_for_run(conn, run_id)
        baselines = _baselines_for_run(conn, run_id)
        job_stats = _job_stats_for_run(conn, run.get("job_id"))
        # Rapport d'audit, C4 -- diagnostic LECTURE SEULE (jamais utilisé pour
        # choisir une config, cf. patrick/tracking/holdout_diagnostic.py) :
        # lu directement en base (contrairement à holdout/DM/PBO ci-dessus,
        # persisté par run, disponible aussi pour un `patrick run`/`resume` CLI
        # sans job web associé).
        holdout_diag = trackholdout.spearman_test_vs_holdout(conn, run_id, metric="F1_dir")
        quality_issues = trackdb.list_data_quality_issues(conn, run["snapshot_id"])
        feature_stability = trackdb.get_feature_stability(conn, run_id)
    finally:
        conn.close()

    config = json.loads(run["config_json"])
    lib_versions = json.loads(run.get("lib_versions") or "{}") if run.get("lib_versions") else {}

    trials_html = "".join(f"""
        <tr class="{'best' if t['is_best'] else ''}">
            <td>{t['trial_id']}</td><td>{html.escape(t['regime'])}</td>
            <td>{html.escape(t['algo'])}</td><td>{html.escape(t['sampler'])}</td>
            <td class="num">{t['n_features']}</td><td>{html.escape(t['selector'])}</td>
            <td class="num">{t['test_metrics'].get('F1_dir', float('nan')):.4f}</td>
            <td>{'★ meilleur' if t['is_best'] else ''}</td>
        </tr>""" for t in trials)

    best_trial = next((t for t in trials if t["is_best"]), None)
    holdout_from_trial = best_trial["holdout_metrics"] if best_trial else {}

    baselines_html = "".join(
        f"<tr><td>{html.escape(b['baseline'])}</td>{_fmt_metrics_table(b['metrics'])}</tr>"
        for b in baselines
    ) or "<tr><td colspan='2' class='hint'>Aucune baseline enregistrée.</td></tr>"

    if job_stats:
        dm = job_stats.get("diebold_mariano")
        pbo = job_stats.get("pbo")
        stats_html = f"""
        <p><strong>Essais cumulés (tout historique, table `trial`)</strong> : {job_stats.get('cumulative_trials', '—')}</p>
        <p><strong>Diebold-Mariano</strong> (meilleur modèle vs {html.escape(dm['baseline']) if dm else '—'}) :
           p-value = {f"{dm['p_value']:.4f}" if dm else '—'}
           {" <span class='flag'>non significatif (p ≥ 0.05)</span>" if dm and dm['p_value'] >= 0.05 else ''}</p>
        <p><strong>PBO</strong> (CSCV, {pbo['n_blocks'] if pbo else '—'} blocs) :
           {f"{pbo['pbo']:.3f}" if pbo else '—'}
           {_fmt_pbo_reliability(pbo.get('reliability') if pbo else None)}</p>
        <p><strong>Holdout terminal</strong> (job) : {_fmt_metrics_table(job_stats.get('holdout') or {})}</p>
        """
    else:
        stats_html = ("<p class='hint'>Non disponible : run lancé hors interface web "
                       "(pas de job associé) — holdout/DM/PBO calculés au niveau du job, "
                       "pas persistés séparément par run pour un <code>patrick run</code>/"
                       "<code>patrick resume</code> en CLI.</p>")
        if holdout_from_trial:
            stats_html += f"<p><strong>Holdout (essai gagnant, table fold_metric)</strong></p>{_fmt_metrics_table(holdout_from_trial)}"

    if holdout_diag["n_trials"] >= 3:
        diag_html = (f"ρ = {holdout_diag['rho']:.4f} (p = {holdout_diag['p_value']:.4f}, "
                     f"n = {holdout_diag['n_trials']} trials)")
    else:
        diag_html = f"non calculable (n = {holdout_diag['n_trials']} trials avec test+holdout, minimum 3)"
    stats_html += (
        "<p><strong>Diagnostic — corrélation de rang test vs holdout (F1_dir), "
        "grille SCAN complète</strong> : "
        f"{diag_html} "
        "<span class='hint'>Lecture seule : ne choisit jamais une config, n'informe que ce rapport "
        "(cf. rapport d'audit, C4).</span></p>"
    )

    dq_cfg = config.get("data_quality", {})
    dq_enabled = dq_cfg.get("enabled", True)
    if dq_enabled:
        if quality_issues:
            issues_html = "".join(
                f"<tr><td>{html.escape(i['series'])}</td><td>{html.escape(i['reason'])}</td>"
                f"<td>{html.escape(i['detail'])}</td></tr>" for i in quality_issues)
            quality_html = (
                f"<p><strong>Portes de qualité de données</strong> : <span class='on'>actives</span> "
                f"— {len(quality_issues)} série(s) exclue(s) de l'univers de ce snapshot.</p>"
                f"<table><thead><tr><th>Série</th><th>Motif</th><th>Détail</th></tr></thead>"
                f"<tbody>{issues_html}</tbody></table>"
            )
        else:
            quality_html = ("<p><strong>Portes de qualité de données</strong> : "
                             "<span class='on'>actives</span> — aucune exclusion sur ce snapshot.</p>")
    else:
        quality_html = ("<p><strong>Portes de qualité de données</strong> : "
                         "<span class='off'>désactivées</span> pour ce run "
                         "(<code>data_quality.enabled: false</code>).</p>")

    stability_enabled = config.get("selection", {}).get("track_stability", True)
    if not stability_enabled:
        stability_html = ("<p><strong>Stabilité de la sélection de features</strong> : "
                           "<span class='off'>désactivée</span> pour ce run "
                           "(<code>selection.track_stability: false</code>).</p>")
    elif feature_stability is None:
        stability_html = ("<p><strong>Stabilité de la sélection de features</strong> : "
                           "<span class='off'>non calculée</span> (aucune config n'a pu être "
                           "évaluée sur au moins 2 folds pour cet horizon).</p>")
    else:
        mj = feature_stability["mean_jaccard"]
        mj_str = f"{mj:.3f}" if mj == mj else "non calculable (< 2 folds)"
        warn_html = ""
        if mj == mj and mj < stability_module.MIN_MEAN_JACCARD_WARNING:
            warn_html = (f"<p class='flag'>Sous le seuil ({stability_module.MIN_MEAN_JACCARD_WARNING}) -- "
                          "sélection instable, indiscernable de l'artefact de corrélation mesuré sur "
                          "données sans signal réel (cf. rapport de correction P6.3). Le signal "
                          "identifié n'est pas démontré reproductible.</p>")
        freq_rows_html = "".join(
            f"<tr><td>{html.escape(r['feature'])}</td><td class='num'>{r['selection_freq']:.0%}</td></tr>"
            for r in feature_stability["selection_freq"][:20]
        ) or "<tr><td colspan='2' class='hint'>Aucune donnée.</td></tr>"
        stability_html = (
            f"<p><strong>Stabilité de la sélection de features</strong> (Jaccard moyen entre "
            f"{feature_stability['n_folds']} folds, config gagnante de cet horizon) : "
            f"<span class='on'>{mj_str}</span></p>{warn_html}"
            f"<p class='hint'>Fréquence de sélection par feature (top 20) :</p>"
            f"<table><thead><tr><th>Feature</th><th class='num'>Sélectionnée (folds)</th></tr></thead>"
            f"<tbody>{freq_rows_html}</tbody></table>"
        )
    quality_html += stability_html

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8">
<title>PATRICK — rapport de run {html.escape(run_id)}</title>
<style>
  :root {{ --bg:#0B0D12; --panel:#151822; --panel-2:#1b1f2b; --gold-1:#E8C97A; --text:#E7E9EE; --muted:#8A90A2; }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: Inter, system-ui, sans-serif;
          margin: 0; padding: 2.5rem 1.5rem; line-height: 1.5; }}
  h1 {{ font-family: 'Cormorant Garamond', Georgia, serif; color: var(--gold-1); font-size: 2.2rem; margin: 0 0 .25rem; }}
  h2 {{ font-family: 'Cormorant Garamond', Georgia, serif; color: var(--gold-1); font-size: 1.4rem; margin: 0 0 .75rem; }}
  .subtitle {{ color: var(--muted); margin: 0 0 2rem; }}
  .card {{ background: var(--panel); border: 1px solid #262b3a; border-radius: 10px;
           padding: 1.25rem 1.5rem; margin: 0 auto 1.25rem; max-width: 920px; }}
  table {{ width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }}
  th, td {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #262b3a; font-size: .92rem; }}
  th {{ color: var(--muted); font-weight: 600; }}
  td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  tr.best {{ background: rgba(232,201,122,0.08); }}
  .hint {{ color: var(--muted); font-size: .9rem; }}
  .flag {{ color: #E39A9A; font-size: .85rem; }}
  .on {{ color: #3FA985; }}
  .off {{ color: #C1544C; }}
  pre {{ background: var(--panel-2); border-radius: 8px; padding: .9rem; overflow-x: auto; font-size: .85rem; }}
  code {{ background: var(--panel-2); padding: .1rem .3rem; border-radius: 4px; }}
  table.metrics {{ margin: .25rem 0 0; }}
</style></head>
<body>
<h1>Rapport de run — {html.escape(config.get('name', run_id))}</h1>
<p class="subtitle">run_id={html.escape(run_id)} · cible={html.escape(run['target'])} · horizon={run['horizon']}j ·
   statut={html.escape(run['status'])} · généré le {generated_at}</p>

{_section("Reproductibilité", f'''
<table><tbody>
<tr><td>Snapshot</td><td>{html.escape(run["snapshot_id"])}</td></tr>
<tr><td>Config hash</td><td>{html.escape(run["config_hash"])}</td></tr>
<tr><td>Git SHA</td><td>{html.escape(run["git_sha"])}</td></tr>
<tr><td>Seed</td><td class="num">{run["seed"]}</td></tr>
<tr><td>Démarré</td><td>{html.escape(run["started_at"] or "—")}</td></tr>
<tr><td>Terminé</td><td>{html.escape(run["finished_at"] or "—")}</td></tr>
<tr><td>Essais (ce run)</td><td class="num">{run["n_trials"] if run["n_trials"] is not None else len(trials)}</td></tr>
</tbody></table>
<p class="hint">Versions des dépendances :</p>
<pre>{html.escape(json.dumps(lib_versions, indent=1, sort_keys=True))}</pre>
''')}

{_section("Corrections phase 6 (rigueur d'échantillonnage)", quality_html)}

{_section("Configuration", f"<pre>{html.escape(json.dumps(config, indent=1, ensure_ascii=False))}</pre>")}

{_section("Essais (table `trial`)", f'''
<table>
<thead><tr><th>#</th><th>Régime</th><th>Algo</th><th>Sampler</th><th class="num">N</th>
<th>Sélecteur</th><th class="num">F1_dir (test, moy. folds)</th><th></th></tr></thead>
<tbody>{trials_html}</tbody>
</table>
''')}

{_section("Baselines systématiques", f'''
<table><thead><tr><th>Baseline</th><th>Métriques (test)</th></tr></thead>
<tbody>{baselines_html}</tbody></table>
''')}

{_section("Validité statistique (Phase 2)", stats_html)}

{_section("Importances SHAP", "<p class='hint'>Non incluses : les features sélectionnées "
          "ne sont actuellement pas persistées par nom en base (seul le nombre `N` l'est) — "
          "limite connue, hors scope Phase 3.</p>")}

</body></html>"""


def save_report(run_id: str, output_path: str | None = None, db_path: str | None = None) -> str:
    html_content = generate_report_html(run_id, db_path=db_path)
    if output_path is None:
        os.makedirs(DEFAULT_REPORTS_DIR, exist_ok=True)
        output_path = os.path.join(DEFAULT_REPORTS_DIR, f"{run_id}.html")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    return output_path
