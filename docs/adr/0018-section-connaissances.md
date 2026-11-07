# ADR 0018 — Section Connaissances : cours intégrés à l'application et dictionnaire du quant

Date : 2026-11-07. Statut : appliquée (pages `/connaissances`, `/connaissances/cours[/{slug}]`, `/connaissances/dictionnaire`, API `/api/dictionary/search`, paquet `patrick/knowledge/`). Demande de Léon : intégrer les cours produits dans l'application, créer une section pour les connaissances du quant « des bases de la finance au plus complexe » et un dictionnaire « hyper complet », en complétant ou réutilisant le lexique existant.

## Contexte

Deux cours existaient en Markdown dans `docs/cours/` (événements de résultats, économétrie d'une série), lisibles seulement dans le dépôt. L'application avait un lexique compact (211 notions, bulles « ? » et page `/vocabulary`), tourné vers ses propres réglages et méthodes ; rien pour le vocabulaire général de la finance ni pour apprendre dans l'ordre.

## Décisions

1. **Une 6ᵉ catégorie de navigation, `connaissances`** (amendement de `design-system/patrick/MASTER.md`) : Parcours, Cours, Dictionnaire. Contenu statique : aucun appel base ni réseau.
2. **Les cours restent des fichiers Markdown de `docs/cours/`** (source unique, lisibles hors de l'application). L'application les rend à la volée et garde le résultat tant que le fichier ne change pas ; si le dossier est absent (installation sans le dépôt), la page le dit au lieu de planter. Ajouter un cours = déposer le fichier et ajouter une ligne au registre `knowledge/courses.py`.
3. **Pas de dépendance nouvelle** (le fichier de contraintes de la CI et le golden master ne bougent pas) : `latex_lite` convertit le sous-ensemble de LaTeX utilisé par les cours en **MathML**, affiché nativement par les navigateurs ; `markdown_lite` convertit le sous-ensemble de Markdown utilisé. Tout texte est échappé ; seules les balises `<sup>` et `<sub>` sont conservées ; un lien vers un fichier du dépôt devient du code, jamais un lien mort ; `javascript:` n'est jamais un lien.
4. **Le dictionnaire réunit le lexique existant et 538 notions nouvelles** (749 au total, dans les deux langues). Chaque notion a un thème (17), un niveau (1 bases, 2 intermédiaire, 3 avancé), un libellé et une définition FR/EN, des renvois (réciproques), éventuellement une formule typographiée, des synonymes et un lien vers le chapitre de cours qui la détaille. Les 211 notions existantes sont reprises telles quelles (clés et textes inchangés : les bulles « ? » et `/vocabulary` fonctionnent comme avant) et classées par thème et niveau ; les bulles pointent désormais vers le dictionnaire.
5. **Écrit par modules thématiques** (`patrick/knowledge/dict_*.py`, un par thème, helper `d(...)`) : ajouter une notion = ajouter une ligne. `dictionary.check()` valide l'ensemble (clés uniques, renvois et ancres de cours existants, formules convertibles, libellés jamais répétés) ; un test l'exécute.
6. **Le cours d'économétrie garde ses formules en blocs de code** (texte lisible) ; celles du cours des résultats sont en LaTeX et typographiées. Les formules du cours d'économétrie sont reprises, typographiées, dans les notions du dictionnaire.

## Conséquences

- Nouvelles routes : `/connaissances`, `/connaissances/cours`, `/connaissances/cours/{slug}`, `/connaissances/dictionnaire`, `/api/dictionary/search`. Le registre de navigation compte six catégories (le test des catégories est mis à jour).
- La page du dictionnaire pèse environ 1 Mo (750 notions rendues d'avance, filtrées côté navigateur) ; elle est construite une fois par langue.
- Limites connues : les cours sont en français seulement (l'interface en anglais l'indique) ; le dictionnaire n'est pas encore branché sur la palette de commandes (l'API de recherche est prête) ; les notions ajoutées sont écrites à la main et n'ont pas été relues par un spécialiste de chaque thème.
