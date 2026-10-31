# Fiche d'un actif et pages de classes d'actifs

Date : 2026-10-31. Demande de Léon : reprendre les pages de classes d'actifs pour qu'elles reflètent ce qui a été fait, et pouvoir cliquer sur
un actif pour une page détaillée « comme l'aperçu de la page ML, avec plus d'infos ».

## Fiche d'un actif (`/targets/{symbole}`)

La page qui listait les runs d'une cible devient la fiche de l'actif ; l'adresse et les liens existants ne changent pas. Cadre instantané
(`asset_view.py` : classe, groupe, historique, voisins, ordres du fonds : lectures légères), le reste en blocs chargés après coup.

| Bloc | Source | Chargement |
|---|---|---|
| En-tête : nom, classe, groupe, source, historique ; lancer en ML / DL / RL ; actualités | `asset_view`, `forms.TARGET_GROUPS` | page |
| Marché : cours zoomable (périodes, bougies, volumes) et statistiques | panneau `asset_panel` (`asset_stats.js`, `/api/asset-stats`) | client |
| Contexte de marché (actions) : indice de la place, S&P 500, composite zone euro | `config/equity_context.py` | page |
| Signaux par horizon : cellule et bulle de `/predictions`, champion de l'horizon | `/fragments/asset-signals/{symbole}` | fragment |
| Actualités notées | `/fragments/news-feed?symbol=` (flux de `/news`) | fragment |
| Dans les fonds : stratégies qui ont passé un ordre sur l'actif | `fund_order` | page |
| Dans le même groupe : liens vers les fiches voisines | `asset_view.peers` | page |
| Entraînements : PBO, runs, SHAP, dérive, modèles alpha (inchangés) | `trackhistory.target_detail` | page |

`_pred_cell.html` porte désormais les macros de cellule de prédiction, partagées par `/predictions` et la fiche.

## Pages de classes d'actifs

Le cadre (titre, grille de cours, bannière de classe) s'ouvre sans lire la base ; compteurs, filtres et tableaux arrivent par
`/fragments/asset-class/{classe}` (lecture de tous les runs mémorisée, `memo`). Une colonne « Signaux » donne le signal de chaque horizon par défaut
(▲▲ ▲ ▼ ▼▼), remplie par `asset_class.js` depuis `/api/class-signals/{classe}` : une seule lecture groupée des derniers signaux des actifs entraînés
de la classe (la vue complète de `/predictions` prend ~90 s sur la vraie base, disque froid). Les noms des actifs pointent vers leur fiche, y compris
dans la grille de cours des classes et sur `/macro` (séries qui sont des cibles).

## Correctif au passage

`text.service.item_feed` plantait (`KeyError: 'known_at'`) sur une base sans actualités ; il renvoie maintenant une liste vide.

## Limites

- Les séries FRED « d'entraînement seulement » (hors cibles) n'ont pas de fiche.
- La vue d'ensemble de `/predictions` reste lente à son premier calcul (non traité ici).
- Le fil de navigation montre toujours « Univers » comme parent d'une fiche, pas la page de sa classe.
