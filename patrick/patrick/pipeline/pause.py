"""Point de pause coopératif : une pause demandée dans l'interface prend effet entre deux calculs, même pendant une phase silencieuse.

Avant, le worker ne regardait la pause que lorsque le pipeline IMPRIMAIT une ligne (`worker._ProgressCapture`) : pendant le réglage Optuna
(100 essais, des heures, aucune ligne) la pause n'avait aucun effet alors que l'interface affichait « en pause ». Le moteur appelle
`checkpoint()` avant chaque ajustement de modèle, chaque sélection de variables et chaque pli d'Optuna ; le worker y branche une porte
(`set_hook`) qui attend tant que la pause est demandée. Sans porte (CLI, tests, processus de calcul parallèle) : aucun effet.
"""
from __future__ import annotations

from collections.abc import Callable

_hook: Callable[[], None] | None = None


def set_hook(hook: Callable[[], None] | None) -> None:
    global _hook
    _hook = hook


def checkpoint() -> None:
    hook = _hook
    if hook is not None:
        hook()
