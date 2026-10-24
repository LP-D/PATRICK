"""Traduction des messages produits côté serveur (`webapp/i18n_server.py`), gestionnaire d'erreurs HTTP traduit, macros qui suivent la
langue de la requête, et deux garde-fous de l'audit d'interface : aucun lien mort vers une page de cible, aucune erreur 500 sur la
configuration d'un ancien run."""
from __future__ import annotations

import json
import re

import pytest
from page_support import FullPageClient as TestClient

from patrick.features import guida
from patrick.tracking import db
from patrick.validation import pbo_reliability
from patrick.webapp import forms
from patrick.webapp.app import app
from patrick.webapp.i18n_server import translate

_FRENCH_LETTERS = re.compile(r"[àâçéèêëîïôùûœ]")


def test_french_is_never_modified():
    assert translate("Run introuvable", "fr") == "Run introuvable"
    assert translate("n'importe quoi", "en") == "n'importe quoi"      # message inconnu : inchangé, jamais perdu


@pytest.mark.parametrize("fr, expected", [
    ("Run introuvable (ni en mémoire, ni en base)", "Run not found."),
    ("Cible inconnue", "Unknown target."),
    ("Hausse forte", "Strong up"),
    ("Baisse faible", "Slight down"),
    ("« Embargo (barres) » : valeur entière invalide.", "“Embargo (bars)”: invalid integer value."),
    ("« Folds CV » doit être un entier >= 2.", "“CV folds” must be an integer >= 2."),
    ("« Horizons » : Historique insuffisant pour AAPL : 12j disponibles, 100j requis pour un horizon de 5j.",
     "“Horizons”: Insufficient history for AAPL: 12d available, 100d required for a 5d horizon."),
    ("aucune P(hausse) enregistrée (run antérieur à la migration 0024)", "no P(up) recorded (run predates migration 0024)"),
    ("Versement", "Deposit"),
    ("PyTorch n'est pas installé : les réseaux de neurones sont indisponibles. Installe-le avec : pip install -e \".[deep]\" (ou pip install torch).",
     "PyTorch is not installed: neural networks are unavailable. Install it with: pip install -e \".[deep]\" (or pip install torch)."),
])
def test_known_messages(fr, expected):
    assert translate(fr, "en") == expected


def test_producer_messages_are_fully_translated():
    """Des messages réels, tels que les modules de domaine les fabriquent : plus une lettre accentuée une fois en anglais."""
    samples = [pbo_reliability.required_blocks_reason(), f"PBO non calculé (2 blocs disponibles). {pbo_reliability.required_blocks_reason()}",
               *guida.EQUITY_FEATURE_EXCLUSIONS.values()]
    for fr in samples:
        en = translate(fr, "en")
        assert en != fr, fr
        assert not _FRENCH_LETTERS.search(en), en


def test_form_field_labels_are_translated_from_the_catalog():
    en = translate("« Top-K configs affinées » doit être un entier strictement positif.", "en")
    assert "Top-K refined configs" in en and "strictement" not in en


def test_http_errors_follow_the_visitor_language(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    fr = client.get("/runs/absent/panel")
    assert fr.status_code == 404 and fr.json()["detail"] == "Run introuvable"
    client.cookies.set("patrick_lang", "en")
    en = client.get("/runs/absent/panel")
    assert en.status_code == 404 and en.json()["detail"] == "Run not found."


def test_shared_macro_defaults_follow_the_page_language(tmp_path, monkeypatch):
    """`data_table` vit dans un module importé sans contexte : son message par défaut doit quand même suivre la langue."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    client = TestClient(app)
    client.cookies.set("patrick_lang", "en")
    page = client.get("/analysis")
    assert page.status_code == 200
    assert "Aucune donnée." not in page.text


def test_data_freshness_links_only_existing_target_pages(tmp_path, monkeypatch):
    """Les séries macro (FRED) figurent dans le tableau mais n'ont pas de page de cible : pas de lien vers un 404."""
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    db.connect(str(tmp_path / "patrick.db")).close()
    page = TestClient(app).get("/universe").text
    linked = set(re.findall(r'href="/targets/([^"]+)"', page))
    assert linked, "les cibles réelles doivent rester cliquables"
    assert not [s for s in linked if s not in forms.TARGET_SOURCE_BY_SYMBOL]


def test_unreadable_run_config_is_a_clear_conflict_not_a_server_error(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    conn = db.connect(str(tmp_path / "patrick.db"))
    db.upsert_snapshot(conn, "snap1", "hash1", None, None, None)
    db.create_run(conn, "old1", "^VIX", 5, "snap1", json.dumps({"name": "ancien"}), "cfghash", "sha", 42)
    conn.close()
    resp = TestClient(app).get("/ml?run_id=old1")
    assert resp.status_code == 409
    assert "illisible" in resp.json()["detail"]
