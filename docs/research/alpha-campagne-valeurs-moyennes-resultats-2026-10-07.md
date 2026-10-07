# Campagne alpha

Famille alpha, m = 12 cibles ; Benjamini-Hochberg à q = 0.1, test de Diebold-Mariano unilatéral contre la persistance de l'alpha sur le holdout ; Sharpe net de 10 points de base par jambe (simulation couverte, paramètres par défaut, rien d'enregistré au registre d'essais).

| Valeur | Statut | Horizon | DM | p bilatéral | p famille | q (BH) | Sharpe net | Découverte |
|---|---|---|---|---|---|---|---|---|
| MC.PA | ok | 5 | -1.16 | 0.248 | 0.124 | 0.499 | -0.94 | non |
| SOP.PA | ok | 20 | +1.85 | 0.066 | 0.967 | 0.967 | -0.33 | non |
| NEX.PA | ok | 5 | +0.44 | 0.660 | 0.670 | 0.835 | -1.12 | non |
| RXL.PA | ok | 20 | -0.97 | 0.333 | 0.166 | 0.499 | -0.05 | non |
| IPS.PA | ok | 20 | -0.68 | 0.496 | 0.248 | 0.595 | +0.14 | non |
| SK.PA | ok | 5 | -1.82 | 0.070 | 0.035 | 0.421 | -0.54 | non |
| NK.PA | ok | 5 | -0.28 | 0.779 | 0.390 | 0.668 | -0.11 | non |
| RUI.PA | ok | 20 | +0.51 | 0.609 | 0.696 | 0.835 | -0.13 | non |
| TRI.PA | ok | 5 | -0.36 | 0.716 | 0.358 | 0.668 | -0.09 | non |
| VIRP.PA | ok | 5 | +1.09 | 0.278 | 0.861 | 0.939 | -0.64 | non |
| RCO.PA | ok | 20 | -1.06 | 0.288 | 0.144 | 0.499 | +0.56 | non |
| ERF.PA | ok | 5 | -0.05 | 0.957 | 0.478 | 0.718 | -0.29 | non |

**Verdict : 0 découverte sur m = 12.**
Aucune évidence d'alpha exploitable avec ce protocole sur ces valeurs.


## Lecture

- Protocole appliqué à la lettre (`docs/research/alpha-campagne-valeurs-moyennes-2026-10.md`, aucun écart) : 12 runs terminés sur 12, aucun échec, aucune valeur retirée.
- **Test statistique** : une seule valeur passe le seuil brut de 5 % avant correction (SK.PA, p famille 0,035), mais elle ne survit pas à Benjamini-Hochberg (q = 0,42) et sa simulation nette perd (Sharpe −0,54). Aucune autre n'approche le seuil. Quatre valeurs (SOP.PA, NEX.PA, RUI.PA, VIRP.PA) ont un DM positif : le modèle fait moins bien que la persistance de l'alpha.
- **Valeur économique** : seules IPS.PA (+0,14) et RCO.PA (+0,56) ont un Sharpe net positif, sans signal statistique (p famille 0,25 et 0,14) : à cette échelle (un holdout d'environ 325 séances), c'est compatible avec du hasard.
- **Verdict** : 0 découverte sur m = 12. Pas d'évidence d'alpha exploitable avec ce pipeline et cette cible sur ces valeurs moyennes françaises. Ce n'est pas la preuve qu'il n'existe aucun alpha : le holdout est court, les 12 valeurs partagent les mêmes dates, et le protocole ne teste qu'une famille de modèles avec les paramètres par défaut.
- Conséquence pratique : la cible alpha reste disponible (simulation couverte, règles du fonds), mais rien ne justifie de s'en servir pour décider un investissement.
