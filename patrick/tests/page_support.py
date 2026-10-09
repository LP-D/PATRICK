"""Les pages lourdes (synthèse, prédictions) n'envoient que leur cadre : leurs tableaux arrivent par des fragments HTML
(`data-lazy-url`, `static/lazy.js`). Ce client de test fait ce que fait le navigateur : un GET d'une page renvoie la page PLUS
ses fragments, de sorte que les tests lisent ce que l'utilisateur voit."""
from __future__ import annotations

import html
import re

from fastapi.testclient import TestClient

_LAZY = re.compile(r'data-lazy-url="([^"]+)"')


class FullPageClient(TestClient):
    def get(self, url, *args, **kwargs):
        response = super().get(url, *args, **kwargs)
        if response.status_code == 200 and "text/html" in response.headers.get("content-type", ""):
            extra = b"".join(super(FullPageClient, self).get(html.unescape(u)).content for u in _LAZY.findall(response.text))
            if extra:
                response._content = response.content + extra
                response.__dict__.pop("_text", None)
        return response
