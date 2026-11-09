# 06 — Contrat tests / JS / Python : ce que la refonte v4 ne doit pas casser

> Recherche préalable à la v4. Constat factuel, aucune décision. Worktree `C:/Users/leonp/PATRICK-wt-v4`, branche `feat/design-v4` (= `main`, `da5cdea`). Aucun fichier du code modifié.

**Abréviations.** Tests : `fichier:ligne` dans `patrick/tests/`, préfixe `test_` omis (`ui_shell:98` = `tests/test_ui_shell.py` l. 98). JS : `nom.js:ligne` dans `webapp/static/`. `css:N` = `static/patrick.css`. Dans les tableaux, `a/b` = « a ou b ».

**Méthode.** grep des assertions de `tests/*.py` (balises, `class=`, `id=`, `data-*`, `aria-*`, `.css`/`.js`, noms kebab-case) et lecture des 14 fichiers de garde-fous ; extraction scriptée des sélecteurs, `classList`, `className`, `dataset`, `*Attribute` et jetons de chaque script ; grep du HTML produit en Python ; croisement des 766 classes CSS avec JS, tests, Python, gabarits (§7). Limite : un sélecteur concaténé n'est vu que par son préfixe.

---

## 0. L'essentiel

- **Trois feuilles aux noms figés** : `patrick.css` (lue en texte par 4 fichiers de tests), `analysis.css`, `knowledge.css`. `patrick.css` + `analysis.css` sont recopiées dans le rapport d'analyse autonome (`analysis_routes.py:216`).
- **Une trentaine de fragments de `patrick.css` exigés mot pour mot** (§2.2) : réécrire la feuille, même à rendu égal, casse ces tests.
- **Nombreuses assertions sensibles à l'ordre des attributs et à l'imbrication** (regex non gourmandes jusqu'au premier `</div>`, `</nav>`, `</aside>`) : §6, premier risque d'un nouveau balisage de coque.
- **Le JS (56 des 58 scripts) dépend d'environ 200 ids, 140 attributs `data-*` et jusqu'à 338 classes** (§4) ; il **crée** ~200 classes (`pp-*`, `ra-*`, `exp-*`, `cmdk-*`, `queue-*`…) que le CSS doit continuer de styler.
- **Gabarits** : `style="…"` limité à 2 occurrences, aucun `<details open>` (sauf `filter-more`), aucun français en dur, aucune boîte native, `sidebar-nav` seulement dans `base_v2.html`.
- **323 classes ne servent qu'au style** (renommables en touchant gabarit + CSS) ; **32 classes sont mortes** (§7).

---

## 1. Fichiers et chargement

| Exigence | Test |
|---|---|
| `asset('x.js')` → `/static/x.js?v=<8 hex>` ; toute `src`/`href` `/static/*.js`, `*.css` de `/` versionnée | `ui_shell:30-50` |
| Versionnée : `immutable, max-age=31536000` ; `/static/patrick.css` nue : `no-cache` ; `/static/fonts/inter-latin.woff2` immuable | `ui_shell:54-60`, `refonte_pages:226` |
| `<script src="/static/help.js?v=` + `classList.add("help-pending")` inline ; `glossary.js` avant `help.js` | `help_minimal_text:30-33` |
| `<script src="/static/X.js?v=` : `confirm`, `machine`, `fonds`, `simulate`, `ml_rule` | `confirm_dialogs:46`, `machine_card_and_ticker:69`, `fund_fonds_page:43`, `fund_systematic:295` |
| `#instrument-names` avant `app.js` ; `names.js` avant `ticker.js` ; `machine.js` avant `app.js` ; `run_notify.js` une seule fois ; `macro_alfred.js` < 4 000 car. avant `</main>` | `instrument_names:117-123`, `machine_card_and_ticker:71`, `run_notify:28`, `macro_alfred_page:102` |
| Noms cités : `analysis_kit`, `analysis_loader`, `run_analysis(_more)` (pas `rl_analysis`), `analyses_hub`, `guardrails`, `carnet`, `exploration`, `drift`, `rl_compare`, `trial_budget`, `launch_batches`, `earnings`, `ticker` | `analysis_web:39-41,87`, `history_families:252`… |
| `node --check` de 27 scripts ; `chart_kit.js` exporte en CommonJS (`:928`) ses `_internals` (13 fonctions pures) ; `names.js` lit `#instrument-names` | `chart_kit_js:14-25`, `instrument_names:133-148`, `tests/js/*.test.js` |
| Rapport autonome : rien sous `/static/` après `</head>` ; `index.html` étend `launch_base.html` | `analysis_web:200`, `deep_config:101` |

## 2. Garde-fous globaux

### 2.1 Tous les gabarits
- `style="` seulement dans `_fund_overview.html:19` et `analysis.html:99` — `ui_shell:102-107` ; aucun `<details open>` sauf `filter-more` de `runs.html` — `details_closed_by_default:11-22`.
- Zéro français en dur, y compris dans `aria-label`, `title`, `placeholder`, `data-tip`, `data-confirm`, `alt` — `i18n_templates:57-120` ; ni `confirm(`, ni `prompt(`, ni `alert(` — `confirm_dialogs:26-38`.
- Source de `base_v2.html` : `<nav class="sidebar-nav"` sans `href="/` ; aucun autre gabarit ne contient `sidebar-nav` — `nav_registry:227-240`. Le popover du glossaire doit être dans cette même source (`id="glossary-search-input"`, `for=`, `id="glossary-search-status" class="glossary-search-status" role="status" aria-live="polite"`, `glossary-search-results`, `glossary-labels`) — `glossary_search:16-22`. **La nav latérale et le popover du glossaire ne peuvent donc pas sortir de `base_v2.html` (vers un include) ; le reste de la coque n'est testé que sur le rendu.**
- Clés lues par un script exposées par `i18n.js_strings` — `i18n_js_keys:36-48`, `analysis_web:126-133`.

### 2.2 Texte exigé dans `patrick.css`

| Fragment exigé | Ligne | Test |
|---|---|---|
| blocs `button.primary, .btn {` et `.btn-secondary, button.secondary {` → `border-radius: var(--radius-pill)` ; `.btn-arrow::after` ; `mask:` | 891, 920, 938 | `ui_lot_a:81-85` |
| bloc `\n.card {` → `var(--radius-card)`, `var(--shadow-card)` ; `--radius-card: 20px` ; **3** `--shadow-card:` | 725, 171, 86/119/153 | `ui_lot_a:93-96` |
| bloc `.kind-tab {` → `var(--radius-pill)` ; `.kind-tab.active { background: var(--brand);` | 2457, 2462 | `ui_lot_a:99-102` |
| `content: counter(sec, decimal-leading-zero)` ; `.section-index a[aria-current="true"]` ; `.to-top[hidden] { display: none; }` ; `.to-top.is-visible` | 1940-42, 2966-67 | `ui_lot_a:77,106-107` |
| `.help-folded { display: none !important; }` ; `.help-pending :is(.hint, .page-subtitle` ; `.help-q::before` ; `.help-pop` ; `.glossary-multi` | 2661-64, 1222, 1251 | `help_minimal_text:48-51,93` |
| liste de `.help-pending :is(…):is(` **identique, même ordre** que `var STATIC` de `help.js:17-18` | 2663 | `help_minimal_text:54-58` |
| `.station-side { grid-column: 2; display: flex; flex-direction: column;` | 1361 | `machine_card_and_ticker:63` |
| `@keyframes ticker-scroll` ; `animation-play-state: paused` ; `prefers-reduced-motion: reduce) { .ticker-track { animation: none` ; `--ticker-dir: reverse` | 1824, 1807, 1828, 1793 | `machine_card_and_ticker:158-160` |
| entre `\n.ticker {` et `\n.ticker[hidden]` : `position: sticky`, `top: 0` ; `:root:has(.ticker:not([hidden])) { --ticker-h: 33px; }` ; entre `\n.topbar {` et `\n.topbar-crumbs` : `top: var(--ticker-h)` | 1784-99, 458-72 | `machine_card_and_ticker:166-170` |
| aucun `top: … --topbar-h` ; ≥ 3 `top: … --stick-top` | 1911, 2272, 2356 | `machine_card_and_ticker:172-173` |

### 2.3 Sources JS lues en texte

- `help.js` (`help_minimal_text:36-86`) : `closest(".help-q")`, jamais `info-icon` ; `hasAttribute("aria-live")`, `("role")`, `("data-keep")`, `el.id`, `data-help") === "fold"` ; `var INLINE_MAX` (80–160), `var INLINE_CARD_MAX` (≤ 200), `INLINE_PAREN_MAX` ; `var SKIP_INSIDE` ⊃ `.pop-content .pred-pop td th summary` ; `function pageTitle`, `seen[key]`.
- `glossary.js` (`help_minimal_text:89-92`, `glossary_search:49-55`) : `function mergeIcons`, `details.adv`, `.adv-title`, `#selection-method-info`, `neighbourIcon`, `glossary-multi`, `normalize("NFD")`, pas d'`innerHTML`. `run_notify.js` : ni `innerHTML` ni `insertAdjacentHTML` (`run_notify:44-46`).
- `window.patrickDialog` + `form[data-confirm]` (`confirm.js`), `patrickDialog.confirm` (`wealth.js`), `window.PatrickMachine` ; `simulate.js` ⊃ `cfd-classes ticker-bank f-symbol-pick` ; `drift.js` ⊃ `vlines` ; `runs_panel.js` ⊃ `compare` — `confirm_dialogs:54-56`, `fund_simulate_page:85,107`, `history_webapp_smoke:431`, `analysis_compare:121`.

---

## 3. Contrat de balisage par zone

### 3.1 Coque (`base_v2.html`)

| Élément | Exigence exacte | Test |
|---|---|---|
| Nav latérale | `<aside class="sidebar"…</aside>`, `<nav class="sidebar-nav"…</nav>` ; groupes `<div class="sidebar-nav-group"[^>]*>(.*?)</div>` **sans div interne** ; texte d'en-tête nu (`[^<]*`) ; libellés `PILOTAGE` … `CLASSES D&#39;ACTIFS`, en anglais `ASSET CLASSES`, `>Overview<` | `nav_registry:135-165,243-249`, `ui_shell:83` |
| Catégories | `<button type="button" class="sidebar-nav-heading" id="nav-cat-{clé}" aria-expanded="true/false" aria-controls="nav-list-{clé}">` (ordre et fin exacts) ; `<ul class="nav-tree" id="nav-list-{clé}"` | `nav_registry:291-293` |
| Dossiers | `<li class="nav-folder" data-nav-key="pilotage/suivi" data-has-active>` puis `<button…aria-expanded="true"` ; fermé : `<button…aria-expanded="false"…>texte</button>` **sans balise enfant** puis `<ul class="nav-tree" id="nav-list-pilotage-signaux" hidden>` ; libellés `>Model tracking<`, `>Signals<`… | `nav_registry:280-285,296-299` |
| Liens | `<a href="…"` (href **premier** attribut), un par entrée, aucun autre `<a href` ; un seul `aria-current="page"` ; pages enfants allument leur entrée | `nav_registry:192-211`, `ui_shell:84`, `analysis_web:94-96` |
| Menu « Parcourir » | `<button type="button" class="mega-trigger" id="mega-trigger" aria-expanded="false" aria-controls="mega-panel"` ; `<div class="mega-panel" id="mega-panel"…hidden>` (hidden en dernier) ; fin = **première suite de 4 `</div>`** ; `<li><a href=` = toutes les entrées ; `<div class="mega-feature">` sans div interne, avec `nav_cat_desc_<cat>` et le lien de la 1re entrée ; `class="mega-col is-current"` | `ui_lot_a:33-70` |
| Fil de localisation | `<div class="topbar-crumbs">(.*?)</div>` sans div interne ; `<a class="crumb-entry" href="/universe">` ; ≥ 2 mots ; jamais `class="breadcrumb"` | `ui_shell:64-92` |
| Bandeau | `<div class="ticker" id="market-ticker"…hidden` quand vide ; avant `class="topbar"` ; `data-symbol`, `▲ +12.35%`, `▼`, `href="/targets/%5EN225"` | `machine_card_and_ticker:124-153` |
| Barre du haut | `id="nav-settings"` ; `#cmdk-data` JSON avec `"url": "/vocabulary"`, `/reglages`… | `settings_routes:60-62`, `refonte_pages:70` |
| Retour en haut | `<button type="button" class="to-top" id="to-top" aria-label="Retour en haut de la page"…hidden>` | `ui_lot_a:76` |
| Confirmation | `<dialog id="confirm-dialog" class="modal"` ; `confirm-message`, `confirm-ok`, `data-default-label` | `confirm_dialogs:44-49` |
| Divers | `stats-bar` sauf /ml /dl /rl ; `<script id="X" type="application/json">` (id puis type) ; classe `data-root-banner` | `refonte_pages:134`, `fund_support.py:82`, `data_root_unavailable:84` |

### 3.2 Composants partagés

| Composant | Exigence | Test |
|---|---|---|
| `lazy_block` | attribut `data-lazy-url` : le client de test suit ces URL comme le navigateur | `page_support.py:11-22` |
| `data_table` | appel `data_table(h, rows, collapse_after=5, more_label=…)` ; 6 lignes → ni `data-rows-toggle` ni `data-extra` ; 9 → 4 `data-extra` ; détail : ≥ 2 `data-extra hidden` | `refonte_pages:146-158` |
| Dates | `<td class="nowrap">AAAA-MM-JJ…</td>` | `ui_shell:98` |
| Badges | `<span class="status-badge status-ok/status-error">Ouvert/Fermé</span>` ; `status-ok">p=…`, `status-warning">p=…`, `status-error">suspect` (classe d'état en dernier) | `market_hours:129`, `predictions_page:120-125`, `refonte_pages:218` |
| Pastilles | `class="kind-tab active"` ; `<nav class="kind-tabs family-tabs"` ; `class="kind-count">N<` | `refonte_pages:207`, `history_families:119-120` |
| Info-bulles | `class="info-icon" data-term="…"` adjacents ; `data-term="…"` | `synthesis_webapp:150`, `dl_page:103`, `rl_page:99` |
| Divers | `class="section-index"` sans numéro écrit ; `primary btn-arrow` (/ml, /runs/run1) ; `#run-control-error` avec `banner-error` + `hidden` + `role="alert"` ; jamais `&lt;span` visible | `ui_lot_a:89-110`, `confirm_dialogs:61-63`, `class_balance:100` |

### 3.3 Pages

| Page | Exigences (ids sans `#`, classes sans `.`) |
|---|---|
| `/` | ids `market-state` ; `class="card first-run"` + lien `/ml?profile=quick` ; pas de `home-actions` — `synthesis_webapp:25,216`, `run_detail_method:98` |
| `/ml /dl /rl` | `id="run-form" data-mode="simple"` ; ids `settings-mode-toggle save-launch-profile launch-profile-list benchmark-field target-greyed-note steps-list log-tail trial-budget batch-gallery profile-gallery` ; `data-adv="section_*"` ; `<details class="log-raw">` ; options `value title data-first selected` ; `data-batch`, `data-gaps='…'`, `data-symbols='…'` (apostrophes) ; `<span class="profile-name">` — `synthesis_webapp:141-202`, `data_health:132`, `asset_classes:132`, `instrument_names:128`, `progress_steps:117`, `launch_batches:131-155` |
| Carte machine | `<section class="dash-panel dash-machine"` identique sur les 3 pages ; `queue-panel queue-list clear-queue-btn` ; `pause-run-btn stop-run-btn` dans `dash-progress` ; ordre §6 ; `queue-toggle queue-summary`, pas de `data-confirm` — `machine_card_and_ticker:24-78`, `run_controls:87-123` |
| `/dl`, `/rl` | `dl-networks` sans `class="adv"`, `name="dl_hidden_size" step min max value`, `launch-btn` + `disabled` — `dl_page:65-144` ; `id="rl-form" data-mode="simple"`, `<label data-algos="PPO"`, `data-actions`, `rl-launch` + `disabled`, `data-initial-run` — `rl_page:61-255` |
| `/runs` | `<section class="history-section" data-family=…>`, `history-table-cls/-rl`, `compare-runs-form`, `compare-rl-form`, `scope-value">0 / 3<`, `cmp-group`, `cmp-diff`, `<td class="num pk-mono best">`, `cmp-rl-data` — `history_families:83-383` ; `<tr class="history-row" data-run-id=`, `tag-partial`, `history-empties` + `data-keep`, `history-more`, `<nav class="history-pager"` — `history_light:59-260` ; `kind-badge kind-alpha`, `tag-suspect` — `refonte_pages:170-185` ; `?vue=analyses` (ids `carte algos rl`) — `analysis_web:85-107` |
| `/runs/<id>` | `id="kpi"` + `href="#kpi"` ; `headline-metrics` < `#resume` < `#folds` ; lazy `run-meta`, `run-advice` ; `avis`, `repartition`, `class-balance-warn` — `run_detail_kpi:48-54`, `refonte_pages:145`, `meta_labeling:68`, `class_balance:90-99` |
| Analyse | `ra-root`, `data-run-id`, `data-ra-mount="<section>"` ; `class="run-tabs compare-tabs"`, `data-run-ids` — `analysis_web:33-49`, `analysis_compare:96-134` |
| `/predictions` | `class="pop-line pop-hit">…`, un seul `class="pop-trigger q-mark"`, `class="pred-legend" data-keep`, `data-rel-target`, `pop-track-4`, `pop-matrix`, ≥ 7 `<th>` — `predictions_page:178-254`, `live_tracking:135-139` |
| `/targets/<s>` | `marche contexte alpha-models drift-chart`, `asset-panel`, lazy `asset-signals`/`news-feed`, pas d'`as-signals` à l'ouverture, `kind-alpha`/`kind-directional` — `asset_page:48-76`, `target_alpha_section:29-52`, `history_webapp_smoke:402` |
| Classes d'actifs | lazy `asset-class`, pas de `cls-row`/`cls-search` dans le cadre ; `data-class-key`, `class="cls-signals"` ; `id="asset-{slug}"`, compte exact de `class="card asset-panel"` — `asset_page:107-111`, `commodities_macro_pages:48-96` |
| `/simulate` | ids `new-strategy-dialog f-date f-symbol-pick f-symbol-manual`, `<option value=… data-opened=… selected>`, **exactement 2** `class="account-card"` — `fund_simulate_page:25-91` |
| `/fonds` | `class="fund-row` (compte), `fund-row is-selected`, `data-strategy-id`, ids `fund-panel fund-chart fund-classes`, `class="fund-position"`, `data-form`, `data-act` (`delete-position archive unarchive delete-strategy apply-rule delete-rule classes-* auto-*`), `fund-archived fund-breakdown fund-share fund-auto-rule fund-rule`, `colspan="13"`, `<dialog id="fund-rename-dialog" class="modal"`, `<select name="tier" data-cls-field>` — `fund_fonds_page:41-251`, `fund_rules_api:135-146`, `fund_asset_classes_routes:45-89`, `fund_autopilot_routes:134-216` |
| Patrimoine | `<span class="pos/neg">… € · … %</span>`, `data-movement-id`, `form add-movement`, `<select name="symbol" data-symbol-select>` — `wealth_webapp:61-183` |
| Savoir | `class="vocab-term"` (compte), `id="term-…"` ; 3 `card kb-level-card`, `kb-course-card`, `data-toc`, `<article class="kb-term"`, `kb-search kb-theme`, ≥ 90 `class="kb-formula"` — `refonte_pages:60-65`, `knowledge_routes:46-106` |
| Autres | `exp-assets`, 8 `role="tabpanel"` (`exploration_routes:59-63`) ; `eco-series` ; liens `target="_blank" rel="noopener noreferrer"` (`news_page:187`) ; `class="earn-card` ; `data-td-launch`, `class="td-pick"` ; `/analysis` : `modeles features series` ; `dx-root rk-root ag-root` |

**Formulaires.** `#run-form` est « soumis » par un analyseur HTML (`launch_batches:240-270`) : aucun `<form>` imbriqué, champs lus par `name`, `checked`, `selected`, `disabled`, `multiple` ; tous les `name=` sont lus par `forms.py`. Chaque `<input type="number">` de /ml respecte `value = min + k × step` (`launch_number_inputs_valid:21-43`).

---

## 4. JavaScript : dépendances au balisage

### 4.1 Coque (14 scripts sur toutes les pages, + `stats_bar.js` hors /ml /dl /rl)

| Script | ids | sélecteurs / classes posées | attributs |
|---|---|---|---|
| `shell.js` | `theme-toggle sidebar-toggle nav-open nav-scrim sidebar-tree nav-collapse-all nav-expand-all cmdk cmdk-input cmdk-list cmdk-open cmdk-data mega mega-trigger mega-panel to-top` | `.sidebar-nav-heading, .nav-folder-btn, .nav-leaf a` (`:80`), `.cmdk-item`, `.kbd`, `a.visually-hidden[href='#main']`, `.section-index a[href^='#']` ; `is-visible` | `data-theme data-sidebar data-nav-open data-nav-key aria-expanded aria-current` |
| `glossary.js` | `glossary-data glossary-labels glossary-popover(-title,-body,-close,-link) glossary-search-input/status/results` | `.info-icon`, `.adv-title`, `.adv-body`, `details.adv`, `#selection-method-info` | `data-term data-term-label data-open-term` |
| `help.js` | — | listes `STATIC` (`:17`), `HEADINGS` (`.dash-panel-title .page-title .group-title .card-title .adv-title`), `CONTAINERS` (`.card .dash-panel .panel`), `SKIP_INSIDE` (`.glossary-popover .cmdk .stats-bar .help-pop .info-pop .pop-content .pred-pop`), `.profile-name`, `.help-q` ; `help-folded help-pending` | `data-keep data-help data-help-host aria-live role` |
| `confirm.js` | `confirm-dialog confirm-ok confirm-message` | `form[data-confirm]`, `[data-close-dialog]` ; `btn-danger` | `data-confirm(-label,-danger) data-default-label` |
| `rows.js`, `table_tools.js`, `lazy.js` | — | `[data-rows-toggle]`, `tr[data-extra]`, `.rows-toggle-label` ; `table.data-table`, `.table-scroll`, `.no-table-tools` ; `[data-lazy-url]`, `.lazy-retry` | `data-more data-less data-tools data-label-* aria-busy` |
| `stats_bar.js`, `run_notify.js`, `ticker.js`, `market.js` | `stats-bar*`, `notify-toggle run-toasts`, `market-ticker ticker-track target_symbols rl-targets preview-chart preview-status preview-ranges news-list` | `.icon-bell-on/off`, `.ticker-viewport`, `.ticker-item`, `.range-btn` | `data-open data-run-id data-symbol data-period` |
| `asset_stats.js`, `shap_waterfall.js`, `names.js`, `chart_kit.js` | `instrument-names` | `.asset-panel[data-symbol]`, `.asset-panel-body`, `#shap-waterfall-widget[data-target]`, `button[data-days]` | `data-state data-zoomed` |

### 4.2 Pages

| Script | Dépendances principales |
|---|---|
| `app.js` | 33 ids (`run-form launch-btn status-panel progress-fill log-tail steps-list results-panel leaderboard-table target_symbols horizons…`), `details.adv`, `.adv-state`, `.launch-bar`, `[name=…]` ; pose `results-arriving flip-move target-short step-* adv-gate adv-tail` ; `data-mode data-progress-mode data-col data-k data-confirm data-modified data-first` |
| `machine.js` | `machine-card`, `li.queue-item`, `button[data-job-action]` ; crée `queue-*`, `machine-kind` ; `data-job-id data-paused` |
| `fonds.js`, `simulate.js`, `ml_rule.js` | ids `fund-*`, `ticket-form ticker-bank futures-data cfd-classes f-*`, `ml-rule-form` ; `.fund-row .fund-form-error .fund-auto .fund-archived`, `form[data-form]`, `[data-act]`, `[data-open-dialog]`, `[data-close-dialog]` ; ~35 `data-*` (`data-strategy-id data-kinds data-pup data-kind-hint data-rule-id…`) |
| `wealth.js`, `runs_panel.js` | `select[data-symbol-select]`, `.draggable-row`, `.drop-target`, `.drop-zone[data-import-account]`, `data-movement-id data-over` ; `run-panel* rename-*`, `.history-row`, `.history-table tbody`, `.compare-run-checkbox`, `data-run-id data-rename` |
| `rl.js`, `launch_batches.js`, `trial_budget.js` | `[data-algos] [data-actions]` ; `[data-batch] data-gaps data-symbols` ; `.trial-budget-lines/title/hint` |
| `asset_class.js`, `predictions_pop.js` | `#cls-search .cls-row .cls-signals[data-symbol] data-filter data-short` ; `.pop-trigger .pop-rel .pop-content data-rel-target` |
| `exploration.js`, `econometrics.js` | `.exp-tabs [role=tab]`, `.exp-panel`, `.exp-period-btns .range-btn`, `#eco-transform` ; `data-panel data-years` |
| Analyse (16 scripts) | racines `ra-root ah-* ac-* ag-* av-* ad-* am-* aj-* cn-* dg-* rk-* dx-*`, `[data-ra-mount]` |
| Savoir, divers | `#kb-search .kb-term .kb-chip[data-level]` ; `#vocab-search .vocab-term` ; `[data-toc] .kb-toc` ; `.td-pick [data-td-launch]` ; `.earn-card .earn-run data-study` ; `#alfred-* .lazy-block` ; `reglages.js` `[data-open]`, ids `pref-* path-*` |

### 4.3 Classes créées par le JS (à garder stylées)
`chart_kit.js` : `pp-*` (≈ 30 : `pp-btn pp-stage pp-legend pp-quote-* pp-tip-* pp-dot…`), `chart-tooltip preview-range-buttons range-btn segmented`. Analyse : ~60 `ra-*`, plus `metric* status-* exp-chip-* exp-heat* banner-* btn-secondary data-table table-scroll pk-mono hint skeleton-line rp-grid`. Coque : `cmdk-empty cmdk-group cmdk-item(-hint)` (`shell.js`), `glossary-multi glossary-search-result*`, `help-q help-pop`, `run-toast*`, `table-tools*`, `ticker-item movers-pick ticker-sym ticker-pct ticker-group`. `carnet.js` : `cn-note cn-<statut>`.

### 4.4 Jetons CSS lus par le JS
- `chart_kit.js:170-178` (accepte `--x` et `var(--x)`) : `--bg --brand --brand-soft --chart-bg --chart-grid --line-strong --mono --neg --neutral-soft --pos --text --text-3`.
- Pages : `--brand --text-3 --warn` ; **alias hérités** `--accent-ink --error-ink --color-warning --ink-2 --ink-text-2 --color-border --color-foreground` (`drift.js:33-34`) ; `--ra-c1…8 --pos-soft --neg-soft --warn-soft --surface-2 --surface-3 --text-2` (SVG d'analyse).
- Écrits par le JS : `--launch-bar-h` (`app.js:731`), `--ticker-duration` (`ticker.js:70`).

### 4.5 Globaux, événements, stockage
Globaux `PatrickPlot PatrickCharts PatrickNames PK patrickDialog PatrickHelp PatrickMachine PatrickTableTools I18N`, `window.DRIFT_*` (`target.html:235-238`). Événements `patrick:themechange` (`shell.js:26` → `chart_kit.js:911`), `patrick:content`, `patrick:run-context`. `localStorage` : `patrick-theme patrick-sidebar patrick-nav-tree patrick-notify* patrick-launch-* patrick-rl-* patrick-earn-enabled`. 14 blocs JSON (`i18n-data instrument-names cmdk-data glossary-* fund-* wealth-chart-data cmp-rl-data rl-initial-runs ra-embed futures-data cfd-classes ticker-bank`).

---

## 5. Python qui produit du HTML ou des classes

| Source | Produit |
|---|---|
| `icons.py:134-145` (`icon`, `nav_icon`) | `<svg class="icon {cls}" … stroke="currentColor" aria-hidden="true">` |
| `instruments.py:255-263` (`iname_tip`) | `<span class="instr" title="{symbole}">{nom}</span>`, exact (`instrument_names:103`) ; `instr` sans règle CSS |
| `earnings_render.py` (`earn_fmt earn_line earn_bars earn_spark`) | `span.na` (`:11`), `p-sig`/`p-ns` (`:38`), SVG `earn-chart`/`earn-spark`, `earn-tick`, `earn-legend(-row)`, couleurs `var(--brand --warn --pos --neg --text-3 --chart-grid --line-strong)` ; un `style="background:…"` en chaîne Python (`:100`) |
| `shap_chart.py:13-127` | SVG `shap-waterfall`, `role="img"`, couleurs **alias** `--color-accent --color-destructive --color-border --color-foreground --color-muted-foreground` (testées, `shap_chart:26,54`) |
| `_components.html` | `status-badge status-*`, `metric*`, `info-icon`, `data-table`, `num pk-mono`, `nowrap`, `rows-toggle*`, `headline-*`, `sparkline` (défaut `var(--accent)`, `:130`), `empty-state`, `asset-panel`, `lazy-block`, `skeleton-line sk-*`, `na` |
| `knowledge/markdown_lite.py:149-201`, `latex_lite.py:270-277` | `a.anchor`, `pre.code-block`, `div.math-block`, `div.table-scroll > table.data-table`, MathML, `tex-boxed`, `tex-unknown` |
| `analysis_routes.py:37-38,214-223` | export : concatène `patrick.css` + `analysis.css` et 4 scripts (ML) / 3 (RL) |
| Gabarits (valeur du domaine) | `status-{{ state }}`, `kind-{{ r.kind }}`, `adv-cost-{{ p.cost }}`, `td-state-…`, `sh-…`, `home-action-…`, `jr-…`, `kb-level-…` : le CSS doit couvrir chaque valeur |
| i18n | **aucun balisage** dans les textes (`<…>` = groupes de regex, `i18n_server.py:23,84,96`) |
| Hors interface | `tracking/report.py:406-407` : rapport CLI, `<style>` propre, palette en dur |

---

## 6. Assertions fragiles (cassent même à noms constants)

1. **Pas d'élément du même type imbriqué** : `div.sidebar-nav-group`, `div.mega-feature`, `div.topbar-crumbs` ; `nav.sidebar-nav` ; `aside.sidebar` ; `section.dash-panel`, `section.history-section` ; `form#run-form`.
2. **Menu en blocs** : sa fin = première suite de 4 `</div>` (`ui_lot_a:34`).
3. **Texte nu** : `sidebar-nav-heading`, `nav-folder-btn`, `kind-count">N<`, `scope-value">N / M<`, `status-…">texte`, `pop-hit">texte`.
4. **Ordre d'attributs** : tous les cas cités en §3 avec plusieurs attributs (`mega-trigger`, `… hidden>`, `sidebar-nav-heading`, `nav-folder`, `dialog id class`, `script id type`, `<a href … aria-current>`, `crumb-entry`, `history-row`, `info-icon data-term`, `value title data-first selected`, `data-act data-strategy-id`…).
5. **Classe exacte, sans ajout** : `account-card`, `fund-position`, `nowrap`, `card first-run`, `card asset-panel`, `cls-signals`, `pred-legend`, `run-tabs compare-tabs`, `log-raw`, `profile-name`, `kb-formula`, `vocab-term`, `fund-share`.
6. **Comptes et ordres** : 3 `--shadow-card:`, 8 `role="tabpanel"`, 2 `role="note"`, `colspan="13"`, AUC < F1 < DM p, `headline-metrics` < `#resume` < `#folds`, `dash-settings` < `station-side` < `dash-progress` < `dash-machine`.

---

## 7. Classes et ids renommables sans risque (style seul)

**Critère** : classe déclarée dans une des 3 feuilles, présente dans un gabarit, absente de tout `static/*.js` (préfixes dynamiques `status- banner- cls-sig- run-toast- step- ra-guide- exp-chip- cn-` compris), de `tests/` et du Python (`webapp/`, `knowledge/`). Renommer = gabarit(s) + CSS ensemble. Bilan des 766 classes : 338 citées par le JS (borne haute), 64 par les seuls tests, 9 produites par Python, **323 style seul**, 32 inutilisées.

- **Coque** : `app-shell main-column brand-mark brand-sub brand-text mark-head sidebar-footer sidebar-lang sidebar-tree-head sidebar-tree-title sidebar-tree-tools nav-label topbar-actions topbar-mega mega-caret mega-cols mega-eyebrow mega-feature-title mega-sub mega-subhead search-label search-trigger crumb-current icon-moon icon-sun cmdk-foot cmdk-input-row cmdk-panel stats-bar-caret stats-bar-hint stats-bar-label stats-bar-pick stats-bar-tools glossary-more glossary-search desktop-only mobile-only session-context`.
- **Composants** : `card-head btn-ghost row-end rows-toggle rows-toggle-caret empty-state-hint empty-state-title error-state error-state-message headline-metric headline-n headline-name headline-value fold-block fold-block-title fold-more lazy-skeleton sk-100 sk-70 sk-72 sk-80 sk-85 sk-86 sk-90 sk-94 sk-gap sk-gap-lg enter-60 enter-100 enter-140 enter-180 page-actions page-header section-index-label metric-grid-spaced hint-flush flush-top spacer subgrid subfieldset input-grow inline-form filter-bar filter-more-grid progress-bar is-applied is-empty block-note-marker group-block config-dump refresh-line`.
- **Pages (patrick.css)** : `account-grid account-name account-type account-value` · `adv-actions adv-changes adv-cost adv-cost-high adv-cost-low adv-diag adv-head adv-item adv-score adv-summary adv-top adv-unavailable` · `an-bar an-bar-fill an-bar-n an-bars an-chips an-grid` · `as-context as-funds as-peers as-section-title as-ts` · `asset-actions asset-hero asset-meta asset-panel-grid asset-panel-symbol` · `batch-card batch-main batch-title` · `cls-chips cls-group cls-prices cls-scroll cls-table cls-tools` · `cmp-legend cmp-rl-title cmp-swatch compare-rl-table compare-runs-table-wrap` · `dash-panel-body station-grid` · `dq-counts dq-item dq-item-head dq-reason dq-row-short dq-scroll dq-status` · `drop-zone-compact import-preview` · `earn-batches earn-card-head earn-confirm-table earn-grid earn-group earn-kv earn-meta earn-pair earn-params earn-row earn-row-warn earn-small-n earn-survives earn-toggle` · `exp-check exp-controls exp-out exp-params exp-period exp-sel-grid exp-sel-list` · `first-run-steps` · `fund-actions fund-check fund-choice fund-form-row fund-inline-form fund-ml fund-orders fund-rule-new fund-share-bar fund-ticker fund-ticket-grid` · `hc-actions hc-check hc-date hc-name` · `history-dialog history-dialog-actions history-empty history-filters history-pager-pos history-table-wrap` · `home-action home-action-error home-action-neutral home-action-warning home-actions-list home-card home-links home-mini home-trio` · `jr-direction jr-exact jr-mark jr-wrong` · `kind-rl launch-profiles macro-toc ml-kinds ml-model-field` · `pop-grid pop-journal pop-title pop-track pop-track-sub pop-track-table pop-track-title pred-arrows pred-table` · `profile-grid profile-main profile-meta queue-caret queue-head` · `recent-runs-foot recent-runs-list recent-runs-meta recent-runs-rel recent-runs-value` · `rp-foot rp-head rp-strong rp-sub rp-table rp-title rp-wide` · `scope-rel settings-mode shap-controls target-news target-preview` · `set-actions set-check set-current set-narrow set-news set-overlay set-overlay-box set-paths set-row set-status` · `sh-cols sh-disabled sh-item sh-item-head sh-list sh-ok sh-read sh-rule sh-steps sh-value sh-warning sh-what` · `td-actions td-detail td-pick-col td-plan td-scroll td-state-blocked td-state-pending td-state-replaced` · `vocab-chip vocab-chips vocab-link vocab-list vocab-tools`.
- **analysis.css** : `ra-export ra-filters`.
- **knowledge.css** (48) : `kb-also kb-back kb-col-rank kb-course-body kb-course-facts kb-course-grid kb-course-link kb-course-list kb-course-terms kb-courses-block kb-filter-label kb-filter-row kb-filters kb-foot-label kb-hub kb-letter-title kb-letters kb-level kb-level-1 kb-level-2 kb-level-3 kb-level-count kb-level-desc kb-level-figure kb-level-grid kb-level-rank kb-level-unit kb-levels kb-link kb-matrix kb-matrix-block kb-meta kb-quick kb-reader kb-ref kb-select-label kb-status kb-term-chips kb-term-foot kb-term-head kb-text kb-themes kb-toc-indent-1 kb-toc-indent-2 kb-toc-item kb-toc-list kb-toc-title kb-zero`.
- **Ids** : `card-share card-window card-performance` (`reglages.html:18,73,92`).

**Réserves.** (a) `sk-*`, `adv-cost-*`, `home-action-*`, `jr-*`, `sh-*`, `td-state-*`, `kb-level-*`, `kb-toc-indent-*` : préfixe renommable, suffixe = valeur du domaine. (b) `mega-cols`, `sidebar-tree-*`, `nav-label`, `crumb-current` : nom libre, imbrication non (§6). (c) Faux positifs du bloc « tests » : `brand`, `stack`, `main-content` n'y figurent que comme mots ou HTML de fixture (`db:258`, `history:148`, `text_fulltext:20`) : style seul aussi ; `advisor` n'est testé que par absence (`retrain_advisor:345`).

**Inutilisées** : `cmp-s0…cmp-s3 example-picker exp-chart exp-tip eyebrow grid-2 grid-3 history-model-actions icon-lg icon-sm is-link metric-help metric-row sim-empty sim-graph-container sim-graph-hint sim-graph-title sim-grid sim-panel-config sim-panel-distribution sim-panel-equity sim-panel-metrics sim-panel-trades sim-title` (patrick) ; `ra-box ra-kind ra-kind-dl ra-kind-ml ra-kind-rl` (analysis). `[data-sim-loaded]` (6 sélecteurs) n'est posé par aucun script ; les ids CSS `#sim-*` et `#ah-compare` n'existent dans aucun gabarit.

---

## 8. Écarts constatés

- `MASTER.md:15` cite 7 scripts « contrat » ; 56 dépendent du balisage, dont 14 sur toutes les pages.
- `_components.html:3-5` renvoie à `style.css` et `tokens.css`, qui n'existent plus.
- Les alias `--color-*`, `--*-ink` sont lus par `drift.js` et `shap_chart.py`.
- `markdown_lite.py:149` : `aria-label="Lien vers cette section"` en dur, hors i18n.
