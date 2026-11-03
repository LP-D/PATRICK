"""Nom de la newsletter -> ligne de cotation. C'est le point le plus fragile : une erreur silencieuse invalide toute l'étude.

Chaîne : (1) table d'alias persistante (`earn_alias`, confirmée par l'utilisateur) -> (2) alias semés (cas ambigus connus) ->
(3) recherche Yahoo, puis (4) ÉCRAN DE CONFIRMATION éditable : rien ne se calcule avant que l'utilisateur ait validé, et une
validation s'inscrit dans la table d'alias (la fois suivante, plus de question).

Ligne par défaut = la ligne LOCALE (la réaction primaire s'y produit) ; l'ADR (certificat coté aux États-Unis représentant
l'action étrangère) sert de contrôle et d'étude de transmission. Un ADR est repéré par : place américaine ET pays émetteur
étranger (`info.country`). Une mention explicite entre parenthèses (« Ryanair (ADR) », « Novo (Copenhague) », « Apple (AAPL) »)
l'emporte sur le défaut.

Garde-fous contre l'erreur silencieuse : le nom renvoyé par Yahoo pour le symbole retenu est comparé au nom collé (drapeau
`nom différent`), deux candidats quasi à égalité lèvent `ambigu`, et un alias semé reste à confirmer une première fois.
"""
from __future__ import annotations

import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from patrick.earnings import exchanges, store
from patrick.earnings.parse import ParsedItem

_LEGAL = {"inc", "incorporated", "corp", "corporation", "co", "company", "plc", "sa", "se", "ag", "nv", "spa", "ltd", "limited",
          "llc", "lp", "the", "de", "et", "and", "asa", "ab", "oyj", "as", "a/s", "adr", "ads"}
_SECONDARY = ("mexico", "dusseldorf", "stuttgart", "berlin", "munich", "hamburg", "hanover", "neo", "dxe", "bombay", "otc",
              "pink", "tradegate", "gettex", "frankfurt", "swiss exchange (virt-x)", "buenos", "sao paulo", "santiago", "lima")

# (symbole local, symbole ADR / ligne de contrôle, nom affiché). Semés pour les cas où la recherche textuelle se trompe.
SEED_ALIASES: dict[str, tuple[str, str | None, str]] = {
    "arm": ("ARM", None, "Arm Holdings plc"), "arm holdings": ("ARM", None, "Arm Holdings plc"),
    "block": ("XYZ", None, "Block, Inc."), "figma": ("FIG", None, "Figma, Inc."),
    "amc": ("AMC", None, "AMC Entertainment Holdings"), "amc entertainment": ("AMC", None, "AMC Entertainment Holdings"),
    "amc networks": ("AMCX", None, "AMC Networks"), "leonardo": ("LDO.MI", None, "Leonardo S.p.A."),
    "leonardo drs": ("LDRS", None, "Leonardo DRS"), "diageo": ("DGE.L", "DEO", "Diageo plc"),
    "sharkninja": ("SN", None, "SharkNinja, Inc."), "novo nordisk": ("NOVO-B.CO", "NVO", "Novo Nordisk A/S"),
    "novo": ("NOVO-B.CO", "NVO", "Novo Nordisk A/S"), "ryanair": ("RYA.IR", "RYAAY", "Ryanair Holdings plc"),
    "air france-klm": ("AF.PA", None, "Air France-KLM SA"), "air france klm": ("AF.PA", None, "Air France-KLM SA"),
    "interparfums": ("ITP.PA", "IPAR", "Interparfums SA (ligne liée : Inter Parfums, Inc.)"),
    "inter parfums": ("IPAR", None, "Inter Parfums, Inc."),
    "berkshire hathaway": ("BRK-B", None, "Berkshire Hathaway Inc."), "berkshire": ("BRK-B", None, "Berkshire Hathaway Inc."),
    "apple": ("AAPL", None, "Apple Inc."), "palantir": ("PLTR", None, "Palantir Technologies"),
    "amd": ("AMD", None, "Advanced Micro Devices"), "advanced micro devices": ("AMD", None, "Advanced Micro Devices"),
    "qualcomm": ("QCOM", None, "Qualcomm Inc."), "microsoft": ("MSFT", None, "Microsoft Corporation"),
    "alphabet": ("GOOGL", None, "Alphabet Inc."), "google": ("GOOGL", None, "Alphabet Inc."), "amazon": ("AMZN", None, "Amazon.com, Inc."),
    "meta": ("META", None, "Meta Platforms"), "meta platforms": ("META", None, "Meta Platforms"), "nvidia": ("NVDA", None, "NVIDIA"),
    "tesla": ("TSLA", None, "Tesla, Inc."), "netflix": ("NFLX", None, "Netflix, Inc."), "oklo": ("OKLO", None, "Oklo Inc."),
    "sap": ("SAP.DE", "SAP", "SAP SE"), "lvmh": ("MC.PA", None, "LVMH Moët Hennessy Louis Vuitton"),
    "airbus": ("AIR.PA", None, "Airbus SE"), "totalenergies": ("TTE.PA", "TTE", "TotalEnergies SE"),
    "asml": ("ASML.AS", "ASML", "ASML Holding N.V."), "shell": ("SHEL.L", "SHEL", "Shell plc"), "bp": ("BP.L", "BP", "BP p.l.c."),
    "hsbc": ("HSBA.L", "HSBC", "HSBC Holdings plc"), "unilever": ("ULVR.L", "UL", "Unilever PLC"),
    "astrazeneca": ("AZN.L", "AZN", "AstraZeneca PLC"), "sanofi": ("SAN.PA", "SNY", "Sanofi"),
    "nestle": ("NESN.SW", "NSRGY", "Nestlé S.A."), "roche": ("ROG.SW", "RHHBY", "Roche Holding AG"),
    "siemens": ("SIE.DE", None, "Siemens AG"), "renault": ("RNO.PA", None, "Renault SA"),
    "stellantis": ("STLAP.PA", "STLA", "Stellantis N.V."), "toyota": ("7203.T", "TM", "Toyota Motor Corporation"),
    "sony": ("6758.T", "SONY", "Sony Group Corporation"), "adidas": ("ADS.DE", None, "adidas AG"),
    "schneider electric": ("SU.PA", None, "Schneider Electric SE"), "vinci": ("DG.PA", None, "VINCI SA"),
    "loreal": ("OR.PA", None, "L'Oréal S.A."), "hermes": ("RMS.PA", None, "Hermès International"),
    "kering": ("KER.PA", None, "Kering SA"), "danone": ("BN.PA", None, "Danone S.A."), "bnp paribas": ("BNP.PA", None, "BNP Paribas SA"),
}


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def normalize_alias(name: str) -> str:
    """Clé d'alias : minuscules, sans accents ni ponctuation, sans formes juridiques (« Inc. », « plc », « SE »...)."""
    text = re.sub(r"[’'`´./]", "", _fold(name))                # « S.p.A. » -> « spa », « A/S » -> « as », « L'Oréal » -> « loreal »
    text = re.sub(r"[^a-z0-9&+\- ]+", " ", text)
    tokens = [t for t in text.split() if t not in _LEGAL]
    return " ".join(tokens).strip()


