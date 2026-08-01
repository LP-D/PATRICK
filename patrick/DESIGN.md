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
  record-plate:
    backgroundColor: "{colors.ink-2}"
    rounded: "6px"
    height: "72px"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#FFFFFF"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "9px 20px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
    textColor: "#FFFFFF"
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
l'identité et l'enregistrement, des feuilles de papier posées dessus qui
portent la lecture.

Il remplace **intégralement** le monde précédent, « Sortie de solveur » (noir
plat à trois fonds quasi identiques, structure par filets horizontaux seuls,
chasse fixe partout y compris le chrome, rayons à zéro, états écrits
`[DONE]`). Aucune valeur n'a été conservée. Si vous trouvez `--r-none`,
`JetBrains Mono`, un `border-radius: 0` posé par doctrine ou un badge à
crochets, c'est un résidu à supprimer, pas une variante à respecter. Le monde
d'avant remplaçait lui-même une charte sombre/or à sérif Cormorant ; ces deux
généalogies sont mortes.

**La thèse tient en deux propositions.** La première est conservée du monde
précédent parce qu'elle appartient au produit, pas à son habillage : *un
chiffre ne s'écrit jamais seul*. La signature de `metric()`
(`_components.html:14`) force un troisième argument `reliability` — le gabarit
ne devine jamais l'incertitude, l'appelant doit l'écrire, même pour dire « non
calculable ». Les tables portent un pied qui énonce les réserves pesant sur
leurs colonnes. Et quand une mesure n'est pas interprétable, le produit
**refuse de l'imprimer** : il affiche `—`, le motif en clair, et renvoie la
justification longue en note `†` sous le bloc.

La seconde est propre à ce monde : *la station enregistre même quand personne
ne regarde*. La bande d'enregistrement du bandeau (`observatory.js`) trace
l'activité des runs dans le temps, sur toutes les pages, avant qu'on lui
demande quoi que ce soit — et une bande vide sur quatre jours est une
information, pas un défaut d'affichage, ce que ses étiquettes de temps et son
repère « maintenant » rendent lisible.

Mode : **Operate**. Le visiteur accomplit une tâche — configurer un run, suivre
son avancement, lire un verdict, simuler un rendement. La scannabilité et la
densité priment sur l'expression ; la marque vit dans la précision des détails,
et il n'y a **ni logo ni monogramme** : le produit s'identifie par son nom en
chasse fixe (`.station-id`), c'est un choix et non un manque à combler.

## Colors

### Deux matières, pas un dégradé de gris

C'est la règle structurante du monde, et la première chose à comprendre avant
de toucher une couleur.

- **Le boîtier** (`--ink`, `--ink-2`) porte le bandeau, la bande
  d'enregistrement, le contexte de reproductibilité, le journal de run, et
  **toutes les plaques de tracé** (`#preview-canvas`, `#sim-equity-canvas`,
  `#sim-drawdown-canvas`, `#sim-dist-canvas`).
- **Le papier** (`--ground` pour le plan de travail, `--surface` pour la
  feuille posée dessus, `--raise` pour le creux d'un champ) porte la lecture.

**Les jetons « sur boîtier » sont identiques dans les deux thèmes** :
`--ink`, `--ink-2`, `--ink-text`, `--ink-text-2`, `--accent-ink`, `--ok-ink`,
`--warn-ink`, `--error-ink`. Une plaque d'instrument ne change pas de matière
quand la pièce s'éclaire, et c'est ce qui permet à `market.js` et
`simulate.js` de tracer sans jamais savoir dans quel thème ils sont.

### Stratégie : Restrained

Neutres + un accent unique. **L'accent ne dit qu'une chose : « ceci est
interactif ou actif ».** Il ne porte jamais une donnée, jamais un jugement.
C'est ce qui permet de lire une page sans se demander si le bleu veut dire
« bon ». Les jugements ont leurs propres jetons (`--ok`, `--warn`, `--error`,
`--pending`) et ceux-là ne servent qu'à ça.

Il n'existe **pas** de jeton « info ». Un état sans jugement n'a pas de
couleur : il s'écrit dans la couleur du texte (`.status-badge.status-neutral`
prend `--text-2` sur `--raise`).

### Deux rendus, écrits séparément

`:root` est clair, `:root[data-theme="dark"]` est sombre. Le second n'est
**pas** une inversion du premier : ses fonds sont bleutés-froids, ses accents
sont remontés en clarté pour tenir 4,5:1 sur fond sombre, et ses ombres
deviennent profondeur + liseré haut (une ombre noire seule est invisible sur
fond noir). La scène le justifie : Patrick sert autant en journée qu'en
soirée, donc aucun des deux n'est le repli de l'autre.

Le choix est explicite (`#theme-toggle`), mémorisé dans `localStorage`, et
posé **avant le premier rendu** par un script bloquant dans le `<head>` —
sinon la page peint en clair puis bascule, ce qui est pire que de n'avoir
aucun mode sombre. Sans choix exprimé, `prefers-color-scheme` tranche, et
continue à trancher si le système change en cours de session.

