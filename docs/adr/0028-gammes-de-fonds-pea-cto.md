# ADR 0028 — Gammes de fonds : Systematic, CTO et PEA, une seule carte de création

Date : 2026-11-22. Statut : acceptée. Code : `fund/asset_classes.py` (`Family`, `FAMILIES`, `family_of`, `setup`, `setup_tiers`, `class_rows`),
`fund/real_funds.py` (`pilot_settings`), `webapp/routes/fund.py` (`_class_options`, `_class_setup`, `/api/fund/asset-classes*`),
`webapp/templates/fonds.html` (carte `#fund-create`), `webapp/static/fonds.js`, `cli.py` (`autopilot-classes|autopilot-tiers --family`).
Tests : `tests/fund/test_fund_asset_classes.py`, `tests/fund/test_fund_asset_classes_routes.py`, `tests/fund/test_fund_autopilot_cli.py`, `tests/fund/test_fund_real_funds.py`.

## Contexte

Demande de Léon (21/11) : en simulation, des fonds PEA et CTO montés comme les fonds `Systematic` (une stratégie par classe d'actifs, une par preuve
statistique), leur création mêlée aux autres, avec deux règles : pas de vente à découvert, et pour le PEA seulement l'Europe.

- Les stratégies par classe et par preuve n'existaient que dans une gamme : `Systematic <classe>`, CTO, vente à découvert par CFD.
- La carte « par classe » de `/fonds` proposait déjà une enveloppe PEA, mais le nom ne changeait pas : choisir PEA reprenait les stratégies CTO
  `Systematic <classe>` du même nom et remplaçait leurs réglages, avec la vente à découvert toujours permise et toutes les classes.
- Les fonds réels (ADR 0026) avaient leur propre carte, et leur CTO vendait à découvert.

## Décisions

1. **Trois gammes** (`FAMILIES`), séparées par le préfixe du nom (une gamme ne reprend jamais la stratégie d'une autre), toutes de catégorie `quant` :

   | Gamme | Enveloppe | Vente à découvert | Capital par défaut | Classes | Stratégies par preuve |
   |---|---|---|---|---|---|
   | `Systematic` | CTO | oui (CFD) | 10 M€ | les 11 classes | tout l'univers |
   | `CTO` | CTO | non : actions et ETF au comptant, le reste en CFD à l'achat | 10 M€ | les 11 classes | tout l'univers |
   | `PEA` | PEA | non : actions de l'UE/EEE en euro au comptant (`envelopes.pea_eligibility`) | plafond de versements (150 000 €) | Actions France, Actions Europe (sans le Royaume-Uni) | groupes `envelopes.PEA_GROUPS` |

   Noms : `CTO Actions US`, `PEA Actions France`, `CTO Diebold-Mariano`, `PEA Benjamini-Hochberg`... Un capital PEA au-dessus du plafond est refusé
   avant toute écriture.
2. **Une seule carte de création** sur `/fonds` : la gamme (Systematic, CTO, PEA, ou fonds réels), puis le découpage (une stratégie par classe
   d'actifs, ou une par preuve statistique : Diebold-Mariano, Benjamini-Hochberg). Le bloc des fonds réels (5 000 €, 1 € par ordre) est dans la même
   carte ; la page ne montre que les classes de la gamme choisie et met le capital par défaut de la gamme. API : `family`, `split` (`classes` ou
   `tiers`), `tiers` dans `/api/fund/asset-classes*` ; `GET /api/fund/asset-classes?family=` décrit les gammes. Commande : `--family`.
3. **Le fonds réel CTO n'a plus de vente à découvert** (remplace le point « CTO : vente à découvert comprise » de l'ADR 0026).

## Conséquences

- Les stratégies `Systematic` existantes ne changent pas (même nom, mêmes réglages). L'option `--wrapper` des commandes et le champ `wrapper` de l'API
  disparaissent au profit de la gamme.
- Un signal de baisse ferme une position CTO ou PEA sans en ouvrir une vendeuse : sur une classe très baissière, ces fonds restent en liquidités.
- Limites héritées : éligibilité PEA jugée sur la place de cotation, pas sur le siège ; ETF exclus du PEA ; actions de l'UE/EEE hors euro refusées.
