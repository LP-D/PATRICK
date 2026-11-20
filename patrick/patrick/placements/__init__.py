"""Placements : simulation complète et automatique à partir de valeurs liquidatives (VL) importées (fonds de PEE, FCPE, OPCVM, ETF…).

Port, généralisé à n'importe quel jeu de fonds, de l'analyse quantitative du notebook `PEE/analyse_pee_5ans.ipynb` :

1. `loader`    : lecture et contrôle d'intégrité des VL (CSV `date,nav` et exports Excel de VL) ;
2. `store`     : jeux de données importés, rangés sous `<racine de données>/placements/<id>/` ;
3. `stats`     : rendement, volatilité, Sharpe, drawdown par fenêtre ;
4. `optimize`  : portefeuilles max rendement / max Sharpe / min volatilité / max Sortino (plafond par fonds), validation walk-forward
                 face au 1/N ;
5. `scenarios` : scénarios à N ans (fenêtres historiques glissantes, bootstrap par blocs, bootstrap stationnaire, GARCH, Monte Carlo
                 à rendement incertain), en version « historique » et « prudente » (rendement espéré rétréci) ;
6. `service`   : orchestration de l'analyse, résultat JSON ; `jobs` : exécution en tâche de fond avec avancement.

Tout est historique et descriptif : ce n'est pas un conseil en investissement ; les performances passées ne préjugent pas des performances futures.
"""
