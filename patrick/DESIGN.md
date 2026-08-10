---
name: PATRICK
description: Nocturne — un instrument de mesure professionnel, dense et sombre, pas un tableau de bord SaaS générique.
colors:
  ink: "#0D0E17"
  ink-2: "#171A28"
  ink-text: "#E9E9ED"
  ink-text-2: "#B2B6CA"
  ground: "#161826"
  surface: "#232532"
  raise: "#282B3B"
  rule: "#34384A"
  rule-strong: "#3D4258"
  text: "#E9E9ED"
  text-2: "#A2A2AC"
  text-3: "#8C8C99"
  accent: "#9184D9"
  accent-hover: "#A7A1DB"
  on-accent: "#0D0E17"
  accent-ink: "#9184D9"
  ok: "#3BC493"
  warn: "#E0A94E"
  error: "#FF8172"
  pending: "#9397AB"
  ok-ink: "#35C08A"
  warn-ink: "#E0A94E"
  error-ink: "#FF8172"
typography:
  head:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  value:
    fontFamily: "ui-monospace, Menlo, SF Mono, Consolas, Liberation Mono, monospace"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  lead:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "ui-monospace, Menlo, SF Mono, Consolas, Liberation Mono, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  small:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.55
    letterSpacing: "normal"
  micro:
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 500
    lineHeight: 1.5
    letterSpacing: "0.12em"
rounded:
  small: "4px"
  control: "8px"
  panel: "14px"
  chip: "999px"
spacing:
  s1: "2.8px"
  s2: "5.6px"
  s3: "8.4px"
  s4: "11.2px"
  s5: "14px"
  s6: "16.8px"
  s7: "19.6px"
  s8: "22.4px"
components:
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.panel}"
    padding: "20px 24px 24px"
  station-bar:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ink-text}"
    padding: "12px 24px"
  station-mark:
    textColor: "{colors.ink-text}"
    accentColor: "{colors.accent-ink}"
    size: "1.3em"
  record-plate:
    backgroundColor: "{colors.ink-2}"
    rounded: "6px"
    height: "72px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "{colors.on-accent}"
  input:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "7px 12px"
  metric-value:
    textColor: "{colors.text}"
    typography: "{typography.value}"
  metric-reliability:
    textColor: "{colors.text-3}"
    typography: "{typography.micro}"
    padding: "8px 0 0 12px"
  status-badge:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text-2}"
    typography: "{typography.micro}"
    rounded: "{rounded.chip}"
    padding: "2px 8px 2px 7px"
  table-header:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text-2}"
    typography: "{typography.micro}"
    padding: "12px 16px"
  table-cell:
    textColor: "{colors.text}"
    typography: "{typography.body}"
    padding: "12px 16px"
  empty-state:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text-2}"
    typography: "{typography.small}"
    rounded: "{rounded.control}"
    padding: "16px"
  verdict-value:
    textColor: "{colors.ink-text}"
    typography: "{typography.micro}"
  verdict-label:
    textColor: "{colors.ink-text-2}"
    typography: "{typography.micro}"
  scope-line:
    textColor: "{colors.text-3}"
    typography: "{typography.small}"
  adv-gate:
    backgroundColor: "{colors.raise}"
    textColor: "{colors.text-2}"
    typography: "{typography.micro}"
    rounded: "{rounded.small}"
    padding: "1px 6px"
  adv-gate-off:
    backgroundColor: "{colors.warn}"
    textColor: "{colors.warn}"
  launch-bar-armed:
    backgroundColor: "{colors.pending}"
    textColor: "{colors.text}"
    padding: "16px 20px"
---

# DESIGN.md — PATRICK

Généré depuis le code construit (`patrick/webapp/`), pas depuis une intention.
Le contrat de direction dont ce document est la mise à plat est en commentaire
HTML en tête de `templates/base.html` (blocs THESIS / OWN-WORLD / STORY /
FIRST VIEWPORT / FORM). Les jetons normatifs vivent dans `static/tokens.css` ;
ce fichier explique **comment les appliquer**, il ne les remplace pas.

## Overview

Le monde s'appelle **« Nocturne »**. Extrait d'une maquette de référence
(deux directions : 1a dense façon terminal, 1b aérée façon analytics) et
réassigné sur la structure sémantique déjà en place — les composants Jinja
n'ont pas été réécrits, seule la feuille de jetons change.

