<#
Passage de nuit de PATRICK : tout ce qui doit tourner chaque jour, puis (si rien d'autre ne tourne) mise en veille prolongee.

Lance par la tache Windows "Patrick-Nightly" (`schtasks_nightly.ps1 -Install`), qui reveille le PC a l'heure choisie.
Chaque etape est independante : une etape en echec est journalisee et n'empeche pas les suivantes.

Etapes, dans l'ordre :
  1. reseau       : attend la connexion (au reveil, le Wi-Fi met parfois une minute).
  2. mise a jour  : `python -m patrick.desktop update` (avance rapide sur la branche `stable`, sautee si un entrainement tourne).
  3. actualites   : `patrick news refresh` (une minute ou deux) ; AVANT les predictions, qui durent des heures (la tache etait coupee a 6 h,
                    sans limite depuis le 27/10) : placee apres, cette etape n'avait jamais tourne (journal du 26-27/10).
  4. predictions  : `scripts/daily_predict.py` = prediction du jour de chaque modele + jugement des anciennes + cycle du pilote
                    automatique des fonds (positions, ordres) + derive.
  5. sauvegarde   : `scripts/backup_db.py` (copie de la base).
  6. synchro      : `patrick sync auto` (fusionne et publie vers le dossier OneDrive).
  7. extinction   : voir ci-dessous.

Extinction (`-End`) : `hibernate` (defaut : le PC se rallumera tout seul a la prochaine echeance), `sleep`, `shutdown`
(attention : un PC eteint ne peut PAS etre reveille par une tache Windows) ou `none`. Elle n'a lieu QUE si :
  - PATRICK n'est pas ouvert et aucun entrainement ne tourne (processus `patrick.cli serve|worker`, `patrick.desktop launch`) ;
  - personne n'utilise le PC : aucune frappe ni mouvement de souris depuis `-IdleMinutes` minutes (10 par defaut).
Sinon le PC reste allume et le journal le dit.

Journal : `runs\nightly.log` (dossier du depot). Test sans rien lancer : `.\nightly_run.ps1 -DryRun`.
#>
param(
    [ValidateSet("hibernate", "sleep", "shutdown", "none")][string]$End = "hibernate",
    [int]$IdleMinutes = 10,
    [int]$NetworkWaitMinutes = 5,
    [switch]$DryRun
)

$ErrorActionPreference = "Continue"
$RepoDir    = Split-Path -Parent $PSScriptRoot
$LogFile    = Join-Path $RepoDir "runs\nightly.log"
$VenvPython = Join-Path $RepoDir ".venv\Scripts\python.exe"
$Python     = if (Test-Path $VenvPython) { $VenvPython } else { (Get-Command python -ErrorAction Stop).Source }
Set-Location $RepoDir
$LogDir = Split-Path -Parent $LogFile
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

function Log([string]$message) {
    $line = "{0:yyyy-MM-dd HH:mm:ss} {1}" -f (Get-Date), $message
    Write-Output $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Step([string]$name, [string[]]$arguments) {
    Log "== $name : python $($arguments -join ' ')"
    if ($DryRun) { return }
    $started = Get-Date
    try {
        & $Python @arguments *>> $LogFile
        Log ("   termine (code {0}) en {1:N0} s" -f $LASTEXITCODE, ((Get-Date) - $started).TotalSeconds)
    } catch {
        Log "   ECHEC : $($_.Exception.Message)"
    }
}

function Wait-Network {
    Log "== reseau : attente de la connexion (au plus $NetworkWaitMinutes min)"
    if ($DryRun) { return }
    $deadline = (Get-Date).AddMinutes($NetworkWaitMinutes)
    while ((Get-Date) -lt $deadline) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $async = $client.BeginConnect("query1.finance.yahoo.com", 443, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(4000) -and $client.Connected) { $client.Close(); Log "   reseau disponible"; return }
            $client.Close()
        } catch { }
        Start-Sleep -Seconds 10
    }
    Log "   pas de reseau : les etapes qui en ont besoin echoueront et seront reessayees au prochain passage"
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PatrickIdle {
    [StructLayout(LayoutKind.Sequential)] struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
    [DllImport("user32.dll")] static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
    public static double IdleMinutes() {
        LASTINPUTINFO info = new LASTINPUTINFO(); info.cbSize = (uint)Marshal.SizeOf(info);
        if (!GetLastInputInfo(ref info)) return 0;
        return ((uint)Environment.TickCount - info.dwTime) / 60000.0;
    }
}
"@

function Patrick-Busy {
    # PATRICK ouvert (serveur, fenetre) ou entrainement en cours : on n'eteint rien.
    $busy = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match 'patrick\.cli (serve|worker)' -or $_.CommandLine -match 'patrick\.desktop launch' }
    return [bool]$busy
}

Log "===== passage de nuit (fin : $End, inactivite requise : $IdleMinutes min)$(if ($DryRun) { ' [SIMULATION]' })"
Wait-Network
Step "mise a jour"  @("-m", "patrick.desktop", "update")
# Les nouvelles d'abord : courtes, alors que les predictions durent des heures.
Step "actualites"   @("-m", "patrick.cli", "news", "refresh")
Step "predictions et pilote automatique" @((Join-Path $RepoDir "scripts\daily_predict.py"), "--base-dir", $RepoDir, "--log-file", (Join-Path $RepoDir "runs\daily_predict.log"))
Step "sauvegarde"   @((Join-Path $RepoDir "scripts\backup_db.py"))
Step "synchronisation" @("-m", "patrick.cli", "sync", "auto")

if ($End -eq "none") { Log "== fin : aucune extinction demandee"; return }
if (Patrick-Busy) { Log "== fin : PATRICK est ouvert ou un entrainement tourne : le PC reste allume"; return }
$idle = [PatrickIdle]::IdleMinutes()
if ($idle -lt $IdleMinutes) { Log ("== fin : quelqu'un utilise le PC (inactif depuis {0:N1} min, il en faut {1}) : le PC reste allume" -f $idle, $IdleMinutes); return }
Log "== fin : mise en $End du PC"
if ($DryRun) { return }
switch ($End) {
    "hibernate" { & shutdown.exe /h }
    "sleep"     { & rundll32.exe powrprof.dll,SetSuspendState 0,1,0 }
    "shutdown"  { & shutdown.exe /s /t 120 /c "PATRICK : passage de nuit termine (annulation : shutdown /a)" }
}
