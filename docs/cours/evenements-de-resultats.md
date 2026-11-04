# Cours : les événements de résultats, la méthode et les maths derrière la page `/resultats`

> Version du 3 novembre 2026. Ce cours décrit le code tel qu'il est fusionné dans `main` (`patrick/patrick/earnings/`, ADR 0016, `ENGINE_VERSION = 3`).
> Quand le cours et le code diffèrent, **le code fait foi** : chaque chapitre cite la fonction qui calcule la chose décrite.
> Rien ici n'est un conseil d'achat, de vente ou de conservation : le cours explique comment on mesure et ce qu'on a le droit de conclure.

## Comment lire ce cours

**Pour qui.** Pour quelqu'un qui fait de l'analyse financière et ne code pas. Il faut savoir ce qu'est une moyenne, un écart-type et une droite de régression ; tout le reste est défini quand il apparaît. Les formules sont écrites pour être lues, pas pour être refaites à la main : le programme les calcule, le cours dit **ce qu'elles veulent dire** et **quand elles trompent**.

**Où les formules s'affichent.** Dans VS Code, ouvrir ce fichier puis `Ctrl+Maj+V` (aperçu Markdown : les formules sont rendues). Sur GitHub aussi.

**Structure d'un chapitre.** Quatre blocs, toujours dans le même ordre :

- **L'idée** : la question posée, en mots.
- **Les maths** : la formule et d'où elle vient.
- **Dans le programme** : quel fichier, quelle fonction, quels réglages par défaut.
- **Les pièges** : comment ça se trompe.

**Les chiffres des exemples** ne sont pas inventés à la main : ils ont été calculés avec les fonctions du programme (et les simulations avec les tests du programme). Quand un chiffre vient d'une simulation, c'est écrit.

**Plan.**

| Partie | Chapitres | Question |
|---|---|---|
| I. Mesurer un événement | 1 à 5 | Quel jour regarder, quel rendement était « attendu », de combien le titre s'en écarte-t-il ? |
| II. Savoir si c'est significatif | 6 à 11 | L'écart moyen sur N annonces est-il réel ou dû au hasard ? |
| III. Les familles d'études | 12 à 17 | Que mesure chacune des 54 cartes, avec quelle formule ? |
| IV. Modéliser et décider | 18 à 24 | Peut-on prédire l'amplitude ou le sens ? Une stratégie survit-elle à l'honnêteté statistique ? |
| V. Lire un résultat | 25 à 27 | Ce que les données gratuites interdisent, check-list de lecture, exercices corrigés. |

Annexes : glossaire, correspondance carte → méthode → fichier, bibliographie.

---

## Table des notations