Il remplace **intégralement** le monde précédent, « Station d'observation »
(boîtier encre profonde / papier clair, Archivo + Spline Sans Mono, échelle
d'élévation à décalage + flou dès le premier niveau). Si vous trouvez
`--shadow-panel`, `--shadow-raised`, `--shadow-overlay`, `Archivo` ou
`Spline Sans Mono`, c'est un résidu à migrer, pas une variante à respecter.

**La thèse produit ne change pas** — elle appartient au produit, pas à son
habillage : *un chiffre ne s'écrit jamais seul*. La signature de `metric()`
force toujours un troisième argument `reliability` ; le verdict de la station
imprime toujours un tiret et son motif tant qu'aucune cible n'a de résultat
Diebold-Mariano, jamais « 0 / 0 » qui se lirait comme un échec. *La station
montre ce qu'elle a enregistré avant qu'on le demande* — le bandeau porte
toujours, sur les cinq surfaces, la bande des runs récents et les deux
chiffres du verdict.

Mode : **Operate**. La scannabilité et la densité priment sur l'expression ;
Nocturne les sert par un fond sombre dense et un accent unique, pas par
l'ornement.

**Mode sombre seul pour cette passe.** `:root` porte directement les valeurs
Nocturne (actives par défaut, pas une bascule) ; `[data-theme="light"]` est un
bloc vide, préparé mais pas écrit — voir « Écarts connus » et
`KNOWN_ISSUES.md`. Le bouton de bascule jour/nuit est masqué tant que ce bloc
est vide.

### Identité

Le nom **PATRICK** est une contrainte intouchable, quelle que soit l'identité
visuelle. Il s'écrit en chasse fixe (`.station-name`), à gauche du bandeau.

**La marque** (`.station-mark`) le précède : un anneau qui enferme trois barres
montantes, la dernière coiffée d'un point d'accent. C'est un relevé, pas un
emblème — la même lecture que la bande d'enregistrement posée juste dessous :
des événements ponctuels, de hauteur inégale, le plus récent à droite. Le
dessin lui-même n'a pas changé avec Nocturne, seules ses couleurs (`currentColor`
→ `--ink-text`, tête → `--accent-ink`) suivent la nouvelle palette.

Trois règles la tiennent :

- **Un seul lien** porte la marque et le nom. Deux liens voisins vers la même
  destination seraient deux arrêts de tabulation pour un seul geste ; le SVG
  est `aria-hidden`, le nom qu'il accompagne étant déjà le nom accessible.
- **Aucune couleur codée en dur.** L'anneau et les barres prennent
  `currentColor`, donc `--ink-text` ; la tête reçoit `--accent-ink` par CSS.
  Une couleur écrite dans le SVG survivrait à un remplacement d'identité et
  repeindrait l'ancien monde — c'est exactement ce que ce remplacement de
  jetons vient de vérifier en pratique.
- **Taille en `em`.** À 200 % de zoom texte, une marque en pixels devient une
  vignette accrochée à un mot.

Le favicon porte la **même géométrie** — seule l'échelle change. Deux dessins
différents pour un même produit se contrediraient.

## Colors

### Deux matières, pas un dégradé de gris

Règle structurante du monde, conservée de « Station d'observation » — à
comprendre avant de toucher une couleur.

- **Le boîtier** (`--ink`, `--ink-2`) porte le bandeau, la bande
  d'enregistrement, le verdict, le contexte de reproductibilité, le journal de
  run, et **toutes les plaques de tracé**.
- **Le papier** (`--ground` plan de travail, `--surface` feuille posée dessus,
  `--raise` creux d'un champ) porte la lecture.

Nocturne, source de cette passe, n'a que deux paliers (`--color-bg`/
`--color-surface`) — `--ink` n'y est pas fourni. Dérivé plus sombre que
`--ground`, même famille de teinte (indigo profond), pour rester la matière la
plus profonde de la scène : mesuré, luminance `--ink` 0,0046 < `--ground`
0,0096.

**Les jetons « sur boîtier »** (`--accent-ink`, `--ok-ink`, `--warn-ink`,
`--error-ink`) restent la structure d'invariants du monde précédent, prête
pour un futur mode clair — `--accent-ink` est aujourd'hui un simple alias de
`--accent` (Nocturne n'a qu'une valeur d'accent, la distinction n'a de sens
que quand deux thèmes existent). `ok-ink`/`warn-ink`/`error-ink` ne sont pas
couverts par la source Nocturne : conservés de l'ancien système, revérifiés
(pas supposés) contre les trois fonds — 6,25:1 à 9,11:1 partout.

