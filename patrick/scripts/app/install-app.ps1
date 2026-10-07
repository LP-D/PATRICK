<#
  Cree le raccourci PATRICK (mode application) sur le Bureau et dans le menu Demarrer de CE PC.
  A relancer si le depot est deplace. Aucun droit administrateur requis.
  Fichier volontairement en ASCII : Windows PowerShell 5.1 lit mal l'UTF-8 sans BOM.
#>
param(
    [string]$Name = 'PATRICK'
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$Launcher = Join-Path $PSScriptRoot 'PATRICK-app.ps1'
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$DataDir = Join-Path $env:LOCALAPPDATA 'PATRICK'
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

# Icone : un P ambre sur fond sombre (aucun fichier image a versionner).
$iconPath = Join-Path $DataDir 'patrick.ico'
$bitmap = New-Object System.Drawing.Bitmap 64, 64
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.SmoothingMode = 'AntiAlias'
$graphics.TextRenderingHint = 'AntiAliasGridFit'
$graphics.Clear([System.Drawing.Color]::FromArgb(27, 31, 42))
$font = New-Object System.Drawing.Font('Segoe UI', 42, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(232, 163, 61))
$format = New-Object System.Drawing.StringFormat
$format.Alignment = 'Center'
$format.LineAlignment = 'Center'
$graphics.DrawString('P', $font, $brush, (New-Object System.Drawing.RectangleF(0, 0, 64, 64)), $format)
$icon = [System.Drawing.Icon]::FromHandle($bitmap.GetHicon())
$stream = [System.IO.File]::Create($iconPath)
$icon.Save($stream)
$stream.Close()
$graphics.Dispose()
$bitmap.Dispose()

$shell = New-Object -ComObject WScript.Shell
$targets = @(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$Name.lnk"),
    (Join-Path ([Environment]::GetFolderPath('Programs')) "$Name.lnk")
)
foreach ($path in $targets) {
    $link = $shell.CreateShortcut($path)
    $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $link.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Launcher`""
    $link.WorkingDirectory = $Root
    $link.IconLocation = $iconPath
    $link.Description = 'PATRICK - fenetre application (synchronisation au demarrage et a la fermeture)'
    $link.Save()
    Write-Output "Raccourci cree : $path"
}
