# 03 — CSS propre aux pages : cartographie avant la refonte v4

> Branche `feat/design-v4` (= `main`, `da5cdea`), relevé du 2026-11-08, lecture seule. Chemins relatifs à `patrick/patrick/webapp/`.
> « l. N » = ligne de `static/patrick.css` ; `an:N` = `static/analysis.css` ; `kb:N` = `static/knowledge.css`.

## 0. Périmètre, méthode, chargement

- **Périmètre** : `patrick.css` l. 1350 (« /launch ») → 2972 (fin) = 1 623 lignes, 83 Ko sur 134 Ko ; `analysis.css` (102 lignes, préfixe `ra-`) ; `knowledge.css` (154 lignes, préfixe `kb-`).
- **Méthode** : sélecteurs extraits par script (commentaires retirés) → 684 classes distinctes (562 dans la plage de patrick.css ; 56 et 66 de plus dans analysis.css et knowledge.css, qui restylent aussi `card`, `section-index`, `metric-value`, `primary`, `btn-secondary`, `queue-action`, `data-table`) + 15 ids. Chaque nom cherché comme jeton exact dans `templates/*.html` (89), `static/*.js` (58) et tous les `.py` de `patrick/patrick/` ; sinon, préfixe dynamique cherché (`x-{{ … }}`, `"x-" + v`) ; noms génériques (`.n`, `.err`…) vérifiés à la main.
- **Chargement** : `patrick.css` dans `base_v2.html:31` (toutes les pages). `analysis.css` par `<link>` dans le corps de 12 gabarits (`_runs_analyses:3`, `analyses_compare:7`, `carnet:5`, `derive:5`, `diagnostics:5`, `donnees:5`, `garde_fous:5`, `journal:5`, `modeles:7`, `risque:5`, `run_analysis:17`, `variables:5`) et recopiée dans l'export (`analysis_routes.py:217` relit `patrick.css` + `analysis.css` par leur nom). `knowledge.css` dans les 4 gabarits `knowledge_*.html:5`.
- **Écarts avec MASTER** : `MASTER.md:13` dit « `patrick.css` (seule feuille) » ; `MASTER.md:15` protège les classes de `simulate.js`, or ces classes `sim-*` sont mortes (§6).

## 1. patrick.css l. 1350–2972, section par section

Consommateurs : gabarits (sans `.html`) / scripts. Mises en page détaillées au §4, doublons au §5, morts au §6, anomalies au §7.