**`--on-accent`** porte le texte posé sur l'accent plein. Mesuré : le blanc
échoue sur l'accent Nocturne (#9184D9, 3,23:1, sous AA) — contrairement à
l'ancien accent bleu sombre qui le tenait. `--on-accent` vaut `--ink`
(5,96:1), dans la famille du boîtier plutôt qu'un noir arbitraire.

### Stratégie : Restrained

Neutres + un accent unique. **L'accent ne dit qu'une chose : « ceci est
interactif ou actif ».** Il ne porte jamais une donnée, jamais un jugement.
Les jugements ont leurs propres jetons (`--ok`, `--warn`, `--error`,
`--pending`) et ceux-là ne servent qu'à ça.

Il n'existe **pas** de jeton « info ». Un état sans jugement s'écrit dans la
couleur du texte.

**`--pending` est délibérément hors de la famille de l'accent.** L'accent
Nocturne (#9184D9) est violet ; l'ancien `--pending` (#BE95F7) l'était aussi —
les deux se seraient lus comme une seule et même couleur, confondant
« interactif/actif » et « en attente de confirmation ». `--pending` prend
`#9397AB`, un ton de la rampe neutre (déjà l'anneau de `--shadow-lg`,
cohérence gratuite) plutôt qu'une nuance d'accent — vérifié (`#75798C`, l'autre
candidat neutre, échoue AA partout : 3,52:1 à 4,46:1, contre 5,25:1 à 6,64:1
pour `#9397AB`). `--pending` porte toujours l'attente de confirmation (barre
de lancement armée) : armer n'est pas avertir.

### Un rendu écrit, un chemin préparé pour le second

`:root` porte Nocturne directement — ce n'est **pas** une bascule pour cette
passe, contrairement à l'ancien système où `:root` était le thème clair par
défaut et `[data-theme="dark"]` un override. `[data-theme="light"]` existe en
bloc vide : l'architecture (jetons sémantiques, structure `:root` +
`[data-theme]`) est prête à recevoir un mode clair sans réarchitecturer la
feuille de jetons ni les composants qui la consomment, mais aucune valeur n'y
est écrite. Voir « Écarts connus ».

### Contraste

Tout texte tient 4,5:1 sur **son fond réel**, fond composité des pastilles
teintées inclus ; tout texte large ou composant d'UI tient 3:1. Recalculé
indépendamment (luminance relative WCAG) pour chaque jeton Nocturne avant
application — pas supposé conforme parce que la maquette source semblait
lisible : un des tons atténués qu'elle utilise (`.card-meta`, 50 % de mélange)
échoue AA sur `--surface` (4,26:1, mesuré), ce qui a fait fixer `--text-3` à
60 % plutôt qu'une valeur de la source. Les valeurs mesurées sont en
commentaire dans `tokens.css`, ligne par ligne — ne pas modifier une couleur
sans refaire le calcul.

## Typography

