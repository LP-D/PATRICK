"""Chaque `<input type="number">` de `/launch` doit être valide avec sa valeur
par défaut au sens HTML5 (valeur = min + k × step). Sinon le navigateur
bloque la soumission du formulaire sans rien afficher d'explicite : les seuils
de régime 1/3 et 2/3 avec `step="0.01"` rendaient `/launch` impossible à
soumettre tel quel. Rend le vrai gabarit Jinja via TestClient, base vide."""
from __future__ import annotations

import re
from decimal import Decimal

from fastapi.testclient import TestClient

from patrick.tracking import db
from patrick.webapp.app import app

_INPUT_RE = re.compile(r"<input\b[^>]*>", re.IGNORECASE)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return m.group(1) if m else None


def test_every_number_input_default_satisfies_its_step(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    resp = TestClient(app).get("/ml")
    assert resp.status_code == 200

    invalid = []
    checked = 0
    for tag in _INPUT_RE.findall(resp.text):
        if _attr(tag, "type") != "number":
            continue
        value, step = _attr(tag, "value"), _attr(tag, "step") or "1"
        if not value or step == "any":
            continue
        base = Decimal(_attr(tag, "min") or "0")
        if (Decimal(value) - base) % Decimal(step) != 0:
            invalid.append(f'{_attr(tag, "name")}={value} (step={step}, min={base})')
        checked += 1

    assert checked > 0
    assert not invalid, "défauts invalides pour le navigateur : " + ", ".join(invalid)
