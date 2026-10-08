"""Application de bureau PATRICK : lanceur (mise à jour, assistant de premier démarrage, synchronisation entre
PC, serveur, fenêtre), préférences, dossier partagé. Point d'entrée : `python -m patrick.desktop`.

Ce paquet n'importe que la bibliothèque standard (et `psutil`, déjà une dépendance) au chargement : le lanceur
doit afficher son écran de démarrage tout de suite, avant que pandas ne soit chargé.
"""
