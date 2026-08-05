"""Interface web de `patrick` : construit une `RunConfig` par formulaire
(remplace l'édition manuelle du YAML), lance `run_pipeline` en arrière-plan
et affiche progression + leaderboard dans le navigateur.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from patrick.config.schema import RunConfig
from patrick.phase9 import determine_signal_quality_status, regime_summary
from patrick.simulate import engine as sim_engine
from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.webapp import alerts, forms, i18n, market_data, run_manager
from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="PATRICK")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

FORM_OPTIONS = {
    "all_families": forms.ALL_FEATURE_FAMILIES,
    "all_samplers": forms.ALL_SAMPLERS,
    "all_algos": forms.ALL_ALGOS,
    "all_vol_models": forms.ALL_VOL_MODELS,
    "vol_model_labels": forms.VOL_MODEL_LABELS,
    "selection_methods": ["shap", "rfe", "lasso"],
    "target_groups": forms.TARGET_GROUPS,
}


@app.on_event("startup")
def _on_startup() -> None:
    alerts.start_background_refresh()


def _station_verdict() -> dict | None:
    """Le verdict de la station, rendu côté SERVEUR dans le bandeau de chaque
    page. Pas d'appel AJAX comme la bande d'enregistrement : c'est une donnée
    de chrome, elle doit être là au premier rendu plutôt que d'apparaître après
    coup. Une seule requête agrégée, lecture seule, échec silencieux — le
    bandeau doit s'afficher même sans base (première installation)."""
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
        # Nom lisible par terme de glossaire ; les termes qui portent déjà leur
        # nom (`technical`, `XGBoost`…) n'y figurent pas et le gabarit retombe
        # sur le terme lui-même.
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
    """Derniers runs persistés, pour la colonne « avancement » de l'accueil
    AU REPOS. Sans eux, cette colonne est vide sur toute la hauteur du premier
    viewport tant qu'aucun run ne tourne -- alors que la base a précisément de
    quoi la remplir. Lecture seule, échec silencieux : l'accueil doit
    s'afficher même si la base n'existe pas encore (première installation)."""
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


@app.get("/")
def index(request: Request, load: str | None = None):
    if load:
        try:
            cfg = forms.load_example_config(load)
        except FileNotFoundError:
            return _render_index(request, forms.to_view(forms.default_config_dict()),
                                  [f"Config d'exemple introuvable : {load}"], status_code=404)
    else:
        cfg = forms.default_config_dict()
    return _render_index(request, forms.to_view(cfg), [])


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


@app.get("/api/activity")
def activity(limit: int = 120):
    """Alimente la bande d'enregistrement du bandeau (`observatory.js`) — une
    marque par run, posée à son heure de départ, hauteur portée par le nombre
    d'essais et couleur par l'état.

    Lecture seule et échec silencieux, comme `_recent_runs` : la bande est un
    élément de gabarit partagé par TOUTES les pages, une base absente
    (première installation) ne doit pas rendre l'interface inutilisable. Le
    front distingue « pas encore de run » (`runs: []`) de « base illisible »
    (`available: false`) et l'écrit dans la légende — la bande ne doit jamais
    laisser croire à une station muette quand c'est la lecture qui a échoué."""
    try:
        conn = trackdb.connect()
    except Exception:
        return {"available": False, "runs": []}
    try:
        rows = trackhistory.list_runs(conn, limit=limit)
    except Exception:
        return {"available": False, "runs": []}
    finally:
        conn.close()
    return {
        "available": True,
        "runs": [
            {
                "run_id": r["run_id"],
                "name": r["name"] or r["run_id"],
                "target": r["target"],
                "status": r["status"],
                "started_at": r["started_at"],
                "n_trials": r["n_trials"],
            }
            for r in rows
        ],
    }


@app.get("/api/next-run-names")
def next_run_names(target: list[str] = Query(default=[])):
    """Aperçu (lecture seule) du nom qui sera attribué à chaque cible si le
    formulaire est soumis maintenant — appelé par `app.js` quand la
    sélection de cibles change. Ne réserve rien : le nombre réel peut
    différer si d'autres runs pour la même cible s'intercalent avant la
    soumission (cf. spec batch-run-launch, limite connue)."""
    return {t: run_manager.next_run_name(t) for t in dict.fromkeys(target)}


