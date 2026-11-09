# 01 — Coque de l'application (shell) : cartographie de l'existant v3

> Recherche préalable à la refonte v4 (« très pro, style Bloomberg, propreté d'Apple »). Constat factuel, aucune décision.
> Worktree `C:/Users/leonp/PATRICK-wt-v4`, branche `feat/design-v4` (= `main`, commit `da5cdea`). Aucun fichier du code modifié.

**Abréviations.** `base:N` = `patrick/patrick/webapp/templates/base_v2.html` ligne N ; `css:N` = `webapp/static/patrick.css` ; `shell.js:N`, `help.js:N`… = `webapp/static/` ; `nav:N` = `webapp/nav_registry.py` ; `icons:N` = `webapp/icons.py` ; tests dans `patrick/tests/`.

**Méthode.** Lecture du code. Les seules valeurs *mesurées* (§3.4) viennent d'une maquette statique de la barre du haut (même balisage que `base:135-196`, vraie feuille `patrick.css`, polices de repli) rendue dans Edge sans interface, dans des iframes de 320 à 1280 px. Le serveur n'a pas été lancé.

---

## 0. L'essentiel

- **Un seul gabarit de coque** : `base_v2.html` (296 l.), étendu directement par 44 gabarits (4 autres via `launch_base.html` et `asset_class.html`) ; seul `run_analysis_export.html` est autonome. Blocs offerts aux pages : `title`, `crumb_trail`, `session_context`, `content` (`base:16,176,204,205`).
- **Une seule source de navigation** : `nav_registry.py`, avec 6 catégories (`nav:52-59`), 5 dossiers (`nav:63-69`), 36 entrées (`nav:71-130`) et 3 pages utilitaires (`nav:134-138`). La barre latérale, le menu « Parcourir », le fil de localisation et la palette sont tous générés depuis ce registre (`base:44-46`).
- **État de la coque porté par `<html>`** : `data-theme`, `data-sidebar="collapsed"`, `data-nav-open`, classe `help-pending`. Les deux premiers sont posés avant le premier rendu par un script inline (`base:18-28`).
- **Bandeaux superposés** : bandeau des variations collant (z 31, 33 px) au-dessus de la barre du haut collante (z 30, 56 px). Tout élément collé dessous utilise `--stick-top` (`css:181`), ce qu'un test impose.
- **Les tests verrouillent du balisage exact** : ordre des attributs, absence de `<div>` imbriqué dans certains blocs, texte nu dans les boutons de catégorie et de dossier (§5). C'est la contrainte principale d'une refonte.

---

## 1. Chargement et ordre des scripts

- `<head>` inline (`base:18-28`) : pose `data-theme` / `data-sidebar` depuis `localStorage` (pas de flash) et ajoute `help-pending`.
- `<head>` (`base:29-41`) : préchargement Inter et JetBrains Mono ; `patrick.css`, `chart_kit.js`, `names.js` via `asset()` (URL `?v=<8 hex>`, `app.py:163-176`) ; JSON `#i18n-data` → `window.I18N` ; JSON `#instrument-names`.
- Après la nav (`base:94-109`) : script inline qui rejoue `localStorage['patrick-nav-tree']`.
- Fin de `<body>` (`base:281-294`) : `confirm.js`, `shell.js`, `run_notify.js`ᵈ, `rows.js`, `table_tools.js`ᵈ, `lazy.js`ᵈ, `glossary.js`, `help.js`, `market.js`, `ticker.js`ᵈ, `asset_stats.js`, `shap_waterfall.js` ; `stats_bar.js`ᵈ (`base:251`) sauf sur /ml /dl /rl (ᵈ = `defer`).

Ordres imposés par des tests : `glossary.js` avant `help.js` (`test_help_minimal_text.py:33`) ; `names.js` avant `ticker.js` et `#instrument-names` avant `app.js` (`test_instrument_names.py:115-123`). `market_state.js` ne fait **pas** partie de la coque : il est chargé par `synthesis.html:116` (hôte `#market-state`, `synthesis.html:111`).

---

## 2. Squelette DOM

```
html[lang][data-theme?][data-sidebar?][data-nav-open?].help-pending?
- body(.has-stats-bar-open?)
  - a.visually-hidden[href="#main"]  lien d'évitement (base:47)
  - div.app-shell  grille sidebar | colonne (css:247-253)
    - aside.sidebar#sidebar  (base:49-117)
      - a.brand > span.brand-mark(svg) + span.brand-text > span.brand-sub
      - div.sidebar-tree-head > span.sidebar-tree-title + span.sidebar-tree-tools > #nav-collapse-all, #nav-expand-all
      - nav.sidebar-nav#sidebar-tree > div.sidebar-nav-group[data-nav-key][data-has-active?] ×6
        - button.sidebar-nav-heading#nav-cat-<clé>[aria-expanded][aria-controls]
        - ul.nav-tree#nav-list-<clé> > li.nav-leaf > a[href][title][aria-current?] > svg.icon + span.nav-label
              ou li.nav-folder[data-nav-key="<cat>/<grp>"] > button.nav-folder-btn + ul.nav-tree[hidden?]
      - div.sidebar-footer > nav.sidebar-lang > a(fr|en)[.active] ; button.icon-btn.desktop-only#sidebar-toggle
    - div.nav-scrim#nav-scrim[hidden]  voile du tiroir (base:118)
    - div.main-column
      - div.ticker#market-ticker[role=region][hidden?] > .ticker-viewport > .ticker-track#ticker-track > ul.ticker-group
      - header.topbar
        - button.icon-btn.mobile-only#nav-open
        - div.topbar-mega.desktop-only#mega > button.mega-trigger#mega-trigger + div.mega-panel#mega-panel[hidden]
        - div.topbar-crumbs
        - div.topbar-actions > button.search-trigger#cmdk-open ; a.icon-btn#nav-<slug> ×3 ; #notify-toggle ; #theme-toggle
      - main.main-content#main > p.banner.data-root-banner? ; {% block session_context %} ; {% block content %}
  - div.cmdk#cmdk[role=dialog][aria-modal=true][hidden] > .cmdk-panel  (base:210-222)
  - script#cmdk-data (JSON)  (base:223-230)
  - aside.stats-bar#stats-bar  (sauf /ml /dl /rl)  (base:234-252)
  - div#glossary-popover.glossary-popover.hidden  (base:254-267)
  - dialog#confirm-dialog.modal  (base:268-277)
  - script#glossary-data, script#glossary-labels
  - button.to-top#to-top[hidden]  (base:280)
```

Le bandeau des variations et la barre du haut sont **dans** `.main-column` : ils ne passent pas au-dessus de la barre latérale.

---

## 3. Régions

### 3.1 Barre latérale arborescente

- **Rendu** : `nav_sections(path)` (`nav:220-236`) renvoie pour chaque catégorie non vide `entries` (liste plate) et `nodes` (feuilles + dossiers ; un dossier prend la place de sa première entrée, `nav:197-217`). Macro `nav_leaf` (`base:67`) : `<li class="nav-leaf"><a href title aria-current?>{{ nav_icon(slug) }}<span class="nav-label">`. Catégories toujours rendues ouvertes (`aria-expanded="true"`, `base:78`) ; dossier ouvert seulement s'il contient la page courante (`base:83-84`).
- **État actif** (`nav:178-184`) : `/` en égalité stricte, sinon préfixe de segment ou motif `child_routes` (`/targets/^VIX` allume Univers). Rendu : `aria-current="page"` → fond `--brand-soft`, icône `--brand`, filet gauche 2 px (`css:401-412`).
- **Icônes** : `NAV_ICONS` (`icons:87-131`), défaut `layers` (`icons:146-147`) pour `econometrics` et `earnings` (et `etfs` explicitement). Doublons : `book`, `compass`, `briefcase` (2 slugs chacun). Lucide, `stroke-width: 1.8` en CSS (`css:241`).
- **Géométrie** (`css:255-436`) : 248 px (`--sidebar-width`), collante, `height: 100vh`, seule `.sidebar-nav` défile ; lignes de 28 px, retrait `8px + --lvl×16px` ; en-têtes 11 px/650 capitales ; chevron CSS (`mask`) tournant de 90° ; guide d'indentation `::before` ; filet entre catégories. Outils `#nav-collapse-all` / `#nav-expand-all` visibles au survol ou au focus seulement (`css:312-313`).
- **JS** (`shell.js:75-129`) : lignes `ROW = ".sidebar-nav-heading, .nav-folder-btn, .nav-leaf a"` ; chaque `[data-nav-key]` pilote `:scope > button` et `:scope > ul`.
- **Clavier** (`shell.js:109-128`) : ↑ ↓ (lignes visibles, via `offsetParent`), Début / Fin, → ouvre puis entre, ← ferme puis remonte au parent ; Entrée / Espace = bouton natif ; ignoré avec Alt / Ctrl / Méta. Motif « disclosure » (boutons `aria-expanded` + `aria-controls`), pas de `role="tree"`. Focus : `outline 2px var(--brand)` intérieur (`css:395`).
- **Stockage** : `localStorage['patrick-nav-tree']` = `{"pilotage": true, "pilotage/suivi": false, …}` ; la branche active (`data-has-active`) ignore l'état sauvegardé (`base:100`).
- **Pied** : langue `/set-lang/fr?next={{ request.url.path }}` (`base:112-113`) : la chaîne de requête (ex. `?vue=analyses`) est perdue au changement de langue (`app.py:387-392`).

### 3.2 Rail replié (≥ 1024 px)

- `#sidebar-toggle` (`base:115`) bascule `data-sidebar="collapsed"` sur `<html>`, met à jour `aria-expanded`, écrit ou efface `localStorage['patrick-sidebar']`, puis émet `resize` après 220 ms pour les graphiques (`shell.js:44-57`).
- CSS (`css:438-452`) : grille 64 px (transition 200 ms) ; masque `.brand-text`, `.nav-label`, `.sidebar-tree-head`, `.sidebar-nav-heading`, `.nav-folder-btn`, `.sidebar-lang` ; **toutes** les listes forcées visibles : 36 icônes en lignes de 34 px, libellé en `title` natif seulement.

### 3.3 Tiroir mobile (≤ 1023 px)

- CSS (`css:2151-2178`) : grille à une colonne ; `.sidebar` en `position: fixed`, `width: min(300px, 86vw)`, `translateX(-102%)` ; `:root[data-nav-open] .sidebar { transform: none }` ; voile `.nav-scrim` (z 35, `--overlay`) ; les règles du rail sont annulées (`display: revert`).
- JS `setDrawer` (`shell.js:58-67`) : `#nav-open` ouvre (`aria-expanded`), clic sur le voile ou Échap (`shell.js:250-252`) ferme.
- **Constats a11y** : le focus n'est ni déplacé dans le tiroir ni piégé ; fermée, la barre n'est que translatée (pas de `visibility: hidden` ni `inert`), donc ses liens restent atteignables au Tab hors écran.

### 3.4 Barre du haut

- **Structure** (`base:135-196`) : `#nav-open` · `#mega` · `.topbar-crumbs` · `.topbar-actions` = `#cmdk-open` (`.search-label`, `.kbd` « Ctrl K », « ⌘K » sur Mac, `shell.js:256-259`), `a.icon-btn#nav-vocabulary|settings|diagnostics` (`utility_links`), `#notify-toggle` (`aria-pressed`, `.icon-bell-on/off`, `run_notify.js`), `#theme-toggle` (`.icon-moon/.icon-sun`, `css:538-544`).
- **Style** (`css:458-520`) : collante `top: var(--ticker-h)`, z 30, 56 px, fond `color-mix(--bg 82%)` + `backdrop-filter: blur(12px)` ; `.icon-btn` 32×32 ; `.search-trigger` `min-width: 240px`. Sous 1024 px : padding 16, recherche réduite à l'icône (`css:2179-2181`).
- **Thème** (`shell.js:17-41`) : `data-theme`, `localStorage['patrick-theme']`, événement `patrick:themechange` (écouté par `chart_kit.js:921`), préférence OS relayée sans choix explicite.
- **Mesures (maquette, voir Méthode)** :

| Largeur | Pointeur | `.topbar-actions` | `#nav-open` | `.topbar-crumbs` | Débordement page |
|---|---|---|---|---|---|
| 320 | fin | 226 px (78→304) | **18 px** (au lieu de 32) | 12 px (contenu 107) | aucun |
| 320 | grossier (règles `css:2198-2205`) | 286 px (66→**352**) | 18 px (au lieu de 44) | 0 px | **32 px** (`scrollWidth` 352) |
| 375 | grossier | 286 px | 18 px | 7 px | aucun |
| 1024 | fin | 430 px | — | 127 px (tronqué) | aucun |
| 1280 | fin | 430 px | — | 226 px | aucun |

Causes lisibles dans le code : 5 boutons d'icône fixes + la recherche + 2 écarts de 16 px (`gap: var(--space-md)`, `css:464`) ; `.icon-btn` n'a pas `flex: none`, donc le bouton menu est écrasé ; `.topbar-crumbs` a `min-width: 0` mais ni `overflow: hidden` (le texte déborde sur les actions) ni `aria-label`. En tactile, `.icon-btn { width: 44px }` (`css:2204`) pousse `.topbar-actions` 32 px hors de l'écran de 320 px.

### 3.5 Fil de localisation

- `ns.cat` / `ns.entry` = dernière entrée active (`base:44-46`). Rendu (`base:170-180`) : `<span>` catégorie (`| lower | capitalize`) + chevron + `<a class="crumb-entry">`, puis `{% block crumb_trail %}` rempli par la macro `crumb(libellé, lien)` (`_components.html:15`) dans 9 gabarits (analyses_compare, compare_rl, compare_runs, modeles, patrimoine_account, run_analysis, run_detail, target, todo).
- Sans entrée active (/reglages, /vocabulary, /diagnostics) : `span.crumb-current` = `<title>` sans « PATRICK — » (`base:178`).
- CSS (`css:472-485`) : 13 px `--text-3`, dernier enfant en `--text` gras et non cliquable. Ni `<nav>`, ni `aria-current`. Seul fil d'Ariane de l'application (MASTER).

### 3.6 Palette de commandes

- **DOM** (`base:210-222`) : `div.cmdk#cmdk[role=dialog][aria-modal=true][aria-label=cmdk_title][hidden]` > `.cmdk-panel` > `.cmdk-input-row` (icône, `input.cmdk-input#cmdk-input[role=combobox][aria-expanded=true][aria-controls=cmdk-list]`, `.kbd` Esc) + `ul.cmdk-list#cmdk-list[role=listbox]` + `.cmdk-foot`.
- **Données** (`base:223-230`) : JSON `#cmdk-data` = `[{url, label, group, slug}]`, entrées du registre puis utilitaires sous le groupe littéral `"PATRICK"`.
- **JS** (`shell.js:131-259`) : recherche sans accents ; score 4 préfixe du libellé, 3 sous-chaîne, 2 URL, 1 groupe, 0,5 sous-séquence (`shell.js:150-161`), plus large que MASTER. Items `li.cmdk-item#cmdk-item-N[role=option][aria-selected]`, `li.cmdk-group[role=presentation]` (sans saisie), `li.cmdk-empty`, `.cmdk-item-hint` (URL). **Icône clonée depuis la barre latérale** : `.sidebar-nav a[href="<url>"] svg` ou `#nav-<slug> svg` (`shell.js:139-142`).
- **Clavier** : Ctrl/⌘ K bascule partout (même dans un champ), `/` ouvre hors saisie, Échap ferme (et ferme le tiroir), ↑ ↓ circulaires, Entrée navigue, Tab bloqué dans le champ ; clic sur le fond ferme ; le focus revient à l'élément d'origine (`shell.js:215-254`). `aria-activedescendant` suivi.
- **CSS** (`css:557-610`) : fixe, z 100, panneau `min(620px,100%)` à 12vh, animation `cmdk-in` 160 ms ; champ 52 px, items 38 px.

### 3.7 Menu en blocs « Parcourir » (≥ 1024 px)

- **DOM** (`base:139-169`) : `div.topbar-mega.desktop-only#mega` > `button.mega-trigger#mega-trigger[aria-expanded=false][aria-controls=mega-panel][title]` (icône `grid`, `nav_mega_trigger`, `.mega-caret`) + `div.mega-panel#mega-panel[role=group][aria-label][hidden]` > `.mega-feature` (`.mega-eyebrow`, `p.mega-feature-title` = `nav_cat_desc_<clé>`, `a.btn.btn-arrow` vers la première entrée, `nav_mega_open`) + `.mega-cols` > `.mega-col(.is-current)` > `.mega-eyebrow` + `ul` > `li > a` ou `li.mega-sub > span.mega-subhead + ul`. Catégorie mise en avant = catégorie courante, sinon la première (`base:139`).
- **JS** (`shell.js:261-302`) : clic bascule ; survol seulement si `(hover: hover) and (pointer: fine)` (ouverture 140 ms, fermeture 260 ms) ; `pointerdown` hors du menu et `focusout` hors du menu ferment ; Échap ferme et rend le focus au bouton (`stopPropagation`) ; ↓ sur le bouton ouvre et focalise le premier lien.
- **CSS** (`css:2870-2942`) : bouton pilule 34 px ; panneau absolu z 60, grille `minmax(220px,270px) 1fr`, largeur `min(1040px, 100vw − sidebar − 56px)`, animation `rise` ; carte de gauche en dégradé de `--brand` ; colonnes `columns: 160px`.

### 3.8 Bandeau des plus fortes variations

- **DOM** (`base:121-134`) : rendu serveur depuis `movers_snapshot()` (garde `is defined`) ; `div.ticker#market-ticker[role=region][aria-label=movers_title][hidden si vide]` > `.ticker-viewport[title=movers_updated_at]` > `.ticker-track#ticker-track` > `ul.ticker-group` > `li > a.ticker-item.movers-pick[href="/targets/<symbole urlencodé>"][data-symbol][title]` > `span.ticker-sym` + `span.ticker-pct.movers-up|movers-down` (« ▲ +x.xx% » / « ▼ x.xx% », signal non coloré).
- **JS** (`ticker.js`) : `GET /api/movers` toutes les 5 min (30 s tant que vide) ; reconstruit seulement si la signature `symbole:pct` change ; duplique le groupe jusqu'à remplir la largeur, puis ajoute une copie `aria-hidden` aux liens `tabIndex=-1` ; vitesse 45 px/s écrite dans `--ticker-duration`. Sur /ml, /dl, /rl, un clic **ajoute** la cible à `#target_symbols` ou `#rl-targets` et émet `change` (`ticker.js:93-106`).
- **Écart** : la copie serveur affiche le **symbole** (`base:129-130`, `title` = nom), la copie JS affiche le **nom** (`PatrickNames.label`, `ticker.js:35`, `title` = symbole). Le premier rendu contredit donc la règle « le nom, jamais le symbole » de MASTER.
- **CSS** (`css:1777-1832`) : `--ticker-h: 33px` via `:root:has(.ticker:not([hidden]))` ; collant `top: 0`, z 31 ; mono 12,5 px ; `ticker-scroll` (−50 %), `--ticker-dir: reverse` (gauche → droite) ; pause au survol et au focus ; mouvement réduit : statique, défilement manuel, copie `aria-hidden` masquée.

### 3.9 Bandeau d'aide en bas de page et « ? » d'aide

**Bandeau d'aide statistique** (`base:232-252`, absent de /ml /dl /rl) : `aside.stats-bar#stats-bar[data-open][data-run-id]` > `button.stats-bar-toggle#stats-bar-toggle[aria-expanded][aria-controls]` (`.stats-bar-label` `sb_label`, `.stats-bar-hint` `sb_hint`, `.stats-bar-caret` ▴) + `#stats-bar-panel[hidden]` > `.stats-bar-tools` (`label.stats-bar-pick > select#stats-bar-run`, `#stats-bar-close`) + `#stats-bar-body[data-loading][data-error]`.
- JS (`stats_bar.js`) : `setOpen` pose `data-open`, `aria-expanded`, `hidden`, `body.has-stats-bar-open` ; fragment `GET /api/stats-help[?run_id=]`, liste `/api/stats-help/runs` ; run fixé par le menu, par `patrick:run-context` (`runs_panel.js:26`) ou par `data-run-id` ; Échap ferme si aucun `dialog[open]`.
- CSS (`css:2537-2570`) : fixe en bas, `left: var(--sidebar-width)` (64 px en rail), z 40 ; panneau `max-height: 56vh` ; `.main-content` reçoit 58vh de marge basse ouvert, 56 px sinon.
- **Écart** : `left: 0` seulement sous **860 px** (`css:2541`), alors que la sidebar devient un tiroir sous **1024 px** : entre 861 et 1023 px, vide de 248 px (ou 64) à gauche.

**« ? » d'aide (`help.js`)** : replie derrière un `button.help-q` les textes `STATIC` (`help.js:17-18`) de plus de `INLINE_MAX = 120` caractères (150 dans `[data-help-host]`) ; épargne `id`, `aria-live`, `role`, `data-keep` (sauf `data-help="fold"`) et `SKIP_INSIDE` (`.cmdk`, `.stats-bar`, `dialog`, `td`, `th`, `summary`…). Bulle `div.help-pop#help-pop[role=note]` (z 60), fermée par Échap, clic dehors, défilement, redimensionnement. Re-balayage sur `patrick:content` ; `help-pending` levé après le balayage ou 2,5 s (`help.js:172,252`). CSS `css:1202-1224`, `2660-2684`.

### 3.10 Retour en haut

- `button.to-top#to-top[aria-label=to_top][title][hidden]` (`base:280`), icône `arrow-up` 18.
- JS (`shell.js:304-325`) : visible au-delà de `max(600 px, 70 % de la hauteur)` (`hidden` retiré, puis `.is-visible`) ; clic : défilement doux (instantané en mouvement réduit), focus rendu au lien d'évitement.
- CSS (`css:2944-2972`) : fixe, droite 22 px, `bottom: 84px` (au-dessus du bandeau d'aide et de `.launch-bar`), z 35, rond de 44 px.

### 3.11 Autres pièces de la coque

- **Lien d'évitement** `a.visually-hidden[href="#main"]` (`base:47`). `.visually-hidden` (`css:2215-2221`) n'a pas de variante `:focus` : le lien reste invisible quand il reçoit le focus.
- **Bannière racine de données manquante** `p.banner.banner-error.data-root-banner[role=alert]` (`base:202-203`).
- **Boîte de confirmation** `dialog#confirm-dialog.modal` + `confirm.js` : `window.patrickDialog.ask/confirm`, `form[data-confirm]`, `data-confirm-label`, `data-confirm-danger` ; aucune boîte native.
- **Blocs différés** (`lazy.js`) : `[data-lazy-url]` → fragment, `aria-busy`, `.lazy-ready`, erreur `.banner-error` + `.lazy-retry` ; macro `lazy_block` (`_components.html:187-190`).
- **En-tête de page** (`css:612-653`) : `.page-header` (6 gabarits), `.page-actions` (4), `.page-title` 24 px/650 (46 ; 20 px sous 480 px), `.page-subtitle` 88ch (42, repliée par `help.js` si longue), `.eyebrow` (aucun). Le « ? » des textes d'en-tête s'accroche à `h1.page-title, main h1` (`help.js:24`).
- **Contenu** : `.main-content` `max-width: 1480px` (`--content-max`), padding 28/28/64 (20/16/48 sous 1024 px) (`css:548-555`, `2182`).

---

## 4. Tableaux transverses

### 4.1 Stockage navigateur

| Clé | Type | Valeurs | Écrit par | Lu par |
|---|---|---|---|---|
| `patrick-theme` | localStorage | `light` / `dark` | `shell.js:33` | `base:22` |
| `patrick-sidebar` | localStorage | `collapsed` / absent | `shell.js:52` | `base:24` |
| `patrick-nav-tree` | localStorage | JSON `{clé: bool}` | `shell.js:91` | `base:97`, `shell.js:79` |
| `patrick-notify` | localStorage | `1` / `0` | `run_notify.js:21` | `run_notify.js:20` |
| `patrick-notify-known` | sessionStorage | JSON | `run_notify.js:11` | `run_notify.js:10` |

Tous les accès sont protégés par `try/catch` : stockage bloqué = thème OS, sidebar dépliée.

### 4.2 Attributs d'état, événements, z-index

- `<html>` : `data-theme`, `data-sidebar="collapsed"`, `data-nav-open`, `.help-pending`. `<body>` : `.has-stats-bar-open`.
- Événements : `patrick:themechange` (window), `resize` synthétique après la bascule du rail, `patrick:content` (bloc différé rempli), `patrick:run-context` (document), `change` émis sur le sélecteur de cibles par le bandeau.
- Pile des z-index : en-tête de tableau 1 · `.launch-bar` 5 · `.section-index` 10 (`css:1911`) · topbar 30 · ticker 31 · `.nav-scrim`, `.to-top`, `.run-panel` 35 · `.sidebar`, `.stats-bar` 40 · `.tip` 50 · `.help-pop`, `.glossary-popover`, `.mega-panel`, `.run-toasts` 60 · `.cmdk` et bulle des prédictions 100 · `.set-overlay` 300 · info-bulle de /simulate (`css:2059`) 1000.

### 4.3 Points de rupture et préférences

| Condition | Effet sur la coque |
|---|---|
| `max-width: 1023px` (`css:2151`) | tiroir, `.mobile-only` visible, `.desktop-only` masqué (Parcourir, rail), topbar et contenu à 16 px, recherche réduite à l'icône |
| `max-width: 860px` (`css:2541`) | bandeau d'aide pleine largeur |
| `max-width: 480px` (`css:2189`) | titre de page 20 px |
| `pointer: coarse` (`css:2198`) | cibles de 44 px (`.icon-btn`, lignes de nav) |
| `(hover: hover) and (pointer: fine)` (JS, `shell.js:277`) | ouverture au survol du menu Parcourir |
| `prefers-reduced-motion` (`css:2135`, `1828`, `2970`) | animations coupées partout ; ticker statique ; défilement instantané |
| `prefers-color-scheme: light` (`css:122`, `541`) | thème clair si aucun `data-theme` |
| `print` (`css:2207`) | masque sidebar, topbar, ticker, cmdk, launch-bar (pas `.stats-bar` ni `.to-top`) |

### 4.4 Clés i18n de la coque

Gabarit : `skip_to_content`, `brand_tagline`, `nav_tree_title|collapse_all|expand_all`, `nav_home`, `sidebar_toggle`, `nav_open`, `theme_toggle`, `cmdk_title|placeholder|move|open`, `nav_mega_trigger|aria|open`, `nav_cat_<clé>`, `nav_cat_desc_<clé>`, `nav_grp_<clé>`, `nav_<slug>`, `movers_title`, `movers_updated_at`, `nt_toggle_off`, `app_status_data_missing`, `sb_label|hint|pick|close|loading|error`, `vocab_open_page`, `glossary_search_*`, `confirm_title|cancel|ok`, `to_top`. JS (`window.I18N`, liste `i18n.js_strings`, `i18n.py:761-811`) : `cmdk_empty`, `help_aria`, `movers_updated_at`. Sources : `i18n.py:450-472`, `i18n_ui.py:15-28`, `i18n_pages.py:90-116,408-414`, `i18n_models.py:29`, `i18n_notify.py:10-11`, `i18n_knowledge.py:11-12`. En dur : « Langue / Language » (`base:111`), « Close » et « × » du glossaire (`base:255`), « Ctrl K », « Esc », « ⌘K », groupe « PATRICK » de la palette.

---

## 5. Ce que les tests vérifient exactement

| Test (fichier:ligne) | Chaînes, classes ou motifs attendus |
|---|---|
| `test_ui_shell.py:29-60` | `asset()` → `/static/<f>?v=[0-9a-f]{8}` ; tout script/feuille de `/` versionné ; versionné → `immutable, max-age=31536000`, nu → `no-cache` |
| `test_ui_shell.py:64-71` | fil lu par `<div class="topbar-crumbs">(.*?)</div>` (**aucun `<div>` dedans**) ; aucun `class="breadcrumb"` sur 9 pages |
| `test_ui_shell.py:74-79` | `/targets/%5EVIX` : fil finit par « Univers Volatilité · VIX (S&P 500) » et contient `<a class="crumb-entry" href="/universe">` ; `/runs/run1/detail` contient « Historique », « VIX (S&P 500) », finit par « run1 » |
| `test_ui_shell.py:82-92` | `<aside class="sidebar".*?</aside>` : seul `/universe` porte `<a href="…"[^>]*aria-current="page"` ; chaque entrée hors `/` a un fil d'au moins 2 mots |
| `test_ui_shell.py:102-107` | `style="` seulement dans `_fund_overview.html` (1) et `analysis.html` (1) : **zéro style en ligne dans `base_v2.html`** |
| `test_nav_registry.py:53-127` | 6 catégories dans l'ordre, libellés FR ; slugs, URL, `order` uniques ; chaque URL en 200 ; aucune route GET orpheline |
| `test_nav_registry.py:134-148` | nav lue par `<nav class="sidebar-nav".*?</nav>` (**`class` en premier attribut**) ; groupes par `<div class="sidebar-nav-group"[^>]*>(.*?)</div>` (**aucun `<div>` imbriqué**) ; en-tête par `class="sidebar-nav-heading"[^>]*>([^<]*)<` (**texte nu, pas d'icône avant**) ; liens par `<a href="` (**`href` en premier**) |
| `test_nav_registry.py:151-240` | URL de chaque groupe dans l'ordre `order` ; `PILOTAGE` en premier ; `CLASSES D&#39;ACTIFS` ; catégorie vide absente ; chaque entrée liée une fois ; état actif sur 7 pages ; aucun `href="/` en dur dans `<nav class="sidebar-nav">` ; « sidebar-nav » dans aucun autre gabarit |
| `test_nav_registry.py:243-249`, `296-299` | anglais : `>Overview<`, `ASSET CLASSES`, `>Model tracking<`, `>Signals<`, `>Research<`, `>Data<`, `>Markets<` |
| `test_nav_registry.py:277-285` | `<li class="nav-folder" data-nav-key="pilotage/suivi" data-has-active>\s*<button[^>]*aria-expanded="true"` et `<li class="nav-folder" data-nav-key="pilotage/signaux">\s*<button[^>]*aria-expanded="false"[^>]*>[^<]*</button>\s*<ul class="nav-tree" id="nav-list-pilotage-signaux" hidden>` |
| `test_nav_registry.py:288-293` | `<button type="button" class="sidebar-nav-heading" id="nav-cat-{clé}" aria-expanded="(true|false)" aria-controls="nav-list-{clé}">` et `<ul class="nav-tree" id="nav-list-{clé}"` |
| `test_help_minimal_text.py:27-63` | `<script src="/static/help.js?v=` et `classList.add("help-pending")` sur 5 pages, après glossary.js ; `closest(".help-q")`, pas de `info-icon` ; gardes `hasAttribute("aria-live")`, `("role")`, `("data-keep")`, `el.id`, `data-help") === "fold"` ; CSS `.help-folded { display: none !important; }`, `.help-pending :is(.hint, .page-subtitle`, `.help-q::before`, `.help-pop` ; liste `STATIC` du JS = liste `:is()` du CSS ; `help_aria` = Aide / Help |
| `test_help_minimal_text.py:67-86` | `80 ≤ INLINE_MAX ≤ 160`, `INLINE_MAX ≤ INLINE_CARD_MAX ≤ 200` ; `SKIP_INSIDE` ⊇ `.pop-content, .pred-pop, td, th, summary` ; `function pageTitle`, `seen[key]` |
| `test_machine_card_and_ticker.py:119-153` | 8 pages : `id="market-ticker"` et `/static/ticker.js`, **avant** `class="topbar"` ; `data-symbol="NVDA".*?▲ \+12\.35%`, `data-symbol="GC=F".*?▼ -4\.50%`, hausses puis baisses, `href="/targets/%5EN225"`, heure présente ; vide ou sans global `movers_snapshot` → `<div class="ticker" id="market-ticker"[^>]*\bhidden\b` |
| `test_machine_card_and_ticker.py:156-173` | CSS : `@keyframes ticker-scroll`, `animation-play-state: paused`, `.ticker-track { animation: none` (mouvement réduit), `--ticker-dir: reverse` ; bloc `\n.ticker {` avec `position: sticky`, `top: 0` ; littéral `:root:has(.ticker:not([hidden])) { --ticker-h: 33px; }` ; bloc `\n.topbar {` avec `top: var(--ticker-h)` ; aucun `top:` sur `--topbar-h`, ≥ 3 sur `--stick-top` |
| `test_ui_lot_a.py:33-58` | panneau lu par `<div class="mega-panel".*?</div>\s*</div>\s*</div>\s*</div>` (**profondeur d'imbrication figée**) ; `<li><a href="…"` = toutes les entrées une fois ; `<button type="button" class="mega-trigger" id="mega-trigger" aria-expanded="false" aria-controls="mega-panel"` ; `<div class="mega-panel" id="mega-panel"[^>]* hidden>` ; `<div class="mega-feature">(.*?)</div>` contient `nav_cat_desc_<cat>` et `href` de la première entrée ; `class="mega-col is-current"` |
| `test_ui_lot_a.py:61-77` | `nav_cat_desc_*` FR ≠ EN ; anglais « Browse », « Open Overview », « Follow your models » ; `<button type="button" class="to-top" id="to-top" aria-label="Retour en haut de la page"[^>]* hidden>` ; CSS `.to-top[hidden] { display: none; }`, `.to-top.is-visible` |
| `test_ui_lot_a.py:105-117` | `content: counter(sec, decimal-leading-zero)`, `.section-index a[aria-current="true"]` ; `node --check shell.js` |
| autres | `test_settings_routes.py:58-62` (`href="/reglages"`, `id="nav-settings"`, `/reglages` dans `<script id="cmdk-data"…>`) ; `test_run_notify.py:25-29` (`id="notify-toggle"`, `run_notify.js` une fois, `<script id="i18n-data" type="application/json">`) ; `test_refonte_pages.py:131-136` (`id="stats-bar"` sauf /ml, `data-run-id`) ; `test_confirm_dialogs.py:41-48` (`<dialog id="confirm-dialog" class="modal"`, `confirm-message`, `confirm-ok`, `data-default-label="Confirmer"`) |

Aucun test ne s'exécute dans un navigateur : clavier, tiroir, palette, rail et responsive ne sont couverts par aucun test automatique.

---

## 6. Écarts et défauts constatés

1. Barre du haut à 320 px : 32 px de débordement en tactile, bouton menu écrasé à 18 px, fil réduit à 0-12 px (§3.4).
2. Bandeau d'aide décalé de 248 px entre 861 et 1023 px (§3.9).
3. Lien d'évitement invisible au focus ; tiroir fermé encore parcouru au Tab, sans gestion du focus (§3.3, §3.11).
4. Bandeau des variations : symbole au premier rendu, nom ensuite (§3.8).
5. Documentation en retard : `utility_links` décrit comme « pied de barre latérale » (`nav:132-133,188`) mais rendu dans la barre du haut (`base:185-188`) ; MASTER parle de « catégorie parmi les 4 » et d'une « 5ᵉ catégorie » (MASTER.md:120,135), le docstring de `test_nav_registry.py:2-3` de 4 catégories ; score de la palette plus large que MASTER (§3.6).
6. Icônes : deux slugs sans icône, trois glyphes partagés (§3.1). 7. Langue : chaîne de requête perdue (§3.1). 8. `.eyebrow` (`css:643-653`) inutilisée.

---

## 7. Opportunités à évaluer (sans décision)

**Barre de commande façon Bloomberg (mnémonique + `<GO>`).**
- *Existe déjà* : JSON `#cmdk-data` (url, label, group, slug), slugs uniques garantis par un test, `go()`, raccourcis Ctrl K et `/`.
- *Manque* : les slugs ne sont pas des mnémoniques courts (`knowledge_dictionary`) ; un champ dédié irait dans `NavEntry` (registre = seule source) ; les pages enfants n'en ont pas.
- *Attention* : place (fil réduit à 127 px dès 1024 px) ; garder `#cmdk-open`, `#cmdk`, `#cmdk-input`, `#cmdk-list`, `#cmdk-data`. Le mnémonique de la page pourrait précéder ou remplacer le fil.

**Barre d'état en bas.**
- *Données déjà servies* : `/api/run-state` (run actif, file), `updated_at` du classement, `/api/market-state`, `data_root_missing`, notifications, langue, thème.
- *Bas d'écran déjà occupé* : `.stats-bar` (fixe, z 40, absente de /ml /dl /rl), `.launch-bar` (/ml /dl /rl), `.to-top` (`bottom: 84px`), `.run-toasts`, marges `body.has-stats-bar-open` : à fusionner ou réordonner, avec un seul point de rupture.

**Barre latérale façon liste source macOS.**
- *Déjà proche* : en-têtes en petites capitales grises, outils au survol, sélection pleine `--brand-soft`, seule la nav défile, rail.
- *Différent* : guides d'indentation, chevrons des catégories, filet actif de 2 px, lignes de 28 px.
- *Attention* : tests sur le balisage exact des boutons (texte nu, ordre des attributs), pas de `<div>` dans `.sidebar-nav-group` ; la palette clone ses icônes depuis `.sidebar-nav a[href] svg` ; le rail exige 36 glyphes distincts (§6.6).
