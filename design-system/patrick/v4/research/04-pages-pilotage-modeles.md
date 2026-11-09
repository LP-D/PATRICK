# 04 — Pages « Pilotage » et « Modèles » : cartographie de l'existant

> Lecture seule de `feat/design-v4` (= `main` @ `da5cdea`), 08/11/2026. Chemins relatifs à `patrick/patrick/webapp/` ; tests dans `patrick/tests/`. Constats vérifiables au fichier:ligne ; « Piste » = proposition. Coque, jetons, CSS : rapports `01` à `03`.

## 1. Périmètre et aiguillage

Registre `nav_registry.py:71-99`. **Pilotage** = 15 entrées (Synthèse + dossiers `suivi`, `signaux`, `recherche`, `donnees`, `:63-67`) ; **Modèles** = 3 feuilles (`:97-99`). Les enfants (`child_routes`) sont les lignes ↳ et routes secondaires du tableau. La fiche cible `/targets/{ticker}` dépend d'Univers (`:101-102`) mais tout le périmètre y renvoie (§5).

Modes : **S** serveur · **L** serveur + `lazy_block` (`_components.html:187-195` → `static/lazy.js`) · **K** coquille remplie par `analysis_kit.js` (`window.PK`, `analysis_kit.js:443-450`) depuis `/api/<page>/*` · **F** formulaire piloté par JS.

| Entrée | Route → gabarit (+ partiels) | Mode | Densité max |
|---|---|---|---|
| Synthèse | `/` (`app.py:665`) → `synthesis.html` + `_home_details.html` (`/fragments/home`, `:744`) | L | 9 KPI, 6 tableaux, 11 cartes |
| ↳ À faire | `/a-faire/{key}` (`app.py:706`) → `todo.html` | S | 6 KPI, 1 tableau par cause |
| Historique | `/runs` (`app.py:1209`) → `runs.html` ; `?vue=analyses` → `_runs_analyses.html` ; `/runs/{id}/panel` (`:1530`) → `_run_panel` / `_rl_run_panel` | S (+K) | 1 tableau par famille (14 ou 13 col.) |
| ↳ Run | `/runs/{id}` (`app.py:1120`) : job RL → 303 `/rl?open=` ; job web → `ml.html`/`dl.html` ; sinon `run_detail.html` (`:1149-1171`) | — | — |
| ↳ Détail | `/runs/{id}/detail` (`app.py:2478`) → `run_detail.html` + `_run_tabs`, `_retrain_advice` (`:2540`), `_run_meta_labeling` (`:2554`) | L | ~18 KPI, 10 cartes, 9 `data_table` + plis |
| ↳ Analyse | `/runs/{id}/analyse` (`analysis_routes.py:131`) → `run_analysis.html` | K | ML : 19 `PK.kpi`, 23 `PK.table`, 20 `PK.plot` |
| ↳ Comparaisons | `/compare-runs` (`app.py:1420`) → `compare_runs.html` / `compare_rl.html` ; `/analyses/comparer` (`analysis_routes.py:225`) → `analyses_compare.html` ; `_compare_tabs` | S / K | 1 tableau ; 3 graphiques + 3 tableaux |
| Registre | `/modeles`, `/modeles/fiche` (`analysis_routes.py:363,367`) → `modeles.html` | K | 4 KPI ; 5 KPI (fiche) |
| Garde-fous, Dérive, Journal, Variables, Carnet | `/garde-fous`, `/derive`, `/journal`, `/variables`, `/carnet` (`analysis_routes.py:256,409,329,433,299`) | K | 3 à 5 KPI |
| Prédictions | `/predictions` (`app.py:1966`) → `predictions.html` + `_predictions_body` (`:2055`), `_pred_cell` | L | 1 matrice par groupe |
| Séries & modèles | `/analysis` (`app.py:1661`) → `analysis.html` | S | 5 KPI, 10 tableaux |
| Exploration / Économétrie | `/exploration` (`exploration_routes.py:218`), `/econometrie` (`econometrics_routes.py:306`) | F | 8 / 6 onglets |
| News / Résultats | `/news` (`news_routes.py:77`) + 4 `_news_*` ; `/resultats`, `/resultats/titre/{symbol}`, `/resultats/evenement` (`earnings_routes.py:118,351,366`) + 7 `_earn_*` | L | 5 KPI ; 3 KPI + 54 cartes |
| Données | `/donnees` (`data_routes.py:55`), `/data-quality` (`app.py:1618`) | K / S | 6 panneaux ; 5 KPI |
| ML / DL | `/ml`, `/dl` (`app.py:650,658`) → `ml.html`/`dl.html` ⊂ `launch_base.html` + `_batch_gallery`, `_profile_gallery`, `_machine_card`, `_run_controls`, `_launch_macros` | F + L | 12 accordéons |
| RL | `/rl` (`rl_routes.py:218`) → `rl.html` ⊂ `base_v2.html` | F + L | 6 accordéons |

