---
target: accueil / (page de configuration et suivi de run)
total_score: 22
max_score: 40
na_heuristics: 
p0_count: 2
p1_count: 2
timestamp: 2026-08-01T22-23-57Z
slug: patrick-webapp-templates-index-html
---
Method: dual-agent (A: revue design isolée · B: détecteur + relevé navigateur isolé)

## Design Health Score

| # | Heuristique | Note | Constat clé |
|---|---|---|---|
| 1 | Visibilité de l'état | 3 | Bande d'enregistrement, file d'attente et panneau de statut sont réels. Mais le panneau titré AVANCEMENT affiche « Derniers runs » au repos, et les deux colonnes de movers sont des `<ul>` vides sans état vide (~330 px de blanc muet). |
| 2 | Correspondance au monde réel | 3 | Vocabulaire du domaine respecté exactement. Mais le glossaire titre en clé de config brute (`DATA_QUALITY_ENABLED`), et la validation native répond « Please fill out this field. » en anglais sur une UI française. |
| 3 | Contrôle et liberté | 2 | Aucune confirmation avant un run de plusieurs heures, aucune annulation d'un run en file, et `<select id="load" onchange="this.form.submit()">` écrase silencieusement 65 champs saisis. |
| 4 | Cohérence et standards | 2 | Deux régimes de focus dans le même formulaire (mesuré : `outline 2px solid #1B4FD8` sur les liens et 8 contrôles, `outline: none` sur 63 autres). `/` est la seule page sans `<h1>`. |
| 5 | Prévention des erreurs | 1 | Le point le plus faible. Aucun garde-fou avant un run long, `#target_symbol` = 550 `<option>` sans recherche, « Lancer la simulation » actif alors qu'aucun run n'est choisi. |
| 6 | Reconnaissance plutôt que rappel | 2 | 65 contrôles dans un conteneur de 613 px pour 3042 px de contenu ; régler `embargo_bars` demande les horizons, 8 fieldsets plus haut et hors champ. Aucun indicateur « modifié vs défaut ». |
| 7 | Flexibilité et efficacité | 2 | Thème, langue et exemples mémorisés, liens profonds : bien. Mais `/runs/{id}` a une barre de sections et le formulaire, quatre fois plus long, n'en a aucune. Impossible de repartir de la config d'un run passé. |
| 8 | Esthétique et minimalisme | 2 | Monde beau et cohérent, mais l'économie d'espace est inversée : 180 px de premier viewport pour une bande à 2 marques visibles, 613 px visibles pour la tâche qui en demande 3042. |
| 9 | Diagnostic et récupération d'erreur | 2 | Les messages de non-calculabilité de `/runs/{id}` sont exemplaires. Mais rien côté client, aucune erreur inline par champ, et une panne de données se rend en `.hint` gris typographiquement identique à un texte d'aide. |
| 10 | Aide et documentation | 3 | 40 popovers de glossaire substantiels et exacts, un `.hint` par fieldset, les pieds de table qui énoncent les réserves. Nettement au-dessus de la moyenne. |
| **Total** | | **22/40** | **Acceptable — améliorations significatives nécessaires** |

## Design Specificity Verdict

**Spécificité forte sur les surfaces de verdict, faible sur l'accueil.**

**Évaluation design (non ancrée).** Ce qu'aucun produit voisin ne pourrait copier honnêtement est bien là, et c'est vérifié au rendu : sur `/runs/{id}`, cinq mesures d'affilée affichent `—` plutôt qu'un chiffre, chacune avec son motif en clair, et la note `†` déroule les 500 caractères de justification. Le filet vertical de 1px qui décroche la ligne de fiabilité sous chaque valeur porte un sens. Le pied de `/runs` énonce ce qu'on n'a pas le droit de conclure de ses propres colonnes. La légende de la bande compte séparément « 6 sans compte d'essais (hauteur plancher) » au lieu d'inventer une hauteur.

Ce qui pourrait être déposé tel quel dans n'importe quelle app de courtage occupe en revanche la moitié de l'accueil : la grille 2×2 de panneaux typographiquement identiques, et surtout le panneau « Plus fortes variations » — hausses/baisses, flèches, vert/rouge — qui n'est relié à rien : ses lignes ne sont pas cliquables, on ne peut pas envoyer un mover dans `target_symbol`. C'est le bloc le plus visible de la page et le moins connecté à la tâche.

