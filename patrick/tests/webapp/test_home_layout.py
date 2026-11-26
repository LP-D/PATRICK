"""Synthèse personnalisable (VI26 du 26/11) : chaque bloc est repérable et le script de mise en page est servi."""
from __future__ import annotations

import re

from fastapi.testclient import TestClient

from patrick.webapp.app import app


def test_home_blocks_are_tagged_and_script_is_served():
    client = TestClient(app)
    html = client.get("/").text
    blocks = re.findall(r'data-home-block="([a-z]+)"', html)
    assert blocks == ["trio", "classes", "signal", "detail", "regime"]
    assert 'id="home-customize"' in html and 'id="home-layout"' in html
    assert "Personnaliser" in html and 'data-label-hide="Masquer"' in html
    src = re.search(r'src="([^"]*home_layout\.js[^"]*)"', html).group(1)
    js = client.get(src)
    assert js.status_code == 200 and "patrick-home-layout" in js.text
