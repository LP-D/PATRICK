# Cadrage — deep learning et modèles de diffusion

Statut : cadrage (aucun modèle DL n'est câblé dans le pipeline). Date : 2026-09-25.

## 1. Le protocole actuel suffit-il pour du DL ?

**Non, pas tel quel.** Il est nécessaire mais pas suffisant : cinq angles
morts propres au DL, chacun avec sa règle.

| Risque propre au DL | Pourquoi le protocole ML ne le couvre pas | Règle à ajouter |
|---|---|---|
| **Early stopping sur le fold de test** | Les GBM n'en ont pas besoin ; un réseau oui. Arrêter sur la perte de test = sélection sur le test. | Validation d'arrêt = bloc **interne** purgé (`optuna_runner.inner_cv_gap`), jamais le fold de test ni le holdout. |
| **Fenêtres d'entrée (lookback)** | Une séquence de `L` barres qui chevauche la coupe transporte le train dans le test. | Embargo ≥ max(horizon, L) ; normalisation ajustée sur le train seul. |
| **Variance de graine** | Un GBM à graine fixe est déterministe ; un réseau varie fortement d'une initialisation à l'autre (et sur GPU, même à graine fixe). | Chaque configuration est évaluée sur ≥ 5 graines ; on rapporte la médiane et l'écart ; **chaque (config, graine) entraînée compte dans le registre d'essais (F03)**. |
| **Espace d'hyperparamètres énorme** | Le DSR déflate par N essais ; un balayage DL non déclaré fait exploser N silencieusement. | Budget d'essais déclaré avant la recherche ; tout essai enregistré via `trial_registry`. |
| **Taille d'échantillon effective** | ~6 000 barres quotidiennes, labels chevauchants : n_eff ≈ n / h (unicité, Phase 6.2). Un réseau de 10⁵ paramètres sur n_eff ~ 1 200 (h = 5) est sur-paramétré. | Plafond de capacité relatif à `effective_n_train` ; régularisation et petites architectures d'abord. |

Tout le reste s'applique sans changement : walk-forward, holdout terminal
jamais utilisé pour choisir, DM-HLN contre la baseline de classe, famille BH
de toutes les cibles, PBO sur blocs/chemins, simulation par segment.

## 2. Modèles de diffusion : pour quoi faire ?

Les modèles de diffusion pour séries temporelles (TimeGrad, CSDI, TSDiff)
apprennent une **distribution conditionnelle** de trajectoires futures, pas
une classe. Deux usages défendables ici, un à éviter :

1. **Prévision probabiliste** — quantiles/intervalles de rendement à
   l'horizon h. Évaluation : CRPS et calibration des quantiles (PIT), à
   comparer à des bases probabilistes bon marché : régression quantile GBM,
   NGBoost, et la **prédiction conforme** (chantier dédié, bien moins
   coûteuse). Si la diffusion ne bat pas le conforme sur CRPS en
   walk-forward, elle n'entre pas.
2. **Générateur de scénarios de stress** pour le patrimoine (queue de
   distribution jointe multi-actifs), évalué sur la couverture des queues
   observées (VaR/ES backtestés, test de Kupiec/Christoffersen), pas sur une
   F1.
3. **À éviter** : les utiliser comme classifieur directionnel 4 classes. Le
   coût (entraînement, variance de graine, cf. §1) est sans rapport avec le
   gain attendu sur un signal dont le F1_dir de référence est ~0,60.

## 3. Ordre recommandé

1. Calibration isotonic/Platt dans le walk-forward (prérequis BL v2).
2. Prédiction conforme (intervalles à couverture garantie, sans DL).
3. Bases probabilistes (quantile GBM / NGBoost) + métriques CRPS/PIT.
4. Seulement ensuite : DL séquentiel léger (TCN/GRU) avec les règles du §1,
   puis diffusion pour les usages 1–2.

## 4. Limites de ce cadrage

Les ordres de grandeur (n_eff, taille de réseau) sont indicatifs ; la
variance de graine doit être mesurée sur les données du projet avant de
fixer le nombre de graines. Je n'ai pas vérifié les implémentations
récentes des modèles cités sur ce jeu de données.
