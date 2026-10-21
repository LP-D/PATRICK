# PATRICK

PATRICK entraîne des modèles de machine learning sur des séries financières pour **prédire la direction d'un actif** (quatre
classes : baisse forte, baisse faible, hausse faible, hausse forte, à un horizon donné), et surtout pour dire **honnêtement si
ce signal survit** à la validation statistique. Un « non » clairement établi est un résultat réussi.

Ce que le projet fait :

- un pipeline de recherche par actif : ingestion (Yahoo Finance, FRED avec vintages point-in-time), variables, sélection (SHAP),
  grille échantillonneur × algorithme, réglage Optuna, validation walk-forward ou CPCV, holdout terminal, export du modèle ;
- une chaîne de validité intégrée, non contournable : purge et embargo, holdout jamais utilisé pour choisir, compteur d'essais
  cumulé, Sharpe déflaté (DSR), probabilité de surapprentissage (PBO), test de Diebold-Mariano contre des baselines, correction
  du taux de fausses découvertes (BH) entre cibles ; méthodologie dans [`patrick/METHODOLOGY.md`](patrick/METHODOLOGY.md),
  limites mesurées dans [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) ;
- une application web locale « Cockpit Pro » (FastAPI + Jinja2) : lancer des runs (`/ml`, `/dl`, `/rl`), explorer des séries
  (`/exploration`), comparer l'historique, simuler le rendement après frictions, suivre les prédictions du jour, le patrimoine et
  des fonds simulés, les nouvelles (`/news`) ;
- une application de bureau Windows : une icône, mise à jour automatique, partage des résultats entre deux PC par un dossier.

Ce que le projet n'est pas : un conseil en investissement. Aucune page ne recommande d'acheter ou de vendre ; elle expose des
éléments pour que l'on juge soi-même.

## Installer (Windows)

PATRICK s'utilise comme une application : une icône sur le bureau, un double-clic. Elle suit la dernière version **validée par la
CI** (branche `stable`), démarre le serveur, ouvre la fenêtre, et partage les résultats entre plusieurs PC via un dossier
OneDrive choisi au premier démarrage (modifiable : engrenage > Réglages).

Installer sur un PC (Git et Python 3.11 ou plus sont installés au besoin) : double-clic sur `app\Installer.bat` après avoir
téléchargé le dépôt, ou, dans PowerShell :

    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/LP-D/PATRICK/main/app/Installer.ps1 | iex"

Mode d'emploi : [`app/LISEZMOI.txt`](app/LISEZMOI.txt). Fonctionnement et réglages : [`docs/ops/application-bureau.md`](docs/ops/application-bureau.md).

## En ligne de commande

Installation du paquet et référence des commandes : [`patrick/README.md`](patrick/README.md). Exemple :

    cd patrick
    pip install -e ".[web,dev]"
    patrick serve            # serveur local sur 127.0.0.1:8000

## Où lire quoi

| Pour | Document |
|---|---|
| Comprendre l'état du code | [`patrick/ARCHITECTURE.md`](patrick/ARCHITECTURE.md) |
| Comprendre la méthode et ses garde-fous | [`patrick/METHODOLOGY.md`](patrick/METHODOLOGY.md) |
| Savoir ce qui est limité ou ouvert | [`KNOWN_ISSUES.md`](KNOWN_ISSUES.md) |
| Savoir pourquoi une décision a été prise | [`docs/adr/`](docs/adr/README.md) |
| Tout le reste (exploitation, recherche, audits) | [`docs/index.md`](docs/index.md) |
| Contribuer | [`CONTRIBUTING.md`](CONTRIBUTING.md) |

## Tests

    cd patrick
    pytest                   # suite rapide
    pytest -m slow           # pipelines complets (long)
    pytest -m validity       # le pipeline sur des marches aléatoires : le protocole protège-t-il vraiment ?

## Politique de résultats

Les sorties expérimentales lourdes (CSV/XLSX, artefacts) vont sur des branches `results/<nom>` et ne sont pas destinées à être
fusionnées dans `main`.

## Licence

Tous droits réservés (copyright Léon, 2026) : voir [`LICENSE`](LICENSE). Le dépôt est public pour être consulté, pas pour être réutilisé :
aucune licence libre n'est concédée. Les polices de l'interface gardent leurs licences propres.
