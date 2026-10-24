"""Affichage des instruments : le NOM à la place du symbole (ticker), partout dans l'interface.

Le symbole (`^GSPC`, `AAPL`, `GC=F`) reste l'identifiant des données, des URL, des runs et des API ; seul ce que la page montre change.
Les noms viennent de `config/instrument_names.py` (les 528 cibles et les séries macro), puis d'un cache local de noms appris
(`~/.patrick/instrument_names.json`, rempli en arrière-plan pour les autres symboles : actifs du patrimoine, tickers saisis dans la
simulation). Règle d'affichage :
  - une société ou un fonds coté (ETF) : son nom seul                         -> « Apple », « SPDR Gold Shares »
  - tout le reste (future, CFD, indice, devise, crypto, taux, série macro) : le genre d'abord
        -> « Future · Or », « CFD · Apple », « Indice · S&P 500 », « Devise · EUR/USD », « Crypto · Bitcoin »
  - un contrat à terme du fonds (`ESZ26.CME`) : le produit du catalogue et l'échéance   -> « Future · E-mini S&P 500 · déc. 2026 »
  - une cible alpha (`AAPL__alpha_^GSPC`) : l'actif puis son benchmark                  -> « Apple · α vs S&P 500 »
  - un symbole inconnu : déduit de sa forme (`=F` future, `=X` devise, `-USD` crypto, `^` indice), sinon le symbole lui-même
    (jamais une valeur inventée, jamais un blanc) ; il est mis en file pour apprendre son nom.
La langue est celle de la requête (`i18n.request_lang()`), comme `ui_t` : utilisable dans un filtre Jinja, un macro importé ou un message
construit côté serveur. Le genre peut être imposé (`kind="cfd"` : une position CFD sur Apple s'affiche « CFD · Apple »).
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time

from markupsafe import Markup, escape

from patrick import paths
from patrick.config.instrument_names import INSTRUMENTS
from patrick.config.target_label import split_run_label
from patrick.webapp import i18n

log = logging.getLogger("patrick.instruments")

# Genre -> clé i18n du mot placé devant le nom (société et ETF : aucun).
KIND_LABEL_KEYS = {
    "future": "inst_kind_future", "cfd": "inst_kind_cfd", "index": "inst_kind_index", "vol": "inst_kind_vol",
    "fx": "inst_kind_fx", "crypto": "inst_kind_crypto", "rate": "inst_kind_rate", "macro": "inst_kind_macro",
}
# Type Yahoo (`quoteType`) -> genre.
_QUOTE_KINDS = {"EQUITY": "stock", "ETF": "etf", "MUTUALFUND": "etf", "FUTURE": "future", "CURRENCY": "fx",
                "CRYPTOCURRENCY": "crypto", "INDEX": "index"}
_SYMBOL_SHAPE = re.compile(r"^[A-Za-z0-9^][A-Za-z0-9.=^_\-]{0,22}$")      # ce qui peut raisonnablement être un symbole boursier
_CONTRACT_RE = re.compile(r"^([A-Z0-9]+?)([FGHJKMNQUVXZ])(\d{2})\.(?:CME|CBT|NYM|CMX)$")
_MONTH_BY_CODE = {c: m for m, c in {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}.items()}
_MONTHS = {"fr": ("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."),
           "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")}

# ------------------------------------------------------------------------------------------------------ noms appris
_learned: dict[str, tuple[str, str]] = {}          # symbole -> (genre, nom), lu dans le fichier au premier besoin
_loaded = False
_pending: set[str] = set()
_tried: set[str] = set()                           # une seule tentative par symbole et par processus
_lock = threading.Lock()
_worker: threading.Thread | None = None


def lookup_enabled() -> bool:
    """Faux dans les tests (`PATRICK_INSTRUMENT_LOOKUP=0`) : aucune requête réseau ne part d'un affichage."""
    return os.environ.get("PATRICK_INSTRUMENT_LOOKUP", "1") != "0"


def _store_path():
    return paths.home_dir() / "instrument_names.json"


