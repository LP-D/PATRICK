# ADR 0027 — Laboratoires généraux : stratégies de tout type, placements de tout portefeuille, lecture souple des tableaux

- Date : 2026-11-21
- Statut : codée (branche `feat/labos-v2`, à fusionner)
- Remplace en partie : ADR 0025 (pages `/strategies` et `/placements` dédiées à deux études)

## Contexte

L'ADR 0025 avait livré deux pages calquées sur des notebooks précis : « acheter avant, vendre après un événement » et straddle autour des
résultats d'un côté, port du notebook PEE de l'autre. Léon a demandé deux pages **générales** :

- un laboratoire où l'on choisit les instruments, les dates d'étude, les frais, et où l'on voit l'évolution du P&L, pour **n'importe quel
  type de stratégie** (les deux études d'origine en deviennent des cas particuliers) ;
- une simulation de placements pour **n'importe quel portefeuille** (assurance vie, PEE notamment) qui accepte une grande variété de
  fichiers Excel de valeurs, l'étude restant celle du notebook PEE.

## Décisions

### 1. Un lecteur de tableaux commun (`patrick/tabular/`)

- `reader` lit CSV (UTF-8 ou Windows-1252, séparateur choisi sur sa régularité), `.xlsx`, `.xls` (xlrd, ou page HTML déguisée en `.xls`
  comme en exportent les banques), `.ods`. Les lecteurs `.xls`, HTML et `.ods` sont **facultatifs** (extra `imports` du `pyproject`) : la CI
  installe des versions figées, on n'y ajoute pas de dépendance ; les tests correspondants sont sautés si le lecteur manque.
- `parse` lit les nombres (« 1 234,56 € », « (3,2) », « 1'234.5 », séparateur décimal décidé pour la colonne entière) et les dates (série
  Excel, jour d'abord sauf preuve contraire dans la colonne, « déc. 2024 », « T4 2024 », année seule), et vérifie la clé des ISIN.
- `detect` trouve les séries dans n'importe quelle mise en page (tableau large, blocs côte à côte, format long, tableau transposé, titre
  au-dessus, ordre anti-chronologique), devine ce que mesurent les valeurs (VL/cours, base 100, performances périodiques ou cumulées en % ou
  en décimal, taux annuels) et la fréquence, avec une **confiance et des notes** affichées. Les valeurs brutes sont gardées : changer le type
  recalcule l'indice sans réimporter. Un taux annuel est capitalisé mois par mois et ne dépasse jamais le mois courant.

### 2. Stratégies : un moteur général, les modèles ne sont que des règles

- Règles « opérande opérateur opérande » regroupées en ET / OU ; 22 indicateurs causaux (moyennes, momentum, RSI, Bollinger, Donchian,
  volatilité, z-score, calendrier, distance à un événement, force relative…), chacun applicable à un autre instrument (filtre de régime
  « VIX < 25 »).
- Moteur en trois étages : éligibilité (machine à états, relue aux dates de décision), sélection par classement (N meilleurs, M pires),
  sorties de risque quotidiennes (stop, objectif, stop suiveur, durée) avec ré-entrée seulement sur un signal frais. Pondérations égales,
  inverse de la volatilité, cible par ligne, poids fixes, par poche ou investi ; levier plafonné ; cible de volatilité du portefeuille.
- Exécution à la clôture ou à l'ouverture, **au moins une séance après le signal** par défaut ; frais = commission avec minimum, frais
  fixes, glissement, emprunt de titres, rémunération des liquidités, coût du levier. Les frais sont prélevés sur les liquidités.
- 19 modèles (achat-conservation, allocation fixe, inverse de la volatilité, cible de volatilité, croisement de moyennes, filtre de Faber,
  momentum absolu, Donchian, rotation momentum, double momentum, faible volatilité, RSI, Bollinger, tournant du mois, effet Halloween,
  événements, paire, filtre de régime, règles libres) **compilés en règles** que la page affiche et laisse modifier. La paire est traitée
  comme le ratio A/B ; les événements viennent des résultats Yahoo, d'un fichier ou d'une liste de dates.
- Robustesse : coupure hors échantillon choisie avant de lancer, comparaison au hasard (permutation circulaire de l'exposition détenue,
  instrument par instrument, Sharpe brut), frais multipliés (seuil de rentabilité), bootstrap stationnaire, Sharpe probabiliste et déflaté
  (nombre de réglages essayés), grille de sensibilité et **walk-forward de la grille** (réglage choisi chaque année sur le passé seul,
  à partir des rendements déjà calculés de chaque réglage, tous causaux). Le test du hasard n'est pas joué pour une allocation toujours
  investie (rien à prouver sur le calendrier). Verdict : robuste / fragile / pas d'avantage démontré, épreuve par épreuve.
- Historique des études sur disque (40 plus récentes, épinglées jamais effacées), comparaison superposée, export / import de la stratégie
  en JSON.

### 3. Placements : enveloppes, épargne réelle, contraintes

- Enveloppes PEE, PERCO, assurance vie, PER, PEA, compte-titres, aucune : un jeu de paramètres unique (frais d'entrée et de gestion,
  abondement plafonné net de CSG, prélèvements annuels sur le fonds en euros, prélèvements et impôt de sortie avant / après un seuil de
  durée, abattement, déductibilité du PER). **Valeurs par défaut 2026, toutes modifiables** : prélèvements sociaux 18,6 % (hausse de la
  CSG par la LFSS 2026, flat tax 31,4 %), 17,2 % pour l'assurance vie (exclue de la hausse), plafond d'abondement PEE 8 % du PASS 2026
  (48 060 €) = 3 844,80 €. Les sources consultées divergeaient sur l'épargne salariale et le PEA : le taux est un paramètre.
- Versements initial, mensuels, annuels (progression annuelle), objectif ; avoirs actuels par support ; bornes de poids par support et
  contraintes par catégorie (« fonds en euros au moins 30 % »). Optimiseurs sous contraintes (point de départ rendu admissible, solution
  admissible gardée même si SLSQP s'arrête à la limite d'itérations), nouveaux objectifs parité de risque et 1/N. Pour les objectifs
  « 100 % risqués », une part minimale imposée au monétaire est mise de côté et le reste optimisé.
- Pour chaque allocation : épargne projetée (bootstrap par blocs de 6 mois tirés ensemble pour tous les supports, hypothèse historique ou
  prudente), capital brut et net, frais, manque à gagner dû aux frais, impôts, probabilité d'atteindre l'objectif ou de perdre, TRI ;
  épargne **rejouée sur l'histoire** (TRI réel, rééquilibrage annuel) ; contributions au risque. Frontière efficiente sous contraintes avec
  l'allocation actuelle placée dessus ; la même épargne comparée d'une enveloppe à l'autre (indicatif : éligibilité et plafonds non
  contrôlés).

## Conséquences

- Les modules `strategylab/core.py`, `straddle.py` et `prices.py` disparaissent ; le straddle (primes Black-Scholes reconstruites) n'est plus
  proposé. L'étude IPO se refait avec le modèle « Autour d'un événement » et un fichier de cours.
- Les anciens résultats des deux pages ne se relisent pas (format différent) ; les jeux de données de placements existants restent
  lisibles (profil par défaut, type « VL / cours », pas de valeurs brutes : la correction de type demande de réimporter).
- Une analyse de placements complète dure 1 à 3 minutes (projections et rejeu pour chaque allocation) ; une étude de stratégie quelques
  secondes, une minute avec une grille de 100 réglages.
- Pas encore fait : fiscalité des plus-values réalisées dans le laboratoire (il est avant impôt), plafonds de versement des enveloppes,
  tris transversaux par facteur sur un univers d'actions (notebook STRAT VOLUME).
