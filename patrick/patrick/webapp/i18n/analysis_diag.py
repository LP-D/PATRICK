"""Chaînes FR/EN de la page Diagnostics (`/diagnostics`, `static/diagnostics.js`). Fusionnées dans `ANALYSIS_STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


DIAG_STRINGS: dict[str, dict[str, str]] = {
    "nav_diagnostics": _s("Diagnostics", "Diagnostics"),
    "dg_title": _s("Diagnostics système", "System diagnostics"),
    "dg_subtitle": _s("L'état de la machine et de PATRICK : charge, mémoire, disques, processus, base de suivi, dossiers de données et journaux. Lecture seule.", "The state of the machine and of PATRICK: load, memory, disks, processes, tracking database, data folders and logs. Read-only."),
    "dg_s_app": _s("Application et base de suivi", "Application and tracking database"),
    "dg_s_proc": _s("Processus PATRICK", "PATRICK processes"),
    "dg_h_proc": _s("Le serveur web et le worker qui exécute les runs. Aucun processus ne peut être arrêté d'ici.", "The web server and the worker that runs the jobs. No process can be stopped from here."),
    "dg_s_cpu": _s("Processeur par cœur", "CPU by core"),
    "dg_s_disks": _s("Disques", "Disks"),
    "dg_s_storage": _s("Dossiers de données", "Data folders"),
    "dg_h_storage": _s("Calculé avec un budget de temps : un signe + indique une taille partielle (dossier très volumineux).", "Computed with a time budget: a + sign means a partial size (very large folder)."),
    "dg_s_logs": _s("Journaux", "Logs"),
    "dg_h_logs": _s("Les dernières lignes d'un journal du dossier des journaux (worker, serveur, synchronisation).", "The last lines of a log in the logs folder (worker, server, synchronisation)."),
    "dg_auto": _s("Actualiser toutes les 5 s", "Refresh every 5 s"), "dg_refresh": _s("Actualiser maintenant", "Refresh now"),
    "dg_k_cpu": _s("Processeur", "CPU"), "dg_k_cpu_sub": _s("{n} cœurs logiques · {f} MHz", "{n} logical cores · {f} MHz"),
    "dg_k_ram": _s("Mémoire", "Memory"), "dg_k_ram_sub": _s("{a} libres sur {t}", "{a} free of {t}"),
    "dg_k_disk": _s("Disque des données", "Data disk"), "dg_k_disk_sub": _s("{m} · {f} libres", "{m} · {f} free"),
    "dg_k_worker": _s("Worker", "Worker"), "dg_k_worker_sub": _s("PID {p} · dernier battement il y a {a} s", "PID {p} · last heartbeat {a} s ago"), "dg_k_worker_none": _s("aucun battement enregistré", "no heartbeat recorded"),
    "dg_alive": _s("vivant", "alive"), "dg_stale": _s("figé ou arrêté", "stalled or stopped"), "dg_none": _s("absent", "absent"),
    "dg_k_queue": _s("File de jobs", "Job queue"), "dg_k_queue_sub": _s("{r} en cours · {q} en attente · {d} terminés", "{r} running · {q} queued · {d} done"),
    "dg_a_db": _s("Base de suivi", "Tracking database"), "dg_a_dbsize": _s("Fichiers de la base", "Database files"), "dg_a_schema": _s("Version du schéma", "Schema version"),
    "dg_a_version": _s("Version de PATRICK", "PATRICK version"), "dg_a_runs": _s("Runs par état", "Runs by status"), "dg_a_python": _s("Python", "Python"),
    "dg_a_platform": _s("Système", "System"), "dg_a_boot": _s("Démarrage de la machine (UTC)", "Machine boot (UTC)"), "dg_a_home": _s("Dossier de données", "Data folder"),
    "dg_role_worker": _s("worker", "worker"), "dg_role_server": _s("serveur", "server"), "dg_role_other": _s("autre", "other"),
    "dg_c_role": _s("Rôle", "Role"), "dg_c_mem": _s("Mémoire", "Memory"), "dg_c_started": _s("Démarré (UTC)", "Started (UTC)"), "dg_c_cmd": _s("Commande", "Command"),
    "dg_no_proc": _s("Aucun processus PATRICK trouvé.", "No PATRICK process found."),
    "dg_core": _s("Cœur {n}", "Core {n}"),
    "dg_c_mount": _s("Disque", "Disk"), "dg_c_total": _s("Total", "Total"), "dg_c_used": _s("Utilisé", "Used"), "dg_c_free": _s("Libre", "Free"), "dg_c_percent": _s("Occupation", "Usage"),
    "dg_c_data": _s("Données", "Data"), "dg_data_here": _s("contient les données", "holds the data"),
    "dg_c_folder": _s("Dossier", "Folder"), "dg_c_size": _s("Taille", "Size"), "dg_c_files": _s("Fichiers", "Files"), "dg_c_path": _s("Chemin", "Path"), "dg_absent": _s("absent", "absent"),
    "dg_storage_total": _s("Total : {t}.", "Total: {t}."), "dg_partial": _s("Au moins un dossier dépasse le budget de calcul : total partiel.", "At least one folder exceeds the compute budget: partial total."),
    "dg_f_file": _s("Journal", "Log"), "dg_lines": _s("{n} dernières lignes", "Last {n} lines"), "dg_only_errors": _s("Erreurs seulement", "Errors only"),
    "dg_filter": _s("Filtrer les lignes", "Filter lines"), "dg_log_empty": _s("(aucune ligne)", "(no line)"), "dg_no_logs": _s("Aucun journal dans le dossier des journaux.", "No log in the logs folder."),
}
