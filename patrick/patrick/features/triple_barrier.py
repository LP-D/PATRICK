"""Étiquettes « barrière triple » (López de Prado, AFML ch. 3) : un module OPTIONNEL, désactivé par défaut et relié à aucun entraînement.

Pour chaque date d'entrée t0, trois barrières : une haute (gain visé), une basse (perte tolérée), l'une et l'autre proportionnelles à la
volatilité du moment (donc plus larges quand le marché est agité), et une barrière verticale (`horizon` séances). L'étiquette est celle de la
première barrière touchée : +1 (haute), -1 (basse), et à l'échéance 0 ou le signe du rendement final (`vertical_label`).

Contrairement à « le cours monte-t-il dans h jours », l'étiquette tient compte du chemin : un titre qui s'effondre puis remonte n'est pas un
gain. Elle fournit aussi la date de fin réelle `t1` de chaque observation, utile pour purger les plis (`validation`) et pondérer les
chevauchements (`models/uniqueness.py`).

Point dans le temps : la volatilité de t0 n'utilise que des cours jusqu'à t0 (écart-type pondéré exponentiellement, décalé d'une séance) ;
les barrières futures sont, par construction, regardées après coup, c'est le principe d'une étiquette. Les `horizon` dernières dates, dont
la fenêtre n'est pas complète, ne reçoivent pas d'étiquette plutôt qu'une étiquette tronquée."""
from __future__ import annotations

import numpy as np
import pandas as pd

VERTICAL_LABELS = ("sign", "zero")


def daily_volatility(close: pd.Series, span: int = 20) -> pd.Series:
    """Écart-type pondéré exponentiellement des rendements journaliers, connu à la clôture de t0 (inclusive)."""
    ret = close.pct_change().replace([np.inf, -np.inf], np.nan)
    return ret.ewm(span=span, min_periods=max(5, span // 2)).std()


def triple_barrier_labels(close: pd.Series, horizon: int, vol: pd.Series | None = None, pt: float = 1.0, sl: float = 1.0,
                          min_vol: float = 1e-6, vertical_label: str = "sign", vol_span: int = 20) -> pd.DataFrame:
    """Étiquettes par date d'entrée : colonnes `label`, `ret` (rendement jusqu'à la sortie), `t1` (date de sortie), `barrier` (`upper`, `lower`, `vertical`),
    `vol` (volatilité utilisée), `bars` (séances écoulées).

    `pt` et `sl` sont des multiples de la volatilité (0 désactive la barrière correspondante). Les dates sans volatilité connue, ou à moins de
    `horizon` séances de la fin, sont absentes du résultat."""
    if horizon < 1:
        raise ValueError("horizon doit valoir au moins 1")
    if vertical_label not in VERTICAL_LABELS:
        raise ValueError(f"vertical_label inconnu : {vertical_label!r} ({VERTICAL_LABELS})")
    if pt < 0 or sl < 0:
        raise ValueError("pt et sl doivent être positifs ou nuls")
    close = close.dropna()
    if (close <= 0).any():
        raise ValueError("les cours doivent être strictement positifs")
    vol = daily_volatility(close, vol_span) if vol is None else vol.reindex(close.index)
    px = close.to_numpy(dtype=float)
    sigma = vol.to_numpy(dtype=float)
    idx = close.index
    n = len(px)
    rows = []
    for i in range(n - horizon):
        s = sigma[i]
        if not np.isfinite(s) or s < min_vol:
            continue
        path = px[i + 1:i + horizon + 1] / px[i] - 1.0                     # rendement cumulé à chaque séance de la fenêtre
        up = np.where(path >= pt * s)[0] if pt > 0 else np.array([], dtype=int)
        dn = np.where(path <= -sl * s)[0] if sl > 0 else np.array([], dtype=int)
        hit_up = int(up[0]) if len(up) else horizon
        hit_dn = int(dn[0]) if len(dn) else horizon
        if hit_up >= horizon and hit_dn >= horizon:
            k, barrier = horizon - 1, "vertical"
            label = int(np.sign(path[k])) if vertical_label == "sign" else 0
        elif hit_up <= hit_dn:                                                # en cas de touche le même jour, la haute prime : jamais testé séparément faute de données intrajournalières
            k, barrier, label = hit_up, "upper", 1
        else:
            k, barrier, label = hit_dn, "lower", -1
        rows.append((idx[i], label, float(path[k]), idx[i + 1 + k], barrier, float(s), k + 1))
    out = pd.DataFrame(rows, columns=["t0", "label", "ret", "t1", "barrier", "vol", "bars"]).set_index("t0")
    return out


def label_balance(labels: pd.DataFrame) -> dict:
    """Part de chaque étiquette et de chaque barrière touchée : à regarder avant d'entraîner (classes très déséquilibrées = barrières mal calibrées)."""
    n = len(labels)
    if not n:
        return {"n": 0, "label": {}, "barrier": {}, "mean_bars": None}
    return {"n": n, "label": {int(k): float(v) for k, v in (labels["label"].value_counts(normalize=True)).items()},
            "barrier": {str(k): float(v) for k, v in (labels["barrier"].value_counts(normalize=True)).items()}, "mean_bars": float(labels["bars"].mean())}
