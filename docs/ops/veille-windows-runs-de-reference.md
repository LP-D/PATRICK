# Veille Windows et runs de référence (PC A)

Date : 2026-09-26. Contexte : après les corrections du bloc 1 (F01–F08, calibration), les runs de référence —
dont ^GSPC — doivent être relancés. Un run complet dure plusieurs heures ; une mise en veille au milieu
suspend le processus Python, les connexions Yahoo/FRED expirent au réveil et le job du worker finit
récupéré comme « abandonné » (`reap_stale_running_jobs`).

## Ce que le code fait désormais

`patrick/keep_awake.py` : chaque run (`patrick run`, `patrick resume`, chaque job du worker lancé depuis
l'interface) s'exécute dans `keep_awake()`, qui appelle `SetThreadExecutionState(ES_CONTINUOUS |
ES_SYSTEM_REQUIRED)` — Windows ne se met pas en veille tant que le run tourne ; l'écran peut s'éteindre.
La demande est levée à la fin du run, y compris en cas d'échec. Sans effet sous Linux/macOS.

Ce que cela **n'empêche pas** : fermeture du capot d'un portable (action « capot » du plan d'alimentation),
Veille/Arrêt demandés explicitement, redémarrage Windows Update, coupure batterie critique.

## À vérifier sur le PC A avant de relancer

PowerShell (pas besoin d'être administrateur pour les requêtes) :

1. `powercfg /a` — états de veille disponibles. « Veille (S0 faible consommation inactive) » = Modern
   Standby : le réseau peut être coupé en veille connectée ; la protection ci-dessus reste valable.
2. Pendant un run : `powercfg /requests` — `python.exe` doit apparaître sous **SYSTEM**. S'il n'y est
   pas, la protection n'est pas active (processus lancé autrement que par `patrick run`/le worker).
3. `powercfg /q SCHEME_CURRENT SUB_BUTTONS LIDACTION` — action à la fermeture du capot (secteur/batterie).
   Pour un run de nuit capot fermé : « Ne rien faire » sur secteur, ou laisser le capot ouvert.
4. Paramètres → Windows Update → Heures d'activité : couvrir la plage du run, ou suspendre les mises à
   jour une semaine le temps des runs de référence.
5. Brancher sur secteur : sur batterie, le seuil critique déclenche une hibernation que rien n'empêche.

## Si le run a été interrompu malgré tout

`patrick resume --run-id <id>` : rejoue le scan (pas de reprise à ce niveau) mais reprend les essais Optuna
déjà terminés depuis `optuna.db`. Les snapshots de données sont en cache, pas de re-téléchargement complet.
