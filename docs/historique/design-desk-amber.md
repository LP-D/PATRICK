# Système visuel « Desk Amber » (remplacé)

Le monde visuel « Desk Amber » (août 2026) a été remplacé fin septembre 2026 par la refonte « Cockpit Pro » : la source de référence actuelle est `design-system/patrick/MASTER.md`. Ces deux documents (spécification puis rapport d'extraction) sont conservés pour l'historique.


---

## Partie 1 — Spécification de design (Desk Amber)

*Source d'origine : `patrick/DESIGN.md`.*

---
name: PATRICK
description: Desk Amber — un instrument de mesure professionnel, dense et sombre, pas un tableau de bord SaaS générique.
colors:
  ink: "#060403"
  ink-2: "#0D0805"
  ink-text: "#F0EAE5"
  ink-text-2: "#A69C95"
  ground: "#130D09"
  surface: "#1D1610"
  raise: "#1C140F"
  rule: "rgba(140, 111, 77, 0.4)"
  rule-strong: "rgba(148, 118, 82, 0.55)"
  text: "#F0EAE5"
  text-2: "#A69C95"
  text-3: "#8D847D"
  accent: "#D6B529"
  accent-hover: "#E6C540"
  on-accent: "#060403"
  accent-ink: "#D6B529"
  ok: "#69BC61"
  warn: "#F0971A"
  error: "#FF645F"
  pending: "#9A9DB1"
  ok-ink: "#69BC61"
  warn-ink: "#F0971A"
  error-ink: "#FF645F"
typography:
  head:
    fontFamily: "Space Grotesk, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  value:
    fontFamily: "JetBrains Mono, ui-monospace, Menlo, SF Mono, Consolas, Liberation Mono, monospace"
    fontSize: "1.5rem"
    fontWeight: 500
    lineHeight: 1.15
    letterSpacing: "-0.02em"
  lead:
    fontFamily: "Space Grotesk, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "JetBrains Mono, ui-monospace, Menlo, SF Mono, Consolas, Liberation Mono, monospace"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  small:
    fontFamily: "Space Grotesk, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 600
    lineHeight: 1.55
    letterSpacing: "normal"
  micro:
    fontFamily: "Space Grotesk, system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 600
    lineHeight: 1.5
    letterSpacing: "0.12em"
rounded:
  small: "2px"
  control: "3px"
  panel: "3px"
  chip: "2px"
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

## DESIGN.md — PATRICK

Généré depuis le code construit (`patrick/webapp/`), pas depuis une intention.
Le contrat de direction dont ce document est la mise à plat est en commentaire
HTML en tête de `templates/base.html` (blocs THESIS / OWN-WORLD / STORY /
FIRST VIEWPORT / FORM). Les jetons normatifs vivent dans `static/tokens.css` ;
ce fichier explique **comment les appliquer**, il ne les remplace pas. Le
rapport d'extraction complet (valeurs OKLCH exactes, calculs de contraste) est
`DESK_AMBER_R1-R5.md` à la racine du dépôt.

### Overview

Le monde s'appelle **« Desk Amber »**. Extrait de la section `id="1c"`
(direction « développée ») de `PATRICK__Directions_visuelles_export.html` et
réassigné sur la structure sémantique déjà en place — les composants Jinja
n'ont pas été réécrits, seule la feuille de jetons change (à une exception
près : les 6 règles `.status-badge.status-*`, voir « Components »).

Il remplace **intégralement** le monde précédent, **« Nocturne »** (encre
violette sur charbon indigo, Inter seule, anneau fin + diffus croissant). Si
vous trouvez `#9184D9`, un `border-radius: 999px` sur une pastille d'état, ou
`Inter` chargée seule, c'est un résidu Nocturne à migrer, pas une variante à
respecter — de même pour tout résidu antérieur (`--shadow-panel`,
`--shadow-raised`, `--shadow-overlay`, `Archivo`, `Spline Sans Mono`) du monde
« Station d'observation » que Nocturne avait déjà remplacé.

**La thèse produit ne change pas** — elle appartient au produit, pas à son
habillage : *un chiffre ne s'écrit jamais seul*. La signature de `metric()`
force toujours un troisième argument `reliability` ; le verdict de la station
imprime toujours un tiret et son motif tant qu'aucune cible n'a de résultat
Diebold-Mariano, jamais « 0 / 0 » qui se lirait comme un échec. *La station
montre ce qu'elle a enregistré avant qu'on le demande* — le bandeau porte
toujours, sur les cinq surfaces, la bande des runs récents et les deux
chiffres du verdict.

