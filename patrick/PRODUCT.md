# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Léon, utilisateur principal et unique à ce jour (outil local, pas de comptes ni de partage aujourd'hui). Chercheur indépendant en ML quantitatif sur séries temporelles financières : configure et lance des runs de backtest, suit leur progression, compare l'historique des résultats, éprouve la validité statistique de ce qu'il trouve, simule le rendement après frictions, et récupère le modèle gagnant — sans éditer de YAML à la main.

**Le partage est explicitement prévu à terme** (multi-utilisateur, comptes, ou déploiement distant) : les décisions de conception ne doivent pas s'enfermer dans l'hypothèse mono-utilisateur local, même si c'est l'état actuel. Corollaire : un écran doit rester compréhensible par quelqu'un qui n'a pas construit l'outil.

## Product Purpose

**Objectif visé** : un outil de quant trading qui entraîne des modèles de machine learning sur l'ensemble des tickers importés afin de construire une **stratégie globale**.

**État actuel** : le pipeline est mono-cible — un run entraîne et valide des modèles pour **une** `target_symbol` à la fois (550 cibles possibles : 507 tickers yfinance + 43 séries FRED), le reste de l'univers servant de features. Un run mono-cible validé est donc une *brique* de l'objectif, pas l'objectif. L'agrégation en stratégie globale n'est pas encore construite.

Le succès d'un run individuel n'est pas « un modèle qui marche » mais **un verdict honnête** : ce signal survit-il à la correction des tests multiples, et rapporte-t-il encore après frictions ? Un « non » clairement établi est un résultat réussi, pas un échec.

## Positioning

Contrairement aux notebooks ad hoc du projet VIX d'origine, `patrick` est pilotable par formulaire (pas de YAML manuel), agnostique à l'actif cible, et persiste l'historique complet de chaque run (SQLite) plutôt que des exécutions non tracées.

Ce qu'un outil voisin ne pourrait pas copier honnêtement : la chaîne de validité est **intégrée et non contournable**, pas un post-traitement optionnel — purge/embargo structurels, holdout terminal jamais utilisé pour choisir, compteur d'essais cumulé sur tout l'historique, Sharpe déflaté, PBO avec intervalle de confiance bootstrap, Diebold-Mariano contre baselines systématiques, et correction FDR **entre cibles** (essayer 550 cibles et ne garder que la significative est un biais que l'outil mesure au lieu de l'ignorer). Le simulateur applique ensuite les frictions réelles et le coût de rentabilité.

## Operating Context

- Exécution locale : `patrick serve` (CLI) ou `PATRICK.bat` (Windows), serveur FastAPI + Jinja2 sur `127.0.0.1`.
- **File d'attente FIFO** : un run soumis pendant qu'un autre tourne n'est jamais rejeté — il est mis en file et démarré automatiquement par un worker en process séparé (`patrick worker`, auto-lancé par le serveur). Les runs survivent au redémarrage du serveur web.
- **Deux rythmes d'usage à servir également** : petits runs de test suivis en direct (progression, logs), gros runs lancés puis abandonnés jusqu'au lendemain (parfois la nuit). Un run réel dure longtemps — ~380s rien que pour construire le pool de features, puis tout le scan. Retrouver l'état et les résultats au retour compte autant que le suivi minute par minute.
- Surfaces web : `/` (formulaire + suivi), `/simulate` (simulateur), `/runs` (historique), `/runs/{id}` (détail), `/targets/{ticker}` (vue par cible), `/universe` (univers de cibles).
- Surfaces CLI : `ingest`, `run`, `resume`, `report`, `predict --live`, `worker`, `serve`, `audit degradation`.
- Sources de données : yfinance (sans clé) + FRED (clé API optionnelle ; vintages ALFRED point-in-time quand la clé est présente, sinon repli avec avertissement explicite).
- Interface bilingue FR/EN (cookie), FR par défaut.

## Capabilities and Constraints