### Contraste

Tout texte tient 4,5:1 sur **son fond réel**, fond composité des pastilles
teintées inclus ; tout texte large tient 3:1. Vérifié avant construction. Les
valeurs mesurées sont en commentaire dans `tokens.css`, ligne par ligne — ne
pas modifier une couleur sans refaire le calcul sur les deux thèmes.

## Typography

Deux familles, téléchargées et servies depuis `/static/fonts/` — **aucune
requête CDN** : un outil local doit s'afficher correctement hors ligne.

- **Archivo** (`--display`, aliasée `--ui`) : chrome, titres, libellés,
  boutons, en-têtes de colonne, pastilles d'état. Grotesque de large chasse
  dessinée pour la signalétique et l'étiquette d'appareil ; elle tient en
  capitales serrées comme en titre de 28px.
- **Spline Sans Mono** (`--mono`) : **toute donnée**. Chasse fixe
  contemporaine, chiffres tabulaires, formes ouvertes — elle aligne les
  décimales sans le costume de terminal des monos de code.

**Le contraste des deux familles porte la hiérarchie**, pas la taille seule.
C'est la différence la plus visible avec le monde précédent, où tout était en
chasse fixe et où la hiérarchie reposait uniquement sur la taille et la casse.

Règle mécanique : `table, .num, .mono, code, pre, .metric-value, input,
select, textarea` reçoivent `--mono` + `tabular-nums` + `"tnum" 1, "zero" 1`.
C'est non négociable — c'est ce qui permet l'alignement décimal d'une colonne
à l'autre.

Six pas (`--t-micro` 12px → `--t-head` 28px). Le monde précédent plafonnait le
corps à 13px et le titre de page à 22px : dense, mais illisible comme produit.

## Depth, radius, motion

**Un panneau est un objet posé**, pas une zone délimitée par un trait :
`--surface`, `1px solid var(--rule)`, `--r-panel` (12px), et `--shadow-panel`
— une ombre avec **décalage vertical ET flou**. Un halo coloré à décalage nul
est de la décoration, pas de la profondeur.

Le filet ne sert plus à structurer la page : il sépare deux lignes **dans** un
panneau (`--rule`) ou cerne un objet manipulable (`--rule-strong`).

