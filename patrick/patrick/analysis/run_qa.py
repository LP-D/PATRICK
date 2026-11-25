"""Questions en langage naturel sur un run (A27) : Claude répond à partir des seuls chiffres enregistrés du run.

Le contexte envoyé est un résumé compact de `tracking.history.run_detail` (cible, horizon, configuration utile, meilleur essai, métriques
de test et du holdout, tests de Diebold-Mariano, PBO, essais cumulés, références naïves, FDR, drapeau « suspect »). Le modèle a pour
consigne de répondre uniquement depuis ces chiffres, de dire quand une information manque, de ne faire ni prévision de marché ni
recommandation.

Garde-fou de fuite temporelle (`text/llm_guard.py`) : le modèle de langage connaît les marchés jusqu'à sa date limite de connaissance.
Pour la part des dates évaluées (test et holdout) antérieures à cette limite plus la marge, toute explication « causale » d'un succès ou
d'un échec peut mêler la lecture des chiffres et le souvenir de ce qui s'est passé ensuite : la réponse le signale, avec la part propre.

Appel : SDK `anthropic` (importé à la demande ; `pip install anthropic`), identifiants résolus par le SDK (`ANTHROPIC_API_KEY` ou
`ant auth login`). Modèle Claude Opus 5.5, effort moyen, repli serveur en cas de refus (`fallbacks: "default"`). Le contexte du run est mis
en cache (bloc système marqué `cache_control`) : plusieurs questions sur le même run ne le repaient pas en entier.
"""
from __future__ import annotations

import json
import sqlite3

import pandas as pd

from patrick.text import llm_guard

MODEL = "claude-opus-5-5"
MAX_QUESTION_CHARS = 2000
MAX_LIST = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM = (
    "Tu es l'assistant d'analyse de PATRICK, une station de recherche quantitative personnelle. On te donne, en JSON, le résumé d'UN run "
    "d'entraînement (modèles qui prédisent la direction d'un actif à un horizon donné) puis une question. Règles :\n"
    "1. Réponds uniquement à partir des chiffres du JSON. Si l'information n'y est pas, dis-le simplement et indique où la trouver "
    "dans l'application si c'est évident (page du run, onglets Analyse, Comparer).\n"
    "2. N'utilise pas ce que tu sais des marchés réels pendant ou après la période évaluée pour expliquer un résultat : ce serait une "
    "fuite d'information future. Tu peux expliquer les méthodes (walk-forward, holdout, Diebold-Mariano, PBO, FDR).\n"
    "3. Aucune prévision de marché, aucune recommandation d'achat ou de vente.\n"
    "4. Réponds en français, de façon concise, en citant les chiffres utilisés (avec leur nom dans le JSON quand c'est utile). Un F1 ou "
    "une AUC proche de 0,5 sur la direction, c'est le hasard : dis-le.\n"
)


NO_CREDENTIALS = ("Aucune clé API Claude configurée : définir la variable d'environnement ANTHROPIC_API_KEY (ou lancer `ant auth login`), "
                  "puis relancer `patrick serve`.")


class QAUnavailable(RuntimeError):
    """Questions impossibles : SDK absent, identifiants manquants ou refusés, API injoignable (message affichable)."""


