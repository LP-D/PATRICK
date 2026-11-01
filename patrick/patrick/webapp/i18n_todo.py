"""Chaînes FR/EN des pages « À faire » de la Synthèse (`/a-faire/<ligne>`, `webapp/todo_actions.py`). Fusionnées dans `i18n.STRINGS` ;
`TODO_JS_KEYS` (lues par `static/a_faire.js`) n'est envoyé au navigateur que sur ces pages (`i18n.js_strings`)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


TODO_STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ cadre des pages
    "td_title_failures": _s("Échecs de run récents", "Recent run failures"),
    "td_title_suspect": _s("Runs à ne pas suivre", "Runs not to follow"),
    "td_title_fx_legacy": _s("Champions de change d'avant la correction", "Currency champions from before the fix"),
    "td_title_queue": _s("File d'attente", "Queue"),
    "td_sub_failures": _s("Les échecs des {d} derniers jours (hors runs arrêtés à la main), groupés par cause. Chaque cause propose le réentraînement qui la "
                          "répare ; ce qui est déjà remplacé ou déjà en file n'est pas reproposé.",
                          "Failures of the last {d} days (runs stopped by hand excluded), grouped by cause. Each cause proposes the retraining that "
                          "fixes it; what is already replaced or already queued is not proposed again."),
    "td_sub_suspect": _s("Runs au score trop beau pour être vrai, d'avant la règle d'alignement des devises, ou sur une cible macro retirée : jamais un "
                         "signal à suivre. Ceux qu'on peut refaire proprement sont proposés ci-dessous.",
                         "Runs with a score too good to be true, from before the currency alignment rule, or on a retired macro target: never a signal "
                         "to follow. The ones that can be redone cleanly are proposed below."),
    "td_sub_fx_legacy": _s("Champions de devise entraînés avec l'ancienne règle d'alignement : leur exactitude est un nowcast, pas une prévision. Les refaire "
                           "avec la règle d'aujourd'hui ; le nouveau modèle remplace le champion dès qu'il gagne le duel.",
                           "Currency champions trained with the old alignment rule: their accuracy is a nowcast, not a forecast. Redo them with today's "
                           "rule; the new model replaces the champion as soon as it wins the duel."),
    "td_sub_queue": _s("Les jobs en cours et ceux qui attendent un worker. Rien à relancer ici.",
                       "Running jobs and jobs waiting for a worker. Nothing to relaunch here."),
    "td_kpi_total": _s("Concernés", "Concerned"),
    "td_kpi_total_rel": _s("le nombre de la Synthèse", "the Overview figure"),
    "td_kpi_todo": _s("À relancer", "To relaunch"),
    "td_kpi_todo_rel": _s("lignes proposées au réentraînement", "lines proposed for retraining"),
    "td_kpi_pending": _s("Déjà en file", "Already queued"),
    "td_kpi_pending_rel": _s("en file ou en cours", "queued or running"),
    "td_kpi_replaced": _s("Déjà remplacés", "Already replaced"),
    "td_kpi_replaced_rel": _s("un run plus récent les couvre", "a newer run covers them"),
    "td_kpi_blocked": _s("Non relançables", "Not relaunchable"),
    "td_kpi_blocked_rel": _s("cible retirée ou config illisible", "target retired or config unreadable"),
    "td_kpi_inspect": _s("À lire", "To read"),
    "td_kpi_inspect_rel": _s("rien à relancer tel quel", "nothing to relaunch as is"),
    "td_see_also": _s("Pour aller plus loin :", "To go further:"),
    "td_empty": _s("Rien à faire ici : ce sujet est réglé.", "Nothing to do here: this item is settled."),
    # ------------------------------------------------------------------ un groupe
    "td_plan_title": _s("Réentraînement proposé", "Proposed retraining"),
    "td_plan_same": _s("Les mêmes réglages que le run d'origine.", "The same settings as the original run."),
    "td_plan_changed": _s("Réglages changés : {changes}.", "Settings changed: {changes}."),
    "td_cost_same": _s("Coût : celui du run d'origine.", "Cost: that of the original run."),
    "td_cost_low": _s("Coût relatif : plus léger que le run d'origine (×{f}).", "Relative cost: lighter than the original run (×{f})."),
    "td_cost_medium": _s("Coût relatif : comparable au run d'origine (×{f}).", "Relative cost: comparable to the original run (×{f})."),
    "td_cost_high": _s("Coût relatif : bien plus long que le run d'origine (×{f}).", "Relative cost: much longer than the original run (×{f})."),
    "td_group_todo": _s("{n} à relancer", "{n} to relaunch"),
    "td_group_runs": _s("{n} run(s)", "{n} run(s)"),
    "td_col_target": _s("Cible", "Target"),
    "td_col_horizons": _s("Horizons", "Horizons"),
    "td_col_run": _s("Run d'origine", "Original run"),
    "td_col_when": _s("Date", "Date"),
    "td_col_detail": _s("Détail", "Detail"),
    "td_col_state": _s("État", "State"),
    "td_state_pending": _s("En file", "Queued"),
    "td_state_replaced": _s("Déjà remplacé", "Replaced"),
    "td_state_blocked": _s("Non relançable", "Not relaunchable"),
    "td_state_todo": _s("À relancer", "To relaunch"),
    "td_state_inspect": _s("À lire", "To read"),
    "td_runs_n": _s("{n} run(s)", "{n} run(s)"),
    "td_open_form": _s("Formulaire", "Form"),
    "td_open_form_title": _s("Ouvrir ce lancement dans le formulaire, pour le modifier à la main", "Open this launch in the form to edit it by hand"),
    "td_select_all": _s("Tout cocher", "Select all"),
    "td_select_none": _s("Tout décocher", "Clear all"),
    "td_selected": _s("{n} sélectionné(s)", "{n} selected"),
    "td_launch": _s("Relancer la sélection", "Relaunch the selection"),
    "td_after": _s("Les runs rejoignent la file (page Machine learning) et démarrent quand le worker est libre.",
                   "The runs join the queue (Machine learning page) and start when the worker is free."),
    "td_untouched": _s("Rien n'est lancé tant que vous ne confirmez pas.", "Nothing is launched until you confirm."),
    # ------------------------------------------------------------------ groupes : échecs (clé = cause, `data_health.ERROR_KINDS`)
    "td_g_staged_cpcv_title": _s("Présélection progressive avec la validation CPCV", "Staged screening with CPCV validation"),
    "td_g_staged_cpcv_why": _s("La présélection progressive ne tourne qu'en walk-forward : la suggestion « confirmer en CPCV » du conseiller la laissait activée, "
                               "et le run échouait à l'ingestion. Cause corrigée le 2026-11-01. Le réentraînement refait le run en CPCV complet, sans "
                               "présélection progressive : c'est la confirmation robuste voulue, plus longue que le run rapide d'origine.",
                               "Staged screening only runs with walk-forward: the advisor's “confirm with CPCV” suggestion left it on, and the run failed at "
                               "ingestion. Cause fixed on 2026-11-01. The retraining redoes the run with full CPCV and no staged screening: the robust "
                               "confirmation that was intended, longer than the original quick run."),
    "td_g_store_locked_title": _s("Fichier du magasin de données verrouillé", "Data store file locked"),
    "td_g_store_locked_why": _s("Windows a refusé de renommer un fichier d'index du magasin : un autre processus le tenait. Corrigé le 2026-10-30 par une écriture "
                                "atomique. Passager : relancer tel quel.",
                                "Windows refused to rename a store index file: another process held it. Fixed on 2026-10-30 with an atomic write. "
                                "Transient: relaunch as is."),
    "td_g_float32_overflow_title": _s("Valeur hors plage dans les variables", "Out-of-range value in the features"),
    "td_g_float32_overflow_why": _s("Une variable a pris une valeur astronomique que XGBoost refuse (limite float32). Corrigé le 2026-10-09 : relancer tel quel.",
                                    "A feature took an astronomical value that XGBoost refuses (float32 limit). Fixed on 2026-10-09: relaunch as is."),
    "td_g_class_missing_title": _s("Classe absente d'un pli d'entraînement", "Class missing from a training fold"),
    "td_g_class_missing_why": _s("Un pli ne contenait que 3 des 4 classes de mouvement et le calibrage a échoué. Corrigé le 2026-10-02 : relancer tel quel.",
                                 "A fold held only 3 of the 4 move classes and the calibration failed. Fixed on 2026-10-02: relaunch as is."),
    "td_g_db_locked_title": _s("Base verrouillée", "Database locked"),
    "td_g_db_locked_why": _s("Une autre écriture a tenu le verrou trop longtemps. Corrigé le 2026-09-27 : relancer tel quel.",
                             "Another write held the lock for too long. Fixed on 2026-09-27: relaunch as is."),
    "td_g_orphaned_title": _s("Processus perdu", "Lost process"),
    "td_g_orphaned_why": _s("Le worker a disparu (fermeture de l'application, veille, plantage) : pas un défaut de données. Relancer tel quel, de préférence depuis "
                            "un PowerShell ouvert par vous.",
                            "The worker disappeared (app closed, sleep, crash): not a data defect. Relaunch as is, preferably from a PowerShell you opened."),
    "td_g_fetch_title": _s("Récupération impossible", "Fetch failed"),
    "td_g_fetch_why": _s("La source (Yahoo Finance, FRED) n'a pas répondu. Passager : relancer tel quel.",
                         "The source (Yahoo Finance, FRED) did not answer. Transient: relaunch as is."),
    "td_g_insufficient_history_title": _s("Historique insuffisant", "Insufficient history"),
    "td_g_insufficient_history_why": _s("La série ne remonte pas assez loin pour le seuil « Historique minimum ». Rien à relancer tel quel : baisser le seuil depuis "
                                        "le formulaire, ou choisir une autre cible.",
                                        "The series does not go back far enough for the “Minimum history” threshold. Nothing to relaunch as is: lower the "
                                        "threshold in the form, or pick another target."),
    "td_g_other_title": _s("Autre erreur", "Other error"),
    "td_g_other_why": _s("Cause non classée : lire le message de chaque ligne. Rien n'est proposé automatiquement ; le formulaire s'ouvre pré-rempli.",
                         "Unclassified cause: read each line's message. Nothing is proposed automatically; the form opens pre-filled."),
    # ------------------------------------------------------------------ groupes : runs suspects
    "td_g_fx_rule1_title": _s("Devises d'avant la règle d'alignement 2", "Currencies from before alignment rule 2"),
    "td_g_fx_rule1_why": _s("Leurs variables du jour recouvraient le label : l'exactitude est un nowcast. Le réentraînement refait chaque lancement avec les mêmes "
                            "réglages et la règle d'aujourd'hui (barres de change au début de journée).",
                            "Their same-day variables overlapped the label: the accuracy is a nowcast. The retraining redoes each launch with the same "
                            "settings and today's rule (currency bars at the start of the day)."),
    "td_g_fix_leak_title": _s("Score trop beau, garde anti-fuite absente", "Score too good, leak guard absent"),
    "td_g_fix_leak_why": _s("Le run date d'avant la garde anti-fuite (`data/alignment.py`). Le réentraînement le refait avec les réglages d'aujourd'hui, garde comprise.",
                            "The run predates the leak guard (`data/alignment.py`). The retraining redoes it with today's settings, guard included."),
    "td_g_derived_target_title": _s("Score trop beau malgré la garde anti-fuite", "Score too good despite the leak guard"),
    "td_g_derived_target_why": _s("Une variable dérivée de la cible reproduit le label. Le réentraînement abaisse le seuil de corrélation de la réduction des variables "
                                  "pour retirer ces dérivées.",
                                  "A variable derived from the target reproduces the label. The retraining lowers the correlation threshold of the feature "
                                  "reduction to drop those derivatives."),
    "td_g_manual_title": _s("Score trop beau, cause à chercher", "Score too good, cause to find"),
    "td_g_manual_why": _s("Aucune cause connue à corriger automatiquement. Ouvrir le run pour lire ses diagnostics, ou le refaire à la main depuis le formulaire.",
                          "No known cause to fix automatically. Open the run to read its diagnostics, or redo it by hand from the form."),
    "td_g_macro_title": _s("Cibles macro retirées", "Retired macro targets"),
    "td_g_macro_why": _s("Les séries macro (FRED) ne sont plus des cibles : leurs runs restent lisibles, mais sont exclus des moyennes et ne sont jamais champions. "
                         "Rien à relancer.",
                         "Macro (FRED) series are no longer targets: their runs stay readable, but are excluded from the averages and never champions. "
                         "Nothing to relaunch."),
    # ------------------------------------------------------------------ groupes : champions de change, file
    "td_g_fx_champions_title": _s("Champions de change à remplacer", "Currency champions to replace"),
    "td_g_fx_champions_why": _s("Chaque ligne est un lancement dont un modèle est encore champion d'une paire de devises. Le réentraînement le refait avec les mêmes "
                                "réglages et la règle d'alignement d'aujourd'hui ; le nouveau modèle remplace le champion quand il gagne le duel.",
                                "Each line is a launch whose model is still a champion of a currency pair. The retraining redoes it with the same settings and "
                                "today's alignment rule; the new model replaces the champion when it wins the duel."),
    "td_g_running_title": _s("En cours", "Running"),
    "td_g_running_why": _s("Jobs en cours d'exécution.", "Jobs being executed."),
    "td_g_queued_title": _s("En attente", "Waiting"),
    "td_g_queued_why": _s("Jobs en attente d'un worker, dans l'ordre de la file.", "Jobs waiting for a worker, in queue order."),
    # ------------------------------------------------------------------ navigateur (static/a_faire.js)
    "td_js_working": _s("Mise en file…", "Queuing…"),
    "td_js_none": _s("Cochez au moins une ligne.", "Tick at least one line."),
    "td_js_confirm": _s("Mettre {n} run(s) en file ?\n\n{title}\n{plan}", "Queue {n} run(s)?\n\n{title}\n{plan}"),
    "td_js_launch": _s("Lancer {n} run(s)", "Launch {n} run(s)"),
    "td_js_done": _s("{n} run(s) mis en file. Ils démarrent dès que le worker est libre.", "{n} run(s) queued. They start as soon as the worker is free."),
    "td_js_partial": _s("{n} run(s) mis en file, {e} refusé(s) : {msg}", "{n} run(s) queued, {e} refused: {msg}"),
    "td_js_error": _s("Échec de la mise en file : {msg}", "Queuing failed: {msg}"),
}

TODO_JS_KEYS: tuple[str, ...] = tuple(k for k in TODO_STRINGS if k.startswith(("td_js_", "td_selected")))
