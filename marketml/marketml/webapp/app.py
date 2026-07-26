"""Interface web de `marketml` : construit une `RunConfig` par formulaire
(remplace l'édition manuelle du YAML), lance `run_pipeline` en arrière-plan
et affiche progression + leaderboard dans le navigateur.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from marketml.config.schema import RunConfig
from marketml.webapp import forms, run_manager

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="marketml")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

FORM_OPTIONS = {
    "all_families": forms.ALL_FEATURE_FAMILIES,
    "all_samplers": forms.ALL_SAMPLERS,
    "all_algos": forms.ALL_ALGOS,
    "selection_methods": ["shap", "rfe", "lasso"],
    "target_sources": ["yfinance", "fred"],
}


def _render_index(request: Request, view: dict, errors: list[str], status_code: int = 200):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "view": view,
            "errors": errors,
            "examples": forms.list_example_configs(),
            "active_run": run_manager.active_run(),
            **FORM_OPTIONS,
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


@app.post("/runs")
async def create_run(request: Request):
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
        return _render_index(request, forms.to_view(config_dict), errors, status_code=400)

    try:
        state = run_manager.start_run(config)
    except RuntimeError as exc:
        return _render_index(request, forms.to_view(config_dict), [str(exc)], status_code=409)

    return RedirectResponse(f"/runs/{state.id}", status_code=303)


def _get_run_or_404(run_id: str):
    state = run_manager.get_run(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run introuvable (redémarrage du serveur ?)")
    return state


@app.get("/runs/{run_id}")
def run_page(request: Request, run_id: str):
    state = _get_run_or_404(run_id)
    return templates.TemplateResponse(
        request, "run.html", {"run_id": run_id, "config_name": state.config.name},
    )


@app.get("/runs/{run_id}/status")
def run_status(run_id: str):
    return _get_run_or_404(run_id).snapshot()


@app.get("/runs/{run_id}/results")
def run_results(run_id: str):
    state = _get_run_or_404(run_id)
    if state.status != "done":
        raise HTTPException(status_code=409, detail=f"Run pas encore terminé (status={state.status})")
    return state.result


ARTIFACT_LABELS = {
    "leaderboard_csv": "Leaderboard (CSV)",
    "leaderboard_xlsx": "Leaderboard (Excel)",
    "tuned_csv": "Configs affinées (CSV)",
    "best_model": "Meilleur modèle (joblib)",
    "best_model_meta": "Métadonnées du modèle (JSON)",
}


@app.get("/runs/{run_id}/download/{artifact}")
def download_artifact(run_id: str, artifact: str):
    state = _get_run_or_404(run_id)
    if state.status != "done" or not state.result:
        raise HTTPException(status_code=409, detail="Run pas encore terminé")
    path = state.result.get("artifacts", {}).get(artifact)
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Artefact introuvable")
    return FileResponse(path, filename=os.path.basename(path))


def main() -> None:
    import uvicorn

    uvicorn.run("marketml.webapp.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
