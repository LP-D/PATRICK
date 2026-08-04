---
target: accueil / (page de configuration et suivi de run)
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 2
timestamp: 2026-08-02T15-42-27Z
slug: patrick-webapp-templates-index-html
---
Method: dual-agent (A: revue design isolée · B: détecteur + relevé navigateur isolé)

## Design Health Score

| # | Heuristique | Note | Δ | Constat clé |
|---|---|---|---|---|
| 1 | Visibilité de l'état | 3 | = | Bande, légende chiffrée, titre de panneau qui suit son contenu. Mais `/` affiche `running` en texte brut là où `/runs` pose une pastille, et un run en cours annonce « F1_dir, meilleur de 0 essai(s) » — une contrepartie qui énonce une fausseté. |
| 2 | Correspondance au monde réel | 3 | = | Glossaire titré en libellé humain, validation francisée. Mais `--ok`/`--error` portent la direction de marché (`▲ Hausses` en vert) : une hausse n'est pas un « bon état », et DESIGN.md réserve ces jetons au jugement. |
| 3 | Contrôle et liberté | 3 | +1 | Armement à deux temps, Échap, désarmement à toute modification, confirmation avant d'écraser 65 champs. Mais l'état `open` des blocs n'est pas persisté : charger un exemple referme les neuf. |
| 4 | Cohérence et standards | 2 | = | Focus désormais uniforme sur les cinq types de contrôles. Mais le statut se rend de deux façons selon la page, `metric()` est employé partout sauf ici, et `--warn` (jaune de jugement) est détourné pour signifier « prêt à confirmer ». |
| 5 | Prévention des erreurs | 2 | +1 | Le compte de combinaisons et le rang en file sont les bons garde-fous. Mais le récapitulatif ne nomme aucune brique de rigueur, et 550 options de cible restent sans recherche. |
| 6 | Reconnaissance plutôt que rappel | 3 | +1 | Résumés d'état et rappel collant : le meilleur gain des passes. Mais les résumés coupent en plein mot à 26 caractères, et le bloc qui contient le seed se résume par « 2 réglage(s) ». |
| 7 | Flexibilité et efficacité | 2 | = | Toujours aucune reprise de la config d'un run passé, et la bande n'est pas cliquable : on identifie un run au survol et on ne peut pas y aller. |
| 8 | Esthétique et minimalisme | 2 | = | Blocs ouverts, la page fait 3416px et la colonne de droite s'arrête à ~1610px : ~1800px de sol vide. Hiérarchie typographique effondrée — 4 pas réels sur 6. |
| 9 | Diagnostic et récupération | 2 | = | Le bandeau de réserve est un vrai correctif. Mais aucune erreur inline par champ, et les colonnes de movers vides affichent quand même « Clique un symbole » — une instruction pour un objet qui n'existe pas. |
| 10 | Aide et documentation | 3 | = | 40 popovers, focus déplacé dedans, Échap qui le rend au déclencheur. Mais quatre `?` orphelins aux zones de clic superposées, et le popover peut déborder du bas du viewport. |
| **Total** | | **25/40** | **+3** | **Acceptable haut — pas encore Good.** |

## Design Specificity Verdict

**Spécifique dans le vocabulaire, générique dans la forme — et le composant signature du système est absent de cette page.**

**Évaluation design.** Ce qui ne pourrait être que ce produit : le récapitulatif armé qui calcule « 330 combinaisons à évaluer » au lieu d'estimer une durée ; la légende qui compte séparément « 6 sans compte d'essais (hauteur plancher) » ; les neuf lignes de configuration repliées, titre Archivo capitales à gauche, valeur en chasse fixe à droite, qui se lisent comme la sortie d'un `--dry-run`.

Mais `metric(label, value, reliability)` — le composant dont DESIGN.md dit qu'il rend « le chiffre nu littéralement impossible » — **n'apparaît nulle part sur `/`**. Mesuré : 638 éléments à 14px, 120 à 13px, 57 à 12px, 40 à 10px, 2 à 17px, et un seul objet au-dessus de 17px (le `h1`). Le pas `--t-value` (24px) n'est pas utilisé une seule fois. La thèse survit sur l'accueil comme copie, jamais comme forme. Sur `/runs/{id}` la même thèse est spectaculaire. L'écart entre les deux surfaces est plus grand que l'écart entre PATRICK et un produit quelconque.

