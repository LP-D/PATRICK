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
   avant le cycle (aucun cycle des 27, 28 et 29/10) et avant la sauvegarde et la synchro. Depuis l'ADR 0029, les prédictions des fonds
   comprennent les modèles des indices de volatilité lus par les fonds combinés « volatilité », et le cycle passe en deux temps : les fonds
   qui ne lisent pas d'agent RL, puis le rejeu des agents RL utiles (`rl/live.py`, quelques dizaines de secondes par agent) et les fonds
   combinés « RL » ;
5. sauvegarde de la base (`scripts/backup_db.py`), synchronisation OneDrive (`patrick sync auto`) ;
6. `scripts/daily_predict.py --skip-funds` : les autres prédictions, le jugement des anciennes et la dérive, en dernier ;
7. remet le PC en veille prolongée.

Chaque étape est indépendante : une étape en échec est notée dans `runs\nightly.log` et n'empêche pas les suivantes.

## Disque plein : la nuit s'arrête au lieu d'échouer 3 000 fois (15/11/2026)

Le 15/11/2026, `D:` était pleine (0 Go libre) : `daily_predict.py` a tenté 2 984 prédictions et enregistré 2 985 échecs `[Errno 28] No space left
on device` (« errno 28 » : le code d'erreur Windows/Python pour « plus de place »), sans rien arrêter ni prévenir. Le cache de variables
(`feature_cache`) avait atteint 315 Go pour un plafond de 150 Go : son nettoyage (l'*éviction* : supprimer les fichiers les moins récemment
lus) n'avait lieu qu'à la fin d'un entraînement.

Désormais, dans `daily_predict.py` (donc dans les deux étapes de prédiction de la nuit) :

- **avant la première prédiction, puis toutes les 25**, l'espace libre du disque de la racine de données est mesuré. Sous le **seuil** (5 Go),
  le cache de variables est ramené sous son plafond (`feature_cache_max_gb`, 150 Go) ; **jamais la base** (elle ne se modifie pas pendant
  qu'un worker vit). Si la place manque encore, les prédictions s'arrêtent avec **un seul message** dans `runs\daily_predict.log`
  (espace libre, seuil, ce que l'éviction a retiré, combien de prédictions n'ont pas été tentées) et le script se termine avec le **code de
  sortie 3** (visible dans `runs\nightly.log` : « termine (code 3) ») ; ni cycle du pilote automatique, ni dérive, ni rapport ne suivent
  (ils liraient des signaux périmés). Les étapes suivantes de la nuit (sauvegarde, synchro) restent indépendantes ;
- une erreur « disque plein » sur **une** prédiction arrête aussitôt la boucle (les suivantes échoueraient de même) ; elle n'est pas notée dans
  la base comme un échec du modèle (elle fausserait la suggestion « entrées perdues » du conseiller de relance) ;
- **à la fin de chaque exécution** de `daily_predict.py`, le cache de variables est ramené sous son plafond (une fois par exécution, donc deux
  fois par nuit). Le geste manuel reste `patrick storage evict` (`--feature-cache-gb 100` pour un plafond plus bas ; `--vol-cache-days 0`
  n'évince rien dans la base) ;
- l'écriture d'un instantané du magasin de données (`store/snapshot=…/*.parquet`) passe par un fichier temporaire puis un renommage : un
  disque plein ne laisse plus de fichier coupé sous le nom d'un vrai instantané. Les anciens fichiers coupés (par exemple
  `snapshot=2026-11-14\raw_FCX__a09f723cf153.parquet`, 986 828 octets au lieu d'environ 1,4 Mo, absent de l'index) ne sont pas supprimés
  automatiquement ; le prochain enregistrement du même contenu le remplace.

Le seuil se règle dans le fichier de réglages de la machine (`predict_min_free_gb`, en Go ; `0` désactive la mesure ; une valeur illisible
rend les 5 Go). Même idée que le plancher de 5 Go de la synchronisation entre PC (`FOLDER_MIN_FREE_BYTES`).

Limite connue : seule la racine de données est mesurée. Un composant déplacé ailleurs par une variable d'environnement
(`PATRICK_FEATURE_CACHE_ROOT`, `PATRICK_STORE_ROOT`) sur un autre disque n'est pas surveillé, mais une erreur « disque plein » y arrête
quand même la boucle.

## Une passe de prédictions par jour, pas une par processus (20/11/2026)

Une passe complète (les ~3 000 prédictions live) coûte une douzaine d'heures de processeur : le pool de variables est reconstruit (~15 s par
modèle) même quand aucune nouvelle barre n'est à écrire. L'app (au lancement, puis une fois par jour UTC) et la tâche `daily_predict.py` en
faisaient chacune une : le serveur restait à ~90 % du processeur, la base disputée par deux écrivains (journal : `serve-stable.log`).

Un marqueur partagé, `~/.patrick/live_pass.json` (qui, quand, avec quels chiffres), dit qui a terminé une passe complète ou qui en fait une :

- l'app ne refait pas la passe si une autre, terminée depuis moins de **12 h** ou en cours dans un processus vivant, existe ; la page
  Prédictions montre alors les chiffres de cette passe-là. Le journal du serveur dit `passe live non refaite` ;
- `daily_predict.py` (sans `--funds-only` ni `--skip-funds`) fait de même et affiche `Prédictions non refaites`, **mais le cycle du pilote
  automatique, la dérive, l'AUC regroupée, le rattrapage et le rapport tournent comme d'habitude**. `--force-predictions` les refait quand
  même ;
- une passe interrompue (disque plein, exception, tâche tuée) ne compte pas : le marqueur « en cours » d'un processus mort est ignoré, et
  `finished_at` garde la dernière passe terminée.

Réglage : `PATRICK_LIVE_REFRESH_MIN_GAP_H` (12 par défaut ; `0` = toujours refaire, comme avant). Limite : les deux moitiés
`--funds-only` / `--skip-funds` de la tâche `Patrick-Nightly` ne marquent pas de passe complète ; un PC qui utilise ce découpage garde la passe
de l'app au lancement.

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
