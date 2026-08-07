# AUDIT_REPO.md — État des lieux du dépôt

Session d'audit, Bloc A uniquement (aucune action destructive exécutée). Toutes
les commandes ci-dessous ont été exécutées depuis `/home/user/claude` (racine
réelle du dépôt, cf. A1).

---

## A1 — Dépôt et remote

```
$ git remote -v
origin  https://github.com/LP-D/claude (fetch)
origin  https://github.com/LP-D/claude (push)

$ git rev-parse --show-toplevel
/home/user/claude

$ git status
On branch claude/marketml-vix-setup-qn43wf
Your branch is up to date with 'origin/claude/marketml-vix-setup-qn43wf'.

Changes not staged for commit:
        modified:   patrick/patrick/config/defaults.py
        modified:   patrick/patrick/config/schema.py
        modified:   patrick/patrick/data/session_calendar.py
        modified:   patrick/patrick/pipeline/engine.py
        modified:   patrick/patrick/tracking/db.py
        modified:   patrick/patrick/tracking/history.py
        modified:   patrick/patrick/tracking/report.py
        modified:   patrick/patrick/tracking/stats.py
        modified:   patrick/patrick/validation/baselines.py
        modified:   patrick/patrick/webapp/static/app.js
        modified:   patrick/tests/test_fdr_integration.py
        modified:   patrick/tests/test_pipeline_smoke.py

Untracked files:
        patrick/patrick/tracking/migrations/0010_dm_result_kind.sql
        patrick/tests/test_asset_class_baselines.py
```

**Point d'attention** : lors d'un push antérieur dans cette même session,
GitHub a répondu `remote: This repository moved. Please use the new location:
https://github.com/LP-D/PATRICK.git`. Le remote `origin` configuré localement
pointe donc vers une URL qui a été renommée côté GitHub (`LP-D/claude` →
probablement `LP-D/PATRICK`). Le push a néanmoins abouti (GitHub suit la
redirection), mais **je signale l'ambiguïté plutôt que de trancher** : à
confirmer si `LP-D/claude` doit être mis à jour dans la config git locale, ou
si c'est un renommage que je ne dois pas présumer définitif.

**État de propreté** : le dépôt a des modifications non commitées — ce sont les
changements de la session de travail précédente (Bloc X, correction du biais
Diebold-Mariano) qui n'ont pas encore été committés. Rien n'est perdu, mais ce
n'est pas un arbre propre.

---

## A2 — Branches, locales et distantes

```
$ git branch -a -v
* claude/marketml-vix-setup-qn43wf   b8ef889 Nettoyer __pycache__ du dépôt
  main                               bf61c1a [behind 212] Initial commit
  remotes/origin/agents/accelerer-entrainement-modeles  7f84761 Implement Phase 9 features...
  remotes/origin/claude/calibrated-threshold            ad91f35 ...
  remotes/origin/claude/code-review-wiuz4f              4dc7f8c ...
  remotes/origin/claude/econometric-benchmarks          eafa26c ...
  remotes/origin/claude/final-features                  dd5c125 ...
  remotes/origin/claude/final-ml-scan                   22fbfa8 ...
  remotes/origin/claude/final-optuna                    3fb733a ...
  remotes/origin/claude/final-tft                       f494101 ...
  remotes/origin/claude/fix-catboost-bug                1fea3cd ...
  remotes/origin/claude/fix-inf-returns                 ce98273 ...
  remotes/origin/claude/marketml                        ab9c0b7 ...
  remotes/origin/claude/marketml-vix-setup-qn43wf       b8ef889 Nettoyer __pycache__ du dépôt
  remotes/origin/claude/ohlc-vol                        2dc9879 ...
  remotes/origin/claude/portfolio-sim                   4789fc8 ...
  remotes/origin/claude/production                      48be989 ...
  remotes/origin/claude/purged-cv                       b3a220e ...
  remotes/origin/claude/regime-router                   9a3a30a ...
  remotes/origin/claude/repo-cleanup                    4e687cd ...
  remotes/origin/claude/spike-scan                      9a3941c ...
  remotes/origin/claude/spike-scan-v2                   dfbeb05 ...
  remotes/origin/claude/stacking-wf                     e9d65d5 ...
  remotes/origin/claude/tft-wf                          5696315 ...
  remotes/origin/claude/var-macro                       d9674b7 ...
  remotes/origin/claude/vscode-vix-amplitude            8faeb97 ...
  remotes/origin/local/full-project                     506f67e ...
  remotes/origin/lp-d-rangement-patrick                 65eca21 Rangement: update README...
  remotes/origin/main                                   0df43f4 (a avancé pendant l'audit, cf. A10)
  remotes/origin/results/vix-*  (16 branches "results/...")
```

