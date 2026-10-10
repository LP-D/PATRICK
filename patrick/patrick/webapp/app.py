"""`patrick`'s web interface: builds a `RunConfig` from a form (replaces
manual YAML editing), launches `run_pipeline` in the background, and
displays progress + leaderboard in the browser. User-facing strings (HTTP
error details, template labels) stay in French, matching the rest of the
web interface.
"""
from __future__ import annotations

import html
import json
import os
import sqlite3
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from patrick import live_refresh
from patrick import settings as settings_store
from patrick.clock import utc_today
from patrick.config import asset_classes, dl_profiles, training_profiles
from patrick.config import defaults as D
from patrick.config import equity_universe as EQ
from patrick.config.schema import RunConfig
from patrick.data.sources import fundamentals_source
from patrick.features import guida, parametric_parallel
from patrick.models import deep as deep_models
from patrick.pipeline import parallel as scan_parallel
from patrick.tracking import champions as trackchampions
from patrick.tracking import class_overview, data_health, memo, retrain_advisor
from patrick.tracking import db as trackdb
from patrick.tracking import history as trackhistory
from patrick.tracking import home as trackhome
from patrick.tracking import hrp as trackhrp
from patrick.tracking import kpi_summary as trackkpi
from patrick.tracking import portfolio as trackportfolio
from patrick.tracking import usage as trackusage
from patrick.validation import equity_sufficiency, feasibility, suspicion
from patrick.webapp import (
    alerts,
    asset_stats,
    exploration_routes,
    forms,
    fund_routes,
    i18n,
    icons,
    market_data,
    market_regime,
    nav_registry,
    progress_steps,
    rl_routes,
    run_manager,
    security,
    settings_routes,
    shap_chart,
    stats_help,
    wealth_routes,
)
from patrick.webapp.glossary import GLOSSARY, TERM_LABEL_KEYS
from patrick.webapp.glossary_extra import CATEGORIES as GLOSSARY_CATEGORIES
from patrick.webapp.glossary_extra import TERM_CATEGORY

# feature/ticker-stats-panel: the two DEFAULT_TARGET_GROUPS keys backing
# `/commodities` and `/macro` -- named once here rather than re-typed at
# each call site (route + tests both need the exact same key).
COMMODITIES_TARGET_GROUP = "Matières premières (futures)"

# P9 -- French display labels for `run_phase_timing` phases (migration
# 0016/0017), used by the `/targets/{ticker}` drift chart legend. Kept here
# (not `i18n.STRINGS`, English-translated) rather than there: these are
# internal pipeline-phase names, not user-facing copy that needs an English
# rendering -- same "hardcode the French label" convention `target.html`
# already uses for its own section titles/hints.
PHASE_LABELS = {
    "ingestion": "Ingestion",
    "pool_construction": "Construction du pool",
    "scan": "Scan (walk-forward / CPCV)",
    "tuning": "Tuning (Optuna)",
    "stability": "Stabilité de sélection",
    "holdout_diagnostic": "Diagnostic holdout",
    "export": "Export",
}

def _validate_alpha(value: float, name: str) -> float:
    """flexibility-gaps Gap 2/Gap 4: bounds guard shared by every
    significance-level query param on this module (`?dm_alpha=` on
    `/predictions`/`/runs/{run_id}/detail`, `?fdr_alpha=` on
    `/runs/{run_id}/detail`/`/targets/{ticker}`/`/`) -- a p-value/FDR
    threshold only means something as a probability strictly between 0 and
    1."""
    if not (0.0 < value < 1.0):
        raise HTTPException(
            status_code=400,
            detail=f"{name} doit être strictement compris entre 0 et 1 (reçu {value}).",
        )
    return value


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="PATRICK")
# Toutes les routes (présentes et futures) : hôte local obligatoire, pas de requête venue d'un autre site.
app.add_middleware(security.LocalGuardMiddleware)
# Pages de 100 à 700 Ko de HTML : compressées (le navigateur décompresse en quelques ms).
app.add_middleware(GZipMiddleware, minimum_size=2000)


