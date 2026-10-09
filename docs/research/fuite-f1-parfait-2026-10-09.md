# F1 de 1,00 : une fuite temporelle, trouvée et corrigée (2026-10-09)

## Constat

Sur 4 085 essais évalués sur holdout, le meilleur F1 directionnel honnête est **0,54**. Douze essais dépassaient 0,85,
jusqu'à **1,00**. Tous appartenaient à des cibles précises, toutes à l'horizon 1 jour :

| Cible | F1_dir holdout | Série de marché qui reproduit le label |
|---|---|---|
| SP500 (FRED) | 1,000 | `^GSPC` (corrélation avec le label : **1,000**) |
| DGS10, DGS30, DGS5, DGS7, DGS20, DGS3, DGS2, DGS1, DTB6 (FRED) | 0,85 à 0,996 | `^TNX`, `^TYX`, `^FVX`, `^IRX` (0,76 à 0,97) |
| VIXCLS (FRED) | 0,990 | `^VIX` (0,996) |
| NFCI (FRED) | 0,940 | séries de taux (0,49) et vintage révisé |
| EURUSD=X (Yahoo) | 0,958 | `DX-Y.NYB` (rang -0,55) |

Les features que le modèle retient le confirment : `IDX_GSPC_ret_1d` (fréquence de sélection 1,0) pour SP500,
`IDX_VIX_ret_1d` pour VIXCLS, `IDX_TNX_*`/`IDX_FVX_*` pour les taux, `DX_Y.NYB_ret_1d` pour EURUSD=X.

## Cause

Le label d'une ligne est le mouvement entre les deux prochaines valeurs de la cible.

1. **Cibles FRED.** F01 (`data/publication_lag.py`) place chaque observation à sa date de *publication* (J+1 pour un taux
   quotidien) : le label de la ligne J est donc le mouvement **du jour J lui-même**. Les séries cotées (`^GSPC`, `^TNX`...)
   étaient jointes à leur date de cotation, sans retard (`session_lag_days` renvoie 0 pour une cible non-yfinance). La
   feature « rendement de `^GSPC` en J » reproduisait le label au signe près : le modèle « prédisait » un chiffre déjà
   observé.
2. **EURUSD=X.** L'horodatage de `DX-Y.NYB` est décalé : sa barre datée J contient le mouvement que `EURUSD=X` date J+1
   (corrélation de rang -0,40 à -0,55 avec le rendement futur). Les deux séries étaient classées « fx » (même heure de clôture)
   donc sans retard.

Ce n'est pas un défaut de modèle ni de validation : le schéma walk-forward, la purge et l'embargo étaient corrects. La fuite
vient de l'alignement des dates **entre séries**.

## Correction

- `data/alignment.py` (nouveau) : une garde en deux étages, décidée **une fois par run** et écrite dans la config
  (`objective.alignment`), puis rejouée à l'identique par la prédiction live, l'explication et la reprise.
  1. Cible FRED : toute série cotée est retardée du délai de publication de la cible
     (`publication_lag.publication_delay_bars` : 1 barre pour un taux, 5 pour un hebdomadaire, 7 pour le pétrole EIA, 14 pour
     un CPI...).
  2. Audit empirique : toute série cotée dont la variation du jour a une corrélation de rang ≥ 0,30 avec la variation future de
     la cible est retardée d'une barre, puis retirée si cela ne suffit pas. Calculé sur les lignes **avant** le holdout.
  Les runs antérieurs (`alignment.version == 0`) gardent exactement leurs entrées d'origine, et leur empreinte de config.
- `validation/suspicion.py` (nouveau) : un F1_dir ≥ 0,80 ou une AUC ≥ 0,85 est une anomalie de données. Un tel challenger ne
  prend jamais le titre de champion ; un champion suspect est remplacé par tout challenger sain (`pipeline/champion_duel.py`).
- Page **Qualité des données** : les quinze runs concernés y sont listés avec leur cause.

Vérifié sur les données réelles du data lake : après correction, la corrélation résiduelle entre le label et toute série de
marché passe de 1,000 à moins de 0,1 pour SP500, VIXCLS, DGS10 et NFCI ; pour EURUSD=X, `DX-Y.NYB` est détecté et retardé
(résidu maximal 0,20, sous le seuil de 0,30).

## À faire côté utilisateur

Relancer les cibles concernées : les anciens résultats (SP500, DGS*, VIXCLS, NFCI, DTB6, EURUSD=X) restent en base, marqués
suspects, mais ne servent plus de référence. Les snapshots de données ne sont pas à refaire : le décalage s'applique après
chargement.

## Limites connues

- NFCI et STLFSI4 sont **révisés rétroactivement** à chaque publication (le dernier millésime lisse l'historique avec des
  données qui n'existaient pas encore). Le retard de publication ne corrige pas cela ; seule la voie ALFRED (clé API FRED,
  `universe.fred_point_in_time = "alfred"`) le fait.
- Pour une série publiée mensuellement ou trimestriellement, le retard de publication retire au modèle l'information de
  marché de plusieurs semaines : c'est le prix d'une cible qui reste « la prochaine valeur publiée ».
