# Vérification des 39 candidats features (2026-09-27)

**Périmètre** : `universe_extension.EXTENDED_FEATURE_CANDIDATES`, la liste de candidats features de la
branche `feature/replay-cache-universe` (39 tickers Yahoo), fusionnée dans `config/universe_extension.py`.
Même contrôle que `patrick audit tickers` (`patrick/data/ticker_check.py`) : historique Yahoo non vide,
dernière cotation à ≤ 7 séances, ≥ 750 séances.

**Deux vérifications indépendantes, même résultat** : sur le PC A (relevé transmis le 2026-09-27) et
depuis le conteneur de développement (tableau ci-dessous). 39/39 acceptés ; le plus court est ETH-USD,
3 244 séances.

## Fusion avec l'univers étendu

- 30 des 39 tickers étaient déjà des cibles vérifiées de `EXTENDED_TARGET_GROUPS` (2026-09-25).
- 9 sont ajoutés comme cibles (`ADDED_ON_2026_09_27`) : ^IXIC (« Indices mondiaux »), ^IRX, ^FVX, ^TNX,
  ^TYX (nouveau groupe « Taux US (indices CBOE) »), PL=F, PA=F, HO=F, RB=F (nouveau groupe
  « Matières premières (compléments) »). Première date servie par Yahoo relevée ci-dessous.
- Une seule source de vérité : chaque candidat feature est un symbole vérifié de l'univers étendu
  (`tests/test_universe_reduction.py`). L'univers de features par défaut ne change pas ; l'univers
  « étendu » reste un choix explicite du formulaire, à coupler avec la réduction par clustering.

## Détail

| Ticker | Statut | Séances | Première | Dernière | Retard (séances) | Motif |
|---|---|---:|---|---|---:|---|
| AUDUSD=X | ok | 5298 | 2006-05-16 | 2026-09-26 | 0 |  |
| ETH-USD | ok | 3244 | 2017-11-09 | 2026-09-27 | 0 |  |
| GBPUSD=X | ok | 5934 | 2003-12-01 | 2026-09-27 | 0 |  |
| HO=F | ok | 6545 | 2000-09-01 | 2026-09-25 | 0 |  |
| HYG | ok | 4897 | 2007-04-11 | 2026-09-25 | 0 |  |
| IEF | ok | 6079 | 2002-07-30 | 2026-09-25 | 0 |  |
| LQD | ok | 6079 | 2002-07-30 | 2026-09-25 | 0 |  |
| NZDUSD=X | ok | 5923 | 2003-12-01 | 2026-09-26 | 0 |  |
| PA=F | ok | 6581 | 1998-09-28 | 2026-09-25 | 0 |  |
| PL=F | ok | 6570 | 1997-10-29 | 2026-09-25 | 0 |  |
| RB=F | ok | 6506 | 2000-11-01 | 2026-09-25 | 0 |  |
| SHY | ok | 6079 | 2002-07-30 | 2026-09-25 | 0 |  |
| TLT | ok | 6079 | 2002-07-30 | 2026-09-25 | 0 |  |
| USDCAD=X | ok | 5990 | 2003-09-17 | 2026-09-26 | 0 |  |
| USDCHF=X | ok | 5987 | 2003-09-17 | 2026-09-25 | 0 |  |
| USDJPY=X | ok | 7756 | 1996-10-30 | 2026-09-26 | 0 |  |
| XLB | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLE | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLF | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLI | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLK | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLP | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLU | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLV | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| XLY | ok | 6982 | 1998-12-22 | 2026-09-25 | 0 |  |
| ^DJI | ok | 8745 | 1992-01-02 | 2026-09-25 | 0 |  |
| ^FCHI | ok | 9289 | 1990-03-01 | 2026-09-25 | 0 |  |
| ^FTSE | ok | 10795 | 1984-01-03 | 2026-09-25 | 0 |  |
| ^FVX | ok | 16171 | 1962-01-02 | 2026-09-25 | 0 |  |
| ^GDAXI | ok | 9797 | 1987-12-30 | 2026-09-25 | 0 |  |
| ^HSI | ok | 9807 | 1986-12-31 | 2026-09-25 | 0 |  |
| ^IRX | ok | 16668 | 1960-01-04 | 2026-09-25 | 0 |  |
| ^IXIC | ok | 14027 | 1971-02-05 | 2026-09-25 | 0 |  |
| ^N225 | ok | 15173 | 1965-01-05 | 2026-09-25 | 0 |  |
| ^RUT | ok | 9835 | 1987-09-10 | 2026-09-25 | 0 |  |
| ^STOXX50E | ok | 4886 | 2007-03-30 | 2026-09-25 | 0 |  |
| ^TNX | ok | 16171 | 1962-01-02 | 2026-09-25 | 0 |  |
| ^TYX | ok | 12429 | 1977-02-15 | 2026-09-25 | 0 |  |
| ^VXN | ok | 6457 | 2001-01-23 | 2026-09-25 | 0 |  |

39/39 ticker(s) acceptés.