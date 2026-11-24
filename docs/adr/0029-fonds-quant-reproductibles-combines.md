# ADR 0029 — Fonds quant, fonds reproductibles de 5 000 €, performance avant frais et fonds de test combinés

Date : 2026-11-24. Statut : acceptée. Code : `fund/store.py` (`CATEGORIES`, `set_terms`), `fund/asset_classes.py` (`Family.category`, `fee_flat`,
`min_position`, `_provision`), `fund/real_funds.py` (`fund_name`, `_rename_legacy`), `fund/kpis.py` (`gross_nav`, `edge_verdict`), `fund/service.py`
(`_totals`, `overview`), `fund/combo.py` (nouveau), `fund/systematic.py` (mode `combo`, `decide_directional(strong, weights)`), `fund/autopilot.py`
(`Settings.combo`, `run_all(needs_rl)`), `rl/live.py` (nouveau), `live/refresh.py`, migration `0054_rl_live_position.sql`, `webapp/templates/fonds.html`,
`_fund_overview.html`, `_fund_panel.html`, `webapp/static/fonds.js`, `cli.py` (`fund combo-setup`, `fund rl-live`).
Tests : `tests/fund/test_fund_before_fees.py`, `tests/fund/test_fund_combo.py`, `tests/rl/test_rl_live.py`, et les tests des gammes mis à jour.

## Contexte

Demande de Léon (23/11) :

