# ADR 0006 — Règle de parcimonie « une erreur-type » activée par défaut

Date : 2026-10-20 · Statut : acceptée · Code : `pipeline/leaderboard.py::Leaderboard.best/top_k`, `pipeline/engine.py::_tuning_candidates/_best_tuned/_select_finals`, `config/schema.py` (`SelectionConfig.one_se_rule`, `RunConfig.from_stored_json`), `pipeline/engine.py::_config_hash` · Tests : `tests/test_one_se_rule.py`, `tests/test_stored_config_legacy.py`

## Contexte

Le gagnant du leaderboard était la configuration de plus haute moyenne de F1_dir sur les plis. Avec des centaines de candidats
(variables × échantillonneur × algorithme × régime) aux scores presque égaux, ce maximum est du bruit de sélection ; le départage
existant ne jouait que sur des égalités exactes. La règle classique : parmi les configurations dont la moyenne est à moins d'une
erreur-type (sur les plis) de la meilleure, prendre la plus simple (le moins de variables), puis la meilleure moyenne.

La règle était codée et testée depuis le 2026-10-19, désactivée par défaut parce qu'elle change le gagnant.

## Décision

`selection.one_se_rule` vaut `true` par défaut. La mettre à `false` rétablit l'ancien comportement. La règle ne s'applique qu'avec au
moins deux plis (sans plis multiples, pas d'erreur-type : le maximum simple reste).

Elle gouverne **toute la chaîne qui désigne le modèle final**, pas seulement le classement du scan :
1. le gagnant du scan avant réglage (`Leaderboard.best(one_se=True)`) ;
2. le candidat envoyé à Optuna : le choix de la règle en tête, les autres par moyenne (`Leaderboard.top_k(one_se=True)`) ;
3. le choix parmi les configurations réglées, avec l'erreur-type des plis du réglage (`_best_tuned`), globalement et par horizon ;
4. la stabilité des variables, mesurée sur ce gagnant.

Pourquoi pas seulement le point 1 : première version (activée par défaut avec le seul point 1), le golden de la CI a changé de façon
inexpliquée. Cause : Optuna réglait le maximum simple du scan, puis `_select_finals` comparait le candidat simple non réglé à ce
candidat réglé, qui gagne presque toujours. Dès que le réglage est actif (c'est le cas par défaut), la règle était neutralisée sans bruit
et le modèle final changeait de nature (réglé au lieu de non réglé) sans que la règle y soit pour rien.

## Conséquences

- Un run lancé maintenant peut retenir un autre gagnant, plus parcimonieux, qu'avant. Les runs déjà faits ne sont pas réécrits.
- Hachage de configuration : une config qui désactive la règle garde exactement le hachage d'avant le champ ; la config par défaut en a
  un nouveau (le champ y figure). Les noms d'études Optuna en dépendent.
- `patrick resume` relit la config enregistrée avec `RunConfig.from_stored_json` : un run enregistré avant le champ reste sous l'ancienne
  règle et retrouve ses études Optuna. Une relance depuis la page d'un run (`/runs/<id>/relaunch`) est un nouveau run : elle suit la
  règle d'aujourd'hui, comme pour les séries FRED.
- Golden masters : en local (autre environnement numérique) les deux restent identiques bit à bit, car le scan y choisit déjà le plus petit N.
  Dans l'environnement épinglé de la CI, le golden walk-forward a changé comme la règle le prévoit : à l'horizon 3, le modèle final passe de
  6 à 4 variables (l'horizon 5, 4 variables, ne bouge pas ; le classement du scan est identique). Régénéré par la CI (`golden-regen/`), seul
  `run_pipeline_walkforward.json` bouge ; le golden CPCV (sans réglage) est inchangé.
- La règle ne rend pas la sélection non biaisée : elle réduit la part de bruit dans le choix, pas le nombre d'essais (compteur d'essais,
  Sharpe déflaté et PBO restent la réponse à cela).