Mode : **Operate**. La scannabilité et la densité priment sur l'expression ;
Desk Amber les sert par un fond charbon dense et un accent ambre unique, pas
par l'ornement — plus assertif que Nocturne (ombres plus marquées, accent
plus chaud et plus saturé), mais la même discipline : l'accent ne porte
jamais un jugement.

**Mode sombre seul pour cette passe.** `:root` porte directement les valeurs
Desk Amber (actives par défaut, pas une bascule) ; `[data-theme="light"]` est
un bloc vide, préparé mais pas écrit — voir « Écarts connus » et
`KNOWN_ISSUES.md`. Le bouton de bascule jour/nuit reste masqué tant que ce
bloc est vide.

#### Identité

Le nom **PATRICK** est une contrainte intouchable, quelle que soit l'identité
visuelle. Il s'écrit en chasse fixe (`.station-name`), à gauche du bandeau.

**La marque** (`.station-mark`) le précède : un anneau qui enferme trois barres
montantes, la dernière coiffée d'un point d'accent. C'est un relevé, pas un
emblème — la même lecture que la bande d'enregistrement posée juste dessous :
des événements ponctuels, de hauteur inégale, le plus récent à droite. Le
dessin lui-même n'a pas changé avec Desk Amber, seules ses couleurs
(`currentColor` → `--ink-text`, tête → `--accent-ink`, désormais ambre) suivent
la nouvelle palette.

Trois règles la tiennent :

- **Un seul lien** porte la marque et le nom. Deux liens voisins vers la même
  destination seraient deux arrêts de tabulation pour un seul geste ; le SVG
  est `aria-hidden`, le nom qu'il accompagne étant déjà le nom accessible.
- **Aucune couleur codée en dur.** L'anneau et les barres prennent
  `currentColor`, donc `--ink-text` ; la tête reçoit `--accent-ink` par CSS.
  Une couleur écrite dans le SVG survivrait à un remplacement d'identité et
  repeindrait l'ancien monde — c'est exactement ce que ce remplacement de
  jetons vient de vérifier en pratique, pour la deuxième fois.
- **Taille en `em`.** À 200 % de zoom texte, une marque en pixels devient une
  vignette accrochée à un mot.

Le favicon porte la **même géométrie** — seule l'échelle change. Deux dessins
différents pour un même produit se contrediraient.

### Colors

#### Deux matières, pas un dégradé de gris

Règle structurante du monde, conservée depuis « Station d'observation » puis
Nocturne — à comprendre avant de toucher une couleur.

- **Le boîtier** (`--ink`, `--ink-2`) porte le bandeau, la bande
  d'enregistrement, le verdict, le contexte de reproductibilité, le journal de
  run, et **toutes les plaques de tracé**.