| Lignes | Section | Classes principales | Consommateurs (pages) | Remarques |
|---|---|---|---|---|
| 1350–1556 | /launch | `station-grid`, `dash-settings`, `station-side`, `dash-panel(-title/-body)`, `settings-mode`, `launch-bar`, `launch-recap`, `launch-cancel`, `queue-*`, `run-controls`, `progress-bar/-fill` | launch_base (/ml, /dl ; `/launch` redirige, `app.py:509`), rl (/rl), _machine_card, _run_controls / app.js, machine.js, rl.js | grille 1,35fr/1fr, pile flex à droite, barre `sticky` bas, `@container` 340 px. Mort : `.history-model-actions` |
| 1557–1584 | Carte « file d'attente » | `dash-machine`, `machine-kind`, `machine-idle`, `run-name-line`, `log-tail` | _machine_card (`launch_base:594`, `rl:215`) / machine.js, app.js | `.machine-kind` = pastille maison |
| 1585–1639 | Avancement | `steps-list`, `step(-warn/-error/-current)`, `log-raw`, `recent-runs*` | launch_base, rl / `app.js:326` | `.step::before` = glyphes ✓ ! ✕ ▸, pas d'icônes Lucide |
| 1640–1684 | Market preview | `target-preview`, `segmented`, `preview-range-buttons`, `range-btn`, `chart-wrap`, `chart-tooltip`, `nowrap` | launch_base, target, patrimoine_account, _fund_panel, econometrics, exploration / chart_kit, market, analysis_kit, asset_stats, 8 scripts d'analyse | `.segmented` (composant MASTER) vit ici |
| 1685–1768 | chart_kit + rendu « cotation » | `pp`, `pp-stage`, `pp-over`, `pp-tip*`, `pp-tools`, `pp-btn`, `pp-legend*`, `pp-quote*`, `pp-up/-down/-flat`, `pp-fin`, `pp-compact` | chart_kit.js (base_v2 l. 33), charts.js | classes produites par le JS : contrat |
| 1769–1780 | (sans en-tête) actualités, variations | `target-news`, `news-list`, `news-publisher`, `movers-up/-down` | launch_base (actualités), base_v2 (variations) / market.js, ticker.js | liste à filets (= `.recent-runs-list`) |
| 1781–1833 | Bandeau ticker | `ticker`, `ticker-viewport/-track/-group/-item/-sym/-pct` | base_v2 (toutes pages) / ticker.js | coque ; textes testés (§8) |
| 1834–1882 | Breadcrumb, scope, filtres | `nav.breadcrumb`, `scope-line`, `scope-value/-rel`, `filter-bar` | scope-line : runs, universe, portfolio, _predictions_body ; filter-bar : runs, portfolio, data_quality | mort : `nav.breadcrumb` ; `.filter-bar` aussi réglé l. 984, 1054, 2195, 2202 |
| 1883–1970 | /runs/{id}/detail | `session-context`, `section-index(-label)`, `block-note`, `config-dump`, `pre` | run_detail, run_analysis ; section-index aussi _runs_analyses, analysis, garde_fous, target, variables / shell.js ; config-dump aussi diagnostics | `.section-index` (MASTER) vit ici, défini deux fois |
| 1971–1977 | /universe | `group-block`, `group-title` | universe, macro, asset_class, equity, _predictions_body | sert bien au-delà de /universe |
| 1978–1993 | /commodities, /macro | `asset-panel-grid`, `macro-toc`, `asset-panel(-body)`, `asset-metric-grid` | asset_class (/indices /crypto /fx /rates /commodities /etfs, `config/asset_classes.py:28-37`), macro (seul à porter `macro-toc`) ; macro `asset_panel` (`_components.html:172`, aussi target) / asset_stats.js | mort : `.asset-panel-symbol` |
| 1994–2005 | /targets (SHAP) | `shap-controls`, `shap-waterfall-*`, `shap-caption` | target / shap_waterfall.js | SVG propre, hors chart_kit |
| 2006–2082 | /simulate (ancien) | `sim-*`, `#sim-*`, `metric-row`, `metric-help`, `table .metric-label` | aucun, sauf `.sim-guard` (feature_drift.js) | bloc mort |
| 2083–2132 | Patrimoine | `account-grid`, `account-card[data-kind]`, `drop-zone[data-over]`, `dialog.modal`, `draggable-row`, `drop-target` | patrimoine, mouvements, patrimoine_account, simulate, fonds, base_v2 (`confirm-dialog`) / wealth.js, confirm.js | `dialog.modal` = modale de référence |
| 2133–2212 | Motion & responsive | réduction des animations, 1180 / 1023 / 480, `pointer:coarse`, `print` | global | cite des classes mortes (§6) |
| 2213–2223 | Utility | `visually-hidden`, `hidden` | `visually-hidden` : base_v2, runs, _fund_overview / shell.js ; `hidden` : 14 gabarits / app.js | dit « last » mais 750 lignes suivent |
| 2224–2310 | /runs | `history-filters`, `filter-more`, `history-table(-cls/-rl)`, `hc-*`, `history-row`, `history-dialog`, `run-panel*`, `rp-*`, `has-run-panel` | runs, _run_panel, _rl_run_panel (`/runs/{id}/panel`) / runs_panel.js ; `main-column` dans base_v2 | `table-layout:fixed` + largeurs `nth-child` ; panneau fixe à droite |
| 2311–2351 | /predictions | `pred-table`, `pred`, `pred-legend`, `q-mark`, `pred-pop`, `pop-grid`, `pop-track*` | predictions, _predictions_body, _pred_cell / predictions_pop.js | bulle `fixed` z 100 |
| 2352–2368 | Simulation : ticket | `fund-ticket-grid`, `fund-preview(-list)`, `fund-choice` | simulate / simulate.js | 1 col. < 900 px |
| 2369–2397 | Fonds | `fund-row`, `fund-panel`, `fund-orders`, `fund-archived`, `fund-breakdown`, `fund-share(-bar)`, `fund-ticker`, `#benchmark-field` | fonds, _fund_overview, _fund_panel, _fund_rule_form / fonds.js, ml_rule.js ; `#benchmark-field` = launch_base + app.js | règle d'une autre page égarée |
| 2398–2417 | Réglages | `set-*`, `#card-share/-window/-performance` | reglages | styles par id ; `.set-paths`, `.set-overlay` maison |
| 2418–2434 | Qualité des données, cibles grisées | `dq-*`, `option.target-short`, `target-greyed-note` | data_quality, todo ; launch_base / app.js | — |
| 2435–2453 | Métriques AUC/F1 | `headline-metric(s)`, `fold-block`, `fold-table`, `rows-toggle` | macros `headline_metrics`, `fold_metrics_table` (`_components.html:92,118`) appelées par run_detail, _run_panel / rows.js, table_tools.js | KPI parallèle à `.metric` |
| 2454–2480 | Directionnel / Alpha | `kind-tabs`, `kind-tab`, `kind-count`, `kind-badge(.kind-directional/-alpha/-rl)`, `tag-partial`, `history-pager`, `family-tabs`, `rp-table` | kind-tabs : runs, predictions ; kind-badge : 12 gabarits | `.kind-tabs` (MASTER, testé) vit ici ; `kind-*` = filtres et badges |
| 2481–2493 | Comparaison RL | `cmp-*`, `compare-rl-table`, `tag-suspect` | compare_rl (/compare-runs) / rl_compare.js ; tag-suspect aussi runs, simulate, _asset_class_body | légende maison |
| 2494–2518 | Bulle de suivi | `pop-track-4`, `pop-matrix`, `pop-journal`, `jr-*`, `pop-hit` | _pred_cell | 2 colonnes 310/390 px ≥ 900 px via `:has()` |
| 2519–2536 | Vocabulaire | `vocab-*`, `glossary-more` | vocabulary / vocabulary.js ; `vocab-chip` aussi target, _asset_class_body ; `glossary-more` : base_v2 | 2ᵉ lexique à côté de `kb-term` |
| 2537–2571 | Bandeau d'aide statistique | `stats-bar*`, `has-stats-bar-open`, `sh-*` | base_v2 (toutes pages sauf /ml /dl /rl, l. 234), _stats_help (`/api/stats-help`) / stats_bar.js | `fixed` bas, `left: var(--sidebar-width)` |
| 2572–2591 | Carte ML, classes d'actifs | `fund-ml`, `ml-kinds`, `cls-tools`, `cls-chips`, `cls-group`, `cls-scroll`, `cls-table` | simulate, _fund_rule_form ; _asset_class_body (`/fragments/asset-class/{classe}`), asset_class / asset_class.js | `.cls-chips .vocab-chip` détourne la puce en bouton |
| 2592–2608 | /analysis, Synthèse | `an-grid`, `an-bars`, `an-bar*` ; `home-trio`, `home-card`, `home-links`, `home-mini` | analysis ; synthesis (/) | — |
| 2609–2647 | Conseiller, profils, lots | `adv-item`, `adv-cost-*`, `profile-grid`, `profile-card`, `profile-main`, `batch-*`, `[data-help-host] > .help-q` | _retrain_advice, _profile_gallery (dans launch_base), rl, _launch_batches, _batch_gallery / launch_batches.js | lien étiré `::after` |
| 2648–2686 | Macro, lazy, texte minimal | `#alfred-vs-fred` ; `lazy-block/-skeleton/-ready` ; `help-folded`, `help-pending`, `help-pop` | _macro_alfred ; macro `lazy_block` (13 gabarits) / lazy.js ; help.js | liste `help-pending` testée |
| 2687–2737 | Exploration | `exp-sel-grid`, `exp-controls`, `exp-tabs`, `exp-panel`, `exp-params`, `exp-heat*`, `exp-chip*`, `exp-two/-three`, `data-table td.neg/.pos` | exploration, econometrics / exploration.js, econometrics.js ; `exp-chip` aussi `_news_*` et 5 scripts | règles globales `.data-table td.neg/.pos` ici. Morts : `.exp-chart`, `.exp-tip` |
| 2738–2757 | RL, notifications | `rl-*`, `#rl-form` ; `notify-toggle`, `run-toast(s)*` | rl / rl.js ; base_v2 / run_notify.js | — |
| 2758–2774 | Outils de tableau, onglets de run | `table-tools*`, `data-table th[aria-sort]` ; `run-tabs` | table_tools.js (tout `table.data-table` ≥ 8 lignes, l. 6) ; _run_tabs, _compare_tabs | tri cassé (§7.1) |
| 2775–2798 | À faire, budget d'essais | `home-action*`, `td-*`, `trial-budget*` | synthesis ; todo (/a-faire/{clé}) / a_faire.js ; launch_base / trial_budget.js | jetons inexistants (§7.2) |
| 2799–2817 | Utilitaires anti-`style=""` | `sk-*`, `enter-*`, `row-end`, `flush-top`, `is-picked`, `compare-tabs`, `pop-rel`… | _components, synthesis, run_detail, mouvements… / runs_panel.js, predictions_pop.js | nés du test des styles en ligne |
| 2818–2833 | Fiche d'un actif | `asset-hero`, `asset-actions`, `as-*`, `cls-sig(-ok/-warning)` | target, _asset_signals ; _asset_class_body / asset_class.js | — |
| 2834–2869 | Résultats | `earn-*`, `p-sig`, `p-ns` | earnings*, `_earn_*` / earnings.js ; SVG produit par `earnings_render.py` | `earn-card` maison |
| 2870–2972 | Menu en blocs, retour en haut | `mega-*`, `to-top` | base_v2 / shell.js | coque ; textes testés |

