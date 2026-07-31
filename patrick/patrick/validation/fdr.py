"""Phase 6.4 (P6.4) -- correction FDR (Benjamini-Hochberg, 1995) à travers
TOUTES les cibles testées historiquement -- distincte des garde-fous
multi-tests déjà en place (section 4 de METHODOLOGY.md), qui corrigent le
nombre d'ESSAIS DE CONFIG au sein d'une même (cible, horizon) : essayer
successivement N cibles différentes (VIX, puis GSPC, puis SPY...) et retenir
celle dont le test Diebold-Mariano est significatif soulève le MÊME problème
de tests multiples, à une échelle différente -- sur 20 cibles sans aucun
vrai signal, environ 1 apparaîtrait "significative" à p<0.05 par pur hasard.

Fonction pure (aucune dépendance SQLite) : `benjamini_hochberg` prend un dict
{cible: meilleure p-value DM historique} et renvoie, pour chaque cible, sa
p-value ajustée (q-value) et son statut significatif au seuil FDR choisi --
le pont vers la base (`tracking/stats.py::fdr_across_targets`) construit ce
dict à partir de `dm_result`/`run`.
"""
from __future__ import annotations


def benjamini_hochberg(p_values: dict[str, float], alpha: float = 0.10) -> dict:
    """Procédure de Benjamini-Hochberg (step-up) : p-values ajustées
    (q-values) telles que `significant = (q <= alpha)` est équivalent au
    critère original (plus grand k tel que p_(k) <= (k/m)*alpha, rejette
    1..k) -- équivalence standard, cf. Benjamini & Hochberg (1995).

    `p_values` : {cible: p_value}, NaN silencieusement exclues (cible sans
    essai DM valide, ex. tous ses runs en mode CPCV -- cf. limite P6.1,
    Diebold-Mariano non calculé dans ce schéma)."""
    items = [(k, v) for k, v in p_values.items() if v == v]  # exclut NaN
    m = len(items)
    if m == 0:
        return {"alpha": alpha, "n_tested": 0, "n_raw_significant": 0,
                "n_bh_significant": 0, "results": {}}

    items_sorted = sorted(items, key=lambda kv: kv[1])
    raw_p = [v for _, v in items_sorted]

    # q_(i) = min_{j>=i} (m/j * p_(j)) -- calculé de la fin vers le début
    # pour garantir la monotonie (q_(1) <= q_(2) <= ... <= q_(m)).
    adjusted = [0.0] * m
    adjusted[-1] = min(1.0, raw_p[-1])
    for i in range(m - 2, -1, -1):
        adjusted[i] = min(adjusted[i + 1], raw_p[i] * m / (i + 1))

    results = {}
    n_bh_sig = 0
    n_raw_sig = 0
    for idx, (target, p) in enumerate(items_sorted):
        sig = adjusted[idx] <= alpha
        n_bh_sig += int(sig)
        n_raw_sig += int(p <= alpha)
        results[target] = {
            "p_value": p, "adjusted_p_value": adjusted[idx],
            "rank": idx + 1, "significant": sig,
        }
    return {
        "alpha": alpha, "n_tested": m,
        "n_raw_significant": n_raw_sig, "n_bh_significant": n_bh_sig,
        "results": results,
    }
