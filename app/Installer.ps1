# Installe PATRICK sur ce PC (ou le met en ordre s'il est déjà installé) :
#   1. vérifie Git et Python (les installe avec winget s'ils manquent) ;
#   2. télécharge PATRICK depuis GitHub (branche main) dans -InstallDir ;
#   3. prépare l'environnement Python et les composants (quelques minutes la première fois) ;
#   4. crée l'icône PATRICK (bureau + menu Démarrer) et la sauvegarde quotidienne de la base ;
#   5. ouvre PATRICK : l'assistant propose de choisir le dossier partagé entre tes PC (OneDrive).
#
# Double-clic sur Installer.bat, ou depuis PowerShell :
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/LP-D/PATRICK/main/app/Installer.ps1 | iex"
# Peut être relancé sans risque (il met à jour ce qui existe, ne touche jamais aux données dans ~\.patrick).
param(
    [string]$InstallDir = (Join-Path $env:USERPROFILE 'PATRICK-stable'),
    [string]$Repo = 'https://github.com/LP-D/PATRICK.git',
    [string]$Branch = 'main',
    [switch]$NoLaunch,
    [switch]$NoBackupTask,      # ne planifie pas la sauvegarde quotidienne de la base
    [switch]$SkipDependencies   # tests : saute l'installation des composants (longue)
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step([string]$text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Write-Ok([string]$text) { Write-Host "   $text" -ForegroundColor Green }
function Stop-Install([string]$text) {
    Write-Host "`nERREUR : $text" -ForegroundColor Red
    if ($Host.Name -eq 'ConsoleHost' -and [Environment]::UserInteractive) { Read-Host 'Appuie sur Entrée pour fermer' | Out-Null }
    exit 1
}

function Update-Path {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

function Install-WithWinget([string]$id, [string]$label) {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) { Stop-Install "$label est introuvable et winget n'est pas disponible. Installe $label à la main puis relance." }
    Write-Host "   Installation de $label (winget)..."
    & winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Update-Path
}

# Python >= 3.10 avec tkinter (assistant graphique) ; renvoie le chemin de python.exe ou $null.
function Find-Python {
    $candidates = @()
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) { foreach ($v in '3.12', '3.11', '3.10', '3.13') { $candidates += ,@($launcher.Source, "-$v") } }
    foreach ($name in 'python', 'python3') {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # le faux « python » du Windows Store (WindowsApps) ouvre le Store : on l'ignore
        if ($cmd -and $cmd.Source -notmatch 'WindowsApps') { $candidates += ,@($cmd.Source) }
    }
    foreach ($c in $candidates) {
        try {
            $exe = $c[0]; $extra = @($c | Select-Object -Skip 1)
            $out = & $exe @extra -c "import sys, tkinter; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).Trim() }
        } catch { continue }
    }
    return $null
}

function Invoke-Checked([string]$what, [string]$exe, [string[]]$arguments, [string]$workDir = $null) {
    if ($workDir) { Push-Location $workDir }
    # Windows PowerShell 5.1 : un message sur stderr (git écrit sa progression là) ne doit pas arrêter le script.
    $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $exe @arguments; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $previous; if ($workDir) { Pop-Location } }
    if ($code -ne 0) { Stop-Install "$what a échoué (code $code)." }
}

Write-Host "Installation de PATRICK dans : $InstallDir" -ForegroundColor White

# --- 1. Git et Python ---------------------------------------------------------------------------------------------
Write-Step '1/5  Git et Python'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Install-WithWinget 'Git.Git' 'Git' }
$git = (Get-Command git -ErrorAction SilentlyContinue)
if (-not $git) { Stop-Install "Git reste introuvable. Ferme cette fenêtre, rouvre-la et relance l'installation." }
Write-Ok "Git : $($git.Source)"

$python = Find-Python
if (-not $python) { Install-WithWinget 'Python.Python.3.12' 'Python 3.12'; $python = Find-Python }
if (-not $python) { Stop-Install "Python 3.10 ou plus (avec tkinter) reste introuvable. Installe Python 3.12 depuis python.org (option « tcl/tk » cochée) puis relance." }
Write-Ok "Python : $python"

