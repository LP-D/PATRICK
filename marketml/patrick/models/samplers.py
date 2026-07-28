"""Registre des samplers — défaut SMOTE seul (grille des 5 variantes disponible en
option, cf. VIX_FINAL_ML_SCAN).

Phase 5.3 (hygiène) : `sampler.candidates` accepte aussi le sentinel
`"none"` (pas de rééchantillonnage) pour permettre l'A/B test SMOTE-seul vs
`class_weight` (+calibration, cf. `models/calibration.py`) demandé par le
plan -- RandomForest/LightGBM/CatBoost ont déjà `class_weight="balanced"`/
`auto_class_weights="Balanced"` câblé en dur dans `models/registry.py`
indépendamment du sampler choisi ; ajouter `"none"` à `sampler.candidates`
dans un YAML de run le fait apparaître comme une config de plus dans le
scan/leaderboard existant, comparable aux configs SMOTE via les mêmes
métriques et le même test Diebold-Mariano -- pas besoin d'un script d'A/B
test séparé. `"none"` est géré directement par `pipeline/engine.py::
_fit_eval` (avant tout appel à `get_sampler`), volontairement PAS ajouté à
`ALL_SAMPLERS`/au registre ci-dessous : ce n'est pas un vrai sampler
instanciable, juste un indicateur "sauter cette étape" reconnu par
l'appelant. Comparaison réelle sur 5 cibles PAS ENCORE FAITE dans cette
session (pas d'accès réseau en sandbox) -- cf. rapport de phase /
METHODOLOGY.md ; le défaut (`SMOTE` seul) n'a donc pas été changé."""
from __future__ import annotations

from imblearn.combine import SMOTEENN, SMOTETomek
from imblearn.over_sampling import ADASYN, SMOTE, BorderlineSMOTE

ALL_SAMPLERS = ("SMOTE", "BorderlineSMOTE", "ADASYN", "SMOTETomek", "SMOTEENN")


def get_sampler(name: str, seed: int = 42):
    registry = {
        "SMOTE": SMOTE(random_state=seed),
        "BorderlineSMOTE": BorderlineSMOTE(random_state=seed, kind="borderline-1"),
        "ADASYN": ADASYN(random_state=seed),
        "SMOTETomek": SMOTETomek(random_state=seed),
        "SMOTEENN": SMOTEENN(random_state=seed),
    }
    if name not in registry:
        raise ValueError(f"Sampler inconnu: '{name}' (attendu: {ALL_SAMPLERS})")
    return registry[name]
