# Passage de nuit : réveiller le PC, tout exécuter, le remettre en veille

Tâche Windows `Patrick-Nightly` (`patrick/scripts/schtasks_nightly.ps1`), qui lance `patrick/scripts/nightly_run.ps1`.

## Ce qu'elle fait, chaque jour à l'heure choisie (23 h par défaut, depuis le 30/10 ; 23 h 30 avant)

1. réveille le PC (veille ou veille prolongée) et attend le réseau ;
2. met PATRICK à jour (avance rapide sur `stable`, sautée si un entraînement tourne) ;
3. actualités (`patrick news refresh`), **avant** les prédictions : elles durent des heures (le passage
   du 26 au 27/10 avait été coupé à 6 h, en pleines prédictions, et l'étape « actualités » placée après n'avait donc jamais tourné ;
   la limite de durée de la tâche est supprimée depuis le 27/10) ;
4. `scripts/daily_predict.py --funds-only` : seulement les prédictions dont un fonds a besoin (modèles retenus par un pilote
   automatique ou suivis par une règle manuelle ; environ 3 h), puis le **cycle du pilote automatique des fonds** (sélection, règles,
   ordres). Les ~2 000 prédictions de tous les modèles durent une douzaine d'heures : sans ce découpage, la nuit était interrompue
   avant le cycle (aucun cycle des 27, 28 et 29/10) et avant la sauvegarde et la synchro ;
5. sauvegarde de la base (`scripts/backup_db.py`), synchronisation OneDrive (`patrick sync auto`) ;
6. `scripts/daily_predict.py --skip-funds` : les autres prédictions, le jugement des anciennes et la dérive, en dernier ;
7. remet le PC en veille prolongée.

Chaque étape est indépendante : une étape en échec est notée dans `runs\nightly.log` et n'empêche pas les suivantes.

## Ce que Windows peut et ne peut pas faire

| Fin choisie (`-End`) | Le PC se rallume tout seul demain ? |
|---|---|
| `hibernate` (défaut), `sleep` | oui, si les « minuteurs de réveil » sont autorisés dans le plan d'alimentation (le script le vérifie) |
| `shutdown` (éteint complètement) | **non** : une tâche Windows ne peut pas allumer un PC éteint (seule une alarme de réveil du BIOS/UEFI le peut) |
| `none` | le PC reste allumé |

La session Windows doit rester ouverte (la veille prolongée la conserve).

## Sécurités

Le PC n'est remis en veille que si **PATRICK est fermé**, qu'**aucun entraînement ne tourne** et que **personne n'a touché au clavier ni à la
souris depuis 10 minutes** (`-IdleMinutes`). Sinon il reste allumé et le journal le dit. Un passage manqué (PC éteint à l'heure prévue)
part dès que le PC redémarre.

## Installer, tester, retirer (PowerShell, depuis `patrick\scripts`)

```powershell
.\schtasks_nightly.ps1                  # aperçu : n'installe rien, dit si le réveil automatique est autorisé
.\schtasks_nightly.ps1 -Install         # crée la tâche (autre heure : -At 22:45 ; autre fin : -End sleep)
.\nightly_run.ps1 -DryRun               # nuit à blanc : liste les étapes, ne lance rien
Start-ScheduledTask -TaskName Patrick-Nightly   # essai immédiat
.\schtasks_nightly.ps1 -Remove          # supprime la tâche
```

Les tâches `Patrick-DailyPredict` (prédictions seules), `Patrick-DailyDBBackup` et `Patrick-NewsRefresh` font chacune une partie de ces
étapes : inutile de les installer en plus (elles ne gênent pas, tout est idempotent).
