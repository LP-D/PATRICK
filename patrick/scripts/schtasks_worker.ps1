<#
Worker planifie (AM8 du 25/11) : tache Windows "Patrick-Worker" qui relance `patrick worker` s'il est mort alors que des jobs attendent.

Jusqu'ici un entrainement lance depuis l'assistant (ou une fenetre fermee) emportait le worker avec lui : il fallait le relancer a la main
dans PowerShell. La tache passe toutes les -EveryMinutes minutes (15 par defaut) et lance `patrick worker --if-no-worker` :
  - un worker vivant tient deja la file (battement recent) : la commande ne fait rien ;
  - aucun job en file : elle ne fait rien ;
  - sinon elle lance le worker, qui s'arrete seul apres 10 minutes sans job.
Deux entrainements ne tournent donc jamais en meme temps a cause de la tache.

Utilisation (PowerShell, depuis n'importe ou) :
    .\schtasks_worker.ps1                       # n'installe RIEN : affiche la tache qui serait creee
    .\schtasks_worker.ps1 -Install              # cree (ou remplace) la tache pour l'utilisateur courant
    .\schtasks_worker.ps1 -Remove               # supprime la tache
    .\schtasks_worker.ps1 -Install -EveryMinutes 30

Choix : session ouverte de l'utilisateur courant, sans mot de passe stocke ; journal dans `runs\worker_task.log` ; pas de limite de duree
(un entrainement dure des heures) ; `MultipleInstances IgnoreNew` (un passage en cours n'est jamais double).
#>
param(
    [switch]$Install,
    [switch]$Remove,
    [int]$EveryMinutes = 15
)

$ErrorActionPreference = "Stop"
$TaskName   = "Patrick-Worker"
$RepoDir    = Split-Path -Parent $PSScriptRoot
$LogFile    = Join-Path $RepoDir "runs\worker_task.log"
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

if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $PythonExe = (Get-Command python -ErrorAction Stop).Source
}

function Quote([string]$s) { "'" + ($s -replace "'", "''") + "'" }
$Command   = "& $(Quote $PythonExe) -m patrick.cli worker --if-no-worker *>> $(Quote $LogFile)"
$Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$Command`""

Write-Output "Tache      : $TaskName (toutes les $EveryMinutes min)"
Write-Output "Commande   : powershell.exe $Arguments"
Write-Output "Dossier    : $RepoDir"
Write-Output "Journal    : $LogFile"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Write-Output ("Etat actuel: " + $(if ($existing) { "deja installee ($($existing.State))" } else { "non installee" }))

if (-not $Install) {
    Write-Output ""
    Write-Output "Rien n'a ete installe. Pour creer la tache : .\schtasks_worker.ps1 -Install"
    return
}

$LogDir = Split-Path -Parent $LogFile
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $RepoDir
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "PATRICK : relance le worker d'entrainement s'il est mort alors que des jobs attendent." | Out-Null
Write-Output ""
Write-Output "Tache $TaskName installee (toutes les $EveryMinutes min). Test immediat : Start-ScheduledTask -TaskName $TaskName"
