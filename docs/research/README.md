# Études de recherche — événements et données horodatées

Commande : `patrick research event-study --ticker T (--events CSV | --earnings) [--benchmark ^GSPC] [--pre -5 --post 20]`.
Module : `patrick/research/event_study.py` (MacKinlay 1997), sources d'événements `patrick/research/event_sources.py`.
Garde-fou d'horodatage pour toute feature NLP / données alternatives : `patrick/features/event_features.py`.

## Règle de J0 (et bug corrigé le 2026-09-26)

J0 = première séance dont la clôture suit **strictement** la publication. Yahoo horodate les résultats publiés
après clôture à 16:00:00 ET pile ; l'ancienne règle (`>` au lieu de `>=`) les rattachait à la séance *précédant*
l'annonce. Mesuré sur les 69 publications NFLX : |AR J0| moyen 2,4 % avec l'ancienne règle (séance sans
information, la réaction tombait en J+1), 10,4 % avec la règle corrigée. Toute analyse sur une fenêtre [0, 0]
concluait à tort à l'absence de réaction.

Pour les **features** (`event_features.visible_session`), la convention sur une date sans heure est inverse de
celle de l'étude d'événements : l'étude suppose l'heure la plus précoce plausible (pré-ouverture, pour mesurer la
réaction du jour), une feature doit supposer la plus tardive (visible à la séance suivante) — sinon fuite.

## Tests

| Question | Test | Remarque |
|---|---|---|
| Dans quel sens, en moyenne ? | BMP (Boehmer-Musumeci-Poulsen 1991), signe | Robuste à la hausse de variance à l'événement |
| Le prix bouge-t-il plus que d'habitude, quel que soit le sens ? | Rang de \|CAR\| parmi les sommes de même longueur de la fenêtre d'estimation | Taille mesurée 3 % à 5 % nominal sous t(3) |
| Idem, paramétrique | χ² sur z² | Sur-rejette sous queues épaisses : 15,5 % à 5 % nominal sous t(3) → indicatif seulement |

Le test non signé est le bon pour un keynote ou des résultats sans conditionnement sur la surprise : les réactions
positives et négatives s'annulent dans le CAAR.

## Résultats sur données réelles (prix Yahoo, 2026-09-26)

**Keynotes iPhone, AAPL vs S&P 500, 19 événements 2007-2025** ([rapport](event-study-apple-keynotes.md)).
- Non signé : z² moyen 3,1 sur [0, +1], p rang < 0,001 — le titre bouge nettement plus que d'habitude.
- Signé : CAAR [0, +1] -0,70 %, p BMP 0,22 ; 13 réactions négatives sur 19, p signe 0,17. Le « sell the news »
  souvent cité n'est **pas** établi statistiquement sur cet échantillon.
- Dates des keynotes établies de mémoire : **à vérifier** contre Apple Newsroom avant toute conclusion publiée
  (le fichier CSV le signale).

**Résultats trimestriels, NFLX vs S&P 500, 69 publications 2006-2026** ([rapport](event-study-netflix-earnings.md)).
- Non signé : z² moyen 15,8 — un jour de résultats vaut environ 4 écarts-types d'un jour ordinaire.
- Conditionner sur la surprise de BPA ne donne **aucun** sens : « beat » -0,58 %, « miss » +0,56 % sur [0, +1]
  (p BMP 0,60 et 0,94). Pour Netflix le marché réagit aux abonnés et aux prévisions, pas au BPA : la surprise de
  BPA est la mauvaise variable de conditionnement. Les abonnés ne sont plus publiés depuis 2025 ; une source
  horodatée des révisions de consensus serait nécessaire.
- Horodatages Yahoo anciens douteux (2008-07-25 07:00, surprise +516 % en 2006 sur un BPA estimé quasi nul) :
  la liste 2006-2010 est à recouper.

## Limites communes

- Fenêtres d'estimation [-250, -21] : un événement précédé d'un autre choc (2008, mars 2020) a un σ gonflé et
  un z² réduit — conservateur, pas biaisé en sens inverse.
- Un seul actif par étude : les événements ne sont pas en coupe transversale indépendante (volatilité groupée) ;
  le portefeuille en temps calendaire n'est pas implémenté.
- Aucune source NLP n'est branchée : les actualités yfinance ne renvoient que les derniers articles (pas
  d'historique d'entraînement). Une archive licenciée avec horodatage de **première diffusion** est le
  prérequis ; elle devra passer par `event_features.align_items` (refus explicite d'un `published_at` manquant).
