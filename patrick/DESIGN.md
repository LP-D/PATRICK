---
name: PATRICK
description: Sortie de solveur — un chiffre ne s'écrit jamais seul.
colors:
  ground: "#0D0F12"
  surface: "#14171B"
  raise: "#1B1F24"
  rule: "#262B32"
  rule-strong: "#39404A"
  text: "#E4E7EC"
  text-2: "#98A0AC"
  text-3: "#8E96A2"
  accent: "#5B9DFF"
  ok: "#4FB286"
  warn: "#D9A03F"
  error: "#E0736B"
  pending: "#C39BE8"
typography:
  head:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "1.375rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.01em"
  lead:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "1rem"
    fontWeight: 500
    lineHeight: 1.2
    letterSpacing: "normal"
  body:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  small:
    fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, Helvetica Neue, Arial, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "normal"
  micro:
    fontFamily: "JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.6875rem"
    fontWeight: 500
    lineHeight: 1.45
    letterSpacing: "0.08em"
rounded:
  none: "0"
  control: "2px"
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
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.ground}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "8px 20px"
  button-primary-hover:
    backgroundColor: "transparent"
    textColor: "{colors.accent}"
  input:
    backgroundColor: "{colors.ground}"
    textColor: "{colors.text}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "5px 8px"
  metric-value:
    textColor: "{colors.text}"
    typography: "{typography.lead}"
    rounded: "{rounded.none}"
  metric-reliability:
    textColor: "{colors.text-3}"
    typography: "{typography.micro}"
    padding: "8px 0 0 12px"
  status-badge:
    backgroundColor: "transparent"
    textColor: "{colors.text}"
    typography: "{typography.micro}"
    rounded: "{rounded.none}"
    padding: "0"
  table-cell:
    textColor: "{colors.text}"
    typography: "{typography.body}"
    padding: "8px 16px 8px 0"
  table-footer:
    textColor: "{colors.text-3}"
    typography: "{typography.micro}"
    padding: "8px 0 0"
---

# DESIGN.md — PATRICK

Généré depuis le code construit (`patrick/webapp/`), pas depuis une intention.
Le contrat de direction dont ce document est la mise à plat est en commentaire
HTML en tête de `templates/base.html` (blocs THESIS / OWN-WORLD / STORY /
FIRST VIEWPORT / FORM). Les jetons normatifs vivent dans `static/tokens.css` ;
ce fichier explique **comment les appliquer**, il ne les remplace pas.

## Overview

Le monde s'appelle **« Sortie de solveur »**. Il refuse le tableau de bord
quant — panneaux sombres, chiffres verts et rouges, KPI en gros — et adopte la
forme que tout quant lit déjà : la sortie d'un solveur statistique (R, Stata),
où l'estimé, son incertitude et son seuil s'impriment dans un même bloc aligné.

Il remplace **intégralement** la charte précédente (fond bleu-nuit, accent or,
sérif Cormorant Garamond en titres, Inter en texte, monogramme `.brand-mark`).
Aucune valeur n'a été conservée. Si vous trouvez `--gold-1`, `--muted`,
`.brand-mark` ou une police sérif quelque part, c'est un résidu à supprimer,
pas une variante à respecter.

**La thèse, en une phrase : un chiffre ne s'écrit jamais seul.** Tout le
système en découle. La signature de `metric()` (`_components.html:14`) force un
troisième argument `reliability` — le gabarit ne devine jamais l'incertitude,
l'appelant doit l'écrire, même pour dire « non calculable ». Les tables portent
un pied qui énonce les réserves pesant sur leurs colonnes. Et quand une mesure
n'est pas interprétable, le produit **refuse de l'imprimer** : il affiche `—`,
le motif en clair, et renvoie la justification longue en note `†` sous le bloc.

Mode : **Operate**. Le visiteur accomplit une tâche — lire une session de
calcul et savoir si le signal tient. La scannabilité et la densité priment sur
l'expression ; la marque vit dans la précision des détails, pas dans un logo.

## Colors

Trois fonds, volontairement très proches. Un listing de solveur n'empile pas
des cartes, il sépare par des filets : les fonds **situent**, les filets
**structurent**.

