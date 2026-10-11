# Lots prêts à lancer (pages ML, DL, RL) et page d'un run instantanée

Date : 2026-10-11. Demande de Léon : (1) depuis la section Univers, le clic sur un nom menait à des runs dont les données ne
s'ouvraient pas ; (2) sur les pages Modèles, des choix en plus des profils : lancer toutes les cibles jamais exécutées, les
horizons, ou tous les runs conseillés ; (3) rappel : la page s'ouvre tout de suite, le reste se charge après.

## 1. Cause du blocage de la page d'un run

`/runs/{id}/detail` calculait le conseil de ré-entraînement avant d'afficher quoi que ce soit. Sa requête sur les classes du meilleur essai
(`WHERE trial_id = ? AND split = 'test'`) était exécutée par SQLite sur l'index `idx_pred_split` : parcours de tous les `test` de la base
(~24 millions de lignes de prédictions), 180 à 256 s par run, puis une erreur 500 pour les runs dont la règle « meilleur horizon » citait
une variable absente de ses chiffres (`best_h`). Les 528 liens de l'Univers répondaient bien ; ce sont les runs, derrière le nom de la
cible, qui ne s'ouvraient pas.

Correctifs : requête forcée sur la clé primaire (`INDEXED BY sqlite_autoindex_prediction_1`, comme les autres requêtes de
`tracking/history.py`), chiffres de la règle corrigés, conseil et méta-étiquetage (170 régressions logistiques, 2 à 4 s) chargés après
l'affichage par `/fragments/run-advice/{id}` et `/fragments/run-meta/{id}`. Mesuré sur la vraie base : page 0,3 à 0,6 s ; les 393 runs
terminés répondent en 200, aucun à plus de 3 s.

## 2. Lots

`webapp/launch_batches.py`. Un run « fait » = terminé ou en cours (`run`), ou en file / en cours (`job`) ; un échec ne compte pas.
La famille (ML ou DL) vient des algorithmes, comme `RunConfig.family` ; le RL se lit dans les jobs `kind: rl` (hors échecs et supprimés).
Les cibles à historique connu trop court (< 10 ans) sont écartées, comme le formulaire les grise.

| Lot | Pages | Effet |
|---|---|---|
| Cibles jamais lancées | ML, DL, RL | Sélectionne dans le formulaire les cibles sans aucun run de la famille. |
| Horizons jamais lancés | ML, DL | Sélectionne les cibles déjà entraînées et l'union de leurs horizons par défaut (1, 2, 3, 5, 7, 10) manquants ; le formulaire envoie `only_missing=1`, le serveur ne crée alors que les couples cible × horizon sans run. |
| Runs conseillés | ML | Analyse à la demande (~10 à 30 s) : par cible, meilleure proposition du conseiller sur son dernier run terminé ; confirmation avec la répartition, puis mise en file. |

Les deux premiers pré-remplissent seulement : rien ne part avant « Lancer » (après la confirmation en deux temps de la barre de lancement).
Un choix manuel dans les listes annule `only_missing`. Les cartes sont dans un cadre chargé après l'affichage
(`/fragments/launch-batches?family=…`), au-dessus des profils.

« Runs conseillés » s'exécute côté serveur : `forms.FormFromView` redit une vue du formulaire (`to_view` + patch de la suggestion) comme
le navigateur la soumettrait, puis `build_config_dict` et `RunConfig` valident comme `POST /runs` (une configuration invalide, rien en
file). Tests : même configuration que le formulaire pré-rempli rendu par `/ml?run_id=…&suggest=…`, noms de champs présents dans les pages.

## 3. Limites connues

- Après « Horizons jamais lancés », le récapitulatif de la barre de lancement multiplie cibles × horizons sélectionnés : il surestime
  (le serveur n'en crée que les couples manquants, le bandeau du lot le dit).
- « Runs conseillés » ne couvre pas le DL (le conseiller est propre au pipeline ML) ni le RL.
- Le serveur lancé avant la fusion garde l'ancien code : relancer `patrick serve` (voir `long-runs-outside-claude-app`).