class _RevalidatedStaticFiles(StaticFiles):
    """Fichiers statiques servis avec `Cache-Control: no-cache` : le navigateur les garde mais revalide (réponse 304, quelques ms)
    avant chaque usage. Sans cet en-tête il les réutilise de façon heuristique, et un script modifié par une mise à jour de
    l'application reste ancien dans le navigateur pendant des heures (vu le 2026-10-09 sur `lazy.js`)."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatedStaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# feature/nav-categories-registry: sidebar built from the registry only
# (base_v2.html iterates `nav_sections(request.url.path)`).
templates.env.globals["nav_sections"] = nav_registry.nav_sections
templates.env.globals["utility_links"] = nav_registry.utility_links
# Design system v3: inline Lucide SVG icons (webapp/icons.py).
templates.env.globals["icon"] = icons.icon
templates.env.globals["nav_icon"] = icons.nav_icon
# 504/756-day horizons are descriptive (decision of 2026-09-26): labelled everywhere.
templates.env.globals["descriptive_horizons"] = D.DESCRIPTIVE_HORIZONS


def _horizon_label(h) -> str:
    try:
        return f"{h}j · descriptif" if int(h) in D.DESCRIPTIVE_HORIZONS else f"{h}j"
    except (TypeError, ValueError):
        return f"{h}j"


templates.env.filters["hlabel"] = _horizon_label

FORM_OPTIONS = {
    "all_families": forms.ALL_FEATURE_FAMILIES,
    "all_samplers": forms.ALL_SAMPLERS,
    "all_algos": forms.ALL_ALGOS,
    "all_vol_models": forms.ALL_VOL_MODELS,
    "all_horizons": forms.ALL_HORIZONS,
    "vol_model_labels": forms.VOL_MODEL_LABELS,
    "selection_methods": ["shap", "rfe", "lasso"],
    "target_groups": forms.TARGET_GROUPS,
    # Phase 1 (feature/hyperparams-ui): drives the "Bornes Optuna" section --
    # one [low, high] input pair per (algo, hyperparameter), pre-filled from
    # `view.optuna_bounds` (see `forms.to_view`).
    "optuna_param_specs": D.OPTUNA_PARAM_SPECS,
    # Phase 3 (feature/hyperparams-lookbacks): drives the "Lookbacks
    # technical" section -- one comma-separated `<input>` per
    # `features/technical.py` function, pre-filled from
    # `view.technical_lookbacks` (see `forms.to_view`).
    "technical_lookback_fields": forms.TECHNICAL_LOOKBACK_FIELDS,
    "technical_lookback_bounds": D.TECHNICAL_LOOKBACK_BOUNDS,
}


@app.on_event("startup")
def _on_startup() -> None:
    # Première installation : crée / migre la base AVANT de lancer les fils d'arrière-plan, sinon ils se disputent
    # la création du fichier (« database is locked » dans le journal).
    try:
        trackdb.connect().close()
    except (sqlite3.Error, OSError):
        pass
    # Les trois rafraîchissements d'arrière-plan (cours des « plus fortes variations », signaux live, état du marché)
    # occupent le processeur pendant des dizaines de secondes : lancés tout de suite, ils ralentiraient précisément les
    # premières pages. Ils démarrent après un court délai (PATRICK_BACKGROUND_DELAY_S, 20 s par défaut, 0 = aussitôt).
    try:
        delay = max(0.0, float(os.environ.get("PATRICK_BACKGROUND_DELAY_S", "20")))
    except ValueError:
        delay = 20.0

    def start_background_jobs() -> None:
        alerts.start_background_refresh()
        live_refresh.start_background_refresh()
        market_regime.start_background_refresh()

    if delay == 0:
        start_background_jobs()
    else:
        timer = threading.Timer(delay, start_background_jobs)
        timer.daemon = True
        timer.start()


def _station_verdict(fdr_alpha: float = 0.10) -> dict | None:
    """The station's verdict -- `verdict.alpha`/`verdict.survivors`/etc.,
    read by `synthesis.html` (the only template that still renders it;
    `runs.html`/`universe.html` carry a stale "le bandeau porte le verdict
    global" comment from the pre-`base_v2.html` banner architecture, but
    neither actually reads `verdict.*` today). A single aggregated query,
    read-only, fails silently — must render even with no database (first
    install).

    flexibility-gaps Gap 4: `fdr_alpha` (default 0.10, matching
    `trackhistory.station_verdict`'s own default) -- forwarded by
    `synthesis_page` (`/`, the only caller that has a validated
    request-level value to give it); every other route keeps calling
    `_i18n_context(request)` with no override, so this default is
    unchanged for them."""
    try:
        conn = trackdb.connect()
    except (sqlite3.Error, OSError):
        return None
    try:
        return trackhistory.station_verdict(conn, fdr_alpha=fdr_alpha)
    except sqlite3.Error:
        return None
    finally:
        conn.close()


_METRIC_LABEL_KEYS = (
    "split_test", "split_test_path", "split_holdout", "split_valid", "fold", "folds_word", "mean", "test", "holdout",
    "more", "less",
)
_METRIC_NAMES = ("AUC_ovr_4cls", "F1_dir", "F1_4cls", "Acc_dir", "BalAcc_4cls", "MCC_4cls", "F1_DOWN_FORT", "F1_UP_FORT",
                 "Brier_up", "ECE_up")


def _metric_labels(t) -> dict:
    """Traductions passées aux macros `fold_metrics_table` / `headline_metrics` (un macro importé ne voit pas `t()`)."""
    out = {k: t(f"m_{k}") if k not in ("more", "less") else t(f"rows_{k}") for k in _METRIC_LABEL_KEYS}
    out.update({f"metric_{m}": t(f"metric_{m}") for m in _METRIC_NAMES})
    return out


def _i18n_context(request: Request, fdr_alpha: float = 0.10) -> dict:
    lang = i18n.get_lang(request)
    t = i18n.translator(lang)
    return {
        "m_labels": _metric_labels(t),
        "lang": lang,
        "t": t,
        "glossary": {k: t_entry.get(lang) or t_entry.get(i18n.DEFAULT_LANG) for k, t_entry in GLOSSARY.items()},
        "group_labels": {k: t(v) for k, v in i18n.TARGET_GROUP_LABEL_KEYS.items()},
        # Human-readable name per glossary term; terms that already carry
        # their own name (`technical`, `XGBoost`…) are absent from it and
        # the template falls back to the term itself.
        "glossary_labels": {k: t(v) for k, v in TERM_LABEL_KEYS.items()},
        "i18n_js": i18n.js_strings(lang, request.url.path),
        "verdict": _station_verdict(fdr_alpha),
    }


def _safe_redirect_target(next_path: str) -> str:
    """Security (open redirect) -- `/set-lang?next=` used to 303-redirect to
    `next` with no validation: a link that looks internal
    (`/set-lang/fr?next=...`) could send the visitor anywhere. Accepts only
    an internal relative path: must start with a single `/` (never `//`,
    which browsers resolve as a scheme-relative absolute URL, e.g.
    `next=//evil.com`) and must not embed an explicit `http(s)://` scheme
    anywhere (e.g. `next=https://evil.com`). Anything else falls back to
    `/`, the same default this route already had before `next` existed."""
    if not next_path or not next_path.startswith("/") or next_path.startswith("//"):
        return "/"
    lowered = next_path.lower()
    if "http://" in lowered or "https://" in lowered:
        return "/"
    return next_path


@app.get("/set-lang/{lang}")
def set_lang(lang: str, next: str = "/"):
    lang = lang if lang in i18n.SUPPORTED_LANGS else i18n.DEFAULT_LANG
    resp = RedirectResponse(_safe_redirect_target(next), status_code=303)
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
    except (sqlite3.Error, OSError):
        return []
    try:
        return trackhistory.list_runs(conn, limit=limit)
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _target_groups_with_equity_badges() -> dict:
    """CHANTIER (feature/equity-asset-class): badge d'insuffisance de
    donnees (`validation/equity_sufficiency.py`) injecte directement dans le
    libelle de chaque option du groupe "Actions individuelles" sur
    `/launch` -- seul groupe concerne (seuil ABSOLU de jours de cotation,
    independant du garde-fou horizon existant, `/api/horizon-feasibility`).
    Recompute a CHAQUE requete (pas au chargement du module, contrairement a
    `forms.TARGET_GROUPS`) : `equity_sufficiency.check_data_sufficiency`
    appelle yfinance (via `download_one`, deja mis en cache localement 7
    jours) -- un calcul au chargement du module figerait le badge au
    demarrage du serveur, jamais rafraichi. Les autres groupes ne sont pas
    touches (aucun appel reseau supplementaire pour eux)."""
    groups = dict(forms.TARGET_GROUPS)
    equity_items = []
    for sym, label in groups.get(EQ.EQUITY_TARGET_GROUP, []):
        result = equity_sufficiency.check_data_sufficiency(sym)
        suffix = "" if result.sufficient else f" [données insuffisantes : {result.n_trading_days}j/{result.min_required}j]"
        equity_items.append((sym, f"{label}{suffix}"))
    if EQ.EQUITY_TARGET_GROUP in groups:
        groups[EQ.EQUITY_TARGET_GROUP] = equity_items
    return groups


def _profile_gallery(family: str = "ml") -> list[dict]:
    """Profils d'entraînement fournis (`config/training_profiles.py` pour le ML, `config/dl_profiles.py` pour le DL) avec le nombre de
    réglages qu'ils changent par rapport à la configuration de départ de la famille."""
    base = forms.to_view(forms.default_config_dict(family))
    out = []
    for p in (dl_profiles.PROFILES if family == "dl" else training_profiles.PROFILES):
        patch = p.resolved_patch()
        out.append({"key": p.key, "cost": p.cost, "needs": p.needs,
                    "n_changes": sum(1 for k, v in patch.items() if base.get(k) != v)})
    return out


def _deep_field_groups() -> list[dict]:
    """Champs du réseau pour le formulaire DL, groupés (`dl_<réglage>`) : bornes issues de `config.defaults.DEEP_BOUNDS`."""
    groups = (("arch", ("hidden_size", "n_layers", "dropout", "lookback", "n_heads", "kernel_size")),
              ("train", ("epochs", "batch_size", "learning_rate", "weight_decay", "patience", "val_fraction", "grad_clip", "class_weight")),
              ("compute", ("n_seeds", "device", "threads")))
    out = []
    for name, keys in groups:
        fields = []
        for key in keys:
            if key == "class_weight":
                fields.append({"key": key, "kind": "choice", "options": list(D.DEEP_CLASS_WEIGHTS)})
            elif key == "device":
                fields.append({"key": key, "kind": "choice", "options": list(D.DEEP_DEVICES)})
            else:
                lo, hi = D.DEEP_BOUNDS[key]
                is_int = key in forms._DEEP_INT_KEYS
                fields.append({"key": key, "kind": "int" if is_int else "float", "min": lo, "max": hi, "step": "1" if is_int else "any"})
        out.append({"key": name, "fields": fields})
    return out


LAUNCH_FAMILIES = ("ml", "dl")


def _render_launch(request: Request, view: dict, errors: list[str], status_code: int = 200,
                    initial_run_id: str | None = None, duplicated_run_id: str | None = None, applied: dict | None = None,
                    family: str = "ml"):
    """Poste de lancement d'une famille de modèles (`ml.html`, `dl.html`) : même gabarit de base, même `app.js`."""
    active = run_manager.active_run()
    family_options = {}
    if family == "dl":
        family_options = {"all_algos": forms.ALL_DL_ALGOS, "optuna_param_specs": D.DL_OPTUNA_PARAM_SPECS,
                          "deep_groups": _deep_field_groups()}
    torch_ok = family != "dl" or deep_models.torch_available()
    return templates.TemplateResponse(
        request,
        f"{family}.html",
        {"family": family,
            "torch_ok": torch_ok,
            "view": view,
            "errors": errors,
            "active_run": active,
            "queued_runs": run_manager.queued_runs(),
            "initial_run_id": initial_run_id if initial_run_id is not None else (active["id"] if active else None),
            "duplicated_run_id": duplicated_run_id,
            "applied": applied,
            "training_profiles": _profile_gallery(family),
            "movers": alerts.get_cached(),
            "recent_runs": _recent_runs(),
            **FORM_OPTIONS,
            **family_options,
            "target_groups": _target_groups_with_equity_badges(),
            # Première date connue de chaque cible (données ingérées, sinon première cotation vérifiée) : la page grise
            # les cibles plus récentes que « Historique minimum (années) » sans appel réseau.
            "depth_first": data_health.depth_by_symbol_for_form(),
            "min_history_bounds": D.MIN_HISTORY_YEARS_BOUNDS,
            "min_history_default": D.DEFAULT_MIN_HISTORY_YEARS,
            **_i18n_context(request),
        },
        status_code=status_code,
    )


@app.get("/launch")
def launch_legacy_redirect(request: Request):
    """Ancien poste de lancement : devenu la page Machine learning (`/ml`). La requête (`?target=`, `?run_id=`,
    `?profile=`, `?suggest=`) est conservée pour que les anciens liens et marque-pages continuent de fonctionner."""
    query = request.url.query
    return RedirectResponse("/ml" + (f"?{query}" if query else ""), status_code=308)


def _launch_page(request: Request, family: str, run_id: str | None, target: str | None, profile: str | None,
                 suggest: str | None):
    cfg = forms.default_config_dict(family)
    if target and target in forms.TARGET_SOURCE_BY_SYMBOL:
        # lien « Lancer » des pages de classes d'actifs : la cible est présélectionnée
        cfg["objective"]["target_symbol"] = target
        cfg["objective"]["target_source"] = forms.TARGET_SOURCE_BY_SYMBOL[target]
    if run_id:
        config = run_manager.get_run_config(run_id)
        if config is None:
            conn = trackdb.connect()
            try:
                row = trackdb.get_run(conn, run_id)
            finally:
                conn.close()
            if row is None or not row.get("config_json"):
                raise HTTPException(status_code=404, detail="Configuration de run introuvable.")
            config = RunConfig.model_validate_json(row["config_json"])
        if config.family != family:
            # un run de réseaux de neurones se rouvre sur /dl, un run d'arbres sur /ml : mêmes paramètres de requête
            return RedirectResponse(f"/{config.family}" + (f"?{request.url.query}" if request.url.query else ""), status_code=303)
        cfg = config.model_dump()
        cfg["output"]["dir"] = ""
    view, applied = forms.to_view(cfg), None
    if profile:
        chosen = (dl_profiles if family == "dl" else training_profiles).get(profile)
        if chosen is None:
            raise HTTPException(status_code=404, detail="Profil d'entraînement inconnu.")
        view = training_profiles.apply_patch(view, chosen.resolved_patch())
        applied = {"kind": "profile", "key": chosen.key,
                   "warning": "prof_warn_equity" if chosen.needs == "equity" else None}
    elif suggest and run_id:
        if family != "ml":
            raise HTTPException(status_code=404, detail="Suggestion de réentraînement indisponible pour cette famille.")
        conn = trackdb.connect()
        try:
            advice = retrain_advisor.advise_run(conn, run_id, limit=20)
        finally:
            conn.close()
        found = next((s for s in (advice or {}).get("suggestions", []) if s.key == suggest), None)
        if found is None:
            raise HTTPException(status_code=404, detail="Suggestion de réentraînement introuvable pour ce run.")
        view = training_profiles.apply_patch(view, {k: v for k, v in found.patch.items() if k in view})
        applied = {"kind": "suggest", "key": found.key, "run_id": run_id, "warning": None}
    return _render_launch(request, view, [], duplicated_run_id=run_id if not applied else None, applied=applied, family=family)


@app.get("/ml")
def ml_page(request: Request, run_id: str | None = None, target: str | None = None, profile: str | None = None,
            suggest: str | None = None):
    """Poste de lancement du machine learning (arbres, forêts, boosting). P8 (synthesis dashboard chantier) l'avait
    déplacé de `/` vers `/launch` ; il vit désormais sur `/ml`, `/dl` et `/rl` étant ses pages sœurs."""
    return _launch_page(request, "ml", run_id, target, profile, suggest)


@app.get("/dl")
def dl_page(request: Request, run_id: str | None = None, target: str | None = None, profile: str | None = None):
    """Poste de lancement du deep learning (MLP, GRU, LSTM, CNN1D, Transformer) : mêmes cibles, horizons, validation, sélection et
    tuning que le machine learning (les réseaux sont des algos de plus du même pipeline), avec un cadrage propre aux réseaux."""
    return _launch_page(request, "dl", run_id, target, profile, None)


@app.get("/")
def synthesis_page(request: Request, fdr_alpha: float = 0.10):
    """P8 -- synthesis dashboard, replaces the old `/` (now `/launch`).
    Structure: coverage banner, per-target DM/BH quality, latest prediction
    per target, winning-model metrics per target (split by direction),
    condensed recent-run history -- all read live from the database on
    every request (no page cache), same components/tokens as `/phase9`.
    Reliability detail (full p-value, cumulative trials, BH detail) is not
    duplicated inline: it lives on `/targets/{ticker}`/`/runs/{id}`, one
    click away.

    flexibility-gaps Gap 4: `fdr_alpha` (`?fdr_alpha=`, default 0.10, same
    literal `trackhistory.synthesis_overview`'s own `alpha` default) --
    `synthesis_overview` internally calls `station_verdict(conn,
    fdr_alpha=alpha)` (one of the three functions named in this gap) plus
    its own per-target FDR table, both fixed at 0.10 with no way to change
    it from the web before this. Plumbing only.

    NOT covered here: the small "verdict" banner shown in EVERY page's
    header chrome (`_station_verdict()`/`_i18n_context()` above) also
    calls `station_verdict()`, unconditionally at the 0.10 default -- it is
    shared header chrome rendered by every single route in this module,
    not this page's own content, so threading `fdr_alpha` through it would
    mean adding the parameter to every route in `app.py` rather than just
    the ones whose PAGE is about FDR/quality detail. The adjustable detail
    is one click away on this same page, `/targets/{ticker}`, and
    `/runs/{run_id}/detail` -- all three now support `?fdr_alpha=`."""
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")
    conn = trackdb.connect()
    try:
        coverage = {**trackhistory.universe_coverage(conn), "last_inference_at": trackhistory.last_inference_at(conn)}
        home = trackhome.home_summary(conn, forms.TARGET_GROUPS)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "synthesis.html",
        {"coverage": coverage, "home": home, "fdr_alpha": fdr_alpha, **_i18n_context(request, fdr_alpha=fdr_alpha)},
    )


