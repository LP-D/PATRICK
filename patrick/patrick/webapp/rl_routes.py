"""Page /rl et API /api/rl/* : cadrage, lancement et lecture des runs de reinforcement learning.

Un run RL est un job de la file commune (`job.config_json` avec `"kind": "rl"`, résultat dans `job.result_json`) : l'avancement, la pause,
l'arrêt et le téléchargement des fichiers passent par les routes génériques `/runs/{id}/status`, `/runs/{id}/results`,
`/runs/{id}/download/{artefact}` et `/api/jobs/{id}/...`. Ce module ajoute la page, le lancement (un job par cible) et la liste des runs RL.
"""
from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import ValidationError

from patrick.config import defaults as D
from patrick.config import rl_profiles
from patrick.rl import agents
from patrick.rl.config import RLRunConfig
from patrick.tracking import db as trackdb
from patrick.webapp import forms, forms_rl, run_manager

RL_JOB_FILTER = '%"kind":"rl"%'
LIST_LIMIT = 30


def _deps_error() -> str | None:
    if agents.rl_available():
        return None
    try:
        agents.require_rl()
    except agents.RLUnavailableError as exc:
        return str(exc)
    return None


def field_groups() -> list[dict]:
    """Champs `rl_<réglage>` du formulaire, par bloc, avec leur type et leurs bornes (le gabarit n'en code aucun en dur)."""
    def spec(key: str) -> dict:
        default = D.DEFAULT_RL[key]
        if isinstance(default, bool):
            return {"key": key, "kind": "bool"}
        choices = {"action_space": D.RL_ACTION_SPACES, "reward": D.RL_REWARDS, "feature_selection": D.RL_FEATURE_SELECTION,
                   "algo": D.RL_ALGOS, "activation": D.RL_ACTIVATIONS, "device": ("auto", "cpu", "cuda"), "retrain": D.RL_RETRAIN}
        if key in choices:
            return {"key": key, "kind": "choice", "options": list(choices[key])}
        lo, hi = D.RL_BOUNDS[key]
        is_int = isinstance(default, int)
        return {"key": key, "kind": "int" if is_int else "float", "min": lo, "max": hi, "step": "1" if is_int else "any"}

    groups = (
        ("env", ("n_levels", "max_leverage", "slippage_bps", "risk_aversion", "dsr_eta", "obs_lookback", "include_position", "episode_length",
                 "random_start")),
        ("features", ("max_features", "feature_selection")),
        ("policy", ("policy_layers", "policy_units", "activation")),
        ("learning", ("learning_rate", "gamma", "n_steps", "batch_size", "n_epochs", "ent_coef", "clip_range", "gae_lambda", "buffer_size",
                      "learning_starts", "train_freq", "target_update_interval", "exploration_fraction", "tau")),
        ("validation", ("min_train_frac", "retrain", "rolling_bars", "n_seeds", "bootstrap_samples")),
        ("compute", ("device", "threads")),
    )
    return [{"key": name, "fields": [spec(k) for k in keys]} for name, keys in groups]


# Terme du glossaire associé à chaque réglage (bouton « ? » à côté du champ) ; absent = pas de définition dédiée.
FIELD_TERMS: dict[str, str] = {
    "n_levels": "rl_action_space", "max_leverage": "rl_leverage", "slippage_bps": "rl_cost", "risk_aversion": "rl_risk_aversion",
    "dsr_eta": "rl_dsr_eta", "obs_lookback": "rl_obs_lookback", "episode_length": "rl_episode", "random_start": "rl_episode",
    "max_features": "rl_features", "feature_selection": "rl_features", "policy_layers": "rl_policy", "policy_units": "rl_policy",
    "learning_rate": "rl_learning_rate", "gamma": "rl_gamma", "n_steps": "rl_n_steps", "ent_coef": "rl_ent_coef",
    "clip_range": "rl_clip_range", "gae_lambda": "rl_gae_lambda", "buffer_size": "rl_buffer", "learning_starts": "rl_buffer",
    "train_freq": "rl_buffer", "target_update_interval": "rl_exploration", "exploration_fraction": "rl_exploration", "tau": "rl_exploration",
    "min_train_frac": "rl_walkforward", "retrain": "rl_retrain", "rolling_bars": "rl_retrain", "n_seeds": "rl_seeds",
    "bootstrap_samples": "rl_bootstrap", "turnover": "rl_turnover",
}

# Réglages qui n'ont de sens que pour certains algorithmes : le formulaire masque les autres (`data-algos`).
ALGO_FIELDS: dict[str, tuple[str, ...]] = {
    "n_steps": ("PPO", "A2C"), "n_epochs": ("PPO",), "ent_coef": ("PPO", "A2C"), "clip_range": ("PPO",), "gae_lambda": ("PPO", "A2C"),
    "buffer_size": ("DQN", "SAC"), "learning_starts": ("DQN", "SAC"), "train_freq": ("DQN", "SAC"), "target_update_interval": ("DQN",),
    "exploration_fraction": ("DQN",), "tau": ("SAC",), "batch_size": ("PPO", "DQN", "SAC"),
}


