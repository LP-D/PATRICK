"""Fraîcheur/retard des données ingérées, par ticker/série (Phase 5,
Dashboard de fraîcheur des données).

RÈGLE STRICTE : ce module ne lit QUE le data lake local (`data/store.py` /
`_index.json`, via `DataStore`) -- jamais d'appel réseau à yfinance ou à
l'API FRED. Le but est d'afficher rapidement, sans latence réseau ni risque
d'échec externe, l'état de fraîcheur de ce que PATRICK a déjà sur disque.

--------------------------------------------------------------------------
Sources lues (les deux locales) :

1. les snapshots `raw_{symbol}` -- un ticker qui a lui-même servi de CIBLE ;
2. `_series_observations.json` (`DataStore.record_series_observations`) --
   la date de la dernière observation RÉELLEMENT publiée de chaque série de
   l'univers, enregistrée à chaque ingestion avant tout forward-fill.

Avant (2), seule la source (1) existait : `ingest()` sauvegarde le frame joint
sous une unique clé `raw_{target}`, colonnes de features forward-fillées (la
dernière vraie observation y est perdue). Audit du cache réel (2026-09-05) :
3 des 68 tickers de `DEFAULT_TARGET_GROUPS` observables. Désormais toute
série ingérée au moins une fois (comme cible OU comme feature) l'est.

Séries FRED : le retard est mesuré contre la publication ATTENDUE de
l'observation suivante (`fred_business_days_late`, calendrier de
`data/publication_lag.py`), pas contre la date de référence de la dernière
observation -- qui est, par construction, antérieure de plusieurs semaines à
sa propre publication.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from patrick.clock import utc_today
from patrick.data.store import DataStore

# ---------------------------------------------------------------------------
# Périodicité de publication par série FRED (préfixe/pattern ou code exact).
#
# `_index.json` ne connaît que des dates de dernière observation, jamais la
# fréquence ATTENDUE de publication d'une série -- sans cette table, un seuil
# unique (pensé pour du quotidien) déclencherait une fausse alerte quasi
# permanente sur CPI/UNRATE/GDP/... (28-90 jours "de retard" chaque cycle,
# largement au-dessus d'un seuil pensé pour 2 jours ouvrés). Table
# volontairement approximative (documentée comme telle), construite à partir
# des indications produit explicites PLUS les autres séries actuellement
# présentes dans `config/defaults.py::DEFAULT_TARGET_GROUPS["Macro (FRED)"]`
# (fréquence de publication FRED réelle de chacune, à titre de complément).
# ---------------------------------------------------------------------------

#: Préfixes reconnus -> quotidien. DGS*/DTB* (taux du Trésor), T10Y*/T5Y*
#: (spreads/breakevens d'inflation), BAML* (spreads de crédit ICE BofA),
#: DCOIL* (WTI/Brent FRED, publiés chaque jour ouvré), VIXCLS/VIXDVOL (VIX).
FRED_DAILY_PREFIXES = ("DGS", "DTB", "T10Y", "T5Y", "BAML", "DCOIL", "VIXCLS", "VIXDVOL")
#: Codes exacts -> quotidien (taux/indices publiés chaque jour ouvré, pas de
#: préfixe commun pratique). SP500/WILL5000IND : indices de marché FRED,
#: mise à jour quotidienne. TEDRATE : spread de taux quotidien (série
#: interrompue par la Fed depuis 2022, mais la FRÉQUENCE de publication
#: documentée reste quotidienne -- ce module classe par fréquence de
#: publication, pas par "série encore active").
FRED_DAILY_EXACT = {"DFF", "EFFR", "SOFR", "SP500", "WILL5000IND", "TEDRATE"}

#: Préfixes reconnus -> mensuel. CPI* (CPIAUCSL/CPILFESL), PCE* (PCE/PCEPILFE).
FRED_MONTHLY_PREFIXES = ("CPI", "PCE")
#: Codes exacts -> mensuel (indications produit explicites).
FRED_MONTHLY_EXACT = {"UNRATE", "PAYEMS", "RSAFS", "INDPRO", "FEDFUNDS", "UMCSENT"}

#: Codes exacts -> trimestriel.
FRED_QUARTERLY_EXACT = {"GDP"}

#: Codes exacts -> hebdomadaire (NFCI/STLFSI4, publiées le jeudi par la Fed
#: de Chicago/St. Louis).
FRED_WEEKLY_EXACT = {"NFCI", "STLFSI4"}

#: Fréquence par défaut pour toute série FRED absente de la table ci-dessus
#: (ex. "OILPRICE", libellé maison sans code FRED standard identifiable avec
#: certitude sans appel réseau). "monthly" est le choix le plus prudent :
#: la fréquence macro la plus répandue, et celle qui minimise le risque de
#: fausse alerte si la série est en réalité mensuelle ou trimestrielle
#: plutôt que quotidienne.
FRED_DEFAULT_PERIODICITY = "monthly"


def fred_periodicity(series_id: str) -> str:
    """Périodicité de publication approximative d'une série FRED, par code
    exact puis par préfixe reconnu -- jamais d'appel réseau à l'API FRED
    (qui exposerait la vraie métadonnée `frequency`), volontairement une
    heuristique locale documentée."""
    if series_id in FRED_QUARTERLY_EXACT:
        return "quarterly"
    if series_id in FRED_WEEKLY_EXACT:
        return "weekly"
    if series_id in FRED_MONTHLY_EXACT or series_id.startswith(FRED_MONTHLY_PREFIXES):
        return "monthly"
    if series_id in FRED_DAILY_EXACT or series_id.startswith(FRED_DAILY_PREFIXES):
        return "daily"
    return FRED_DEFAULT_PERIODICITY


# ---------------------------------------------------------------------------
# Seuils d'alerte par périodicité, exprimés en JOURS OUVRÉS de retard.
#
# "Jours ouvrés" ici = jours de semaine (lundi-vendredi), via
# `numpy.busday_count` avec le calendrier par défaut (week-ends exclus,
# AUCUN calendrier de jours fériés marché/Fed) -- approximation documentée
# et assumée : un jour férié ajoute au plus 1-2 jours ouvrés apparents de
# "retard", largement absorbé par la marge de chaque seuil ci-dessous.
# ---------------------------------------------------------------------------

PERIODICITY_ALERT_THRESHOLD_BDAYS = {
    # yfinance / FRED quotidien : seuil produit explicite -- au-delà de 2
    # jours ouvrés (plus qu'un long week-end/jour férié isolé), le marché a
    # coté au moins une fois de plus sans que la donnée locale ne bouge.
    "daily": 2,
    # NFCI/STLFSI4 publiées chaque jeudi : ~5 jours ouvrés séparent deux
    # points normalement. Seuil = ~2 cycles (10 jours ouvrés) pour absorber
    # un jour férié ou un léger retard de publication sans fausse alerte.
    "weekly": 10,
    # Cycle mensuel ≈ 21 jours ouvrés ; les séries macro (CPI, PAYEMS...)
    # sont en outre publiées avec un délai de quelques semaines après la
    # fin de la période couverte. Seuil = ~7 semaines ouvrées (35 jours
    # ouvrés), soit un cycle complet + marge de délai de publication.
    "monthly": 35,
    # Cycle trimestriel ≈ 63 jours ouvrés (GDP, publié avec ~1 mois de
    # délai après la fin du trimestre). Seuil = ~1 trimestre + le délai de
    # publication + marge (95 jours ouvrés) avant de considérer la série
    # réellement en retard (et pas simplement "pas encore republiée ce
    # trimestre-ci").
    "quarterly": 95,
}


def business_days_late(date_max, as_of=None) -> int:
    """Nombre de jours ouvrés séparant `date_max` (dernière donnée connue,
    `date`/`str`/`Timestamp`) de `as_of` (par défaut aujourd'hui). Jamais
    négatif : une `date_max` égale ou postérieure à `as_of` renvoie 0."""
    as_of = as_of if as_of is not None else utc_today()
    d0 = pd.Timestamp(date_max).normalize().date()
    d1 = pd.Timestamp(as_of).normalize().date()
    if d0 >= d1:
        return 0
    return int(np.busday_count(d0, d1))


# FRED -- tolérance (jours ouvrés) au-delà de la date de publication ATTENDUE
# de l'observation suivante (`fred_business_days_late`).
FRED_RELEASE_MARGIN_BDAYS = {"daily": 2, "weekly": 3, "monthly": 5, "quarterly": 10}

_NEXT_PERIOD = {
    "daily": pd.offsets.BDay(1),
    "weekly": pd.Timedelta(days=7),
    "monthly": pd.offsets.MonthBegin(1),
    "quarterly": pd.offsets.QuarterBegin(1, startingMonth=1),
}


def fred_business_days_late(series_id: str, date_max, periodicity: str, as_of=None) -> int:
    """Retard d'une série FRED mesuré contre la publication ATTENDUE de
    l'observation suivante (période suivante + délai de publication,
    `data/publication_lag.py`), pas contre sa date de référence : le CPI de
    mai (daté du 1er mai) reste la dernière valeur disponible jusqu'à la
    publication de juin, mi-juillet -- 43 jours ouvrés « de retard » au 1er
    juillet sur la date de référence, zéro en réalité."""
    from patrick.data import publication_lag

    as_of = as_of if as_of is not None else utc_today()
    next_ref = pd.Timestamp(date_max) + _NEXT_PERIOD[periodicity]
    expected = publication_lag.availability_dates(pd.DatetimeIndex([next_ref]), series_id)[0]
    return business_days_late(expected, as_of=as_of)


def classify_freshness(periodicity: str, business_days_late: int) -> str:
    """`"ok"` si `business_days_late` reste dans la fenêtre normale de
    publication de cette périodicité, `"warning"` au-delà -- voir
    `PERIODICITY_ALERT_THRESHOLD_BDAYS` pour la justification de chaque
    seuil."""
    threshold = PERIODICITY_ALERT_THRESHOLD_BDAYS[periodicity]
    return "warning" if business_days_late > threshold else "ok"


def _store_key(symbol: str) -> str:
    """Reproduit EXACTEMENT la convention de `data/ingest.py::ingest()`
    (`cache_key = f"raw_{objective.target_symbol}"`) -- c'est la seule clé
    sous laquelle un ticker donné peut avoir été sauvegardé dans le data
    lake (voir la limite d'architecture documentée en tête de module)."""
    return f"raw_{symbol}"


@dataclass(frozen=True)
class FreshnessResult:
    symbol: str
    label: str
    source: str            # "yfinance" | "fred"
    periodicity: str       # "daily" | "weekly" | "monthly" | "quarterly"
    cached: bool
    date_max: str | None
    business_days_late: int | None
    state: str             # "ok" | "warning" | "disabled"


def compute_freshness(symbol: str, label: str, source: str,
                       store: DataStore | None = None, as_of=None) -> FreshnessResult:
    """Fraîcheur d'un seul ticker/série, lue UNIQUEMENT depuis le data lake
    local (`store.list_snapshots`, donc `_index.json`) -- jamais de requête
    yfinance/FRED. Si la clé `raw_{symbol}` n'a aucun snapshot, l'état est
    `"disabled"` (jamais mis en cache) : un état vide explicite, pas une
    erreur -- voir le docstring du module."""
    store = store or DataStore()
    periodicity = fred_periodicity(symbol) if source == "fred" else "daily"
    snapshots = store.list_snapshots(_store_key(symbol))
    dated_snapshots = [s for s in snapshots if s.get("date_max")]

    # Dernière observation réellement publiée de la série, enregistrée à
    # chaque ingestion (`DataStore.record_series_observations`) -- la seule
    # source pour une série qui n'a jamais été elle-même une cible.
    observed = store.series_observation(symbol)
    candidates = [s["date_max"][:10] for s in dated_snapshots]
    if observed and observed.get("date_max"):
        candidates.append(observed["date_max"])
    if not candidates:
        return FreshnessResult(symbol=symbol, label=label, source=source,
                                periodicity=periodicity, cached=False,
                                date_max=None, business_days_late=None, state="disabled")

    # Plusieurs snapshots (contenus différents, cf. `store.py`) peuvent
    # coexister pour une même clé -- on retient la donnée la PLUS RÉCENTE
    # jamais vue, pas nécessairement le dernier snapshot ajouté à l'index.
    date_max = max(candidates)
    if source == "fred":
        late = fred_business_days_late(symbol, date_max, periodicity, as_of=as_of)
        state = "warning" if late > FRED_RELEASE_MARGIN_BDAYS[periodicity] else "ok"
    else:
        late = business_days_late(date_max, as_of=as_of)
        state = classify_freshness(periodicity, late)
    return FreshnessResult(symbol=symbol, label=label, source=source,
                            periodicity=periodicity, cached=True,
                            date_max=date_max, business_days_late=late, state=state)


def freshness_overview(store: DataStore | None = None, as_of=None) -> list[dict]:
    """Fraîcheur de tout `DEFAULT_TARGET_GROUPS`, groupée comme le formulaire
    de lancement / `/universe` (même source, `config/defaults.py`) --
    `[{"group": str, "results": [FreshnessResult, ...]}, ...]`."""
    from patrick.config import defaults as D

    store = store or DataStore()
    out = []
    for group, items in D.DEFAULT_TARGET_GROUPS.items():
        source = "fred" if group == D.FRED_TARGET_GROUP else "yfinance"
        results = [compute_freshness(sym, label, source, store=store, as_of=as_of)
                   for sym, label in items]
        out.append({"group": group, "results": results})
    return out
