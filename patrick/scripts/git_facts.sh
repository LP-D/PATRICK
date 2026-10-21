#!/bin/sh
# État git en faits bruts, une ligne `clé=valeur` par fait (audit externe du 2026-10-19, point 11) :
# de quoi vérifier le compte rendu d'un agent contre l'état réel du dépôt. Rien n'est déduit ni interprété.
# À lancer depuis le dépôt : sh patrick/scripts/git_facts.sh
GIT_TERMINAL_PROMPT=0
export GIT_TERMINAL_PROMPT

count() { wc -l | tr -d ' '; }

branch=$(git symbolic-ref --short -q HEAD || echo DETACHED)
echo "repo=$(git rev-parse --show-toplevel)"
echo "branch=$branch"
echo "head=$(git rev-parse HEAD)"

upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)
if [ -n "$upstream" ]; then
    echo "upstream=$upstream"
    set -- $(git rev-list --left-right --count 'HEAD...@{u}')
    echo "ahead=$1"
    echo "behind=$2"
    remote=${upstream%%/*}
else
    echo "upstream=none"
    echo "ahead=unknown"
    echo "behind=unknown"
    remote=origin
fi

# Le sommet de la branche TEL QUE LE DISTANT LE DIT (pas la copie locale origin/...).
remote_head=unreachable
if [ "$branch" != DETACHED ]; then
    if command -v timeout >/dev/null 2>&1; then
        out=$(timeout 20 git ls-remote --exit-code "$remote" "refs/heads/$branch" 2>/dev/null); rc=$?
    else
        out=$(git ls-remote --exit-code "$remote" "refs/heads/$branch" 2>/dev/null); rc=$?
    fi
    if [ $rc -eq 0 ] && [ -n "$out" ]; then
        remote_head=$(echo "$out" | cut -f1)
    elif [ $rc -eq 2 ]; then
        remote_head=absent
    fi
fi
echo "remote_head=$remote_head"

echo "dirty_tracked=$(git status --porcelain --untracked-files=no | count)"
echo "untracked=$(git ls-files --others --exclude-standard | count)"
echo "stash=$(git stash list | count)"
echo "last_commit=$(git log -1 --format='%h %cs %s')"