def _compact(value, depth: int = 0):
    """Copie JSON-sérialisable et bornée : listes tronquées à `MAX_LIST`, profondeur limitée, flottants arrondis."""
    if depth > 5:
        return "…"
    if isinstance(value, dict):
        return {str(k): _compact(v, depth + 1) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        items = [_compact(v, depth + 1) for v in list(value)[:MAX_LIST]]
        if len(value) > MAX_LIST:
            items.append(f"… {len(value) - MAX_LIST} de plus")
        return items
    if isinstance(value, float):
        return round(value, 4) if pd.notna(value) else None
    if isinstance(value, (int, str, bool)) or value is None:
        return value
    return str(value)


def _evaluated_dates(conn: sqlite3.Connection, trial_id: str | None) -> tuple[str | None, str | None]:
    if not trial_id:
        return None, None
    try:
        first, last = conn.execute("SELECT MIN(ts), MAX(ts) FROM prediction WHERE trial_id = ? AND split IN ('test', 'holdout')",
                                   (trial_id,)).fetchone()
    except sqlite3.Error:
        return None, None
    return (str(first)[:10] if first else None), (str(last)[:10] if last else None)


def run_context(conn: sqlite3.Connection, run_id: str) -> dict | None:
    """Résumé compact du run pour le modèle ; None si le run n'existe pas."""
    from patrick.tracking import history

    detail = history.run_detail(conn, run_id, with_meta_labeling=False, lite=True)
    if detail is None:
        return None
    run, cfg, best = detail["run"], detail["config"], detail.get("best_trial") or {}
    trials = sorted(detail.get("trials") or [], key=lambda t: (not t.get("is_best"), str(t.get("trial_id"))))
    first, last = _evaluated_dates(conn, best.get("trial_id"))
    return _compact({
        "run": {k: run.get(k) for k in ("run_id", "target", "horizon", "status", "created_at", "finished_at", "snapshot_id")},
        "config": {"objective": cfg.get("objective"), "validation": cfg.get("validation"), "models": cfg.get("models"),
                   "selection": cfg.get("selection"), "features": {k: (cfg.get("features") or {}).get(k)
                                                                   for k in ("families", "vol_models", "enable_text_features")},
                   "universe_size": len((cfg.get("universe") or {}).get("yf_tickers") or []),
                   "fred_series": len((cfg.get("universe") or {}).get("fred_series") or {})},
        "evaluated_period": {"first": first, "last": last},
        "best_trial": best, "headline": detail.get("headline"), "holdout": detail.get("holdout_f1_dir"),
        "diebold_mariano": detail.get("dm_result"), "pbo": detail.get("pbo"), "cumulative_trials": detail.get("cumulative_trials"),
        "baselines": detail.get("baselines"), "fdr": detail.get("fdr_result"), "suspect": detail.get("suspect"),
        "fold_metrics": detail.get("fold_metrics"), "trials": trials,
    })


def leak_note(context: dict, model: str = MODEL, margin_days: int = llm_guard.DEFAULT_MARGIN_DAYS) -> dict:
    """Part des dates évaluées postérieures à la limite de connaissance du modèle (plus la marge) : `{"clean_share", "cutoff"}`."""
    period = context.get("evaluated_period") or {}
    cutoff = llm_guard.knowledge_cutoff(model)
    if not period.get("first") or not period.get("last"):
        return {"clean_share": None, "cutoff": cutoff.strftime("%Y-%m-%d")}
    days = pd.bdate_range(period["first"], period["last"])
    share = float(llm_guard.clean_mask(model, days, margin_days=margin_days).mean()) if len(days) else None
    return {"clean_share": share, "cutoff": cutoff.strftime("%Y-%m-%d")}


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise QAUnavailable("Le module « anthropic » n'est pas installé : `pip install anthropic` dans l'environnement de PATRICK.") from exc
    try:
        return anthropic.Anthropic()
    except Exception as exc:  # frontière fournisseur : configuration invalide (relancée en message affichable)
        raise QAUnavailable(f"Client Claude impossible à créer ({type(exc).__name__}) : définir ANTHROPIC_API_KEY ou lancer `ant auth login`.") from exc


def ask(question: str, context: dict, client=None) -> dict:
    """Réponse de Claude à `question` sur le run résumé par `context` : `{"answer", "model", "refused", "leak", "usage"}`."""
    question = (question or "").strip()
    if not question:
        raise ValueError("question vide")
    question = question[:MAX_QUESTION_CHARS]
    leak = leak_note(context)
    client = client or _client()
    request = {
        "model": MODEL, "max_tokens": 16000, "betas": [FALLBACK_BETA], "fallbacks": "default",
        "output_config": {"effort": "medium"},
        "system": [{"type": "text", "text": SYSTEM},
                   {"type": "text", "text": "Résumé du run (JSON) :\n" + json.dumps(context, ensure_ascii=False, sort_keys=True),
                    "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": question}],
    }
    try:
        import anthropic
        errors = (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.RateLimitError, anthropic.APIStatusError,
                  anthropic.APIConnectionError)
    except ImportError:                       # faux client des tests
        errors = ()
    try:
        response = client.beta.messages.create(**request)
    except errors as exc:
        raise QAUnavailable(_api_error_message(exc)) from exc
    except TypeError as exc:                  # le SDK ne trouve aucun identifiant : il le dit à l'envoi, par une TypeError
        if "authentication" not in str(exc).lower():
            raise
        raise QAUnavailable(NO_CREDENTIALS) from exc
    refused = getattr(response, "stop_reason", None) == "refusal"
    text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    if refused and not text:
        text = "Le modèle a refusé de répondre à cette question."
    usage = getattr(response, "usage", None)
    return {"answer": text, "model": getattr(response, "model", MODEL), "refused": refused, "leak": leak,
            "usage": {"input": getattr(usage, "input_tokens", None), "output": getattr(usage, "output_tokens", None),
                      "cache_read": getattr(usage, "cache_read_input_tokens", None)} if usage is not None else None}


def _api_error_message(exc: Exception) -> str:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "Clé API refusée : vérifier ANTHROPIC_API_KEY (ou relancer `ant auth login`)."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "La clé API n'a pas accès à ce modèle."
    if isinstance(exc, anthropic.RateLimitError):
        return "Limite de débit de l'API atteinte : réessayer dans une minute."
    if isinstance(exc, anthropic.APIConnectionError):
        return "API Claude injoignable (réseau)."
    status = getattr(exc, "status_code", None)
    return f"Erreur de l'API Claude ({status}) : réessayer plus tard." if status and status >= 500 else f"Requête refusée par l'API ({status})."
