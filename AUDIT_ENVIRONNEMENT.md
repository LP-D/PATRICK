# AUDIT_ENVIRONNEMENT.md — Emplacement, connexion, persistance

Session d'audit, exécutée en aval du commit + push + PR des blocs D4/D6
(traduction), demandés par ailleurs dans la même conversation. Aucune
action destructive. Toutes les commandes ci-dessous ont été exécutées
depuis `/home/user/claude` (racine réelle du dépôt) sauf mention contraire.

**Contexte déclencheur** : en préparant le commit de D6, j'ai découvert que
tout le travail non committé de cette session (D6, ~29 fichiers, plusieurs
heures) avait disparu du disque — les fichiers étaient revenus à leur état
français d'origine, alors même que mes appels d'outils dans cette
conversation montraient des éditions réussies. L'investigation qui a suivi
constitue l'essentiel de cet audit.

---

## E1 — Identité et emplacement de l'environnement courant

```
$ pwd
/home/user/claude/patrick
$ hostname
vm
$ whoami
root
$ git rev-parse --show-toplevel
/home/user/claude
$ uptime
21:00:39 up 2 min, 0 user, load average: 0.16, 0.12, 0.05
$ cat /proc/uptime
169.70 616.94
```

**Point central** : au moment de cette vérification, la machine tournait
depuis **2 minutes**. Or cette même conversation avait, dans les heures
précédentes, exécuté des commandes shell dans un environnement où des
processus tournaient depuis 3h+ (suite de tests complète en arrière-plan,
~6h25 au total). Il s'agit donc de deux instances différentes du
"sandbox", pas de la même machine ayant simplement redémarré un service.

Confirmation indirecte : tous les timestamps de fichiers sous
`/home/user/claude/patrick` (mtime, ctime, **birth time**) sont figés à
`2026-08-07 13:55:36` ou `15:02` (heure d'un checkpoint antérieur), pas à
l'heure réelle de mes éditions de cette session (2026-08-08, après-midi/
soir). Une `birth time` figée pour des fichiers que j'avais explicitement
réécrits est la preuve la plus directe : le disque que je voyais dans les
derniers appels d'outils n'est pas celui sur lequel mes éditions
précédentes avaient été écrites — c'est une image restaurée depuis un
instantané antérieur à ces éditions.

---

## E2 — État de synchronisation local/distant, ici

```
$ git remote -v
origin  https://github.com/LP-D/claude (fetch)
origin  https://github.com/LP-D/claude (push)

$ git fetch --all
From https://github.com/LP-D/claude
   3189d54..913ed82  claude/marketml-vix-setup-qn43wf -> origin/claude/marketml-vix-setup-qn43wf
 * [new branch]      agents/accelerer-entrainement-modeles -> origin/...
 * [new branch]      lp-d-rangement-patrick -> origin/...

$ git status -sb
## claude/marketml-vix-setup-qn43wf...origin/claude/marketml-vix-setup-qn43wf [behind 1]
```

**Bonne nouvelle découverte ici** : le HEAD local (`3189d54`) était en
retard d'**un seul commit** sur le distant (`913ed82`) — pas divergent,
pas perdu. Ce commit `913ed82` (« docs: translate code comments/docstrings
to English (D1-D5) ») contenait déjà tout le travail de traduction D4 que
je pensais avoir perdu : il avait été committé et poussé par le conteneur
précédent avant que celui-ci ne soit recyclé/remplacé, simplement **après**
le dernier instantané utilisé pour recréer ce nouveau conteneur.

Vérification que le contenu du working tree local (avant resynchronisation)
correspondait exactement, fichier par fichier, à `913ed82` :

```
$ git diff 913ed82 -- patrick/cli.py
(vide)
$ git diff 913ed82 --stat
(vide)
```

Résolution : `git reset 913ed82` (avance le pointeur de branche vers le
commit distant, sans toucher au working tree — déjà identique). **Zéro
perte pour D4.**

