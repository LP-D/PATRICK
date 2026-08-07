# AUDIT_RECONCILIATION_MAIN.md — Réconciliation avec `origin/main`

Session d'audit, aucune fusion exécutée. Toutes les commandes ci-dessous ont
été exécutées depuis `/home/user/claude`.

---

## R1 — Sécurisation du travail en cours

```
$ git status -s
(vide)
$ git status
On branch claude/marketml-vix-setup-qn43wf
Your branch is ahead of 'origin/claude/marketml-vix-setup-qn43wf' by 1 commit.
nothing to commit, working tree clean
```

Rien à sécuriser : le Bloc X (correction Diebold-Mariano par classe d'actif,
commit `a8834b3`) et la purge `marketml/` (commit `4fae2df`) avaient déjà été
committés lors des sessions précédentes. Arbre propre, aucun WIP nécessaire.

---

## R2 — Régression Diebold-Mariano : confirmée par exécution

```
$ git worktree add /tmp/audit-main origin/main
Preparing worktree (detached HEAD 0df43f4)
HEAD is now at 0df43f4 Merge pull request #37 from LP-D/claude/marketml-vix-setup-qn43wf
```

**Point d'attention découvert en ouvrant le worktree** : `origin/main` a
avancé depuis le dernier audit (`AUDIT_REPO.md`, A10 : `5ec16eb..0df43f4`).
Ce nouveau commit est un merge de la **PR #37, depuis notre propre branche**
`claude/marketml-vix-setup-qn43wf` — mais au niveau du commit `b8ef889`
("Nettoyer __pycache__ du dépôt"), c'est-à-dire **avant** le Bloc X5 et la
purge `marketml/` de cette session. `origin/main` contient donc désormais
notre travail jusqu'à `b8ef889` inclus, mais pas `a8834b3` ni `4fae2df`.

```
$ git merge-base --is-ancestor a8834b3 origin/main && echo OUI || echo NON
NON
$ git rev-list --left-right --count origin/main...claude/marketml-vix-setup-qn43wf
22   2
```

Exécution du test suspecté :

```
$ cd /tmp/audit-main/patrick && pip install -e . --no-deps -q
$ python3 -m pytest tests/ -k "diebold" -v
...
tests/test_diebold_mariano.py::test_dm_too_few_observations_returns_nan FAILED
tests/test_diebold_mariano.py::test_dm_not_significant_when_identical_performance PASSED
tests/test_diebold_mariano.py::test_dm_symmetry_flips_sign PASSED
1 failed, 3 passed, 254 deselected

$ python3 -m pytest tests/test_diebold_mariano.py::test_dm_too_few_observations_returns_nan -v
FAILURES
___________________ test_dm_too_few_observations_returns_nan ___________________

    def test_dm_too_few_observations_returns_nan():
        out = diebold_mariano(np.array([1.0, 0.0, 1.0]), np.array([0.0, 0.0, 1.0]))
>       assert np.isnan(out["dm_stat"])
E       AssertionError: assert np.False_
E        +  where np.False_ = <ufunc 'isnan'>(0.0)
E        +    where <ufunc 'isnan'> = np.isnan
```

**Verdict R2 : régression confirmée, par exécution réelle du test contre le
code actuel de `origin/main`, pas par inférence.** Origine identifiée :

```
$ git log --all -p -- "*/validation/diebold_mariano.py" | grep -B 30 'dm_stat": 0.0' | grep -E "^commit|^Author|^Date"
commit 7f84761097cd6ef5c0378e05443a17abfc6a7f14
Author: LP-D <leonpauldufour@gmail.com>
Date:   Wed Aug 5 23:52:04 2026 +0200

$ git show --stat 7f84761
    Implement Phase 9 features and updates across multiple modules
    - Add new phase9.py for Phase 9 logic
    - Update db.py for tracking enhancements
    - Create migration for Phase 9 tracking
    - Modify validation and webapp files for integration
    - Add tests for Phase 9 functionality

 patrick/patrick/__init__.py                                    |  28 +
 patrick/patrick/phase9.py                                      | 767 +++
 patrick/patrick/tracking/db.py                                 |  69 ++
 patrick/patrick/tracking/migrations/0010_phase9_tracking.sql   |  20 +
 patrick/patrick/validation/diebold_mariano.py                  |   6 +-
 patrick/patrick/webapp/app.py                                  |  76 ++
 patrick/patrick/webapp/templates/base.html                     |   1 +
 patrick/patrick/webapp/templates/phase9_overview.html          |  99 ++
 patrick/tests/test_phase9.py                                   | 148 ++
 9 files changed, 1212 insertions(+), 2 deletions(-)
```

