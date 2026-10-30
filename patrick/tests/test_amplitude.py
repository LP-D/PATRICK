"""`patrick/amplitude.py` : inerte sans clé, événement anonyme et bien formé avec, jamais d'exception vers l'appelant.
Aucun test ne touche le réseau : `requests.post` est remplacé."""
from __future__ import annotations

import threading

import pytest
import requests
from typer.testing import CliRunner

from patrick import __version__, amplitude
from patrick.cli import app


class _Reponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code


@pytest.fixture
def appels(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "home" / "patrick.db"))
    recus: list[dict] = []

    def faux_post(url, json=None, timeout=None):
        recus.append({"url": url, "json": json, "timeout": timeout})
        return _Reponse(200)

    monkeypatch.setattr(amplitude.requests, "post", faux_post)
    return recus


def test_sans_cle_rien_ne_part_et_aucun_fichier_n_est_ecrit(appels, tmp_path):
    amplitude.track_app_started("web")
    ok, detail = amplitude.send("app_started")
    assert not amplitude.enabled()
    assert not ok
    assert "AMPLITUDE_API_KEY" in detail
    assert appels == []
    assert not (tmp_path / "home").exists()


def test_evenement_de_demarrage_anonyme_et_bien_forme(appels, monkeypatch):
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    ok, _ = amplitude.send("app_started", amplitude.app_started_properties("web"))
    assert ok
    (appel,) = appels
    assert appel["url"] == "https://api2.amplitude.com/2/httpapi"
    assert appel["timeout"] == amplitude.TIMEOUT_S
    assert appel["json"]["api_key"] == "cle-de-test"
    (evenement,) = appel["json"]["events"]
    assert evenement["event_type"] == "app_started"
    assert evenement["app_version"] == __version__
    assert len(evenement["device_id"]) >= 5
    assert evenement["insert_id"]
    assert set(evenement["event_properties"]) == {"entry_point", "python_version"}
    assert "user_id" not in evenement


def test_region_europe(appels, monkeypatch):
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    monkeypatch.setenv("AMPLITUDE_REGION", "EU")
    amplitude.send("app_started")
    assert appels[0]["url"] == "https://api.eu.amplitude.com/2/httpapi"


def test_identifiant_d_appareil_stable_d_un_envoi_a_l_autre(appels, monkeypatch):
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    amplitude.send("app_started")
    amplitude.send("app_started")
    premier, second = (a["json"]["events"][0] for a in appels)
    assert premier["device_id"] == second["device_id"]
    assert premier["insert_id"] != second["insert_id"]


def test_reponse_refusee_ou_reseau_coupe_ne_leve_pas(monkeypatch, tmp_path):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "home" / "patrick.db"))
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    monkeypatch.setattr(amplitude.requests, "post", lambda *a, **k: _Reponse(400))
    assert amplitude.send("app_started") == (False, "HTTP 400")

    def coupe(*a, **k):
        raise requests.ConnectionError("pas de réseau")

    monkeypatch.setattr(amplitude.requests, "post", coupe)
    assert amplitude.send("app_started") == (False, "réseau : ConnectionError")


def test_track_envoie_en_arriere_plan(appels, monkeypatch):
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    amplitude.track_app_started("web")
    for fil in threading.enumerate():
        if fil.name == "amplitude":
            fil.join(timeout=5)
    assert len(appels) == 1
    assert appels[0]["json"]["events"][0]["event_properties"]["entry_point"] == "web"


def test_commande_cli_sans_cle_sort_en_erreur(appels):
    resultat = CliRunner().invoke(app, ["amplitude-test"])
    assert resultat.exit_code == 1
    assert "AMPLITUDE_API_KEY" in resultat.output
    assert appels == []


def test_commande_cli_avec_cle_affiche_la_reponse_sans_la_cle(appels, monkeypatch):
    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-secrete-de-test")
    resultat = CliRunner().invoke(app, ["amplitude-test"])
    assert resultat.exit_code == 0
    assert "événement reçu" in resultat.output
    assert "cle-secrete-de-test" not in resultat.output
    assert appels[0]["json"]["events"][0]["event_properties"]["entry_point"] == "cli_test"


def test_le_demarrage_de_l_app_web_declenche_l_evenement(appels, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from patrick.webapp.app import app as web_app

    monkeypatch.setenv("AMPLITUDE_API_KEY", "cle-de-test")
    monkeypatch.setenv("PATRICK_BACKGROUND_DELAY_S", "3600")
    with TestClient(web_app):
        for fil in threading.enumerate():
            if fil.name == "amplitude":
                fil.join(timeout=5)
    points = [a["json"]["events"][0]["event_properties"]["entry_point"] for a in appels]
    assert points == ["web"]
