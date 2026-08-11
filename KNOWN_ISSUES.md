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

### 4. `test_audit_degradation.py::test_audit_degradation_runs_all_four_configurations_and_exports` — résolu 2026-08-11

Même cause, même famille que les points 1-2 (fixture à date absolue,
`START = "2015-01-01"`) : passée sous le seuil des 20 ans d'historique
minimum requis par `data/ingest.py`. Pas détectée avant cette session car
le test est marqué `slow` (exclu de la suite rapide par défaut,
`pyproject.toml::addopts`) et n'était donc pas visible tant que
`pytest -m slow` n'avait pas été relancé après que la fixture ait
franchi le seuil. `_OLD_ENOUGH_START` (point 1) déplacée de
`test_data_quality.py` vers `tests/conftest.py::OLD_ENOUGH_START`
(helper partagé plutôt que dupliqué une deuxième fois, cf. règle du
projet) ; les deux fichiers l'importent désormais.

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

## Instable, cause identifiée -- pas corrigé (charge machine, pas un bug)

### `test_webapp_smoke.py` (tests slow lançant un vrai pipeline) — `deadline_s=240` insuffisant sous charge externe, identifié 2026-08-11

`pytest -m slow` complet (session C1-C4) : 2 échecs sur 16 tests slow,
`test_audit_degradation...` (point 4 ci-dessus, résolu) et
`test_relaunch_reuses_config_with_fresh_name`
(`test_webapp_smoke.py`) — timeout dans `_wait_for_status(...,
deadline_s=240)`.

**Investigation avant correctif** (règle du projet) : `test_relaunch_reuses_
config_with_fresh_name` passe seul en isolation (29,5s, marge large sur
240s). Reproduit de façon fiable en relançant les 6 tests slow de
`test_webapp_smoke.py` ensemble (~5 min) -- mais avec `-x` (arrêt au premier
échec), c'est le PREMIER test du fichier
(`test_run_via_web_form_end_to_end`), pas le test du rapport initial, qui
échoue le premier : `elapsed_s=235.6`, `phase='features'`,
`progress={'done': 0, 'total': 16}` -- le pipeline réel n'avait même pas
commencé les essais de modèles après 235s, alors qu'il termine
normalement en quelques secondes à quelques dizaines de secondes. Au
moment de cette relance, `uptime` mesurait une charge machine de
**19,3 sur 4 cœurs** (`nproc`) sans aucun processus pytest concurrent de
cette session -- charge externe au conteneur, pas une contention entre
tests de cette suite.

**Conclusion** : pas la même famille que les points 1-2-4 (aucune fixture
en cause) et pas un bug de code -- le budget de 240s de
`_wait_for_status` n'a simplement aucune marge quand la machine hôte est
fortement chargée par autre chose que cette session, et LEQUEL des 6
tests du fichier échoue en premier dépend du moment exact où la charge
frappe, pas d'un test spécifique ni d'un ordre d'exécution particulier.
**Non corrigé délibérément** : augmenter `deadline_s` à une valeur
arbitraire (600? 900?) serait deviner un correctif sans savoir si la
marge serait suffisante à la prochaine charge externe -- exactement ce
que la règle du projet interdit. Nécessite une décision produit (budget
de timeout acceptable pour la CI/le sandbox, ou marquer ces tests comme
non fiables sous charge partagée) plutôt qu'un ajustement de constante
à la volée.

---

## Code mort — traité (audit phase9.py, D1-D4)

### 1. `patrick/patrick/features/vol_models.py::build_vol_model_features` — identifié 2026-08-09, supprimé 2026-08-11

Fonction combinée (paramétrique + non-paramétrique) **jamais appelée en
production** — confirmé par recherche exhaustive des appelants : seule
`build_vol_model_features_parametric` (et séparément
`build_vol_model_features_base`) est utilisée, depuis
`pipeline/engine.py::build_parametric_pool`/`build_base_feature_pool`.
Lue en détail (D4) : duplication exacte des deux fonctions séparées
concaténées, en plus ancien -- sans le cache (`conn`/`snapshot_id`,
migration 0015) ni l'instrumentation de profilage (P1) ajoutés depuis aux
deux fonctions séparées. Supprimée, ainsi que `_VOL_MODEL_BUILDERS` (dict
de fusion qui n'existait que pour l'alimenter). Les 3 tests de
`tests/test_features_robustness.py` qui l'utilisaient (régression zero-
crossing/infini, cf. en-tête du fichier) ont été portés sur un helper de
test local qui appelle les deux fonctions séparées et concatène -- la
couverture réelle (le bug historique testé) est préservée, seul le point
d'entrée mort a disparu.

