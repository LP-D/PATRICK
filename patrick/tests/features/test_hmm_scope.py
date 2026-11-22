"""Décision du 2026-09-26 : le HMM sert uniquement aux modèles de régime et à
l'analyse de l'état du marché, plus comme feature des modèles ML.

Mesure qui l'a motivée (`docs/audits/audit-vitesse-2026-09-25.md`) : sur le
run réel ^GSPC, la feature `*_hmm_filtered_stress_prob` représentait 64 % du
temps de construction des features pour zéro feature retenue par les modèles
exportés.

- plus dans les modèles de volatilité par défaut ni proposés au lancement ;
- toujours calculable quand une configuration existante le demande
  explicitement : `predict`/`explain` reconstruisent le pool d'un modèle déjà
  exporté à partir de sa configuration enregistrée ;
- la détection de régime (`features/regime_detection.py`) reste intacte.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from patrick.config import defaults as D
from patrick.config.schema import RunConfig
from patrick.features import regime_detection, vol_models
from patrick.webapp import forms


def test_hmm_is_no_longer_a_default_or_selectable_feature():
    assert "hmm" not in D.DEFAULT_VOL_MODELS
    assert "hmm" not in D.ALL_VOL_MODELS
    assert "hmm" not in forms.ALL_VOL_MODELS
    config = RunConfig.model_validate({"objective": {"target_symbol": "^GSPC"}})
    assert "hmm" not in config.features.vol_models


def test_a_stored_config_that_asked_for_hmm_still_rebuilds_its_column():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2015-01-01", periods=400)
    s = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400))), index=idx)
    out = vol_models.build_vol_model_features_parametric(s, prefix="X", models=["hmm"], fit_end_idx=300)
    assert "X_hmm_filtered_stress_prob" in out.columns
    assert out["X_hmm_filtered_stress_prob"].iloc[320:].notna().all()


def test_regime_detection_still_uses_its_own_hmm():
    rng = np.random.default_rng(1)
    calm = rng.normal(0, 0.005, 400)
    stress = rng.normal(0, 0.03, 200)
    idx = pd.bdate_range("2015-01-01", periods=600)
    s = pd.Series(100 * np.exp(np.cumsum(np.r_[calm, stress])), index=idx)
    res = regime_detection.detect_regime(s, n_states=2, fit_end_idx=450)
    assert res.stress_prob.iloc[-50:].mean() > res.stress_prob.iloc[100:350].mean()
