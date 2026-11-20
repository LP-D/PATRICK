"""Laboratoire de stratégies : explorer une règle « acheter avant / vendre après un événement » (résultats, introduction en Bourse, annonce,
keynote…) et dire honnêtement si elle tient.

Inspiré des études du dossier STRAT : l'IPO (achat au prix d'offre ou à l'ouverture, vente à J+k, k = 1 à 20, jour de sortie optimal avec
intervalles bootstrap et stabilité), les straddles autour des résultats (primes reconstruites par Black-Scholes, scénarios de baisse de volatilité,
validation chronologique), les keynotes Apple (« buy the rumor, sell the news »).

- `events`   : listes d'événements (CSV importé, résultats trimestriels Yahoo, préréglages) ;
- `prices`   : cours quotidiens (CSV importé d'abord, Yahoo en repli) ;
- `core`     : rendement de chaque événement pour chaque jour de sortie, courbe moyenne / médiane / taux de gain, bootstrap, validation sur les
               événements les plus récents, courbe de capital, concentration, Monte Carlo d'une campagne de transactions ;
- `straddle` : straddle long autour d'un événement (Black-Scholes, volatilité d'entrée = multiple de la volatilité réalisée) ;
- `service`  : orchestration, résultat JSON ; `jobs` : exécution en tâche de fond.

Le meilleur jour de sortie est choisi sur l'échantillon : c'est un maximum parmi k = 1 à 20 essais, donc optimiste par construction. Le verdict ne
s'appuie jamais sur lui seul : il exige que le jour choisi sur les événements anciens tienne sur les événements récents (hors échantillon).
Aucun frais, aucune liquidité ni aucun prix d'option réel n'est garanti : c'est une exploration historique, pas un conseil.
"""