## 2. analysis.css

| Lignes | Bloc | Classes | Remarques |
|---|---|---|---|
| an:3–16 | Palette | `--ra-c1…8` (sombre / clair / clair auto) | hors jetons de patrick.css ; écrite en chaîne `var(--ra-cN)` (`analysis_kit.js:436`) |
| an:18–34 | Structure | `ra-section` (`scroll-margin-top:150px`), `ra-block`, `ra-subcard`, `ra-grid-2` (auto-fit 300), `ra-grid-3` (340), `ra-kpis`/`ra-kpi` (surcharge `.metric-grid`), `ra-chips`, `ra-empty` | gabarits du §0 (`class="card ra-section"`) + 16 scripts (analysis_kit, analysis_loader, analyses_hub, analyses_compare, carnet, diagnostics, donnees, drift_monitor, guardrails, journal, model_registry, risque, rl_analysis, run_analysis, run_analysis_more, variables) |
| an:36–55 | Graphiques SVG | `ra-chart(-wrap)`, `ra-png`, `ra-axis`, `ra-on-bar` (`fill:#fff`), `ra-tip` (fixed, z 1000), `ra-legend*`, `ra-swatch` | moteur SVG parallèle à chart_kit |
| an:57–64 | Contrôles | `ra-controls`, `ra-select/-num/-date` (rayon 6 px), `ra-range`, `ra-seg` | `.ra-seg` = copie de `.segmented` |
| an:66–87 | Chaleur, barres, lecture guidée | `ra-heat`, `ra-hbar*`, `ra-guide`, `ra-guide-ok/-warn/-info` | `"ra-guide-" + kind` (`model_registry.js:108`, `run_analysis_more.js:444`) |
| an:89–102 | Hub /analyses (en-tête trompeur) | `ra-filters` (carnet, derive, garde_fous, journal, modeles, variables), `ra-sortable` (▲▼ corrects ; 4 scripts), `ra-cell-link`, `ra-kind*`, `#ah-compare`, `ra-box` | 3 derniers morts ; 1 col. < 760 px |