| Jeton | Valeur | Emploi |
|---|---|---|
| `--ground` | `#0D0F12` | La page. Noir **neutre**, jamais le bleu-nuit remplacé. |
| `--surface` | `#14171B` | Bandeau de session, bloc de résultats. |
| `--raise` | `#1B1F24` | Second niveau : champ de saisie, ligne survolée. |
| `--rule` | `#262B32` | Filet ordinaire. |
| `--rule-strong` | `#39404A` | Séparation majeure (haut d'un bloc, en-tête de table). |
| `--text` | `#E4E7EC` | Valeur, donnée, titre. |
| `--text-2` | `#98A0AC` | Libellé, en-tête de colonne, unité. |
| `--text-3` | `#8E96A2` | Incertitude, note de bas de bloc, valeur absente. |
| `--accent` | `#5B9DFF` | **Interactif ou actif. Rien d'autre.** |
| `--ok` | `#4FB286` | Mesure concluante. |
| `--warn` | `#D9A03F` | Réserve, seuil non atteint, fiabilité faible. |
| `--error` | `#E0736B` | Échec, exclusion, valeur invalide. |
| `--pending` | `#C39BE8` | En cours, issue non connue. |

Trois règles gouvernent la couleur :

1. **L'accent ne porte jamais une donnée ni un jugement.** Il dit « ceci est
   interactif ». Un chiffre bleu serait une erreur de catégorie.
2. **Il n'existe pas de jeton « info ».** Un état sans jugement s'écrit dans la
   couleur du texte. Le jeton `--info` a existé et a été supprimé : à 11 px il
   ne se distinguait ni de l'accent ni de `--text-3`, et il n'apportait aucune
   information que la casse et la position ne portaient déjà.
3. **La hiérarchie se fait par la taille et la casse, pas par le contraste.**
   Trois niveaux de texte suffisent.

`--pending` est à 271° et l'accent à 216° : **55° d'écart**, délibérés. La
valeur précédente (`#8A93E8`, 234°) n'était qu'à 20° de l'accent, et les deux
se rencontraient dans la même ligne de `/runs` — l'accent cessait alors de ne
dire que « interactif ».

Toute la palette a été vérifiée **avant construction**, à 4,5:1 minimum sur les
trois fonds *et* sur un fond composite de pastille à 12 %. Pire ratio mesuré :
**4,57:1**. Mesurez sur le fond composité réel, jamais sur le panneau nu —
c'est là que les échecs se cachent.

## Typography

Deux familles, une frontière nette :

- **La donnée est en chasse fixe** (`--mono`, JetBrains Mono 400/500/700).
  C'est la seule façon d'aligner des décimales, et l'alignement décimal est le
  geste central de ce monde.
- **Le chrome est en pile système** (`--ui`). Dans une sortie de solveur, le
  contenu est du listing et l'habillage est celui du système d'exploitation.
  Aucune police n'est téléchargée pour le chrome.

Cinq pas seulement, tous utiles — un listing dense ne peut pas se permettre
sept tailles :

| Jeton | Taille | Emploi |
|---|---|---|
| `--t-micro` | 11 px | En-tête de colonne, note, unité, marqueur d'état |
| `--t-small` | 12 px | Libellé, métadonnée de session |
| `--t-body` | 13 px | Donnée courante, cellule de table |
| `--t-lead` | 16 px | Valeur mise en avant, titre de bloc |
| `--t-head` | 22 px | Titre de page — **un seul par écran** |

`font-variant-numeric: tabular-nums` et `font-feature-settings: "tnum" 1,
"zero" 1` sont posés globalement sur `table, .num, .mono, code, pre,
.metric-value, input, select, textarea` (`style.css:27`). Non négociable :
c'est ce qui permet l'alignement décimal.

**Réserve connue :** JetBrains Mono est chargée depuis Google Fonts alors que
l'outil tourne sur `127.0.0.1`, souvent hors ligne. Hors ligne, le repli
`ui-monospace` prend le relais — la grammaire tient (chasse fixe, chiffres
tabulaires), le visage change.

## Layout

Colonne de contenu : `max-width: 1680px`, gouttières `--s5`. Un seul point de
rupture, **980 px** (`style.css:686`), où les grilles à deux colonnes passent à
une, le bandeau de session se replie et la grille de mesures s'empile.

**Les filets sont horizontaux. Il n'existe aucun filet vertical**, ni
séparateur de colonne, ni accent latéral, ni bord de carte. Seuls les
**contrôles** (champ, bouton, infobulle) gardent un contour fermé : un contrôle
est un objet qu'on manipule, pas une séparation entre deux contenus. Cinq
`border-left` décoratifs ont existé dans ce fichier et ont été supprimés ; ne
les réintroduisez pas pour marquer une subordination — **l'indentation seule la
marque** (`.metric-reliability`).

**Le plancher explicite.** Une table de résultats porte beaucoup de colonnes ;
les comprimer jusqu'à l'illisible coûte plus cher que le défilement. Les tables
défilent donc dans `.table-scroll`, et le vidage de config dans `.config-dump`
— **dans leur propre conteneur, jamais la page**. Mesuré : sans cette règle,
`/runs/{id}` débordait de 250 px en 390 px de large, et le bloc de config seul
portait la page à 13 266 px de haut.

**Le premier viewport porte la provenance.** `base.html` expose
`{% block session_context %}` : une ligne pleine largeur sous le bandeau,
portant cible / snapshot / hash de config / git SHA / seed. C'est le quadruplet
sans lequel aucun chiffre de la page n'est refaisable, et un listing imprime sa
provenance **avant** son premier résultat. Ne le reléguez pas en bas de page.

**Fermez vos listes.** Chaque `data_table()` accepte un `footer` : compte de
lignes, filtres actifs, et les réserves qui pèsent sur les colonnes (« F1_dir =
meilleur essai sur n, non déflaté ; p-value DM brute, non corrigée du test
multiple »). Une table sans pied se lit comme tronquée.

## Elevation & Depth

**Il n'y a pas d'élévation.** Zéro `box-shadow` dans tout le système. La
profondeur, quand elle est nécessaire, vient de l'écart de fond (trois niveaux)
et du filet, jamais d'une ombre portée. Le bandeau de session est `sticky` sans
ombre : c'est son fond `--surface` et son filet bas qui le détachent.

Le mouvement est rare et **toujours informatif** :

| Nom | Valeur | Objet |
|---|---|---|
| `state-transition` | `0.12s linear` | Bord de champ, fond de bouton |
| `progress-settle` | `transform 0.55s cubic-bezier(0.16,1,0.3,1)` | La jauge se pose sur sa valeur |
| `measuring` | `1900ms cubic-bezier(0.45,0,0.55,1) infinite` | Balayage de phase non mesurable |
| `flip-move` | `transform 0.42s cubic-bezier(0.16,1,0.3,1)` | Continuité de tri du leaderboard |
| `arrive` | `opacity 220ms` | Arrivée des résultats en fin de run |

**Le geste signature :** `worker.py` n'incrémente `progress_done` que sur les
lignes de fold ; pendant l'ingestion et la construction des features (~380 s)
il vaut 0. Afficher « 0 % » y serait **un chiffre qui ne mesure rien présenté
comme une mesure**. La jauge balaie donc au lieu d'afficher une valeur, et se
pose sur sa vraie valeur au premier fold. Le balayage s'arrête quand l'onglet
passe en arrière-plan (`html[data-page-hidden]`).

Sous `prefers-reduced-motion: reduce`, tout le mouvement est retiré et **aucune
information ne l'est** : le balayage disparaît, l'état « non mesurable » reste
lisible dans la ligne de statut.

## Shapes

Rayons quasi nuls : `--r-none: 0` partout, `--r-control: 2px` uniquement sur
les contrôles, et seulement pour ne pas faire d'angle vif agressif.

**Aucune pilule, aucun cercle, aucune icône décorative, aucune imagerie.** Les
états ne sont pas des pastilles : ils s'écrivent entre crochets, via
`::before`/`::after` sur `.status-badge` — `[DONE]`, `[RUNNING]`, `[ACTIVES]`,
`[NON CALCULÉE]`. Le texte porte l'information ; la couleur ne fait que la
doubler, ce qui rend l'état lisible même en monochrome.

La ligne retenue d'une table se marque **en graisse et par le mot « meilleur »
dans sa dernière colonne** — pas par un filet latéral (il n'en existe pas), pas
par un aplat coloré derrière des chiffres, qui nuirait à leur lecture.

## Components

Composants Jinja partagés dans `templates/_components.html`, CSS dans
`static/style.css`.

**`metric(label, value, reliability, state)`** — le composant signature. Le
troisième argument est **obligatoire** : c'est la mise en œuvre mécanique de la
thèse. Le libellé, la valeur et la ligne de fiabilité forment un bloc
indivisible, exactement comme `coef  std.err  p` sort d'un solveur. La ligne de
fiabilité est indentée sous la valeur, en `--t-micro`, en `--text-3`.

**`data_table(headers, rows, empty_message, row_classes, num_cols, footer)`** —
`num_cols` porte les indices (base 0) des colonnes de **mesure** ; elles seules
reçoivent la classe `num` qui déclenche l'alignement à droite. L'appelant
déclare, le gabarit ne devine pas : une cellule peut contenir un badge, un
intervalle ou un NA, et aucun de ces cas ne se détecte de façon fiable. Le
sélecteur couvre `table.data-table` **et** `table.leaderboard`.

**`status_badge(label, state)`** — six états : `ok`, `warning`, `error`,
`neutral`, `pending`, `disabled`. `neutral` prend la couleur du texte (pas de
teinte propre) ; `disabled` prend `--text-3`. Un run **échoué** doit prendre
`error`, jamais `neutral`.

**`empty_state` / `error_state`** — le vide s'écrit comme un solveur l'écrit :
un jeton et une phrase, pas une illustration.

**Le refus de calculer.** Ce n'est pas un composant, c'est une doctrine, et
c'est ce qui distingue ce rendu d'un monospace en costume. Quand
`pbo_reliability` refuse (moins de 6 blocs), la page n'affiche **pas** la
valeur ponctuelle à côté d'un message disant qu'elle n'a pas été calculée —
elle affiche `—`, la première phrase du motif, un appel de note `†`, et renvoie
les ~500 caractères de justification sous le bloc en `.block-note`. Rien n'est
masqué ; tout est déplacé là où ça se lit.

**Valeur absente.** Un solveur n'imprime pas une case vide : il imprime NA, et
la case reste alignée avec les chiffres de sa colonne. Le tiret cadratin tient
ce rôle, dans `<span class="na">`, en gris — **jamais dans la couleur d'une
mesure**. Trois absences sur une même ligne doivent avoir la même couleur.

**Contrôles.** `button.primary` est plein accent au repos et s'inverse au
survol (fond transparent, texte accent) — la seule inversion de contraste du
système. Les champs sont sur `--ground` avec un bord `--rule-strong` qui passe
à `--accent` au focus. `fieldset` n'a qu'un `border-top`.

**Toiles (canvas).** Une toile ne peut pas hériter d'une couleur CSS : elle
doit la **lire**. `simulate.js` et `market.js` exposent chacun un helper
`token(name)` **sans valeur de repli codée en dur**. C'est délibéré : un repli
survit à un remplacement d'identité et repeint silencieusement l'ancien monde —
c'est exactement ce qui s'est produit avec `--gold-1`. Si le jeton disparaît,
on veut le voir tout de suite.

## Do's and Don'ts

**À faire**

- Écrire la contrepartie de fiabilité de chaque chiffre — n, intervalle, ou le
  motif de sa non-calculabilité.
- Refuser d'imprimer une mesure non interprétable, et dire pourquoi en clair.
- Déclarer `num_cols` sur toute table portant des mesures.
- Fermer chaque liste par un pied portant compte et réserves.
- Écrire les états en `[TEXTE]`, la couleur ne faisant que doubler.
- Faire défiler tables et blocs de code dans leur propre conteneur.
- Lire les couleurs de toile depuis les jetons, sans repli.
- Vérifier le contraste sur le fond **composité réel**, avant de construire.

**À ne pas faire**

- Afficher un chiffre nu, sans son dénominateur ni sa réserve.
- Afficher une valeur ponctuelle à côté d'un message disant qu'elle n'a pas été
  calculée.
- Dessiner un filet vertical, un bord de carte, une pilule ou un cercle.
- Utiliser l'accent pour porter une donnée ou un jugement.
- Introduire un sixième neutre bleuté « informatif ».
- Afficher « 0 % » pendant une phase qui ne produit aucune mesure.
- Poser un `cursor: pointer` ou un survol d'accent sur un élément que rien
  n'active.
- Réintroduire un logo, un monogramme ou un placeholder de logo : le produit
  s'identifie par son nom en chasse fixe, et c'est un choix, pas un manque.

## Écarts connus entre le contrat et le code

Documentés parce qu'ils sont réels, pas corrigés ici :

- **`/simulate` au repos** ne rend ni pied de listing ni état vide : deux toiles
  vides et deux tables à en-têtes seuls. C'est la surface la moins dense du
  produit.
- **`sparkline()`** est déclarée dans `_components.html` mais n'est importée ni
  appelée nulle part — code mort.
- **Aucune capture ne montre une toile avec données** : le repointage des
  couleurs de graphique est vérifié en lecture de code, jamais observé au
  rendu.