# --- 2. Code ------------------------------------------------------------------------------------------------------
Write-Step "2/5  Téléchargement de PATRICK ($Branch)"
$env:GIT_TERMINAL_PROMPT = '0'
if (Test-Path (Join-Path $InstallDir '.git')) {
    Invoke-Checked 'git fetch' $git.Source @('-C', $InstallDir, 'fetch', 'origin', $Branch)
    $current = (& $git.Source -C $InstallDir rev-parse --abbrev-ref HEAD).Trim()
    $dirty = (& $git.Source -C $InstallDir status --porcelain --untracked-files=no)
    if ($current -eq $Branch -and -not $dirty) {
        Invoke-Checked 'git merge' $git.Source @('-C', $InstallDir, 'merge', '--ff-only', "origin/$Branch")
    } else {
        Write-Host "   Dossier existant sur '$current' ou modifié : code laissé tel quel." -ForegroundColor Yellow
    }
} elseif ((Test-Path $InstallDir) -and (Get-ChildItem $InstallDir -Force | Select-Object -First 1)) {
    Stop-Install "Le dossier $InstallDir existe déjà et n'est pas une installation de PATRICK. Choisis un autre -InstallDir."
} else {
    Invoke-Checked 'git clone' $git.Source @('clone', '--branch', $Branch, $Repo, $InstallDir)
}
$project = Join-Path $InstallDir 'patrick'
if (-not (Test-Path (Join-Path $project 'pyproject.toml'))) { Stop-Install "pyproject.toml introuvable dans $project : dépôt inattendu." }
Write-Ok 'Code à jour.'

# --- 3. Environnement Python ----------------------------------------------------------------------------------------
Write-Step '3/5  Environnement Python et composants (plusieurs minutes la première fois)'
$venv = Join-Path $project '.venv'
$venvPy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $venvPy)) { Invoke-Checked 'création de l''environnement' $python @('-m', 'venv', $venv) }
if ($SkipDependencies) {
    Write-Host '   (-SkipDependencies : composants non installés)' -ForegroundColor Yellow
} else {
    Invoke-Checked 'pip (mise à jour)' $venvPy @('-m', 'pip', 'install', '--upgrade', 'pip', '-q')
    Invoke-Checked 'installation des composants' $venvPy @('-m', 'pip', 'install', '-e', '.[web]') $project
}
Write-Ok 'Environnement prêt.'

# --- 4. Raccourcis et sauvegarde quotidienne -----------------------------------------------------------------------------
Write-Step '4/5  Icône PATRICK et sauvegarde quotidienne'
Invoke-Checked 'création des raccourcis' $venvPy @('-m', 'patrick.desktop', 'shortcuts') $project
$pythonw = Join-Path $venv 'Scripts\pythonw.exe'
$backupScript = Join-Path $project 'scripts\backup_db.py'
$backupLog = Join-Path $env:USERPROFILE '.patrick\backups\backup.log'
New-Item -ItemType Directory -Force -Path (Split-Path $backupLog) | Out-Null
$task = "`"$pythonw`" `"$backupScript`" --log-file `"$backupLog`""
if ($NoBackupTask) { $global:LASTEXITCODE = 1 } else { & schtasks /Create /TN 'PATRICK-SauvegardeBase' /TR $task /SC DAILY /ST 23:30 /F | Out-Null }
if ($LASTEXITCODE -eq 0) {
    # sur batterie et rattrapage si le PC était éteint à 23h30
    & powershell -NoProfile -Command "Set-ScheduledTask -TaskName 'PATRICK-SauvegardeBase' -Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable) | Out-Null"
    Write-Ok 'Sauvegarde de la base chaque jour à 23h30 (conservée 30 jours).'
} else {
    Write-Host '   Sauvegarde quotidienne non planifiée.' -ForegroundColor Yellow
}

# --- 5. Lancement ---------------------------------------------------------------------------------------------------
Write-Step '5/5  Terminé'
Write-Host "PATRICK est installé. Icône « PATRICK » sur le bureau et dans le menu Démarrer." -ForegroundColor Green
if (-not $NoLaunch) {
    Write-Host 'Ouverture de PATRICK : choisis ton dossier partagé (OneDrive) dans la fenêtre qui s''affiche.'
    Start-Process -FilePath $pythonw -ArgumentList @('-m', 'patrick.desktop', 'launch') -WorkingDirectory $project
}
exit 0
