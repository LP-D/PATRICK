#!/usr/bin/env bash
# Garde-fou contre la dÃƒÂ©synchronisation silencieuse du worktree local --
# incident du 2026-08-07 (session de consolidation) : le conteneur d'exÃƒÂ©cution
# a redÃƒÂ©marrÃƒÂ© depuis un instantanÃƒÂ© figÃƒÂ© antÃƒÂ©rieur ÃƒÂ  plusieurs sessions de
# travail poussÃƒÂ©es et fusionnÃƒÂ©es, sans qu'aucune erreur ne le signale --
# `git log -1` affichait un historique valide (juste ancien), `import patrick`
# rÃƒÂ©solvait vers un chemin qui existait rÃƒÂ©ellement sur disque (juste le
# mauvais). Rien ne criait, jusqu'au rejet d'un `git push` (non-fast-forward).
#
# A LANCER EN PRÃƒâ€°AMBULE de toute session d'agent sur ce dÃƒÂ©pÃƒÂ´t, avant toute
# autre commande git ou Python. Pas une automatisation CI -- une commande
# manuelle systÃƒÂ©matique.
#
# Sortie : une ligne "ENV_SYNC: ..." avec le statut des deux vÃƒÂ©rifications.
# Code de sortie non nul (1) si l'une des deux ÃƒÂ©choue -- ARRÃƒÅ TER la session
# et rapporter avant de continuer, ne jamais travailler sur un ÃƒÂ©tat non
# confirmÃƒÂ© (cf. session de consolidation, rÃƒÂ¨gle G0).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$REPO_ROOT" ]; then
    echo "ENV_SYNC: FAIL -- impossible de localiser la racine du dÃƒÂ©pÃƒÂ´t git"
    exit 1
fi
cd "$REPO_ROOT" || exit 1

FAIL=0

# --- 1. HEAD local vs distant : ancÃƒÂªtre lÃƒÂ©gitime, pas divergent ---
LOCAL_HEAD="$(git rev-parse HEAD 2>/dev/null)"
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
if [ -z "$LOCAL_HEAD" ]; then
    echo "ENV_SYNC: FAIL -- HEAD local introuvable"
    exit 1
fi

REMOTE_HEAD="$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | cut -f1)"
COMPARE_TARGET="origin/$BRANCH"
if [ -z "$REMOTE_HEAD" ]; then
    # Branche locale sans homologue distant (ex : fusionnÃƒÂ©e puis auto-supprimÃƒÂ©e
    # aprÃƒÂ¨s merge de PR, cf. incident du 2026-08-07 -- PR #39) -- repli sur
    # origin/main comme rÃƒÂ©fÃƒÂ©rence plutÃƒÂ´t que d'ÃƒÂ©chouer sans explication.
    git fetch origin main -q 2>/dev/null
    REMOTE_HEAD="$(git rev-parse origin/main 2>/dev/null)"
    COMPARE_TARGET="origin/main (repli : '$BRANCH' absente du distant)"
fi

if [ -z "$REMOTE_HEAD" ]; then
    HEAD_STATUS="FAIL (remote injoignable -- rÃƒÂ©seau ou URL origin ÃƒÂ  vÃƒÂ©rifier)"
    FAIL=1
elif [ "$LOCAL_HEAD" = "$REMOTE_HEAD" ]; then
    HEAD_STATUS="OK (identique ÃƒÂ  $COMPARE_TARGET)"
elif git merge-base --is-ancestor "$LOCAL_HEAD" "$REMOTE_HEAD" 2>/dev/null; then
    HEAD_STATUS="OK (ancÃƒÂªtre lÃƒÂ©gitime de $COMPARE_TARGET -- en retard, pas divergent)"
elif git merge-base --is-ancestor "$REMOTE_HEAD" "$LOCAL_HEAD" 2>/dev/null; then
    HEAD_STATUS="OK (en avance sur $COMPARE_TARGET -- travail local non encore poussÃƒÂ©)"
else
    HEAD_STATUS="FAIL -- DIVERGENT : historiques incompatibles avec $COMPARE_TARGET"
    FAIL=1
fi

# --- 2. import patrick rÃƒÂ©sout sous CE worktree, pas un chemin rÃƒÂ©siduel ---
# ExÃƒÂ©cutÃƒÂ© depuis /tmp, jamais depuis REPO_ROOT ni un de ses sous-dossiers :
# un sous-dossier nommÃƒÂ© "patrick" dans le cwd est traitÃƒÂ© par Python comme un
# namespace package implicite et masque silencieusement l'installation
# ÃƒÂ©ditable rÃƒÂ©elle -- __file__ vaut alors None SANS lever d'erreur (source du
# faux-nÃƒÂ©gatif rencontrÃƒÂ© en session, cf. rapport). /tmp n'a par construction
# aucun sous-dossier "patrick" pour reproduire ce piÃƒÂ¨ge.
PYBIN=$(command -v python || command -v python3)
IMPORT_PATH="$(cd /tmp && "$PYBIN" -c "import patrick; print(patrick.__file__ or '')" 2>/dev/null)"
if [ -z "$IMPORT_PATH" ]; then
    IMPORT_STATUS="FAIL (import patrick ÃƒÂ©choue, ou __file__ vide/None)"
    FAIL=1
elif [[ "$IMPORT_PATH" == "$REPO_ROOT/patrick/patrick/"* ]]; then
    IMPORT_STATUS="OK ($IMPORT_PATH)"
else
    IMPORT_STATUS="FAIL -- rÃƒÂ©sout hors du worktree courant : $IMPORT_PATH"
    FAIL=1
fi

echo "ENV_SYNC: HEAD=$LOCAL_HEAD [$HEAD_STATUS] | import_patrick=$IMPORT_STATUS"

exit $FAIL