def _load() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        _loaded = True
        try:
            raw = json.loads(_store_path().read_text(encoding="utf-8"))
            for symbol, pair in raw.items():
                if isinstance(pair, list) and len(pair) == 2 and all(isinstance(x, str) for x in pair):
                    _learned[symbol] = (pair[0], pair[1])
        except (OSError, ValueError):
            pass                                    # pas encore de fichier, ou fichier illisible : on repart de zéro


def _save() -> None:
    try:
        target = _store_path()
        tmp = target.with_suffix(".json.part")
        tmp.write_text(json.dumps({s: list(p) for s, p in sorted(_learned.items())}, ensure_ascii=False, indent=0), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        log.debug("noms d'instruments : écriture impossible", exc_info=True)


def _fetch_name(symbol: str) -> tuple[str, str] | None:
    """(genre, nom) d'un symbole d'après Yahoo, ou None."""
    import yfinance as yf

    info = yf.Ticker(symbol).info or {}
    name = (info.get("longName") or info.get("shortName") or "").strip()
    if not name:
        return None
    return _QUOTE_KINDS.get(str(info.get("quoteType") or "").upper(), "stock"), name


def _run_worker() -> None:
    global _worker
    while True:
        with _lock:
            if not _pending:
                _worker = None
                return
            symbol = _pending.pop()
        try:
            found = _fetch_name(symbol)
        except Exception:  # noqa: BLE001 -- frontière fournisseur : un échec ne casse jamais un affichage
            found = None
        if found:
            with _lock:
                _learned[symbol] = found
            _save()
        time.sleep(0.4)                             # poli avec Yahoo : un symbole à la fois


def request_names(symbols) -> None:
    """Met en file les symboles dont le nom est inconnu ; un fil d'arrière-plan les apprend (sans jamais bloquer la page)."""
    global _worker
    if not lookup_enabled():
        return
    _load()
    with _lock:
        todo = {s for s in symbols if s and s not in INSTRUMENTS and s not in _learned and s not in _tried
                and "__alpha_" not in s and not _CONTRACT_RE.match(s) and _SYMBOL_SHAPE.match(s)}
        if not todo:
            return
        _tried.update(todo)
        _pending.update(todo)
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, name="instrument-names", daemon=True)
            _worker.start()


# --------------------------------------------------------------------------------------------------- noms et genres
def _guess(symbol: str) -> tuple[str, str] | None:
    """(genre, nom) déduits de la forme d'un symbole absent du registre ; None si rien d'évident."""
    if symbol.endswith("=F"):
        return "future", symbol
    if symbol.endswith("=X"):
        base = symbol[:-2]
        if len(base) == 6 and base.isalpha():
            return "fx", f"{base[:3]}/{base[3:]}"
        if len(base) == 3 and base.isalpha():
            return "fx", f"USD/{base}"
        return "fx", symbol
    if symbol.endswith("-USD") and symbol[:-4].isalnum():
        return "crypto", symbol[:-4]
    if symbol.startswith("^"):
        return "index", symbol
    return None


def _contract(symbol: str, lang: str) -> tuple[str, str] | None:
    """(« future », « E-mini S&P 500 · déc. 2026 ») pour un contrat à terme du fonds (`ESZ26.CME`), si son produit est au catalogue."""
    match = _CONTRACT_RE.match(symbol)
    if not match:
        return None
    try:
        from patrick.fund.instruments import FUTURES_CATALOG
    except ImportError:
        return None
    root, code, yy = match.groups()
    spec = FUTURES_CATALOG.get(root)
    if spec is None:
        return None
    month = _MONTH_BY_CODE[code]
    return "future", f"{spec.name} · {_MONTHS['en' if lang == 'en' else 'fr'][month - 1]} 20{yy}"


def _bare(symbol: str, lang: str) -> tuple[str | None, str]:
    entry = INSTRUMENTS.get(symbol)
    if entry:
        return entry[0], entry[2] if lang == "en" else entry[1]
    contract = _contract(symbol, lang)
    if contract:
        return contract
    _load()
    learned = _learned.get(symbol)
    if learned:
        return learned
    guess = _guess(symbol)
    request_names([symbol])
    return guess if guess else (None, symbol)


