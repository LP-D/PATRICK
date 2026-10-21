# Design System Master File — v3 « Cockpit Pro »

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** PATRICK
**v3 (refonte complète) :** 2026-09-25 — remplace v2 « Internal Cockpit » (2026-08-22 : sombre uniquement, Fira Code/Fira Sans, palette slate/vert). Historique v2 : `git log -- design-system/patrick/MASTER.md`.
**Category:** Financial Dashboard — outil interne de recherche quantitative, pas un produit commercial.

**Fichiers :** `webapp/static/patrick.css` (seule feuille), `webapp/templates/base_v2.html` (shell ; nom conservé pour ne pas toucher les 16 gabarits enfants), `webapp/static/shell.js` (thème, rail, tiroir, palette), `webapp/icons.py` (icônes).

**Contrat de migration :** tous les noms de classes utilisés par les gabarits et par le JS (`app.js`, `simulate.js`, `market.js`, `drift.js`, `asset_stats.js`, `shap_waterfall.js`, `glossary.js`) sont conservés. La v3 est un re-skin + un nouveau shell, jamais un changement du balisage des zones de données.

---

## Principes

1. **La donnée d'abord.** Chiffres en JetBrains Mono tabulaire, alignés à droite dans les tableaux ; aucun ornement qui concurrence un nombre.
2. **Aucun chiffre sans sa fiabilité** (hérité de la Phase 7) : `metric(label, value, reliability)` impose le troisième argument.
3. **Sobre, pas plat.** Profondeur par surfaces étagées (`--bg` < `--surface` < `--surface-2` < `--surface-3`) et filets fins (`--line`), ombres discrètes ; pas de translation au survol des panneaux statiques.
4. **Deux thèmes de première classe.** Sombre par défaut, clair complet ; choix explicite persisté (`localStorage['patrick-theme']`), sinon préférence OS. Appliqué avant le premier rendu (script inline dans `<head>`) : pas de flash.
5. **Une seule couleur de marque** (`--brand`, bleu) pour l'interaction et l'état actif ; vert/rouge/ambre réservés au **sens** (gain/perte/alerte), jamais décoratifs.

## Jetons

Définis sur `:root` (sombre) et `:root[data-theme="light"]` (+ `@media (prefers-color-scheme: light)` pour `:root:not([data-theme])`). Contrastes WCAG mesurés (luminance relative) notés dans `patrick.css`.

| Rôle | Sombre | Clair | Usage |
|---|---|---|---|
| `--bg` | `#0A0C10` | `#F5F6F8` | fond de page |
| `--surface` | `#111419` | `#FFFFFF` | cartes, sidebar |
| `--surface-2` | `#161A21` | `#F3F4F7` | en-têtes de tableau, survol |
| `--surface-3` | `#1D222B` | `#E9EBF0` | pistes (progress), grilles |
| `--line` / `--line-strong` | blanc 7.5 % / 14 % | `#E4E7EC` / `#CDD2DA` | filets / bordures de contrôles |
| `--text` | `#E8EBF0` (16.3:1) | `#0F1419` (17.9:1) | texte |
| `--text-2` | `#A3ABB9` (8.3:1) | `#4A5261` (8.0:1) | texte secondaire |
| `--text-3` | `#7C8594` (5.1:1) | `#6A7282` (5.0:1) | métadonnées |
| `--brand` | `#5B8DEF` (6.1:1) | `#2F5FD0` (6.0:1) | liens, actif, bouton primaire, courbe stratégie |
| `--pos` | `#2FBF84` | `#0B7A55` | gain, significatif, OK |
| `--neg` | `#F0616D` | `#C62834` | perte, erreur, drawdown |
| `--warn` | `#E5A83B` | `#9A5B00` | à vérifier, biais signalé |
| `--chart-bg` / `--chart-grid` | `#0D1015` / blanc 6 % | `#FBFBFC` / noir 7 % | fonds et grilles de graphiques |

