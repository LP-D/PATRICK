# 02 — Jetons et composants de base (état des lieux avant la v4)

> Lecture seule du worktree `feat/design-v4` (= `main` @ `da5cdea`, 8 nov. 2026). Aucun fichier de code modifié.
> Chemins relatifs à `patrick/patrick/webapp/`. `patrick.css` = `static/patrick.css` (2 972 lignes, 133 865 octets).
> Comptages par script (regex). Un « usage » = une occurrence `var(--x)` **hors** blocs de définition l. 56-205. « Socle » = l. 1-1349.
> Contrastes : luminance relative WCAG 2.x, fonds translucides composés sur leur fond réel.

## 0. L'essentiel

1. **29 jetons de thème** (sombre l. 56-87 ; clair l. 89-120 ; copie du clair pour l'OS l. 122-155, identique), **20 jetons fixes** (l. 157-182), **19 alias hérités** (l. 184-204) ; `static/analysis.css:3-15` ajoute `--ra-c1…8`.
2. Seul `chart_kit.js` lit des jetons par `getPropertyValue` (12 noms en dur + tout `--x` passé par les pages, dont 7 alias via `drift.js`). `analysis_kit.js` et 16 autres scripts écrivent `var(--x)` dans du SVG/DOM ; 3 modules Python aussi.
3. `chart_kit.js` n'accepte que `#rgb`, `#rrggbb`, `rgb()/rgba()` pour l'opacité (`withAlpha`, l. 130-138) et que `#rrggbb` pour l'encre des pastilles (`inkFor`, l. 309-313) : un jeton en `oklch()`/`color-mix()` casserait aires, volumes et étiquettes.
4. Typographie sans échelle : 13 tailles dans les composants du socle, 42 écritures dans le fichier (px, rem, em), aucun style global `h2-h4`.
5. Espacements : 18 déclarations sur 115 passent par `--space-*` dans les composants du socle (75/661 dans le fichier). Rayons : 69 littéraux sur 117.
6. Doublons : `.settings-mode` (l. 1090 / 1382, valeurs divergentes), `.run-form[data-mode="simple"] details.adv` (1128 / 1395), `.section-index` (1909 / 1928).
7. Cascade involontaire : `.hint` (756) écrase taille, couleur et interligne de `.metric-reliability` (715), toujours posées ensemble.
8. Bogue visible : flèches de tri `.data-table` (2765-2766) = caractère de contrôle U+0015 + « B2 »/« BC ».
9. Accessibilité : `.range-btn.active` 4,45:1 et `.btn-danger` 3,16:1 en sombre, badges `status-disabled` < 4,5:1, liens non soulignés à 2,70:1 du texte, bordures de champs 1,5:1, focus quasi invisible sur `.glossary-search-result`.
10. Code mort : 8 alias, `--space-2xl`, 9 classes du socle, macro `error_state`.

---

## 1. Jetons

### 1.1 Mécanique des thèmes

- Sombre sur `:root` (`color-scheme: dark`, l. 57) ; clair sur `:root[data-theme="light"]` (l. 89) ou `@media (prefers-color-scheme: light) { :root:not([data-theme]) }` (l. 122). Copie manuelle : chaque valeur claire existe deux fois (idem soleil/lune l. 538-544, `--ra-c*` analysis.css:7-15). Aucun `@property`, `@layer`, `light-dark()`.
- `data-theme` posé avant rendu par `templates/base_v2.html:18-27` (`localStorage['patrick-theme']`) ; `shell.js:26` émet `patrick:themechange`, écouté par `chart_kit.js:920-925`.
- En dur hors CSS : `<meta name="theme-color">` (base_v2.html:14-15, suit l'OS, pas `data-theme`) ; favicon (base_v2.html:17) aux couleurs de `.brand-mark` (292-297).

### 1.2 Couleurs et ombres de thème (29)

« CSS » = usages dans patrick.css total/socle ; « Ailleurs » = analysis.css + knowledge.css (CSS), scripts (JS), gabarits et Python (HTML/Py).

| Jeton | Sombre | Clair | Rôle constaté | CSS | Ailleurs |
|---|---|---|---|---|---|
| `--bg` | `#0A0C10` | `#F5F6F8` | fond de page | 4/2 | JS 1, HTML 1 |
| `--surface` | `#111419` | `#FFFFFF` | cartes, tableaux, champs, popovers | 56/17 | CSS 5 |
| `--surface-2` | `#161A21` | `#F3F4F7` | en-têtes de tableau, survols, capsules | 50/19 | CSS 14, JS 1 |
| `--surface-3` | `#1D222B` | `#E9EBF0` | pistes, barres, reflet du squelette | 8/1 | CSS 1, JS 2 |
| `--overlay` | `rgba(4,6,10,.72)` | `rgba(15,18,25,.38)` | voiles (palette, dialogues, tiroir) | 3/1 | — |
| `--line` | blanc 7,5 % | `#E4E7EC` | filets, bordures de cartes | 78/24 | CSS 16 |
| `--line-strong` | blanc 14 % | `#CDD2DA` | bordures de contrôles, axe zéro | 34/14 | CSS 11, JS 17, Py 2 |
| `--text` | `#E8EBF0` | `#0F1419` | texte | 99/42 | CSS 12, JS 5, HTML 1 |
| `--text-2` | `#A3ABB9` | `#4A5261` | secondaire, libellés, `.hint` | 84/24 | CSS 20, JS 4, HTML/Py 2 |
| `--text-3` | `#7C8594` | `#6A7282` | métadonnées, repères de graphique | 70/32 | CSS 9, JS 52, Py 1 |
| `--brand` | `#5B8DEF` | `#2F5FD0` | liens, actif, primaire, courbe par défaut | 82/29 | CSS 22, JS 72, Py 5 |
| `--brand-strong` | `#7AA2F7` | `#244BAA` | survol de lien, dégradés primaire et progression | 3/2 | — |
| `--brand-soft` | marque 14 % | marque 9 % | fond actif, sélection de zoom | 17/7 | CSS 6, JS 3 |
| `--on-brand` | `#06080C` | `#FFFFFF` | texte sur primaire | 4/2 | CSS 2 |
| `--pos` / `--neg` / `--warn` | `#2FBF84` / `#F0616D` / `#E5A83B` | `#0B7A55` / `#C62834` / `#9A5B00` | gain / perte / alerte | 18/4, 26/10, 21/6 | JS 37 / 39 / 24, Py 3 / 1 / 2 |
| `--pos-soft` / `--neg-soft` / `--warn-soft` | 13 % / 13 % / 14 % | 9 % / 8 % / 9 % | fonds badges, bannières | 5/1, 5/3, 8/3 | JS 1 / 1 / 5 |
| `--neutral-soft` | blanc 6 % | `rgba(15,20,25,.05)` | badge neutre, `code`, bande | 6/5 | CSS 2, JS 10 |
| `--chart-grid` | blanc 6 % | `rgba(15,20,25,.07)` | grille de graphique | **0**/0 | JS 3, Py 1 |
| `--chart-bg` | `#0D1015` | `#FBFBFC` | fond des toiles | 5/0 | CSS 1, JS 1 |
| `--focus` | `#7AA2F7` (= `--brand-strong`) | `#2F5FD0` (= `--brand`) | anneau de focus | 9/1 | — |
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,.35)` | `0 1px 2px rgba(16,24,40,.06)` | KPI, boutons | 8/3 | — |
| `--shadow-md` | `0 4px 14px …,.38` | `0 4px 12px …,.08` | survol primaire | 3/1 | CSS 1 |
| `--shadow-lg` | `0 12px 32px …,.5` | `0 12px 28px …,.12` | popovers, info-bulles | 7/2 | — |
| `--shadow-xl` | `0 24px 64px …,.6` | `0 24px 56px …,.16` | carte cliquable, palette, dialogue, tiroir, menu | 5/2 | — |
| `--shadow-card` | `0 14px 44px …,.26` | `0 14px 40px …,.09` | toutes les `.card` | 1/1 | test |

### 1.3 Jetons fixes (20)

`--sans` (Inter, ui-sans-serif, system-ui… ; 9/4) ; `--mono` (JetBrains Mono, ui-monospace… ; 30/8, lu par `chart_kit.js`) ; `--space-xs/sm/md/lg/xl/2xl` = 4/8/16/24/32/48 px (usages 5, 16, 39, 17, 1, **0**) — pas de 12 px, pourtant 4e valeur littérale du fichier (64 occurrences) ; `--radius-sm/radius/radius-lg/radius-card/radius-pill` = 6/10/14/20/999 px (4, 25, 9, 2, 9) ; `--ease-out` `cubic-bezier(0.16, 1, 0.3, 1)` (61, seule courbe) ; coque : `--sidebar-width` 248, `--sidebar-collapsed` 64, `--topbar-h` 56, `--ticker-h` 0 (33 px via `:root:has(.ticker:not([hidden]))`, l. 1784), `--stick-top` = ticker + topbar, `--content-max` 1480.

### 1.4 Alias hérités (19, aucun usage CSS)

| Alias → cible | Lecteurs |
|---|---|
| `--color-background`→`--bg`, `--color-card`→`--surface`, `--color-primary`→`--surface-2`, `--color-secondary`→`--surface-3`, `--color-on-accent`→`--on-brand`, `--color-muted`→`--surface-2`, `--color-ring`→`--focus`, `--ok-ink`→`--pos` | **aucun** |
| `--color-accent`→**`--pos`** (vert, pas la marque), `--color-destructive`→`--neg`, `--color-muted-foreground`→`--text-2` | `shap_chart.py:13-17` |
| `--color-foreground`→`--text`, `--color-border`→`--line-strong` | `shap_chart.py`, `drift.js:34` |
| `--color-warning`→`--warn`, `--accent-ink`→`--brand`, `--error-ink`→`--neg`, `--ink-text-2`→`--text-2`, `--ink-2`→**`--surface-3`** | `drift.js:33-34, 84` |
| `--accent`→`--brand` | macro `sparkline` (`_components.html:130`) |

### 1.5 Catégorielles et orphelines

- `--ra-c1…8` : sombre `#5B8DEF #E5A83B #2FBF84 #C77DFF #F0616D #4CC9F0 #F7B267 #9BA3B4`, clair `#2F5FD0 #9A5B00 #0B7A55 #7B3FC4 #C62834 #0B7FA6 #B3541E #5B6372` (c1/c2/c3/c5 = marque/alerte/gain/perte). Lues par `analysis_kit.js:436` et 7 scripts.
- Locales : `--enter-delay` (675-682, 726, 2806), `--lvl` (coque), `--ticker-duration` (1791, écrite par `ticker.js:70`), `--ticker-dir` (1793).
- **Lues, jamais définies** (repli littéral permanent, insensible au thème) : `--run-panel-w` (2275, 2295 → 360px), `--error` (2780 → `#d92d20`), `--warning` (2781, 2795 → `#b54708`), `--accent-soft` (2811 → `rgba(37,99,235,.08)`). **Écrite, jamais lue** : `--launch-bar-h` (`app.js:731`).

---

## 2. Variables CSS lues par le JS (noms à conserver)

- **`chart_kit.js`** : `token(name)` = `getComputedStyle(documentElement).getPropertyValue(name).trim()` (l. 170-173, objet vivant mis en cache) ; `color(c)` (174-179) résout `"--x"` et `"var(--x)"`, défaut `--brand`. Noms en dur : `--brand` (175, 554, 570, 891, 894), `--brand-soft` (570), `--mono` (316, 348, 650), `--text-3` (348, 397, 403, 579, 590), `--chart-grid` (348), `--line-strong` (348), `--pos` et `--neg` (370, 520, 536 ; `--neg` aussi 554), `--neutral-soft` (392), `--chart-bg` (601), `--text` (606, 610), `--bg` (610). `withAlpha` sert l. 408, 431, 487 (aire), 541 (volumes), 591, 611. Polices de toile en dur `'600 11px '` / `'11px '` + `--mono`.
- **Passés à `PatrickPlot` par les pages** : `--brand` (market.js:45, asset_stats.js:35, fonds.js:60, wealth.js:345, econometrics.js, exploration.js), `--text-3` (fonds.js:61, wealth.js:346…), `--warn` (wealth.js:347), palette `drift.js:33-34` : `--accent-ink --error-ink --color-warning --ink-2 --ink-text-2 --color-border --color-foreground`.
- **`charts.js`** : aucune lecture ; `lineChart`/`barChart` (72-91) relaient `o.color`. Construit `.table-scroll > table.data-table`, `.info-icon`, `.exp-chip-*`, `num pk-mono pos|neg` (46-65).
- **`analysis_kit.js`** : couleurs SVG posées en style (`STYLE_ATTRS`, l. 10, 65), donc `var()` résolu sans redessin : `--chart-grid` (195, 202), `--line-strong` (205), `--brand` (238-273, 331, 386), `--neg` (273, 435), `--text-3` (283, 291, 313, 435), `--neutral-soft` (300, 308), `--pos` (435), `--ra-c1…8` (436). `exportPng` (145-158) recopie les styles calculés. `segmented()` (404-407) crée `.range-btn`/`.active` ; `kpi()` (352-355) crée `.metric`.
- **Autres** : `var()` dans 16 scripts (ajoutent `--brand-soft --neg-soft --pos-soft --warn-soft --surface-2 --surface-3 --text --text-2`) ; SVG serveur `shap_chart.py:13-17`, `earnings_render.py:60-136`, `rl_compare.py:13` ; export hors ligne `analysis_routes.py:217` (inline `patrick.css` + `analysis.css`).

**Liste à ne pas renommer** — thème : `--bg --surface-2 --surface-3 --line-strong --text --text-2 --text-3 --brand --brand-soft --pos --neg --warn --pos-soft --neg-soft --warn-soft --neutral-soft --chart-grid --chart-bg` ; fixes : `--mono --sans --ticker-duration` ; alias : `--accent --accent-ink --error-ink --ink-2 --ink-text-2 --color-accent --color-destructive --color-warning --color-foreground --color-muted-foreground --color-border` ; analyse : `--ra-c1`…`--ra-c8`.

---

## 3. Échelles réellement utilisées

### 3.1 Typographie

- Polices : Inter variable (`inter-latin.woff2` 48 Ko + `-latin-ext` 85 Ko, 100-900), JetBrains Mono variable (40 + 15 Ko, 100-800), `font-display: swap`, `unicode-range` (l. 16-47), préchargées (base_v2.html:29-30), pas d'italique. `html, body` 14px/1.55, `cv11 ss01 ss03` (212-223), donc 1rem = 14px. `code, .pk-mono, .num` : mono, `tabular-nums`, `"zero" 0` (228-232).
- Tailles des composants du socle : **24** (`.page-title` 627, 650 ; `.metric-value` 704, mono 600 ; 20/19 sous 480px), **18** (fermeture du glossaire), **15** (`.card h2`), **14** (base, `.page-subtitle`), **13.5** ×7 (`.card h3`, `.banner`, boutons, champs `.run-form`, `.adv-title`), **13** ×9 (tableaux, `.btn-ghost`, labels, champs `:where`, popover), **12.5** ×3 (`.hint`, textarea, readonly), **12** ×5 (`.metric-label`, `.table-footer`, `.tip`), **11.5** ×4 (`th`, `.status-badge`, `optgroup`, `.adv-state`), **11** ×8 (`.eyebrow`, `.tag`, `legend`, `.adv-gate`, glossaire), **10** (« ? »), `0.92em` (`code`).
- Graisses 600 (17), 650 (6), 500 (6), 550 (3), 400 (2), 700 (1) — 550/650 exacts seulement avec la police variable. Interlignes 1.55, 1, 1.6, 1.35, 1.25, 1.15, 1.45, 1.4, 1.5. Approche −0.02em (titre, KPI), −0.011em (`h1-h4`, 239), 0.01em (`th`), 0.04em, 0.08em (majuscules).
- Aucune taille globale pour `h2/h3/h4` hors `.card` : taille du navigateur ou 11 règles locales (12.5px à 17px, l. 2128-2852). Fichier : 42 écritures, dont 20 en `rem`/`em` (doublons `.85rem`/`0.85rem`, `.95rem`/`0.95rem`, `.8rem`/`0.8rem` ; `.headline-value` 1.9rem l. 2440).

### 3.2 Espacements, hauteurs, rayons, ombres

- Espacements (socle) : 8px (21), 12 (12), 6 (11), 14 (9), 10 (9), 16 (7), 4 (7), 7 (6), 18 et 9 (4). Paddings types : KPI 16/18, carte 22/24, cellule 9/12, bannière 12/14/12/16, état vide 22, champ 7/10, bouton 0/18.
- Hauteurs (aucun jeton) : boutons 38, champs 36 (min), bouton nu 34, `.btn-ghost` 30, primaire de tableau 28, `.range-btn` 26 (1652), badge 22, `.tag`/`.adv-gate` 20, `.info-icon` 16 (cible 36), `.adv-summary` 42 ; 44 en pointeur grossier (2198-2205).
- Rayons (socle) : `--radius` 5, `8px` 5 (champs, bouton nu, `.adv-summary`, `.tip`), `4px`, `5px`, `6px` 3 chacun, `10px` 2 (= `--radius` en dur), `999px` 1 (badge), `7px` 1 (`.btn-ghost`), pilule 2, `--radius-lg` 1, `--radius-card` 1. Fichier : 48 via jeton sur 117.
- Ombres composites en dur : anneau de champ `0 0 0 3px color-mix(… --brand 22%, transparent)` (1031, 1059), reflet primaire `inset 0 1px 0 rgba(255,255,255,.16/.2)` (907, 910, deux thèmes), filet `inset 3px 0 0 var(--brand)` (801).

### 3.3 Mouvement, couches, ruptures

- Durées : 100 ms (survol de cellule 792), 120 ms (champs, `.adv-summary`, `.info-icon`, opacité `.tip`), 140-160 ms (popovers, chevron), **300 ms** (KPI 691, cartes 735, boutons 908/934, flèche 946). `--ease-out` partout, `linear` pour opacités et squelette.
- Animations : `rise` (718-721, opacité + `translateY(6px)`) sur chaque `.metric` (360 ms, décalage 0/35/70/105/140 ms, 675-679) et chaque `.card` (340 ms) ; `skel` 1,6 s (867) ; popover en `allow-discrete` + `@starting-style` (1239-1247). Réduction globale `prefers-reduced-motion` (2135-2142).
- Couches : `th` collant 1, `.tip::after` 50, `.glossary-popover` 60. Ruptures : 1180 (`.grid-3`), 1023 (grilles en 1 colonne, `.adv-state`), 560 (`.settings-mode`, `.launch-profiles`), 480 (KPI 2 colonnes, carte 16px, `.filter-bar` en colonne), `pointer: coarse`, `print` (2207-2211).

---

## 4. Familles de composants

**Socle (207-243) et utilitaires.** `a` marque **non soulignée** (225-226) ; `:focus-visible` 2px `--focus`, décalage 2px, `border-radius: 4px` (237) ; `.icon` 16px trait 1.8, `.icon-sm` 14, `.icon-lg` 20 (241-243). Utilitaires 655-665, `.nowrap` (1683), `.visually-hidden .hidden` (2213-2222, dits « last » alors que 750 lignes suivent), `.sk-*`, `.enter-*` et consorts (2799-2813). `icons.py:134-142` émet `width/height="{size}"` et `stroke-width="2"`, mais `.icon` impose 16px et 1.8 : les 27 appels à 13/14/15/18px des gabarits sortent en 16px (seule exception `.drop-zone .icon`, 2113).

**En-tête de page (612-653).** `.page-header` (6 gabarits), `.page-actions`, `.page-title` 24/650/1.25 (49 occurrences), `.page-subtitle` 88ch 14/1.6 `--text-2`, `.eyebrow` (0 usage).

**KPI (667-721 ; 2189-2192 ; variante `.asset-metric-grid .metric` 1990).** `.metric-grid` `auto-fit minmax(210px,1fr)` ; `.metric` padding 16/18, `--line`, `--radius-lg`, `--surface`, `--shadow-sm`, `rise`, survol `--line-strong` sur un élément non cliquable ; `.metric-label` 12/500 `--text-2` ; `.metric-value` mono 24/600 ; états `status-ok|error|warning` (pos/neg/warn), `status-pending|disabled` (`--text-3`), `neutral` sans règle. Macro **`metric(label, value, reliability, state='neutral')`** (`_components.html:19-25`, 108 appels) → `div.metric > .metric-label + .metric-value.pk-mono.status-{state} + .metric-reliability.hint`. Balisage recopié dans `analysis_kit.js:352-355` (avec `data-keep`), `asset_stats.js:81-82` (**sans fiabilité**), `_earn_title.html:9-13`.

**Cartes (723-757).** `.card` padding 22/24, `--radius-card`, fond `color-mix(--surface-2 45 %, --surface)` → `--surface` à 70 %, `--shadow-card`, `rise` 340 ms ; survol réservé à `a.card`/`.card.is-link` (bordure marque 45 %, `--shadow-xl` ; `.is-link` inutilisée). `.card h2` 15/600, `.card h3` 13.5/600, `.card-head`, adjacences `.hint`/`.table-scroll`/`.empty-state` (752-754) ; `.hint` 12.5/1.55 `--text-2` (756) et `.na` (757) vivent ici.

**Tableaux (759-805 ; tri 2758-2767 ; plis 2436-2452).** `.table-scroll` (défilement interne, `--radius`) ; `.data-table, table.leaderboard` 13px ; `th` collant, 9/12, `--surface-2`, 11.5/600 ; `td` 9/12, survol de ligne 100 ms ; `td.num/th.num` à droite (`.data-table` seulement), `th.num/th.pk-mono` remis en sans ; liens `--text`/500 ; `tr.best` 600 + marque 6 % + filet 3px ; `.table-footer` 12px `--text-3`. Tri : `table_tools.js:79-81` pose `aria-sort`. Macro **`data_table(headers, rows, empty_message=none, row_classes=none, num_cols=none, footer=none, collapse_after=none, more_label=none, less_label=none)`** (61-87, 35 appels) : `num_cols` → `num pk-mono`, date → `nowrap`, cellules en `| safe` (échappement à la charge de l'appelant, 43-57), repli au-delà de `collapse_after + 1` lignes (`has-collapsible-rows`, `tr[data-extra][hidden]`, `button.rows-toggle[data-rows-toggle]`, `rows.js`), sans ligne : `<p class="hint">` et non `.empty-state`. **`fold_metrics_table(block, labels, collapse_after=5)`** (92-115) : `.fold-block`, `.fold-table`, `tr.fold-mean`, `.headline`. Même balisage construit par 10 scripts (charts.js:63, analysis_kit.js:375, asset_stats.js:64, feature_drift.js:34-36, market_state.js:38-40, drift_monitor.js:60, guardrails.js:133, model_registry.js:69…).

**Badges (807-842).** `.status-badge` 22px, rayon 999px en dur, 11.5/600, point `::before` 6px ; variantes `status-ok|error|warning|pending|disabled|neutral` = fond `*-soft` + texte coloré (`pending` = marque). `.tag` 20px, rayon 5, mono 11. Macro **`status_badge(label, state='neutral')`** (12, 59 appels) ; aussi feature_drift.js:49, market_state.js:56. Variantes `.pred .status-badge` (2317), `.pred-pop .status-badge` (2345). Système parallèle `.exp-chip(-pos|-ok|-neg|-warn|-faded)` (2725-2729, `charts.js:46`).

**Vide, erreur, chargement (844-867 ; 2653-2657).** `.empty-state`/`.error-state` (tirets `--line-strong`, fond `--surface-2` 55 % ; erreur : bordure `--neg` 45 %, `--neg-soft`), `-message`, `.empty-state-title/-hint` (runs.html seul), `.skeleton-line` 12px `skel`. Macros **`empty_state(message, hint='', action_url='', action_label='')`** (144-151, 22 appels, action en `a.btn-secondary`), **`error_state(message, hint='')`** (153-158, **0 appel**), **`lazy_block(url, lines=6, label=none, retry=none)`** (187-195, 19 appels : `.lazy-block[data-lazy-url][aria-busy][aria-live=polite] > .lazy-skeleton[role=status] > .skeleton-line.sk-NN.sk-gap-lg` ; erreur → `.banner.banner-error`, `lazy.js:24`), **`asset_panel(symbol, label, slug, note='', href='')`** (172-181, 3 appels, `label` inutilisé).

**Bannières (869-887).** `.banner` filet gauche 3px, `--radius`, 13.5/1.55 ; `.banner-error|warning|info` (bordure 40/40/35 %, fond `*-soft`). Pas de macro : 31 gabarits et 21 scripts écrivent `banner banner-error` (souvent `role="alert"`). `help.js:17-18` replie `.banner:not(.banner-error):not(.banner-warning)` au-delà de 120 caractères. `span.class-balance-warn` (885) y est rangée par erreur.

**Boutons (889-960, 1033-1048).**

| Variante | Lignes | Aspect | États | Usages |
|---|---|---|---|---|
| `button.primary`, `.btn` | 891-919 | 38px, pilule, dégradé `--brand-strong` → `--brand` → marque + `#fff`, `--on-brand` 13.5/600 | survol `brightness(1.1)` ; actif `translateY(.5px)` ; `:disabled` | `primary` 16, `btn` 31 |
| `.btn-secondary`, `button.secondary` | 920-936 | 38px, pilule, `--line-strong`, fond texte 6 % | survol ; **pas de `:disabled`** | 82 / 0 |
| `.btn-arrow::after` | 938-948 | flèche en masque SVG | +3px au survol | 3 |
| `.btn-ghost` | 949-957 | 30px, rayon 7px, `--text-2` 13/500 | survol `--surface-2` | 22 |
| `.btn-danger` | 958-959 | `--neg` + `#fff` | survol `--neg` 85 % + `#000` | `confirm.js:42` sur `#confirm-ok.btn` |
| `button:not([class])` | 1033-1047 | 34px, rayon 8, `--surface` | survol | 3 boutons nus |
| `.data-table button.primary` | 1048 | 28px, 12px | — | — |

`.btn-primary` (_earn_confirm.html:33) n'a pas de règle ; `<a class="primary">` (knowledge_courses.html:17) n'est pas stylé (sélecteur qualifié `button`). `.icon-btn` : coque (488-501).

**Formulaires (962-1200).** Labels `.run-form/.form label` 13/550 `--text-2`, `label.checkbox` ; cases 15px `accent-color: var(--brand)` (980). Champs (982-1000 : `.run-form`, `.filter-bar`, `.form`, `.input`, `.shap-controls`, `.example-picker`) : min 36px, padding 7/10, `--line-strong`, rayon 8, 13.5px ; hors formulaire `:where(.card, .filter-bar, .dash-panel) :where(…)` (1017-1032, spécificité nulle, 13px, textarea mono 12.5). Survol `--text-3` 70 % ; focus `outline: none` + bordure marque + anneau 22 % (1028-1031, 1053-1060) ; `readonly` (1050) ; `select[multiple]` (1001-1013). **Aucun style `:disabled`, `:invalid`, `aria-invalid`, `::placeholder`.** Structure : `fieldset`/`legend` (11/650 majuscules), `.subgrid` (26 usages), `.subfieldset`, `.settings-mode`, `.launch-profiles`, `.compare-run-*`. Divulgation `details.adv` (1135-1200) : `.adv-summary` 42px + chevron, `.adv-title`, `.adv-state[data-modified]`, `.adv-gate[data-off]`, `.adv-tail`, `.adv-body` ; masqué en mode simple (1128, 1395).

**Aides (1202-1348).** `.info-icon, .help-q` : rond 16px, « ? » en `::before` (texte masqué par `font-size: 0`), cible 36px. Macro **`help_icon(term, label, aria_label)`** (17, 25 appels) → `button.info-icon[data-term][data-term-label]` (glossary.js) ; `.help-q` créé par help.js. `.glossary-popover` (+ `-title -body -close`, `.glossary-multi`, `.glossary-search` et sous-classes). `.tip[data-tip]` : bulle `::after` en `attr(data-tip)`.

**Autres macros.** **`crumb(label, href=none)`** (15, 11 appels) ; **`headline_metrics(headline, labels, notes=None)`** (118-128 : `.headline-metrics > .headline-metric > .headline-name + .headline-value.pk-mono + .headline-sub.hint`) ; **`sparkline(values, width=120, height=28, color='var(--accent)')`** (130-142, 1 appel, `svg.sparkline` sans CSS) ; **`up_down(summary, which)`** (199-204, `.class-balance-warn`, `.na`).

---

## 5. Incohérences et dettes

### 5.1 Règles dupliquées ou contradictoires

| Sélecteur | Lignes | Effet |
|---|---|---|
| `.settings-mode` | 1090 / 1382 | `gap` 12px → `--space-md`, padding 12px → 10px 12px, rayon 10px → `--radius` ; la marge de 1095 survit |
| `.settings-mode .hint` / `strong` | 1102 / 1393 ; 1101 / 1392 | marge 3px → 2px ; 13px répété |
| `.run-form[data-mode="simple"] details.adv` | 1128 / 1395 | identiques |
| `.section-index` | 1909 / 1928 | padding 6px → 5px 8px, rayon `--radius` → `--radius-pill` |
| `.filter-bar select/input`, `.shap-controls select`, `.example-picker select` | 986 / 1881, 1998, 1088 | largeur 100 % et marge 6px annulées plus bas |
| `.metric-reliability.hint`, `.card .table-scroll` | 716, 768 | redondants (715, 765) |

### 5.2 Cascade involontaire

- `.hint` (756) suit `.metric-reliability` (715) à spécificité égale : la fiabilité s'affiche en 12.5px `--text-2` interligne 1.55 au lieu de 12px `--text-3` 1.45, sur tous les usages (macro, `_earn_title.html`, `analysis_kit.js:355`).
- `:focus-visible { border-radius: 4px }` (237) bat les champs `:where` (rayon 8px) : 8 → 4px au focus.
- `metric()` ne pose pas `data-keep` : une fiabilité de plus de 120 caractères est repliée par `help.js:45-55`.

### 5.3 Valeurs en dur au lieu de jetons

Couleurs : `#fff`/`#000` (900, 958-959), reflets blancs (907, 910), `.brand-mark` (292-297), `#140E02` (1427), replis 2780-2811, `rgb(0 0 0 / .45)` (2265), `rgba(0,0,0,.25)` (2749). Rayons : `999px` (815), `10px` (1098, 1111), `6px` (862, 1261, 1306)… Contrastes en commentaire (65-74, 98-107) : écarts jusqu'à 0,6 avec le recalcul (`--text` clair 17,9 → 18,5 ; `--text-3` clair 5,0 → 4,84).

### 5.4 Code mort ou orphelin

8 alias (1.4), `--space-2xl`, `--launch-bar-h`, 4 variables jamais définies (1.5). Classes du socle à 0 usage (gabarits, JS, Python) : `.icon-sm .icon-lg .eyebrow .grid-2 .grid-3 .stack .muted .is-link .example-picker` et `button.secondary`. Classes sans règle : `.btn-primary`, `.sparkline`. Macro `error_state` : 0 appel ; `asset_panel(label)` inutilisé. `_components.html:3-5, 34` renvoie à `static/style.css` et `static/tokens.css`, disparus.

### 5.5 Bogues visibles

- `patrick.css:2765-2766` : `content: " \x15B2"` / `" \x15BC"` (octet 0x15 vérifié par `od`) ; `"\25B2"` a perdu son `\25`.
- `drift.js:33-34` : la 4e phase est tracée en `--ink-2` = `--surface-3`, soit 1,19:1 (sombre) / 1,15:1 (clair) sur `--chart-bg` : invisible ; la 6e (`--color-border`) à 1,46:1.
- Paramètre `size` d'`icon()` ignoré (section 4, socle).

### 5.6 Accessibilité

| Paire (texte : 4,5:1 attendu) | Sombre | Clair |
|---|---|---|
| `.range-btn.active` (`--brand` sur `--brand-soft` / `--surface-2`) | **4,45** (4,43 dans la commande, sans source dans le dépôt) | 4,61 |
| `.btn-danger` (`#fff` sur `--neg`), survol | **3,16**, 4,26 | 5,59, 7,17 |
| `.status-badge.status-disabled` sur `--surface` (haut de carte) | **4,28** (4,13) | **4,36** (4,17) |
| `.status-badge.status-pending` sur `--surface` / haut de carte | 4,76 / 4,59 | 5,05 / 4,84 |
| `--text-3` sur `--bg` / `--surface` / `--surface-2` | 5,26 / 4,96 / 4,68 | **4,47** / 4,84 / **4,40** |
| Primaire : `--on-brand` sur la fin du dégradé | 8,06 | **3,84** (centre ≥ 5,7) |
| Lien `--brand` vs `--text` (non souligné ; 3:1 attendu) | **2,70** | 3,23 |
| Bordure de champ `--line-strong` vs `--surface` (3:1 attendu) | **1,50** | **1,52** |
| Anneau des champs (marque 22 %) vs `--surface` ; bordure marque | 1,38 ; 5,71 | 1,38 ; 5,72 |

- Liens jamais soulignés au repos (225), sauf survol dans `.page-subtitle`, `.table-footer`, `.empty-state-hint` ; liens de tableau couleur du texte (798), distingués par la seule graisse 500.
- Focus : global 2px `--focus` (237) ; remplacé par un fond `--surface-2` (≈ 1,1:1) sur `.glossary-search-result` (1287) ; `.glossary-search input` utilise `--brand` au lieu de `--focus` (1266).
- `.tip` : bulle en pseudo-élément ; `patrimoine.html:64` sans `tabindex` (pas d'accès clavier), `portfolio.html:114` avec.
- Cibles en pointeur fin : `.info-icon` 36px, `.range-btn` 26px, cases 15px.

### 5.7 Écarts avec MASTER.md

MASTER:47 (alias) inclut `--mono`, cite `--ok-ink` (sans lecteur), omet `--accent`. MASTER:73 (300 ms) contredit MASTER:171 (100-200 ms). MASTER:169 (pas de rayon propre) : 69 littéraux. MASTER:164 (trait 2px) : 1.8 en CSS. MASTER:13 (seule feuille) : 3 feuilles. MASTER:69 : `.is-link` inutilisée. MASTER:73 (deux niveaux) : le bouton nu (1033) en fait un troisième.

---

## 6. Contrat à préserver (noms exacts)

- **Jetons lus hors CSS** : liste de la section 2 ; formats compatibles `withAlpha`/`inkFor` ; événement `patrick:themechange` ; `data-theme` sur `<html>` ; `localStorage['patrick-theme']`.
- **Classes émises par macros et JS** : `metric-grid metric metric-label metric-value metric-reliability status-ok status-error status-warning status-pending status-disabled status-neutral status-badge tag table-scroll data-table leaderboard num pk-mono nowrap best table-footer has-collapsible-rows rows-toggle rows-toggle-caret rows-toggle-label fold-block fold-block-title fold-table fold-mean headline headline-metrics headline-metric headline-name headline-value headline-sub headline-n empty-state empty-state-message error-state error-state-message skeleton-line sk-70 sk-72 sk-80 sk-85 sk-86 sk-90 sk-94 sk-100 sk-gap sk-gap-lg lazy-block lazy-skeleton asset-panel asset-panel-body banner banner-error banner-warning banner-info card card-head hint na pos neg primary btn btn-secondary btn-ghost btn-arrow btn-danger icon-btn range-btn active segmented info-icon help-q glossary-popover tip sparkline sparkline-empty class-balance-warn hidden visually-hidden`.
- **Attributs** : `data-rows-toggle data-extra data-more data-less data-lazy-url data-label-error data-label-retry data-state data-symbol data-term data-term-label data-tip data-keep data-help data-mode data-modified data-off aria-sort`.
- **Macros** : les 13 signatures de la section 4 ; clés `ui_t` `rows_more rows_less dt_empty sparkline_aria sb_loading lazy_retry`.
- **Sélecteurs de `help.js:17-25`** : `.hint, .page-subtitle, .table-footer, .scope-line, .block-note, .pred-legend, .profile-desc, .headline-sub, .banner:not(.banner-error):not(.banner-warning)` (égale à `patrick.css:2663`, vérifié par test) ; titres `.page-title .card-title .adv-title .dash-panel-title .group-title` ; conteneurs `.card .dash-panel .panel`.
- **Chaînes testées dans `patrick.css`** : `button.primary, .btn {` et `.btn-secondary, button.secondary {` contenant `border-radius: var(--radius-pill)` ; `.btn-arrow::after`, `mask:` ; `\n.card {` contenant `var(--radius-card)` et `var(--shadow-card)` ; `--radius-card: 20px` ; exactement 3 `--shadow-card:` ; `.kind-tab {` (pilule), `.kind-tab.active { background: var(--brand);` ; `content: counter(sec, decimal-leading-zero)` ; `.section-index a[aria-current="true"]` ; `.to-top[hidden] { display: none; }`, `.to-top.is-visible` (`test_ui_lot_a.py:77-107`) ; `.help-folded { display: none !important; }`, `.help-q::before`, `.help-pop`, `.glossary-multi` (`test_help_minimal_text.py:49-93`) ; `\n.ticker {` (sticky, top 0), `:root:has(.ticker:not([hidden])) { --ticker-h: 33px; }`, `--ticker-dir: reverse`, `top: var(--ticker-h)` dans `\n.topbar {`, ≥ 3 `top:` via `--stick-top`, aucun via `--topbar-h` (`test_machine_card_and_ticker.py:155-172`).
- **Fichiers** : `/static/patrick.css` versionné (`test_ui_shell.py:53-58`) ; `analysis_routes.py:217` ; `style="…"` limité à `_fund_overview.html` et `analysis.html` (`test_ui_shell.py:102-108`) ; 1 texte français toléré dans `_components.html` (`test_i18n_templates.py:87`) ; polices `static/fonts/*.woff2` préchargées par chemin, aucune requête externe.

## 7. Pistes pour la v4 (tirées de l'existant)

1. Une source unique pour les thèmes, en gardant hex/rgba pour les jetons lus par `chart_kit.js` (ou en étendant d'abord `withAlpha`/`inkFor`).
2. Jetons manquants : typographie, hauteurs (26/30/36/38), espacement 12px, anneau de focus, durées ; puis remplacer les rayons littéraux.
3. Supprimer le mort ; définir ou retirer les 4 variables orphelines ; sortir `--ink-2` de la palette de `drift.js`.
4. Fusionner les doublons, corriger `.metric-reliability`/`.hint` et les flèches de tri.
5. Contrastes ≥ 4,5:1 (`.range-btn.active`, `.btn-danger`), liens identifiables, bordures de champ à 3:1, focus partout, `:disabled`/`aria-invalid`.
6. Unifier `.status-badge`/`.exp-chip` et le balisage dupliqué macros/JS, sans changer les noms de la section 6.
