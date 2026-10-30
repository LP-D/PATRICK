<#
Collecte des nouvelles planifiee : tache Windows "Patrick-NewsRefresh" pour `patrick news refresh`.

Les flux RSS ne gardent que quelques dizaines d'articles : pour constituer un historique point-in-time utilisable (la variable
textuelle n'entre dans aucun entrainement tant que cet historique est trop court), la collecte doit tourner regulierement, meme
app fermee. Chaque passage ajoute les nouvelles, les note (lexique, ton des banques centrales, nouveaute, evenements) et les
rattache aux actifs. Aucun cache de series ni data lake n'est touche : seule la base de suivi recoit des lignes `news_*`.

Utilisation (PowerShell, depuis n'importe ou) :
    .\schtasks_news.ps1                    # n'installe RIEN : affiche la tache qui serait creee
    .\schtasks_news.ps1 -Install           # cree (ou remplace) la tache pour l'utilisateur courant
    .\schtasks_news.ps1 -Remove            # supprime la tache
    .\schtasks_news.ps1 -Install -EveryHours 2   # autre cadence (defaut : 4 h)

Choix :
- Chemins deduits de l'emplacement de ce script ; python = `.venv\Scripts\python.exe` s'il existe, sinon le `python` du PATH.
- `StartWhenAvailable` : un passage manque (PC eteint) est rattrape au redemarrage ; une nouvelle rattrapee n'est jamais visible
  dans le passe (`known_at` = heure de premiere observation).
- Tourne sous l'utilisateur courant, session ouverte, sans mot de passe stocke ; journal dans `runs\news_refresh.log`.
- Ne pas lancer pendant une maintenance de la base : la collecte n'ecrit que quelques lignes, mais elle prend le verrou d'ecriture.
#>
param(
    [switch]$Install,
    [switch]$Remove,
    [int]$EveryHours = 4
)

$ErrorActionPreference = "Stop"
$TaskName   = "Patrick-NewsRefresh"
$RepoDir    = Split-Path -Parent $PSScriptRoot
$LogFile    = Join-Path $RepoDir "runs\news_refresh.log"
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
$Command   = "& $(Quote $PythonExe) -m patrick.cli news refresh *>> $(Quote $LogFile)"
$Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -Command `"$Command`""

Write-Output "Tache      : $TaskName (toutes les $EveryHours h)"
Write-Output "Commande   : powershell.exe $Arguments"
Write-Output "Dossier    : $RepoDir"
Write-Output "Journal    : $LogFile"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Write-Output ("Etat actuel: " + $(if ($existing) { "deja installee ($($existing.State))" } else { "non installee" }))

if (-not $Install) {
    Write-Output ""
    Write-Output "Rien n'a ete installe. Pour creer la tache : .\schtasks_news.ps1 -Install"
    Write-Output "Test immediat apres installation       : Start-ScheduledTask -TaskName $TaskName"
    return
}

$LogDir = Split-Path -Parent $LogFile
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $RepoDir
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Hours $EveryHours)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "PATRICK : collecte des nouvelles (flux RSS), notes et rattachement aux actifs." | Out-Null
Write-Output ""
Write-Output "Tache $TaskName installee (toutes les $EveryHours h). Test immediat : Start-ScheduledTask -TaskName $TaskName"
