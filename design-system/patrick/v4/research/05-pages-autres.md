# 05 — Autres pages : Classes d'actifs, Simulation, Patrimoine, Connaissances, pages d'usage, recherche et données

> Lecture seule de `feat/design-v4` (= `main`, `da5cdea`), 08/11/2026. Chemins relatifs à `patrick/patrick/webapp/`, tests dans `patrick/tests/`. « Piste » = proposition v4 ; le reste se vérifie au fichier:ligne. Coque, jetons, CSS : `01`-`03` ; Pilotage/Modèles : `04` (Exploration → Données y sont résumées, détaillées ici au §8).

Modes de rendu : **S** tout serveur · **L** serveur + `lazy_block` (`_components.html:187-195`, `static/lazy.js`) · **K** coquille vide remplie par `analysis_kit.js` · **F** page-formulaire pilotée par un script.

## 1. Périmètre et inventaire

| Entrée (catégorie) | Route | Gabarit + partiels | Mode | Scripts de page |
|---|---|---|---|---|
| Univers (classes) | `/universe` (`app.py:1583`) | `universe.html` | S | — |
| ↳ Fiche actif | `/targets/{ticker}` (`app.py:2395`) | `target.html` + `_asset_signals`, `_news_feed`, `_pred_cell` | L | `drift.js`, `feature_drift.js` (+ `asset_stats.js`, `shap_waterfall.js` globaux) |
| Portefeuille | `/portfolio` (`app.py:2098`) | `portfolio.html` + `_portfolio_bl` (`app.py:2082`) | L | — |
| Indices, Cryptos, Devises, Taux, Mat. premières, ETF | URL de `config/asset_classes.py:28-35`, routes créées en boucle (`app.py:2245-2259`) | `asset_class.html` + `_asset_class_body` (`app.py:2227`) | L | `asset_class.js` |
| Equity | `/equity` (`app.py:2322`) | `equity.html` ⊂ `asset_class.html` | L | idem |
| Macro (FRED) | `/macro` (`app.py:2275`) | `macro.html` + `_macro_alfred` (`app.py:2286`) | L | `macro_alfred.js` |
| Simulation | `/simulate` (`fund_routes.py:184`) | `simulate.html` + `_fund_rule_form` | F | `simulate.js`, `ml_rule.js` |
| Fonds | `/fonds` (`fund_routes.py:196`) | `fonds.html` + `_fund_overview` (`:206`), `_fund_panel` (`:218`), `_fund_rule_form_block` (`:240`), `_fund_autopilot_preview` (`:426`), `_fund_classes_preview` (`:500`) | L + F | `fonds.js` |
| Comptes (patrimoine) | `/patrimoine` (`wealth_routes.py:164`) | `patrimoine.html` | S | `wealth.js` |
| ↳ Compte | `/patrimoine/comptes/{id}` (`wealth_routes.py:174`) | `patrimoine_account.html` | S | `wealth.js` |
| Mouvements | `/mouvements` (`wealth_routes.py:189`) | `mouvements.html` | S | `wealth.js` |
| Risque | `/risque` (`risk_routes.py:63`) | `risque.html` | K | `analysis_kit.js`, `risque.js` |
| Parcours (connaissances) | `/connaissances` (`knowledge_routes.py:82`) | `knowledge_hub.html` | S | — |
| Cours / un cours | `/connaissances/cours`, `/{slug}` (`knowledge_routes.py:91,96`) | `knowledge_courses.html`, `knowledge_course.html` | S | `course.js` |
| Dictionnaire | `/connaissances/dictionnaire` (`knowledge_routes.py:110`) | `knowledge_dictionary.html` | S | `dictionary.js` |
| Vocabulaire, Réglages, Diagnostics (usage) | `/vocabulary` (`app.py:1640`), `/reglages` (`settings_routes.py:93`), `/diagnostics` (`analysis_routes.py:270`) | `vocabulary.html`, `reglages.html`, `diagnostics.html` | S / F / K | `vocabulary.js`, `reglages.js`, `diagnostics.js` |
| Résultats (+ titre, événement) | `/resultats`, `/resultats/titre/{s}`, `/resultats/evenement` (`earnings_routes.py:118,351,366`) | `earnings*.html` + 7 `_earn_*` | L + F | `earnings.js` |
| Économétrie / Exploration | `/econometrie` (`econometrics_routes.py:306`), `/exploration` (`exploration_routes.py:218`) | `econometrics.html`, `exploration.html` | F | `charts.js` + `econometrics.js` / `exploration.js` |
| News | `/news` (`news_routes.py:77`) | `news.html` + 4 `_news_*` | L | `news.js` |
| Données / Qualité | `/donnees` (`data_routes.py:55`), `/data-quality` (`app.py:1618`) | `donnees.html`, `data_quality.html` | K / S | `analysis_kit.js`, `donnees.js` |

