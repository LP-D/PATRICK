#!/usr/bin/env bash
# Garde-fou contre la désynchronisation silencieuse du worktree local --
# incident du 2026-08-07 (session de consolidation) : le conteneur d'exécution
# a redémarré depuis un instantané figé antérieur à plusieurs sessions de
# travail poussées et fusionnées, sans qu'aucune erreur ne le signale --
# `git log -1` affichait un historique valide (juste ancien), `import patrick`
# résolvait vers un chemin qui existait réellement sur disque (juste le
# mauvais). Rien ne criait, jusqu'au rejet d'un `git push` (non-fast-forward).
#
# A LANCER EN PRÉAMBULE de toute session d'agent sur ce dépôt, avant toute
# autre commande git ou Python. Pas une automatisation CI -- une commande
# manuelle systématique.
#
# Sortie : une ligne "ENV_SYNC: ..." avec le statut des deux vérifications.
# Code de sortie non nul (1) si l'une des deux échoue -- ARRÊTER la session
# et rapporter avant de continuer, ne jamais travailler sur un état non
# confirmé (cf. session de consolidation, règle G0).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "ENV_SYNC: FAIL -- impossible de localiser la racine du dépôt git"
    exit 1
fi
cd "$REPO_ROOT" || exit 1

FAIL=0

# --- 1. HEAD local vs distant : ancêtre légitime, pas divergent ---
LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
if [ -z "$LOCAL_HEAD" ]; then
    echo "ENV_SYNC: FAIL -- HEAD local introuvable"
    exit 1
fi

REMOTE_HEAD="$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)"
COMPARE_TARGET="origin/$BRANCH"
if [ -z "$REMOTE_HEAD" ]; then
    # Branche locale sans homologue distant (ex : fusionnée puis auto-supprimée
    # après merge de PR, cf. incident du 2026-08-07 -- PR #39) -- repli sur
    # origin/main comme référence plutôt que d'échouer sans explication.
    git fetch origin main -q 2>/dev/null
    REMOTE_HEAD="$(git rev-parse origin/main 2>/dev/null)"
    COMPARE_TARGET="origin/main (repli : '$BRANCH' absente du distant)"
fi

if [ -z "$REMOTE_HEAD" ]; then
    HEAD_STATUS="FAIL (remote injoignable -- réseau ou URL origin à vérifier)"
    FAIL=1
elif [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    HEAD_STATUS="OK (identique à $COMPARE_TARGET)"
elif git merge-base --is-ancestor "$LOCAL_HEAD" "$REMOTE_HEAD" 2>/dev/null; then
    HEAD_STATUS="OK (ancêtre légitime de $COMPARE_TARGET -- en retard, pas divergent)"
elif git merge-base --is-ancestor "$REMOTE_HEAD" "$LOCAL_HEAD" 2>/dev/null; then
    HEAD_STATUS="OK (en avance sur $COMPARE_TARGET -- travail local non encore poussé)"
else
    HEAD_STATUS="FAIL -- DIVERGENT : historiques incompatibles avec $COMPARE_TARGET"
    FAIL=1
fi

# --- 2. import patrick résout sous CE worktree, pas un chemin résiduel ---
# Exécuté depuis /tmp, jamais depuis REPO_ROOT ni un de ses sous-dossiers :
# un sous-dossier nommé "patrick" dans le cwd est traité par Python comme un
# namespace package implicite et masque silencieusement l'installation
# éditable réelle -- __file__ vaut alors None SANS lever d'erreur (source du
# faux-négatif rencontré en session, cf. rapport). /tmp n'a par construction
# aucun sous-dossier "patrick" pour reproduire ce piège.
IMPORT_PATH="$(cd /tmp && python3 -c "import patrick; print(patrick.__file__ or '')" 2>/dev/null)"
if [ -z "$IMPORT_PATH" ]; then
    IMPORT_STATUS="FAIL (import patrick échoue, ou __file__ vide/None)"
    FAIL=1
elif [[ "$IMPORT_PATH" == "$REPO_ROOT/patrick/patrick/"* ]]; then
    IMPORT_STATUS="OK ($IMPORT_PATH)"
else
    IMPORT_STATUS="FAIL -- résout hors du worktree courant : $IMPORT_PATH"
    FAIL=1
fi

echo "ENV_SYNC: HEAD=$LOCAL_HEAD [$HEAD_STATUS] | import_patrick=$IMPORT_STATUS"

exit $FAIL
