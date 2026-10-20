# CONTRIBUTING

## Commits fréquents pendant les sessions longues (agent ou humain)

**Règle : committer sur une branche de travail au plus tard toutes les 45
minutes, ou tous les 5 fichiers modifiés — le premier des deux seuils
atteint.**

### Pourquoi ce seuil précis

- **45 minutes** : plus court que la durée observée des incidents de
  bascule silencieuse de conteneur déjà documentés (`docs/historique/audits-2026-09.md`,
  `scripts/check_env_sync.sh`) — ces bascules ont eu lieu en plein milieu
  de sessions ayant accumulé plusieurs **heures** de travail non committé.
  Un seuil de 45 minutes borne la perte maximale possible à une fraction de
  ce qui a été perdu concrètement (D6, ~29 fichiers de traduction, plusieurs
  heures de travail).
- **5 fichiers modifiés** : sur ce projet, une unité de travail cohérente
  (une traduction de fichier, un correctif ciblé, une nouvelle feature avec
  son test) touche rarement plus de 5 fichiers à la fois. Ce seuil capture
  le cas où le travail progresse vite en nombre de fichiers mais où 45
  minutes ne sont pas encore écoulées — évite d'accumuler un lot trop
  hétérogène avant le premier commit.
- Les deux seuils sont combinés (pas seulement l'un ou l'autre) parce que
  ni la durée ni le nombre de fichiers ne prédisent seuls le risque : une
  session peut modifier peu de fichiers mais très longtemps (un seul
  fichier dense, ex. `pipeline/engine.py`), ou beaucoup de fichiers très
  vite (traduction mécanique répétitive, ex. le bloc D6 de
  `docs/historique/audits-2026-09.md`).

### Comment

1. Committer sur la branche de travail en cours (pas de nouvelle branche à
   chaque fois) dès qu'un seuil est atteint, même si le lot de travail
   n'est pas "fini" au sens produit — un message de commit `wip:` explicite
   est acceptable pour ces commits intermédiaires.
2. Une fois le lot de travail réellement terminé et vérifié (tests verts,
   revue), **squasher les commits intermédiaires** avant d'ouvrir ou de
   mettre à jour la pull request — l'historique final visible en review
   reste un commit logique par unité de travail, pas un journal de
   checkpoints.
3. Ce squash se fait via `git rebase -i` sur la branche de travail avant
   push final, ou en écrasant l'historique local avant le premier push si
   le travail n'a jamais quitté la machine — jamais en réécrivant
   l'historique d'une branche déjà partagée/revue par quelqu'un d'autre.

### Ce que ça ne change pas

Cette règle porte sur la fréquence des commits **locaux**, pas sur quand
pousser ni sur quand ouvrir une PR — une session peut toujours choisir de
ne pousser/ouvrir la PR qu'une fois le travail complet et testé,
conformément aux instructions explicites du moment. L'objectif est
uniquement de limiter l'exposition à une perte totale de travail non
committé en cas de bascule d'environnement, pas de changer le rythme de
revue ou de publication.

## Gardes git (dépôt public)

- **`.gitignore`** : ni `.env`, ni bases SQLite (`*.db`, `-wal`, `-shm`), ni `runs/`, ni l'état local des outils
  d'agent (`.claude/`, sauf `.claude/settings.json`, versionné exprès). `patrick/tests/test_repo_hygiene.py`
  vérifie ce que git fait de ces chemins.
- **Hook `pre-push`** (`.githooks/pre-push`) : refuse la suppression d'une branche ou d'une étiquette et la
  réécriture d'un historique publié (push forcé, étiquette déplacée), sauf sur `wip/`, `tmp/`, `golden-regen/`, `mutation-check/`.
  À activer une fois par copie du dépôt (l'installeur de l'application le fait) :
  `git config core.hooksPath .githooks`. Passage exprès : `PATRICK_ALLOW_UNSAFE_PUSH=1 git push ...`.
- **Faits bruts** : `sh patrick/scripts/git_facts.sh` imprime branche, commit, avance/retard, sommet de la branche
  lu sur le distant, fichiers modifiés — de quoi vérifier le compte rendu d'un agent (en complément du garde
  d'entrée `patrick/scripts/check_env_sync.sh`).
- **Historique** : une donnée personnelle déjà poussée reste dans l'historique public même après suppression du
  fichier ; la retirer demande de réécrire l'historique (décision à prendre explicitement).
- **Test de validité statistique** : `pytest -m validity` (≈ 15 min) fait tourner le pipeline sur des marches aléatoires et des
  mondes à signal (`patrick/tests/test_null_world_validity.py`) ; exclu de `pytest` et de la CI poussée, il tourne chaque
  lundi (`.github/workflows/validity.yml`). `PATRICK_WORLD_CACHE_DIR=<dossier>` conserve les mondes calculés (reprise possible).
