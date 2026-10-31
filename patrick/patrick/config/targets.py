"""Ce qu'on a le droit de prédire : une série macro (FRED) n'est plus une cible (2026-10-31, `config/defaults.py::NON_TARGET_SOURCES`)."""
from __future__ import annotations

from patrick.config import defaults as D


def refuse_non_target(config, *, resumed: bool) -> None:
    """Refuse un NOUVEAU run dont la cible est une série macro. Un run déjà commencé (`patrick resume`) peut être repris : on ne change pas
    la configuration d'un run enregistré. Point de passage commun du formulaire web, de la file (`run_manager.start_run`), du worker et de
    la ligne de commande : `run_pipeline` l'appelle avant tout téléchargement."""
    if not resumed and config.objective.target_source in D.NON_TARGET_SOURCES:
        raise ValueError(D.NON_TARGET_MESSAGE)
