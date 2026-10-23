# inventaire_stockage.ps1  --  LECTURE SEULE
# Ne modifie, ne deplace et ne supprime rien. Ecrit un rapport texte (par defaut sur le Bureau) : volumes, plus gros
# dossiers de C:, OneDrive (copie locale / en ligne seulement), dossier maison de PATRICK (~/.patrick) et racine de
# donnees (reglage data_root), sauvegardes, feature_cache, taches planifiees, jonctions deja creees.
# Usage :  powershell -ExecutionPolicy Bypass -File inventaire_stockage.ps1
# Duree : 3 a 20 minutes selon le nombre de fichiers. Peut etre lance pendant que PATRICK tourne.
# Fichier volontairement en ASCII (Windows PowerShell 5.1 lit les scripts sans BOM en ANSI).
param([string]$Rapport = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'inventaire-stockage.txt'))

$ErrorActionPreference = 'SilentlyContinue'
$t0 = Get-Date
$script:lines = New-Object System.Collections.Generic.List[string]
function Say([string]$t = '') { Write-Host $t; $script:lines.Add($t) }
function Gb($b) { '{0,8:N1} Go' -f ($b / 1GB) }

# Attributs "en ligne seulement" (OneDrive a la demande) : RecallOnDataAccess, RecallOnOpen, Offline.
$RECALL = 0x400000 + 0x40000 + 0x1000
$script:liens = New-Object System.Collections.Generic.List[string]

# Taille d'un dossier sans suivre les jonctions/liens symboliques (sinon un dossier deplace sur un autre
# disque serait compte deux fois). Separe ce qui occupe le disque (Local) du "en ligne seulement" (Online).
function Get-DirSize([string]$Path) {
    $local = 0L; $online = 0L; $n = 0
    $stack = New-Object System.Collections.Generic.Stack[string]
    $stack.Push($Path)
    while ($stack.Count -gt 0) {
        $d = $stack.Pop()
        try {
            $di = New-Object System.IO.DirectoryInfo($d)
            foreach ($f in $di.EnumerateFiles()) {
                $n++
                if (([int]$f.Attributes -band $RECALL) -ne 0) { $online += $f.Length } else { $local += $f.Length }
            }
            foreach ($s in $di.EnumerateDirectories()) {
                # Un point d'analyse n'est une jonction/un lien que si LinkType le dit : les dossiers OneDrive a la
                # demande en portent aussi (sans etre des liens) et doivent etre parcourus.
                $it = $null
                if (([int]$s.Attributes -band 0x400) -ne 0) { $it = Get-Item -LiteralPath $s.FullName -Force }
                if ($it -and $it.LinkType) {
                    $script:liens.Add(('{0}  ->  {1}' -f $s.FullName, ($it.Target -join ' ; ')))
                } else { $stack.Push($s.FullName) }
            }
        } catch {}
    }
    [pscustomobject]@{ Path = $Path; Local = $local; Online = $online; Files = $n }
}

