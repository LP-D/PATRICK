"""`patrick`'s web interface: builds a `RunConfig` from a form (replaces
manual YAML editing), launches `run_pipeline` in the background, and
displays progress + leaderboard in the browser. User-facing strings (HTTP
error details, template labels) stay in French, matching the rest of the
web interface.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from patrick import explain
from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.webapp import alerts, asset_stats, forms, i18n, market_data, run_manager, shap_chart
from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS

# feature/ticker-stats-panel: the two DEFAULT_TARGET_GROUPS keys backing
# `/commodities` and `/macro` -- named once here rather than re-typed at
# each call site (route + tests both need the exact same key).
COMMODITIES_TARGET_GROUP = "Matières premières (futures)"

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="PATRICK")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

FORM_OPTIONS = {
    "all_families": forms.ALL_FEATURE_FAMILIES,
    "all_samplers": forms.ALL_SAMPLERS,
    "all_algos": forms.ALL_ALGOS,
    "all_vol_models": forms.ALL_VOL_MODELS,
    "all_horizons": forms.ALL_HORIZONS,
    "vol_model_labels": forms.VOL_MODEL_LABELS,
    "selection_methods": ["shap", "rfe", "lasso"],
    "target_groups": forms.TARGET_GROUPS,
}


@app.on_event("startup")
def _on_startup() -> None:
    alerts.start_background_refresh()


def _station_verdict() -> dict | None:
    """The station's verdict, rendered SERVER-side in every page's banner.
    No AJAX call like the activity strip: this is chrome data, it must be
    there on first render rather than appear afterward. A single aggregated
    query, read-only, fails silently — the banner must render even with no
    database (first install)."""
    try:
        conn = trackdb.connect()
    except Exception:
        return None
    try:
        return trackhistory.station_verdict(conn)
    except Exception:
        return None
    finally:
        conn.close()


def _i18n_context(request: Request) -> dict:
    lang = i18n.get_lang(request)
    t = i18n.translator(lang)
    return {
        "lang": lang,
        "t": t,
        "glossary": {k: t_entry.get(lang) or t_entry.get(i18n.DEFAULT_LANG) for k, t_entry in GLOSSARY.items()},
        "group_labels": {k: t(v) for k, v in i18n.TARGET_GROUP_LABEL_KEYS.items()},
        # Human-readable name per glossary term; terms that already carry
        # their own name (`technical`, `XGBoost`…) are absent from it and
        # the template falls back to the term itself.
        "glossary_labels": {k: t(v) for k, v in TERM_LABEL_KEYS.items()},
        "i18n_js": i18n.js_strings(lang),
        "verdict": _station_verdict(),
    }


@app.get("/set-lang/{lang}")
def set_lang(lang: str, next: str = "/"):
    lang = lang if lang in i18n.SUPPORTED_LANGS else i18n.DEFAULT_LANG
    resp = RedirectResponse(next or "/", status_code=303)
    resp.set_cookie(i18n.LANG_COOKIE, lang, max_age=60 * 60 * 24 * 365)
    return resp


def _recent_runs(limit: int = 8) -> list[dict]:
    """Most recent persisted runs, for the "progress" column of the home
    page AT REST. Without them, this column stays empty across the whole
    first-viewport height as long as no run is running -- even though the
    database has exactly what's needed to fill it. Read-only, fails
    silently: the home page must render even if the database does not exist
    yet (first install)."""
    try:
        conn = trackdb.connect()
    except Exception:
        return []
    try:
        return trackhistory.list_runs(conn, limit=limit)
    except Exception:
        return []
    finally:
        conn.close()


def _render_index(request: Request, view: dict, errors: list[str], status_code: int = 200,
                   initial_run_id: str | None = None):
    active = run_manager.active_run()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "view": view,
            "errors": errors,
            "examples": forms.list_example_configs(),
            "active_run": active,
            "queued_runs": run_manager.queued_runs(),
            "initial_run_id": initial_run_id if initial_run_id is not None else (active["id"] if active else None),
            "movers": alerts.get_cached(),
            "recent_runs": _recent_runs(),
            **FORM_OPTIONS,
            **_i18n_context(request),
        },
        status_code=status_code,
    )


@app.get("/launch")
def launch_page(request: Request, load: str | None = None):
    """P8 (synthesis dashboard chantier): moved from `/` to free that route
    for the new synthesis page. Same handler, same template
    (`index.html`), only the route changed -- nav/breadcrumb links updated
    accordingly (see `base.html`, `i18n.py::nav_launch`)."""
    if load:
        try:
            cfg = forms.load_example_config(load)
        except FileNotFoundError:
            return _render_index(request, forms.to_view(forms.default_config_dict()),
                                  [f"Config d'exemple introuvable : {load}"], status_code=404)
    else:
        cfg = forms.default_config_dict()
    return _render_index(request, forms.to_view(cfg), [])


@app.get("/")
def synthesis_page(request: Request):
    """P8 -- synthesis dashboard, replaces the old `/` (now `/launch`).
    Structure: coverage banner, per-target DM/BH quality, latest prediction
    per target, winning-model metrics per target (split by direction),
    condensed recent-run history -- all read live from the database on
    every request (no page cache), same components/tokens as `/phase9`.
    Reliability detail (full p-value, cumulative trials, BH detail) is not
    duplicated inline: it lives on `/targets/{ticker}`/`/runs/{id}`, one
    click away."""
    conn = trackdb.connect()
    try:
        overview = trackhistory.synthesis_overview(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "synthesis.html",
        {"overview": overview, **_i18n_context(request)},
    )


@app.get("/api/preview/{symbol}")
def preview(symbol: str, period: str = "1y"):
    source = forms.TARGET_SOURCE_BY_SYMBOL.get(symbol)
    if source is None:
        raise HTTPException(status_code=404, detail="Symbole inconnu")
    return market_data.price_history(symbol, source, period)


@app.get("/api/news/{symbol}")
def news(symbol: str):
    if symbol not in forms.TARGET_SOURCE_BY_SYMBOL:
        raise HTTPException(status_code=404, detail="Symbole inconnu")
    return {"items": market_data.latest_news(symbol)}


@app.get("/api/movers")
def movers():
    return alerts.get_cached()


@app.get("/api/next-run-names")
def next_run_names(target: list[str] = Query(default=[])):
    """(Read-only) preview of the name that will be assigned to each target
    if the form is submitted now — called by `app.js` when the target
    selection changes. Reserves nothing: the actual number may differ if
    other runs for the same target slot in before submission (see the
    batch-run-launch spec, known limitation)."""
    return {t: run_manager.next_run_name(t) for t in dict.fromkeys(target)}


@app.post("/runs")
async def create_run(request: Request):
    """Responds in JSON (consumed by `app.js` via AJAX, no page reload): a
    run starts immediately if none is active, otherwise queued — never
    rejected, `start_run` no longer raises an error in that case (see
    `run_manager.py`).

    A single submission can target several symbols at once (`<select
    multiple name="target_symbols">`): one job is enqueued per target, with
    distinct name/output directory (`run_manager.next_run_name`) — the
    existing FIFO queue chains them, no new orchestrator. If a single config
    is invalid among the submitted targets, nothing is enqueued."""
    form = await request.form()
    targets = list(dict.fromkeys(form.getlist("target_symbols")))
    if not targets:
        return JSONResponse({"errors": ["Sélectionne au moins une cible."]}, status_code=400)

    raw_output_dir = (form.get("output_dir") or "").strip()
    errors: list[str] = []
    configs: list[RunConfig] = []
    for sym in targets:
        name = run_manager.next_run_name(sym)
        config_dict, errs = forms.build_config_dict(form, target_symbol=sym, name=name)
        if errs:
            errors.extend(f"{sym} : {e}" for e in errs)
            continue
        # A manually entered output directory applies as-is to a single
        # target; for a batch, it is shared across the form -- without this
        # guard, N targets with the same explicit `output_dir` would
        # overwrite each other's artifacts.
        if len(targets) > 1 and raw_output_dir:
            config_dict["output"]["dir"] = f"{raw_output_dir}/{name}"
        try:
            configs.append(RunConfig.model_validate(config_dict))
        except ValidationError as exc:
            errors.extend(
                f"{sym} : {'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()
            )

    if errors:
        return JSONResponse({"errors": errors}, status_code=400)

    runs = []
    for config in configs:
        job_view = run_manager.start_run(config)
        runs.append({
            "run_id": job_view["id"],
            "status": job_view["status"],
            "queue_position": job_view["queue_position"],
            "target": config.objective.target_symbol,
        })
    return JSONResponse({"runs": runs})


@app.post("/runs/{run_id}/relaunch")
def relaunch_run(run_id: str):
    """Relaunches a past run identically, except for name/output directory
    (new number, see `run_manager.next_run_name`) -- a new attempt must be
    distinguishable in the history, not confused with the original. Works
    for a run submitted via the web (config found in the `job` table) and
    for a run launched via CLI (falls back to `run.config_json`, absent from
    `job`)."""
    config = run_manager.get_run_config(run_id)
    if config is None:
        conn = trackdb.connect()
        try:
            row = trackdb.get_run(conn, run_id)
        finally:
            conn.close()
        if row is None or not row["config_json"]:
            raise HTTPException(status_code=404, detail="Run introuvable (config indisponible)")
        config = RunConfig.model_validate_json(row["config_json"])

    new_name = run_manager.next_run_name(config.objective.target_symbol)
    cfg_dict = config.model_dump()
    cfg_dict["name"] = new_name
    # The relaunch's output directory reuses the ROOT (parent) of the
    # original config's directory -- a batch submitted with an explicit
    # `output_dir`, or a CLI-launched run with its own root, must not get
    # overwritten in favor of a hardcoded `runs/` relative to the web
    # process's cwd. Only the last component (the run's name) changes.
    original_dir = Path(config.output.dir)
    cfg_dict["output"]["dir"] = (
        str(original_dir.parent / new_name) if original_dir.parent != Path(".") else f"runs/{new_name}"
    )
    new_config = RunConfig.model_validate(cfg_dict)

    job_view = run_manager.start_run(new_config)
    return RedirectResponse(f"/runs/{job_view['id']}", status_code=303)


@app.get("/api/run-state")
def run_state():
    """Lightweight aggregated state (active run + queue) — periodic JS-side
    polling to track queue progress, distinct from the detailed polling of
    `/runs/{run_id}/status` (progress/logs of a specific run)."""
    active = run_manager.active_run()
    return {
        "active_run": {"id": active["id"], "name": active["name"]} if active else None,
        "queue": [{"id": s["id"], "name": s["name"]} for s in run_manager.queued_runs()],
    }


def _get_run_or_404(run_id: str) -> dict:
    job = run_manager.get_run(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Run introuvable (redémarrage du serveur ?)")
    return job


@app.get("/runs/{run_id}")
def run_page(request: Request, run_id: str):
    """Same dashboard as `index()` (a single template, `index.html`) — only
    `initial_run_id` changes, forced to this specific run rather than the
    current active one. Allows reopening/sharing the link of a past or
    ongoing run without duplicating the template. The settings form is
    prefilled with this run's real config (not the defaults).

    Phase 7.2 (P7.2) -- `run_manager.get_run` only knows about runs launched
    from the web interface (`job` table): a CLI `patrick run`/`patrick
    resume` never has an associated `job` row, and is therefore never found
    there. If this run_id has no job but exists in `run` (a table populated
    by every run, CLI or web), we fall back to the read-only detail page
    (`run_detail.html`) rather than returning a 404 -- the history must
    never become inaccessible through this link (see PRODUCT.md, "nothing
    is silently lost")."""
    if run_manager.get_run(run_id) is not None:
        config = run_manager.get_run_config(run_id)
        view = forms.to_view(config.model_dump())
        return _render_index(request, view, [], initial_run_id=run_id)

    conn = trackdb.connect()
    try:
        detail = trackhistory.run_detail(conn, run_id)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable (ni en mémoire, ni en base)")
    return templates.TemplateResponse(
        request, "run_detail.html", {"detail": detail, **_i18n_context(request)},
    )




@app.get("/runs/{run_id}/status")
def run_status(run_id: str):
    return _get_run_or_404(run_id)


@app.get("/runs/{run_id}/results")
def run_results(run_id: str):
    job = _get_run_or_404(run_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Run pas encore terminé (status={job['status']})")
    result = run_manager.get_run_result(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Résultat introuvable")
    return result


ARTIFACT_LABELS = {
    "leaderboard_csv": "Leaderboard (CSV)",
    "leaderboard_xlsx": "Leaderboard (Excel)",
    "tuned_csv": "Configs affinées (CSV)",
    "best_model": "Meilleur modèle (joblib)",
    "best_model_meta": "Métadonnées du modèle (JSON)",
}


@app.get("/runs/{run_id}/download/{artifact}")
def download_artifact(run_id: str, artifact: str):
    job = _get_run_or_404(run_id)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Run pas encore terminé")
    result = run_manager.get_run_result(run_id) or {}
    path = result.get("artifacts", {}).get(artifact)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Artefact introuvable")
    return FileResponse(path, filename=os.path.basename(path))


@app.get("/runs")
def runs_explorer(request: Request, target: str | None = None, status: str | None = None,
                   scheme: str | None = None):
    """Phase 7.1 — full run-history explorer."""
    conn = trackdb.connect()
    try:
        all_runs = trackdb.list_all_runs(conn)
    finally:
        conn.close()

    # Server-side filtering (scheme) and client-side (target/status) — see P2 critique
    runs = all_runs
    if target:
        runs = [r for r in runs if r.get("target") == target]
    if status:
        runs = [r for r in runs if r.get("status") == status]
    if scheme:
        # Scheme stored in config_json — extracted on the Python side
        runs = [r for r in runs if _extract_scheme(r) == scheme]

    # Count runs per target for the dropdown filter
    target_counts = {}
    for r in all_runs:
        tgt = r.get("target")
        if tgt:
            target_counts[tgt] = target_counts.get(tgt, 0) + 1
    targets = [{"target": k, "n_runs": v} for k, v in sorted(target_counts.items())]

    return templates.TemplateResponse(
        request, "runs.html",
        {"runs": runs, "targets": targets, "filter_target": target or "",
         "filter_status": status or "", "filter_scheme": scheme or "",
         **_i18n_context(request)},
    )


def _extract_scheme(run: dict) -> str:
    """Extract the validation scheme from the run (stored in config_json)."""
    import json
    try:
        if run.get("config_json"):
            cfg = json.loads(run["config_json"])
            return cfg.get("validation", {}).get("scheme", "walkforward")
    except (json.JSONDecodeError, TypeError):
        pass
    return "walkforward"


@app.get("/universe")
def universe_page(request: Request):
    """Target universe cross-referenced with run history.

    The DB/config join itself (`DEFAULT_TARGET_GROUPS` x run history) is
    delegated to `tracking/history.py::universe_overview` -- previously
    duplicated here with a bug (iterating `(symbol, label)` tuples as if
    they were plain symbol strings, so `target in symbol_info` was always
    False and every group came back empty). Only the i18n group-name
    translation stays here, since it needs `request`, which the read-only
    history layer doesn't have access to."""
    conn = trackdb.connect()
    try:
        raw_groups = trackhistory.universe_overview(conn)
    finally:
        conn.close()

    t = i18n.translator(i18n.get_lang(request))
    groups = [
        {"group": t(i18n.TARGET_GROUP_LABEL_KEYS.get(g["group"], f"group_{g['group']}")),
         "symbols": g["symbols"]}
        for g in raw_groups if g["symbols"]
    ]

    return templates.TemplateResponse(
        request, "universe.html",
        {"groups": groups, **_i18n_context(request)},
    )


def _asset_group_view(group_key: str) -> list[dict]:
    """Per-asset panel skeleton for `/commodities`/`/macro`: symbol/label
    from `DEFAULT_TARGET_GROUPS` (same source `/universe` reads) plus a
    DOM-safe `slug` for the panel's `id` -- reuses `forms.slug_target`
    rather than a second slugifier, since it already turns e.g. `GC=F` or
    `^VIX`-shaped symbols into a valid id for exactly this kind of use
    (run output dirs today, a DOM id here)."""
    return [
        {"symbol": sym, "label": label, "slug": forms.slug_target(sym)}
        for sym, label in D.DEFAULT_TARGET_GROUPS[group_key]
    ]


@app.get("/commodities")
def commodities_page(request: Request):
    """feature/ticker-stats-panel: one display-stats panel per commodity
    future in the reduced universe (returns/z-score/MA/vol -- never the ML
    pipeline). The page itself renders only panel skeletons (no
    yfinance/FRED fetch here, see `asset_stats.py` module docstring) --
    `static/asset_stats.js` fills each one via `/api/asset-stats/{symbol}`
    once loaded, same client-fetch split as the market preview
    (`market.js` / `/api/preview/{symbol}`)."""
    return templates.TemplateResponse(
        request, "commodities.html",
        {"assets": _asset_group_view(COMMODITIES_TARGET_GROUP), **_i18n_context(request)},
    )


@app.get("/macro")
def macro_page(request: Request):
    """feature/ticker-stats-panel: same panel, for the Macro (FRED) group."""
    return templates.TemplateResponse(
        request, "macro.html",
        {"assets": _asset_group_view(D.FRED_TARGET_GROUP), **_i18n_context(request)},
    )


@app.get("/api/asset-stats/{symbol}")
def asset_stats_api(symbol: str, period: str = "5y"):
    """feature/ticker-stats-panel: fetched client-side, once per panel, by
    `asset_stats.js`. Same data-access path as `/api/preview/{symbol}`
    (`forms.TARGET_SOURCE_BY_SYMBOL` -> `market_data.price_history`) --
    `asset_stats.compute_stats` only adds the display-stats layer on top,
    it does not fetch anything itself. `period="5y"`: comfortably covers
    every window this module computes (longest is the 252-bar view /
    200-bar MA) without requesting `"max"` for every asset on every page
    load."""
    source = forms.TARGET_SOURCE_BY_SYMBOL.get(symbol)
    if source is None:
        raise HTTPException(status_code=404, detail="Symbole inconnu")
    series = market_data.price_history(symbol, source, period)
    return asset_stats.compute_stats(series)


@app.get("/targets/{ticker}")
def target_page(request: Request, ticker: str):
    """Phase 7.3 — aggregated view of all runs for a target."""
    if ticker not in forms.TARGET_SOURCE_BY_SYMBOL:
        raise HTTPException(status_code=404, detail="Cible inconnue")

    conn = trackdb.connect()
    try:
        detail = trackhistory.target_detail(conn, ticker)
    finally:
        conn.close()

    # feature/shap-waterfall (Phase 7): horizons offered in the on-demand
    # SHAP selector -- any horizon with at least one DONE run MAY have an
    # exported model (`explain.explain_last_prediction` checks for real,
    # returns `ok: False` otherwise; this list is only there to avoid
    # offering an horizon that obviously never finished a run).
    done_horizons = sorted({r["horizon"] for r in (detail["runs"] if detail else []) if r["status"] == "done"})

    return templates.TemplateResponse(
        request, "target.html",
        {"target": ticker, "detail": detail, "shap_horizons": done_horizons, **_i18n_context(request)},
    )


@app.get("/api/targets/{ticker}/shap-waterfall")
def target_shap_waterfall(ticker: str, horizon: int):
    """feature/shap-waterfall (Phase 7): on-demand SHAP explanation of the
    most recent RECORDED prediction for (ticker, horizon) -- see
    `patrick.explain.explain_last_prediction` for the feasibility rationale
    (cost measured on a real exported model, why the selection-time SHAP
    cache is not reused) and `docs/PHASE7_SHAP_FEASIBILITY.md` for the
    numbers. Computed synchronously on request (button-triggered from
    `shap_waterfall.js`), never on page load."""
    if ticker not in forms.TARGET_SOURCE_BY_SYMBOL:
        raise HTTPException(status_code=404, detail="Cible inconnue")
    try:
        result = explain.explain_last_prediction(ticker, horizon)
    except Exception as exc:  # never let an explanation failure break the page
        return JSONResponse({"ok": False, "message": f"Erreur de calcul SHAP : {exc}"})
    if result is None:
        return JSONResponse({"ok": False, "message": "Aucune prédiction exploitable pour cet horizon."})
    svg = shap_chart.render_waterfall_svg(result["base_value"], result["contributions"], result["final_value"])
    return JSONResponse({
        "ok": True, "svg": svg, "ts": result["ts"], "split": result["split"],
        "y_pred": result["y_pred"], "y_pred_label": result["y_pred_label"],
        "y_proba": result["y_proba"], "n_features_total": result["n_features_total"],
    })


@app.get("/runs/{run_id}/detail")
def run_detail_page(request: Request, run_id: str):
    """Phase 7.2 — read-only detail page for a run (CLI or web)."""
    conn = trackdb.connect()
    try:
        detail = trackhistory.run_detail(conn, run_id)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return templates.TemplateResponse(
        request, "run_detail.html",
        {"detail": detail, **_i18n_context(request)},
    )


@app.get("/simulate")
def simulate_page(request: Request, run_id: str | None = None):
    """Phase 4 -- dedicated view (not the dashboard's 2x2 grid: variable-
    height content). The simulator never re-runs a model: it only reads
    already-`done` runs and their persisted `prediction` rows."""
    conn = trackdb.connect()
    try:
        runs = trackdb.list_done_runs(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "simulate.html",
        {"runs": runs, "initial_run_id": run_id, **_i18n_context(request)},
    )


@app.get("/phase9")
def phase9_overview(request: Request):
    """P8/B6: trimmed to what is genuinely unique here after the synthesis
    dashboard (`/`) absorbed signal quality -- the manual decision journal
    and named snapshots (`tracking/db.py`, real persistence) have no other
    surface in the product. `signal_quality`/`regime_summary` (hardcoded
    literals, `phase9.determine_signal_quality_status`/`regime_summary`)
    removed rather than kept duplicated -- same real data now lives on `/`,
    the fake numbers here served no one. See DASHBOARD_B1-B2.md."""
    conn = trackdb.connect()
    try:
        entries = trackdb.list_phase9_journal_entries(conn, limit=20)
        snapshots = trackdb.list_phase9_snapshots(conn, limit=10)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "phase9_overview.html",
        {"entries": entries, "snapshots": snapshots, **_i18n_context(request)},
    )


@app.get("/api/phase9/summary")
def api_phase9_summary():
    """No caller anywhere in the frontend (checked: absent from every
    `static/*.js`) -- kept only as a thin journal/snapshots mirror of the
    page above, `signal_quality`/`regime_summary` (same fabricated literals
    as the page used to carry) dropped rather than kept for a route nothing
    reads."""
    conn = trackdb.connect()
    try:
        entries = trackdb.list_phase9_journal_entries(conn, limit=20)
        snapshots = trackdb.list_phase9_snapshots(conn, limit=10)
    finally:
        conn.close()
    return {
        "entries": entries,
        "snapshots": snapshots,
    }


@app.get("/api/phase9/journal")
def api_phase9_journal(limit: int = 20):
    conn = trackdb.connect()
    try:
        return {"entries": trackdb.list_phase9_journal_entries(conn, limit=limit)}
    finally:
        conn.close()


@app.post("/api/phase9/journal")
async def api_phase9_record_journal(request: Request):
    body = await request.json()
    action = str(body.get("action") or "manual_review")
    actor = str(body.get("actor") or "operator")
    reason = str(body.get("reason") or "phase9 review")
    before = body.get("before")
    after = body.get("after")
    conn = trackdb.connect()
    try:
        entry = trackdb.save_phase9_journal_entry(conn, action, actor, before, after, reason)
    finally:
        conn.close()
    return {"entry": entry}


@app.post("/api/phase9/snapshot")
async def api_phase9_snapshot(request: Request):
    body = await request.json()
    name = str(body.get("name") or "snapshot")
    state = body.get("state") or {}
    conn = trackdb.connect()
    try:
        snapshot_id = trackdb.save_phase9_snapshot(conn, name, state)
    finally:
        conn.close()
    return {"snapshot_id": snapshot_id, "snapshot_name": name}


@app.get("/api/runs/{run_id}/trials")
def api_list_trials(run_id: str):
    conn = trackdb.connect()
    try:
        return {"trials": trackdb.list_trials_for_run(conn, run_id)}
    finally:
        conn.close()


_SIM_PARAM_FIELDS = set(sim_engine.SimParams.__dataclass_fields__)


@app.post("/api/simulate")
async def api_simulate(request: Request):
    """Runs a simulation (Phase 4) and ALWAYS logs it to the database (Phase
    4.5, anti-overfitting guard), success or failure -- the number of
    configurations tried must never be hidden."""
    body = await request.json()
    try:
        trial_id = int(body["trial_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status_code=400, detail="trial_id manquant ou invalide")

    raw_params = {k: v for k, v in (body.get("params") or {}).items() if k in _SIM_PARAM_FIELDS}
    try:
        params = sim_engine.SimParams(**raw_params)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = sim_engine.simulate(trial_id, params)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Données de la cible introuvables : {exc}")

    conn = trackdb.connect()
    try:
        simulation_id = sim_engine.save_simulation(conn, trial_id, params, result)
    finally:
        conn.close()
    result["simulation_id"] = simulation_id
    return result


@app.get("/api/simulate/{simulation_id}")
def api_get_simulation(simulation_id: str):
    import json as _json
    conn = trackdb.connect()
    try:
        row = conn.execute(
            "SELECT trial_id, params_json, metrics_json, error FROM simulation WHERE simulation_id = ?",
            (simulation_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Simulation introuvable")
    trial_id, params_json, metrics_json, error = row
    return {
        "trial_id": trial_id,
        "params": _json.loads(params_json),
        "result": _json.loads(metrics_json) if metrics_json else None,
        "error": error,
    }


def main() -> None:
    import uvicorn

    uvicorn.run("patrick.webapp.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
