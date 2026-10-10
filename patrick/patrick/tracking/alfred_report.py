"""Rapport FRED contre ALFRED de la page Macro : pour chaque série du pool, ce que change l'usage de la première publication
(`data/alfred.py`) à la place de la version révisée d'aujourd'hui.

Le calcul interroge l'API (2 à 5 requêtes par série, ~100 séries) : il tourne dans un fil d'arrière-plan lancé par un bouton,
écrit son résultat dans le cache local et la page lit ce cache -- aucun appel réseau au chargement de la page.
"""
from __future__ import annotations

import os
import threading
import time

from patrick.cache_manager import LocalCache
from patrick.clock import utc_now
from patrick.config import defaults as D
from patrick.data import alfred

CACHE_KEY = "alfred_vs_fred_report"
_lock = threading.Lock()
_state: dict = {"running": False, "done": 0, "total": 0, "error": None, "started_at": None}


def series_to_compare() -> list[tuple[str, str, str]]:
    """`(id FRED, libellé, rubrique)` de toutes les séries de la page Macro, dans l'ordre d'affichage."""
    return [(sid, label, section) for section, series in D.macro_page_sections() for sid, label in series]


_ROW_FIELDS = ("level_break", "first_vintage", "first_obs", "lost_years_if_alfred_only", "share_revised", "mean_abs_revision",
               "max_abs_revision", "revision_vs_move", "lag_real_days", "lag_assumed_days", "note")


def load_report() -> dict | None:
    """Rapport du cache local (lignes complétées : une série absente d'ALFRED n'a ni révisions ni délais)."""
    payload = LocalCache().load_json(CACHE_KEY, max_age_days=3650)
    if not payload:
        return None
    for row in payload.get("rows", []):
        for key in _ROW_FIELDS:
            row.setdefault(key, None)
        row.setdefault("n_compared", 0)
    return payload


def status() -> dict:
    with _lock:
        return dict(_state)


def api_key_available() -> bool:
    return bool(os.environ.get(alfred.API_KEY_ENV))


def summarize(rows: list[dict]) -> dict:
    """Chiffres d'en-tête : combien de séries sont révisées, hybrides ou absentes d'ALFRED, les plus révisées."""
    modes = {"alfred": 0, "hybrid": 0, "fred": 0}
    for r in rows:
        modes[r.get("mode", "fred")] = modes.get(r.get("mode", "fred"), 0) + 1
    revised = [r for r in rows if r.get("n_compared") and (r.get("share_revised") or 0) > 0.05]
    top = sorted((r for r in rows if r.get("revision_vs_move") is not None), key=lambda r: -r["revision_vs_move"])[:5]
    rebased = [r for r in rows if r.get("level_break")]
    return {"n": len(rows), "modes": modes, "n_revised": len(revised), "n_rebased": len(rebased),
            "most_revised": [{"series": r["series"], "label": r.get("label"), "ratio": r["revision_vs_move"]} for r in top]}


def compute_report(*, refresh: bool = False, pause_s: float = 0.4, progress=None) -> dict:
    """Calcule le rapport complet et l'écrit dans le cache. `progress(done, total)` est appelé après chaque série."""
    key = os.environ.get(alfred.API_KEY_ENV)
    if not key:
        raise RuntimeError(f"{alfred.API_KEY_ENV} absente : ALFRED est inaccessible.")
    todo = series_to_compare()
    rows: list[dict] = []
    for i, (sid, label, section) in enumerate(todo, 1):
        try:
            row = alfred.compare_with_fred(sid, "2000-01-01", key, refresh=refresh)
        except Exception as exc:  # noqa: BLE001 -- une série en panne n'arrête pas le rapport
            row = {"series": sid, "mode": "fred", "n_compared": 0, "note": f"erreur : {str(exc)[:80]}"}
        rows.append({**row, "label": label, "section": section})
        if progress:
            progress(i, len(todo))
        time.sleep(pause_s)
    payload = {"computed_at": utc_now().isoformat(timespec="seconds"), "start": "2000-01-01", "rows": rows,
               "summary": summarize(rows)}
    LocalCache().save_json(CACHE_KEY, payload)
    return payload


def start_background(*, refresh: bool = False) -> bool:
    """Lance le calcul dans un fil (un seul à la fois). `False` s'il en tourne déjà un ou si la clé manque."""
    if not api_key_available():
        return False
    with _lock:
        if _state["running"]:
            return False
        _state.update(running=True, done=0, total=len(series_to_compare()), error=None, started_at=utc_now().isoformat())

    def work() -> None:
        def tick(done: int, total: int) -> None:
            with _lock:
                _state.update(done=done, total=total)

        try:
            compute_report(refresh=refresh, progress=tick)
        except Exception as exc:  # noqa: BLE001 -- l'état d'erreur est lu par la page
            with _lock:
                _state["error"] = str(exc)[:200]
        finally:
            with _lock:
                _state["running"] = False

    threading.Thread(target=work, name="alfred-report", daemon=True).start()
    return True
