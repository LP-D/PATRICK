# Cours : l'économétrie d'une série financière

Ce document explique **ce que calcule la page Économétrie** (`/econometrie`) et l'onglet Multivarié de `/exploration`, avec les mathématiques qui les fondent. Il suit l'ordre des onglets. Il suppose que vous connaissez la moyenne, la variance et la corrélation ; tout le reste est défini quand il apparaît.

**Comment lire les formules.** Elles sont écrites en texte simple : `x_t` se lit « x à la date t », `x_{t-1}` « x à la date précédente », `Σ` est une somme, `σ²` une variance, `E[·]` une espérance (une moyenne théorique), `Var(·)` une variance théorique, `ln` le logarithme népérien. Un encadré « À retenir » résume chaque section.

**Sources des chiffres.** Les exemples « simulés » viennent de processus dont on connaît les paramètres (fonctions de `patrick/econometrics/simulate.py`, graine fixe : on peut les rejouer, les tests du dépôt le font). Les exemples « réels » viennent de la page elle-même, mesurés le 2026-11-03 sur `^GSPC` (S&P 500, Yahoo Finance) du 2016-11-04 au 2026-11-03, 2 512 rendements journaliers.

---

## Table des matières

0. Vue d'ensemble et règles de la maison
1. Les données : de la cotation à la série étudiée
2. Stationnarité et racine unitaire
3. Dépendance dans le temps
4. Moyenne conditionnelle : AR, MA, ARMA, ARIMA
5. Variance conditionnelle : ARCH, GARCH et famille
6. Régimes : Markov-switching et HMM
7. Prévision hors échantillon et comparaison de modèles
8. Multivarié : VAR, Johansen, VECM
9. Pièges : la check-list
10. Ce qui n'est pas fait, et pourquoi
11. Carte du code
12. Exercices avec la page
13. Références

---

## 0. Vue d'ensemble et règles de la maison

### La question posée à une série de rendements

Un rendement journalier `r_t` se décompose en deux parties :

```
r_t = μ_t + σ_t · z_t
```

- `μ_t` est la **moyenne conditionnelle** : ce qu'on peut prévoir du rendement de demain à partir du passé. Sur des rendements journaliers, elle est presque toujours indiscernable d'une constante.
- `σ_t²` est la **variance conditionnelle** : l'amplitude attendue du mouvement de demain, sachant le passé. Elle est, elle, très prévisible : les périodes agitées se regroupent.
- `z_t` est un choc imprévisible, de moyenne 0 et de variance 1.

« Conditionnel » veut dire « sachant l'information disponible à la date précédente ». Les onglets de la page répondent chacun à une question sur cette décomposition :

| Onglet | Question |
|---|---|
| Stationnarité | La série garde-t-elle les mêmes propriétés dans le temps ? Y a-t-il une rupture ? |
| Dépendance | Le passé de la série informe-t-il sur son futur, pour la moyenne, pour la variance, ou d'une façon non linéaire ? |
| Moyenne | Un modèle ARMA bat-il la simple constante ? |
| Variance | Quel modèle de variance décrit le mieux la série, et avec quelle asymétrie, quelle persistance ? |
| Régimes | La série change-t-elle d'état (calme / stress) ? |
| Prévision | Quel modèle de variance **prévoit** le mieux, hors échantillon, et la différence est-elle réelle ? |
| Multivarié (`/exploration`) | Plusieurs séries se répondent-elles (VAR) ou restent-elles liées à long terme (cointégration) ? |

### Les quatre règles de la page

1. **Descriptif contre prévision.** Un modèle ajusté sur *tout* l'échantillon décrit le passé ; il ne le prévoit pas, car ses paramètres ont « vu » les jours qu'il prétend expliquer. Les ajustements pleine période portent le bandeau « lecture descriptive, pas une prévision ». Seul l'onglet Prévision réestime sur le passé uniquement.
2. **Le verdict d'abord, dit tel quel.** La première ligne d'un résultat est la conclusion : « aucun modèle ne bat la constante », « 3 modèles sur 9 n'ont pas convergé ». La page ne cherche pas un gagnant quand il n'y en a pas.
3. **Compter les essais.** Si l'on essaie 20 modèles sur 66 séries, quelques-uns « gagnent » par hasard. La page affiche le nombre de spécifications essayées et corrige les p-values (§4 et §7).
4. **Montrer les échecs.** Un modèle qui n'a pas convergé reste dans le tableau avec son message ; on ne le retire pas.

> **À retenir.** Une série de rendements = une moyenne presque constante + une variance très structurée. La page vérifie chaque affirmation par un test, compte ses essais, et sépare ce qui décrit le passé de ce qui prévoit l'avenir.

---

## 1. Les données : de la cotation à la série étudiée

### 1.1 Le log-rendement

À partir d'un prix `P_t`, la page utilise par défaut le **log-rendement** :

```
r_t = ln(P_t) − ln(P_{t-1}) = ln(P_t / P_{t-1})
```

Raisons : pour de petites variations, `ln(1 + x) ≈ x`, donc le log-rendement est proche du rendement simple `(P_t − P_{t-1}) / P_{t-1}`. Surtout, les log-rendements **s'additionnent** : le rendement sur trois jours est `r_{t} + r_{t-1} + r_{t-2}`, ce qui rend la mathématique des horizons simple. Si le niveau n'est pas toujours strictement positif (un taux, un écart de crédit), le logarithme n'existe pas : la page passe en **différence** `x_t − x_{t-1}` et le signale.

### 1.2 Rendement au carré et proxy de variance

On n'observe jamais la variance d'un jour : on n'a qu'un rendement. Comme `E[r_t²] = σ_t²` (si la moyenne est nulle), `r_t²` est un **estimateur sans biais** de la variance du jour. Mais il est très bruité : si `z` suit une loi normale, `Var(r_t²) = 2σ_t⁴`, donc l'écart-type de `r_t²` vaut `√2 ≈ 1,41` fois sa valeur attendue. Un seul jour ne dit presque rien.

### 1.3 Variances fondées sur l'amplitude haut-bas (Parkinson, Garman-Klass)

Avec les prix OHLC (ouverture `O`, plus haut `H`, plus bas `L`, clôture `C`), on tire beaucoup plus d'information d'une journée.

**Parkinson (1980)** :

```
σ²_Parkinson = (ln(H / L))² / (4 ln 2)
```

L'idée : pour un mouvement brownien sans dérive, l'espérance de `(ln(H/L))²` sur une période vaut `4 ln 2 · σ²`. L'amplitude de la journée contient donc la même information que `r²` mais avec un bruit environ cinq fois plus faible (efficacité théorique de 5,2 pour des prix continus).

**Garman-Klass (1980)** ajoute l'ouverture et la clôture :

```
σ²_GK = 0,5 · (ln(H / L))² − (2 ln 2 − 1) · (ln(C / O))²
```

*Limites.* Ces formules supposent des prix continus, sans saut. Les écarts de la nuit (clôture de la veille → ouverture) ne sont pas dans `H − L` : l'estimateur sous-estime la variance close-to-close. C'est pourquoi la page l'appelle un **proxy** et compare les modèles *sur le même proxy*. Les séries FRED n'ont pas d'OHLC : seuls `r²`, la différence et le log-rendement leur sont offerts.

### 1.4 Différenciation fractionnaire

Un prix n'est pas stationnaire (§2) ; son rendement l'est, mais il a oublié toute mémoire du niveau. La **différenciation fractionnaire** d'ordre `d` (0 < d < 1) est un entre-deux. Avec l'opérateur retard `L` (`L x_t = x_{t-1}`) :

```
(1 − L)^d = Σ_{k≥0} w_k L^k        avec  w_0 = 1,   w_k = − w_{k-1} · (d − k + 1) / k
```

Pour `d = 1` on retrouve la différence ordinaire (`w_0 = 1, w_1 = −1`, les autres sont nuls). Pour `0 < d < 1` les poids décroissent lentement : la série garde une mémoire longue. La version « fenêtre fixe » du projet (`features/fracdiff.py`, López de Prado) coupe les poids dès que `|w_k| < seuil` : chaque valeur ne dépend que des `width` observations précédentes, donc **seulement du passé**.

### 1.5 Fréquences

Les prix Yahoo sont **quotidiens**, les séries FRED souvent **mensuelles**. La page ne les mélange jamais : une série mensuelle garde sa fréquence (12 périodes par an), et seule elle offre la composante saisonnière du SARIMA. Rééchantillonner du mensuel en quotidien fabriquerait de fausses observations.

> **À retenir.** Log-rendement par défaut (additif). `r²` est sans biais mais très bruité (écart-type = 1,41 × sa moyenne) ; Parkinson et Garman-Klass sont bien moins bruités mais ignorent la nuit.

---

## 2. Stationnarité et racine unitaire

### 2.1 Stationnarité

