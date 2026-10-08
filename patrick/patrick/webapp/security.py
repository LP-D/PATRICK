"""Garde des requêtes HTTP : le serveur PATRICK est local, rien d'autre qu'une page PATRICK ne doit pouvoir le piloter.

Le serveur n'écoute que sur 127.0.0.1, mais une page web quelconque ouverte dans le navigateur de l'utilisateur
peut tout de même lui envoyer des requêtes :
- CSRF : un formulaire ou un `fetch` en « requête simple » (Content-Type text/plain, sans préliminaire CORS)
  suffit à créer un compte, passer un ordre ou lancer un run ;
- « DNS rebinding » : un nom de domaine du site hostile qui se met à pointer vers 127.0.0.1 permet de LIRE les
  réponses (patrimoine inclus).

Règles (middleware ASGI `LocalGuardMiddleware`, appliqué à TOUTES les routes, présentes et futures) :
1. l'en-tête `Host` doit désigner la machine (127.0.0.1, localhost, [::1], plus `PATRICK_EXTRA_HOSTS`) — toutes méthodes;
2. pour les méthodes qui écrivent (tout sauf GET/HEAD/OPTIONS) et pour l'API JSON (`/api/`), `Origin` ne doit pas
   être un autre site (ni `null`) et `Sec-Fetch-Site` doit valoir `same-origin` ou `none`.
Les clients qui n'envoient pas ces en-têtes (curl, scripts Python) passent : seuls les navigateurs les ajoutent, et ce
sont eux qu'il faut empêcher d'être utilisés par un autre site. Une navigation GET depuis un autre site (un lien) reste
possible : elle ne modifie rien et n'expose rien à la page appelante.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]"})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
ENV_EXTRA_HOSTS = "PATRICK_EXTRA_HOSTS"        # noms d'hôte supplémentaires, séparés par des virgules


def allowed_hosts() -> frozenset[str]:
    extra = {h.strip().lower() for h in os.environ.get(ENV_EXTRA_HOSTS, "").split(",") if h.strip()}
    return LOCAL_HOSTS | extra


def _hostname(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):                      # IPv6 : « [::1]:8000 »
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def check(method: str, path: str, headers: dict[str, str]) -> str | None:
    """Motif de refus (message pour l'utilisateur), ou None si la requête est acceptée. `headers` : clés en minuscules."""
    host = headers.get("host", "")
    if _hostname(host) not in allowed_hosts():
        return "Hôte non autorisé."
    if method.upper() in SAFE_METHODS and not path.startswith("/api/"):
        return None
    origin = headers.get("origin")
    if origin is not None and (origin == "null" or urlparse(origin).netloc.lower() != host.strip().lower()):
        return "Requête d'un autre site refusée."
    if headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
        return "Requête d'un autre site refusée."
    return None


class LocalGuardMiddleware:
    """Middleware ASGI pur (pas de `BaseHTTPMiddleware` : il ne doit jamais bufferiser une réponse)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            problem = check(scope["method"], scope["path"], headers)
            if problem:
                await JSONResponse({"detail": problem, "error": problem}, status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)