Registre : catégories `nav_registry.py:52-59`, dossier *Marchés* `:68`, entrées `:101-129`, pages d'usage hors catégories (pied de barre latérale) `:134-138`. Exploration → Données sont rangées sous **Pilotage** (`:87-94`), pas dans une catégorie de ce rapport. Redirections 308 (non-pages, `:148-152`) : `/launch`→`/ml`, `/patrimoine-simulation`→`/fonds` (`fund_routes.py:213`), `/equities`→`/equity` (`app.py:2316`), `/data-freshness`→`/universe` (`app.py:1612`), `/analyses`→`/runs?vue=analyses`.

Volumes réels (mesurés par import de `forms.TARGET_GROUPS` et `config.defaults`) : 488 symboles en 23 groupes ; Equity 320 (8 groupes), ETF 47, Indices 37, Mat. premières 30, Devises 20, Taux 20, Cryptos 14 ; Macro 109 séries en 14 sections ; dictionnaire ≈ 750 notions (`MASTER.md:185`).

## 2. Constats transverses

**2.1 Deux squelettes d'en-tête.** `.page-header > div + .page-actions` (simulate, fonds, patrimoine, compte, mouvements, réglages) contre `h1.page-title` + `p.page-subtitle` nus (toutes les autres). Résultats et News mettent leur sous-titre dans un `p.hint` (`earnings.html:11`, `news.html:11`).

**2.2 Feuilles chargées dans le corps.** `<link rel="stylesheet">` au milieu de `main` : `knowledge.css` (4 pages Connaissances, ligne 5), `analysis.css` (`risque.html:5`, `diagnostics.html:5`, `donnees.html:5`). `analysis.css:4-14` définit sa propre palette littérale `--ra-c1…8` (25 couleurs hexadécimales) hors de `patrick.css`.

**2.3 Scripts.** Pas de bloc `scripts` dans `base_v2.html` : les `<script>` de page vivent dans `content`, avant les scripts globaux (`base_v2.html:281-294`) ; `asset_stats.js`, `shap_waterfall.js`, `market.js`, `ticker.js` sont chargés partout (`:289-294`), `chart_kit.js` et `names.js` en `<head>` (`:33-35`).

**2.4 Différé.** Fragments de ce périmètre : asset-signals, news-feed (fiche actif), portfolio-bl, asset-class, macro-alfred, fund-overview, earn-* (5), news-* (4). **Défaut visible** : `lazy_block` reçoit le libellé « Chargement… » (`t('sb_loading')`) et le recopie dans `data-label-error` (`_components.html:188-190`) ; en cas d'échec, `lazy.js:24` affiche donc une bannière rouge « Chargement… » + « Réessayer ». `asset_stats.js` ne cherche les `.asset-panel[data-symbol]` qu'une fois, au chargement (`asset_stats.js:132`) puis par `IntersectionObserver` (`:133-141`) : un panneau posé plus tard par un fragment ne serait jamais rempli.

