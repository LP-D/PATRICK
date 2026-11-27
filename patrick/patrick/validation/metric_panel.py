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

Modèles de valeur exacte (étiquette `__val`, ADR 0029 puis 0032) : ils prédisent un rendement, pas une classe. Leurs probabilités de classe
existent (tirées de leurs erreurs hors échantillon), donc le panneau de direction se calcule aussi, mais il ne dit pas ce qu'un régresseur
fait de mieux ou de pire. Ils se lisent sur leur propre panneau, même logique, même ordre de lecture :

- `IC`       : ordonne-t-il bien les rendements ? Corrélation de rang prévu / réalisé (l'équivalent de l'AUC). 0 = hasard.
- `R2_oos`   : ses amplitudes valent-elles mieux que « rendement nul » ? (Campbell et Thompson.) > 0 = oui ; < 0 = il se trompe plus fort
  que s'il ne prédisait rien. L'équivalent du MCC : la décision chiffrée, pas seulement l'ordre.
- `Hit_sign` : part des signes justes (l'équivalent de la bonne direction). 50 % = hasard.
- `Cov80`    : son incertitude est-elle juste ? Part des rendements réels dans son intervalle à 80 % (l'équivalent du Brier : les
  probabilités de classe lues par les fonds viennent de ces mêmes erreurs). Cible 80 % : au-dessous, il se croit plus précis qu'il n'est.

Règle du duel de la catégorie : le challenger prend le titre s'il ORDONNE mieux (IC strictement plus haute sur le même holdout) SANS
dégrader ses amplitudes (R² hors échantillon au plus `R2_TOLERANCE` sous celui du champion) ; sans R² d'un côté, l'IC seule décide.
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
    target: float | None = None   # mesure « au plus près de » (couverture d'un intervalle) : ni plus haut ni plus bas ne vaut mieux
    digits: int = 3          # décimales (pourcentage : décimales du pourcentage)
    signed: bool = False     # signe toujours affiché (R² hors échantillon : « -0,012 » se lit « pire que rien »)


PANEL: tuple[PanelMetric, ...] = (
    PanelMetric("AUC_dir", True, 0.5),
    PanelMetric("Brier_up", False, 0.25),
    PanelMetric("MCC_4cls", True, 0.0),
    PanelMetric("Acc_dir_p", True, 0.5, percent=True, digits=1),
)
PANEL_KEYS: tuple[str, ...] = tuple(m.key for m in PANEL)
BY_KEY = {m.key: m for m in PANEL}

# Panneau des modèles de valeur exacte (voir le module) et leurs mesures secondaires (fiche d'un run).
VALUE_PANEL: tuple[PanelMetric, ...] = (
    PanelMetric("IC", True, 0.0),
    PanelMetric("R2_oos", True, 0.0, signed=True),
    PanelMetric("Hit_sign", True, 0.5, percent=True, digits=1),
    PanelMetric("Cov80", True, 0.8, percent=True, digits=1, target=0.8),
)
VALUE_PANEL_KEYS: tuple[str, ...] = tuple(m.key for m in VALUE_PANEL)
VALUE_EXTRA: tuple[PanelMetric, ...] = (
    PanelMetric("MAE_skill", True, 0.0, signed=True),
    PanelMetric("MZ_slope", True, 0.0, digits=2, target=1.0),
    PanelMetric("Gain_sign", True, 0.0, percent=True, digits=2, signed=True),
    PanelMetric("MAE", False, 0.0, percent=True, digits=2),
    PanelMetric("RMSE", False, 0.0, percent=True, digits=2),
)
VALUE_EXTRA_KEYS: tuple[str, ...] = tuple(m.key for m in VALUE_EXTRA)
ALL_BY_KEY = {m.key: m for m in (*PANEL, *VALUE_PANEL, *VALUE_EXTRA)}

# Le Brier d'un même modèle bouge de quelques millièmes d'un holdout à l'autre ; le réglage le baisse de 0,006 en moyenne (audit du
# 2026-10-23). Au-delà de 0,005 de plus que le champion, les probabilités du challenger sont jugées moins fiables : il ne gagne pas.
BRIER_TOLERANCE = 0.005
# Valeur exacte : sur les 84 premiers champions (27/11/2026), le R² hors échantillon du holdout va de -0,95 à +0,09 (médiane par horizon entre
# -0,013 et +0,023). Un point de R² de moins que le champion est du bruit d'échantillon ; au-delà, le challenger amplifie ses prévisions à tort.
R2_TOLERANCE = 0.01

CRITERION_AUC_BRIER = "AUC_dir+Brier_up"
CRITERION_AUC = "AUC_dir"
CRITERION_MCC = "MCC_4cls"
CRITERION_IC = "IC"
CRITERION_IC_R2 = "IC+R2_oos"

RULES = {
    CRITERION_IC_R2: (f"exact-value models: IC (rank correlation of predicted vs realised return) strictly greater on the same holdout AND "
                      f"R2_oos at most {R2_TOLERANCE} below the champion's, both configurations retrained on the same pre-holdout data; "
                      "tie or doubt -> the champion stays"),
    CRITERION_IC: ("exact-value models: IC (rank correlation of predicted vs realised return) strictly greater on the same holdout (a side "
                   "has no R2_oos), both configurations retrained on the same pre-holdout data; tie -> the champion stays"),
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


def value_panel(metrics: dict | None, extra: bool = False) -> dict[str, float | None]:
    """`{IC, R2_oos, Hit_sign, Cov80}` (et les mesures secondaires avec `extra`) extraits de `metrics`, None pour une mesure absente."""
    return {key: value(metrics, key) for key in (*VALUE_PANEL_KEYS, *(VALUE_EXTRA_KEYS if extra else ()))}


def keys_for(kind: str | None) -> tuple[str, ...]:
    """Les clés du panneau d'un modèle de ce genre (`value` : valeur exacte ; tout le reste : direction)."""
    return VALUE_PANEL_KEYS if kind == "value" else PANEL_KEYS


def panel_for(metrics: dict | None, kind: str | None) -> dict[str, float | None]:
    """Le panneau qui convient au genre du modèle (`keys_for`)."""
    return value_panel(metrics) if kind == "value" else panel(metrics)


def has_any(p: dict | None) -> bool:
    return bool(p) and any(v is not None for v in p.values())


def _distance(m: PanelMetric, v: float) -> float:
    return abs(v - m.target) if m.target is not None else (-v if m.higher_is_better else v)


def better(key: str, a: float | None, b: float | None) -> bool:
    """`a` strictement meilleur que `b` pour la métrique `key` (False si l'un manque) ; une mesure à cible (`Cov80`) : le plus proche."""
    if a is None or b is None:
        return False
    m = ALL_BY_KEY[key]
    return _distance(m, a) < _distance(m, b)


def best_of(key: str, values) -> float | None:
    """La meilleure valeur de `values` pour `key` (min pour le Brier, la plus proche de la cible pour une couverture, max sinon), None si aucune."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    m = ALL_BY_KEY[key]
    return min(vals, key=lambda v: _distance(m, v))


def duel_verdict(challenger: dict | None, champion: dict | None) -> dict | None:
    """Applique la règle du duel à deux jeux de métriques du MÊME holdout.

    Renvoie `{criterion, rule, winner, reason, challenger: panel, champion: panel, challenger_score, champion_score}` ou None si rien ne
    permet de les comparer (aucune mesure commune). `reason` : `better` (le challenger gagne), `auc_not_better`, `brier_worse`,
    `mcc_not_better`, `ic_not_better`, `r2_worse`. `*_score` : la mesure qui classe (AUC_dir, IC pour la valeur exacte, ou MCC_4cls en
    dernier recours), pour les journaux et `duel_outcome`."""
    chal, champ = panel(challenger), panel(champion)
    ic_c, ic_k = value(challenger, "IC"), value(champion, "IC")
    if ic_c is not None and ic_k is not None:
        # Catégorie « valeur exacte » (étiquette `__val`) : le meilleur modèle est celui qui ordonne le mieux les rendements, ML ou DL,
        # sans amplifier ses prévisions au point de faire pire que son prédécesseur sur l'erreur quadratique.
        ic_ok = ic_c > ic_k
        r2_c, r2_k = value(challenger, "R2_oos"), value(champion, "R2_oos")
        if r2_c is not None and r2_k is not None:
            criterion = CRITERION_IC_R2
            r2_ok = r2_c >= r2_k - R2_TOLERANCE
            wins = ic_ok and r2_ok
            reason = "better" if wins else ("ic_not_better" if not ic_ok else "r2_worse")
        else:
            criterion, wins = CRITERION_IC, ic_ok
            reason = "better" if wins else "ic_not_better"
        return {"criterion": criterion, "rule": RULES[criterion], "winner": "challenger" if wins else "champion",
                "reason": reason, "challenger": value_panel(challenger), "champion": value_panel(champion),
                "challenger_score": ic_c, "champion_score": ic_k}
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
    """Texte d'une mesure (« — » si absente) : pourcentage pour la bonne direction, le bon signe, la couverture et le gain par position,
    trois décimales sinon ; signe affiché pour le R² et le gain hors échantillon. Une mesure inconnue du panneau : trois décimales."""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v) or math.isinf(v):
        return "—"
    m = ALL_BY_KEY.get(key)
    if m is None:
        return f"{v:.3f}"
    sign = "+" if m.signed else ""
    return f"{v * 100:{sign}.{m.digits}f} %" if m.percent else f"{v:{sign}.{m.digits}f}"


def cells(p: dict | None, keys: tuple[str, ...] = PANEL_KEYS) -> list[str]:
    """Les mesures de `p` en texte, dans l'ordre du panneau (cellules d'un tableau) ; `keys` : `VALUE_PANEL_KEYS` pour la valeur exacte."""
    return [fmt(key, (p or {}).get(key)) for key in keys]


def heads(labels: dict, keys: tuple[str, ...] = PANEL_KEYS) -> list[str]:
    """Les en-têtes de colonne, traduits (`labels` = `m_labels` des gabarits : clés `pm_<métrique>`)."""
    return [labels.get(f"pm_{key}", key) for key in keys]


def rank_key(p: dict | None) -> tuple:
    """Clé de classement d'un modèle dans une liste (meilleur en premier avec `sorted(..., key=rank_key)`) : AUC_dir décroissante, puis
    Brier_up croissant ; un modèle sans AUC_dir passe après tous les autres. Même ordre que la règle du duel, sans la tolérance (qui n'a de
    sens qu'entre deux modèles notés sur le même holdout)."""
    auc, brier = value(p, "AUC_dir"), value(p, "Brier_up")
    return (auc is None, -(auc or 0.0), brier is None, brier or 0.0)


def value_rank_key(p: dict | None) -> tuple:
    """Même chose pour la valeur exacte : IC décroissante, puis R² hors échantillon décroissant ; sans IC, après tous les autres."""
    ic, r2 = value(p, "IC"), value(p, "R2_oos")
    return (ic is None, -(ic or 0.0), r2 is None, -(r2 or 0.0))
