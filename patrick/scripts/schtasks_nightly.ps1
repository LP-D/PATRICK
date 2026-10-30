<#
Passage de nuit planifie : tache Windows "Patrick-Nightly" pour `scripts/nightly_run.ps1`.

Chaque jour a l'heure choisie (23:00 par defaut), la tache REVEILLE le PC, lance tout ce qui doit tourner (mise a jour, predictions des modeles et
cycle du pilote automatique des fonds, actualites, sauvegarde de la base, synchronisation OneDrive), puis remet le PC en veille
prolongee s'il n'y a plus rien d'autre en cours. Detail des etapes : en-tete de `nightly_run.ps1`.

Utilisation (PowerShell, depuis n'importe ou) :
    .\schtasks_nightly.ps1                        # n'installe RIEN : affiche la tache et l'etat du reveil automatique
    .\schtasks_nightly.ps1 -Install               # cree (ou remplace) la tache pour l'utilisateur courant
    .\schtasks_nightly.ps1 -Install -At 23:30 -End hibernate -IdleMinutes 10   # autre heure, autre fin
    .\schtasks_nightly.ps1 -Remove                # supprime la tache

CE QUE WINDOWS PEUT ET NE PEUT PAS FAIRE
- Une tache reveille un PC en VEILLE ou en VEILLE PROLONGEE (hibernation) : c'est ce que fait `-End hibernate` (defaut) ou `sleep`.
- Elle ne peut PAS allumer un PC completement ETEINT (`-End shutdown`) : il faudrait une alarme de reveil dans le BIOS/UEFI
  ("Power on by RTC alarm"), reglage propre a chaque carte mere. Choisir `shutdown` revient donc a ne plus avoir de reveil.
- Le reveil exige que les "minuteurs de reveil" soient autorises dans le plan d'alimentation ; ce script le VERIFIE et affiche la
  commande a lancer si ce n'est pas le cas, mais ne change aucun reglage du systeme.
- La session Windows doit rester ouverte (la veille prolongee la conserve) : la tache tourne sous ton compte, sans mot de passe stocke.

Securites : le PC n'est remis en veille que si PATRICK n'est pas ouvert, qu'aucun entrainement ne tourne et que personne n'a touche
au clavier ni a la souris depuis `-IdleMinutes` minutes. `StartWhenAvailable` : un passage manque (PC eteint a l'heure prevue)
part des que le PC redemarre. Aucune limite de duree (Windows coupait la tache a 6 h, en pleines predictions : sauvegarde et synchro ne tournaient jamais). Journal : `runs\nightly.log`.
#>
param(
    [switch]$Install,
    [switch]$Remove,
    [string]$At = "23:00",
    [ValidateSet("hibernate", "sleep", "shutdown", "none")][string]$End = "hibernate",
    [int]$IdleMinutes = 10
)

$ErrorActionPreference = "Stop"
$TaskName   = "Patrick-Nightly"
$RepoDir    = Split-Path -Parent $PSScriptRoot
$RunScript  = Join-Path $RepoDir "scripts\nightly_run.ps1"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Tache $TaskName supprimee."
    } else {
        Write-Output "Tache $TaskName absente : rien a supprimer."
    }
    return
}

if (-not (Test-Path $RunScript)) { throw "nightly_run.ps1 introuvable : $RunScript" }
$Arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$RunScript`" -End $End -IdleMinutes $IdleMinutes"

Write-Output "Tache      : $TaskName (tous les jours a $At, heure locale, reveil du PC)"
Write-Output "Commande   : powershell.exe $Arguments"
Write-Output "Dossier    : $RepoDir"
Write-Output "Fin        : $End (seulement si PATRICK est ferme, aucun entrainement et PC inutilise depuis $IdleMinutes min)"
Write-Output "Duree max  : aucune (la tache va au bout des predictions, meme si elles durent plus de 6 h)"
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Write-Output ("Etat actuel: " + $(if ($existing) { "deja installee ($($existing.State))" } else { "non installee" }))

# Etat du reveil automatique (lecture seule : aucun reglage n'est modifie).
$wakeOk = $null
try {
    $q = (& powercfg /query SCHEME_CURRENT SUB_SLEEP RTCWAKE) -join "`n"
    # Les deux dernieres valeurs hexadecimales de la sortie : secteur puis batterie (libelles traduits selon la langue de Windows).
    $hex = [regex]::Matches($q, "0x([0-9a-fA-F]{8})")
    if ($hex.Count -ge 2) { $wakeOk = ([Convert]::ToInt32($hex[$hex.Count - 2].Groups[1].Value, 16) -ne 0) }
} catch { }
if ($null -eq $wakeOk) {
    Write-Output "Reveil     : etat des minuteurs de reveil non lisible (plan d'alimentation) - a verifier dans Options d'alimentation."
} elseif ($wakeOk) {
    Write-Output "Reveil     : minuteurs de reveil autorises (secteur) - OK."
} else {
    Write-Output "Reveil     : minuteurs de reveil INTERDITS sur secteur : la tache ne pourra pas reveiller le PC."
    Write-Output "             Pour les autoriser : powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 ; powercfg /setactive SCHEME_CURRENT"
}
if ($End -eq "hibernate") {
    $avail = (& powercfg /a) -join "`n"
    if ($avail -notmatch "Hibernat|veille prolong") { Write-Output "Attention  : la veille prolongee n'a pas l'air activee (powercfg /hibernate on, en administrateur)." }
}
if ($End -eq "shutdown") {
    Write-Output "Attention  : un PC eteint ne peut pas etre reveille par une tache Windows (voir l'en-tete de ce script)."
}

if (-not $Install) {
    Write-Output ""
    Write-Output "Rien n'a ete installe. Pour creer la tache : .\schtasks_nightly.ps1 -Install"
    Write-Output "Essai a blanc de la nuit (rien n'est lance) : .\nightly_run.ps1 -DryRun"
    Write-Output "Essai immediat apres installation          : Start-ScheduledTask -TaskName $TaskName"
    Write-Output "Verification                               : Get-ScheduledTaskInfo -TaskName $TaskName"
    return
}

$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $Arguments -WorkingDirectory $RepoDir
$trigger  = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force `
    -Description "PATRICK : passage de nuit (predictions, pilote automatique des fonds, actualites, sauvegarde, synchronisation), puis mise en veille prolongee." | Out-Null
Write-Output ""
Write-Output "Tache $TaskName installee. Premier passage : $At (heure locale). Essai immediat : Start-ScheduledTask -TaskName $TaskName"
