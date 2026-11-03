# Page « Économétrie » : une série à la fois

Date : 2026-11-03. Origine : un cadrage rédigé hors dépôt (claude.ai) que Léon a confié à Claude Code pour l'adapter à l'existant. Ce document le remplace ; les écarts avec le cadrage d'origine sont au §2. Rien n'est codé : c'est la phase P0 (audit en lecture seule) du cadrage.

## 1. Intention

Donner à UNE série (une cible, une série macro) les questions classiques de l'économétrie, avec des réponses honnêtes :

- est-elle stationnaire, a-t-elle une rupture ?
- est-elle dépendante dans le temps (moyenne, variance) ?
- sa moyenne est-elle prévisible ? (presque jamais, sur des rendements journaliers)
- sa variance est-elle prévisible ? (presque toujours : c'est là que se trouve la valeur)
- quel modèle de variance prévoit le mieux, hors échantillon, et la différence est-elle réelle ?

La page sert aussi à apprendre : chaque surface porte une aide courte, et un cours écrit précède chaque phase de code (règle du cadrage d'origine, conservée).

Anti-objectifs : couronner un « meilleur modèle » ; produire une recommandation d'achat ou de vente ; masquer un modèle qui n'a pas convergé ; fabriquer un ordre (p,d,q) « gagnant » quand rien ne bat la constante.

## 2. Ce que l'audit change au cadrage d'origine

| Le cadrage disait | Dans le dépôt (vérifié le 2026-11-03) | Conséquence |
|---|---|---|
| Nav : « 5ᵉ catégorie ANALYSE », amendement de `MASTER.md` « comme pour les 4 catégories » | Il y a déjà 5 catégories (`pilotage`, `modeles`, `classes_actifs`, `simulation`, `patrimoine`) et un dossier `Recherche` sous Pilotage, qui contient `/exploration` (`nav_registry.py`) | Pas de nouvelle catégorie, donc pas d'amendement de catégories. Une entrée `econometrie` dans le dossier `Recherche`, juste après Exploration |
| « Cockpit v2 » | Le design système en vigueur est v3 « Cockpit Pro » (`design-system/patrick/MASTER.md`) | Suivre la v3 |
| Python 3.10 à vérifier | venv en Python 3.14.6 ; `requires-python >= 3.11` ; la CI teste 3.11 et 3.12 ; numpy 2.5, pandas 3.0, `arch` 8.0.0, `statsmodels` 0.14.6 | Toutes les classes nécessaires s'importent (liste au §3). Le vrai risque n'est pas 3.10 mais la CI qui installe les dernières versions : statsmodels 0.15 a déjà cassé `ar_residuals` en silence. Tests de compatibilité obligatoires (voir §5) |
| « 66 cibles et 105 séries features » | Ces chiffres n'apparaissent pas dans le code. Le catalogue de l'exploration compte 528 symboles (488 Yahoo, 40 FRED) | Utiliser le catalogue existant (`exploration_routes.catalog`), jamais une liste figée. Chiffres d'origine à confirmer par Léon |
| Onglets 1, 2, 5 à écrire | ADF, KPSS, Hurst, ratio de variance, ACF/PACF, Ljung-Box (sur r et r²), ARCH-LM, Granger, Engle-Granger, PCA, CCF existent déjà dans `exploration/studies.py` | Ne pas recopier : la nouvelle page appelle ces fonctions et ajoute ce qui manque |
| Onglet 6 : « réutiliser le HMM de `vol_models.py` » | Le HMM filtré est dans `features/regime_detection.py` (choix du nombre d'états par BIC) et `features/vol_models.py::hmm_filtered_stress_prob` | Réutiliser ces deux, sans nouvel ajustement HMM |
| P3 « pont ML » à créer | Il existe déjà pour EGARCH, HMM, Kalman et résidu ARIMA : réestimé sur le pli d'entraînement (`fit_end_idx`), probabilités filtrées jamais lissées, modèles mis en cache dans SQLite | P3 devient une extension (GJR, APARCH, HAR…) et non une création. Voir §7 pour le piège du golden master |
| Cache « dans la lignée de `cache_tables.py` » | `cache_tables.py` ne contient que le cache SHAP | Voir §5 : cache à écrire, avec un choix à trancher |
| Heavy grids « par `run_manager` » | `run_manager.py` pilote les runs d'entraînement ; `exploration_routes` calcule à la demande dans un pool de threads | Calcul au clic dans un pool de threads (même motif que l'exploration) ; pas de passage par la file de runs en P1 |

## 3. Ce qui existe, ce qui manque

Chemins relatifs à `patrick/patrick/`.

| Onglet | Déjà là | À écrire |
|---|---|---|
| 1. Stationnarité et ruptures | ADF + KPSS sur niveau et rendement, verdict croisé, Hurst (`exploration/studies.py::stationarity`, `hurst_exponent`) ; ratio de variance (`variance_ratio`) ; `features/fracdiff.py` | Phillips-Perron, DF-GLS, Zivot-Andrews (`arch.unitroot`, `statsmodels.tsa.stattools.zivot_andrews`) |
| 2. Dépendance | ACF, PACF, ACF², Ljung-Box sur r et r² (= McLeod-Li), ARCH-LM (`studies.memory`) | BDS (`statsmodels.tsa.stattools.bds`), appliqué aux résidus du modèle de moyenne |
| 3. Moyenne conditionnelle | Résidu ARIMA d'ordre fixe en feature (`features/vol_models.py`) ; AR d'ordre AIC (`studies.ar_residuals`) | Grille (p,d,q) triée AIC/BIC, SARIMA (mensuel seulement), ARIMAX, diagnostics des résidus (Ljung-Box, Jarque-Bera, QQ). ARFIMA n'existe pas dans statsmodels : à trancher au plan (estimateur de d + ARMA sur la série différenciée) |
| 4. Variance conditionnelle | EGARCH(1,1,1) normal, filtré (`vol_models.egarch_conditional_vol`) ; proxys Heston ; Parkinson/GK/RS/YZ **glissants** pour les features (`features/technical.py`) | ARCH, GARCH, GJR, EGARCH, APARCH, FIGARCH, HAR-RV : tous natifs dans `arch` ; lois normal, Student, skew-t, GED natives. IGARCH : GARCH sous contrainte α+β=1 (ou EWMA). **GARCH-M n'existe pas dans `arch` : hors P1.** À écrire à la main : courbe d'impact des nouvelles, tests de signe d'Engle-Ng. La page a besoin de la variance **journalière** de Parkinson/GK (une ligne chacune), pas des versions glissantes |
| 5. Multivarié | Granger (bivarié, matrice, conditionnel), Engle-Granger, PCA, CCF dans `/exploration` | VAR, IRF/FEVD, Johansen, VECM : **à ajouter à `/exploration`**, pas à la nouvelle page (plusieurs séries). DCC-GARCH à la main (P3) |
| 6. Régimes | HMM filtré + BIC des états (`features/regime_detection.py`) | Markov-switching moyenne/variance (`statsmodels`), lecture du HMM existant |
| 7. Prévision et comparaison | Diebold-Mariano (`validation/diebold_mariano.py`, ADR 0003 : refus sous 15 blocs), BH-FDR (`validation/fdr.py`), DSR (`validation/dsr.py`), Kupiec (`analysis/portfolio_risk.py`) | QLIKE (n'existe qu'en privé dans `earnings/model.py`), MSE, Mincer-Zarnowitz, Model Confidence Set (`arch.bootstrap.MCS`), Christoffersen |
| 8. Backlog | Kalman en feature | EVT (`scipy.stats.genpareto`), ondelettes (PyWavelets non installé), entropie, Bai-Perron (absent de statsmodels ; `ruptures` fait autre chose) |

Disponibilité des bibliothèques : importés avec succès dans le venv du projet, 33 classes ou fonctions distinctes sur 33 (ADF, KPSS, PP, ZA, DFGLS, VarianceRatio, HARX, FIGARCH, APARCH, EGARCH, EWMA, SkewStudent, GeneralizedError, MCS, SPA, bds, Johansen, VECM, MarkovRegression, MarkovAutoregression, ARIMA, SARIMAX, UnobservedComponents, VAR…). Non vérifié : que chaque ajustement tourne proprement sous pandas 3 ; c'est le premier test à écrire.

## 4. La page

**Sélecteurs** (barre fixe en haut) : série (catalogue de l'exploration, recherche par nom), transformation, fenêtre (dates), mode (échantillon complet, ou expansif avec réestimation tous les k jours).

Transformations : log-rendement (défaut), rendement², variance journalière de Parkinson ou Garman-Klass (seulement si les prix OHLC existent : `yfinance_source.download_ohlc` ; les séries FRED n'en ont pas), différence, différenciation fractionnaire (`features/fracdiff.py`).

**Fréquences** : journalier (Yahoo) et mensuel (FRED, via `fred_periodicity`) ne se mélangent jamais. SARIMA et saisonnalité ne sont proposés que sur le mensuel ; le reste du menu s'adapte à la fréquence.

**Onglets** (ordre de P1) : 1 Stationnarité, 2 Dépendance, 3 Moyenne, 4 Variance, 7 Prévision. Puis 6 Régimes en P2. Chaque onglet charge au clic ; la page s'ouvre sans calcul.

**Première ligne de chaque onglet : le verdict, dit tel quel.** Exemples : « Aucun modèle de moyenne ne bat la constante (ΔBIC < 2) » ; « 3 modèles de variance sur 9 n'ont pas convergé » ; « 41 spécifications essayées, 2 significatives avant correction, 0 après ». Le tableau d'une grille affiche toujours le modèle constant comme ligne de référence, et le nombre de spécifications essayées.

## 5. Architecture

- **Calculs purs** dans `patrick/econometrics/` (aucun accès web ni base) : `transforms.py`, `unitroot.py`, `serial.py` (dépendance ; pas `dependence.py`, qui existe déjà dans `exploration/`), `mean_models.py`, `variance_models.py`, `forecast_eval.py`, plus tard `regimes.py`, `dcc.py`. Chaque fonction renvoie un dict JSON, nettoyé par `studies.clean`, comme l'exploration. Les fonctions de `exploration/studies.py` sont importées telles quelles, sans les déplacer (leurs tests restent en place).
- **Web** : `webapp/econometrics_routes.py` sur le modèle de `exploration_routes.py` (tuple `STUDIES`, `/api/econometrics/{étude}`, `loader` remplaçable par les tests, `run_in_threadpool`), gabarit `econometrics.html`, `static/econometrics.js`, textes dans `webapp/i18n_econometrics.py` (FR/EN, `t('clé')`), entrée dans `nav_registry.py` (groupe `recherche`, ordre 43).
- **Cache « calculer une fois »** : clé = empreinte de (symbole, source, transformation, spécification, fenêtre, mode, version des données = dernière date + nombre d'observations + empreinte des valeurs, version du code). **Mon choix recommandé** : fichiers JSON compressés via `LocalCache` (écriture atomique depuis l'incident du 10/10 ; éviction à relire dans `cache_eviction.py`), plutôt qu'une table SQLite : pas de migration, pas de contention avec les runs, et facile à exclure de la synchronisation OneDrive (l'export de synchronisation se fait déjà sans caches). À confirmer au plan après lecture de `cache_manager`/`cache_eviction`.
- **Temps** : un GARCH sur ~6 000 observations se compte en dixièmes de seconde ; une grille de 16 modèles × 4 lois, en quelques secondes. À mesurer sur la vraie série, pas sur des données simulées (leçon de `/runs`).
- **Mise à l'échelle** : `arch` converge mal sur des rendements ~0,01 ; les rendements sont multipliés par 100 en interne, et les paramètres sont ramenés à l'échelle d'origine avant affichage.
- **Tests** (TDD, hors réseau) : processus simulés à paramètres connus (marche aléatoire contre AR(1) pour ADF ; GARCH(1,1) simulé dont on retrouve α, β à tolérance près ; QLIKE minimal en la vérité) ; comparaison directe avec la sortie d'`arch`/`statsmodels` ; Kupiec/Christoffersen sur des cas à résultat connu. Un test par fonction exposée à l'écran vérifie qu'un modèle non convergé est **affiché**, pas retiré. Les ajustements lents passent dans la suite lente. Obligatoire : un test de compatibilité avec la dernière version de `statsmodels` et d'`arch` (`uvx --python 3.12 --with statsmodels --with arch python script.py`, qui installe les dernières versions comme la CI), et aucun `except Exception` qui avale une rupture d'API sans la signaler.
- **Interface** : règles de la maison (une phrase d'aide ≤ 120 caractères visible, un « ? » par zone, une donnée jamais repliée ; test `test_help_minimal_text.py`), garde-fou i18n (`test_i18n_templates.py`), cellules de tableau avec liens construites par blocs `{% set %}`, jamais par concaténation `~` avec `| e`.
- **Aperçu** : serveur d'aperçu isolé (`PATRICK_CACHE_ROOT`, `PATRICK_FEATURE_CACHE_ROOT`), jamais le vrai cache ; scanner `~/.patrick/cache/series_*.parquet` après tout test réseau.

## 6. Pièges du cadrage d'origine et traitement retenu

1. **Moyenne AR/MA sur rendements journaliers** : non significative presque toujours. La page l'affiche telle quelle (§4) ; aucun ordre « gagnant » n'est mis en avant tant que ΔBIC < 2 contre la constante.
2. **Fuite temporelle** : ajusté sur tout l'échantillon, un modèle est **descriptif**. Les ajustements pleine période portent le bandeau « estimé sur tout l'échantillon : descriptif, pas une prévision ». L'onglet 7 réestime en fenêtre expansive (tous les k jours) et compare des prévisions à un pas, filtrées. Le pont ML (P3) réutilise `fit_end_idx`, comme l'existant.
3. **Chasse au meilleur modèle** : compteur de spécifications, BH-FDR sur la famille de p-values (`validation/fdr.py`), Model Confidence Set pour les prévisions, DM avec la règle existante des 15 blocs. Avertissement affiché, jamais blocage (philosophie de l'exploration).
4. **Proxy de variance bruité** : QLIKE et MSE calculés contre r² **et** contre Parkinson/GK quand l'OHLC existe ; sur les séries sans OHLC, l'écran le dit.
5. **Convergence** : colonne « Convergence » dans chaque tableau, nombre d'échecs en tête, message de l'optimiseur disponible au survol, paramètres collés aux bornes signalés.
6. **Fréquences mixtes** : voir §4.
7. **Erreurs standards** : indiquer si elles sont robustes (QMLE de Bollerslev-Wooldridge) ; ne pas comparer des log-vraisemblances entre lois sans le dire.

## 7. Phasage

- **P0 (ce document)** : audit. Reste le **cours** : `docs/cours/econometrie/` (à créer), en français, 1 à 2 pages par sujet : formule exacte du test ou du modèle tel qu'utilisé à l'écran, comment lire le résultat, ce qui ressemble à un faux positif. Ordre du cadrage : stationnarité, ARMA, GARCH/GJR ; puis HAR, QLIKE/MCS. Chaque cours alimente l'aide et le glossaire de la page. Léon relit avant que le code correspondant commence.
- **P1a — socle + onglets 1 et 2** : module, route, page, cache, i18n, tests, nav ; ajoute PP, DF-GLS, Zivot-Andrews, BDS. Plus petit morceau qui prouve toute l'architecture.
- **P1b — onglet 3 (moyenne)**, **P1c — onglet 4 (variance)**, **P1d — onglet 7 (prévision)** : dans cet ordre, un cours avant chacun.
- **P2** : onglet 5 dans `/exploration` (VAR, IRF/FEVD, Johansen, VECM) ; onglet 6 (Markov-switching + lecture du HMM).
- **P3** : (a) nouvelles features ML walk-forward (GJR, APARCH, HAR…) **en option, hors du hachage de configuration par défaut**, comme l'interrupteur de l'ADR 0012 : les ajouter au hachage change les identifiants de tous les runs et invalide le golden master (régénération via une branche `golden-regen/<nom>`, voir la mémoire du projet) ; (b) DCC-GARCH comme estimateur supplémentaire de `tracking/covariance.py` (`COVARIANCE_ESTIMATORS`), consommé par HRP et `/portfolio`. `arch` n'a pas de DCC : implémentation maison, testée sur un processus DCC simulé à paramètres connus et sur des propriétés (matrice semi-définie positive, diagonale unitaire de la corrélation).
- Un ADR (0017) au démarrage de P1a : « page Économétrie : une série à la fois ; calculs descriptifs contre prévisions ; pas de meilleur modèle couronné ».

## 8. Hors périmètre (maintenant)

Analyse en lot sur tout le catalogue (« quelles séries ont des effets ARCH ? ») : possible plus tard comme tâche de nuit avec correction FDR, pas en P1. Bai-Perron et `ruptures`. Onglet 8. Toute modification des sorties ou des identifiants du pipeline avant P3. Toute recommandation de position.

## 9. Mes appels (à corriger si faux)

1. Page séparée `/econometrie` pour la série unique ; le multivarié va dans `/exploration` qui contient déjà Granger et Engle-Granger.
2. Pas de nouvelle catégorie de navigation.
3. Cache en fichiers via `LocalCache`, pas de migration SQLite (à confirmer au plan).
4. GARCH-M et ARFIMA exacts hors P1 ; IGARCH par contrainte α+β=1.
5. Calcul au clic dans un pool de threads, pas la file de runs.
6. Cours rédigés par moi en français dans `docs/cours/econometrie/`, relus par Léon avant chaque phase de code.
7. Les chiffres « 66 cibles / 105 séries » du cadrage sont remplacés par le catalogue réel (528 symboles).
