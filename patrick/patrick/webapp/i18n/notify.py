"""Chaînes FR/EN de la notification de fin de run (`static/run_notify.js`, bouton cloche de la barre supérieure). Livrées sur toutes les pages."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


NOTIFY_STRINGS: dict[str, dict[str, str]] = {
    "nt_toggle_on": _s("Notifications de fin de run activées (cliquer pour les couper)", "Run-end notifications on (click to turn off)"),
    "nt_toggle_off": _s("Prévenir à la fin d'un run (cliquer pour activer)", "Notify when a run ends (click to turn on)"),
    "nt_toggle_denied": _s("Notifications bloquées par le navigateur : seul le bandeau dans la page est affiché", "Notifications blocked by the browser: only the in-page banner is shown"),
    "nt_done": _s("Run terminé : {name}", "Run finished: {name}"),
    "nt_error": _s("Run en erreur : {name}", "Run failed: {name}"),
    "nt_body_done": _s("{kind} · le résultat est prêt.", "{kind} · the result is ready."),
    "nt_body_error": _s("{kind} · le run s'est arrêté sur une erreur.", "{kind} · the run stopped on an error."),
    "nt_more": _s("… et {n} autre(s) run(s) terminé(s).", "… and {n} more run(s) finished."),
    "nt_open": _s("Ouvrir", "Open"),
    "nt_close": _s("Fermer", "Close"),
    # Poste de lancement : versions et différences des profils enregistrés (app.js)
    "profile_diff_count": _s("réglage(s) diffèrent :", "setting(s) differ:"),
    "profile_diff_more": _s(" …", " …"),
    "profile_diff_none": _s("Aucun réglage modifié.", "No setting changed."),
    "nt_test": _s("Notifications activées : vous serez prévenu à la fin de chaque run.", "Notifications on: you will be told when each run ends."),
}