44 refs au total (branches locales + distantes). Le détail par ancienneté
(`for-each-ref`) montre :

- `claude/marketml-vix-setup-qn43wf` (notre branche active) : dernier commit
  il y a moins d'une heure.
- `origin/lp-d-rangement-patrick` : 28h.
- `origin/main` et `origin/agents/accelerer-entrainement-modeles` : 2 jours.
- **Toutes les autres branches `claude/*` et `results/*` (24 branches)** :
  dernier commit il y a **2 semaines**, aucune activité depuis. Ce sont les
  notebooks de la campagne de validation VIX (VIX_CHAMPION_WF, VIX_FINAL_*,
  VIX_PORTFOLIO_SIM, etc.) — un couple `claude/<nom>` (le notebook) +
  `results/<nom>` (ses résultats agrégés) par expérience.
- `main` (locale) : `[behind 212]`, dernier commit "Initial commit" — **la
  branche locale `main` n'a jamais été mise à jour depuis le tout premier
  commit du dépôt**, complètement obsolète par rapport à `origin/main`.

**Branche par défaut réelle** (`git remote show origin` → `HEAD branch`) :
**`main`**.

```
$ git branch --merged origin/main
  main

$ git branch --no-merged origin/main
* claude/marketml-vix-setup-qn43wf
```

Notre branche de travail **n'est PAS fusionnée** dans `origin/main`.

```
$ git rev-list --left-right --count origin/main...claude/marketml-vix-setup-qn43wf
21   1
```

Divergence réelle : `origin/main` a **21 commits** que notre branche n'a pas,
notre branche a **1 commit** (`b8ef889`, nettoyage pycache) que `origin/main`
n'a pas. Détail en A4/A9.

---

## A3 — Worktrees

```
$ git worktree list
/home/user/claude  b8ef889 [claude/marketml-vix-setup-qn43wf]
```

**Un seul worktree**, celui du dépôt courant. Le chemin `PROJET VIX
(main).worktrees\accelerer-entrainement-modeles` mentionné dans un rapport
antérieur ne correspond à rien dans cet environnement cloud — il s'agissait
vraisemblablement d'un worktree Windows sur la machine locale de
l'utilisateur, hors de portée de cette session.

---

## A4 — Historique récent, toutes branches

