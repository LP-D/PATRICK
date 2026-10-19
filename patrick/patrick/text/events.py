"""Extraction d'événements par règles : choc d'offre, sanction, grève, météo.

Volontairement par expressions (pas par mots isolés) : « strike » seul désigne aussi un accord (« strikes a deal »), un prix
d'exercice ou un bombardement. Les règles privilégient la précision ; une news peut porter plusieurs étiquettes.
Anglais et français. Aucun apprentissage : rien à ajuster, donc rien qui puisse fuir.
"""
from __future__ import annotations

import re

_RULES: dict[str, list[str]] = {
    "supply_shock": [
        r"supply\s+(?:disruptions?|shocks?|cuts?|shortages?|outages?|crunch)", r"(?:production|output)\s+cuts?",
        r"pipeline\s+(?:outages?|attacks?|explosions?|leaks?)", r"refiner(?:y|ies)\s+(?:fire|outage|shutdown|explosion)s?",
        r"export\s+bans?", r"embargo(?:es)?", r"shortages?", r"blockade", r"mine\s+(?:closure|shutdown)s?",
        r"pénuries?", r"baisse de (?:la )?production", r"rupture d'approvisionnement",
    ],
    "sanction": [
        r"sanctions?", r"sanctioned", r"embargo(?:es)?", r"export\s+controls?", r"asset\s+freezes?",
        r"blacklist(?:ed|s)?", r"entity\s+list", r"sanctionn(?:e|ent|és?)",
    ],
    "strike": [
        r"go(?:es)?\s+on\s+strike", r"on\s+strike", r"strike\s+action", r"walk-?outs?", r"work\s+stoppages?",
        r"(?:workers|union|unions|miners|dockworkers|dockers|pilots|truckers|labou?r)\s+strikes?",
        r"grèves?", r"grévistes?",
    ],
    "weather": [
        r"hurricanes?", r"typhoons?", r"cyclones?", r"tornado(?:es)?", r"droughts?", r"flood(?:s|ing)?", r"frosts?",
        r"heat\s?waves?", r"cold\s+snaps?", r"polar\s+vortex", r"wildfires?", r"el\s+niño", r"la\s+niña", r"blizzards?",
        r"sécheresses?", r"inondations?", r"canicules?", r"ouragans?",
    ],
}
_COMPILED = {tag: [re.compile(rf"(?<!\w){p}(?!\w)", re.IGNORECASE) for p in patterns] for tag, patterns in _RULES.items()}


def extract_events(text: str) -> list[str]:
    text = (text or "").replace("’", "'")
    return sorted(tag for tag, rxs in _COMPILED.items() if any(rx.search(text) for rx in rxs))
