"""Étiquette de cible d'un run (`run.target`).

Cible brute : le symbole lui-même (`MC.PA`), comme toujours. Cible alpha : le symbole suivi du benchmark
(`MC.PA__alpha_^GSPC`). Objectif « valeur exacte » (le modèle prédit le rendement à l'horizon, pas sa classe) : l'étiquette
précédente suivie de `__val` (`MC.PA__val`, `MC.PA__alpha_^GSPC__val`). L'étiquette SANS l'objectif est aussi la clé du snapshot
de données (`raw_<étiquette>`) : direction et valeur exacte lisent les mêmes données.

Pourquoi une étiquette distincte plutôt qu'une colonne à filtrer : `run.target` est lu par des dizaines de requêtes
(champions, registre d'essais, familles DM/BH, rejeu du patrimoine, historique). Avec une étiquette distincte, un run
alpha ne se mélange jamais à un run brut du même actif, et tout consommateur qui attend un symbole échoue franchement
au lieu de traiter silencieusement un modèle d'alpha (qui prédit une surperformance) comme un signal de direction du prix.
Même règle pour l'objectif : un modèle de valeur exacte a ses propres champions, ML et DL confondus, distincts de ceux de la direction.
"""
from __future__ import annotations

ALPHA_SEP = "__alpha_"
VALUE_SUFFIX = "__val"
TASKS = ("direction", "value")


def run_label(symbol: str, kind: str = "raw", benchmark: str | None = None, task: str = "direction") -> str:
    base = f"{symbol}{ALPHA_SEP}{benchmark}" if kind == "alpha" else symbol
    return f"{base}{VALUE_SUFFIX}" if task == "value" else base


def split_task(label: str) -> tuple[str, str]:
    """`(étiquette sans l'objectif, "direction" | "value")`."""
    label = label or ""
    if label.endswith(VALUE_SUFFIX):
        return label[: -len(VALUE_SUFFIX)], "value"
    return label, "direction"


def is_value_label(label: str) -> bool:
    return split_task(label)[1] == "value"


def is_alpha_label(label: str) -> bool:
    return ALPHA_SEP in (label or "")


def split_run_label(label: str) -> tuple[str, str, str | None]:
    """`(symbole, "raw" | "alpha", benchmark | None)` ; l'objectif (`__val`) est retiré : voir `split_task`."""
    base, _task = split_task(label)
    if not is_alpha_label(base):
        return base, "raw", None
    symbol, benchmark = base.split(ALPHA_SEP, 1)
    return symbol, "alpha", benchmark
