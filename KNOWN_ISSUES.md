# KNOWN_ISSUES.md — Problèmes connus, hors scope des sessions en cours

Suivi des échecs pré-existants identifiés mais volontairement **non corrigés**
dans les sessions de traduction (D1-D6) et d'infrastructure (CI, commit
fréquent, nettoyage de branches) — hors mandat de ces sessions
(« aucune modification de logique fonctionnelle »). Traités dans une session
de correction dédiée (voir « Résolus » ci-dessous).

---

## Résolus

### 1. `test_data_quality.py::test_ingest_excludes_series_with_explicit_reason_and_persists` — résolu 2026-08-08

Cause confirmée : fixture à date absolue `2018-01-01`. Corrigé en remplaçant
par `_OLD_ENOUGH_START`, une date calculée relativement à l'exécution
(`pd.Timestamp.today() - 30 ans`, marge de 10 ans au-delà du seuil de 20 ans
testé) — `patrick/tests/test_data_quality.py`. Voir l'historique git de ce
fichier / le commit associé sur la PR #41 pour le diff exact.

### 2. `test_data_quality.py::test_data_quality_disabled_restores_pre_p6_5_behavior` — résolu 2026-08-08

Même cause, même correctif que le point 1 (fixture partageant la même
constante `_OLD_ENOUGH_START`).

### 3. `test_history_webapp_smoke.py::test_universe_page_renders` — résolu 2026-08-08

**Ce n'était pas un problème de date** : investigation menée avant toute
correction (voir règle du projet : ne jamais deviner la cause). Cause réelle,
confirmée par exécution directe : `patrick/webapp/app.py::universe_page`
contenait une confusion de type — `DEFAULT_TARGET_GROUPS.values()` donne des
listes de tuples `(symbole, label)`, mais la route les itérait comme si
c'étaient des symboles bruts (`for s in targets`), puis testait
`target in symbol_info` avec `target` = tuple entier contre un dict à clés
string. Résultat : `target in symbol_info` était **toujours `False`**, donc
la liste `groups` restait vide dans 100% des cas, indépendamment du contenu
de la base — un bug de production, pas un artefact de test.

`tracking/history.py::universe_overview` faisait déjà cette jointure
correctement (`for symbol, label in items:`) mais n'était pas appelée par la
route — une deuxième implémentation parallèle, divergente, avait été écrite
directement dans `app.py`. Corrigé en supprimant cette duplication : la route
appelle désormais `universe_overview()` pour le regroupement, et ne conserve
que la logique propre à la route (traduction i18n du nom de groupe, qui a
besoin de `request` et n'a donc pas sa place dans la couche lecture seule
`tracking/history.py`).

---

## Contexte de découverte

Ces trois échecs sont apparus de façon répétée et cohérente tout au long
des sessions D1-D6 (traduction) et de mise en place de la CI — toujours
les mêmes trois, jamais de régression supplémentaire causée par les
changements de ces sessions (vérifié systématiquement via exécution
isolée et comparaison `git stash`/HEAD non modifié). Confirmés une
dernière fois par la CI elle-même (`.github/workflows/tests.yml`,
premiers runs sur PR #41) : `3 failed, 221 passed, 42 deselected`.

Après correction : suite complète rapide vérifiée verte —
`224 passed, 42 deselected, 0 failed`.

---

## Code mort identifié (non traité dans ce chantier)

### 1. `patrick/patrick/features/vol_models.py::build_vol_model_features` — identifié 2026-08-09

Fonction combinée (paramétrique + non-paramétrique, ligne ~313) **jamais
appelée en production** — confirmé par recherche exhaustive des appelants
(`grep` sur tout `patrick/patrick/`) : seule
`build_vol_model_features_parametric` (et séparément
`build_vol_model_features_base`) est utilisée, depuis
`pipeline/engine.py::build_parametric_pool`/`build_base_feature_pool`.
Identifié pendant le chantier du cache EGARCH/Kalman/HMM (recherche du
point d'insertion unique) — non supprimée ici, hors du mandat de ce
chantier. À traiter dans une passe de nettoyage séparée.

