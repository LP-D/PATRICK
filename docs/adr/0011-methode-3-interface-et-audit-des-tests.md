# ADR 0011 — Méthode 3 (niveaux bruts, calibration), interface, audit des tests

Date : 2026-10-30 · Statut : acceptée (méthode 3 codée, **non activée par défaut** : voir « Activation ») · Code : `features/fracdiff.py` (`fracdiff_level`), `features/macro.py`, `pipeline/engine.py` (`_stationary_raw`, `_fracdiff_levels`, `_features_payload`), `config/defaults.py` (`DEFAULT_FORM_CALIBRATION`), `config/training_profiles.py` (`identify`), `tracking/history.py` (`evaluation_sizes`), `webapp/` (`trial_budget.js`, `_compare_tabs.html`, états vides, guide de premier lancement), `static/chart_kit.js` (`vlines`, `sync`), `tests/conftest.py` · Tests : `tests/test_method_v3.py`, `tests/test_training_profile_identify.py`, `tests/test_run_detail_method.py`, `tests/test_analysis_compare.py`, `tests/js/chart_kit.test.js`

## Contexte

Suite de la critique du 28/10 (ADR 0007 à 0010). Restaient : les points de méthode qui changent l'entraînement de tout run neuf (1.7, 5.1, 5.5), l'interface (budget au lancement,
badge de profil, N_eff, hygiène CSS, comparateur, états vides, graphiques) et, demandé le 30/10, un audit de la suite de tests, devenue très longue.

## Décisions

### Méthode 3 (`validation.method_version >= 3`)

1. **Niveaux bruts différenciés fractionnairement (1.7).** Les colonnes de `raw` (cours des autres séries) et les `_level` / `_lagN` des séries macro sont non stationnaires : les arbres
   extrapolent mal hors de la plage vue. En méthode 3 chacune devient son niveau différencié fractionnairement (`fracdiff_level`, d = 0,4, seuil 1e-3, log pour une série strictement
   positive), **sous le même nom** : la réduction d'univers, les modèles exportés et les pages ne changent pas. Le prix de la cible et celui du benchmark d'une cible alpha restent
   des prix (les étiquettes en dépendent). Causal : chaque valeur ne dépend que des ~140 dernières observations. La clé du cache de réserves ne bouge que pour la méthode 3
   (`_features_payload`) : un run de méthode 1 ou 2 retrouve ses réserves.
2. **Calibration cochée par défaut dans le formulaire (5.5).** `DEFAULT_FORM_CALIBRATION = True` pour les formulaires ML et DL ; `DEFAULT_CALIBRATION_ENABLED` (schéma) reste `False` : les
   fichiers de configuration, le golden master et les runs enregistrés ne bougent pas. La case reste décochable.

### Activation

`D.CURRENT_METHOD_VERSION` reste **2**. Le point 1 change les variables de tous les runs neufs ; le protocole de l'ADR 0010 demande de le mesurer sur un panel de cibles avant
de le rendre défaut. Protocole : mêmes cibles, mêmes réglages (profil rapide), méthode 2 contre méthode 3, un run chacun, comparer AUC et F1 de holdout, Brier de P(hausse), placebo
de décalage, nombre de variables de niveau retenues. Pour essayer un run en méthode 3 : `validation.method_version: 3` dans la configuration (CLI ou fichier). Basculer le défaut =
changer `CURRENT_METHOD_VERSION` et ajouter la ligne à l'ADR avec les chiffres.

### Interface

- **Budget d'essais dans le formulaire de lancement** (`trial_budget.js` → `/api/trial-budget`) : pour chaque cible (3 au plus) et horizon cochés, essais comptés, ajoutés, seuil de Sharpe sous H0 avant / après.
- **Badge de profil** sur la page d'un run : un run n'enregistre pas son profil, il se déduit de ses réglages (`training_profiles.identify` : le profil dont le plus de réglages coïncident,
  `standard` si tout ce que touche un profil est par défaut, « Personnalisé » sinon). Les 17 profils se reconnaissent eux-mêmes (test).
- **N_eff et plis à côté des métriques** (`history.evaluation_sizes`) : n lignes, N_eff ≈ n / horizon (les étiquettes à h jours se recouvrent), nombre de plis. Le PBO est déjà refusé sous 6 blocs.
- **Comparateur** : le tableau des réglages et l'analyse détaillée sont deux vues d'une même comparaison, reliées par une barre d'onglets (`_compare_tabs.html`). L'onglet « Comparer » d'un run
  menait à une erreur 400 (un seul run envoyé) : il ouvre l'historique avec ce run déjà coché (`/runs?compare=<id>`). Le tableau montre le profil et la méthode de chaque run et avertit quand ils diffèrent.
