"""Per-asset-class time alignment (Phase 0.4): this project's DataFrames are
indexed by CALENDAR DATE (daily yfinance bars), with no close timestamp — a
"same date" join implicitly treats a Tokyo close (~08:00 UTC) and a New York
close (~20:00-21:00 UTC) of the same calendar day as simultaneous. This is
correct in one direction (Tokyo closes before New York the same day, using it
as a "same-day" feature for a US target is legitimate) but wrong in the
other: a feature whose "same-day" close happens AFTER the target's close
contains information not yet available at decision time.

Without real intraday timestamps (out of reach with daily yfinance bars —
getting them would require migrating the entire ingestion to hourly data,
out of scope here), the fix applied is a one-business-day shift: any feature
whose asset class closes (approximate UTC hour) AFTER the target's is
delayed by one bar before being joined — i.e. on date D, the feature used is
its value known as of D-1 (already fully elapsed before the target's close),
not its "same-day" value (not yet known). A documented approximation, better
than no alignment at all, but not equivalent to a true intraday as-of join.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

# Approximate UTC close hour per asset class (0-24 scale, latest value of the
# class — conservative: when in doubt, assume a late close, which delays MORE
# features rather than fewer, at the cost of some freshness, never at the
# cost of leaking information).
CLOSE_UTC_HOUR = {
    "crypto": 24.0,           # 24/7, the "same-day" bar is only complete at the end of the UTC day
    "fx": 22.0,                # NY close convention ~5pm ET
    "futures": 21.0,           # CME/ICE settlement, late US afternoon
    "equities_us": 20.0,       # NYSE/NASDAQ ~4pm ET
    "volatility_index": 20.0,  # VIX & related, quoted on the same session as US indices
    "equities_americas_other": 21.0,
    "equities_europe": 16.5,   # Paris/Frankfurt/London ~16:30-17:30 UTC
    "equities_asia_pacific": 8.0,   # Tokyo/HK/Shanghai/Sydney, the earliest
    "macro": 24.0,              # FRED series used as a direct target (not yfinance)
    "other": 24.0,              # unknown -> treated as the latest (conservative)
}

_EU_SUFFIXES = (".PA", ".DE", ".AS", ".BR", ".MI", ".MC", ".LS", ".VI", ".L",
                ".IR", ".SW", ".ST", ".HE", ".CO", ".OL")
_ASIA_SUFFIXES = (".HK", ".T", ".SS", ".SZ", ".KS", ".TW", ".SI", ".JK", ".KL",
                   ".BO", ".NS", ".AX", ".NZ")
_AMERICAS_OTHER_SUFFIXES = (".SA", ".MX", ".TO", ".BA")

# Indices ("^"-prefixed) classified individually (the suffix alone isn't
# enough to distinguish their region) — not exhaustive: any absent index
# falls back to "other" (conservative handling, see CLOSE_UTC_HOUR["other"]).
_VOLATILITY_INDICES = ("^VIX", "^VIX3M", "^VVIX", "^VXN", "^OVX", "^GVZ", "^EVZ", "^VIX9D", "^VXD", "^MOVE", "^SKEW")

# Indices de TAUX : la valeur est un rendement en % (^TNX = 10 ans), pas un prix.
_YIELD_INDICES = ("^IRX", "^FVX", "^TNX", "^TYX")

_INDEX_REGION = {
    "^GSPC": "equities_us", "^DJI": "equities_us", "^IXIC": "equities_us",
    "^RUT": "equities_us", "^NYA": "equities_us", "^XAX": "equities_us", "^SOX": "equities_us", "^DJT": "equities_us",
    "^FCHI": "equities_europe", "^GDAXI": "equities_europe", "^FTSE": "equities_europe",
    "^STOXX50E": "equities_europe", "^IBEX": "equities_europe", "^N100": "equities_europe",
    "^BFX": "equities_europe", "^AEX": "equities_europe", "^SSMI": "equities_europe",
    "^HSI": "equities_asia_pacific", "^N225": "equities_asia_pacific",
    "^AXJO": "equities_asia_pacific", "^AORD": "equities_asia_pacific",
    "^BSESN": "equities_asia_pacific", "^NSEI": "equities_asia_pacific",
    "^KS11": "equities_asia_pacific", "^TWII": "equities_asia_pacific",
    "^STI": "equities_asia_pacific", "^JKSE": "equities_asia_pacific",
    "^KLSE": "equities_asia_pacific", "^NZ50": "equities_asia_pacific",
    "000001.SS": "equities_asia_pacific",
    "^BVSP": "equities_americas_other", "^MXX": "equities_americas_other",
    "^MERV": "equities_americas_other", "^GSPTSE": "equities_americas_other",
    "DX-Y.NYB": "fx",
}


def untradable_kind(symbol: str, source: str = "yfinance") -> str | None:
    """Pourquoi la série de `symbol` ne donne pas un P&L réalisable si on la traite comme un prix négociable, ou None.
    `volatility` : indice de volatilité (^VIX, ^VVIX, ^MOVE, ^SKEW...), qui ne se négocie que par des contrats à terme ou des produits cotés
    à report négatif, sans suivre l'indice ; `yield` : indice de taux (^TNX...), un rendement en %, pas un prix."""
    if source != "yfinance":
        return None
    if symbol in _VOLATILITY_INDICES:
        return "volatility"
    if symbol in _YIELD_INDICES:
        return "yield"
    return None