## 3. knowledge.css

| Lignes | Bloc | Classes | Pages / remarques |
|---|---|---|---|
| kb:3–23 | Pastilles, parcours | `kb-level(-1..3)`, `kb-theme`, `kb-meta`, `kb-text`, `kb-quick`, `kb-search`, `kb-course-grid` (auto-fit 320), `kb-course-card`, `kb-matrix` | /connaissances, /connaissances/cours, /connaissances/dictionnaire ; niveaux 1/2 en `--pos`/`--warn` |
| kb:25–54 | Dictionnaire | `kb-filters`, `kb-chip(.is-active)`, `kb-letters`, `kb-letter`, `kb-term(:target)`, `kb-formula`, `kb-ref`, `kb-course-link` | /connaissances/dictionnaire / dictionary.js |
| kb:56–94 | Lecture | `kb-reader` (220-280px / 1fr), `kb-toc` (sticky `top:76px`), `kb-toc-item a.is-current`, `kb-toc-indent-N`, `kb-course-body` (titres, `pre.code-block`, `blockquote`, `math`, `.math-block`, `.anchor`), `tex-boxed`, `tex-unknown` | /connaissances/cours/{slug} / course.js ; HTML de `knowledge/markdown_lite.py` et `latex_lite.py` ; 1 col. < 960 px |
| kb:96–154 | Accueil `.kb-hub` (essai frontend-design, a2c03e8) | `kb-level-grid` (3 col.), `kb-level-card`, `kb-level-figure`, `kb-course-list`, `kb-course-facts` | /connaissances ; variables en ligne `--share`, `--step` (`knowledge_hub.html:22`), `--heat` (:69) ; `@container` 640 px ; redéfinit `.kb-course-card` (kb:19 vs 137) et recolore `.kb-level` |

## 4. Primitives de mise en page

- **2 colonnes asymétriques** : `.station-grid` 1,35fr/1fr (l. 1352), `.fund-ticket-grid` 1,5fr/minmax(280px,1fr) (2354), `.exp-sel-grid` minmax(260px,1.2fr)/minmax(220px,1fr) (2688), `.kb-reader` 220-280px/1fr (kb:57), `.sh-cols` 3fr/2fr (2557), `.mega-panel` 220-270px/1fr (2900).
- **Galeries `auto-fill/auto-fit`**, minimum de colonne : 110 (`asset-metric-grid`), 170 (`ra-kpis`), 220 (`exp-three`), 230 (`profile-grid`, `earn-grid`), 260 (`account-grid`, `exp-two`), 300 (`home-trio`, `ra-grid-2`), 320 (`kb-course-grid`), 340 (`ra-grid-3`, `exp-two-wide`), 360 (`asset-panel-grid`), 380 (`an-grid`) : dix valeurs pour le même motif.
- **« Libellé / barre / valeur »** : `.an-bars li` 200px/1fr/110px (2596), `.ra-hbar` minmax(120px,34%)/1fr/56px (an:73), `.fund-share` minmax(8rem,14rem)/1fr/auto (2387).
- **Paires clé-valeur `dl`** : `.rp-grid` (3 col.), `.pop-grid`, `.fund-preview-list`, `.earn-kv`.
- **Collants** : ticker `top:0` ; `.section-index`, `.fund-preview`, `.run-panel` calés sur `--stick-top` ; `.launch-bar` `bottom:0` ; `.kb-toc` `top:76px` (littéral).
- **Fixes** : `.run-panel` z 35, `.to-top` z 35, `.stats-bar` z 40, `.run-toasts` z 60, `.pred-pop` z 100, `.set-overlay` z 300, `.ra-tip` z 1000. Échelle sans jetons (feuille entière, 30 et 50 hors plage) : 1, 5, 6, 10, 30, 31, 35, 40, 50, 60, 100, 300, 1000.
- **Zones bornées** : `.exp-chips` 150, `.log-tail`/`.steps-list` 320, `.dq-scroll` 340, `.td-scroll` 420, `.config-dump` 480, `.cls-scroll` 560, `.queue-list` min(46vh,22rem), `.stats-bar-panel` 56vh.
- **Ruptures** : 1180, 1023 (tiroir), 980, 960, 900, 860, 760, 640, 480 (+ 560 en base, l. 1129) ; `min-width:900px` ; `@container` 340 et 640 ; `hover:none`, `pointer:coarse` (cibles 44 px), `print`.

