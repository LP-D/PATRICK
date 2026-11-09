# Design System Master File — v4 « Terminal »

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** PATRICK
**v4 (refonte visuelle complète) :** 2026-11-09 — « très pro, style Bloomberg, avec la propreté d'Apple » (demande de Léon). Remplace v3 « Cockpit Pro » (2026-09-25 : bleu de marque, cartes à 20 px avec ombre douce, boutons en pilule à dégradé). Décision et mesures : `docs/adr/0019-design-v4-terminal.md`. Historique v3 : `git log -- design-system/patrick/MASTER.md`. Cartographie de l'existant faite avant la refonte : `design-system/patrick/v4/research/01…06`.
**Category:** Financial Dashboard — outil interne de recherche quantitative, pas un produit commercial.

**Fichiers :** `webapp/static/patrick.css` (feuille principale), `analysis.css` (pages d'analyse), `knowledge.css` (Connaissances), `webapp/templates/base_v2.html` (shell), `webapp/static/shell.js` (thème, rail, tiroir, palette), `webapp/icons.py` (icônes).

**Contrat de migration (inchangé depuis la v3) :** tous les noms de classes, identifiants et attributs utilisés par les gabarits, le JS et les tests sont conservés ; les jetons lus par le JS (`--brand`, `--brand-soft`, `--mono`, `--text`, `--text-3`, `--bg`, `--chart-bg`, `--chart-grid`, `--line-strong`, `--pos`, `--neg`, `--warn`, `--neutral-soft`, `--ra-c1…8` et les alias hérités) gardent leur nom et une valeur `#rrggbb` / `rgba()`. La v4 est un re-skin : aucun balisage de zone de données ne change.

---

## Principes

1. **La donnée d'abord (Bloomberg).** Densité d'un terminal : corps à 13 px, lignes de tableau de 30 px, en-têtes courts en capitales, chiffres en JetBrains Mono tabulaire. Les KPI forment un **tableau d'affichage joint** (filets de 1 px), pas des cartes séparées.
2. **Aucun chiffre sans sa fiabilité** (hérité de la Phase 7) : `metric(label, value, reliability)` impose le troisième argument.
3. **Propre, pas décoré (Apple).** Panneaux en aplat (`--shadow-card: none`), profondeur par surfaces étagées (`--bg` < `--surface` < `--surface-2` < `--surface-3`) et filets ; aucun dégradé, aucune animation d'entrée, aucune translation au survol. Les ombres restent aux couches flottantes (menus, bulles, fenêtres).
4. **Une seule couleur d'identité : l'orange terminal** (`--brand`) pour la marque, la page active, l'action principale et l'anneau de focus. Vert / rouge / jaune réservés au **sens** (gain / perte / alerte), bleu `--info` à « en cours » ; jamais décoratifs.
5. **Deux thèmes de première classe.** Noir pur par défaut (écran de terminal), clair sur le gris de macOS (`#F2F2F7`, panneaux blancs, orange brûlé). Choix persisté (`localStorage['patrick-theme']`), sinon préférence OS, appliqué avant le premier rendu.
6. **Une échelle, pas des valeurs.** Tailles, rayons, hauteurs de contrôle et durées viennent des jetons ; une valeur en dur dans une règle de page est un défaut.

## Jetons

Définis sur `:root` (sombre) et `:root[data-theme="light"]` (+ `@media (prefers-color-scheme: light)` pour `:root:not([data-theme])`). Contrastes WCAG calculés (luminance relative), sur `--bg` / `--surface`.

| Rôle | Sombre | Clair | Usage |
|---|---|---|---|
| `--bg` | `#000000` | `#F2F2F7` | fond de page, bandeau des variations |
| `--surface` | `#111113` | `#FFFFFF` | panneaux, barre latérale |
| `--surface-2` | `#18181B` | `#F7F7F9` | champs, en-têtes de tableau, survol |
| `--surface-3` | `#222226` | `#EBEBF0` | boutons secondaires, pistes |
| `--line` / `--line-strong` | blanc 8 % / 16 % | `rgba(60,60,67,.14)` / `.29` | filets / bordures de contrôles |
| `--text` | `#F5F5F7` (19,3 / 17,3) | `#1D1D1F` (15,1 / 16,8) | texte |
| `--text-2` | `#AEAEB2` (9,5 / 8,5) | `#48484A` (8,2 / 9,1) | texte secondaire, libellés |
| `--text-3` | `#8E8E93` (6,4 / 5,8) | `#636368` (5,4 / 6,0) | métadonnées |
| `--brand` | `#FF9F0A` (10,2 / 9,2) | `#A93A0B` (5,7 / 6,4) | identité, actif, bouton principal, focus ; texte posé dessus `--on-brand` (noir / blanc) |
| `--pos` | `#30D158` | `#146C2E` | gain, significatif, OK |
| `--neg` | `#FF453A` | `#C80014` | perte, erreur, drawdown |
| `--warn` | `#FFD60A` | `#7F5300` | à vérifier, biais signalé (jaune : distinct de l'orange d'identité) |
| `--info` | `#409CFF` | `#005BBF` | « en cours », bannière d'information |
| `--chart-bg` / `--chart-grid` | `#0A0A0B` / blanc 7 % | `#FFFFFF` / noir 7 % | fonds et grilles de graphiques |
| `--ra-c1…8` | bleu `#3987E5` … rouge `#E66767` | bleu `#2A78D6` … rouge `#E34948` | séries catégorielles des graphiques (voir *Graphiques*) |

Variantes `*-soft` (fonds teintés de badges et bannières). **Alias hérités** (`--color-*`, `--accent-ink`, `--ok-ink`, `--error-ink`, `--ink-2`, `--ink-text-2`) pointent vers ces jetons.

**Échelles fixes** (communes aux deux thèmes) :

| Famille | Jetons |
|---|---|
| Texte | `--fs-xs` 11 · `--fs-sm` 12 · `--fs-base` 13 · `--fs-md` 15 · `--fs-lg` 17 · `--fs-xl` 22 · `--fs-2xl` 28 (px) |
| Rayons | `--radius-sm` 4 (pastilles internes) · `--radius` 6 (boutons, champs, onglets) · `--radius-lg` 8 (blocs internes, barres de filtres) · `--radius-card` 10 (panneaux, fenêtres, menu en blocs) · `--radius-pill` (pastilles de filtre, badges) |
| Hauteurs | `--control-h` 30 · `--row-h` 30 · `--topbar-h` 48 · 44 en pointeur grossier |
| Espacements | `--space-2xs` 2 · `xs` 4 · `sm` 8 · `12` · `md` 16 · `lg` 24 · `xl` 32 · `2xl` 48 |
| Mouvement | `--ease-out` ; 120 ms pour les états, 140–220 ms pour une couche qui s'ouvre ; tout est coupé par `prefers-reduced-motion` |

## Typographie

- **UI :** Inter (variable, vendorisée, OFL), **13 px** de base, interligne 1,5, `cv11/ss01/ss03` + `tnum`.
- **Chiffres et code :** JetBrains Mono (variable, vendorisée, OFL), `tabular-nums`, poids 500 pour les grands chiffres (KPI, cours, comptes).
- Titre de page 22/650 (−0,022 em) ; titre de panneau 15/600 ; sous-titre de panneau (`h3`) 13/600 ; libellé KPI 12/500 `--text-2` ; valeur KPI 22 mono ; en-tête de tableau 11/600 capitales (+0,05 em).
- Lecture longue (cours de Connaissances) : 15 px, ligne ≤ 80 caractères.
- Aucune requête externe (pas de CDN de polices).

## Shell

- **Barre latérale** 232 px (rail 56 px replié), lignes de 26 px façon liste source macOS : marque (pastille orange pleine), **arborescence** du registre de navigation, pied (langue + repli). < 1024 px : tiroir, **hors de l'ordre de tabulation quand il est fermé** (`visibility: hidden`).
- **Barre du haut** collante, 48 px, opaque : fil de localisation, menu en blocs (« Parcourir »), **ligne de commande** (déclencheur de la palette en monospace, icône orange, Ctrl K / ⌘K / `/`), raccourcis, cloche, thème. ≤ 480 px : Vocabulaire, Réglages et Diagnostics quittent la barre (ils restent dans la palette) pour tenir à 320 px.
- **Bandeau des variations** au-dessus : bande noire (`--bg`), symboles en `--text-2`, variations colorées par le sens.
- **Menu en blocs** : carte de la catégorie courante (aplat `--surface-2`, filet orange en haut), une colonne par catégorie ; comportement inchangé (clic, clavier, Échap, survol différé à la souris).
- **Palette de commandes** : entrées = registre de navigation, recherche insensible aux accents.
- **Contenu** : colonne `max-width: 1680px`, marges 20 × 24 px (16 px mobile). Lien d'évitement « Aller au contenu » visible au focus.

## Composants (classes stables)

| Composant | Classes | Notes |
|---|---|---|
| KPI | `.metric-grid > .metric` (`.metric-label`, `.metric-value.status-*`, `.metric-reliability`) | tableau d'affichage joint : `gap: 1px` sur fond `--line`, cadre et rayon communs ; aucune animation. Même dessin pour `.headline-metrics` (AUC / F1) |
| Panneau | `.card` (`h2`, `.card-head`), `.dash-panel` (`.dash-panel-title`) | aplat `--surface`, filet `--line`, rayon `--radius-card` ; le titre forme un **en-tête séparé par un filet** (marges négatives) ; seul un panneau cliquable réagit au survol (bordure) |
| Tableau | `.table-scroll > .data-table` (`th.num`/`td.num`, `tr.best`) | lignes `--row-h`, en-têtes 11 px capitales sur filet fort, chiffres mono à droite, en-tête collant ; tri ▲ ▼ |
| Badge | `.status-badge.status-{ok,error,warning,pending,neutral,disabled}` | 20 px, pastille ; `pending` = bleu `--info` |
| Bannière | `.banner.banner-{error,warning,info}` | filet gauche 3 px, rayon `--radius-lg` |
| Boutons | `button.primary` / `.btn` (aplat orange, texte `--on-brand`) et `.btn-secondary` (`--surface-3` + filet) ; `.btn-ghost`, `.icon-btn`, `.btn-danger` (contour rouge) | `--control-h`, rayon `--radius`, 44 px en pointeur grossier. Un seul bouton principal par page ; `.btn-arrow` sur l'action principale |
| Champs | `.run-form`, `.form`, `.filter-bar`, `:where(.card, .filter-bar, .dash-panel)` | `--control-h`, fond `--surface-2`, bordure `--line-strong` ; focus = bordure orange + anneau plein de 2 px |
| Focus clavier | `:focus-visible` | anneau `--focus` de **3 px**, décalé de 2 px (−3 px à l'intérieur des lignes et onglets), partout |
| Info-bulles | `.info-icon`, `.help-q`, `.tip[data-tip]`, `.help-pop`, `.glossary-popover` | couches flottantes : rayon `--radius-lg`, ombre `--shadow-lg` |
| Pastilles de filtre | `.kind-tabs > .kind-tab` (+ `.kind-count`), `.vocab-chip`, `.kb-chip` | pilule de 28 px, la pastille active est pleine (orange) |
| Segments | `.segmented` / `.preview-range-buttons > .range-btn`, `.ra-seg` | contrôle segmenté façon macOS : cadre `--radius-lg`, segments `--radius`, actif teinté orange avec filet |
| Onglets | `.exp-tabs [role=tab]`, `.run-tabs a` | soulignés (filet orange de 2 px), même dessin |
| Index de sections | `.section-index > a[href="#…"]` | barre collée opaque, onglets rectangulaires numérotés `01`, `02`… (compteurs CSS) ; section en cours soulignée en orange |
| Barre de lancement | `.launch-bar` (`[data-confirm]`) | collée au bas du panneau, aplat ; confirmation en jaune `--warn` |
| Retour en haut | `#to-top.to-top` | carré arrondi `--radius-card`, au-dessus du bandeau d'aide |
| Patrimoine | `.account-grid > .account-card[data-kind]`, `.drop-zone[data-over]`, `.draggable-row`, `.drop-target` | comptes en aplat, valeur mono |

## Graphiques

**Un seul moteur : `webapp/static/chart_kit.js` (`PatrickPlot.create(hôte, options)`)**, canvas sans bibliothèque. Aucune page ne dessine plus sa propre toile : aperçu de cible, statistiques par actif, dérive des phases, fonds, patrimoine, Exploration et RL (via `PatrickCharts.lineChart/barChart` de `charts.js`, enveloppes minces au même contrat qu'avant) passent tous par lui.

- **Interactions** (souris, clavier, tactile) : glisser = sélection puis zoom ; Maj + glisser, un doigt (tactile) ou ← → = déplacer la fenêtre zoomée ; Ctrl/⌘ + molette ou pincement = zoom centré sur le curseur (la molette seule défile la page) ; double-clic, Échap, Origine ou « Tout » = vue initiale ; boutons zoom +/− / réinitialiser au survol (toujours visibles au tactile et quand un zoom est actif) ; périodes 1M…Tout sur les séries temporelles.
- **Échelles** : l'axe Y est recalculé sur les points *visibles* à chaque zoom (graduations « rondes », décimales cohérentes, marge calculée sur la largeur réelle des étiquettes) ; les repères (`hlines`, `band`) ne comptent qu'à la vue initiale ou s'ils sont proches des données ; l'axe du temps choisit jours / semaines / mois / années selon la fenêtre.
- **Lisibilité** : infobulle (date + valeur de chaque série, en nœuds texte), légende cliquable (masquer une série recalcule l'échelle), trous honnêtes (une valeur absente coupe le trait), décimation min/max par colonne de pixels au-delà de 2 points par pixel.
- **Rendu « cotation »** (Yahoo Finance / Boursorama / Bloomberg), défaut des courbes (`finance: false` pour l'éteindre) : axe des valeurs à **droite**, grille horizontale en pointillés, **aire dégradée** sous une courbe seule, **étiquette du dernier point** sur l'axe (pastille de la couleur de la courbe, fil pointillé), **réticule** à pastilles (valeur sur l'axe, date en bas). Options : `trend: true` (vert / rouge selon la variation de la fenêtre + niveau de départ en pointillés), `quote: true` (en-tête : dernière valeur, variation absolue et en %, date ; suit le survol), `ohlc: {open, high, low}` (bascule **Courbe / Bougies**, infobulle O H L C), `volume: [...]` (barres sous la courbe, colorées selon le sens), `initialDays: N` (vue de départ sur les N derniers jours), `quoteTitle: false`. Périodes : 1M 3M 6M **YTD** 1A 5A Tout. Les couleurs restent des jetons (`--pos` / `--neg` ne servent qu'au sens du mouvement). Source des bougies : `market_data.price_history` (yfinance ; FRED n'a que des clôtures), transmises par `/api/preview/{symbol}` et `/api/asset-stats/{symbol}`.
- **Contrat de toile** inchangé : couleurs lues dans les jetons au tracé, redessin sur `patrick:themechange` et au redimensionnement (`ResizeObserver`), buffer = boîte CSS × `devicePixelRatio`, `aria-label` régénéré avec les vraies bornes de la fenêtre visible, libellés via `window.I18N` (clés `chart_*`).
- **Couleurs des séries** : une série seule prend `--brand` ; plusieurs séries prennent les **séries catégorielles `--ra-c1…8`** dans cet ordre fixe (bleu, orange, vert d'eau, jaune, magenta, vert, violet, rouge), définies dans `patrick.css` pour les deux thèmes et validées par `validate_palette.js` (skill dataviz) : bande de luminosité, chroma, écart daltonien adjacent ≥ 8,4, vision normale ≥ 17,4, contraste ≥ 3:1 sur `--chart-bg`. Une 9ᵉ série se replie dans « Autres » ; une couleur suit l'entité, jamais son rang. `--pos` / `--neg` / `--warn` ne servent jamais d'identité de série (dérive des phases, comparaison RL et référence du patrimoine corrigées en v4).
- **Nouveau graphique** : créer un hôte `<div>` (jamais une `<canvas>`) et appeler `PatrickPlot.create`. Fonctions pures testées sous Node : `tests/js/chart_kit.test.js` (lancé par `tests/test_chart_kit_js.py`).

---

### Navigation Registry (extension formelle, post-lock)

> **Introduit par :** commit `6b5a0bd` (branche `feature/nav-categories-registry`). Étend le pattern *Internal Cockpit* ci-dessus : la « fixed left sidebar navigation » n'est plus une liste de liens écrite à la main, c'est le rendu d'un registre unique.

**Source unique :** `patrick/patrick/webapp/nav_registry.py`. `templates/base_v2.html` itère `nav_sections(request.url.path)` (global Jinja enregistré dans `webapp/app.py`) et ne contient **aucun** `<a href>` de nav en dur — garanti par `tests/test_nav_registry.py::test_base_template_has_no_hardcoded_nav_link`.

**Structure :**

| Objet | Champs | Rôle |
|-------|--------|------|
| `NavCategory` | `key`, `label` (repli FR), `label_key` (i18n) | Section de la sidebar. Tuple `CATEGORIES`, ordre fixe = ordre d'affichage. |
| `NavEntry` | `slug` (unique), `label` (repli FR), `url`, `category`, `order`, `label_key` (i18n, optionnel), `child_routes` | Un lien de nav. `child_routes` = pages paramétrées rattachées à l'entrée mais non listées (ex. `/runs/{run_id}/detail`, `/targets/{ticker}`). |
| `NON_PAGE_PREFIXES` / `NON_PAGE_ROUTES` | — | Routes GET qui ne sont pas des pages (`/api/*`, `/static`, `/set-lang/*`, statut/résultats/téléchargements de run). |

**Taxonomie — 6 catégories fixes, dans cet ordre :**

| Clé | En-tête | Règle d'appartenance |
|-----|---------|----------------------|
| `pilotage` | PILOTAGE | Piloter la station : vue d'ensemble, suivi des runs, prédictions, analyses transverses, santé des données. |
| `modeles` | MODÈLES | Cadrer et lancer un entraînement, une page par famille : machine learning, deep learning, reinforcement learning. |
| `classes_actifs` | CLASSES D'ACTIFS | Ce que PATRICK modélise, présenté par famille de sous-jacents (univers, matières premières, macro, actions…), y compris les vues cross-actifs sur l'univers PATRICK (`/portfolio` : agrégation de signaux par classe + allocation HRP). |
| `simulation` | SIMULATION | Ouvrir des positions fictives (ticket d'ordres) et suivre les stratégies du fonds. |
| `patrimoine` | PATRIMOINE | Gestion patrimoniale réelle ou fictive : comptes, mouvements. |
| `connaissances` | CONNAISSANCES | Apprendre : parcours du débutant à l'avancé (`/connaissances`), cours détaillés (`/connaissances/cours`), dictionnaire du quant (`/connaissances/dictionnaire`). Contenu statique, aucun calcul. |

Une page relève d'**une seule** catégorie (6 : `pilotage`, `modeles`, `classes_actifs`, `simulation`, `patrimoine`, `connaissances`). En cas de doute, la catégorie est tranchée par Léon-Paul, pas par l'implémenteur. Ajouter une 5ᵉ catégorie est un amendement de ce fichier, pas un changement de code isolé. Une catégorie sans entrée n'est pas rendue (pas d'en-tête orphelin).

**Arborescence (2026-10-24) :** `NavGroup` (`GROUPS`) = sous-dossier d'une catégorie ; `NavEntry.group` y range une entrée (vide = feuille posée sous la catégorie). Un dossier prend la place de sa première entrée (plus petit `order`). `nav_sections(path)` rend `entries` (liste plate : palette de commandes, état actif) et `nodes` (arbre : feuilles et dossiers, `active` = contient la page courante). Dossiers actuels : Pilotage → *Suivi des modèles*, *Signaux*, *Recherche*, *Données* ; Classes d'actifs → *Marchés*. Les pages en doublon se fusionnent dans une seule entrée (ex. `/data-freshness` redirige vers `/universe`, `/analyses` vers `/runs?vue=analyses` : l'Historique a deux vues, la liste des runs — avec un lien d'analyse détaillée par ligne — et les analyses transverses).

**Rendu (v3) :**
- Catégories et dossiers = boutons `aria-expanded` (`.sidebar-nav-heading`, `.nav-folder-btn`) qui montrent / cachent la `ul.nav-tree` suivante ; chevron 16 px qui tourne, guides d'indentation (`--lvl`), ligne active pleine largeur. L'état (clé → ouvert) est rangé dans `localStorage['patrick-nav-tree']` (`shell.js`), rejoué avant le premier rendu par le petit script de `base_v2.html` ; la branche de la page courante est toujours ouverte. Boutons « Tout replier / Tout déplier » au survol de l'en-tête. Clavier : ↑ ↓ Début Fin, → ouvre / entre, ← ferme / remonte. Rail replié : toutes les feuilles en icônes, un filet par catégorie.
- En-tête de section `.sidebar-nav-heading` : Inter 11px, 650, uppercase, `letter-spacing: 0.07em`, `--text-2`.
- Chaque lien porte l'icône de son slug (`webapp/icons.py::NAV_ICONS`, défaut `layers`) puis son libellé dans `.nav-label` ; `title` = libellé (info-bulle du rail replié).
- Liens : état actif `aria-current="page"` (fond `--brand-soft`, icône `--brand`, filet gauche `--brand`).
- État actif : `/` en égalité stricte, toute autre entrée par préfixe de segment (`/runs` s'allume sur `/runs/{id}/detail`) ; une page enfant déclarée dans `child_routes` allume aussi son entrée (`/targets/^VIX` → Univers, `/compare-runs` → Historique).
- Rail replié (bouton en pied de sidebar, persisté `localStorage['patrick-sidebar']`) : icônes seules, en-têtes réduits à un filet.
- < 1024px : tiroir hors-canevas ouvert par le bouton menu de la topbar, fermé par le voile ou Échap.

**Procédure obligatoire pour toute nouvelle page :**
1. Déclarer la route FastAPI dans `webapp/app.py` (le template étend `base_v2.html`).
2. Ajouter **une** `NavEntry` dans `NAV_ENTRIES` (slug unique, catégorie parmi les 4, `order` libre dans la catégorie) — ou, pour une page paramétrée non listée, l'ajouter à `child_routes` de l'entrée parente.
3. Ajouter la clé i18n `nav_<slug>` (fr + en) dans `webapp/i18n.py` si le libellé doit être traduit.
4. `pytest tests/test_nav_registry.py` doit rester vert : une route GET absente du registre et non déclarée non-page fait échouer `test_no_orphan_page_route`.

❌ **Interdit :** tout lien de navigation latérale écrit en dur dans un template, toute seconde liste de nav, toute logique d'état actif hors `nav_registry.is_active`. Les liens contextuels dans le contenu des pages ne sont pas de la nav latérale et restent hors registre.

**Fil de localisation (barre du haut) — seul fil d'Ariane de l'application :** `catégorie › entrée du registre`, déduit du chemin. Une page *enfant* (détail d'un run, fiche d'une cible, compte, comparaison) y ajoute ses maillons avec `{% block crumb_trail %}{{ crumb(libellé, lien) }}{% endblock %}` (macro `crumb` de `_components.html`) ; le dernier maillon est la page courante (non cliquable). ❌ Plus de `<nav class="breadcrumb">` dans le corps des pages : il doublait la barre du haut (et nommait encore « Poste » la synthèse).

---


---

## Textes et traductions

- **Aucun texte visible en dur** : gabarits `t('clé')` (FR + EN dans `webapp/i18n*.py`) ; scripts `window.I18N` (clés à lister dans `i18n.js_strings` ou dans le `*_JS_KEYS` du module) ; macros importées sans contexte (`_components.html`) `ui_t('clé')` (langue de la requête, posée par `LangMiddleware`).
- **Messages produits par le domaine** (`validation/`, `tracking/`, `fund/`… : français pour la ligne de commande) : traduits à l'affichage par `webapp/i18n_server.py` — `{{ message | tx }}` ou `t.tx(message)` dans un gabarit, gestionnaire d'erreurs HTTP et listes d'erreurs de formulaire déjà branchés. Un message sans règle reste en français (jamais perdu) : ajouter la règle + un cas dans `tests/test_i18n_server.py`.
- **Vocabulaire commun** (un terme = une traduction) : *Hausse forte / faible, Baisse forte / faible* (jamais « Forte baisse »), *Drawdown max*, *Tuning Optuna*, *Derniers runs*, *Stacking*, *Fonds / Fund*, *Ticket d'ordres / Order ticket*. Nombres, dates et devises suivent la langue de la page (`Intl`, pas de `fr-FR` en dur).

## Noms des instruments

- **L'interface montre le nom, jamais le symbole** : société et ETF → le nom seul (*Apple*, *LVMH*) ; futures, CFD, indices, volatilité, devises, cryptos, taux, séries macro → le genre en tête (*Future · Or*, *CFD · Apple*, *Indice · S&P 500*, *Devise · EUR/USD*, *Crypto · Bitcoin*, *Taux · Trésor US 10 ans*, *Macro · …*). Cible d'alpha : *Apple · α vs S&P 500*.
- **Le symbole reste l'identifiant** (URL, `value`, API, base) et se lit au survol : `title="{{ symbole }}"`. Registre : `config/instrument_names.py` (symbole → genre, nom FR, nom EN) ; règle serveur `webapp/instruments.py` ; navigateur `static/names.js` (`PatrickNames.label/name/tip`, `PK.inst` dans `analysis_kit.js`), alimenté par `<script id="instrument-names">` posé dans l'en-tête de `base_v2.html`, avant tout script de page.
- **Gabarits** : `{{ s | iname }}` (texte), `{{ s | iname_tip }}` (avec bulle), `{{ s | iname_h }}` pour une cellule assemblée par `~` puis `| safe` (déjà échappé, `str` ordinaire — voir le piège Markup). Position de fonds : `{{ p.symbol | iname(none, p.kind) }}` impose le genre ; instrument de règle : `instr_name(c.instrument)`.
- **Nouveau symbole dans l'univers** : l'ajouter au registre (`tests/test_instrument_names.py` échoue sinon). Symbole inconnu (Patrimoine, Simulation) : genre deviné d'après la forme (`=F`, `=X`, `-USD`, `^`), puis nom appris en arrière-plan chez Yahoo (`~/.patrick/instrument_names.json`, coupé par `PATRICK_INSTRUMENT_LOOKUP=0`).
- **Exceptions assumées** : les messages composés par le domaine (phrases traduites par `i18n_server`) et les noms de runs enregistrés gardent le symbole tel qu'il a été écrit.

## Anti-Patterns (Do NOT Use)

- ❌ Emojis comme icônes — icônes Lucide via `icon()` uniquement (un seul jeu, trait 2px)
- ❌ Couleur littérale dans un gabarit ou un script (hors `patrick.css` jetons)
- ❌ Une `<canvas>` dessinée à la main dans une page : tout graphique passe par `PatrickPlot` (`chart_kit.js`)
- ❌ Un texte français en dur dans un gabarit, un script ou un libellé d'erreur affiché tel quel
- ❌ Vert / rouge / jaune décoratifs (réservés au sens) ; orange ailleurs que sur l'identité, l'actif, l'action principale et le focus
- ❌ Dégradé, ombre sous un panneau posé, animation d'entrée, flou décoratif
- ❌ Taille de police, rayon ou hauteur de contrôle en dur : utiliser les échelles (`--fs-*`, `--radius*`, `--control-h`)
- ❌ Plus de deux niveaux de boutons côte à côte (un principal, un secondaire)
- ❌ Translation/zoom au survol de panneaux statiques (décale la mise en page)
- ❌ Changement d'état instantané (transitions de 120 ms) ; animation ignorant `prefers-reduced-motion`
- ❌ Focus invisible ; élément cliquable sans `cursor: pointer`
- ❌ Hero, CTA commerciaux, logos clients, tunnels

## Pre-Delivery Checklist

- [ ] Les deux thèmes vérifiés (capture sombre + clair)
- [ ] 320px, 375px, 768px, 1024px, 1440px ; aucun défilement horizontal de page (`scrollWidth == clientWidth`)
- [ ] Rail replié et tiroir mobile : aucun contenu masqué
- [ ] Contraste texte ≥ 4.5:1 sur `--bg` et `--surface` dans les deux thèmes ; palette des graphiques revalidée (`validate_palette.js`) si une série change
- [ ] Focus clavier visible ; palette utilisable au clavier seul
- [ ] Graphiques : redessin au changement de thème, texte net en HiDPI
- [ ] `pytest tests/test_nav_registry.py` vert

**Amendement du 2026-11-07 — 6ᵉ catégorie `connaissances` (demandée par Léon).** Section d'apprentissage : parcours en trois niveaux, cours rendus depuis `docs/cours/` (Markdown, formules en MathML), dictionnaire de 750 notions (lexique des bulles « ? » inclus). Classes CSS dédiées `kb-*` dans `static/knowledge.css` ; les composants existants (`card`, `data-table`, `table-scroll`, `queue-action`, `primary`) sont réutilisés. Voir `docs/adr/0018-section-connaissances.md`.

**Amendement du 2026-11-09 — v4 « Terminal ».** Refonte visuelle de toute l'application (jetons, coque, composants, CSS des pages, palette des graphiques) ; noms de classes et balisage inchangés. Voir `docs/adr/0019-design-v4-terminal.md`.
