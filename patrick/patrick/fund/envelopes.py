"""Fonds, enveloppes : ce qu'un PEA et un CTO peuvent détenir (ADR 0026). Calcul pur, sans base ni réseau.

Le PEA ne détient que des actions de sociétés de l'UE/EEE, au comptant, à l'achat : ni matière première, ni crypto, ni devise, ni indice,
ni future, ni CFD, ni vente à découvert, ni levier, ni action américaine ou asiatique, ni action britannique ou suisse (hors UE/EEE). L'application
est plus stricte que la loi sur un point, déjà dans `fund/rules.py` : titres cotés en euro seulement (les actions suédoises, danoises, norvégiennes,
polonaises... sont éligibles en droit, mais refusées ici). Les ETF sont exclus : seuls certains ETF sont éligibles au PEA (réplication physique d'actions
européennes) et rien dans la base ne dit lesquels. Le CTO détient tout.

L'éligibilité se juge sur le symbole (suffixe de la place Yahoo, classe d'actifs de `data/session_calendar`) : c'est une heuristique. L'éligibilité
légale dépend du siège de l'émetteur, pas de la place de cotation (une société cotée à Paris mais de siège hors UE ne l'est pas). Un motif d'exclusion
est toujours rendu : rien n'est écarté en silence.
"""
from __future__ import annotations

from patrick.data.session_calendar import classify_asset_class
from patrick.fund import instruments
from patrick.wealth.ledger import PEA_LIKELY_ELIGIBLE_SUFFIXES

REAL_CAPITAL = 5_000.0           # € de chaque fonds réel
REAL_FLAT_FEE = 1.0              # € par ordre, tout compris
REAL_MIN_POSITION = 200.0        # € : un aller-retour (2 €) ne coûte alors pas plus de 1 % de la position
REAL_MAX_MODELS = 60             # cellules examinées par le pilote : le capital n'en finance que `capital / REAL_MIN_POSITION` (25)

# Places de l'UE/EEE cotées dans une autre devise que l'euro : éligibles en droit, refusées par la règle « euro seulement » du moteur.
PEA_NON_EURO_SUFFIXES = (".ST", ".CO", ".OL", ".WA", ".PR", ".BD")
PEA_EURO_SUFFIXES = tuple(s for s in PEA_LIKELY_ELIGIBLE_SUFFIXES if s not in PEA_NON_EURO_SUFFIXES)

# Groupes de l'univers où le pilote d'un PEA cherche ses modèles : actions françaises, allemandes et des autres pays d'Europe. « Actions Royaume-Uni »
# est hors périmètre (le Royaume-Uni a quitté l'UE) ; le groupe « Autres pays » contient encore des actions suisses et nordiques, écartées une à une.
PEA_GROUPS = ("Actions France (CAC 40)", "Actions France (autres valeurs)", "Actions Allemagne", "Actions Europe (autres pays)")

# Motifs d'exclusion d'un PEA (codes des cellules écartées du pilote, libellés dans `fund/autopilot.LABELS`).
PEA_NOT_A_SHARE = "pea"
PEA_ETF = "pea_etf"
PEA_ZONE = "pea_zone"
PEA_CURRENCY = "pea_devise"


def pea_eligibility(symbol: str, groups: dict[str, str] | None = None) -> str | None:
    """None si l'actif peut entrer dans un PEA (action cotée d'une place de l'UE/EEE en euro), sinon le code du motif :
    `pea` (pas une action au comptant : indice, devise, matière première, crypto, future), `pea_etf` (ETF), `pea_zone` (hors UE/EEE : États-Unis,
    Asie, Royaume-Uni, Suisse...), `pea_devise` (UE/EEE mais pas en euro). `groups` : symbole -> groupe de l'univers (le nom d'un groupe d'ETF
    contient « ETF »)."""
    sym = symbol.upper()
    if instruments.classify_cfd_underlying(sym) != "equity" or sym.endswith(".NYB"):
        return PEA_NOT_A_SHARE
    if "ETF" in (groups or {}).get(symbol, ""):
        return PEA_ETF
    if not sym.endswith(PEA_LIKELY_ELIGIBLE_SUFFIXES):          # États-Unis (sans suffixe), Asie, Royaume-Uni (.L), Suisse (.SW)...
        return PEA_ZONE
    if sym.endswith(PEA_NON_EURO_SUFFIXES):
        return PEA_CURRENCY
    if classify_asset_class(sym) != "equities_europe":           # .F, .AT, .LU : place de l'UE que le calendrier des séances ne range pas en Europe
        return PEA_ZONE
    return None
