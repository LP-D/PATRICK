# ADR 0023 — Mouvement de l'interface : dix-huit règles

Date : 2026-11-16. Statut : codée et testée sur la branche `feat/mouvements-interface`. Demande de Léon : appliquer une liste de dix-huit règles de mouvement (ease-out pour les entrées, menus en 150-250 ms, lignes décalées de 30 ms, boutons à 0,97, étirement de 12 %, mouvements en courbe, pulsation de réussite, ease-in-out pour bouger, popovers à 0,95, entrée depuis et sortie vers le déclencheur, pas de ressort, sorties 20 % plus courtes, ancien et nouvel état mêlés, poids aux révélations, fondu d'icônes avec flou, élastique aux limites, identifiant de mise en page partagé), et revoir la place des onglets.

## Contexte

Le design v4 « Terminal » (ADR 0019) avait des durées éparses (100 à 300 ms en dur), une seule courbe (`--ease-out`) pour tout, des sorties instantanées (`display: none`) et aucune réponse à l'appui. Les barres d'onglets passaient sur deux rangées sous un même filet quand la largeur manquait, et celles d'/exploration et d'/econometrie disparaissaient en haut de page dès qu'on lisait un panneau long.

PATRICK est un outil de travail utilisé tous les jours : la règle de fréquence (Emil Kowalski) prime. Ce qui est déclenché des centaines de fois (survol, frappe, tri) reste instantané ; ce qui l'est quelques fois par session (menu, popover, changement d'onglet) reçoit un mouvement court ; ce qui est rare (thème) peut se permettre plus.

## Décision

1. **Une seule source** : jetons de `:root` dans `patrick.css` (`--ease-enter/exit/move`, `--dur-*` et leurs `-out` à 80 %, `--stagger`, `--press-scale`, `--pop-scale`, `--stretch`). Aucune courbe ne dépasse sa cible (test).
2. **CSS d'abord.** Entrées et sorties des couches flottantes par `@starting-style` et `transition-behavior: allow-discrete` sur `display` / `overlay` : l'élément reste peint pendant sa sortie, sans JavaScript ni changement des scripts qui l'ouvrent (`hidden`, `.hidden`, `showModal`).
3. **`static/motion.js`** pour ce que le CSS ne sait pas faire : origine de la transformation au centre du déclencheur, modalité clavier/pointeur, trait glissant des onglets d'analyse (animation à trois images clés, étirée à mi-course), révélations décalées, élastique au bout du défilement, pulsation de réussite (`window.patrickMotion.success`). Un seul `MutationObserver` sur `hidden`, `class`, `open`, `aria-selected`.
4. **Identifiant partagé entre pages** : transitions de vue entre documents (`@view-transition { navigation: auto; }`). Le repère de la page courante (`.nav-ink`, barre latérale) et le trait de l'onglet d'un run (`.tab-ink`) sont des éléments à part, présents dans le gabarit (pas injectés par script, pour exister dès le premier rendu) ; le navigateur les fait glisser de l'ancienne place à la nouvelle. Un nom de transition sur un pseudo-élément n'est pas pris en charge : d'où les `<span>`.
5. **Garde-fous** : `prefers-reduced-motion` coupe tout (transitions de page comprises, activées seulement sous `no-preference`) ; un geste au clavier n'anime rien (`<html data-input="keyboard">`, posé dès la touche : `focus()` force le calcul du style avant qu'un observateur ne passe) ; seules `opacity`, `transform`/`scale`/`translate`, `filter` et `clip-path` sont animées, sauf la colonne latérale repliée (déjà animée avant). Le bandeau défilant garde sa propre vie pendant une transition de page.
6. **Onglets** : une ligne qui défile (filet en ombre intérieure, que le défilement ne rogne pas), bords estompés et onglet courant gardé dans le champ ; `.exp-tabs` collés sous la barre du haut. Les onglets d'un run ne collent pas (l'index des sections est déjà collé à cette hauteur) ; les pastilles de filtre gardent leur aspect (pastilles indépendantes, test existant).

## Conséquences

- Navigateur visé : Chrome / Edge récents (transitions de vue entre documents, `@starting-style`, `allow-discrete`, propriété enregistrée `--elastic`). Ailleurs, tout s'affiche sans animation : rien ne dépend du mouvement.
- Un nouveau popover ou menu reprend le motif (`--origin-x/y`, `--pop-scale`, `-out` à 80 %) et s'ajoute à la liste `POPS` de motion.js ; une nouvelle barre d'onglets entre dans `initStrip`.
- `MASTER.md` § Mouvement tient le tableau des règles ; `tests/test_ui_motion.py` fige jetons et contrats.
- Non vérifié en conditions réelles depuis la session : la vue intégrée de l'app ne produit pas d'images hors écran, les durées ont été contrôlées par l'état des animations (`getAnimations`, `currentTime`), pas à l'œil.