- **Le papier** (`--ground` plan de travail, `--surface` feuille posée dessus,
  `--raise` creux d'un champ) porte la lecture.

Desk Amber, source de cette passe, ne montre que le panneau boîté (deux
paliers, `--ground`/`--surface`) — pas le fond de page derrière. `--ink` reste
dérivé, plus sombre que `--ground`, même famille de teinte (ambre neutre, hue
OKLCH 60, au lieu de l'indigo Nocturne) : mesuré, `--ink` (L=0,11) plus sombre
que `--ground` (L=0,165) par construction.

**Les jetons « sur boîtier »** (`--accent-ink`, `--ok-ink`, `--warn-ink`,
`--error-ink`) restent la structure d'invariants du monde précédent, prête
pour un futur mode clair — tous de simples alias de leur jeton non-ink
respectif (aucune variante « ink » distincte n'apparaît dans la source Desk
Amber, la distinction n'a de sens que quand deux thèmes existent).

**`--on-accent`** porte le texte posé sur l'accent plein. Mesuré : `--ink`
tient 9,97:1 sur `--accent` (#D6B529) — la source utilise déjà ce même
`--ink` sur ses badges ON et son bouton principal, rien à corriger ici.

#### Stratégie : Restrained

Neutres + un accent unique. **L'accent ne dit qu'une chose : « ceci est
interactif ou actif ».** Il ne porte jamais une donnée, jamais un jugement.
Les jugements ont leurs propres jetons (`--ok`, `--warn`, `--error`,
`--pending`) et ceux-là ne servent qu'à ça.

Il n'existe **pas** de jeton « info ». Un état sans jugement s'écrit dans la
couleur du texte.

**`--pending` est délibérément hors de la famille de l'accent.** L'accent
Desk Amber (#D6B529) est ambre ; `--pending` prend `#9A9DB1`, un gris-violet à
faible chroma hors de toute famille chaude — doctrine inchangée depuis
Nocturne (« ne jamais confondre interactif/actif et en attente »). Aucune des
deux couleurs n'existe dans la maquette source (son mock de données ne va pas
jusqu'à « en attente ») : dérivée en OKLCH avec la même méthode de
construction que le reste du système (luminance/chroma cohérents), pas
copiée d'ailleurs. `--pending` porte toujours l'attente de confirmation
(barre de lancement armée) : armer n'est pas avertir.

#### Un rendu écrit, un chemin préparé pour le second

`:root` porte Desk Amber directement — ce n'est **pas** une bascule pour cette
passe. `[data-theme="light"]` existe en bloc vide : l'architecture (jetons
sémantiques, structure `:root` + `[data-theme]`) est prête à recevoir un mode
clair sans réarchitecturer la feuille de jetons ni les composants qui la
consomment, mais aucune valeur n'y est écrite. Voir « Écarts connus ».

#### Contraste

Tout texte tient 4,5:1 sur **son fond réel**, tout texte large ou composant
d'UI tient 3:1. Recalculé indépendamment (luminance relative WCAG via OKLab)
pour chaque jeton Desk Amber avant application — pas supposé conforme parce
que la maquette source semblait lisible.

Deux corrections faites en conséquence :

1. **`--text-3`** : la source utilise L=0,5 (OKLCH), qui échoue AA sur son
   propre fond de badge OFF (2,81:1, mesuré). Fixé à L=0,62 — 4,64:1 dans ce
   pire cas, 4,91 à 5,28:1 ailleurs.
2. **Motif des pastilles de statut** : la source utilise un fond teinté à
   16 % + texte de la même couleur pour ses badges (`done`/`running`/
   `failed`). Vérifié : ce motif est **structurellement** inatteignable en AA
   pour au moins le rouge — sa chroma (0,19) sort du gamut sRGB dès L≈0,72,
   plafonnant le contraste à 3,45:1 quelle que soit la luminosité poussée
   au-delà (balayage empirique, pas une extrapolation). Ce n'est pas une
   valeur à ajuster, c'est le motif visuel qui ne peut pas passer pour ces
   teintes. Remplacé par le motif déjà présent et déjà conforme dans la même
   maquette pour ON/OFF : fond plein + texte `--on-accent` (8,48 à 9,21:1
   selon le statut). Implique 6 règles CSS modifiées dans `style.css`
   (`.status-badge.status-*`), la seule dérogation de ce chantier à « seule
   la feuille de jetons change ». Détail complet : `DESK_AMBER_R1-R5.md`.

Les valeurs mesurées sont en commentaire dans `tokens.css`, ligne par ligne —
ne pas modifier une couleur sans refaire le calcul, et pour un jeton de
statut, vérifier le contraste sur son fond **composité réel**, pas sur
l'hypothèse que fond-teinté-de-la-même-couleur est automatiquement sûr.

### Typography

Deux familles, servies depuis `/static/fonts/` — **aucune requête CDN**.
Remplace Inter seule (Nocturne) : la maquette Desk Amber distingue le chrome
de la donnée par la famille, pas seulement par la graisse.

- **Space Grotesk** (`--display`, aliasée `--ui`) : chrome, titres, libellés,
  boutons, nav, pastilles d'état. Poids **600** sur les titres/nav actif
  (700 sur le logo et le CTA, géré au cas par cas dans `style.css` — pas de
  jeton dédié pour cette seule exception, comme sous Nocturne).
- **`JetBrains Mono`** (`--mono`) : **toute donnée**, plus le nom du produit.
  La classe utilitaire `pk-mono` documente explicitement l'intention dans le
  balisage de `metric()`/`data_table()`, en plus de la règle mécanique
  ci-dessous.

**Le contraste des deux familles porte toujours la hiérarchie**, pas la
taille seule.

Règle mécanique inchangée : `table, .num, .mono, .pk-mono, code, pre,
.metric-value, input, select, textarea` reçoivent `--mono` + `tabular-nums` +
`"tnum" 1, "zero" 1`. Non négociable — c'est ce qui permet l'alignement
décimal.

Six pas, **valeurs inchangées** (`--t-micro` 12px → `--t-head` 28px) — la
source Desk Amber ne redéfinit pas d'échelle numérique générique (les tailles
observées, 10,5 à 15px, sont propres à sa maquette dense, pas une échelle à
importer par-dessus celle déjà calibrée du projet). Tout titre porte toujours
`overflow-wrap: break-word` (mesuré à 200 % de zoom texte en 390px, cf.
historique).

### Layout

Section **inchangée par ce chantier** — Desk Amber ne touche ni à la grille,
ni à la divulgation progressive, ni à la barre collante, ni à l'adaptation
tactile : uniquement jetons de couleur, typographie, rayon, élévation.

#### La grille du poste

Asymétrique et délibérée : `1.3fr / 1fr`. La colonne gauche porte la tâche
principale, la droite ce qui la sert.

**Aucun panneau ne défile en interne.** Le seul défilement d'une page est
celui de la page.

#### Divulgation progressive

Deux blocs de formulaire restent ouverts — le nom du run et l'objectif. Les
neuf autres se replient en `<details>` portant leur état en résumé.

#### Barre de lancement collante

En bas de la colonne de configuration, avec le rappel cible / horizons /
schéma. `html` réserve `scroll-padding-bottom` égal à `--launch-bar-h`.

#### Adaptation : le pointeur, pas la largeur

Les cibles tactiles s'adaptent sur `pointer: coarse`, jamais sur une largeur
de viewport. Deux seuils : 44px pour un contrôle (WCAG 2.5.5), 24px pour un
lien de texte dans une table dense (WCAG 2.5.8).

Ruptures inchangées : 1100px (simulateur en colonne), 980px (grille du poste
en colonne, bandeau enroulé).

### Elevation & Depth

**Philosophie remplacée, pas fusionnée** avec Nocturne (anneau fin 1px +
ombre diffuse croissante). Desk Amber : **triple couche** — un highlight
interne (`inset`, matière qui capte la lumière par le haut), une ombre
courte (contact), une ombre diffuse (portée). Le bord n'est plus fondu dans
l'ombre : `--rule`/`--rule-strong` portent la bordure séparément, en CSS
`border`, comme déjà pour toute autre matière du système.

- `--shadow-sm` — highlight + ombre courte + ombre diffuse modérée
  (mesuré sur les cartes de réglage au repos de la source). Rôle : carte au
  repos, champ et bouton au repos — **au repos**, pas seulement au survol :
  Desk Amber pose une ombre par défaut plus marquée que l'anneau fin de
  Nocturne, différence de caractère assumée entre les deux mondes.
- `--shadow-md` — même structure, couches plus prononcées (mesuré sur le
  survol des mêmes cartes). Rôle : élément relevé/actif au survol.
  `--shadow-md-up` en miroir vertical pour la barre de lancement collante.
- `--shadow-lg` — 4 couches (highlight + 2 ombres de contact + une large
  diffuse), mesuré sur le panneau boîtier de la source, son niveau le plus
  élevé. Rôle : ce qui flotte au-dessus de **toute** la page — seul le
  popover du glossaire (`role="dialog"`) l'utilise aujourd'hui.

Le filet ne structure plus la page : il sépare deux lignes **dans** un panneau
(`--rule`) ou cerne un objet manipulable (`--rule-strong`).

**Jamais de panneau dans un panneau** : il ne dit rien de plus que le filet
qu'il remplace et brouille la hiérarchie.

**Détail signature** (hérité de Nocturne, inchangé par Desk Amber) : les
filets de table (`data_table()`, leaderboard) sont peints en dégradé fondu sur
48px à chaque bout plutôt qu'un arrêt net — porté par la ligne (`background`,
peint en bas de la ligne), jamais par une bordure de cellule.

#### Mouvement

**Un seul moment authoré** : la bande se révèle de gauche à droite en 620ms
(sortie cubique) au chargement. Le reste est fonctionnel : la jauge balaie
**uniquement** pendant les phases non mesurables, le leaderboard glisse au tri
(FLIP), le panneau de résultats apparaît. `prefers-reduced-motion` retire le
mouvement, **jamais** l'information.

Desk Amber ajoute un halo (glow) sur l'accent au survol du CTA principal et
de l'onglet actif — jamais sur un élément neutre ou de statut, même
parcimonie que le reste de la doctrine (« l'accent signale l'actif/
interactif, jamais un jugement »).

### Shapes

`--r-small` 2px, `--r-control` 3px, `--r-panel` 3px, `--r-chip` 2px —
rayons Desk Amber exacts, mesurés sur la source, remplacent l'échelle
4/8/14/999px de Nocturne. Échelle resserrée : Desk Amber n'a qu'un seul
palier « élevé » distinct (le panneau CTA/résumé, à 4px dans la source) sans
équivalent dans les jetons existants — non doté d'un jeton dédié pour cette
unique exception, `--r-panel` partage la valeur de `--r-control` (3px,
dominante partout ailleurs dans la source).

**`--r-chip` passe de 999px (pilule) à 2px (carré).** Mesuré directement sur
les badges ON/OFF de la source : `border-radius: 2px`, pas une pilule — écart
vérifié avant implémentation plutôt que supposé (une pilule existe ailleurs
dans le fichier source, section différente, non `1c`). Affecte pastilles de
statut, boutons de plage, tout consommateur de `--r-chip`.

#### Focus — un seul régime, sans exception

```css
:where(a, button, input, select, textarea, summary, [tabindex]):focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--r-small);
}
```

Règle inchangée par ce chantier. **Toute règle qui repose `outline: none` sur
un élément focusable est un défaut.**

### Components

Composants Jinja partagés dans `templates/_components.html`, CSS dans
`static/style.css`, jetons dans `static/tokens.css`. **Aucun composant Jinja
n'a été réécrit par ce chantier** — seule la feuille de jetons change, à une
exception CSS près (pas de gabarit) : `status_badge()`.

**`metric(label, value, reliability, state)`** — le composant signature. Le
troisième argument est **obligatoire**. Valeur en `--t-value` (24px) en chasse
fixe (`pk-mono`, JetBrains Mono) ; ligne de fiabilité décrochée par un filet
vertical de 1px.

**`data_table(headers, rows, empty_message, row_classes, num_cols, footer)`** —
`num_cols` porte les indices des colonnes de **mesure** ; elles seules
reçoivent les classes `num pk-mono`. Filet de ligne en dégradé fondu 48px
(voir Elevation & Depth), en-tête collant sur fond `--raise`.

**`status_badge(label, state)`** — pastille avec point de 6px en
`currentColor`. **Seul composant dont la CSS (pas le gabarit Jinja) a changé** :
`.status-badge.status-{ok,warning,error,pending}` passent de
`color: var(--X); background: var(--X-weak)` à
`background: var(--X); color: var(--on-accent)` — motif fond-plein plutôt que
fond-teinté, seul moyen de tenir AA pour ces teintes (voir « Contraste »
ci-dessus). `.status-neutral`/`.status-disabled` inchangés, jamais concernés
(texte clair sur `--raise`, pas un aplat de la même famille que son propre
texte).

**`empty_state` / `error_state`** — encadré sur `--raise`, message préfixé de
`NA`. Inchangé.

**Le verdict de la station** (`.verdict`) — inchangé structurellement, jetons
Desk Amber (chasse fixe boîtier).

**Les lignes de portée locale** (`.scope-line`) — inchangées.

**La bande d'enregistrement** (`.record`, `observatory.js`) — inchangée.

**Les briques de rigueur** (`.adv-gate`) — inchangées.

**La barre de lancement à deux temps** — `--shadow-md-up` (mécanique triple
couche, cf. Elevation & Depth). Le teinté d'armement reste **composé sur** la
surface.

**Le glossaire** — `--shadow-lg`, 4 couches (voir Elevation & Depth), même
rôle qu'avant : flotte au-dessus de toute la page.

**Toiles (canvas)** — inchangées : lisent les jetons au tracé, aucun repli
codé en dur.

### Do's and Don'ts

**À faire**

- Écrire la contrepartie de fiabilité de chaque chiffre.
- Refuser d'imprimer une mesure non interprétable, et dire pourquoi.
- Rendre l'état d'une brique de rigueur en permanence, ON comme OFF.
- Déclarer `num_cols` sur toute table portant des mesures.
- Fermer chaque liste par un pied portant compte et réserves.
- Poser toute toile sur le boîtier et lire ses couleurs sans repli.
- Donner à toute surface au repos son état vide écrit.
- Adapter les cibles tactiles sur `pointer: coarse`, jamais sur la largeur.
- Vérifier le contraste sur le fond **composité réel** — pour un jeton de
  statut, ça veut dire son propre fond teinté s'il en a un, pas seulement le
  fond de page derrière.
- Poser `--shadow-sm` avant `--shadow-md`/`--shadow-lg` — le niveau de repos
  n'est pas une étape à sauter.

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
- Supposer qu'un motif fond-teinté-de-la-même-couleur + texte-coloré est sûr
  parce qu'il ressemble à celui d'un autre système — une chroma élevée peut
  sortir du gamut sRGB et plafonner le contraste indépendamment de la
  luminosité choisie (mesuré sur ce chantier, voir « Contraste »).

### Écarts connus entre le contrat et le code

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
  inchangée par ce chantier, seules ses couleurs suivent Desk Amber.
- **`--r-panel` partage la valeur de `--r-control`** (3px) faute d'un palier
  « élevé » distinct dans la structure de jetons existante — le panneau
  CTA/résumé à 4px de la source n'a pas de jeton dédié. Voir « Shapes ».


---

## Partie 2 — Rapport d'extraction R1-R5

*Source d'origine : `patrick/DESK_AMBER_R1-R5.md`.*

Livrable intermédiaire du chantier de remplacement du système « Nocturne » par « Desk Amber » (direction `1c` de `PATRICK__Directions_visuelles_export.html`). **Aucun fichier de production modifié à ce stade** — extraction, mapping et vérification de contraste uniquement. Implémentation (R6, gabarits, captures) en attente de validation.

Source : section `id="1c"` de l'export, décodée le 2026-08-11.

---

### R1 — Extraction exacte

**Espace colorimétrique** : 100 % OKLCH, aucun hex dans l'extrait (hors `rgba(...)` pour les ombres portées, comme sous Nocturne).

**Teinte de base** = hue `60` (neutres/fonds/bordures/texte), **accent** = hue `95`, chroma constant `0.15`.

| Rôle | Valeur OKLCH exacte | Usage observé |
|---|---|---|
| Fond boîtier (outer shell, dégradé) | `oklch(0.165 0.013 60)` → `oklch(0.14 0.011 60)` | fond du panneau principal |
| Fond carte/en-tête (dégradé) | `oklch(0.205 0.016 60)` → `oklch(0.185 0.015 60)` | header, cartes réglage ON |
| Fond carte OFF (plat) | `oklch(0.185 0.014 60)` | cartes désactivées, `opacity:.7` |
| Fond panneau élevé (CTA, dégradé diagonal) | `oklch(0.26 0.02 60)` → `oklch(0.21 0.017 60)` | résumé config + bouton lancer |
| Fond en-tête de table | `oklch(0.18 0.014 60)` | thead |
| Fond ligne survolée | `oklch(0.2 0.016 60)` | tr:hover |
| Fond input/select | `oklch(0.24 0.019 60)` | filtres |
| Fond chip/tag | `oklch(0.25 0.02 60)` → hover `oklch(0.28 0.022 60)` | tickers, modèles |
| Fond badge OFF | `oklch(0.23 0.018 60)` | pastille OFF |
| Texte bright | `oklch(0.94 0.01 60)` | titres carte, valeurs, IDs |
| Texte secondary | `oklch(0.7 0.015 60)` | nav, corps de table, inputs |
| Texte muted | `oklch(0.5 0.015 60)` | libellés OFF, dates, en-têtes table |
| Ink (texte sur accent plein) | `oklch(0.14 0.012 60)` | texte badge ON, texte bouton CTA |
| Accent | `oklch(0.78 0.15 95)` — hover `oklch(0.83 0.15 95)` | onglet actif, badges ON, sparkline, CTA |
| Bordure carte | `oklch(0.36 0.026 60 / 0.55)` — OFF : `oklch(0.34 0.024 60 / 0.4)` | |

**Typographie** : `'Space Grotesk'` (interface/titres/nav/boutons) + `'JetBrains Mono'` (IDs, tickers, dates, toutes colonnes numériques) — confirmé exactement comme attendu, à télécharger et auto-héberger.

**Ombres triple couche** (cartes de réglage) :
`inset 0 1px 0 rgba(255,255,255,.05), 0 2px 5px rgba(0,0,0,.4), 0 8px 16px -6px rgba(0,0,0,.45)` → hover : `inset …06, 0 3px 7px …5, 0 12px 22px -6px …55` + `translateY(-1px)`.

Le panneau boîtier (niveau le plus élevé) a une **4ᵉ couche** supplémentaire (`0 24px 48px -12px rgba(0,0,0,.7)`) — cohérent avec l'échelle à 4 niveaux déjà en place pour Nocturne.

**Rayons** : `2px` (badges, chips, pastille indice) / `3px` (cartes, header, boutons, inputs) / `4px` (panneau élevé CTA) — confirmé « 2–4px ».

> ⚠️ **Correction vs consigne initiale** : les badges ON/OFF ne sont **pas en pilule** dans cet extrait — `border-radius:2px`, un rectangle quasi carré, pas un radius ≈ moitié-hauteur. La pilule (20px) croisée en cherchant le fichier appartient à une **autre** section (hue 265), pas à `1c`. Documenté ici tel quel (2px) — à confirmer si une pilule est voulue malgré tout.

**Survol** : `translateY(-1px)` + halo accent uniquement sur le CTA et l'onglet actif (glow `0 0 22px oklch(0.78 0.15 95 / .45)`) — jamais sur un élément neutre ou de statut. Conforme à la doctrine déjà en place (« l'accent signale l'actif/interactif, jamais un jugement »).

---

### R2 — Mapping sémantique proposé

| Jeton existant | Nouvelle valeur (Amber) | Statut |
|---|---|---|
| `--ink` | `oklch(0.11 0.009 60)` | **dérivé** — absent de l'extrait (qui ne montre que le panneau boîté, pas le fond de page derrière) ; plus sombre que `--ground`, même famille |
| `--ground` | `oklch(0.165 0.013 60)` | extrait (stop clair du dégradé boîtier) |
| `--surface` | `oklch(0.205 0.016 60)` | extrait |
| `--raise` | `oklch(0.2 0.016 60)` | extrait (fond ligne survolée) |
| `--rule` / `--rule-strong` | `oklch(0.34 0.024 60 / 0.4)` / `oklch(0.36 0.026 60 / 0.55)` | extrait |
| `--text` | `oklch(0.94 0.01 60)` | extrait |
| `--text-2` | `oklch(0.7 0.015 60)` | extrait |
| `--text-3` | `oklch(0.62 0.015 60)` | **corrigé** — l'extrait utilise 0.5, échoue AA (R4) |
| `--accent` / `--accent-hover` | `oklch(0.78 0.15 95)` / `oklch(0.83 0.15 95)` | extrait |
| `--on-accent` | `oklch(0.14 0.012 60)` (= nouvel `--ink`) | extrait |

Aucun renommage littéral — seules les valeurs changent, comme pour Nocturne. Les composants partagés (`metric()`, `data_table()`, `status_badge()`, `empty_state()`, `error_state()`) ne sont pas touchés à ce stade.

---

### R3 — Couleurs de statut

**Correction vs prémisse initiale** : l'extrait contient en fait des valeurs pour 3 des 4 statuts (dans le script de données mock, pas dans une palette déclarée) — `done`/`running`/`failed`, en fond teinté 16 % + texte coloré :

- succès : `oklch(0.72 0.15 142)`
- « en cours » (mappé à info, pas vraiment « attention ») : `oklch(0.75 0.14 230)`
- erreur : `oklch(0.7 0.19 25)`
- **rien pour « en attente »** (aucun statut queued dans le mock).

**Problème réel trouvé (voir R4)** : le motif fond-teinté-16 %+texte-coloré **ne peut pas atteindre AA 4,5:1**, pas seulement pour les valeurs actuelles mais **structurellement** pour rouge/bleu à cette chroma — `oklch(…, 0.19, 25)` sort du gamut sRGB dès L≈0.72 et le contraste plafonne à 3,45:1 quelle que soit la luminosité poussée au-delà (vérifié par balayage empirique de L, pas supposé). Ce n'est pas un problème de valeur, c'est le motif visuel lui-même qui est intenable en AA pour ces teintes.

**Palette proposée** — bascule du motif « fond teinté + texte coloré » (non conforme) vers le motif déjà présent et déjà vérifié dans l'extrait pour ON/OFF (fond plein + texte `--ink` foncé) :

| Statut | Valeur | Origine |
|---|---|---|
| success | `oklch(0.72 0.15 142)` | extrait, inchangé |
| info | `oklch(0.75 0.14 230)` | extrait, inchangé |
| error | `oklch(0.70 0.19 25)` | extrait, inchangé |
| **attention** (absent de l'extrait) | ~~`oklch(0.75 0.16 80)`~~ → `oklch(0.75 0.16 67)` | **dérivé, révisé après implémentation (R6)** — hue 80 initiale trop proche de l'accent (95, écart 15°) pour rester nette sur les daltonismes protan/deutéranopes ; décalée à hue 67 (écart 28°). Contraste recalculé sur la nouvelle valeur, motif fond-plein + `--on-accent` : 8,89:1 (amélioré vs 8,80:1 avant) |
| **pending/attente** (absent de l'extrait) | `oklch(0.70 0.03 280)` | **dérivé** — faible chroma, hors famille accent, même doctrine que `--pending` sous Nocturne (sorti de la teinte active pour ne jamais se confondre avec l'interactif) |

> ⚠️ « Même teinte de base 60 » (consigne initiale) n'a **pas** été lue au sens littéral (hue=60 pour tous les statuts) — ça rendrait succès/attention/erreur indiscernables entre eux et du neutre. Lu comme « même méthode de construction (L/C cohérents avec le reste) », comme le fait l'extrait lui-même (hues distincts 142/230/25). **À confirmer** si ce n'est pas la lecture voulue.

---

### R4 — Contraste WCAG AA

Recalculé indépendamment (formules OKLab officielles → luminance relative → ratio WCAG), pas supposé conforme parce que l'extrait a l'air lisible.

| Paire | Ratio | AA texte normal (4,5:1) |
|---|---|---|
| `--text` sur `--surface` / `--ground` | 15,03 / 15,63 | ✅ |
| `--text-2` sur `--surface` / `--ground` | 6,70 / 7,20 | ✅ |
| `--text-3` **original (0.5)** sur `--surface`/`--ground`/badge OFF | 2,98 / 3,20 / **2,81** | ❌ |
| `--text-3` **corrigé (0.62)** sur `--surface`/`--ground`/badge OFF | 4,91 / 5,28 / 4,64 | ✅ |
| `--on-accent` sur `--accent` / `--accent-hover` | 9,97 / 11,83 | ✅ |
| `--accent` sur `--ground` / header | 9,65 / 8,98 | ✅ |
| status texte coloré sur fond teinté 16 % (motif original) | success 3,81 / info 3,93 / error **3,45 (plafond gamut, non atteignable)** | ❌ les trois |
| status `--on-accent` sur fond plein (motif corrigé) | success 8,48 / info 9,21 / error 6,85 / attention 8,80 / pending 7,42 | ✅ tous |
| status couleur (texte/dot) sur `--surface` opaque | 7,64 / 8,30 / 6,17 / 7,93 / 6,69 | ✅ tous |

---

### R5 — Mapping pages

Identique à Nocturne (aucune nouvelle réflexion de structure) : dashboard dense sur `/` (Poste de lancement, seul gabarit fourni par l'export), `JetBrains Mono` sur toutes les colonnes numériques des tables (`/runs`, `/universe`), pages de détail plus aérées via `--s*`/`--t-*` inchangés.

---

### Points à trancher avant R6

1. Badges ON/OFF en 2px carré (mesuré dans l'extrait) ou pilule forcée (absente de l'extrait, vue ailleurs dans le fichier) ?
2. Lecture de « même teinte de base 60 » pour les statuts dérivés (attention/pending) — confirmée ou pas ?

Aucun fichier de production touché par ce rapport.