def classify_asset_class(symbol: str, source: str = "yfinance") -> str:
    """Asset class of a yfinance symbol, by ticker pattern — deliberately
    simple heuristic (no dependency on an external reference database).
    `source == "fred"`: macro series used as a direct target (Phase X5,
    baseline selection by asset class) -- distinct from "other" so it can be
    assigned the random-walk-with-drift baseline rather than the default,
    more conservative one."""
    if source == "fred":
        return "macro"
    if source != "yfinance":
        return "other"
    if symbol in _VOLATILITY_INDICES:
        return "volatility_index"
    if symbol in _INDEX_REGION:
        return _INDEX_REGION[symbol]
    if symbol.endswith(("-USD", "-USDT", "-USDC")):
        return "crypto"
    if symbol.endswith("=X"):
        return "fx"
    if symbol.endswith("=F"):
        return "futures"
    if symbol.endswith(_EU_SUFFIXES):
        return "equities_europe"
    if symbol.endswith(_ASIA_SUFFIXES):
        return "equities_asia_pacific"
    if symbol.endswith(_AMERICAS_OTHER_SUFFIXES):
        return "equities_americas_other"
    if symbol.startswith("^"):
        return "other"
    if "." not in symbol:
        return "equities_us"
    return "other"


# Règle d'alignement des cibles de change (`ObjectiveConfig.session_rule`, ADR 0007). 1 = règle d'origine (barre `=X` supposée
# clôturer à 22 h UTC), conservée pour tout run enregistré avant le champ. 2 = une barre Yahoo `=X` datée d porte le cours du
# DÉBUT de la journée d, pas de sa clôture : Brexit (chute de la livre le ven. 24/06/2016) lu à la date du lun. 27/06, choc du
# franc suisse (jeu. 15/01/2015) lu à la date du ven. 16/01, yen du Brexit à la date du 27/06. Le rendement d'un label `=X`
# daté d (prix d+1 / prix d) est donc le mouvement réel de la journée d : toute série cotée à sa vraie date (or, S&P 500...)
# dont la clôture du jour d est « connue » à la ligne d recouvre le label. Placebo EURUSD h=1 : exactitude 70,8 % -> 45,8 %
# et AUC 0,69 -> 0,51 quand les variables sont retardées d'un jour de plus.
CURRENT_SESSION_RULE = 2


def is_yahoo_fx_pair(symbol: str, source: str = "yfinance") -> bool:
    return source == "yfinance" and symbol.endswith("=X")


def session_rule_tag(target_symbol: str, target_source: str, session_rule: int) -> str:
    """Suffixe de la version de cache d'un snapshot brut (`data/ingest.py`) : seule une cible de change sous la règle 2 est
    construite autrement ; toute autre cible garde la version (et donc les snapshots) d'avant."""
    if session_rule >= 2 and is_yahoo_fx_pair(target_symbol, target_source):
        return ":fx-start-of-day"
    return ""


# Clôture américaine des séries FRED quotidiennes de marché (VIXCLS, VXNCLS, écarts de crédit ICE BofA, anticipations d'inflation...) :
# en mode ALFRED la première publication tombe le soir même, donc la valeur du jour d est « connue » à la ligne d.
FRED_MARKET_CLOSE_UTC_HOUR = 20.0


def target_close_hour(target_symbol: str, target_source: str, rule: int = 1) -> float:
    """Heure UTC (0-24) à laquelle une ligne de cette cible est « décidée » : la clôture de sa classe, ou le début de journée
    d'une paire `=X` sous la règle 2."""
    if rule >= 2 and is_yahoo_fx_pair(target_symbol, target_source):
        return 1.0
    return CLOSE_UTC_HOUR[classify_asset_class(target_symbol, target_source)]


def session_lag_days(feature_symbol: str, feature_source: str,
                      target_symbol: str, target_source: str, rule: int = 1) -> int:
    """1 if the feature must be delayed by one bar before being joined to the
    target (its "same-day" close happens after the target's -> not yet known
    at decision time), 0 otherwise. Always 0 if the target itself is not
    yfinance (FRED: its own temporal correction is the subject of Phase 0.5,
    not this one — see module docstring).

    `rule >= 2`, cible `=X` : une autre paire `=X` suit la même convention de date (aucun retard) ; toute autre série cotée,
    DXY compris (cours de clôture réel), est retardée d'une barre. Voir `CURRENT_SESSION_RULE`."""
    if target_source != "yfinance":
        return 0
    if rule >= 2 and is_yahoo_fx_pair(target_symbol, target_source):
        return 0 if is_yahoo_fx_pair(feature_symbol, feature_source) else 1
    feature_class = classify_asset_class(feature_symbol, feature_source)
    target_class = classify_asset_class(target_symbol, target_source)
    return 1 if CLOSE_UTC_HOUR[feature_class] > CLOSE_UTC_HOUR[target_class] else 0


