"""Point 17 : tickers et données de marché/macro Yahoo ajoutés le 2026-10-09 (univers étendu, opt-in)."""
from __future__ import annotations

from patrick.config import asset_classes
from patrick.config import universe_extension as UX
from patrick.data.session_calendar import classify_asset_class
from patrick.webapp import forms
from patrick.webapp.i18n import TARGET_GROUP_LABEL_KEYS


def test_every_added_symbol_is_a_selectable_target_and_has_a_unique_label():
    symbols = set(UX.ADDED_ON_2026_10_09)
    assert len(symbols) == len(UX.ADDED_ON_2026_10_09) > 40
    assert symbols <= set(forms.TARGET_SOURCE_BY_SYMBOL)
    labels = [label for items in UX.EXTENDED_TARGET_GROUPS.values() for _s, label, _f in items]
    assert len(labels) == len(set(labels)), "deux symboles ne peuvent pas partager un libellé (colonne de features)"


def test_added_groups_belong_to_a_page_and_have_a_translated_name():
    for group in UX.EXTENDED_TARGET_GROUPS:
        assert asset_classes.class_of_group(group), group
        assert group in TARGET_GROUP_LABEL_KEYS, group


def test_volatility_and_tail_risk_indices_are_classified_for_the_session_lag():
    """Un indice mal classé tomberait dans « other » : décalage de séance conservateur mais faux pour un indice américain."""
    for symbol in ("^MOVE", "^SKEW", "^VIX9D", "^VXD"):
        assert classify_asset_class(symbol) == "volatility_index", symbol
    for symbol in ("^SOX", "^DJT", "^NYA", "GLD", "UUP"):
        assert classify_asset_class(symbol) == "equities_us", symbol
    for symbol in ("^AEX", "^SSMI"):
        assert classify_asset_class(symbol) == "equities_europe", symbol


def test_new_feature_candidates_are_part_of_the_extended_universe():
    targets = {sym for items in UX.EXTENDED_TARGET_GROUPS.values() for sym, _l, _f in items}
    assert {"^MOVE", "^SKEW", "^VIX9D", "^SOX", "DBC", "GLD", "UUP"} <= set(UX.EXTENDED_FEATURE_CANDIDATES)
    assert set(UX.EXTENDED_FEATURE_CANDIDATES) <= targets