@app.post("/runs")
async def create_run(request: Request):
    """Répond en JSON (consommé par `app.js` en AJAX, sans rechargement de
    page) : un run est démarré immédiatement s'il n'y en a pas d'actif, sinon
    mis en file d'attente — jamais rejeté, `start_run` ne lève plus d'erreur
    dans ce cas (cf. `run_manager.py`).

    Une soumission peut cibler plusieurs symboles à la fois (`<select
    multiple name="target_symbols">`) : un job est enfilé par cible, avec un
    nom/dossier de sortie distincts (`run_manager.next_run_name`) — la queue
    FIFO existante les enchaîne, aucun nouvel orchestrateur. Si une seule
    config est invalide parmi les cibles soumises, rien n'est enqueue."""
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
        # Un dossier de sortie saisi à la main s'applique tel quel à une
        # cible unique ; pour un batch, il est partagé par le formulaire --
        # sans ce garde-fou, N cibles avec le même `output_dir` explicite
        # écraseraient les artefacts les unes des autres.
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
    """Relance un run passé à l'identique, sauf nom/dossier de sortie
    (nouveau numéro, cf. `run_manager.next_run_name`) -- une nouvelle
    tentative doit être distinguable dans l'historique, pas confondue avec
    l'originale. Fonctionne pour un run soumis via le web (config retrouvée
    dans la table `job`) et pour un run lancé en CLI (repli sur
    `run.config_json`, absent de `job`)."""
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
    # Le dossier de sortie de la relance reprend le RACINE (parent) du
    # dossier de la config d'origine -- un batch soumis avec un `output_dir`
    # explicite, ou un run lancé en CLI avec sa propre racine, ne doit pas se
    # faire écraser au profit d'un `runs/` codé en dur relatif au cwd du
    # process web. Seul le dernier composant (le nom du run) change.
    original_dir = Path(config.output.dir)
    cfg_dict["output"]["dir"] = (
        str(original_dir.parent / new_name) if original_dir.parent != Path(".") else f"runs/{new_name}"
    )
    new_config = RunConfig.model_validate(cfg_dict)

    job_view = run_manager.start_run(new_config)
    return RedirectResponse(f"/runs/{job_view['id']}", status_code=303)


@app.get("/api/run-state")
def run_state():
    """État agrégé léger (run actif + file d'attente) — poll périodique côté
    JS pour suivre l'avancement de la file, distinct du polling détaillé
    `/runs/{run_id}/status` (progression/logs d'un run précis)."""
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
    """Même tableau de bord qu'`index()` (un seul gabarit, `index.html`) —
    seul `initial_run_id` change, forcé sur ce run précis plutôt que sur le
    run actif courant. Permet de rouvrir/partager le lien d'un run passé ou en
    cours sans dupliquer le template. Le formulaire settings est prérempli
    avec la config réelle de ce run (pas les défauts).

    Phase 7.2 (P7.2) -- `run_manager.get_run` ne connaît que les runs lancés
    depuis l'interface web (table `job`) : un `patrick run`/`patrick resume`
    CLI n'a jamais de ligne `job` associée, et ne s'y trouve donc jamais. Si
    ce run_id n'a pas de job mais existe dans `run` (table remplie par tout
    run, CLI ou web), on bascule sur la page de détail lecture seule
    (`run_detail.html`) plutôt que de renvoyer une 404 -- l'historique ne
    doit jamais devenir inaccessible par ce lien (cf. PRODUCT.md, "rien
    n'est silencieusement perdu")."""
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
    """Phase 7.1 — explorateur de l'historique complet de runs."""
    conn = trackdb.connect()
    try:
        all_runs = trackdb.list_all_runs(conn)
    finally:
        conn.close()

    # Filtrage côté serveur (scheme) et client (target/status) — cf. critique P2
    runs = all_runs
    if target:
        runs = [r for r in runs if r.get("target") == target]
    if status:
        runs = [r for r in runs if r.get("status") == status]
    if scheme:
        # Schéma stocké dans config_json — extraction côté Python
        runs = [r for r in runs if _extract_scheme(r) == scheme]

    # Compter les runs par cible pour le filtre dropdown
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
    """Extraire le schéma de validation depuis le run (stocké en config_json)."""
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
    """Univers de cibles croisé avec historique de runs."""
    from patrick.config import defaults
    symbol_info = {s: (label, src) for s, label, src in defaults.DEFAULT_TARGET_CHOICES}
    conn = trackdb.connect()
    try:
        symbol_stats = {s: {"n_runs": 0, "n_done": 0, "last_started_at": None}
                       for targets in defaults.DEFAULT_TARGET_GROUPS.values()
                       for s in targets}
        for run in trackdb.list_all_runs(conn):
            if run["target"] in symbol_stats:
                symbol_stats[run["target"]]["n_runs"] += 1
                if run["status"] == "done":
                    symbol_stats[run["target"]]["n_done"] += 1
                if not symbol_stats[run["target"]]["last_started_at"] or run["started_at"] > symbol_stats[run["target"]]["last_started_at"]:
                    symbol_stats[run["target"]]["last_started_at"] = run["started_at"]
    finally:
        conn.close()

    t = i18n.translator(i18n.get_lang(request))
    groups = []
    for group_name, group_targets in defaults.DEFAULT_TARGET_GROUPS.items():
        symbols = []
        for target in group_targets:
            if target in symbol_info:
                label, source = symbol_info[target]
                stats = symbol_stats.get(target, {"n_runs": 0, "n_done": 0, "last_started_at": None})
                symbols.append({"symbol": target, "label": label, "source": source,
                               "n_runs": stats["n_runs"], "n_done": stats["n_done"],
                               "last_started_at": stats["last_started_at"]})
        if symbols:
            translated_group = t(i18n.TARGET_GROUP_LABEL_KEYS.get(group_name, f"group_{group_name}"))
            groups.append({"group": translated_group, "symbols": symbols})

    return templates.TemplateResponse(
        request, "universe.html",
        {"groups": groups, **_i18n_context(request)},
    )