| Symbole | Sens |
|---|---|
| $i$ | un événement (une annonce de résultats d'un titre) ; $N$ = nombre d'événements |
| $t$ | une **séance relative** : $t=0$ est J0, le jour où le cours réagit ; $t=-1$ la séance d'avant, etc. |
| $P_t$, $R_t$ | cours de clôture ajusté et rendement **simple** du titre : $R_t = P_t/P_{t-1}-1$ |
| $R_{m,t}$, $RF_t$ | rendement de l'indice de marché local, taux sans risque |
| $\mathbf{x}_t$, $\boldsymbol\theta$ | variables explicatives du jour $t$ (constante, marché, ...) et coefficients du modèle de rendement attendu |
| $\mu$, $\beta$ | constante et « bêta » du modèle de marché |
| $T$ | nombre de séances de la fenêtre d'estimation ; $k$ = nombre de coefficients ; $T-k$ = degrés de liberté |
| $\hat\sigma$ | écart-type résiduel **quotidien** du titre (estimé sur la fenêtre d'estimation) |
| $AR_t$ | rendement anormal du jour $t$ (réel moins attendu) |
| $[a,b]$ | fenêtre d'événement, de la séance relative $a$ à $b$ ; $L=b-a+1$ jours |
| $CAR_i[a,b]$ | rendement anormal cumulé de l'événement $i$ sur la fenêtre |
| $CAAR[a,b]$ | moyenne des CAR sur les événements |
| $SCAR_i$ | CAR standardisé : $CAR_i$ divisé par son écart-type estimé |
| $\bar r$ | corrélation moyenne entre événements (chapitre 7) |
| $p$, $q$ | p-value brute, p-value corrigée du FDR |
| $\alpha$ | niveau d'un test (5 % ou 10 % selon le contexte) |
| $\Phi$ | fonction de répartition de la loi normale centrée réduite ; $\Phi^{-1}$ son inverse |

Les **rendements simples** sont utilisés partout (pas les logarithmiques), ce qui fait que « +4,2 % » se lit tel quel.

---

# Partie I. Mesurer un événement

## Chapitre 1. Pourquoi une étude d'événement

### L'idée

Un jour de publication de résultats, le cours d'un titre bouge pour deux raisons mélangées :

1. ce que **tout le marché** (ou son secteur) fait ce jour-là ;
2. l'information **propre à l'annonce**.

On veut isoler la seconde. Une **étude d'événement** (en anglais *event study*) compare le rendement observé au rendement que le titre « aurait eu » sans l'événement. L'écart s'appelle le **rendement anormal** : *anormal* ne veut pas dire bizarre, seulement « non expliqué par le modèle de rendement attendu ».

L'hypothèse de départ est celle d'un marché efficace : tout ce qui est prévisible dans les résultats est déjà dans le cours **avant** la publication. Seule la **surprise** (ce qui n'était pas attendu) devrait faire bouger le cours. Deux conséquences que le cours reprend sans cesse :

- la **direction** (hausse ou baisse) est très difficile à prévoir : la moyenne des réactions sur beaucoup d'annonces est proche de zéro, parce que hausses et baisses s'annulent ;
- l'**amplitude** (de combien ça bouge, quel que soit le sens) est, elle, en partie prévisible : un titre volatil, peu suivi, ou dont les annonces ont toujours été violentes, bougera probablement beaucoup.

La page `/resultats` pose donc trois questions distinctes, avec trois outils distincts :

| Question | Outil | Chapitres |
|---|---|---|
| Le titre bouge-t-il **en moyenne** dans un sens ? | CAAR et tests de significativité | 5 à 7 |
| Bouge-t-il **plus que d'habitude**, quel que soit le sens ? | test d'amplitude | 8 |
| Peut-on **prévoir** l'amplitude ou le sens avant l'annonce ? | modèles en panel, validés hors échantillon | 19 à 22 |

### Le fil de données, de la newsletter à la carte

```
newsletter collée ──► noms de sociétés ──► symboles Yahoo ──► dates d'annonce + heure (BMO / AMC)
        (parse)            (resolve)             (écran de confirmation)       (schedule, exchanges)
                                                        │
                      cours ajustés + indice + facteurs + secteur ◄─── provider (Yahoo, gratuit)
                                                        │
                    par événement : J0, modèle attendu, AR, CAR, variance, volumes, liquidité  (engine)
                                                        │
                         tableau « un événement par ligne » + historique point-in-time  (panel)
                                                        │
          54 cartes d'étude (studies/) ──► cache ──► registre FDR  ──► page /resultats
```

Chaque flèche est un fichier du dossier [`patrick/patrick/earnings/`](../../patrick/patrick/earnings/). Le chapitre 2 traite de « quel jour », les chapitres 3 à 5 de « quel écart ».

### Les pièges

- **Confondre « significatif » et « important »** : un effet de 0,1 % peut être très significatif sur 5 000 annonces et sans intérêt économique ; l'inverse arrive sur 12 annonces.
- **Confondre l'absence de preuve et la preuve d'absence** : avec peu d'annonces, un test qui ne rejette pas dit surtout que l'échantillon est trop petit (chapitre 6, puissance).

---

## Chapitre 2. Le temps : quel est J0 ?

### L'idée

Une annonce a une **date** et une **heure**. Le cours, lui, ne réagit qu'aux heures où la Bourse est ouverte. Le jour qui nous intéresse n'est donc pas « le jour de l'annonce » mais **la première séance dont le cours intègre la nouvelle**. On l'appelle **J0** (jour 0).

- **BMO** (*before market open*, avant l'ouverture) : la nouvelle est publiée avant l'ouverture, la réaction est dans la séance **du même jour**.
- **AMC** (*after market close*, après la clôture) : la nouvelle sort après la fermeture, la réaction est dans la séance **suivante**.
- **DURING** : publication pendant la séance. La réaction commence le jour même **et déborde** sur le lendemain.
- **UNKNOWN** : heure absente. Même traitement que DURING.

### Les maths

Soit $d$ la date d'annonce et $S$ l'ensemble des séances du titre. Alors

$$
J0 = \begin{cases}
\min\{\, s \in S : s > d \,\} & \text{si AMC},\\[2pt]
\min\{\, s \in S : s \ge d \,\} & \text{sinon (BMO, DURING, UNKNOWN, ou } d \text{ sans séance : samedi, férié).}
\end{cases}
$$

La **fenêtre de réaction** est $[0,0]$ si l'heure est connue et hors séance, et $[0,+1]$ sinon (DURING, UNKNOWN, ou timing « incertain »). Les séances relatives sont comptées **en séances du titre lui-même** : $t=+1$ est la séance suivante de cette place, pas le lendemain calendaire.

Le programme stocke pour chaque événement la **trajectoire** des séances $t \in [-10,\,+60]$ autour de J0, soit 71 valeurs par grandeur.

### Dans le programme

- [`exchanges.day_zero`](../../patrick/patrick/earnings/exchanges.py) implémente la règle ci-dessus ; [`exchanges.classify_timing`](../../patrick/patrick/earnings/exchanges.py) classe l'heure en BMO, AMC, DURING ou UNKNOWN selon les horaires d'ouverture de la place (Paris 9 h-17 h 30, New York 9 h 30-16 h, Tokyo 9 h-15 h 30 depuis le 5 novembre 2024, etc.).
- Réglage `reaction` : `auto` (défaut : $[0]$ si timing certain, sinon $[0,+1]$), `d0`, `d01` ([`EarningsConfig`](../../patrick/patrick/earnings/config.py)).

### Les pièges (tous rencontrés sur le vrai Yahoo)

- **Yahoo donne toutes les heures en heure de New York**, même pour Paris, Copenhague ou Tokyo. Une publication à 07:00 à Copenhague apparaît à 01:00 New York. Lue telle quelle, elle serait classée à tort « avant l'ouverture américaine ». Le programme **reconvertit** dans le fuseau de la place avant de classer.
- **11:00 à New York sur une date à venir est une heure fantôme** (valeur par défaut de Yahoo, vue sur LVMH, Diageo, Air France...). Elle est traitée comme heure inconnue, avec un repli par place : les émetteurs européens publient en général avant l'ouverture (BMO), les japonais après la clôture (AMC), et pour les États-Unis il n'y a pas de repli honnête (UNKNOWN).
- **Choisir J0 « là où le mouvement est le plus gros » est interdit.** Ce serait choisir la fenêtre après avoir vu le résultat : la réaction mesurée serait biaisée vers le haut. Le programme calcule seulement un **drapeau de timing douteux** (affichage, jamais règle de sélection) : on le lève quand le jour alternatif (J+1 pour une annonce dite BMO, J−1 pour une annonce dite AMC) a un rendement anormal plus de deux fois plus grand **et** supérieur à trois écarts-types quotidiens :

$$
|AR_{\text{alt}}| > 2\,|AR_0| \quad\text{et}\quad |AR_{\text{alt}}| > 3\,\hat\sigma .
$$

---

## Chapitre 3. Rendements, prix ajustés, overnight et intraday

### L'idée

On mesure partout des **rendements simples** :

$$
R_t = \frac{P_t}{P_{t-1}} - 1 .
$$

Le **rendement logarithmique** $r_t=\ln(P_t/P_{t-1})$ a la propriété pratique de s'additionner dans le temps, mais il se lit mal ($+10\ \%$ de rendement simple correspond à $r = 9{,}53\ \%$) et les modèles à facteurs ainsi que le rendement composé (BHAR, chapitre 5) sont définis en rendements simples. Les deux sont proches pour de petits mouvements : $\ln(1+R) \approx R - R^2/2$.

### Les maths

**Prix ajustés.** Un split (une action devient deux) ou le détachement d'un dividende fait chuter le cours sans qu'un investisseur perde de l'argent. Les cours sont donc **ajustés** des splits et des dividendes avant de calculer $R_t$. Sans cela, le jour de détachement d'un dividende ressortirait comme un faux rendement négatif dans la fenêtre. Les ouvertures, plus hauts et plus bas sont ajustés du même facteur.

**Overnight et intraday.** Soit $O_t$ l'ouverture du jour $t$ et $C_t$ la clôture. On découpe le rendement du jour en deux parties :

$$
\underbrace{on_t = \frac{O_t}{C_{t-1}} - 1}_{\text{overnight : de la clôture à l'ouverture}},\qquad
\underbrace{id_t = \frac{C_t}{O_t} - 1}_{\text{intraday : de l'ouverture à la clôture}},\qquad
(1+on_t)(1+id_t) = 1 + R_t .
$$

La dernière égalité est exacte ($\frac{O_t}{C_{t-1}}\cdot\frac{C_t}{O_t} = \frac{C_t}{C_{t-1}}$). Pour une annonce après la clôture, l'essentiel de la réaction est dans l'overnight (le « gap » d'ouverture) ; la part de l'intraday mesure la rapidité avec laquelle l'information est incorporée (carte *Overnight contre intraday*).

### Dans le programme

`SymbolPrices` dans [`engine.py`](../../patrick/patrick/earnings/engine.py) calcule une fois par titre `r`, `on` et `id`. Les cours viennent du fournisseur gratuit ([`provider.py`](../../patrick/patrick/earnings/provider.py)).

### Les pièges

- Les opérations plus complexes que le split (scission, spin-off) ne sont **pas toujours** ajustées par la source gratuite : un drapeau `split_flag` signale les événements dont la fenêtre $[-250,+60]$ contient un split (les volumes sont alors à lire avec prudence).
- Un rendement « overnight » dépend de l'ouverture fournie par Yahoo, qui est parfois une ouverture d'auction peu représentative sur les petites valeurs.

---

## Chapitre 4. Le rendement attendu

### L'idée

Pour dire « le titre a fait +5,9 % mais le modèle attendait −0,3 % », il faut un modèle qui dit ce qui était **attendu**. On l'estime sur une période **calme**, avant l'annonce (la **fenêtre d'estimation**), puis on l'applique autour de l'annonce.

Fenêtre d'estimation par défaut : les séances $[-250,\,-30]$ (221 séances, soit environ dix mois de bourse, qui s'arrêtent 30 séances avant J0 pour ne pas être contaminées par l'annonce ni par son éventuel run-up). On **exclut** de l'estimation les séances situées à $\pm 2$ séances d'une **autre** annonce du même titre : un jour d'annonce est exceptionnellement volatil, ce qui gonflerait la variance résiduelle et fausserait le bêta. Il faut au moins 100 observations valides, sinon l'événement est écarté (et le dit).

### Les maths

Tous les modèles sont des régressions linéaires par les moindres carrés ordinaires (MCO, *OLS*) sur la fenêtre d'estimation. Avec $y_t$ la variable à expliquer et $\mathbf{x}_t$ le vecteur des variables explicatives (une ligne de la matrice $X$, $T$ lignes) :

$$
y_t = \mathbf{x}_t'\,\boldsymbol\theta + \varepsilon_t,\qquad
\hat{\boldsymbol\theta} = (X'X)^{-1}X'\mathbf{y},\qquad
\hat\sigma^2 = \frac{1}{T-k}\sum_{t}\hat\varepsilon_t^{\,2}.
$$

Intuition de $(X'X)^{-1}X'\mathbf y$ : c'est le choix de coefficients qui rend la somme des carrés des résidus la plus petite possible. $\hat\sigma$ est l'écart-type de ce que le modèle n'explique pas, par jour.

Les quatre modèles proposés (réglage `model`) :

| Modèle | $y_t$ | $\mathbf{x}_t$ | Lecture |
|---|---|---|---|
| `market` (**défaut**) | $R_t$ | $(1,\ R_{m,t})$ | $R_t = \mu + \beta\,R_{m,t} + \varepsilon_t$ : le « bêta » $\beta$ mesure la sensibilité à l'indice local |
| `market_adjusted` | $R_t - R_{m,t}$ | aucun ($k=0$) | on impose $\beta=1$ et $\mu=0$ : pas d'estimation, $\hat\sigma^2$ est la variance de $R-R_m$ |
| `factor` | $R_t - RF_t$ | $(1,\ MktRF,\ SMB,\ HML,\ MOM)$ | facteurs de Fama-French (1993) + momentum de Carhart (1997), fichiers de Kenneth French Europe / États-Unis / Japon |
| `sector` | $R_t$ | $(1,\ R_{\text{secteur},t})$ | ETF sectoriel (États-Unis) ou panier de pairs |

Une fois $\hat{\boldsymbol\theta}$ estimé, le **rendement attendu** du jour $t$ de la trajectoire est $E_t=\mathbf{x}_t'\hat{\boldsymbol\theta}$ (pour `market_adjusted`, $E_t = R_{m,t}$).

### Dans le programme

- `SymbolPrices.design` construit $(y, X)$ pour chaque modèle ; `compute_event` fait l'estimation, le masque d'exclusion (`est_exclude = 2`), le minimum de 100 observations (`min_est_obs`) et calcule $\hat\sigma$ avec $T-k$ degrés de liberté. Fichier [`engine.py`](../../patrick/patrick/earnings/engine.py).
- **Repli** : les facteurs de French sont publiés avec un à deux mois de retard. Pour une annonce récente, le modèle à facteurs n'a pas ses données au jour J0 ; le programme retombe sur le modèle de marché et l'écrit dans le champ `model_used` (carte *Ajustements, drapeaux et biais de survie*). Même repli si l'indice manque : « constante » (moyenne), dit comme tel.
- **L'indice de marché est local** : CAC 40 pour une valeur de Paris, DAX pour Francfort, Nikkei pour Tokyo... avec un repli européen puis le S&P 500. Le choix est fait **par couverture** (l'indice qui a assez d'historique), après qu'un indice trop court (OMXC25 pour Copenhague) a faussé des estimations.

### Exemple chiffré (titre synthétique, bêta vrai 1,2)

On génère 600 jours de bourse : marché $\sim$ moyenne 0,04 %, écart-type 1 % ; titre $= 0{,}02\ \% + 1{,}2\,R_m + \text{bruit}$ (écart-type 1,2 %), et on **injecte** +4,5 % au jour de réaction. Le programme (`compute_event`, modèle de marché, annonce avant l'ouverture) donne :

| Grandeur | Valeur |
|---|---|
| Séances utilisées pour l'estimation $T$ | 221 (sur $[-250,-30]$) |
| Bêta estimé $\hat\beta$ | 1,139 (vrai : 1,2) |
| $\hat\sigma$ quotidien | 1,175 % |
| Rendement observé à J0 | +5,69 % |
| Rendement attendu à J0 (le marché a baissé ce jour-là) | −0,28 % |
| **Rendement anormal $AR_0$** | **+5,97 %** |

Le +5,97 % n'est pas exactement le +4,5 % injecté : il contient aussi le bruit propre de la journée (écart-type 1,2 %) et l'erreur d'estimation du bêta. Même avec des paramètres connus, l'événement ne se mesure qu'avec une **erreur** : c'est ce que les chapitres 5 à 7 quantifient.

### Les pièges

- **Le bêta bouge** avec le temps (une année calme n'est pas une année de crise) ; la fenêtre de 220 séances est un compromis entre précision et actualité (la carte *Sensibilité* teste d'autres fenêtres).
- Le modèle de marché est **volontairement simple** : Brown et Warner (1985) montrent que, pour tester une réaction moyenne, des modèles simples font aussi bien que des modèles sophistiqués. Le modèle à facteurs et le modèle sectoriel servent de contrôles de robustesse.
- Un titre qui cote dans un autre fuseau horaire que son indice (ADR, double cotation) a des rendements non synchrones ; la carte *Ligne locale contre ADR* traite spécifiquement ce cas.

---

## Chapitre 5. Rendement anormal, CAR, CAAR, BHAR et leur variance

### L'idée

Une fois le rendement attendu connu :

- le **rendement anormal** d'un jour est l'écart réel moins attendu ;
- le **CAR** (*cumulative abnormal return*) additionne ces écarts sur une fenêtre ;
- le **CAAR** (*cumulative average abnormal return*) fait la moyenne des CAR de tous les événements.

On retrouve les trois fenêtres de la page : **run-up** $[-10,-1]$ (avant l'annonce : fuite d'information, anticipation), **réaction** $[0]$ ou $[0,+1]$, **continuation / dérive** $[+2,+5]$, $[+2,+20]$, $[+2,+60]$ (le marché ajuste-t-il lentement ?).

### Les maths

$$
AR_{i,t} = R_{i,t} - E_{i,t},\qquad
CAR_i[a,b] = \sum_{t=a}^{b} AR_{i,t},\qquad
CAAR[a,b] = \frac{1}{N}\sum_{i=1}^{N} CAR_i[a,b].
$$

**Variance d'un CAR.** C'est la formule la plus importante du cours, parce que tout test en dépend. Pour un événement, les vrais coefficients $\boldsymbol\theta$ sont inconnus ; on a utilisé $\hat{\boldsymbol\theta}$. Donc

$$
AR_t = \varepsilon_t - \mathbf{x}_t'(\hat{\boldsymbol\theta}-\boldsymbol\theta)
\;\Longrightarrow\;
CAR = \sum_{t=a}^{b}\varepsilon_t \;-\; \mathbf{s}'(\hat{\boldsymbol\theta}-\boldsymbol\theta),\qquad \mathbf{s}=\sum_{t=a}^{b}\mathbf{x}_t .
$$

Deux sources d'incertitude : le **bruit du jour** (somme de $L$ résidus indépendants, variance $L\sigma^2$) et l'**erreur d'estimation** du modèle (variance de $\hat{\boldsymbol\theta}$ égale à $\sigma^2(X'X)^{-1}$). Les deux sont indépendantes (les résidus de la fenêtre d'événement ne servent pas à l'estimation), donc

$$
\boxed{\ \operatorname{Var}\big(CAR[a,b]\big) = \hat\sigma^2\Big(L + \mathbf{s}'\,(X'X)^{-1}\,\mathbf{s}\Big)\ }
$$

Si le modèle n'a pas de coefficient estimé ($k=0$, `market_adjusted`), il reste $\hat\sigma^2 L$. Le terme $\mathbf s'(X'X)^{-1}\mathbf s$ est la **correction d'erreur de prévision** : petit pour un jour (l'estimation sur 220 séances est précise), il grandit avec la longueur de la fenêtre et avec l'éloignement des valeurs de $R_m$ par rapport à celles de l'estimation.

Sur l'exemple du chapitre 4 :

| Fenêtre | $L$ | $\hat\sigma^2 L$ | facteur $1 + \mathbf s'(X'X)^{-1}\mathbf s / L$ | écart-type du CAR |
|---|---|---|---|---|
| $[0,0]$ | 1 | $1{,}38\times10^{-4}$ | 1,0046 | 1,18 % |
| $[0,4]$ | 5 | $6{,}9\times10^{-4}$ | 1,0263 | 2,66 % |

Le CAR$[0]$ vaut +5,97 %, soit $z = CAR/\sqrt{\operatorname{Var}} = 5{,}07$ écarts-types. Sur $[0,4]$ le CAR vaut +5,35 % : la réaction s'est peu défaite en cinq jours. La statistique $z$ est la brique de tous les tests du chapitre 7.

**Amplitude en écarts-types quotidiens.** Pour comparer les titres entre eux, la page utilise aussi

$$
z^{\text{abs}} = \frac{|CAR|}{\hat\sigma}
$$

(« de combien de jours ordinaires de ce titre a-t-il bougé »). Elle ne divise **pas** par $\sqrt L$ : sur $[0,+1]$, sous $H_0$, $z^{\text{abs}}$ vaut en moyenne $\sqrt2$ fois plus qu'un jour. C'est une **mesure descriptive d'amplitude**, pas la statistique d'un test (qui est $z$, avec sa propre variance).

**BHAR.** Le rendement **composé** anormal :

$$
BHAR_i[a,b] = \prod_{t=a}^{b}(1+R_{i,t}) - \prod_{t=a}^{b}(1+E_{i,t}).
$$

Il correspond à ce que gagnerait un investisseur qui achète à $a$ et garde jusqu'à $b$, contre le rendement attendu composé (Barber et Lyon, 1997). Il est **asymétrique** (composer des rendements donne une loi à queue droite) et sensible aux valeurs extrêmes : on le teste par bootstrap en blocs de dates (chapitre 7), pas avec un test de moyenne classique.

**Courbe de CAAR cumulé.** Le graphique « CAAR moyen cumulé depuis J−10 » empile les événements. En chaque séance relative, c'est la moyenne des sommes cumulées, avec une bande de $\pm1{,}96$ erreurs-types : $\overline{C}_t \pm 1{,}96\, s_t/\sqrt{n_t}$ ($n_t$ événements disponibles à cette séance ; la courbe n'est tracée que là où au moins la moitié des événements existent). Cette bande suppose les événements indépendants : **elle est trop étroite** si des annonces d'une même semaine se ressemblent (chapitre 7).

### Dans le programme

`compute_event` stocke `ar`, `er`, `ret`, `on`, `id`, `sigma`, `k`, `xtx_inv` (la matrice $(X'X)^{-1}$) et `x_path` (les lignes $\mathbf{x}_t$ de la trajectoire). C'est ce qui permet de recalculer la variance du CAR sur **n'importe quelle fenêtre** sans refaire l'estimation : [`car_variance`](../../patrick/patrick/earnings/engine.py), [`window_sum`](../../patrick/patrick/earnings/engine.py), [`bhar`](../../patrick/patrick/earnings/engine.py), [`reaction_stats`](../../patrick/patrick/earnings/engine.py).

### Les pièges

- La variance suppose des résidus **non autocorrélés** d'un jour à l'autre et de variance constante ; le jour d'annonce la variance est en réalité plus grande (chapitre 7, Patell contre BMP).
- Les **fenêtres postérieures** ne sont calculables que si les séances sont écoulées : une annonce de la semaine dernière n'a pas de $[+2,+60]$ ; la somme vaut alors « non disponible », jamais une somme partielle.
- Un **gros CAR n'est pas un gros $z$** : +6 % sur un titre qui bouge d'habitude de 3 % par jour n'a pas la même portée que +6 % sur un titre à 0,8 % par jour. C'est pourquoi on standardise.


---

# Partie II. Savoir si c'est significatif

## Chapitre 6. Tester une hypothèse : le vocabulaire minimal

### L'idée

Sur $N$ annonces, le CAAR (la moyenne des CAR) n'est jamais exactement zéro, même si l'annonce n'a aucun effet moyen : le hasard seul le fait bouger. La question est : **ce CAAR est-il trop grand pour être du hasard ?**

Le raisonnement d'un test statistique, en cinq mots :

- **Hypothèse nulle $H_0$** : « il n'y a pas d'effet moyen » (ici : l'espérance du CAR vaut 0). C'est l'hypothèse que l'on cherche à mettre en difficulté.
- **Statistique de test** : un nombre calculé sur l'échantillon (par exemple CAAR divisé par son erreur-type). Plus il est grand en valeur absolue, plus l'échantillon s'éloigne de $H_0$.
- **p-value** : la probabilité d'observer une statistique **au moins aussi extrême**, **si $H_0$ était vraie**. Ce n'est pas la probabilité que $H_0$ soit vraie.
- **Niveau $\alpha$** : le seuil fixé à l'avance (5 % ou 10 %) en dessous duquel on rejette $H_0$. Par construction, un test **calibré** rejette à tort $H_0$ dans $\alpha$ % des cas où elle est vraie (*erreur de type I*, ou « faux positif »).
- **Puissance** : la probabilité de rejeter $H_0$ quand l'effet existe vraiment. Une faible puissance est l'autre risque (*erreur de type II*, ne rien voir alors qu'il y a quelque chose).

### Les maths : un ordre de grandeur de puissance

Si les CAR ont un écart-type $s$ et que l'effet vrai est $\delta$, la statistique attendue est environ $t \approx \delta/(s/\sqrt N)$. Quelques cas :

| Effet moyen $\delta$ | $s$ (CAR) | $N$ | $t$ attendu |
|---|---|---|---|
| 0,5 % | 4 % | 100 | 1,25 |
| 0,5 % | 4 % | 400 | 2,50 |
| 0,2 % | 4 % | 400 | 1,00 |

Lecture : un effet de 0,5 % avec 100 annonces est **invisible** (t ≈ 1,25 < 2). Sur des simulations de 100 événements indépendants où l'effet vrai vaut 0,3 écart-type, les tests rejettent $H_0$ dans **83,5 %** des cas : on rate donc l'effet une fois sur six même quand il existe. Ce n'est pas un défaut du test mais du nombre d'observations.

Pourquoi un cours entier de tests, alors ? Parce que les données d'événements ont **deux défauts** qui fabriquent de faux positifs si on utilise la formule naïve $t=\overline{CAR}/(s/\sqrt N)$ :

1. **la variance augmente le jour de l'annonce** (le titre est plus agité qu'à l'ordinaire) ;
2. **les annonces d'une même semaine ne sont pas indépendantes** (elles partagent les mêmes chocs de marché et de secteur).

Le chapitre 7 présente les tests qui traitent l'un, l'autre ou les deux.

---

## Chapitre 7. Les sept tests d'un CAAR

### L'idée

Un seul CAAR, sept façons de le tester, parce que chaque test corrige un défaut différent. Le programme les calcule tous (carte *Event study*) et affiche le **BMP** comme verdict de référence, avec le **bootstrap par blocs** comme contrôle.

Pour chaque événement $i$ on a le CAR et sa variance estimée (chapitre 5). On définit le **CAR standardisé**

$$
SCAR_i = \frac{CAR_i}{\sqrt{\widehat{\operatorname{Var}}(CAR_i)}} ,
$$

qui doit valoir en moyenne 0 et avoir une variance voisine de 1 sous $H_0$ : il exprime chaque réaction **dans l'unité de bruit de son propre titre**. Notation : $d_i = T_i-k_i$ (degrés de liberté de l'estimation, avec un plancher à 3), $\bar{S}$ et $s_S$ la moyenne et l'écart-type (avec $N-1$ au dénominateur) des $SCAR_i$.

### Les maths

**1. t-test naïf (`cross`).** Test de la moyenne des CAR bruts :

$$
t_{\text{naïf}} = \frac{\overline{CAR}}{s_{CAR}/\sqrt N},\qquad \text{loi de Student à } N-1 \text{ degrés de liberté.}
$$

Il traite chaque CAR comme venant d'une même loi et indépendante des autres. À ne pas croire ; le programme ne l'affiche pas, il sert de point de comparaison.

**2. Patell (1976) (`patell`).** Chaque $SCAR_i$ suit approximativement une loi de Student à $d_i$ degrés de liberté, de variance $d_i/(d_i-2)$. La somme de $N$ variables indépendantes a pour variance la somme des variances :

$$
Z_{\text{Patell}} = \frac{\sum_i SCAR_i}{\sqrt{\sum_i d_i/(d_i-2)}} ,\qquad \text{loi normale centrée réduite.}
$$

Il suppose que la variance du CAR le jour de l'annonce est **exactement** celle de l'estimation. Or le jour d'une annonce le titre est plus agité : la variance réelle est supérieure, donc le test **rejette trop**.

**3. BMP (Boehmer, Musumeci, Poulsen, 1991) (`bmp`, défaut).** Au lieu de supposer la variance des $SCAR_i$, on la **mesure** sur l'échantillon d'événements lui-même, ce qui absorbe l'augmentation de variance :

$$
t_{\text{BMP}} = \frac{\bar S}{s_S/\sqrt N},\qquad \text{loi de Student à } N-1 \text{ degrés de liberté.}
$$

Ce n'est rien d'autre que le t-test **sur les CAR standardisés** (au lieu des CAR bruts). Deux gains : chaque titre pèse selon sa propre incertitude (un +4 % sur un titre calme informe plus qu'un +4 % sur un titre agité) et la dispersion observée des $SCAR_i$ remplace la variance supposée.

**4. Kolari-Pynnönen (2010) (`kp`).** Le BMP suppose les événements indépendants. Si les résidus de deux annonces sont corrélés avec une corrélation moyenne $\bar r$ (surtout quand elles tombent la même semaine), la variance d'une moyenne de $N$ variables de variance $\sigma^2$ devient

$$
\operatorname{Var}(\bar X)=\frac{\sigma^2}{N}\big(1+(N-1)\,\bar r\big),
\qquad\text{soit}\qquad N_{\text{eff}}=\frac{N}{1+(N-1)\bar r}
$$

échantillons **vraiment indépendants** équivalents. Par ailleurs l'écart-type empirique des $SCAR_i$ est lui-même sous-estimé d'un facteur $(1-\bar r)$ en variance. Les deux corrections donnent

$$
t_{\text{KP}} = t_{\text{BMP}}\ \sqrt{\frac{1-\bar r}{1+(N-1)\,\bar r}},\qquad \text{Student à } N-1 \text{ degrés de liberté.}
$$

Valeurs du facteur multiplicatif et de l'échantillon équivalent :

| $N$ | $\bar r$ | facteur sur $t$ | $N_{\text{eff}}$ |
|---|---|---|---|
| 100 | 0,02 | 0,57 | 33,6 |
| 100 | 0,05 | 0,40 | 16,8 |
| 100 | 0,10 | 0,29 | 9,2 |
| 300 | 0,05 | 0,24 | 18,8 |

Avec 100 annonces et une corrélation moyenne de seulement 5 %, il ne reste que **17 observations indépendantes** : le $t$ est divisé par 2,5.

*Comment le programme estime $\bar r$.* Pour chaque événement on dispose des résidus standardisés de sa fenêtre d'estimation. Deux annonces proches dans le calendrier ont des fenêtres d'estimation qui se recouvrent presque entièrement (même marché, mêmes jours). On aligne les résidus **par jours ouvrés** (jour calendaire commun) et on calcule la corrélation de chaque paire d'événements (sur au plus 300 événements tirés au hasard, graine fixe). **$\bar r$ est la moyenne sur TOUTES les paires, celles qui ne se recouvrent pas comptant pour 0.** Moyenner seulement les paires qui se chevauchent surestimerait $\bar r$ (deux annonces à plus d'un an d'écart n'ont aucune fenêtre commune, leur corrélation vaut 0) et le facteur ci-dessus écraserait toute statistique. $\bar r$ est borné à 0 par le bas.

**5. Corrado (1989), Campbell-Wasley (1993) (`corrado`).** Test **par les rangs**, sans hypothèse de loi (utile quand les rendements ont des queues épaisses). Pour chaque événement on classe le rendement anormal de chaque jour de la fenêtre d'événement parmi **tous** les résidus de la fenêtre d'estimation de ce même événement. Le rang est transformé en écart à la médiane :

$$
U_{i,t} = \frac{\operatorname{rang}(AR_{i,t})}{T_i+1}-\frac12 ,
$$

où $T_i$ est le nombre de jours classés (estimation + fenêtre d'événement). Sous $H_0$, $U_{i,t}$ est symétrique autour de 0. On moyenne sur les événements ($\bar U_t$) puis sur les jours de la fenêtre, et on divise par l'écart-type observé de la même agrégation sur la période d'estimation :

$$
Z_{\text{Corrado}} = \frac{\frac1L\sum_{t=a}^{b}\bar U_t}{s_{\bar U}},\qquad s_{\bar U}=\text{écart-type des moyennes glissantes sur }L\text{ jours de }\bar U_t\text{ sur l'estimation.}
$$

Loi normale. Un rendement extrême pèse comme un autre rang, pas plus : le test est insensible aux valeurs aberrantes.

**6. Test des signes généralisé (Cowan, 1992) (`sign`).** Compare la **proportion de CAR positifs** non pas à 50 %, mais à la proportion qu'on observe **sur les fenêtres glissantes de l'estimation** (les rendements ne sont pas symétriques). Soit $\hat p$ cette proportion, moyennée sur les événements, $w$ le nombre de CAR positifs observés :

$$
Z_{\text{signes}}=\frac{w - N\hat p}{\sqrt{N\,\hat p\,(1-\hat p)}},\qquad\text{loi normale.}
$$

Le programme **refuse** ce test pour une fenêtre de plus de 10 séances : les sommes glissantes de $L>10$ jours se recouvrent presque toutes, la fréquence de référence devient instable (des p-values absurdes avaient été constatées sur $[+2,+60]$).

**7. Bootstrap par blocs de dates (`bootstrap`).** Au lieu d'une formule, on **simule** la variabilité du CAAR en rééchantillonnant les données. Le **bootstrap** consiste à tirer au hasard, avec remise, des observations de l'échantillon pour fabriquer des échantillons « alternatifs » et voir comment la statistique varie. Pour respecter la dépendance entre annonces d'une même semaine, on ne rééchantillonne pas les annonces une à une mais des **blocs : les semaines calendaires de J0** (semaine ISO). Algorithme (2 000 tirages par défaut) :

1. regrouper les CAR par semaine ; $k$ semaines, avec pour chaque semaine la somme $\Sigma_j$ de ses CAR et son effectif $n_j$ ;
2. à chaque tirage, choisir $k$ semaines avec remise ; la moyenne du tirage est $\bar X^{*} = \sum \Sigma_j^{*}\big/\sum n_j^{*}$ ;
3. recentrer sous $H_0$ : $\bar X^{*} - \bar X_{\text{obs}}$ ;
4. p-value bilatérale :

$$
p = 2\,\min\Big(\Pr\big[\bar X^{*}-\bar X_{\text{obs}} \ge \bar X_{\text{obs}}\big],\ \Pr\big[\bar X^{*}-\bar X_{\text{obs}} \le \bar X_{\text{obs}}\big]\Big),
$$

avec un plancher à $1/n_{\text{boot}}$ ; l'intervalle à 95 % est donné par les quantiles 2,5 % et 97,5 % des $\bar X^{*}$. Il faut **au moins 3 semaines**, sinon le test n'est pas calculé.

### Récapitulatif

| Test | Corrige | Hypothèse restante | Fragile quand |
|---|---|---|---|
| t naïf | rien | indépendance, variance constante | toujours (référence) |
| Patell | titres de risques différents | variance du jour d'annonce = variance d'estimation | variance accrue le jour J0 |
| **BMP** (défaut) | + variance accrue | événements indépendants | annonces corrélées (même semaine) |
| KP | + corrélation moyenne $\bar r$ | corrélation uniforme entre toutes les paires | corrélations très hétérogènes |
| Corrado | queues épaisses | symétrie des rangs | beaucoup d'ex æquo, fenêtre longue |
| Signes | valeurs extrêmes | proportion stable sur l'estimation | $L>10$ (refusé), asymétrie |
| Bootstrap en blocs | dépendance intra-semaine | blocs indépendants entre eux | moins de ~10 semaines, queues très lourdes |

### Ce que disent les simulations (chiffres du programme)

*Tests avec chocs communs par semaine.* On simule 100 annonces (20 semaines de 5), $H_0$ **vraie** (aucun effet), un choc commun par semaine de variance 0,5 pour 1 de bruit propre (corrélation 1/3 dans la semaine, soit $\bar r = 0{,}0135$ moyennée sur toutes les paires). Taux de rejet à 5 % (600 répétitions, précision de l'ordre de ±1 point) :

| Test | Taux de rejet (devrait valoir 5 %) |
|---|---|
| t naïf | 21,3 % |
| Patell | 31,8 % |
| BMP | 21,3 % |
| **KP avec $\bar r$ moyenné sur toutes les paires** | **5,7 %** |
| KP avec la corrélation intra-semaine (erreur) | 0,0 % |
| Bootstrap en blocs | 7,8 % |

Sur 100 annonces apparemment indépendantes, le t naïf se trompe **une fois sur cinq** et conclut à un effet inexistant. Le chiffre de la ligne « erreur » est le piège décrit plus haut : mettre la corrélation intra-semaine (0,33) à la place de la moyenne sur toutes les paires (0,0135) fait fondre la statistique à rien.

*Tests avec variance accrue le jour d'annonce.* 100 événements indépendants, $H_0$ vraie, mais les $SCAR_i$ ont un écart-type de 1,5 ou 2 au lieu de 1 (2 000 répétitions) :

| Écart-type des $SCAR_i$ | Naïf | Patell | BMP |
|---|---|---|---|
| 1,0 (conforme à l'estimation) | 5,7 % | 5,6 % | 5,7 % |
| 1,5 | 5,7 % | **20,1 %** | 5,7 % |
| 2,0 | 6,5 % | **32,8 %** | 6,5 % |

Patell rejette à tort une fois sur trois ou cinq dès que la variance du jour d'annonce dépasse celle de l'estimation ; BMP, qui mesure la dispersion des $SCAR_i$, reste à 5 %. (Dans cette simulation tous les CAR ont le même écart-type, donc le t naïf et le BMP coïncident : leur différence apparaît quand les titres ont des risques différents.)

### Dans le programme

[`signif.py`](../../patrick/patrick/earnings/signif.py) : `window_table` (une ligne par événement : CAR, variance, SCAR, degrés de liberté, semaine), `cross_sectional`, `patell`, `bmp`, `kolari_pynnonen`, `mean_pairwise_correlation`, `corrado`, `generalized_sign`, `block_bootstrap`, et `run_tests` qui les assemble. Le test affiché comme verdict dans la carte *Event study* se choisit parmi `bmp`, `patell`, `corrado`, `sign`, `kp`, `bootstrap` (défaut `bmp`). Il faut au moins 4 événements exploitables pour tester, et le réglage `winsorize` (rognage des CAR extrêmes) ne modifie que la **moyenne affichée**, jamais les tests.

### Exemple sur 6 événements

Six annonces, dont les CAR sur $[0]$ valent +4,1 %, −2,0 %, +3,3 %, +5,2 %, −0,8 %, +2,6 % avec des écarts-types estimés de 1,8 %, 2,2 %, 1,5 %, 2,5 %, 1,2 %, 1,9 %, groupées par paires en trois semaines. On trouve $SCAR=(2{,}28;\ -0{,}91;\ 2{,}20;\ 2{,}08;\ -0{,}67;\ 1{,}37)$, de moyenne $\bar S=1{,}058$ et d'écart-type $s_S=1{,}468$ ; le CAAR vaut +2,07 %.

| Test | Statistique | p-value |
|---|---|---|
| t naïf (sur les CAR) | 1,78 | 0,135 |
| Patell | 2,58 | **0,010** |
| BMP | 1,77 | 0,138 |
| KP avec $\bar r = 0{,}05$ | 1,54 | 0,184 |
| KP avec $\bar r = 0{,}15$ | 1,23 | 0,273 |
| Bootstrap en blocs (3 semaines) | 2,33 | 0,084 |

Patell déclare l'effet significatif à 1 % : il suppose les $SCAR_i$ de variance voisine de 1 (ici $s_S^2\approx 2{,}2$, plus de deux fois trop) et se laisse impressionner. BMP, qui regarde la dispersion réelle, dit « pas significatif » ; KP, qui sait que les annonces sont en paires, le dit encore plus fort. Le bootstrap, avec seulement 3 blocs, n'a presque aucune résolution (peu de combinaisons possibles) : c'est un contrôle utile quand il y a assez de semaines, pas ici.

### Les pièges

- **Choisir son test après avoir vu les résultats** est une forme de triche. D'où le test de référence fixé à l'avance (BMP) et, pour aller plus loin, le registre FDR (chapitre 10).
- Un **test qui ne rejette pas** n'est pas une preuve d'absence d'effet : voir la puissance au chapitre 6.
- **Les tests valident l'inférence, pas la causalité** : un CAAR significatif sur $[+2,+5]$ dit que la moyenne n'est pas nulle dans l'échantillon, pas qu'une stratégie en tirerait un profit net de coûts (chapitre 23).

---

## Chapitre 8. Bouge-t-il plus que d'habitude ?

### L'idée

Si la moitié des annonces fait +5 % et l'autre −5 %, le CAAR est nul alors que **chaque annonce a été très violente**. Or l'amplitude d'une réaction est justement ce qui est prévisible (chapitre 1). On a donc besoin d'un test qui ignore le signe : le titre bouge-t-il **plus que sur une séance ordinaire** ?

### Les maths

Deux lectures, indépendantes l'une de l'autre, sur la fenêtre $[a,b]$ de $L$ jours.

**Test de rang sur $|CAR|$.** Pour un événement, on forme la distribution de référence : les valeurs absolues de toutes les **sommes de $L$ jours consécutifs** des résidus de la fenêtre d'estimation de **ce même titre** (au moins 30 valeurs). On calcule le **percentile** du $|CAR|$ observé dans cette distribution (les égalités comptent pour une demi-unité) :

$$
u_i = \Pr\big[\,|S_L| < |CAR_i|\,\big] + \tfrac12\Pr\big[\,|S_L| = |CAR_i|\,\big].
$$

Sous $H_0$ (« ce jour est un jour comme les autres pour ce titre »), $u_i$ est uniforme sur $[0,1]$ : moyenne $\tfrac12$, variance $\tfrac1{12}$. Sur $m$ événements :

$$
Z = \frac{\bar u - \frac12}{\sqrt{1/(12\,m)}},\qquad p = 1-\Phi(Z)\quad(\text{unilatéral : on cherche un excès}).
$$

Avantage : aucune hypothèse de loi, et chaque titre est comparé **à lui-même**.

**Test sur la variance du CAR standardisé.** Sous $H_0$, $SCAR_i$ est de moyenne 0 et de variance 1, donc $E[SCAR_i^2]=1$. On teste que la moyenne des $SCAR_i^2$ dépasse 1 (t unilatéral à $N-1$ degrés de liberté, écart-type empirique de la moyenne comme au BMP). Un $\overline{SCAR^2}$ de 2,5 signifie que les réactions sont typiquement de $\sqrt{2{,}5}\approx 1{,}6$ fois plus ample que ce que le bruit du titre laisse attendre.

### Dans le programme

[`signif.abs_move_test`](../../patrick/patrick/earnings/signif.py), affichée dans la carte *Event study* (bloc « Bouge-t-il plus que d'habitude ? ») pour les fenêtres $[0]$ et $[0,+1]$ ; les deux p-values (`core.abs.rank.*`, `core.abs.var.*`) entrent au registre FDR.

### Les pièges

- C'est un test **unilatéral** : on ne teste que « plus de mouvement », pas « moins ».
- L'amplitude sur $[0,+1]$ mélange deux jours quand le timing est incertain ; la comparaison aux sommes de 2 jours de l'estimation en tient compte (même $L$).

---

## Chapitre 9. Étalonner les tests avec des placebos

### L'idée

Les formules des tests reposent sur des hypothèses (normalité approchée, indépendance...) que les vraies données ne respectent pas parfaitement. Plutôt que de les croire, on **mesure** leur taux de faux positifs sur des données où l'on **sait** que $H_0$ est vraie : des **dates tirées au hasard** pour les **mêmes titres**. Si un test rejette 20 % de ces faux événements à un niveau de 5 %, il est invalide sur cet échantillon, quelle que soit la belle p-value de la vraie carte.

### Les maths

Pour une fenêtre $[a,b]$ choisie, on répète $R$ fois (30 par défaut) :

1. tirer $n$ dates (100 par défaut) pour des titres choisis avec une probabilité proportionnelle à leur nombre d'annonces réelles (les 60 titres les plus fréquents), à au moins 8 jours calendaires de toute vraie annonce du titre ;
2. calculer l'événement avec le **même** modèle de marché (annonce prise avant l'ouverture) et les mêmes tests ;
3. noter si $p<\alpha$.

Le taux de rejet empirique $\hat\pi$ doit valoir $\alpha$. On teste $H_0:\pi=\alpha$ par un test binomial exact : sous $H_0$ le nombre de rejets suit une loi binomiale de paramètres $(R,\alpha)$. Verdict affiché :

| Condition | Verdict |
|---|---|
| p (binomial) > 5 % | **calibré** |
| p ≤ 5 % et $\hat\pi>\alpha$ | **TROP DE REJETS : invalide** |
| p ≤ 5 % et $\hat\pi<\alpha$ | conservateur (rejette trop rarement : sûr mais peu puissant) |

Un drapeau est levé quand $\hat\pi > 2\alpha$.

### Dans le programme

Carte *Événements placebo* ([`studies/robustness.py`](../../patrick/patrick/earnings/studies/robustness.py), `m_placebo`) : paramètres `draws`, `per_draw`, `level`, `win_lo`, `win_hi`. Lors de la livraison, la calibration a été vérifiée sur les fenêtres $[0,0]$ et $[2,5]$. Pendant la mise au point sur les vraies données, des défauts de ce genre avaient été constatés et corrigés (Kolari-Pynnönen trop sévère, test des signes aux p-values absurdes sur $[+2,+60]$) : la formule d'un test ne dispense jamais de le mesurer.

### Les pièges

- Avec 30 répétitions, le taux de rejet a lui-même une incertitude de l'ordre de $\sqrt{0{,}05\times0{,}95/30}\approx4$ points : le placebo détecte les gros défauts, pas les petits.
- Les placebos partagent les mêmes titres que l'échantillon réel : ils capturent donc les propriétés propres à ces titres (queues, corrélations), ce qui est le but.

---

## Chapitre 10. Beaucoup de tests : le taux de fausses découvertes (FDR)

### L'idée

Le problème qui pèse le plus sur ce genre de page est invisible dans une carte isolée : avec 54 cartes, plusieurs fenêtres, plusieurs sous-groupes, on teste **des centaines d'hypothèses**. Même si **rien** n'existe, certaines p-values passent sous 5 par hasard pur. Annoncer « j'ai trouvé un effet à p = 0,03 » après avoir regardé 200 résultats ne veut rien dire.

### Les maths

Si l'on teste $m$ hypothèses nulles vraies, indépendantes, chacune au niveau $\alpha$, la probabilité d'avoir **au moins un faux positif** est

$$
1-(1-\alpha)^m .
$$

Avec $\alpha=5\ \%$ : $m=1\to5\ \%$, $m=10\to40{,}1\ \%$, $m=54\to\mathbf{93{,}7\ \%}$, $m=200\to$ pratiquement 100 %.

On peut contrôler deux choses différentes. La **correction de Bonferroni** (multiplier chaque p par $m$) garantit que la probabilité d'au moins un faux positif reste sous $\alpha$ : très stricte quand $m$ est grand, elle noie les vrais effets. Le **taux de fausses découvertes** (FDR, *false discovery rate*), proposé par Benjamini et Hochberg (1995), contrôle autre chose : **parmi les résultats déclarés significatifs, la proportion attendue de faux**. C'est moins strict, plus adapté à l'exploration.

**Procédure de Benjamini-Hochberg.** On trie les $m$ p-values : $p_{(1)}\le p_{(2)}\le\dots\le p_{(m)}$. La **p-value corrigée** (*q-value*) du rang $i$ est

$$
q_{(i)} = \min_{j\ge i}\ \Big(\frac{m}{j}\,p_{(j)}\Big),\qquad q_{(i)}\le 1 .
$$

On déclare significatif ce qui a $q\le\alpha_{\text{FDR}}$ (10 % par défaut dans le programme). Le minimum « de la fin vers le début » garantit que les $q$ croissent avec les $p$. Lecture : $q$ est le plus petit taux de fausses découvertes pour lequel ce résultat serait retenu.

Exemple (8 p-values, seuil 10 %) :

| Test | $p$ | rang | $q$ | Survit ? |
|---|---|---|---|---|
| A | 0,001 | 1 | 0,008 | oui |
| B | 0,008 | 2 | 0,032 | oui |
| C | 0,020 | 3 | 0,053 | oui |
| D | 0,041 | 4 | 0,078 | oui |
| E | 0,049 | 5 | 0,078 | oui |
| F | 0,300 | 6 | 0,400 | non |
| G | 0,620 | 7 | 0,709 | non |
| H | 0,900 | 8 | 0,900 | non |

Remarquer que D et E partagent le même $q$ : le minimum « vers l'arrière » les égalise.

**Ce que ça fait quand rien n'existe** (simulation : 54 p-values tirées uniformément, c'est-à-dire 54 faux effets, 2 000 répétitions) :

| Mesure | Résultat |
|---|---|
| p < 0,05 par carte : nombre moyen de « découvertes » | 2,68 |
| Probabilité d'avoir **au moins une** p < 0,05 | **93,9 %** |
| Après BH à 10 % : nombre moyen de découvertes retenues | 0,13 |
| Probabilité d'avoir au moins une découverte retenue | 10,3 % |

Autrement dit, sans correction, regarder 54 cartes **produit presque à coup sûr** une trouvaille fantôme ; avec BH, on ne se trompe « complètement » (au moins une fausse découverte, alors que tout est bruit) que dans environ 10 % des cas, ce que le niveau annoncé promet.

### Dans le programme

[`validation/fdr.py`](../../patrick/patrick/validation/fdr.py) (`benjamini_hochberg`) et [`studies/runner.py`](../../patrick/patrick/earnings/studies/runner.py) (`fdr_ledger`, `ledger_inputs`). Chaque carte déclare ses p-values (clé `pvalues`) ; le **registre FDR** en bas de la page rassemble **toutes les cartes déjà calculées pour le périmètre, quelles que soient leurs variantes de paramètres** : essayer une autre fenêtre ou un autre sous-groupe **compte** comme un test de plus, sinon explorer des variantes donnerait l'illusion de peu de tests. C'est ce tableau, pas la p-value brute d'une carte, qui dit ce qui survit.

### Les pièges

- BH est démontré pour des tests **indépendants ou positivement dépendants**. Les cartes sont en partie corrélées (elles partagent les mêmes événements) ; le $q$ est donc **indicatif**, pas une garantie mathématique exacte. Une variante prudente existe (Benjamini et Yekutieli, 2001) mais n'est pas utilisée ici.
- Le registre ne compte que les tests **réellement lancés** : ceux que l'on a regardés et écartés sans les lancer échappent au décompte. C'est le *jardin des chemins qui bifurquent* : la discipline reste humaine.

---

## Chapitre 11. La boîte à outils des tests secondaires

Les autres cartes utilisent quelques outils classiques. Ils sont regroupés ici pour ne pas les redéfinir à chaque fois.

**Corrélation de rang de Spearman $\rho$.** C'est la corrélation de Pearson calculée sur les **rangs** des deux variables (le plus petit vaut 1, etc.). Elle mesure une relation monotone, sans exiger qu'elle soit linéaire, et résiste aux valeurs extrêmes. $\rho=0$ : aucun lien monotone ; $\rho=\pm1$ : lien monotone parfait. La p-value utilise l'approximation de Student ($t=\rho\sqrt{(n-2)/(1-\rho^2)}$).

**Test de Kruskal-Wallis, de Mann-Whitney, de Wilcoxon.** Tests **sans hypothèse de loi**, fondés sur les rangs.

- *Mann-Whitney* : deux groupes indépendants ont-ils la même distribution (par exemple l'amplitude un jour de FOMC contre un autre jour) ?
- *Kruskal-Wallis* : même question pour trois groupes ou plus (jours de la semaine, régimes de marché...).
- *Wilcoxon des rangs signés* : une série appariée est-elle centrée en 0 (par exemple $\ln(\text{vol après}/\text{vol avant})$) ?

**Test t de Welch.** Compare les moyennes de deux groupes sans supposer la même variance (écart haut contre bas des déciles de surprise).

**Test exact de Fisher.** Sur un tableau $2\times2$ (beat ou non, hausse ou baisse), la probabilité exacte d'un tableau au moins aussi déséquilibré, sans approximation : indiqué quand les effectifs sont petits.

**Intervalle de Wilson** pour une proportion $\hat p=k/n$ (niveau 95 %, $z=1{,}96$), préférable à l'intervalle usuel quand $n$ est petit ou $\hat p$ proche de 0 ou 1 :

$$
\frac{\hat p + \frac{z^2}{2n}\ \pm\ z\sqrt{\frac{\hat p(1-\hat p)}{n}+\frac{z^2}{4n^2}}}{1+\frac{z^2}{n}} .
$$

**Asymétrie et aplatissement** (distribution des réactions). L'*asymétrie* (skewness) mesure le déséquilibre entre queue droite et queue gauche (0 si symétrique) ; l'*aplatissement* (kurtosis) l'épaisseur des queues (3 pour une loi normale ; au-dessus, plus de valeurs extrêmes que la normale).

**Régression avec erreurs-types robustes groupées (« en sandwich »).** Les cartes qui régressent une réaction sur une variable (ERC, pairs, leader...) ne peuvent pas supposer l'indépendance des annonces d'une même semaine. Les coefficients sont ceux des MCO, $\hat{\boldsymbol\theta}=(X'X)^{-1}X'\mathbf y$, mais la variance est calculée **par groupes** (les semaines de J0, ou les titres pour la carte HAR) :

$$
\widehat{\operatorname{Var}}(\hat{\boldsymbol\theta}) = c\ (X'X)^{-1}\Big(\sum_{g=1}^{G}X_g'\hat{\mathbf e}_g\hat{\mathbf e}_g'X_g\Big)(X'X)^{-1},
\qquad c=\frac{G}{G-1}\cdot\frac{n-1}{n-k},
$$

où $X_g,\hat{\mathbf e}_g$ sont les lignes et résidus du groupe $g$. Le $t$ est comparé à une loi de Student à $G-1$ degrés de liberté (peu de groupes → seuil plus exigeant). Le coefficient est le même qu'avec des MCO ; seule l'**honnêteté sur son incertitude** change. Fonction : `cluster_ols` dans [`studies/base.py`](../../patrick/patrick/earnings/studies/base.py).


---

# Partie III. Les familles d'études

La page propose 54 cartes, rangées en familles notées par des lettres. Chaque carte est une brique **activable et paramétrable**, calculée une fois puis lue dans un cache (la clé contient les paramètres et la version des données ; elle change dès qu'un événement est ajouté ou recalculé). Cette partie explique ce que mesure chaque famille et la formule qui la sous-tend ; la correspondance exacte carte → fichier est en annexe B.

Deux règles s'appliquent à **toutes** les cartes :

1. **Point-in-time.** Toute grandeur « historique » d'un événement (moyenne passée de ses réactions, série de dépassements...) n'est calculée qu'avec les événements **strictement antérieurs**. L'événement testé ne se contient jamais lui-même et le futur n'entre jamais.
2. **Fiabilité visible.** Chaque statistique affiche un score de fiabilité (chapitre 18) : un titre a 12 à 40 annonces, aucune statistique par titre n'est fiable seule.

---

## Chapitre 12. Famille A : l'anatomie de la réaction

### L'idée

Avant de tester quoi que ce soit, décrire : que fait un cours le jour d'une annonce, et dans quel sens ?

### Les maths

**Distribution du CAR de réaction** (*Distribution des réactions*). Moyenne, médiane, écart-type, asymétrie, aplatissement, quantiles 5 % et 95 %, probabilité de hausse $P(CAR>0)$ avec son intervalle de Wilson (chapitre 11) et la probabilité de **gros mouvement** :

$$
P\big(z^{\text{abs}} > k\big),\qquad k=3\ \text{par défaut}\quad(\text{réglage }\texttt{big\_move\_sigma}).
$$

Repère : pour des rendements normaux sur une seule séance, $P(|Z|>2)=4{,}6\ \%$ et $P(|Z|>3)=0{,}27\ \%$. Si des « gros mouvements » à 3 écarts-types arrivaient, par exemple, dans 15 % des annonces, cela dirait que le jour d'annonce est **loin** d'un jour normal.

**Overnight contre intraday.** Avec les notations du chapitre 3, pour chaque événement la part overnight est $|on_0|\big/\big(|on_0|+|id_0|\big)$ ; on affiche sa médiane et la part cumulée $\sum|on|\big/\big(\sum|on|+\sum|id|\big)$, ainsi que la fréquence où l'intraday va dans le **même sens** que le gap (poursuite).

**Continuation ou retournement.** On mesure le lien entre la réaction $CAR_i[\text{réaction}]$ et le rendement anormal ultérieur $y_i$ ($[+2,+5]$, $[+2,+20]$, $[+2,+60]$), par la corrélation de Spearman $\rho$ et la pente d'une droite de régression :

$$
\rho<0:\ \text{retournement (le marché a sur-réagi)}\qquad\rho>0:\ \text{continuation (sous-réaction, dérive).}
$$

**« Beat and drop ».** Un *beat* est un BPA publié supérieur à l'estimé. La carte compte la part de beats suivis d'une baisse et la part de *misses* (BPA publié inférieur à l'estimé) suivis d'une hausse, et compare par un test exact de Fisher la fréquence de baisse après un beat à celle des autres cas. Une fréquence de baisse élevée après un beat dit que le consensus **officiel** n'est pas celui du marché (les attentes implicites étaient plus hautes).

**Concentration des sauts.** Pour un titre et une année, la part de la variance annuelle portée par les jours d'annonce :

$$
\text{part observée}=\frac{\sum CAR^2}{\sum CAR^2+\bar\sigma^2\,(252-n_{\text{jours d'annonce}})},\qquad
\text{part si jours ordinaires}=\frac{n_{\text{jours d'annonce}}}{252},
$$

et le rapport entre les deux. Un rapport de 6 signifie que les jours d'annonce pèsent six fois ce que pèseraient des jours ordinaires.

### Les pièges

- La moyenne du CAR de réaction mélange des fenêtres $[0]$ et $[0,+1]$ selon l'événement (timing certain ou non) : elle est lisible, pas testable sans précaution (d'où la carte *Event study* pour les tests).
- L'asymétrie et l'aplatissement d'un petit échantillon sont très instables : lire avec le score de fiabilité.

---

## Chapitre 13. Famille B : la volatilité autour de l'annonce

### L'idée

L'annonce est un **événement de volatilité** : l'incertitude monte avant, se résout le jour J0, retombe après (le *vol crush* des options, c'est-à-dire la chute de la volatilité implicite après l'annonce). La page mesure la version « réalisée » de cela avec des cours journaliers.

### Les maths

**Volatilité de Parkinson (1980).** Avec seulement le plus haut $H_t$ et le plus bas $L_t$ de la séance, on estime la variance du jour par

$$
\hat\sigma^2_{P,t}=\frac{\big[\ln(H_t/L_t)\big]^2}{4\ln 2}.
$$

D'où vient le $4\ln2$ : pour un mouvement brownien continu de variance $\sigma^2$ par jour, l'espérance du carré de l'amplitude haut-bas est $4\ln2\,\sigma^2$. L'estimateur est donc sans biais en temps continu ; sur des données réelles (pas de prix continu), il est un peu trop bas. Une simulation d'un brownien à 2 000 pas par jour donne $0{,}969\,\sigma^2$, qui tend vers 1 quand le pas diminue. Plus efficace qu'un carré de rendement journalier car il utilise toute l'amplitude de la séance.

**Volatilité relative.** Pour chaque jour de la trajectoire, $\sqrt{\hat\sigma^2_{P,t}\big/\overline{\hat\sigma^2_{P}}_{\text{estimation}}}$ : 1 vaut « volatilité habituelle du titre ». La carte *Volatilité réalisée avant et après* trace la moyenne de ce rapport de $-10$ à $+20$ et teste la chute après l'annonce :

$$
\text{crush}_i=\ln\frac{\text{vol relative moyenne sur }[+2,+5]}{\text{vol relative moyenne sur }[-5,-1]},\qquad
H_0:\ \text{médiane}(\text{crush})=0\ \ (\text{Wilcoxon}).
$$

**HAR-RV avec variable d'annonce.** Le modèle HAR (*heterogeneous autoregressive*, Corsi, 2009) explique la volatilité du jour par celle de la veille, de la semaine et du mois, sur une échelle logarithmique. La carte ajoute des indicatrices d'événement :

$$
\ln RV_t=c+\beta_d\ln RV_{t-1}+\beta_w\ln\overline{RV}_{t-5\ldots t-1}+\beta_m\ln\overline{RV}_{t-22\ldots t-1}
+\delta_{\text{avant}}D^{[-3,-1]}_t+\delta_{\text{réaction}}D^{[0,+1]}_t+\delta_{\text{après}}D^{[+2,+5]}_t+u_t ,
$$

où $RV_t$ est la variance de Parkinson du jour et $D$ vaut 1 dans la fenêtre indiquée. Comme l'explicative est en logarithme, $e^{\delta}-1$ est l'**effet en pourcentage sur la variance** : $\delta_{\text{réaction}}=1{,}1$ signifierait une variance multipliée par $e^{1{,}1}\approx3$ les jours J0 et J+1, **au-delà** de ce que le HAR prédit seul. Erreurs groupées par titre.

**Mouvement implicite contre réalisé.** Un **straddle** (achat simultané d'un call et d'un put au même prix d'exercice) a une valeur d'autant plus grande que le titre est susceptible de bouger beaucoup dans l'un ou l'autre sens. À l'argent (strike ≈ cours $S$) et en ignorant taux et dividendes, si le mouvement jusqu'à l'échéance est normal $X\sim N(0,s^2)$ avec $s=\sigma\sqrt T$ :

$$
\frac{C+P}{S}\approx E|X|/S = s\sqrt{\tfrac2\pi}\approx0{,}8\,s .
$$

Le prix du straddle rapporté au cours est donc, en première approximation, le **mouvement absolu attendu par le marché des options**. La carte le compare au mouvement absolu réalisé :

$$
\text{prime de risque de volatilité d'événement}=\text{implicite}-\text{réalisé},\qquad\text{ratio}=\frac{\text{réalisé}}{\text{implicite}} ,
$$

testée par Wilcoxon (la prime est-elle centrée en 0 ?). Un ratio moyen sous 1 signifie que le marché des options paie en moyenne **plus** que ce que l'annonce déplace. La *Backtest de straddle* en déduit un rendement net d'acheter (ou de vendre) le straddle la veille : $\pm\dfrac{\text{réalisé}-\text{implicite}}{\text{implicite}}-c$, avec un coût aller-retour $c$ (5 % du straddle par défaut), évalué par la DSR (chapitre 23).

### Dans le programme

[`studies/vol_liq.py`](../../patrick/patrick/earnings/studies/vol_liq.py). La carte HAR est lourde (`heavy`) et se limite aux titres les plus fréquents (30 par défaut, 6 ans d'historique).

### Les pièges

- **Il n'existe pas d'historique gratuit d'options.** Les cartes *Mouvement implicite* et *Backtest de straddle* lisent des **instantanés quotidiens** pris avant chaque annonce puis appariés au mouvement réalisé : vides aujourd'hui, utilisables après quelques trimestres d'accumulation, et elles le disent.
- Le straddle d'un instantané **inclut les jours entre l'annonce et l'échéance** : il surestime le mouvement dû à l'annonce seule.
- La variance de Parkinson n'est pas une vraie volatilité intrajournalière (pas de données à la minute) : le HAR de la page est un HAR « de pauvre ».

---

## Chapitre 14. Famille C : volume et liquidité

### L'idée

Une annonce fait venir des acheteurs et des vendeurs : le volume monte, la liquidité se dégrade un instant (les écarts bid-ask s'élargissent). Quatre mesures, toutes calculées sans carnet d'ordres.

### Les maths

**Volume anormal.** Volume du jour divisé par le volume moyen de la fenêtre d'estimation :

$$
\text{vol\_ratio}_{i,t}=\frac{V_{i,t}}{\overline{V}_{i,\text{estimation}}}\quad(1=\text{volume habituel}),
$$

avec le test de Wilcoxon sur $\ln\big(\text{vol}_0/\text{vol}_{[-5,-1]}\big)$ pour l'effet « le jour de réaction trade plus que les jours précédents ». La **rotation** divise le volume par le nombre d'actions en circulation (valeur *actuelle* : approximation pour les anciennes annonces).

**Illiquidité d'Amihud (2002).**

$$
ILLIQ_t=\frac{|R_t|}{C_t\,V_t}\times10^{6},
$$

le mouvement du cours par dollar échangé : plus il est élevé, moins le marché absorbe de volume sans bouger. La carte compare la moyenne sur $[0,+1]$ et sur $[-5,-1]$ à celle de l'estimation, et teste $\ln(\text{ratio})\ne0$ par Wilcoxon.

**Spread de Corwin-Schultz (2012).** Estime le **spread bid-ask relatif** à partir des seuls plus hauts et plus bas de deux jours consécutifs. L'idée : l'amplitude haut-bas d'un jour mélange la variance du cours (qui croît avec le temps : elle double si l'on regarde deux jours) et le spread (qui est une constante, indépendante de la durée). En comparant l'amplitude d'un jour à celle de deux jours, on sépare les deux. Avec

$$
\beta=\sum_{j=0}^{1}\Big[\ln\frac{H_{t+j}}{L_{t+j}}\Big]^2,\qquad
\gamma=\Big[\ln\frac{\max(H_t,H_{t+1})}{\min(L_t,L_{t+1})}\Big]^2,\qquad k=3-2\sqrt2 ,
$$

$$
\alpha=\frac{\sqrt{2\beta}-\sqrt\beta}{k}-\sqrt{\frac{\gamma}{k}},\qquad
S=\frac{2\,(e^{\alpha}-1)}{1+e^{\alpha}}\quad(\text{négatif ramené à }0).
$$

Exemple : plus hauts $(102{,}0;\ 103{,}5)$, plus bas $(99{,}5;\ 100{,}2)$ sur deux jours : $\beta=0{,}001666$, $\gamma=0{,}001553$, $\alpha=0{,}003380$, soit $S\approx0{,}34\ \%$ (le spread vaut 0,34 % du cours).

**Le volume d'avant prédit-il l'amplitude ?** Corrélation de Spearman entre le volume anormal moyen des 5 séances précédentes et l'amplitude, puis une régression log-log **contrôlée par l'amplitude historique** du titre :

$$
\ln z^{\text{abs}}_i=c+\gamma_1\ln(\text{vol\_pre}_i)+\gamma_2\ln(\text{hist\_mean\_abs\_z}_i)+u_i ,
$$

erreurs groupées par semaine. Sans le contrôle, un titre qui est toujours très échangé **et** toujours très agité fausserait le lien.

### Les pièges

- Corwin-Schultz est **biaisé à la baisse** sur les titres très liquides (spread proche de 0 : beaucoup de valeurs négatives ramenées à 0).
- Les volumes sont faussés par un split dans la fenêtre : drapeau `split_flag`.

---

## Chapitre 15. Famille D : surprise, ERC et dérive post-annonce

### L'idée

Ce qui bouge le cours, ce n'est pas le résultat mais la **différence entre le résultat et ce qui était attendu**. Cette famille mesure cette surprise, la réponse du cours à la surprise (*earnings response coefficient*, ERC) et la question classique : le cours finit-il de s'ajuster **après** l'annonce (*post-earnings announcement drift*, PEAD, Ball et Brown 1968 ; Bernard et Thomas 1989) ?

### Les maths

**Surprise en pourcentage** (donnée par Yahoo avec les annonces passées) :

$$
S_n=\frac{EPS^{\text{publié}}_n-EPS^{\text{estimé}}_n}{|EPS^{\text{estimé}}_n|} .
$$

Elle est grossière : un BPA estimé proche de 0 donne des surprises énormes. D'où deux surprises **standardisées**, toutes deux construites uniquement avec le **passé** du titre (au moins 4 valeurs passées) :

$$
SUE_n=\frac{S_n-\bar S_{<n}}{s(S_{<n})},\qquad
SUE^{\text{sais}}_n=\frac{\Delta_n}{s(\Delta_{<n})}\ \text{ avec }\ \Delta_n=EPS_n-EPS_{n-4}.
$$

Le second est le SUE à « marche aléatoire saisonnière » (variation du BPA par rapport au même trimestre de l'année précédente, rapportée à la variabilité passée de cette variation).

**ERC.** Régression de la réaction sur la surprise, par groupe (tous, secteur, pays...) :

$$
CAR_i=c+\mathrm{ERC}\cdot x_i+u_i ,
$$

où $x_i$ est la surprise rognée à 2 %/98 % (en fraction du BPA estimé pour la surprise en pourcentage : 0,10 = +10 %), erreurs groupées par semaine. Un ERC positif : le marché récompense les surprises positives, et $\mathrm{ERC}=0{,}05$ veut dire que +10 points de surprise valent +0,5 point de réaction. La carte affiche aussi la réaction moyenne par quintile de surprise (lecture sans régression).

**PEAD.** Les événements sont classés par décile de $SUE$ (5 classes si $N<200$, 3 si $N<80$), puis on regarde le CAR cumulé après l'annonce par classe. Le test porte sur l'**écart haut moins bas** de la dérive (test t de Welch) et sur la pente de la dérive contre le **rang** percentile de la surprise (erreurs groupées par semaine). La littérature décrit cette dérive comme très affaiblie, voire disparue, dans les grandes capitalisations (par exemple Martineau, 2021) : la carte demande si elle existe dans **ton** échantillon, elle ne le présume pas.

**Séries de dépassements.** Réaction selon le nombre de *beats* consécutifs précédents (0, 1, 2, 3 ou plus), testée par Kruskal-Wallis. L'hypothèse : une série de beats habitue le consensus à monter, donc le beat suivant surprend moins.

### Les pièges

- **Chiffre d'affaires et guidance : aucun historique gratuit.** Les cartes correspondantes affichent « indisponible » plutôt qu'un chiffre inventé.
- La surprise historique repose sur l'estimé que Yahoo conserve pour chaque annonce passée. Sa qualité (date à laquelle il a été figé, révisions) ne peut pas être auditée gratuitement : à lire avec cette réserve.

---

## Chapitre 16. Familles E et F : anticipation, sentiment, analystes

### L'idée

Tout ce qui est visible **avant** l'annonce (avance du cours, ton des news, révisions d'analystes) peut-il prédire la réaction ? Cette famille est la plus exposée à la **fuite d'information** (utiliser sans le savoir quelque chose qu'on ne pouvait pas connaître à la date de la décision). Les règles du programme sont donc strictes.

### Les maths

**Run-up** (carte *Run-up pré-annonce*). $CAR[-10,-1]$. Deux lectures : $\rho(\text{run-up},CAR)$ pour le **sens** et $\rho(|\text{run-up}|,z^{\text{abs}})$ pour l'**amplitude**. Un $\rho>0$ évoque une fuite d'information (le cours « sait » avant) ; un $\rho<0$ évoque des attentes déjà intégrées (les bonnes nouvelles ont déjà fait monter le titre, la réaction est plus faible).

**Vendeurs à découvert.** Part du flottant vendue à découvert, par instantané (Yahoo ne donne que la valeur du jour, avec une publication différée de l'ordre de deux semaines) : l'historique se construit au jour le jour.

**Sentiment des news** (carte *Sentiment des news avant l'annonce*). Une news est rattachée à un titre par un lien d'entité ou par le nom de la société dans le titre, et reçoit un score de sentiment (lexique) et un indice de nouveauté. Sur la fenêtre $[-7\text{ j},\ -1\text{ j}]$ avant le début du jour d'annonce :

$$
\text{sent\_mean}=\text{moyenne des scores},\qquad
\text{attention\_z}=\frac{n_{\text{cur}}-\overline{n}_{\text{base}}}{s(n_{\text{base}})},\qquad
\text{sent\_surprise}=\text{sent\_mean}-\overline{\text{sent\_mean}}_{\text{base}} ,
$$

où « base » regroupe jusqu'à 8 fenêtres hebdomadaires précédentes (il en faut au moins 4 pour l'attention, 3 pour la surprise de sentiment) et où seules sont utilisées les fenêtres couvertes par le magasin de news. La **surprise de sentiment** évite de prendre un titre structurellement « positif » pour un signal. Chaque variable est reliée à la réaction (sens ou amplitude) par une corrélation de Spearman.

**Règle du point-in-time pour les news.** Seul l'instant où le programme a **réellement connu** la news (`known_at`) compte, jamais la date affichée par la source : une news antidatée ne doit pas entrer. Les news **postérieures** à l'annonce servent à une analyse a posteriori (carte *Réaction des news après l'annonce*) et ne doivent **jamais** entrer dans un modèle prédictif, parce qu'elles reprennent le mouvement du cours au lieu de l'annoncer.

**Décalage news → prix.** Corrélation croisée entre le sentiment quotidien $s_{t-k}$ et le rendement $R_t$, pour $k\in[-3,+3]$. $k>0$ : le sentiment **précède** le rendement (information exploitable si $\rho\neq0$) ; $k\le0$ : les news ne font que reprendre le mouvement.

**Résumé du consensus des analystes** (fonction `consensus.summarize`) :

$$
\text{dispersion}=\frac{EPS_{\text{haut}}-EPS_{\text{bas}}}{|EPS_{\text{moyen}}|},\qquad
\text{rév}_{h}=\frac{EPS^{\text{actuel}}}{EPS^{\text{il y a }h\text{ jours}}}-1,\qquad
\text{rév. nettes}=\frac{\text{hausses}-\text{baisses}}{\max(\text{hausses}+\text{baisses},1)},
$$

$$
\text{score reco.}=\frac{(\text{achat fort}+\text{achat})-(\text{vente}+\text{vente forte})}{\text{total}} .
$$

**Le principe qui commande tout dans cette famille.** Yahoo ne donne le consensus que tel qu'il est **aujourd'hui**. Tester un signal d'analyste sur des annonces passées avec la valeur d'aujourd'hui serait contaminé par l'information future. Le programme :

- prend **chaque jour** un instantané daté (consensus, vendeurs à découvert, straddle de la prochaine annonce) pour les titres suivis (`patrick earnings snapshot`, aussi lancé la nuit) ;
- traite le signal analyste comme un **affichage** tant que moins de 60 annonces passées disposent d'un instantané **daté pris avant elles** ;
- n'exploite rétrospectivement que la seule série datée gratuite : les **changements de recommandation** (`upgrades_downgrades`), avec un score $-1/0/+1$ par note, le nombre net de relèvements et la variation moyenne des objectifs de cours $\text{cible actuelle}/\text{cible précédente}-1$ dans les 30 jours avant l'annonce, reliés à la réaction par Spearman (avec la réserve que Yahoo peut être incomplet).

**Biais du consensus.** Taux de dépassement $=\text{beats}/N$, testé contre 50 % par un test binomial exact, et rétréci vers le secteur par le même mécanisme que le chapitre 18. La littérature américaine cite environ 70 % de dépassements : les directions guident les analystes, qui visent bas.

### Les pièges

- **La fuite d'information est le piège numéro un** de cette famille ; une fois trouvée, elle donne des résultats trop beaux (voir le chapitre 20 pour un cas vécu).
- **Le texte des conférences téléphoniques** (ton Loughran-McDonald, prudence du discours, contraste discours préparé / questions-réponses) est **indisponible** gratuitement : la carte le dit.

---

## Chapitre 17. Familles G, H, I, J : croisements, régimes, structure, calendrier

### Famille G : transmission entre titres

**Lecture croisée.** La réaction d'un titre qui publie plus tard est-elle liée à celle de ses pairs qui ont déjà publié ? Pour chaque événement $i$, on prend les pairs (même secteur ou même industrie, autres titres) dont J0 est strictement antérieur et dans les 10 jours calendaires précédents ; $\bar z^{\text{pairs}}_i$ est la moyenne de leurs réactions standardisées.

$$
z_i=c+\gamma\,\bar z^{\text{pairs}}_i+u_i ,
$$

erreurs groupées par semaine. $\gamma>0$ : les pairs qui publient avant « informent » ceux qui publient après. Les chocs de marché communs étant déjà retirés des rendements anormaux, ce qui reste est un lien sectoriel.

**Leader → suiveurs.** Même régression avec le **leader** (le titre de plus grande capitalisation d'un secteur à au moins 3 titres) au lieu de la moyenne des pairs. Le graphe fournisseurs-clients n'est pas disponible gratuitement : le « leader » est un substitut.

**Impact sur l'indice.** Un jour donné, avec les annonces américaines de l'échantillon, de capitalisation $m_j$, on forme $w_j=m_j/\sum m$ et

$$
\text{contribution}=\sum_j w_j\,CAR_j,\qquad R_{S\&P}=c+\gamma\cdot\text{contribution}+u ,
$$

régression du rendement du S&P 500 sur la contribution. Les poids ne sont pas ceux de l'indice (non gratuits) : c'est un indicateur de direction, pas une attribution comptable.

**Densité de la saison.** $\text{densité}_w=\dfrac{\text{annonces de la semaine }w}{\text{titres déjà suivis}}$ (corrige la croissance de l'univers), corrélation de Spearman avec la volatilité réalisée annualisée du S&P 500 de la semaine, $s\sqrt{252}$ ($s$ = écart-type des rendements journaliers), et avec le niveau et la variation du VIX. Corrélation, pas causalité : une saison dense coïncide avec l'actualité macro du trimestre.

### Famille H : régimes de marché

**Modèle de Markov caché (HMM).** On suppose que le marché est, à chaque séance, dans un état caché $s_t$ (calme ou agité) qu'on n'observe pas, qui évolue selon une matrice de transition $A$ ($A_{ij}=P(s_t=j\mid s_{t-1}=i)$), et que le rendement de l'indice a une loi normale propre à chaque état, $r_t\mid s_t=j\sim N(\mu_j,\sigma_j^2)$ (Hamilton, 1989). La **probabilité filtrée** de l'état agité, calculée avec le seul passé par la récurrence « avant » (*forward*)

$$
\alpha_t(j)\ \propto\ f_j(r_t)\sum_i\alpha_{t-1}(i)\,A_{ij},
$$

est découpée en trois classes par ses terciles : **calme / normal / stress**. Le régime d'un événement est celui connu à la séance qui précède sa réaction. (Les paramètres $\mu_j,\sigma_j,A$ sont estimés sur tout l'historique de l'indice, comme sur la page Synthèse ; seule la probabilité d'état est causale.)

**Terciles du VIX.** Niveau du VIX à la séance précédente, comparé aux quantiles à 33 % et 67 % de **tout le passé** du VIX (quantiles « expansifs », décalés d'une séance) : `bas`, `moyen`, `haut`. Aucune information future.

La carte compare l'amplitude (ou le CAR, le volume...) entre niveaux par Mann-Whitney contre un niveau de référence et par Kruskal-Wallis, **avec correction FDR de Benjamini-Hochberg à l'intérieur de la carte** (chapitre 10).

### Famille I : structure

**Amplitude par taille, bêta, momentum, valeur, qualité, secteur, pays, devise.** Chaque facteur numérique est découpé en classes par quantiles (5 pour la taille, 3 pour le reste) et l'amplitude comparée par Kruskal-Wallis. *Taille, bêta et momentum* sont mesurés avant chaque annonce (point-in-time) ; *valeur* (P/B) et *qualité* (ROE) sont des instantanés **actuels** de Yahoo, donc indicatifs pour les anciennes annonces.

**Effet de la devise.** Spearman entre le mouvement de la devise contre le dollar le jour de réaction et le CAR (sens), ou son module et l'amplitude. Le CAR est en devise locale : un lien reflète une réaction commune (exportateurs) et non une conversion.

**Introductions récentes.** Amplitude des quatre premières annonces après la cotation (si moins de 3 ans) contre les suivantes, Mann-Whitney.

### Famille J : calendrier

- **Jour de la semaine et moment de la journée** (BMO, AMC) : amplitude et sens par modalité, Kruskal-Wallis.
- **Premier ou dernier annonceur de la saison.** Dans un secteur et un trimestre de calendrier, position relative $r=(\text{rang}-\tfrac12)/n$ ; premier tiers ($r<1/3$) contre dernier tiers ($r>2/3$), Mann-Whitney.
- **Trimestriel contre annuel.** Une annonce est « annuelle » quand le trimestre qu'elle commente clôt l'exercice (mois de clôture tiré de la fiche Yahoo).
- **Retard par rapport à la date habituelle.** $\text{retard}_n=\text{délai}_n-\text{médiane}(\text{délais passés du même trimestre})$ où $\text{délai}=$ jours entre la fin de période et l'annonce ; Spearman retard → CAR (Chambers et Penman, 1984 : à vérifier aujourd'hui).
- **Prime d'annonce.** CAAR sur $[0]$ et $[0,+1]$ de tout l'échantillon (BMP et bootstrap en blocs), et par année (Savor et Wilson, 2016 documentent un rendement anormal moyen positif les jours d'annonce : ici à tester, pas à présumer).
- **Ligne locale contre ADR.** Pour un titre qui existe sur deux places (le local et son *American Depositary Receipt*, ou une ligne liée), écart des CAR sur la fenêtre commune, décalage de J0 entre les deux places et contribution du change.

### Les pièges

- Plus on **découpe** (secteur × pays × régime...), plus les groupes sont petits et plus les p-values brutes sont trompeuses : c'est pourquoi chaque découpage alimente le registre FDR.
- Les capitalisations, P/B et ROE de Yahoo sont **actuels** : pour une annonce de 2015 ils décrivent la société d'aujourd'hui. Les cartes l'indiquent.


---

# Partie IV. Modéliser et décider

## Chapitre 18. Petit échantillon : fiabilité et rétrécissement bayésien

### L'idée

Un titre a 12 à 40 annonces. Sa moyenne de réaction est donc entachée d'une grande incertitude : un titre à 4 annonces peut sembler « très agité » ou « très calme » par pur hasard. Deux réponses, présentes sur toute la page :

1. un **score de fiabilité** (0 à 100), affiché à côté de chaque statistique ;
2. un **rétrécissement** (*shrinkage*, ou *partial pooling*) : la moyenne d'un titre est ramenée vers celle de son secteur, d'autant plus fort que le titre a peu d'annonces.

### Les maths : le score de fiabilité

$$
\text{score}=100\Big(0{,}5\,s_n+0{,}3\,s_{\text{disp}}+0{,}2\,s_{\text{âge}}\Big),
\qquad
s_n=1-e^{-n/25},\quad s_{\text{disp}}=e^{-\min(\mathrm{se}_{\text{rel}},\,5)},\quad s_{\text{âge}}=e^{-\text{âge}/8} ,
$$

où $\mathrm{se}_{\text{rel}}=\dfrac{s/\sqrt n}{|\bar x|}$ est l'erreur-type de la moyenne **rapportée à la moyenne** (une moyenne de 3 % avec une erreur-type de 3 % vaut $\mathrm{se}_{\text{rel}}=1$ : elle est indistinguable de zéro) et l'âge est la médiane de l'ancienneté des événements en années.

Quand l'écart-type n'est pas calculable ou l'âge est inconnu, le programme prend $\mathrm{se}_{\text{rel}}=1$ et $s_{\text{âge}}=0{,}7$ (hypothèses prudentes). Niveaux : $\ge75$ « bon », $\ge55$ « moyen », $\ge35$ « faible », en dessous « insuffisant », et **toujours « insuffisant » si $n<8$** quoi qu'en dise le reste.

| $n$ | $s_n$ | score (dispersion et âge inconnus) | niveau |
|---|---|---|---|
| 8 | 0,27 | 38,7 | faible |
| 25 | 0,63 | 56,6 | moyen |
| 60 | 0,91 | 70,5 | moyen |
| 100 | 0,98 | 74,1 | moyen |
| 200 | 1,00 | 75,0 | bon |

La forme $1-e^{-n/25}$ dit que les 25 premières annonces apportent l'essentiel de la fiabilité (63 %), et que passer de 60 à 100 annonces change peu. Avec une dispersion et un âge inconnus, le score plafonne à 75 : sans mesure de l'erreur-type relative, on ne dit jamais « bon » avant 200 annonces.

### Les maths : le rétrécissement

**Modèle.** Chaque titre $i$ a une « vraie » amplitude moyenne $\theta_i$ (inconnue). On suppose que ces valeurs vraies se répartissent autour de la moyenne du secteur $\mu$ avec une dispersion $\tau^2$ (**variance entre titres**), et que les observations d'un titre fluctuent autour de $\theta_i$ avec une variance $\sigma^2$ (**variance à l'intérieur d'un titre**) :

$$
\theta_i\sim N(\mu,\tau^2),\qquad y_{i,j}\mid\theta_i\sim N(\theta_i,\sigma^2),\qquad \bar y_i\mid\theta_i\sim N\!\big(\theta_i,\sigma^2/n_i\big).
$$

**Estimation de $\theta_i$.** La moyenne a posteriori (celle que donne la règle de Bayes) est une moyenne pondérée entre la moyenne observée et celle du secteur :

$$
\hat\theta_i=w_i\,\bar y_i+(1-w_i)\,\mu,\qquad
\boxed{\,w_i=\frac{\tau^2}{\tau^2+\sigma^2/n_i}=\frac{n_i}{n_i+k}\,},\qquad k=\frac{\sigma^2}{\tau^2}.
$$

*D'où vient $w$.* On a deux « mesures » de $\theta_i$ : la moyenne observée (incertitude $\sigma^2/n_i$) et la moyenne du secteur (incertitude $\tau^2$). Combiner deux mesures revient à les pondérer par l'**inverse** de leur variance, ce qui donne exactement $w_i$. C'est aussi, sous une autre forme, l'estimateur de James et Stein ; Efron et Morris (1973) en donnent une démonstration très lisible.

**Exemple.** Avec une dispersion entre titres de 2 points ($\tau^2=0{,}0004$) et une dispersion intra-titre de 4 points ($\sigma^2=0{,}0016$), $k=4$ :

| Annonces $n$ | 1 | 4 | 16 | 40 |
|---|---|---|---|---|
| Poids du titre $w$ | 0,20 | 0,50 | 0,80 | 0,91 |

Un titre à 4 annonces dont l'amplitude moyenne observée est de 6 % dans un secteur à 3 % est ramené à $0{,}5\times6+0{,}5\times3=4{,}5\ \%$ ; à 40 annonces, il resterait à $0{,}91\times6+0{,}09\times3=5{,}7\ \%$.

**Estimation de $\sigma^2$ et $\tau^2$ (méthode des moments).** Par la moyenne des variances intra-titre pour $\sigma^2$, et par l'excédent de la variance des moyennes sur ce que l'on attendrait du seul bruit :

$$
\hat\sigma^2=\overline{\operatorname{Var}_i},\qquad
\hat\tau^2=\max\Big(\operatorname{Var}(\bar y_i)-\overline{\hat\sigma^2/n_i},\ 0\Big).
$$

La moyenne du secteur $\mu$ est la moyenne de toutes les observations des titres du secteur s'il y en a au moins 5, sinon la moyenne générale.

### Dans le programme

[`reliability.py`](../../patrick/patrick/earnings/reliability.py) : `reliability` et `partial_pooling`. La **vue semaine** de la page classe les titres de la newsletter par leur amplitude attendue, c'est-à-dire la moyenne **rétrécie** de $|CAR|$ ([`service.week_rows`](../../patrick/patrick/earnings/service.py)). La carte *Rétrécissement bayésien empirique* en vérifie l'intérêt **hors échantillon** : pour prédire l'amplitude du prochain événement, elle compare l'erreur absolue moyenne de la moyenne passée brute, de la moyenne passée rétrécie (poids $n/(n+k)$, $k=\sigma^2_{\text{intra}}/\tau^2_{\text{inter}}$ estimé sur l'échantillon) et de la moyenne passée du secteur.

### Les pièges

- Le rétrécissement **suppose** que les titres d'un secteur se ressemblent (même $\mu$) ; un titre vraiment atypique (une biotech dans le secteur « santé ») est tiré à tort vers une moyenne qui n'est pas la sienne.
- $\hat\tau^2$ peut valoir 0 sur un petit échantillon (poids du titre alors 0) : le titre n'est alors plus décrit que par son secteur ; la fiabilité l'indique.

---

## Chapitre 19. Prédire l'amplitude : le modèle en panel

### L'idée

L'amplitude de la réaction est bien plus prévisible que son sens (chapitre 1). Le modèle de la carte *Modèle d'amplitude* tente de la prédire **avant l'annonce** à partir de caractéristiques connues à l'avance, puis juge ses prédictions **sur des événements qu'il n'a jamais vus**.

Un **panel** est un tableau d'événements de nombreux titres, une ligne par événement. On ne peut pas entraîner un modèle par titre (12 à 40 annonces seulement) : un seul modèle **poolé** apprend sur tous les titres à la fois, avec des variables normalisées pour qu'elles soient comparables.

### Les maths : la cible et les variables

**Cible.** $y_i=\ln\big(z^{\text{abs}}_i+0{,}1\big)$ où $z^{\text{abs}}_i=|CAR_i|/\hat\sigma_i$ (amplitude en écarts-types quotidiens). Le logarithme rend la distribution moins asymétrique (quelques réactions énormes tirent la moyenne) ; le décalage de 0,1 évite $\ln0$.

**Variables** (12, toutes connues **avant** l'annonce) :

| Variable | Définition | Idée |
|---|---|---|
| `f_hist` | $\ln(\text{moyenne passée de }z^{\text{abs}}\text{ du titre}+0{,}1)$ | un titre agité le reste |
| `f_sector` | idem pour le secteur (événements dont J0 est strictement antérieur) | repli quand le titre a peu d'histoire |
| `f_vol` | $\ln$ de la volatilité quotidienne de la fenêtre d'estimation | volatilité de fond |
| `f_size` | $\ln$ du volume en valeur échangé | taille, liquidité |
| `f_beta` | bêta de marché | sensibilité à l'indice |
| `f_mom` | $\lvert$momentum sur $[-250,-30]\rvert$ | gagnants / perdants extrêmes |
| `f_runup` | $\lvert$run-up$\rvert/\hat\sigma$ | information déjà en mouvement |
| `f_volpre` | $\ln$ du volume anormal sur $[-5,-1]$ | attention avant l'annonce |
| `f_unc` | timing incertain (0/1) | fenêtre $[0,+1]$ au lieu de $[0]$ |
| `f_annual` | annonce annuelle (0/1) | structure d'information différente |
| `f_evno` | $\ln$ du numéro d'annonce du titre | jeunesse de l'historique |
| `f_stress` | régime « stress » (0/1) | amplitude en période agitée |

**Historique point-in-time.** Pour un titre, avec $z^{\text{abs}}_{i,1},\dots,z^{\text{abs}}_{i,n}$ ses réactions classées par date,

$$
\text{hist\_mean\_abs\_z}_{i,n}=\frac{1}{n-1}\sum_{m<n}z^{\text{abs}}_{i,m}\qquad(\text{le }n\text{-ième événement n'est jamais inclus}).
$$

Dans le code, c'est « la série décalée d'un cran puis moyenne expansive ». Le secteur suit la même règle sur tous ses titres (au moins 5 observations passées).

### Les maths : le modèle linéaire (ridge)

Les variables sont imputées (valeur médiane de l'entraînement pour les manquantes) puis **standardisées** (moyenne 0, écart-type 1) avec les moyennes et écarts-types de l'**entraînement seul**. Le modèle de base est une **régression ridge** (Hoerl et Kennard, 1970), une régression linéaire dont on **pénalise** la taille des coefficients :

$$
\hat{\mathbf w}=\arg\min_{\mathbf w}\ \sum_i\big(\tilde y_i-\mathbf x_i'\mathbf w\big)^2+\lambda\,\|\mathbf w\|^2
\quad\Longrightarrow\quad
\hat{\mathbf w}=(X'X+\lambda I)^{-1}X'\tilde{\mathbf y},
$$

avec $\tilde y$ centrée (la constante n'est pas pénalisée) et $\lambda=8$. La pénalité $\lambda\|\mathbf w\|^2$ empêche les coefficients de devenir énormes quand deux variables sont presque redondantes (par exemple volatilité et taille) et limite le surapprentissage. Plus $\lambda$ est grand, plus les coefficients sont tirés vers 0 ; $\lambda\to0$ redonne les moindres carrés. (Vérification numérique : la formule fermée coïncide avec `sklearn.linear_model.Ridge` à 5 décimales près, pour $\lambda=0{,}0001$, $8$ et $100$.)

Le second modèle est un **gradient boosting** (`HistGradientBoostingRegressor`) : une somme de petits arbres de décision de profondeur 3 (120 arbres, pas d'apprentissage 0,05), chacun corrigeant l'erreur des précédents. Il peut capturer des interactions que le modèle linéaire ne voit pas.

La prédiction revient à l'échelle de $z^{\text{abs}}$ par $\hat z=\max\big(e^{\hat y}-0{,}1,\ 0{,}05\big)$.

### Les maths : valider hors échantillon sans tricher

On ne juge jamais un modèle sur les données qui l'ont entraîné. La validation est **chronologique** :

```
événements triés par J0 :  ├──────────── 40 % : jamais testés ────────────┤
plis de test (5 blocs)                                       [ test 1 ][ test 2 ][ test 3 ][ test 4 ][ test 5 ]
entraînement du pli k :  tous les événements dont J0 < (début du pli k) − 10 jours   ◄─ « purge »
```

- L'entraînement du pli $k$ n'inclut que des événements **antérieurs** au test, jamais des plis mélangés dans le temps.
- La **purge** retire les événements d'entraînement trop proches du début du test (10 jours) : des annonces de la même semaine partagent les mêmes chocs de marché, donc entraîner sur l'une et tester sur l'autre revient à donner la réponse au modèle.
- Il faut au moins 40 événements d'entraînement et 3 de test par pli.

**Baselines obligatoires.** Un modèle n'a de valeur que s'il bat le plus simple des pronostics : la **moyenne passée du titre** (repli : celle du secteur) et la **moyenne passée du secteur**.

**Métriques** (hors échantillon, sur tous les plis mis bout à bout) :

- **MAE** (erreur absolue moyenne) : $\frac1n\sum|z-\hat z|$, en écarts-types quotidiens ;
- **QLIKE**, une perte adaptée aux **variances** (Patton, 2011) : si $\sigma^2$ est la variance réalisée et $h$ la prévision,

$$
\mathrm{QLIKE}=\frac{\sigma^2}{h}-\ln\frac{\sigma^2}{h}-1\ \ge 0,
$$

nulle seulement si $h=\sigma^2$, et qui pénalise plus une prévision trop basse qu'une prévision trop haute pour une même erreur absolue sur la variance. Ici la « variance » réalisée est $z^2$ et la prévision $h=\hat z^2\cdot\pi/2$ : pour une loi demi-normale (valeur absolue d'une normale), $E[z^2]=(E|z|)^2\cdot\pi/2$, donc $h$ est la variance déduite d'un $|z|$ prévu. Exemples avec $\hat z=1$ (donc $h\approx1{,}571$) : la perte vaut 0,088 si $z=1$ (elle n'est pas nulle, car QLIKE s'annule pour $z=\sqrt{\pi/2}\,\hat z\approx1{,}25$), 0,612 si $z=2$ et 0,997 si $z=0{,}5$.
- **Corrélation de rang** de Spearman entre prévision et réalisé ;
- **test de Diebold-Mariano** contre la baseline (ci-dessous).

**Test de Diebold-Mariano (1995).** Les deux modèles ont-ils vraiment des précisions différentes, ou l'écart observé est-il du bruit ? On forme la différence des pertes événement par événement, $d_t=L_t^{A}-L_t^{B}$ (négative si le modèle $A$ fait mieux), puis

$$
DM=\frac{\bar d}{\sqrt{\widehat V/T}},\qquad
DM^{*}=DM\cdot\sqrt{\frac{T+1-2h+h(h-1)/T}{T}},
$$

$\widehat V$ étant la variance de long terme de $d_t$ (qui tient compte d'une autocorrélation jusqu'au retard $h-1$ quand les prévisions sont à horizon $h>1$). La correction de Harvey, Leybourne et Newbold (1997) est toujours appliquée et $DM^{*}$ est comparé à une loi de Student à $T-1$ degrés de liberté. Pour un horizon $h=1$ comme ici, il n'y a pas de recouvrement et l'implémentation du projet (module `validation/diebold_mariano.py`) exige au moins 10 observations.

**Lecture.** « Le modèle bat la moyenne passée du titre » exige les deux conditions à la fois : une MAE plus basse **et** un DM significatif (p < 5 %). Le gain est affiché : $1-\mathrm{MAE}_{\text{modèle}}/\mathrm{MAE}_{\text{titre}}$.

### Dans le programme

[`model.py`](../../patrick/patrick/earnings/model.py) : `build_features`, `target_amplitude`, `walk_forward_folds`, `evaluate_amplitude`, `importance_ridge` ; carte `p_amplitude` dans [`studies/probabilistic.py`](../../patrick/patrick/earnings/studies/probabilistic.py). Le panel est construit par [`panel.py`](../../patrick/patrick/earnings/panel.py) (`_add_history` pour les colonnes point-in-time).

### Les pièges

- **Fuite d'information** : toute variable calculée avec l'événement testé, ou après lui, rend les résultats trop beaux. Les colonnes d'historique excluent l'événement testé ; la surprise de BPA de l'annonce testée (publiée en même temps que la réaction) **ne peut pas** servir à prédire, elle sert à expliquer (famille D).
- Un petit panel donne des plis de test de quelques dizaines d'événements : la MAE a une marge d'erreur large, d'où la fiabilité affichée.

---

## Chapitre 20. Prédire le sens : le modèle de direction

### L'idée

Le sens (hausse ou baisse) est proche de l'efficience : on s'attend à un résultat à peine meilleur que le hasard. Un résultat spectaculaire serait **suspect**, à vérifier contre une fuite d'information avant d'être cru.

### Les maths

**Régression logistique.** Elle modélise la probabilité d'une hausse :

$$
P(y=1\mid\mathbf x)=\frac{1}{1+e^{-(w_0+\mathbf w'\mathbf x)}},
$$

ajustée avec une pénalité $L^2$ (paramètre `C = 0,3`, soit une régularisation plus forte que la valeur par défaut). Les variables n'utilisent que des informations antérieures à l'annonce testée : surprise de l'annonce **précédente**, série de dépassements, signe du CAR précédent, run-up et momentum normalisés, régime de stress, taux de dépassement passé.

**Métriques.**

- **AUC** (aire sous la courbe ROC) : probabilité qu'une annonce tirée au hasard parmi les hausses reçoive une probabilité prédite supérieure à celle d'une annonce tirée parmi les baisses. 0,5 = aucun pouvoir, 1 = parfait.
- **Taux de réussite** (hit rate) du modèle contre celui d'une baseline de classe majoritaire.
- **Score de Brier** : $\frac1n\sum(p_i-y_i)^2$, l'erreur quadratique moyenne d'une probabilité (0 = parfait ; une prévision toujours à 50 % donne 0,25). Comparée à la fréquence passée de hausses, avec un test de Diebold-Mariano sur les pertes de Brier.
- **Diagramme de fiabilité** : on classe les événements par probabilité prédite (déciles) et l'on compare à la fréquence réellement observée ; les points doivent suivre la diagonale.

### Un cas vécu : le piège de la fuite

Lors de la mise au point sur les vraies données, la première version du modèle de direction affichait un **AUC de 0,62**. C'était faux : la surprise de BPA **de l'annonce testée** figurait parmi les variables. Or cette surprise est publiée **en même temps** que la réaction du cours : le modèle « prédisait » la hausse en connaissant déjà le résultat. Correction : seules les surprises des annonces **précédentes** entrent (`f_prev_surprise`), et une liste d'interdits (`FORBIDDEN_FEATURES`) ainsi qu'un test empêchent leur retour. Le chiffre de 0,62 n'était pas un résultat, c'était un symptôme.

Règle pratique : **un résultat étonnamment bon est d'abord un défaut à chercher**, pas une découverte à fêter.

---

## Chapitre 21. Aller au-delà de la moyenne : quantiles et intervalles conformes

### L'idée

Une prévision d'amplitude ponctuelle ne dit pas son incertitude. Deux compléments donnent une fourchette plutôt qu'un chiffre.

### Les maths

**Perte pinball et régression quantile.** Pour estimer le quantile de niveau $\tau$ (par exemple 90 % : la valeur que l'amplitude dépasse 10 % du temps), on minimise la perte *pinball*

$$
\rho_\tau(u)=\max\big(\tau u,\ (\tau-1)u\big),\qquad u=y-\hat q ,
$$

qui pénalise un quantile trop bas ($u>0$) par $\tau u$ et un quantile trop haut par $(1-\tau)|u|$. L'espérance de cette perte est minimale exactement au vrai quantile : sa dérivée est $F(q)-\tau$ (où $F$ est la fonction de répartition), qui s'annule quand $F(q)=\tau$. Exemple : $y=(0{,}4;\ 1{,}2;\ 2{,}0)$ prévu à 1,0 donne une perte moyenne de 0,22 pour $\tau=0{,}1$ et 0,38 pour $\tau=0{,}9$. La **régression quantile** (Koenker et Bassett, 1978) ajuste ainsi un modèle linéaire au quantile plutôt qu'à la moyenne, à $\tau\in\{0{,}1;\ 0{,}5;\ 0{,}9\}$.

La carte affiche, hors échantillon, la **couverture observée** (part des amplitudes réalisées sous le quantile prédit, qui doit valoir le niveau nominal $\tau$) et le **gain relatif** $1-\dfrac{\text{pinball du modèle}}{\text{pinball du quantile inconditionnel}}$. Un gain $\le0$ signifie que les variables n'apportent rien.

**Prédiction conforme (conformal prediction).** Méthode pour fabriquer un intervalle de prédiction **sans hypothèse sur la loi** (Vovk et ses coauteurs ; version « split »). Algorithme, pour un niveau $1-\alpha$ :

1. entraîner le modèle sur les 70 % les plus anciens de l'entraînement ;
2. calculer sur les 30 % restants (calibration) l'**erreur absolue** $|y_j-\hat y_j|$ de chaque événement ;
3. prendre le $\lceil(m+1)(1-\alpha)\rceil$-ième plus petit de ces $m$ écarts : $\hat q$ ;
4. pour un nouvel événement, l'intervalle est $[\hat y-\hat q,\ \hat y+\hat q]$.

Exemples du rang : pour $m=29$ et un niveau de 80 %, on prend le 24<sup>e</sup> écart ; pour $m=99$ et 90 %, le 90<sup>e</sup>. Garantie : si les événements sont **échangeables** (aucun ne ressemble plus à un autre qu'aux autres), l'intervalle contient la vraie valeur avec une probabilité au moins $1-\alpha$.

### Les pièges

- Les événements d'une même semaine **ne sont pas échangeables** (ils sont corrélés) et le régime de marché change : la couverture réelle peut s'écarter du niveau nominal. C'est pourquoi la carte **mesure** la couverture empirique hors échantillon au lieu de la supposer.

---

## Chapitre 22. Le score de sentiment composite

### L'idée

Sept indicateurs, une seule note lisible. Mais la note n'a de sens que si les poids viennent des **données** et que la note se lit **décomposée**.

### Les maths

Les sept composantes : sentiment des news, surprise de sentiment, choc d'attention (famille F), révisions du consensus à 30 jours, dispersion des analystes, run-up pré-annonce rapporté à $\hat\sigma$, et indicatrice de stress. Pour les $K$ composantes retenues, on les standardise ($z_j=(x_j-\mu_j)/s_j$, valeur manquante remplacée par 0 après standardisation) et on ajuste une **ridge** ($\lambda=20$) de la réaction standardisée $z_i$ (rognée à $[-5,5]$) :

$$
\text{score}_i=\sum_{j=1}^{K}w_j\,z_{ij},\qquad\text{contribution de }j=w_j\,z_{ij}.
$$

Pour un modèle **linéaire**, la contribution $w_jz_{ij}$ est exactement la valeur de Shapley (SHAP) de la variable $j$ : la note se lit comme une addition, composante par composante.

**Fiabilité de la note** : le $R^2$ **hors échantillon**, calculé en validation chronologique purgée (chapitre 19) :

$$
R^2_{\text{hors éch.}}=1-\frac{\sum(y-\hat y)^2}{\sum\big(y-\bar y_{\text{entraînement}}\big)^2},
$$

où le dénominateur est la perte d'un pronostic qui répond toujours « la moyenne de l'entraînement ». Un $R^2$ proche de 0 ou **négatif** signifie que la note n'a **aucun pouvoir prédictif démontré** : elle reste un résumé lisible, pas un signal.

**Garde-fous.** Une composante est retenue si elle est disponible pour au moins 15 % des événements et 30 événements ; il faut au moins 60 événements pour ajuster. Les composantes **analystes** sont affichées mais pondérées **0** tant que moins de 60 annonces ont un instantané daté pris avant elles (chapitre 16) : avec le consensus d'aujourd'hui, le backtest serait contaminé par le futur.

### Dans le programme

[`composite.py`](../../patrick/patrick/earnings/composite.py) : `components_frame`, `fit`, `decompose`. Les poids ne sont **jamais écrits à la main**.

---

## Chapitre 23. Des stratégies de référence, jamais présumées rentables

### L'idée

Montrer qu'un effet existe ne montre pas qu'on peut en tirer un profit. La famille K évalue trois stratégies **de référence** :

| Stratégie | Position | Configurations testées |
|---|---|---|
| **Run-up** | acheter (ou vendre) à $k$ séances avant J0 et sortir à la clôture de J0−1 | 6 : $k\in\{3,5,10\}\times$ long ou court |
| **Dérive** | suivre le sens de la surprise ou de la réaction, entrée à l'ouverture de J0+$k$, tenue $h$ séances | 12 : 2 signaux × $k\in\{1,2\}$ × $h\in\{5,20,60\}$ |
| **Retournement** (*fade*) | parier contre une réaction qui dépasse $\theta$ écarts-types, entrée à l'ouverture suivante | 6 : $\theta\in\{2,3\}\times h\in\{1,3,5\}$ |

### Les maths

**Une transaction.** Entrée à l'**ouverture** (jamais à la clôture du jour de l'annonce : un titre qui publie après la clôture a déjà « gappé » à l'ouverture, qui est le premier prix réellement exécutable), sortie à la clôture :

$$
\text{brut}=d\Big(\frac{P^{\text{sortie}}}{P^{\text{entrée}}}-1\Big),\qquad
\text{net}=\text{brut}-2c-\varsigma\,\Big|\frac{O_{\text{entrée}}}{C_{\text{veille}}}-1\Big| ,
$$

où $d=\pm1$ est le sens, $c$ le coût par côté (5 points de base par défaut, soit $2c=0{,}10\ \%$ aller-retour) et $\varsigma$ la part du gap d'entrée perdue en **glissement** (*slippage*, 10 % par défaut : sur un gap de 3 %, 0,3 %). Les gaps d'ouverture sont précisément les moments où le glissement est maximal.

**Cohortes.** Les transactions entrées la même semaine ne sont pas indépendantes (mêmes chocs de marché). On les regroupe en **cohortes hebdomadaires** (rendement net moyen), et le Sharpe, la DSR et la perte maximale se calculent sur les cohortes, jamais sur les transactions une à une (ce qui les gonflerait, comme au chapitre 7). Avec $\bar c$ et $s_c$ la moyenne et l'écart-type des rendements de cohorte, $n_a$ le nombre de cohortes par an :

$$
\text{Sharpe annualisé}=\frac{\bar c}{s_c}\sqrt{n_a},\qquad\text{équité}=\text{somme cumulée des }c,
$$

(somme et non produit : pas de capitalisation sur des positions qui se chevauchent). Exemple : 0,12 % de moyenne et 2 % d'écart-type par semaine donnent $0{,}06\times\sqrt{52}=0{,}43$.

**Le Sharpe corrigé du nombre d'essais (DSR).** Le meilleur de $N$ essais a un Sharpe gonflé par la **sélection** : sur 18 configurations sans aucun pouvoir réel, la meilleure aura un Sharpe nettement positif par hasard. Bailey et López de Prado (2014) corrigent cela. Avec $\widehat{SR}$ le Sharpe estimé (par période), $T$ le nombre d'observations, $\gamma_3$ l'asymétrie et $\gamma_4$ l'aplatissement des rendements :

$$
\hat\sigma_{SR}=\sqrt{\frac{1-\gamma_3\widehat{SR}+\frac{\gamma_4-1}{4}\widehat{SR}^2}{T-1}},\qquad
SR_0=\hat\sigma_{SR}\Big[(1-\gamma_E)\,\Phi^{-1}\!\big(1-\tfrac1N\big)+\gamma_E\,\Phi^{-1}\!\big(1-\tfrac1{Ne}\big)\Big],
$$

$$
DSR=\Phi\!\Big(\frac{\widehat{SR}-SR_0}{\hat\sigma_{SR}}\Big),\qquad p=1-DSR ,
$$

où $\gamma_E=0{,}5772$ est la constante d'Euler-Mascheroni. $SR_0$ est le Sharpe **que l'on s'attend à obtenir par pur hasard comme meilleur de $N$ essais**. (Le programme approxime l'écart-type du Sharpe entre essais par $\hat\sigma_{SR}$ calculé sur la stratégie évaluée.) Valeurs de $SR_0/\hat\sigma_{SR}$ :

| $N$ | 1 | 2 | 6 | 12 | 18 | 54 |
|---|---|---|---|---|---|---|
| $SR_0/\hat\sigma_{SR}$ | 0 | 0,52 | 1,30 | 1,66 | 1,85 | 2,31 |

*Exemple* (120 cohortes hebdomadaires simulées, rendement moyen 0,12 %, écart-type 2 %) : le Sharpe réalisé est de 0,0254 par semaine (0,18 en annuel). Avec un seul essai, $p=0{,}39$ ; avec 18 essais, le seuil à battre monte à $SR_0=0{,}170$ par semaine (1,23 en annuel), $DSR=0{,}057$ et $p=0{,}94$ : ce Sharpe, présentable seul, **ne prouve rien** une fois qu'on avoue les 17 autres configurations essayées.

**Probabilité de surajustement du backtest (PBO).** Bailey, Borwein, López de Prado et Zhu (2017). On découpe le temps en $S=8$ blocs et l'on passe en revue les $\binom84=70$ façons de choisir 4 blocs « d'apprentissage » (le reste est « de test »). Pour chacune, on retient la **meilleure** configuration sur l'apprentissage et on regarde son rang $\omega\in(0,1)$ sur le test (la part des autres configurations qu'elle bat). Son *logit* $\lambda=\ln\frac{\omega}{1-\omega}$ est négatif si elle fait moins bien que la médiane des autres :

$$
\mathrm{PBO}=\Pr(\lambda\le0)=\frac{\#\{\text{combinaisons où la meilleure en apprentissage fait pire que la médiane en test}\}}{70}.
$$

Une PBO proche de 50 % ou plus signifie que **choisir la meilleure configuration passée ne dit rien de sa qualité future**.

**Holdout terminal préservé.** Les 15 derniers mois (réglable) sont mis de côté : la configuration est **choisie** sur le Sharpe d'entraînement (événements antérieurs au holdout, au moins 10 transactions), puis **jugée** sur le holdout, jamais l'inverse. Les résultats du holdout (N, gain net moyen, taux de gain, Sharpe, perte maximale, p de la DSR) sont ceux à regarder ; le Sharpe d'entraînement flatteur sans holdout équivalent est du surajustement.

### Dans le programme

[`studies/strategies.py`](../../patrick/patrick/earnings/studies/strategies.py) : `make_trade`, `stats_of`, `evaluate_grid` ; DSR dans [`validation/dsr.py`](../../patrick/patrick/validation/dsr.py), PBO dans [`validation/pbo.py`](../../patrick/patrick/validation/pbo.py).

### Les pièges

- **Les coûts font disparaître beaucoup d'effets** : une dérive de 0,2 % par transaction ne survit pas à 0,10 % de coûts et 0,3 % de glissement.
- La carte le dit : *hypothèse à tester, pas un signal*. Un holdout positif avec une DSR élevée et une PBO basse serait un **indice**, pas une preuve.

---

## Chapitre 24. La robustesse méthodologique (famille M)

### L'idée

Avant de croire un résultat, on le secoue. Quatre contrôles.

### Les maths et les contrôles

1. **Placebos** (chapitre 9) : la taille réelle des tests.
2. **Sensibilité** (*Sensibilité du résultat principal*). On recalcule le CAAR $[0,+1]$ avec d'autres fenêtres d'estimation ($[-150,-30]$, $[-200,-40]$, $[-120,-20]$), d'autres modèles de rendement attendu (market_adjusted, secteur, facteurs) et une winsorisation à 1 % ou 5 %, sur un échantillon tiré au hasard de 250 événements au plus (graine fixe). Un drapeau est levé si **le signe du CAAR change** selon la méthode. Un résultat qui dépend du choix de fenêtre est un artefact.
3. **Recoupement macro.** Comparaison des annonces dont la fenêtre $[J0-1,J0+1]$ contient un jour de FOMC (Réserve fédérale) ou d'emploi américain (approximé au premier vendredi du mois) aux autres : test de Mann-Whitney sur l'amplitude, CAAR avec et sans ces jours. L'inflation (CPI) n'a pas de calendrier gratuit fiable : contrôle partiel, dit comme tel.
4. **Ajustements et drapeaux.** Part des événements concernés par : timing incertain ; timing douteux ; modèle de repli ; split dans $[-250,+60]$ ; dividende détaché dans $[-10,+60]$ (cours ajustés : sans effet sur les rendements, simple information) ; fenêtre post-annonce incomplète ($<60$ séances). Comparaison des résultats avec et sans les événements à timing incertain ou douteux.

### Le biais de survie

Les titres délistés, absorbés ou en faillite **disparaissent** des données gratuites. L'échantillon ne contient que des **survivants**, c'est-à-dire des sociétés dont l'histoire d'annonces s'est, en moyenne, plutôt bien passée. Les statistiques décrivent donc des survivants, pas l'ensemble des sociétés qui ont existé. Le biais pousse en général les rendements moyens **vers le haut**. Une dérive positive observée après les annonces de sociétés qui ont survécu n'a pas le même sens que la même dérive sur toutes les sociétés cotées à l'époque. Aucune des cartes ne peut corriger ce biais avec des données gratuites ; toutes les cartes de rendement l'héritent.

### Dans le programme

[`studies/robustness.py`](../../patrick/patrick/earnings/studies/robustness.py) : `m_placebo`, `m_sensitivity`, `m_macro_overlap`, `m_adjustments`.


---

# Partie V. Lire un résultat

## Chapitre 25. Ce que les données gratuites permettent et interdisent

### L'idée

Toute la page repose sur Yahoo Finance (gratuit). C'est suffisant pour l'essentiel d'une étude d'événement, parce que celle-ci n'exige que des **prix**, des **volumes** et des **dates**. Mais plusieurs ingrédients que la littérature utilise n'existent tout simplement pas gratuitement, et le programme refuse de les inventer.

| Besoin | Disponible en gratuit ? | Traitement dans le programme |
|---|---|---|
| Prix, volumes, dates et heures d'annonce, BPA estimé, publié et surprise | **Oui**, historique profond | Utilisés (heures reconverties du fuseau de New York vers celui de la place) |
| Consensus des analystes, révisions, recommandations, cibles de cours, vendeurs à découvert | **Valeur du jour seulement** | Instantané pris chaque jour ; **affichage** tant que moins de 60 annonces passées ont un instantané daté pris avant elles ; jamais d'évaluation avec le consensus d'aujourd'hui sur le passé |
| Changements de recommandation | **Oui, datés** | Utilisés (carte F), avec la réserve d'une couverture ancienne incomplète |
| Options historiques | **Non** | Straddle de la prochaine annonce pris chaque jour puis apparié au réalisé : cartes vides aujourd'hui, utilisables après quelques trimestres |
| Transcriptions, guidance, chiffre d'affaires publié face à l'estimé | **Non** | Cartes marquées « indisponible avec des données gratuites » |
| Historique d'annonces de certains titres (Diageo, LVMH, Interparfums constatés) | **Absent chez Yahoo** | Saisie manuelle des dates passées (`patrick earnings manual`) |
| Fournisseurs-clients, poids d'indice réels, capitalisation historique | **Non** | Leader = plus grande capitalisation du secteur ; poids = capitalisation relative dans l'échantillon ; capitalisation, P/B, ROE : instantanés actuels (dit) |
| Calendrier macro | **Partiel** | FOMC (liste à compléter chaque année), emploi américain approximé au premier vendredi du mois, pas de CPI |
| Titres délistés, absorbés, en faillite | **Non** | Biais de survie assumé (chapitre 24) |

### Le principe de l'accumulation prospective

Quand une donnée n'existe qu'« aujourd'hui », le programme la **stocke chaque jour** : consensus, vendeurs à découvert, straddle de la prochaine annonce (étape de nuit `resultats instantanes`, bouton « Instantané du jour », commande `patrick earnings snapshot`). Dans quelques trimestres, ces instantanés deviendront une vraie série **datée**, utilisable sans information future. D'ici là, les cartes qui en dépendent l'écrivent plutôt que de simuler. C'est la seule façon honnête de faire de la donnée gratuite un jour exploitable.

---

## Chapitre 26. Comment lire un résultat honnêtement

### L'idée

Une p-value n'est pas un verdict. Voici dix questions à se poser, **dans l'ordre**, devant n'importe quel résultat de la page. Un résultat qui échoue à l'une d'elles n'est pas faux : il est **non démontré**.

### La check-list

1. **Quel est $N$, et combien de semaines distinctes ?** Cent annonces sur quatre semaines valent bien moins que cent annonces réparties sur deux ans (chapitre 7 : $N_{\text{eff}}$).
2. **Quel test le dit ?** Les tests robustes (BMP, KP, bootstrap par blocs) disent-ils la même chose ? Si seul le t naïf ou Patell rejette, c'est un artefact probable (chapitre 7).
3. **Le placebo est-il calibré sur cette fenêtre ?** Sinon, la p-value ne vaut pas ce qu'elle affiche (chapitre 9).
4. **Le résultat survit-il au registre FDR ?** Une p brute de 0,03 parmi 54 cartes et plusieurs fenêtres est la norme du hasard (chapitre 10).
5. **Le signe tient-il quand on change de méthode ?** Fenêtre d'estimation, modèle, winsorisation (chapitre 24).
6. **Quelle part des événements a un timing incertain ou un modèle de repli ?** Si c'est beaucoup, la mesure elle-même est floue (chapitres 2 et 24).
7. **Quel est le score de fiabilité ?** « Insuffisant » veut dire ne pas conclure (chapitre 18).
8. **L'échantillon est-il petit, corrélé, survivant ?** Peu de titres, une même période, des sociétés qui ont survécu : les trois réunis sont le cas habituel (chapitre 24).
9. **Était-ce connu avant ?** Pour tout signal prédictif : la variable existait-elle **avant** l'annonce, avec la valeur qu'on lui attribue ? Un résultat trop beau est d'abord une fuite à chercher (chapitre 20).
10. **Est-ce tradable, net de coûts, hors échantillon ?** Un effet statistique n'est pas un profit : holdout, DSR avec le nombre d'essais, PBO (chapitre 23).

### Un exemple réel de lecture

Lors de la mise au point, sur un échantillon de valeurs gagnantes (Palantir, AMD, Apple, Block...), la **continuation** sur $[+2,+5]$ (le cours qui continue dans le sens de la réaction) est ressortie à $p<0{,}001$ avec **tous** les tests. Passons la check-list :

| Question | Constat |
|---|---|
| 2. Tests robustes concordants | Oui, tous rejettent |
| 3. Placebo calibré sur $[2,5]$ | Oui (5 à 10 % de rejets sur des dates aléatoires) : ce n'est **pas** un artefact de méthode |
| 1, 8. $N$, corrélation, survie | Petit échantillon de valeurs gagnantes, annonces corrélées, titres survivants |
| 4. FDR | Non évalué sur un univers assez large |

La conclusion honnête est : « ce résultat est robuste *dans cet échantillon*, mais cet échantillon ne permet pas d'en dire davantage ». Seul le registre FDR sur un univers plus large de titres, y compris des perdants, peut trancher. Rien dans ce constat n'est un signal d'achat ni de vente.

### Les pièges de la lecture

- **L'effet de cadrage** : on se souvient du résultat qui a surpris, pas des 53 autres qui n'ont rien donné.
- **La conclusion par défaut** : « non significatif » ne veut pas dire « pas d'effet » (chapitre 6, puissance).
- **Les titres choisis à la main** : les titres de la newsletter ne sont pas un échantillon aléatoire (ce sont ceux qui font l'actualité, souvent des gagnants récents).

---

## Chapitre 27. Exercices corrigés

Chaque exercice se fait avec une calculatrice ; les corrections ont été recalculées avec le programme.

**Exercice 1. Rendements.** (a) Un titre gagne 10 % : quel est son rendement logarithmique ? (b) Un rendement logarithmique de −5 % correspond à quel rendement simple ?

*Corrigé.* (a) $\ln(1{,}10)=9{,}53\ \%$. (b) $e^{-0{,}05}-1=-4{,}88\ \%$. Le rendement logarithmique est toujours plus petit que le simple pour les hausses, plus grand en valeur absolue pour les baisses.

**Exercice 2. J0.** (a) Une société de Paris publie le mardi à 8 h 00 (heure de Paris). Quel est J0 ? (b) Un titre américain publie le vendredi à 16 h 30, après la clôture. Quel est J0 ? (c) Yahoo affiche 01:00 (New York) pour une société de Copenhague. À quelle heure locale et dans quelle catégorie est cette publication ?

*Corrigé.* (a) BMO (avant 9 h) : J0 = le mardi, fenêtre $[0]$. (b) AMC : J0 = la première séance **strictement après** le vendredi, donc le lundi suivant (s'il y a séance). (c) Copenhague a 6 heures d'avance sur New York : 01:00 NY = 07:00 CET, donc BMO (la Bourse de Copenhague ouvre à 9 h). Sans conversion, 01:00 donnerait ici le même verdict, mais pas pour une publication à 16 h 30 heure de New York : c'est 22 h 30 à Copenhague, donc après la clôture (AMC), alors que « 16 h 30 » lu comme une heure locale serait classé à tort « pendant la séance ».

**Exercice 3. Variance d'un CAR.** Un titre a $\hat\sigma=1{,}5\ \%$ par jour. Sur une fenêtre de $L=3$ jours, $\mathbf s'(X'X)^{-1}\mathbf s=0{,}12$. Le CAR observé est de +6 %. Quel est le $z$ ?

*Corrigé.* $\operatorname{Var}=\hat\sigma^2(L+0{,}12)=\hat\sigma^2\times3{,}12$, donc l'écart-type vaut $1{,}5\ \%\times\sqrt{3{,}12}=2{,}65\ \%$ et $z=6/2{,}65=2{,}26$, soit $p\approx0{,}024$ (normale, bilatérale). Sans la correction d'erreur de prévision on aurait trouvé $1{,}5\times\sqrt3=2{,}60\ \%$ et $z=2{,}31$ : la correction est modeste ici.

**Exercice 4. Kolari-Pynnönen.** Sur $N=64$ annonces, $t_{\text{BMP}}=3{,}0$ ($p=0{,}004$) et la corrélation moyenne vaut $\bar r=0{,}03$. Que devient le résultat ?

*Corrigé.* Facteur $=\sqrt{(1-0{,}03)/(1+63\times0{,}03)}=\sqrt{0{,}97/2{,}89}=0{,}579$ ; $t_{\text{KP}}=3{,}0\times0{,}579=1{,}74$, soit $p\approx0{,}087$ (Student à 63 degrés de liberté). L'échantillon équivalent est $N_{\text{eff}}=64/2{,}89=22{,}1$. Une corrélation moyenne de seulement 3 % fait passer d'un résultat « significatif à 1 % » à un résultat qui ne l'est pas à 5 %.

**Exercice 5. Benjamini-Hochberg.** Cinq p-values : 0,004 ; 0,011 ; 0,030 ; 0,200 ; 0,600. Lesquelles survivent à un FDR de 10 % ?

*Corrigé.* Avec $m=5$ : $\frac{m}{i}p_{(i)}=0{,}020;\ 0{,}0275;\ 0{,}050;\ 0{,}250;\ 0{,}600$. En prenant le minimum de la fin vers le début, les $q$ valent $0{,}020;\ 0{,}0275;\ 0{,}050;\ 0{,}250;\ 0{,}600$. Les **trois premières** survivent à 10 % ($q\le0{,}10$), pas les deux dernières. Remarque : la troisième ($p=0{,}030$, $q=0{,}050$) ne survivrait à un seuil de 5 % que de justesse ($q\le\alpha$ avec égalité).

**Exercice 6. Rétrécissement.** Un titre a $n=9$ annonces, une amplitude moyenne de 5 %, son secteur de 2 %, et $k=\sigma^2/\tau^2=3$. Quelle est l'amplitude rétrécie ?

*Corrigé.* $w=9/(9+3)=0{,}75$ ; $\hat\theta=0{,}75\times5+0{,}25\times2=4{,}25\ \%$.

**Exercice 7. Straddle.** Un straddle à l'argent vaut 8 pour un cours de 100. Le mouvement réalisé est de +5 % (en valeur absolue). Quel est le rendement d'un acheteur du straddle, avant et après un coût de 5 % du straddle ?

*Corrigé.* Mouvement implicite $\approx8\ \%$, réalisé 5 % : ratio $5/8=0{,}625$. Rendement avant coûts $=(5-8)/8=-37{,}5\ \%$ ; après le coût de 5 %, $-42{,}5\ \%$. Un seul cas ne dit rien : la prime de risque de volatilité se juge sur beaucoup d'annonces (test de Wilcoxon).

**Exercice 8. Lecture critique.** Vous lancez 54 cartes et l'une d'elles affiche $p=0{,}02$. Que répondez-vous à « c'est significatif » ?

*Corrigé.* Sous l'hypothèse que rien n'existe, on attend en moyenne $54\times0{,}05\approx2{,}7$ cartes à $p<0{,}05$ (simulation : 2,68), et la probabilité d'en avoir **au moins une** est de 94 %. Un $p$ de 0,02 isolé est donc banal. Seule sa q-value du registre FDR compte. Pour qu'une p-value de 0,02 soit retenue à 10 % parmi 54 tests, son rang $i$ doit vérifier $i\ge m\,p/\alpha_{\text{FDR}}=54\times0{,}02/0{,}10=10{,}8$, soit au moins le 11<sup>e</sup> : il faut qu'une dizaine d'autres p-values soient au moins aussi faibles (ou qu'une p-value plus grande soit elle-même retenue).

---

# Annexe A. Glossaire

| Terme | Définition en une phrase |
|---|---|
| **AMC / BMO** | Annonce publiée *après la clôture* / *avant l'ouverture* de la Bourse |
| **AR** | Rendement anormal : rendement réel moins rendement attendu |
| **Baseline** | Prévision de référence simple que tout modèle doit battre (moyenne passée du titre, du secteur) |
| **Beat / miss** | BPA publié supérieur / inférieur à l'estimé |
| **Bêta** | Sensibilité du rendement d'un titre à celui de l'indice de marché |
| **BHAR** | Rendement anormal composé (produit des $(1+R)$ moins produit des $(1+E)$) |
| **Biais de survie** | Échantillon limité aux sociétés qui existent encore, donc plutôt bien passées |
| **Bootstrap** | Tirage avec remise dans l'échantillon pour mesurer la variabilité d'une statistique |
| **BPA / EPS** | Bénéfice par action |
| **CAR / CAAR** | Rendement anormal cumulé d'un événement / moyenne des CAR sur les événements |
| **Cohorte** | Ensemble des transactions entrées la même semaine, traitées comme une seule observation |
| **Conforme (prédiction)** | Intervalle de prédiction sans hypothèse de loi, calibré sur des erreurs passées |
| **DM (Diebold-Mariano)** | Test de l'égalité de précision de deux prévisions |
| **DSR** | Sharpe corrigé du nombre d'essais et de la non-normalité |
| **ERC** | Coefficient de réponse aux résultats : pente de la réaction sur la surprise |
| **Fenêtre d'estimation** | Séances avant l'annonce sur lesquelles on estime le modèle de rendement attendu |
| **FDR** | Taux de fausses découvertes : part attendue de faux positifs parmi les résultats déclarés significatifs |
| **Fuite d'information** | Utilisation, sans le savoir, d'une information indisponible à la date de la décision |
| **Gap** | Écart entre la clôture de la veille et l'ouverture du jour |
| **HMM** | Modèle de Markov caché : états inobservables (calme, agité) qui gouvernent la loi des rendements |
| **Holdout** | Dernière période mise de côté, jamais utilisée pour choisir |
| **J0** | Première séance dont le cours intègre la nouvelle |
| **MAE** | Erreur absolue moyenne |
| **MCO / OLS** | Moindres carrés ordinaires : régression linéaire usuelle |
| **PBO** | Probabilité que la meilleure configuration passée soit sous la médiane hors échantillon |
| **PEAD** | Dérive après annonce : le cours continue de s'ajuster dans le sens de la surprise |
| **Placebo** | Faux événements sur des dates tirées au hasard, où l'effet vrai est nul par construction |
| **Point-in-time** | N'utiliser que ce qui était connu à la date considérée |
| **Pinball (perte)** | Perte asymétrique dont le minimum est le quantile |
| **p-value** | Probabilité d'une statistique au moins aussi extrême si l'hypothèse nulle est vraie |
| **q-value** | p-value corrigée du taux de fausses découvertes |
| **QLIKE** | Perte adaptée aux prévisions de variance |
| **Ridge** | Régression linéaire pénalisée par la taille des coefficients |
| **Run-up** | Rendement anormal cumulé avant l'annonce ($[-10,-1]$) |
| **SCAR** | CAR divisé par son écart-type estimé |
| **Séance relative** | Numéro de séance par rapport à J0 ($0$ = J0, $-1$ = la veille) |
| **Shrinkage** | Rétrécissement d'une moyenne vers celle du groupe, d'autant plus que l'effectif est petit |
| **Slippage** | Écart entre le prix visé et le prix obtenu |
| **SUE** | Surprise standardisée par l'historique du titre |
| **Walk-forward (purgé)** | Validation chronologique : entraîner sur le passé, tester sur le futur, en retirant les chevauchements |
| **Winsorisation** | Remplacement des valeurs extrêmes par un quantile (rognage) |

---

# Annexe B. Carte → méthode → fichier

Tous les fichiers sont dans [`patrick/patrick/earnings/studies/`](../../patrick/patrick/earnings/studies/). « Ch. » renvoie au chapitre de ce cours. *(i)* signifie : carte qui affiche « indisponible » ou « en accumulation » avec des données gratuites.

| Identifiant | Ce que mesure la carte | Ch. | Fichier |
|---|---|---|---|
| `core_event_study` | CAAR par fenêtre, 6 tests, BHAR, courbe cumulée, test d'amplitude | 5, 7, 8 | `core_a.py` |
| `a_reaction_dist` | distribution des réactions, probabilité de hausse et de gros mouvement | 12 | `core_a.py` |
| `a_overnight_share` | part overnight / intraday | 12 | `core_a.py` |
| `a_continuation` | continuation ou retournement (Spearman, pente) | 12 | `core_a.py` |
| `a_beat_and_drop` | beat suivi d'une baisse (Fisher) | 12 | `core_a.py` |
| `a_jump_share` | part de la variance annuelle portée par les jours d'annonce | 12 | `core_a.py` |
| `b_vol_prepost` | volatilité relative, « vol crush » réalisé | 13 | `vol_liq.py` |
| `b_har_event` | HAR-RV avec indicatrices d'annonce | 13 | `vol_liq.py` |
| `b_implied_realized` *(i)* | straddle ATM contre mouvement réalisé | 13 | `vol_liq.py` |
| `b_straddle_backtest` *(i)* | rentabilité d'acheter ou vendre le straddle | 13 | `vol_liq.py` |
| `c_abnormal_volume` | volume anormal, rotation | 14 | `vol_liq.py` |
| `c_amihud` | illiquidité d'Amihud | 14 | `vol_liq.py` |
| `c_corwin_schultz` | spread bid-ask estimé | 14 | `vol_liq.py` |
| `c_volume_predicts_move` | volume d'avant et amplitude | 14 | `vol_liq.py` |
| `e_runup` | run-up et pouvoir prédictif | 16 | `vol_liq.py` |
| `e_short_interest` *(i)* | vendeurs à découvert avant l'annonce | 16 | `vol_liq.py` |
| `d_surprise_erc` | ERC par groupe, quintiles de surprise | 15 | `surprise.py` |
| `d_sue_pead` | dérive post-annonce par décile de SUE | 15 | `surprise.py` |
| `d_guidance` *(i)* | révision de guidance | 15 | `surprise.py` |
| `d_sequences` | séries de beats consécutifs | 15 | `surprise.py` |
| `f_news_sentiment` | sentiment, attention, nouveauté avant l'annonce | 16 | `news_analysts.py` |
| `f_news_lag` | corrélation croisée sentiment / rendement | 16 | `news_analysts.py` |
| `f_news_post` | news après l'annonce (a posteriori) | 16 | `news_analysts.py` |
| `f_analyst_snapshot` *(i)* | consensus et révisions (instantané) | 16 | `news_analysts.py` |
| `f_analyst_bias` | taux de dépassement du consensus | 16 | `news_analysts.py` |
| `f_analyst_actions` | changements de recommandation datés | 16 | `news_analysts.py` |
| `f_transcripts` *(i)* | texte des conférences téléphoniques | 16 | `news_analysts.py` |
| `g_peer_transmission` | lecture croisée entre pairs | 17 | `cross.py` |
| `g_leader_follower` | leader → suiveurs | 17 | `cross.py` |
| `g_index_impact` | contribution des annonces au mouvement de l'indice | 17 | `cross.py` |
| `g_week_density` | densité de la saison et volatilité de l'indice | 17 | `cross.py` |
| `h_regimes` | HMM et terciles du VIX | 17 | `cross.py` |
| `i_structure` | amplitude selon taille, bêta, style, secteur, pays | 17 | `cross.py` |
| `i_currency` | effet de la devise | 17 | `cross.py` |
| `i_ipo` | introductions récentes | 17 | `cross.py` |
| `j_calendar_effects` | jour de la semaine, BMO contre AMC | 17 | `calendar_effects.py` |
| `j_season_order` | premier contre dernier annonceur de la saison | 17 | `calendar_effects.py` |
| `j_quarter_annual` | trimestriel contre annuel | 17 | `calendar_effects.py` |
| `j_delay` | retard par rapport à la date habituelle | 17 | `calendar_effects.py` |
| `j_announcement_premium` | prime d'annonce | 17 | `calendar_effects.py` |
| `j_local_adr` | ligne locale contre ADR | 17 | `calendar_effects.py` |
| `k_strategy_runup` | stratégie run-up | 23 | `strategies.py` |
| `k_strategy_drift` | stratégie de dérive | 23 | `strategies.py` |
| `k_strategy_fade` | stratégie de retournement | 23 | `strategies.py` |
| `l_quantile` | régression quantile de l'amplitude | 21 | `probabilistic.py` |
| `l_conformal` | intervalles conformes | 21 | `probabilistic.py` |
| `l_shrinkage` | rétrécissement bayésien empirique | 18 | `probabilistic.py` |
| `p_amplitude` | modèle d'amplitude (panel, walk-forward purgé) | 19 | `probabilistic.py` |
| `p_direction` | modèle de direction | 20 | `probabilistic.py` |
| `p_composite` | score de sentiment composite | 22 | `probabilistic.py` |
| `m_placebo` | taille réelle des tests sur des placebos | 9 | `robustness.py` |
| `m_sensitivity` | sensibilité du résultat principal | 24 | `robustness.py` |
| `m_macro_overlap` | recoupement avec FOMC et emploi | 24 | `robustness.py` |
| `m_adjustments` | drapeaux, ajustements, biais de survie | 24 | `robustness.py` |

Les modules hors études : [`engine.py`](../../patrick/patrick/earnings/engine.py) (mesures par événement), [`signif.py`](../../patrick/patrick/earnings/signif.py) (tests), [`reliability.py`](../../patrick/patrick/earnings/reliability.py) (fiabilité, rétrécissement), [`panel.py`](../../patrick/patrick/earnings/panel.py) (tableau d'événements), [`model.py`](../../patrick/patrick/earnings/model.py) (modèles prédictifs), [`composite.py`](../../patrick/patrick/earnings/composite.py) (score composite), [`consensus.py`](../../patrick/patrick/earnings/consensus.py) (instantanés), [`exchanges.py`](../../patrick/patrick/earnings/exchanges.py) (places, J0), [`schedule.py`](../../patrick/patrick/earnings/schedule.py) (calendrier). Mode d'emploi de la page : [`docs/ops/evenements-resultats.md`](../ops/evenements-resultats.md). Décisions de conception : [`docs/adr/0016-evenements-de-resultats.md`](../adr/0016-evenements-de-resultats.md).

---

# Annexe C. Bibliographie

*Références citées de mémoire (auteurs, année, revue) : à revérifier avant de les citer ailleurs.*

**Études d'événement et tests**

- MacKinlay, A. C. (1997), « Event studies in economics and finance », *Journal of Economic Literature*.
- Brown, S. et Warner, J. (1985), « Using daily stock returns: the case of event studies », *Journal of Financial Economics*.
- Patell, J. (1976), « Corporate forecasts of earnings per share and stock price behavior », *Journal of Accounting Research*.
- Boehmer, E., Musumeci, J. et Poulsen, A. (1991), « Event-study methodology under conditions of event-induced variance », *Journal of Financial Economics*.
- Kolari, J. et Pynnönen, S. (2010), « Event study testing with cross-sectional correlation of abnormal returns », *Review of Financial Studies*.
- Corrado, C. (1989), « A nonparametric test for abnormal security-price performance in event studies », *Journal of Financial Economics*.
- Campbell, C. et Wasley, C. (1993), « Measuring security price performance using daily NASDAQ returns », *Journal of Financial Economics*.
- Cowan, A. (1992), « Nonparametric event study tests », *Review of Quantitative Finance and Accounting*.
- Barber, B. et Lyon, J. (1997), « Detecting long-run abnormal stock returns », *Journal of Financial Economics*.
- Künsch, H. (1989), « The jackknife and the bootstrap for general stationary observations », *Annals of Statistics* (bootstrap par blocs).
- Fama, E. et French, K. (1993), « Common risk factors in the returns on stocks and bonds », *Journal of Financial Economics* ; Carhart, M. (1997), « On persistence in mutual fund performance », *Journal of Finance*.

**Résultats comptables, surprises, dérive**

- Ball, R. et Brown, P. (1968), « An empirical evaluation of accounting income numbers », *Journal of Accounting Research*.
- Bernard, V. et Thomas, J. (1989), « Post-earnings-announcement drift: delayed price response or risk premium? », *Journal of Accounting Research*.
- Martineau, C. (2021), « Rest in peace post-earnings announcement drift », *Critical Finance Review*.
- Chambers, A. et Penman, S. (1984), « Timeliness of reporting and the stock price reaction to earnings announcements », *Journal of Accounting Research*.
- Savor, P. et Wilson, M. (2016), « Earnings announcements and systematic risk », *Journal of Finance*.
- Loughran, T. et McDonald, B. (2011), « When is a liability not a liability? Textual analysis, dictionaries, and 10-Ks », *Journal of Finance*.

**Volatilité, liquidité**

- Parkinson, M. (1980), « The extreme value method for estimating the variance of the rate of return », *Journal of Business*.
- Corsi, F. (2009), « A simple approximate long-memory model of realized volatility », *Journal of Financial Econometrics*.
- Amihud, Y. (2002), « Illiquidity and stock returns: cross-section and time-series effects », *Journal of Financial Markets*.
- Corwin, S. et Schultz, P. (2012), « A simple way to estimate bid-ask spreads from daily high and low prices », *Journal of Finance*.
- Hamilton, J. (1989), « A new approach to the economic analysis of nonstationary time series and the business cycle », *Econometrica*.

**Statistique, comparaisons multiples, prévision**

- Benjamini, Y. et Hochberg, Y. (1995), « Controlling the false discovery rate », *Journal of the Royal Statistical Society B* ; Benjamini, Y. et Yekutieli, D. (2001), *Annals of Statistics* (dépendance arbitraire).
- Efron, B. et Morris, C. (1973), « Stein's estimation rule and its competitors », *Journal of the American Statistical Association*.
- Hoerl, A. et Kennard, R. (1970), « Ridge regression: biased estimation for nonorthogonal problems », *Technometrics*.
- Koenker, R. et Bassett, G. (1978), « Regression quantiles », *Econometrica*.
- Vovk, V., Gammerman, A. et Shafer, G. (2005), *Algorithmic Learning in a Random World* (prédiction conforme).
- Diebold, F. et Mariano, R. (1995), « Comparing predictive accuracy », *Journal of Business & Economic Statistics* ; Harvey, D., Leybourne, S. et Newbold, P. (1997), « Testing the equality of prediction mean squared errors », *International Journal of Forecasting*.
- Patton, A. (2011), « Volatility forecast comparison using imperfect volatility proxies », *Journal of Econometrics*.
- Wilson, E. B. (1927), « Probable inference, the law of succession, and statistical inference », *Journal of the American Statistical Association*.
- Arellano, M. (1987), « Computing robust standard errors for within-groups estimators », *Oxford Bulletin of Economics and Statistics* (erreurs-types groupées).

**Évaluation de stratégies**

- Bailey, D. et López de Prado, M. (2014), « The deflated Sharpe ratio: correcting for selection bias, backtest overfitting and non-normality », *Journal of Portfolio Management*.
- Bailey, D., Borwein, J., López de Prado, M. et Zhu, Q. (2017), « The probability of backtest overfitting », *Journal of Computational Finance*.

