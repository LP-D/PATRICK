# Analyse des runs de reinforcement learning (2026-11-16)

Demande de Léon : « quasiment aucune stratégie ne fonctionne ». Base locale lue en lecture seule (`job`, `rl_oos.csv` de chaque run).
Scripts : `rl_analysis.py` et `rl_oos_analysis.py` (scratchpad de la session). Refonte qui en découle : [ADR 0022](../adr/0022-refonte-du-moteur-rl.md).

Vocabulaire : **Sharpe** = rendement moyen / volatilité, annualisé. **Acheter-garder** (BH) = rester investi tout le temps.
**Rotation** = part du capital échangée par an (une rotation de 66 = le capital renouvelé 66 fois). **Brut** = avant frais.
**Jambe longue / courte** = ce que rapportent les jours où l'agent est acheteur / vendeur à découvert.

## 1. Ce qui a été lancé

456 runs terminés (11/10 → 15/11), 422 cibles, presque une par cible. **Une seule configuration** pour tous : PPO, trois positions
(−1, 0, +1), vente à découvert permise, levier 1, récompense log-croissance, 7 points de base de frais, une décision par jour.
Variations marginales : 25 runs « mémoire » du 15/11 (80 000 pas, 20 lignes empilées, 3 graines), 11 runs à 10 000 pas.

## 2. Résultat global

| | RL | Acheter-garder | Momentum 20 j |
|---|---|---|---|
| Sharpe médian | 0,12 | 0,46 | −0,22 |
| Part des runs où le RL fait mieux | — | 19,5 % | 76,5 % |

- 32 runs battent BH à 5 % (bootstrap unilatéral). **26 sont des artefacts** : 15 devises, 6 indices d'Asie, 5 indices de volatilité.
- **Périmètre propre** (actions US et Europe, futures, crypto ; 413 runs) : **5 runs significatifs, contre ~21 attendus par pur hasard**. Le RL
  y bat BH dans 13 % des runs. Ce n'est pas du bruit autour de zéro : l'agent fait **systématiquement moins bien** que rester investi.
- Le momentum 20 j est une référence trop facile (Sharpe médian négatif) : « bat le momentum » ne voulait rien dire.

## 3. Pourquoi ça échoue : la décomposition

Sur le périmètre propre (422 séries hors échantillon, médianes) :

| Composante | Par an |
|---|---|
| Rendement brut de l'agent | +7,1 % |
| Frais | −4,6 % |
| Rendement de l'actif (BH) | +12,5 % |
| Jambe longue | +8,1 % |
| Jambe courte | −1,6 % |
| Rotation | 66 fois le capital |
| Position moyenne nette | +0,16 (34 % du temps vendeur, 17 % à plat) |

Trois causes, dans l'ordre :

1. **Les frais mangent le signal.** L'agent a un vrai petit talent de timing : 81 % des runs ont un Sharpe brut positif, corrélation de rang
   position/rendement suivant de 0,018 en moyenne (t ≈ 15 sur l'ensemble, séries non indépendantes). En retirant la dérive, le timing vaut
   environ +4 %/an brut. Mais l'agent change de position tous les 3-4 jours et paie 4,6 %/an : tout part en frais.
2. **La vente à découvert coûte la prime des actions.** Être vendeur un tiers du temps sur des actifs qui montent de 12 %/an perd la dérive.
   Contrefactuel sur les mêmes positions, la jambe courte remplacée par « à plat » : Sharpe net médian 0,31 au lieu de 0,10 (×3).
3. **Plus d'entraînement = pire.** Le profil « mémoire » (80 000 pas, 20 lignes, 3 graines) : Sharpe médian −0,31, rotation 110, corrélation
   0,008. Sur un signal aussi faible, l'agent apprend le bruit de l'échantillon d'entraînement. Rien ne l'arrêtait (pas de validation).

Autres constats :
- Dispersion entre graines : écart-type 0,21 de Sharpe pour une même configuration, du même ordre que l'effet cherché.
- 59 % des plis ont un Sharpe positif ; la moitié des plis d'un run, en médiane.
- Lisser les positions sur 10 jours après coup (Sharpe 0,18) aide moins que supprimer la jambe courte : la rotation se règle à la source.

## 4. Les « réussites » et ce qu'elles apprennent

| Classe | Sharpe net médian | Sharpe brut | Brut, positions décalées d'un jour | Lecture |
|---|---|---|---|---|
| Devises (21) | 2,1 (jusqu'à 5,3) | 3,5 | −0,1 | **Fuite** |
| Indices de volatilité (9) | 1,1 | 1,2 | 1,0 | Vrai signal, non négociable |
| Actions Asie (9) | 1,2 | 1,6 | 0,2 | Suspect (même signature que les devises) |
| Actions US / Europe | 0,1 | 0,3 | 0,2 | Signal faible, mangé par les frais |

- **Devises : fuite connue, encore présente dans le RL.** Les barres Yahoo `=X` portent le cours du début de journée (ADR 0007). Le pipeline ML
  applique la règle des séances 2 depuis le 28/10, **le moteur RL jamais** (`run_rl` ne fixait pas `session_rule`). Décaler les positions
  d'un jour fait passer le Sharpe brut de 3,5 à environ 0 (AUDUSD 6,7 → 0,4 ; KRW 5,8 → −0,5).
- **Indices de volatilité** (VVIX, SKEW, VIX9D...) : le gain survit au décalage (retour à la moyenne réel). Mais ces indices ne s'achètent
  pas ; le résultat ne se négocie pas (avertissement déjà affiché).
- **Leçon positive** : quand un signal existe (même une fuite), PPO le trouve vite et fort. La mécanique RL fonctionne ; le problème est
  le rapport signal/bruit, les frais et le cadre (vendeur sur des actifs haussiers, aucun garde-fou).

## 5. Ce que la refonte change (ADR 0022)

| Échec mesuré | Changement |
|---|---|
| Fuite des devises | `run_rl` applique la règle des séances d'aujourd'hui ; test du décalage d'un jour publié avec chaque run |
| Rotation 66, frais 4,6 %/an | Une décision toutes les 5 barres ; frais ×2 à l'entraînement |
| Jambe courte perdante | Positions longues seulement par défaut (0, ½, 1) ; profil « Long et court » pour qui veut |
| Bruit du marché dans la récompense | Récompense « au-delà d'acheter-garder » (même optimum, moins de bruit) |
| Sur-apprentissage (80 000 pas pire que 30 000) | Validation en fin de fenêtre ; meilleur point de contrôle gardé |
| 80 % des agents perdent contre BH | Repli : un pli où l'agent ne bat pas BH en validation tient BH |
| Référence trop facile | Référence « tendance 200 j » ; écart de Sharpe contre elle |
| Décomposition invisible | Rendement brut, frais, jambes longue/courte affichés |

## 6. Banc d'essai moteur 1 contre moteur 2

Mêmes cibles, mêmes données (au 16/11), même graine, une graine par agent (comme 431 des 456 runs). Voir la section suivante, remplie à
la fin du banc d'essai.
