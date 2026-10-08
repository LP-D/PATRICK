"""Préférences de l'application de bureau (`~/.patrick/settings.json`, même fichier que les réglages machine).

Bibliothèque standard uniquement : le lanceur les lit avant tout le reste. Chaque préférence a un défaut, un
type et une validation ; `update()` refuse en bloc une valeur invalide (rien n'est écrit à moitié).
"""
from __future__ import annotations

from patrick import settings

KEY_SETUP_DONE = "setup_done"          # l'assistant de premier démarrage a été traité (dossier choisi ou « aucun »)
KEY_AUTO_UPDATE = "auto_update"        # chercher une nouvelle version au démarrage
KEY_SYNC_ON_START = "sync_on_start"    # fusionner le partage avant d'ouvrir PATRICK
KEY_SYNC_ON_CLOSE = "sync_on_close"    # publier ce PC à la fermeture
KEY_APP_WINDOW = "app_window"          # fenêtre dédiée (Chrome/Edge « mode app ») plutôt que le navigateur par défaut
KEY_PORT = "port"                      # port local du serveur

DEFAULT_PORT = 8000
MIN_PORT, MAX_PORT = 1024, 65535

DEFAULTS: dict[str, bool | int] = {
    KEY_AUTO_UPDATE: True,
    KEY_SYNC_ON_START: True,
    KEY_SYNC_ON_CLOSE: True,
    KEY_APP_WINDOW: True,
    KEY_PORT: DEFAULT_PORT,
}
BOOL_KEYS = (KEY_AUTO_UPDATE, KEY_SYNC_ON_START, KEY_SYNC_ON_CLOSE, KEY_APP_WINDOW)


class PrefError(ValueError):
    """Valeur de préférence invalide (message destiné à l'utilisateur)."""


def _as_bool(value: object, key: str) -> bool:
    if isinstance(value, bool):
        return value
    raise PrefError(f"« {key} » doit être vrai ou faux.")


def _as_port(value: object) -> int:
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise PrefError("Le port doit être un nombre entier.") from exc
    if isinstance(value, bool) or not MIN_PORT <= port <= MAX_PORT:
        raise PrefError(f"Le port doit être compris entre {MIN_PORT} et {MAX_PORT}.")
    return port


def get_bool(key: str) -> bool:
    value = settings.load().get(key, DEFAULTS[key])
    return value if isinstance(value, bool) else bool(DEFAULTS[key])


def get_port() -> int:
    try:
        return _as_port(settings.load().get(KEY_PORT, DEFAULT_PORT))
    except PrefError:
        return DEFAULT_PORT


def setup_done() -> bool:
    return settings.load().get(KEY_SETUP_DONE) is True


def mark_setup_done() -> None:
    settings.save({KEY_SETUP_DONE: True})


def all_prefs() -> dict[str, bool | int]:
    """Les préférences effectives (valeurs enregistrées, sinon défauts)."""
    return {**{k: get_bool(k) for k in BOOL_KEYS}, KEY_PORT: get_port()}


def update(changes: dict) -> dict[str, bool | int]:
    """Valide puis enregistre `changes` (clés inconnues refusées). Renvoie les préférences effectives."""
    clean: dict[str, bool | int] = {}
    for key, value in changes.items():
        if key in BOOL_KEYS:
            clean[key] = _as_bool(value, key)
        elif key == KEY_PORT:
            clean[key] = _as_port(value)
        else:
            raise PrefError(f"Préférence inconnue : {key}.")
    if clean:
        settings.save(clean)
    return all_prefs()
