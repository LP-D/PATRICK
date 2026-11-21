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
- **Actions d'Asie : fuite confirmée par le test du décalage d'un jour** (rejoué sur les fichiers hors échantillon, 16/11 au soir) : ^STI
  1,68 → 0,50, ^TWII 2,46 → 0,47, ^KS11 1,73 → 0,09, ^AXJO 1,45 → 0,08, ^N225 2,30 → 0,30 (Sharpe brut, puis positions décalées). ^NSEI
  garde 60 % (1,60 → 0,96). **Cause trouvée le 21/11** : ces runs du 20/10 précèdent l'alignement version 2 (28/10), qui retarde d'un jour
  les séries FRED quotidiennes pour une cible qui clôture avant New York. Le VIX FRED du jour (leur variable favorite : `VIX_ret_1d`,
  `VIX_zscore_10d`, `VIX_level`) se fixe douze heures après la clôture de Tokyo et annonce la séance suivante (corrélation de rang −0,195
  sur ^N225, environ 0 une fois retardé). Les 9 runs RL d'Asie, ^NSEI compris, et 168 runs ML sont marqués « séries FRED du jour »
  (ADR 0007, complément du 21/11).
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

Mêmes cibles, mêmes données (au 16/11), même graine, une graine par agent (comme 431 des 456 runs), 4 plis, 30 000 pas. Les deux moteurs
tournent sous la règle des séances corrigée. 21 cibles, 20 exploitables (CL=F refusé : cours négatif en avril 2020).

| Cible | BH | Tendance 200 j | Moteur 1 | Moteur 2 | Agent sans repli | Ancien run stocké |
|---|---|---|---|---|---|---|
| AAPL | 0,99 | 0,91 | 0,39 | 0,99 | 0,92 | 0,49 |
| MSFT | 0,93 | 0,74 | 0,34 | 0,89 | 0,58 | 0,22 |
| JPM | 0,77 | 0,69 | 0,19 | 0,65 | 0,61 | 0,32 |
| XOM | 0,44 | 0,43 | −0,38 | 0,12 | 0,26 | 0,07 |
| ^GSPC | 0,79 | 0,71 | 0,35 | 0,71 | 0,72 | 0,19 |
| ^NDX | 0,82 | 0,89 | 0,53 | 0,78 | 0,64 | 0,20 |
| ^FCHI | 0,40 | 0,30 | 0,06 | 0,36 | 0,35 | −0,56 |
| ^GDAXI | 0,56 | 0,40 | −0,05 | 0,26 | 0,22 | −0,03 |
| ^STOXX50E | 0,45 | 0,24 | 0,20 | 0,32 | 0,24 | −0,52 |
| ^N225 | 0,64 | 0,29 | 0,00 | 0,61 | 0,40 | 1,83 |
| MC.PA | 0,49 | 0,30 | 0,40 | 0,40 | 0,42 | 0,15 |
| SAN.PA | 0,35 | −0,08 | −0,30 | 0,34 | 0,37 | −0,37 |
| AIR.PA | 0,54 | 0,40 | 0,35 | 0,52 | 0,52 | −0,03 |
| GC=F | 0,73 | 0,60 | 0,08 | 0,76 | 0,70 | −0,34 |
| ZN=F | −0,21 | −0,34 | −0,07 | −0,35 | −0,55 | — |
| XLE | 0,36 | 0,32 | −0,14 | 0,08 | −0,16 | −0,11 |
| EEM | 0,37 | 0,36 | 0,31 | 0,37 | 0,37 | 0,41 |
| EURUSD=X | 0,02 | 0,09 | −0,38 | −0,14 | −0,21 | 2,14 |
| USDJPY=X | 0,39 | 0,12 | −0,17 | 0,04 | −0,02 | 3,70 |
| ^VIX | 0,63 | −0,56 | 0,76 | 1,12 | 1,12 | 1,31 |

Synthèse (20 cibles) :

| | Moteur 1 | Moteur 2 |
|---|---|---|
| Sharpe médian (BH 0,51, tendance 0,34) | 0,14 | 0,38 |
| Le moteur 2 fait mieux que le moteur 1 | — | 18 cibles sur 20, +0,32 de Sharpe en moyenne (t = 5,8) |
| Croissance au-delà de BH, médiane | −9,4 %/an | −1,3 %/an |
| Rotation médiane | 56 | 4 |
| Frais, médiane | 3,9 %/an | 0,3 %/an |
| Drawdown maximal, médiane | −51 % | −37 % |
| Bat BH en Sharpe | 2 sur 20 | 3 sur 20 |
| Bat BH à 5 % (bootstrap) | 0 | 1 (^VIX, non négociable) |

- **Le repli seul** vaut +0,07 de Sharpe en moyenne (aide sur 13 cibles, nuit sur 4, t = 2,8) ; 39 plis sur 80 ont été repliés. Le reste du
  gain (+0,25) vient des positions longues, de la décision tous les 5 jours, des frais gonflés et du point de contrôle choisi en validation.
- **Fuite des devises confirmée et corrigée** : EURUSD et USDJPY passent de 2,14 et 3,70 (anciens runs, règle 1) à −0,38 et −0,17 (moteur 1,
  règle 2). Aucun test du décalage d'un jour ne se déclenche sur le banc d'essai.
- **Ce que le moteur 2 ne fait pas** : battre acheter-garder sur les actions. Il ne détruit plus de valeur (−1,3 %/an au lieu de −9,4 %/an
  face à BH, drawdown plus faible), mais il n'en crée pas : avec ces variables quotidiennes, aucun signal de timing ne survit aux frais sur
  les actifs testés. Seul le VIX (retour à la moyenne réel mais non négociable) bat nettement la référence.
- Le moteur 2 rejoint la règle de tendance 200 j (0,38 contre 0,34) : c'est le niveau d'une règle simple, pas un avantage.
- Sur ZN=F (Treasury 10 ans, actif baissier sur la période), le moteur 2 fait pire que le moteur 1 : se replier sur acheter-garder ne
  protège pas quand la référence perd elle-même, et les positions longues seules interdisent de profiter de la baisse.

**Conclusion** : la refonte corrige ce qui faisait perdre de l'argent (frais, jambe courte, sur-apprentissage, fuite). Le moteur rend
désormais un résultat honnête, proche d'acheter-garder quand il n'y a rien à trouver. Elle ne crée pas un signal qui n'est pas dans les
données : pour battre le marché, il faudra d'autres informations que les variables techniques et macro quotidiennes, ou des horizons
plus longs, pas un meilleur agent.
