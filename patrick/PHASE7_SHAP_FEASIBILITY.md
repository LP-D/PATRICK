# Phase 7 — Faisabilité SHAP par prédiction individuelle

Constat de faisabilité (feature/shap-waterfall) : **implémenté**, coût jugé
acceptable pour un affichage à la demande. Ce document consigne les chiffres
réels mesurés, référencés depuis `patrick/explain.py` et `tests/test_explain.py`.

## Où les valeurs SHAP existaient déjà — et pourquoi elles ne sont pas réutilisées

`selection/shap_select.py` calcule déjà des valeurs SHAP, mais sur un modèle
**pilote jetable** (XGBoost `n_estimators=80, max_depth=4`, entraîné
uniquement pour classer/sélectionner les features, jamais exporté). La
migration `tracking/migrations/0014_shap_selection_cache.sql` ne persiste
que `selected_columns` — jamais les valeurs SHAP elles-mêmes. Le modèle
réellement **exporté** (`tracking/export.py::export_best_model`) peut être
n'importe lequel des 5 algos de `models/registry.py`, avec hyperparamètres
tunés et données rééchantillonnées — un objet entraîné complètement
différent. Expliquer une vraie prédiction exige donc de calculer SHAP sur
CE modèle, pas de réutiliser le cache de sélection.

## Coût mesuré (chiffres réels, pas une estimation)

Mesuré sur un modèle réellement exporté en production
(`~/.patrick/runs/mon_run/BTC_USD_1_best_model_h1.joblib`, LightGBM, 15
features sélectionnées) :

| Étape | Coût mesuré |
|---|---|
| `shap.TreeExplainer(model)` + `shap_values()` sur 1 ligne, à froid | ~0,73s (joblib.load + explainer + shap_values) |
| Même appel, explainer réutilisé (à chaud) | ~5ms |
| Reconstruction du pool de features (`build_base_feature_pool` + `build_parametric_pool`, EGARCH/Kalman/HMM/particle-filter sur tout l'univers, `fit_end_idx=None`) pour retrouver la ligne exacte à expliquer | **~33,6s** (mesuré sur l'export réel BTC-USD/h1, données brutes déjà en cache, aucun appel réseau) |

**Conclusion** : le calcul SHAP proprement dit est négligeable (<1s, "rounding error" face au reste). Le coût réel visible par l'utilisateur vient de la reconstruction du pool de features nécessaire pour retrouver la ligne exacte de la date expliquée — un coût **préexistant**, payé de la même façon par `predict.py` lors de chaque inférence live, pas quelque chose que ce module ajoute.

## Décision produit

- Calcul **à la demande** (bouton "Générer l'explication" sur `/targets/{ticker}`), jamais au chargement de page — le bouton se désactive et affiche un message d'attente pendant le calcul (~30s en pratique), sans prétendre que c'est instantané.
- Pas de cache inter-requêtes de l'`explainer` : le trafic visé (outil local, un seul utilisateur) ne justifie pas la complexité de garder une référence au modèle chargé + données de fond entre deux requêtes HTTP.
- Valeurs SHAP affichées dans l'**espace brut du modèle** (`TreeExplainer(model_output="raw")`, unités type marge/log-odds) — PAS une décomposition de probabilité : pour un ensemble d'arbres multiclasse, la garantie d'additivité de SHAP tient dans cet espace brut, pas après passage par softmax. Le front-end (`shap_waterfall.js`) affiche explicitement cet avertissement sous le graphique.

## Limite honnête trouvée en testant contre une vraie base

`trial.artifact_path` est un chemin **relatif**, résolu par `joblib.load()`
contre le `cwd` du process serveur au moment de l'appel — pas contre
l'emplacement du code. Si `patrick serve`/`patrick worker` tourne depuis un
répertoire différent de celui où le run a été exporté à l'origine, la
résolution échoue (`FileNotFoundError` remontée proprement en `ok: false`
côté JSON, jamais une page cassée). C'est exactement le même piège déjà
documenté par `feature/scheduled-inference` (`daily_predict.py`, option
`--base-dir`) — cette route API n'a pas d'équivalent `--base-dir` (elle
tourne dans le process web déjà démarré au bon endroit en production), mais
le constat mérite d'être connu si le mode de déploiement change un jour.
