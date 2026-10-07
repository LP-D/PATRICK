<#
  PATRICK en mode application : une fenetre Chrome (ou Edge) sans barre d'onglets, avec le serveur local
  demarre a l'ouverture et arrete a la fermeture.

  Demarrage : fusion de ce que l'autre PC a publie (si `patrick sync setup` a ete fait sur ce PC), puis
              `patrick serve`, puis la fenetre.
  Fermeture : arret du serveur, puis publication de ce PC en arriere-plan. Un entrainement en cours n'est
              pas interrompu (le worker est independant du serveur) et la publication attend sa fin.

  Raccourcis : install-app.ps1. Journaux : ~\.patrick\logs\ (sync.log, app-serve.out.log, app-serve.err.log).
  Options : -Port (defaut 8000), -NoSync (ni fusion ni publication), -NoBrowser (demarre puis arrete, pour test).
  Fichier volontairement en ASCII : Windows PowerShell 5.1 lit mal l'UTF-8 sans BOM.
#>
param(
    [int]$Port = 8000,
    [switch]$NoSync,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # dossier `patrick` (contient pyproject.toml)
$LogDir = Join-Path $env:USERPROFILE '.patrick\logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$SyncLog = Join-Path $LogDir 'sync.log'
$Url = "http://127.0.0.1:$Port/"

# --- fenetre d'attente ---------------------------------------------------------------------------------
$script:Splash = $null
$script:SplashLabel = $null

function Update-Splash { [System.Windows.Forms.Application]::DoEvents() }

function Show-Splash([string]$Text) {
    if (-not $script:Splash) {
        $form = New-Object System.Windows.Forms.Form
        $form.Text = 'PATRICK'
        $form.FormBorderStyle = 'FixedDialog'
        $form.ControlBox = $false
        $form.StartPosition = 'CenterScreen'
        $form.TopMost = $true
        $form.ClientSize = New-Object System.Drawing.Size(380, 96)
        $label = New-Object System.Windows.Forms.Label
        $label.Location = New-Object System.Drawing.Point(16, 14)
        $label.Size = New-Object System.Drawing.Size(348, 28)
        $label.Font = New-Object System.Drawing.Font('Segoe UI', 11)
        $bar = New-Object System.Windows.Forms.ProgressBar
        $bar.Style = 'Marquee'
        $bar.MarqueeAnimationSpeed = 30
        $bar.Location = New-Object System.Drawing.Point(16, 54)
        $bar.Size = New-Object System.Drawing.Size(348, 18)
        $form.Controls.AddRange(@($label, $bar))
        $script:Splash = $form
        $script:SplashLabel = $label
        $form.Show()
    }
    $script:SplashLabel.Text = $Text
    Update-Splash
}

function Close-Splash {
    if ($script:Splash) {
        $script:Splash.Close()
        $script:Splash.Dispose()
        $script:Splash = $null
    }
}

function Stop-WithError([string]$Message) {
    Close-Splash
    [void][System.Windows.Forms.MessageBox]::Show($Message, 'PATRICK', 'OK', 'Error')
    exit 1
}

# --- utilitaires ---------------------------------------------------------------------------------------
function ConvertTo-Arg([string]$Text) {
    if ($Text -match '[\s"]') { return '"' + ($Text -replace '"', '\"') + '"' }
    return $Text
}

function Invoke-Native([string]$Exe, [string[]]$ArgList) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $Exe
    $psi.Arguments = ($ArgList | ForEach-Object { ConvertTo-Arg $_ }) -join ' '
    $psi.WorkingDirectory = $Root
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $out = $proc.StandardOutput.ReadToEnd()
    [void]$proc.StandardError.ReadToEnd()
    $proc.WaitForExit()
    return [pscustomobject]@{ Code = $proc.ExitCode; Out = $out.Trim() }
}