def session_close_utc(asset_class: str, session_date: date) -> datetime:
    """Approximate close (UTC) of the session of `session_date` for an asset class -- `CLOSE_UTC_HOUR`, i.e. the late,
    conservative end of the class (a crypto / macro daily bar ends at midnight UTC)."""
    hours = CLOSE_UTC_HOUR.get(asset_class, CLOSE_UTC_HOUR["other"])
    return datetime.combine(session_date, time.min, tzinfo=UTC) + timedelta(hours=hours)


def bar_is_final(asset_class: str, session_date: date, now: datetime) -> bool:
    """True once the daily bar of `session_date` is the session's CLOSE and no longer a price in the making. Yahoo's
    daily bar of a session still running carries the current price: a signal computed from it starts from that price,
    not from the close. `now` must be timezone-aware."""
    return now >= session_close_utc(asset_class, session_date)


# --- Marché ouvert maintenant ? ------------------------------------------------------------------------------------
# Horaires APPROXIMATIFS par classe d'actifs, en heure locale de la place (l'heure d'été est gérée par le fuseau) :
# (fuseau, ouverture, fermeture), lundi au vendredi. Une classe regroupe plusieurs places (Tokyo, Hong Kong, Séoul pour
# l'Asie ; Paris, Francfort, Londres pour l'Europe) : on prend la fenêtre qui les couvre à peu près.
_EXCHANGE_HOURS = {
    "equities_us": ("America/New_York", time(9, 30), time(16, 0)),
    "volatility_index": ("America/New_York", time(9, 30), time(16, 15)),
    "equities_americas_other": ("America/New_York", time(9, 0), time(16, 0)),
    "equities_europe": ("Europe/Paris", time(9, 0), time(17, 30)),
    "equities_asia_pacific": ("Asia/Tokyo", time(9, 0), time(17, 0)),
}
# Une actualisation faite au moins une heure après l'ouverture qui ne trouve toujours pas de barre du jour = séance fériée.
_HOLIDAY_GRACE = timedelta(hours=1)


def market_is_open(asset_class: str, now: datetime) -> bool | None:
    """Le marché est-il ouvert à `now` (aware) d'après les horaires de sa classe ? `None` pour une série sans séance (macro
    FRED, classe inconnue). Les jours fériés ne sont pas connus ici : voir `market_open_now`."""
    from zoneinfo import ZoneInfo

    if asset_class == "crypto":
        return True
    if asset_class in ("macro", "other"):
        return None
    if asset_class in ("fx", "futures"):
        local = now.astimezone(ZoneInfo("America/New_York"))
        weekday, at = local.weekday(), local.time()
        if weekday == 5:                                       # samedi : fermé
            return False
        if weekday == 6:                                       # dimanche : ouverture le soir (17 h devises, 18 h futures)
            return at >= (time(17, 0) if asset_class == "fx" else time(18, 0))
        if weekday == 4:                                       # vendredi : fermeture à 17 h
            return at < time(17, 0)
        # Futures : pause quotidienne 17 h - 18 h (heure de New York)
        return not (asset_class == "futures" and time(17, 0) <= at < time(18, 0))
    zone, opens, closes = _EXCHANGE_HOURS.get(asset_class, _EXCHANGE_HOURS["equities_us"])
    local = now.astimezone(ZoneInfo(zone))
    return local.weekday() < 5 and opens <= local.time() < closes


def market_open_now(asset_class: str, now: datetime, last_bar_date: date | None = None,
                    updated_at: datetime | None = None) -> bool | None:
    """`market_is_open` + jours fériés des places boursières, détectés plutôt que listés : si l'horaire dit « ouvert », que la
    dernière actualisation des cours date d'au moins une heure après l'ouverture du jour et que la dernière barre est
    antérieure à aujourd'hui, la place n'a pas ouvert (férié). Sans actualisation récente, on s'en tient à l'horaire."""
    from zoneinfo import ZoneInfo

    is_open = market_is_open(asset_class, now)
    if not is_open or asset_class not in _EXCHANGE_HOURS or last_bar_date is None or updated_at is None:
        return is_open
    zone, opens, _ = _EXCHANGE_HOURS[asset_class]
    local_now = now.astimezone(ZoneInfo(zone))
    opened_at = datetime.combine(local_now.date(), opens, tzinfo=ZoneInfo(zone))
    if updated_at >= opened_at + _HOLIDAY_GRACE and last_bar_date < local_now.date():
        return False
    return is_open
