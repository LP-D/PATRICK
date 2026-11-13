"""Ce qu'on a le droit de prédire : une série macro (FRED) n'est plus une cible (2026-10-31, `config/defaults.py::NON_TARGET_SOURCES`)."""
from __future__ import annotations

from patrick.config import defaults as D


def macro_symbols() -> frozenset[str]:
    """Les séries macro (FRED) du catalogue : variables d'entraînement seulement, plus des cibles."""
    return frozenset(sym for sym, _, src in D.DEFAULT_TARGET_CHOICES if src in D.NON_TARGET_SOURCES)


def is_macro_target(label: str) -> bool:
    """`run.target` (symbole ou étiquette alpha) désigne-t-il une série macro ? Les runs d'avant le 2026-10-31 en portent encore : leurs
    signaux du jour, leur « résultat réel » et leur signal regroupé seraient de la fausse information (aucune de ces séries ne se
    négocie, et leurs scores étaient gonflés par des séries dérivées du même taux), donc rien de ce qu'on suit ne les lit."""
    from patrick.config.target_label import split_run_label

    return split_run_label(label or "")[0] in macro_symbols()


def refuse_non_target(config, *, resumed: bool) -> None:
    """Refuse un NOUVEAU run dont la cible est une série macro. Un run déjà commencé (`patrick resume`) peut être repris : on ne change pas
    la configuration d'un run enregistré. Point de passage commun du formulaire web, de la file (`run_manager.start_run`), du worker et de
    la ligne de commande : `run_pipeline` l'appelle avant tout téléchargement."""
    if not resumed and config.objective.target_source in D.NON_TARGET_SOURCES:
        raise ValueError(D.NON_TARGET_MESSAGE)