## 2. Constats transverses

### 2.1 Squelette commun
- `base_v2.html` n'expose que 4 blocs : `title` (`:16`), `crumb_trail` (`:176`), `session_context` (`:204`), `content` (`:205`). Sans bloc `head`/`scripts`, 10 gabarits du périmètre posent `<link … analysis.css>` dans le corps (ex. `modeles.html:7`) et leurs `<script>` en fin de `content`.
- Patron partout : `h1.page-title` → `p.page-subtitle` → `.metric-grid` (`minmax(210px, 1fr)`, `static/patrick.css:669-674`) → `section.card` empilées (rayon 20 px, padding 22/24, `:725-736`), colonne de 1480 px (`:182`). Grilles internes : `.home-trio`, `.an-grid`, `.station-grid` seulement.
- `help.js` replie derrière un « ? » tout texte statique de plus de 120 caractères (`static/help.js:17-18,27`), sauf `data-keep` et éléments à `id`/`role`/`aria-live`. `table_tools.js` greffe tri, filtre et CSV à tout `table.data-table` ≥ 8 lignes (`static/table_tools.js:6,29-31`), libellés écrits dans le script (`:8-10`).

### 2.2 Composants en double
| Besoin | Variantes en service |
|---|---|
| Onglets | `.kind-tabs > a.kind-tab` (pilules-liens qui rechargent : `runs.html:12,24,36`, `predictions.html:14`) · `.run-tabs` soulignés (`_run_tabs.html`, `_compare_tabs.html`, `patrick.css:2770-2773`) · `.exp-tabs [role=tab]` (`exploration.html:81`, `econometrics.html:83`) · `PK.segmented` (`static/donnees.js:39`) · `.section-index` collant numéroté (`patrick.css:1909-1943`) |
| Panneau | `.card` (20 px) vs `.dash-panel` (14 px, fond plat, `patrick.css:1363-1370`), réservé à ML/DL/RL |
| Tableau | macro `.table-scroll > .data-table` · `data-table ra-sortable` fait main, tri et pagination propres (`static/guardrails.js:110-141`, `drift_monitor.js:60`, `model_registry.js:69`) · `.table-wrap` (5 partiels Résultats, sans CSS) · `table.leaderboard` + `style="overflow-x:auto"` (`static/app.js:480-481`) · `.history-table` à colonnes fixes (`patrick.css:2234-2244`) |
| Graphique | canvas `chart_kit.js` via `charts.js` (Exploration, Économétrie, RL) et `market.js` · SVG `PK.plot` (`analysis_kit.js:185-214`, info-bulle, plage, PNG ; ni zoom, ni périodes, ni axe à droite) · SVG serveur (`earnings_render.py:63-136`) · SVG à la main (`static/predictions_pop.js:31`). « Un seul moteur » (`MASTER.md:84`) : faux ici |
| Aide | `help_icon` « ? » (`_components.html:17`) · `info` « i » (`_launch_macros.html:10`) · « i » à la main (`synthesis.html:110`, `_home_details.html:8`, `run_detail.html:283`, `target.html:157`) · `q()` défini deux fois (`predictions.html:6`, `_pred_cell.html:6`) · « ? » de `help.js` |
| État vide | `empty_state` + lien d'action (`_components.html:144-151`) · carte à la main (`runs.html:300-306`) · `p.hint` (`todo.html:26`, `_components.html:85`) · `PK.empty` · bannière (`_earn_title.html:5`) |
| Bouton | `primary`/`.btn` · `.btn-secondary` · `.btn-ghost` · `.queue-action` (7 px, `patrick.css:1512-1516`) · `button` sans classe (8 px, `:1033-1039` : `runs.html:103`, `data_quality.html:13`, `launch_base.html:512`) · `.btn-primary` absente du CSS (`_earn_confirm.html:33`) ; `analysis.css` écrit 6-8 px en dur (`:38-64`) |

