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

- **Décision produit ouverte, non tranchée** : par quel mécanisme la « stratégie globale » agrège-t-elle les tickers ? Portefeuille de signaux mono-cible combinés, ou modèle transversal unique entraîné sur tous les tickers à la fois ? Les deux impliquent des architectures très différentes. À trancher avant toute conception qui en dépend — ne pas présumer.
- Un run = une cible, un ou plusieurs horizons, un ou plusieurs régimes.
- Deux schémas de validation au choix, jamais l'un imposé à l'autre : `walkforward` (défaut) ou `cpcv` (validation croisée purgée combinatoire, distribution de performance sur plusieurs chemins plutôt qu'un point). En mode CPCV, holdout terminal / tuning Optuna / Diebold-Mariano ne sont structurellement pas calculés — limite assumée et affichée, jamais masquée.
- Le simulateur d'investissement est **mono-actif** aujourd'hui, et ne ré-exécute jamais un modèle : il lit uniquement les prédictions déjà persistées. Il journalise toute simulation tentée (garde-fou anti-surapprentissage : le nombre de configurations essayées n'est jamais caché).
- Paper trading (`patrick predict --live`) : écrit la prédiction du jour **avant** de connaître le résultat, complété a posteriori.
- Vocabulaire du domaine à respecter tel quel dans l'UI (walk-forward, purge, embargo, SHAP/RFE/LASSO, sampler, Optuna, F1_dir, PBO, DSR, CPCV, calibration, stacking) — outil de recherche quant technique, pas un produit grand public à vulgariser. Le partage prévu ne change pas ce registre : il exige que les chiffres soient *interprétables*, pas que le vocabulaire soit dilué.
- Les valeurs par défaut du formulaire encodent des leçons mesurées du projet VIX d'origine (SHAP par défaut, stacking désactivé, sampler=SMOTE seul, embargo activé, calibration désactivée) — l'UI doit rester lisible sur ces choix, pas les masquer.
- Chaque brique de rigueur est explicitement activable/désactivable et le rapport indique lesquelles étaient actives — aucune ne doit devenir un défaut silencieux.
- Pas d'authentification aujourd'hui (état actuel, pas un principe durable : cf. partage prévu).

## Brand Commitments

Nom du produit : « PATRICK » (titre affiché dans l'onglet navigateur). Le monogramme « P » en cercle doré (`.brand-mark`, en-tête de toutes les pages) est un **placeholder CSS, pas un logo réel** — à remplacer si un logo est un jour fourni (cf. commentaire au-dessus de `.brand-mark` dans `static/style.css`). Charte visuelle existante : fond sombre, accent or, sérif Cormorant Garamond pour les titres, Inter pour le texte ; jetons centralisés dans `static/tokens.css`.

## Evidence on Hand

- `METHODOLOGY.md` : document de référence principal (13 sections) — justification mesurée de chaque choix méthodologique, limites connues, anti-patterns explicitement refusés, et les rapports de correction (fuite, PBO, holdout, inf).
- `README.md` : méthodologie et justification des défauts.
- Gabarits : `index.html`, `simulate.html`, `runs.html`, `run_detail.html`, `target.html`, `universe.html`, `base.html`, `_components.html`.
- Assets : `static/tokens.css`, `style.css`, `app.js`, `market.js`, `glossary.js`, `simulate.js`.
- Exemples de config réels : `configs/examples/vix_direction.yaml`, `aapl_direction.yaml`.
- Données de marché réelles via yfinance/FRED — **pas de données fictives/mock en usage normal** ; les tests utilisent des sources monkeypatchées, jamais le réseau.
- Absence à ne pas combler par invention : aucun résultat de performance publié, aucun track record réel, aucun utilisateur tiers à ce jour.

## Product Principles

- **Config avant code** : tout choix du pipeline doit être atteignable depuis le formulaire, sans édition manuelle de YAML pour un usage standard.
- **La rigueur reste visible, pas masquée** : les choix de validation et leurs limites restent lisibles dans l'UI, jamais abstraits ni enjolivés.
- **Aucun chiffre sans sa contrepartie de fiabilité** : intervalle de confiance, taille d'échantillon, ou mention explicite de non-calculabilité — jamais un nombre nu.
- **Rien n'est silencieusement perdu ni silencieusement par défaut** : historique complet persisté, exclusions et garde-fous motivés et annoncés.
- **Un verdict négatif est un livrable** : l'outil doit rendre aussi lisible « ce signal ne tient pas » que « ce signal tient » — c'est la valeur principale.
- **Bilingue par défaut (FR/EN)** : reflète l'usage réel (francophone principal, repli anglais).
