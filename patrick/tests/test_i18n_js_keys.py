"""Les scripts ne lisent leurs textes que dans `window.I18N` (clés exposées par `i18n.js_strings`) : une clé demandée mais jamais exposée
laisserait s'afficher son texte de repli (souvent du français) dans l'autre langue, sans aucune erreur."""
from __future__ import annotations

import re
from pathlib import Path

from patrick.webapp import i18n
from patrick.webapp.i18n import STRINGS
from patrick.webapp.i18n_models import PAGE_JS_KEYS

STATIC = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "static"
_USES = [
    re.compile(r"""\b(?:tr|T|_tr)\(\s*["']([a-z][a-z0-9_]*)["']"""),
    re.compile(r"""\bI18N\.([a-z][a-z0-9_]*)\b"""),
    re.compile(r"""\bI18N\[\s*["']([a-z][a-z0-9_]*)["']\s*\]"""),
]
# Scripts qui n'ont pas leur propre fonction de traduction : ne regarder que les motifs ci-dessus.
_DYNAMIC_PREFIXES = ("phase_", "status_", "queue_", "run_", "preview_", "news_", "gate_", "confirm_line_", "artifact_")


# Pages dont `js_strings` ajoute des clés propres (analyses, actualités…) : on réunit ce que chacune expose.
_PATHS = ("/", "/news", "/analyses", "/garde-fous", "/variables", "/derive", "/modeles", "/journal", "/carnet", "/diagnostics", "/risque",
          "/donnees", "/runs/x/analyse")


def _exposed() -> set[str]:
    keys: set[str] = set()
    for path in _PATHS:
        keys.update(i18n.js_strings("fr", path))
    for path_keys in PAGE_JS_KEYS.values():
        keys.update(path_keys)
    return keys


def test_every_key_read_by_a_script_is_exposed_to_the_browser():
    exposed = _exposed()
    missing: dict[str, set[str]] = {}
    for script in sorted(STATIC.glob("*.js")):
        source = script.read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/|//[^\n]*", "", source, flags=re.DOTALL)
        for pattern in _USES:
            for key in pattern.findall(source):
                if key not in STRINGS:
                    continue                         # pas une clé de traduction (variable locale, propriété d'objet…)
                if key not in exposed:
                    missing.setdefault(script.name, set()).add(key)
    assert not missing, "clés lues par un script mais absentes de i18n.js_strings : " + "; ".join(f"{k}: {sorted(v)}" for k, v in missing.items())
