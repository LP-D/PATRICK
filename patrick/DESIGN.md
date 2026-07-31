---
name: PATRICK
description: Banc d'essai quant sombre et doré, où chaque chiffre affiche sa fiabilité
colors:
  bg: "#0B0D12"
  panel: "#151822"
  panel-2: "#1b1f2b"
  border: "rgba(201, 162, 75, 0.25)"
  text: "#F3EFE7"
  muted: "#9A9587"
  gold-1: "#E8C97A"
  gold-2: "#8A6A2F"
  ok: "#3FA985"
  warning: "#D9A441"
  error: "#C1544C"
  neutral: "#6E8CAE"
  pending: "#6E7FD8"
  disabled: "#6B6558"
typography:
  display:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "2.2rem"
    fontWeight: 600
  headline:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "1.6rem"
    fontWeight: 600
  title:
    fontFamily: "Cormorant Garamond, Georgia, serif"
    fontSize: "1.2rem"
    fontWeight: 600
  body:
    fontFamily: "Inter, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.95rem"
    fontWeight: 400
  label:
    fontFamily: "Inter, -apple-system, Segoe UI, Roboto, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    letterSpacing: "0.04em"
rounded:
  pill: "999px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  xl: "14px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  "6": "24px"
  "7": "32px"
  "8": "48px"
components:
  button-primary:
    textColor: "{colors.bg}"
    rounded: "{rounded.md}"
    padding: "12px 26px"
  status-badge:
    rounded: "{rounded.pill}"
    padding: "2px 9px"
    typography: "{typography.label}"
  metric:
    backgroundColor: "{colors.panel-2}"
    rounded: "{rounded.lg}"
    padding: "{spacing.4}"
  card:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.xl}"
    padding: "20px 24px"
  input:
    backgroundColor: "{colors.bg}"
    textColor: "{colors.text}"
    rounded: "{rounded.sm}"
    padding: "8px 10px"
---

# Design System: PATRICK

## Overview

**Creative North Star: "L'Instrument de Laboratoire"**

Un instrument de mesure, pas un tableau de bord de trading. La référence n'est ni la salle de marché (rouge/vert clignotant, densité maximale, urgence) ni l'outil SaaS générique : c'est l'appareil scientifique posé sur une paillasse — boîtier sombre, graduations dorées gravées, cadrans qui affichent une valeur *et* sa tolérance. On ne le consulte pas pour être stimulé, on le consulte pour lire une mesure et savoir si elle est fiable.

Cette métaphore explique les trois traits qui autrement paraîtraient arbitraires. Le fond très sombre (`bg`) n'est pas une mode « dark UI » : il fait du chiffre le seul élément lumineux de l'écran. L'or n'est pas décoratif : il est rare, réservé aux bords, aux graduations et à l'action principale — c'est la gravure sur l'instrument, jamais la donnée elle-même. Et le serif Cormorant en titres, sur un outil technique, ancre le projet du côté du carnet de recherche plutôt que du terminal : ce qu'on lit ici est un compte rendu, pas un flux.

L'interface est en mode Operate sur toutes ses surfaces : on y accomplit une tâche, jamais on n'y contemple. Aucun moment spectaculaire, aucune illustration, aucune photographie. La qualité se joue entièrement dans la précision — alignement des chiffres, cohérence des états, justesse des libellés. Un écran qui impressionne mais qu'on ne peut pas piloter est un échec ici.

**Key Characteristics:**
- Fond sombre quasi-noir : le chiffre est la seule source de lumière
- Or rare et structural (bords, graduations, action principale) — jamais porteur de donnée
- Serif éditorial en titres, sans-serif tabulaire en données
- Six états sémantiques distincts, dont trois qui ne sont ni succès ni échec
- Chiffres en chasse fixe (`tabular-nums`) partout, sans exception
- Zéro imagerie : aucune photo, aucune illustration, aucune icône décorative

## Colors

Palette sombre à accent unique : un or froid porte toute l'identité, six teintes sémantiques portent tout le sens, et rien d'autre n'a le droit d'exister.

### Primary
- **Or Pâle** (`gold-1`) : l'accent unique. Bords au repos (à 25 % d'opacité via `border`), texte actif, focus, dégradé de l'action principale, graduation du monogramme. Il signale « ceci est vivant / sélectionné / actionnable », jamais « ceci est bon ».
- **Or Brûlé** (`gold-2`) : uniquement l'extrémité sombre des dégradés (bouton principal, barre de progression, pastille de `legend`). Ne s'emploie jamais seul, en aplat ni en texte.

