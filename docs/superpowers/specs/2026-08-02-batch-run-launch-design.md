# Lancer plusieurs runs à la suite + relancer un run passé

Date : 2026-08-02
Statut : approuvé (design), en attente de plan d'implémentation

## Contexte

Un run = un target (ex. `^VIX`), multi-horizons dans le run, mais un seul
target par soumission de formulaire aujourd'hui. La queue de jobs
(`patrick/tracking/jobs.py`, table `job`) est déjà strictement FIFO,
consommée par un unique worker (`patrick/worker.py`) : soumettre N jobs les
enchaîne automatiquement, sans rien construire de neuf côté orchestration.

Univers configuré = 550 tickers possibles (`DEFAULT_TARGET_GROUPS`), à ~9h+
par run actuellement -> "tout lancer" au sens littéral (les 550) n'a pas de
sens. Le batch reste une **sélection libre à chaque soumission**, pas une
liste figée.

Hors périmètre de ce cycle (cycles suivants, dans cet ordre) :
- cache disque du pool de features -> réentraînement plus rapide
- parallélisation des horizons (indépendants entre eux dans un même run)

## 1. Sélection multi-target

`patrick/webapp/templates/index.html` : le `<select name="target_symbol">`
(single) devient `<select name="target_symbols" multiple>`, mêmes
`<optgroup>`/labels que l'existant (`target_groups`). Les boutons quick-pick
(qui posaient `target_symbol`) togglent l'appartenance à la sélection au lieu
de la remplacer. Le bouton submit affiche le nombre de runs qui vont être
enchaînés ("Lancer 3 runs").

La prévisualisation (`/api/preview/{symbol}`, `/api/news/{symbol}`) reste
attachée à un seul symbole à la fois (le dernier cliqué/sélectionné) — pas de
raison de la dupliquer par target sélectionné.

## 2. Règle de nommage (nouveau, remplace le champ "Nom du run" libre)

Le nom d'un run n'est plus un champ texte libre : il est **toujours** dérivé
du target + un numéro de séquence.

- `slug(target_symbol)` : retire le `^` initial, remplace tout caractère non
  alphanumérique (`=`, `.`, espace...) par `_`, réduit les `_` répétés.
  Exemples : `^VIX` -> `VIX`, `EURUSD=X` -> `EURUSD_X`,
  `000001.SS` -> `000001_SS`.
- `next_run_number(target_symbol)` : `1 + COUNT(*) FROM run WHERE target =
  target_symbol` (table `run`, historique complet CLI + web, tous statuts
  confondus — le numéro sert à distinguer, pas à compter les succès).
- Nom généré = `f"{slug}_{n}"`. `output.dir` par défaut =
  `f"runs/{nom_généré}"`.

Calculé côté serveur, à l'enqueue (pas à l'affichage du formulaire), pour
chaque target de chaque soumission (single ou batch — même règle partout,
pas de cas particulier). Le formulaire garde un champ nom en lecture seule,
mis à jour en JS quand la sélection change, pour prévisualisation seulement
(ex: cible unique sélectionnée -> "VIX_4" affiché avant de cliquer "Lancer").
Avec plusieurs cibles sélectionnées, affiche la liste des noms qui seront
générés.

**Limite connue, acceptée** : deux jobs pour le *même* target soumis dans un
intervalle très court (avant que le premier n'ait inséré sa ligne `run`)
peuvent recevoir le même numéro — outil local mono-utilisateur, impact
cosmétique uniquement (les `run_id`/`job_id` restent uniques), pas traité
dans ce cycle.

## 3. `POST /runs` (`patrick/webapp/app.py:176`)

Lit `form.getlist("target_symbols")` (au lieu de `target_symbol` singulier).
Pour chaque symbole : mêmes réglages partagés (horizons, familles de
features, algos, trials...), mais `target_symbol`/`target_source`/univers
(`universe_excluding`)/`name`/`output.dir` calculés par symbole (règle du
§2). Chaque config validée (`RunConfig.model_validate`) avant tout enqueue —
si une seule échoue, tout le batch est rejeté, rien n'est enqueue
partiellement (comportement actuel conservé, étendu au batch).

Réponse JSON : toujours une liste, même à un seul élément —
`{"runs": [{"run_id", "status", "queue_position", "target"}, ...]}`.
`patrick/webapp/static/app.js` adapté à cette forme (actuellement attend un
objet unique).

## 4. Bouton "Relancer"

Nouvelle route `POST /runs/{run_id}/relaunch`. Résout la config d'origine :
`run_manager.get_run_config(run_id)` (table `job`, runs soumis via le web)
sinon fallback lecture directe de `run.config_json` (couvre aussi les runs
lancés en CLI, absents de la table `job`). Recalcule `name`/`output.dir`
selon la règle du §2 (nouvelle tentative = nouveau numéro), garde tout le
reste de la config à l'identique, puis enqueue comme un job neuf
(`run_manager.start_run`).

Placé sur `run_detail.html` (vue détail d'un run passé) et sur chaque ligne
de run listée dans `target.html`.

## Pas de migration DB

Tables `job`/`run` réutilisées telles quelles, aucune colonne ajoutée.

## Tests

- `slug()` / `next_run_number()` : cas `^`, `=`, `.`, collisions de comptage.
- `POST /runs` avec 2 targets -> 2 jobs distincts en queue, noms/`output.dir`
  distincts, ordre de queue respecté (FIFO par `created_at`).
- `POST /runs` avec une config invalide parmi N -> rien enqueue, erreurs
  renvoyées.
- `/relaunch` sur un run web ET sur un run CLI-only -> reproduit la config à
  l'identique sauf nom/dossier de sortie (nouveau numéro).
