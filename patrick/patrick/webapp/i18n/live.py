"""Chaînes FR/EN de la page « Résultat réel » (`/reel`, `tracking/live_board.py`). Fusionnées dans `i18n.STRINGS`."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


LIVE_STRINGS: dict[str, dict[str, str]] = {
    "nav_live_board": _s("Résultat réel", "Live results"),
    "lb_title": _s("Résultat réel", "Live results"),
    "lb_subtitle": _s("Ce que les champions ont réellement prédit, jour après jour, une fois l'horizon écoulé. Toujours à côté de la stratégie "
                      "sans modèle : un score ne vaut que par ce qu'il ajoute à « toujours hausse ».",
                      "What the champions actually predicted, day after day, once the horizon has elapsed. Always next to the no-model "
                      "strategy: a score is only worth what it adds to 'always up'."),
    "lb_empty": _s("Aucune prédiction réelle jugée.", "No judged live prediction yet."),
    "lb_empty_hint": _s("Une prédiction est jugée quand son horizon est écoulé : les premières arrivent quelques jours après le premier modèle.",
                        "A prediction is judged once its horizon has elapsed: the first ones come a few days after the first model."),
    "lb_k_rate": _s("Bonne direction", "Right direction"),
    "lb_k_rate_hint": _s("{n} prédictions jugées, {models} modèles · intervalle à 95 % : {low} à {high}",
                         "{n} judged predictions, {models} models · 95% interval: {low} to {high}"),
    "lb_k_naive": _s("Stratégie sans modèle", "No-model strategy"),
    "lb_k_naive_up": _s("« toujours hausse » : la part de hausses réalisées", "'always up': the share of realised rises"),
    "lb_k_naive_down": _s("« toujours baisse » : la part de baisses réalisées", "'always down': the share of realised falls"),
    "lb_k_edge": _s("Apport des modèles", "What the models add"),
    "lb_k_edge_hint": _s("bonne direction moins la stratégie sans modèle ; négatif : les modèles font moins bien qu'elle",
                         "right direction minus the no-model strategy; negative: the models do worse than it"),
    "lb_k_bias": _s("Hausses annoncées", "Rises announced"),
    "lb_k_bias_hint": _s("contre {up} de hausses réalisées", "against {up} of realised rises"),
    "lb_s_week": _s("Semaine après semaine", "Week after week"),
    "lb_h_week": _s("Semaine du signal (lundi). Les dernières semaines sont incomplètes tant que leurs horizons ne sont pas écoulés.",
                    "Week of the signal (Monday). The latest weeks are incomplete until their horizons have elapsed."),
    "lb_s_class": _s("Par classe d'actifs", "By asset class"),
    "lb_h_class": _s("Les actifs d'une même classe montent et baissent ensemble : l'intervalle est un minimum, pas une certitude.",
                     "Assets of one class rise and fall together: the interval is a minimum, not a certainty."),
    "lb_s_horizon": _s("Par horizon", "By horizon"),
    "lb_h_horizon": _s("Des prédictions quotidiennes à plusieurs jours se recouvrent : n jugements à l'horizon h valent environ n / h jugements indépendants.",
                       "Daily predictions several days ahead overlap: n judgements at horizon h are worth about n / h independent ones."),
    "lb_s_algo": _s("Par algorithme", "By algorithm"),
    "lb_h_algo": _s("L'algorithme du champion de chaque cellule.", "The algorithm of each cell's champion."),
    "lb_c_week": _s("Semaine", "Week"),
    "lb_c_class": _s("Classe d'actifs", "Asset class"),
    "lb_c_horizon": _s("Horizon", "Horizon"),
    "lb_c_algo": _s("Algorithme", "Algorithm"),
    "lb_c_n": _s("Jugées", "Judged"),
    "lb_c_rate": _s("Bonne direction", "Right direction"),
    "lb_c_ci": _s("Intervalle 95 %", "95% interval"),
    "lb_c_up": _s("Hausses réalisées", "Realised rises"),
    "lb_c_pred_up": _s("Hausses annoncées", "Rises announced"),
    "lb_c_edge": _s("Apport", "Added"),
    "lb_horizon_days": _s("{h} j", "{h} d"),
    "lb_too_few": _s("Pas assez de prédictions jugées (moins de 30 par ligne).", "Not enough judged predictions (fewer than 30 per row)."),
    "lb_s_bias": _s("Biais de direction : seuil recalé (mesure seule)", "Direction bias: re-centred threshold (measurement only)"),
    "lb_h_bias": _s("Chaque semaine, par classe d'actifs, le seuil sur P(hausse) est celui qui aurait annoncé, sur les semaines passées, autant de "
                    "hausses qu'il s'en est produit. Aucun signal n'est modifié : c'est ce que ce réglage AURAIT donné sur les mêmes prédictions.",
                    "Each week, per asset class, the threshold on P(up) is the one that would have announced, over past weeks, as many rises as "
                    "actually happened. No signal is changed: this is what that setting WOULD have given on the same predictions."),
    "lb_b_base": _s("Seuil d'origine", "Original threshold"),
    "lb_b_n": _s("{n} prédictions comparées", "{n} predictions compared"),
    "lb_b_shadow": _s("Seuil recalé", "Re-centred threshold"),
    "lb_b_shadow_hint": _s("même lignes, seuil appris sur le passé seulement", "same rows, threshold learned on the past only"),
    "lb_b_gain": _s("Écart", "Gap"),
    "lb_b_gain_hint": _s("positif : le recalage aurait aidé", "positive: re-centring would have helped"),
    "lb_b_none": _s("Pas encore assez d'historique (200 prédictions jugées par classe avant la première comparaison).",
                    "Not enough history yet (200 judged predictions per class before the first comparison)."),
    "lb_s_consensus": _s("Avis d'ensemble par cible", "Combined view per target"),
    "lb_h_consensus": _s("Le dernier signal de chaque horizon d'une même cible, réunis : moyenne des P(hausse). Les cibles les plus tranchées d'abord. "
                         "Ce n'est pas un conseil d'achat ou de vente.",
                         "The latest signal of each horizon of one target, combined: mean of P(up). The most clear-cut targets first. "
                         "This is not advice to buy or sell."),
    "lb_c_target": _s("Cible", "Target"),
    "lb_c_direction": _s("Avis", "View"),
    "lb_c_score": _s("P(hausse) moyenne", "Mean P(up)"),
    "lb_c_votes": _s("Horizons haussiers", "Horizons up"),
    "lb_c_horizons": _s("Horizons (jours)", "Horizons (days)"),
    "lb_c_last": _s("Dernier signal", "Latest signal"),
    "lb_dir_up": _s("Hausse", "Up"),
    "lb_dir_down": _s("Baisse", "Down"),
    "lb_consensus_none": _s("Aucune cible n'a de signal récent sur au moins deux horizons.", "No target has a recent signal on at least two horizons."),
}
