"""Tout bloc repliable (`<details>`) s'affiche fermé au chargement : on l'ouvre en cliquant sur sa flèche.

Seule exception, voulue : « Plus de filtres » de /runs, qui s'ouvre quand l'un de SES filtres est actif (sinon un filtre
appliqué serait caché derrière une flèche fermée)."""
from __future__ import annotations

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "templates"
ALLOWED = {("runs.html", "filter-more")}


def test_no_template_opens_a_details_block_by_default():
    offenders = []
    for path in sorted(TEMPLATES.glob("*.html")):
        for tag in re.findall(r"<details\b[^>]*>", path.read_text(encoding="utf-8")):
            if re.search(r"\bopen\b", re.sub(r'"[^"]*"', '""', tag)):   # `open` hors valeurs d'attributs, Jinja compris
                cls = re.search(r'class="([^"]*)"', tag)
                if (path.name, (cls.group(1).split()[-1] if cls else "")) not in ALLOWED:
                    offenders.append(f"{path.name}: {tag}")
    assert not offenders, "blocs repliables ouverts par défaut :\n" + "\n".join(offenders)
