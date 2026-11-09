# Décisions d'architecture (ADR)

Une décision qui change la façon de travailler ou ce que les résultats veulent dire s'écrit ici, une fois, avec son
contexte : pour qu'elle ne vive pas seulement dans la mémoire de quelqu'un. Format court : **Contexte**, **Décision**,
**Conséquences**. Une décision remplacée n'est pas effacée : on la marque « remplacée par » et on écrit la suivante.

| N° | Décision | Date | Statut |
|---|---|---|---|
| [0001](0001-lever-linterdiction-du-deep-learning.md) | Lever l'interdiction du deep learning et du stacking | 2026-09-25 | Acceptée |
| [0002](0002-mise-a-jour-sur-une-reference-validee.md) | Les PC suivent une branche `stable`, validée par la CI | 2026-10-20 | Acceptée (à fusionner) |
| [0003](0003-diebold-mariano-sens-unique-et-testabilite.md) | Diebold-Mariano : sens « meilleur » dans la famille BH, et refus sous 15 blocs | 2026-10-19 | Acceptée |
| [0004](0004-cpcv-interactions-par-combinaison.md) | CPCV : formules d'interaction découvertes par combinaison | 2026-10-19 | Acceptée |
| [0005](0005-registre-d-acces-au-holdout.md) | Registre d'accès au holdout terminal | 2026-10-19 | Acceptée |
| [0006](0006-regle-une-erreur-type-par-defaut.md) | Règle de parcimonie « une erreur-type » activée par défaut | 2026-10-20 | Acceptée |
| [0007](0007-alignement-des-devises-et-audit-statistique.md) | Alignement des cibles de change et audit statistique des fuites de date | 2026-10-28 | Acceptée |
| [0008](0008-methode-d-evaluation-2.md) | Méthode d'évaluation 2 : DM sur la direction, jours plats dans l'évaluation, régimes par volatilité, SHAP récent, placebo | 2026-10-28 | Acceptée |
| [0009](0009-stockage-et-entretien-de-la-base.md) | Stockage : archivage des prédictions du scan, caches comprimés et évincés, index | 2026-10-29 | Acceptée |
| [0010](0010-budget-d-essais-dm-continu-et-interface.md) | Budget d'essais, DM sur le Brier, runs sans évaluation en échec, interface (onglets, tableaux, À faire) | 2026-10-29 | Acceptée |
| [0011](0011-methode-3-interface-et-audit-des-tests.md) | Méthode 3 (niveaux bruts, calibration), interface, audit des tests | 2026-10-30 | Acceptée (méthode 3 non activée) |
| [0012](0012-actions-dans-leur-groupe-et-features-de-contexte.md) | Les actions dans leur vrai groupe, features de contexte de marché (zone euro) | 2026-10-30 | Acceptée |
| [0013](0013-efficacite-du-f1-macro-decision-selection-signal.md) | Efficacité du F1 : cibles macro retirées, décision de direction causale, critère AUC, signal regroupé, placebo de l'Asie | 2026-10-31 | Acceptée |
| [0014](0014-feuille-de-route-2026-11-02.md) | Feuille de route du 2026-11-02 : duel sur l'AUC, placebo toutes classes, déflation par classes, dimensionnement proportionnel, retraits, sauvegardes | 2026-11-02 | Acceptée |
| [0015](0015-journal-fusionne-bandit-carry.md) | Journal de prédictions fusionné entre PC, dimensionnement appris et carry de change mesurés | 2026-11-02 | Acceptée |
| [0016](0016-evenements-de-resultats.md) | Événements de résultats : newsletter, event study, 54 cartes d'études, données gratuites seulement | 2026-11-03 | Acceptée |
| [0017](0017-page-econometrie.md) | Page Économétrie : une série à la fois, descriptif contre prévision, aucun modèle couronné | 2026-11-03 | Acceptée |
| [0018](0018-section-connaissances.md) | Section Connaissances : cours intégrés à l'application et dictionnaire du quant (749 notions) | 2026-11-07 | Acceptée |
| [0019](0019-design-v4-terminal.md) | Design v4 « Terminal » : densité de Bloomberg, propreté d'Apple (noir, orange terminal, échelles, palette de graphiques validée) | 2026-11-09 | Acceptée |
