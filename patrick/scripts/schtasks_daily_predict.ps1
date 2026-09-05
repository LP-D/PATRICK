<#
Phase 2 -- inférence programmée quotidienne : commande de planification
Windows pour `scripts/daily_predict.py`.

CE FICHIER NE S'EXÉCUTE PAS TOUT SEUL AU SENS "installe la tâche" -- il
DOCUMENTE la commande `schtasks /create ...` à lancer manuellement (une
fois) pour créer la tâche planifiée. Il n'a jamais été exécuté par l'agent
qui l'a rédigé (consigne explicite : "NE L'EXÉCUTE PAS toi-même").

Convention de planification : ce projet n'avait, avant cette phase, AUCUN
script ni convention existante pour le Planificateur de tâches Windows
(recherché sans résultat dans `patrick/scripts/` et dans un éventuel
`scripts/` à la racine du dépôt) -- ce fichier introduit la première.

Prérequis avant de lancer la commande ci-dessous :
- Adapter $RepoDir si le checkout de déploiement n'est pas
  C:\Users\leonp\PATRICK\patrick.
- Le service/serveur (patrick serve / patrick worker) tourne dans ce même
  répertoire -- c'est de là que proviennent les `runs\...\*.joblib`
  référencés (chemins RELATIFS) par `trial.artifact_path` en base ; c'est
  pourquoi `daily_predict.py` reçoit --base-dir explicitement plutôt que de
  compter sur le "Start in" du Planificateur de tâches (qui, pour une tâche
  SYSTEM ou lancée hors session interactive, ne vaut pas toujours ce qu'on
  attend).
- L'heure choisie (22:05) est APRÈS la clôture des marchés US (22:00 heure
  de Paris en heure d'hiver US / heure d'été europ. -- ajuster si besoin ;
  voir le commentaire déjà présent dans patrick/patrick/cli.py::predict_cmd
  pour le même choix sur `patrick predict --live` en cron Linux).
#>

$RepoDir    = "C:\Users\leonp\PATRICK\patrick"
$PythonExe  = "$RepoDir\.venv\Scripts\python.exe"
$ScriptPath = "$RepoDir\scripts\daily_predict.py"
$LogFile    = "$RepoDir\runs\daily_predict.log"

Write-Output "Commande schtasks (a executer manuellement, PAS par ce script) -- copier-coller"
Write-Output "telle quelle dans une invite cmd.exe ou PowerShell (les guillemets internes sont"
Write-Output "deja echappes pour /tr, qui attend UNE seule chaine cmd.exe) :"
Write-Output @"

schtasks /create /tn "Patrick-DailyPredict" /tr "\`"C:\Users\leonp\PATRICK\patrick\.venv\Scripts\python.exe\`" \`"C:\Users\leonp\PATRICK\patrick\scripts\daily_predict.py\`" --base-dir \`"C:\Users\leonp\PATRICK\patrick\`" --log-file \`"C:\Users\leonp\PATRICK\patrick\runs\daily_predict.log\`"" /sc daily /st 22:05 /ru "%USERNAME%" /rl LIMITED /f

"@

Write-Output "Verification apres creation :"
Write-Output "  schtasks /query /tn `"Patrick-DailyPredict`" /v /fo LIST"
Write-Output ""
Write-Output "Test manuel immediat (sans attendre 22:05) :"
Write-Output "  schtasks /run /tn `"Patrick-DailyPredict`""
Write-Output ""
Write-Output "Suppression :"
Write-Output "  schtasks /delete /tn `"Patrick-DailyPredict`" /f"
Write-Output ""
Write-Output "Notes :"
Write-Output "  /sc daily /st 22:05      -> tous les jours a 22:05 (adapter l'heure : marche US fermee)."
Write-Output "  /ru `"%USERNAME%`"         -> tourne sous l'utilisateur courant (necessite session ouverte"
Write-Output "                             OU /rp <mot de passe> pour tourner hors session -- NON inclus"
Write-Output "                             ici volontairement, a fournir interactivement par l'utilisateur,"
Write-Output "                             jamais en clair dans un script versionne)."
Write-Output "  /rl LIMITED              -> privileges standard (pas besoin d'admin pour ce script)."
Write-Output "  /f                       -> ecrase une tache existante du meme nom sans prompt de confirmation."
Write-Output "  --base-dir               -> critique : force la resolution des artifact_path relatifs (voir"
Write-Output "                             daily_predict.py, docstring de find_predictable_candidates) contre"
Write-Output "                             le checkout de deploiement reel, independamment du 'Start in' que"
Write-Output "                             le Planificateur de taches choisit pour la tache."
Write-Output "  --log-file               -> le Planificateur de taches ne capture pas la sortie standard par"
Write-Output "                             defaut ; ce fichier est la seule trace fiable en cas d'echec."
