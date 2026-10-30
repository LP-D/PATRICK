"""Un run n'enregistre pas son profil d'entraînement : il se déduit de ses réglages (badge de la page d'un run)."""
from __future__ import annotations

import pytest

from patrick.config import training_profiles as tp
from patrick.webapp import forms


@pytest.fixture(scope="module")
def default_view() -> dict:
    return forms.to_view(forms.default_config_dict("ml"))


@pytest.mark.parametrize("key", [p.key for p in tp.PROFILES])
def test_every_shipped_profile_recognises_itself(key, default_view):
    view = tp.apply_patch(default_view, tp.get(key).resolved_patch())
    assert tp.identify(view, default_view) == key


def test_a_customised_run_is_not_given_a_profile(default_view):
    custom = {**default_view, "algos": ["RandomForest"], "n_wf_folds": 5}
    assert tp.identify(custom, default_view) is None


def test_the_most_specific_profile_wins(default_view):
    # `quick` change sept réglages, `regimes` un seul : une config qui satisfait les deux est un `quick`
    view = tp.apply_patch(default_view, {**tp.get("quick").resolved_patch(), **tp.get("regimes").resolved_patch()})
    assert tp.identify(view, default_view) == "quick"
