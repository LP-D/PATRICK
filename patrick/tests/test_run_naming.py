"""Règle de nommage des runs (spec `docs/superpowers/specs/
2026-08-02-batch-run-launch-design.md` §2) : nom = slug(target) + numéro de
séquence, toujours -- jamais de saisie libre."""
from __future__ import annotations

from patrick.webapp import forms


def test_slug_target_strips_leading_caret():
    assert forms.slug_target("^VIX") == "VIX"


def test_slug_target_replaces_equals():
    assert forms.slug_target("EURUSD=X") == "EURUSD_X"


def test_slug_target_replaces_dot():
    assert forms.slug_target("000001.SS") == "000001_SS"


def test_slug_target_collapses_adjacent_separators():
    assert forms.slug_target("AB==CD") == "AB_CD"


def test_slug_target_leaves_plain_ticker_unchanged():
    assert forms.slug_target("AAPL") == "AAPL"