**2.5 Boutons (`MASTER.md:73` : un seul principal par page).** Comptage dans les gabarits : Résultats 6 `.btn` (+2 par carte d'étude, `_earn_library.html:31-32`), Fonds 3 + 3 dans le panneau, Réglages 3, Simulation 2 + 1 dans le formulaire de règle, Patrimoine 2, News 2, fiche actif 1 `.btn` + 1 `button.primary` **par ligne de run** (`target.html:133`) + 1 (`:166`), Économétrie 2 dont `queue-action primary` (`econometrics.html:251`), cartes de cours 1 `a.primary` chacune (`knowledge_courses.html:17`). Aucune page du périmètre n'utilise `.btn-arrow`. Boutons sans classe (style neutre `patrick.css:1033`) : `portfolio.html:70`, `data_quality.html:13`. **Classes sans règle CSS** (aucune occurrence dans `static/*.css`) : `.btn-primary` (`_earn_confirm.html:33`), `.table-wrap` (tous les `_earn_*`, donc tableaux sans conteneur de défilement), `label.check` (`_fund_panel.html:214`).

**2.6 Composants en double.** Pastilles : `.kind-tab` (charte) / `.vocab-chip` détourné (`_asset_class_body.html:16-22`) / `.kb-chip` / `.range-btn` hors `.segmented` (`exploration.html:51-57`). Recherche : `.vocab-search`, `.kb-search`, `#exp-filter` nu. Aide : `help_icon` « ? » (`_components.html:17`) contre `info-icon` « i » écrits à la main (`target.html:157`, `_macro_alfred.html:8`, `patrimoine_account.html:8`). Tableaux : macro `data_table` contre tableaux écrits à la main (`_asset_class_body`, `_fund_*`, `mouvements`, `data_quality`, `_earn_*`, `_asset_signals`). Graphiques : `PatrickPlot` (actif, fonds, compte, macro) contre SVG rendus serveur sans interaction (`earnings_render.py:60-136`), carte de chaleur SVG faite main (`exploration.js:14-40`) et macro `sparkline` (`_components.html:130`, couleur par défaut `var(--accent)`).

**2.7 Textes et noms.** En dur : `'négative attendue'` (`portfolio.html:82`), `Macro (FRED)` (`macro.html:3`), « Runs », « Horizon » (`target.html:91,128,183`), « PRU », « vs », « TWR » (`patrimoine_account.html:48,91`, `patrimoine.html:63-64`), `S` / `O` (`_fund_panel.html:86`), `'F1 ≥ 0,80'` (`_asset_class_body.html:42`, `simulate.html:119`). Phrases du domaine sans `| tx` : `data_quality.html:33-51` (françaises, `tracking/data_health.py:100-177`). Symbole brut : `earnings_title.html:3,7`, `earnings_event.html:3,6`, `_earn_week.html:16`, `news.html:37`. Tests sur chaînes françaises : `patrimoine_account.html:80,123`.

**2.8 Fil de localisation.** Seules la fiche actif et le compte ajoutent un maillon (`target.html:5`, `patrimoine_account.html:10`). `knowledge_course`, `earnings_title`, `earnings_event` et `/data-quality` n'en ont pas et posent un lien retour dans le corps (`knowledge_course.html:6`, `earnings_title.html:8`, `earnings_event.html:7`).

**2.9 Textes repliés à l'exécution.** `help.js:17-29` cache derrière un « ? » tout `.hint`, `.page-subtitle`, `.table-footer`, `.scope-line`, `.banner` (hors erreur/alerte) de plus de 120 caractères, sauf dans `td, th, summary, dialog` (`:22-23`). Les très nombreux `p.hint` de ces pages ne sont donc pas tous visibles : une maquette doit le prévoir.

**2.10 Styles en ligne.** Garde `test_ui_shell.py:102-107` : seuls `_fund_overview.html` et `analysis.html` ont droit à un `style="…"`. `knowledge_hub.html:22,69` en a deux (variables `--share`, `--step`, `--heat`) : **le test échoue sur cette branche** (lancé le 08/11 : `1 failed`).

## 3. Classes d'actifs

### 3.1 Univers `/universe`
- **Structure** : titre + aide (`universe.html:8-10`), sous-titre, 2 `.scope-line` calculées dans le gabarit (`:16-35`), puis un `.group-block` par groupe : `h2.group-title` + `data_table` 6 colonnes (instrument, périodicité, dernière date, fraîcheur, historique de runs, dernier run) + pied (`:37-67`).
- **Densité** : ~490 lignes, 23 tableaux, tout serveur (route synchrone, `app.py:1593-1605`). Aucun filtre ni recherche, à la différence des pages de classe.
- **États vides** : message par défaut de `data_table` (`dt_empty`).
- **Piste** : un seul tableau type *screener* (groupe = colonne + en-têtes de groupe repliables collants), recherche et pastilles reprises de `asset_class.js`, fraîcheur en pastille + jours de retard en chiffres alignés à droite.

### 3.2 Fiche actif `/targets/{ticker}`
- **Structure** (`target.html`) : titre + ligne méta (classe, groupe, source, historique) (`:8-14`) ; 5 actions (`.btn`, 2 secondaires, 2 fantômes) (`:15-21`) ; `.section-index` à 6 ancres (`:23-31`) ; `#marche` = `asset_panel` (`:34`) ; `#contexte` (actions, `:36-46`) ; `#signaux`, `#actualites` différés (`:49-57`) ; `#fonds` (`:59-71`) ; `#voisins` (`:73-78`) ; titre `#entrainements` hors carte (`:80`) ; 3 KPI (`:87-102`) ; PBO (`:104-125`) ; Runs, 14 colonnes, un « Relancer » par ligne (`:127-154`) ; SHAP (`:156-172`) ; PSI (`:178-191`) ; alpha (`:196-219`) ; dérive des phases (`:221-230`) ; `window.DRIFT_*` (`:234-239`).
- **États vides** : `empty_state` avec action « lancer un run rapide » (`:84`, `_asset_signals.html:7`), « aucun fonds » (`:69`), « pas de dérive » (`:228`), « pas de modèle » pour SHAP (`:170`).
- **Problèmes** : l'index omet voisins, PBO, SHAP, PSI, alpha, dérive ; le graphique principal n'est qu'une carte parmi 12 ; tableau de 14 colonnes ; plusieurs actions principales.
- **Piste** : fiche « description de titre » : bandeau (nom, symbole mono, classe, dernier cours et variation, déjà dans `asset_stats`) ; grille 2/3 graphique + 1/3 signaux et champions ; onglets dessous (Entraînements · Robustesse · Explications · Alpha · Dérive · Actualités · Fonds) ; une action principale, le reste en barre d'outils.

### 3.3 Portefeuille `/portfolio`
- **Structure** : titre, sous-titre + badge directionnel, note, bannière modèles suspects (`portfolio.html:15-18`), `.scope-line` (`:25-29`), 4 cartes animées `enter-60…180` : signaux par classe (5 colonnes, `:31-50`), contradictions avec formulaire GET `textarea` des paires (`:52-89`), poids HRP (2 colonnes + note Ledoit-Wolf, `:96-118`), Black-Litterman : liens d'horizon qui rechargent la page (`:127-129`) + fragment 7 colonnes (`:130`, `_portfolio_bl.html:21-24`).
- **États vides** : 5 `empty_state` (`:34,73,102`, `_portfolio_bl.html:5,7`).
- **Problèmes** : baisses en `status-warning` (ambre) (`:41,81`) ; éditeur de paires au milieu d'une page de lecture ; horizons en liens texte.
- **Piste** : grille 2×2 de panneaux à en-tête ; HRP et BL fusionnés (poids de référence, poids BL, inclinaison en barre divergente) ; horizons en `.segmented` ; éditeur de paires dans un tiroir.

### 3.4 Pages de classe (Indices, Cryptos, Devises, Taux, Mat. premières, ETF) et Equity
- **Cadre** (`asset_class.html`) : titre + jusqu'à 3 aides (`:6-12`), sous-titre, bannière info pour crypto/fx/rates/indices (`:15-17`), fragment (`:21`), puis `details.card.cls-prices` (fermé) avec une grille de panneaux de cours seulement si la classe compte ≤ 40 actifs (`app.py:2223`) — donc rien pour Equity (320) ni ETF (47) ; bloc `class_extra` (`:32`).
- **Fragment** (`_asset_class_body.html`) : 5-6 KPI (`:5-12`), outils (recherche, 5 pastilles, compteur `aria-live`) (`:14-24`), un `details.card.cls-group` **fermé** par groupe avec tableau 10 colonnes (`:26-59`), colonne Signaux remplie après coup par `/api/class-signals/{classe}` (`asset_class.js:52-73`, `app.py:2031`), `#cls-none` (`:60`).
- **Equity** ajoute une carte « features propres aux actions / exclusions » (`equity.html:5-29`).
- **Problèmes** : toutes les données sont derrière un clic (groupes fermés tant qu'aucun filtre n'est actif, `asset_class.js:35`) ; dernière colonne sans en-tête (`:36`) ; jusqu'à 37 panneaux de 360 px minimum (`patrick.css:1980`).
- **Piste** : *screener* ouvert par défaut, une table unique, groupe en facette ; cours en tableau de cotation à petits graphiques (dernier, variation, sparkline), détail au clic.

### 3.5 Macro `/macro`
- **Structure** : titre (en dur) + 2 aides (`macro.html:3-9`), sous-titre, carte FRED/ALFRED différée (`:13` → `_macro_alfred.html` : 4 KPI, top des séries révisées, tableau 9 colonnes replié après 12, bouton de calcul `.btn-secondary` `:55-58`), sommaire en étiquettes (`:15-19`), 14 sections de cartes `asset_panel` (`:21-30`).
- **Densité** : 109 cartes graphiques, chargées au défilement (`asset_stats.js:130-141`) ; l'étiquette « entraînement seulement » est posée sur toutes (`app.py:2270`), sans lien.
- **Piste** : tableau type calendrier économique (série, dernière, précédente, variation, date, périodicité, mode ALFRED, sparkline), graphique dans un panneau latéral au clic.

## 4. Simulation

### 4.1 Simulation `/simulate`
- **Structure** (`simulate.html`) : en-tête + « Nouvelle stratégie » (`:11-19`), flash (`:21-22`), ticket : formulaire en grille (~16 champs selon le type : action, ETF, future, CFD) + aperçu serveur `#ticket-preview` (`:25-104`) ; « piloter avec un modèle » = `_fund_rule_form.html` (22 champs, `:111-127`) ; portefeuilles en `.account-grid` + sparkline (`:130-154`) ; dialogue (`:156-175`) ; îlots JSON (`:178-180`).
- **États vides** : `empty_state` sans stratégie (`:106`).
- **Problèmes** : ticket, formulaire de règle et portefeuilles empilés ; trois boutons principaux (`:97`, `_fund_rule_form.html:72`, `:172`).
- **Piste** : ticket d'ordres en colonne droite collante avec l'aperçu dessous ; portefeuilles en liste dense à gauche.

### 4.2 Fonds `/fonds`
- **Cadre** (`fonds.html`) : en-tête + `.btn` vers `/simulate` (`:12-20`), flash, `#fund-overview` différé (`:24-26`), `#fund-panel` caché (`:28`), création par classe d'actifs en `details` (`:31-69`), dialogue de renommage (`:73-82`), archives (`:84-94`).
- **Fragment** (`_fund_overview.html`) : 3 KPI (`:7-11`), barres de répartition (seul style en ligne autorisé, `:19`), tableau 9 colonnes à lignes cliquables `role="button"` (`:26-66`).
- **Panneau** (`_fund_panel.html`, injecté sous le tableau par `fonds.js`) : 4 boutons (`:9-16`), bannières (`:20-22`), **18 KPI** neutres sauf le Sharpe déflaté (`:24-45`), graphique (`:47-49`), positions ouvertes 13 colonnes + formulaires en lignes cachées (`:51-159`), closes (`:161-191`), pilote (`:194-252`), règles (`:254-292`), nouvelle règle (`:294-297`), ordres (`:299-324`).
- **Problèmes** : détail sous la liste (long défilement) ; 12 `btn-ghost` ; P&L non coloré dans les KPI, son % dans la case « fiabilité » de `metric()` (`_fund_overview.html:10`) ; marqueurs `!` et `*` sans légende (`_fund_panel.html:74,273,316-317`).
- **Piste** : maître-détail côte à côte (blotter 40 %, détail 60 % en onglets Positions · Pilote · Règles · Ordres) ; bandeau de 6 KPI clés + « plus ».

## 5. Patrimoine

### 5.1 Comptes `/patrimoine`
- **Structure** : en-tête + lien Mouvements + `.btn` nouveau compte (`patrimoine.html:11-22`), flash, alertes (`:26-31`), 4 KPI dont la volatilité avec une phrase de fiabilité assemblée de 5 morceaux (`:35-46`), cartes de comptes `a.account-card.drop-target` (lien et cible de dépôt à la fois, `:48-73`), positions consolidées 5 colonnes (`:75-93`), dialogue (`:95-119`, exemple en dur « PEA Boursorama » `:98`).
- **Rendu** synchrone avec cotations (`wealth_routes.py:164-172`). États vides : `:71`, `pat_c_none`.
- **Piste** : bandeau à deux totaux bien séparés (réel / fictif), comptes en lignes denses (TWR, écart au benchmark), positions en tableau.

### 5.2 Compte `/patrimoine/comptes/{id}`
- **Structure** : maillon (`patrimoine_account.html:10`), en-tête avec badges, cloner / supprimer (`:12-31`), 4-5 KPI (`:39-59`), graphique (`:61-71`), positions 7 colonnes (`:73-94`), import CSV par dépôt (`:97-106`), mouvements : formulaire d'ajout de 10 champs + tableau 8 colonnes (`:108-159`).
- **Piste** : deux colonnes (graphique + positions / journal des mouvements), formulaire d'ajout dans un tiroir.

### 5.3 Mouvements `/mouvements`
- **Structure** : en-tête (`mouvements.html:10-17`), cartes-cibles avec zone CSV chacune (`:22-41`), journal 9 colonnes à lignes glissables (`:43-71`). Cellules `td.num` sans `pk-mono` (`:58-60`). États vides `:69,73`.
- **Piste** : blotter pleine largeur filtrable par compte, cibles de dépôt en rail latéral.

### 5.4 Risque `/risque`
- **Coquille K** (`risque.html:9-29`) : barre de contrôles, statut, KPI, 9 cartes (VaR, courbe, contributions, corrélations, crises, chocs, backtest, attribution, écarts) remplies par `risque.js` via `/api/risque/*`, lexique en `<dl>` sans aucun `<dt>` (`:23-25`).
- **Piste** : bandeau KPI + grille 2 colonnes de panneaux, contrôles collants.

## 6. Connaissances

- **Parcours** `/connaissances` : recherche rapide avec `button.primary` (`knowledge_hub.html:13-16`), « escalier » de niveaux en cartes à hauteur proportionnelle (`:18-31`), liste de cours (`:33-52`), matrice thème × niveau en carte de chaleur (`:54-75`). Aucun script.
- **Cours** : grille de cartes, une action principale par carte (`knowledge_courses.html:9-20`). **Lecteur** : lien retour (`knowledge_course.html:6`), avis « français seulement » en anglais (`:9`), sommaire collant + corps Markdown/MathML (`:14-32`, `knowledge.css:57-66`), puces de notions ; erreur = bannière (`:11-12`).
- **Dictionnaire** : carte de filtres (recherche, thème, réinitialiser, pastilles de niveau, lettres, compteur `aria-live`) (`knowledge_dictionary.html:9-29`) ; les ≈ 750 `article.kb-term` sont tous rendus serveur (`:31-56`), filtrés par `dictionary.js`.
- **Piste** : garder la lecture aérée ; remonter la matrice (seule donnée chiffrée) ; dictionnaire avec rail gauche (lettres, thèmes).

## 7. Pages d'usage

- **Vocabulaire** `/vocabulary` : se déclare page héritée et renvoie au dictionnaire (`vocabulary.html:7`) ; recherche, pastilles de rubrique, une carte `dl` par rubrique (`:9-32`). La bulle du glossaire pointe déjà vers le dictionnaire (`base_v2.html:258`). Piste : fusion / redirection.
- **Réglages** `/reglages` : 5 cartes (`#card-share` `:18-56`, `#card-update` `:59-70`, `#card-window` `:73-89`, `#card-performance` `:92-105`, `#card-data` `:108-123`) + voile de relance (`:125-132`), tout rempli par `reglages.js` depuis `/api/app/overview`. 3 `.btn` (`:40,48,65`). Piste : réglages façon macOS (liste de sections à gauche, volet à droite, listes groupées à interrupteurs).
- **Diagnostics** `/diagnostics` : coquille K, 6 cartes (application, processus, CPU, disques, stockage, journaux en `<pre>`) (`diagnostics.html:9-18`). Piste : tableau de bord de supervision en grille.

## 8. Recherche et données (registre : Pilotage)

### 8.1 Résultats `/resultats` (+ fiche titre, événement)
- **Structure** (`earnings.html`) : titre + aide, sous-titre en `.hint` (`:8-11`), 3 KPI dont un sans fiabilité (`:13-17`), collage du calendrier (`textarea`, date d'ancrage, `.btn`, lots en `details`) (`:19-41`), lot courant : confirmation ou vue semaine différée (`:43-55`), instantané (`:57-61`), configuration 11 champs + 2 `.btn` (`:63-87`), bibliothèque d'études différée (`:89-102` → cartes par groupe, `_earn_library.html`), registre FDR au clic (`:104-110`), méthode (`:112-115`).
- **Fiche titre / événement** : cadre minimal + fragment (`earnings_title.html`, `earnings_event.html`) ; KPI écrits à la main (`_earn_title.html:7-15`), courbes SVG serveur (`:30`, `_earn_event.html:17-28`).
- **Problèmes** : ≥ 6 actions principales ; `.table-wrap` / `.btn-primary` sans CSS ; graphiques sans zoom ni infobulle ; symboles bruts (§2.7).
- **Piste** : la semaine de résultats en blotter central ; configuration dans un tiroir ; bibliothèque en liste à colonne d'état (en cache, lourde) ; courbes passées à `PatrickPlot`.

### 8.2 Économétrie `/econometrie` et 8.3 Exploration `/exploration`
- **Structure commune** : carte de sélection (filtre, `select` de 9 ou 11 lignes, transformation, période `.range-btn`, `button.primary`, statut) (`econometrics.html:32-81`, `exploration.html:19-79`) ; `role="tablist"` de 6 / 8 onglets (`:83-90`, `:81-90`) ; par onglet un `.card.exp-panel` : `.exp-params` + `.queue-action` + `.exp-out` vide (`:93-255`, `:93-287`).
- **Problèmes** : sorties vides sans texte d'attente tant qu'on n'a pas lancé ; l'ordre des panneaux dans le DOM (corr, dist, mémoire, dép.) diffère de celui des onglets (corr, dép., dist, mémoire) ; Économétrie réutilise l'espace de noms `exp-*`.
- **Piste** : espace de travail partagé : rail gauche persistant (séries), barre d'outils (transformation, période, fréquence), panneau central à onglets, paramètres en barre d'outils de panneau.

### 8.4 News `/news`
- **Structure** : titre + aide, sous-titre `.hint`, 5 KPI (`news.html:13-19`), barre « fenêtre » en liens + `.btn` actualiser (`:21-26`), 4 cartes : sentiment par actif, flux (8 colonnes, replié après 12), banques centrales, étude d'événement au clic (`:28-58`), méthode (`:60-63`). Pastilles `exp-chip-*` empruntées à Exploration (`_news_assets.html:10`).
- **Piste** : fil d'actualités pleine hauteur à gauche, tableau de sentiment à droite, bandeau de ton des banques centrales.

### 8.5 Données `/donnees` et 8.6 Qualité `/data-quality`
- **Données** : coquille K, onglets fabriqués par `donnees.js` dans `#dx-tabs`, 6 panneaux (lac, point dans le temps, révisions, calendrier, listes de suivi, import) (`donnees.html:10-21`).
- **Qualité** (enfant de Données, sans maillon) : barre de seuil avec bouton nu (`data_quality.html:9-15`), 5 KPI (`:17-23`), échecs (`:25-42`), séries écartées en `details` plafonnés à 60 lignes (`:44-70`), résultats suspects (`:72-92`), historique par groupe en `details` (`:94-129`).
- **Piste** : liste d'anomalies triée par gravité ; historique en table unique filtrable (même composant que le *screener* de l'Univers).

## 9. Contrat à ne pas casser (noms exacts)

- **Registre** : slugs `universe portfolio equity indices crypto fx rates commodities etfs macro simulate fonds patrimoine mouvements risque knowledge_hub knowledge_courses knowledge_dictionary vocabulary settings diagnostics`, leurs URL et `child_routes` (`/targets/{ticker}`, `/patrimoine/comptes/{account_id}`, `/connaissances/cours/{slug}`) ; redirections de `NON_PAGE_ROUTES`.
- **Différé** : `[data-lazy-url]`, `data-label-error`, `data-label-retry`, `.lazy-retry`, `.lazy-ready`, événement `patrick:content` (attendu par `asset_class.js:81-83`).
- **Panneau de cours** : `.card.asset-panel#asset-{slug}[data-symbol]`, `.asset-panel-body[data-state]`, `.asset-chart`, `.asset-panel-grid`.
- **Classes d'actifs** : `[data-class-key]`, `#cls-search`, `#cls-count`, `#cls-none`, `[data-filter]`, `[data-group]`, `tr.cls-row[data-symbol][data-search][data-trained][data-alpha][data-short]`, `td.cls-signals[data-symbol]`, `.cls-sig-{état}` ; Macro `#macro-{clé}`, `#alfred-vs-fred[data-running]`, `#alfred-refresh[data-url][data-label-running]`, `#alfred-progress`.
- **Fiche actif** : ancres `#marche #contexte #signaux #actualites #fonds #entrainements #alpha-models`, `#shap-waterfall-widget[data-target]`, `.shap-horizon-select`, `.shap-generate-btn`, `.shap-waterfall-output`, `#feature-drift-widget`, `.drift-horizon-select`, `.drift-measure-btn`, `.drift-output`, `#drift-chart`, `window.DRIFT_POINTS / DRIFT_PHASE_LABELS / DRIFT_CHAMPIONS / DRIFT_CHAMPION_LABEL`.
- **Simulation / Fonds** : `#ticket-form` et ses `name`, `#f-strategy #f-symbol-pick #f-symbol-manual #f-symbol #f-symbol-list #f-root #f-contract #f-leverage #f-leverage-hint #f-date #f-manual-price #f-price #f-fees #ticket-submit #ticket-preview`, `[data-kinds]`, `[data-modes]`, `[data-alpha-only]`, `[data-actions]`, `#futures-data #cfd-classes #ticker-bank #fund-selected #fund-chart-data` (îlots JSON), `#new-strategy-dialog/-form`, `[data-open-dialog]`, `[data-close-dialog]`, `#ml-rule-form`, `form[data-form="rule|adjust|correct"]`, `.fund-form-error`, `#fund-flash #fund-overview #fund-panel #fund-classes #fund-chart #fund-rename-dialog #fund-rename-form`, `[data-cls-field] [data-cls-result] [data-auto-field] [data-auto-result] [data-rule-form-url]`, `data-act` = `classes-preview classes-create unarchive delete-strategy rename archive close-panel toggle delete-position auto-preview auto-save auto-run auto-off apply-rule delete-rule`, `.fund-row[data-strategy-id]` (+ `.is-selected`), `.fund-share`, `.fund-breakdown`, `.fund-position`, `.fund-archived`, `data-confirm`.
- **Patrimoine** : `#wealth-flash`, `form[data-api][data-method]`, `button[data-api]`, `data-redirect-account`, `data-redirect`, `data-reload`, `.drop-target[data-account-id][data-account-mode][data-account-name]`, `.draggable-row[data-movement-id]`, `.drop-zone[data-import-account]`, `[data-import-preview]`, `select[data-symbol-select]`, `[data-symbol-other]`, `#wealth-chart(-data)`, `.account-card[data-kind]`, `.form.add-movement`, `#new-account-dialog` ; Risque `#rk-root #rk-controls #rk-status #rk-kpis #rk-var #rk-equity #rk-contrib #rk-corr #rk-stress #rk-shocks #rk-bt-controls #rk-bt #rk-attr #rk-gap-controls #rk-gaps`.
- **Connaissances / Vocabulaire** : `#kb-search #kb-theme #kb-reset #kb-count[data-template][data-total] #kb-body #kb-none #kb-course-body`, `.kb-chip[data-level]`, `[data-letter-link]`, `.kb-letter[data-letter]`, `article.kb-term#term-{clé}[data-theme][data-level][data-alias][data-other]`, `.kb-formula`, `[data-toc]`, `.card.kb-level-card` ; `#vocab-search #vocab-count #vocab-body #vocab-none`, `[data-cat-chip]`, `.vocab-term#term-{clé}[data-search]`.
- **Réglages / Diagnostics / Données** : tous les `id` de `reglages.html` (`share-*`, `pref-*`, `update-*`, `port-save`, `shortcuts-make`, `setting-*`, `perf-*`, `path-*`, `backup-*`, `relaunch-*`, `app-flash`, `[data-open]`), `dg-*`, `dx-*`.
- **Résultats / News / Exploration / Économétrie** : `#earn-paste #earn-text #earn-anchor #earn-parse #earn-batch[data-batch][data-status] #earn-snapshot #earn-config #earn-recompute #earn-library-card[data-scope][data-batch] #earn-scope #earn-scope-symbol #earn-compute-all #earn-library #earn-ledger-run[data-url] #earn-ledger #earn-confirm[data-batch] #earn-manual[data-symbol] #earn-title-body[data-symbol]`, `tr[data-item]`, `.earn-card[data-study][data-default-on]`, `.earn-enable`, `[data-param]`, `.earn-run[data-url]`, `.earn-force`, `.earn-result`, les `*-status` ; `#news-refresh[data-url][data-status-url] #news-status #news-es-run[data-url] #news-es` ; tous les `exp-*` / `eco-*`, `.exp-asset-select[data-role]`, `[role="tab"][data-panel]`, `.exp-panel[data-study]`, `.range-btn[data-years]`, `.eco-grid-model`, `.eco-grid-dist`, `#eco-fc-specs`.
- **Transverse** : `t('clé')` et les clés `*_JS_KEYS`, filtres `iname`, `iname_h`, `iname_tip`, `hlabel`, `eur`, `pct`, `qty`, `mvkind`, `tx` ; `data-keep`, `aria-live`, `role="status"` (protègent un texte du repli, `test_help_minimal_text.py:41-45`) ; `| safe` de `data_table` (échappement à la charge de l'appelant, `_components.html:43-57`).
- **Tests qui figent ce balisage** : `test_asset_page`, `test_asset_classes`, `test_equity_asset_class`, `test_commodities_macro_pages`, `test_macro_alfred_page`, `test_target_alpha_section`, `test_portfolio_*` (3), `test_universe_extension`, `test_data_freshness_page`, `test_fund_*` (3), `test_confirm_dialogs`, `test_wealth_webapp`, `test_risk_routes`, `test_knowledge_routes`, `test_refonte_pages`, `test_settings_routes`, `test_analysis_diagnostics`, `test_earnings_page`, `test_econometrics_routes`, `test_exploration_*` (2), `test_news_page`, `test_data_explorer`, `test_data_health`, `test_ui_shell`, `test_help_minimal_text`, `test_nav_registry`.

## 10. Ce qu'une mise en page « terminal + propreté Apple » changerait

1. **Panneau à en-tête dense** (titre, compteur, actions en icônes, « ? ») à la place des cartes de 20 px empilées (fiche actif : 12, Risque : 10).
2. **Données d'abord** : tableaux de classe ouverts, Macro en tableau de cotation, Univers filtrable.
3. **Maître-détail** : Fonds, Patrimoine, Résultats, Mouvements. **Espace de travail** : Exploration, Économétrie.
4. **Grammaire unique** : une pastille, une recherche, un « ? », un conteneur de tableau, une action principale par page, `PatrickPlot` partout ; `.page-header` et fil de localisation partout, libellés traduits, noms au lieu des symboles.
