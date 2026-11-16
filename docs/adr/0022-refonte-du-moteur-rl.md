# ADR 0022 — Refonte du moteur de reinforcement learning (moteur 2)

Date : 2026-11-16. Statut : codée et testée sur la branche `feat/rl-refonte`. Analyse qui la motive :
[analyse-rl-2026-11-16](../modelisation/analyse-rl-2026-11-16.md). Code : `rl/config.py`, `rl/core.py`, `rl/env.py`, `rl/agents.py`,
`rl/walkforward.py`, `rl/metrics.py`, `rl/run.py`, `config/defaults.py` (`DEFAULT_RL`, `RL_LEGACY_SETTINGS`, `RL_ENGINE_VERSION`),
`config/rl_profiles.py`, page /rl.

## Contexte

Sur 456 runs du moteur 1 (tous PPO, positions −1/0/+1, décision quotidienne, aucune validation), le RL battait acheter-garder dans 19,5 %
des runs ; sur le périmètre sans artefact, 5 runs significatifs pour ~21 attendus au hasard. La décomposition des séries hors échantillon
montre un petit talent de timing (+4 %/an brut) rendu en frais (rotation 66, 4,6 %/an), une jambe courte perdante (−1,6 %/an) et un
sur-apprentissage quand on entraîne plus. Les seuls Sharpe élevés venaient des devises, où le moteur RL n'appliquait pas la règle des
séances de l'ADR 0007 (fuite des barres datées du début de journée).

## Décision

1. **Règle des séances** : `run_rl` fixe `objective.session_rule = CURRENT_SESSION_RULE` avant l'ingestion, comme `run_pipeline`.
2. **Positions longues seulement par défaut** (`allow_short = False` : 0, ½, 1). La vente à découvert reste un réglage (profil « Long et court »).
3. **Une décision toutes les `rebalance_every` barres (5)** : l'environnement Gymnasium avance de 5 barres par pas, la récompense est la
   somme des récompenses par barre, les frais ne sont payés qu'au changement. L'évaluation (`rollout`) consulte la politique au même rythme.
4. **Frais × `train_cost_mult` (2) à l'entraînement** seulement ; l'évaluation et les références paient les vrais frais.
5. **Récompense `excess` (défaut)** : log(1 + net) − log(1 + rendement de l'actif). Le terme retiré ne dépend pas des actions (dates
   d'épisode tirées indépendamment de la politique) : même politique optimale que `log`, variance réduite.
6. **Validation par pli** (`val_frac` = 0,2) : la fin de la fenêtre d'entraînement, après un jour d'écart, n'est ni apprise ni utilisée pour
   choisir ou mettre à l'échelle les variables. `train_agent(validate=)` la score 10 fois pendant l'entraînement et recharge le meilleur point
   de contrôle. Score = log-croissance annualisée au-delà d'acheter-garder, nette des vrais frais. Validation abandonnée si elle ferait moins
   de 60 lignes ou laisserait moins de 250 lignes à apprendre.
7. **Repli** (`gate`, défaut activé) : si l'ensemble des agents ne bat pas acheter-garder en validation (score ≤ 0), le pli tient
   acheter-garder (position `min(1, levier)`). L'agent sans repli reste publié (`agent_ungated`, courbe `agent`, colonne par pli) et
   `strategy.agent_share` donne la part des dates où l'agent a eu la main.
8. **Références et diagnostics** : référence « tendance 200 j » (investi au-dessus de la moyenne des 200 dernières barres, à plat sinon) et
   écart de Sharpe contre elle ; test du décalage d'un jour (Sharpe brut des positions, puis décalées d'une barre ; signalé si le brut
   dépasse 1 et que le décalé en garde moins de 30 %) ; résumé enrichi (rendement brut, frais, jambes longue et courte, annualisés).
9. **Compatibilité** : `RLSettings.engine_version` (2). Une configuration COMPLÈTE du moteur 1 (tous ses réglages, aucun du moteur 2 ; les
   463 configurations RL en base le sont) reçoit `RL_LEGACY_SETTINGS` pour les réglages absents : relancer un ancien run rejoue le moteur 1.
   Un dictionnaire partiel reçoit les défauts du moteur 2. Profil « Moteur 1 (comparaison) » pour comparer sur une même cible.
10. **Lecture d'un run dans l'interface** (`rl/reading.py`, ajout du 16/11 au soir) : toutes les pages qui affichent un run RL
    (Historique et son panneau, /rl, comparaison, page d'analyse, nuage de /analyses, journal du run) montrent les mêmes chiffres : un
    verdict (fuite probable, non négociable, = acheter-garder, bat acheter-garder à 5 %, au-dessus sans preuve, sous acheter-garder), le
    moteur, la croissance par an au-delà d'acheter-garder, la part de l'agent et les frais par an. Pour le moteur 1, ces chiffres sont
    reconstitués (log(1 + CAGR) − log(1 + CAGR de BH), part 100 %, coûts × 252 / séances) et le test du décalage d'un jour est rejoué
    sur `rl_oos.csv` quand le run battrait acheter-garder. Le rendement total et le momentum 20 j quittent les vues de tête (le momentum
    reste pour un run du moteur 1, qui n'a pas la tendance 200 j).

## Conséquences

- **Banc d'essai** (20 cibles, mêmes données, analyse section 6) : Sharpe médian 0,14 → 0,38 (BH 0,51), mieux sur 18 cibles sur 20
  (+0,32 en moyenne, t = 5,8), rotation 56 → 4, frais 3,9 → 0,3 %/an, croissance face à BH −9,4 → −1,3 %/an. Le repli seul : +0,07.
  Aucune cible négociable ne bat BH de façon significative : le moteur 2 cesse de détruire de la valeur, il n'en crée pas.
- Les runs du moteur 1 ne sont ni réécrits ni supprimés ; ils restent comparables (Historique, comparaison) avec leurs réglages effectifs.
- Sur les 458 runs RL terminés de la base au 16/11, la lecture en retient 6 qui battent acheter-garder sans alerte (11 avant le test du
  décalage rejoué : ^STI, ^TWII, ^KS11, ^AXJO et ^N225 perdent 70 à 95 % de leur Sharpe brut quand les positions sont décalées d'un jour).
  Les 6 restants sont tous du moteur 1 (deux actions en chute, CO.PA et WLN.PA, jouées à la baisse ; ALI=F, HRC=F, ^NSEI, SHY).
- Le Sharpe d'un run du moteur 2 se lit avec `agent_share` : un run entièrement replié EST acheter-garder (message dans les avertissements).
  Le Sharpe déflaté compte toujours les runs terminés de la cible, moteurs confondus.
- Un pli coûte autant qu'avant : l'environnement fait 5 barres par pas (calcul NumPy négligeable), les 10 validations sont des rejeux
  déterministes de quelques centaines de barres. La partie apprise perd 20 % de la fenêtre.
- Limites : la validation est courte (un an et demi à trois ans selon le pli), son score est bruité ; le repli protège surtout contre
  l'agent qui sur-échange ou parie contre la dérive. Le RL reste sans preuve de signal négociable sur les actions tant que le banc d'essai
  et de nouveaux runs ne montrent pas l'inverse. Les runs des devises du moteur 1 sont à relire comme des artefacts.