### Secondary
- **Vert Éprouvé** (`ok`) : résultat validé, porte de qualité active, run terminé.
- **Ambre d'Alerte** (`warning`) : résultat à surveiller — sous un seuil, non significatif, fiabilité faible. **Pas une erreur** : une réserve.
- **Rouge Sourd** (`error`) : échec réel, exclusion, valeur invalide. Volontairement sourd, jamais saturé : un échec méthodologique se lit, il ne crie pas.

### Tertiary
Trois états ajoutés en Phase 7 pour les cas que le triptyque vert/ambre/rouge écrasait :
- **Bleu Ardoise** (`neutral`) : informatif, sans jugement — schéma de validation, comptage, rang.
- **Indigo d'Attente** (`pending`) : en cours ou en file. L'issue n'est pas encore connue.
- **Gris Étouffé** (`disabled`) : désactivé pour ce run, ou non calculable. **Ni un succès ni un échec.**

### Neutral
- **Ivoire** (`text`) : texte courant. Légèrement chaud, jamais blanc pur.
- **Sable Éteint** (`muted`) : texte secondaire, en-têtes de colonne, contreparties de fiabilité, libellés d'axe.
- **Encre** (`bg`) : fond de page et fond des champs de saisie — les entrées sont *en creux*, plus sombres que leur conteneur.
- **Ardoise** (`panel`) : encarts et barre supérieure.
- **Ardoise Claire** (`panel-2`) : second niveau — fieldsets, cartes de métrique, journaux, survol de ligne. Un cran plus clair pour que les champs en `bg` restent visibles en creux à l'intérieur.

### Named Rules

**La Règle de l'Or Structural.** L'or décrit la structure, jamais la donnée. Un bord, un focus, une graduation, l'action principale : oui. Une valeur, un statut, une métrique : jamais. Test : si l'or disparaissait, aucune information ne devrait être perdue — seulement le relief.

**La Règle des Trois États Neutres.** « Non calculable », « désactivé pour ce run » et « en attente » ne sont ni verts ni rouges. Forcer l'un de ces cas dans le vert ou le rouge est un bug de conception, pas un raccourci : cela transforme une absence de mesure en jugement.

**La Règle de l'Échec Sourd.** Les couleurs d'échec sont désaturées par rapport à leur équivalent web standard. Un verdict négatif est un livrable normal de cet outil (cf. PRODUCT.md) — il s'affiche avec la même dignité qu'un succès.

## Typography

**Display Font:** Cormorant Garamond (avec Georgia, serif)
**Body Font:** Inter (avec -apple-system, Segoe UI, Roboto)

**Character:** Un serif éditorial à fort contraste pour tout ce qui nomme, un grotesque neutre pour tout ce qui mesure. Le contraste entre les deux est la seule ornementation du système : le Cormorant apporte la voix du carnet de recherche, l'Inter disparaît pour laisser lire les chiffres.

### Hierarchy
- **Display** (serif, 600, 2.2rem) : titre de page. Un seul par écran.
- **Headline** (serif, 600, 1.6rem) : titre de vue majeure (simulateur).
- **Title** (serif, 600, 1.2rem) : titre d'encart, de carte, de section.
- **Body** (Inter, 400, 0.95rem) : texte courant, valeurs de formulaire.
- **Label** (Inter, 600, 0.75rem, `letter-spacing` 0.04em, capitales) : en-têtes de tableau, libellés de métrique, marque temporelle. Les capitales sont réservées à ce rôle.
- **Hint** (Inter, 400, 0.85rem, en `muted`) : la contrepartie de fiabilité. Rôle à part entière, pas une note de bas de page.

### Named Rules

**La Règle des Chiffres Alignés.** `font-variant-numeric: tabular-nums` est posé sur `body` et ne doit jamais être annulé. Deux nombres l'un sous l'autre doivent pouvoir se comparer en colonne, sans lecture. C'est non négociable dans un outil de mesure.

**La Règle du Serif Nommant.** Le serif nomme, le sans-serif mesure. Un chiffre en Cormorant est une faute ; un titre de section en Inter aussi.

## Layout

Conteneur centré à 1560px avec 24px de marge — large, parce que les tableaux de résultats portent beaucoup de colonnes et que les tronquer coûte plus que la longueur de ligne ne gagne.