**Scan déterministe.** Le scan CLI des gabarits rend toujours 0 : les `<link href="/static/…">` absolus ne sont pas résolubles depuis le disque. L'agent a poussé plus loin que la passe précédente avec un **test-sentinelle** — une feuille CSS fautive liée en chemin *relatif* dans un miroir local : scannée comme fichier CSS elle rend 2 trouvailles, scannée via le HTML qui la lie elle en rend 0. **Le mode HTML du détecteur n'analyse pas le CSS lié, quel que soit le chemin.** Et le scan URL sort en **code 0 avec `[]`** quand Puppeteer manque : un scan non instrumenté passerait pour propre. C'est un piège d'outillage, pas un résultat.

Par injection dans la page : 56 trouvailles sur `/`, 14 sur `/runs/{id}`, 10 sur `/simulate`. Après vérification, **l'essentiel est faux positif** :

- **40 « contenu débordant » sur `/`** visent toutes `.info-icon`. Mesure : boîte 15×15, `scrollWidth` 29. C'est le pseudo-élément de 44×44 que j'ai posé délibérément à la passe `adapt` pour étendre la zone de contact. Le détecteur lit une extension de cible comme un débordement.
- **« Texte masqué par un élément superposé »** : l'agent a extrait l'`outerHTML` des coupables — ce sont **les badges que le détecteur injecte lui-même**.
- **em-dash ×570** : 3 dans le gabarit source, le reste vient des données (libellés d'options, `<span class="na">—</span>`).
- **Deux `#000`** : des stops de `mask-image`, donc des valeurs d'opacité, jamais peintes.

Restent comme vrais positifs : longueur de ligne sur `#record-caption` (~232 caractères) et sur trois `.hint`, capitales sur des libellés de 33 à 37 caractères, et le glyphe de 10px hors rampe.

**Pas de superposition à consulter** : l'injection s'est faite hors écran et le live-server a été arrêté (vérifié : port fermé, application intacte).

## Overall Impression

Les quatre passes ont fermé ce qu'elles visaient, et le relevé le confirme sans ambiguïté : **0 échec de contraste sur 20 contextes** (harnais validé par une injection délibérée à 1,92:1, donc le zéro est réel et non un outil muet), **0 arrêt de tabulation sans indicateur sur 24**, **0 toile sans nom accessible**, **0 libellé technique brut**, **0 champ sans étiquette**, **0 saut de titre**, **0 erreur console**.

Mais le score ne monte que de 3 points, et la raison est nette : **mes propres passes ont introduit deux P0**. Le repli du formulaire a rendu invisibles les garde-fous désactivés — sur un produit dont l'argument est que la fuite est structurellement empêchée. Et la barre de confirmation que j'ai ajoutée est translucide, donc illisible sur mobile au moment précis où elle sert. Ce ne sont pas des dettes héritées : je les ai créées en corrigeant autre chose.

## What's Working

1. **L'armement à deux temps.** `projectedCombinations()` calcule le produit réel des cardinalités du formulaire — pas une estimation — et affiche le rang en file. Refuser d'inventer une durée en minutes pendant qu'on affiche un compte calculable, c'est la doctrine du produit appliquée à une interaction.
2. **Les lignes de configuration repliées.** Le seul endroit de la page où le monde visuel produit une forme qu'aucun autre produit n'aurait.
3. **L'accessibilité mécanique, mesurée et non affirmée.** Le bouton primaire en sombre est passé de 2,56:1 à 7,84:1. Les cibles tactiles de `/universe` sont passées de 558 sous-dimensionnées à 0 au seuil applicable (24×24 en table dense), sans toucher la densité à la souris.

## Priority Issues

### [P0] Le résumé des blocs repliés ne montre que ce qui est ACTIVÉ — les garde-fous désactivés sont devenus des défauts silencieux

`advSummaryText()` itère sur `input[type=checkbox]:checked`. À l'état par défaut : `purge = false`, `calibration = false`, `stacking = false`. Le résumé de « Validation » affiche donc `Embargo (retire les premi… · Walk-forward` — **le mot « purge » n'apparaît nulle part**.

**Pourquoi ça nuit.** PRODUCT.md : « chaque brique de rigueur est explicitement activable/désactivable et le rapport indique lesquelles étaient actives — aucune ne doit devenir un défaut silencieux ». En repliant, j'ai produit exactement l'inverse : on peut lancer un run **sans purge** sans jamais l'avoir su, sur un produit dont l'argument de vente est que la fuite est structurellement empêchée. Et le sous-titre que j'ai écrit l'aggrave — « leur résumé les affiche sans qu'il faille les ouvrir » est faux, et c'est écrit sur le premier écran.

**Correctif.** Traiter les briques de rigueur comme une classe à part : un jeu explicite de clés (`purge`, `embargo_enabled`, `calibration`, `stacking`, `data_quality_enabled`, `uniqueness_weights`) dont l'état est **toujours** rendu, ON comme OFF, avant le reste du résumé — `Purge OFF · Embargo ON · Walk-forward`. Et faire porter la même ligne au récapitulatif armé, seul instant où le refus est encore gratuit.

**Commande :** `/impeccable polish`

### [P0] La barre de lancement armée devient translucide : la confirmation s'imprime par-dessus le formulaire

`.launch-bar[data-confirm]` **remplace** `background: var(--surface)` par `var(--warn-weak)` — `rgba(138,90,8,0.12)`. La barre est `position: sticky`, donc le formulaire transparaît à travers. Vérifié au rendu 390×844 : le texte du récapitulatif se superpose au champ `mon_run` et au titre « OBJECTIF ». Illisible.

**Pourquoi ça nuit.** C'est le moment le plus engageant du produit et le seul texte qui décrit ce qu'on va lancer. DESIGN.md impose de vérifier le contraste « sur le fond composité réel » : ici ce fond dépend de la position de défilement. Sur mobile — le rythme « lancer puis abandonner » — la confirmation est inutilisable.

**Correctif.** Composer le teinté sur la surface au lieu de la remplacer : `background: color-mix(in srgb, var(--warn) 12%, var(--surface))`. Et reconsidérer `--warn` : armer un lancement n'est pas un avertissement, `--pending` porte mieux « en attente de confirmation ».

**Commande :** `/impeccable polish`

### [P1] La barre collante masque le champ « Régimes », et rien ne compense au clavier

Mesuré à 1440×900, page en haut : `.launch-bar` commence à `top: 832`, `input[name=regimes]` occupe `835 → 867`. Entièrement derrière. `scroll-padding-bottom` vaut `auto`. En tabulant depuis « Seuil flat », le navigateur ne défile pas — le champ est techniquement dans le viewport — donc on tape dans un champ invisible. Sur mobile la barre fait 111px au repos, **165px armée**, soit 20 % du viewport.

**Correctif.** `scroll-padding-bottom` égal à la hauteur de la barre, publiée en variable par `ResizeObserver` (elle varie de 68 à 165px), plus un `scrollIntoView({block:'nearest'})` au `focusin` dans `.run-form`. Sous 900px, replier la barre sur une ligne.

**Commande :** `/impeccable adapt`

### [P1] Le zoom texte à 200 % déborde en mobile — non mesuré jusqu'ici

L'audit avait vérifié le zoom à 1440px seulement, et trouvé 0. En 390px : **`/` déborde de 100px, `/universe` de 333px, `/simulate` de 64px**. Coupables isolés (aucun ancêtre ne les clippe) : les boutons de plage « 5Y » et « Max » de l'aperçu marché, et le jeton insécable `config/defaults.py::DEFAULT_TARGET_GROUP` dans le sous-titre de `/universe`.

**Pourquoi ça nuit.** WCAG 1.4.4 : le contenu doit rester utilisable jusqu'à 200 % sans défilement horizontal. C'est une régression de couverture, pas de code — le défaut existait, personne ne l'avait mesuré à la bonne largeur.

**Correctif.** `flex-wrap` sur `.preview-range-buttons`, et `overflow-wrap: anywhere` sur les `code` du sous-titre.

**Commande :** `/impeccable adapt`

### [P2] La bande d'enregistrement : 97 % de vide, aucune sortie, aucun clavier

Toujours 1392×72px pour 18 runs concentrés sur ~90 secondes réelles, étalés sur 6 jours : deux amas. L'agent a balayé 61 positions horizontales — l'infobulle ne répond que sur les premières, et nomme **un** run là où neuf se superposent. Le canvas a `tabIndex = -1` et aucun gestionnaire de clic sur desktop : on identifie un run et on ne peut pas s'y rendre. Sur mobile, bande + légende consomment ~350px des 844 — **41 % du premier écran, sur toutes les pages**.

**Correctif.** Cadrer l'échelle sur l'étendue réelle des runs ; regrouper les marques coïncidentes avec un compte (`×9`) et lister le groupe dans l'infobulle ; rendre la marque cliquable ; canvas focusable avec ←/→ et infobulle en `aria-live`. Sous 700px, réduire à ~32px et replier la légende.

**Commande :** `/impeccable distill`

## Persona Red Flags

**Léon — expert, pressé, l'utilisateur réel.** Il veut relancer `run_a` avec un horizon de plus : aucun moyen de repartir de cette config, il retape. Il tabule vers « Régimes » et tape dans un champ caché derrière la barre. Il arme, lit « 330 combinaisons », confirme — **sans avoir jamais vu que purge est désactivé** et que le seed est resté dans un bloc résumé « 2 réglage(s) ». Ce qu'il croit avoir lancé et ce qu'il a lancé diffèrent sur le point que le produit revendique comme non contournable.

**Le collègue à qui Léon partage l'outil** (le partage est prévu dans PRODUCT.md). Il arrive sur « Poste de lancement » : une bande vide, un formulaire dont deux lignes disent « 2 réglage(s) » et une dit « Activé », trois panneaux qui affichent tous « pas de données ». Aucun chiffre en typographie de valeur, aucune trace du `metric()` qui fait la réputation de `/runs/{id}`. L'accueil ne fait aucune promesse que les autres pages tiennent pourtant.

**Casey — mobile, une main.** 41 % du premier écran pour une bande qu'il ne peut pas survoler. La barre lui prend 165px armée. Et quand il arme, **la confirmation est illisible** : le texte se superpose au formulaire. Il ne peut pas relire ce qu'il va lancer. Restent 9 liens interactifs entre 25 et 30px de haut — au-dessus du seuil AA de 24, sous le seuil AAA de 44.

## Minor Observations

- « F1_dir, meilleur de 0 essai(s) » sur un run en cours : une contrepartie de fiabilité qui affirme une fausseté.
- Le `<title>` de `/` est `PATRICK` seul quand les quatre autres portent `PATRICK — <page>`. Avec un run suivi, l'onglet pourrait porter la progression — c'est le cas d'usage « lancé puis abandonné » de PRODUCT.md.
- Le bouton de thème affiche l'état courant avec `aria-pressed` **et** `aria-live` sur le même élément : un lecteur d'écran annonce « Jour, bouton bascule, non pressé » sans dire ce qui se passera au clic.
- Quatre `?` orphelins dans « Sélection de features », à 18px d'écart pour des zones de clic de 44px : elles se chevauchent de 26px.
- Le popover de glossaire ne bascule pas quand il dépasse le bas du viewport.
- Les colonnes de movers vides affichent quand même « Clique un symbole pour en faire la cible du run ».
- `▲ Hausses` / `▼ Baisses` utilisent `--ok`/`--error` pour porter une donnée de marché, pas un jugement.
- L'état `open` des blocs n'est pas persisté.
- Les résumés tronquent en plein mot à 26 caractères.
- Aucun lien d'évitement : la première tabulation atterrit sur le nom du produit.
- Le scan URL du détecteur sort en code 0 avec `[]` quand Puppeteer manque — un scan non instrumenté passerait pour propre.

## Questions to Consider

1. Le sous-titre promet que les blocs repliés affichent leurs valeurs « sans qu'il faille les ouvrir ». Trois briques de rigueur sont à `false` et n'apparaissent nulle part. Le produit refuse d'imprimer une mesure non interprétable — **pourquoi imprime-t-il une promesse fausse sur son premier écran ?**
2. `metric()` force un troisième argument pour rendre le chiffre nu impossible. L'accueil n'appelle `metric()` nulle part et n'affiche aucun chiffre en typographie de valeur. **La contrainte fonctionne-t-elle, ou a-t-elle rendu plus facile de ne pas afficher de chiffre du tout ?**
3. La bande a traversé quatre passes sans que sa densité d'information change, et consomme 41 % du premier écran mobile de chaque page. **Combien de passes avant d'admettre qu'une file d'attente lisible en permanence servirait mieux la même idée ?**
4. L'armement calcule « 330 combinaisons » — donc le produit sait mesurer, pour zéro seconde de calcul, la dette de tests multiples qu'il s'apprête à contracter. **Pourquoi ne s'en sert-il pas pour avertir quand la configuration rend PBO, DSR et Diebold-Mariano structurellement non calculables ?**
