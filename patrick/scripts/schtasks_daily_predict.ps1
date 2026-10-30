<#
Inference live quotidienne planifiee : tache Windows "Patrick-DailyPredict" pour `scripts/daily_predict.py`.

Chaque jour, chaque modele deja entraine fait sa nouvelle prediction ET juge celles dont l'horizon est
ecoule (`patrick.predict.predict_live`) -- meme app fermee. Sans cette tache, l'evaluation ne tourne que
quand l'app est ouverte (`patrick.live_refresh`) ; un jour manque est reconstitue au lancement suivant.

Utilisation (PowerShell, depuis n'importe ou) :
    .\schtasks_daily_predict.ps1            # n'installe RIEN : affiche la tache qui serait creee
    .\schtasks_daily_predict.ps1 -Install   # cree (ou remplace) la tache pour l'utilisateur courant
    .\schtasks_daily_predict.ps1 -Remove    # supprime la tache
    .\schtasks_daily_predict.ps1 -Install -At 21:30   # autre heure (heure locale)

Choix :
- Chemins deduits de l'emplacement de ce script (checkout de deploiement = le dossier qui contient `scripts\`),
  python = `.venv\Scripts\python.exe` s'il existe, sinon le `python` du PATH. `--base-dir` est critique : les
  `trial.artifact_path` relatifs sont resolus contre ce dossier, pas contre le "Start in" du Planificateur.
- 22:05 heure locale : apres la cloture des marches US (22:00 a Paris). La base est sauvegardee plus tard
  (`schtasks_daily_dbbackup.ps1`, 23:30), elle contient donc deja les predictions du jour.
- `StartWhenAvailable` : si le PC etait eteint a l'heure prevue, la tache part des qu'il redemarre.
- Tourne sous l'utilisateur courant, session ouverte, sans mot de passe stocke. Fenetre masquee, journal dans
  `runs\daily_predict.log` (le Planificateur ne capture pas la sortie standard).
- Idempotent : une barre deja enregistree n'est jamais reecrite, lancer la tache en plus de l'app ne double rien.
#>
param(
    [switch]$Install,
    [switch]$Remove,
    [string]$At = "22:05"
)

$ErrorActionPreference = "Stop"
$TaskName   = "Patrick-DailyPredict"
$RepoDir    = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $RepoDir "scripts\daily_predict.py"
$LogFile    = Join-Path $RepoDir "runs\daily_predict.log"
$VenvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Tache $TaskName supprimee."
    } else {
        Write-Output "Tache $TaskName absente : rien a supprimer."
    }
    return
}

if (-not (Test-Path $ScriptPath)) { throw "daily_predict.py introuvable : $ScriptPath" }
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}

# `powershell -WindowStyle Hidden` : pas de console qui reste ouverte pendant la duree du calcul.
function Quote([string]$s) { "'" + ($s -replace "'", "''") + "'" }
$Command   = "& $(Quote $PythonExe) $(Quote $ScriptPath) --base-dir $(Quote $RepoDir) --log-file $(Quote $LogFile)"
$Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$Command`""

Write-Output "Tache      : $TaskName (tous les jours a $At, heure locale)"
Write-Output "Commande   : powershell.exe $Arguments"
Write-Output "Dossier    : $RepoDir"
Write-Output "Journal    : $LogFile"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Write-Output ("Etat actuel: " + $(if ($existing) { "deja installee ($($existing.State))" } else { "non installee" }))

if (-not $Install) {
    Write-Output ""
    Write-Output "Rien n'a ete installe. Pour creer la tache : .\schtasks_daily_predict.ps1 -Install"
    Write-Output "Test immediat apres installation       : Start-ScheduledTask -TaskName $TaskName"
    Write-Output "Verification                           : Get-ScheduledTaskInfo -TaskName $TaskName"
    return
}

$LogDir = Split-Path -Parent $LogFile
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $RepoDir
$trigger  = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "PATRICK : prediction live quotidienne de chaque modele + jugement des signaux arrives a echeance." | Out-Null
Write-Output ""
Write-Output "Tache $TaskName installee. Premier passage : $At (heure locale). Test immediat : Start-ScheduledTask -TaskName $TaskName"