function Start-Hidden([string]$Exe, [string[]]$ArgList, [hashtable]$Extra = @{}) {
    $proc = Start-Process -FilePath $Exe -ArgumentList (($ArgList | ForEach-Object { ConvertTo-Arg $_ }) -join ' ') `
        -WorkingDirectory $Root -WindowStyle Hidden -PassThru @Extra
    [void]$proc.Handle   # garde le handle ouvert : sans cela ExitCode reste vide une fois le processus termine
    return $proc
}

function Wait-Ui($Proc, [int]$TimeoutSec) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $Proc.HasExited) {
        if ($watch.Elapsed.TotalSeconds -gt $TimeoutSec) { return $false }
        Update-Splash
        Start-Sleep -Milliseconds 80
    }
    return $true
}

# Port ouvert = serveur pret (uvicorn n'ecoute qu'une fois l'application demarree). On ne teste pas une page :
# le tableau de bord peut mettre une dizaine de secondes a repondre.
function Test-Server {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        return ($pending.AsyncWaitHandle.WaitOne(500) -and $client.Connected)
    } catch { return $false } finally { $client.Close() }
}

# Arrete le serveur qu'on a demarre. Avec un venv, python.exe est un relais qui lance le vrai interpreteur :
# on arrete le processus qui ecoute sur le port, puis le relais. Jamais d'arret "en arbre" : le worker d'un
# entrainement est un descendant independant du serveur et doit survivre a la fermeture de la fenetre.
function Stop-Server($Proc) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue }
    if ($Proc -and -not $Proc.HasExited) { Stop-Process -Id $Proc.Id -Force -ErrorAction SilentlyContinue }
}

function Find-Browser {
    $candidates = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($path in $candidates) { if (Test-Path $path) { return $path } }
    return $null
}

# --- interpreteur Python + dossier de partage ----------------------------------------------------------
Show-Splash 'Preparation...'
$probe = "import patrick, uvicorn; from patrick import sync; print(sync.configured_folder() or '')"
$py = $null
$shareFolder = ''
$interpreters = @()
$venvPython = Join-Path $Root '.venv\Scripts\python.exe'
if (Test-Path $venvPython) { $interpreters += $venvPython }
$onPath = Get-Command python.exe -ErrorAction SilentlyContinue
if ($onPath) { $interpreters += $onPath.Source }
foreach ($candidate in $interpreters) {
    $res = Invoke-Native $candidate @('-c', $probe)
    if ($res.Code -eq 0) { $py = $candidate; $shareFolder = $res.Out; break }
}
if (-not $py) {
    Stop-WithError ("Python avec PATRICK introuvable.`n`nDans $Root :`n  python -m venv .venv`n  .venv\Scripts\activate`n  pip install -e `".[dev,web]`"")
}
$syncActive = (-not $NoSync) -and $shareFolder

# --- serveur deja ouvert (autre fenetre, patrick serve lance a la main) : on s'y connecte -------------------
$server = $null
if (Test-Server) {
    $syncActive = $false   # la base est utilisee : ni fusion ni publication, ce n'est pas nous qui fermons le serveur
} else {
    # --- fusion de ce que l'autre PC a publie -------------------------------------------------------------
    if ($syncActive) {
        Show-Splash 'Synchronisation...'
        $sync = Start-Hidden $py @('-m', 'patrick.cli', 'sync', 'auto', '--only', 'pull', '--log-file', $SyncLog)
        if (-not (Wait-Ui $sync 1800)) {
            Stop-Process -Id $sync.Id -Force
            Stop-WithError "La synchronisation depasse 30 minutes : arretee. Relance PATRICK ou lance `patrick sync auto` a la main."
        }
        if ($sync.ExitCode -ne 0) {
            Close-Splash
            [void][System.Windows.Forms.MessageBox]::Show(
                "La synchronisation n'a pas abouti (details : $SyncLog).`nPATRICK demarre quand meme avec les donnees de ce PC.",
                'PATRICK', 'OK', 'Warning')
        }
    }

    # --- serveur ------------------------------------------------------------------------------------------
    Show-Splash 'Demarrage de PATRICK...'
    $outLog = Join-Path $LogDir 'app-serve.out.log'
    $errLog = Join-Path $LogDir 'app-serve.err.log'
    $server = Start-Hidden $py @('-m', 'patrick.cli', 'serve', '--port', "$Port") @{
        RedirectStandardOutput = $outLog; RedirectStandardError = $errLog }
    $ready = $false
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($watch.Elapsed.TotalSeconds -lt 120) {
        if ($server.HasExited) { break }
        if (Test-Server) { $ready = $true; break }
        Update-Splash
        Start-Sleep -Milliseconds 300
    }
    if (-not $ready) {
        $detail = ''
        if (Test-Path $errLog) { $detail = (Get-Content $errLog -Tail 8) -join "`n" }
        Stop-Server $server
        Stop-WithError "Le serveur PATRICK n'a pas demarre.`n`n$detail`n`nJournal : $errLog"
    }
}
Close-Splash

# --- fenetre en mode application -----------------------------------------------------------------------
if (-not $NoBrowser) {
    $browser = Find-Browser
    if (-not $browser) {
        if ($server) { Stop-Server $server }
        Stop-WithError "Ni Chrome ni Edge trouves. PATRICK tourne sur $Url (installe Chrome ou ouvre cette adresse)."
    }
    # Profil dedie : la fenetre est un processus a part, ce qui permet de savoir quand elle est fermee.
    $profileDir = Join-Path $env:LOCALAPPDATA 'PATRICK\app-profile'
    New-Item -ItemType Directory -Force -Path $profileDir | Out-Null
    $browserArgs = @("--app=$Url", "--user-data-dir=$profileDir", '--window-size=1500,950',
                     '--no-first-run', '--no-default-browser-check')
    Start-Process -FilePath $browser -ArgumentList (($browserArgs | ForEach-Object { ConvertTo-Arg $_ }) -join ' ')

    $isOpen = {
        $found = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
            Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileDir) }
        return [bool]$found
    }
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not (& $isOpen) -and $watch.Elapsed.TotalSeconds -lt 30) { Start-Sleep -Milliseconds 500 }
    while (& $isOpen) { Start-Sleep -Seconds 2 }
}

# --- fermeture : serveur, puis publication en arriere-plan ----------------------------------------------
if ($server) { Stop-Server $server }
if ($syncActive) {
    [void](Start-Hidden $py @('-m', 'patrick.cli', 'sync', 'auto', '--only', 'push', '--log-file', $SyncLog))
}
exit 0