### 2. `patrick/patrick/phase9.py::signal_strength` — identifié et supprimé 2026-08-11

Orpheline totale (même pas exportée dans `__init__.py`, contrairement au
reste de `phase9.py`). Enveloppe triviale `{signal: score} -> DataFrame`
à 2 colonnes ; son rôle (poser une colonne `signal` en entrée
d'`aggregate_signals`) est déjà rempli en production par la sortie
(bien plus riche : `dm_stat`/`p_value`/`testable`/`significant`...) de
`signal_dm_summary`, qui alimente réellement `aggregate_signals`.
Supprimée sans réécriture de test (aucun test n'y faisait référence).

### 3. `patrick/patrick/phase9.py::reconstruct_state` — identifié et supprimé 2026-08-11

Fonction libre, strictement orpheline : aucun appelant, y compris depuis
`StrategyEngine` (qui n'a jamais utilisé `take_snapshot`/`reconstruct_state`
comme une paire symétrique malgré les noms). Supprimée.

### 4. `patrick/patrick/phase9.py::DecisionJournal`/`DecisionJournalEntry`/`take_snapshot` — **conservées**, décision révisée 2026-08-11

Identifiées dans l'audit comme redondantes avec la vraie persistance
(`tracking/db.py::save_phase9_journal_entry`/`save_phase9_snapshot`,
branchée sur `/api/phase9/journal` et `/phase9`) -- la décision initiale de
l'audit était de les supprimer avec le reste du "journal en double" (D3).
Lecture du code avant suppression (règle du projet : jamais deviner) a
révélé une dépendance structurelle non anticipée : `StrategyEngine`
(conservée, cf. bloc 5-7 ci-dessous) journalise en interne via
`self.journal` (une `DecisionJournal`) sur CHAQUE méthode, et
`StrategyEngine.snapshot_state` appelle directement `take_snapshot`.
Supprimer ces trois symboles aurait cassé `StrategyEngine`, ce que D1
(même audit) demande explicitement de ne pas toucher. Rôle clarifié en
commentaire de module (`phase9.py`, juste avant `StrategyRule`) : ce ne
sont pas des concurrentes de `tracking/db.py` mais l'audit trail interne,
en mémoire, du futur moteur de stratégie -- gardées pour cette seule
raison, pas pour un usage autonome.

---

## Plomberie future volontaire (non retirée)

### `StrategyRule`/`StrategyVersion`/`StrategyEngine`/`enforce_risk_constraints`/`ExecutionOrder`/`simulate_execution`/`parameter_grid_summary` — audit D1, 2026-08-11

Jamais appelées hors de leurs propres tests -- blocs 5-7 du plan PATRICK
original en 9 blocs (stratégie, backtest, exécution), jamais commencés en
pratique puisque l'univers reste limité à `^VIX`. Pas du code mort par
accident : plomberie préparée pour cette phase future, documentée en
commentaire de module dans `phase9.py` plutôt que supprimée et à
réécrire plus tard.

---

## Chantier futur distinct

### 2. Mode clair non implémenté (monde visuel « Nocturne ») — identifié 2026-08-10

`patrick/patrick/webapp/static/tokens.css` porte `:root` (Nocturne, sombre,
actif) et `[data-theme="light"]` (bloc vide, `/* not yet implemented — see
KNOWN_ISSUES.md */`) — l'architecture (jetons sémantiques, structure
`:root` + `[data-theme]`) est prête à recevoir un mode clair sans
réarchitecturer la feuille de jetons ni les composants qui la consomment
(`metric()`, `data_table()`, `status_badge()`, `empty_state()`,
`error_state()`), mais aucune valeur n'y est écrite. En conséquence, le
bouton de bascule jour/nuit (`#theme-toggle`, `templates/base.html`) est
masqué et le script de détection de thème (`localStorage`/
`prefers-color-scheme`, posé avant le premier rendu) a été retiré du
`<head>` — l'un et l'autre redeviendront nécessaires quand ce bloc sera
écrit. `observatory.js` garde son code de bascule intact (guardé par
`if (toggle)`, inerte sans bouton) : aucune modification JS ne sera
nécessaire pour réactiver la bascule, seul `tokens.css` et le bouton dans
`base.html` doivent être complétés. Chantier futur distinct, non traité
dans le remplacement de charte visuelle qui a introduit cette structure.