Un **seul commit monolithique** ("Implement Phase 9 features and updates
across multiple modules") a modifié `diebold_mariano.py` **en même temps**
que l'ajout de `phase9.py`, sans que le test associé (dont le nom affirme
toujours `returns_nan`) n'ait été mis à jour ou re-vérifié. Tout indique un
effet de bord non intentionnel de l'intégration Phase 9, pas une décision
délibérée et testée de changer le contrat de la fonction.

---

## R3 — Contenu réel du lot « lancement batch multi-cible »

```
$ git log --format="%H %s" 4f79ff8..5f54117
5f54117 Merge branch 'claude/marketml-vix-setup-qn43wf'
cb89b42 fix: correctifs de revue finale -- collision nom de run en file, dedup batch...
165003c feat: bouton Relancer sur la page de detail d'un run et l'historique par cible
9651a36 fix: repare l'apercu marche apres renommage target_symbol -> target_symbols...
deb9b65 feat: selection multi-cible + apercu de nom en lecture seule...
f73d061 fix: couvre le repli run.config_json de /relaunch (run CLI sans job)
13fa92e feat: POST /runs/{run_id}/relaunch pour relancer un run passe
b038352 test: couvre le garde-fou anti-collision output_dir en batch
af95004 feat: POST /runs accepte plusieurs cibles, enfile un job par cible
d89bf2e feat: endpoint GET /api/next-run-names...
7181143 refactor: build_config_dict prend target_symbol/name en parametres explicites
3108c96 feat: run_manager.next_run_name()...
a56747c feat: slug_target()...
b6010f5 docs: plan d'implementation...
426ab27 docs: spec...
```

Fonctionnalité réelle : sélection multi-cible sur le formulaire de
lancement, nommage automatique de run (`slug_target`, `next_run_name`),
endpoint `POST /runs` acceptant plusieurs cibles (une file par cible),
bouton "Relancer" sur la page de détail d'un run et l'historique par cible,
garde-fou anti-collision de nom en batch.

```
$ git diff --stat 4f79ff8..5f54117 -- patrick/
patrick/patrick/webapp/app.py                    | 104 ++++++++++++---
patrick/patrick/webapp/forms.py                  |  21 ++-
patrick/patrick/webapp/i18n.py                   |  11 +-
patrick/patrick/webapp/run_manager.py            |  36 +++++
patrick/patrick/webapp/static/app.js             |  65 ++++++---
patrick/patrick/webapp/static/market.js          |  18 ++-
patrick/patrick/webapp/static/style.css          |   2 +
patrick/patrick/webapp/templates/index.html      |  19 +--
patrick/patrick/webapp/templates/run_detail.html |   3 +
patrick/patrick/webapp/templates/target.html     |   4 +-
patrick/tests/test_run_naming.py                 |  74 +++
patrick/tests/test_webapp_forms.py               |  70 +++
patrick/tests/test_webapp_smoke.py               | 160 +++++++++
13 files changed, 528 insertions(+), 59 deletions(-)
```

Recoupement avec les fichiers modifiés par notre branche depuis le même
ancêtre : **seul `app.js` est commun**. Vérification ligne par ligne :

```
$ git diff 4f79ff8..5f54117 -- patrick/patrick/webapp/static/app.js | grep "^@@"
@@ -382,14 +382,11 @@
@@ -486,11 +483,15 @@
@@ -498,6 +499,29 @@
@@ -508,6 +532,12 @@
@@ -516,18 +546,21 @@

$ git diff 4f79ff8..5f54117 -- patrick/patrick/webapp/static/app.js | grep -n "renderStatsBox\|diebold\|dm\."
(vide)
```

