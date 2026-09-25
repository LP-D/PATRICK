# Tâche planifiée créée par un agent (`ScheduleWakeup`) — enquête

Date : 2026-09-25. Statut : **origine non localisable depuis le dépôt ni le cloud ;
à vérifier sur le PC A** (procédure ci-dessous). Garde-fou ajouté.

## Ce qui a été vérifié

| Vérification | Résultat |
|---|---|
| Code du dépôt (`schtasks`, `Register-ScheduledTask`, `crontab`, `launchctl`) | Aucune création. `scripts/schtasks_daily_predict.ps1` et `schtasks_daily_dbbackup.ps1` **affichent** la commande `schtasks /create` à exécuter à la main, ils ne l'exécutent pas. |
| Historique git de ces deux scripts | Écrits par Léon (2026-09-05 → 2026-09-20), inchangés depuis. |
| Routines Claude Code du compte (cloud) | **Aucune** (`list_triggers`, y compris terminées). |

`ScheduleWakeup` n'est pas du code du projet : c'est un outil du harnais
Claude Code (mode `/loop` dynamique), comme `CronCreate` et les Routines.
Une tâche créée par un agent **local** (session Claude Code sur le PC A) est
stockée localement et n'apparaît ni dans le dépôt ni dans les Routines cloud.

## À faire sur le PC A

1. Planificateur Windows :
   `schtasks /query /fo LIST /v | findstr /i "Patrick claude python"` —
   comparer avec les deux seules tâches documentées (`Patrick-DailyPredict`
   22:05, `Patrick-DailyDBBackup` 23:30).
2. Dans une session Claude Code locale sur le dépôt : outil `CronList`
   (tâches cron de session) ; dans l'app de bureau, section des tâches
   planifiées.
3. Pour toute tâche inconnue : noter son créateur/sa date, la supprimer
   (`schtasks /delete /tn <nom> /f` ou `CronDelete`).

## Garde-fou ajouté

`.claude/settings.json` (projet) place en `permissions.ask` :
`CronCreate`, `ScheduleWakeup`, `mcp__Claude_Code_Remote__create_trigger`,
`mcp__Claude_Code_Remote__send_later`. Un agent travaillant dans ce dépôt ne
peut plus créer de tâche récurrente ou différée sans approbation humaine
explicite. Ce n'est pas une interdiction (`/loop` reste utilisable, avec
confirmation). Limite : ne couvre pas une commande shell `schtasks /create`
lancée via Bash — elle reste soumise aux règles de permission Bash normales.
