# ADR 0006 — Règle de parcimonie « une erreur-type » activée par défaut

Date : 2026-10-20 · Statut : acceptée · Code : `pipeline/leaderboard.py::Leaderboard.best`, `config/schema.py` (`SelectionConfig.one_se_rule`, `RunConfig.from_stored_json`), `pipeline/engine.py::_config_hash` · Tests : `tests/test_one_se_rule.py`, `tests/test_stored_config_legacy.py`

## Contexte

Le gagnant du leaderboard était la configuration de plus haute moyenne de F1_dir sur les plis. Avec des centaines de candidats
(variables × échantillonneur × algorithme × régime) aux scores presque égaux, ce maximum est du bruit de sélection ; le départage
existant ne jouait que sur des égalités exactes. La règle classique : parmi les configurations dont la moyenne est à moins d'une
erreur-type (sur les plis) de la meilleure, prendre la plus simple (le moins de variables), puis la meilleure moyenne.

La règle était codée et testée depuis le 2026-10-19, désactivée par défaut parce qu'elle change le gagnant.

## Décision

`selection.one_se_rule` vaut `true` par défaut. La mettre à `false` rétablit l'ancien comportement. La règle ne s'applique qu'avec au
moins deux plis (sans plis multiples, pas d'erreur-type : le maximum simple reste).

## Conséquences

- Un run lancé maintenant peut retenir un autre gagnant, plus parcimonieux, qu'avant. Les runs déjà faits ne sont pas réécrits.
- Hachage de configuration : une config qui désactive la règle garde exactement le hachage d'avant le champ ; la config par défaut en a
  un nouveau (le champ y figure). Les noms d'études Optuna en dépendent.
- `patrick resume` relit la config enregistrée avec `RunConfig.from_stored_json` : un run enregistré avant le champ reste sous l'ancienne
  règle et retrouve ses études Optuna. Une relance depuis la page d'un run (`/runs/<id>/relaunch`) est un nouveau run : elle suit la
  règle d'aujourd'hui, comme pour les séries FRED.
- Les deux golden masters (walk-forward, CPCV) sont restés identiques bit à bit avec le nouveau défaut (comparaison locale, golden
  produit sur le code d'avant) : la règle n'y change pas le gagnant. Ils ne la mettent donc pas à l'épreuve dans un run complet ;
  ce sont les tests unitaires de `Leaderboard.best` et de `_select_finals` qui le font.
- La règle ne rend pas la sélection non biaisée : elle réduit la part de bruit dans le choix, pas le nombre d'essais (compteur d'essais,
  Sharpe déflaté et PBO restent la réponse à cela).
