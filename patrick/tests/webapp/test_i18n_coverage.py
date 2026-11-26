"""Couverture anglaise des libellés de l'interface (AM24 du 25/11) : mesurée à 100 % le 25/11 (6 042 clés), ce test la garde."""
from __future__ import annotations

from patrick.webapp.i18n import core

ACCENTS = "éèàçêûîôù"


def test_every_label_has_an_english_text():
    missing = sorted(k for k, v in core.STRINGS.items() if not isinstance(v, dict) or not (v.get("en") or "").strip())
    assert missing == [], f"libellés sans anglais : {missing[:20]}"


def test_no_english_text_is_a_copy_of_an_accented_french_one():
    copied = sorted(k for k, v in core.STRINGS.items()
                    if isinstance(v, dict) and v.get("fr") == v.get("en") and any(c in (v.get("fr") or "") for c in ACCENTS))
    assert copied == [], f"anglais recopié du français : {copied[:20]}"