Une série est **faiblement stationnaire** si sa moyenne et sa variance ne dépendent pas de la date, et si la covariance entre `x_t` et `x_{t-k}` ne dépend que de `k`. Pourquoi y tenir : la plupart des outils statistiques (moyennes, corrélations, régressions) supposent que « la moyenne d'hier » estime « la moyenne de demain ». Régresser deux séries non stationnaires l'une sur l'autre donne des relations « fabuleuses » qui n'existent pas (régression fallacieuse, Granger et Newbold 1974).

### 2.2 La racine unitaire

Prenons l'autorégression d'ordre 1 :

```
x_t = φ · x_{t-1} + ε_t        (ε_t : choc de variance σ²)
```

- `|φ| < 1` : la série revient vers sa moyenne, elle est stationnaire ; les chocs s'estompent.
- `φ = 1` : c'est une **marche aléatoire**, `x_t = x_0 + ε_1 + … + ε_t`. Sa variance vaut `t · σ²` : elle croît sans limite, un choc est permanent. On dit que la série a une **racine unitaire**.

Un prix est typiquement une marche aléatoire (avec dérive) ; son log-rendement est stationnaire.

### 2.3 Test de Dickey-Fuller augmenté (ADF)

On réécrit le modèle en différences en soustrayant `x_{t-1}` :

```
Δx_t = α + γ · x_{t-1} + Σ_{i=1..p} δ_i Δx_{t-i} + ε_t        avec  γ = φ − 1
```

- `H0 : γ = 0` (racine unitaire). `H1 : γ < 0` (stationnaire).
- La statistique est le t de Student de `γ̂`. Sous H0, elle **ne suit pas** une loi de Student, mais la loi de Dickey-Fuller (non standard : à cause de la non-stationnarité, elle est décalée vers les valeurs négatives). Les valeurs critiques (constante dans le modèle, 1 000 observations, bibliothèque `arch`) sont **−3,44 à 1 %, −2,86 à 5 %, −2,57 à 10 %**.
- On rejette H0 si la statistique est **plus négative** que la valeur critique. Les termes `Δx_{t-i}` (« augmentés ») absorbent l'autocorrélation des chocs ; leur nombre `p` est choisi par le critère AIC (§4).
- On peut ajouter une tendance linéaire (`ct` dans la page) si la série dérive de façon déterministe.

### 2.4 Phillips-Perron et DF-GLS

- **Phillips-Perron (1988)** garde la régression de Dickey-Fuller simple, mais corrige la statistique par une estimation non paramétrique de la variance de long terme (noyau de Newey-West) au lieu d'ajouter des retards. Mêmes valeurs critiques, même H0.
- **DF-GLS (Elliott, Rothenberg, Stock 1996)** commence par retirer la constante (ou la tendance) par moindres carrés généralisés, puis applique l'ADF aux résidus. Il est plus **puissant** quand `φ` est proche de 1.

### 2.5 Le test KPSS : l'hypothèse nulle inversée

KPSS (Kwiatkowski, Phillips, Schmidt, Shin 1992) pose le modèle :

```
x_t = ξ · t + r_t + ε_t        avec  r_t = r_{t-1} + u_t   (marche aléatoire de variance σ_u²)
```

- `H0 : σ_u² = 0` (pas de composante marche aléatoire : la série est stationnaire autour d'une constante ou d'une tendance). `H1 : σ_u² > 0`.
- Avec `e_t` les résidus de la régression de `x` sur une constante, `S_t = e_1 + … + e_t` les sommes partielles, la statistique est :

```
η = ( Σ_{t=1..T} S_t² ) / ( T² · σ̂²_LR )
```

où `σ̂²_LR` est la variance de long terme (Newey-West). Si la série est stationnaire, les sommes partielles restent petites ; sinon elles dérivent et `η` explose. Valeurs critiques (niveau, `arch`) : **0,743 (1 %), 0,461 (5 %), 0,348 (10 %)**. On rejette si `η` est **grand**.

### 2.6 Lecture croisée ADF × KPSS

Les deux familles ont des hypothèses nulles **opposées**. Ne conclure que lorsqu'elles s'accordent :

| | KPSS ne rejette pas | KPSS rejette |
|---|---|---|
| **ADF rejette** | **Stationnaire** | Contradictoire (rupture, tendance, variance changeante) |
| **ADF ne rejette pas** | Non concluant (puissance faible) | **Racine unitaire** |

*Exemple simulé* (n = 1 000) :

| Série | ADF (stat. ; p) | KPSS (stat. ; p) | Verdict |
|---|---|---|---|
| Marche aléatoire | −2,22 ; 0,198 | 1,665 ; < 0,001 | racine unitaire |
| AR(1), φ = 0,5 | −16,51 ; < 0,001 | 0,103 ; 0,57 | stationnaire |

Un test à 5 % se trompe une fois sur vingt par construction. Le test du dépôt le vérifie sur 20 tirages plutôt que sur un seul.

*Exemple réel.* Sur le log-rendement du S&P 500, la page affiche « stationnaire » : c'est attendu. Un rendement est une différence de logarithmes de prix ; tester la racine unitaire sur un rendement est surtout une vérification.

### 2.7 Rupture endogène : Zivot-Andrews

Un changement de niveau peut faire passer une série stationnaire pour une marche aléatoire. **Zivot et Andrews (1992)** testent la racine unitaire en laissant une rupture, dont la date `λ` est choisie par les données :

```
Δx_t = α + θ · DU_t(λ) + γ · x_{t-1} + Σ δ_i Δx_{t-i} + ε_t        DU_t(λ) = 1 si t > λ·T, sinon 0
```

