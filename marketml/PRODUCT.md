# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Léon, seul utilisateur (outil local mono-utilisateur, pas de comptes ni de partage). Chercheur indépendant en ML quantitatif sur séries temporelles financières : configure et lance des runs de backtest walk-forward, suit leur progression, compare les résultats (leaderboard) et récupère le modèle gagnant — sans éditer de YAML à la main.

## Product Purpose

`patrick` généralise la méthodologie mise au point sur un projet de recherche spécifique au VIX (notebooks `../notebooks/`) en un pipeline ML/DL configurable pour n'importe quel actif/indice : walk-forward strict, features avancées, sélection de features, grille sampler×algo, tuning Optuna. Le succès = obtenir un modèle validé honnêtement (pas de fuite) sur la cible choisie, avec le minimum de friction de configuration.

## Positioning

Contrairement aux notebooks ad hoc du projet VIX d'origine, `patrick` est pilotable par formulaire/config (pas de YAML manuel), agnostique à l'actif cible, et persiste l'historique complet de chaque run (SQLite : snapshot/run/trial/fold_metric/prediction) plutôt que des exécutions de notebook non tracées.

## Operating Context

- Exécution locale : `patrick serve` (CLI) ou `PATRICK.bat` (Windows), serveur FastAPI+Jinja2 sur `127.0.0.1`.
- Un seul run actif à la fois (contrainte assumée et appliquée côté serveur, 409 sinon).
- Flux : partir des défauts ou charger un exemple de config → ajuster via formulaire → lancer → suivre la progression (polling `/status`) → consulter le leaderboard → télécharger les artefacts (CSV/Excel/modèle joblib).
- Sources de données : yfinance (sans clé) + FRED (clé API optionnelle, sinon repli scrape avec avertissement explicite dans les logs).
- Interface bilingue FR/EN (cookie), FR par défaut.

## Capabilities and Constraints

- Vocabulaire du domaine à respecter tel quel dans l'UI (walk-forward, purge, embargo, SHAP/RFE/LASSO, sampler, Optuna, F1_dir, calibration, stacking) — outil de recherche quant technique, pas un produit grand public à vulgariser.
- Les valeurs par défaut du formulaire encodent des leçons du projet VIX d'origine (documentées dans `README.md` : SHAP par défaut, stacking désactivé, sampler=SMOTE seul, embargo activé, calibration désactivée) — l'UI doit rester lisible sur ces choix, pas les masquer.
- Pas d'authentification (outil local mono-utilisateur).

## Brand Commitments

Nom du produit : « PATRICK » (titre affiché dans l'onglet navigateur). Aucune identité visuelle formalisée au-delà du CSS existant (`patrick/webapp/static/style.css`) — monde visuel non documenté à ce stade (relève de `/impeccable document`, pas de cet init).

## Evidence on Hand

- `marketml/README.md` : méthodologie complète et justification des défauts.
- Templates existants : `index.html` (formulaire de config), `run.html` (suivi + résultats).
- Assets existants : `static/style.css`, `app.js`, `market.js`, `glossary.js`.
- Exemples de config réels : `configs/examples/vix_direction.yaml`, `aapl_direction.yaml`.
- Données de marché réelles via yfinance/FRED (pas de données fictives/mock en usage normal).

## Product Principles

- Config avant code : tout choix du pipeline doit être atteignable depuis le formulaire, sans édition manuelle de YAML pour un usage standard.
- La rigueur reste visible, pas masquée : les choix de validation (purge, embargo, folds walk-forward) et leur justification restent lisibles dans l'UI, pas abstraits.
- Une seule source de vérité par run : un run actif à la fois, historique complet persisté (SQLite + leaderboard), rien n'est silencieusement perdu.
- Outil solo, pas un produit : construit pour le flux de travail de recherche personnel de l'auteur — pas d'onboarding, de multi-utilisateur ni de surface marketing à prévoir.
- Bilingue par défaut (FR/EN) : reflète l'usage réel (utilisateur francophone principal, repli anglais).