@app.get("/targets/{ticker}")
def target_page(request: Request, ticker: str):
    """Phase 7.3 — vue agrégée de tous les runs d'une cible."""
    if ticker not in forms.TARGET_SOURCE_BY_SYMBOL:
        raise HTTPException(status_code=404, detail="Cible inconnue")

    conn = trackdb.connect()
    try:
        target_runs = [r for r in trackdb.list_all_runs(conn) if r["target"] == ticker]
    finally:
        conn.close()

    if not target_runs:
        return templates.TemplateResponse(
            request, "target.html",
            {"target": ticker, "detail": None, **_i18n_context(request)},
        )

    detail = {
        "cumulative_trials": sum(r.get("n_trials") or 0 for r in target_runs),
        "n_runs": len(target_runs),
        "runs": target_runs,
        "target_fdr": None,  # Phase 5+ : PBO/FDR requiert stats.py
        "fdr_result": {"n_tested": 0, "alpha": 0.10},
        "pbo_by_horizon": {},  # Phase 5+ : à remplir depuis stats
    }

    return templates.TemplateResponse(
        request, "target.html",
        {"target": ticker, "detail": detail, **_i18n_context(request)},
    )


@app.get("/runs/{run_id}/detail")
def run_detail_page(request: Request, run_id: str):
    """Phase 7.2 — page détail lecture seule d'un run (CLI ou web)."""
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
    """Phase 4 -- vue dédiée (pas la grille 2x2 du dashboard : contenu de
    hauteur variable). Le simulateur ne ré-exécute jamais de modèle : il lit
    seulement les runs déjà `done` et leurs `prediction` persistées."""
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
    """Vue synthétique Phase 9 : signal quality + régime + journal + snapshots."""
    conn = trackdb.connect()
    try:
        entries = trackdb.list_phase9_journal_entries(conn, limit=20)
        snapshots = trackdb.list_phase9_snapshots(conn, limit=10)
    finally:
        conn.close()

    summary = {
        "signal_quality": determine_signal_quality_status({"s1": 0.02, "s2": 0.04, "s3": 0.18, "s4": 0.65}, alpha=0.10),
        "regime_summary": regime_summary(["CALM", "NORMAL", "STRESS", "CRASH", "CALM"]),
    }
    return templates.TemplateResponse(
        request,
        "phase9_overview.html",
        {"summary": summary, "entries": entries, "snapshots": snapshots, **_i18n_context(request)},
    )


@app.get("/api/phase9/summary")
def api_phase9_summary():
    conn = trackdb.connect()
    try:
        entries = trackdb.list_phase9_journal_entries(conn, limit=20)
        snapshots = trackdb.list_phase9_snapshots(conn, limit=10)
    finally:
        conn.close()
    return {
        "signal_quality": determine_signal_quality_status({"s1": 0.02, "s2": 0.04, "s3": 0.18, "s4": 0.65}, alpha=0.10),
        "regime_summary": regime_summary(["CALM", "NORMAL", "STRESS", "CRASH", "CALM"]),
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
    """Lance une simulation (Phase 4) et la journalise TOUJOURS en base (Phase
    4.5, garde-fou anti-surapprentissage), succès ou échec -- le nombre de
    configurations essayées ne doit jamais être caché."""
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