Leur diff app.js (lignes 382-546) ne touche ni `renderStatsBox` ni la
section Diebold-Mariano — c'est la partie formulaire/multi-cible du fichier,
disjointe de nos modifications (cf. R5 pour la comparaison exacte sur
l'état final).

**Verdict R3 : fusion propre attendue pour ce lot** (fichiers disjoints, ou
communs mais sur des zones de code différentes).

---

## R4 — Contenu réel de la Phase 9

```
$ git show origin/main:patrick/patrick/phase9.py | grep -n "^def \|^class "
class RegimeThresholds
def classify_regime_daily(...)
def regime_summary(...)
def p_value_histogram(...)
def signal_strength(...)
def signal_dm_summary(...)          # réutilise diebold_mariano() existant
def reduce_correlated_signals(...)
def compare_test_holdout(...)
def aggregate_signals(...)
def regime_alignment_score(...)
def validate_aggregate_signal_quality(...)
def build_event_calendar(...)
def credit_risk_regime(...)
def trend_follow_signal(...)
def risk_parity_weights(...)
class StrategyRule / StrategyVersion / StrategyEngine
def enforce_risk_constraints(...)
def parameter_grid_summary(...)
class ExecutionOrder
def simulate_execution(...)
class DecisionJournalEntry / DecisionJournal
def take_snapshot(...) / def reconstruct_state(...)
def determine_signal_quality_status(...)
```

**Nature réelle** : une couche « plateforme de trading / gestion de
portefeuille » au-dessus des cibles individuelles déjà validées — pas une
réimplémentation de la validation statistique elle-même. Elle importe
correctement `diebold_mariano` et `benjamini_hochberg` plutôt que de les
recoder (`from patrick.validation.diebold_mariano import diebold_mariano` /
`from patrick.validation.fdr import benjamini_hochberg`, lignes 9-10).

Fonctions notables au regard de ce qui avait été discuté dans les sessions
précédentes de cette conversation (agrégation de signaux multi-cibles,
correction FDR) :

- `signal_dm_summary` : agrège des DM par signal, réutilise l'implémentation
  partagée — pas de duplication.
- `aggregate_signals` / `reduce_correlated_signals` / `regime_alignment_score` :
  logique d'agrégation multi-signaux par régime, avec pondération par
  corrélation — **correspond bien à l'idée d'agrégation par régime
  discutée**, mais implémentée indépendamment, sans lien visible avec le
  travail de cette branche sur les baselines par classe d'actif (Bloc X5).
- `determine_signal_quality_status` : importe `benjamini_hochberg` mais **ne
  l'appelle pas** — comptage naïf `p_value <= alpha` sans correction FDR
  (déjà signalé en A9 de l'audit précédent, reconfirmé ici).
- `StrategyEngine`/`ExecutionOrder`/`DecisionJournal` : gestion de
  portefeuille, simulation d'exécution, journal d'audit avec
  snapshots/rollback — fonctionnalité entièrement nouvelle, aucun
  équivalent sur notre branche.

Persistance ajoutée :

```
$ git show origin/main:patrick/patrick/tracking/migrations/0010_phase9_tracking.sql
CREATE TABLE phase9_snapshot (id, snapshot_name, payload_json, created_at)
CREATE TABLE phase9_journal (id, action, actor, before_json, after_json, reason, created_at)
```

Routes web ajoutées :
`/phase9`, `/api/phase9/summary`, `/api/phase9/journal` (GET+POST),
`/api/phase9/snapshot` (POST) -- plus les routes du lot batch (R3) :
`/runs`, `/universe`, `/targets/{ticker}`, `/runs/{run_id}/detail`,
`/runs/{run_id}/relaunch`, `/api/next-run-names`.

**Verdict R4 : travail parallèle sur une idée voisine (agrégation multi-
signaux), pas redondant avec le Bloc X5 de cette branche** (qui porte sur la
CORRECTION de la baseline DM par cible individuelle, pas sur l'agrégation
inter-cibles) — complémentaire plutôt que concurrent, sous réserve de la
régression R2 à corriger avant toute intégration, et du conflit mécanique
R5 (migration 0010) à résoudre.

---

## R5 — Cartographie des conflits potentiels

```
$ BASE=$(git merge-base claude/marketml-vix-setup-qn43wf origin/main)
$ git log -1 --format="%h %s" $BASE
b8ef889 Nettoyer __pycache__ du dépôt

$ git diff --name-only $BASE claude/marketml-vix-setup-qn43wf | sort > ours.txt   # 128 fichiers
$ git diff --name-only $BASE origin/main | sort > theirs.txt                      # 30 fichiers
$ comm -12 ours.txt theirs.txt
patrick/patrick/tracking/db.py
patrick/patrick/webapp/static/app.js
```

Sur 128 fichiers modifiés côté notre branche (dont 113 sont la purge
`marketml/`, sans équivalent côté `origin/main`) et 30 côté `origin/main`,
**seuls 2 fichiers sont modifiés des deux côtés**. Vérification ligne par
ligne des zones touchées (pas seulement du nom de fichier) :

```
$ git diff $BASE claude/marketml-vix-setup-qn43wf -- patrick/patrick/tracking/db.py | grep "^@@"
@@ -180,19 +180,25 @@ def get_feature_stability(...)   # -> save_dm_result (Bloc X5)

$ git diff $BASE origin/main -- patrick/patrick/tracking/db.py | grep "^@@"
@@ -140,6 +140,75 @@ def list_data_quality_issues(...)   # -> Phase 9 (nouvelles fonctions)
@@ -232,22 +301,42 @@ def get_run(...)                     # -> Phase 9 (nouvelles fonctions)
```

Notre plage modifiée (180-199) tombe **entre** leurs deux plages (140-146 et
232-254) — aucun chevauchement de lignes. Même vérification pour `app.js` :

```
$ git diff $BASE claude/marketml-vix-setup-qn43wf -- .../app.js | grep "^@@"
@@ -237,16 +237,26 @@          # renderStatsBox / DM (Bloc X5)

$ git diff $BASE origin/main -- .../app.js | grep "^@@"
@@ -409,14 +409,11 @@
@@ -520,7 +517,14 @@
@@ -728,11 +732,15 @@
@@ -740,6 +748,29 @@
@@ -750,6 +781,12 @@
@@ -774,18 +811,21 @@
```

Notre plage (237-262) est très en amont de toutes leurs plages
(409-811) — aucun chevauchement.

**Conflit textuel Git : aucun trouvé sur les fichiers réellement communs.**
(Analyse par diff de plages de lignes, pas par exécution d'un vrai `git
merge` -- conforme à la consigne "aucune fusion automatique dans cette
session".)

### Conflit mécanique confirmé (hors fichiers Python) : numérotation de migration

```
$ git show origin/main:patrick/patrick/tracking/migrations/0010_phase9_tracking.sql > /tmp/.../0010_phase9_tracking.sql
$ # + notre 0010_dm_result_kind.sql dans le même dossier, migrate() exécuté :
Ordre d'application : [..., '0009_dm_result.sql', '0010_dm_result_kind.sql', '0010_phase9_tracking.sql']
OK    : 0010_dm_result_kind.sql (version 10)
ECHEC : 0010_phase9_tracking.sql (version 10) -> IntegrityError: UNIQUE constraint failed: schema_version.version
```

**Reproduit par exécution réelle, pas par inspection.** Les deux lignées ont
créé indépendamment un fichier `0010_*.sql` — noms différents, contenus
différents, mais même numéro de version. `schema_version.version` est clé
primaire ; la seconde migration numéro 10 provoque un crash immédiat de
`patrick.tracking.db.migrate()`, donc de toute commande `patrick` sur une
base ayant déjà appliqué l'autre 0010. **C'est le seul conflit réellement
bloquant identifié** — mécanique et trivial à corriger (renuméroter l'une
des deux migrations en 0011), mais qui DOIT être résolu avant toute fusion,
automatique ou manuelle.

---

## SYNTHÈSE ET RECOMMANDATION

| # | Point | Verdict |
|---|---|---|
| R2 | Régression `diebold_mariano.py` sur `origin/main` (NaN -> 0.0/1.0) | **Confirmée par exécution** (`1 failed, 3 passed`), introduite par `7f84761` (Phase 9), test contradictoire non corrigé |
| R3 | Lot batch multi-cible | Fichiers disjoints ou zones non chevauchantes avec notre branche -- fusion propre attendue |
| R4 | Phase 9 | Couche complémentaire (agrégation/stratégie/portefeuille), réutilise correctement DM/FDR existants, pas redondante avec le Bloc X5 |
| R5 | Conflits Git textuels | Aucun trouvé sur les 2 fichiers communs (`db.py`, `app.js`) -- analyse ligne par ligne, pas de merge exécuté |
| R5 | Conflit mécanique migration `0010` | **Bloquant, confirmé par exécution** (crash `IntegrityError` reproduit) |

**Recommandation : fusionner après correction préalable, pas maintenant et
pas jamais.**

1. **Ne pas fusionner en l'état** — le conflit de migration `0010` ferait
   planter `patrick.tracking.db.migrate()` dès qu'une base aurait déjà
   appliqué l'une des deux versions (notre commit `4fae2df`/`a8834b3` est
   déjà poussé avec `0010_dm_result_kind.sql` -- toute base y ayant tourné
   `patrick run` une fois est concernée).
2. **Corriger d'abord, séparément, avant toute fusion** :
   - Renuméroter l'une des deux migrations `0010_*.sql` en `0011_*.sql`
     (préférence à documenter : celle qui sera fusionnée en dernier dans
     l'historique final, pour rester dans l'ordre chronologique).
   - Statuer sur la régression `diebold_mariano.py` : soit revenir au
     comportement `NaN` (le test `origin/main` l'exige déjà), soit assumer
     et documenter le changement `0.0/1.0` avec une justification vérifiée
     (ex. si `phase9.py::p_value_histogram` a réellement besoin d'une valeur
     numérique plutôt que NaN -- à vérifier avant de trancher, pas supposé
     ici).
3. **Une fois ces deux points corrigés**, les trois lignées (notre Bloc X5,
   le lot batch multi-cible, la Phase 9) apparaissent complémentaires plutôt
   que concurrentes au niveau du code — aucune preuve de redondance
   fonctionnelle trouvée qui justifierait de les traiter comme des
   expérimentations à ne jamais réconcilier. Une fusion (`git merge` ou
   rebase, au choix à discuter séparément) semble viable après correction,
   mais reste à confirmer par un vrai essai de fusion à blanc le moment
   venu — cette session ne l'a pas exécuté, par consigne.

**Aucune fusion exécutée. En attente de décision.**
