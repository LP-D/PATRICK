"""Laboratoire de stratégies : n'importe quelle stratégie sur n'importe quels instruments, à n'importe quelles dates, avec de vrais frais, et
une réponse honnête à la question « est-ce que ça tient ? ».

- `indicators` : indicateurs techniques et calendaires, causaux, pour tous les instruments à la fois ;
- `rules`      : conditions « opérande opérateur opérande » regroupées en ET / OU ;
- `templates`  : modèles (tendance, retour à la moyenne, rotation, allocation, calendrier, événements, paire, régime) compilés en règles ;
- `backtest`   : moteur quotidien (éligibilité, sélection, risque, pondération, rééquilibrage, frais, exécution à la clôture ou à l'ouverture) ;
- `metrics`    : performance, drawdowns, opérations, comparaison à l'indice de référence ;
- `robustness` : hors échantillon, hasard (permutation de l'exposition), frais multipliés, bootstrap, Sharpe probabiliste et déflaté,
                 walk-forward de la grille de réglages, verdict ;
- `data`       : cours (fichier importé de n'importe quelle mise en page, puis Yahoo), paire synthétique, événements ;
- `events`     : listes d'événements (fichier, résultats trimestriels Yahoo, préréglages) ;
- `service`    : une étude complète ; `jobs` : exécution en tâche de fond et historique comparable.

Ce sont des explorations historiques avant impôt : rien ici n'est un conseil d'investissement.
"""
