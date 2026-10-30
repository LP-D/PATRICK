"""Mesure d'usage anonyme vers Amplitude (API HTTP v2) : un événement `app_started` au démarrage de l'interface web.

Inactif tant que `AMPLITUDE_API_KEY` est absente : aucune requête, aucun fichier écrit, l'application et les tests n'ont
besoin ni de clé ni de réseau. La clé vient de l'environnement (jamais du dépôt) ; `AMPLITUDE_REGION=eu` choisit le serveur
européen (défaut : `us`). Un événement ne porte que la version de PATRICK, le système, la version de Python et le point
d'entrée -- jamais un symbole, un chiffre financier, un chemin ni un nom de run.

L'identifiant d'appareil est un hasard (`uuid4`) gardé dans le dossier maison (`amplitude_device_id`), sans lien avec la
personne ni le PC. L'envoi part dans un fil d'arrière-plan avec un délai court et n'échoue jamais vers l'appelant : un
Amplitude injoignable ne doit pas ralentir ni casser le démarrage.
"""
from __future__ import annotations

import logging
import os
import platform
import threading
import time
import uuid

import requests

from patrick import __version__, paths

logger = logging.getLogger("patrick.amplitude")

ENV_API_KEY = "AMPLITUDE_API_KEY"
ENV_REGION = "AMPLITUDE_REGION"
ENDPOINTS = {
    "us": "https://api2.amplitude.com/2/httpapi",
    "eu": "https://api.eu.amplitude.com/2/httpapi",
}
TIMEOUT_S = 5
DEVICE_ID_FILE = "amplitude_device_id"


def api_key() -> str | None:
    return os.environ.get(ENV_API_KEY, "").strip() or None


def enabled() -> bool:
    return api_key() is not None


def endpoint() -> str:
    return ENDPOINTS.get(os.environ.get(ENV_REGION, "").strip().lower(), ENDPOINTS["us"])


def device_id() -> str:
    """Identifiant anonyme de cette installation, créé au premier envoi. Si le dossier maison est illisible, un
    identifiant jetable : l'événement part quand même."""
    path = paths.home_dir() / DEVICE_ID_FILE
    try:
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 5:
            return value
    except OSError:
        pass
    value = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


def build_event(event_type: str, properties: dict | None = None) -> dict:
    return {
        "device_id": device_id(),
        "event_type": event_type,
        "time": int(time.time() * 1000),
        "insert_id": uuid.uuid4().hex,
        "app_version": __version__,
        "os_name": platform.system(),
        "event_properties": dict(properties or {}),
    }


def send(event_type: str, properties: dict | None = None) -> tuple[bool, str]:
    """Envoie un événement tout de suite et rend (reçu, détail). Ne lève jamais."""
    key = api_key()
    if key is None:
        return False, f"{ENV_API_KEY} absente : envoi désactivé"
    body = {"api_key": key, "events": [build_event(event_type, properties)]}
    try:
        response = requests.post(endpoint(), json=body, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        logger.warning("Amplitude injoignable : %s", type(exc).__name__)
        return False, f"réseau : {type(exc).__name__}"
    if response.status_code != 200:
        logger.warning("Amplitude a refusé l'événement (HTTP %s)", response.status_code)
        return False, f"HTTP {response.status_code}"
    return True, "HTTP 200"


def track(event_type: str, properties: dict | None = None) -> None:
    """Comme `send`, mais sans attendre : fil d'arrière-plan, rien si la clé est absente."""
    if not enabled():
        return
    threading.Thread(target=send, args=(event_type, properties), daemon=True, name="amplitude").start()


def app_started_properties(entry_point: str) -> dict:
    return {"entry_point": entry_point, "python_version": platform.python_version()}


def track_app_started(entry_point: str) -> None:
    track("app_started", app_started_properties(entry_point))
