# Ways of working — PATRICK

Référence versionnée (la copie locale du PC A, hors dépôt, doit s'aligner
sur celle-ci). Mise à jour : 2026-09-25.

## Méthode

1. **Tout finding est SUSPECT tant qu'un test rouge ne l'a pas confirmé.**
   Le test est écrit et vu rouge *avant* le correctif, puis la correction
   est prouvée par mutation : le test doit échouer sur l'ancien code.
2. **Jamais deviner une cause** : mesurer sur données réelles quand c'est
   possible (cf. qualification GSPC, portes qualité, 2026-09-25).
3. **Un chantier = une branche**, commits fréquents (CONTRIBUTING.md),
   jamais de merge sur `main` sans confirmation explicite.
4. **Un monkeypatch ne corrige rien** : s'il masque un comportement (ex.
   sélection non déterministe entre OS), la cause racine est un bug ouvert.

## Protocole statistique (s'applique à TOUT modèle, sans exception)

- Walk-forward : purge/embargo à chaque frontière, y compris dans la CV
  interne d'Optuna (F02) et les découpes méta (stacking).
- Données point-in-time : séries FRED à leur date de publication (F01).
- Sélection sur la moyenne walk-forward, jamais sur le meilleur fold (F07).
- Diebold-Mariano avec correction HLN (F04), **unilatéral** : seul « le modèle fait mieux que sa baseline »
  compte (un modèle significativement moins bon n'est jamais une découverte, corrigé le 2026-10-07) ;
  famille Benjamini-Hochberg = toutes les cibles testées d'un même type, **brutes et alpha en familles
  séparées** (F05) ; DSR déflaté par le registre d'essais
  persistant (F03) ; holdout terminal jamais utilisé pour choisir.
- Simulations par segment statistique, jamais poolées (F06).

## Familles de modèles : plus d'exclusion a priori

**Le deep learning et le stacking ne sont plus exclus par principe.**
Les constats historiques du projet VIX restent des *résultats mesurés*
(« le DL n'a jamais battu le ML classique », « le stacking perd sur 93 % des
paires horizon/fold ») — ils ne sont plus des interdits de conception :

- le **stacking** est un algorithme de la grille depuis le 2026-10-23
  (`models/stacking.py`, nombre de modèles saisi à la main), jugé comme les
  autres candidats (DM/FDR/PBO) par (cible, horizon). La comparaison en trois
  catégories (global / par régime / stacking) esquissée en septembre n'a
  jamais été branchée au moteur et a été retirée le 2026-11-02 : la grille
  compare déjà un modèle global, des modèles par régime (`objective.regimes`)
  et le stacking ;
- le **DL** (séquentiel, TFT, modèles de diffusion) peut être introduit
  comme famille candidate **aux mêmes conditions** que le ML classique :
  même protocole ci-dessus, même registre d'essais (chaque configuration
  entraînée compte dans le DSR), budget d'essais déclaré à l'avance. Le
  cadrage détaillé (adéquation du protocole anti-surapprentissage au DL)
  est dans `docs/modelisation/cadrage-dl.md`.

La valeur par défaut d'une option reste la leçon mesurée
(`config/defaults.py`) ; lever un interdit n'est pas activer par défaut.