- **États vides actionnables** (`empty_state(…, action_url, action_label)`) et **guide de premier lancement** (trois gestes) sur la synthèse quand aucun run n'est terminé.
- **Hygiène** : les `style="…"` en ligne deviennent des classes ; il n'en reste que deux, des largeurs calculées par les données (test garde-fou).
- **Graphiques** : `chart_kit.js` accepte `vlines` (repères verticaux datés : frontière de pli, début du holdout, promotion, rupture) et `sync` (réticule partagé entre graphiques
  empilés d'un même groupe). Capacité livrée et testée sous Node ; **aucune page ne les passe encore** (voir « Non fait »).

### Suite de tests (audit du 30/10)

Mesure : 3 610 tests (3 521 rapides, 84 lents, 5 de validité) dans 300 fichiers ; aucun corps de test en double ; 6 tests sans assertion (ils vérifient l'absence d'erreur). La suite
rapide prenait **~17 min** en série. La cause n'était pas la redondance :

- **Les tests de pages n'isolaient pas la base.** `paths.db_path()` retombe sur `~/.patrick/patrick.db` (13 Go) quand `PATRICK_DB_PATH` n'est pas posé : ~12 s par rendu de page pour une
  demi-douzaine de tests (≈ 230 s), et rien n'empêchait un test d'écrire dans la vraie base. `conftest.py` isole désormais la base de chaque test : 88 tests de pages de 230 s à 24 s.
- **`pytest -n 5` (pytest-xdist)** : chaque test a déjà sa base, ses caches et sa racine de données, donc ils ne partagent rien. Suite rapide complète : **4 min 58 s, 3 548 réussis, 0 échec**.
  La CI rapide utilise `-n auto` ; la suite lente reste en série (golden master exact, entraînements parallèles).
- **Jeux de données des six tests « pas de requête N+1 »** réduits (8 runs au lieu de 30 à 40) : mêmes assertions (au plus une requête).
- Les 2 243 tests de moins de 0,1 s pèsent 59 s en tout (6 %) : supprimer des tests ne ferait rien gagner ; aucun n'a été supprimé.

Restent coûteux (≥ 10 s sous charge) : `test_regime_detection` (HMM, trois tests), `test_cpcv_interaction_leak`, `test_cli_main_guard`, `test_selection_determinism`,
`test_fund_selection::test_no_cap_keeps_every_model_and_none_round_trips`. Ce sont de vraies estimations ; les passer en `slow` les sortirait de la CI poussée au prix de la couverture.

## Non fait

- **Cible de volatilité (5.1).** Un nouveau `target_kind` n'est pas un réglage : l'étiquette de cible (`symbole__alpha_benchmark`) est lue par plus de vingt consommateurs (`fund/selection.py`,
  `fund/systematic.py`, `simulate/engine.py`, `tracking/stats.py` : familles DM/BH, `class_overview`, `usage`, `history`, `launch_batches`, `webapp/instruments.py`, `names.js`, `compare_runs.html`...) qui
  doivent chacun décider ce qu'un modèle de volatilité y fait (jamais un signal de direction du prix, jamais dans la famille BH des directions). Conception retenue pour la suite : étiquette
  `symbole__vol`, classes sur `log(σ_futur / σ_passé)` avec la même fenêtre `h` que l'horizon (sinon la purge est trop courte), baselines HAR-RV sur le niveau de volatilité. Rien n'est écrit :
  du code non branché serait de la plomberie morte (voir la critique sur `phase9`).
- **Annotations et réticule dans les pages** : `vlines` / `sync` ne sont passés par aucune page (il faut, par page, la donnée : dates de plis, début du holdout, promotion du champion, ruptures Page-Hinkley).
  Petits multiples de la vue toutes cibles, diagramme de fiabilité à côté de chaque `p_up` de la page Prédictions (la page d'analyse d'un run en a déjà), page de run réellement fusionnée.
- **Vitesse des pages** (2.3, 2.6, 2.7) : mesurées le 30/10 sur une base vide : 22 à 131 ms de rendu, 150 à 320 Ko de HTML dont 100 Ko de JSON (glossaire 60 Ko, noms d'instruments 21 Ko,
  textes 18 Ko). Sur une machine locale (boucle locale, cache de fichiers statiques) le gain de sortir ce JSON ou de différer `chart_kit.js` est nul, et `glossary.js` / `names.js` lisent ces blocs
  de façon synchrone : les rendre asynchrones coûte du code pour un gain non mesurable. Le sondage de l'état d'un run (1,5 s) ne tourne que sur la page de suivi, onglet visible : le flux SSE n'apporte rien de plus.
- **Reprise au niveau du scan (3.4)**, **ablation de Kalman (3.5)**, **plusieurs workers (3.3)**, **Sharpe déflaté au niveau d'une stratégie (1.5)**, **mutants survivants / mondes à pertes égales (1.8)** :
  inchangés (voir l'ADR 0009 pour la conception de 3.4 et 3.5, qui demandent des runs complets appariés).

## Conséquences

- Les runs de méthode 1 et 2 ne changent pas (clé de cache, hachage de configuration et noms de variables identiques).
- La suite rapide passe de ~17 à ~5 min sur ce poste (6 coeurs) ; un poste sans pytest-xdist continue de lancer `pytest` en série.