Et la signature du monde se retourne contre elle : la bande mesure 1392 px et ne contient que deux amas de marques, le survol ne répond que sur 12 px cumulés (0,9 % de sa surface). Elle annonce 18 runs et en montre visiblement 2.

**Scan déterministe.** Le scan CLI direct des gabarits rend 0 trouvaille, mais **ce résultat n'est pas exploitable** : les gabarits référencent leur CSS en chemin absolu serveur (`/static/tokens.css`), que le détecteur ne peut pas résoudre depuis le disque — aucun CSS n'a été lu. Le scan URL natif a échoué faute de Puppeteer dans l'environnement. Deux substitutions ont été faites : miroir local des pages rendues (0 faute, 4 avis) et injection de `detect.js` dans la page via Playwright.

L'injection a fonctionné (aucun en-tête CSP), sur `/`, `/runs/{id}` et `/simulate` : **13, 11 et 9 anti-patterns**. Répartition réelle après tri :

- `gpt-thin-border-wide-shadow` (17 occurrences, tous panneaux et popovers) — **faux positif de règle**. Les valeurs viennent de `--shadow-panel` / `--shadow-raised` : décalage vertical de 10px et 18px avec spread négatif. La règle vise le halo diffus à décalage nul ; ici c'est exactement l'inverse, et c'est ce que le monde revendique.
- `em-dash-overuse` (568 sur `/`, 551 sur `/universe`) — **faux positif**. Vérifié : 3 cadratins dans le gabarit source contre 571 dans la page rendue. Ils viennent des données (libellés d'options `^AORD — AORD_AUS`, valeurs `<span class="na">—</span>`), pas de la copie.
- `#000` dans `style.css:677` et `:1065` — **faux positifs**. Ce sont des `mask-image` : dans un masque, le noir est un canal alpha, pas une couleur perçue.
- `line-length` (232 car. sur `.record-caption`, 206 et 192 car. sur des `.hint` de `/runs/{id}`) — **vrai positif**, mesure de lisibilité réelle.
- `all-caps-body` sur les `legend` et `.metric-label` (jusqu'à 41 caractères en capitales) — **vrai positif partiel** : c'est une convention assumée du monde, mais 41 caractères en capitales espacées se lisent mal.
- `font-size: 10px` sur `.info-icon` — **vrai positif**, en dessous du plus petit pas documenté (12px), et il coïncide avec le problème de cible tactile ci-dessous.
- `flat-type-hierarchy` : tailles effectives 10/12/13/14/17px, ratio 1,7:1 — **vrai positif** et il recoupe le constat de hiérarchie visuelle de la revue design.

**Ce que le détecteur et les mesures ont trouvé que la revue design avait manqué** : le bouton primaire échoue le contraste en thème sombre (détail en Problème 2). C'est la trouvaille la plus sérieuse des deux passes, et elle porte sur l'action principale du produit.

**Ce qui est propre, mesuré sur 20 contextes** (5 pages × desktop/mobile × clair/sombre) : débordement horizontal 0 partout, 0 erreur console et 0 exception, 0 champ de formulaire sans libellé, 0 saut de niveau de titre, aucune requête vers un hôte externe, poids maximal 273 Ko / 13 requêtes.

**Pas de superposition visuelle dans le navigateur de l'utilisateur** : l'injection a été faite dans une session Playwright hors écran, et le live-server a été arrêté. Il n'y a pas d'onglet à consulter.

## Overall Impression

Le monde visuel tient, et sa thèse est réellement implémentée là où elle compte : la page de verdict d'un run est excellente et n'a pas d'équivalent générique. Le problème n'est pas l'habillage, c'est que **la tâche principale du produit — configurer et lancer un run — est la surface la plus maltraitée**. Le formulaire vit dans une lucarne de 613 px pour 3042 px de contenu, son bouton de lancement n'apparaît sur aucune capture, 63 de ses champs n'ont pas d'indicateur de focus visible, et ce bouton échoue le contraste en thème sombre. Un produit dont la doctrine est « refuser d'imprimer une mesure non interprétable » traite l'engagement de plusieurs heures de calcul comme un clic sur un lien.

La plus grosse opportunité : sortir le formulaire de son scroll imbriqué et le hiérarchiser (défauts repliés, réglages exposés), ce qui règle d'un coup la charge cognitive, la visibilité de l'action primaire et l'échec de validation qui coupe le libellé du champ fautif.

## What's Working

1. **`metric(label, value, reliability)` avec troisième argument obligatoire, tenu au rendu.** Sur `/runs/{id}` : six blocs, six contreparties, dont cinq disent « non calculable » avec le motif. La contrainte est mécanique — signature Jinja — donc elle ne dépend pas de la discipline de celui qui écrit. Elle rend l'anti-pattern du chiffre nu littéralement impossible.
2. **Le pied de `/runs`** : « 18 run(s) affiché(s) · F1_dir = meilleur essai sur n, non déflaté du nombre d'essais · p-value DM brute, non corrigée du test multiple ». Une table qui énonce elle-même ce qu'on n'a pas le droit d'en conclure. C'est la posture du produit convertie en composant réutilisable.
3. **La robustesse mesurée.** 20 contextes, zéro débordement horizontal, zéro erreur console, zéro champ non étiqueté, zéro saut de titre, tout auto-hébergé. Sur `/universe` — 550 lignes, 28 663 px de haut — le mobile à 390 px ne déborde pas d'un pixel. Ce n'est pas rien et c'est rarement le cas.

## Priority Issues

### [P0] Le formulaire de run vit dans un scroll imbriqué ; l'action primaire n'est jamais visible

**Ce que c'est.** `.dash-settings .dash-panel-body` : `overflow-y: auto`, hauteur visible 613 px, contenu 3042 px. La grille est figée à `690px 409px`. Conséquence vérifiée sur capture pleine page : la page entière ne fait que 1374 px de haut et `#launch-btn` n'apparaît sur **aucune** capture — il faut scroller dans un panneau interne pour l'atteindre.

**Pourquoi ça nuit.** Double barre de défilement, molette ambiguë, `Ctrl+F` du navigateur inutilisable sur ce qui est hors du flux, action primaire invisible. Et lors d'un échec de validation, le navigateur scrolle le panneau interne en coupant le libellé du champ fautif : on voit un champ vide sans savoir lequel.

**Correctif.** Supprimer `overflow-y: auto` sur `.dash-panel-body` et la hauteur de rangée fixe ; laisser le formulaire couler dans la page. Puis replier par défaut les 7 fieldsets avancés en `<details>` portant chacun un résumé de son état (« SHAP · 5 familles · SMOTE seul »), et rendre `#launch-btn` collant en bas du panneau avec un rappel `cible · horizons · schéma`.

**Commande suggérée :** `/impeccable layout`

### [P0] L'accessibilité de la tâche principale échoue à deux endroits

**Ce que c'est.** Deux défauts distincts, tous deux sur le chemin critique, tous deux mesurés.

*Focus.* Les liens et 8 contrôles reçoivent `outline: 2px solid #1B4FD8`. Les 63 champs de `.run-form` reçoivent `outline: none` et à la place `box-shadow: 0 0 0 3px rgba(27,79,216,0.1)` — alpha 0,1, soit un anneau à ~1,15:1 contre le blanc, imperceptible. Le seul signal réel est le passage de la bordure de `#C3CBD8` à `#1B4FD8` sur 1px. Deux `<select>` de la même page ont deux traitements de focus différents.

*Contraste.* En thème sombre, `button#launch-btn.primary` et `button#sim-run-btn.primary` affichent du blanc sur `#74A0FF` : **2,56:1**, contre 4,5:1 requis. L'accent a été éclairci pour le fond sombre mais le texte du bouton est resté blanc.

**Pourquoi ça nuit.** Échec WCAG 2.4.7, 1.4.11 et 1.4.3 sur l'action principale du produit. Au clavier, on ne sait pas où on est dans un formulaire de 105 arrêts de tabulation. Et l'incohérence est pire que l'absence : elle laisse croire que le focus est visible jusqu'à ce qu'il disparaisse.

**Correctif.** Un seul sélecteur global sans exception : `:where(a,button,input,select,textarea,[tabindex]):focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }`, et supprimer l'anneau à 10 % qui prétend faire le travail. Pour le bouton, poser une couleur de texte sur accent qui tienne dans les deux thèmes (`--ink` sur `#74A0FF` donne ~7:1) plutôt qu'un blanc figé.

**Commande suggérée :** `/impeccable audit`

### [P1] Aucun garde-fou avant un run de plusieurs heures, et le seul raccourci détruit la saisie

**Ce que c'est.** `#launch-btn` soumet directement. Pas de confirmation, pas d'estimation de durée, pas de position en file, pas de récapitulatif des 65 valeurs. Symétriquement, `<select id="load" onchange="this.form.submit()">` recharge la page et écrase toute saisie en cours sans avertir.

**Pourquoi ça nuit.** C'est l'engagement le plus coûteux du produit — le contexte produit documente ~380 s rien que pour le pool de features et des runs lancés la nuit — et il est traité comme un lien. L'unique accélérateur de la page est en même temps son unique destructeur de travail.

**Correctif.** Un récapitulatif avant soumission : cible, horizons, régimes, schéma, nombre d'essais projeté, durée attendue, rang en file — puis confirmation. Sur `#load`, ne soumettre que si le formulaire est vierge, sinon demander confirmation, et remplacer `onchange=submit` par un bouton « Charger ».

**Commande suggérée :** `/impeccable harden`

### [P1] La bande d'enregistrement est vide à 99 %, muette au clavier, et les quatre autres canvas n'ont aucun nom accessible

**Ce que c'est.** 1392 px de plaque pour 18 runs concentrés sur ~90 minutes réelles, mais l'échelle couvre 4 jours : deux amas, survol actif sur 0,9 % de la surface. Le canvas porte un unique `aria-label` pour 18 points de données, et l'infobulle n'existe qu'au survol. Sur mobile, bande + légende consomment ~200 px des 844 (24 % du viewport) sur **toutes** les pages, et la légende s'étale sur 4 lignes sous une bande de 40 px. Par ailleurs `#preview-canvas`, `#sim-equity-canvas`, `#sim-drawdown-canvas` et `#sim-dist-canvas` n'ont **ni `role`, ni `aria-label`, ni `aria-hidden`** — quatre graphiques sans aucun texte de remplacement.

**Pourquoi ça nuit.** L'élément qui incarne la thèse est celui qui prouve visuellement qu'il n'y a rien à voir, et il taxe un quart du premier écran mobile de chaque page. Pour un lecteur d'écran, 18 runs valent un mot et les quatre graphiques valent zéro.

**Correctif.** Échelle temporelle adaptative cadrée sur l'étendue réelle des runs, avec regroupement des marques coïncidentes (« ×6 »). Canvas focusable avec navigation ←/→ entre marques et `aria-live` sur l'infobulle, doublé d'une table équivalente en `visually-hidden`. Sous 700 px, réduire la bande ou la replier derrière sa légende. Et donner à chacun des quatre autres canvas un résumé textuel de ce qu'il trace.

**Commande suggérée :** `/impeccable adapt`

### [P2] Charge cognitive critique : 7 échecs sur 8, et six points de décision au-delà de la limite

**Ce que c'est.** Seul le groupement visuel est tenu. Échouent : focus unique (5 objets co-égaux dans le premier viewport), paquets ≤ 4 (11 fieldsets, dont un à 14 cases), hiérarchie visuelle (les 4 titres de panneau sont identiques au pixel, aucun `h1`, et l'objet typographique le plus gros de la page est le « 18 » de la légende de bande — un chiffre sur lequel on n'agit jamais), une décision à la fois, mémoire de travail, divulgation progressive (zéro repli). Points de décision offrant plus de 4 options visibles : **6**, dont `#target_symbol` avec **550 options** dans un select natif sans recherche.

**Pourquoi ça nuit.** Le contexte produit dit que les 65 défauts encodent des leçons mesurées du projet VIX. Un formulaire qui présente les 65 au même niveau, sans distinguer ce qui est un réglage de ce qui est une leçon, a déjà perdu la leçon.

**Correctif.** Remplacer le select de 550 options par un champ à recherche incrémentale groupé par catégorie. Marquer visuellement tout champ modifié par rapport à son défaut. Replier l'avancé (voir Problème 1).

**Commande suggérée :** `/impeccable distill`

## Persona Red Flags

**Alex — expert pressé (le seul utilisateur réel aujourd'hui).** Il veut lancer `^GSPC/5j` en 20 secondes. Il doit ouvrir un select de 550 options sans recherche, puis scroller un panneau interne de 613 px sur 3042 en traversant 11 fieldsets qu'il ne veut pas toucher, pour atteindre un bouton qu'aucune capture ne montre. S'il vient de `/runs` avec l'idée « refaire `run_a` en changeant l'horizon », il n'a aucun moyen de repartir de cette config — il retape tout. Et s'il touche « Charger un exemple » après avoir saisi, il perd tout sans message.

**Sam — dépendant de l'accessibilité.** Il arrive sur la seule page du produit sans `<h1>` : sa navigation par titres saute directement aux quatre `h2`, dont aucun ne nomme la page. Il tabule : 63 contrôles sans anneau de focus perceptible, alors que les liens intercalés en ont un — il perd sa position exactement là où il en a besoin. En thème sombre, le bouton qu'il finit par atteindre est à 2,56:1. Les 40 boutons de glossaire s'annoncent « data_quality_enabled, bouton » — des identifiants de code — et mesurent 11×15 à 15×15 px. L'ouverture du popover ne déplace pas le focus dedans (vérifié : `document.activeElement` reste le bouton). Les quatre graphiques ne lui disent rien du tout.

**Casey — mobile, une main.** Sur `/`, **130 cibles tactiles sous 44×44 px**, dont 36 boutons de glossaire à 15×15 et 30 cases à cocher natives à 15×15. Sur `/universe`, **558**, dont des liens de symbole descendant à **8×16 px**. La bande d'enregistrement lui prend 24 % de l'écran sur chaque page pour une information qu'il ne peut pas survoler — le survol n'existe pas au doigt. Et l'action primaire est à ~2 400 px de scroll interne du premier champ.

## Minor Observations

- Le panneau **AVANCEMENT** affiche « Derniers runs » au repos : le titre décrit une chose, le contenu une autre.
- Les deux colonnes de movers sont des `<ul>` vides sans état vide — alors que le système de design l'exige explicitement pour toute surface au repos.
- `tokens.css` redéfinit `--ink`, `--ink-2`, `--ink-text` et `--ink-text-2` dans le bloc sombre, quatre lignes sous un commentaire du **même bloc** affirmant qu'ils ne le sont pas, et que le système de design en fait un interdit. Conséquence réelle : en sombre, `--ink #05080F`, `--ground #0A0F18` et `--surface #121A26` sont trois bleus-noirs voisins — la distinction « boîtier / papier », règle structurante du monde, s'effondre là où le clair la tient franchement.
- `PRODUCT.md` décrit encore l'ancien monde (« Sortie de solveur », JetBrains Mono, badges `[DONE]`) et interdit tout logo — deux affirmations désormais fausses.
- Le popover de glossaire s'ouvre par-dessus les champs voisins et masque précisément ceux que la définition sert à régler.
- `/universe` : 28 663 px de haut, 13 tables, aucun filtre, aucune recherche, aucun sommaire collant.
- Ratio de contraste minimum en thème clair sur toute l'app : 4,83:1. Ça tient, mais sans marge — `--text-3` est au plafond.
- `sparkline()` est déclaré et jamais appelé. Le documenter comme code mort ne le supprime pas.

## Questions to Consider

1. Si le panneau « Plus fortes variations » disparaissait ce soir, quelle décision deviendrait impossible ? Si la réponse est « aucune », pourquoi occupe-t-il un quart de l'accueil alors que l'action primaire n'est visible dans aucun viewport ?
2. La thèse dit « la station enregistre même quand personne ne regarde », et elle est illustrée par une bande vide à 99 %. Le produit a-t-il besoin d'un héliocorder, ou d'une **file d'attente lisible** — le seul état temporel qui change réellement le comportement (« puis-je lancer maintenant ou suis-je 3e ? ») et qui n'est visible nulle part avant soumission ?
3. Le produit refuse d'imprimer une mesure non interprétable. Pourquoi ne refuse-t-il pas symétriquement de **lancer** un run dont la configuration rend PBO, DSR et Diebold-Mariano structurellement non calculables ? Le refus est post-hoc alors qu'il pourrait être préventif, dans le formulaire, au moment où il coûte 0 seconde de calcul.
4. `/runs/{id}` a une barre de sections pour 4 blocs ; `/` en a 11 et n'en a pas. Quelle règle justifie de donner la carte au territoire le plus simple ?
