"""Panneau de métriques d'un modèle, et règle qui compare deux modèles (ADR 0023, 2026-11-16).

Pourquoi : le F1 de direction ne départage pas les modèles. Il dépend d'un seuil (la classe la plus probable parmi quatre), son classement
en validation croisée prédit mal le holdout (corrélation de rang +0,11 contre +0,37 pour l'AUC, ADR 0013) et il ne dit rien de la
fiabilité des probabilités dont se servent le fonds et le conseiller. Un modèle se lit désormais sur quatre mesures, toujours les mêmes,
toujours dans cet ordre :

- `AUC_dir`  : classe-t-il bien les jours de hausse avant les jours de baisse ? P(hausse) contre la direction réelle, sans seuil. 0,5 = hasard.
- `Brier_up` : ses probabilités sont-elles fiables ? Écart quadratique moyen entre P(hausse) et ce qui s'est passé. Plus bas = mieux ;
  0,25 = annoncer 50 % tous les jours.
- `MCC_4cls` : ses décisions sur les quatre mouvements sont-elles corrélées à la réalité ? -1 à 1, 0 = hasard, insensible au déséquilibre.
- `Acc_dir_p` : part des jours où la direction annoncée (P(hausse) au-dessus de la médiane de ses prédictions récentes, décision causale,
  `validation/direction.py`) était la bonne. 50 % = hasard.

Règle du duel champion / challenger : le challenger prend le titre s'il CLASSE mieux (AUC_dir strictement plus haute sur le même holdout)
SANS dégrader la fiabilité de ses probabilités (Brier_up au plus `BRIER_TOLERANCE` au-dessus de celui du champion). Égalité ou doute :
le champion reste. Quand un côté n'a pas de Brier, l'AUC seule décide ; quand un côté n'a pas de P(hausse) du tout (ni AUC ni Brier),
le MCC décide. Le F1 n'intervient plus dans aucune comparaison.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class PanelMetric:
    key: str                 # nom dans `fold_metric.metric`
    higher_is_better: bool
    chance: float            # valeur d'un modèle qui ne sait rien
    percent: bool = False    # affiché en pourcentage


PANEL: tuple[PanelMetric, ...] = (
    PanelMetric("AUC_dir", True, 0.5),
    PanelMetric("Brier_up", False, 0.25),
    PanelMetric("MCC_4cls", True, 0.0),
    PanelMetric("Acc_dir_p", True, 0.5, percent=True),
)
PANEL_KEYS: tuple[str, ...] = tuple(m.key for m in PANEL)
BY_KEY = {m.key: m for m in PANEL}

# Le Brier d'un même modèle bouge de quelques millièmes d'un holdout à l'autre ; le réglage le baisse de 0,006 en moyenne (audit du
# 2026-10-23). Au-delà de 0,005 de plus que le champion, les probabilités du challenger sont jugées moins fiables : il ne gagne pas.
BRIER_TOLERANCE = 0.005

CRITERION_AUC_BRIER = "AUC_dir+Brier_up"
CRITERION_AUC = "AUC_dir"
CRITERION_MCC = "MCC_4cls"

RULES = {
    CRITERION_AUC_BRIER: (f"AUC_dir strictly greater on the same holdout AND Brier_up at most {BRIER_TOLERANCE} above the champion's, "
                          "both configurations retrained on the same pre-holdout data; tie or doubt -> the champion stays"),
    CRITERION_AUC: ("AUC_dir strictly greater on the same holdout (a side has no Brier_up), both configurations retrained on the same "
                    "pre-holdout data; tie -> the champion stays"),
    CRITERION_MCC: ("MCC_4cls strictly greater on the same holdout (a side has no P(up), hence no AUC_dir), both configurations retrained "
                    "on the same pre-holdout data; tie -> the champion stays"),
}


def value(metrics: dict | None, key: str) -> float | None:
    """La métrique `key` de `metrics`, ou None (absente, NaN, illisible)."""
    if not metrics:
        return None
    raw = metrics.get(key)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def panel(metrics: dict | None) -> dict[str, float | None]:
    """`{AUC_dir, Brier_up, MCC_4cls, Acc_dir_p}` extraits de `metrics` (None pour une mesure absente)."""
    return {key: value(metrics, key) for key in PANEL_KEYS}


def has_any(p: dict | None) -> bool:
    return bool(p) and any(v is not None for v in p.values())


def better(key: str, a: float | None, b: float | None) -> bool:
    """`a` strictement meilleur que `b` pour la métrique `key` (False si l'un manque)."""
    if a is None or b is None:
        return False
    return a < b if not BY_KEY[key].higher_is_better else a > b


def best_of(key: str, values) -> float | None:
    """La meilleure valeur de `values` pour `key` (min pour le Brier, max sinon), None si aucune."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return min(vals) if not BY_KEY[key].higher_is_better else max(vals)


def duel_verdict(challenger: dict | None, champion: dict | None) -> dict | None:
    """Applique la règle du duel à deux jeux de métriques du MÊME holdout.

    Renvoie `{criterion, rule, winner, reason, challenger: panel, champion: panel, challenger_score, champion_score}` ou None si rien ne
    permet de les comparer (aucune mesure commune). `reason` : `better` (le challenger gagne), `auc_not_better`, `brier_worse`,
    `mcc_not_better`. `*_score` : la mesure qui classe (AUC_dir, ou MCC_4cls en dernier recours), pour les journaux et `duel_outcome`."""
    chal, champ = panel(challenger), panel(champion)
    auc_c, auc_k = chal["AUC_dir"], champ["AUC_dir"]
    brier_c, brier_k = chal["Brier_up"], champ["Brier_up"]
    if auc_c is not None and auc_k is not None:
        auc_ok = auc_c > auc_k
        if brier_c is not None and brier_k is not None:
            criterion = CRITERION_AUC_BRIER
            brier_ok = brier_c <= brier_k + BRIER_TOLERANCE
            wins = auc_ok and brier_ok
            reason = "better" if wins else ("auc_not_better" if not auc_ok else "brier_worse")
        else:
            criterion, wins = CRITERION_AUC, auc_ok
            reason = "better" if wins else "auc_not_better"
        score_c, score_k = auc_c, auc_k
    else:
        mcc_c, mcc_k = chal["MCC_4cls"], champ["MCC_4cls"]
        if mcc_c is None or mcc_k is None:
            return None
        criterion, wins = CRITERION_MCC, mcc_c > mcc_k
        reason = "better" if wins else "mcc_not_better"
        score_c, score_k = mcc_c, mcc_k
    return {"criterion": criterion, "rule": RULES[criterion], "winner": "challenger" if wins else "champion", "reason": reason,
            "challenger": chal, "champion": champ, "challenger_score": score_c, "champion_score": score_k}


def fmt(key: str, v: float | None) -> str:
    """Texte d'une mesure du panneau (« — » si absente) : pourcentage à une décimale pour la bonne direction, trois décimales sinon."""
    if v is None:
        return "—"
    return f"{v * 100:.1f} %" if BY_KEY[key].percent else f"{v:.3f}"


def cells(p: dict | None) -> list[str]:
    """Les quatre mesures de `p` en texte, dans l'ordre du panneau (cellules d'un tableau)."""
    return [fmt(key, (p or {}).get(key)) for key in PANEL_KEYS]


def heads(labels: dict) -> list[str]:
    """Les quatre en-têtes de colonne, traduits (`labels` = `m_labels` des gabarits : clés `pm_<métrique>`)."""
    return [labels.get(f"pm_{key}", key) for key in PANEL_KEYS]


def rank_key(p: dict | None) -> tuple:
    """Clé de classement d'un modèle dans une liste (meilleur en premier avec `sorted(..., key=rank_key)`) : AUC_dir décroissante, puis
    Brier_up croissant ; un modèle sans AUC_dir passe après tous les autres. Même ordre que la règle du duel, sans la tolérance (qui n'a de
    sens qu'entre deux modèles notés sur le même holdout)."""
    auc, brier = value(p, "AUC_dir"), value(p, "Brier_up")
    return (auc is None, -(auc or 0.0), brier is None, brier or 0.0)
