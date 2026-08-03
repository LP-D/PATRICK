"""Interface web de `patrick` : construit une `RunConfig` par formulaire
(remplace l'édition manuelle du YAML), lance `run_pipeline` en arrière-plan
et affiche progression + leaderboard dans le navigateur.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from patrick.config.schema import RunConfig
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


@app.post("/runs")
async def create_run(request: Request):
    """Répond en JSON (consommé par `app.js` en AJAX, sans rechargement de
    page) : un run est démarré immédiatement s'il n'y en a pas d'actif, sinon
    mis en file d'attente — jamais rejeté, `start_run` ne lève plus d'erreur
    dans ce cas (cf. `run_manager.py`)."""
    form = await request.form()
    config_dict, errors = forms.build_config_dict(form)

    if not errors:
        try:
            config = RunConfig.model_validate(config_dict)
        except ValidationError as exc:
            errors = [f"{'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors()]
            config = None
    else:
        config = None

    if errors:
        return JSONResponse({"errors": errors}, status_code=400)

    job_view = run_manager.start_run(config)
    return JSONResponse({
        "run_id": job_view["id"],
        "status": job_view["status"],
        "queue_position": job_view["queue_position"],
    })


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


@app.get("/runs")
def runs_explorer(request: Request, target: str | None = None, status: str | None = None,
                   scheme: str | None = None):
    """Phase 7.1 (P7.1) -- explorateur de l'historique complet de runs (table
    `run`), lecture seule -- distinct de la file d'attente en mémoire de
    `run_manager` (runs terminés/anciens y compris, tout redémarrage
    confondu)."""
    conn = trackdb.connect()
    try:
        runs = trackhistory.list_runs(conn, target=target, status=status, scheme=scheme)
        targets = trackhistory.list_distinct_targets(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "runs.html",
        {"runs": runs, "targets": targets, "filter_target": target or "",
         "filter_status": status or "", "filter_scheme": scheme or "",
         **_i18n_context(request)},
    )


@app.get("/targets/{ticker}")
def target_page(request: Request, ticker: str):
    """Phase 7.3 (P7.3) -- vue agrégée de tout l'historique de runs d'UNE
    cible (tous horizons/schémas confondus), y compris la correction FDR
    resituant sa meilleure p-value DM parmi toutes les cibles testées."""
    conn = trackdb.connect()
    try:
        detail = trackhistory.target_detail(conn, ticker)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "target.html", {"target": ticker, "detail": detail, **_i18n_context(request)},
    )


@app.get("/universe")
def universe_page(request: Request):
    """Phase 7.5 (P7.5) -- univers de cibles configurables
    (`config/defaults.py::DEFAULT_TARGET_GROUPS`, déjà utilisé par le
    formulaire de lancement), croisé avec l'historique réel de runs -- aucune
    donnée nouvelle, juste la jointure des deux."""
    conn = trackdb.connect()
    try:
        groups = trackhistory.universe_overview(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "universe.html", {"groups": groups, **_i18n_context(request)},
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
def runs_explorer(request: Request):
    """Explorateur : tous les runs exécutés."""
    conn = trackdb.connect()
    try:
        runs = trackdb.list_all_runs(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "runs.html",
        {"runs": runs, **_i18n_context(request)},
    )


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
    """Agrégation sur une cible."""
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
        "best_dm_result": None,
    }

    return templates.TemplateResponse(
        request, "target.html",
        {"target": ticker, "detail": detail, "pbo_blocks": [], "target_runs": target_runs,
         **_i18n_context(request)},
    )


@app.get("/runs/{run_id}/detail")
def run_detail_page(request: Request, run_id: str):
    """Détails d'un run."""
    run = _get_run_or_404(run_id)
    return templates.TemplateResponse(
        request, "run_detail.html",
        {"run": run, "run_id": run_id, **_i18n_context(request)},
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