function Show-Children([string]$Path, [int]$Top = 15) {
    if (-not (Test-Path -LiteralPath $Path)) { Say "  (absent : $Path)"; return }
    $res = New-Object System.Collections.Generic.List[object]
    Get-ChildItem -LiteralPath $Path -Force | ForEach-Object {
        if ($_.PSIsContainer) {
            if (([int]$_.Attributes -band 0x400) -ne 0 -and $_.LinkType) {
                $script:liens.Add(('{0}  ->  {1}' -f $_.FullName, ($_.Target -join ' ; ')))
            } else {
                $r = Get-DirSize $_.FullName
                $res.Add([pscustomobject]@{ Nom = $_.Name + '\'; Local = $r.Local; Online = $r.Online; Files = $r.Files })
            }
        } else {
            $on = ([int]$_.Attributes -band $RECALL) -ne 0
            $res.Add([pscustomobject]@{ Nom = $_.Name; Local = $(if ($on) { 0 } else { $_.Length }); Online = $(if ($on) { $_.Length } else { 0 }); Files = 1 })
        }
    }
    $res | Sort-Object Local -Descending | Select-Object -First $Top | ForEach-Object {
        Say ('  {0}  (+{1} en ligne seulement)  {2,9:N0} fichiers  {3}' -f (Gb $_.Local), (Gb $_.Online).Trim(), $_.Files, $_.Nom)
    }
}

Say "Inventaire du stockage -- $env:COMPUTERNAME -- $(Get-Date -Format 'yyyy-MM-dd HH:mm')   (LECTURE SEULE)"
Say ''
Say '== Volumes'
Get-Volume | Where-Object { $_.DriveLetter } | ForEach-Object {
    Say ('  {0}:  {1,-14} {2,-6} total {3}  libre {4}' -f $_.DriveLetter, $_.FileSystemLabel, $_.FileSystem, (Gb $_.Size), (Gb $_.SizeRemaining))
}
Say '== Disques physiques'
Get-PhysicalDisk | ForEach-Object { Say ('  {0}  type={1}  bus={2}  {3}' -f $_.FriendlyName, $_.MediaType, $_.BusType, (Gb $_.Size)) }

Say ''
Say '== Racine de C: (hors Users, detaille plus bas)'
$rootRes = New-Object System.Collections.Generic.List[object]
Get-ChildItem 'C:\' -Force | Where-Object { $_.Name -ne 'Users' } | ForEach-Object {
    if ($_.PSIsContainer) { $r = Get-DirSize $_.FullName; $rootRes.Add([pscustomobject]@{ Nom = $_.Name + '\'; Local = $r.Local; Online = $r.Online; Files = $r.Files }) }
    else { $rootRes.Add([pscustomobject]@{ Nom = $_.Name; Local = $_.Length; Online = 0; Files = 1 }) }
}
$rootRes | Sort-Object Local -Descending | Select-Object -First 12 | ForEach-Object {
    Say ('  {0}  {1,9:N0} fichiers  {2}' -f (Gb $_.Local), $_.Files, $_.Nom)
}

Say ''
Say "== Profil utilisateur : $env:USERPROFILE"
Show-Children $env:USERPROFILE 18
Say '-- AppData\Local'
Show-Children (Join-Path $env:USERPROFILE 'AppData\Local') 12
Say '-- AppData\Roaming'
Show-Children (Join-Path $env:USERPROFILE 'AppData\Roaming') 8
Say '-- Autres profils (taille totale)'
Get-ChildItem 'C:\Users' -Force | Where-Object { $_.PSIsContainer -and $_.FullName -ne $env:USERPROFILE } | ForEach-Object {
    $r = Get-DirSize $_.FullName; Say ('  {0}  {1}' -f (Gb $r.Local), $_.Name)
}

Say ''
Say '== OneDrive (copie locale vs en ligne seulement)'
$seen = @{}
foreach ($v in 'OneDrive', 'OneDriveCommercial', 'OneDriveConsumer') {
    $p = [Environment]::GetEnvironmentVariable($v)
    if ($p -and -not $seen.ContainsKey($p) -and (Test-Path -LiteralPath $p)) {
        $seen[$p] = 1
        $r = Get-DirSize $p
        Say ('  {0}' -f $p)
        Say ('    sur le disque : {0}   en ligne seulement : {1}   {2:N0} fichiers' -f (Gb $r.Local).Trim(), (Gb $r.Online).Trim(), $r.Files)
        Show-Children $p 10
    }
}

Say ''
$pat = Join-Path $env:USERPROFILE '.patrick'
# Racine de donnees (reglage data_root de settings.json) : magasin, modeles, caches et sauvegardes y vivent quand elle est reglee.
$dr = $pat
$cfg = Get-Content -Raw -LiteralPath (Join-Path $pat 'settings.json') | ConvertFrom-Json
if ($cfg -and $cfg.data_root) { $dr = [string]$cfg.data_root }
Say "== PATRICK : dossier maison $pat"
Show-Children $pat 20
if ($dr -ne $pat) {
    Say "-- Racine de donnees (data_root) : $dr"
    if (Test-Path -LiteralPath $dr) { Show-Children $dr 20 } else { Say '  INTROUVABLE (disque absent ?)' }
}
$bk = Join-Path $dr 'backups'
if (Test-Path -LiteralPath $bk) {
    Say '-- Sauvegardes de la base (les plus grosses, puis les plus recentes)'
    $f = Get-ChildItem -LiteralPath $bk -File -Filter 'patrick_backup_*.db' | Sort-Object LastWriteTime -Descending
    Say ('  {0} fichiers, {1}' -f $f.Count, (Gb (($f | Measure-Object Length -Sum).Sum)).Trim())
    $f | Sort-Object Length -Descending | Select-Object -First 5 | ForEach-Object { Say ('  {0:yyyy-MM-dd HH:mm}  {1}  {2}' -f $_.LastWriteTime, (Gb $_.Length), $_.Name) }
    Say '  ...'
    $f | Select-Object -First 4 | ForEach-Object { Say ('  {0:yyyy-MM-dd HH:mm}  {1}  {2}' -f $_.LastWriteTime, (Gb $_.Length), $_.Name) }
}
$fc = Join-Path $dr 'feature_cache'
if (Test-Path -LiteralPath $fc) {
    Say '-- feature_cache par anciennete (derniere ecriture)'
    $now = Get-Date
    Get-ChildItem -LiteralPath $fc -Recurse -File -Filter '*.parquet' | Group-Object {
        $d = ($now - $_.LastWriteTime).TotalDays
        if ($d -le 7) { 'a: <= 7 j' } elseif ($d -le 14) { 'b: 7-14 j' } elseif ($d -le 30) { 'c: 14-30 j' } else { 'd: > 30 j' }
    } | Sort-Object Name | ForEach-Object { Say ('  {0,-11} {1,7} fichiers  {2}' -f $_.Name, $_.Count, (Gb (($_.Group | Measure-Object Length -Sum).Sum))) }
}
Say '-- Reglages PATRICK (settings.json)'
Get-Content -LiteralPath (Join-Path $pat 'settings.json') | ForEach-Object { Say "  $_" }
Say '-- Taches planifiees PATRICK'
Get-ScheduledTask | Where-Object { $_.TaskName -like 'PATRICK*' } | ForEach-Object {
    $i = Get-ScheduledTaskInfo -TaskName $_.TaskName -TaskPath $_.TaskPath
    Say ('  {0}  etat={1}  derniere={2}  resultat={3}' -f $_.TaskName, $_.State, $i.LastRunTime, $i.LastTaskResult)
}
Say '-- Processus PATRICK / sauvegarde en cours'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'patrick' -and $_.Name -notmatch 'chrome|powershell|cmd' } | ForEach-Object {
    $c = $_.CommandLine; if ($c.Length -gt 140) { $c = $c.Substring(0, 140) + '...' }
    Say ('  pid {0}  {1}' -f $_.ProcessId, $c)
}

Say ''
Say '== Gros consommateurs connus'
foreach ($p in 'C:\Windows.old', 'C:\Windows\SoftwareDistribution\Download', 'C:\Windows\Temp', (Join-Path $env:LOCALAPPDATA 'Temp'),
               (Join-Path $env:USERPROFILE '.claude'), (Join-Path $env:LOCALAPPDATA 'Docker'), (Join-Path $env:LOCALAPPDATA 'pip\Cache'),
               (Join-Path $env:LOCALAPPDATA 'npm-cache'), (Join-Path $env:USERPROFILE '.cache'), (Join-Path $env:USERPROFILE '.ollama')) {
    if (Test-Path -LiteralPath $p) { $r = Get-DirSize $p; Say ('  {0}  {1}' -f (Gb $r.Local), $p) }
}
foreach ($f in 'C:\hiberfil.sys', 'C:\pagefile.sys', 'C:\swapfile.sys') { $i = Get-Item -LiteralPath $f -Force; if ($i) { Say ('  {0}  {1}' -f (Gb $i.Length), $f) } }
Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Packages\*\LocalState\*.vhdx') -Force | ForEach-Object { Say ('  {0}  {1}' -f (Gb $_.Length), $_.FullName) }
Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Docker\wsl\*\*.vhdx') -Force | ForEach-Object { Say ('  {0}  {1}' -f (Gb $_.Length), $_.FullName) }

Say ''
Say '== Jonctions / liens vers un autre disque ou dans PATRICK (dossiers deja deplaces ailleurs ?)'
$tous = @($script:liens | Sort-Object -Unique)
$utiles = @($tous | Where-Object { $_ -match '\\\.patrick\\|\\PATRICK|->\s+[D-Za-z]:' -and $_ -notmatch '->\s+C:\\(ProgramData|Users\\[^\\]+\\\.bun)' })
if ($utiles.Count -eq 0) { Say '  aucun' } else { $utiles | Select-Object -First 60 | ForEach-Object { Say "  $_" } }
Say ('  ({0} autres liens systeme ignores)' -f ($tous.Count - $utiles.Count))

Say ''
Say ('Termine en {0:N0} min. Rapport : {1}' -f ((Get-Date) - $t0).TotalMinutes, $Rapport)
$script:lines | Set-Content -LiteralPath $Rapport -Encoding UTF8
