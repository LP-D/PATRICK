# Mesures du 2026-11-02 : dimensionnement appris et carry de change

Sorties brutes de `patrick/scripts/bandit_sizing_bench.py` et `patrick/scripts/fx_carry_study.py` (ADR 0015). Reproductibles sur la base et le cache locaux ; les chiffres bougent avec les données.

## Dimensionnement appris (bandit, Kelly ridge) contre les heuristiques de /simulate


**bandit** : Sharpe net moyen 0.045 sur 459 modèles
| contre | Sharpe moyen de l'heuristique | écart moyen | médiane | part meilleure | IC | test des signes (p) |
|---|---|---|---|---|---|---|
| threshold | 0.163 | -0.119 | -0.083 | 45% | [-0.209 ; -0.031] | 0.025 |
| proportional | 0.176 | -0.131 | -0.153 | 41% | [-0.213 ; -0.052] | 0.000 |
| leverage_half | 0.176 | -0.131 | -0.153 | 41% | [-0.215 ; -0.051] | 0.000 |
Verdict : ne bat pas toutes les heuristiques

**kelly_ridge** : Sharpe net moyen 0.095 sur 459 modèles
| contre | Sharpe moyen de l'heuristique | écart moyen | médiane | part meilleure | IC | test des signes (p) |
|---|---|---|---|---|---|---|
| threshold | 0.163 | -0.068 | -0.118 | 41% | [-0.148 ; +0.010] | 0.000 |
| proportional | 0.176 | -0.080 | -0.113 | 42% | [-0.152 ; -0.010] | 0.001 |
| leverage_half | 0.176 | -0.080 | -0.113 | 42% | [-0.155 ; -0.007] | 0.001 |
Verdict : ne bat pas toutes les heuristiques

Par classe d'actifs (écart de Sharpe moyen contre le seuil 0,55) :
- crypto (2) : bandit -0.610, kelly_ridge -0.201
- equities_americas_other (3) : bandit +0.134, kelly_ridge +0.174
- equities_asia_pacific (23) : bandit -0.278, kelly_ridge -0.170
- equities_europe (149) : bandit -0.107, kelly_ridge +0.022
- equities_us (229) : bandit -0.127, kelly_ridge -0.156
- futures (27) : bandit +0.042, kelly_ridge +0.215
- fx (13) : bandit -0.342, kelly_ridge -0.321
- other (5) : bandit +0.081, kelly_ridge +0.374
- volatility_index (9) : bandit +0.056, kelly_ridge +0.157

## Carry de change


| stratégie | période | n | rendement annuel | vol | Sharpe | pire perte | asymétrie | t(moyenne) | IC95 de la moyenne mensuelle | Sharpe sans portage (change seul) |
|---|---|---|---|---|---|---|---|---|---|---|
| time_series | 2000-2025 | 305 | +0.7% | 4.5% | 0.17 | -17% | -0.02 | +0.87 | [-0.0009 ; +0.0021] | -0.15 |
| time_series | 2000-2012 | 151 | +1.5% | 4.7% | 0.34 | -17% | +0.19 | +1.21 | [-0.0012 ; +0.0037] | -0.04 |
| time_series | 2013-2025 | 154 | -0.1% | 4.4% | -0.00 | -15% | -0.30 | -0.01 | [-0.0018 ; +0.0017] | -0.27 |
| cross_section | 2000-2025 | 305 | +1.0% | 6.9% | 0.18 | -27% | -0.58 | +0.92 | [-0.0013 ; +0.0031] | -0.22 |
| cross_section | 2000-2012 | 151 | +1.9% | 7.1% | 0.29 | -27% | -0.73 | +1.05 | [-0.0027 ; +0.0052] | -0.18 |
| cross_section | 2013-2025 | 154 | +0.2% | 6.6% | 0.07 | -20% | -0.43 | +0.23 | [-0.0020 ; +0.0024] | -0.25 |

Sharpe déflaté de time_series (2 stratégies essayées) : 0.636 (Sharpe 0.17, seuil sous H0 0.030 par mois)
Sharpe déflaté de cross_section (2 stratégies essayées) : 0.650 (Sharpe 0.18, seuil sous H0 0.030 par mois)
