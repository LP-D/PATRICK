<#
Phase 6 -- sauvegarde periodique de la base SQLite de suivi : commande de
planification Windows pour `scripts/backup_db.py`.

CE FICHIER NE S'EXECUTE PAS TOUT SEUL AU SENS "installe la tache" -- il
DOCUMENTE la commande `schtasks /create ...` a lancer manuellement (une
fois) pour creer la tache planifiee. Il n'a jamais ete execute par l'agent
qui l'a redige (meme consigne explicite que pour
`schtasks_daily_predict.ps1`, branche feature/scheduled-inference : "NE
L'EXECUTE PAS toi-meme").

Prerequis avant de lancer la commande ci-dessous :
- Adapter $RepoDir si le checkout de deploiement n'est pas
  C:\Users\leonp\PATRICK\patrick.
- La base source est lue via $PATRICK_DB_PATH ou, a defaut,
  ~/.patrick/patrick.db (voir `tracking/db.py::default_db_path`) -- pas
  besoin de --source explicite si la tache tourne sous le meme utilisateur
  que le serveur/worker.
- Destination par defaut : ~/.patrick/backups/ (cree si absent),
  volontairement HORS du depot git.
- L'heure choisie (23:30) est apres la fenetre habituelle d'inference
  quotidienne (`Patrick-DailyPredict`, 22:05, cf. schtasks_daily_predict.ps1)
  pour sauvegarder une base qui inclut deja les predictions live du jour.
#>

$RepoDir    = "C:\Users\leonp\PATRICK\patrick"
$PythonExe  = "$RepoDir\.venv\Scripts\python.exe"
$ScriptPath = "$RepoDir\scripts\backup_db.py"
$LogFile    = "$env:USERPROFILE\.patrick\backups\backup.log"

Write-Output "Commande schtasks (a executer manuellement, PAS par ce script) -- copier-coller"
Write-Output "telle quelle dans une invite cmd.exe ou PowerShell (les guillemets internes sont"
Write-Output "deja echappes pour /tr, qui attend UNE seule chaine cmd.exe) :"
Write-Output @"

schtasks /create /tn "Patrick-DailyDBBackup" /tr "\`"C:\Users\leonp\PATRICK\patrick\.venv\Scripts\python.exe\`" \`"C:\Users\leonp\PATRICK\patrick\scripts\backup_db.py\`" --log-file \`"%USERPROFILE%\.patrick\backups\backup.log\`"" /sc daily /st 23:30 /ru "%USERNAME%" /rl LIMITED /f

"@

Write-Output "Verification apres creation :"
Write-Output "  schtasks /query /tn `"Patrick-DailyDBBackup`" /v /fo LIST"
Write-Output ""
Write-Output "Test manuel immediat (sans attendre 23:30) :"
Write-Output "  schtasks /run /tn `"Patrick-DailyDBBackup`""
Write-Output ""
Write-Output "Suppression :"
Write-Output "  schtasks /delete /tn `"Patrick-DailyDBBackup`" /f"
Write-Output ""
Write-Output "Notes :"
Write-Output "  /sc daily /st 23:30      -> tous les jours a 23:30 (apres l'inference quotidienne 22:05)."
Write-Output "  /ru `"%USERNAME%`"         -> tourne sous l'utilisateur courant (necessite session ouverte"
Write-Output "                             OU /rp <mot de passe> pour tourner hors session -- NON inclus"
Write-Output "                             ici volontairement, a fournir interactivement par l'utilisateur,"
Write-Output "                             jamais en clair dans un script versionne)."
Write-Output "  /rl LIMITED              -> privileges standard (pas besoin d'admin pour ce script)."
Write-Output "  /f                       -> ecrase une tache existante du meme nom sans prompt de confirmation."
Write-Output "  --log-file               -> le Planificateur de taches ne capture pas la sortie standard par"
Write-Output "                             defaut ; ce fichier est la seule trace fiable en cas d'echec."
Write-Output "  Retention                -> ce script ne purge PAS les anciennes sauvegardes (hors scope de"
Write-Output "                             cette phase) -- surveiller manuellement l'espace disque de"
Write-Output "                             ~/.patrick/backups/ ou ajouter une purge separee si besoin."
