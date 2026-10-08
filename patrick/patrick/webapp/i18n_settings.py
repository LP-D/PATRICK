"""Chaînes FR/EN de la page Réglages (`/reglages`). Fusionnées dans `i18n.STRINGS` ; `SETTINGS_JS_KEYS` complète
`i18n.js_strings` (clés lues par `reglages.js` via `window.I18N`)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


SETTINGS_STRINGS: dict[str, dict[str, str]] = {
    "nav_settings": _s("Réglages", "Settings"),
    "app_title": _s("Réglages", "Settings"),
    "app_subtitle": _s("Dossier partagé entre tes PC, mises à jour, fenêtre, performances et sauvegardes.",
                       "Folder shared between your PCs, updates, window, performance and backups."),
    "app_open": _s("Ouvrir", "Open"),
    "app_saved": _s("Enregistré.", "Saved."),
    "app_error": _s("Erreur : {error}", "Error: {error}"),
    "app_working": _s("En cours…", "Working…"),

    # --- partage entre PC
    "app_share_title": _s("Partage entre PC", "Sharing between PCs"),
    "app_share_intro": _s(
        "Un dossier synchronisé (OneDrive, disque réseau…) permet à tes PC d'échanger leurs résultats. "
        "Rien n'est jamais écrasé : les résultats de chaque PC s'additionnent.",
        "A synced folder (OneDrive, network drive…) lets your PCs exchange their results. "
        "Nothing is ever overwritten: each PC's results are added together."),
    "app_share_none": _s("Aucun dossier partagé : ce PC travaille seul.", "No shared folder: this PC works alone."),
    "app_share_current": _s("Dossier partagé : {folder}", "Shared folder: {folder}"),
    "app_share_folder_label": _s("Dossier partagé", "Shared folder"),
    "app_share_browse": _s("Parcourir…", "Browse…"),
    "app_share_save": _s("Enregistrer le dossier", "Save folder"),
    "app_share_clear": _s("Ne plus partager (ce PC seul)", "Stop sharing (this PC only)"),
    "app_share_reference": _s("Ce PC est la référence du patrimoine (comptes, fonds)",
                              "This PC is the reference for wealth (accounts, funds)"),
    "app_share_reference_hint": _s(
        "Il publie son patrimoine dans le dossier partagé ; les autres PC l'adoptent en remplaçant le leur. "
        "Choisis donc un dossier privé.",
        "It publishes its wealth data into the shared folder; the other PCs adopt it, replacing their own. "
        "Pick a private folder."),
    "app_share_schedule": _s("Publier ce PC automatiquement toutes les heures (tâche planifiée Windows)",
                             "Publish this PC automatically every hour (Windows scheduled task)"),
    "app_share_auto_title": _s("Au démarrage et à la fermeture", "At startup and on exit"),
    "app_share_sync_start": _s("Fusionner les résultats des autres PC au démarrage",
                               "Merge the other PCs' results at startup"),
    "app_share_sync_close": _s("Publier ce PC à la fermeture", "Publish this PC on exit"),
    "app_share_sync_now": _s("Synchroniser maintenant", "Sync now"),
    "app_share_clear_label": _s("Ne plus partager", "Stop sharing"),
    "app_share_sync_now_label": _s("Synchroniser", "Sync"),
    "app_update_apply_label": _s("Mettre à jour", "Update"),
    "app_share_sync_now_hint": _s("PATRICK se ferme un instant, fusionne le dossier partagé puis se rouvre.",
                                  "PATRICK closes for a moment, merges the shared folder, then reopens."),
    "app_share_open": _s("Ouvrir le dossier", "Open folder"),
    "app_inspect_share": _s("Partage PATRICK trouvé : {runs} run(s), publié le {date}.",
                            "PATRICK share found: {runs} run(s), published on {date}."),
    "app_inspect_empty": _s("Dossier vide : ce PC sera le premier à publier.",
                            "Empty folder: this PC will be the first to publish."),
    "app_inspect_create": _s("Ce dossier sera créé.", "This folder will be created."),
    "app_inspect_readonly": _s("PATRICK ne peut pas écrire dans ce dossier.", "PATRICK cannot write to this folder."),
    "app_inspect_missing": _s("Dossier introuvable (le dossier parent doit exister).",
                              "Folder not found (its parent folder must exist)."),
    "app_inspect_other": _s("Ce dossier contient d'autres fichiers : PATRICK y ajoutera les siens.",
                            "This folder contains other files: PATRICK will add its own."),
    "app_status_title": _s("État de la synchronisation", "Sync status"),
    "app_status_loading": _s("Calcul en cours…", "Computing…"),
    "app_status_local": _s("Ce PC : {n} run(s)", "This PC: {n} run(s)"),
    "app_status_remote": _s("Partage : {n} run(s), publié le {date}", "Share: {n} run(s), published on {date}"),
    "app_status_remote_empty": _s("Partage : vide", "Share: empty"),
    "app_status_last": _s("Dernier échange : {date}", "Last exchange: {date}"),
    "app_status_never": _s("jamais", "never"),
    "app_status_todo": _s("À faire : {todo}", "To do: {todo}"),
    "app_status_uptodate": _s("rien, tout est à jour", "nothing, everything is up to date"),
    "app_status_pull": _s("fusionner le partage", "merge the share"),
    "app_status_push": _s("publier ce PC", "publish this PC"),
    "app_status_role_ref": _s("Patrimoine : ce PC est la référence (il le publie).",
                              "Wealth: this PC is the reference (it publishes it)."),
    "app_status_role_follow": _s("Patrimoine : adopté du PC de référence s'il en publie un, sinon local.",
                                 "Wealth: adopted from the reference PC if it publishes one, otherwise local."),
    "app_task_on": _s("Publication horaire active (prochaine : {next})", "Hourly publication active (next: {next})"),
    "app_task_off": _s("Publication horaire inactive.", "Hourly publication inactive."),
    "app_lastsync_title": _s("Dernière synchronisation au démarrage", "Last sync at startup"),
    "app_confirm_clear": _s(
        "Ne plus partager ? Tes données restent sur ce PC et la publication horaire est arrêtée. "
        "Le dossier partagé n'est pas touché.",
        "Stop sharing? Your data stays on this PC and hourly publication stops. The shared folder is untouched."),
    "app_confirm_sync": _s(
        "PATRICK va se fermer un instant pour fusionner le dossier partagé, puis se rouvrir. Continuer ?",
        "PATRICK will close for a moment to merge the shared folder, then reopen. Continue?"),
    "app_confirm_update": _s(
        "PATRICK va se fermer un instant pour se mettre à jour, puis se rouvrir. Continuer ?",
        "PATRICK will close for a moment to update, then reopen. Continue?"),
    "app_relaunch_title": _s("PATRICK redémarre…", "PATRICK is restarting…"),
    "app_relaunch_hint": _s("Cette page se rechargera toute seule. Une synchronisation peut durer plusieurs minutes.",
                            "This page will reload by itself. A sync can take several minutes."),
    "app_relaunch_lost": _s("Le serveur ne répond plus. Relance PATRICK avec son icône.",
                            "The server is not responding. Relaunch PATRICK from its icon."),
    "app_busy_training": _s("Un entraînement est en cours : réessaie à la fin.",
                            "A training run is in progress: try again when it finishes."),

    # --- mises à jour
    "app_update_title": _s("Mises à jour", "Updates"),
    "app_update_version": _s("Version installée : {commit} ({date}, branche {branch})",
                             "Installed version: {commit} ({date}, branch {branch})"),
    "app_update_auto": _s("Chercher une mise à jour à chaque démarrage", "Look for an update at every startup"),
    "app_update_check": _s("Rechercher maintenant", "Check now"),
    "app_update_apply": _s("Mettre à jour maintenant", "Update now"),
    "app_update_uptodate": _s("PATRICK est à jour.", "PATRICK is up to date."),
    "app_update_available": _s("{n} nouveauté(s) disponible(s) :", "{n} update(s) available:"),
    "app_update_hint": _s(
        "Une sauvegarde de la base est faite avant chaque mise à jour. Un entraînement en cours la reporte.",
        "The database is backed up before every update. A running training postpones it."),
    "app_update_checking": _s("Recherche en cours…", "Checking…"),

    # --- fenêtre et démarrage
    "app_window_title": _s("Fenêtre et démarrage", "Window and startup"),
    "app_window_dedicated": _s("Ouvrir PATRICK dans sa propre fenêtre (Chrome ou Edge en mode application)",
                               "Open PATRICK in its own window (Chrome or Edge in app mode)"),
    "app_window_hint": _s(
        "Désactivé : PATRICK s'ouvre dans ton navigateur par défaut et le serveur reste actif "
        "jusqu'à « Arrêter PATRICK » (menu Démarrer).",
        "Off: PATRICK opens in your default browser and the server keeps running until "
        "“Stop PATRICK” (Start menu)."),
    "app_port_label": _s("Port local du serveur", "Local server port"),
    "app_port_hint": _s("À changer seulement si un autre programme utilise ce port (effet au prochain démarrage).",
                        "Change only if another program uses this port (takes effect at next startup)."),
    "app_shortcuts": _s("Recréer les raccourcis", "Recreate shortcuts"),
    "app_shortcuts_hint": _s("Icône du bureau et dossier PATRICK du menu Démarrer.",
                             "Desktop icon and the PATRICK folder in the Start menu."),
    "app_shortcuts_done": _s("Raccourcis recréés.", "Shortcuts recreated."),

    # --- données et sauvegardes
    "app_data_title": _s("Données et sauvegardes", "Data and backups"),
    "app_data_dir": _s("Données de ce PC", "This PC's data"),
    "app_data_logs": _s("Journaux", "Logs"),
    "app_data_backups": _s("Sauvegardes", "Backups"),
    "app_data_install": _s("Dossier d'installation", "Installation folder"),
    "app_backup_info": _s("{n} sauvegarde(s) de la base, la dernière le {date}.",
                          "{n} database backup(s), the latest on {date}."),
    "app_backup_none": _s("Aucune sauvegarde pour l'instant.", "No backup yet."),
    "app_backup_now": _s("Sauvegarder maintenant", "Back up now"),
    "app_backup_started": _s("Sauvegarde lancée en arrière-plan.", "Backup started in the background."),
}

SETTINGS_JS_KEYS: tuple[str, ...] = (
    "app_saved", "app_error", "app_working", "app_share_none", "app_share_current", "app_inspect_share",
    "app_inspect_empty", "app_inspect_create", "app_inspect_readonly", "app_inspect_missing", "app_inspect_other",
    "app_status_loading", "app_status_local", "app_status_remote", "app_status_remote_empty", "app_status_last",
    "app_status_never", "app_status_todo", "app_status_uptodate", "app_status_pull", "app_status_push",
    "app_status_role_ref", "app_status_role_follow", "app_task_on", "app_task_off", "app_confirm_clear",
    "app_confirm_sync", "app_confirm_update",
    "app_share_clear_label", "app_share_sync_now_label", "app_update_apply_label", "app_relaunch_lost", "app_busy_training", "app_update_uptodate",
    "app_update_available", "app_update_checking", "app_shortcuts_done", "app_backup_info", "app_backup_none",
    "app_backup_started", "app_lastsync_title", "app_update_version", "setting_saved",
)