def _plain(symbol: str) -> str:
    """Certaines listes (`list_all_runs`) livrent des cibles déjà échappées pour le HTML : on les défait avant la recherche,
    l'affichage les échappe de nouveau une seule fois."""
    return html.unescape(symbol) if "&" in symbol else symbol


def kind_of(symbol: str | None) -> str | None:
    """Genre d'un symbole (`stock`, `etf`, `future`…), ou None s'il est inconnu et sans forme reconnaissable."""
    return _bare(symbol, "fr")[0] if symbol else None


def name_of(symbol: str | None, lang: str | None = None) -> str:
    """Le nom seul, sans genre (« S&P 500 ») ; le symbole lui-même s'il est inconnu."""
    if not symbol:
        return ""
    return _bare(split_run_label(_plain(symbol))[0], lang or i18n.request_lang())[1]


def display(symbol: str | None, lang: str | None = None, kind: str | None = None) -> str:
    """Ce que l'interface montre pour un symbole ou une étiquette de cible (alpha comprise) : cf. l'en-tête du module.
    `kind` impose le genre (position CFD ou future du fonds), quel que soit celui du sous-jacent."""
    if not symbol:
        return ""
    symbol = _plain(symbol)
    lang = lang or i18n.request_lang()
    t = i18n.translator(lang)
    base, mode, bench = split_run_label(symbol)
    if mode == "alpha":
        return f"{display(base, lang, kind)} · {t('inst_alpha_vs', bench=name_of(bench, lang))}"
    found_kind, name = _bare(symbol, lang)
    key = KIND_LABEL_KEYS.get(kind or found_kind or "")
    if key is None:
        return name                                 # société, ETF ou genre inconnu : le nom seul
    prefix = t(key)
    return name if name.startswith(prefix + " · ") else f"{prefix} · {name}"


def display_instrument(instrument: dict | None, lang: str | None = None) -> str:
    """Instrument d'une règle du fonds : `{kind, symbol}` (action, ETF, CFD) ou `{kind: "future", spec: {root}}` (produit du catalogue)."""
    if not instrument:
        return ""
    kind, symbol = instrument.get("kind"), instrument.get("symbol")
    if symbol:
        return display(symbol, lang, kind)
    root = (instrument.get("spec") or {}).get("root")
    if not root:
        return ""
    try:
        from patrick.fund.instruments import FUTURES_CATALOG
    except ImportError:
        return root
    spec = FUTURES_CATALOG.get(root)
    prefix = i18n.translator(lang or i18n.request_lang())("inst_kind_future")
    return f"{prefix} · {spec.name}" if spec else f"{prefix} · {root}"


def display_html(symbol: str | None, lang: str | None = None, kind: str | None = None) -> str:
    """Comme `display`, échappé pour le HTML mais rendu en `str` ordinaire : à utiliser dans les cellules assemblées par concaténation
    (`'<a …>' ~ (symbole | iname_h) ~ '</a>'`), qui passent ensuite `| safe`. Un `| e` en ferait un `Markup` qui échapperait le reste."""
    return str(escape(display(symbol, lang, kind)))


def display_with_tip(symbol: str | None, lang: str | None = None, kind: str | None = None) -> Markup:
    """Comme `display`, dans un `<span title="symbole">` : le symbole reste lisible au survol (HTML échappé)."""
    if not symbol:
        return Markup("")
    symbol = _plain(symbol)
    text = display(symbol, lang, kind)
    if text == symbol:
        return Markup(escape(text))
    return Markup('<span class="instr" title="{}">{}</span>').format(symbol, text)


def names_for_browser(lang: str) -> dict[str, str]:
    """`symbole -> affichage` pour les scripts de la page (`window.PatrickNames`) : le registre entier puis les noms appris."""
    _load()
    out = {symbol: display(symbol, lang) for symbol in INSTRUMENTS}
    out.update({symbol: display(symbol, lang) for symbol in list(_learned) if symbol not in out})
    return out