On répète la régression pour chaque date de rupture candidate (en excluant les 15 % extrêmes de l'échantillon) et on retient celle qui minimise le t de `γ̂`, c'est-à-dire celle qui rend la racine unitaire la moins plausible. `H0` : racine unitaire **sans** rupture. Rejeter signifie « stationnaire avec une rupture à la date donnée ». La page affiche la date et sa position dans l'échantillon. *Test du dépôt :* sur du bruit avec un saut de +4 écarts-types au milieu, la rupture est localisée à ±5 % du milieu.

### 2.8 Ratio de variance et exposant de Hurst

- **Ratio de variance (Lo et MacKinlay 1988).** Si les rendements sont imprévisibles, la variance du rendement sur `q` périodes vaut `q` fois celle d'une période :

```
VR(q) = Var( r_t + … + r_{t-q+1} ) / ( q · Var(r_t) )        vaut 1 pour une marche aléatoire
```

`VR > 1` : les mouvements se prolongent (momentum) ; `VR < 1` : ils se corrigent (retour à la moyenne). Le z « robuste » tient compte d'une variance qui change dans le temps ; le test d'ensemble de Chow-Denning (1993) évite de compter plusieurs fois la même chance sur plusieurs horizons.
- **Exposant de Hurst (Hurst 1951).** Mesure comment l'écart-type des variations d'une série grandit avec l'horizon `τ` : `std(x_{t+τ} − x_t) ∝ τ^H`. La page l'estime par la pente d'une régression de `ln std` sur `ln τ` (horizons de 2 à 100 jours), appliquée au **log-niveau** (la somme cumulée de la série étudiée). `H = 0,5` : marche aléatoire ; `H > 0,5` : tendance persistante ; `H < 0,5` : retour à la moyenne (la page parle de « marche aléatoire » entre 0,45 et 0,55). Estimation bruitée sur un échantillon court.

> **À retenir.** ADF/PP/DF-GLS testent « racine unitaire » ; KPSS teste « stationnaire ». Conclure seulement quand ils s'accordent. Un test à 5 % se trompe 1 fois sur 20.

---

## 3. Dépendance dans le temps

### 3.1 Autocorrélation (ACF) et autocorrélation partielle (PACF)

L'autocorrélation à l'ordre `k` mesure à quel point `x_t` ressemble à `x_{t-k}` :

```
ρ_k = Cov(x_t, x_{t-k}) / Var(x_t)           estimée par   ρ̂_k = Σ_t (x_t − x̄)(x_{t-k} − x̄) / Σ_t (x_t − x̄)²
```

L'**autocorrélation partielle** `φ_kk` est la corrélation entre `x_t` et `x_{t-k}` une fois retirée l'influence des retards intermédiaires. Elle sert à reconnaître un AR(p) : `φ_kk` s'annule après `p`.

**La bande ±1,96/√n.** Pour une série indépendante et identiquement distribuée (i.i.d.), `ρ̂_k` est approximativement normale de moyenne 0 et de variance `1/n`. Un coefficient hors de `±1,96/√n` est donc « significatif à 5 % ». Sur 20 retards, on s'attend à environ un dépassement par hasard : un seul barre hors bande ne prouve rien.

### 3.2 Test de Ljung-Box

Plutôt que juger chaque retard, on teste ensemble les `m` premiers (Ljung et Box 1978) :

```
Q(m) = n (n + 2) · Σ_{k=1..m} ρ̂_k² / (n − k)        sous H0 (aucune autocorrélation) : Q ~ χ²(m)
```

`H0` : les `m` premières autocorrélations sont nulles. Si les données sont les résidus d'un ARMA(p, q), les degrés de liberté deviennent `m − p − q`.

**McLeod-Li (1983).** C'est le test de Ljung-Box appliqué à `x_t²`. Il détecte la dépendance de la **variance** : si les carrés sont autocorrélés, les grosses variations appellent les grosses variations.

### 3.3 ARCH-LM d'Engle

Engle (1982) régresse le carré de la série sur ses `q` retards :

```
x_t² = a_0 + a_1 x_{t-1}² + … + a_q x_{t-q}² + e_t        LM = n · R²  ~  χ²(q)   sous H0 : a_1 = … = a_q = 0
```

`R²` est la part de variance expliquée par la régression. Un rejet signifie « effets ARCH » : la variance dépend de ses valeurs passées (§5).

### 3.4 Test BDS

Les tests précédents ne voient que la dépendance linéaire (ou de variance). Le test **BDS** (Brock, Dechert, Scheinkman, LeBaron 1996) détecte *toute* dépendance, y compris non linéaire. Il repose sur l'**intégrale de corrélation** :

```
C_m(ε) = proportion de paires de « mots » de m observations consécutives dont tous les termes diffèrent de moins de ε
```

Si la série est i.i.d., `C_m(ε) = C_1(ε)^m`. La statistique est :

```
W_m = √n · ( C_m(ε) − C_1(ε)^m ) / σ_m(ε)       sous H0 (i.i.d.) : approximativement N(0, 1)
```

La page prend `ε = 1,5` écart-type, teste les dimensions `m = 2 … 5` et corrige le rejet global par Bonferroni (multiplier la plus petite p-value par le nombre de dimensions). Le calcul compare toutes les paires de points (coût en `n²`) : la page garde les 2 000 observations les plus récentes. **Lecture :** appliqué aux rendements bruts, le BDS rejette presque toujours (à cause de la variance qui change) ; il devient informatif sur les **résidus standardisés** d'un GARCH : un rejet là dit que le modèle a laissé de la structure.

### 3.5 Les trois faits stylisés (Cont 2001)

Sur des rendements journaliers d'actions ou d'indices, on observe presque toujours :

1. **autocorrélation des rendements quasi nulle** (`ρ̂_1 ≈ 0`) ;
2. **forte autocorrélation de `r²` et `|r|`** : regroupement de la volatilité ;
3. **queues épaisses** : plus de grands mouvements que ne le prévoit une loi normale (kurtosis > 3).

*Exemple simulé* (GARCH(1,1), n = 3 000, paramètres ω = 0,05, α = 0,10, β = 0,85) : autocorrélation de `r` à l'ordre 1 : 0,001 ; de `r²` : 0,176. Ljung-Box sur `r` : p = 0,45 (5 retards), 0,68 (10), 0,63 (20) ; sur `r²` : p < 10⁻⁸⁰. ARCH-LM : statistique 266,9, p ≈ 10⁻⁵⁵. Le rendement est imprévisible, sa variance l'est.

> **À retenir.** ACF/PACF et Ljung-Box regardent la dépendance linéaire de `x` ; Ljung-Box sur `x²` et ARCH-LM regardent celle de la variance ; BDS regarde tout, et se lit surtout sur des résidus.

---

## 4. Moyenne conditionnelle : AR, MA, ARMA, ARIMA

### 4.1 Les modèles

Avec l'opérateur retard `L` :

```
AR(p)      : x_t = c + φ_1 x_{t-1} + … + φ_p x_{t-p} + ε_t
MA(q)      : x_t = c + ε_t + θ_1 ε_{t-1} + … + θ_q ε_{t-q}
ARMA(p,q)  : φ(L) x_t = c + θ(L) ε_t        φ(L) = 1 − φ_1 L − … − φ_p L^p,   θ(L) = 1 + θ_1 L + … + θ_q L^q
ARIMA(p,d,q) : on applique ARMA(p,q) à la série différenciée d fois : (1 − L)^d x_t
```

`ε_t` est un choc de moyenne nulle et de variance constante. Deux conditions : **stationnarité** (les racines de `φ(z) = 0` sont hors du cercle unité, c'est-à-dire de module > 1) et **inversibilité** (celles de `θ(z) = 0` aussi). `d = 0` : modèle sur le niveau de la série (adapté à un rendement) ; `d = 1` : sur sa différence (adapté à un prix ou un niveau macro).

**SARIMA.** On ajoute des termes aux retards saisonniers (12 pour du mensuel). La page propose la composante `(1,0,0)12` : `x_t` dépend aussi de `x_{t-12}`.

**ARIMAX.** On ajoute un régresseur externe. La page le **retarde d'une période** : la valeur de la veille d'un autre actif peut expliquer celle d'aujourd'hui ; sa valeur du jour n'aurait pas de sens prédictif.

### 4.2 Estimation et critères de choix

Le modèle s'écrit sous forme d'état-espace et l'on maximise la **vraisemblance** gaussienne via le filtre de Kalman (statsmodels). La vraisemblance `L` mesure à quel point les données sont plausibles sous le modèle ; `ℓ = ln L`. Plus on ajoute de paramètres, plus `ℓ` monte, donc on pénalise :

```
AIC = −2ℓ + 2k            BIC = −2ℓ + k · ln(n)           (k : nombre de paramètres, n : observations)
```

Le **BIC pénalise plus que l'AIC** dès que `n > 7` (car `ln n > 2`) ; il choisit des modèles plus petits. On compare les modèles par leur **écart de BIC** `ΔBIC = BIC_modèle − BIC_constante`. Échelle usuelle (Raftery 1995) : un écart de 0 à 2 est de l'évidence faible, 2 à 6 positive, 6 à 10 forte, > 10 très forte. La page ne déclare qu'un modèle « bat la constante » si `ΔBIC ≤ −2`.

**Pourquoi la constante est la référence.** Un rendement journalier a une moyenne presque constante : le meilleur modèle de moyenne est souvent « la moyenne ». La grille affiche toujours cette ligne.

### 4.3 Rapport de vraisemblance et correction des essais multiples

Le modèle constant est **emboîté** dans un ARMA (il en est le cas particulier où les coefficients sont nuls). Le test du rapport de vraisemblance :

```
LR = 2 · (ℓ_ARMA − ℓ_constante)        sous H0 (coefficients supplémentaires nuls) : LR ~ χ²(k_ARMA − k_constante)
```

C'est une approximation (les ARMA sur-paramétrés ont des paramètres mal identifiés). Surtout, la grille teste plusieurs modèles : sur 8 p-values à 5 %, la probabilité qu'au moins une soit « significative » par hasard est d'environ `1 − 0,95⁸ ≈ 34 %`. La page corrige donc par **Benjamini-Hochberg** (1995) : on classe les `m` p-values `p_(1) ≤ … ≤ p_(m)` et la p-value corrigée du rang `i` est :

```
q_(i) = min_{j ≥ i} ( m / j · p_(j) )         (plafonnée à 1)
```

Cette procédure contrôle le **taux de fausses découvertes** (la part attendue de « découvertes » qui sont fausses). Ce taux est le même critère que celui de `validation/fdr.py` du projet.

### 4.4 Diagnostics des résidus

Un bon modèle laisse des résidus imprévisibles. La page affiche :
- **Ljung-Box des résidus**, avec `m − p − q` degrés de liberté ;
- **ARCH-LM des résidus** : un ARMA ne modélise pas la variance, on s'attend à un rejet sur des rendements ;
- **Jarque-Bera** : teste que les résidus ont l'asymétrie et le kurtosis d'une loi normale :

```
JB = (n / 6) · ( S² + (K − 3)² / 4 )        S : asymétrie, K : kurtosis ; sous H0 (normalité) JB ~ χ²(2)
```

- le **diagramme quantile-quantile** : on trace les quantiles des résidus standardisés contre ceux de la loi normale ; les points sur la diagonale = normalité, une courbe en S = queues épaisses.

### 4.5 Mémoire longue : GPH

Un modèle ARFIMA généralise l'ARIMA avec un ordre de différenciation `d` **fractionnaire** : `(1 − L)^d x_t = ε_t`. Pour `0 < d < 0,5`, la série est stationnaire mais ses autocorrélations décroissent lentement (mémoire longue) ; `d = 0` mémoire courte ; `d → 1` racine unitaire. Sous cette forme, `x_t` est une moyenne mobile infinie : `x_t = Σ ψ_k ε_{t-k}` avec `ψ_0 = 1`, `ψ_k = ψ_{k-1} · (k − 1 + d) / k`.

La page estime `d` par la méthode de **Geweke et Porter-Hudak (1983)** : on régresse le logarithme du périodogramme `I(λ_j)` sur `ln(4 sin²(λ_j / 2))` aux `m = n^0,5` premières fréquences `λ_j = 2πj/n` :

```
ln I(λ_j) = c − d · ln( 4 sin²(λ_j / 2) ) + erreur        d̂ = − pente,     écart-type de d̂ = π / √( 6 Σ (g_j − ḡ)² )
```

(avec `g_j = ln(4 sin²(λ_j/2))`). C'est une **approximation** : l'ARFIMA exact n'existe pas dans `statsmodels` et n'est pas implémenté (§10).

### 4.6 Exemples

*Simulé.* Sur un AR(1) de paramètre 0,6 (n = 1 500), la grille retient un modèle avec `p ≥ 1` et un `ΔBIC` très négatif ; le coefficient estimé est 0,6 ± 0,08. Sur du **bruit blanc**, 9 tirages sur 10 donnent « aucun modèle ne bat la constante » ; le dixième est le taux d'erreur attendu.

*Réel.* Sur `^GSPC`, 2016-2026, grille p, q ≤ 2 : « un modèle bat la constante : ARIMA(2,0,0), ΔBIC = −50,5 ». Il faut interpréter : ce n'est pas la preuve qu'on peut gagner de l'argent avec un AR(2). Les rendements du S&P 500 ont une autocorrélation négative marquée pendant les épisodes agités (mars 2020 en tête) ; sur 2 512 jours, quelques semaines extrêmes suffisent à faire gagner le modèle au BIC. La page le dit (ΔBIC) ; elle ne dit pas que la prévision est exploitable. Seul l'onglet Prévision répond à cette question.

> **À retenir.** Comparer par ΔBIC à la constante, corriger les essais multiples (Benjamini-Hochberg), vérifier les résidus. Un ΔBIC favorable en échantillon n'est pas une prévision.

---

## 5. Variance conditionnelle : ARCH, GARCH et famille

C'est le cœur de la page. On pose `ε_t = r_t − μ` (le choc, ou « surprise ») et `ε_t = σ_t z_t`, `z_t` de moyenne 0 et variance 1.

### 5.1 ARCH et GARCH

**ARCH(q) (Engle 1982)** : la variance du jour dépend des carrés des `q` derniers chocs :

```
σ_t² = ω + α_1 ε²_{t-1} + … + α_q ε²_{t-q}              (ω > 0, α_i ≥ 0)
```

**GARCH(1,1) (Bollerslev 1986)** ajoute la variance de la veille :

```
σ_t² = ω + α · ε²_{t-1} + β · σ²_{t-1}
```

Lecture : `ω` fixe un plancher ; `α` mesure la **réaction** au dernier choc ; `β` la **mémoire** de la variance passée.

**Propriétés.**
- *Stationnarité* : `α + β < 1`. La **persistance** est `α + β`.
- *Variance inconditionnelle* (moyenne à long terme) : `σ̄² = ω / (1 − α − β)`.
- *Retour à la moyenne.* Le GARCH(1,1) est un ARMA(1,1) sur `ε²`. La variance prévue à l'horizon `h` est :

```
E[σ²_{t+h} | information en t] = σ̄² + (α + β)^{h−1} · ( σ²_{t+1} − σ̄² )
```

L'écart à la moyenne de long terme décroît géométriquement à la vitesse `α + β`. La **demi-vie** est le nombre de périodes pour que cet écart soit divisé par deux :

```
demi-vie = ln(0,5) / ln(α + β)
```

Avec `α + β = 0,95`, la demi-vie est de 13,5 jours ; avec 0,98, de 34 jours.

### 5.2 Asymétrie : GJR, EGARCH, APARCH

Sur les actions, les mauvaises nouvelles augmentent plus la volatilité que les bonnes (**effet de levier**). Trois façons de le modéliser :

**GJR-GARCH (Glosten, Jagannathan, Runkle 1993)** :

```
σ_t² = ω + ( α + γ · 1[ε_{t-1} < 0] ) · ε²_{t-1} + β · σ²_{t-1}
```

`1[·]` vaut 1 si la condition est vraie. Un choc négatif pèse `α + γ`, un positif `α`. Persistance (en supposant des chocs symétriques) : `α + γ/2 + β`.

**EGARCH (Nelson 1991)** modélise le logarithme de la variance (donc aucune contrainte de positivité sur les paramètres). Avec `e_t = ε_t / σ_t` (le choc standardisé) :

```
ln σ_t² = ω + α · ( |e_{t-1}| − √(2/π) ) + γ · e_{t-1} + β · ln σ²_{t-1}
```

(`√(2/π)` est `E|e|` pour une loi normale.) `γ < 0` signale un effet de levier. Persistance : `β`.

**APARCH (Ding, Granger, Engle 1993)** généralise en estimant l'exposant `δ` :

```
σ_t^δ = ω + α · ( |ε_{t-1}| − γ · ε_{t-1} )^δ + β · σ_{t-1}^δ
```

`δ = 2` redonne un GJR particulier ; `δ = 1` modélise l'écart-type plutôt que la variance.

### 5.3 IGARCH, RiskMetrics et FIGARCH

- **IGARCH** impose `α + β = 1` : un choc de variance est **permanent**, il n'y a pas de retour à la moyenne ni de demi-vie. Avec `ω = 0`, c'est la moyenne mobile pondérée exponentiellement (EWMA) de **RiskMetrics** :

```
σ_t² = λ · σ²_{t-1} + (1 − λ) · r²_{t-1}        λ = 0,94 en données journalières (J.P. Morgan 1996)
```

La page ajuste `λ` par maximum de vraisemblance (modèle « IGARCH ») et propose aussi `λ = 0,94` fixé comme référence dans l'onglet Prévision.
- **FIGARCH (Baillie, Bollerslev, Mikkelsen 1996)** introduit une différenciation fractionnaire de `ε²` : la variance retourne à sa moyenne **hyperboliquement** (très lentement), entre le GARCH (décroissance géométrique) et l'IGARCH (aucun retour). Son paramètre `d` mesure cette mémoire longue.
- **GARCH-M** (la variance entre dans la moyenne : `μ_t = μ + λ σ_t`, prime de risque) n'existe pas dans la bibliothèque `arch` et n'est pas implémenté (§10).

### 5.4 Lois des innovations et vraisemblance

On suppose `z_t ~ F`. La log-vraisemblance gaussienne est :

```
ℓ = −½ · Σ_t ( ln 2π + ln σ_t² + ε_t² / σ_t² )
```

Les rendements ont des queues plus épaisses qu'une normale : la page offre
- **Student** à `ν` degrés de liberté, ramenée à variance 1 : plus `ν` est petit, plus les queues sont épaisses (`ν → ∞` redonne la normale) ;
- **skew-t** de Hansen (1994) : Student asymétrique (deux paramètres, `η` et `λ`) ;
- **GED** (loi des erreurs généralisée), paramètre de forme `ν`.

*Erreurs-types.* Même si la loi est mal spécifiée, l'estimateur du maximum de vraisemblance gaussien reste convergent pour les paramètres de variance (**quasi-maximum de vraisemblance**, Bollerslev et Wooldridge 1992). La bibliothèque `arch` calcule par défaut des erreurs-types **robustes** (« sandwich ») ; la page les affiche. On ne compare pas des log-vraisemblances entre lois sans le dire : le BIC de la grille les compare, car les données sont les mêmes.

### 5.5 Diagnostics sur les résidus standardisés

On forme `z_t = ε_t / σ_t`. Si le modèle est bon, `z_t` est i.i.d. de variance 1. La page affiche :

- **Ljung-Box sur `z`** et **sur `z²`** (p > 0,05 attendu : plus de dépendance restante) ;
- **ARCH-LM sur `z`** ;
- **Jarque-Bera** et **kurtosis en excès** (un rejet de normalité est attendu si l'on a choisi la loi normale) ;
- éventuellement **BDS sur `z`**.

**Tests de signe d'Engle et Ng (1993).** Ils vérifient si le modèle a capturé l'asymétrie. Avec `S⁻_{t-1} = 1` si `z_{t-1} < 0` :

```
z_t² = a + b · S⁻_{t-1} + erreur                    test du biais de signe        (H0 : b = 0)
z_t² = a + b · S⁻_{t-1} · z_{t-1} + erreur          biais de taille négatif       (H0 : b = 0)
z_t² = a + b · (1 − S⁻_{t-1}) · z_{t-1} + erreur    biais de taille positif       (H0 : b = 0)
z_t² = a + b_1 S⁻_{t-1} + b_2 S⁻_{t-1} z_{t-1} + b_3 (1 − S⁻_{t-1}) z_{t-1} + erreur       test d'ensemble : LM = n R² ~ χ²(3)
```

Un rejet signifie que le signe ou la taille du choc d'hier **prédit encore** le carré du résidu d'aujourd'hui : le modèle ignore une asymétrie.

*Exemple simulé.* Données GJR (α = 0,03, γ = 0,12, β = 0,88, n = 4 000) : le GARCH symétrique donne BIC = 12 767,6 et un test d'ensemble de p = 1,5·10⁻⁵ (il rate le levier) ; le GJR donne BIC = 12 703,6 (64 points de mieux) et p = 0,14 (rien à redire) ; γ̂ = 0,123, proche de 0,12.

**Courbe d'impact des nouvelles (NIC).** Elle trace la variance de demain en fonction du choc d'aujourd'hui, la variance d'aujourd'hui étant fixée à sa valeur de long terme. Pour le GARCH : `σ²(ε) = ω + α ε² + β σ̄²` (parabole symétrique) ; pour le GJR : la branche gauche (ε < 0) est plus raide.

### 5.6 HAR-RV (Corsi 2009)

Le HAR-RV décrit la variance **réalisée** `RV_t` (ici le proxy de Parkinson ou de Garman-Klass, ou `r²`) comme une combinaison de moyennes sur trois horizons :

```
RV_t = c + β_d · RV_{t-1} + β_w · mean(RV_{t-5..t-1}) + β_m · mean(RV_{t-22..t-1}) + e_t
```

Les trois horizons (jour, semaine, mois) représentent des opérateurs qui réagissent à des fréquences différentes (hypothèse de marché hétérogène, Müller et al. 1997). On estime par **moindres carrés ordinaires** avec des erreurs-types de Newey-West (robustes à l'autocorrélation et à l'hétéroscédasticité des résidus). **Tous les régresseurs sont retardés** : la valeur du jour n'est jamais dans ses propres régresseurs. La somme `β_d + β_w + β_m` est la persistance.

*Réel.* Sur `^GSPC` avec Parkinson : R² = 0,542, persistance = 0,827.

### 5.7 Convergence et échelle

L'optimiseur d'un GARCH est sensible à l'échelle : avec des rendements décimaux (écart-type ≈ 0,01) les paramètres de variance sont minuscules (`ω ≈ 10⁻⁶`) et l'optimiseur peut échouer. La page **multiplie les rendements par 100** (pourcent) avant d'estimer ; `ω` est donc en %² (`scale = "percent"` dans la sortie).

Un modèle est « **non convergé** » quand l'optimiseur s'arrête sans avoir atteint un optimum (limite d'itérations, gradient non nul). Ses paramètres ne sont pas fiables. La page affiche le message de l'optimiseur et laisse le modèle dans la grille. Autres signaux : **erreurs-types manquantes** (paramètres mal identifiés ou sur une borne) ; **persistance ≈ 1** (variance quasi intégrée : la demi-vie n'est pas définie).

### 5.8 Exemples

*Simulé* (GARCH(1,1), ω = 0,05, α = 0,10, β = 0,85, n = 3 000, loi normale) : estimé ω̂ = 0,063 (± 0,017), α̂ = 0,110 (± 0,017), β̂ = 0,832 (± 0,029) ; persistance 0,942 (vraie : 0,95) ; demi-vie 11,6 jours ; volatilité annualisée inconditionnelle 16,5 % (vraie : `√(0,05/0,05) × √252 = 15,9 %`).

*Réel* (`^GSPC`, GJR-t) : μ̂ = 0,078, ω̂ = 0,022, α̂ = 0,003, γ̂ = 0,234, β̂ = 0,859, ν̂ = 5,67. Lecture : l'effet est presque entièrement **asymétrique** (α ≈ 0 : un choc positif n'ajoute presque rien ; un choc négatif pèse α + γ ≈ 0,24) ; persistance `α + γ/2 + β ≈ 0,979` donc demi-vie d'environ 33 jours ; les queues sont épaisses (`ν ≈ 5,7`, loin de la normale). Sur la grille de 9 modèles (GARCH, GJR, EGARCH × normale, Student, skew-t), le meilleur BIC bat le GARCH(1,1) normal de 298 points.

> **À retenir.** La variance est très prévisible ; GARCH décrit le regroupement, GJR/EGARCH/APARCH l'asymétrie, Student les queues épaisses. Vérifier : résidus sans dépendance, Engle-Ng non rejeté, convergence. Les paramètres décrivent le passé.

---

## 6. Régimes : Markov-switching et HMM

### 6.1 Le modèle

Au lieu d'une variance qui varie en continu (GARCH), on suppose que la série saute entre `k` **états** cachés (calme, stress), chacun avec sa moyenne et sa variance :

```
x_t = μ_{S_t} + σ_{S_t} · ε_t              S_t ∈ {1, …, k}  : état caché,   ε_t ~ N(0, 1)
P( S_t = j | S_{t-1} = i ) = p_ij          matrice de transition
```

La **durée espérée** d'un état est `1 / (1 − p_ii)` : avec `p_ii = 0,98` on reste en moyenne 50 jours dans l'état.

### 6.2 Filtre de Hamilton, filtrée contre lissée

On ne voit pas l'état. Le **filtre de Hamilton (1989)** calcule, jour après jour, la probabilité de chaque état sachant ce qu'on a observé *jusqu'à ce jour* :

```
prédiction :   ξ_{t|t-1} = P' · ξ_{t-1|t-1}                                (ξ : vecteur des probabilités d'état)
mise à jour :  ξ_{t|t}   = ( ξ_{t|t-1} ⊙ η_t ) / ( 1' (ξ_{t|t-1} ⊙ η_t) )         η_t[j] = densité gaussienne de x_t dans l'état j,  ⊙ : produit terme à terme
vraisemblance :  ℓ = Σ_t ln( 1' (ξ_{t|t-1} ⊙ η_t) )
```

On obtient la **probabilité filtrée** `P(S_t | x_1..x_t)`. Le **lissage de Kim (1994)** repasse en arrière et calcule `P(S_t | x_1..x_T)`, la **probabilité lissée**, qui utilise aussi les observations *après* `t`.

La distinction compte :
- la **filtrée** est ce qu'on aurait su ce jour-là : la seule utilisable pour décider ou comme variable d'un modèle ;
- la **lissée** est plus nette mais **regarde l'avenir** : à réserver à la description du passé.

Dans les deux cas, les paramètres (`μ_j`, `σ_j`, `p_ij`) sont estimés sur tout l'échantillon : la lecture est descriptive. La page trace les deux courbes.

### 6.3 Combien de régimes ? Les états imaginaires

Sur un bruit sans aucun régime, un modèle à deux états trouve souvent des états qui n'existent pas (il ajuste le bruit). La page compare au modèle à **un seul régime** par le BIC :

```
ΔBIC = BIC(k régimes) − BIC(1 régime)           « régimes soutenus » si ΔBIC ≤ −2, sinon « un seul régime suffit »
```

Le test du dépôt vérifie qu'à partir de bruit blanc, deux tirages sur trois concluent « un seul régime suffit ».

### 6.4 Le HMM du projet

Le projet possède un HMM gaussien (`features/regime_detection.py`, bibliothèque `hmmlearn`), estimé par l'algorithme **EM** (espérance-maximisation), avec un choix du nombre d'états par BIC (`select_n_states_bic`). La page le **réutilise** (pas de second HMM) et ajoute deux précautions :

1. **Échelle.** `hmmlearn` ajoute un plancher de `10⁻³` à la variance de chaque état (`min_covar`). Pour des rendements décimaux (variance ≈ `10⁻⁴`), ce plancher *écrase* la variance réelle et les états ne se distinguent plus. La page travaille donc en pourcent.
2. **Optima locaux.** L'EM peut s'arrêter sur un optimum local (deux états quasi identiques). La page garde le meilleur de 3 départs aléatoires, comme le fait déjà `select_n_states_bic` pour le BIC.

L'état de **stress** est celui de plus forte variance ; la probabilité affichée est la probabilité **filtrée** de cet état (algorithme avant écrit à la main, jamais `predict_proba`, qui lisse).

*Réel* (`^GSPC`, 2016-2026) : le Markov-switching à 2 régimes bat le régime unique de 1 121 points de BIC ; le HMM retient 3 états.

> **À retenir.** Filtrée = ce qu'on savait ; lissée = ce qu'on sait maintenant. Comparer à un seul régime par le BIC ; un régime « trouvé » n'existe pas forcément.

---

## 7. Prévision hors échantillon et comparaison de modèles

Un modèle peut très bien décrire le passé et mal prévoir : il a vu les données. Prévoir, c'est n'utiliser que le passé.

### 7.1 La procédure

Pour chaque date `j` après un apprentissage minimal (750 jours par défaut) :

- les **paramètres** sont estimés sur les données **antérieures au bloc** qui contient `j` : fenêtre **expansive** (tout le passé) ou **glissante** (les `W` derniers jours) ;
- on les **réestime tous les `k` jours** (60 par défaut) ; entre deux réestimations, ils sont **figés** (`arch.fix`) et seul le filtre de variance avance : `σ_j²` ne dépend que des rendements jusqu'à `j − 1` ;
- on obtient `σ̂_j²` et des quantiles de rendement pour la VaR.

Le test du dépôt vérifie l'absence de fuite : les prévisions calculées sur la série tronquée à une date sont identiques à celles calculées sur la série entière aux mêmes dates.

### 7.2 Évaluer une prévision de variance avec un proxy bruité

On compare `σ̂_j²` à un proxy `P_j` de la vraie variance (`r_j²` ou Parkinson). Comme le proxy est bruité (§1.2), toutes les fonctions de perte ne sont pas admissibles. Patton (2011) montre que seules certaines familles classent correctement les modèles malgré le bruit. Deux sont retenues :

```
QLIKE(P, h) = P/h − ln(P/h) − 1          (≥ 0 ; nul seulement si h = P)
Erreur quadratique (MSE)(P, h) = (P − h)²
```

Le **QLIKE** pénalise davantage la sous-prévision que la sur-prévision : sous-estimer la variance coûte plus cher (en risque) que la surestimer. Il est moins dominé par les journées extrêmes que la MSE.

*Exemple simulé* (GARCH(1,1), vraie variance connue, proxy `r²`, n = 3 000) : perte moyenne avec la vraie variance : QLIKE = 1,286, MSE = 3,61 ; avec la variance doublée : 1,476 et 5,04 ; avec la variance divisée par deux : 1,600 et 4,11. La vérité a la perte minimale, **malgré** un proxy très bruité ; la sous-prévision (×0,5) est pénalisée plus que la sur-prévision (×2) par le QLIKE (1,600 contre 1,476).

### 7.3 Régression de Mincer-Zarnowitz

On régresse le proxy sur la prévision : `P_j = a + b · σ̂_j² + e_j` (erreurs de Newey-West). Une prévision sans biais a `a = 0` et `b = 1` ; la page teste les deux ensemble (test de Wald). `b < 1` : les prévisions sont trop dispersées ; `b > 1` : trop timides. Si la prévision est constante, la pente n'est pas identifiable (résultat « dégénéré » affiché comme tel).

### 7.4 Diebold-Mariano

Pour comparer deux modèles `A` et `B`, on forme la différence de pertes `d_t = L(A)_t − L(B)_t`. Sous H0 (même précision), `E[d_t] = 0`. La statistique :

```
DM = d̄ / √( LRV(d) / T )          LRV : variance de long terme de d (autocorrélation prise en compte)
```

On applique la correction de petit échantillon de Harvey, Leybourne et Newbold (1997) et la loi de Student. C'est la fonction du projet (`validation/diebold_mariano.py`, ADR 0003) : à un pas (`h = 1`, le cas de cette page) il faut au moins 10 observations ; à un horizon `h > 1`, où les pertes voisines se recouvrent, elle **refuse de conclure** sous 15 blocs indépendants (`n / h`). `DM < 0` : le modèle `A` perd moins que la référence. La page compare chaque modèle à une **référence** (RiskMetrics par défaut) et corrige les p-values du nombre de comparaisons par Benjamini-Hochberg.

### 7.5 Model Confidence Set

Quand on compare beaucoup de modèles, le « meilleur » peut l'être par chance. Le **Model Confidence Set** (Hansen, Lunde, Nason 2011) renvoie l'ensemble des modèles qu'on **ne peut pas exclure** au niveau choisi (90 % ici). Procédure : tester « tous les modèles de l'ensemble ont la même perte espérée » ; si rejeté, éliminer le pire, recommencer ; s'arrêter au premier non-rejet. Les p-values sont obtenues par **bootstrap par blocs** (qui respecte l'autocorrélation des pertes). **Lecture :** les modèles « dans le MCS » ne sont pas distinguables ; ceux qui en sont sortis sont significativement pires. Un MCS qui contient tout le monde est une information : les données ne permettent pas de départager.

### 7.6 Backtest de la VaR

La **Value-at-Risk** à 1 % est le seuil sous lequel le rendement du jour doit tomber 1 fois sur 100. Ici le seuil est `μ + σ̂_j · q`, où `q` est le quantile à 1 % (ou 5 %) des résidus standardisés du bloc d'estimation (simulation historique filtrée : elle capte les queues épaisses sans supposer de loi). Un **dépassement** est un rendement inférieur au seuil.

**Test de Kupiec (1995)** : le taux de dépassements vaut-il le niveau `p` ? Avec `x` dépassements sur `n` jours et `π̂ = x/n` :

```
LR_pof = −2 · ln[ (1 − p)^{n−x} · p^x ] + 2 · ln[ (1 − π̂)^{n−x} · π̂^x ]        ~ χ²(1) sous H0 (taux = p)
```

**Test d'indépendance de Christoffersen (1998)** : les dépassements arrivent-ils en grappes ? On modélise « dépassement ou non » par une chaîne de Markov d'ordre 1 ; avec `n_ij` le nombre de passages de l'état `i` à l'état `j` :

```
LR_ind = −2 · ln( L(π) / L(π_01, π_11) )       ~ χ²(1)     π_01 = n_01/(n_00+n_01),  π_11 = n_11/(n_10+n_11)
LR_cc  = LR_pof + LR_ind                       ~ χ²(2)     (test conjoint : bon taux ET indépendance)
```

*Exemple.* 10 dépassements en 250 jours au niveau 1 % (4 %, au lieu de 2,5 attendus) : LR_pof = 12,96, p = 0,0003 (modèle rejeté) ; avec 2 dépassements, LR = 0,11, p = 0,74 (compatible). Une VaR à variance **constante** sur une série à volatilité groupée dépasse en grappes : l'indépendance est rejetée ; la vraie VaR conditionnelle n'est pas rejetée (testé sur 5 tirages).

### 7.7 Exemple réel

`^GSPC`, 1 762 dates hors échantillon, proxy `r²`, 3 modèles réestimés tous les 60 jours (30 réestimations chacun, aucun échec ni non-convergence) :

| Modèle | QLIKE moyen | Pente de Mincer-Zarnowitz | DM vs RiskMetrics (p corrigé) | Dans le MCS 90 % | Dépassements à 1 % |
|---|---|---|---|---|---|
| GJR-GARCH Student | 1,5225 | 0,83 | 0,170 | oui | 19 (1,08 %) |
| GARCH(1,1) normal | 1,5285 | 0,95 | 0,036 | oui | 17 (0,96 %) |
| RiskMetrics (λ = 0,94) | 1,5742 | 0,88 | (référence) | **non** | 41 (2,33 %, Kupiec p < 0,001) |

Lecture : les deux GARCH ne sont pas distinguables entre eux (tous deux dans le MCS) ; RiskMetrics est exclu du MCS et sous-estime le risque extrême (41 dépassements au lieu d'environ 18 attendus à 1 % sur 1 762 jours). Un détail à ne pas sur-interpréter : le GARCH(1,1) normal est déclaré meilleur que RiskMetrics par Diebold-Mariano corrigé (p = 0,036) alors que le GJR-Student, dont le QLIKE moyen est pourtant plus bas, ne l'est pas (p = 0,17). Le DM compare la différence de pertes **jour par jour** et tient compte de sa variabilité : un écart moyen plus grand peut être plus bruité. C'est une raison de plus de lire l'ensemble (MCS, DM, MZ, VaR) plutôt que le seul QLIKE moyen.

> **À retenir.** Prévoir = paramètres estimés sur le passé seulement, réestimés régulièrement. Juger par QLIKE (robuste au bruit du proxy), puis MZ, DM corrigé et MCS ; ne jamais lire le seul rang. Valider la VaR par Kupiec ET Christoffersen.

---

## 8. Multivarié : VAR, Johansen, VECM

Onglet « Multivarié » de `/exploration`. Il s'applique à la sélection d'actifs de la page.

### 8.1 Le VAR

Un **vecteur autorégressif** relie chaque série à son passé et à celui des autres. Pour `y_t` un vecteur de `k` rendements :

```
y_t = c + A_1 y_{t-1} + … + A_p y_{t-p} + u_t        u_t : chocs, de matrice de covariance Σ
```

`A_i[a][b]` est l'effet de la variable `b` au retard `i` sur l'équation de `a`. L'ordre `p` est choisi par le BIC (entre 1 et un maximum).

**Stabilité.** On écrit le VAR(p) sous forme d'un VAR(1) plus grand (la **matrice compagnon**). Le système est stable si toutes ses valeurs propres sont de module < 1 : alors un choc finit par s'éteindre. La page affiche « stable » ou « instable ».

### 8.2 Réponses impulsionnelles

Un VAR stable est une moyenne mobile infinie : `y_t = μ + Σ_h Ψ_h u_{t-h}`. `Ψ_h` mesure l'effet, `h` périodes plus tard, d'un choc `u`. Les chocs `u` sont **corrélés** entre séries, donc « un choc sur la série 1 seule » n'a pas de sens direct. On **orthogonalise** par la décomposition de Cholesky de la covariance :

```
Σ = P · P'          (P triangulaire inférieure)          Θ_h = Ψ_h · P         (réponse à un choc ORTHOGONAL d'un écart-type)
```

**Conséquence importante.** Le résultat dépend de l'**ordre** des séries : la première ne réagit pas *à l'instant 0* aux chocs des suivantes, la deuxième réagit à la première, etc. L'ordre de la page est celui de la sélection ; la lecture doit en tenir compte.

Les **bandes à 90 %** sont obtenues par Monte-Carlo : on simule 200 séries du VAR estimé (chocs gaussiens de covariance `Σ`, graine fixe), on réestime le VAR sur chacune, on prend les quantiles 5 % et 95 % des réponses. *Remarque d'ingénierie :* la fonction `irf_resim` de statsmodels repasse la **même graine** à chaque réplication ; avec une graine fixée, les 200 séries sont identiques et la bande s'effondre en un point. La page écrit donc sa propre boucle (test de non-régression dans le dépôt).

### 8.3 Décomposition de la variance de l'erreur de prévision (FEVD)

Quelle part de l'incertitude sur la série `i` à l'horizon `H` vient des chocs de la série `j` ?

```
ω_{ij}(H) = Σ_{h=0..H-1} (Θ_h[i][j])²  /  Σ_{j'} Σ_{h=0..H-1} (Θ_h[i][j'])²           Σ_j ω_{ij}(H) = 1
```

Elle dépend elle aussi de l'ordre de Cholesky.

### 8.4 Cointégration

Deux prix peuvent chacun dériver (racine unitaire) et pourtant rester **liés** : leur écart `y_t − β x_t` est stationnaire. On dit qu'ils sont **cointégrés** (Engle et Granger 1987). Exemple : `x_t` marche aléatoire, `y_t = 2 x_t + bruit stationnaire`. C'est une relation de **niveaux** : on travaille donc sur le **log des prix**, pas sur les rendements (qui effacent la relation de long terme).

**Le VECM.** Le modèle à correction d'erreur s'écrit :

```
Δy_t = Π · y_{t-1} + Γ_1 Δy_{t-1} + … + Γ_{p-1} Δy_{t-p+1} + c + u_t          Π = α · β'
```

- `β` : les **relations de long terme** (les vecteurs de cointégration) ;
- `α` : les **vitesses d'ajustement**, c'est-à-dire de combien chaque série corrige l'écart à la relation de long terme `β' y_{t-1}` à chaque période.

Le **rang** `r` de `Π` est le nombre de relations de long terme : `r = 0` aucune (les séries dérivent indépendamment), `r = k` toutes stationnaires, `0 < r < k` cointégration.

### 8.5 Test de Johansen

Johansen (1988, 1991) estime `Π` sans imposer son rang, calcule les valeurs propres `λ̂_1 > … > λ̂_k` d'un problème de corrélations canoniques, et teste le rang par la **statistique de la trace** :

```
λ_trace(r) = − T · Σ_{i = r+1..k} ln(1 − λ̂_i)           H0 : rang ≤ r
```

(la statistique de la **valeur propre maximale** `−T ln(1 − λ̂_{r+1})` teste « rang = r » contre « rang = r+1 »). Les valeurs critiques ne sont pas celles d'un χ² ; elles sont tabulées (statsmodels). La page teste de `r = 0` vers le haut et retient le **premier rang non rejeté** à 5 %. Les vecteurs de cointégration sont **normalisés** sur la première série.

*Exemple simulé* (`x` marche aléatoire, `y = 2x + AR(1)`, n = 1 500, constante, 1 retard) :

| Hypothèse (H0 : rang ≤ r) | Statistique de la trace | Valeur critique à 5 % | Décision |
|---|---|---|---|
| r = 0 | 340,5 | 15,49 | rejeté |
| r = 1 | 0,3 | 3,84 | non rejeté |

Rang retenu : 1. Vecteur de cointégration normalisé : `(1 ; −0,501)`, soit `x − 0,5 y ≈ stationnaire`, équivalent à `y ≈ 2x`.

**Lecture du VECM sur ce rang.** L'**écart** `ECT_t = β' y_t` (centré) est stationnaire. Pour un rang 1, son coefficient de retour vers sa moyenne est `vitesse = β' α` ; l'écart suit en gros `ECT_t ≈ (1 + vitesse) · ECT_{t-1} + bruit`. La **demi-vie** de l'écart est :

```
demi-vie = ln(0,5) / ln(1 + vitesse)          (si −1 < vitesse < 0)
```

*Exemple simulé* : `vitesse = −0,511`, demi-vie = 0,97 période : un écart est comblé de moitié en une période. Les vitesses α estimées sont (−0,001 ; 1,017) : c'est la série `y` qui corrige l'écart, `x` ne bouge pas (elle guide le long terme).

*Réel* (`^GSPC`, `^NDX`, `XLK`, log des cours, 2021-2026, constante, 1 retard) : le test ne détecte aucune relation de long terme (rang 0) ; le VAR(1) sur les rendements est stable.

> **À retenir.** VAR sur les rendements : lire les réponses avec leur ordre de Cholesky. Cointégration sur les log-niveaux : le rang compte les relations de long terme ; vitesse et demi-vie disent à quelle vitesse un écart se résorbe.

---

## 9. Pièges : la check-list

1. **Un modèle ajusté sur tout l'échantillon n'est pas une prévision.** Utiliser l'onglet Prévision (réestimation sur le passé).
2. **Ne jamais exporter un GARCH estimé sur tout l'échantillon comme variable d'apprentissage d'un modèle ML** : c'est une fuite d'information. Il faut réestimer pli par pli et utiliser la variance filtrée, jamais lissée (le projet le fait déjà pour EGARCH, HMM, Kalman et résidu ARIMA via `fit_end_idx`).
3. **Chasse au meilleur modèle.** 20 spécifications sur 66 séries donnent des « gagnants » par pur hasard. Compter les essais, corriger (Benjamini-Hochberg), lire le MCS plutôt que le rang.
4. **`r²` est un proxy très bruité** (écart-type 1,41 fois sa moyenne) : utiliser QLIKE/MSE, et Parkinson ou Garman-Klass quand les prix OHLC existent.
5. **Convergence.** Lire la colonne « Convergence », les erreurs-types manquantes, la persistance ≈ 1. Un résultat non convergé est un résultat de moindre valeur, pas une absence de résultat.
6. **Fréquences mixtes.** Quotidien et mensuel séparément ; saisonnalité seulement sur le mensuel.
7. **Un test à 5 % se trompe 1 fois sur 20**, même quand tout va bien ; regarder plusieurs tests et plusieurs tirages.
8. **Ordre de Cholesky** pour les réponses impulsionnelles et la FEVD.
9. **Échelle.** Les paramètres de variance sont en %² : `ω` n'est pas comparable à un `ω` en décimal.
10. **Une moyenne qui « bat la constante » en échantillon n'est pas exploitable** : épisodes extrêmes, ΔBIC dominé par quelques semaines. Vérifier hors échantillon.

---

## 10. Ce qui n'est pas fait, et pourquoi

| Élément | Raison |
|---|---|
| **GARCH-M** | N'existe pas dans `arch` ; à implémenter à la main (la variance conditionnelle entre dans la moyenne : `μ_t = μ + λ σ_t`). Peu utile en journalier. |
| **ARFIMA exact** | N'existe pas dans `statsmodels`. La page donne l'estimateur de `d` (GPH), pas l'estimation conjointe d'un ARFIMA(p,d,q). |
| **Bai-Perron** (plusieurs ruptures) | N'existe pas dans `statsmodels` ; `ruptures` fait de la détection de points de changement, ce qui n'est pas le même test. Zivot-Andrews (une rupture) est proposé. |
| **DCC-GARCH** | Les corrélations dynamiques d'Engle (2002) ne sont pas dans `arch`. Le modèle : `Q_t = (1 − a − b) Q̄ + a z_{t-1} z'_{t-1} + b Q_{t-1}`, `R_t = diag(Q_t)^{-1/2} Q_t diag(Q_t)^{-1/2}`, `H_t = D_t R_t D_t` (D : écarts-types GARCH univariés). À brancher ensuite sur la covariance de `/portfolio` (`tracking/covariance.py`) ; implémentation maison à tester sur un processus simulé. Non fait. |
| **Pont vers l'apprentissage automatique** (variables GJR, APARCH, HAR en walk-forward) | Ajouter des variables au pipeline change l'empreinte de configuration de tous les runs et invalide le golden master (régénération via une branche dédiée). À faire en option, hors de l'empreinte par défaut, comme l'interrupteur de l'ADR 0012. Non fait. |
| **EVT (queues GPD), ondelettes, entropie** | Backlog du cadrage. |

---

## 11. Carte du code

Chemins relatifs à `patrick/`.

| Sujet | Module (fonctions) | Tests |
|---|---|---|
| Processus simulés | `patrick/econometrics/simulate.py` (`garch11`, `arma`, `arfima`, `random_walk`) | `test_econometrics_basics.py` |
| Transformations | `econometrics/transforms.py` (`apply_transform`, `parkinson_variance`, `garman_klass_variance`) | `test_econometrics_basics.py` |
| Stationnarité | `econometrics/unitroot.py` (`unit_root_tests`, `cross_verdict`, `zivot_andrews`) ; ratio de variance et Hurst : `exploration/studies.py` | `test_econometrics_basics.py` |
| Dépendance | `econometrics/serial.py` (`dependence_summary`, `bds_test`) ; ACF/Ljung-Box/ARCH-LM : `exploration/studies.py::memory` | `test_econometrics_basics.py` |
| Moyenne | `econometrics/mean_models.py` (`fit_arma_grid`, `gph_d`) | `test_econometrics_mean.py` |
| Variance | `econometrics/variance_models.py` (`fit_variance_model`, `fit_variance_grid`, `fit_har`, `engle_ng`) | `test_econometrics_variance.py` |
| Régimes | `econometrics/regimes.py` (`markov_switching`, `hmm_reading`) ; HMM : `features/regime_detection.py` | `test_econometrics_regimes.py` |
| Prévision | `econometrics/forecast_eval.py` (`variance_forecasts`, `compare_forecasts`, `kupiec_pof`, `christoffersen`, `evaluate_forecasts`) | `test_econometrics_forecast.py` |
| Multivarié | `econometrics/multivariate.py` (`var_analysis`, `johansen`, `vecm`) | `test_econometrics_multivariate.py`, `test_exploration_multivariate.py` |
| Cache des résultats | `webapp/econometrics_cache.py` | `test_econometrics_routes.py` |
| Routes et page | `webapp/econometrics_routes.py`, `templates/econometrics.html`, `static/econometrics.js`, `webapp/i18n_econometrics.py` ; multivarié : `webapp/exploration_routes.py`, `static/exploration.js` | `test_econometrics_routes.py`, `test_exploration_multivariate.py` |
| Comparaison et correction | `validation/diebold_mariano.py`, `validation/fdr.py` (existants, réutilisés) | tests existants |

Cadrage de la conception : `docs/superpowers/specs/2026-11-03-econometrie-serie-design.md`.

---

## 12. Exercices avec la page

1. **Marche aléatoire contre rendement.** Chargez `^GSPC`, transformation « log-rendement », onglet Stationnarité : lisez le tableau (quatre tests) et le verdict. Passez ensuite la transformation à « différence fractionnaire » avec `d = 0,4` : comparez.
2. **Les trois faits stylisés.** Onglet Dépendance sur un indice : relevez `ρ̂_1` (proche de 0), l'ACF de `x²` (positive sur de nombreux retards), le rejet ARCH-LM. Refaites sur une série FRED mensuelle : que devient le regroupement de volatilité ?
3. **La constante est dure à battre.** Onglet Moyenne sur 5 actifs différents : combien « battent » la constante ? Regardez la colonne « p corrigé » : combien survivent à la correction ?
4. **L'effet de levier.** Onglet Variance : ajustez GARCH (normale) puis GJR (normale) sur une action. Comparez BIC, γ, et le test d'ensemble d'Engle-Ng. Tracez la courbe d'impact des nouvelles : est-elle symétrique ?
5. **Les queues.** Même modèle, loi normale puis Student : comparez le BIC et `ν̂`. Que dit le QQ-plot ?
6. **Convergence.** Dans la grille, cochez FIGARCH et GED : y a-t-il des échecs ou des non-convergences ? Où sont-ils affichés ?
7. **Prévoir pour de vrai.** Onglet Prévision : comparez GARCH, GJR-t et RiskMetrics. Lisez dans l'ordre : QLIKE, MCS, DM corrigé, puis les dépassements de VaR. Un modèle gagne-t-il *et* passe-t-il Kupiec ?
8. **Cointégration.** Dans `/exploration`, sélectionnez deux ETF d'un même secteur, onglet Multivarié : le rang de Johansen est-il 1 ? Si oui, lisez la demi-vie de l'écart.

---

## 13. Références

Les références sont données par auteur et année, sans lien.

- Baillie, Bollerslev, Mikkelsen (1996). Fractionally integrated generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics*.
- Benjamini, Hochberg (1995). Controlling the false discovery rate. *Journal of the Royal Statistical Society B*.
- Bollerslev (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics*.
- Bollerslev, Wooldridge (1992). Quasi-maximum likelihood estimation and inference in dynamic models with time-varying covariances. *Econometric Reviews*.
- Brock, Dechert, Scheinkman, LeBaron (1996). A test for independence based on the correlation dimension. *Econometric Reviews*.
- Chow, Denning (1993). A simple multiple variance ratio test. *Journal of Econometrics*.
- Christoffersen (1998). Evaluating interval forecasts. *International Economic Review*.
- Cont (2001). Empirical properties of asset returns: stylized facts and statistical issues. *Quantitative Finance*.
- Corsi (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics*.
- Dickey, Fuller (1979). Distribution of the estimators for autoregressive time series with a unit root. *Journal of the American Statistical Association*.
- Diebold, Mariano (1995). Comparing predictive accuracy. *Journal of Business and Economic Statistics*.
- Ding, Granger, Engle (1993). A long memory property of stock market returns and a new model. *Journal of Empirical Finance*.
- Elliott, Rothenberg, Stock (1996). Efficient tests for an autoregressive unit root. *Econometrica*.
- Engle (1982). Autoregressive conditional heteroscedasticity with estimates of the variance of United Kingdom inflation. *Econometrica*.
- Engle (2002). Dynamic conditional correlation. *Journal of Business and Economic Statistics*.
- Engle, Granger (1987). Co-integration and error correction. *Econometrica*.
- Engle, Ng (1993). Measuring and testing the impact of news on volatility. *Journal of Finance*.
- Garman, Klass (1980). On the estimation of security price volatilities from historical data. *Journal of Business*.
- Geweke, Porter-Hudak (1983). The estimation and application of long memory time series models. *Journal of Time Series Analysis*.
- Glosten, Jagannathan, Runkle (1993). On the relation between the expected value and the volatility of the nominal excess return on stocks. *Journal of Finance*.
- Granger, Newbold (1974). Spurious regressions in econometrics. *Journal of Econometrics*.
- Hamilton (1989). A new approach to the economic analysis of nonstationary time series and the business cycle. *Econometrica*. Hamilton (1994), *Time Series Analysis*, Princeton University Press.
- Hansen (1994). Autoregressive conditional density estimation. *International Economic Review*.
- Hansen, Lunde, Nason (2011). The model confidence set. *Econometrica*.
- Harvey, Leybourne, Newbold (1997). Testing the equality of prediction mean squared errors. *International Journal of Forecasting*.
- Hurst (1951). Long-term storage capacity of reservoirs. *Transactions of the American Society of Civil Engineers*.
- Johansen (1988). Statistical analysis of cointegration vectors. *Journal of Economic Dynamics and Control*. Johansen (1991). *Econometrica*.
- Kim (1994). Dynamic linear models with Markov-switching. *Journal of Econometrics*.
- Kupiec (1995). Techniques for verifying the accuracy of risk measurement models. *Journal of Derivatives*.
- Kwiatkowski, Phillips, Schmidt, Shin (1992). Testing the null hypothesis of stationarity against the alternative of a unit root. *Journal of Econometrics*.
- Ljung, Box (1978). On a measure of lack of fit in time series models. *Biometrika*.
- Lo, MacKinlay (1988). Stock market prices do not follow random walks. *Review of Financial Studies*.
- López de Prado (2018). *Advances in Financial Machine Learning*, chapitre 5 (différenciation fractionnaire). Wiley.
- Lütkepohl (2005). *New Introduction to Multiple Time Series Analysis*. Springer.
- McLeod, Li (1983). Diagnostic checking of ARMA time series models using squared-residual autocorrelations. *Journal of Time Series Analysis*.
- Müller, Dacorogna, Davé, Olsen, Pictet, von Weizsäcker (1997). Volatilities of different time resolutions. *Journal of Empirical Finance*.
- Nelson (1991). Conditional heteroskedasticity in asset returns: a new approach. *Econometrica*.
- Newey, West (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. *Econometrica*.
- Parkinson (1980). The extreme value method for estimating the variance of the rate of return. *Journal of Business*.
- Patton (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*.
- Phillips, Perron (1988). Testing for a unit root in time series regression. *Biometrika*.
- Raftery (1995). Bayesian model selection in social research. *Sociological Methodology*.
- Sims (1980). Macroeconomics and reality. *Econometrica*.
- Tsay (2010). *Analysis of Financial Time Series*, 3ᵉ éd. Wiley.
- Zivot, Andrews (1992). Further evidence on the Great Crash, the oil-price shock, and the unit-root hypothesis. *Journal of Business and Economic Statistics*.