```
$ git log --all --oneline --graph --decorate -40
* b8ef889 (HEAD -> claude/marketml-vix-setup-qn43wf, origin/claude/marketml-vix-setup-qn43wf) Nettoyer __pycache__ du dépôt
| * 65eca21 (origin/lp-d-rangement-patrick) Rangement: update README and add docs index
| *   5ec16eb (origin/main historique) Merge branch 'agents/accelerer-entrainement-modeles' into main
| |\
| | * 7f84761 (origin/agents/accelerer-entrainement-modeles) Implement Phase 9 features and updates across multiple modules
| | * 8efc254 Agent Host changes for agents/accelerer-entrainement-modeles
| |/
| *   baac347 merge: intègre le travail parallèle (Phase 4.8/5, design, i18n) depuis origin/claude/marketml-vix-setup-qn43wf
| |\
| |/
|/|
* | e485fe7 D4: Add detailed CLI command documentation
* | 141a4c6 D3: Make holdout_months configurable via YAML (range: 12-24)
* | 5bce1c1 D2: Rename kelly position mode to heuristic_leverage with disclaimer
* | c173c63 Phase 4.8 simulator: Excel-like metric annotations & enhanced graph details
* | 3f0bcff Phase 5.2 impeccable layout — spacing, rhythm, density, grouping
* | b7c9707 Phase 5.1 impeccable harden — navigation, empty states, routes consolidées
* | 039fe5b Phase 5 : routes et fonction list_all_runs complètent l'explorateur
* | 2d2cc15 Phase 5 (Surfaces exploratoires) : i18n, templates, et routes
  ... (16 commits impeccable/craft/design supplémentaires)
| *   5f54117 Merge branch 'claude/marketml-vix-setup-qn43wf'
| |\
| | * cb89b42 fix: correctifs de revue finale -- collision nom de run en file...
| | * 165003c feat: bouton Relancer sur la page de detail d'un run...
| | * 9651a36 fix: repare l'apercu marche apres renommage target_symbol -> target_symbols...
| | * deb9b65 feat: selection multi-cible + apercu de nom en lecture seule...
| | * f73d061 fix: couvre le repli run.config_json de /relaunch...
| | * 13fa92e feat: POST /runs/{run_id}/relaunch pour relancer un run passe
| | * b038352 test: couvre le garde-fou anti-collision output_dir en batch
| | * af95004 feat: POST /runs accepte plusieurs cibles, enfile un job par cible
| | * d89bf2e feat: endpoint GET /api/next-run-names...
| | * 7181143 refactor: build_config_dict prend target_symbol/name en parametres explicites
| | * 3108c96 feat: run_manager.next_run_name()...
| | * a56747c feat: slug_target()...
| | * b6010f5 docs: plan implementation lancement batch de runs + relance
| | * 426ab27 docs: spec lancement batch de runs + relance + règle de nommage
| | * 47be4d5 az
| |/
|/|
```

**Lecture** : `origin/main` a intégré, via deux fusions successives
(`5f54117` puis `baac347`), un lot de fonctionnalités (lancement batch
multi-cible, bouton "Relancer", nommage automatique de run) **qui ne sont pas
présentes sur notre branche actuelle**. Notre branche a continué en parallèle
(D2/D3/D4, Phase 4.8, travail impeccable) sans jamais réintégrer ce lot. Puis
`origin/main` a reçu en plus `agents/accelerer-entrainement-modeles` (Phase 9,
767 lignes, cf. A9) — un troisième lot que nous n'avons pas non plus.

**Trois lignées de développement actives et non réconciliées** sur le même
produit, en plus des 24 branches figées de la campagne notebooks.

---

## A5 — Arborescence réelle

```
$ find . -maxdepth 3 -type d | grep -v -E "\.git|__pycache__|node_modules|\.venv"
./.claude
./.pytest_cache
./marketml
./marketml/marketml/{config,data,features,models,pipeline,selection,tracking,tuning,validation}
./marketml/patrick/{config,data,features,models,pipeline,selection,simulate,tracking,tuning,validation,webapp}
./marketml/tests
./notebooks/{archive,final_campaign,production,research,validation}
./patrick
./patrick/.impeccable
./patrick/.vscode
./patrick/configs/examples
./patrick/patrick/{config,data,features,models,pipeline,selection,simulate,tracking,tuning,validation,webapp}
./patrick/tests
```

**Deux arborescences top-level distinctes existent réellement et
simultanément à la racine du dépôt** : `./marketml/` et `./patrick/`. Mesure
quantitative :

```
$ find ./marketml -iname "*.py" -not -path "*__pycache__*" | wc -l
0
$ du -sh ./marketml
1.1M

$ find ./patrick -iname "*.py" -not -path "*__pycache__*" | wc -l
113
$ du -sh ./patrick
2.8M
```

