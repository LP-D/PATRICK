---
name: PATRICK
description: Station d'observation — un chiffre ne s'écrit jamais seul, et la station enregistre même quand personne ne regarde.
colors:
  ink: "#0B1220"
  ink-2: "#16213A"
  ink-text: "#EDF1F7"
  ink-text-2: "#9FAEC6"
  ground: "#ECEFF4"
  surface: "#FFFFFF"
  raise: "#F4F6FA"
  rule: "#DEE3EC"
  rule-strong: "#C3CBD8"
  text: "#0F1626"
  text-2: "#47536A"
  text-3: "#626D80"
  accent: "#1B4FD8"
  accent-hover: "#143CAB"
  on-accent: "#FFFFFF"
  accent-ink: "#7EA6FF"
  ok: "#0B6E4F"
  warn: "#8A5A08"
  error: "#B32D22"
  pending: "#5B34B0"
  ok-ink: "#35C08A"
  warn-ink: "#E0A94E"
  error-ink: "#FF8172"
typography:
  head:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 700
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  value:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  lead:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  small:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.55
    letterSpacing: "normal"
  micro:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0.12em"
rounded:
  small: "6px"
  control: "8px"
  panel: "12px"
  chip: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
  s7: "32px"
  s8: "48px"
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

Le monde s'appelle **« Station d'observation »**. Il rend l'outil comme un
appareil de mesure en service : un boîtier d'encre profonde qui porte
l'identité, l'enregistrement et le verdict ; des feuilles de papier posées
dessus qui portent la lecture.

Il remplace **intégralement** le monde précédent, « Sortie de solveur » (noir
plat, filets horizontaux seuls, chasse fixe partout, rayons à zéro, états
écrits `[DONE]`). Si vous trouvez `--r-none`, `JetBrains Mono`, un
`border-radius: 0` posé par doctrine ou un badge à crochets, c'est un résidu à
supprimer, pas une variante à respecter.

**La thèse tient en deux propositions.**

La première appartient au produit, pas à son habillage : *un chiffre ne
s'écrit jamais seul*. La signature de `metric()` force un troisième argument
`reliability` — le gabarit ne devine jamais l'incertitude. Quand une mesure
n'est pas interprétable, le produit **refuse de l'imprimer** : il affiche `—`,
le motif en clair, et renvoie la justification longue en note sous le bloc.
Cette règle vaut jusque dans le bandeau : le verdict de la station imprime un
tiret et son motif tant qu'aucune cible n'a de résultat Diebold-Mariano,
jamais « 0 / 0 » qui se lirait comme un échec.

La seconde est propre à ce monde : *la station montre ce qu'elle a enregistré
avant qu'on le demande*. Le bandeau porte, sur les cinq surfaces, la bande des
runs récents et les deux chiffres du verdict — ce qui tient, et ce que ça a
coûté.

Mode : **Operate**. La scannabilité et la densité priment sur l'expression ; la
marque vit dans la précision des détails.

### Identité

Le nom **PATRICK** est une contrainte intouchable, quelle que soit l'identité
visuelle. Il s'écrit en chasse fixe (`.station-name`), à gauche du bandeau.

**La marque** (`.station-mark`) le précède : un anneau qui enferme trois barres
montantes, la dernière coiffée d'un point d'accent. C'est un relevé, pas un
emblème — la même lecture que la bande d'enregistrement posée juste dessous :
des événements ponctuels, de hauteur inégale, le plus récent à droite.

Elle est **redessinée** d'après le logo fourni par l'utilisateur (marque
circulaire, anneau et glyphe), pas importée. Ce qui a été gardé : la forme
circulaire et le glyphe enfermé. Ce qui a été laissé : l'or, le sérif et le
lettrage en petites capitales, qui appartiennent au monde précédent. Une
version antérieure de ce document interdisait tout logo ; cette consigne a été
levée.

Trois règles la tiennent :

- **Un seul lien** porte la marque et le nom. Deux liens voisins vers la même
  destination seraient deux arrêts de tabulation pour un seul geste ; le SVG
  est `aria-hidden`, le nom qu'il accompagne étant déjà le nom accessible.