Rayons : `--r-small` 6px (plaque de tracé, micro-contrôle du bandeau),
`--r-control` 8px (champ, bouton, état vide), `--r-panel` 12px (panneau),
`--r-chip` 999px (pastille d'état, bouton de plage). Le monde
précédent les mettait à zéro par doctrine ; c'est le premier signe extérieur
qui faisait lire l'outil comme inachevé.

**Un seul moment de mouvement authoré** : la bande d'enregistrement se révèle
de gauche à droite en 620ms (sortie cubique) au chargement — le mouvement
natif d'un enregistreur. Tout le reste est fonctionnel : la jauge de
progression balaie **uniquement** pendant les phases non mesurables (le worker
n'incrémente `progress_done` que sur les lignes de fold), le leaderboard fait
glisser ses lignes au tri (FLIP), le panneau de résultats apparaît.
`prefers-reduced-motion` retire le mouvement, **jamais** l'information : la
jauge non mesurable devient un motif rayé statique.

## Components

Composants Jinja partagés dans `templates/_components.html`, CSS dans
`static/style.css`, jetons dans `static/tokens.css`.

**`metric(label, value, reliability, state)`** — le composant signature. Le
troisième argument est **obligatoire** : c'est la mise en œuvre mécanique de
la première thèse. La valeur est en `--t-value` (24px) en chasse fixe ; la
ligne de fiabilité est décrochée sous elle par un filet vertical de 1px
(`border-left: 1px solid var(--rule-strong)`). **C'est la seule verticale du
système**, et elle dit « ceci appartient au chiffre au-dessus » — elle ne
décore pas.

**`data_table(headers, rows, empty_message, row_classes, num_cols, footer)`** —
`num_cols` porte les indices (base 0) des colonnes de **mesure** ; elles seules
reçoivent la classe `num` qui déclenche l'alignement à droite. L'appelant
déclare, le gabarit ne devine pas : une cellule peut contenir une pastille, un
intervalle ou un NA, et aucun de ces cas ne se détecte de façon fiable. Le
conteneur `.table-scroll` porte le cadre et le rayon ; l'en-tête est
**collant** (`position: sticky`) sur fond `--raise`. Le sélecteur couvre
`table.data-table` **et** `table.leaderboard`.

**`status_badge(label, state)`** — pastille : `inline-flex`, rayon `--r-chip`,
fond teinté `-weak`, précédée d'un point de 6px en `currentColor`. Six états :
`ok`, `warning`, `error`, `neutral`, `pending`, `disabled`. **Le texte porte
l'état, la couleur ne fait que le doubler** — lisible en monochrome, lisible
pour un daltonien. Un run **échoué** prend `error`, jamais `neutral`.

**`empty_state` / `error_state`** — encadré pointillé sur `--raise`. Le
message d'état vide est préfixé de `NA` en gris : le vide s'écrit comme une
station l'écrit, un jeton et une phrase, pas une illustration.

**La bande d'enregistrement** (`.record`, `observatory.js`) — signature du
monde, présente sur toutes les pages via `base.html`. Une marque = un run,
posée à son heure de départ ; **hauteur = nombre d'essais** (échelle
logarithmique) ; **couleur = état**. Trois refus inscrits dans le code, qui ne
sont pas des oublis :

1. elle ne relie pas les marques par une courbe — les runs sont des événements
   ponctuels, les relier inventerait une continuité que les données n'ont pas ;
2. elle n'invente pas de hauteur pour un run sans compte d'essais — la marque
   tombe à la hauteur plancher et le run est compté séparément dans la légende ;
3. sa légende porte **toujours** le plafond de l'échelle et l'étendue
   temporelle — une hauteur sans son maximum n'est pas une mesure.

Elle distingue aussi « pas encore de run » (`runs: []`) de « base illisible »
(`available: false`) : `/api/activity` échoue en silence côté serveur, mais le
front l'écrit en clair — une station muette et une station en panne ne se
ressemblent pas.

**Le refus de calculer.** Ce n'est pas un composant, c'est une doctrine, et
c'est ce qui distingue ce produit d'un tableau de bord. Quand
`pbo_reliability` refuse (moins de 6 blocs), la page n'affiche **pas** la
valeur ponctuelle à côté d'un message disant qu'elle n'a pas été calculée —
elle affiche `—`, la première phrase du motif, un appel de note `†`, et renvoie
les ~500 caractères de justification sous le bloc en `.block-note`. Rien n'est
masqué ; tout est déplacé là où ça se lit.

**Valeur absente.** Le tiret cadratin dans `<span class="na">`, en `--text-3`,
**jamais dans la couleur d'une mesure** : trois absences sur une même ligne
doivent avoir la même couleur.

**Toiles (canvas).** Une toile ne peut pas hériter d'une couleur CSS : elle
doit la **lire**. `observatory.js`, `market.js` et `simulate.js` exposent
chacun un helper `token(name)` **sans valeur de repli codée en dur**. C'est
délibéré : un repli survit à un remplacement d'identité et repeint
silencieusement l'ancien monde. Elles lisent les jetons « sur boîtier », et
`observatory.js` les redessine sur l'événement `patrick:theme`.

## Do's and Don'ts

**À faire**

- Écrire la contrepartie de fiabilité de chaque chiffre — n, intervalle, ou le
  motif de sa non-calculabilité.
- Refuser d'imprimer une mesure non interprétable, et dire pourquoi en clair.
- Déclarer `num_cols` sur toute table portant des mesures.
- Fermer chaque liste par un pied portant compte et réserves.
- Poser toute toile sur le boîtier (`--ink`) et lire ses couleurs dans les
  jetons « sur boîtier », sans repli.
- Donner à toute surface au repos son état vide écrit — une plaque de tracé
  vide de 400px est un trou, pas un état.
- Vérifier le contraste sur le fond **composité réel**, dans les deux thèmes,
  avant de construire.

**À ne pas faire**

- Afficher un chiffre nu, sans son dénominateur ni sa réserve.
- Afficher une valeur ponctuelle à côté d'un message disant qu'elle n'a pas
  été calculée.
- Utiliser l'accent pour porter une donnée ou un jugement.
- Introduire un sixième neutre bleuté « informatif ».
- Imbriquer un panneau dans un panneau : il ne dit rien de plus que le filet
  qu'il remplace et brouille la hiérarchie du plan de travail.
- Dériver le thème sombre par inversion du clair.
- Redéfinir un jeton « sur boîtier » dans le bloc `[data-theme="dark"]`.
- Afficher « 0 % » pendant une phase qui ne produit aucune mesure.
- Poser un `cursor: pointer` ou un survol d'accent sur un élément que rien
  n'active.
- Réintroduire un logo, un monogramme ou un placeholder de logo.

## Écarts connus entre le contrat et le code

Documentés parce qu'ils sont réels, pas corrigés ici :

- **La bande d'enregistrement ne porte que l'heure de DÉPART d'un run**, pas sa
  durée. Une station enregistre la durée d'un événement ; ici un run de 10
  minutes et un run de 9 heures produisent la même marque. `finished_at` existe
  en base et n'est pas encore exploité.
- **`sparkline()`** est déclarée dans `_components.html` mais n'est importée ni
  appelée nulle part — code mort.
- **Aucune capture ne montre une toile de marché avec données** : le réseau
  yfinance étant coupé dans l'environnement de construction, la grille de
  plaque ajoutée à `market.js` est vérifiée en lecture de code, pas au rendu.
- **`/simulate` au repos** ne rend aucune plaque : toiles et tables sont
  masquées tant que `body[data-sim-loaded]` est absent, et chaque panneau porte
  sa phrase d'attente. C'est un état écrit, mais la surface reste la moins
  dense du produit.
