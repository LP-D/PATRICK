"""Bibliothèque d'études : importer ce paquet enregistre toutes les cartes dans `base.REGISTRY`."""
from patrick.earnings.studies import (  # noqa: F401 -- l'import enregistre les cartes
    calendar_effects,
    core_a,
    cross,
    news_analysts,
    probabilistic,
    robustness,
    strategies,
    surprise,
    vol_liq,
)
from patrick.earnings.studies.base import (  # noqa: F401
    GROUP_TITLES,
    GROUPS,
    REGISTRY,
    Ctx,
    Param,
    Study,
)
from patrick.earnings.studies.runner import (  # noqa: F401
    fdr_ledger,
    run_many,
    run_study,
)