**`./marketml/` ne contient AUCUN fichier source `.py`** — uniquement des
`.pyc` compilés obsolètes (100 fichiers, cf. A8) et des `.egg-info`. C'est un
résidu mort : la Phase 5.1 (`git mv marketml/ patrick/`, commit `38760ef`,
déjà présent dans notre historique) a renommé la vraie arborescence source, ce
qui aurait dû faire disparaître `./marketml/` du suivi — au lieu de ça, une
copie fantôme de son ancien contenu (pycache uniquement) est restée trackée
sous son ancien nom.

**`./patrick/` est la seule arborescence contenant du code source réel**
(113 fichiers `.py`, `configs/examples/*.yaml`, `tests/`) — c'est la
référence actuelle, sans ambiguïté sur ce point précis. `./notebooks/`
(28M, 53 notebooks) est une troisième zone, indépendante, contenant
l'historique de la campagne de recherche VIX (pas du code applicatif).

---

## A6 — Fichiers volumineux ou binaires versionnés

```
$ git ls-files | grep -E "\.db$|\.sqlite$|\.parquet$|\.joblib$|\.pkl$"
(vide)
```

**Aucun fichier de base de données, modèle sérialisé ou snapshot Parquet
versionné.** Point positif confirmé.

```
$ git ls-files | xargs -I{} du -h {} | sort -rh | head -30
6.4M  notebooks/archive/VIX_ML3_original_uncorrected_with_outputs.ipynb
6.4M  notebooks/archive/VIX_ML3_original_uncorrected.ipynb
6.4M  notebooks/VIX_ML3.ipynb
1.9M  notebooks/archive/VIX_STACKING_FINAL.ipynb
928K  notebooks/archive/VIX_REGIME_CLUSTERING_EXPLORATION.ipynb
792K  notebooks/archive/VIX_STACKING_V2 (1).ipynb
592K  notebooks/archive/VIX_STACKING_V2.ipynb
... (53 notebooks au total, 26M cumulés)
```

Les gros fichiers sont exclusivement des notebooks Jupyter **avec sorties
embarquées** (graphiques). Plusieurs sont des **quasi-doublons évidents** :
`VIX_ML3.ipynb` / `VIX_ML3_original_uncorrected.ipynb` /
`VIX_ML3_original_uncorrected_with_outputs.ipynb` (3 × 6.4M), `VIX_STACKING_V2.ipynb` /
`VIX_STACKING_V2 (1).ipynb`, `VIX_EGARCH_SPX_AMPLITUDE.ipynb` avec 4 variantes
numérotées `(1)`/`(2)`/`(2) (1)`. Taille totale du dépôt : `.git` = 93M,
arbre de travail = 125M.

---

## A7 — `.gitignore`

```
$ cat .gitignore
cat: .gitignore: No such file or directory
```

**Aucun `.gitignore` à la racine du dépôt.** Un seul existe, à
`patrick/.gitignore` (ne couvre donc que ce sous-dossier, pas `marketml/` ni
la racine) :

```
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
build/
dist/
runs/
.patrick/
+ règles impeccable-live (hors sujet)
```

```
$ git check-ignore -v ~/.patrick/patrick.db
fatal: /root/.patrick/patrick.db: is outside repository at '/home/user/claude'
$ git check-ignore -v ~/.patrick/data
fatal: /root/.patrick/data: is outside repository at '/home/user/claude'
```

