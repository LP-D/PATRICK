"""Étiquette de cible d'un run (`run.target`).

Cible brute : le symbole lui-même (`MC.PA`), comme toujours. Cible alpha : le symbole suivi du benchmark
(`MC.PA__alpha_^GSPC`). Cette étiquette est aussi la clé du snapshot de données (`raw_<étiquette>`).

Pourquoi une étiquette distincte plutôt qu'une colonne à filtrer : `run.target` est lu par des dizaines de requêtes
(champions, registre d'essais, familles DM/BH, rejeu du patrimoine, historique). Avec une étiquette distincte, un run
alpha ne se mélange jamais à un run brut du même actif, et tout consommateur qui attend un symbole échoue franchement
au lieu de traiter silencieusement un modèle d'alpha (qui prédit une surperformance) comme un signal de direction du prix.
"""
from __future__ import annotations

ALPHA_SEP = "__alpha_"


def run_label(symbol: str, kind: str = "raw", benchmark: str | None = None) -> str:
    if kind == "alpha":
        return f"{symbol}{ALPHA_SEP}{benchmark}"
    return symbol


def is_alpha_label(label: str) -> bool:
    return ALPHA_SEP in (label or "")


def split_run_label(label: str) -> tuple[str, str, str | None]:
    """`(symbole, "raw" | "alpha", benchmark | None)`."""
    if not is_alpha_label(label):
        return label, "raw", None
    symbol, benchmark = label.split(ALPHA_SEP, 1)
    return symbol, "alpha", benchmark
