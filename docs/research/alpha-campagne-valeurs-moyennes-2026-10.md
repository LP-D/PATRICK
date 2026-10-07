# Campagne alpha sur dix valeurs moyennes françaises (protocole fixé avant les runs)

Écrit le 2026-10-07, **avant** le premier run de la campagne. Rien de ce document ne se modifie après coup : un écart au
protocole se consigne dans une section « Écarts » en fin de fichier, jamais en réécrivant ce qui précède.

## Question

La cible alpha (rendement excédentaire `actif − β × benchmark`, β point-in-time) permet-elle à ce pipeline de prédire la
surperformance d'une valeur moyenne française face à son indice ? Deux runs préliminaires (LVMH, Sopra Steria) n'ont montré
aucun avantage hors échantillon ; un second a même un signal de validation croisée (+4 à +5 points sur la meilleure
baseline) qui ne survit pas au holdout. Deux runs ne permettent pas de conclure sur l'approche : on teste dix valeurs de plus.

## Hypothèse nulle

H0 : sur ces valeurs, le modèle final ne fait pas mieux, hors échantillon, que la règle triviale « l'alpha des `h` derniers
jours se répète » (baseline de persistance de l'alpha), et ne gagne pas d'argent net de coûts.

## Univers (figé)

Dix valeurs, non détenues dans le patrimoine, historique complet depuis 2008, données vérifiées (aucun trou de plus de 7
jours, aucun cours nul) : `NEX.PA`, `RXL.PA`, `IPS.PA`, `SK.PA`, `NK.PA`, `RUI.PA`, `TRI.PA`, `VIRP.PA`, `RCO.PA`, `ERF.PA`.
Avec `MC.PA` et `SOP.PA` déjà exécutés, la famille compte **m = 12 cibles**. Aucune valeur n'est remplacée ni retirée :
un run qui échoue (données, benchmark écarté par le contrôle qualité) compte comme p = 1.

## Protocole (identique pour chaque valeur)

Configuration de `configs/examples/mc_pa_alpha.yaml`, seule la cible, le nom et le dossier de sortie changent : benchmark
automatique (`^STOXX50E`, sans décalage de séance), horizons 5 et 20 jours, 4 plis walk-forward avec purge, SHAP,
RandomForest / XGBoost / LightGBM, 20 essais Optuna, graine 42, holdout terminal d'environ 325 séances, jamais utilisé pour
choisir. Le modèle final est celui que le pipeline retient (aucun choix manuel).

## Critère de découverte (par valeur)

Une valeur est une **découverte** si et seulement si les deux conditions sont vraies :

1. **Test statistique** : sur le holdout du modèle final, le test de Diebold-Mariano (correction HLN) contre la baseline de
   persistance de l'alpha est **unilatéral en faveur du modèle** (`dm_stat < 0`, p bilatéral ÷ 2), ajusté de Šidák sur les
   runs de la valeur, puis significatif après **Benjamini-Hochberg à q = 0,10** sur la famille alpha de 12 cibles
   (`fdr_across_targets(family="alpha", one_sided=True)`).
2. **Valeur économique** : Sharpe **net** de la simulation couverte sur ce holdout **> 0**, avec 10 points de base par
   jambe (paire longue actif / courte β × benchmark, retard d'exécution d'une séance, seuil par défaut 0,55).

Aucune simulation n'est enregistrée au registre d'essais : la simulation de critère est une mesure unique, aux paramètres
par défaut figés ci-dessus.

## Lecture du résultat

- **0 découverte** : pas d'évidence d'alpha exploitable avec ce protocole sur ces valeurs.
- **1 découverte ou plus** : candidates à une confirmation sur une autre période, jamais à un déploiement. Les holdouts des
  douze valeurs couvrent les mêmes dates : les tests sont positivement corrélés (le BH reste valide sous dépendance positive),
  mais une année de marché favorable à une famille de valeurs peut produire plusieurs « découvertes » liées.
- Le nombre de découvertes s'interprète contre le hasard : BH à q = 0,10 garantit que la part attendue de fausses découvertes
  parmi les découvertes est au plus 10 %, et, si H0 est vraie pour les douze valeurs, que la probabilité d'obtenir au moins
  une découverte est au plus 10 %. Une découverte isolée reste donc un résultat à confirmer, pas une preuve.

## Exécution

```
patrick research alpha-campaign-run --symbols NEX.PA,RXL.PA,IPS.PA,SK.PA,NK.PA,RUI.PA,TRI.PA,VIRP.PA,RCO.PA,ERF.PA
patrick research alpha-campaign-report --symbols MC.PA,SOP.PA,NEX.PA,RXL.PA,IPS.PA,SK.PA,NK.PA,RUI.PA,TRI.PA,VIRP.PA,RCO.PA,ERF.PA
```

Un run après l'autre, chacun dans son processus ; un échec n'arrête pas la campagne ; relancer saute ce qui est terminé.

## Rapport

`patrick research alpha-campaign report` produit le tableau (valeur, F1 holdout, DM, p brut, p ajusté, Sharpe net,
découverte) et le verdict. Sortie conservée dans `docs/research/` avec la date.

## Écarts

(aucun à ce jour)