## 5. Composants « réinventés »

| Composant de base | Réimplémentations dans les pages |
|---|---|
| Carte `.card` (`--radius-card` 20 px) | `.dash-panel` (l. 1363, `--radius-lg`), `.account-card` (2086), `.headline-metric` (2437, 12 px), `.adv-item` (2611, 10 px), `.profile-card` (2625, 10 px), `.earn-card` (2845), `.sh-item` (2565), `.fund-preview` (2355), `.set-overlay-box` (2414) |
| Bandeau encadré | `.scope-line` (1850), `.filter-bar` (1867), `.session-context` (1885) : même recette |
| KPI `.metric` | `.headline-metric` (1,9 rem), `.asset-metric-grid .metric`, `.ra-kpi`, `.account-value` (22 px), `.pp-quote-val` (26 px), `.sh-value`, `.kb-level-figure` |
| Badge `.status-badge`, `.tag` | `.kind-badge`, `.machine-kind`, `.adv-cost-*`, `.exp-chip-*` (aussi actualités), `.kb-level-*`, `.kb-theme`, `.kb-ref`, `.cls-sig-*` (4 px), `.kind-count`, `.kb-count` |
| Pastille de filtre `.kind-tab` | `.vocab-chip`, `.cls-chips .vocab-chip.active`, `.kb-chip.is-active`, `.exp-chip-btn`, `.macro-toc .tag` |
| Onglets / segments `.segmented`, `.section-index` | `.exp-tabs [role=tab]`, `.run-tabs a[aria-current]` (même soulignement réécrit), `.ra-seg` (rayon 8 px) |
| Boutons (2 niveaux, pilule) | `.queue-action` (rayon 7 px, 30 px de haut, 10 fichiers), `.launch-cancel` (rayon 8 px), `.queue-icon`, `.queue-toggle`, `.rows-toggle`, `.batch-main`, `.stats-bar-toggle`, `.run-toast-close`, `.pp-btn`, `.ra-legend-btn`, `.ra-png` ; MASTER l. 169 interdit les rayons de page |
| Tableau `.data-table` | `.set-paths` (2408), `.pop-track-table`, `.pop-matrix`, `.ra-heat`, `.history-table`, `.rp-table`, `.fold-table`, `.compare-rl-table`, `.pred-table` |
| Tri | `.data-table th[aria-sort]` (2764, cassé) et `.ra-sortable` (an:96-98) |
| Recherche | `.vocab-search`, `.kb-search`, `.table-tools input[type=search]`, `.ra-filters input[type=search]`, `.exp-sel-list input[type=search]` |
| Modale | `dialog.modal` (2118), `.history-dialog` (2264), `.set-overlay` (`div`, 2412) |
| Infobulle `.tip`, `.info-icon` | `.chart-tooltip`, `.pred-pop`, `.help-pop`, `.ra-tip`, `.q-mark`, `.help-q`, `.metric-help` (mort) |
| Bannière `.banner` (filet 3 px) | `.sh-rule`, `.sh-item`, `.td-plan`, `.trial-budget`, `.home-action`, `.ra-guide li`, `.run-toast-*`, `.adv-item.adv-top`, `.kb-course-body blockquote` |
| Progression, légendes, vides | `.progress-bar`/`.fund-share-bar`/`.an-bar`/`.ra-hbar-track` ; `.pp-legend`/`.ra-legend`/`.cmp-legend`/`.exp-legend`/`.earn-legend-row`/`.pred-legend` ; `.ra-empty`/`.machine-idle`/`.history-empty` vs `.empty-state` |
| Graphique (`PatrickPlot`) | SVG `ra-chart` (analysis_kit.js), `exp-heat`, `earn-chart`/`earn-spark` (Python), `shap-waterfall-svg` |

**Hétérogénéité chiffrée** (plage + 2 feuilles) : 49 valeurs de `font-size` écrites (46 après `.85rem` = `0.85rem`…), px, rem, em et `clamp()` mélangés, plus 24 raccourcis `font:` ; rayons littéraux 999px ×13, 8px ×12, 6px ×9, 50 % ×7, 10px ×7, 7/5/2px ×3, 4/12px ×2, 3px ×1, contre 41 usages de jetons `--radius*`. `.kb-hub .kb-quick button.primary { height: 48px }` (kb:105) déroge aux 38 px de MASTER l. 73.

## 6. Sélecteurs morts (preuves)