1. distinguer clairement les fonds « quant » (vente à découvert, capital d'étude) des fonds CTO et PEA qu'un particulier pourrait reproduire ;
2. ces fonds reproductibles à 5 000 €, et des totaux séparés ;
3. voir la performance sans les frais, pour savoir si l'avantage est perdu à cause des frais ou s'il n'y en a pas ;
4. dans d'autres fonds, combiner les modèles ML/DL avec les agents RL et les modèles qui prévoient la volatilité, au lieu de trader chaque signal tel quel.

Avant : les gammes CTO et PEA de l'ADR 0028 étaient en catégorie `quant`, avec 10 M€ ou le plafond du PEA (150 000 €), et un seul total consolidé
additionnait un capital virtuel de 10 M€ et des fonds de 5 000 €. Le seul P&L affiché était net de frais.

## Décisions

1. **Trois catégories** (`store.CATEGORIES`), une section chacune sur `/fonds`, **jamais de total général** :

   | Catégorie | Fonds | Conditions |
   |---|---|---|
   | `quant` : fonds quant (Systematic) | gamme `Systematic` (par classe, par preuve) | CTO, 10 M€ virtuels, vente à découvert par CFD, frais estimés |
   | `real` : fonds reproductibles CTO / PEA | gammes `CTO` et `PEA` (par classe, par preuve), `CTO Tous signaux`, `PEA Tous signaux` | 5 000 €, 1 € par ordre tout compris, 200 € au moins par position, achat seulement |
   | `lab` : fonds de test combinés | les quatre `Combiné …` | comme `quant` |

   Une synthèse compare les catégories et les enveloppes (CTO, PEA) côte à côte ; chaque groupe d'enveloppe a son sous-total. L'API garde le total
   consolidé (`overview()["fund"]`) pour la compatibilité, la page ne l'affiche plus.
2. **Les gammes CTO et PEA deviennent reproductibles** (`Family.category = "real"`, `fee_flat = 1 €`, `min_position = 200 €`, capital 5 000 €). Une
   stratégie existante sans ordre prend ces conditions à la prochaine création (`store.set_terms`) ; une stratégie qui a déjà tradé garde ses frais et son
   capital (refus explicite), seule sa catégorie peut suivre. Les 17 stratégies CTO et PEA de la vraie base ont été basculées le 23/11 avant le cycle de
   nuit (aucune n'avait d'ordre ; sauvegarde des lignes : `D:\PATRICK DATA\backups\fonds-cto-pea-avant-5000-2026-11-23.json`).
3. **« Systematic » ne désigne plus que les fonds quant** : les fonds réels de l'ADR 0026 `Systematic CTO` et `Systematic PEA` sont renommés
   `CTO Tous signaux` et `PEA Tous signaux` (`real_funds._rename_legacy`, au premier `real_funds.setup`, seulement si l'ancien est de catégorie `real`).
4. **Performance avant frais** : valeur avant frais = valeur nette + frais cumulés + financement cumulé (CFD), jour par jour (`kpis.gross_nav`). Pour
   chaque stratégie et chaque total : P&L avant frais, coûts, Sharpe avant frais, part du gain avant frais mangée par les coûts, et une lecture
   (`kpis.edge_verdict`) :
   - `no_edge` : même sans frais, la stratégie ne gagne pas : le signal ne vaut rien ici ;
   - `eaten` : gain avant frais, perte (ou zéro) après : les frais mangent l'avantage ;
   - `kept` : gain après frais ;
   - `none` : aucun ordre.

   Le graphique ajoute la courbe avant frais (pointillés). Sous 60 séances, un avertissement rappelle que l'échantillon est court.
5. **Fonds de test combinés** (`fund/combo.py`) : quatre fonds en pilote automatique, mêmes modèles (niveau `auc`, horizon 1, 100 modèles au plus),
   mêmes conditions, **un seul ingrédient qui change**. Chacun se lit contre `Combiné Référence` :

   | Fonds | Décision d'une séance |
   |---|---|
   | `Combiné Référence` | le signal de direction brut, taille fixe (le témoin) |
   | `Combiné ML + RL` | l'agent RL de la cible doit être d'accord : achat ML ⇒ agent acheteur ; vente ML ⇒ agent à plat ou vendeur ; sinon pas de position. Sans agent crédible ou sans position RL récente (5 jours), le signal ML passe seul |
   | `Combiné ML + volatilité` | volatilité prévue de l'actif (RiskMetrics, moyenne exponentielle, λ = 0,94) ; modèle ML de l'indice de volatilité de la classe (VIX pour actions, indices et crypto ; OVX pétrole ; GVZ or ; MOVE taux) ; filtre de coût |
   | `Combiné ML + RL + volatilité` | les deux |

   - **Filtre de coût** : gain attendu = conviction × 0,8 × σ prévue × √(horizon × durée de tenue attendue) × facteur de régime, où conviction =
     |2 P(hausse) − 1|, 0,8 ≈ E|r|/σ d'un rendement normal, et la durée de tenue vient de la persistance du signal sur le holdout (au plus 10 horizons).
     Ouverture seulement si ce gain ≥ aller-retour × `cost_multiple` (frais estimés de l'instrument, change et financement du CFD compris). Sinon le
     signal ne fait que renouveler une position déjà ouverte dans le même sens (garder ne coûte rien) ou fermer une position opposée.
   - **Taille** : conviction / (2 × conviction médiane) × min(1, σ de référence d'un an / σ prévue) × facteur de régime, bornée entre 25 % et 100 %
     de la taille de la règle.
   - **Régime** : si le modèle de l'indice prévoit une hausse de la volatilité (P = 0,75 ⇒ facteur 0,5), les achats d'actifs risqués et les ventes de
     valeurs refuges (or) sont réduits ; pour les taux, seule la taille baisse.
   - **Passé figé** : les décisions de chaque séance passée sont écrites dans la règle (`combo_log`) au premier cycle qui suit ; un signal révisé, un
     cours corrigé ou une position RL recalculée ne réécrit jamais une décision déjà prise. Changer d'agent RL, de modèle de régime ou de
     `cost_multiple` retire la règle et en commence une autre (`autopilot._signature`).
6. **Positions live des agents RL** (`rl/live.py`, table `rl_live_position`) : un run RL s'arrête à sa dernière date. Chaque nuit, l'agent du dernier
   pli du meilleur run crédible de la cible (moteur 2, lecture « bat » ou « au-dessus » d'acheter-garder, décalage non suspect, dernier pli non replié,
   modèles présents) est rejoué sur les données du jour : mêmes variables, même mise à l'échelle (ajustée sur les dates d'entraînement du pli), même
   cadence, en repartant de la position du fichier hors échantillon. Garde-fous : un pli replié n'a pas d'avis ; si le rejeu retrouve moins de 80 % des
   positions d'origine sur la fenêtre du pli (`drift`), rien n'est écrit ; une séance enregistrée n'est jamais réécrite ; une séance rattrapée après
   coup est marquée `backfill`.
7. **Ordre de la nuit** (`live/refresh.run_autopilots`) : les fonds qui ne lisent pas de RL d'abord, puis le rejeu des agents nécessaires, puis les
   fonds combinés « RL ». Les modèles des indices de volatilité sont prédits avec les autres cellules des fonds (`combo.auxiliary_cells`).
8. **Création** : un bloc « Test · fonds combinés » dans la carte unique de `/fonds` (`POST /api/fund/combo`, `dry_run` pour l'aperçu) ; commande
   `patrick fund combo-setup [--create] [--only reference|rl|vol|full] [--cost-multiple]` ; `patrick fund rl-live` rejoue les agents à la main.

## Conséquences

- La section des fonds reproductibles se lit en euros réels ; les fonds quant et combinés restent des études (10 M€). Comparer un fonds combiné à sa
  référence se fait sur les P&L **avant et après frais** : un ingrédient peut améliorer le signal sans payer ses frais, ou l'inverse.
- Les agents RL du moteur 2 n'achètent ou ne restent qu'à plat : leur veto ne bloque que des achats ; une vente ML passe dès que l'agent est à plat.
- Peu de cibles ont un agent crédible : beaucoup de règles des fonds « RL » tradent le signal ML seul. Le compte rendu du pilote dit combien de règles
  ont un agent (`combo.rl`) et un modèle de régime (`combo.regime`).
- Le rejeu d'un agent recalcule les variables sur un historique plus long que le run d'origine (les modèles de volatilité réestiment leurs paramètres) :
  le contrôle d'accord protège contre un agent qui ne voit plus le même monde, pas contre une petite dérive.
- Limites : coût d'aller-retour au tarif médian (pas le tirage réel de l'ordre), volatilité prévue par une moyenne exponentielle (pas les modèles
  GARCH des variables), un seul modèle de régime par famille (le premier indice qui a un champion à 1 jour avec des signaux live). Les fonds combinés
  ne commencent qu'à leur création : pas de rejeu du passé.