- **Mécanisme de la stratégie globale — tranché** : **portefeuille de signaux mono-cible combinés**, et non modèle transversal unique. L'architecture actuelle (un modèle par cible) est conservée ; une couche d'allocation vient au-dessus, transformant les signaux validés en poids de portefeuille. Choix incrémental : tout l'existant (pipeline, validité, persistance) est réutilisé tel quel.
- Allocation visée, **conditionnelle à sa propre fiabilité** : **risk parity / volatilité ciblée** en principal — les poids égalisent la contribution au risque, pas le capital. Cela introduit une estimation de covariance, qui est elle-même un objet à valider (elle sur-ajuste comme n'importe quel paramètre estimé, d'autant plus que le nombre de positions approche le nombre d'observations) et non un calcul de plomberie. **Repli décidé** : si la covariance est jugée trop bruitée, l'allocation bascule sur la **confiance des modèles** — métriques de validation disponibles (`F1_dir`, `Acc_dir`, `BalAcc_4cls`, `F1_4cls`, `MCC_4cls`) et probabilité prédite (`prediction.y_proba`, déjà persistée). Le critère de bascule doit être mesuré et affiché, jamais implicite.
- **Réserve à lever avant d'utiliser `y_proba` comme poids** : la calibration est **désactivée par défaut** (`DEFAULT_CALIBRATION_ENABLED = False`, leçon mesurée du projet VIX). Une « probabilité » non calibrée d'un XGBoost/RandomForest ordonne correctement mais ne vaut pas 0,8 = 80 % empiriques. Elle est donc défendable comme **rang** (trier, découper en paliers), pas comme **magnitude** linéaire d'un poids — sauf à réactiver la calibration pour les modèles destinés au portefeuille. Décision à prendre explicitement, pas par défaut silencieux.
- Réserve analogue sur les métriques de validation comme poids : ce sont des estimations sur folds finis, déjà porteuses de la dette de tests multiples que PBO/DSR/FDR servent à mesurer — les transformer en poids réinjecte ce biais dans le portefeuille.
- Aucun plafond a priori sur le nombre de positions : la taille du portefeuille est une **conséquence** des tests statistiques (ce qui passe le filtre entre), pas un réglage. Elle peut varier de quelques positions à plusieurs centaines selon les périodes — toute surface qui l'affiche doit encaisser les deux régimes.
- Un run = une cible, un ou plusieurs horizons, un ou plusieurs régimes.
- Deux schémas de validation au choix, jamais l'un imposé à l'autre : `walkforward` (défaut) ou `cpcv` (validation croisée purgée combinatoire, distribution de performance sur plusieurs chemins plutôt qu'un point). En mode CPCV, holdout terminal / tuning Optuna / Diebold-Mariano ne sont structurellement pas calculés — limite assumée et affichée, jamais masquée.
- Le simulateur d'investissement est **mono-actif** aujourd'hui, et ne ré-exécute jamais un modèle : il lit uniquement les prédictions déjà persistées. Il journalise toute simulation tentée (garde-fou anti-surapprentissage : le nombre de configurations essayées n'est jamais caché).
- Paper trading (`patrick predict --live`) : écrit la prédiction du jour **avant** de connaître le résultat, complété a posteriori.
- Vocabulaire du domaine à respecter tel quel dans l'UI (walk-forward, purge, embargo, SHAP/RFE/LASSO, sampler, Optuna, F1_dir, PBO, DSR, CPCV, calibration, stacking) — outil de recherche quant technique, pas un produit grand public à vulgariser. Le partage prévu ne change pas ce registre : il exige que les chiffres soient *interprétables*, pas que le vocabulaire soit dilué.
- Les valeurs par défaut du formulaire encodent des leçons mesurées du projet VIX d'origine (SHAP par défaut, stacking désactivé, sampler=SMOTE seul, embargo activé, calibration désactivée) — l'UI doit rester lisible sur ces choix, pas les masquer.
- Chaque brique de rigueur est explicitement activable/désactivable et le rapport indique lesquelles étaient actives — aucune ne doit devenir un défaut silencieux.
- Pas d'authentification aujourd'hui (état actuel, pas un principe durable : cf. partage prévu).

## Brand Commitments

Nom du produit : « PATRICK » — contrainte intouchable, le nom reste quelle que
soit l'identité visuelle. Il s'écrit en chasse fixe en tête du bandeau
(`.station-name`), pas en lettrage de marque.

**Un logo existe** (fourni par l'utilisateur : marque circulaire, anneau et
glyphe, nom en petites capitales sérif). Il est désormais intégré, sous forme
d'une **marque redessinée** (`.station-mark`) qui en garde la forme circulaire
et le glyphe enfermé, recolorée sur les jetons du boîtier ; le nom reste en
chasse fixe. Une version antérieure de ce document interdisait tout logo et
tout monogramme — cette consigne a été levée explicitement ; elle ne doit plus
être invoquée pour refuser une intégration.

Le monde visuel courant s'appelle « Station d'observation » ; ses règles
normatives sont dans `DESIGN.md` et `webapp/static/tokens.css`, pas ici.