**D6 en revanche était réellement perdu** : ces 29 fichiers avaient été
traduits *après* le commit `913ed82` et *après* le dernier instantané du
conteneur (le commit `913ed82` est daté du 8 août 02:57 UTC ; le
travail D6 de cette session s'est déroulé après cela, dans le même
conteneur qui a ensuite été recyclé sans jamais committer D6). Rien à
récupérer depuis git — ces éditions n'avaient jamais atteint l'index ni un
commit. Récupération effectuée en réappliquant les mêmes traductions
depuis le contexte de la conversation elle-même (chaque appel d'outil de
traduction restait visible dans l'historique de session), puis re-vérifiées
fichier par fichier et par la suite de tests avant nouveau commit
(`cbe5f54`).

**État actuel, après commit + rebase + push documentés dans la même
conversation** :

```
$ git log --oneline -5
cbe5f54 docs: translate remaining French comments/docstrings to English (D6)
7fe1761 docs: translate code comments/docstrings to English (D1-D5)
a227f36 Merge pull request #40 from LP-D/claude/marketml-vix-setup-qn43wf
3189d54 Ajoute scripts/check_env_sync.sh : garde-fou contre la désynchronisation silencieuse
b10daf4 Merge pull request #39 from LP-D/claude/marketml-vix-setup-qn43wf

$ git status -sb
## claude/marketml-vix-setup-qn43wf...origin/claude/marketml-vix-setup-qn43wf
(rien d'autre -- à jour, propre)
```

Local et distant sont identiques après le push (`--force-with-lease`,
nécessaire car la branche avait été rebasée sur `origin/main` entre-temps).

---

## E3 — Persistance de cet environnement lui-même

```
$ ls -la /home/user/claude/patrick/.git
ls: cannot access '/home/user/claude/patrick/.git': No such file or directory
```

Normal, pas une anomalie : `.git` vit à la racine réelle du dépôt,
`/home/user/claude/.git` (cf. E5) — `patrick/` n'est qu'un sous-dossier.

```
$ stat -c '%y' /home/user/claude
2026-08-07 13:55:36 (Birth identique sur la quasi-totalité des fichiers du worktree)
```

**Conclusion, à partir de ce que ce sandbox peut voir de lui-même** :
l'environnement est **éphémère**, recréé depuis un instantané à chaque
(re)provisionnement, pas une machine persistante entre les sessions. C'est
documenté dans mes instructions système ("the container is reclaimed after
a period of inactivity... anything worth keeping needs to be committed and
pushed first") — ce que cette session vient de vérifier par les faits, pas
seulement par la documentation. **Ce n'est pas déterminable avec certitude
depuis l'intérieur du sandbox à quel événement précis (inactivité, durée
max de session, autre) a déclenché ce remplacement précis** — seul le
résultat (nouveau conteneur, instantané antérieur) est observable.

Point notable : ce n'est pas un cas isolé. `scripts/check_env_sync.sh`
(committé le 2026-08-07, PR #40, déjà mergée) documente un incident
**identique** survenu la veille (« le conteneur d'exécution a redémarré
depuis un instantané figé antérieur à plusieurs sessions de travail
poussées et fusionnées, sans qu'aucune erreur ne le signale »). Ce script
sert justement de garde-fou contre cette classe de problème — mais il doit
être lancé manuellement en **préambule** d'une session ; il ne protège pas
contre une bascule survenant **en cours** de session (exactement le cas
rencontré ici : la bascule a eu lieu au milieu d'une conversation déjà
longue, sans point de reprise identifiable pour relancer le script avant
qu'elle ne se produise).

---

## E4 — Configuration GitHub réelle, vue distante

```
$ git ls-remote origin | head -3
a227f36c48e13548d712a0f3d129e24b0a2035bc  HEAD
...
```

Accès à l'API GitHub disponible via les outils MCP (pas de `gh` CLI dans
cet environnement, conformément à la configuration de session).

**Renommage du dépôt confirmé** (déjà repéré dans `AUDIT_REPO.md`, une
session antérieure) : le remote local pointe vers
`https://github.com/LP-D/claude`, mais l'API GitHub renvoie
`full_name: "LP-D/PATRICK"` pour ce même dépôt, et un `git push` day
affiche explicitement :

```
remote: This repository moved. Please use the new location:
remote:   https://github.com/LP-D/PATRICK.git
```

Le push aboutit quand même (GitHub suit la redirection) — **statu quo
inchangé depuis l'audit précédent** : je signale la situation, je ne
corrige pas l'URL locale unilatéralement (ce n'est pas déterminant tant
que la redirection fonctionne, et une correction demanderait de valider
que rien d'autre ne dépend du nom `claude`).

**Pull requests** : 41 PR au total sur ce dépôt, la totalité fermées/
mergées sauf **une seule ouverte** — #41 (« docs: translate French
comments/docstrings to English (D1-D6) »), la PR créée dans cette même
conversation pour le travail D4/D6, en brouillon, avec suivi CI/commentaires
activé.

Point notable retrouvé en listant les PR : #40 (« Ajoute
scripts/check_env_sync.sh ») était déjà **mergée** avant que cette session
ne pousse D4/D6 — le commit `913ed82` (D4) avait donc été poussé
directement sur la branche `claude/marketml-vix-setup-qn43wf` **après** la
fusion de sa propre PR, sans nouvelle PR ouverte à ce moment-là. C'est
pour cette raison qu'une nouvelle PR (#41), et non une réouverture de #40,
a été créée pour ce travail — cohérent avec les instructions de session sur
ce cas de figure.

**Branches distantes** : 47 branches au total (`git branch -a | wc -l`
avant fetch complet), dont une longue liste de branches `claude/...` et
`results/...` correspondant à des sessions d'agent antérieures, la plupart
déjà fusionnées et non nettoyées.

---

## E5 — Recherche d'autres copies du projet, dans le système de fichiers accessible

```
$ find / -maxdepth 6 -iname "patrick" -type d 2>/dev/null | grep -v "^/proc"
/home/user/claude/marketml/patrick
/home/user/claude/patrick
/home/user/claude/patrick/patrick

$ find / -maxdepth 4 -iname "*.git" 2>/dev/null | grep -v "^/proc"
/workspace/claude-setup/.git
/home/user/claude/.git
/opt/rbenv/.git
/opt/nvm/.git
```

**Un seul dépôt git réel sur ce système** : `/home/user/claude/.git`. Les
deux autres `.git` (`rbenv`, `nvm`) sont des outils système sans rapport.
`/workspace/claude-setup` est hors du périmètre de ce projet.

Ce dépôt unique contient **deux arborescences de code source à sa
racine** :
- `patrick/` — l'arborescence active, suivie par git, c'est elle que
  toutes les commandes `git status`/`git log` de cette session concernent.
- `marketml/` — une arborescence **legacy**, contenant elle-même un
  `marketml/marketml/` et un `marketml/patrick/` imbriqués. Vérifié
  **explicitement ignorée par git** :
  ```
  $ git status --short --ignored marketml/
  !! marketml/
  $ git ls-files marketml/ | wc -l
  0
  ```
  Elle n'est ni suivie, ni un doublon actif du dépôt — un résidu du
  renommage `marketml → patrick`, volontairement exclu. C'est exactement
  la source du piège documenté dans `check_env_sync.sh` : un sous-dossier
  nommé `patrick` dans le cwd (ici `marketml/patrick/`) est traité par
  Python comme un namespace package implicite qui peut masquer
  silencieusement l'installation éditable réelle si l'on exécute une
  commande depuis le mauvais répertoire.

**Aucune deuxième copie active/synchronisée détectée dans ce sandbox** —
il n'y en a structurellement qu'une, correctement identifiée.

**Ce que je ne peux PAS vérifier depuis ici, à signaler explicitement à
l'utilisateur** : l'existence et l'état d'une copie locale sur la machine
Windows mentionnée dans les préférences de collaboration (usage courant
via Git Bash/VS Code). Si ce dossier de travail local se trouve à
l'intérieur d'un dossier synchronisé OneDrive, c'est un risque réel et
indépendant de tout ce qui se passe dans ce sandbox : OneDrive et Git
gèrent tous deux les mêmes fichiers avec des sémantiques différentes
(verrouillage, renommage, résolution de conflit), et ça peut produire des
corruptions ou des conflits silencieux sans lien avec l'incident de
bascule de conteneur documenté ici. **Question à te poser directement, je
ne peux pas y répondre à ta place : ton dossier de travail `patrick` en
local est-il à l'intérieur ou à l'extérieur d'un dossier synchronisé par
OneDrive, et si à l'intérieur, as-tu déjà observé des conflits ou des
fichiers dupliqués (suffixés type "nom (2).py") ?**

---

## E6 — État du `.gitignore` face aux artefacts locaux volumineux

```
$ cat patrick/.gitignore
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
build/
dist/
runs/
.patrick/
... (règles impeccable-live, sans rapport)

$ git check-ignore -v ~/.patrick/patrick.db
fatal: '/root/.patrick/patrick.db' is outside repository at '/home/user/claude'
```

`~/.patrick/` (base SQLite + cache local) est en dehors de l'arbre du
dépôt (`/root/.patrick`, alors que le dépôt racine est
`/home/user/claude`) — la question de l'exclusion par `.gitignore` ne se
pose donc même pas, elle est physiquement hors de portée de git. C'est la
configuration attendue (`patrick/data/store.py::_default_store_dir`,
`~/.patrick/store` par défaut, hors du worktree par construction).

`.patrick/` figure bien dans `.gitignore` du sous-dossier `patrick/`
malgré tout (garde-fou redondant mais inoffensif si jamais un run était
lancé avec un `PATRICK_STORE_ROOT` pointant par erreur dans l'arbre du
dépôt). **Rien de cassé ici.**

---

## E7 — Workflows CI/CD

```
$ find . -path "*/.github/workflows/*" -name "*.yml"
(aucun résultat)
```

**Aucun workflow CI/CD sur ce dépôt.** Confirmé par deux moyens
indépendants : recherche de fichiers locale (ci-dessus) et absence de tout
check de statut associé aux PR consultées via l'API GitHub. Aucune
vérification automatique (tests, lint) ne protège donc ce dépôt contre une
régression poussée par erreur — chaque session d'agent (ou toi en local)
est actuellement la seule ligne de défense, via l'exécution manuelle de
`pytest tests/ -q -m ""`. **Point ouvert, pas corrigé dans cette session**
(hors périmètre de l'audit demandé, et une décision produit — ex. GitHub
Actions gratuit tant que le dépôt est public — t'appartient).

---

## SYNTHÈSE

### 1. Carte des copies connues

| Emplacement | Nature | Fait autorité ? |
|---|---|---|
| `/home/user/claude` (ce sandbox, conteneur recréé à chaque session) | Dépôt git unique, `patrick/` actif + `marketml/` legacy ignoré | **Oui, pour tout travail poussé sur GitHub** — mais éphémère localement, rien de non-committé n'y survit entre deux sessions |
| `github.com/LP-D/claude` → redirige vers `LP-D/PATRICK` | Distant unique | **Source de vérité ultime** — c'est ce qui doit faire foi en cas de doute |
| Machine Windows locale (OneDrive ?) | Non vérifiable depuis ici | **Inconnu — à vérifier par toi** (cf. E5) |

Il n'existe qu'**un seul** dépôt distant et qu'**une seule** copie de
travail active par sandbox — la complexité ne vient pas d'une
multiplication de copies, mais du caractère éphémère du sandbox combiné à
l'absence de commit fréquent.

### 2. Risques identifiés

- **Confirmé, reproduit dans cette session** : bascule silencieuse du
  conteneur vers un instantané antérieur, en cours de session, avec perte
  totale de tout travail non committé à ce moment-là (D6, plusieurs
  heures). Deuxième occurrence documentée de cette classe d'incident sur
  ce projet (la première a produit `check_env_sync.sh`, PR #40).
  **Recommandation directe** : committer plus souvent, même sur une
  branche de travail, plutôt que d'accumuler des heures de modifications
  non committées avant une vérification finale — la contrainte "aucun
  commit avant confirmation complète" (légitime pour éviter de polluer
  l'historique avec du travail non testé) doit être mise en balance avec
  ce risque de perte pure et simple. Une alternative : committer sur une
  branche/tag temporaire à intervalles réguliers, à squasher/nettoyer
  avant la PR finale.
- **check_env_sync.sh protège le début de session, pas le milieu.** Aucun
  mécanisme actuel ne détecte une bascule survenant après le premier
  message d'une conversation déjà en cours — à surveiller, pas de
  correctif proposé ici (changerait le comportement du harness, hors
  périmètre).
- **Renommage de dépôt non résolu dans la config locale** (`LP-D/claude`
  vs `LP-D/PATRICK`) — inoffensif tant que la redirection GitHub
  fonctionne, mais signalé pour la deuxième fois consécutive (audits
  successifs) sans décision prise.
- **Aucune CI** — aucune garde automatique contre une régression poussée
  par erreur sur ce dépôt.
- **Risque non vérifiable depuis ce sandbox** : conflit potentiel
  OneDrive/Git sur la machine Windows locale, si le dossier de travail y
  est synchronisé.

### 3. Questions à te poser explicitement (je n'y réponds pas à ta place)

1. Ton dossier de travail `patrick` en local (Windows) est-il à
   l'intérieur ou à l'extérieur d'un dossier synchronisé par OneDrive ?
   Si à l'intérieur, as-tu déjà observé des fichiers dupliqués ou des
   conflits de synchronisation dessus ?
2. Veux-tu que je committe plus fréquemment sur cette branche pendant les
   sessions longues (au prix d'un historique plus bruyant, à nettoyer
   avant merge), pour limiter l'exposition à ce type de perte ?
3. Le renommage `LP-D/claude` → `LP-D/PATRICK` : figé définitivement côté
   GitHub, ou dois-je mettre à jour l'URL du remote local pour éviter de
   dépendre de la redirection ?
4. CI/CD : veux-tu qu'on mette en place un workflow GitHub Actions minimal
   (au moins `pytest` sur push/PR) dans une session dédiée ?

**Aucune action corrective exécutée dans cette session au-delà de ce qui
était déjà en cours (commit D6 + rebase + push + PR, déjà réalisés avant
cet audit, conformément à l'instruction).**