def _summary(job: dict) -> dict:
    """Une ligne de la liste des runs RL : nom, cible, algorithme, état et, si terminé, les chiffres clés."""
    try:
        config = json.loads(job["config_json"])
    except (TypeError, ValueError):
        config = {}
    row = {"run_id": job["job_id"], "name": config.get("name"), "target": (config.get("objective") or {}).get("target_symbol"),
           "algo": (config.get("rl") or {}).get("algo"), "status": job["status"], "created_at": job.get("created_at"),
           "finished_at": job.get("finished_at")}
    if job["status"] == "done" and job.get("result_json"):
        try:
            result = json.loads(job["result_json"])
            row.update({"sharpe": (result.get("strategy") or {}).get("sharpe"),
                        "sharpe_buy_hold": ((result.get("baselines") or {}).get("buy_hold") or {}).get("sharpe"),
                        "total_return": (result.get("strategy") or {}).get("total_return"),
                        "max_drawdown": (result.get("strategy") or {}).get("max_drawdown")})
        except ValueError:
            pass
    return row


def list_rl_jobs(limit: int = LIST_LIMIT) -> list[dict]:
    conn = trackdb.connect(trackdb.default_db_path())
    try:
        rows = conn.execute("SELECT * FROM job WHERE config_json LIKE ? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                            (RL_JOB_FILTER, limit)).fetchall()
        cols = [d[0] for d in conn.execute("SELECT * FROM job LIMIT 0").description]
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    return [_summary(dict(zip(cols, r, strict=True))) for r in rows]


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n de l'application."""

    def render(request: Request, view: dict, errors: list[str] | None = None, applied: dict | None = None, run_id: str | None = None):
        ctx = context(request)
        return templates.TemplateResponse(request, "rl.html", {
            **ctx, "view": view, "errors": errors or [], "applied": applied, "initial_run_id": run_id,
            "target_groups": forms_rl.rl_target_groups(), "rl_ready": agents.rl_available(), "deps_error": _deps_error(),
            "field_groups": field_groups(), "algo_fields": ALGO_FIELDS, "rl_terms": FIELD_TERMS, "rl_algos": D.RL_ALGOS, "rl_families": D.RL_FEATURE_FAMILIES,
            "rl_profiles": rl_profiles.gallery(forms_rl.to_view_rl(forms_rl.default_rl_config_dict())),
            "recent_runs": list_rl_jobs(), "bounds": D.RL_BOUNDS,
        })

    @app.get("/rl")
    def rl_page(request: Request, run_id: str | None = None, open: str | None = None, target: str | None = None, profile: str | None = None):
        """`run_id` : reprendre les réglages d'un run (formulaire pré-rempli, rien n'est suivi) ; `open` : idem ET suivre ce run (avancement,
        puis résultats) -- c'est la cible de `/runs/<id>` pour un job RL."""
        cfg = forms_rl.default_rl_config_dict()
        if target and forms.TARGET_SOURCE_BY_SYMBOL.get(target) == "yfinance":
            cfg["objective"]["target_symbol"] = target
        source = open or run_id
        if source:
            raw = run_manager.get_job_config_dict(source)
            if raw is None:
                raise HTTPException(status_code=404, detail="Run introuvable.")
            if raw.get("kind") != "rl":
                algos = (raw.get("models") or {}).get("algos") or []
                family = "dl" if algos and all(a in D.ALL_DL_ALGOS for a in algos) else "ml"
                return RedirectResponse(f"/{family}?run_id={source}", status_code=303)
            cfg = {**raw, "output": {**(raw.get("output") or {}), "dir": ""}}
        view, applied = forms_rl.to_view_rl(cfg), None
        if profile:
            chosen = rl_profiles.get(profile)
            if chosen is None:
                raise HTTPException(status_code=404, detail="Profil d'entraînement inconnu.")
            view = rl_profiles.apply_patch(view, chosen.patch)
            applied = {"kind": "profile", "key": chosen.key}
        return render(request, view, applied=applied, run_id=open)

    @app.post("/api/rl/runs")
    async def rl_create_runs(request: Request):
        form = await request.form()
        targets = list(dict.fromkeys(form.getlist("target_symbols")))
        if not targets:
            return JSONResponse({"errors": ["Sélectionne au moins une cible."]}, status_code=400)
        missing = _deps_error()
        if missing:
            return JSONResponse({"errors": [missing]}, status_code=400)
        errors: list[str] = []
        configs: list[RLRunConfig] = []
        raw_output_dir = (form.get("output_dir") or "").strip()
        if raw_output_dir and not forms.validate_output_dir(raw_output_dir, errors):
            raw_output_dir = ""
        for sym in targets:
            name = run_manager.next_rl_run_name(sym)
            cfg, errs = forms_rl.build_rl_config_dict(form, target_symbol=sym, name=name)
            if errs:
                errors.extend(f"{sym} : {e}" for e in errs)
                continue
            if len(targets) > 1 and raw_output_dir:
                cfg["output"]["dir"] = f"{raw_output_dir}/{name}"
            try:
                configs.append(RLRunConfig.model_validate(cfg))
            except ValidationError as exc:
                errors.extend(f"{sym} : {'.'.join(str(p) for p in e['loc'])} : {e['msg']}" for e in exc.errors())
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)
        runs = []
        for config in configs:
            job = run_manager.start_run(config)
            runs.append({"run_id": job["id"], "status": job["status"], "queue_position": job["queue_position"],
                         "target": config.objective.target_symbol, "name": config.name})
        return JSONResponse({"runs": runs})

    @app.get("/api/rl/runs")
    def rl_runs():
        return {"runs": list_rl_jobs()}

    @app.get("/api/rl/profile-patch/{key}")
    def rl_profile_patch(key: str):
        chosen = rl_profiles.get(key)
        if chosen is None:
            raise HTTPException(status_code=404, detail="Profil d'entraînement inconnu.")
        return {"patch": chosen.patch}
