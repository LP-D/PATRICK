"""Lecture souple de tableaux de valeurs (Excel, CSV, ODS, pages HTML enregistrées en .xls) : un module commun aux pages Placements et Stratégies.

- `reader.read_tables(nom, octets)` : chaque feuille (ou le CSV) en grille brute de cellules, sans rien supposer de la mise en page ;
- `parse` : nombres (« 1 234,56 € », « (3,2 %) », « 1'234.5 ») et dates (série Excel, « 31/12/2024 », « déc. 2024 », « T4 2024 », « 2024 ») ;
- `detect.detect(nom, octets)` : trouve dans ces grilles les séries datées (tableau large, blocs côte à côte, format long, tableau transposé,
  titre au-dessus du tableau), devine ce que sont les valeurs (cours/VL, base 100, performances périodiques ou cumulées, taux annuels) et la
  fréquence, puis les convertit en niveaux comparables (`levels`). Chaque série dit ce qui a été deviné (`notes`) et avec quelle confiance.
"""
