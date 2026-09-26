"""CHANTIER (feature/equity-asset-class) -- univers "actions individuelles",
volontairement SEPARE de `config/defaults.py::DEFAULT_TARGET_GROUPS` (commo-
dites/macro/indices/devises/crypto) : contrairement a ce dernier,
`EQUITY_UNIVERSE` n'alimente PAS `DEFAULT_UNIVERSE_YF_TICKERS` (l'univers de
features par defaut de CHAQUE run, `webapp/forms.py::universe_excluding`).
Une action individuelle reste donc uniquement une CIBLE possible (ajoutee au
selecteur `/launch` par `webapp/forms.py`, voir son en-tete), jamais une
feature injectee silencieusement dans un run predisant le VIX, l'or ou
n'importe quel autre actif existant -- c'est le point explicite de cette
separation (README de la session : "nouvelle table/config ... separee de
l'univers commo/macro existant").

Metadonnees par ticker (devise, place de cotation, date de premiere
cotation disponible) : `first_listed` documente la date a partir de
laquelle yfinance renvoie effectivement des donnees pour ce symbole --
mesuree empiriquement (`yf.Ticker(symbol).history(period="max")`, le
2026-09-19), PAS la date d'introduction en bourse historique reelle de la
societe quand celle-ci est anterieure (cas de TTE.PA/HO.PA : Yahoo Finance
ne remonte pas au-dela du 2000-01-03 pour ces deux places, alors que Total
et Thales cotent depuis bien plus longtemps -- limite de la source de
donnees, pas de l'entreprise). Pour D.A.T.E (IPO a venir), `first_listed`
est au contraire une date CONNUE a l'avance (communiquee par l'emetteur/
Euronext), puisqu'aucune donnee n'existe encore.
"""
from __future__ import annotations

# Nom de groupe reutilise tel quel (pas un nouveau libelle) : c'est le nom
# HISTORIQUE du groupe "Actions individuelles" retire lors de la reduction
# d'univers (voir `config/defaults.py::DEFAULT_TARGET_GROUPS`, commentaire de
# tete), pour lequel une traduction i18n existe deja
# (`webapp/i18n.py::TARGET_GROUP_LABEL_KEYS["Actions individuelles"] =
# "group_stocks"`, deja traduite en anglais "Individual stocks") -- aucune
# nouvelle clef i18n a ajouter.
EQUITY_TARGET_GROUP = "Actions individuelles"

# Ticker D.A.T.E confirme via recherche web (Zonebourse/Boursorama,
# 2026-09-19) : mnemonique ALDAT, ISIN FR0014018PW8, Euronext Growth Paris,
# premiere cotation annoncee le 2026-09-25. Le suffixe ".PA" (convention
# Yahoo Finance pour Euronext Paris/Growth Paris) n'est PAS encore
# confirmable empiriquement aupres de yfinance avant cette date (verifie le
# 2026-09-19 : `yf.Ticker("ALDAT.PA")` renvoie une erreur 404 "Quote not
# found", pas juste une serie vide -- comportement ATTENDU pour un titre pas
# encore cote, a reverifier apres le 2026-09-25).
EQUITY_UNIVERSE: dict[str, dict] = {
    "TTE.PA": {
        "label": "TotalEnergies",
        "currency": "EUR",
        "exchange": "Euronext Paris",
        "first_listed": "2000-01-03",
    },
    "HO.PA": {
        "label": "Thales",
        "currency": "EUR",
        "exchange": "Euronext Paris",
        "first_listed": "2000-01-03",
    },
    "AMZN": {
        "label": "Amazon",
        "currency": "USD",
        "exchange": "NASDAQ",
        "first_listed": "1997-05-15",
    },
    "ALDAT.PA": {
        "label": "D.A.T.E",
        "currency": "EUR",
        "exchange": "Euronext Growth Paris",
        "first_listed": "2026-09-25",
        # Roadmap bloc 4 -- pas d'historique : risque estime via un proxy
        # (tracking/covariance.py::backfill_with_proxy). Verifie le
        # 2026-09-25 : ALDAT.PA ne renvoie encore aucune cotation ; aucun
        # indice petites valeurs sur Yahoo (^CACS, ^CACMS : 404) -- ^FCHI
        # (CAC 40) est le proxy disponible. Multiplicateur de volatilite
        # A PRIORI (petite capitalisation vs grand indice), remplace par
        # l'estimation sur le chevauchement des 20 premieres seances.
        "proxy": "^FCHI",
        "proxy_vol_multiplier": 2.0,
    },
}


def equity_target_choices() -> list[tuple[str, str, str]]:
    """(symbole, libelle, source) pour chaque action -- meme forme que
    `config.defaults.DEFAULT_TARGET_CHOICES`, source toujours "yfinance"
    (aucune action de cet univers n'est une serie FRED)."""
    return [(sym, meta["label"], "yfinance") for sym, meta in EQUITY_UNIVERSE.items()]


def history_proxies() -> dict[str, tuple[str, float | None]]:
    """{symbol: (proxy symbol, prior vol multiplier)} for assets declared
    without enough history (roadmap bloc 4)."""
    return {sym: (meta["proxy"], meta.get("proxy_vol_multiplier"))
            for sym, meta in EQUITY_UNIVERSE.items() if meta.get("proxy")}


def is_equity_symbol(symbol: str) -> bool:
    return symbol in EQUITY_UNIVERSE