Zéro occurrence du jeton dans les gabarits, les scripts et les `.py`, et aucun préfixe dynamique.

| Sélecteur(s) | Lignes | Preuve |
|---|---|---|
| `nav.breadcrumb` + 4 descendants | 1836–1848 | hors CSS : commentaire `i18n.py:448` et clé inutilisée `breadcrumb_aria` (`i18n_legacy.py:380`), aucune classe ; `tests/test_ui_shell.py:69-71` interdit `class="breadcrumb"` |
| `.history-model-actions` (+ `form`, `input`) | 1524–1526 | 0 |
| `.asset-panel-symbol` | 1987 | 0 (la macro `asset_panel` ne l'émet pas) |
| `.sim-title`, `.sim-grid`, `.sim-panel-*`, `.sim-empty`, `.sim-graph-*`, `body[data-sim-loaded]`, `#sim-{equity,drawdown,dist}-canvas`, `#sim-{metrics,trades}-table`, `#sim-trades-download`, `.metric-row`, `.metric-help` | 2008–2076, 2145–2147 | 0 ; `simulate.html` est un ticket d'ordre ; `simulate.js` ne contient aucun `sim-` (en-tête l. 1-6). Seul `.sim-guard` (2032) vit (`feature_drift.js:31,63`) |
| `table .metric-label/-value` | 2080–2081 | probablement mort : les `.metric-label` restants sont des `div` (`_components.html:21`, `_earn_title.html:8-14`, `analysis_kit.js:353`, `asset_stats.js:81`) |
| `.grid-2`, `.grid-3` (responsive) | 2148, 2183 | 0 (`ra-grid-2/-3` sont d'autres jetons) ; bases l. 657-659 aussi inutilisées |
| `.example-picker select` | 2202 | 0 ; bases l. 986, 1056, 1079-1087 aussi |
| `.pop-track-table .err` | 2498 | aucune classe `err` dans `_pred_cell.html` ni `predictions_pop.js` |
| `.exp-chart`, `.exp-tip` | 2723, 2721 | 0 ; `charts.js:73,85` n'émet que `exp-chart-wrap` |
| `.ra-kind*`, `#ah-compare.disabled`, `.ra-box` | an:92–95, 100, 101 | 0 ; le hub n'utilise que `ra-section`, `ra-skeleton`, `ra-axis`, `ra-num` |

**Faux positifs à garder** (classe construite) : `step-warn/-error` (`app.js:326`), `cmp-s0..3` (`compare_rl.html:18,28`), `jr-*` (`_pred_cell.html:113`), `sh-ok/-warning/-disabled` (`_stats_help.html:16`), `adv-cost-low/-high` (`_retrain_advice.html:26`, `_profile_gallery.html:21`, `rl.html:66`), `home-action-*` (`synthesis.html:23`), `td-state-*` (`todo.html:51`), `run-toast-ok/-error` (`run_notify.js:48`), `cls-sig-*` (`asset_class.js:65`), `ra-guide-*`, `kb-level-1..3`, `kb-toc-indent-N`, `exp-chip-faded` (`exploration.js:184,338`), `sk-86`, `sk-94` (`_components.html:192`).

Volume mort ≈ 100 lignes, ≈ 6 % de la plage.

## 7. Anomalies factuelles

1. **Flèches de tri corrompues** (l. 2765-2766) : octet de contrôle U+0015 suivi du texte `B2`/`BC` (vérifié par `od -c`) au lieu de `\25B2`/`\25BC` (▲▼). Commit `a3b7424` (29/10). Touche tous les `table.data-table` triés par `table_tools.js`.
2. **Jetons inexistants**, couleurs figées dans les deux thèmes : `--error` (2780, repli `#d92d20`), `--warning` (2781, 2795, repli `#b54708`), `--accent-soft` (2811). `--run-panel-w` (2275, 2295) n'est posé nulle part.
3. **Couleurs littérales** : `#140E02` (1427), `rgb(0 0 0 / .45)` (2265), `rgba(0,0,0,.25)` (2749), `fill:#fff` (an:44) ; `--ra-c1/c2/c3/c5` (an:4-14) recopient en hexadécimal `--brand`, `--warn`, `--pos`, `--neg` des deux thèmes au lieu de les référencer.
4. **Décalages codés en dur** : `.kb-toc { top:76px }` alors que `--stick-top` vaut 89 px bandeau visible (l. 177-181, 1784) ; `scroll-margin-top` 80 (2527), 84 (kb:42, 71-74), 150 (an:18), 16 (1985).
5. **Ruptures incohérentes** : tiroir < 1024 px (2151) mais `.stats-bar { left:0 }` seulement < 861 px (2541) → entre 861 et 1023 px, barre décalée de 248 px (64 px rail replié, 2540) alors que la barre latérale est un tiroir (déduit du code).
6. **Empilement** sur /runs : `.run-panel` (`bottom:0`, z 35) sous `.stats-bar` (`bottom:0`, z 40), sans compensation (déduit du code).
7. **Doubles définitions** : `.settings-mode` (1090 et 1382, valeurs différentes), `.run-form[data-mode="simple"] details.adv` (1128 = 1395), `.section-index` (1909/1928), `.pp-ranges` (1688/1763), `.pp-stage` (1689/1767), `.exp-chart-wrap` (1748/2722), `.pop-track-table` (2348/2500).
8. **Globaux égarés** dans des sections de page : `.segmented`, `.section-index`, `.filter-bar`, `.scope-line`, `.kind-tabs`, `.data-table td.neg/.pos`, `.data-table th[aria-sort]`, `pre {}`, `.nowrap` ; 20 rustines `[hidden]`.
9. **Couleurs de sens en décor** (contraire à MASTER l. 25) : `.kind-alpha` en `--pos` (2467), `.cmp-s1/-s2` (2485), `.kb-level-1/-2`, `cls-sig-warning` pour une baisse (`app.py:1879-1882`).
10. **En-têtes trompeurs** : « /launch », « /commodities, /macro », « /simulate », « Exploration » ; préfixes `adv-` et `kind-` à double sens.
11. **Couplages fragiles** : marges négatives de `.launch-bar` (1405) = padding de `.dash-panel` (1365) ; `nth-child` de `.history-table-cls/-rl` (2241-2262, 2301-2309) liés à l'ordre des colonnes de `runs.html` ; styles par id (2396, 2404, 2649, 2743).
12. **Test rouge sur `main`** : `tests/test_ui_shell.py::test_templates_keep_only_data_driven_inline_styles` échoue à cause de `knowledge_hub.html:22,69` (relancé : `1 failed`).

## 8. Contrat à ne pas casser

**Textes CSS vérifiés littéralement par les tests**
- `test_machine_card_and_ticker.py:63` : `.station-side { grid-column: 2; display: flex; flex-direction: column;` ; `:158-160` : `@keyframes ticker-scroll`, `animation-play-state: paused`, `.ticker-track { animation: none` (réduction des animations), `--ticker-dir: reverse` ; `:166-173` : `\n.ticker {` avec `position: sticky` et `top: 0`, `:root:has(.ticker:not([hidden])) { --ticker-h: 33px; }`, aucun `top:` sur `--topbar-h`, au moins 3 sur `--stick-top`.
- `test_ui_lot_a.py:77` : `.to-top[hidden] { display: none; }`, `.to-top.is-visible` ; `:100-102` : `.kind-tab {` avec `var(--radius-pill)`, `.kind-tab.active { background: var(--brand);` ; `:106-107` : `content: counter(sec, decimal-leading-zero)`, `.section-index a[aria-current="true"]`.
- `test_help_minimal_text.py:49-58, 93` : `.help-folded { display: none !important; }`, `.help-pending :is(.hint, .page-subtitle…` identique à `STATIC` de help.js, `.help-q::before`, `.help-pop`, `.glossary-multi`.
- `test_ui_shell.py:69-71` (pas de `breadcrumb`), `:102-107` (styles en ligne).

**Classes attendues dans le HTML par les tests** (vérifiées dans `tests/`) : `dash-{settings,progress,machine}`, `station-side`, `queue-{panel,list,toggle}`, `#clear-queue-btn`, `steps-list`, `log-{tail,raw}`, `ticker-track`, `scope-{line,value}`, `asset-panel`, `account-card`, `filter-more`, `history-{table,table-cls,table-rl,section-title,row,more,pager,empties}`, `tag-{partial,suspect}`, `family-tabs`, `kind-{tabs,tab,count,hint,badge,directional,alpha}`, `run-panel`, `q-mark`, `pred-{legend,pop}`, `pop-{content,line,hit,track-4,matrix}`, `fund-{preview,row,panel,archived,breakdown,share}`, `is-selected`, `target-greyed-note`, `#benchmark-field`, `headline-metrics`, `cmp-{group,diff}`, `vocab-term`, `stats-bar`, `cls-{row,signals}`, `as-signals`, `advisor`, `profile-{gallery,card,name}`, `batch-gallery`, `help-q`, `notify-toggle`, `run-tabs`, `compare-tabs`, `home-actions`, `trial-budget`, `earn-{textarea,card}`, `#rl-form`, `mega-{trigger,panel,feature,col}`, `to-top`, `kb-{theme,search,course-card,term,formula,level-card}`, `tex-{boxed,unknown}`.

**Classes fabriquées hors gabarits** : JS — `pp-*` (chart_kit.js, dont `segmented pp-mode` l. 741), `ra-*` (16 scripts), `queue-{item,rank,name,icon}`, `machine-kind`, `dragging` (machine.js), `step step-{info,warn,error}`, `step-current`, `launch-cancel`, `target-short` (app.js), `has-run-panel`, `is-picked` (runs_panel.js), `run-toast*`, `table-tools*`, `help-{pop,folded,pending}`, `pred-pop`, `pop-rel`, `has-stats-bar-open`, `lazy-ready`, `cls-sig*`, `exp-chip exp-chip-{kind}` (`charts.js:46`, `analysis_kit.js:398`), `exp-{heat,axis,cell,two,three}`, `shap-*`, `kb-chip`, `is-current`. Python — `earnings_render.py` (`earn-{chart,tick,legend,legend-row,spark}`, `p-sig`, `p-ns`), `knowledge/markdown_lite.py` (`table-scroll data-table` l. 201, `code-block`, `math-block`, `anchor`), `knowledge/latex_lite.py` (`tex-boxed`, `tex-unknown`).

**Crochets d'état et variables** : `.run-form[data-mode="simple"]`, `.launch-bar[data-confirm]`, `.progress-bar[data-progress-mode="measuring"]`, `.pp-stage[data-zoomed="true"]`, `.drop-zone[data-over]`, `.drop-target[data-over]`, `.draggable-row[data-dragging]`, `.account-card[data-kind="fictive"]`, `.stats-bar[data-open="true"]`, `[data-kinds][hidden]`, `[data-help-host]`, `[data-help="fold"]`, `[data-keep]`, états ARIA `aria-current/-pressed/-expanded/-selected/-sort` ; variables `--share`, `--step`, `--heat`, `--enter-delay`, `--ra-c1…8` ; jetons lus par chart_kit.js : `--bg`, `--brand`, `--brand-soft`, `--chart-bg`, `--chart-grid`, `--line-strong`, `--mono`, `--neg`, `--neutral-soft`, `--pos`, `--text`, `--text-3`.

**Noms de fichiers** : `patrick.css` + `analysis.css` relus par `analysis_routes.py:217` ; `analysis.css` et `knowledge.css` liés par nom dans 16 gabarits.

## 9. Synthèse : 14 motifs de mise en page récurrents

| # | Motif | Primitives | Pages |
|---|---|---|---|
| 1 | Réglages + colonne latérale + barre d'action collante | `.station-grid`, `.dash-panel` empilés, `.launch-bar`, `details.adv` | /ml, /dl, /rl |
| 2 | Formulaire + aperçu collant | `.fund-ticket-grid`, `.fund-preview` sticky, `dl` | /simulate |
| 3 | Laboratoire : sélection + contrôles + onglets d'études | `.exp-sel-grid`, `.exp-controls`, `.exp-tabs` + `.exp-panel`, `.exp-two/-three` | /exploration, /econometrie |
| 4 | Tableau dense + filtres + panneau de détail | `.filter-bar`, `.kind-tabs`, `.history-table`, `.run-panel` fixe à droite | /runs ; variante sous le tableau sur /fonds (`.fund-row` + `.fund-panel`) |
| 5 | Tableau groupé par familles repliables | `.group-block`/`.cls-group`, `.scope-line`, zones bornées, puces | /predictions, /universe, classes d'actifs, /data-quality, /a-faire/{clé} |
| 6 | Page d'analyse longue à sections numérotées | `.section-index`, `.card.ra-section` chargées par JS, `.ra-kpis`, `.ra-controls`, `.ra-grid-*`, SVG | /runs/{id}/analyse, /runs?vue=analyses, /variables, /garde-fous, /analysis ; sans index : /risque, /diagnostics, /donnees, /derive, /journal, /carnet, /modeles, /analyses/comparer |
| 7 | Fiche détail (run ou actif) | `.session-context`, `.run-tabs`, `.section-index`, `.headline-metrics`, `.fold-block`, `.config-dump` ; `.asset-hero` + `.pp-quote` | /runs/{id}, /compare-runs, /targets/{symbole} |
| 8 | Galerie de graphiques | `.asset-panel-grid` (360), `.asset-panel`, `.asset-metric-grid` | /indices, /crypto, /fx, /rates, /commodities, /etfs, /macro (/equity : `group-block` seuls) |
| 9 | Galerie de cartes d'action | `.profile-grid` (230), `.account-grid` (260), `.earn-card` | profils et lots de /ml /dl /rl, /patrimoine, /mouvements, /simulate, /resultats |
| 10 | Tableau de bord d'accueil | `.metric-grid`, `.home-action` à filet, `.home-trio` (300), mini-tableaux | / (synthèse), aperçu de /fonds |
| 11 | Réglages en cartes empilées | `.card` + `.set-row`, `.set-paths`, `.set-overlay` ; `.earn-grid` | /reglages, /resultats |
| 12 | Page de lecture / lexique | `.kb-reader` (sommaire collant + corps 92 ch), `.kb-letters`/`.kb-term`, `.vocab-list` | /connaissances/cours/{slug}, /connaissances/dictionnaire, /vocabulary, /connaissances |
| 13 | Liste « libellé / barre / valeur » | `.an-bars`, `.ra-hbar`, `.fund-share`, `.progress-bar` | /analysis, pages d'analyse, /fonds, avancement de /ml /dl /rl |
| 14 | Couches flottantes de la coque | ticker, menu en blocs, `.stats-bar`, `.to-top`, `.run-toasts`, bulles, 3 modales | toutes les pages |