**La question ne se pose pas dans les termes attendus** : `~/.patrick/`
(= `/root/.patrick/` dans cet environnement) est physiquement **hors de
l'arborescence du dépôt** (`/home/user/claude`), donc structurellement
impossible à committer par erreur, gitignore ou pas. La ligne `.patrick/`
dans `patrick/.gitignore` protège en fait un chemin RELATIF
(`patrick/.patrick/`, s'il existait), pas le vrai chemin absolu utilisé par
l'application — redondant mais inoffensif. **Le vrai risque n'est pas là.**

---

## A8 — Fichiers suivis mais indésirables

```
$ git ls-files | grep -E "__pycache__|\.pyc$|\.DS_Store$|\.env$|secrets|api_key" | wc -l
100
```

**100 fichiers `.pyc` compilés sont versionnés**, tous sous
`marketml/marketml/__pycache__/` et `marketml/patrick/__pycache__/` (aucun
`.py` source correspondant, cf. A5) — le résidu mort a été committé à un
moment donné, probablement par un `git add -A` non filtré exécuté avant
l'existence du `.gitignore` de `patrick/`, sur l'ancien chemin `marketml/`.

```
$ git ls-files | grep -iE "\.env|secret|api_key|apikey|token|credential"
patrick/patrick/webapp/static/tokens.css
```

Faux positif vérifié : `tokens.css` est un fichier de design (variables CSS,
palette de couleurs), pas un secret. Contenu inspecté, aucune valeur de clé
en dur trouvée par ailleurs (`grep FRED_API_KEY\s*=\s*["'][a-zA-Z0-9]`
sur tout le dépôt : vide). **Aucun secret versionné détecté.**

---

## A9 — Doublons de logique statistique (DM / PBO / DSR)

**Sur la branche actuelle** (`claude/marketml-vix-setup-qn43wf`) :

```
$ find . -iname "*.py" -not -path "*__pycache__*" | xargs grep -l "diebold"
patrick/patrick/validation/diebold_mariano.py   (implémentation)
patrick/patrick/pipeline/engine.py              (appelant)
patrick/patrick/tracking/{report,stats,db}.py   (persistance/lecture)
patrick/patrick/worker.py                       (passe-plat)
patrick/patrick/config/{defaults,schema}.py     (config X5, cf. session précédente)
patrick/tests/test_{diebold_mariano,fdr_integration,pipeline_smoke}.py

$ find . -iname "*.py" -not -path "*__pycache__*" | xargs grep -l "class.*PBO\|def compute_pbo"
patrick/patrick/validation/pbo.py               (seule implémentation)

$ find . -iname "phase9*"
(vide)
```

**Sur notre branche, une seule implémentation de chaque (DM, PBO), pas de
`phase9.py`.** Le doute signalé par une session précédente concerne en
réalité une **branche distincte, jamais fusionnée chez nous** :

```
$ git log --all --oneline -- "*/phase9.py"
7f84761 Implement Phase 9 features and updates across multiple modules
```

`patrick/patrick/phase9.py` (767 lignes) existe **uniquement** sur
`origin/agents/accelerer-entrainement-modeles`, fusionnée dans `origin/main`
— absente de notre arbre de travail actuel. Contenu inspecté
(`git show origin/main:patrick/patrick/phase9.py`) :

```python
from patrick.validation.diebold_mariano import diebold_mariano
from patrick.validation.fdr import benjamini_hochberg
...
def signal_dm_summary(...):
    result = diebold_mariano(loss_a, loss_b)   # réutilise l'implémentation existante
```

**`phase9.py` ne réimplémente PAS Diebold-Mariano ni PBO/DSR** — c'est une
couche supérieure (agrégation de signaux, moteur de stratégie/portefeuille,
journal de décision, simulation d'exécution) construite AU-DESSUS des
primitives `validation/` existantes, en les import ant correctement.

**Réserve identifiée, secondaire** : `phase9.py::determine_signal_quality_status`
importe `benjamini_hochberg` mais ne l'utilise pas — il compte naïvement
`p_value <= alpha` sans correction FDR, dans une fonction séparée qui
coexiste avec la correction proprement implémentée. Pas un doublon à
proprement parler, mais un raccourci moins rigoureux à surveiller si cette
fonction est un jour utilisée pour une décision de production.

**Découverte plus grave, hors du périmètre strict d'A9 mais directement liée** :
le fichier PARTAGÉ `validation/diebold_mariano.py` a **divergé de contenu**
entre notre branche et `origin/main` :

```
$ git diff claude/marketml-vix-setup-qn43wf origin/main -- patrick/patrick/validation/diebold_mariano.py
     n = len(d)
+    d_mean = float(np.mean(d))
     if n < 10:
-        return {"dm_stat": np.nan, "p_value": np.nan, "n_obs": n, "mean_loss_diff": np.nan}
+        return {"dm_stat": 0.0, "p_value": 1.0, "n_obs": n, "mean_loss_diff": round(d_mean, 6)}
```

Sur `origin/main`, quand il y a moins de 10 observations, la fonction
retourne désormais **`dm_stat=0.0, p_value=1.0`** (résultat interprété comme
"testé, aucune différence significative") **au lieu de `NaN`** (résultat
correct : "impossible à tester, donnée insuffisante"). C'est une régression
de correction : un signal non testable devient silencieusement un signal
"non significatif", ce qui n'est pas la même affirmation statistique.

Le test associé sur `origin/main` s'appelle toujours
`test_dm_too_few_observations_returns_nan` et **affirme toujours
`assert np.isnan(out["dm_stat"])`** — donc soit ce test échoue actuellement
sur `origin/main` (implémentation et test contradictoires), soit il n'a pas
été relancé après ce changement. **Je n'ai pas basculé sur `origin/main` pour
l'exécuter réellement** (cela aurait perturbé l'arbre de travail contenant le
travail non commité de la session précédente) — cette conclusion est une
inférence forte à partir du diff et du texte du test, pas une exécution
confirmée. À vérifier par exécution directe si `origin/main` doit un jour
être fusionné.

---

## A10 — Cohérence dépôt local / GitHub distant

```
$ git fetch --all
From https://github.com/LP-D/claude
   5ec16eb..0df43f4  main  -> origin/main
```

`origin/main` a avancé une nouvelle fois pendant cette session d'audit
(0df43f4) — cible mouvante, à refetcher avant toute décision de fusion.

```
$ git status -sb
## claude/marketml-vix-setup-qn43wf...origin/claude/marketml-vix-setup-qn43wf
 M patrick/patrick/config/defaults.py
 ... (12 fichiers modifiés, 2 fichiers non suivis — cf. A1)

$ git log HEAD..origin/claude/marketml-vix-setup-qn43wf --oneline
(vide)

$ git log origin/claude/marketml-vix-setup-qn43wf..HEAD --oneline
(vide)
```

**Notre branche est exactement synchronisée avec son propre remote** — ni en
avance ni en retard sur `origin/claude/marketml-vix-setup-qn43wf`. Le seul
écart local est le travail non commité de la session précédente (A1). La
désynchronisation réelle est ailleurs : avec `origin/main` (21 commits
d'écart, cf. A2/A4/A9), pas avec notre propre remote de travail.

---

## SYNTHÈSE

### 1. Structure confirmée

- **Racine réelle du dépôt** : `/home/user/claude` (pas `/home/user/claude/patrick`
  ni `/home/user/claude/marketml` — ce sont des sous-dossiers du même dépôt).
- **Branche de travail active et de référence pour cette session** :
  `claude/marketml-vix-setup-qn43wf`, synchronisée avec son remote (A10).
- **Branche par défaut du dépôt GitHub** : `main`, mais **notre branche n'y
  est pas fusionnée** et en diverge de 21 commits (A2).
- **Arborescence de code source de référence** : `patrick/patrick/` (113
  fichiers `.py` réels, installable, testée). `marketml/` (racine) est un
  résidu mort à 0 fichier source, preuve à l'appui (A5).
- **Remote `origin`** pointe vers une URL (`LP-D/claude`) que GitHub indique
  avoir déplacée — ambiguïté signalée, non tranchée (A1).

### 2. Problèmes identifiés, par gravité

1. **Aucun secret versionné** — vérifié, rien à signaler en priorité absolue (A8).
2. **Divergence de contenu sur un fichier statistique partagé** entre notre
   branche et `origin/main` (`validation/diebold_mariano.py`), avec une
   régression probable (NaN → 0.0/1.0 sur cas insuffisant, test
   potentiellement contradictoire côté `origin/main`) — **le point le plus
   important à trancher avant toute fusion future** (A9).
3. **Trois lignées de développement non réconciliées** sur `origin/main` vs
   notre branche : lancement batch multi-cible + bouton Relancer (5f54117),
   Phase 9 (agrégation de signaux/stratégie/portefeuille, 7f84761), et notre
   propre lot D2-D4/Phase 4.8/impeccable — 21 commits d'écart cumulés (A2/A4).
4. **Résidu mort volumineux** : arborescence `marketml/` à la racine (0
   fichier source, 1.1M, 100 `.pyc` obsolètes trackés) qui n'aurait jamais dû
   survivre au renommage Phase 5.1 (A5/A8).
5. **`.gitignore` incomplet** : absent à la racine, présent seulement sous
   `patrick/` — n'a jamais protégé `marketml/`, d'où les `.pyc` orphelins
   toujours suivis (A7/A8).
6. **24 branches de campagne notebooks figées depuis 2 semaines**
   (`claude/vix-*` + `results/vix-*`) — probablement des archives légitimes
   de résultats d'expériences, pas du désordre actif, mais jamais confirmées
   comme fusionnées ou définitivement closes (A2).
7. **Notebooks volumineux en quasi-doublon** (jusqu'à 4 copies numérotées du
   même fichier, ex. `VIX_EGARCH_SPX_AMPLITUDE*.ipynb`) gonflant le dépôt de
   plusieurs Mo sans valeur ajoutée apparente (A6).
8. **Branche locale `main` totalement obsolète** (212 commits de retard,
   jamais mise à jour depuis le tout premier commit) — sans conséquence
   fonctionnelle tant qu'elle n'est pas utilisée, mais trompeuse si consultée
   par erreur (A2).

### 3. Proposition de rangement (à valider avant exécution — RIEN n'est fait)

- **Purge/consolidation `marketml/`** : confirmer que `patrick/patrick/` est
  bien la seule source de vérité, puis retirer du suivi (`git rm --cached`,
  jamais suppression sèche sans confirmation) les 100 `.pyc` orphelins et
  l'arborescence `marketml/` à la racine — en conservant son historique via
  les commits déjà existants (rien à archiver séparément, l'historique git le
  garde déjà).
- **`.gitignore` racine** : en ajouter un à `/home/user/claude/.gitignore`
  couvrant au minimum `__pycache__/`, `*.pyc`, `*.egg-info/`, `.pytest_cache/`
  — pour que ce problème ne se reproduise pas sur n'importe quel futur
  sous-dossier, pas seulement `patrick/`.
- **Décision de fusion `origin/main`** : à trancher explicitement — fusionner
  les 21 commits (batch multi-cible, Phase 9) dans notre branche, ou
  documenter pourquoi notre branche reste volontairement en retard. Ne pas
  fusionner sans avoir d'abord résolu la divergence `diebold_mariano.py`
  (point 2 ci-dessus) — un merge automatique choisirait arbitrairement une
  des deux versions sans vérifier laquelle est correcte.
- **Notebooks en doublon** : identifier lesquelles des copies numérotées
  (`(1)`, `(2)`, `(2) (1)`) sont réellement distinctes vs de simples
  ré-exports accidentels, avant suppression — nécessite un diff de contenu
  notebook par notebook, pas une suppression automatique par nom.
- **Branches de campagne (`claude/vix-*`, `results/vix-*`)** : confirmer
  qu'elles sont closes (probable, 2 semaines d'inactivité) puis les laisser
  telles quelles sur le remote (elles ne coûtent rien tant qu'elles ne sont
  pas re-fetchées en local) — pas de suppression proposée sans confirmation
  qu'aucun travail n'y est encore attendu.
- **Branche locale `main`** : la resynchroniser (`git fetch` + `git checkout
  main && git reset --hard origin/main`) ou la supprimer localement — aucun
  risque, elle n'est référencée par rien d'actif.

**Arrêt ici, dans l'attente de validation avant le bloc B.**