@app.get("/fragments/home")
def home_fragment(request: Request, fdr_alpha: float = 0.10):
    """Fragment de la synthèse : les tableaux qui lisent les prédictions (6 s sur la vraie base), chargés après le cadre."""
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")
    conn = trackdb.connect()
    try:
        overview = memo.memoize(conn, ("home-overview", fdr_alpha), lambda: trackhistory.synthesis_overview(conn, alpha=fdr_alpha))
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "_home_details.html", {"overview": overview, **_i18n_context(request, fdr_alpha=fdr_alpha)},
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


@app.get("/api/market-state")
def market_state_api():
    """HMM market state (descriptive), refreshed in the background every 6 h."""
    return market_regime.get_cached()


@app.get("/api/next-run-names")
def next_run_names(target: Annotated[list[str] | None, Query()] = None):
    """(Read-only) preview of the name that will be assigned to each target
    if the form is submitted now — called by `app.js` when the target
    selection changes. Reserves nothing: the actual number may differ if
    other runs for the same target slot in before submission (see the
    batch-run-launch spec, known limitation)."""
    return {t: run_manager.next_run_name(t) for t in dict.fromkeys(target or [])}


@app.get("/api/horizon-feasibility")
def horizon_feasibility(target: Annotated[list[str] | None, Query()] = None):
    """Phase 1 (feature/expanded-horizons) -- data for `app.js` to disable
    infeasible `<option>`s in the shared `<select multiple name="horizons">`
    (index.html) as the target selection changes, mirroring
    `/api/next-run-names`'s pattern. A batch submission applies the SAME
    horizons list to every selected target (`create_run` calls
    `build_config_dict` once per target with the same form), so a horizon is
    reported infeasible here as soon as it is infeasible for ANY currently
    selected target -- the first blocking target/reason is surfaced.

    Based on the REAL cached history depth (`validation/feasibility.py`,
    `data/store.py`) -- never a static table, and never blocked when nothing
    is cached yet for a target (exposed with a warning instead, per this
    phase's guiding principle)."""
    symbols = list(dict.fromkeys(target or []))
    out: dict[str, dict] = {}
    for h in D.SELECTABLE_HORIZONS:
        blocking = None
        for sym in symbols:
            result = feasibility.check_feasibility(sym, h)
            if not result.feasible:
                blocking = result
                break
        if blocking is None:
            out[str(h)] = {"feasible": True}
        else:
            out[str(h)] = {
                "feasible": False,
                "symbol": blocking.symbol,
                "reason": blocking.reason,
                "n_obs": blocking.n_obs,
                "n_obs_required": blocking.n_obs_required,
            }
    return out


@app.get("/api/settings")
def get_settings():
    """Réglages machine exposés à la page « Lancer » (hors config des runs)."""
    cpu = os.cpu_count() or 1
    return {"parametric_jobs": settings_store.get_parametric_jobs(), "max_parametric_jobs": cpu,
            "env_override": os.environ.get(parametric_parallel.ENV_JOBS),
            "scan_jobs": settings_store.get_scan_jobs(), "env_override_scan": os.environ.get(scan_parallel.ENV_JOBS)}


@app.post("/api/settings/parametric-jobs")
async def set_parametric_jobs(request: Request):
    try:
        jobs = int((await request.json())["jobs"])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"error": "jobs doit être un entier."}, status_code=400)
    cpu = os.cpu_count() or 1
    if not 1 <= jobs <= cpu:
        return JSONResponse({"error": f"jobs doit être compris entre 1 et {cpu}."}, status_code=400)
    settings_store.save({settings_store.KEY_PARAMETRIC_JOBS: jobs})
    return {"parametric_jobs": jobs}