- **Aucune couleur codée en dur.** L'anneau et les barres prennent
  `currentColor`, donc `--ink-text` ; la tête reçoit `--accent-ink` par CSS.
  Une couleur écrite dans le SVG survivrait à un remplacement d'identité et
  repeindrait l'ancien monde.
- **Taille en `em`.** À 200 % de zoom texte, une marque en pixels devient une
  vignette accrochée à un mot.

Le favicon porte la **même géométrie** — seule l'échelle change. Deux dessins
différents pour un même produit se contrediraient.

## Colors

### Deux matières, pas un dégradé de gris

Règle structurante du monde, à comprendre avant de toucher une couleur.

- **Le boîtier** (`--ink`, `--ink-2`) porte le bandeau, la bande
  d'enregistrement, le verdict, le contexte de reproductibilité, le journal de
  run, et **toutes les plaques de tracé**.
- **Le papier** (`--ground` plan de travail, `--surface` feuille posée dessus,
  `--raise` creux d'un champ) porte la lecture.

**Quatre jetons « sur boîtier » sont identiques dans les deux thèmes** :
`--accent-ink`, `--ok-ink`, `--warn-ink`, `--error-ink`. Ce sont eux les
invariants, parce qu'ils tiennent sur les deux valeurs d'encre — mesuré :
7,83:1 et 8,38:1 pour l'accent, 7,70:1 et 8,24:1 pour l'erreur. C'est ce qui
permet à `market.js` et `simulate.js` de tracer sans savoir dans quel thème.

**`--ink` lui-même descend en thème sombre** (`#0B1220` → `#05080F`), et ce
n'est pas une entorse : sans ça, la plaque deviendrait plus claire que la page
qu'elle troue. La plaque est toujours la matière la plus profonde de la scène
— c'est la règle, pas sa valeur.

Conséquence mesurée et assumée : en clair la plaque se détache par la
luminance (18,72:1 contre `--surface`), en sombre elle ne le peut plus
(1,15:1). Elle se détache donc par un **bord explicite**, `--plate-edge`.
Aucun écart de luminance atteignable ne le remplacerait : poussé jusqu'à la
limite du contraste de texte, l'écart entre deux fonds sombres plafonne à
1,30:1.

**`--on-accent`** porte le texte posé sur l'accent plein. Le blanc tient sur
l'accent clair (6,65:1) mais pas sur l'accent sombre éclairci (2,56:1).

### Stratégie : Restrained

Neutres + un accent unique. **L'accent ne dit qu'une chose : « ceci est
interactif ou actif ».** Il ne porte jamais une donnée, jamais un jugement.
Les jugements ont leurs propres jetons (`--ok`, `--warn`, `--error`,
`--pending`) et ceux-là ne servent qu'à ça.

Il n'existe **pas** de jeton « info ». Un état sans jugement s'écrit dans la
couleur du texte.

`--pending` porte aussi l'attente de confirmation (barre de lancement armée) :
armer n'est pas avertir.

### Deux rendus, écrits séparément

`:root` est clair, `:root[data-theme="dark"]` est sombre. Le second n'est
**pas** une inversion : fonds bleutés-froids, accents remontés en clarté,
ombres devenues profondeur + liseré haut. Le choix est explicite, mémorisé, et
posé **avant le premier rendu** par un script bloquant dans le `<head>`.

### Contraste

Tout texte tient 4,5:1 sur **son fond réel**, fond composité des pastilles
teintées inclus ; tout texte large tient 3:1. Les valeurs mesurées sont en
commentaire dans `tokens.css`, ligne par ligne — ne pas modifier une couleur
sans refaire le calcul sur les deux thèmes.

## Typography

Deux familles, servies depuis `/static/fonts/` — **aucune requête CDN**.

- **Archivo** (`--display`, aliasée `--ui`) : chrome, titres, libellés,
  boutons, en-têtes de colonne, pastilles d'état.
- **Spline Sans Mono** (`--mono`) : **toute donnée**, plus le nom du produit.

**Le contraste des deux familles porte la hiérarchie**, pas la taille seule.

Règle mécanique : `table, .num, .mono, code, pre, .metric-value, input,
select, textarea` reçoivent `--mono` + `tabular-nums` + `"tnum" 1, "zero" 1`.
Non négociable — c'est ce qui permet l'alignement décimal.

Six pas (`--t-micro` 12px → `--t-head` 28px). Tout titre porte
`overflow-wrap: break-word` : mesuré à 200 % de zoom texte en 390px, le mot
« d'investissement » fait 438px pour 358 disponibles et poussait la page.

## Layout

### La grille du poste

Asymétrique et délibérée : `1.3fr / 1fr`. La colonne gauche porte la tâche
principale, la droite ce qui la sert. Une grille de panneaux égaux donnait le
même poids à un formulaire de 65 contrôles et à un widget de variations.

**Aucun panneau ne défile en interne.** Mesuré sur la version qui le faisait :
613px visibles pour 3042px de contenu, deux barres de défilement concurrentes,
`Ctrl+F` inopérant hors flux, bouton de lancement absent de tout viewport. Le
seul défilement d'une page est celui de la page.

### Divulgation progressive

Deux blocs de formulaire restent ouverts — le nom du run et l'objectif, les
seuls réglés à chaque lancement. Les neuf autres se replient en `<details>`
portant leur état en résumé. Gain mesuré : le chemin clavier vers l'action
principale est passé d'environ 105 arrêts à 24, les blocs repliés retirant
leur contenu de l'ordre de tabulation.

### Barre de lancement collante

En bas de la colonne de configuration, avec le rappel cible / horizons /
schéma. `html` réserve `scroll-padding-bottom` égal à `--launch-bar-h`,
publiée par un `ResizeObserver` : sans cette réserve, un champ derrière la
barre est « dans le viewport » pour le navigateur, qui ne défile donc pas
quand on l'atteint au clavier. Mesurer la boîte de **bordure**, pas
`contentRect` — celui-ci exclut le remplissage et rendait 35px pour une barre
de 68.

### Adaptation : le pointeur, pas la largeur

Les cibles tactiles s'adaptent sur `pointer: coarse`, jamais sur une largeur
de viewport. Une tablette de 1024px se touche ; une fenêtre réduite à 390px se
pilote à la souris. Vérifié : `/universe` fait la même hauteur à la souris
avant et après.

**Deux seuils, pas un.** 44px pour un **contrôle** (WCAG 2.5.5). 24px pour un
lien de texte **dans une table dense** (WCAG 2.5.8) : imposer 44px à 550
lignes ajouterait plus de 24 000px de défilement pour un gain que la norme
n'exige pas.

Une petite marque n'impose pas une petite cible : l'appel de glossaire garde
son gabarit de 15px et porte une zone de contact de 44px par pseudo-élément.

Zones sûres : `viewport-fit=cover` et `env(safe-area-inset-*)` sur le bandeau
et la barre de lancement.

Ruptures : 1100px (le simulateur passe en colonne), 980px (la grille du poste
passe en colonne, le bandeau s'enroule). Zéro débordement horizontal sur les
20 contextes mesurés, et zéro à 200 % de zoom texte.

## Elevation & Depth

**Un panneau est un objet posé**, pas une zone délimitée par un trait :
`--surface`, `1px solid var(--rule)`, `--r-panel`, et `--shadow-panel` — une
ombre avec **décalage vertical ET flou**. Un halo coloré à décalage nul est de
la décoration, pas de la profondeur.

Le filet ne structure plus la page : il sépare deux lignes **dans** un panneau
(`--rule`) ou cerne un objet manipulable (`--rule-strong`).

`--plate-edge` est le seul indice de matière qui survive au thème sombre : un
liseré interne posé sur la bande d'enregistrement, l'aperçu marché, les trois
toiles du simulateur et le journal de run.

**Jamais de panneau dans un panneau** : il ne dit rien de plus que le filet
qu'il remplace et brouille la hiérarchie.

### Mouvement

**Un seul moment authoré** : la bande se révèle de gauche à droite en 620ms
(sortie cubique) au chargement — le mouvement natif d'un enregistreur. Le
reste est fonctionnel : la jauge balaie **uniquement** pendant les phases non
mesurables, le leaderboard glisse au tri (FLIP), le panneau de résultats
apparaît. `prefers-reduced-motion` retire le mouvement, **jamais**
l'information : la jauge non mesurable devient un motif rayé statique.

## Shapes

`--r-small` 6px (plaque de tracé, micro-contrôle du bandeau, pastille d'état
de brique), `--r-control` 8px (champ, bouton, état vide), `--r-panel` 12px
(panneau), `--r-chip` 999px (pastille d'état, bouton de plage). Le monde
précédent les mettait à zéro par doctrine ; c'est le premier signe extérieur
qui faisait lire l'outil comme inachevé.

### Focus — un seul régime, sans exception

```css
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--r-small);
}
```

Le formulaire a porté pendant une passe sa propre règle — `outline: none`
compensé par un anneau à 10 % d'opacité, mesuré à 1,15:1 contre le blanc,
c'est-à-dire rien. L'incohérence est pire que l'absence. **Toute règle qui
repose `outline: none` sur un élément focusable est un défaut.**

## Components

Composants Jinja partagés dans `templates/_components.html`, CSS dans
`static/style.css`, jetons dans `static/tokens.css`.

**`metric(label, value, reliability, state)`** — le composant signature. Le
troisième argument est **obligatoire**. Valeur en `--t-value` (24px) en chasse
fixe ; ligne de fiabilité décrochée par un filet vertical de 1px. **C'est la
seule verticale du système**, et elle dit « ceci appartient au chiffre
au-dessus ».

**`data_table(headers, rows, empty_message, row_classes, num_cols, footer)`** —
`num_cols` porte les indices des colonnes de **mesure** ; elles seules
reçoivent la classe `num`. L'appelant déclare, le gabarit ne devine pas.
En-tête collant sur fond `--raise`.

**`status_badge(label, state)`** — pastille avec point de 6px en
`currentColor`. Six états. **Le texte porte l'état, la couleur ne fait que le
doubler.** Un run échoué prend `error`, jamais `neutral`.

**`empty_state` / `error_state`** — encadré pointillé sur `--raise`, message
préfixé de `NA`.

**Le verdict de la station** (`.verdict`, rendu côté serveur dans le bandeau)
— deux chiffres sur les cinq surfaces : *ce qui tient* (cibles survivant à la
correction Benjamini-Hochberg entre cibles) et *ce que ça a coûté* (essais
cumulés). Registre du **boîtier**, pas de la valeur : chasse fixe au corps de
la ligne de provenance, contrepartie en ligne. Deux grands chiffres ici
feraient une barre de KPI. `survivors = None` tant qu'aucune cible n'a de
résultat DM : on imprime `—` et le motif.

**Les lignes de portée locale** (`.scope-line`, en tête de `/universe` et
`/runs`) — même grammaire, posée sur le papier. Elles ne répètent **jamais**
le verdict global : chacune répond à la question de sa surface.

**La bande d'enregistrement** (`.record`, `observatory.js`) — une colonne par
run, la plus récente à droite. **La coordonnée est la séquence, pas le temps
écoulé** : un axe de temps absolu dépensait toute la largeur en durée plutôt
qu'en runs (mesuré : 18 runs sur 90 secondes étalés sur 6 jours, deux amas
dans 3 % de la surface). Hauteur = essais (log), couleur = état, plafond de 40
colonnes. C'est un **contrôle** : `tabindex=0`, flèches, Home/End, Entrée pour
ouvrir, Échap pour lâcher.

Trois refus inscrits dans le code, qui ne sont pas des oublis : pas de courbe
entre les marques (les runs sont des événements ponctuels) ; pas de hauteur
inventée sans compte d'essais ; la légende porte **toujours** le plafond de
l'échelle et l'étendue temporelle, qui a quitté le tracé pour elle.

**Les briques de rigueur dans les blocs repliés** (`.adv-gate`) — six
garanties (`data_quality_enabled`, `purge`, `embargo_enabled`,
`uniqueness_weights`, `calibration`, `stacking`) dont l'état est **toujours
rendu, ON comme OFF**, et OFF se colore. Une case ordinaire ne se résume que
si elle est cochée — c'est un réglage ; une brique se résume toujours — c'est
une garantie, et son absence est l'information qui compte. La même ligne est
reprise par le récapitulatif de lancement.

**La barre de lancement à deux temps** — le premier clic arme et déplie ce qui
va tourner (cible, horizons, régimes, schéma, combinaisons **calculées**, rang
en file, état des briques) ; le second lance. Pas de fenêtre modale : l'action
n'a pas besoin d'interrompre, seulement d'être relue. Échap ou toute
modification désarme. Le teinté d'armement est **composé sur** la surface,
jamais posé à sa place — une barre collante translucide laisse voir le
formulaire au travers.

**Le glossaire** — `role="dialog"`, prend le focus à l'ouverture, Échap le
rend au déclencheur, tabuler hors de lui le referme. Le focus est posé à la
frame suivante : le popover sort de `display: none` par une transition
`allow-discrete` et un `focus()` synchrone est ignoré. Nom accessible =
« Définition : <libellé humain> », via `TERM_LABEL_KEYS` — le glossaire ne peut
pas être le seul endroit qui laisse ses clés brutes.

**Toiles (canvas)** — une toile ne peut pas hériter d'une couleur CSS : elle
doit la **lire**, sans repli codé en dur (un repli survit à un remplacement
d'identité et repeint l'ancien monde). Toutes portent `role="img"` et un
`aria-label` **réécrit à partir des vraies séries** après tracé.

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
- Vérifier le contraste sur le fond **composité réel**, dans les deux thèmes.

**À ne pas faire**

- Afficher un chiffre nu, sans dénominateur ni réserve.
- Afficher une valeur ponctuelle à côté d'un message disant qu'elle n'a pas
  été calculée.
- Résumer un bloc replié en ne listant que ce qui est activé : une garantie
  désactivée devient alors un défaut silencieux.
- Utiliser l'accent pour porter une donnée ou un jugement.
- Introduire un sixième neutre bleuté « informatif ».
- Imbriquer un panneau dans un panneau.
- Dériver le thème sombre par inversion du clair.
- Redéfinir `--accent-ink`, `--ok-ink`, `--warn-ink` ou `--error-ink` dans le
  bloc sombre : ces quatre-là sont les invariants.
- Poser du blanc codé en dur sur un fond d'accent — c'est `--on-accent`.
- Reposer `outline: none` sur un élément focusable.
- Remplacer le fond d'un élément collant par une couleur translucide.
- Afficher « 0 % » pendant une phase qui ne produit aucune mesure.
- Poser un `cursor: pointer` sur un élément que rien n'active.

## Écarts connus entre le contrat et le code

Documentés parce qu'ils sont réels, pas corrigés ici :

- **`metric()` n'apparaît nulle part sur `/`**, et la page n'affiche aucun
  chiffre en typographie de valeur : mesuré, un seul objet au-dessus de 17px
  (le `h1`). Décision explicite de l'utilisateur — le verdict vit dans le
  bandeau, qui est le boîtier et non le papier. La critique le remonte, et
  c'est assumé.
- **La bande ne porte pas la durée d'un run**, seulement son rang et son
  effort. `finished_at` existe en base et n'est pas exploité.
- **`sparkline()`** est déclarée dans `_components.html` et jamais appelée.
- **Aucune capture ne montre une toile de marché avec données** : le réseau
  yfinance est coupé dans l'environnement de construction.
- **Aucun lien d'évitement** : la première tabulation atterrit sur la marque et
  le nom du produit, pas sur un « aller au contenu ».
- **La marque est une interprétation du logo fourni**, redessinée de mémoire et
  non tracée sur le fichier d'origine (aucun fichier n'a été transmis, seulement
  une image). Les proportions de l'anneau et le nombre de barres sont des choix,
  pas une reprise — à valider ou corriger par l'utilisateur.
