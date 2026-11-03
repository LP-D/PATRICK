# ADR 0017 — Page Économétrie : une série à la fois, descriptif contre prévision, aucun modèle couronné

Date : 2026-11-03. Statut : appliquée (page `/econometrie`, paquet `patrick/econometrics/`, onglet Multivarié de `/exploration`). Cadrage : `docs/superpowers/specs/2026-11-03-econometrie-serie-design.md`. Cours (formules, lecture, exemples chiffrés) : `docs/cours/econometrie/cours-econometrie.md`.

## Contexte

Le projet avait déjà, dans `/exploration`, des études entre actifs (ADF/KPSS, ACF, Ljung-Box, Granger, Engle-Granger…) et, dans le pipeline, des variables issues de modèles (EGARCH, HMM, Kalman, résidu ARIMA) réestimées pli par pli. Il manquait un endroit où poser à **une** série les questions classiques de l'économétrie (stationnarité, dépendance, moyenne, variance, régimes, prévision) et lire des réponses honnêtes. Un cadrage rédigé hors dépôt a été confronté à l'existant : pas de nouvelle catégorie de navigation (il y en avait déjà cinq), Python 3.14 et non 3.10, tests de base déjà présents.

## Décisions

1. **Une page par série, le multivarié dans `/exploration`.** `/econometrie` (Pilotage › Recherche) traite une série à la fois ; VAR, réponses impulsionnelles, décomposition de la variance, Johansen et VECM vont dans l'onglet Multivarié de `/exploration`, qui contient déjà Granger et Engle-Granger.
2. **Calculs purs.** `patrick/econometrics/` n'accède ni au web, ni à la base, ni au réseau ; chaque fonction renvoie un dict JSON. Les fonctions déjà présentes (`exploration/studies.py`, `validation/diebold_mariano.py`, `validation/fdr.py`, `features/regime_detection.py`, `features/fracdiff.py`) sont **réutilisées**, pas copiées.
3. **Descriptif contre prévision.** Un modèle ajusté sur tout l'échantillon est affiché comme descriptif. Seul l'onglet Prévision réestime sur le passé uniquement (fenêtre expansive ou glissante, paramètres figés entre deux réestimations) ; un test vérifie qu'aucune prévision ne dépend du futur.
4. **Aucun modèle couronné.** Le modèle constant est toujours la référence de la grille de moyenne ; le verdict (« aucun modèle ne bat la constante ») est la première ligne d'un onglet ; les spécifications essayées sont comptées et les p-values corrigées par Benjamini-Hochberg ; les comparaisons de prévisions passent par le QLIKE, Mincer-Zarnowitz, Diebold-Mariano corrigé et le Model Confidence Set.
5. **Les échecs s'affichent.** Un modèle qui échoue ou ne converge pas est une ligne du tableau (message de l'optimiseur, erreurs-types manquantes, persistance ≈ 1 signalées).
6. **Calculé une fois.** Cache de résultats en fichiers JSON compressés sous `<cache>/econometrics/` (écriture atomique, éviction au-delà de 600 entrées), clé = empreinte de l'étude, de la série (valeurs comprises), des paramètres et de la version du code. Pas de migration SQLite.
7. **Calcul au clic dans un pool de threads**, comme l'exploration ; pas de passage par la file des runs.
8. **Échelle.** Les rendements sont multipliés par 100 avant d'être donnés à `arch` ; les paramètres de variance sont en %².

## Pièges rencontrés (à ne pas redécouvrir)

- `statsmodels` repasse la **même graine** à chaque réplication de `irf_resim` / `errband_mc` : avec une graine fixe, les réplications sont identiques et la bande des réponses impulsionnelles se réduit à un point. La boucle de Monte-Carlo est écrite dans `econometrics/multivariate.py` (test de non-régression).
- `hmmlearn` ajoute un plancher de variance de 10⁻³ : sur des rendements décimaux (variance ~10⁻⁴) les états ne se distinguent plus ; on travaille en pourcent. L'EM tombe parfois sur un optimum local : on garde le meilleur de trois départs.
- `arch` ne propose pas GARCH-M, IGARCH, DCC ; `statsmodels` ne propose pas ARFIMA ni Bai-Perron. IGARCH est l'EWMA de RiskMetrics à λ estimé ; l'ordre fractionnaire est estimé par GPH, sans ARFIMA conjoint.
- Un test à 5 % se trompe une fois sur vingt : les tests de la bibliothèque vérifient des fréquences sur plusieurs tirages, pas un tirage chanceux.

## Conséquences

- Nouvelles entrées : route `/econometrie`, API `/api/econometrics/{étude}` (9 études), études `var` et `johansen` de `/api/exploration`. Le registre de navigation gagne `econometrics` (ordre 43) ; News, Carnet et Résultats passent à 44, 45, 46.
- `pyproject.toml` inchangé : `arch`, `statsmodels`, `hmmlearn`, `scipy` étaient déjà des dépendances. La CI installe les dernières versions : le piège `statsmodels` 0.15 déjà rencontré reste à surveiller (aucun `except` large n'avale une rupture d'API sans la signaler à l'écran).
- **Non fait** (voir le cours, §10) : GARCH-M ; ARFIMA exact ; Bai-Perron ; DCC-GARCH vers la covariance de `/portfolio` ; variables GJR/APARCH/HAR en walk-forward pour le pipeline (elles changeraient l'empreinte de configuration de tous les runs et invalideraient le golden master : à faire en option, hors de l'empreinte par défaut, comme l'ADR 0012) ; EVT, ondelettes, entropie.