Variantes `*-soft` (fonds teintés de badges/bannières). **Alias hérités** (`--color-*`, `--accent-ink`, `--ok-ink`, `--error-ink`, `--ink-2`, `--ink-text-2`, `--mono`) pointent vers ces jetons : lus par le JS des graphiques, ne jamais y mettre une couleur littérale.

## Typographie

- **UI :** Inter (variable, vendorisée `static/fonts/inter-*.woff2`, OFL), 14px de base, `cv11/ss01/ss03`.
- **Chiffres et code :** JetBrains Mono (variable, vendorisée, OFL), `tabular-nums`.
- Titres : 24px/650 (`.page-title`), cartes 15px/600, libellés KPI 12px/500 `--text-2`, en-têtes de tableau 11.5px/600.
- Aucune requête externe (pas de CDN de polices : cf. l'incident Chrome/Google Fonts de la v2).

## Shell

- **Sidebar** 248px (rail 64px replié) : marque, groupes du registre de navigation avec icônes, pied (langue + repli).
- **Topbar** collante, translucide (`backdrop-filter`) : fil de localisation (catégorie › page, déduit du registre ; à défaut le `<title>` de la page), déclencheur de la **palette de commandes** (Ctrl K / ⌘K / `/`), bascule de thème. < 1024px : bouton menu (tiroir).
- **Palette de commandes** : entrées = registre de navigation (JSON rendu serveur), recherche insensible aux accents, préfixe > sous-chaîne > sous-séquence, ↑ ↓ ↵ Échap.
- **Contenu** : colonne `max-width: 1480px`, marges 28px (16px mobile).

## Composants (classes stables)

| Composant | Classes | Notes |
|---|---|---|
| KPI | `.metric-grid > .metric` (`.metric-label`, `.metric-value.status-*`, `.metric-reliability`) | apparition échelonnée 35ms, désactivée par `prefers-reduced-motion` |
| Carte | `.card` (`h2`, `.card-head`) | rayon 14px, pas de survol animé |
| Tableau | `.table-scroll > .data-table` (`th.num`/`td.num`, `tr.best`) | en-tête collant dans son conteneur, survol de ligne |
| Badge | `.status-badge.status-{ok,error,warning,pending,neutral,disabled}` | pastille + point coloré |
| Bannière | `.banner.banner-{error,warning,info}` | filet gauche 3px |
| Boutons | `button.primary` / `.btn`, `.btn-secondary`, `.btn-ghost`, `.icon-btn`, `.btn-danger` | 36px (44px en pointeur grossier) |
| Formulaires | `.run-form`, `.form`, `.filter-bar`, `details.adv` | anneau de focus `--brand` 22 % |
| Info-bulles | `.info-icon` (glossaire, `glossary.js`), `.tip[data-tip]` (CSS seul) | à utiliser sur toute surface régime/HRP/BL |
| Segments | `.segmented` / `.preview-range-buttons > .range-btn` | |
| Patrimoine | `.account-grid > .account-card[data-kind]`, `.drop-zone[data-over]`, `.draggable-row`, `.drop-target` | comptes réels/fictifs, glisser-déposer |

## Graphiques

**Un seul moteur : `webapp/static/chart_kit.js` (`PatrickPlot.create(hôte, options)`)**, canvas sans bibliothèque. Aucune page ne dessine plus sa propre toile : aperçu de cible, statistiques par actif, dérive des phases, fonds, patrimoine, Exploration et RL (via `PatrickCharts.lineChart/barChart` de `charts.js`, enveloppes minces au même contrat qu'avant) passent tous par lui.

- **Interactions** (souris, clavier, tactile) : glisser = sélection puis zoom ; Maj + glisser, un doigt (tactile) ou ← → = déplacer la fenêtre zoomée ; Ctrl/⌘ + molette ou pincement = zoom centré sur le curseur (la molette seule défile la page) ; double-clic, Échap, Origine ou « Tout » = vue initiale ; boutons zoom +/− / réinitialiser au survol (toujours visibles au tactile et quand un zoom est actif) ; périodes 1M…Tout sur les séries temporelles.
- **Échelles** : l'axe Y est recalculé sur les points *visibles* à chaque zoom (graduations « rondes », décimales cohérentes, marge calculée sur la largeur réelle des étiquettes) ; les repères (`hlines`, `band`) ne comptent qu'à la vue initiale ou s'ils sont proches des données ; l'axe du temps choisit jours / semaines / mois / années selon la fenêtre.
- **Lisibilité** : infobulle (date + valeur de chaque série, en nœuds texte), légende cliquable (masquer une série recalcule l'échelle), trous honnêtes (une valeur absente coupe le trait), décimation min/max par colonne de pixels au-delà de 2 points par pixel.
- **Contrat de toile** inchangé : couleurs lues dans les jetons au tracé, redessin sur `patrick:themechange` et au redimensionnement (`ResizeObserver`), buffer = boîte CSS × `devicePixelRatio`, `aria-label` régénéré avec les vraies bornes de la fenêtre visible, libellés via `window.I18N` (clés `chart_*`).
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

**Taxonomie — 5 catégories fixes, dans cet ordre :**

| Clé | En-tête | Règle d'appartenance |
|-----|---------|----------------------|
| `pilotage` | PILOTAGE | Piloter la station : vue d'ensemble, suivi des runs, prédictions, analyses transverses, santé des données. |
| `modeles` | MODÈLES | Cadrer et lancer un entraînement, une page par famille : machine learning, deep learning, reinforcement learning. |
| `classes_actifs` | CLASSES D'ACTIFS | Ce que PATRICK modélise, présenté par famille de sous-jacents (univers, matières premières, macro, actions…), y compris les vues cross-actifs sur l'univers PATRICK (`/portfolio` : agrégation de signaux par classe + allocation HRP). |
| `simulation` | SIMULATION | Ouvrir des positions fictives (ticket d'ordres) et suivre les stratégies du fonds. |
| `patrimoine` | PATRIMOINE | Gestion patrimoniale réelle ou fictive : comptes, mouvements. |

Une page relève d'**une seule** catégorie (5 : `pilotage`, `modeles`, `classes_actifs`, `simulation`, `patrimoine`). En cas de doute, la catégorie est tranchée par Léon-Paul, pas par l'implémenteur. Ajouter une 5ᵉ catégorie est un amendement de ce fichier, pas un changement de code isolé. Une catégorie sans entrée n'est pas rendue (pas d'en-tête orphelin).

**Rendu (v3) :**
- En-tête de section `.sidebar-nav-heading` : Inter 10.5px, 600, uppercase, `letter-spacing: 0.08em`, `--text-3`.
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

## Anti-Patterns (Do NOT Use)

- ❌ Emojis comme icônes — icônes Lucide via `icon()` uniquement (un seul jeu, trait 2px)
- ❌ Couleur littérale dans un gabarit ou un script (hors `patrick.css` jetons)
- ❌ Une `<canvas>` dessinée à la main dans une page : tout graphique passe par `PatrickPlot` (`chart_kit.js`)
- ❌ Un texte français en dur dans un gabarit, un script ou un libellé d'erreur affiché tel quel
- ❌ Vert/rouge décoratifs (réservés au sens gain/perte)
- ❌ Translation/zoom au survol de panneaux statiques (décale la mise en page)
- ❌ Changement d'état instantané (transitions 100–200ms) ; animation ignorant `prefers-reduced-motion`
- ❌ Focus invisible ; élément cliquable sans `cursor: pointer`
- ❌ Hero, CTA commerciaux, logos clients, tunnels

## Pre-Delivery Checklist

- [ ] Les deux thèmes vérifiés (capture sombre + clair)
- [ ] 375px, 768px, 1024px, 1440px ; aucun défilement horizontal de page (`scrollWidth == clientWidth`)
- [ ] Rail replié et tiroir mobile : aucun contenu masqué
- [ ] Contraste texte ≥ 4.5:1 sur `--bg` et `--surface` dans les deux thèmes
- [ ] Focus clavier visible ; palette utilisable au clavier seul
- [ ] Graphiques : redessin au changement de thème, texte net en HiDPI
- [ ] `pytest tests/test_nav_registry.py` vert