def name_similarity(a: str, b: str) -> float:
    """Ressemblance 0..1 entre deux noms de société (après normalisation) : inclusion de jetons ou rapport de séquences."""
    na, nb = normalize_alias(a), normalize_alias(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    contain = len(ta & tb) / min(len(ta), len(tb))
    return max(contain * 0.95 if ta <= tb or tb <= ta else contain * 0.8, SequenceMatcher(None, na, nb).ratio())


def name_matches(pasted: str, yahoo: str) -> bool:
    """Le nom collé désigne-t-il la société que Yahoo associe au symbole ? Chaque mot collé doit se retrouver (au préfixe près pour les mots de 5 lettres et plus : « Arm » n'est pas « Armstrong ») dans le nom
    Yahoo, ou le nom collé être le sigle de ses initiales (AMD / Advanced Micro Devices). Plus strict que `name_similarity`, qui laisserait
    passer « Block » pour « Blackrock » (rapport de séquences 0,71) : l'erreur silencieuse que l'écran de confirmation doit attraper."""
    a, b = normalize_alias(pasted).split(), normalize_alias(yahoo).split()
    if not a or not b:
        return False
    if len(a) == 1 and a[0] == "".join(t[0] for t in b):
        return True
    return all(any(y == x or (min(len(x), len(y)) >= 5 and (y.startswith(x) or x.startswith(y))) for y in b) for x in a)


def _is_secondary(exchange: str) -> bool:
    low = exchange.lower()
    return any(word in low for word in _SECONDARY)


def rank_candidates(name: str, quotes: list[dict]) -> list[dict]:
    """Candidats Yahoo triés : actions d'abord, proches du nom collé, places principales avant places secondaires."""
    out = []
    for q in quotes:
        if not q.get("symbol"):
            continue
        sim = name_similarity(name, q.get("name", ""))
        is_equity = q.get("type") == "EQUITY"
        score = sim * 3 + (1.0 if is_equity else -2.0) + (-1.5 if _is_secondary(q.get("exchange", "")) else 0.0)
        out.append({**q, "similarity": round(sim, 3), "score": round(score, 3), "suffix": exchanges.suffix_of(q["symbol"])})
    return sorted(out, key=lambda c: -c["score"])


def _label_adr(candidates: list[dict], provider, limit: int = 4) -> None:
    """Marque `is_adr` sur les meilleurs candidats : place américaine ET pays émetteur étranger (un appel `info` chacun)."""
    top = [c for c in candidates[:limit] if c.get("type") == "EQUITY"]

    def one(c):
        info = provider.info(c["symbol"]) if provider else {}
        c["country"] = info.get("country", "")
        c["yahoo_name"] = info.get("longName") or info.get("shortName") or c.get("name", "")
        c["is_adr"] = bool(c["suffix"] == "" and c["country"] and c["country"] != "United States")
        c["currency"] = info.get("currency", "")

    with ThreadPoolExecutor(max_workers=min(4, max(len(top), 1))) as pool:
        list(pool.map(one, top))
    for c in candidates:
        c.setdefault("is_adr", False)


def pick_lines(name: str, candidates: list[dict], item: ParsedItem | None = None) -> tuple[str | None, str | None, list[str]]:
    """(ligne locale, ligne de contrôle ADR, drapeaux) parmi des candidats déjà classés et marqués `is_adr`."""
    flags: list[str] = []
    equities = [c for c in candidates if c.get("type") == "EQUITY"]
    if not equities:
        return None, None, ["aucune action trouvée"]
    locals_ = [c for c in equities if not c.get("is_adr")]
    adrs = [c for c in equities if c.get("is_adr")]
    listing = item.listing_hint if item else ""
    if listing and listing not in ("adr", "us", "local"):
        wanted = [c for c in equities if c["suffix"].lower() == listing]
        if wanted:
            locals_ = wanted + [c for c in locals_ if c not in wanted]
    local = (locals_ or equities)[0]
    adr = next((c for c in adrs if c["symbol"] != local["symbol"]), None)
    if listing in ("adr", "us") and adr is not None:
        local, adr = adr, local if local["symbol"] != adr["symbol"] else None
    ranked = [c for c in equities if c["similarity"] >= 0.5]
    if len(ranked) >= 2 and abs(ranked[0]["score"] - ranked[1]["score"]) < 0.3 and ranked[0]["suffix"] == ranked[1]["suffix"]:
        flags.append("ambigu")
    if local["similarity"] < 0.6:
        flags.append("nom différent")
    if adr is not None or len({c["suffix"] for c in ranked}) > 1:
        flags.append("plusieurs lignes")
    return local["symbol"], (adr["symbol"] if adr else None), flags


def resolve_one(conn, item: ParsedItem, provider) -> dict:
    alias = normalize_alias(item.name)
    base = {"day_index": item.day_index, "plan_date": item.plan_date.isoformat(), "name": item.name, "alias": alias,
            "hint": item.hint, "timing_override": item.timing_hint or None, "candidates": [], "flags": []}
    if item.symbol_hint:
        return {**base, "symbol": item.symbol_hint, "adr_symbol": None, "status": "pending", "flags": ["symbole indiqué"]}
    saved = store.get_alias(conn, alias)
    if saved and saved["source"] == "user":
        symbol, adr = saved["symbol"], saved["adr_symbol"]
        if item.listing_hint in ("adr", "us") and adr:
            symbol, adr = adr, symbol
        return {**base, "symbol": symbol, "adr_symbol": adr, "status": "confirmed", "flags": ["alias confirmé"]}
    if alias in SEED_ALIASES:
        symbol, adr, _display = SEED_ALIASES[alias]
        if item.listing_hint in ("adr", "us") and adr:
            symbol, adr = adr, symbol
        return {**base, "symbol": symbol, "adr_symbol": adr, "status": "pending", "flags": ["alias semé : à confirmer"]}
    quotes = provider.search(item.name, 8) if provider else []
    candidates = rank_candidates(item.name, quotes)
    if not candidates:
        return {**base, "symbol": None, "adr_symbol": None, "status": "pending", "flags": ["introuvable"]}
    _label_adr(candidates, provider)
    symbol, adr, flags = pick_lines(item.name, candidates, item)
    return {**base, "symbol": symbol, "adr_symbol": adr, "status": "pending", "flags": flags,
            "candidates": [{k: c.get(k) for k in ("symbol", "name", "exchange", "type", "is_adr", "similarity", "country")}
                           for c in candidates[:8]]}


def check_names(rows: list[dict], provider) -> None:
    """Compare le nom collé à celui que Yahoo associe au symbole retenu (drapeau `nom différent`) : attrape un alias
    erroné ou périmé (ticker changé) avant qu'il ne fausse l'étude."""
    todo = [r for r in rows if r.get("symbol") and not any(f in ("nom différent", "introuvable") for f in r["flags"])]

    def one(r):
        info = provider.info(r["symbol"])
        r["yahoo_name"] = info.get("longName") or info.get("shortName") or ""
        if r["yahoo_name"]:
            r["flags"].append(f"Yahoo : {r['yahoo_name']}")
            if not name_matches(r["name"], r["yahoo_name"]) and "nom différent" not in r["flags"]:
                r["flags"].append("nom différent")
        else:
            r["flags"].append("symbole inconnu de Yahoo")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, todo))


def resolve_all(conn, items: list[ParsedItem], provider, progress=None) -> list[dict]:
    rows = []
    for i, item in enumerate(items):
        rows.append(resolve_one(conn, item, provider))
        if progress:
            progress(i + 1, len(items))
    if provider:
        check_names(rows, provider)
    return rows


def confirm_item(conn, row: dict, symbol: str, adr_symbol: str | None = None) -> None:
    """Valide une ligne : mémorise l'alias (source `user`) pour ne plus poser la question."""
    store.put_alias(conn, row["alias"], symbol.strip(), (adr_symbol or "").strip() or None, row.get("name"), source="user")