@app.post("/api/settings/scan-jobs")
async def set_scan_jobs(request: Request):
    try:
        jobs = int((await request.json())["jobs"])
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"error": "jobs doit être un entier."}, status_code=400)
    cpu = os.cpu_count() or 1
    if not 1 <= jobs <= cpu:
        return JSONResponse({"error": f"jobs doit être compris entre 1 et {cpu}."}, status_code=400)
    settings_store.save({settings_store.KEY_SCAN_JOBS: jobs})
    return {"scan_jobs": jobs}


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
    if any(a in D.ALL_DL_ALGOS for a in form.getlist("algos")) and not deep_models.torch_available():
        message = ("PyTorch n'est pas installé : les réseaux de neurones sont indisponibles. "
                   "Installe-le avec : pip install -e \".[deep]\" (ou pip install torch).")
        return JSONResponse({"errors": [message]}, status_code=400)

    raw_output_dir = (form.get("output_dir") or "").strip()
    errors: list[str] = []
    if raw_output_dir and not forms.validate_output_dir(raw_output_dir, errors):
        # Rejected (path traversal / invalid character, see
        # `forms.validate_output_dir`) -- clear it so the batch override
        # below never applies; each target's own `build_config_dict` call
        # independently re-validates the same raw form field and falls
        # back to its own `runs/{name}` default.
        raw_output_dir = ""
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
    # Une relance suit les règles d'aujourd'hui pour les séries FRED : première publication ALFRED (`data/alfred.py`), sauf
    # pour un audit en `reference_date` qui mesure justement l'ancienne fuite.
    if cfg_dict["universe"].get("fred_point_in_time") != "reference_date":
        cfg_dict["universe"]["fred_point_in_time"] = D.DEFAULT_FRED_POINT_IN_TIME
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
        "active_run": active,
        "queue": run_manager.queued_runs(),
    }


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str):
    job = run_manager.set_active_run_paused(job_id, True)
    if job is None:
        raise HTTPException(status_code=409, detail="Ce run n'est plus actif.")
    return job


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    job = run_manager.set_active_run_paused(job_id, False)
    if job is None:
        raise HTTPException(status_code=409, detail="Ce run n'est plus actif.")
    return job


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    try:
        stopped = run_manager.stop_active_run(job_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not stopped:
        raise HTTPException(status_code=409, detail="Ce run n'est plus actif.")
    return {"stopped": True}


@app.delete("/api/queue/{job_id}")
def remove_queued_job(job_id: str):
    if not run_manager.remove_queued_run(job_id):
        raise HTTPException(status_code=409, detail="Cet élément n'est plus dans la file.")
    return {"removed": 1}


@app.post("/api/queue/reorder")
async def reorder_queued_jobs(request: Request):
    """Body `{"order": [job_id, ...]}` = the full desired execution order of
    the queue. Returns the queue as it actually stands afterwards."""
    try:
        order = (await request.json())["order"]
        if not isinstance(order, list) or not all(isinstance(i, str) for i in order):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return JSONResponse({"error": "order doit être une liste d'identifiants."}, status_code=400)
    return {"queue": run_manager.reorder_queued_runs(order)}


@app.delete("/api/queue")
def clear_queued_jobs():
    return {"removed": run_manager.clear_queued_runs()}


def _get_run_or_404(run_id: str) -> dict:
    job = run_manager.get_run(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Run introuvable (redémarrage du serveur ?)")
    return job


@app.get("/runs/{run_id}")
def run_page(request: Request, run_id: str, dm_alpha: float = trackhistory.DM_SIGNIFICANCE_ALPHA,
             fdr_alpha: float = 0.10):
    """Same dashboard as the launch page (`launch_base.html`) — only
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
    is silently lost").

    flexibility-gaps Gap 2: this fallback renders the same
    `run_detail.html` template as `run_detail_page` below, so it needs the
    same `dm_significance_alpha` context value (`?dm_alpha=`) -- otherwise
    the template's comparison against an undefined value would raise.

    flexibility-gaps Gap 4: `fdr_alpha` (`?fdr_alpha=`, default 0.10 --
    same literal `tracking.history.run_detail`'s own default already uses)
    was already a parameter on `trackhistory.run_detail` (used by `patrick
    report --fdr-alpha`) but never reached this route -- every web visitor
    saw the FDR correction fixed at 0.10 no matter what. No new FDR
    calculation here, only the missing plumbing to the existing param."""
    if run_manager.get_run_kind(run_id) == "rl":
        return RedirectResponse(f"/rl?open={run_id}", status_code=303)
    if run_manager.get_run(run_id) is not None:
        config = run_manager.get_run_config(run_id)
        view = forms.to_view(config.model_dump())
        return _render_launch(request, view, [], initial_run_id=run_id, family=config.family)

    dm_alpha = _validate_alpha(dm_alpha, "dm_alpha")
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")
    conn = trackdb.connect()
    try:
        detail = trackhistory.run_detail(conn, run_id, fdr_alpha=fdr_alpha)
        kpi = trackkpi.summarize(conn, trackkpi.sibling_run_ids(conn, run_id))
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable (ni en mémoire, ni en base)")
    return templates.TemplateResponse(
        request, "run_detail.html",
        {"detail": detail, "kpi": kpi, "dm_significance_alpha": dm_alpha, "stats_run_id": run_id,
         **_i18n_context(request)},
    )




@app.get("/runs/{run_id}/status")
def run_status(run_id: str, request: Request):
    job = _get_run_or_404(run_id)
    # `log_tail` stays the raw pipeline output ("Journal technique"); `steps` is
    # the same log rewritten as readable sentences for the Avancement panel.
    return {**job, "steps": progress_steps.humanize_log(job.get("log_tail") or [], i18n.get_lang(request))}


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
                   scheme: str | None = None, q: str | None = None, algo: str | None = None,
                   kind: str | None = None,
                   started_after: date | None = None, started_before: date | None = None,
                   min_duration_s: float | None = Query(default=None, ge=0),
                   max_duration_s: float | None = Query(default=None, ge=0)):
    """Phase 7.1 — full run-history explorer."""
    if started_after and started_before and started_after > started_before:
        raise HTTPException(status_code=400, detail="La date de début doit précéder la date de fin.")
    if min_duration_s is not None and max_duration_s is not None and min_duration_s > max_duration_s:
        raise HTTPException(status_code=400, detail="La durée minimale dépasse la durée maximale.")
    conn = trackdb.connect()
    try:
        all_runs = trackdb.list_all_runs(conn)
    finally:
        conn.close()

    # Directional (price-direction) and alpha (excess return vs a benchmark) models are never mixed: a tab each.
    kind_counts = {"directional": sum(1 for r in all_runs if r.get("kind") == "directional"),
                   "alpha": sum(1 for r in all_runs if r.get("kind") == "alpha")}
    kind = kind if kind in kind_counts else None
    # Server-side filtering (scheme) and client-side (target/status) — see P2 critique
    runs = all_runs
    if kind:
        runs = [r for r in runs if r.get("kind") == kind]
    if target:
        runs = [r for r in runs if r.get("target") == target]
    if status:
        runs = [r for r in runs if r.get("status") == status]
    if scheme:
        # Scheme stored in config_json — extracted on the Python side
        runs = [r for r in runs if _extract_scheme(r) == scheme]
    algorithm_options = sorted({
        model for run in all_runs for model in _extract_algorithms(run.get("config_json"))
    })
    if algo:
        runs = [r for r in runs if algo in _extract_algorithms(r.get("config_json"))]
    if q:
        needle = q.casefold()
        runs = [
            r for r in runs
            if needle in str(r.get("name") or "").casefold()
            or needle in str(r.get("target") or "").casefold()
            or needle in str(r.get("run_id") or "").casefold()
        ]
    if started_after:
        runs = [r for r in runs if r.get("started_at") and r["started_at"][:10] >= started_after.isoformat()]
    if started_before:
        runs = [r for r in runs if r.get("started_at") and r["started_at"][:10] <= started_before.isoformat()]
    if min_duration_s is not None or max_duration_s is not None:
        runs = [
            r for r in runs
            if (duration := _run_duration_seconds(r)) is not None
            and (min_duration_s is None or duration >= min_duration_s)
            and (max_duration_s is None or duration <= max_duration_s)
        ]

    # Count runs per target for the dropdown filter
    target_counts = {}
    for r in all_runs:
        tgt = r.get("target")
        if tgt:
            target_counts[tgt] = target_counts.get(tgt, 0) + 1
    targets = [{"target": k, "n_runs": v} for k, v in sorted(target_counts.items())]

    # Security (reflected XSS) -- `runs.html`'s footer concatenates these
    # three query-param-derived strings directly into an HTML string that
    # is then rendered with `{{ footer | safe }}` (`_components.html::
    # data_table`) -- escaped here, at the one place they enter the
    # template context, rather than in the template (which legitimately
    # needs `|safe` for the rest of the footer's own server-built markup).
    # A no-op for every real filter value (ticker symbols, "done"/
    # "running"/..., "walkforward"/"cpcv" never contain HTML metacharacters).
    return templates.TemplateResponse(
        request, "runs.html",
        {"runs": runs, "targets": targets,
         "filter_target": html.escape(target) if target else "",
         "filter_status": html.escape(status) if status else "",
         "filter_scheme": html.escape(scheme) if scheme else "",
         "filter_query": q or "",
         "filter_kind": kind or "", "kind_counts": kind_counts, "n_all_runs": len(all_runs),
         "filter_algo": algo or "",
         "filter_started_after": started_after.isoformat() if started_after else "",
         "filter_started_before": started_before.isoformat() if started_before else "",
         "filter_min_duration_s": min_duration_s if min_duration_s is not None else "",
         "filter_max_duration_s": max_duration_s if max_duration_s is not None else "",
         "algorithms": algorithm_options,
         **_i18n_context(request)},
    )


def _extract_algorithms(config_json: str | None) -> list[str]:
    if not config_json:
        return []
    try:
        config = json.loads(config_json)
    except (TypeError, ValueError):
        return []
    if not isinstance(config, dict):
        return []
    models = config.get("models")
    algorithms = models.get("algos", []) if isinstance(models, dict) else []
    return [algorithm for algorithm in algorithms if isinstance(algorithm, str)] if isinstance(algorithms, list) else []


def _run_duration_seconds(run: dict) -> float | None:
    if not run.get("started_at") or not run.get("finished_at"):
        return None
    try:
        started = datetime.strptime(run["started_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        finished = datetime.strptime(run["finished_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (finished - started).total_seconds())


@app.get("/compare-runs")
def compare_runs(request: Request, run_ids: Annotated[list[str] | None, Query()] = None):
    selected_ids = list(dict.fromkeys(run_ids or []))
    if not 2 <= len(selected_ids) <= 4:
        raise HTTPException(status_code=400, detail="Sélectionne entre 2 et 4 runs à comparer.")
    conn = trackdb.connect()
    try:
        runs_by_id = {run["run_id"]: run for run in trackdb.list_all_runs(conn)}
    finally:
        conn.close()
    if any(run_id not in runs_by_id for run_id in selected_ids):
        raise HTTPException(status_code=404, detail="Un run sélectionné est introuvable.")
    selected_runs = []
    for run_id in selected_ids:
        run = runs_by_id[run_id]
        try:
            config = json.loads(run["config_json"]) if run.get("config_json") else {}
        except (TypeError, ValueError):
            config = {}
        if not isinstance(config, dict):
            config = {}
        objective = config.get("objective") if isinstance(config.get("objective"), dict) else {}
        sampler = config.get("sampler") if isinstance(config.get("sampler"), dict) else {}
        horizons = objective.get("horizons", [run.get("horizon")])
        selected_runs.append({
            **run,
            "name": config.get("name") or run_id,
            "target": html.unescape(run.get("target") or ""),
            "algorithms": _extract_algorithms(run.get("config_json")),
            "samplers": sampler.get("candidates", []) if isinstance(sampler.get("candidates", []), list) else [],
            "horizons": horizons if isinstance(horizons, list) else [run.get("horizon")],
            "duration_s": _run_duration_seconds(run),
        })
    return templates.TemplateResponse(
        request, "compare_runs.html",
        {"runs": selected_runs, **_i18n_context(request)},
    )


@app.post("/runs/{run_id}/rename")
async def rename_historical_run(run_id: str, request: Request):
    form = await request.form()
    name = form.get("name")
    conn = trackdb.connect()
    try:
        run = trackdb.get_run(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        if run["status"] in {"running", "queued"}:
            raise HTTPException(status_code=409, detail="Un run en cours ne peut pas être renommé.")
        try:
            trackdb.rename_run(conn, run_id, name if isinstance(name, str) else "")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run introuvable") from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()
    return RedirectResponse("/runs", status_code=303)


@app.post("/runs/{run_id}/delete")
def delete_historical_run(run_id: str):
    conn = trackdb.connect()
    try:
        if trackdb.get_run(conn, run_id) is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
        try:
            trackchampions.delete_non_champion_run(conn, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()
    return RedirectResponse("/runs", status_code=303)


@app.get("/runs/{run_id}/panel")
def run_side_panel(request: Request, run_id: str):
    """HTML fragment for the history page's right-hand panel (one section per
    selected run, fetched by `static/runs_panel.js`)."""
    conn = trackdb.connect()
    try:
        run = next((r for r in trackdb.list_all_runs(conn) if r["run_id"] == run_id), None)
    finally:
        conn.close()
    if run is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    try:
        config = json.loads(run["config_json"]) if run.get("config_json") else {}
    except (TypeError, ValueError):
        config = {}
    config = config if isinstance(config, dict) else {}
    objective = config.get("objective") if isinstance(config.get("objective"), dict) else {}
    sampler = config.get("sampler") if isinstance(config.get("sampler"), dict) else {}
    samplers = sampler.get("candidates", [])
    conn = trackdb.connect()
    try:
        best = trackhistory._best_trial_id(conn, run_id)
        folds = trackhistory.fold_metrics(conn, best) if best else []
        headline = trackhistory._headline_for_trial(conn, best) if best else {}
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "_run_panel.html",
        {"r": run, "fold_blocks": folds, "headline": headline,
         "algorithms": _extract_algorithms(run.get("config_json")),
         "samplers": [s for s in samplers if isinstance(s, str)] if isinstance(samplers, list) else [],
         "horizons": objective.get("horizons") or [run.get("horizon")],
         "duration_s": _run_duration_seconds(run), **_i18n_context(request)},
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


@app.get("/data-freshness")
def data_freshness_page(request: Request):
    """Phase 5 -- fraîcheur des données ingérées, par ticker/série, lue
    uniquement depuis le data lake local (`data/freshness.py`, jamais
    d'appel réseau yfinance/FRED depuis cette page)."""
    from patrick.data import freshness as data_freshness

    t = i18n.translator(i18n.get_lang(request))
    raw_groups = data_freshness.freshness_overview()
    groups = [
        {"group": t(i18n.TARGET_GROUP_LABEL_KEYS.get(g["group"], f"group_{g['group']}")),
         "results": g["results"]}
        for g in raw_groups
    ]
    return templates.TemplateResponse(
        request, "data_freshness.html",
        {"groups": groups, **_i18n_context(request)},
    )


@app.get("/data-quality")
def data_quality_page(request: Request, min_history_years: int = D.DEFAULT_MIN_HISTORY_YEARS):
    """Qualité des données telle que les entraînements l'ont vécue (`tracking/data_health.py`) : échecs et leur cause,
    séries écartées à l'ingestion, historique par cible comparé au seuil, résultats suspects. Lecture seule, sans réseau."""
    bounds = D.MIN_HISTORY_YEARS_BOUNDS
    if not bounds["min_allowed"] <= min_history_years <= bounds["max_allowed"]:
        raise HTTPException(status_code=400, detail=f"min_history_years doit être compris entre "
                                                    f"{bounds['min_allowed']} et {bounds['max_allowed']}.")
    t = i18n.translator(i18n.get_lang(request))
    conn = trackdb.connect()
    try:
        overview = data_health.overview(conn, forms.TARGET_GROUPS, min_history_years)
    finally:
        conn.close()
    for row in overview["history"]:
        row["group_label"] = t(i18n.TARGET_GROUP_LABEL_KEYS.get(row["group"], f"group_{row['group']}"))
    return templates.TemplateResponse(
        request, "data_quality.html",
        {"o": overview, "bounds": bounds, **_i18n_context(request)},
    )


@app.get("/vocabulary")
def vocabulary_page(request: Request):
    """Vocabulaire complet de l'application, par rubrique : les mêmes définitions que les bulles « ? », lisibles d'un
    bloc et filtrables. Aucun appel base ni réseau."""
    lang = i18n.get_lang(request)
    t = i18n.translator(lang)
    by_cat: dict[str, list[dict]] = {key: [] for key, _, _ in GLOSSARY_CATEGORIES}
    for term, entry in GLOSSARY.items():
        label_key = TERM_LABEL_KEYS.get(term)
        by_cat[TERM_CATEGORY.get(term, "app")].append({
            "key": term, "label": t(label_key) if label_key else term,
            "text": entry.get(lang) or entry.get(i18n.DEFAULT_LANG) or ""})
    categories = [{"key": key, "label": fr if lang == "fr" else en,
                   "terms": sorted(by_cat[key], key=lambda x: x["label"].casefold())}
                  for key, fr, en in GLOSSARY_CATEGORIES if by_cat[key]]
    return templates.TemplateResponse(
        request, "vocabulary.html",
        {"categories": categories, "n_terms": sum(len(c["terms"]) for c in categories), **_i18n_context(request)},
    )


@app.get("/analysis")
def analysis_page(request: Request):
    """Séries, features et modèles, vus de haut : lesquels reviennent le plus dans les modèles finaux, lesquels ne servent
    jamais, leur meilleure contribution, et les caractéristiques des modèles (algorithme, nombre de features, horizon, type).
    Lecture seule : base de suivi et fichiers méta des modèles exportés (`tracking/usage.py`)."""
    conn = trackdb.connect()
    try:
        analysis = trackusage.analyse(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(request, "analysis.html", {"a": analysis, **_i18n_context(request)})


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


def _alpha_run_labels(conn) -> list[tuple[str, str, str | None]]:
    """(étiquette de run, actif, benchmark) de chaque modèle alpha en base."""
    from patrick.config.target_label import split_run_label
    out = []
    for (label,) in conn.execute("SELECT DISTINCT target FROM run WHERE target LIKE ? ESCAPE '\\' ORDER BY target",
                                 ("%\\_\\_alpha\\_%",)):
        asset, _, benchmark = split_run_label(label)
        out.append((label, asset, benchmark))
    return out


def _predictions_overview(kind: str = "directional") -> dict:
    """feature/predictions-overview: universe-wide (target x horizon) table
    -- one row per pair, grouped by `DEFAULT_TARGET_GROUPS` category (same
    grouping `/universe` already uses). Server-rendered live from the DB on
    every request (no page cache, same philosophy as `/phase9`/`/universe`)
    via three small grouped queries (`trackhistory.
    latest_predictions_by_target_and_horizon`/
    `direction_metrics_by_target_and_horizon`/
    `live_hit_rate_by_target_and_horizon`) -- NOT a page-load client fetch
    like `asset_stats.js`: this data lives in our own indexed sqlite DB, not
    an external API, so there is no latency reason to defer it.

    `live_hit_rate_by_target_and_horizon` (Phase 3, suivi prediction ->
    realise) is a DISTINCT signal from `dm_p_value`: the Diebold-Mariano
    p-value comes from the backtest (`split IN ('test', 'holdout')`), while
    the live hit rate comes from actual `split='live'` calls already
    resolved against reality (`y_true IS NOT NULL`, backfilled by
    `predict.py::_update_live_outcomes`) -- a target can look good on
    backtest and still be missing live track record (`live_hit_rate is
    None`), or vice versa.

    Returns `{"groups": [{group, assets: [{symbol, label, cells: {horizon: cell}}]}], "horizons": [...]}`:
    one row per ASSET, one cell per horizon. Raw data (direction, confidence, dm p-value, live hit rate,
    live tally per movement) -- the
    ok/warning state and badge label are computed in the template, same
    convention as `universe.html`'s own inline `{% set state = ... %}`, not
    precomputed here as HTML strings."""
    alpha = kind == "alpha"
    conn = trackdb.connect()
    try:
        if alpha:
            alpha_labels = _alpha_run_labels(conn)
            all_symbols = [label for label, _, _ in alpha_labels]
            item_groups = {"Modèles alpha": [(label, f"{asset} α vs {bench}") for label, asset, bench in alpha_labels]}
            trained = {int(r[0]) for r in conn.execute("SELECT DISTINCT horizon FROM run WHERE target LIKE ? ESCAPE '\\'",
                                                       ("%\\_\\_alpha\\_%",))}
            horizons = sorted(trained & set(D.SELECTABLE_HORIZONS)) or list(D.DEFAULT_HORIZONS)
        else:
            all_symbols = [sym for items in D.DEFAULT_TARGET_GROUPS.values() for sym, _ in items]
            item_groups = D.DEFAULT_TARGET_GROUPS
            # Colonnes = horizons par defaut + tout horizon deja entraine (ex. 15/20/30 j).
            trained = {int(r[0]) for r in conn.execute("SELECT DISTINCT horizon FROM run")}
            horizons = sorted(set(D.DEFAULT_HORIZONS) | (trained & set(D.SELECTABLE_HORIZONS)))
        preds = trackhistory.latest_predictions_by_target_and_horizon(conn, all_symbols, horizons)
        metrics = trackhistory.direction_metrics_by_target_and_horizon(conn, all_symbols, horizons)
        live_hit_rates = trackhistory.live_hit_rate_by_target_and_horizon(conn, all_symbols, horizons)
        tallies = trackhistory.live_class_tally_by_target_and_horizon(conn, all_symbols, horizons)
        drift = trackhistory.drift_badges(conn, all_symbols, horizons)
        # Un modèle au score impossible (fuite de données) n'affiche pas de signal : `validation/suspicion.py`.
        shown = trackdb.batch_best_metrics(conn, sorted({p["run_id"] for p in preds.values()}))
        n_alpha = len(_alpha_run_labels(conn)) if not alpha else len(all_symbols)
    finally:
        conn.close()

    today = utc_today()
    signals = _PREDICTION_SIGNALS_ALPHA if alpha else _PREDICTION_SIGNALS
    groups = []
    for group_name, items in item_groups.items():
        assets = []
        for sym, label in items:
            cells = {}
            for h in horizons:
                pred = preds.get((sym, h))
                dm = (metrics.get((sym, h)) or {}).get("dm_result") if metrics.get((sym, h)) else None
                hit_rate = live_hit_rates.get((sym, h))
                tally = tallies.get((sym, h))
                signal = None
                market_closed = False
                suspect = None
                if pred:
                    scores = shown.get(pred["run_id"], {})
                    suspect = suspicion.suspect_reason(scores.get("holdout")) or suspicion.suspect_reason(scores.get("test"))
                    signal = None if suspect else signals.get((pred["direction"], pred["amplitude"]))
                    try:
                        market_closed = date.fromisoformat(str(pred["ts"])[:10]) < today
                    except ValueError:
                        market_closed = False
                cells[h] = {
                    "horizon": h,
                    "direction": pred["direction"] if pred else None,
                    "signal": signal,
                    "confidence": pred["confidence"] if pred else None,
                    "ts": pred["ts"] if pred else None,
                    "split": pred["split"] if pred else None,
                    "market_closed": market_closed,
                    "run_id": pred["run_id"] if pred else None,
                    "suspect": suspect,
                    "dm_p_value": dm["p_value"] if dm else None,
                    "dm_sample": dm.get("sample") if dm else None,
                    "drift": drift.get((sym, h)),
                    "live_hit_rate": hit_rate["hit_rate"] if hit_rate else None,
                    "live_hit_rate_n": hit_rate["n"] if hit_rate else None,
                    "tally": _tally_view(tally),
                }
            assets.append({"symbol": sym, "label": label, "cells": cells})
        groups.append({"group": group_name, "assets": assets})
    return {"groups": groups, "horizons": horizons, "kind": kind, "n_alpha": n_alpha}


# (direction, amplitude) -> (libelle, fleches, etat du badge) : les 4 mouvements du modele.
_PREDICTION_SIGNALS = {
    ("UP", "FORT"): ("Hausse forte", "▲▲", "ok"),
    ("UP", "FAIBLE"): ("Hausse faible", "▲", "ok"),
    ("DOWN", "FAIBLE"): ("Baisse faible", "▼", "warning"),
    ("DOWN", "FORT"): ("Baisse forte", "▼▼", "warning"),
}
# Idem pour un modèle alpha : il prédit l'écart de rendement face au benchmark, pas le sens du prix.
_PREDICTION_SIGNALS_ALPHA = {
    ("UP", "FORT"): ("Surperformance forte", "▲▲", "ok"),
    ("UP", "FAIBLE"): ("Surperformance faible", "▲", "ok"),
    ("DOWN", "FAIBLE"): ("Sous-performance faible", "▼", "warning"),
    ("DOWN", "FORT"): ("Sous-performance forte", "▼▼", "warning"),
}
_LIVE_CLASS_ORDER = (3, 2, 1, 0)  # indices de classe : 3 hausse forte ... 0 baisse forte
_LIVE_CLASS_LABELS = {3: "Hausse forte", 2: "Hausse faible", 1: "Baisse faible", 0: "Baisse forte"}


def _tally_view(tally: dict | None) -> dict | None:
    """Suivi live prêt à afficher, pour séparer l'erreur de DIRECTION de l'erreur d'INTENSITÉ.

    Par mouvement prédit : `n` signaux jugés, `exact` (bon mouvement), `intensity` (bon sens mais mauvaise intensité :
    hausse forte prédite, hausse faible réalisée) et `wrong_way` (mauvais sens). `exact + intensity + wrong_way = n`.
    `direction` : la même chose réduite à HAUSSE / BAISSE (inclut les signaux sans classe réalisée)."""
    if not tally:
        return None
    classes = []
    for c in _LIVE_CLASS_ORDER:
        row = (tally.get("matrix") or {}).get(c, {})
        n = sum(row.values())
        up = c >= 2
        exact = row.get(c, 0)
        same_side = sum(v for a, v in row.items() if (a >= 2) == up)
        classes.append({"label": _LIVE_CLASS_LABELS[c], "n": n, "hits": exact, "exact": exact,
                        "intensity": same_side - exact, "wrong_way": n - same_side,
                        "share": {_LIVE_CLASS_LABELS[a]: row.get(a, 0) for a in _LIVE_CLASS_ORDER}})
    d = tally.get("direction") or {"up": {"up": 0, "down": 0}, "down": {"up": 0, "down": 0}}
    direction = []
    for side, label in (("up", "Hausse prédite"), ("down", "Baisse prédite")):
        n = d[side]["up"] + d[side]["down"]
        hits = d[side][side]
        direction.append({"label": label, "n": n, "hits": hits, "wrong": n - hits})
    return {
        "since": str(tally["since"])[:10],
        "pending": tally["pending"],
        "direction_n": tally["direction_n"],
        "direction_hits": tally["direction_hits"],
        "classes": classes,
        "direction": direction,
        "n_four": sum(c["n"] for c in classes),
    }


@app.get("/predictions")
def predictions_page(request: Request, dm_alpha: float = trackhistory.DM_SIGNIFICANCE_ALPHA,
                     kind: str = "directional"):
    """feature/predictions-overview: tableau universel (cible x horizon) -- signal, significativité Diebold-Mariano, fiabilité
    live. La page n'envoie que son cadre (titre, onglets, légende) ; le tableau, qui lit ~24 millions de prédictions
    (3 s sur la vraie base), arrive par `/fragments/predictions` après l'affichage et est mémorisé tant que la base ne change pas.

    `live_hit_rate_window`/`live_hit_rate_warning_threshold` (Phase 3): passés au fragment pour nommer la fenêtre et le seuil
    plutôt que de coder un nombre qui pourrait diverger de `tracking/history.py`.

    flexibility-gaps Gap 2: `dm_significance_alpha` (`?dm_alpha=`, défaut `tracking.history.DM_SIGNIFICANCE_ALPHA` = 0.05)."""
    dm_alpha = _validate_alpha(dm_alpha, "dm_alpha")
    kind = "alpha" if kind == "alpha" else "directional"
    conn = trackdb.connect()
    try:
        n_alpha = len(_alpha_run_labels(conn))
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "predictions.html",
        {"kind": kind, "n_alpha": n_alpha, "live_refresh": live_refresh.refresh_status(),
         "dm_significance_alpha": dm_alpha, **_i18n_context(request)},
    )


@app.get("/fragments/predictions")
def predictions_fragment(request: Request, dm_alpha: float = trackhistory.DM_SIGNIFICANCE_ALPHA,
                         kind: str = "directional"):
    """Fragment HTML du tableau des prédictions (chargé par `static/lazy.js`)."""
    dm_alpha = _validate_alpha(dm_alpha, "dm_alpha")
    kind = "alpha" if kind == "alpha" else "directional"
    conn = trackdb.connect()
    try:
        overview = memo.memoize(conn, ("predictions", kind, utc_today().isoformat()), lambda: _predictions_overview(kind))
    finally:
        conn.close()
    return templates.TemplateResponse(
        request, "_predictions_body.html",
        {**overview, "live_hit_rate_window": trackhistory.LIVE_HIT_RATE_WINDOW,
         "live_hit_rate_warning_threshold": trackhistory.LIVE_HIT_RATE_WARNING_THRESHOLD,
         "dm_significance_alpha": dm_alpha, **_i18n_context(request)},
    )


@app.get("/portfolio")
def portfolio_page(request: Request, pairs: str | None = None):
    """Phase 8 (feature/portfolio-view): cross-asset aggregated synthesis --
    bullish/bearish signal counts per `DEFAULT_TARGET_GROUPS` category, plus
    contradiction detection between historically correlated pairs (DXY/EUR-
    USD, WTI/Brent, S&P500/VIX -- see
    `tracking.portfolio.CORRELATED_PAIRS`). All aggregation happens in
    `tracking.portfolio.portfolio_overview()`, which sources its data from
    the SAME grouped query `/predictions` already uses
    (`history.latest_predictions_by_target_and_horizon`) -- no new DB query
    written for this page, same read-only-on-every-request philosophy as
    every other page in this module.

    flexibility-gaps Gap 6: `pairs` (`?pairs=`, GET form on `portfolio.html`
    itself -- one `symbol_a:symbol_b:sens` per line) overrides the
    hardcoded `CORRELATED_PAIRS`. Not routed through `/launch`: that form
    builds a `RunConfig` for the ML pipeline, which this read-only,
    run-independent aggregation page has no relationship to (it reads
    `latest_predictions_by_target_and_horizon` directly, not any specific
    run's config) -- a GET query param on this page's own route, same
    pattern as every other display-time override in this session
    (`?zscore_window=` on `/api/asset-stats`, `?dm_alpha=`/`?fdr_alpha=`
    above), fits the data flow here. Malformed input (see
    `tracking.portfolio.parse_correlated_pairs`) is this route's only 400;
    missing/blank keeps the 3 defaults."""
    try:
        parsed_pairs = trackportfolio.parse_correlated_pairs(pairs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    conn = trackdb.connect()
    try:
        overview = trackportfolio.portfolio_overview(conn, pairs=parsed_pairs)
    finally:
        conn.close()
    # CHANTIER D (feature/hrp-portfolio): s'ajoute a la synthese ci-dessus,
    # ne la remplace pas -- calcul independant (prix caches localement, pas
    # `latest_predictions_by_target_and_horizon`), echoue silencieusement
    # vers une liste de poids vide plutot que de faire echouer toute la page
    # (meme esprit read-only-avec-avertissement que le reste de cette route).
    try:
        hrp = trackhrp.hrp_overview()
    except Exception:  # noqa: BLE001 -- page robustness: HRP failure degrades to an empty panel, never a 500
        hrp = {"weights": None, "skipped": [], "as_of": None, "n_assets": 0}
    return templates.TemplateResponse(
        request, "portfolio.html",
        {
            "overview": overview,
            "pairs_text": trackportfolio.format_correlated_pairs(overview["pairs_used"]),
            "hrp": hrp,
            **_i18n_context(request),
        },
    )


@app.post("/api/drift/{target}/{horizon}")
def api_measure_drift(target: str, horizon: int):
    """Roadmap bloc 3 -- on-demand PSI of the exported model's features for
    ONE (target, horizon) (`explain.compute_drift_for_ticker_horizon`, which
    records it in `drift_psi_history`, read by the /predictions badge).
    Rebuilds the feature pool: an explicit user action, never a page loop."""
    from patrick import explain as explain_module
    from patrick.validation.drift import data_drift_status

    try:
        result = explain_module.compute_drift_for_ticker_horizon(target, horizon)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Mesure impossible : {exc}") from exc
    if not result:
        raise HTTPException(status_code=404, detail="Pas de modèle exporté avec une référence de dérive "
                                                    "pour cette cible et cet horizon (ou historique récent insuffisant).")
    features = sorted(({"feature": f, "psi": v["psi"], "status": v.get("status") or data_drift_status(v["psi"])}
                       for f, v in result.items()), key=lambda r: -r["psi"])
    return {"target": target, "horizon": horizon, "features": features}


# Roadmap bloc 4 -- PATRIMOINE (pages /patrimoine, /mouvements + /api/wealth/*).
wealth_routes.register(app, templates, lambda request: _i18n_context(request))

# Application de bureau : page Réglages (/reglages) et API /api/app/* (dossier partagé, mises à jour, fenêtre).
settings_routes.register(app, templates, lambda request: _i18n_context(request))

# Refonte Simulation + Fonds (chantier 1) : pages /simulate, /fonds et API /api/fund/*.
fund_routes.register(app, templates, lambda request: _i18n_context(request))

# Page Exploration (/exploration) et API /api/exploration/* : études statistiques entre actifs (patrick/exploration/).
exploration_routes.register(app, templates, lambda request: _i18n_context(request))

# Page Reinforcement learning (/rl) et API /api/rl/* : cadrage, lancement et lecture des runs RL (patrick/rl/).
rl_routes.register(app, templates, lambda request: _i18n_context(request))


def _asset_class_context(request: Request, class_key: str, min_history_years: int) -> dict:
    """Contexte commun des pages de classes d'actifs (`templates/asset_class.html`) : une ligne par cible avec son historique et
    ses modèles directionnels / alpha, les compteurs d'en-tête, et la grille de cours (si la classe est assez petite)."""
    bounds = D.MIN_HISTORY_YEARS_BOUNDS
    if not bounds["min_allowed"] <= min_history_years <= bounds["max_allowed"]:
        raise HTTPException(status_code=400, detail=f"min_history_years doit être compris entre "
                                                    f"{bounds['min_allowed']} et {bounds['max_allowed']}.")
    conn = trackdb.connect()
    try:
        page = class_overview.class_page(conn, class_key, forms.TARGET_GROUPS, min_history_years)
    finally:
        conn.close()
    total = page["kpi"]["n_targets"]
    panels = ([{"symbol": r["symbol"], "label": r["label"], "slug": forms.slug_target(r["symbol"])}
               for g in page["groups"] for r in g["rows"]] if total <= 40 else [])
    return {"cls": page["class"], "groups": page["groups"], "kpi": page["kpi"], "panels": panels,
            "min_years": min_history_years,
            **_i18n_context(request)}


def _register_asset_class_pages() -> None:
    """Une page par classe d'actifs (hors Equity et Macro, qui ont leur propre gabarit) : mêmes colonnes, mêmes filtres."""
    def make(class_key: str):
        def page(request: Request, min_history_years: int = D.DEFAULT_MIN_HISTORY_YEARS):
            return templates.TemplateResponse(request, "asset_class.html",
                                              _asset_class_context(request, class_key, min_history_years))
        page.__name__ = f"{class_key}_page"
        return page

    for cls in asset_classes.ASSET_CLASSES:
        if cls.key not in ("equity", "macro"):
            app.add_api_route(cls.url, make(cls.key), methods=["GET"], name=f"{cls.key}_page")


_register_asset_class_pages()


def _macro_sections_view(t) -> list[dict]:
    """/macro: every FRED series of the universe, one panel skeleton each,
    grouped by domain with the headline indicators first
    (`D.MACRO_PAGE_SECTIONS`). `training_only` flags the series that feed
    the models but are not offered as targets."""
    targets = {sym for sym, _ in D.DEFAULT_TARGET_GROUPS[D.FRED_TARGET_GROUP]}
    return [
        {"key": key, "title": t(f"macro_section_{key}"),
         "assets": [{"symbol": sid, "label": label, "slug": forms.slug_target(sid),
                     "training_only": sid not in targets} for sid, label in series]}
        for key, series in D.macro_page_sections()
    ]


@app.get("/macro")
def macro_page(request: Request):
    """feature/ticker-stats-panel: same panel, for every FRED series of the
    universe, sectioned by domain (key indicators first)."""
    t = i18n.translator(i18n.get_lang(request))
    return templates.TemplateResponse(
        request, "macro.html",
        {"macro_sections": _macro_sections_view(t), **_i18n_context(request)},
    )


@app.get("/fragments/macro-alfred")
def macro_alfred_fragment(request: Request):
    """Tableau FRED contre ALFRED de la page Macro, lu dans le cache local (jamais d'appel réseau ici)."""
    from patrick.tracking import alfred_report

    return templates.TemplateResponse(
        request, "_macro_alfred.html",
        {"report": alfred_report.load_report(), "state": alfred_report.status(), "key_ok": alfred_report.api_key_available(),
         **_i18n_context(request)},
    )


@app.post("/api/macro/alfred-refresh")
def macro_alfred_refresh():
    """Lance (en arrière-plan) le calcul du rapport FRED contre ALFRED ; une seule exécution à la fois."""
    from patrick.tracking import alfred_report

    if not alfred_report.api_key_available():
        raise HTTPException(status_code=409, detail="FRED_API_KEY absente : ALFRED est inaccessible.")
    started = alfred_report.start_background(refresh=True)
    return {"started": started, **alfred_report.status()}


@app.get("/api/macro/alfred-status")
def macro_alfred_status():
    from patrick.tracking import alfred_report

    return alfred_report.status()


def _equity_asset_group_view() -> list[dict]:
    """CHANTIER (feature/equity-asset-class): same panel-skeleton shape as
    `_asset_group_view` (symbol/label/slug), plus the data-sufficiency badge
    (`validation/equity_sufficiency.py`) and the ticker's metadata
    (`config.equity_universe.EQUITY_UNIVERSE`) -- unlike commodities/macro,
    this group has few enough tickers (4) that computing the badge
    server-side, once per page load, is cheap (cached 7 days via
    `yfinance_source.download_one`'s own `LocalCache`)."""
    out = []
    for sym, meta in EQ.EQUITY_UNIVERSE.items():
        result = equity_sufficiency.check_data_sufficiency(sym)
        out.append({
            "symbol": sym, "label": meta["label"], "slug": forms.slug_target(sym),
            "currency": meta["currency"], "exchange": meta["exchange"],
            "first_listed": meta["first_listed"],
            "sufficient": result.sufficient, "n_trading_days": result.n_trading_days,
            "min_required": result.min_required, "reason": result.reason,
        })
    return out


@app.get("/equities")
def equities_legacy_redirect():
    """Ancienne page « Actions individuelles » : devenue le module Equity (`/equity`)."""
    return RedirectResponse("/equity", status_code=308)


@app.get("/equity")
def equity_page(request: Request, min_history_years: int = D.DEFAULT_MIN_HISTORY_YEARS):
    """Module Equity : toutes les actions de l'univers (US, France, Allemagne, Royaume-Uni, Europe, Asie), avec pour chacune
    son historique et ses modèles directionnels / alpha ; puis le détail des actions suivies en profondeur (prix et
    statistiques, disponibilité des données, fondamentaux). Fondamentaux rendus côté serveur (4 tickers seulement, déjà
    mis en cache 7 jours par `fundamentals_source.fetch_fundamentals`)."""
    ctx = _asset_class_context(request, "equity", min_history_years)
    assets = _equity_asset_group_view()
    fundamentals = {
        a["symbol"]: fundamentals_source.fetch_fundamentals(a["symbol"]).tail(12).to_dict("records")
        for a in assets
    }
    return templates.TemplateResponse(
        request, "equity.html",
        {**ctx, "assets": assets, "fundamentals": fundamentals, "exclusions": guida.equity_feature_exclusions()},
    )


@app.get("/api/asset-stats/{symbol}")
def asset_stats_api(
    symbol: str,
    period: str = "5y",
    zscore_window: int = asset_stats.ZSCORE_WINDOW,
    ma_windows: str | None = None,
    long_windows_bars: str | None = None,
):
    """feature/ticker-stats-panel: fetched client-side, once per panel, by
    `asset_stats.js`. Same data-access path as `/api/preview/{symbol}`
    (`forms.TARGET_SOURCE_BY_SYMBOL` -> `market_data.price_history`) --
    `asset_stats.compute_stats` only adds the display-stats layer on top,
    it does not fetch anything itself. `period="5y"`: comfortably covers
    every window this module computes (longest is the 252-bar view /
    200-bar MA) without requesting `"max"` for every asset on every page
    load.

    flexibility-gaps Gap 1: `zscore_window`/`ma_windows`/`long_windows_bars`
    (e.g. `?zscore_window=90&ma_windows=20,50,100`) override
    `asset_stats.py`'s fixed `ZSCORE_WINDOW`/`MA_WINDOWS`/`LONG_WINDOWS_BARS`
    defaults -- unset means unchanged default, matching every other
    optional query param in this module. Only this API route takes the
    parameter: `/commodities`/`/macro` (`commodities_page`/`macro_page`
    above) render static panel skeletons with no computation of their own
    (see their docstrings and `asset_stats.py` module docstring) --
    `asset_stats.js` fetches this route per panel without forwarding any
    query string today, so a page-level query param here would reach no
    code at all. Validated via `asset_stats.validate_window`/
    `parse_window_list`; a `ValueError` from either becomes this route's
    only 400 (every other error path here is a 404 on an unknown
    symbol)."""
    source = forms.TARGET_SOURCE_BY_SYMBOL.get(symbol)
    if source is None and symbol in D.MACRO_DISPLAY_IDS:
        source = "fred"     # shown on /macro, but not a target
    if source is None:
        raise HTTPException(status_code=404, detail="Symbole inconnu")
    try:
        zscore_window = asset_stats.validate_window(zscore_window, name="zscore_window")
        ma_windows_list = asset_stats.parse_window_list(
            ma_windows, asset_stats.MA_WINDOWS, name="ma_windows"
        )
        long_windows_list = asset_stats.parse_window_list(
            long_windows_bars, asset_stats.LONG_WINDOWS_BARS, name="long_windows_bars"
        )
    except asset_stats.InvalidWindowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if source == "fred" and period == "5y":
        # 5 years of a quarterly series is 19 points, under the stats
        # minimum: slow series get their whole (still small) history.
        from patrick.data.freshness import fred_periodicity
        if fred_periodicity(symbol) in ("monthly", "quarterly"):
            period = "max"
    series = market_data.price_history(symbol, source, period)
    return asset_stats.compute_stats(
        series,
        zscore_window=zscore_window,
        ma_windows=ma_windows_list,
        long_windows_bars=long_windows_list,
    )


@app.get("/targets/{ticker}")
def target_page(request: Request, ticker: str, fdr_alpha: float = 0.10):
    """Phase 7.3 — aggregated view of all runs for a target.

    flexibility-gaps Gap 4: `fdr_alpha` (`?fdr_alpha=`, default 0.10, same
    literal as `trackhistory.target_detail`'s own default) -- plumbing
    only, same rationale as `run_detail_page`/`run_page` above.
    `target.html` already reads `detail.fdr_result.alpha` dynamically."""
    if ticker not in forms.TARGET_SOURCE_BY_SYMBOL:
        raise HTTPException(status_code=404, detail="Cible inconnue")
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")

    conn = trackdb.connect()
    try:
        detail = trackhistory.target_detail(conn, ticker, fdr_alpha=fdr_alpha)
        # P9 -- phase-timing drift, independent of `detail`'s None-ness on
        # purpose: cheap either way (empty list when there is no
        # `run_phase_timing` row for this target), and computing it inside
        # the same connection avoids a second `trackdb.connect()`.
        phase_drift = trackhistory.phase_timing_drift_for_target(conn, ticker)
        alpha_runs = trackhistory.alpha_runs_for_asset(conn, ticker)
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
        {"target": ticker, "detail": detail, "phase_drift": phase_drift, "alpha_runs": alpha_runs,
         "phase_labels": PHASE_LABELS, "shap_horizons": done_horizons, **_i18n_context(request)},
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
        from patrick import (
            explain,  # chargé à la demande : shap + pipeline coûtent ~3,5 s à l'import (démarrage de l'app)
        )

        result = explain.explain_last_prediction(ticker, horizon)
    except Exception as exc:  # noqa: BLE001 -- never let an explanation failure break the page
        return JSONResponse({"ok": False, "message": f"Erreur de calcul SHAP : {exc}"})
    if result is None:
        return JSONResponse({"ok": False, "message": "Aucune prédiction exploitable pour cet horizon."})
    svg = shap_chart.render_waterfall_svg(result["base_value"], result["contributions"], result["final_value"])
    return JSONResponse({
        "ok": True, "svg": svg, "ts": result["ts"], "split": result["split"],
        "y_pred": result["y_pred"], "y_pred_label": result["y_pred_label"],
        "y_proba": result["y_proba"], "n_features_total": result["n_features_total"],
        "units": result.get("units", "raw"),
    })


@app.get("/runs/{run_id}/detail")
def run_detail_page(request: Request, run_id: str, dm_alpha: float = trackhistory.DM_SIGNIFICANCE_ALPHA,
                     fdr_alpha: float = 0.10):
    """Phase 7.2 — read-only detail page for a run (CLI or web).

    flexibility-gaps Gap 2: `dm_significance_alpha` (`?dm_alpha=`), same
    constant/param/validation as `predictions_page` above -- single source
    for the Diebold-Mariano ok/warning threshold this template shows.

    flexibility-gaps Gap 4: `fdr_alpha` (`?fdr_alpha=`, default 0.10, same
    literal as `trackhistory.run_detail`'s own default) -- plumbing only,
    `trackhistory.run_detail` already accepted this parameter (used by
    `patrick report --fdr-alpha`), no web route forwarded it. `template
    (`run_detail.html`) already reads the resulting `detail.fdr_result.alpha`
    dynamically, so no template change is needed here."""
    dm_alpha = _validate_alpha(dm_alpha, "dm_alpha")
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")
    conn = trackdb.connect()
    advice = None
    try:
        detail = trackhistory.run_detail(conn, run_id, fdr_alpha=fdr_alpha)
        # KPI of the WHOLE launch (all the horizons that share this run's job)
        kpi = trackkpi.summarize(conn, trackkpi.sibling_run_ids(conn, run_id))
        if detail is not None:
            try:
                advice = retrain_advisor.advise_run(conn, run_id, detail=detail, history=data_health.history_depths())
            except Exception:  # noqa: BLE001 -- le conseil est un plus : il ne doit jamais faire échouer la page du run
                advice = None
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail="Run introuvable")
    return templates.TemplateResponse(
        request, "run_detail.html",
        {"detail": detail, "kpi": kpi, "advice": advice, "dm_significance_alpha": dm_alpha, "stats_run_id": run_id,
         **_i18n_context(request)},
    )


@app.get("/api/stats-help/runs")
def stats_help_runs():
    """Runs proposés comme référence du bandeau d'aide statistique : les terminés, les plus récents d'abord."""
    conn = trackdb.connect()
    try:
        runs = trackdb.list_done_runs(conn, limit=60)
    finally:
        conn.close()
    return {"runs": [{"run_id": r["run_id"], "label": f"{r['name'] or r['run_id']} · {r['target']} · {r['horizon']}j"}
                     for r in runs]}


@app.get("/api/stats-help")
def stats_help_fragment(request: Request, run_id: str | None = None, dm_alpha: float = trackhistory.DM_SIGNIFICANCE_ALPHA,
                        fdr_alpha: float = 0.10):
    """Fragment HTML du bandeau d'aide statistique : les p-values et la procédure du run de référence (`run_id`), ou
    l'explication générale sans run."""
    dm_alpha = _validate_alpha(dm_alpha, "dm_alpha")
    fdr_alpha = _validate_alpha(fdr_alpha, "fdr_alpha")
    detail = None
    if run_id:
        conn = trackdb.connect()
        try:
            detail = trackhistory.run_detail(conn, run_id, fdr_alpha=fdr_alpha)
        finally:
            conn.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="Run introuvable")
    if detail is not None:
        run = {"name": detail["config"].get("name") or run_id, "target": detail["run"]["target"],
               "horizon": detail["run"]["horizon"]}
        items = stats_help.pvalue_items(detail, dm_alpha, fdr_alpha)
        steps = stats_help.procedure_steps(detail, dm_alpha, fdr_alpha)
    else:
        run, steps = None, []
        items = [{"key": k, "state": "neutral", "value": None, "reading": "", "args": {}}
                 for k in ("dm", "bh", "spearman", "pbo", "trials")]
    return templates.TemplateResponse(
        request, "_stats_help.html",
        {"run": run, "items": items, "steps": steps, "dm_alpha": f"{dm_alpha:g}", "fdr_alpha": f"{fdr_alpha:g}",
         **_i18n_context(request)},
    )


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


def main() -> None:
    import uvicorn

    uvicorn.run("patrick.webapp.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