Une seule famille, Inter, servie depuis `/static/fonts/` — **aucune requête
CDN**. Remplace Archivo (chrome) + Spline Sans Mono (donnée) : la maquette
Nocturne n'a qu'une police, la hiérarchie titre/corps se fait par graisse
(**500 sur les titres**, contre 600-700 dans l'ancien système) et par taille,
pas par changement de famille.

- **Inter** (`--display`, aliasée `--ui`) : chrome, titres, libellés, boutons,
  en-têtes de colonne, pastilles d'état.
- **`--mono`** (police monospace système, `ui-monospace, Menlo, SF Mono...`) :
  **toute donnée**, plus le nom du produit. La classe utilitaire `pk-mono`
  (nom repris de la maquette Nocturne) documente explicitement l'intention
  dans le balisage de `metric()`/`data_table()`, en plus de la règle
  mécanique ci-dessous.

**Le contraste des deux familles porte toujours la hiérarchie**, pas la
taille seule — même principe qu'avant, une seule famille chrome au lieu de
deux.

Règle mécanique inchangée : `table, .num, .mono, .pk-mono, code, pre,
.metric-value, input, select, textarea` reçoivent `--mono` + `tabular-nums` +
`"tnum" 1, "zero" 1`. Non négociable — c'est ce qui permet l'alignement
décimal.

Six pas, **valeurs inchangées** (`--t-micro` 12px → `--t-head` 28px) — la
source Nocturne ne redéfinit pas d'échelle numérique, seulement famille et
graisse des titres. Tout titre porte toujours `overflow-wrap: break-word`
(mesuré à 200 % de zoom texte en 390px, cf. historique).

## Layout

Section **inchangée par ce chantier** — Nocturne ne touche ni à la grille, ni
à la divulgation progressive, ni à la barre collante, ni à l'adaptation
tactile : uniquement jetons de couleur, typographie, espacement, rayon,
élévation.

### La grille du poste

Asymétrique et délibérée : `1.3fr / 1fr`. La colonne gauche porte la tâche
principale, la droite ce qui la sert.

**Aucun panneau ne défile en interne.** Le seul défilement d'une page est
celui de la page.

### Divulgation progressive

Deux blocs de formulaire restent ouverts — le nom du run et l'objectif. Les
neuf autres se replient en `<details>` portant leur état en résumé.

### Barre de lancement collante

En bas de la colonne de configuration, avec le rappel cible / horizons /
schéma. `html` réserve `scroll-padding-bottom` égal à `--launch-bar-h`.

### Adaptation : le pointeur, pas la largeur

Les cibles tactiles s'adaptent sur `pointer: coarse`, jamais sur une largeur
de viewport. Deux seuils : 44px pour un contrôle (WCAG 2.5.5), 24px pour un
lien de texte dans une table dense (WCAG 2.5.8).

Ruptures inchangées : 1100px (simulateur en colonne), 980px (grille du poste
en colonne, bandeau enroulé).

## Elevation & Depth

**Philosophie remplacée, pas fusionnée** avec l'ancien système à 4 niveaux
(`--shadow-panel`/`--shadow-raised`/`--shadow-overlay`/`--shadow-control`,
tous à décalage + flou dès le premier niveau). Nocturne : **anneau fin
d'abord** (1px, net, sans flou), **ombre diffuse croissante ensuite**.

- `--shadow-sm` — anneau seul (`0 0 0 1px #3F424D`). Rôle : carte au repos,
  bord de plaque (`--plate-edge` de l'ancien système est absorbé ici), champ
  et bouton au repos.
- `--shadow-md` — anneau plus clair + ombre diffuse moyenne. Rôle : tooltip,
  élément relevé/actif. `--shadow-md-up` en miroir vertical pour la barre de
  lancement collante (objet collé au bas du viewport, l'ombre porte vers le
  haut sur le contenu surplombé).
- `--shadow-lg` — anneau le plus clair + ombre diffuse large. Rôle : ce qui
  flotte au-dessus de **toute** la page — seul le popover du glossaire
  (`role="dialog"`) l'utilise aujourd'hui.

Le filet ne structure plus la page : il sépare deux lignes **dans** un panneau
(`--rule`) ou cerne un objet manipulable (`--rule-strong`).

**Jamais de panneau dans un panneau** : il ne dit rien de plus que le filet
qu'il remplace et brouille la hiérarchie.

**Détail signature Nocturne** : les filets de table (`data_table()`,
leaderboard) sont peints en dégradé fondu sur 48px à chaque bout plutôt qu'un
arrêt net — porté par la ligne (`background`, peint en bas de la ligne),
jamais par une bordure de cellule.

### Mouvement

**Un seul moment authoré** : la bande se révèle de gauche à droite en 620ms
(sortie cubique) au chargement. Le reste est fonctionnel : la jauge balaie
**uniquement** pendant les phases non mesurables, le leaderboard glisse au tri
(FLIP), le panneau de résultats apparaît. `prefers-reduced-motion` retire le
mouvement, **jamais** l'information.

## Shapes

`--r-small` 4px (plaque de tracé, micro-contrôle du bandeau, pastille d'état
de brique), `--r-control` 8px (champ, bouton, état vide — inchangé), `--r-panel`
14px (panneau), `--r-chip` 999px (pastille d'état, bouton de plage) — rayons
Nocturne exacts (`--radius-sm`/`md`/`lg` de la source), remplacent 6/8/12px.

### Focus — un seul régime, sans exception

```css
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--r-small);
}
```

Règle inchangée par ce chantier. **Toute règle qui repose `outline: none` sur
un élément focusable est un défaut.**

## Components

Composants Jinja partagés dans `templates/_components.html`, CSS dans
`static/style.css`, jetons dans `static/tokens.css`. **Aucun composant n'a été
réécrit par ce chantier** — seule la feuille de jetons change, R2 de la
consigne Nocturne. `metric()` et `data_table()` portent en plus la classe
`pk-mono` sur leurs valeurs/colonnes numériques (documentation explicite dans
le balisage, redondante avec la règle mécanique mais utile hors table/metric).

**`metric(label, value, reliability, state)`** — le composant signature. Le
troisième argument est **obligatoire**. Valeur en `--t-value` (24px) en chasse
fixe (`pk-mono`) ; ligne de fiabilité décrochée par un filet vertical de 1px.

**`data_table(headers, rows, empty_message, row_classes, num_cols, footer)`** —
`num_cols` porte les indices des colonnes de **mesure** ; elles seules
reçoivent les classes `num pk-mono`. Filet de ligne en dégradé fondu 48px
(voir Elevation & Depth), en-tête collant sur fond `--raise`.

**`status_badge(label, state)`** — pastille avec point de 6px en
`currentColor`. Six états, `--pending` désormais un ton neutre (voir Colors),
plus jamais confondable avec l'accent.

**`empty_state` / `error_state`** — encadré sur `--raise`, message préfixé de
`NA`. Inchangé.

**Le verdict de la station** (`.verdict`) — inchangé structurellement, jetons
Nocturne (chasse fixe boîtier).

**Les lignes de portée locale** (`.scope-line`) — inchangées.

**La bande d'enregistrement** (`.record`, `observatory.js`) — inchangée.

**Les briques de rigueur** (`.adv-gate`) — inchangées.

**La barre de lancement à deux temps** — `--shadow-md-up` remplace l'ombre
codée en dur de l'ancien système (une seule couche, jamais redéfinie en
sombre). Le teinté d'armement reste **composé sur** la surface.

**Le glossaire** — `--shadow-lg` remplace `--shadow-overlay` : même rôle
(flotte au-dessus de toute la page), nouvelle mécanique (anneau + diffus large
plutôt que décalage + flou).

**Toiles (canvas)** — inchangées : lisent les jetons au tracé, aucun repli
codé en dur.

## Do's and Don'ts

**À faire**

- Écrire la contrepartie de fiabilité de chaque chiffre.
- Refuser d'imprimer une mesure non interprétable, et dire pourquoi.
- Rendre l'état d'une brique de rigueur en permanence, ON comme OFF.
- Déclarer `num_cols` sur toute table portant des mesures.
- Fermer chaque liste par un pied portant compte et réserves.
- Poser toute toile sur le boîtier et lire ses couleurs sans repli.
- Donner à toute surface au repos son état vide écrit.
- Adapter les cibles tactiles sur `pointer: coarse`, jamais sur la largeur.
- Vérifier le contraste sur le fond **composité réel**.
- Poser `--shadow-sm` avant `--shadow-md`/`--shadow-lg` — l'anneau fin est le
  niveau de repos, pas une étape à sauter.

**À ne pas faire**

- Afficher un chiffre nu, sans dénominateur ni réserve.
- Afficher une valeur ponctuelle à côté d'un message disant qu'elle n'a pas
  été calculée.
- Résumer un bloc replié en ne listant que ce qui est activé.
- Utiliser l'accent pour porter une donnée ou un jugement.
- Poser `--pending` (ou tout jugement) dans la famille de teinte de l'accent.
- Imbriquer un panneau dans un panneau.
- Poser du texte clair codé en dur sur un fond d'accent — c'est `--on-accent`.
- Reposer `outline: none` sur un élément focusable.
- Afficher « 0 % » pendant une phase qui ne produit aucune mesure.
- Poser un `cursor: pointer` sur un élément que rien n'active.
- Écrire une ombre à décalage + flou dès le premier niveau — c'est l'ancienne
  mécanique, pas celle de Nocturne.

## Écarts connus entre le contrat et le code

Documentés parce qu'ils sont réels, pas corrigés ici :

- **Mode clair non implémenté.** `[data-theme="light"]` est un bloc vide dans
  `tokens.css` — l'architecture est prête, aucune valeur n'est écrite. Le
  bouton de bascule jour/nuit est masqué en conséquence. Chantier futur
  distinct, voir `KNOWN_ISSUES.md`.
- **`metric()` n'apparaît nulle part sur `/`**, et la page n'affiche aucun
  chiffre en typographie de valeur — décision explicite de l'utilisateur,
  inchangée par ce chantier.
- **La bande ne porte pas la durée d'un run**, seulement son rang et son
  effort. `finished_at` existe en base et n'est pas exploité.
- **`sparkline()`** est déclarée dans `_components.html` et jamais appelée.
- **Aucune capture ne montre une toile de marché avec données** : le réseau
  yfinance est coupé dans l'environnement de construction.
- **Aucun lien d'évitement** : la première tabulation atterrit sur la marque et
  le nom du produit, pas sur un « aller au contenu ».
- **La marque est une interprétation du logo fourni**, redessinée de mémoire —
  inchangée par ce chantier, seules ses couleurs suivent Nocturne.
