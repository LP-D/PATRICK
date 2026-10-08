# Application de bureau PATRICK

PATRICK s'utilise comme une application : une icône, un double-clic, une fenêtre. Le lanceur
(`python -m patrick.desktop`, code dans `patrick/patrick/desktop/`) se charge de tout le reste.
Mode d'emploi pour l'utilisateur : [`app/LISEZMOI.txt`](../../app/LISEZMOI.txt).

## Ce que fait un double-clic

| Étape | Réglage qui la désactive | Détail |
|---|---|---|
| 1. Mise à jour | `auto_update` | `git fetch` + avance rapide sur `origin/main`, sauvegarde de la base avant, réinstallation des composants seulement si `patrick/pyproject.toml` a changé, retour en arrière si pip échoue. Ignorée si un entraînement tourne, si le dossier n'est pas sur `main` ou a des modifications locales. Si le code a changé, le lanceur se relance avec le nouveau code. |
| 2. Assistant | — (une seule fois) | Si aucun choix n'a été fait (`setup_done`) et qu'aucun dossier n'est réglé : fenêtre « Où sont tes données partagées ? » (dossier OneDrive détecté / Parcourir / ce PC seul / plus tard). Une installation déjà réglée n'est pas interrogée. |
| 3. Fusion | `sync_on_start`, ou aucun dossier | `patrick sync auto --only pull` (serveur fermé, voir [partage entre PC](partage-entre-pc.md)). Une erreur n'empêche jamais l'ouverture. |
| 4. Serveur | — | `python -m patrick.cli serve --port <port>` sans console; attend qu'il réponde (120 s max). |
| 5. Fenêtre | `app_window` | Chrome ou Edge en « mode application » (`--app`, profil dédié `~/.patrick/app-profile-stable`); sinon navigateur par défaut (le serveur reste alors actif jusqu'à « Arrêter PATRICK »). |
| 6. Fermeture | `sync_on_close` | Fenêtre fermée (3 contrôles vides de 3 s) : le serveur s'arrête, puis `patrick sync auto --only push` part en arrière-plan. Un entraînement lancé continue. |

Un deuxième double-clic ouvre seulement une fenêtre de plus (verrou `~/.patrick/launcher.lock`).

## Réglages (`/reglages`, engrenage en haut à droite)

Tout est enregistré dans `~/.patrick/settings.json` (même fichier que les réglages de performance) :

| Clé | Défaut | Effet |
|---|---|---|
| `sync_folder` | absente | dossier partagé; absente = ce PC travaille seul |
| `sync_wealth_reference` | `false` | ce PC est la référence du patrimoine (voir partage entre PC) |
| `setup_done` | `false` | l'assistant a été traité |
| `auto_update` | `true` | cherche une nouvelle version à chaque démarrage |
| `sync_on_start` / `sync_on_close` | `true` | fusion au démarrage / publication à la fermeture |
| `app_window` | `true` | fenêtre dédiée plutôt que le navigateur par défaut |
| `port` | `8000` | port local du serveur (effet au prochain démarrage) |

Changer ou retirer le dossier partagé ne touche jamais au dossier lui-même; l'état d'échange
(`sync_state.json`) est oublié, et la tâche planifiée `PATRICK-Sync` supprimée quand on choisit « ne plus partager ».
Les boutons « Synchroniser maintenant » et « Mettre à jour maintenant » lancent un assistant détaché
(`python -m patrick.desktop relaunch`) : il arrête le serveur, met à jour / fusionne, relance le serveur, et la page
(qui reste ouverte) se recharge toute seule. Refusé tant qu'un entraînement tourne.

Sécurité : les routes `/api/app/*` refusent toute requête dont l'`Host` n'est pas local ou dont l'`Origin` /
`Sec-Fetch-Site` désigne un autre site (une page web ouverte dans le navigateur ne peut pas les piloter).

## Installer sur un autre PC

`app\Installer.bat` (ou `irm …/app/Installer.ps1 | iex`, voir le README) : installe Git et Python via winget si
besoin, clone le dépôt dans `%USERPROFILE%\PATRICK-stable`, crée `patrick\.venv`, installe les composants,
crée les raccourcis et la sauvegarde quotidienne (`PATRICK-SauvegardeBase`, 23h30), puis ouvre PATRICK.
Relançable sans risque. Les données (`~/.patrick`) ne sont jamais touchées.

Sur le 2e PC, choisir le **même** dossier OneDrive que sur le premier et **ne pas** cocher « référence du
patrimoine » : il adopte le patrimoine publié par le PC de référence.

## Fichiers et journaux

| Fichier (`~/.patrick/`) | Contenu |
|---|---|
| `logs/launcher.log` | mises à jour, assistant, fermeture |
| `logs/serve-stable.log(.err)` | sortie du serveur |
| `logs/sync.log` | synchronisations (démarrage, fermeture, tâche horaire) |
| `logs/relaunch.log`, `relaunch.json` | relance demandée depuis Réglages (journal, avancement) |
| `last_launch.json` | résultat de la dernière mise à jour / fusion au démarrage (affiché dans Réglages) |
| `update_state.json` | dernière vérification et dernière mise à jour |

## Développement

- Le lanceur n'importe que la bibliothèque standard, `psutil` et `patrick.settings/sync` : `import patrick` ne charge
  plus pandas (`patrick/__init__.py` charge les ré-exports de `phase9` à la demande), ce qui garde le démarrage rapide.
- Tests : `tests/test_desktop_*.py`, `tests/test_settings_routes.py`, `tests/test_package_lazy_import.py`.
  La fixture `fake_task` (conftest) remplace la tâche planifiée Windows : un test ne doit jamais toucher la vraie.
- Essai à blanc d'un lanceur complet sans toucher à ses vraies données : définir `PATRICK_SETTINGS_PATH`,
  `PATRICK_DB_PATH`, `PATRICK_STORE_ROOT` et `PATRICK_CACHE_ROOT` vers un dossier temporaire, puis
  `python -m patrick.desktop launch --no-update`.