Probable (à vérifier à l'écran) : les tableaux `ra-sortable` émettent `patrick:content` (`guardrails.js:143`, `model_registry.js:79`) et `table_tools.js` ne les exclut pas (`:29`) : au-delà de 8 lignes, second filtre, second tri (`guardrails.js:123`) et CSV s'ajoutent aux filtres `PK`.

### 2.3 « Un seul bouton principal par page » (`MASTER.md:73`) non tenu
- `/runs` : 3 `primary` (`runs.html:138,156,289`) ; `/resultats` : 6 `.btn` (`earnings.html:27,60,83,84,99,108`) + un `.btn earn-run` par carte (`_earn_library.html:31`) × 54 études (`@study`) ; `/econometrie` : 2 (`econometrics.html:76,251`) ; `/news` : 2 (`news.html:24,53`) ; `/a-faire/{key}` : un par groupe (`todo.html:74`) ; `/targets/{t}` : `.btn` (`target.html:16`) + un `primary` par run (`:133`) + SHAP (`:166`).
- À l'inverse `/runs/{id}/analyse` n'a aucune action principale et jusqu'à 5 `btn-secondary` (`run_analysis.html:28-37`).

### 2.4 Trois noms pour une même page
Fil = libellé du registre (`base_v2.html:171-176`) ; h1 et `<title>` = autres clés i18n.

- Historique → `<title>` « Historique des runs » (clé `rl_title`, `runs.html:3`) ; Garde-fous → h1 « Garde-fous : budget d'exploration et holdout » ; Dérive → « Moniteur de dérive des modèles » ; Journal → « Journal de prédictions » ; Séries & modèles → « Séries, features et modèles » (`analysis.html:9`) ; Variables (EN *Features*) → « Explorateur de variables » ; News → « News et sentiment » ; Carnet → « Carnet de recherche » ; Données → « Explorateur de données » ; Résultats (EN *Earnings*) → « Événements de résultats ».
- Comparaison : maillon « Comparaison », h1 « Comparer les runs », `<title>` « Comparaison de runs » ; vue sœur : maillon « Comparer », h1 « Comparaison détaillée de runs ». Détail : maillon = id tronqué, h1 = nom de config, `<title>` « run <id> » (`run_detail.html:3,16,20`). `/runs/{id}` d'un job web : fil « Historique », h1 « Machine learning » (`ml.html:4`).

### 2.5 Données affichées hors charte
- **Statuts bruts anglais** (`done`, `failed`, `running`, `queued`, `stopped`) : `runs.html:84,187,238`, `_home_details.html:79`, `run_detail.html:24`, `run_analysis.html:25`, `_run_panel.html:18`, `_rl_run_panel.html:32` (sans `status_label`), `compare_runs.html:24`, `launch_base.html:563`, `target.html:138`. `status_label` ne traduit rien (`patrick/tracking/db.py:962-967`) ; des tests attendent `stopped` dans la ligne et le panneau (`test_history_light.py:159,171`).
- **Symboles au lieu des noms** (`MASTER.md:156`) : `todo.html:53`, `analysis.html:88` (jusqu'à 400 étiquettes), `data_quality.html:38,57`, `news.html:37`, `earnings_title.html:3,7`, `earnings_event.html:3,6`.
- **Textes en dur ou codes** : « j » (`analysis.html:42,111`), « h=…d » (`static/app.js:448`), horizons sans unité (`launch_base.html:116`), `snapshot/config/git/seed` (`run_detail.html:9-12`), `F1_dir`, `MCC_4cls`, `Sampler` (`run_detail.html:218,232,274`), « obs., min 10 » (`_home_details.html:61-62`), « Runs » (`target.html:91,128`), familles, algos et paramètres Optuna bruts (`launch_base.html:196,395,462-470`), « Chargement… » (`static/runs_panel.js:20`), id de run en lien (`analysis.html:109`), 54 études en français seul (`_earn_library.html:9-15`, `patrick/earnings/studies/base.py:81-86`).
- **Couleurs de sens détournées** (`MASTER.md:25`) : marché fermé en rouge (`_pred_cell.html:34`) ; ton « colombe » en vert (`_news_central.html:9` → `.exp-chip-ok` = `--pos`, `patrick.css:2726`) ; badge « alpha » en `--pos` (`:2467`) ; `kind-alpha`/`kind-directional` pour « meilleur »/« indisponible » (`_retrain_advice.html:22-23`) ; séries RL en `--brand/--warn/--pos` (`:2485`) ; `--ra-c1..8` littéraux aux teintes des jetons de sens (`analysis.css:3-14`).

### 2.6 Navigation et liens
- `/runs/{id}` d'un job web affiche la page Machine learning sous un fil et une barre latérale qui allument « Historique » (`app.py:1151-1154`, préfixe `nav_registry.py:183`).
- **Lien mort** : l'onglet « Détail » (`_run_tabs.html:3`) vise `/runs/{id}/detail` aussi sur l'analyse d'un run RL ; la route lit la table `run` (`patrick/tracking/history.py:450-452`) où un run RL n'existe jamais (`app.py:1339`) → 404.
- L'onglet « Comparer » mène à `/runs?compare=<id>` ; la case n'est cochée que si la ligne est rendue (`static/runs_panel.js:113-123`), or la vue « Tous » n'en montre que 12 par famille (`app.py:1206,1271`).
- Enfants sans maillon de fil : `data_quality.html`, `earnings_title.html`, `earnings_event.html` (retour par lien dans le corps, ex. `earnings_title.html:8`). Le fil du détail et de l'analyse passe par la fiche cible, d'une autre catégorie (`run_detail.html:16`, `run_analysis.html:15`).

### 2.7 Différé, erreurs, rafraîchissement
- **Bug d'état d'erreur** : `lazy_block` range le libellé d'*attente* dans `data-label-error` (`_components.html:188,190`) et tous les appels passent `t('sb_loading')` ou `t('batch_loading')` : l'échec affiche « Chargement… » + « Réessayer » (`static/lazy.js:22-25`).
- Latences notées : `/fragments/home` ~6 s (`app.py:746`), `/fragments/predictions` ~3 s (`:1969-1971`), méta-étiquetage 2-4 s (`:2497`), vues d'analyse 1-5 s, cache 60 s (`analysis_routes.py:45-47`). Interrogations : file 4 s (`static/machine.js:20`), run 1,5 s (`app.js:304`), RL 2-4 s (`rl.js:188,192`), notifications 15/60 s (`run_notify.js:8`).
- **Colonne phare masquée** (Historique ML/DL) : panneau ouvert → colonnes 8-9 = **F1 et Écart** cachées (`patrick.css:2260-2262`, `runs.html:219-220`) ; ≤ 1180 px → colonne 9 ; ≤ 960 px → colonne 8 (`:2301-2309`). Colonne Cible de 76 px avec ellipse (`:2235-2242`) pour des noms comme « Indice · S&P 500 » (à vérifier).

## 3. Fiches — Pilotage

### 3.1 Synthèse `/` (`app.py:665-703`)
- **Structure** : h1, sous-titre avec lien « Machine learning → » (`synthesis.html:14-15`) ; carte « À faire », un `btn-secondary` par ligne (`:18-27`) ; « Premier lancement » sans run terminé (`:30-39`) ; 6 à 9 KPI (`:42-63`) ; bannière suspects (`:65-67`) ; `.home-trio` de 3 cartes-questions (`:70-93`) ; classes (`:96-104`) ; fragment (`:107`) ; régime HMM via `market_state.js` (`:109-116`).
- **Fragment** (mémoïsé, `app.py:750`) : 4 cartes-tableaux repliées à 5 lignes (`_home_details.html:7-85`). **Vides** : `empty_state` vers `/ml?profile=robust|quick` (`:10,51`), message simple sinon (`:44,83`).
- **UX** : pas de grille ; KPI hétérogènes (comptes, médianes, date) ; régime en dernier, après 6 s de fragment ; cellules « n · P · R · F1 ». **Piste** : grille 12 colonnes : bandeau KPI ; alertes + qualité à gauche, signaux au centre, régime + derniers runs à droite.

### 3.2 À faire `/a-faire/{key}` (`app.py:706-720`)
- 4 clés (`todo_actions.py:29`). 1 à 6 KPI (`todo.html:14-23`) ; une `section.card.td-group` par cause : badges, explication, plan, tableau à cases, barre Tout/Rien/Lancer (`:29-79`) ; mise en file par `a_faire.js` après `patrickDialog.confirm` (`static/a_faire.js:46`). **Vide** : `p.hint` (`:26`).
- **UX** : un `primary` par groupe ; cibles et horizons bruts (`:53-54`). **Piste** : causes à gauche, détail à droite, une action « Mettre en file (n) » en en-tête.

### 3.3 Historique `/runs` (`app.py:1209-1335`)
- **Liste** : 3 rangées de pastilles (`runs.html:12-40`), 1-2 `scope-line` (`:51-63`), filtres (5 + 4 repliés, `:65-122`), « runs vides » (`:125-132`), comparaison (`:137-140`), une section par famille (12 lignes, ou 50 par page, `app.py:1205-1206`), tableau ML/DL 14 colonnes (`:209-259`) ou RL 13 (`:159-207`), pagination (`:264-272`), renommage (`:283-292`). **Vides** : carte à la main (`:300-306`), `p.hint` par famille (`:150-152`).
- **Panneau** : clic ou Entrée sur une ligne → jusqu'à 3 fragments empilés (`static/runs_panel.js:7`) dans un `aside` fixe de 360 px (`patrick.css:2270-2295`) : AUC/F1, 11 champs, plis, 2 liens (`_run_panel.html`) ; RL : stratégie contre références (`_rl_run_panel.html:15-29`). Vue Analyses : 3 cartes (`_runs_analyses.html:11-27`).
- **UX** : jusqu'à 6 rangées d'en-tête avant la première ligne ; 3 `primary` ; icônes de 28 px (`patrick.css:2258`) ; F1 masqué (§2.7). **Piste** : maître-détail natif, une ligne de filtres à puces, barre « Comparer (n) » à la sélection, clavier ↑ ↓ ↵.

### 3.4 Détail d'un run `/runs/{id}/detail` (`app.py:2478-2511`)
- **Cadre** : bandeau `session_context` (`run_detail.html:5-14`) ; onglets **avant** le h1 (`:18`) ; h1 = nom de config (`:20`) ; 3 actions non regroupées : « Relancer » (`primary btn-arrow`), Dupliquer, Analyse (`:27-31`) ; AUC/F1 test et holdout (`:40`) ; index de 7 ancres (`:47-56`).
- **Sections** : Résumé, 10 à 12 KPI (`:61-158`) ; classes (`:164-186`) ; conseil (fragment, `:190`) ; plis (`:192-203`) ; KPI du lancement, 4 tableaux (`:207-249`) ; durées et criblage (`:251-277`) ; conformal 4 KPI + méta-étiquetage 2 KPI (fragment, `:281-298`) ; Phase 6 (`:300-324`) ; essais et baselines (`:326-354`) ; config JSON (`:362`). **Vides** : KPI « — » en `disabled` avec raison (`:98,106,115,123,131,150`), `empty_state` conformal (`:286`).
- **UX** : `#repartition`, `#conforme` et Phase 6 (sans `id`) absents de l'index ; l'ancre « Conseil » vise un bloc vide sans suggestion (`_retrain_advice.html:6`) ; deux `h2` dans la carte Essais (`:327,347`) ; baselines en `clé=valeur` (`:350`). **Piste** : en-tête d'identité figé (nom, cible, statut, une action + menu), index vertical collant, KPI en tableau valeur | fiabilité, config dans un tiroir.

### 3.5 Analyse d'un run `/runs/{id}/analyse`
- Même contexte, fil et onglets ; 3 à 5 `btn-secondary` (`run_analysis.html:28-37`) ; une `section.card.ra-section` à squelette par section (`:45-53`) : 17 ML (+ `paths` en CPCV, `analysis_routes.py:40-41,100-101`) ou 7 RL (`patrick/analysis/rl_sections.py:21`), chargées à l'approche (`static/analysis_loader.js:91`).
- **Piste** : panneaux 2 colonnes (graphique | chiffres), sommaire latéral, exports dans un menu.

### 3.6 Comparaisons
- `/compare-runs` ML/DL (2 à 4 runs, `app.py:1423-1424`) : onglets (`compare_runs.html:9`), bannières de mélange (`:11,13`), tableau hors carte, chiffres sans `num pk-mono` (`:25-29`), meilleur non signalé. RL : courbes (`compare_rl.html:14-23`), tableau `cmp-diff`/`best` (`:25-43`), sans onglets.
- `/analyses/comparer` : contrôles + 5 cartes JS (`analyses_compare.html:12-20`) ; runs RL refusés (404, `analysis_routes.py:236`).
- **Piste** : une page à colonnes figées (mesure | runs), meilleur et écarts surlignés, graphiques au-dessus.

### 3.7 Registre `/modeles` (+ `/modeles/fiche`)
- Liste : 4 KPI (`static/model_registry.js:32-35`), filtres, tableau `ra-sortable` paginé par 50 (`:17,69-76`), cible → fiche (`:19`). Fiche, autre URL : 5 KPI (`:97-101`), versions avec « Promouvoir » ou « actuelle » (`:125-129`), archive (`:136`).
- **Piste** : maître-détail (cible × horizon à gauche, fiche à droite) au lieu de deux URL.

### 3.8 Garde-fous, Dérive, Journal, Variables, Carnet
- Garde-fous : 3 ancres (`garde_fous.html:9-12`), 5 KPI (`guardrails.js:20-24`), budget (graphique), paires (nuage + filtres + tableau paginé, `:110-141`), lectures du holdout (`:153`). Dérive : 4 KPI (`drift_monitor.js:12-17`), tableau, détail caché ouvert au clic (`derive.html:18-21`) avec « Mesurer » et 3 graphiques (`drift_monitor.js:82-127`).
- Journal : 5 KPI, « Vérifier » (`primary`), « Sceller », CSV (`journal.js:13-22`). Variables : 4 KPI, chaleur cibles × familles, détail sous la liste (`variables.js:18-21,33,80`). Carnet : 3 KPI, formulaire (`primary`, `carnet.js:53`), liste. **Vides** : `PK.empty`. Pagination recopiée (`guardrails.js:136-141`, `drift_monitor.js:64`, `model_registry.js:71-76`).
- **Piste** : un patron unique « KPI + liste filtrable + volet de détail » pour ces pages et le Registre.

### 3.9 Prédictions `/predictions`
- **Cadre** : h1 portant 2 `help_icon` (`predictions.html:10-13`) ; onglets, compteur sur Alpha seulement (`:14-17`) ; sous-titre **après** les onglets (`:19`) ; actualisation (`:21-27`) ; légende 4 badges + 1 « ? » (`:29-39`) ; fragment (`:41`).
- **Fragment** : couverture (`_predictions_body.html:11-15`) ; par groupe, `h2.group-title` hors carte et tableau actif × horizons (`:22-45`) ; en Alpha l'actif n'est pas un lien (`:34`). Cellule = badge à flèches + bulle au survol de 9 rubriques `<dt>` (`_pred_cell.html:9-124`). **Vide** : `empty_state` (`:17-20`).
- **UX** : tout le détail dépend du survol, sans sélection persistante. **Piste** : matrice compacte colorée, clic = volet de détail, en-têtes de groupe collants.

### 3.10 Séries & modèles `/analysis`
- 5 KPI (`analysis.html:12-18`) ; index de 4 liens pour 5 sections (`#liste` absente, `:24-28,105`) ; 6 mini-tableaux en `.an-grid` (`:33-48`) ; top 30 et moins utilisées (`:51-74`) ; jusqu'à 400 étiquettes repliées (`:88`) ; barres de familles (`style=` toléré, `test_ui_shell.py:102-107`) ; liste des modèles « ★ » (`:105-115`).
- **Piste** : mini-tableaux en grille 3 × 2 dense, liste des modèles en tableau principal à volet.

### 3.11 Exploration et Économétrie
- Patron `exp-*` : carte de sélection (liste multiple de 11 lignes, préréglages, puces, période, fréquence, transformation, `primary` — `exploration.html:19-79`), 8 onglets ARIA (`:81-90`) ; panneau = `exp-params` + « Appliquer » (`queue-action`) + `exp-out`. Économétrie : une série (liste de 9 lignes, `econometrics.html:38`), 6 onglets (`:83-90`), prévision lente (`:225-255`).
- **UX** : deux niveaux de commande (« Lancer » puis « Appliquer ») ; tout est vide avant le premier lancement. **Piste** : sélection persistante à gauche, paramètres en barre d'outils au-dessus de chaque sortie.

### 3.12 News, Résultats
- News : sous-titre en `p.hint` (`news.html:11`) ; 5 KPI (`:13-19`) ; fenêtre en liens + `.btn` Actualiser (`:21-26`) ; 5 cartes dont 3 fragments et une étude au clic (`:28-63`). **Vide** : `empty_state` (`_news_central.html:5`). **Piste** : fil défilant en colonne étroite, sentiment au centre.
- Résultats : 3 KPI, collage + date, lots, lot courant (fragments), instantané, 11 réglages, 54 cartes d'études repliées, registre FDR au clic (`earnings.html:13-115`). Fiches titre / événement : h1 au symbole, KPI hors macro `metric` (`_earn_title.html:7-15`), SVG serveur. **Piste** : séparer le flux (coller → confirmer → semaine) de la bibliothèque (liste | résultat).

### 3.13 Données `/donnees` et Qualité `/data-quality`
- Données : lien vers Qualité dans le corps (`donnees.html:8`), 6 panneaux commutés par `PK.segmented` (`:11-18`, `static/donnees.js:37-39`).
- Qualité : seuil (bouton sans classe, `data_quality.html:13`), 5 KPI (`:18-22`), 4 cartes (`:25,44,72,94`). **Piste** : une page à onglets, Qualité en onglet.

## 4. Fiches — Modèles

### 4.1 Socle ML/DL — `launch_base.html` (`app.py:470-506, 599-662`)
- Grille `.station-grid` 1,35fr / 1fr (`patrick.css:1352-1361`).
- **Gauche** `dash-panel dash-settings` : erreurs (`:27-30`) ; lots prêts (fragment : cartes par classe, « horizons jamais lancés », « runs conseillés » en ML, `_launch_batches.html:4-30`) ; profils repliés ; `#run-form[data-mode]` : simple/expert, profils personnels (`:44-66`), objectif (cibles et horizons en listes multiples de 8 lignes, type, benchmark, budget, seuil, régimes — `:75-134`), 12 `details.adv` (`:136-515`, bornes Optuna `:452-480`) ; barre collante récapitulatif + `primary btn-arrow` (`:523-528`).
- **Droite** `.station-side` : Avancement (titre basculant, derniers runs, progression, pause/arrêt, étapes, journal brut, résultats — `:542-592`) ; File (`_machine_card.html`) ; Aperçu marché (`:596-618`). Résultats : `table.leaderboard` aux en-têtes bruts (`static/app.js:444-487`). Pas de bandeau d'aide statistique (`base_v2.html:234`). **Vide** : `#no-run-message` (`:551`).
- **UX** : réglage machine au milieu du formulaire (`:497-515`, bouton sans classe, script en ligne `:629-653`) ; 3 styles de boutons dans un panneau. **DL** : bannière et bouton désactivé sans torch (`dl.html:8-10`) ; `sec_models` = réseaux + `section_deep_{arch,train,compute}` + extra (`dl.html:15-66`).
- **Piste** : formulaire en colonnes (Cible / Méthode / Calcul) au lieu de 12 accordéons, récapitulatif façon ticket d'ordre toujours visible, file et run actif en barre d'état basse.

### 4.2 RL `/rl` — `rl.html` (`rl_routes.py:205-242`)
- N'étend pas `launch_base.html` : galerie de profils recopiée (`rl.html:56-72`) ; agent (`:111-147`) + 6 sections `rl_<groupe>` (`rl_routes.py:51-60`) aux champs masqués selon l'algorithme (`data-algos`, `data-actions`) ; lancement sans `btn-arrow` (`:188`) ; à droite Avancement, File, Résultats (caché), Runs RL, 3 sections de classe `dash-progress` (`:197-226`) ; pas d'aperçu marché.
- **Piste** : même gabarit que ML/DL : trois pages Modèles identiques à la grammaire près.

## 5. Fiche cible `/targets/{ticker}` (enfant d'Univers)
- `target.html`, `app.py:2395-2445`. h1 = nom (`:8`) ; jusqu'à 5 actions (`.btn`, `btn-secondary`, `btn-ghost`, `:15-21`) ; 6 ancres (`:23-31`) ; `asset_panel` ; contexte, signaux et actualités (fragments, `:51,56`), fonds, voisins ; `h2` « Entraînements » hors carte (`:80`) ; 3 KPI, PBO, runs (14 colonnes, un `primary` par ligne, `:127-154`), SHAP, PSI, alpha, phases (`:156-232`). **Vide** : `empty_state` (`:84`). **UX** : l'index ignore 6 sections ; N boutons principaux.

## 6. Contrat à ne pas casser (noms exacts)
- **Blocs** : `title`, `crumb_trail`, `session_context`, `content` ; `launch_base.html` : `page_head`, `sec_sampler`, `sec_models`, `sec_tuning`, `sec_optuna_bounds`.
- **Macros** : `metric(label, value, reliability, state)`, `data_table(headers, rows, empty_message, row_classes, num_cols, footer, collapse_after, more_label, less_label)`, `lazy_block(url, lines, label, retry)`, `crumb`, `status_badge`, `empty_state`, `help_icon`, `fold_metrics_table`, `headline_metrics`, `up_down`, `asset_panel`, `pred_cell`, `q`, `info`. API `window.PK` (`analysis_kit.js:443-450`) qui produit `metric ra-kpi`, `data-table`, `table-scroll`, `ra-heat`, `ra-seg`, `range-btn`, `ra-empty`.
- **Identifiants lus par le JS** (notation `a-{x,y}` = `a-x`, `a-y`) — ML/DL : `run-form`, `launch-{btn,recap}`, `target_symbols`, `horizons`, `target_kind`, `benchmark-field`, `trial-budget`, `run-errors(-list)`, `settings-mode-{toggle,hint}`, `launch-profile-{name,list,status}`, `{save,load,delete}-launch-profile`, `selection-method-info`, `run-name-{preview,line}`, `target-greyed-note`, `progress-{title,fill}`, `no-run-message`, `recent-runs`, `status-{panel,line}`, `steps-list`, `log-tail`, `results-panel`, `leaderboard-table`, `preview-{chart,ranges,status}`, `news-list`, `batch-{gallery,status}`, `machine-{card,idle}`, `queue-{panel,toggle,summary,list}`, `clear-queue-btn`, `run-controls`, `{pause,stop}-run-btn`, `run-control-error`, `setting-*`. RL : `rl-root[data-initial-run]`, `rl-{form,targets,algo,action-space,launch,recap,idle,status-panel,run-name,progress-fill,status-line,log,runs,initial-runs}`, `rl-errors(-list)`, `rl-results(-panel)`, `rl-profile-*`. Historique : `run-panel(-body/-close)`, `rename-{dialog,form,input,cancel}`, `compare-{runs,rl}-form`, `compare-runs-{submit,count}`, `.history-row[data-run-id]`, `.history-table tbody`, `.compare-run-checkbox`, `form.compare-run-actions`, `[data-rename]`, `[data-rp-remove]`, `body.has-run-panel`. Coquilles : `#ra-root[data-run-id][data-kind]`, `[data-ra-mount]`, `#ac-root[data-run-ids]`, `#am-card[data-target][data-horizon]`, préfixes `#ah-` `#am-` `#ag-` `#ad-` `#aj-` `#av-` `#cn-` `#dx-` (+ `data-panel`). Exploration/Économétrie : `exp-*`, `eco-*`, `.exp-tabs [role=tab]`, `.exp-panel`, `.exp-period-btns .range-btn`, `.exp-asset-select`. Prédictions : `.pop-trigger`, `.pop-content`, `data-rel-target`, `data-rel-horizon`. News : `news-refresh[data-url][data-status-url]`, `news-status`, `news-es-run`, `news-es`. Résultats : `earn-*`, `.earn-card[data-study]`, `.earn-enable`, `.earn-run`, `.earn-force`, `.earn-result`, `[data-param]`. À faire : `.td-group[data-key][data-group][data-title][data-plan]`, `.td-pick`, `[data-td-all]`, `[data-td-launch]`, `#td-status`. Synthèse : `#market-state`. Détail : ancres `#resume`, `#avis`, `#folds`, `#kpi`.
- **Mécanismes** : `[data-lazy-url]`, `data-label-error/-retry`, événements `patrick:content` et `patrick:run-context` (`runs_panel.js:26` → `stats_bar.js:65`) ; `.hidden`/`hidden` basculés par les scripts ; `help.js` (`STATIC`, `data-keep`, `data-help-host`, `data-help="fold"`, liste identique côté CSS : `test_help_minimal_text.py:53-58`) ; `data-rows-toggle` / `tr[data-extra]` ; `data-adv` / `data-adv-state` ; tous les `name=` lus par `forms.py` / `forms_rl.py` (`tl__<champ>`, `ob__<algo>__<param>__low|high`, `dl_<réglage>`, `rl_<réglage>` : `forms.py:230,346-347,398`).
- **Littéraux exigés dans `patrick.css`** (`test_ui_lot_a.py:81-111`, `test_machine_card_and_ticker.py:63`) : `button.primary, .btn {` et `.btn-secondary, button.secondary {` en `var(--radius-pill)` ; `.btn-arrow::after` + `mask:` ; `\n.card {` avec `var(--radius-card)` et `var(--shadow-card)` ; `--radius-card: 20px` ; 3 définitions `--shadow-card:` ; `.kind-tab {` en pilule ; `.kind-tab.active { background: var(--brand);` ; `content: counter(sec, decimal-leading-zero)` ; `.section-index a[aria-current="true"]` ; `.station-side { grid-column: 2; display: flex; flex-direction: column;`.
- **Balisage testé** : `primary btn-arrow` sur `/ml` et `/runs/run1` (`test_ui_lot_a.py:88-90`) ; ordre `dash-settings` < `<div class="station-side">` < `dash-progress` / `dash-machine` (`test_machine_card_and_ticker.py:59-61`) ; `id="run-form|rl-form" data-mode="simple"`, `data-adv="section_validation|section_optuna_bounds|section_deep_<g>|rl_<g>"` ; `headline-metrics` < `id="resume"` < `id="folds"`, AUC < F1 < DM p (`test_refonte_pages.py:145,176-177`) ; un seul `pop-trigger q-mark`, `class="pred-legend" data-keep` (`test_predictions_page.py:187-188`) ; aucun `class="breadcrumb"` (`test_ui_shell.py:69-71`) ; `style="` seulement dans `_fund_overview.html` et `analysis.html` (`:102-107`) ; `stopped`. 83 des 344 `tests/*.py` citent une URL du périmètre (grep).

## 7. Ce qu'un espace de travail dense façon terminal changerait (pistes)
| Constat | Piste concrète |
|---|---|
| Cartes de 20 px empilées, colonne de 1480 px | Panneaux à en-tête fin (titre, actions, « ? ») en grille 12 colonnes pleine largeur. **Conflit** avec les tests de `--radius-card: 20px` et des pilules : amender `MASTER.md` et les tests |
| 5 composants d'onglets ; détail caché (bulle, panneau qui masque F1, fiche sur une autre URL) | Un seul composant d'onglets ; volet de détail persistant à droite (Historique, Prédictions, Registre, Dérive, Variables, À faire) |
| Quatre moteurs de graphiques | Une grammaire : `PK.plot` et SVG serveur alignés sur `chart_kit` |
| Fil, h1, `<title>` divergents ; plusieurs actions principales | Fil = h1 = `<title>` ; une action principale à droite de l'en-tête, le reste en menu |
| KPI de 210 px hétérogènes | Bandeau KPI compact monospace, fiabilité visible |
| Statuts bruts, symboles, couleurs détournées | Libellé traduit + couleur (valeur brute en attribut pour les tests) ; `iname` ; palette catégorielle hors couleurs de sens |
| 12 accordéons ; fragments de 3 à 6 s ; listes PK recopiées | Ticket de lancement en colonnes et barre d'état ; squelettes à la taille finale, libellé d'erreur corrigé ; un composant « liste filtrable » |