Deux topologies coexistantes selon le rythme d'usage :
- **Grille fixe** (tableau de bord) : 2×2, lignes de 420px minimum, hauteur calée sur la fenêtre (`100vh - 120px`, plancher 640px). Chaque encart défile **indépendamment** ; seule sa zone de corps bouge, son en-tête reste fixe. Choix délibéré : des contenus de longueurs très inégales ne doivent pas étirer la page.
- **Flux libre** (simulateur, pages d'historique) : hauteur variable, la page défile normalement. Le simulateur pose une colonne de configuration fixe à 340px contre une zone de résultats fluide.

Rythme d'espacement en base 4px, huit pas (`spacing.1` à `spacing.8`). Les grilles de contenu répétable utilisent `auto-fit` avec un plancher explicite plutôt qu'un nombre de colonnes figé : 180px pour les métriques, 220px pour les listes de variations, 140px pour les sous-champs de formulaire.

Point de rupture unique : **980px**. En dessous, la grille 2×2 s'effondre en colonne unique avec des encarts plafonnés à 70vh, et la grille du simulateur passe en pile. Il n'y a pas d'échelle de points de rupture : l'outil est pensé pour un écran de travail, le mobile est une dégradation gracieuse, pas une cible.

**La Règle du Plancher Explicite.** Toute grille répétable déclare une largeur minimale de cellule. Un tableau qui se comprime jusqu'à l'illisible pour tenir sur une ligne trahit l'outil : on préfère le défilement horizontal contenu.

## Elevation & Depth

Système **essentiellement plat, à profondeur tonale**. La hiérarchie vient de trois niveaux de fond empilés (`bg` → `panel` → `panel-2`) et d'un bord doré à 25 % d'opacité, pas d'un système d'ombres. Le bord fait le travail que l'ombre ferait ailleurs.

L'ombre est réservée à quatre rôles précis, jamais décoratifs :

### Shadow Vocabulary
- **Séparation de barre fixe** (`0 2px 14px rgba(0,0,0,0.35)`) : uniquement sous la barre supérieure collante, pour la détacher du contenu qui défile dessous.
- **Flottement de surcouche** (`0 8px 24px rgba(0,0,0,0.45)`) : uniquement pour l'infobulle de glossaire, qui sort du flux.
- **Lueur d'action** (`0 4px 14px rgba(232,201,122,0.2)`, au survol `0 6px 18px .../0.3`) : uniquement sur l'action principale. C'est la seule ombre colorée du système.
- **Anneau de focus** (`0 0 0 3px rgba(232,201,122,0.15)`) : sur les champs actifs, doublé d'un passage du bord en or plein.

### Named Rules

**La Règle du Plat au Repos.** Une surface au repos n'a pas d'ombre. L'ombre est une réponse à un état (collé, flottant, survolé, focalisé) ou n'existe pas. Une carte, un encart, une métrique, un tableau : plats, toujours.

## Shapes

Langage de formes **doux mais non arrondi** : le rayon augmente avec la surface, ce qui donne une hiérarchie lisible sans variation de couleur.

- **8px** — champs de saisie, liens de téléchargement, onglets de navigation supérieure. L'échelle du contrôle.
- **10px** — bouton principal, journaux, zones de graphique, infobulle. L'échelle du bloc.
- **12px** — cartes de métrique, bannières. Palier intermédiaire.
- **14px** — encarts, cartes, fieldsets, états vides. L'échelle du conteneur.
- **999px** — exclusivement les pastilles d'état (`status-badge`). La pilule est réservée au statut ; rien d'autre n'est complètement arrondi.
- **50%** — points et anneaux uniquement : monogramme, pastille de `legend`, icône d'information, point de la pastille d'état.

Les bords sont systématiquement 1px en `border` (or à 25 %). Deux exceptions expressives et volontaires : le tiret (`1px dashed`) marque le provisoire ou le contenant sans contenu — file d'attente, état vide, séparateur de sous-groupe ; le pointillé (`1px dotted`) souligne les liens d'actualité.

**La Règle du Rayon Croissant.** Le rayon suit la taille : contrôle 8, bloc 10, conteneur 14. Un petit élément très arrondi ou un grand conteneur à angle vif casse la lecture de hiérarchie.

## Components

### Buttons
- **Shape:** rayon de bloc (10px), sans bord.
- **Primary:** dégradé or (135°, `gold-1` → `gold-2`), texte en `bg` — l'unique inversion de contraste du système, réservée à l'action qui lance un run ou une simulation. Padding 12px 26px, 600.
- **Hover / Focus:** la lueur d'action s'intensifie ; l'appui descend d'1px (`translateY(1px)`).
- **Disabled:** opacité 0.5, ombre retirée, curseur interdit.
- **Secondary:** il n'existe pas de bouton secondaire plein. Les actions secondaires sont des liens bordés (`downloads`, `topnav`, `range-btn`) : transparents au repos, bord et texte passant à l'or au survol.

### Chips
- **`status-badge`** — pilule 999px, texte 0.75rem 600, avec un **point de 6px en `currentColor`** en préfixe. Fond et bord dérivent de la couleur d'état à 12 % et 30 % d'opacité.
- **Six variantes obligatoires** : `ok`, `warning`, `error`, `neutral`, `pending`, `disabled`. Le point coloré rend l'état lisible sans dépendre uniquement de la teinte.

### Cards / Containers
- **`card`** : fond `panel`, bord or 25 %, rayon 14px, padding 20px/24px. Titre en serif 1.2rem.
- **`dash-panel`** : même habillage, mais en colonne flex avec en-tête figé et corps défilant indépendamment.
- **`metric`** : fond `panel-2`, rayon 12px, padding 16px. **Structure en trois parties, non négociable** : libellé en capitales `muted`, valeur en serif 1.6rem colorée par l'état, puis contrepartie de fiabilité en `hint`.
- **Shadow Strategy:** aucune (cf. Règle du Plat au Repos).

### Inputs / Fields
- **Style:** fond `bg` (plus sombre que le conteneur — en creux), bord or 25 %, rayon 8px, padding 8px 10px.
- **Focus:** bord en `gold-1` plein + anneau de focus. Le contour natif est retiré, remplacé — jamais simplement supprimé.
- **Fieldset:** fond `panel-2`, rayon 14px, bord passant à l'or plein au `focus-within` — le groupe entier signale qu'on travaille dedans.
- **Legend:** serif 1.05rem, précédé d'une pastille dégradée or de 8px.

### Navigation
- **Barre supérieure** collante, fond `panel`, séparée par la seule ombre de barre fixe. Monogramme + nom en serif espacé (0.06em), accroche en capitales `muted`, puis navigation et sélecteur de langue poussés à droite.
- **`topnav`** : liens bordés, rayon 8px, 0.85rem 600 en `muted` ; bord et texte passent à l'or au survol.
- **`tabs`** (pages de détail) : soulignement de 2px transparent au repos, or à l'actif. Pas de fond, pas de pilule.

### Signature: la métrique à contrepartie

Le composant qui porte la thèse du produit. Aucune valeur ne s'affiche sans sa troisième ligne : intervalle de confiance, taille d'échantillon, ou raison explicite de non-calculabilité. Le gabarit force ce troisième argument — il ne peut pas être omis par distraction. Quand la valeur n'est pas calculable, elle s'affiche « — » en `disabled` accompagnée du motif, **jamais** `nan`, `0`, ou un blanc.

### Signature: l'icône de glossaire

Un cercle de 16px bordé en `muted`, portant « i », posé après un terme technique. Au survol il passe à l'or, au clic il ouvre une infobulle flottante. C'est le compromis assumé du produit : le vocabulaire quant reste intact (cf. PRODUCT.md), l'explication est disponible à la demande sans diluer le libellé.

## Do's and Don'ts

### Do:
- **Do** afficher la contrepartie de fiabilité de chaque chiffre — IC, n, ou motif de non-calculabilité — dans la troisième ligne de la métrique.
- **Do** utiliser `disabled` (gris) pour « non calculable » et « désactivé pour ce run », et `pending` (indigo) pour « en cours ».
- **Do** conserver `tabular-nums` sur toute donnée numérique.
- **Do** déclarer une largeur minimale de cellule sur toute grille répétable.
- **Do** remplacer le contour de focus natif par le bord or + l'anneau ; ne jamais se contenter de le retirer.
- **Do** garder le serif pour nommer et l'Inter pour mesurer.

### Don't:
- **Don't** utiliser l'or pour porter une donnée ou un statut — il est structural (Règle de l'Or Structural).
- **Don't** afficher `nan`, `Infinity`, `null` ou une cellule vide : un chiffre non calculable s'écrit « — » avec son motif.
- **Don't** ajouter une ombre à une surface au repos.
- **Don't** introduire une septième couleur sémantique ni une teinte hors palette ; les six états couvrent les cas, et un cas nouveau se discute avant de s'ajouter.
- **Don't** arrondir complètement (999px) autre chose qu'une pastille d'état.
- **Don't** ajouter photographie, illustration ou icône décorative : le système est sans imagerie par construction.
- **Don't** saturer les couleurs d'échec pour « alerter davantage » (Règle de l'Échec Sourd).
- **Don't** traiter le monogramme « P » comme un logo : c'est un placeholder CSS explicitement documenté.
