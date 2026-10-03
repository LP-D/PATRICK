# Fonds et Simulation — chantier 1 (socle) : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le simulateur de signaux par un ticket d'ordres multi-instruments (action/ETF, future, CFD) rattaché à des stratégies avec capital, enveloppe PEA/CTO, frais et KPI, et transformer « Simulateur patrimoine » en page **Fonds** (`/fonds`, EN « LP Fund »).

**Architecture:** Nouveau paquet `patrick/fund/` piloté par les événements : les ordres sont les seules données stockées, la valeur du portefeuille se recalcule jour par jour (`engine.simulate`, fonctions pures). Les cotations utilisées sont conservées définitivement en base (`fund_price`). La couche web (`webapp/fund_routes.py`) reste mince : l'aperçu d'un ordre est calculé par le serveur (`service.quote`), les pages sont rendues par Jinja avec des fragments HTML échappés.

**Tech Stack:** Python 3.10+ (pandas, numpy, SQLite, yfinance), FastAPI + Jinja2, JavaScript sans dépendance (canvas), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md` (à lire avant de commencer ; ce plan en amende deux points, voir Task 1 et Task 10).

## Global Constraints

- Python `>=3.10` : la CI exécute 3.10, 3.11 et 3.12.
- `ruff check .` (depuis `patrick/`) est **bloquant** en CI et `[tool.ruff.lint].ignore` est vide : aucune violation tolérée, seulement des `# noqa` motivés ligne par ligne.
- Tests rapides seulement : `pytest -m 'not slow'`. **Aucun accès réseau** dans les tests (Yahoo et FRED sont simulés).
- Dates en ISO `YYYY-MM-DD`. Pas de `datetime.now()` / `date.today()` naïfs (règles DTZ de ruff) : utiliser `patrick.clock.utc_today()` ou, dans `patrick/fund`, `service.current_date()`.
- Devise de base : EUR (l'interface n'en propose pas d'autre). Les frais manuels sont saisis en devise de base. Les cotations sont stockées en unités de la devise ISO (les pence `GBp` sont convertis en `GBP` à l'écriture).
- Les cotations utilisées par une stratégie sont conservées définitivement dans `fund_price` (Yahoo retire les contrats expirés).
- Toutes les chaînes d'interface passent par `i18n.STRINGS` en français et en anglais ; clé `nav_fonds` : FR « Fonds », EN « LP Fund ».
- `webapp/nav_registry.py` est la seule source de la navigation ; toute route GET qui n'est pas une page déclarée y figure dans `NON_PAGE_PREFIXES` / `NON_PAGE_ROUTES` (`tests/test_nav_registry.py::test_no_orphan_page_route`).
- Tout texte dynamique rendu côté navigateur passe par `textContent` ; les fragments HTML viennent de gabarits Jinja (échappement automatique).
- Les valeurs de frais, de marge et de spread sont des ordres de grandeur **indicatifs** (spec §8) ; elles vivent dans des constantes nommées (`fund/fees.py`, `fund/instruments.py`).
- Commits en français après un préfixe `feat(fund):` / `test(fund):` / `refactor:` / `docs:`, avec la ligne finale `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Les commandes de ce plan s'exécutent dans Git Bash, depuis le dossier `patrick/` **du worktree** (voir Task 1) ; `PY` désigne le Python du venv du projet.

## Review Focus

Entrées que la spec laisse implicites et que les tests des tâches couvrent :

1. **Ordre antidaté qui rend invalide un ordre postérieur** (ex. un achat daté avant un autre vide le cash) → refusé avec le motif, pas d'écriture (Task 6 `test_validate_replays_the_whole_timeline…`, Task 7 `test_backdated_order_that_breaks_a_later_one_is_refused`).
2. **Date d'exécution qui tombe un week-end ou un jour férié** → exécution à la séance suivante, jour réellement stocké (Task 7 `test_a_date_between_sessions_executes_on_the_next_trading_day`).
3. **Taille impossible** : montant inférieur à une action, quantité fractionnaire de contrats, quantité 0 ou texte → refus avec un motif explicite, jamais un arrondi silencieux (Task 7 `test_sizes_that_cannot_be_traded_are_refused_with_a_reason`).
4. **Symbole inconnu, contrat expiré ou Yahoo hors ligne** → message clair à l'aperçu ; valorisation avec les cotations stockées et mention « hors ligne » (Task 5 `test_prices_are_persisted_and_served_offline…`, Task 7 `test_future_date_unknown_symbol_and_unknown_strategy_are_refused`).
5. **Nom de stratégie contenant du HTML** (`<script>…`) → échappé sur toutes les pages et dans le panneau (Task 9 et Task 10 `test_strategy_names_are_escaped…`).
6. **Stratégie sans aucun ordre, fonds vide, stratégie archivée** → pages et panneau s'affichent sans erreur (Task 7 `test_overview_of_an_empty_fund…`, Task 9 `test_page_without_a_strategy…`, Task 10 `test_panel_for_a_strategy_without_positions`).

---

## Structure des fichiers

| Fichier | Responsabilité |
|---|---|
| `patrick/patrick/tracking/migrations/0029_fund.sql` (créé) | Tables `fund_strategy`, `fund_order`, `fund_price`, `fund_price_meta`. |
| `patrick/patrick/fund/__init__.py` (créé, vide) | Paquet. |
| `patrick/patrick/fund/store.py` (créé) | CRUD des stratégies et des ordres ; validation de la création d'une stratégie. |
| `patrick/patrick/fund/fees.py` (créé) | Estimation reproductible des frais (loi log-normale + commission déterministe). |
| `patrick/patrick/fund/instruments.py` (créé) | Catalogue de futures, règles d'échéance, classes d'actifs et plafonds de levier des CFD. |
| `patrick/patrick/fund/engine.py` (créé) | Rejeu des ordres jour par jour : cash, positions, marge, valeur, P&L. Fonctions pures. |
| `patrick/patrick/fund/prices.py` (créé) | Cotations Yahoo, persistance dans `fund_price`, change, taux de référence, `build_market`. |
| `patrick/patrick/fund/rules.py` (créé) | Règles d'enveloppe et validation chronologique d'un ordre candidat. |
| `patrick/patrick/fund/kpis.py` (créé) | KPI d'une stratégie à partir du résultat du moteur. |
| `patrick/patrick/fund/service.py` (créé) | Aperçu et passage d'ordres, correction, instantanés, vue d'ensemble. |
| `patrick/patrick/webapp/fund_routes.py` (créé) | Pages `/simulate`, `/fonds`, redirection, API `/api/fund/*`. |
| `patrick/patrick/webapp/i18n_fund.py` (créé) | Chaînes FR/EN des deux pages, fusionnées dans `i18n.STRINGS`. |
| `patrick/patrick/webapp/templates/simulate.html` (réécrit), `fonds.html`, `_fund_panel.html` (créés) | Pages et fragment de détail. |
| `patrick/patrick/webapp/static/simulate.js` (réécrit), `fonds.js` (créé) | Interactions. |
| `patrick/patrick/webapp/static/patrick.css` (complété) | Styles `fund-*`. |
| `patrick/scripts/check_fund_catalog.py` (créé) | Contrôle manuel (réseau) du catalogue de futures. |
| `patrick/tests/test_fund_*.py`, `patrick/tests/fund_support.py` (créés) | Tests et cotations factices. |

Modifiés : `app.py`, `wealth_routes.py`, `nav_registry.py`, `icons.py`, `i18n.py`, `wealth.js`, `test_nav_registry.py`, `test_wealth_signal_replay.py`, `test_simulate_webapp.py` (renommé), README/ARCHITECTURE/MASTER. Supprimé : `templates/patrimoine_simulation.html`.

**Écart avec la spec** (assumé, amendé dans la spec par ce plan) : `fund/store.py` s'ajoute au tableau du §4 ; `fund_price` porte une colonne `volume` (volume moyen pour la taille des frais) et une table `fund_price_meta` mémorise la devise et l'heure de la dernière actualisation (§5).

---

### Task 1 : Worktree, migration 0029 et stockage

**Files:**
- Create: `patrick/patrick/tracking/migrations/0029_fund.sql`, `patrick/patrick/fund/__init__.py`, `patrick/patrick/fund/store.py`
- Test: `patrick/tests/test_fund_store.py`
- Modify: `docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md` (amendement §4 et §5)

**Interfaces:**
- Produces (`patrick.fund.store`) : `FundError(ValueError)` ; `WRAPPERS`, `ACTIONS`, `INSTRUMENT_KINDS` ; `new_id(prefix) -> str` ; `create_strategy(conn, name, wrapper, initial_capital, opened_on, base_currency="EUR") -> str` ; `get_strategy(conn, strategy_id) -> dict | None` ; `list_strategies(conn, include_archived=False) -> list[dict]` ; `update_strategy(conn, strategy_id, **fields)` (champs `name`, `archived`) ; `delete_strategy(conn, strategy_id)` ; `insert_order(conn, raw: dict) -> int` ; `update_order(conn, order_id, raw)` ; `get_order(conn, order_id) -> dict | None` ; `list_orders(conn, strategy_id) -> list[dict]` (clé `spec` : dict) ; `delete_position(conn, position_id) -> int`.

- [ ] **Step 1 : Créer le worktree isolé et vérifier l'import**

Le dépôt principal contient des modifications non commitées d'un autre chantier (`app.py`, `i18n.py`…) : tout le travail se fait dans un worktree.

```bash
cd /c/Users/leonp/PATRICK
git worktree add ../PATRICK-fonds -b feature/fonds-socle main
cd ../PATRICK-fonds/patrick
PY=/c/Users/leonp/PATRICK/patrick/.venv/Scripts/python.exe
$PY -c "import patrick; print(patrick.__file__)"
```

Résultat attendu : un chemin sous `PATRICK-fonds\patrick\patrick\__init__.py`. Si le chemin pointe vers `PATRICK\patrick`, lancer toutes les commandes avec `PYTHONPATH=$PWD` en préfixe.

- [ ] **Step 2 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_store.py` :

```python
"""Persistance des stratégies et des ordres (migration 0029)."""
from __future__ import annotations

import pytest

from patrick.fund import store


def _order(strategy_id, **kw):
    base = {"strategy_id": strategy_id, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
            "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0, "price": 700.0,
            "price_source": "market", "currency": "EUR", "fx_rate": 1.0, "fees": 1.0,
            "fees_source": "estimated", "fee_seed": 7, "spec": {"leverage": 5}, "note": None}
    base.update(kw)
    return base


def test_migration_creates_the_fund_tables(conn):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"fund_strategy", "fund_order", "fund_price", "fund_price_meta"} <= tables


def test_create_list_rename_archive_delete_strategy(conn):
    sid = store.create_strategy(conn, "  Macro CTO ", "CTO", "100 000,50", "2026-01-05")
    s = store.get_strategy(conn, sid)
    assert s["name"] == "Macro CTO" and s["wrapper"] == "CTO" and s["initial_capital"] == 100_000.5
    assert s["base_currency"] == "EUR" and s["archived"] == 0
    other = store.create_strategy(conn, "Actions PEA", "PEA", 50_000, "2026-02-02")
    assert [x["strategy_id"] for x in store.list_strategies(conn)] == [sid, other]
    store.update_strategy(conn, sid, name="Macro 2", archived=1)
    assert store.get_strategy(conn, sid)["name"] == "Macro 2"
    assert [x["strategy_id"] for x in store.list_strategies(conn)] == [other]
    assert len(store.list_strategies(conn, include_archived=True)) == 2
    store.delete_strategy(conn, sid)
    assert store.get_strategy(conn, sid) is None


@pytest.mark.parametrize("args, message", [
    (("", "CTO", 1000, "2026-01-05"), "nom"),
    (("x", "AV", 1000, "2026-01-05"), "enveloppe"),
    (("x", "CTO", 0, "2026-01-05"), "positif"),
    (("x", "CTO", "abc", "2026-01-05"), "capital invalide"),
    (("x", "CTO", float("inf"), "2026-01-05"), "positif"),
    (("x", "CTO", 1000, "pas une date"), "date invalide"),
    (("x", "CTO", 1000, "2999-01-01"), "futur"),
    (("x", "PEA", 150_000.01, "2026-01-05"), "plafond"),
])
def test_strategy_validation(conn, args, message):
    with pytest.raises(store.FundError, match=message):
        store.create_strategy(conn, *args)


def test_pea_accepts_exactly_the_deposit_cap(conn):
    assert store.create_strategy(conn, "PEA plein", "PEA", 150_000, "2026-01-05")


def test_update_strategy_rejects_unknown_fields_and_blank_name(conn):
    sid = store.create_strategy(conn, "A", "CTO", 1000, "2026-01-05")
    with pytest.raises(store.FundError, match="non modifiable"):
        store.update_strategy(conn, sid, wrapper="PEA")
    with pytest.raises(store.FundError, match="nom"):
        store.update_strategy(conn, sid, name="  ")


def test_orders_roundtrip_update_and_position_delete(conn):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    first = store.insert_order(conn, _order(sid))
    second = store.insert_order(conn, _order(sid, ts="2026-01-09", action="reduce", quantity=1.0, spec={}))
    other = store.insert_order(conn, _order(sid, position_id="pos_b", symbol="TTE.PA"))
    orders = store.list_orders(conn, sid)
    assert [o["order_id"] for o in orders] == [first, other, second]      # triés par date puis par identifiant
    assert orders[0]["spec"] == {"leverage": 5} and orders[0]["fee_seed"] == 7
    store.update_order(conn, first, _order(sid, quantity=6.0, spec={"leverage": 3}))
    assert store.get_order(conn, first)["quantity"] == 6.0 and store.get_order(conn, first)["spec"] == {"leverage": 3}
    assert store.delete_position(conn, "pos_a") == 2
    assert [o["order_id"] for o in store.list_orders(conn, sid)] == [other]
    assert store.get_order(conn, 9999) is None


def test_deleting_a_strategy_removes_its_orders(conn):
    sid = store.create_strategy(conn, "A", "CTO", 100_000, "2026-01-05")
    store.insert_order(conn, _order(sid))
    store.delete_strategy(conn, sid)
    assert conn.execute("SELECT COUNT(*) FROM fund_order").fetchone()[0] == 0
```

- [ ] **Step 3 : Vérifier que le test échoue**

```bash
$PY -m pytest tests/test_fund_store.py -q -W ignore
```

Résultat attendu : erreur de collecte `ModuleNotFoundError: No module named 'patrick.fund'`.

- [ ] **Step 4 : Créer la migration, le paquet et le stockage**

Créer `patrick/patrick/tracking/migrations/0029_fund.sql` :

```sql
-- Refonte Simulation + page Fonds, chantier 1 : stratégies, ordres, cotations
-- persistantes. Aucune position ni aucun solde n'est stocké : tout se recalcule
-- depuis les ordres (patrick/fund/engine.py).
CREATE TABLE fund_strategy (
    strategy_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    wrapper TEXT NOT NULL CHECK (wrapper IN ('PEA', 'CTO')),
    base_currency TEXT NOT NULL DEFAULT 'EUR',
    initial_capital REAL NOT NULL CHECK (initial_capital > 0),
    opened_on TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- `instrument_kind` sans CHECK : le code le valide, les chantiers 2 et 3
-- ajoutent des types (options, swaps) sans reconstruire la table.
-- `fees` est en devise de base ; `fx_rate` = devise de base par unité de la
-- devise de l'instrument à la date d'exécution ; `spec_json` porte les
-- composantes (multiplicateur, mois de contrat, levier, marge, stop, objectif).
CREATE TABLE fund_order (
    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL REFERENCES fund_strategy(strategy_id) ON DELETE CASCADE,
    position_id TEXT NOT NULL,
    ts TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('open', 'increase', 'reduce', 'close', 'modify')),
    instrument_kind TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL CHECK (side IN ('long', 'short')),
    quantity REAL NOT NULL CHECK (quantity >= 0),
    price REAL,
    price_source TEXT CHECK (price_source IN ('market', 'manual')),
    currency TEXT NOT NULL,
    fx_rate REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    fees_source TEXT CHECK (fees_source IN ('manual', 'estimated')),
    fee_seed INTEGER,
    spec_json TEXT NOT NULL DEFAULT '{}',
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_fund_order_strategy ON fund_order(strategy_id, ts, order_id);
CREATE INDEX idx_fund_order_position ON fund_order(position_id);

-- Cotations conservées DÉFINITIVEMENT : Yahoo retire les contrats expirés et la
-- valeur d'une stratégie doit rester calculable après l'échéance. Prix en
-- unités de la devise ISO (les pence sont convertis à l'écriture).
CREATE TABLE fund_price (
    symbol TEXT NOT NULL,
    day TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL NOT NULL DEFAULT 0,
    dividend REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, day)
);
CREATE TABLE fund_price_meta (
    symbol TEXT PRIMARY KEY,
    currency TEXT,
    refreshed_at TEXT
);
```

Créer `patrick/patrick/fund/__init__.py` (fichier vide), puis `patrick/patrick/fund/store.py` :

```python
"""Persistance des stratégies et des ordres (migration 0029). Aucune position
ni aucun solde n'est stocké : tout se recalcule depuis les ordres."""
from __future__ import annotations

import json
import math
import sqlite3
import uuid

import pandas as pd

from patrick.clock import utc_today
from patrick.wealth.ledger import PEA_DEPOSIT_CAP_EUR

WRAPPERS = ("PEA", "CTO")
ACTIONS = ("open", "increase", "reduce", "close", "modify")
INSTRUMENT_KINDS = ("equity", "etf", "future", "cfd")
_STRATEGY_COLUMNS = ("strategy_id", "name", "wrapper", "base_currency", "initial_capital", "opened_on",
                     "archived", "created_at")
_ORDER_COLUMNS = ("order_id", "strategy_id", "position_id", "ts", "action", "instrument_kind", "symbol", "side",
                  "quantity", "price", "price_source", "currency", "fx_rate", "fees", "fees_source", "fee_seed",
                  "spec_json", "note")


class FundError(ValueError):
    """Entrée invalide (400 à l'API)."""


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _iso(value) -> str:
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise FundError(f"date invalide : {value!r}") from exc


# -------------------------------------------------------------- strategies

def create_strategy(conn: sqlite3.Connection, name: str, wrapper: str, initial_capital, opened_on,
                    base_currency: str = "EUR") -> str:
    name = (name or "").strip()
    if not name:
        raise FundError("nom de stratégie manquant")
    if wrapper not in WRAPPERS:
        raise FundError(f"enveloppe inconnue : {wrapper!r} ({WRAPPERS})")
    try:
        capital = float(str(initial_capital).replace(",", ".").replace(" ", ""))
    except ValueError as exc:
        raise FundError(f"capital invalide : {initial_capital!r}") from exc
    if not math.isfinite(capital) or capital <= 0:
        raise FundError("le capital doit être strictement positif")
    if wrapper == "PEA" and capital > PEA_DEPOSIT_CAP_EUR:
        raise FundError(f"PEA : capital {capital:,.0f} € > plafond de versements {PEA_DEPOSIT_CAP_EUR:,.0f} €"
                        .replace(",", " "))
    opened = _iso(opened_on)
    if opened > utc_today().isoformat():
        raise FundError("la date d'ouverture ne peut pas être dans le futur")
    strategy_id = new_id("str")
    with conn:
        conn.execute("INSERT INTO fund_strategy (strategy_id, name, wrapper, base_currency, initial_capital, "
                     "opened_on) VALUES (?, ?, ?, ?, ?, ?)",
                     (strategy_id, name[:120], wrapper, (base_currency or "EUR").upper()[:3], capital, opened))
    return strategy_id


def get_strategy(conn: sqlite3.Connection, strategy_id: str) -> dict | None:
    row = conn.execute(f"SELECT {', '.join(_STRATEGY_COLUMNS)} FROM fund_strategy WHERE strategy_id = ?",
                       (strategy_id,)).fetchone()
    return dict(zip(_STRATEGY_COLUMNS, row)) if row else None


def list_strategies(conn: sqlite3.Connection, include_archived: bool = False) -> list[dict]:
    sql = f"SELECT {', '.join(_STRATEGY_COLUMNS)} FROM fund_strategy"
    if not include_archived:
        sql += " WHERE archived = 0"
    return [dict(zip(_STRATEGY_COLUMNS, r)) for r in conn.execute(sql + " ORDER BY created_at, rowid")]


def update_strategy(conn: sqlite3.Connection, strategy_id: str, **fields) -> None:
    allowed = {"name", "archived"}
    unknown = set(fields) - allowed
    if unknown:
        raise FundError(f"champ(s) non modifiable(s) : {sorted(unknown)}")
    if "name" in fields and not str(fields["name"]).strip():
        raise FundError("nom de stratégie manquant")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE fund_strategy SET {sets} WHERE strategy_id = ?", (*fields.values(), strategy_id))


def delete_strategy(conn: sqlite3.Connection, strategy_id: str) -> None:
    with conn:
        conn.execute("DELETE FROM fund_strategy WHERE strategy_id = ?", (strategy_id,))


# ------------------------------------------------------------------ orders

def _order_row(raw: dict) -> dict:
    out = {k: raw.get(k) for k in _ORDER_COLUMNS if k not in ("order_id", "spec_json")}
    out["spec_json"] = json.dumps(raw.get("spec") or {}, sort_keys=True)
    return out


def _parse_order(row: tuple) -> dict:
    o = dict(zip(_ORDER_COLUMNS, row))
    o["spec"] = json.loads(o.pop("spec_json") or "{}")
    return o


def insert_order(conn: sqlite3.Connection, raw: dict) -> int:
    r = _order_row(raw)
    cols = list(r)
    with conn:
        cur = conn.execute(f"INSERT INTO fund_order ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                           tuple(r[c] for c in cols))
    return int(cur.lastrowid)


def update_order(conn: sqlite3.Connection, order_id: int, raw: dict) -> None:
    r = _order_row(raw)
    sets = ", ".join(f"{c} = ?" for c in r)
    with conn:
        conn.execute(f"UPDATE fund_order SET {sets} WHERE order_id = ?", (*r.values(), order_id))


def get_order(conn: sqlite3.Connection, order_id: int) -> dict | None:
    row = conn.execute(f"SELECT {', '.join(_ORDER_COLUMNS)} FROM fund_order WHERE order_id = ?",
                       (order_id,)).fetchone()
    return _parse_order(row) if row else None


def list_orders(conn: sqlite3.Connection, strategy_id: str) -> list[dict]:
    rows = conn.execute(f"SELECT {', '.join(_ORDER_COLUMNS)} FROM fund_order WHERE strategy_id = ? "
                        "ORDER BY ts, order_id", (strategy_id,)).fetchall()
    return [_parse_order(r) for r in rows]


def delete_position(conn: sqlite3.Connection, position_id: str) -> int:
    with conn:
        cur = conn.execute("DELETE FROM fund_order WHERE position_id = ?", (position_id,))
    return cur.rowcount
```

- [ ] **Step 5 : Vérifier que les tests passent**

```bash
$PY -m pytest tests/test_fund_store.py tests/test_db.py -q -W ignore
$PY -m ruff check patrick/fund tests/test_fund_store.py
```

Résultat attendu : tous les tests passent (`test_db.py` compte les fichiers de migration et suit automatiquement le nouveau) ; ruff : `All checks passed!`.

- [ ] **Step 6 : Amender la spec (écarts assumés)**

```bash
$PY - <<'PYEOF'
from pathlib import Path
p = Path("../docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md")
s = p.read_text(encoding="utf-8")
old = "| `fund/service.py` | Agrégats pour les pages et l'API (une fonction par écran). |"
new = old + "\n| `fund/store.py` | Persistance des stratégies et des ordres ; validation de la création d'une stratégie. |"
assert s.count(old) == 1
s = s.replace(old, new)
old = """    open REAL, high REAL, low REAL, close REAL,
    dividend REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, day)
);"""
new = """    open REAL, high REAL, low REAL, close REAL,
    volume REAL NOT NULL DEFAULT 0,        -- volume moyen 20 jours : taille des frais estimés
    dividend REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, day)
);

CREATE TABLE fund_price_meta (              -- devise ISO du symbole et dernière actualisation (cache 6 h)
    symbol TEXT PRIMARY KEY,
    currency TEXT,
    refreshed_at TEXT
);"""
assert s.count(old) == 1
p.write_text(s.replace(old, new), encoding="utf-8")
PYEOF
```

- [ ] **Step 7 : Commit**

```bash
git add patrick/tracking/migrations/0029_fund.sql patrick/fund tests/test_fund_store.py ../docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md
git commit -m "feat(fund): migration 0029 et stockage des stratégies et des ordres" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2 : Estimation des frais

**Files:**
- Create: `patrick/patrick/fund/fees.py`
- Test: `patrick/tests/test_fund_fees.py`

**Interfaces:**
- Produces (`patrick.fund.fees`) : `FeeContext(kind, notional_base, quantity, currency, base_currency="EUR", fee_class="", adv_notional_base=None, commission_per_contract_base=0.0, tick_bps=0.0)` ; `FeeBreakdown(commission, spread, fx)` avec propriété `total` (arrondie à 2 décimales) ; `make_seed(*parts) -> int` ; `estimate_fees(ctx, seed) -> FeeBreakdown` ; constantes `SPREAD_MEDIAN_BPS`, `SIGMA`, `FX_FEE_BPS`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_fees.py` :

```python
"""Estimation des frais (spec §8) : reproductible, commissions déterministes."""
from __future__ import annotations

import pytest

from patrick.fund import fees


def test_estimate_is_reproducible_and_future_commission_is_fixed():
    ctx = fees.FeeContext(kind="future", notional_base=500_000.0, quantity=2.0, currency="USD",
                          commission_per_contract_base=2.0, tick_bps=0.5)
    a = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 1))
    b = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 1))
    assert a == b and a.commission == 4.0 and a.fx > 0
    c = fees.estimate_fees(ctx, fees.make_seed("s", "p", "2026-01-06", 2))
    assert c.spread != a.spread and c.commission == a.commission


def test_seed_depends_on_every_part():
    assert fees.make_seed("a", "b") == fees.make_seed("a", "b")
    assert fees.make_seed("a", "b") != fees.make_seed("a", "c")


def test_equity_commission_has_a_one_euro_floor_then_scales():
    small = fees.estimate_fees(fees.FeeContext(kind="equity", notional_base=1_000.0, quantity=1, currency="EUR"), 1)
    big = fees.estimate_fees(fees.FeeContext(kind="equity", notional_base=10_000.0, quantity=10, currency="EUR"), 1)
    assert small.commission == 1.0 and big.commission == pytest.approx(5.0)
    assert small.fx == 0.0


def test_etf_spread_is_three_halves_of_a_large_cap_for_the_same_draw():
    kw = {"notional_base": 10_000.0, "quantity": 10, "currency": "EUR", "adv_notional_base": 50_000_000.0}
    large = fees.estimate_fees(fees.FeeContext(kind="equity", **kw), 3)
    etf = fees.estimate_fees(fees.FeeContext(kind="etf", **kw), 3)
    assert etf.spread / large.spread == pytest.approx(3.0 / 2.0)
    thin = fees.estimate_fees(fees.FeeContext(kind="equity", **{**kw, "adv_notional_base": 1_000_000.0}), 3)
    assert thin.spread > large.spread * 4       # action peu liquide : médiane 8 bps et plus grande participation


def test_cfd_has_no_commission_and_foreign_currency_pays_the_conversion_fee():
    eur = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=100_000.0, quantity=10, currency="EUR",
                                             fee_class="cfd_index"), 5)
    usd = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=100_000.0, quantity=10, currency="USD",
                                             fee_class="cfd_index"), 5)
    assert eur.commission == 0.0 and eur.fx == 0.0
    assert usd.fx == pytest.approx(100.0) and usd.spread == eur.spread
    assert usd.total == pytest.approx(usd.spread + usd.fx, abs=0.01)


def test_larger_derivative_orders_pay_a_larger_spread_per_unit_of_notional():
    def spread_bps(notional):
        b = fees.estimate_fees(fees.FeeContext(kind="cfd", notional_base=notional, quantity=1, currency="EUR",
                                               fee_class="cfd_index"), 11)
        return b.spread / notional * 1e4
    assert spread_bps(5_000_000.0) > spread_bps(10_000.0)


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError, match="inconnu"):
        fees.estimate_fees(fees.FeeContext(kind="swap", notional_base=1.0, quantity=1, currency="EUR"), 1)
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_fees.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.fees`.

- [ ] **Step 3 : Implémenter `fees.py`**

```python
"""Estimation des frais d'un ordre (spec §8) : commission déterministe +
coût de spread tiré d'une loi log-normale + frais de change. Le tirage est
reproductible : même graine, même montant. Toutes les constantes sont des
ordres de grandeur indicatifs, pas des mesures sur un courtier réel."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

import numpy as np

SIGMA = 0.5                       # écart-type du log du coût de spread
FX_FEE_BPS = 10.0                 # frais de change si devise instrument != devise de base
EQUITY_MIN_COMMISSION = 1.0       # € par ordre action/ETF
EQUITY_COMMISSION_RATE = 0.0005   # 0,05 % du montant
LARGE_CAP_ADV_BASE = 20_000_000.0  # volume moyen quotidien (devise de base) au-delà duquel une action est « grande capitalisation »
EQUITY_PARTICIPATION_SLOPE = 100.0
EQUITY_SIZE_CAP = 5.0
DERIV_SIZE_REF = 1_000_000.0
DERIV_SIZE_CAP = 2.0

# Médiane du coût de spread, en points de base du notionnel.
SPREAD_MEDIAN_BPS = {
    "equity_large": 2.0, "equity_mid": 8.0, "etf": 3.0,
    "cfd_index": 1.0, "cfd_fx_major": 0.8, "cfd_fx_other": 3.0, "cfd_commodity": 4.0,
    "cfd_equity": 5.0, "cfd_crypto": 30.0, "cfd_other": 5.0,
}


@dataclass(frozen=True)
class FeeContext:
    kind: str                       # equity | etf | future | cfd
    notional_base: float
    quantity: float
    currency: str
    base_currency: str = "EUR"
    fee_class: str = ""             # clé de SPREAD_MEDIAN_BPS (CFD) ; ignoré pour action/ETF/future
    adv_notional_base: float | None = None        # volume moyen 20 j en devise de base (action/ETF)
    commission_per_contract_base: float = 0.0     # future : commission fixe par contrat, devise de base
    tick_bps: float = 0.0                          # future : demi-tick en points de base du notionnel


@dataclass(frozen=True)
class FeeBreakdown:
    commission: float
    spread: float
    fx: float

    @property
    def total(self) -> float:
        return round(self.commission + self.spread + self.fx, 2)


def make_seed(*parts) -> int:
    raw = "|".join(str(p) for p in parts).encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def estimate_fees(ctx: FeeContext, seed: int) -> FeeBreakdown:
    z = float(np.random.default_rng(seed).standard_normal())
    notional = abs(ctx.notional_base)
    if ctx.kind in ("equity", "etf"):
        commission = max(EQUITY_MIN_COMMISSION, EQUITY_COMMISSION_RATE * notional)
        if ctx.kind == "etf":
            median = SPREAD_MEDIAN_BPS["etf"]
        elif ctx.adv_notional_base and ctx.adv_notional_base >= LARGE_CAP_ADV_BASE:
            median = SPREAD_MEDIAN_BPS["equity_large"]
        else:
            median = SPREAD_MEDIAN_BPS["equity_mid"]
        participation = notional / ctx.adv_notional_base if ctx.adv_notional_base else 0.0
        size = 1.0 + min(EQUITY_SIZE_CAP, EQUITY_PARTICIPATION_SLOPE * participation)
    elif ctx.kind == "future":
        commission = ctx.commission_per_contract_base * ctx.quantity
        median = ctx.tick_bps
        size = 1.0 + min(DERIV_SIZE_CAP, notional / DERIV_SIZE_REF)
    elif ctx.kind == "cfd":
        commission = 0.0
        median = SPREAD_MEDIAN_BPS.get(ctx.fee_class, SPREAD_MEDIAN_BPS["cfd_other"])
        size = 1.0 + min(DERIV_SIZE_CAP, notional / DERIV_SIZE_REF)
    else:
        raise ValueError(f"type d'instrument inconnu : {ctx.kind!r}")
    spread = notional * median / 1e4 * math.exp(SIGMA * z) * size
    fx = notional * FX_FEE_BPS / 1e4 if ctx.currency != ctx.base_currency else 0.0
    return FeeBreakdown(round(commission, 6), round(spread, 6), round(fx, 6))
```

- [ ] **Step 4 : Vérifier**

```bash
$PY -m pytest tests/test_fund_fees.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_fees.py
```

Résultat attendu : tests verts, ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/fees.py tests/test_fund_fees.py
git commit -m "feat(fund): frais estimés reproductibles (commission + spread log-normal)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3 : Catalogue de futures, échéances, CFD

**Files:**
- Create: `patrick/patrick/fund/instruments.py`
- Test: `patrick/tests/test_fund_instruments.py`

**Interfaces:**
- Produces (`patrick.fund.instruments`) : `FutureSpec` (champs `root, name, exchange, currency, multiplier, tick_size, months, expiry_rule, margin, commission, group`, méthodes `yahoo_symbol(year, month)`, `expiry(year, month) -> date`) ; `FUTURES_CATALOG: dict[str, FutureSpec]` ; `EXPIRY_RULES: dict[str, callable]` ; `listed_contracts(root, today, n=None) -> list[dict]` (clés `root, year, month, symbol, expiry, label`) ; `CFD_LEVERAGE_CAPS`, `CFD_FEE_CLASS` ; `classify_cfd_underlying(symbol, quote_type=None) -> str` ; `cfd_leverage_cap(symbol, quote_type=None) -> float`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_instruments.py` :

```python
"""Catalogue de futures, règles d'échéance, classes d'actifs et plafonds de levier CFD."""
from __future__ import annotations

import datetime as dt
import re

import pytest

from patrick.fund import instruments as ins


def test_every_catalog_entry_is_well_formed():
    assert {"ES", "CL", "NG", "GC"} <= set(ins.FUTURES_CATALOG)
    for root, spec in ins.FUTURES_CATALOG.items():
        assert spec.root == root and spec.multiplier > 0 and spec.margin > 0 and spec.commission > 0
        assert spec.tick_size > 0 and spec.expiry_rule in ins.EXPIRY_RULES
        assert spec.months and all(1 <= m <= 12 for m in spec.months)
        assert re.fullmatch(rf"{root}[FGHJKMNQUVXZ]\d\d\.(CME|CBT|NYM|CMX)", spec.yahoo_symbol(2026, spec.months[0]))


def test_listed_contracts_are_future_sorted_and_labelled():
    listed = ins.listed_contracts("ES", dt.date(2026, 10, 3))
    assert [c["label"] for c in listed][:3] == ["Z26", "H27", "M27"]
    assert listed[0]["symbol"] == "ESZ26.CME" and listed[0]["expiry"] == "2026-12-18"
    assert len(listed) == 6
    assert all(c["expiry"] > "2026-10-03" for c in listed)
    assert [c["expiry"] for c in listed] == sorted(c["expiry"] for c in listed)
    crude = ins.listed_contracts("CL", dt.date(2026, 10, 3))
    assert crude[0]["label"] == "X26" and len(crude) == 8        # V26 est déjà échu
    assert len(ins.listed_contracts("CL", dt.date(2026, 10, 3), n=3)) == 3


def test_listed_contracts_roll_over_the_year_end():
    assert ins.listed_contracts("GC", dt.date(2026, 12, 20))[0]["label"] == "Z26"           # échoit le 29 décembre
    listed = ins.listed_contracts("GC", dt.date(2026, 12, 30))
    assert listed[0]["label"] == "G27" and listed[0]["expiry"].startswith("2027-02")
    assert ins.listed_contracts("ES", dt.date(2026, 12, 19))[0]["label"] == "H27"


@pytest.mark.parametrize("rule, year, month, expected", [
    ("third_friday", 2026, 12, "2026-12-18"),
    ("crude", 2026, 12, "2026-11-20"),         # 3 jours ouvrés avant le 25 novembre
    ("crude", 2027, 1, "2026-12-22"),           # janvier : le décembre précédent, 25 = vendredi
    ("natgas", 2026, 12, "2026-11-26"),         # 3 jours ouvrés avant le 1er décembre
    ("third_last_bd", 2026, 12, "2026-12-29"),
    ("grain", 2026, 12, "2026-12-14"),
    ("treasury", 2026, 12, "2026-12-22"),       # 7 jours ouvrés avant le 31 décembre (Noël ignoré)
    ("fx", 2026, 12, "2026-12-14"),             # 2 jours ouvrés avant le 3e mercredi (16)
])
def test_expiry_rules(rule, year, month, expected):
    assert ins.EXPIRY_RULES[rule](year, month).isoformat() == expected


@pytest.mark.parametrize("symbol, quote_type, expected", [
    ("EURUSD=X", None, "fx_major"), ("USDJPY=X", None, "fx_major"), ("EURSEK=X", None, "fx_other"),
    ("XAUUSD=X", None, "gold"), ("GC=F", None, "gold"), ("CL=F", None, "commodity"),
    ("^GSPC", None, "index_major"), ("^STOXX50E", "INDEX", "index_major"), ("^VIX", "INDEX", "index_other"),
    ("BTC-EUR", None, "crypto"), ("DOGE", "CRYPTOCURRENCY", "crypto"),
    ("AAPL", None, "equity"), ("MC.PA", "EQUITY", "equity"), ("URTH", "ETF", "equity"),
    ("XYZ", "MUTUALFUND", "other"),
])
def test_cfd_underlying_classification(symbol, quote_type, expected):
    assert ins.classify_cfd_underlying(symbol, quote_type) == expected


def test_leverage_caps_follow_the_esma_classes():
    caps = {s: ins.cfd_leverage_cap(s) for s in ("EURUSD=X", "EURSEK=X", "GC=F", "^GSPC", "CL=F", "^VIX", "AAPL",
                                                  "BTC-USD")}
    assert caps == {"EURUSD=X": 30.0, "EURSEK=X": 20.0, "GC=F": 20.0, "^GSPC": 20.0, "CL=F": 10.0, "^VIX": 10.0,
                    "AAPL": 5.0, "BTC-USD": 2.0}
    assert set(ins.CFD_FEE_CLASS) == set(ins.CFD_LEVERAGE_CAPS)
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_instruments.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.instruments`.

- [ ] **Step 3 : Implémenter `instruments.py`**

Les marges et commissions sont des **estimations indicatives** (non relevées sur le barème CME) : le docstring le dit, et le contrôle réseau de la Task 11 vérifie seulement que Yahoo sert chaque racine.

```python
"""Spécifications des instruments du chantier 1 (spec §7) : catalogue de
futures, règles d'échéance, classes d'actifs et plafonds de levier des CFD.

Les marges et commissions du catalogue sont des ORDRES DE GRANDEUR
INDICATIFS (estimation au 2026-10-03, non relevés sur le barème CME Group) :
à rafraîchir depuis les barèmes publiés avant tout usage sérieux."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

import numpy as np

MONTH_CODES = {1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M", 7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z"}
QUARTERLY = (3, 6, 9, 12)
ALL_MONTHS = tuple(range(1, 13))


def _third_weekday(year: int, month: int, weekday: int) -> dt.date:
    first = dt.date(year, month, 1)
    shift = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=shift + 14)


def _bd(day: dt.date, offset: int, roll: str) -> dt.date:
    return np.busday_offset(day, offset, roll=roll).astype(dt.date)


def _last_day(year: int, month: int) -> dt.date:
    return dt.date(year, month, calendar.monthrange(year, month)[1])


# Règles d'échéance approchées (jours fériés ignorés, écart possible de 1 à 2 jours) ;
# si la série stockée s'arrête avant, la dernière date stockée fait foi (engine.simulate).
def expiry_third_friday(year: int, month: int) -> dt.date:
    return _third_weekday(year, month, 4)


def expiry_crude(year: int, month: int) -> dt.date:
    prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
    return _bd(_bd(dt.date(prev_year, prev_month, 25), 0, "backward"), -3, "backward")


def expiry_natgas(year: int, month: int) -> dt.date:
    return _bd(dt.date(year, month, 1), -3, "forward")


def expiry_third_last_bd(year: int, month: int) -> dt.date:
    return _bd(_last_day(year, month), -2, "backward")


def expiry_grain(year: int, month: int) -> dt.date:
    return _bd(dt.date(year, month, 15), -1, "forward")


def expiry_treasury(year: int, month: int) -> dt.date:
    return _bd(_bd(_last_day(year, month), 0, "backward"), -7, "backward")


def expiry_fx(year: int, month: int) -> dt.date:
    return _bd(_third_weekday(year, month, 2), -2, "backward")


EXPIRY_RULES = {
    "third_friday": expiry_third_friday, "crude": expiry_crude, "natgas": expiry_natgas,
    "third_last_bd": expiry_third_last_bd, "grain": expiry_grain, "treasury": expiry_treasury, "fx": expiry_fx,
}


@dataclass(frozen=True)
class FutureSpec:
    root: str
    name: str
    exchange: str            # suffixe Yahoo : CME | CBT | NYM | CMX
    currency: str
    multiplier: float        # devise du contrat par point de prix
    tick_size: float
    months: tuple[int, ...]
    expiry_rule: str
    margin: float            # marge initiale par contrat, devise du contrat (indicatif)
    commission: float        # commission par contrat et par sens, devise du contrat (indicatif)
    group: str

    def yahoo_symbol(self, year: int, month: int) -> str:
        return f"{self.root}{MONTH_CODES[month]}{year % 100:02d}.{self.exchange}"

    def expiry(self, year: int, month: int) -> dt.date:
        return EXPIRY_RULES[self.expiry_rule](year, month)


def _f(root, name, exch, ccy, mult, tick, months, rule, margin, comm, group):
    return FutureSpec(root, name, exch, ccy, mult, tick, months, rule, margin, comm, group)


_GRAIN_MONTHS = (3, 5, 7, 9, 12)
FUTURES_CATALOG: dict[str, FutureSpec] = {s.root: s for s in (
    _f("ES", "E-mini S&P 500", "CME", "USD", 50.0, 0.25, QUARTERLY, "third_friday", 22000.0, 2.0, "equity_index"),
    _f("MES", "Micro E-mini S&P 500", "CME", "USD", 5.0, 0.25, QUARTERLY, "third_friday", 2200.0, 0.6, "equity_index"),
    _f("NQ", "E-mini Nasdaq-100", "CME", "USD", 20.0, 0.25, QUARTERLY, "third_friday", 32000.0, 2.0, "equity_index"),
    _f("MNQ", "Micro E-mini Nasdaq-100", "CME", "USD", 2.0, 0.25, QUARTERLY, "third_friday", 3200.0, 0.6, "equity_index"),
    _f("YM", "E-mini Dow", "CBT", "USD", 5.0, 1.0, QUARTERLY, "third_friday", 15000.0, 2.0, "equity_index"),
    _f("RTY", "E-mini Russell 2000", "CME", "USD", 50.0, 0.1, QUARTERLY, "third_friday", 8000.0, 2.0, "equity_index"),
    _f("CL", "Pétrole brut WTI", "NYM", "USD", 1000.0, 0.01, ALL_MONTHS, "crude", 6000.0, 2.5, "energy"),
    _f("MCL", "Micro pétrole brut WTI", "NYM", "USD", 100.0, 0.01, ALL_MONTHS, "crude", 600.0, 0.8, "energy"),
    _f("NG", "Gaz naturel Henry Hub", "NYM", "USD", 10000.0, 0.001, ALL_MONTHS, "natgas", 3500.0, 2.5, "energy"),
    _f("GC", "Or", "CMX", "USD", 100.0, 0.1, (2, 4, 6, 8, 10, 12), "third_last_bd", 11000.0, 2.5, "metal"),
    _f("MGC", "Micro or", "CMX", "USD", 10.0, 0.1, (2, 4, 6, 8, 10, 12), "third_last_bd", 1100.0, 0.8, "metal"),
    _f("SI", "Argent", "CMX", "USD", 5000.0, 0.005, (3, 5, 7, 9, 12), "third_last_bd", 14000.0, 2.5, "metal"),
    _f("HG", "Cuivre", "CMX", "USD", 25000.0, 0.0005, (3, 5, 7, 9, 12), "third_last_bd", 6500.0, 2.5, "metal"),
    _f("ZC", "Maïs", "CBT", "USD", 50.0, 0.25, _GRAIN_MONTHS, "grain", 1800.0, 2.5, "grain"),
    _f("ZW", "Blé", "CBT", "USD", 50.0, 0.25, _GRAIN_MONTHS, "grain", 2200.0, 2.5, "grain"),
    _f("ZS", "Soja", "CBT", "USD", 50.0, 0.25, (1, 3, 5, 7, 8, 9, 11), "grain", 3300.0, 2.5, "grain"),
    _f("ZN", "T-Note 10 ans", "CBT", "USD", 1000.0, 0.015625, QUARTERLY, "treasury", 2000.0, 2.0, "rate"),
    _f("6E", "Euro / dollar", "CME", "USD", 125000.0, 0.00005, QUARTERLY, "fx", 2800.0, 2.5, "fx"),
)}


def listed_contracts(root: str, today: dt.date, n: int | None = None) -> list[dict]:
    """Contrats du produit encore négociables à `today` (échéance calculée dans
    le futur), du plus proche au plus lointain."""
    spec = FUTURES_CATALOG[root]
    limit = n or (6 if len(spec.months) <= 4 else 8)
    out: list[dict] = []
    year, month = today.year, today.month
    for _ in range(24 * 12):
        if month in spec.months:
            expiry = spec.expiry(year, month)
            if expiry > today:
                out.append({"root": root, "year": year, "month": month, "symbol": spec.yahoo_symbol(year, month),
                            "expiry": expiry.isoformat(), "label": f"{MONTH_CODES[month]}{year % 100:02d}"})
                if len(out) >= limit:
                    break
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return out


# ------------------------------------------------------------------ CFD
# Plafonds de levier pour un client non professionnel (mesures d'intervention
# de l'ESMA sur les CFD, 2018) : 30:1 paires de devises majeures ; 20:1 autres
# paires, or et indices majeurs ; 10:1 matières premières hors or et indices
# non majeurs ; 5:1 actions et autres ; 2:1 cryptoactifs.
CFD_LEVERAGE_CAPS = {"fx_major": 30.0, "fx_other": 20.0, "gold": 20.0, "index_major": 20.0, "commodity": 10.0,
                     "index_other": 10.0, "equity": 5.0, "crypto": 2.0, "other": 5.0}
CFD_FEE_CLASS = {"fx_major": "cfd_fx_major", "fx_other": "cfd_fx_other", "gold": "cfd_commodity",
                 "index_major": "cfd_index", "index_other": "cfd_index", "commodity": "cfd_commodity",
                 "equity": "cfd_equity", "crypto": "cfd_crypto", "other": "cfd_other"}
ESMA_MAJOR_CURRENCIES = frozenset({"USD", "EUR", "JPY", "GBP", "CAD", "CHF"})
MAJOR_INDICES = frozenset({"^GSPC", "^DJI", "^NDX", "^FTSE", "^FCHI", "^GDAXI", "^STOXX50E", "^N225", "^AXJO"})
_CRYPTO_RE = re.compile(r"^[A-Z0-9]{2,10}-(USD|EUR|GBP|USDT)$")


def classify_cfd_underlying(symbol: str, quote_type: str | None = None) -> str:
    sym = symbol.upper()
    if sym.endswith("=X"):
        pair = sym[:-2]
        if pair.startswith("XAU"):
            return "gold"
        if len(pair) == 6 and pair[:3] in ESMA_MAJOR_CURRENCIES and pair[3:] in ESMA_MAJOR_CURRENCIES:
            return "fx_major"
        return "fx_other"
    if sym == "GC=F":
        return "gold"
    if sym.endswith("=F"):
        return "commodity"
    if sym.startswith("^"):
        return "index_major" if sym in MAJOR_INDICES else "index_other"
    if (quote_type or "").upper() == "CRYPTOCURRENCY" or _CRYPTO_RE.match(sym):
        return "crypto"
    if (quote_type or "EQUITY").upper() in ("EQUITY", "ETF"):
        return "equity"
    return "other"


def cfd_leverage_cap(symbol: str, quote_type: str | None = None) -> float:
    return CFD_LEVERAGE_CAPS[classify_cfd_underlying(symbol, quote_type)]
```

- [ ] **Step 4 : Vérifier**

```bash
$PY -m pytest tests/test_fund_instruments.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_instruments.py
```

Résultat attendu : tests verts, ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/instruments.py tests/test_fund_instruments.py
git commit -m "feat(fund): catalogue de futures, règles d'échéance, classes et plafonds de levier CFD" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4 : Moteur de valorisation

**Files:**
- Create: `patrick/patrick/fund/engine.py`
- Test: `patrick/tests/test_fund_engine.py`

**Interfaces:**
- Consumes (Task 2) : `fees.FeeContext`, `fees.estimate_fees`, `fees.make_seed`.
- Produces (`patrick.fund.engine`) :
  - `MarketData(bars, fx, ref_rates, base_currency="EUR")` : `bars: dict[str, DataFrame]` (colonnes `open high low close volume dividend`, index de dates croissantes), `fx: dict[str, Series]` (devise → unités de base par unité de devise), `ref_rates: dict[str, float]` ; méthodes `close_at`, `bar_on`, `last_bar_day`, `dividend_on`, `fx_at`, `ref_rate`.
  - `simulate(strategy: dict, orders: list[dict], market, end=None) -> SimResult` ; `SimResult(daily: DataFrame, positions: list[dict], violations: list[dict], alert_days: list[str])`.
  - `daily` : index de dates, colonnes `cash, equity_value, cfd_unrealized, nav, margin_used, buying_power, gross_exposure, net_exposure, fees_cum, dividends_cum, financing_cum`.
  - Chaque position (`positions`) : `position_id, symbol, kind, side, currency, status` (`open|closed|stop|target|expired`), `opened_on, closed_on, quantity, avg_entry, last_price, fx_open, fx_now, value_base, margin, realized, latent, price_effect, fx_effect, fees, dividends, financing, pnl, pnl_pct, stop, target, leverage, expiry, price_quality`.
  - Un ordre est un dict : `order_id, strategy_id, position_id, ts, action (open|increase|reduce|close|modify), instrument_kind, symbol, side, quantity, price, currency, fx_rate, fees, spec`. `spec` porte `multiplier, margin_per_unit, expiry, fee_ctx` (future), `leverage, fee_ctx` (CFD), `stop, target`.
  - Constantes : `EQUITY_KINDS = ("equity", "etf")`, `DERIV_KINDS = ("future", "cfd")`, `EPS`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `patrick/tests/test_fund_engine.py` (cas chiffrés à la main : change, PRU, dividende à l'ex-date, short future avec règlement quotidien, stop sur gap, objectif, priorité du stop, échéance, financement du week-end, violations, identité comptable) :

```python
"""Moteur de valorisation (spec §7, §9, §10) : cas chiffrés à la main, sans réseau."""
from __future__ import annotations

import pandas as pd
import pytest

from patrick.fund.engine import MarketData, simulate

DAYS = pd.bdate_range("2026-01-05", periods=10)  # lun 5 janv. -> ven 16 janv. 2026
STRAT = {"initial_capital": 100_000.0, "opened_on": "2026-01-05"}
END = "2026-01-16"


def bars(closes, *, opens=None, highs=None, lows=None, dividends=None):
    n = len(closes)
    return pd.DataFrame({
        "open": opens or closes, "high": highs or closes, "low": lows or closes, "close": closes,
        "volume": [1e6] * n, "dividend": dividends or [0.0] * n}, index=DAYS[:n])


def order(**kw):
    base = {"order_id": 1, "strategy_id": "s", "position_id": "p1", "ts": "2026-01-06", "action": "open",
            "instrument_kind": "equity", "symbol": "AAA", "side": "long", "quantity": 10.0, "price": 100.0,
            "currency": "EUR", "fx_rate": 1.0, "fees": 0.0, "spec": {}}
    base.update(kw)
    return base


def pos_of(res, pid="p1"):
    return next(p for p in res.positions if p["position_id"] == pid)


def test_equity_usd_splits_price_and_fx_effects():
    mkt = MarketData(bars={"AAA": bars([100.0] * 9 + [110.0])},
                     fx={"USD": pd.Series([0.9] * 9 + [0.95], index=DAYS)})
    res = simulate(STRAT, [order(currency="USD", fx_rate=0.9, fees=1.5)], mkt, END)
    p = pos_of(res)
    assert res.daily["nav"].iloc[-1] == pytest.approx(100_000 - 900 - 1.5 + 10 * 110 * 0.95)
    assert p["price_effect"] == pytest.approx(90.0)
    assert p["fx_effect"] == pytest.approx(55.0)
    assert p["pnl"] == pytest.approx(143.5)
    assert p["pnl_pct"] == pytest.approx(143.5 / 900)
    assert p["fx_open"] == pytest.approx(0.9) and p["fx_now"] == pytest.approx(0.95)
    assert not res.violations


def test_increase_then_reduce_uses_weighted_average_cost():
    mkt = MarketData(bars={"AAA": bars([100, 100, 120, 130] + [130.0] * 6)})
    orders = [order(order_id=1, ts="2026-01-06"),
              order(order_id=2, ts="2026-01-07", action="increase", price=120.0),
              order(order_id=3, ts="2026-01-08", action="reduce", quantity=5.0, price=130.0)]
    p = pos_of(simulate(STRAT, orders, mkt, END))
    assert p["quantity"] == 15 and p["avg_entry"] == pytest.approx(110.0)
    assert p["realized"] == pytest.approx(100.0)       # 5 x (130 - 110)
    assert p["latent"] == pytest.approx(300.0)         # 15 x 130 - 1650
    assert p["pnl"] == pytest.approx(400.0)


def test_dividend_goes_to_holders_of_the_previous_close_only():
    mkt = MarketData(bars={"AAA": bars([100.0] * 10, dividends=[0, 0, 0, 0.5, 0, 0, 0, 0, 0, 0])})
    early = order(order_id=1, ts="2026-01-06", position_id="early")
    late = order(order_id=2, ts="2026-01-08", position_id="late")   # achetée le jour de l'ex-date
    res = simulate(STRAT, [early, late], mkt, END)
    assert pos_of(res, "early")["dividends"] == pytest.approx(5.0)
    assert pos_of(res, "late")["dividends"] == 0.0
    assert res.daily["dividends_cum"].iloc[-1] == pytest.approx(5.0)


FUT_SPEC = {"multiplier": 50.0, "margin_per_unit": 20_000.0, "expiry": "2026-02-20",
            "fee_ctx": {"commission_per_contract_base": 2.0, "tick_bps": 0.5}}


def fut(**kw):
    return order(instrument_kind="future", symbol="FUT", side="short", quantity=2.0, price=5000.0,
                 spec=dict(FUT_SPEC), **kw)


def test_short_future_settles_variation_daily_and_blocks_margin():
    mkt = MarketData(bars={"FUT": bars([5000, 5000, 4990, 4980] + [4980.0] * 6)})
    res = simulate(STRAT, [fut(fees=4.0)], mkt, END)
    d = res.daily
    assert d["margin_used"].iloc[1] == pytest.approx(40_000)
    assert d["buying_power"].iloc[1] == pytest.approx(100_000 - 4 - 40_000)
    # 01-07 : -2 x 50 x (4990 - 5000) = +1000 ; 01-08 : -2 x 50 x (4980 - 4990) = +1000
    assert d["cash"].iloc[-1] == pytest.approx(100_000 - 4 + 2000)
    assert d["nav"].iloc[-1] == pytest.approx(100_000 - 4 + 2000)
    p = pos_of(res)
    assert p["pnl"] == pytest.approx(1996.0)
    assert p["pnl_pct"] == pytest.approx(1996.0 / 40_000)
    assert p["price_effect"] + p["fx_effect"] == pytest.approx(2000.0)
    assert p["realized"] + p["latent"] == pytest.approx(2000.0)


def test_stop_on_gap_fills_at_the_open():
    spec = dict(FUT_SPEC, stop=4900.0)
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    closes = [5000, 5000, 4820] + [4820.0] * 7
    opens = [5000, 5000, 4850] + [4820.0] * 7
    lows = [5000, 5000, 4800] + [4820.0] * 7
    highs = [5000, 5000, 4900] + [4820.0] * 7
    mkt = MarketData(bars={"FUT": bars(closes, opens=opens, highs=highs, lows=lows)})
    res = simulate(STRAT, [o], mkt, END)
    p = pos_of(res)
    assert p["status"] == "stop" and p["closed_on"] == "2026-01-07"
    assert p["realized"] == pytest.approx(-150 * 50)       # fill 4850, pas 4900 ni 4820
    assert res.daily["margin_used"].iloc[-1] == 0.0
    assert p["fees"] > 0                                    # frais estimés de la clôture automatique


def test_target_hit_and_stop_priority_when_both_touch_the_same_day():
    spec = dict(FUT_SPEC, stop=4900.0, target=5100.0)
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    flat = [5000.0] * 10
    mkt = MarketData(bars={"FUT": bars(flat, highs=[5000, 5000, 5200] + [5000.0] * 7,
                                        lows=[5000, 5000, 4800] + [5000.0] * 7)})
    assert pos_of(simulate(STRAT, [o], mkt, END))["status"] == "stop"
    mkt2 = MarketData(bars={"FUT": bars(flat, highs=[5000, 5000, 5200] + [5000.0] * 7)})
    p2 = pos_of(simulate(STRAT, [o], mkt2, END))
    assert p2["status"] == "target" and p2["realized"] == pytest.approx(100 * 50)


def test_future_expires_at_its_expiry_date():
    spec = dict(FUT_SPEC, expiry="2026-01-14")
    o = order(instrument_kind="future", symbol="FUT", side="long", quantity=1.0, price=5000.0, spec=spec)
    mkt = MarketData(bars={"FUT": bars([5000.0 + i for i in range(10)])})
    res = simulate(STRAT, [o], mkt, END)
    p = pos_of(res)
    assert p["status"] == "expired" and p["closed_on"] == "2026-01-14"
    assert res.daily["margin_used"].iloc[-1] == 0.0


def test_cfd_financing_covers_the_weekend():
    spec = {"leverage": 10.0, "fee_ctx": {"fee_class": "cfd_index"}}
    o = order(instrument_kind="cfd", symbol="IDX", quantity=100.0, price=50.0, ts="2026-01-09", spec=spec)
    mkt = MarketData(bars={"IDX": bars([50.0] * 10)})
    res = simulate(STRAT, [o], mkt, END)
    d = res.daily
    fri, mon = d.index.get_loc(pd.Timestamp("2026-01-09")), d.index.get_loc(pd.Timestamp("2026-01-12"))
    assert d["financing_cum"].iloc[fri] == pytest.approx(5000 * 0.045 * 3 / 365)    # vendredi -> lundi
    assert d["financing_cum"].iloc[mon] - d["financing_cum"].iloc[fri] == pytest.approx(5000 * 0.045 / 365)
    assert d["margin_used"].iloc[fri] == pytest.approx(500.0)
    assert d["nav"].iloc[fri] == pytest.approx(100_000 - 5000 * 0.045 * 3 / 365)


def test_short_cfd_receives_reference_minus_spread():
    spec = {"leverage": 10.0, "fee_ctx": {"fee_class": "cfd_index"}}
    o = order(instrument_kind="cfd", symbol="IDX", side="short", quantity=100.0, price=50.0, ts="2026-01-12", spec=spec)
    res = simulate(STRAT, [o], MarketData(bars={"IDX": bars([50.0] * 10)}, ref_rates={"EUR": 0.05}), END)
    assert res.daily["financing_cum"].iloc[-1] == pytest.approx(-5000 * (0.05 - 0.025) * (1 / 365) * 5)


def test_violations_are_reported_not_raised():
    mkt = MarketData(bars={"AAA": bars([100.0] * 10)})
    too_big = order(quantity=2000.0)                                       # 200 000 > capital
    res = simulate(STRAT, [too_big], mkt, END)
    assert any("insuffisant" in v["message"] for v in res.violations)
    oversell = [order(order_id=1), order(order_id=2, ts="2026-01-07", action="reduce", quantity=50.0)]
    assert any("détenus" in v["message"] for v in simulate(STRAT, oversell, mkt, END).violations)
    early = order(ts="2026-01-02")
    assert any("antérieur" in v["message"] for v in simulate(STRAT, [early], mkt, END).violations)
    closed = [order(order_id=1), order(order_id=2, ts="2026-01-07", action="close"),
              order(order_id=3, ts="2026-01-08", action="increase")]
    assert any("clôturée" in v["message"] for v in simulate(STRAT, closed, mkt, END).violations)


def test_accounting_identity_holds_across_instruments():
    """NAV - capital = somme des P&L des positions (réalisé + latent + dividendes - frais - financement)."""
    n = 10
    mkt = MarketData(
        bars={"AAA": bars([100, 101, 103, 102, 105, 107, 106, 108, 110, 111], dividends=[0, 0, 0, 0.4] + [0] * 6),
              "FUT": bars([5000, 5010, 4990, 5020, 5050, 5000, 4980, 5030, 5060, 5040]),
              "IDX": bars([50, 51, 49, 50, 52, 53, 51, 52, 54, 55])},
        fx={"USD": pd.Series([0.92, 0.91, 0.93, 0.92, 0.9, 0.91, 0.92, 0.94, 0.93, 0.95], index=DAYS[:n])})
    orders = [
        order(order_id=1, position_id="a", ts="2026-01-06", symbol="AAA", currency="USD", fx_rate=0.91,
              quantity=40.0, price=101.0, fees=2.0),
        order(order_id=2, position_id="a", ts="2026-01-09", action="reduce", symbol="AAA", currency="USD",
              fx_rate=0.9, quantity=15.0, price=105.0, fees=1.0),
        order(order_id=3, position_id="f", ts="2026-01-06", instrument_kind="future", symbol="FUT", side="short",
              currency="USD", fx_rate=0.91, quantity=1.0, price=5010.0, fees=3.0, spec=dict(FUT_SPEC)),
        order(order_id=4, position_id="f", ts="2026-01-13", action="increase", instrument_kind="future",
              symbol="FUT", side="short", currency="USD", fx_rate=0.92, quantity=1.0, price=4980.0, fees=3.0,
              spec=dict(FUT_SPEC)),
        order(order_id=5, position_id="f", ts="2026-01-15", action="close", instrument_kind="future",
              symbol="FUT", side="short", currency="USD", fx_rate=0.93, quantity=2.0, price=5060.0, fees=3.0,
              spec=dict(FUT_SPEC)),
        order(order_id=6, position_id="c", ts="2026-01-07", instrument_kind="cfd", symbol="IDX", currency="USD",
              fx_rate=0.93, quantity=200.0, price=49.0, fees=1.0, spec={"leverage": 5.0, "fee_ctx": {"fee_class": "cfd_index"}}),
        order(order_id=7, position_id="c", ts="2026-01-14", action="reduce", instrument_kind="cfd", symbol="IDX",
              currency="USD", fx_rate=0.91, quantity=50.0, price=52.0, fees=1.0, spec={"leverage": 5.0}),
    ]
    res = simulate(STRAT, orders, mkt, END)
    assert not res.violations
    total = sum(p["pnl"] for p in res.positions)
    assert res.daily["nav"].iloc[-1] - STRAT["initial_capital"] == pytest.approx(total, abs=1e-6)
    fees = sum(p["fees"] for p in res.positions)
    assert res.daily["fees_cum"].iloc[-1] == pytest.approx(fees)
    assert any(p["dividends"] > 0 for p in res.positions)
    assert any(p["financing"] > 0 for p in res.positions)
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_engine.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.engine`.

- [ ] **Step 3 : Implémenter `engine.py`**

Séquence d'une journée : dividendes, déclenchement des stop/objectif, ordres du jour, règlement de fin de journée (variation des futures, financement des CFD, échéance), photographie. Le financement d'un CFD est prélevé à la clôture de chaque jour pour les nuits jusqu'au prochain jour ouvré (3 le vendredi).

```python
"""Moteur de valorisation d'une stratégie (spec §7, §9, §10).

Fonctions pures : (stratégie, ordres, données de marché) -> série quotidienne
de cash / NAV / marge + état de chaque position. Rien n'est stocké : on
rejoue les ordres jour par jour.

Séquence d'une journée de bourse :
  a. dividendes des actions/ETF détenus en début de journée ;
  b. déclenchement des stop/objectif (futures et CFD) des positions dont le
     dernier ordre est antérieur au jour ;
  c. ordres du jour (par ordre d'identifiant) ;
  d. règlement de fin de journée : variation des futures, financement des CFD,
     échéance des futures ;
  e. photographie (cash, valeur, marge, exposition).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from patrick.clock import utc_today
from patrick.fund import fees as fees_mod

EPS = 1e-9
FINANCING_SPREAD = 0.025          # marge du fournisseur sur le taux de référence (CFD)
DEFAULT_REF_RATES = {"EUR": 0.02, "USD": 0.04, "GBP": 0.04, "JPY": 0.005, "CHF": 0.005}
EQUITY_KINDS = ("equity", "etf")
DERIV_KINDS = ("future", "cfd")
DAILY_COLUMNS = ["cash", "equity_value", "cfd_unrealized", "nav", "margin_used", "buying_power",
                 "gross_exposure", "net_exposure", "fees_cum", "dividends_cum", "financing_cum"]


@dataclass
class MarketData:
    """Cotations en unités de la devise ISO (les pence sont déjà convertis)."""
    bars: dict[str, pd.DataFrame] = field(default_factory=dict)   # open high low close volume dividend
    fx: dict[str, pd.Series] = field(default_factory=dict)        # devise -> unités de base par unité de devise
    ref_rates: dict[str, float] = field(default_factory=dict)
    base_currency: str = "EUR"

    def close_at(self, symbol: str, day: pd.Timestamp) -> float | None:
        df = self.bars.get(symbol)
        if df is None or df.empty:
            return None
        s = df["close"][df.index <= day].dropna()
        return float(s.iloc[-1]) if len(s) else None

    def bar_on(self, symbol: str, day: pd.Timestamp) -> pd.Series | None:
        df = self.bars.get(symbol)
        if df is None or day not in df.index:
            return None
        return df.loc[day]

    def last_bar_day(self, symbol: str) -> pd.Timestamp | None:
        df = self.bars.get(symbol)
        return None if df is None or df.empty else df.index[-1]

    def dividend_on(self, symbol: str, day: pd.Timestamp) -> float:
        bar = self.bar_on(symbol, day)
        if bar is None or "dividend" not in bar or pd.isna(bar["dividend"]):
            return 0.0
        return float(bar["dividend"])

    def fx_at(self, currency: str, day: pd.Timestamp, default: float = 1.0) -> float:
        if currency == self.base_currency:
            return 1.0
        s = self.fx.get(currency)
        if s is None or s.empty:
            return default
        s = s[s.index <= day].dropna()
        return float(s.iloc[-1]) if len(s) else default

    def ref_rate(self, currency: str) -> float:
        return self.ref_rates.get(currency, DEFAULT_REF_RATES.get(currency, 0.03))


@dataclass
class _Pos:
    position_id: str
    symbol: str
    kind: str
    side: str
    currency: str
    spec: dict
    opened_on: str
    qty: float = 0.0
    cost_local: float = 0.0       # somme quantité x prix de la quantité ouverte (devise de l'instrument)
    cost_base: float = 0.0        # idem en devise de base, au change de chaque ordre
    fx_ref: float = 1.0           # change moyen d'entrée = cost_base / cost_local
    mark: float = 0.0             # futures : prix de règlement moyen de la quantité ouverte
    realized: float = 0.0         # action/CFD : plus-value réalisée (devise de base, hors frais)
    var_cum: float = 0.0          # futures : variation cumulée réglée en cash (devise de base)
    pnl_local_cum: float = 0.0    # futures : variation cumulée en devise du contrat
    fees: float = 0.0
    dividends: float = 0.0
    financing_cost: float = 0.0
    engaged_peak: float = 0.0     # base du %, action : coût ; future/CFD : marge maximale
    status: str = "open"          # open | closed | stop | target | expired
    closed_on: str | None = None
    last_order_day: str = ""
    last_price: float | None = None
    last_fx: float = 1.0

    @property
    def sgn(self) -> float:
        return 1.0 if self.side == "long" else -1.0

    @property
    def multiplier(self) -> float:
        return float(self.spec.get("multiplier", 1.0)) if self.kind == "future" else 1.0

    @property
    def avg_local(self) -> float:
        return self.cost_local / self.qty if self.qty > EPS else 0.0


@dataclass
class SimResult:
    daily: pd.DataFrame
    positions: list[dict]
    violations: list[dict]
    alert_days: list[str]


def simulate(strategy: dict, orders: list[dict], market: MarketData, end=None) -> SimResult:
    base = market.base_currency
    start = pd.Timestamp(strategy["opened_on"])
    end_ts = pd.Timestamp(end if end is not None else utc_today())
    days = pd.bdate_range(start, end_ts)
    violations: list[dict] = []
    by_day: dict[pd.Timestamp, list[dict]] = {}
    for o in sorted(orders, key=lambda o: (o["ts"], o.get("order_id") or 0)):
        d = pd.Timestamp(o["ts"])
        if d < start:
            violations.append({"day": o["ts"], "message": f"ordre du {o['ts']} antérieur à l'ouverture de la stratégie"})
            continue
        i = days.searchsorted(d)
        if i >= len(days):
            violations.append({"day": o["ts"], "message": f"ordre du {o['ts']} postérieur à la fin de la période"})
            continue
        by_day.setdefault(days[i], []).append(o)

    cash = float(strategy["initial_capital"])
    positions: dict[str, _Pos] = {}
    totals = {"fees": 0.0, "dividends": 0.0, "financing": 0.0}
    rows: list[dict] = []
    alert_days: list[str] = []

    def violate(day: str, message: str) -> None:
        violations.append({"day": day, "message": message})

    def apply_open_or_increase(pos: _Pos, o: dict, fx: float) -> None:
        nonlocal cash
        q, p = float(o["quantity"]), float(o["price"])
        if pos.kind == "future":
            pos.mark = (pos.qty * pos.mark + q * p) / (pos.qty + q)
        if pos.kind in EQUITY_KINDS:
            cash -= q * p * fx
        pos.cost_local += q * p
        pos.cost_base += q * p * fx
        pos.fx_ref = pos.cost_base / pos.cost_local if pos.cost_local > EPS else fx
        pos.qty += q
        if pos.kind in EQUITY_KINDS:
            pos.engaged_peak = max(pos.engaged_peak, pos.cost_base)

    def apply_reduce(pos: _Pos, o: dict, fx: float, day: str, whole: bool) -> None:
        nonlocal cash
        q = pos.qty if whole else float(o["quantity"])
        if q > pos.qty + 1e-6:
            violate(day, f"{pos.symbol} : vente de {q:g} pour {pos.qty:g} détenus")
        q = min(q, pos.qty)
        if q <= EPS:
            return
        p = float(o["price"])
        frac_left = (pos.qty - q) / pos.qty
        if pos.kind in EQUITY_KINDS:
            proceeds = q * p * fx
            pos.realized += proceeds - pos.cost_base / pos.qty * q
            cash += proceeds
        elif pos.kind == "cfd":
            gain = pos.sgn * q * (p - pos.avg_local) * fx
            pos.realized += gain
            cash += gain
        else:  # future : règle la variation de la quantité sortante jusqu'au prix de l'ordre
            local = pos.sgn * q * pos.multiplier * (p - pos.mark)
            gain = local * fx
            pos.pnl_local_cum += local
            pos.var_cum += gain
            cash += gain
        pos.cost_local *= frac_left
        pos.cost_base *= frac_left
        pos.qty -= q
        if pos.qty <= EPS:
            pos.qty = 0.0
            pos.cost_local = pos.cost_base = 0.0
            pos.status, pos.closed_on = "closed", day

    def charge_fees(pos: _Pos, amount: float) -> None:
        nonlocal cash
        cash -= amount
        pos.fees += amount
        totals["fees"] += amount

    def auto_close(pos: _Pos, price: float, day: pd.Timestamp, reason: str) -> None:
        iso = day.date().isoformat()
        fx = market.fx_at(pos.currency, day, pos.fx_ref)
        fc = pos.spec.get("fee_ctx", {})
        notional = pos.qty * pos.multiplier * price * fx
        ctx = fees_mod.FeeContext(kind=pos.kind, notional_base=notional, quantity=pos.qty,
                                  currency=pos.currency, base_currency=base, **fc)
        amount = fees_mod.estimate_fees(ctx, fees_mod.make_seed(pos.position_id, reason)).total
        apply_reduce(pos, {"price": price}, fx, iso, whole=True)
        charge_fees(pos, amount)
        pos.status, pos.closed_on = reason, iso

    for i, day in enumerate(days):
        iso = day.date().isoformat()
        # nuits à financer après cette clôture : jusqu'au prochain jour ouvré (3 le vendredi)
        cal_days = (days[i + 1] - day).days if i + 1 < len(days) else 1

        # a. dividendes (quantité détenue en début de journée)
        for pos in positions.values():
            if pos.status == "open" and pos.kind in EQUITY_KINDS and pos.qty > EPS:
                div = market.dividend_on(pos.symbol, day)
                if div:
                    amount = pos.qty * div * market.fx_at(pos.currency, day, pos.fx_ref)
                    cash += amount
                    pos.dividends += amount
                    totals["dividends"] += amount

        # b. stop / objectif
        for pos in positions.values():
            if pos.status != "open" or pos.kind not in DERIV_KINDS or pos.last_order_day >= iso:
                continue
            bar = market.bar_on(pos.symbol, day)
            if bar is None or bar[["open", "high", "low"]].isna().any():
                continue
            hit = _trigger(pos, float(bar["open"]), float(bar["high"]), float(bar["low"]))
            if hit:
                auto_close(pos, hit[1], day, hit[0])

        # c. ordres du jour
        for o in by_day.get(day, []):
            pid, act = o["position_id"], o["action"]
            pos = positions.get(pid)
            fx = float(o["fx_rate"])
            if act == "open":
                if pos is not None:
                    violate(iso, f"{o['symbol']} : position {pid} déjà ouverte")
                    continue
                pos = positions[pid] = _Pos(pid, o["symbol"], o["instrument_kind"], o["side"], o["currency"],
                                            dict(o.get("spec") or {}), iso)
            elif pos is None:
                violate(iso, f"{o['symbol']} : ordre {act} sans position ouverte")
                continue
            elif pos.status != "open":
                violate(iso, f"{pos.symbol} : position déjà clôturée ({pos.status}) le {pos.closed_on}")
                continue
            if act in ("open", "increase"):
                apply_open_or_increase(pos, o, fx)
            elif act in ("reduce", "close"):
                apply_reduce(pos, o, fx, iso, whole=(act == "close"))
            elif act == "modify":
                pos.spec.update({k: v for k, v in (o.get("spec") or {}).items() if k in ("stop", "target", "leverage")})
            else:
                violate(iso, f"action inconnue : {act!r}")
                continue
            charge_fees(pos, float(o.get("fees") or 0.0))
            pos.last_order_day = iso

        # d. règlement de fin de journée
        for pos in positions.values():
            if pos.status != "open" or pos.qty <= EPS:
                continue
            close = market.close_at(pos.symbol, day)
            if close is None:
                continue
            fx = market.fx_at(pos.currency, day, pos.fx_ref)
            pos.last_price, pos.last_fx = close, fx
            if pos.kind == "future":
                local = pos.sgn * pos.qty * pos.multiplier * (close - pos.mark)
                cash += local * fx
                pos.var_cum += local * fx
                pos.pnl_local_cum += local
                pos.mark = close
                last = market.last_bar_day(pos.symbol)
                expiry = pd.Timestamp(pos.spec["expiry"]) if pos.spec.get("expiry") else None
                if expiry is not None and last is not None and last < end_ts - pd.Timedelta(days=7):
                    expiry = min(expiry, last)
                if expiry is not None and day >= expiry:
                    auto_close(pos, close, day, "expired")
            elif pos.kind == "cfd":
                notional = pos.qty * close * fx
                rate = market.ref_rate(pos.currency)
                fin = (-notional * (rate + FINANCING_SPREAD) if pos.side == "long"
                       else notional * (rate - FINANCING_SPREAD)) * cal_days / 365.0
                cash += fin
                pos.financing_cost -= fin
                totals["financing"] -= fin

        # e. photographie
        equity_value = cfd_unreal = margin = gross = net = 0.0
        for pos in positions.values():
            if pos.status != "open" or pos.qty <= EPS or pos.last_price is None:
                continue
            c, fx = pos.last_price, pos.last_fx
            if pos.kind in EQUITY_KINDS:
                mv = pos.qty * c * fx
                equity_value += mv
                gross += abs(mv)
                net += mv
            elif pos.kind == "cfd":
                cfd_unreal += pos.sgn * pos.qty * (c - pos.avg_local) * fx
                notional = pos.qty * c * fx
                m = notional / float(pos.spec.get("leverage") or 1.0)
                margin += m
                gross += notional
                net += pos.sgn * notional
                pos.engaged_peak = max(pos.engaged_peak, m)
            else:
                notional = pos.qty * pos.multiplier * c * fx
                m = pos.qty * float(pos.spec.get("margin_per_unit", 0.0)) * fx
                margin += m
                gross += notional
                net += pos.sgn * notional
                pos.engaged_peak = max(pos.engaged_peak, m)
        nav = cash + equity_value + cfd_unreal
        buying_power = cash + cfd_unreal - margin
        if by_day.get(day) and buying_power < -1e-6:
            violate(iso, f"liquidités ou marge insuffisantes le {iso} (disponible {buying_power:,.2f} {base})")
        if margin > EPS and nav < 0.5 * margin:
            alert_days.append(iso)
        rows.append({"date": day, "cash": cash, "equity_value": equity_value, "cfd_unrealized": cfd_unreal,
                     "nav": nav, "margin_used": margin, "buying_power": buying_power,
                     "gross_exposure": gross, "net_exposure": net, "fees_cum": totals["fees"],
                     "dividends_cum": totals["dividends"], "financing_cum": totals["financing"]})

    daily = pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=DAILY_COLUMNS)
    return SimResult(daily, [_view(p, market, end_ts) for p in positions.values()], violations, alert_days)


def _trigger(pos: _Pos, o: float, h: float, lo: float) -> tuple[str, float] | None:
    stop, target = pos.spec.get("stop"), pos.spec.get("target")
    if pos.side == "long":
        if stop is not None and lo <= stop:
            return "stop", min(float(stop), o)
        if target is not None and h >= target:
            return "target", max(float(target), o)
    else:
        if stop is not None and h >= stop:
            return "stop", max(float(stop), o)
        if target is not None and lo <= target:
            return "target", min(float(target), o)
    return None


def _view(pos: _Pos, market: MarketData, end_ts: pd.Timestamp) -> dict:
    close = pos.last_price if pos.last_price is not None else market.close_at(pos.symbol, end_ts)
    fx_now = market.fx_at(pos.currency, end_ts, pos.fx_ref)
    is_open = pos.status == "open" and pos.qty > EPS
    value = latent = price_effect = fx_effect = margin = 0.0
    if is_open and close is not None:
        if pos.kind in EQUITY_KINDS:
            value = pos.qty * close * fx_now
            latent = value - pos.cost_base
            price_effect = pos.qty * (close - pos.avg_local) * pos.fx_ref
            fx_effect = pos.qty * close * (fx_now - pos.fx_ref)
        elif pos.kind == "cfd":
            latent = pos.sgn * pos.qty * (close - pos.avg_local) * fx_now
            value = latent
            price_effect = pos.sgn * pos.qty * (close - pos.avg_local) * pos.fx_ref
            fx_effect = latent - price_effect
            margin = pos.qty * close * fx_now / float(pos.spec.get("leverage") or 1.0)
        else:
            latent = pos.sgn * pos.qty * pos.multiplier * (close - pos.avg_local) * pos.fx_ref
            margin = pos.qty * float(pos.spec.get("margin_per_unit", 0.0)) * fx_now
    if pos.kind == "future":
        realized = pos.var_cum - latent
        price_effect = pos.pnl_local_cum * pos.fx_ref
        fx_effect = pos.var_cum - price_effect
        gross = pos.var_cum
    else:
        realized = pos.realized
        if not is_open:
            price_effect, fx_effect = realized, 0.0
        gross = realized + latent
    pnl = gross - pos.fees + pos.dividends - pos.financing_cost
    engaged = pos.engaged_peak
    return {
        "position_id": pos.position_id, "symbol": pos.symbol, "kind": pos.kind, "side": pos.side,
        "currency": pos.currency, "status": pos.status, "opened_on": pos.opened_on, "closed_on": pos.closed_on,
        "quantity": pos.qty, "avg_entry": pos.avg_local if is_open else None, "last_price": close,
        "fx_open": pos.fx_ref, "fx_now": fx_now, "value_base": value, "margin": margin,
        "realized": realized, "latent": latent, "price_effect": price_effect, "fx_effect": fx_effect,
        "fees": pos.fees, "dividends": pos.dividends, "financing": pos.financing_cost,
        "pnl": pnl, "pnl_pct": pnl / engaged if engaged > EPS else None,
        "stop": pos.spec.get("stop"), "target": pos.spec.get("target"),
        "leverage": pos.spec.get("leverage"), "expiry": pos.spec.get("expiry"),
        "price_quality": pos.spec.get("price_quality"),
    }
```

- [ ] **Step 4 : Vérifier**

```bash
$PY -m pytest tests/test_fund_engine.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_engine.py
```

Résultat attendu : 11 tests verts, ruff propre. L'identité comptable `NAV − capital = Σ P&L des positions` est vérifiée sur un scénario mixte action USD + future + CFD.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/engine.py tests/test_fund_engine.py
git commit -m "feat(fund): moteur de valorisation (actions, futures, CFD, stop/objectif, échéance)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5 : Cotations persistantes, change et taux de référence

**Files:**
- Create: `patrick/patrick/fund/prices.py`, `patrick/tests/fund_support.py`
- Test: `patrick/tests/test_fund_prices.py`

**Interfaces:**
- Consumes (Task 4) : `engine.MarketData`, `engine.DEFAULT_REF_RATES` ; (Task 1) tables `fund_price`, `fund_price_meta`.
- Produces (`patrick.fund.prices`) : `download_bars(symbol, start=None) -> (DataFrame | None, raw_currency | None)` (fonction de module : les tests la remplacent) ; `iso_currency(raw) -> (iso | None, scale)` ; `save_bars(conn, symbol, df, raw_currency, now=None)` ; `load_bars(conn, symbol) -> DataFrame | None` ; `get_meta(conn, symbol) -> dict | None` ; `BarsResult(df, currency, status)` avec `status ∈ fresh|stored|missing` ; `ensure_bars(conn, symbol, *, max_age_hours=6.0, now=None) -> BarsResult` ; `fx_symbol(base, currency) -> str` ; `fx_series(conn, base, currency) -> Series | None` ; `reference_rates(currencies: set[str]) -> (dict, notes)` ; `build_market(conn, orders, base="EUR", with_rates=True) -> (MarketData, notes)`.
- Produces (`tests/fund_support.py`) : `IDX`, `FAKE`, `TODAY`, `CALLS`, `day_index`, `price_on`, `fx_on`, `fake_download`, `install(monkeypatch)`.

- [ ] **Step 1 : Écrire les cotations factices partagées et le test qui échoue**

Créer `patrick/tests/fund_support.py` (version initiale ; Task 8 l'étend) :

```python
"""Cotations factices partagées par les tests du fonds : aucun réseau.

Importé par les fichiers `test_fund_*.py` (le dossier `tests/` est sur le
chemin d'import, comme `conftest`)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from patrick.fund import prices

IDX = pd.bdate_range("2025-06-02", "2026-10-02")
# symbole -> (devise brute, prix de départ, dérive quotidienne)
FAKE = {
    "AAPL": ("USD", 200.0, 0.4), "MC.PA": ("EUR", 700.0, 0.5), "TTE.PA": ("EUR", 60.0, 0.05),
    "VOD.L": ("GBp", 70.0, 0.02), "EURUSD=X": ("USD", 1.10, 0.0004), "EURGBP=X": ("GBP", 0.85, 0.0),
    "ESZ26.CME": ("USD", 6000.0, 3.0), "^GSPC": ("USD", 6000.0, 3.0),
}
TODAY = dt.date(2026, 1, 16)
CALLS: list[tuple[str, str | None]] = []


def day_index(day: str) -> int:
    return list(IDX).index(pd.Timestamp(day))


def price_on(symbol: str, day: str) -> float:
    _, p0, drift = FAKE[symbol]
    return p0 + drift * day_index(day)


def fx_on(day: str) -> float:
    """Euros par dollar : inverse du cours EURUSD=X."""
    return 1.0 / price_on("EURUSD=X", day)


def fake_download(symbol, start=None):
    CALLS.append((symbol, start))
    if symbol not in FAKE:
        return None, None
    ccy, p0, drift = FAKE[symbol]
    close = p0 + drift * np.arange(len(IDX))
    df = pd.DataFrame({"open": close, "high": close * 1.002, "low": close * 0.998, "close": close,
                       "volume": 5_000_000.0, "dividend": 0.0}, index=IDX)
    return df, ccy


def install(monkeypatch) -> None:
    CALLS.clear()
    monkeypatch.setattr(prices, "download_bars", fake_download)
    monkeypatch.delenv("FRED_API_KEY", raising=False)
```

Créer `patrick/tests/test_fund_prices.py` :

```python
"""Cotations des stratégies : persistance définitive, hors ligne, pence, change, taux de référence."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pandas as pd
import pytest

from patrick.data.sources import fred_source
from patrick.fund import prices


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def test_pence_quotes_are_converted_to_pounds(conn):
    res = prices.ensure_bars(conn, "VOD.L")
    assert res.currency == "GBP" and res.df["close"].iloc[0] == pytest.approx(0.70)
    assert prices.iso_currency("GBp") == ("GBP", 0.01) and prices.iso_currency("USD") == ("USD", 1.0)
    assert prices.iso_currency(None) == (None, 1.0)


def test_prices_are_persisted_and_served_offline_after_expiry_of_the_cache(conn, monkeypatch):
    prices.ensure_bars(conn, "MC.PA")
    monkeypatch.setattr(prices, "download_bars", lambda s, start=None: (None, None))
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    res = prices.ensure_bars(conn, "MC.PA", now=later)
    assert res.status == "stored" and len(res.df) == len(fs.IDX) and res.currency == "EUR"
    assert prices.ensure_bars(conn, "UNKNOWN").status == "missing"


def test_a_fresh_cache_is_not_downloaded_again_and_a_stale_one_refreshes_incrementally(conn):
    prices.ensure_bars(conn, "MC.PA")
    prices.ensure_bars(conn, "MC.PA")
    assert fs.CALLS == [("MC.PA", None)]
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=7)
    prices.ensure_bars(conn, "MC.PA", now=later)
    assert fs.CALLS[1][0] == "MC.PA" and fs.CALLS[1][1] == "2026-09-25"     # dernier jour stocké - 7 jours


def test_upsert_overwrites_revised_rows_without_duplicating(conn):
    df, ccy = fs.fake_download("MC.PA")
    prices.save_bars(conn, "MC.PA", df, ccy)
    revised = df.copy()
    revised.iloc[-1, revised.columns.get_loc("close")] = 1.0
    prices.save_bars(conn, "MC.PA", revised, ccy)
    stored = prices.load_bars(conn, "MC.PA")
    assert len(stored) == len(df) and stored["close"].iloc[-1] == 1.0


def test_fx_series_is_the_inverse_of_the_yahoo_pair(conn):
    s = prices.fx_series(conn, "EUR", "USD")
    assert s.iloc[0] == pytest.approx(1 / 1.10) and prices.fx_symbol("EUR", "USD") == "EURUSD=X"
    assert prices.fx_series(conn, "EUR", "SEK") is None


def test_build_market_collects_bars_fx_rates_and_notes(conn):
    orders = [
        {"symbol": "AAPL", "currency": "USD", "instrument_kind": "equity"},
        {"symbol": "^GSPC", "currency": "USD", "instrument_kind": "cfd"},
        {"symbol": "MC.PA", "currency": "EUR", "instrument_kind": "equity"},
        {"symbol": "GHOST", "currency": "EUR", "instrument_kind": "equity"},
        {"symbol": "TTE.PA", "currency": "SEK", "instrument_kind": "equity"},   # devise sans paire de change
    ]
    market, notes = prices.build_market(conn, orders, "EUR")
    assert set(market.bars) == {"AAPL", "^GSPC", "MC.PA", "TTE.PA"} and set(market.fx) == {"USD"}
    assert market.ref_rates == {"USD": 0.04}
    assert any("GHOST" in n and "aucune cotation" in n for n in notes)
    assert any("change EUR/SEK indisponible" in n for n in notes)
    assert any("taux de référence USD" in n for n in notes)


def test_stored_prices_are_flagged_as_offline_in_the_notes(conn, monkeypatch):
    prices.ensure_bars(conn, "MC.PA")
    conn.execute("UPDATE fund_price_meta SET refreshed_at = '2020-01-01 00:00:00'")
    monkeypatch.setattr(prices, "download_bars", lambda s, start=None: (None, None))
    _, notes = prices.build_market(conn, [{"symbol": "MC.PA", "currency": "EUR", "instrument_kind": "equity"}])
    assert any("hors ligne" in n for n in notes)


def test_reference_rates_use_fred_when_the_key_is_set(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "key")
    seen = []
    monkeypatch.setattr(fred_source, "download_series",
                        lambda name, sid, start: seen.append(sid) or pd.Series([4.5, 4.3]))
    rates, notes = prices.reference_rates({"USD", "JPY"})
    assert rates["USD"] == pytest.approx(0.043) and seen == ["SOFR"]
    assert rates["JPY"] == 0.005 and len(notes) == 1 and "JPY" in notes[0]


def test_reference_rates_fall_back_to_constants_without_the_key():
    rates, notes = prices.reference_rates({"EUR", "AUD"})
    assert rates == {"EUR": 0.02, "AUD": 0.03} and len(notes) == 2
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_prices.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.prices`.

- [ ] **Step 3 : Implémenter `prices.py`**

```python
"""Cotations des stratégies : Yahoo Finance + persistance définitive dans
`fund_price` (spec §6). Yahoo retire les contrats expirés ; les cotations
utilisées restent donc stockées pour que la valeur d'une stratégie reste
calculable. Clôtures non ajustées des dividendes (le dividende est crédité
au cash par le moteur), ajustées des fractionnements.

`download_bars` est une fonction de module : les tests la remplacent."""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from dataclasses import dataclass

import pandas as pd

from patrick.fund.engine import DEFAULT_REF_RATES, MarketData

HISTORY_START = "2000-01-01"
MAX_AGE_HOURS = 6.0
BAR_COLUMNS = ["open", "high", "low", "close", "volume", "dividend"]
PENCE = {"GBp": ("GBP", 0.01), "GBX": ("GBP", 0.01), "ZAc": ("ZAR", 0.01), "ILA": ("ILS", 0.01)}
# Série FRED du taux court de chaque devise (si FRED_API_KEY est défini).
FRED_RATE_SERIES = {"USD": "SOFR", "EUR": "ECBESTRVOLWGTTRMDMNRT", "GBP": "IUDSOIA"}


def iso_currency(raw: str | None) -> tuple[str | None, float]:
    """(devise ISO, facteur d'échelle) : les cours en pence deviennent des livres."""
    if raw is None:
        return None, 1.0
    return PENCE.get(raw, (raw, 1.0))


def download_bars(symbol: str, start: str | None = None) -> tuple[pd.DataFrame | None, str | None]:
    """(barres, devise brute) depuis Yahoo, ou (None, None). Frontière fournisseur :
    un symbole en échec ne casse jamais une page."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        raw = ticker.history(start=start or HISTORY_START, auto_adjust=False, actions=True)
        if raw is None or raw.empty:
            return None, None
        currency = (ticker.history_metadata or {}).get("currency")
    except Exception as exc:  # noqa: BLE001 -- frontière fournisseur
        print(f"  [WARN] yfinance {symbol}: {str(exc)[:100]}")
        return None, None
    df = raw.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close",
                             "Volume": "volume", "Dividends": "dividend"})
    for col in BAR_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    df = df[BAR_COLUMNS].dropna(subset=["close"])
    idx = pd.DatetimeIndex(df.index)
    df.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    return df[~df.index.duplicated(keep="last")].sort_index(), currency


def save_bars(conn: sqlite3.Connection, symbol: str, df: pd.DataFrame, raw_currency: str | None,
              now: dt.datetime | None = None) -> None:
    currency, scale = iso_currency(raw_currency)
    rows = []
    for day, r in df.iterrows():
        px = [None if pd.isna(r[c]) else float(r[c]) * scale for c in ("open", "high", "low", "close")]
        rows.append((symbol, day.date().isoformat(), *px, float(r["volume"]) if not pd.isna(r["volume"]) else 0.0,
                     float(r["dividend"]) * scale if not pd.isna(r["dividend"]) else 0.0))
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    with conn:
        conn.executemany(
            "INSERT INTO fund_price (symbol, day, open, high, low, close, volume, dividend) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(symbol, day) DO UPDATE SET open = excluded.open, "
            "high = excluded.high, low = excluded.low, close = excluded.close, volume = excluded.volume, "
            "dividend = excluded.dividend", rows)
        conn.execute(
            "INSERT INTO fund_price_meta (symbol, currency, refreshed_at) VALUES (?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET currency = COALESCE(excluded.currency, fund_price_meta.currency), "
            "refreshed_at = excluded.refreshed_at", (symbol, currency, stamp))


def load_bars(conn: sqlite3.Connection, symbol: str) -> pd.DataFrame | None:
    rows = conn.execute("SELECT day, open, high, low, close, volume, dividend FROM fund_price "
                        "WHERE symbol = ? ORDER BY day", (symbol,)).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["day", *BAR_COLUMNS])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("day")))
    return df


def get_meta(conn: sqlite3.Connection, symbol: str) -> dict | None:
    row = conn.execute("SELECT currency, refreshed_at FROM fund_price_meta WHERE symbol = ?", (symbol,)).fetchone()
    return {"currency": row[0], "refreshed_at": row[1]} if row else None


@dataclass
class BarsResult:
    df: pd.DataFrame | None
    currency: str | None
    status: str          # fresh | stored | missing


def ensure_bars(conn: sqlite3.Connection, symbol: str, *, max_age_hours: float = MAX_AGE_HOURS,
                now: dt.datetime | None = None) -> BarsResult:
    """Rafraîchit `symbol` si la dernière actualisation a plus de `max_age_hours`.
    Hors ligne ou symbole retiré : on sert ce qui est stocké."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stored, meta = load_bars(conn, symbol), get_meta(conn, symbol)
    if stored is not None and meta and meta["refreshed_at"]:
        age = now - dt.datetime.strptime(meta["refreshed_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
        if age < dt.timedelta(hours=max_age_hours):
            return BarsResult(stored, meta["currency"], "fresh")
    start = (stored.index[-1] - pd.Timedelta(days=7)).date().isoformat() if stored is not None else None
    fetched, raw_ccy = download_bars(symbol, start)
    if fetched is not None and not fetched.empty:
        save_bars(conn, symbol, fetched, raw_ccy, now)
        return BarsResult(load_bars(conn, symbol), get_meta(conn, symbol)["currency"], "fresh")
    if stored is not None:
        return BarsResult(stored, meta["currency"] if meta else None, "stored")
    return BarsResult(None, None, "missing")


def fx_symbol(base: str, currency: str) -> str:
    return f"{base}{currency}=X"


def fx_series(conn: sqlite3.Connection, base: str, currency: str) -> pd.Series | None:
    """Unités de `base` par unité de `currency` (inverse du cours Yahoo EURUSD=X)."""
    res = ensure_bars(conn, fx_symbol(base, currency))
    if res.df is None or res.df.empty:
        return None
    return (1.0 / res.df["close"]).rename(currency)


def reference_rates(currencies: set[str]) -> tuple[dict[str, float], list[str]]:
    """Taux court annuel par devise (FRED si FRED_API_KEY est défini, sinon constantes
    de `engine.DEFAULT_REF_RATES`) et avertissements à afficher."""
    rates: dict[str, float] = {}
    notes: list[str] = []
    for ccy in sorted(currencies):
        value = None
        if os.environ.get("FRED_API_KEY") and ccy in FRED_RATE_SERIES:
            from patrick.data.sources import fred_source
            s = fred_source.download_series(ccy, FRED_RATE_SERIES[ccy], "2024-01-01")
            if s is not None and len(s.dropna()):
                value = float(s.dropna().iloc[-1]) / 100.0
        if value is None:
            value = DEFAULT_REF_RATES.get(ccy, 0.03)
            notes.append(f"taux de référence {ccy} : constante {value:.2%} (FRED indisponible ou non configuré)")
        rates[ccy] = value
    return rates, notes


def build_market(conn: sqlite3.Connection, orders: list[dict], base: str = "EUR",
                 with_rates: bool = True) -> tuple[MarketData, list[str]]:
    """Données de marché pour rejouer `orders` : barres de chaque symbole, change de
    chaque devise étrangère, taux de référence des devises des CFD."""
    market = MarketData(base_currency=base)
    notes: list[str] = []
    currencies: set[str] = set()
    cfd_currencies: set[str] = set()
    for o in orders:
        sym = o["symbol"]
        if sym not in market.bars:
            res = ensure_bars(conn, sym)
            if res.df is None:
                notes.append(f"{sym} : aucune cotation disponible")
                continue
            market.bars[sym] = res.df
            if res.status == "stored":
                notes.append(f"{sym} : cotations hors ligne (dernière donnée stockée {res.df.index[-1].date()})")
        currencies.add(o["currency"])
        if o["instrument_kind"] == "cfd":
            cfd_currencies.add(o["currency"])
    for ccy in sorted(currencies - {base}):
        s = fx_series(conn, base, ccy)
        if s is None:
            notes.append(f"change {base}/{ccy} indisponible")
        else:
            market.fx[ccy] = s
    if with_rates and cfd_currencies:
        market.ref_rates, rate_notes = reference_rates(cfd_currencies)
        notes.extend(rate_notes)
    return market, notes
```

- [ ] **Step 4 : Vérifier**

```bash
$PY -m pytest tests/test_fund_prices.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_prices.py tests/fund_support.py
```

Résultat attendu : tests verts, ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/prices.py tests/fund_support.py tests/test_fund_prices.py
git commit -m "feat(fund): cotations persistantes, change, pence, taux de référence" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6 : Règles d'enveloppe, validation chronologique et KPI

**Files:**
- Create: `patrick/patrick/fund/rules.py`, `patrick/patrick/fund/kpis.py`
- Test: `patrick/tests/test_fund_rules_kpis.py`

**Interfaces:**
- Consumes (Tasks 3, 4) : `engine.simulate`, `engine.MarketData`, `engine.EQUITY_KINDS/DERIV_KINDS`, `instruments.cfd_leverage_cap`, `wealth.ledger.PEA_LIKELY_ELIGIBLE_SUFFIXES`.
- Produces : `rules.Check(blocking: list[str], warnings: list[str])` ; `rules.static_checks(strategy, order, today) -> Check` ; `rules.validate(strategy, orders, candidate, market, today, baseline=None) -> (Check, SimResult)` — `orders` = chronologie **sans** le candidat ; un candidat portant un `order_id` déjà présent le remplace (correction) ; seules les violations **nouvelles** par rapport à la chronologie existante bloquent. `kpis.compute(strategy, result) -> dict` (clés `nav, capital, pnl, pnl_pct, realized, latent, fees, dividends, financing, twr, volatility, sharpe, max_drawdown, gross_exposure_pct, net_exposure_pct, leverage, margin_used, buying_power, cash, n_open_positions`) ; `kpis.series_points(daily, columns=("nav", "cash")) -> list[{"t", ...}]`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `patrick/tests/test_fund_rules_kpis.py` :

```python
"""Règles d'enveloppe (statiques et chronologiques) et KPI d'une stratégie."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from patrick.fund import engine, kpis, rules

DAYS = pd.bdate_range("2026-01-05", periods=10)
TODAY = dt.date(2026, 1, 16)
CTO = {"strategy_id": "s", "wrapper": "CTO", "opened_on": "2026-01-05", "initial_capital": 100_000.0}
PEA = {**CTO, "wrapper": "PEA"}


def bars(closes):
    n = len(closes)
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                         "volume": [1e6] * n, "dividend": [0.0] * n}, index=DAYS[:n])


def order(**kw):
    base = {"order_id": 1, "strategy_id": "s", "position_id": "p1", "ts": "2026-01-06", "action": "open",
            "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 10.0, "price": 100.0,
            "currency": "EUR", "fx_rate": 1.0, "fees": 0.0, "spec": {}}
    base.update(kw)
    return base


def test_static_checks_for_a_clean_cto_order():
    chk = rules.static_checks(CTO, order(), TODAY)
    assert chk.blocking == [] and chk.warnings == []


@pytest.mark.parametrize("strategy, overrides, expected", [
    (CTO, {"ts": "2026-02-01"}, "futur"),
    (CTO, {"ts": "2026-01-02"}, "antérieure à l'ouverture"),
    (CTO, {"quantity": 0}, "quantité"),
    (CTO, {"price": None}, "prix indisponible"),
    (CTO, {"side": "short"}, "découvert"),
    (CTO, {"instrument_kind": "etf", "side": "short"}, "découvert"),
    (PEA, {"instrument_kind": "future", "side": "long"}, "ni future ni CFD"),
    (PEA, {"instrument_kind": "cfd"}, "ni future ni CFD"),
    (PEA, {"currency": "USD"}, "euro"),
    (PEA, {"side": "short"}, "longues seulement"),
    (CTO, {"instrument_kind": "cfd", "symbol": "^GSPC", "spec": {"leverage": 25}}, "plafond 20:1"),
    (CTO, {"instrument_kind": "cfd", "symbol": "AAPL", "spec": {"leverage": 6}}, "plafond 5:1"),
    (CTO, {"instrument_kind": "cfd", "symbol": "AAPL", "spec": {"leverage": 0.5}}, "levier minimal"),
])
def test_static_blocking_rules(strategy, overrides, expected):
    chk = rules.static_checks(strategy, order(**overrides), TODAY)
    assert any(expected in m for m in chk.blocking), chk.blocking


def test_modify_needs_neither_price_nor_quantity_but_still_caps_leverage():
    ok = order(action="modify", quantity=0.0, price=None, instrument_kind="cfd", symbol="^GSPC",
               spec={"stop": 4000.0})
    assert rules.static_checks(CTO, ok, TODAY).blocking == []
    too_much = order(action="modify", quantity=0.0, price=None, instrument_kind="cfd", symbol="^GSPC",
                     spec={"leverage": 50})
    assert any("plafond" in m for m in rules.static_checks(CTO, too_much, TODAY).blocking)


def test_pea_warns_on_a_probably_ineligible_venue_but_does_not_block():
    chk = rules.static_checks(PEA, order(symbol="AAPL"), TODAY)
    assert chk.blocking == [] and any("non éligible" in m for m in chk.warnings)
    assert rules.static_checks(PEA, order(symbol="MC.PA"), TODAY).warnings == []


def test_validate_replays_the_whole_timeline_and_keeps_only_new_violations():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    small_cap = {**CTO, "initial_capital": 10_000.0}
    later = order(order_id=1, ts="2026-01-12", quantity=95.0)                # 9 500 EUR : tient dans le capital
    chk, _ = rules.validate(small_cap, [later], order(order_id=None, position_id="p2", ts="2026-01-07",
                                                       quantity=20.0), market, TODAY)
    assert any("insuffisant" in m for m in chk.blocking)                      # l'ordre antidaté casse celui du 12
    ok, result = rules.validate(small_cap, [later], order(order_id=None, position_id="p2", ts="2026-01-13",
                                                           quantity=1.0), market, TODAY)
    assert ok.blocking == [] and result.positions


def test_validate_ignores_violations_that_already_exist():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    oversold = [order(order_id=1, quantity=5.0),
                order(order_id=2, ts="2026-01-07", action="reduce", quantity=50.0)]   # anomalie déjà présente
    candidate = order(order_id=None, position_id="p2", ts="2026-01-13", quantity=1.0)
    assert rules.validate(CTO, oversold, candidate, market, TODAY)[0].blocking == []
    overdrawn = [order(order_id=1, quantity=5000.0)]          # capital dépassé : tout nouvel ordre est refusé
    assert any("insuffisant" in m for m in rules.validate(CTO, overdrawn, candidate, market, TODAY)[0].blocking)


def test_validate_replaces_the_corrected_order_instead_of_duplicating_it():
    market = engine.MarketData(bars={"MC.PA": bars([100.0] * 10)})
    existing = order(order_id=7, quantity=5.0)
    chk, result = rules.validate(CTO, [existing], order(order_id=7, quantity=8.0), market, TODAY)
    assert chk.blocking == [] and result.positions[0]["quantity"] == 8.0 and len(result.positions) == 1


def test_validate_warns_when_net_value_falls_below_half_the_required_margin():
    spec = {"multiplier": 50.0, "margin_per_unit": 20_000.0, "expiry": "2026-06-19",
            "fee_ctx": {"commission_per_contract_base": 2.0, "tick_bps": 0.5}}
    market = engine.MarketData(bars={"FUT": bars([5000.0] * 3 + [4000.0] * 7)})
    cand = order(order_id=None, instrument_kind="future", symbol="FUT", side="long", quantity=4.0, price=5000.0,
                 spec=spec)
    small = {**CTO, "initial_capital": 90_000.0}
    chk, _ = rules.validate(small, [], cand, market, TODAY)
    assert any("50 %" in m for m in chk.warnings)


def _result(closes, quantity=10.0):
    market = engine.MarketData(bars={"MC.PA": bars(closes)})
    return engine.simulate(CTO, [order(quantity=quantity)], market, "2026-01-16")


def test_kpis_of_a_simple_long_position():
    res = _result([100, 100, 102, 101, 105, 104, 108, 107, 110, 112])
    k = kpis.compute(CTO, res)
    assert k["nav"] == pytest.approx(100_000 + 10 * 12) and k["pnl"] == pytest.approx(120.0)
    assert k["pnl_pct"] == pytest.approx(0.0012) and k["twr"] == pytest.approx(0.0012)
    assert k["latent"] == pytest.approx(120.0) and k["realized"] == 0.0 and k["n_open_positions"] == 1
    assert k["gross_exposure_pct"] == pytest.approx(1120 / 100_120) and k["leverage"] == k["gross_exposure_pct"]
    assert k["max_drawdown"] <= 0 and k["volatility"] > 0 and k["margin_used"] == 0.0
    assert k["buying_power"] == pytest.approx(100_000 - 1000)


def test_kpis_of_a_strategy_without_orders_are_neutral_and_json_safe():
    market = engine.MarketData()
    k = kpis.compute(CTO, engine.simulate(CTO, [], market, "2026-01-16"))
    assert k["nav"] == 100_000 and k["pnl"] == 0 and k["n_open_positions"] == 0
    assert k["sharpe"] is None and k["volatility"] in (None, 0.0)
    assert k["cash"] == 100_000 and k["gross_exposure_pct"] == 0


def test_series_points_are_rounded_and_dated():
    res = _result([100.0] * 10)
    pts = kpis.series_points(res.daily)
    assert pts[0] == {"t": "2026-01-05", "nav": 100000.0, "cash": 100000.0} and len(pts) == 10
    assert kpis.series_points(pd.DataFrame()) == []
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_rules_kpis.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.rules`.

- [ ] **Step 3 : Implémenter `rules.py` et `kpis.py`**

```python
"""Règles d'enveloppe et de marge (spec §9).

Deux étages : `static_checks` (propres à l'ordre : sens, type, devise,
plafond de levier) et `validate`, qui rejoue TOUTE la chronologie de la
stratégie avec l'ordre candidat et ne retient que les violations nouvelles
par rapport à la chronologie existante -- un ordre antidaté est refusé s'il
invalide un événement postérieur, sans que d'anciennes anomalies de données
bloquent définitivement la stratégie."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from patrick.fund import engine, instruments
from patrick.wealth.ledger import PEA_LIKELY_ELIGIBLE_SUFFIXES


@dataclass
class Check:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def static_checks(strategy: dict, order: dict, today: dt.date) -> Check:
    chk = Check()
    action, kind, side = order["action"], order["instrument_kind"], order["side"]
    spec = order.get("spec") or {}
    if order["ts"] > today.isoformat():
        chk.blocking.append("date d'exécution dans le futur")
    if order["ts"] < strategy["opened_on"]:
        chk.blocking.append(f"date antérieure à l'ouverture de la stratégie ({strategy['opened_on']})")
    if action in ("open", "increase", "reduce") and not (order.get("quantity") and order["quantity"] > 0):
        chk.blocking.append("quantité strictement positive requise")
    if action != "modify" and not (order.get("price") and order["price"] > 0):
        chk.blocking.append("prix indisponible")
    if kind in engine.EQUITY_KINDS and side == "short":
        chk.blocking.append("vente à découvert impossible sur action/ETF (compte comptant) : passer par un CFD "
                            "ou un future")
    if strategy["wrapper"] == "PEA":
        if side == "short":
            chk.blocking.append("PEA : positions longues seulement")
        if kind in engine.DERIV_KINDS:
            chk.blocking.append("PEA : ni future ni CFD")
        if order["currency"] != "EUR":
            chk.blocking.append("PEA : titres cotés en euro seulement")
        if kind in engine.EQUITY_KINDS and not order["symbol"].endswith(PEA_LIKELY_ELIGIBLE_SUFFIXES):
            chk.warnings.append(f"PEA : {order['symbol']} probablement non éligible (place hors UE/EEE)")
    if kind == "cfd" and action in ("open", "modify") and spec.get("leverage") is not None:
        cap = instruments.cfd_leverage_cap(order["symbol"])
        if float(spec["leverage"]) > cap:
            chk.blocking.append(f"CFD : levier {float(spec['leverage']):g}:1 > plafond {cap:g}:1 pour cette classe "
                                "d'actifs (client non professionnel)")
        if float(spec["leverage"]) < 1:
            chk.blocking.append("CFD : levier minimal 1:1")
    return chk


def validate(strategy: dict, orders: list[dict], candidate: dict, market: engine.MarketData, today: dt.date,
             baseline: engine.SimResult | None = None) -> tuple[Check, engine.SimResult]:
    """`orders` = chronologie SANS le candidat ; si le candidat porte un `order_id`
    déjà présent dans `orders`, il le remplace (correction)."""
    chk = static_checks(strategy, candidate, today)
    cid = candidate.get("order_id")
    timeline = [o for o in orders if cid is None or o.get("order_id") != cid] + [candidate]
    result = engine.simulate(strategy, timeline, market, end=today)
    if baseline is None:
        baseline = engine.simulate(strategy, orders, market, end=today)
    known = {v["message"] for v in baseline.violations}
    chk.blocking.extend(v["message"] for v in result.violations if v["message"] not in known)
    if result.alert_days:
        chk.warnings.append(f"marge : la valeur nette passe sous 50 % de la marge requise "
                            f"({len(result.alert_days)} jour(s), dès le {result.alert_days[0]})")
    return chk, result
```

```python
"""KPI d'une stratégie à partir du résultat du moteur (spec §10)."""
from __future__ import annotations

import math

import pandas as pd

from patrick.fund.engine import SimResult
from patrick.simulate import metrics as simmetrics


def _num(value) -> float | None:
    if value is None:
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def compute(strategy: dict, result: SimResult) -> dict:
    capital = float(strategy["initial_capital"])
    daily = result.daily
    positions = result.positions
    open_positions = [p for p in positions if p["status"] == "open"]
    if daily.empty:
        nav = capital
        last: dict = {}
    else:
        nav = float(daily["nav"].iloc[-1])
        last = daily.iloc[-1].to_dict()
    pnl = nav - capital
    returns = daily["nav"].pct_change().dropna() if len(daily) > 1 else pd.Series(dtype=float)
    max_dd = simmetrics.max_drawdown(daily["nav"])[0] if len(daily) > 1 else float("nan")
    gross = float(last.get("gross_exposure", 0.0))
    net = float(last.get("net_exposure", 0.0))
    return {
        "nav": nav, "capital": capital, "pnl": pnl, "pnl_pct": pnl / capital,
        "realized": sum(p["realized"] for p in positions),
        "latent": sum(p["latent"] for p in open_positions),
        "fees": float(last.get("fees_cum", 0.0)), "dividends": float(last.get("dividends_cum", 0.0)),
        "financing": float(last.get("financing_cum", 0.0)),
        "twr": pnl / capital,    # aucun flux externe au chantier 1 : le TWR égale le rendement sur capital
        "volatility": _num(simmetrics.annualized_vol(returns)),
        "sharpe": _num(simmetrics.sharpe_ratio(returns)),
        "max_drawdown": _num(max_dd),
        "gross_exposure_pct": gross / nav if nav > 0 else None,
        "net_exposure_pct": net / nav if nav > 0 else None,
        "leverage": gross / nav if nav > 0 else None,
        "margin_used": float(last.get("margin_used", 0.0)),
        "buying_power": float(last.get("buying_power", capital)),
        "cash": float(last.get("cash", capital)),
        "n_open_positions": len(open_positions),
    }


def series_points(daily: pd.DataFrame, columns=("nav", "cash")) -> list[dict]:
    if daily.empty:
        return []
    out = []
    for day, row in daily.iterrows():
        out.append({"t": day.date().isoformat(), **{c: round(float(row[c]), 4) for c in columns}})
    return out
```

- [ ] **Step 4 : Vérifier**

```bash
$PY -m pytest tests/test_fund_rules_kpis.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_rules_kpis.py
```

Résultat attendu : tests verts, ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/rules.py patrick/fund/kpis.py tests/test_fund_rules_kpis.py
git commit -m "feat(fund): règles PEA/CTO, validation chronologique et KPI de stratégie" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7 : Service — aperçu, ordres, correction, instantanés

**Files:**
- Create: `patrick/patrick/fund/service.py`
- Test: `patrick/tests/test_fund_service.py`

**Interfaces:**
- Consumes (Tasks 1–6) : `store`, `prices.ensure_bars/fx_series/build_market`, `fees`, `instruments`, `engine`, `rules.validate`, `kpis`.
- Produces (`patrick.fund.service`) :
  - `FundRuleError(blocking: list[str])` ; `current_date() -> date` (date du jour, **fonction patchable** par les tests de routes).
  - `quote(conn, req, today=None) -> dict` : `{"ok", "blocking", "warnings", "order", "preview"}` ; ne lève jamais pour une saisie incomplète (les motifs sont dans `blocking`). `preview` : `symbol, exec_day, price, price_source, currency, fx_rate, quantity, notional_local, notional_base, margin_required, fees{total, source, seed, commission, spread, fx}, buying_power_after, cash_after, provisional, position_id, underlying_class, leverage_cap`.
  - `place_order(conn, req, today=None) -> {"order_id", ...quote}` (lève `FundRuleError` si refus, `store.FundError` pour une saisie invalide) ; `correct_order(conn, order_id, req, today=None)` (ordre d'ouverture uniquement) ; `strategy_snapshot(conn, strategy, today=None) -> dict` (`strategy, kpis, positions, series, orders, notes, violations, alert_days`) ; `overview(conn, today=None) -> {"strategies": [snapshot], "fund": {nav, capital, pnl, pnl_pct, n_strategies}}`.
  - Requête (`req`) : `strategy_id`, `action` (`open` par défaut), `position_id`, `instrument_kind`, `symbol` (ou `spec.root/year/month` pour un future), `side`, `quantity` ou `amount`, `date`, `price` (manuel), `fees_mode` (`estimated`|`manual`), `fees`, `fee_seed`, `spec{leverage, stop, target}`.

- [ ] **Step 1 : Écrire les tests qui échouent**

Créer `patrick/tests/test_fund_service.py` :

```python
"""Cas d'usage du fonds : aperçu et passage d'ordres, correction, instantanés. Aucun réseau."""
from __future__ import annotations

import datetime as dt

import fund_support as fs
import pytest

from patrick.fund import service, store

TODAY = dt.date(2026, 1, 16)


@pytest.fixture(autouse=True)
def _quotes(monkeypatch):
    fs.install(monkeypatch)


def cto(conn, capital=100_000):
    return store.create_strategy(conn, "Macro CTO", "CTO", capital, "2026-01-05")


def equity(sid, symbol="MC.PA", **kw):
    return {"strategy_id": sid, "instrument_kind": "equity", "symbol": symbol, "side": "long",
            "date": "2026-01-07", **kw}


def es_future(sid, **kw):
    return {"strategy_id": sid, "instrument_kind": "future", "side": "short", "quantity": 2, "date": "2026-01-07",
            "spec": {"root": "ES", "year": 2026, "month": 12}, **kw}


def test_equity_quote_then_place_records_the_quoted_fees(conn):
    sid = cto(conn)
    req = equity(sid, "AAPL", amount=5000, fees_mode="estimated")
    q = service.quote(conn, req, TODAY)
    assert q["ok"], q["blocking"]
    pv = q["preview"]
    fx, price = fs.fx_on("2026-01-07"), fs.price_on("AAPL", "2026-01-07")
    assert pv["quantity"] == int(5000 // (price * fx)) and pv["currency"] == "USD"
    assert pv["fx_rate"] == pytest.approx(fx) and pv["fees"]["source"] == "estimated" and pv["fees"]["fx"] > 0
    assert pv["cash_after"] == pytest.approx(100_000 - pv["quantity"] * price * fx - pv["fees"]["total"])
    placed = service.place_order(conn, {**req, "fee_seed": pv["fees"]["seed"], "position_id": pv["position_id"]}, TODAY)
    assert placed["preview"]["fees"]["total"] == pv["fees"]["total"]
    assert store.list_orders(conn, sid)[0]["fees"] == pv["fees"]["total"]
    assert store.list_orders(conn, sid)[0]["position_id"] == pv["position_id"]


def test_manual_fees_and_manual_price(conn):
    sid = cto(conn)
    pv = service.place_order(conn, equity(sid, quantity=3, price=650.0, fees_mode="manual", fees=7.5), TODAY)["preview"]
    assert pv["price"] == 650.0 and pv["price_source"] == "manual"
    assert pv["fees"]["total"] == 7.5 and pv["fees"]["source"] == "manual"
    bad = service.quote(conn, equity(sid, quantity=3, fees_mode="manual", fees=-1), TODAY)
    assert not bad["ok"] and "frais manuels" in bad["blocking"][0]


def test_a_date_between_sessions_executes_on_the_next_trading_day(conn):
    sid = cto(conn)
    pv = service.quote(conn, equity(sid, quantity=1, date="2026-01-10"), TODAY)["preview"]      # un samedi
    assert pv["exec_day"] == "2026-01-12" and pv["price"] == pytest.approx(fs.price_on("MC.PA", "2026-01-12"))
    assert pv["provisional"] is False
    today_quote = service.quote(conn, equity(sid, quantity=1, date="2026-01-16"), dt.date(2026, 10, 2))["preview"]
    assert today_quote["exec_day"] == "2026-01-16" and today_quote["provisional"] is False
    last = service.quote(conn, equity(sid, quantity=1, date="2026-10-02"), dt.date(2026, 10, 2))["preview"]
    assert last["provisional"] is True                                  # dernier cours d'aujourd'hui


def test_sizes_that_cannot_be_traded_are_refused_with_a_reason(conn):
    sid = cto(conn)
    tiny = service.quote(conn, equity(sid, amount=100), TODAY)                         # < 1 action à 700 €
    assert not tiny["ok"] and "montant insuffisant" in tiny["blocking"][0]
    assert "quantité ou montant" in service.quote(conn, equity(sid), TODAY)["blocking"][0]
    assert "quantité entière" in service.quote(conn, es_future(sid, quantity=1.5), TODAY)["blocking"][0]
    assert "quantité entière" in service.quote(conn, equity(sid, quantity=0.4), TODAY)["blocking"][0]
    assert "invalide" in service.quote(conn, equity(sid, quantity="abc"), TODAY)["blocking"][0]


def test_future_date_unknown_symbol_and_unknown_strategy_are_refused(conn):
    sid = cto(conn)
    q = service.quote(conn, equity(sid, quantity=1, date="2026-02-20"), TODAY)
    assert not q["ok"] and "futur" in q["blocking"][0]
    q = service.quote(conn, equity(sid, "ZZZZ", quantity=1), TODAY)
    assert not q["ok"] and "aucune cotation" in q["blocking"][0]
    q = service.quote(conn, equity(sid, quantity=1, date="2025-06-03"), TODAY)
    assert not q["ok"] and "antérieure à l'ouverture" in q["blocking"][0]
    q = service.quote(conn, equity(sid, quantity=1, date="2025-05-01"), TODAY)
    assert not q["ok"] and "pas de cotation avant le 2025-06-02" in q["blocking"][0]
    q = service.quote(conn, equity("nope", quantity=1), TODAY)
    assert not q["ok"] and "introuvable" in q["blocking"][0]
    with pytest.raises(store.FundError, match="introuvable"):
        service.place_order(conn, equity("nope", quantity=1), TODAY)
    with pytest.raises(service.FundRuleError) as exc:
        service.place_order(conn, equity(sid, "ZZZZ", quantity=1), TODAY)
    assert "aucune cotation" in exc.value.blocking[0]


def test_pea_blocks_short_usd_and_derivatives_but_warns_on_eligibility(conn):
    sid = store.create_strategy(conn, "PEA", "PEA", 50_000, "2026-01-05")
    q_usd = service.quote(conn, equity(sid, "AAPL", quantity=2), TODAY)
    assert not q_usd["ok"] and any("euro" in m for m in q_usd["blocking"])
    assert any("probablement non éligible" in m for m in q_usd["warnings"])
    q_short = service.quote(conn, equity(sid, quantity=2, side="short"), TODAY)
    assert any("longues seulement" in m for m in q_short["blocking"])
    assert any("ni future ni CFD" in m for m in service.quote(conn, es_future(sid), TODAY)["blocking"])
    ok = service.quote(conn, equity(sid, quantity=2), TODAY)
    assert ok["ok"] and not ok["warnings"]


def test_cto_blocks_equity_short_and_excess_cfd_leverage_and_reports_the_cap(conn):
    sid = cto(conn)
    short = service.quote(conn, equity(sid, quantity=1, side="short"), TODAY)
    assert any("découvert" in m for m in short["blocking"])
    cfd = {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long", "quantity": 1,
           "date": "2026-01-07", "spec": {"leverage": 30}}
    q = service.quote(conn, cfd, TODAY)
    assert any("plafond 20:1" in m for m in q["blocking"]) and q["preview"]["leverage_cap"] == 20.0
    assert q["preview"]["underlying_class"] == "index_major"
    cfd["spec"]["leverage"] = 20
    ok = service.quote(conn, cfd, TODAY)
    assert ok["ok"] and ok["preview"]["margin_required"] == pytest.approx(
        ok["preview"]["notional_base"] / 20)


def test_cfd_without_a_leverage_defaults_to_the_lower_of_the_cap_and_five(conn):
    sid = cto(conn)
    q = service.quote(conn, {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "short",
                             "quantity": 1, "date": "2026-01-07"}, TODAY)
    assert q["ok"] and q["order"]["spec"]["leverage"] == 5.0


def test_future_preview_reports_margin_notional_and_fixed_commission(conn):
    sid = cto(conn)
    q = service.quote(conn, es_future(sid), TODAY)
    assert q["ok"], q["blocking"]
    pv = q["preview"]
    assert pv["symbol"] == "ESZ26.CME" and pv["margin_required"] == pytest.approx(2 * 22000 * pv["fx_rate"])
    assert pv["notional_local"] == pytest.approx(2 * 50 * fs.price_on("ESZ26.CME", "2026-01-07"))
    assert pv["fees"]["commission"] == pytest.approx(2 * 2.0 * pv["fx_rate"])
    assert q["order"]["spec"]["expiry"] == "2026-12-18" and q["order"]["spec"]["multiplier"] == 50.0
    big = service.quote(conn, es_future(sid, quantity=6), TODAY)                  # 6 x 22 000 $ > 100 000 EUR
    assert not big["ok"] and any("insuffisant" in m for m in big["blocking"])


def test_future_and_unknown_root_and_month_are_refused(conn):
    sid = cto(conn)
    bad_root = es_future(sid, spec={"root": "XX", "year": 2026, "month": 12})
    assert "racine" in service.quote(conn, bad_root, TODAY)["blocking"][0]
    bad_month = es_future(sid, spec={"root": "ES", "year": 2026, "month": 11})
    assert "pas de contrat" in service.quote(conn, bad_month, TODAY)["blocking"][0]
    assert "instrument" in service.quote(conn, {"strategy_id": sid, "instrument_kind": "bond"}, TODAY)["blocking"][0]
    assert "sens" in service.quote(conn, equity(sid, quantity=1, side="sideways"), TODAY)["blocking"][0]


def test_stop_and_target_must_bracket_the_entry_price(conn):
    sid = cto(conn)
    price = fs.price_on("ESZ26.CME", "2026-01-07")
    long_bad = es_future(sid, side="long", spec={"root": "ES", "year": 2026, "month": 12, "stop": price + 10})
    assert "long : stop sous le prix" in service.quote(conn, long_bad, TODAY)["blocking"][0]
    short_bad = es_future(sid, spec={"root": "ES", "year": 2026, "month": 12, "target": price + 10})
    assert "short : stop au-dessus" in service.quote(conn, short_bad, TODAY)["blocking"][0]
    ok = es_future(sid, side="long", spec={"root": "ES", "year": 2026, "month": 12, "stop": price - 50,
                                           "target": price + 80})
    q = service.quote(conn, ok, TODAY)
    assert q["ok"] and q["order"]["spec"]["stop"] == price - 50 and q["order"]["spec"]["target"] == price + 80


def test_reduce_more_than_held_close_and_reopen_rules(conn):
    sid = cto(conn)
    pid = service.place_order(conn, equity(sid, quantity=4), TODAY)["preview"]["position_id"]
    reduce = {"strategy_id": sid, "action": "reduce", "position_id": pid, "date": "2026-01-09"}
    assert any("détenus" in m for m in service.quote(conn, {**reduce, "quantity": 9}, TODAY)["blocking"])
    assert "quantité requise" in service.quote(conn, reduce, TODAY)["blocking"][0]
    closed = service.place_order(conn, {"strategy_id": sid, "action": "close", "position_id": pid,
                                        "date": "2026-01-09"}, TODAY)
    assert closed["preview"]["quantity"] == 4 and closed["preview"]["fees"]["total"] > 0
    again = service.quote(conn, {"strategy_id": sid, "action": "increase", "position_id": pid, "quantity": 1,
                                 "date": "2026-01-12"}, TODAY)
    assert any("clôturée" in m for m in again["blocking"])
    unknown = service.quote(conn, {"strategy_id": sid, "action": "increase", "position_id": "nope", "quantity": 1,
                                   "date": "2026-01-12"}, TODAY)
    assert "position introuvable" in unknown["blocking"][0]
    assert "action inconnue" in service.quote(conn, {**reduce, "action": "explode"}, TODAY)["blocking"][0]
    snap = service.strategy_snapshot(conn, store.get_strategy(conn, sid), TODAY)
    assert [p["status"] for p in snap["positions"]] == ["closed"]


def test_modify_sets_a_stop_that_the_snapshot_reports(conn):
    sid = cto(conn)
    pid = service.place_order(conn, es_future(sid, side="long", quantity=1), TODAY)["preview"]["position_id"]
    mod = service.place_order(conn, {"strategy_id": sid, "action": "modify", "position_id": pid, "date": "2026-01-09",
                                     "spec": {"stop": 5500.0, "target": ""}}, TODAY)
    assert mod["preview"]["quantity"] == 0 and mod["preview"]["fees"]["total"] == 0 and mod["preview"]["price"] is None
    pos = service.strategy_snapshot(conn, store.get_strategy(conn, sid), TODAY)["positions"][0]
    assert pos["stop"] == 5500.0 and pos["target"] is None and pos["status"] == "open"


def test_backdated_order_that_breaks_a_later_one_is_refused(conn):
    sid = cto(conn, 10_000)
    service.place_order(conn, equity(sid, quantity=12, date="2026-01-12"), TODAY)           # ~ 8 800 EUR
    backdated = service.quote(conn, equity(sid, "TTE.PA", quantity=100), TODAY)
    assert not backdated["ok"] and any("insuffisant" in m for m in backdated["blocking"])


def test_correct_order_changes_the_opening_order_only(conn):
    sid = cto(conn)
    a = service.place_order(conn, equity(sid, "AAPL", quantity=10), TODAY)
    fut = service.place_order(conn, es_future(sid, quantity=1, date="2026-01-08"), TODAY)
    corrected = service.correct_order(conn, a["order_id"], {"quantity": 12, "date": "2026-01-08", "price": 190.0,
                                                            "fees_mode": "manual", "fees": 2.0}, TODAY)
    row = store.get_order(conn, a["order_id"])
    assert corrected["preview"]["quantity"] == 12 and row["quantity"] == 12 and row["ts"] == "2026-01-08"
    assert row["price"] == 190.0 and row["price_source"] == "manual" and row["fees"] == 2.0
    assert row["position_id"] == a["preview"]["position_id"] and len(store.list_orders(conn, sid)) == 2
    fut_fix = service.correct_order(conn, fut["order_id"], {"quantity": 2, "date": "2026-01-08"}, TODAY)
    assert fut_fix["preview"]["symbol"] == "ESZ26.CME" and store.get_order(conn, fut["order_id"])["quantity"] == 2
    reduce = service.place_order(conn, {"strategy_id": sid, "action": "reduce", "position_id": row["position_id"],
                                        "quantity": 1, "date": "2026-01-12"}, TODAY)
    with pytest.raises(store.FundError, match="ouverture"):
        service.correct_order(conn, reduce["order_id"], {"quantity": 1}, TODAY)
    with pytest.raises(service.FundRuleError):
        service.correct_order(conn, a["order_id"], {"quantity": 100_000, "date": "2026-01-08"}, TODAY)


def test_snapshot_and_overview_are_consistent_across_instruments(conn):
    sid = cto(conn)
    service.place_order(conn, equity(sid, "AAPL", quantity=10), TODAY)
    service.place_order(conn, es_future(sid, quantity=1, date="2026-01-08"), TODAY)
    service.place_order(conn, {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long",
                               "quantity": 3, "date": "2026-01-09", "spec": {"leverage": 10}}, TODAY)
    ov = service.overview(conn, TODAY)
    snap = ov["strategies"][0]
    assert not snap["violations"] and not snap["alert_days"]
    assert snap["kpis"]["nav"] - snap["kpis"]["capital"] == pytest.approx(sum(p["pnl"] for p in snap["positions"]))
    assert snap["kpis"]["n_open_positions"] == 3 and snap["kpis"]["margin_used"] > 0
    assert any("taux de référence" in n for n in snap["notes"])          # CFD en USD, FRED non configuré
    assert ov["fund"]["capital"] == 100_000 and ov["fund"]["n_strategies"] == 1 and len(snap["series"]) > 5
    assert ov["fund"]["pnl"] == pytest.approx(snap["kpis"]["pnl"])
    by_kind = {p["kind"]: p for p in snap["positions"]}
    assert by_kind["equity"]["currency"] == "USD" and by_kind["equity"]["fx_effect"] != 0
    assert by_kind["future"]["margin"] > 0 and by_kind["cfd"]["leverage"] == 10.0


def test_overview_of_an_empty_fund_and_a_strategy_without_orders(conn):
    assert service.overview(conn, TODAY) == {"strategies": [], "fund": {
        "nav": 0, "capital": 0, "pnl": 0, "pnl_pct": None, "n_strategies": 0}}
    cto(conn)
    snap = service.overview(conn, TODAY)["strategies"][0]
    assert snap["kpis"]["nav"] == 100_000 and snap["positions"] == [] and snap["orders"] == []


def test_modify_cfd_leverage_respects_the_cap(conn):
    sid = cto(conn)
    cfd = {"strategy_id": sid, "instrument_kind": "cfd", "symbol": "^GSPC", "side": "long", "quantity": 1,
           "date": "2026-01-07", "spec": {"leverage": 5}}
    pid = service.place_order(conn, cfd, TODAY)["preview"]["position_id"]
    modify = {"strategy_id": sid, "action": "modify", "position_id": pid, "date": "2026-01-09"}
    assert service.quote(conn, {**modify, "spec": {"leverage": 10}}, TODAY)["ok"]
    over = service.quote(conn, {**modify, "spec": {"leverage": 25}}, TODAY)
    assert not over["ok"] and any("plafond 20:1" in m for m in over["blocking"])
    keep = service.quote(conn, {**modify, "spec": {"leverage": ""}}, TODAY)
    assert keep["ok"] and "leverage" not in keep["order"]["spec"]
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_service.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.fund.service`.

- [ ] **Step 3 : Implémenter `service.py`**

Points de conception à ne pas casser : (1) la graine des frais est dérivée de `strategy_id|position_id|jour|numéro` et renvoyée à l'aperçu ; le client la renvoie à la validation, donc le montant affiché est celui qui est enregistré ; (2) `quote` rejoue toute la chronologie avec le candidat ; (3) `close` enregistre la quantité restante (le moteur ferme tout, quelle que soit la quantité).

```python
"""Cas d'usage du fonds : aperçu et passage d'ordres, correction, instantané
d'une stratégie, vue d'ensemble. Une fonction par écran/route ; la couche web
reste mince."""
from __future__ import annotations

import datetime as dt
import math
import sqlite3

import pandas as pd

from patrick.clock import utc_today
from patrick.fund import engine, instruments, kpis, prices, rules, store
from patrick.fund import fees as fees_mod

TICK_HALF = 0.5


class FundRuleError(ValueError):
    """Ordre refusé : `blocking` liste les motifs (422 à l'API)."""

    def __init__(self, blocking: list[str]):
        super().__init__("; ".join(blocking))
        self.blocking = blocking


def current_date() -> dt.date:
    """Date du jour, isolée pour que les tests de routes puissent la figer."""
    return utc_today()


def _today(today: dt.date | None) -> dt.date:
    return today or current_date()


def _opening(orders: list[dict], position_id: str) -> dict | None:
    return next((o for o in orders if o["position_id"] == position_id and o["action"] == "open"), None)


def _number(value, name: str, *, positive: bool = False) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(str(value).replace(",", ".").replace(" ", ""))
    except ValueError as exc:
        raise store.FundError(f"{name} invalide : {value!r}") from exc
    if not math.isfinite(out) or (positive and out <= 0):
        raise store.FundError(f"{name} invalide : {value!r}")
    return out


def _execution_day(df: pd.DataFrame, requested: str, today: dt.date) -> tuple[pd.Timestamp, bool]:
    day = pd.Timestamp(requested)
    if day.date() > today:
        raise FundRuleError(["date d'exécution dans le futur"])
    if day < df.index[0]:
        raise FundRuleError([f"pas de cotation avant le {df.index[0].date()} pour ce symbole"])
    i = df.index.searchsorted(day)
    exec_day = df.index[i] if i < len(df) else df.index[-1]
    return exec_day, exec_day.date() == today


def _prepare(conn: sqlite3.Connection, req: dict, today: dt.date, replace_order_id: int | None = None) -> dict:
    strategy = store.get_strategy(conn, req.get("strategy_id") or "")
    if strategy is None:
        raise store.FundError("stratégie introuvable")
    base = strategy["base_currency"]
    orders = store.list_orders(conn, strategy["strategy_id"])
    action = req.get("action") or "open"
    if action not in store.ACTIONS:
        raise store.FundError(f"action inconnue : {action!r}")
    req_spec = dict(req.get("spec") or {})
    position_id = req.get("position_id")
    fut = None
    if action == "open":
        kind, side = req.get("instrument_kind"), req.get("side")
        if kind not in store.INSTRUMENT_KINDS:
            raise store.FundError(f"type d'instrument inconnu : {kind!r}")
        if side not in ("long", "short"):
            raise store.FundError("sens requis : long ou short")
        if kind == "future":
            fut = instruments.FUTURES_CATALOG.get(str(req_spec.get("root") or ""))
            if fut is None:
                raise store.FundError("racine de future inconnue (voir le catalogue)")
            year, month = int(req_spec["year"]), int(req_spec["month"])
            if month not in fut.months:
                raise store.FundError(f"{fut.root} : pas de contrat en mois {month}")
            symbol = fut.yahoo_symbol(year, month)
        else:
            symbol = str(req.get("symbol") or "").strip().upper()
            if not symbol:
                raise store.FundError("symbole manquant")
        position_id = position_id or store.new_id("pos")
        opening = None
    else:
        opening = _opening(orders, position_id or "")
        if opening is None:
            raise store.FundError("position introuvable")
        kind, side, symbol = opening["instrument_kind"], opening["side"], opening["symbol"]
        if kind == "future":
            fut = instruments.FUTURES_CATALOG.get(opening["spec"].get("root"))

    bars = prices.ensure_bars(conn, symbol)
    if bars.df is None or bars.df.empty:
        raise FundRuleError([f"{symbol} : aucune cotation disponible"])
    currency = opening["currency"] if opening else bars.currency
    if not currency:
        raise FundRuleError([f"{symbol} : devise inconnue"])
    exec_day, provisional = _execution_day(bars.df, req.get("date") or today.isoformat(), today)
    manual_price = _number(req.get("price"), "prix", positive=True)
    price = manual_price if manual_price is not None else float(bars.df["close"].loc[exec_day])
    price_source = "manual" if manual_price is not None else "market"
    fx = 1.0
    if currency != base:
        series = prices.fx_series(conn, base, currency)
        if series is None or series[series.index <= exec_day].empty:
            raise FundRuleError([f"change {base}/{currency} indisponible"])
        fx = float(series[series.index <= exec_day].iloc[-1])

    mult = fut.multiplier if fut else 1.0
    quantity = _number(req.get("quantity"), "quantité", positive=True)
    amount = _number(req.get("amount"), "montant", positive=True)
    if action in ("open", "increase"):
        if kind in engine.EQUITY_KINDS and quantity is None and amount is not None:
            quantity = math.floor(amount / (price * fx))
            if quantity < 1:
                raise FundRuleError(["montant insuffisant pour une action entière"])
        if quantity is None:
            raise store.FundError("quantité ou montant requis")
        if kind in ("equity", "etf", "future"):
            if abs(quantity - round(quantity)) > 1e-9 or round(quantity) < 1:
                raise store.FundError("quantité entière >= 1 requise")
            quantity = float(round(quantity))
    elif action == "reduce" and quantity is None:
        raise store.FundError("quantité requise")
    elif action == "close" or action == "modify":
        quantity = 0.0

    # --- composantes
    spec: dict = {}
    fee_ctx: dict = dict(opening["spec"].get("fee_ctx", {})) if opening else {}
    if action == "open":
        if kind == "future":
            spec.update({"root": fut.root, "year": int(req_spec["year"]), "month": int(req_spec["month"]),
                         "multiplier": fut.multiplier, "margin_per_unit": fut.margin,
                         "expiry": fut.expiry(int(req_spec["year"]), int(req_spec["month"])).isoformat()})
            fee_ctx = {"commission_per_contract_base": fut.commission * fx,
                       "tick_bps": TICK_HALF * fut.tick_size / price * 1e4}
        elif kind == "cfd":
            cls = instruments.classify_cfd_underlying(symbol)
            cap = instruments.CFD_LEVERAGE_CAPS[cls]
            leverage = _number(req_spec.get("leverage"), "levier", positive=True) or min(cap, 5.0)
            spec.update({"leverage": leverage, "underlying_class": cls})
            fee_ctx = {"fee_class": instruments.CFD_FEE_CLASS[cls]}
            if symbol.endswith("=F"):
                spec["price_quality"] = "continuous_roll_unadjusted"
        if kind in engine.DERIV_KINDS:
            spec["fee_ctx"] = fee_ctx
    if kind in engine.DERIV_KINDS and action in ("open", "modify"):
        for key in ("stop", "target"):
            if key in req_spec:
                spec[key] = _number(req_spec[key], key, positive=True)
        if action == "modify" and req_spec.get("leverage") not in (None, ""):
            spec["leverage"] = _number(req_spec["leverage"], "levier", positive=True)
        ref = price if action == "open" else bars.df["close"].iloc[-1]
        stop, target = spec.get("stop"), spec.get("target")
        if action == "open":
            if side == "long" and ((stop and stop >= ref) or (target and target <= ref)):
                raise FundRuleError(["long : stop sous le prix et objectif au-dessus"])
            if side == "short" and ((stop and stop <= ref) or (target and target >= ref)):
                raise FundRuleError(["short : stop au-dessus du prix et objectif en dessous"])

    # --- frais
    n_orders = sum(1 for o in orders if o["position_id"] == position_id) + 1
    fee_seed = req.get("fee_seed")
    breakdown = None
    if action == "modify":
        fees, fees_source = 0.0, "manual"
    elif req.get("fees_mode") == "manual":
        fees = _number(req.get("fees"), "frais")
        if fees is None or fees < 0:
            raise store.FundError("frais manuels : montant >= 0 requis")
        fees_source = "manual"
    else:
        qty_for_fees = quantity if action != "close" else _remaining(conn, strategy, orders, position_id, today)
        adv = None
        vol = bars.df["volume"].tail(20).mean()
        if kind in engine.EQUITY_KINDS and vol and not math.isnan(vol):
            adv = float(vol) * price * fx
        ctx = fees_mod.FeeContext(kind=kind, notional_base=qty_for_fees * mult * price * fx, quantity=qty_for_fees,
                                  currency=currency, base_currency=base, adv_notional_base=adv, **fee_ctx)
        fee_seed = int(fee_seed) if fee_seed else fees_mod.make_seed(strategy["strategy_id"], position_id,
                                                                     exec_day.date().isoformat(), n_orders)
        breakdown = fees_mod.estimate_fees(ctx, fee_seed)
        fees, fees_source = breakdown.total, "estimated"

    if action == "close":
        quantity = _remaining(conn, strategy, orders, position_id, today)
    candidate = {
        "order_id": replace_order_id, "strategy_id": strategy["strategy_id"], "position_id": position_id,
        "ts": exec_day.date().isoformat(), "action": action, "instrument_kind": kind, "symbol": symbol,
        "side": side, "quantity": quantity, "price": None if action == "modify" else price,
        "price_source": None if action == "modify" else price_source, "currency": currency, "fx_rate": fx,
        "fees": fees, "fees_source": fees_source, "fee_seed": fee_seed, "spec": spec, "note": req.get("note"),
    }
    return {"strategy": strategy, "orders": orders, "candidate": candidate, "provisional": provisional,
            "breakdown": breakdown, "multiplier": mult, "opening": opening, "future": fut}


def _remaining(conn, strategy, orders, position_id, today) -> float:
    market, _ = prices.build_market(conn, [o for o in orders if o["position_id"] == position_id],
                                    strategy["base_currency"], with_rates=False)
    res = engine.simulate(strategy, orders, market, end=today)
    pos = next((p for p in res.positions if p["position_id"] == position_id), None)
    return float(pos["quantity"]) if pos else 0.0


def _evaluate(conn: sqlite3.Connection, prep: dict, today: dt.date) -> tuple[rules.Check, engine.SimResult, list[str]]:
    strategy, orders, cand = prep["strategy"], prep["orders"], prep["candidate"]
    market, notes = prices.build_market(conn, orders + [cand], strategy["base_currency"])
    check, result = rules.validate(strategy, orders, cand, market, today)
    return check, result, notes


def _preview(prep: dict, check: rules.Check, result: engine.SimResult, notes: list[str]) -> dict:
    c, mult = prep["candidate"], prep["multiplier"]
    price = c["price"]
    notional_local = None if price is None else c["quantity"] * mult * price
    notional_base = None if notional_local is None else notional_local * c["fx_rate"]
    margin = None
    if c["instrument_kind"] == "future":
        margin = c["quantity"] * prep["future"].margin * c["fx_rate"]
    elif c["instrument_kind"] == "cfd" and notional_base is not None:
        leverage = (c["spec"].get("leverage") or (prep["opening"] or {}).get("spec", {}).get("leverage") or 1.0)
        margin = notional_base / float(leverage)
    underlying = None
    if c["instrument_kind"] == "cfd":
        underlying = c["spec"].get("underlying_class") or (prep["opening"] or {}).get("spec", {}).get("underlying_class")
    day = pd.Timestamp(c["ts"])
    row = result.daily.loc[day] if day in result.daily.index else None
    b = prep["breakdown"]
    return {
        "ok": not check.blocking, "blocking": check.blocking, "warnings": check.warnings + notes,
        "order": {k: v for k, v in c.items() if k != "spec"} | {"spec": c["spec"]},
        "preview": {
            "symbol": c["symbol"], "exec_day": c["ts"], "price": price, "price_source": c["price_source"],
            "currency": c["currency"], "fx_rate": c["fx_rate"], "quantity": c["quantity"],
            "notional_local": notional_local, "notional_base": notional_base, "margin_required": margin,
            "fees": {"total": c["fees"], "source": c["fees_source"], "seed": c["fee_seed"],
                     "commission": b.commission if b else None, "spread": b.spread if b else None,
                     "fx": b.fx if b else None},
            "buying_power_after": None if row is None else float(row["buying_power"]),
            "cash_after": None if row is None else float(row["cash"]),
            "provisional": prep["provisional"], "position_id": c["position_id"],
            "underlying_class": underlying,
            "leverage_cap": instruments.CFD_LEVERAGE_CAPS.get(underlying) if underlying else None,
        },
    }


def quote(conn: sqlite3.Connection, req: dict, today: dt.date | None = None) -> dict:
    """Aperçu d'un ordre : ne bloque pas, n'écrit rien, renvoie motifs de refus et avertissements."""
    today = _today(today)
    try:
        prep = _prepare(conn, req, today, replace_order_id=req.get("order_id"))
    except FundRuleError as exc:
        return {"ok": False, "blocking": exc.blocking, "warnings": [], "order": None, "preview": None}
    except store.FundError as exc:       # saisie en cours : motif affiché, pas une erreur HTTP
        return {"ok": False, "blocking": [str(exc)], "warnings": [], "order": None, "preview": None}
    check, result, notes = _evaluate(conn, prep, today)
    return _preview(prep, check, result, notes)


def place_order(conn: sqlite3.Connection, req: dict, today: dt.date | None = None) -> dict:
    today = _today(today)
    prep = _prepare(conn, req, today)
    check, result, notes = _evaluate(conn, prep, today)
    if check.blocking:
        raise FundRuleError(check.blocking)
    order_id = store.insert_order(conn, prep["candidate"])
    return {"order_id": order_id, **_preview(prep, check, result, notes)}


def correct_order(conn: sqlite3.Connection, order_id: int, req: dict, today: dt.date | None = None) -> dict:
    """Corrige l'ordre d'ouverture d'une position (instrument et sens inchangés)."""
    today = _today(today)
    existing = store.get_order(conn, order_id)
    if existing is None or existing["action"] != "open":
        raise store.FundError("seul l'ordre d'ouverture d'une position peut être corrigé")
    merged = {**req, "strategy_id": existing["strategy_id"], "action": "open",
              "position_id": existing["position_id"], "instrument_kind": existing["instrument_kind"],
              "side": existing["side"], "symbol": existing["symbol"]}
    if existing["instrument_kind"] == "future":
        merged["spec"] = {**{k: existing["spec"][k] for k in ("root", "year", "month")}, **(req.get("spec") or {})}
    prep = _prepare(conn, merged, today, replace_order_id=order_id)
    check, result, notes = _evaluate(conn, prep, today)
    if check.blocking:
        raise FundRuleError(check.blocking)
    store.update_order(conn, order_id, prep["candidate"])
    return {"order_id": order_id, **_preview(prep, check, result, notes)}


# ------------------------------------------------------------- instantanés

def strategy_snapshot(conn: sqlite3.Connection, strategy: dict, today: dt.date | None = None) -> dict:
    today = _today(today)
    orders = store.list_orders(conn, strategy["strategy_id"])
    market, notes = prices.build_market(conn, orders, strategy["base_currency"])
    result = engine.simulate(strategy, orders, market, end=today)
    return {"strategy": strategy, "kpis": kpis.compute(strategy, result), "positions": result.positions,
            "series": kpis.series_points(result.daily), "orders": orders, "notes": notes,
            "violations": [v["message"] for v in result.violations],
            "alert_days": result.alert_days}


def overview(conn: sqlite3.Connection, today: dt.date | None = None) -> dict:
    snaps = [strategy_snapshot(conn, s, today) for s in store.list_strategies(conn)]
    capital = sum(s["kpis"]["capital"] for s in snaps)
    nav = sum(s["kpis"]["nav"] for s in snaps)
    return {"strategies": snaps,
            "fund": {"nav": nav, "capital": capital, "pnl": nav - capital,
                     "pnl_pct": (nav - capital) / capital if capital else None, "n_strategies": len(snaps)}}
```

- [ ] **Step 4 : Vérifier toute la couche serveur et le lint**

```bash
$PY -m pytest tests/test_fund_*.py -q -W ignore && $PY -m ruff check patrick/fund tests/test_fund_*.py tests/fund_support.py
```

Résultat attendu : tous les tests `test_fund_*` passent (store, fees, instruments, engine, prices, rules_kpis, service) ; ruff propre.

- [ ] **Step 5 : Commit**

```bash
git add patrick/fund/service.py tests/test_fund_service.py
git commit -m "feat(fund): service d'ordres (aperçu, passage, correction) et instantanés de stratégie" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8 : API `/api/fund/*` et enregistrement dans l'application

**Files:**
- Create: `patrick/patrick/webapp/fund_routes.py`
- Modify: `patrick/patrick/webapp/app.py` (import + enregistrement), `patrick/tests/fund_support.py` (date figée et aides)
- Test: `patrick/tests/test_fund_routes.py`

**Interfaces:**
- Consumes (Task 7) : `service.quote/place_order/correct_order/strategy_snapshot/overview/current_date`, `service.FundRuleError`, `store.*`, `instruments.listed_contracts`, `wealth.symbols.yahoo_search`.
- Produces (`patrick.webapp.fund_routes`) : `register(app, templates, context)` ; `search_symbols(query, kind) -> list[dict]` et `futures_payload(today) -> list[dict]` (fonctions de module, remplaçables par les tests). Routes :
  `GET /api/fund/overview` · `GET|PATCH|DELETE /api/fund/strategies/{id}` (detail / renommer-archiver / supprimer) · `POST /api/fund/strategies` · `GET /api/fund/instruments/search?q=&kind=` · `GET /api/fund/futures/catalog` · `POST /api/fund/quote` · `POST /api/fund/strategies/{id}/orders` · `PATCH /api/fund/orders/{id}` · `DELETE /api/fund/positions/{id}`. Refus de règle : 422 `{"detail": {"blocking": [...]}}` ; saisie invalide : 400 `{"detail": "..."}` ; ressource absente : 404.
- Produces (`tests/fund_support.py`) : `freeze_today(monkeypatch)` (fige `service.current_date` au 2026-01-16), `make_strategy(client, name=..., **kw) -> id`, `place(client, strategy_id, **kw) -> dict`, `json_script(html, script_id)`.

- [ ] **Step 1 : Étendre `fund_support.py` et écrire le test qui échoue**

Dans `patrick/tests/fund_support.py` : (a) remplacer la ligne `from patrick.fund import prices` par `from patrick.fund import prices, service` ; (b) ajouter `import json` et `import re` sous `import datetime as dt` ; (c) ajouter à la fin du fichier :

```python
def freeze_today(monkeypatch) -> None:
    """Fige « aujourd'hui » au 2026-01-16 pour les tests de routes (les contrats expirent sinon avec le temps)."""
    monkeypatch.setattr(service, "current_date", lambda: TODAY)
```

```python
def make_strategy(client, name="Macro CTO", **kw) -> str:
    body = {"name": name, "wrapper": "CTO", "initial_capital": 100_000, "opened_on": "2026-01-05", **kw}
    resp = client.post("/api/fund/strategies", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["strategy_id"]


def place(client, strategy_id, **kw) -> dict:
    body = {"instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4, "date": "2026-01-07", **kw}
    resp = client.post(f"/api/fund/strategies/{strategy_id}/orders", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def json_script(html: str, script_id: str):
    match = re.search(rf'<script id="{script_id}" type="application/json">(.*?)</script>', html, re.DOTALL)
    assert match, script_id
    return json.loads(match.group(1))
```

Créer `patrick/tests/test_fund_routes.py` :

```python
"""API /api/fund/* de bout en bout par FastAPI, base isolée, cotations factices (aucun réseau)."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import fund_routes
from patrick.webapp.app import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def strategy(client, **kw):
    body = {"name": "Macro CTO", "wrapper": "CTO", "initial_capital": 100_000, "opened_on": "2026-01-05", **kw}
    resp = client.post("/api/fund/strategies", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["strategy_id"]


def equity(**kw):
    return {"instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4, "date": "2026-01-07", **kw}


def test_strategy_lifecycle(client):
    sid = strategy(client)
    detail = client.get(f"/api/fund/strategies/{sid}/detail")
    assert detail.status_code == 200 and detail.json()["kpis"]["nav"] == 100_000
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": "Renommée"}).json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["strategy"]["name"] == "Renommée"
    assert client.get("/api/fund/overview").json()["fund"]["n_strategies"] == 1
    client.patch(f"/api/fund/strategies/{sid}", json={"archived": True})
    assert client.get("/api/fund/overview").json()["fund"]["n_strategies"] == 0
    assert client.delete(f"/api/fund/strategies/{sid}").json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").status_code == 404
    assert client.delete(f"/api/fund/strategies/{sid}").status_code == 404
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": "x"}).status_code == 404


def test_invalid_input_is_a_400_with_the_reason(client):
    assert client.post("/api/fund/strategies", json={"name": "", "wrapper": "CTO", "initial_capital": 1,
                                                     "opened_on": "2026-01-05"}).status_code == 400
    resp = client.post("/api/fund/strategies", json={"name": "PEA", "wrapper": "PEA", "initial_capital": 200_000,
                                                     "opened_on": "2026-01-05"})
    assert resp.status_code == 400 and "plafond" in resp.json()["detail"]
    assert client.post("/api/fund/strategies", content=b"not json").status_code == 400
    assert client.post("/api/fund/strategies", content=b"[1]").status_code == 400
    sid = strategy(client)
    assert client.patch(f"/api/fund/strategies/{sid}", json={"name": " "}).status_code == 400


def test_quote_never_writes_and_explains_refusals(client):
    sid = strategy(client)
    ok = client.post("/api/fund/quote", json={"strategy_id": sid, **equity()}).json()
    assert ok["ok"] and ok["preview"]["quantity"] == 4 and ok["preview"]["fees"]["seed"]
    refused = client.post("/api/fund/quote", json={"strategy_id": sid, **equity(side="short")}).json()
    assert not refused["ok"] and any("découvert" in m for m in refused["blocking"])
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []


def test_place_order_uses_the_quoted_seed_and_a_refusal_is_a_422_with_the_blocking_list(client):
    sid = strategy(client)
    q = client.post("/api/fund/quote", json={"strategy_id": sid, **equity()}).json()["preview"]
    placed = client.post(f"/api/fund/strategies/{sid}/orders",
                         json={**equity(), "fee_seed": q["fees"]["seed"], "position_id": q["position_id"]})
    assert placed.status_code == 200
    assert placed.json()["preview"]["fees"]["total"] == q["fees"]["total"] and placed.json()["order_id"]
    refused = client.post(f"/api/fund/strategies/{sid}/orders", json=equity(quantity=100_000))
    assert refused.status_code == 422
    assert any("insuffisant" in m for m in refused.json()["detail"]["blocking"])
    assert client.post(f"/api/fund/strategies/{sid}/orders", json=equity(symbol="ZZZZ")).status_code == 422
    assert client.post(f"/api/fund/strategies/{sid}/orders", json={"instrument_kind": "bond"}).status_code == 400
    assert client.post("/api/fund/strategies/str_missing/orders", json=equity()).status_code == 400
    assert len(client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"]) == 1


def test_correct_adjust_and_delete_a_position(client):
    sid = strategy(client)
    opened = client.post(f"/api/fund/strategies/{sid}/orders", json=equity()).json()
    pid = opened["preview"]["position_id"]
    fixed = client.patch(f"/api/fund/orders/{opened['order_id']}", json={"quantity": 6, "date": "2026-01-07"})
    assert fixed.status_code == 200 and fixed.json()["preview"]["quantity"] == 6
    reduce = client.post(f"/api/fund/strategies/{sid}/orders",
                         json={"action": "reduce", "position_id": pid, "quantity": 2, "date": "2026-01-09"})
    assert reduce.status_code == 200
    assert client.patch(f"/api/fund/orders/{reduce.json()['order_id']}", json={"quantity": 1}).status_code == 400
    assert client.patch("/api/fund/orders/9999", json={"quantity": 1}).status_code == 400
    assert client.patch(f"/api/fund/orders/{opened['order_id']}", json={"quantity": 1_000_000}).status_code == 422
    detail = client.get(f"/api/fund/strategies/{sid}/detail").json()
    assert detail["positions"][0]["quantity"] == 4
    assert client.delete(f"/api/fund/positions/{pid}").json() == {"ok": True}
    assert client.get(f"/api/fund/strategies/{sid}/detail").json()["orders"] == []
    assert client.delete(f"/api/fund/positions/{pid}").status_code == 404


def test_instrument_search_and_futures_catalog(client, monkeypatch):
    seen = []

    def fake_search(query, kind):
        seen.append((query, kind))
        return [{"symbol": "MC.PA", "name": "LVMH", "exchange": "Paris", "type": "EQUITY"}]
    monkeypatch.setattr(fund_routes, "search_symbols", fake_search)
    assert client.get("/api/fund/instruments/search?q=l").json() == {"results": []} and seen == []
    found = client.get("/api/fund/instruments/search?q=lvmh&kind=etf").json()
    assert found["results"][0]["symbol"] == "MC.PA" and seen == [("lvmh", "etf")]
    catalog = client.get("/api/fund/futures/catalog").json()["futures"]
    es = next(f for f in catalog if f["root"] == "ES")
    assert es["multiplier"] == 50 and es["contracts"][0]["label"] == "H26"       # au 2026-01-16 (mars 2026)
    assert es["contracts"][0]["symbol"] == "ESH26.CME"


def test_search_symbols_filters_yahoo_quotes_by_kind(monkeypatch):
    quotes = [{"symbol": "MC.PA", "shortname": "LVMH", "exchDisp": "Paris", "quoteType": "EQUITY"},
              {"symbol": "CW8.PA", "longname": "MSCI World", "quoteType": "ETF"},
              {"symbol": "^GSPC", "shortname": "S&P 500", "quoteType": "INDEX"},
              {"symbol": "AAA", "quoteType": "OPTION"}, {"quoteType": "EQUITY"}]
    monkeypatch.setattr(fund_routes.symbols, "yahoo_search", lambda q: quotes)
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "equity")] == ["MC.PA"]
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "etf")] == ["CW8.PA"]
    assert [r["symbol"] for r in fund_routes.search_symbols("x", "cfd")] == ["MC.PA", "CW8.PA", "^GSPC"]
    assert fund_routes.search_symbols("x", "equity")[0] == {"symbol": "MC.PA", "name": "LVMH", "exchange": "Paris",
                                                           "type": "EQUITY"}
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_routes.py -q -W ignore
```

Résultat attendu : `ImportError` sur `patrick.webapp.fund_routes`.

- [ ] **Step 3 : Créer `fund_routes.py` (API seulement pour l'instant)**

```python
"""Pages /simulate et /fonds et API /api/fund/* (spec §11).

Les écritures passent par `fund.service` / `fund.store` : les motifs de refus
d'un ordre deviennent un 422 `{"detail": {"blocking": [...]}}`, les erreurs de
saisie un 400. `search_symbols` est une fonction de module pour que les tests
remplacent la recherche réseau."""
from __future__ import annotations

import json
import sqlite3

from fastapi import FastAPI, HTTPException, Request

from patrick.fund import instruments, service, store
from patrick.tracking import db as trackdb
from patrick.wealth import symbols
from patrick.webapp.wealth_routes import fmt_eur, fmt_pct, fmt_qty

SEARCH_TYPES = {"equity": {"EQUITY"}, "etf": {"ETF", "MUTUALFUND"},
                "cfd": {"EQUITY", "ETF", "INDEX", "CURRENCY", "FUTURE", "CRYPTOCURRENCY"}}


def search_symbols(query: str, kind: str) -> list[dict]:
    wanted = SEARCH_TYPES.get(kind, SEARCH_TYPES["equity"])
    out = []
    for q in symbols.yahoo_search(query):
        quote_type = (q.get("quoteType") or "").upper()
        if quote_type in wanted and q.get("symbol"):
            out.append({"symbol": q["symbol"], "name": q.get("shortname") or q.get("longname") or "",
                        "exchange": q.get("exchDisp") or "", "type": quote_type})
    return out[:10]


def futures_payload(today) -> list[dict]:
    return [{"root": s.root, "name": s.name, "currency": s.currency, "multiplier": s.multiplier,
             "tick_size": s.tick_size, "margin": s.margin, "commission": s.commission, "group": s.group,
             "contracts": instruments.listed_contracts(s.root, today)}
            for s in instruments.FUTURES_CATALOG.values()]


def _json_body(raw: bytes) -> dict:
    try:
        body = json.loads(raw or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="corps JSON invalide") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="objet JSON attendu")
    return body


def _call(fn, *args, **kwargs):
    """Ouvre une connexion, appelle `fn(conn, ...)`, traduit les erreurs métier en HTTP."""
    conn = trackdb.connect()
    try:
        return fn(conn, *args, **kwargs)
    except service.FundRuleError as exc:
        raise HTTPException(status_code=422, detail={"blocking": exc.blocking}) from exc
    except store.FundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=400, detail=f"contrainte violée : {exc}") from exc
    finally:
        conn.close()


def _require_strategy(conn: sqlite3.Connection, strategy_id: str) -> dict:
    strategy = store.get_strategy(conn, strategy_id)
    if strategy is None:
        raise HTTPException(status_code=404, detail="Stratégie introuvable")
    return strategy


def register(app: FastAPI, templates, context) -> None:
    """`context(request)` = constructeur de contexte i18n/glossaire de l'application."""
    templates.env.filters.setdefault("eur", fmt_eur)
    templates.env.filters.setdefault("pct", fmt_pct)
    templates.env.filters.setdefault("qty", fmt_qty)

    # ---------------------------------------------------------------- API

    @app.get("/api/fund/overview")
    def api_overview():
        return _call(service.overview, service.current_date())

    @app.get("/api/fund/strategies/{strategy_id}/detail")
    def api_strategy_detail(strategy_id: str):
        def run(conn):
            return service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), service.current_date())
        return _call(run)

    @app.post("/api/fund/strategies")
    async def api_create_strategy(request: Request):
        b = _json_body(await request.body())
        strategy_id = _call(store.create_strategy, b.get("name"), b.get("wrapper"), b.get("initial_capital"),
                            b.get("opened_on"))
        return {"strategy_id": strategy_id}

    @app.patch("/api/fund/strategies/{strategy_id}")
    async def api_update_strategy(request: Request, strategy_id: str):
        b = _json_body(await request.body())
        fields = {k: b[k] for k in ("name", "archived") if k in b}
        if "archived" in fields:
            fields["archived"] = 1 if fields["archived"] else 0

        def run(conn):
            _require_strategy(conn, strategy_id)
            store.update_strategy(conn, strategy_id, **fields)
            return {"ok": True}
        return _call(run)

    @app.delete("/api/fund/strategies/{strategy_id}")
    def api_delete_strategy(strategy_id: str):
        def run(conn):
            _require_strategy(conn, strategy_id)
            store.delete_strategy(conn, strategy_id)
            return {"ok": True}
        return _call(run)

    @app.get("/api/fund/instruments/search")
    def api_search_instruments(q: str = "", kind: str = "equity"):
        query = q.strip()
        return {"results": search_symbols(query, kind) if len(query) >= 2 else []}

    @app.get("/api/fund/futures/catalog")
    def api_futures_catalog():
        return {"futures": futures_payload(service.current_date())}

    @app.post("/api/fund/quote")
    async def api_quote(request: Request):
        return _call(service.quote, _json_body(await request.body()))

    @app.post("/api/fund/strategies/{strategy_id}/orders")
    async def api_place_order(request: Request, strategy_id: str):
        b = _json_body(await request.body())
        return _call(service.place_order, {**b, "strategy_id": strategy_id})

    @app.patch("/api/fund/orders/{order_id}")
    async def api_correct_order(request: Request, order_id: int):
        return _call(service.correct_order, order_id, _json_body(await request.body()))

    @app.delete("/api/fund/positions/{position_id}")
    def api_delete_position(position_id: str):
        def run(conn):
            if store.delete_position(conn, position_id) == 0:
                raise HTTPException(status_code=404, detail="Position introuvable")
            return {"ok": True}
        return _call(run)
```

- [ ] **Step 4 : Enregistrer les routes dans `app.py`**

```bash
$PY - <<'PYEOF'
from pathlib import Path
p = Path("patrick/webapp/app.py")
s = p.read_text(encoding="utf-8")
old = "    forms,\n    i18n,\n"
assert s.count(old) == 1
s = s.replace(old, "    forms,\n    fund_routes,\n    i18n,\n")
old = "wealth_routes.register(app, templates, lambda request: _i18n_context(request))\n"
assert s.count(old) == 1
s = s.replace(old, old + "\n# Refonte Simulation + Fonds (chantier 1) : pages /simulate, /fonds et API /api/fund/*.\n"
              "fund_routes.register(app, templates, lambda request: _i18n_context(request))\n")
p.write_text(s, encoding="utf-8")
PYEOF
```

- [ ] **Step 5 : Vérifier**

```bash
$PY -m pytest tests/test_fund_routes.py tests/test_nav_registry.py -q -W ignore
$PY -m ruff check patrick/webapp/fund_routes.py patrick/webapp/app.py tests/test_fund_routes.py tests/fund_support.py
```

Résultat attendu : tests verts (les routes `/api/...` sont couvertes par `NON_PAGE_PREFIXES`, `test_no_orphan_page_route` passe). Si ruff signale `I001` sur `app.py`, lancer `$PY -m ruff check --fix patrick/webapp/app.py`.

- [ ] **Step 6 : Commit**

```bash
git add patrick/webapp/fund_routes.py patrick/webapp/app.py tests/fund_support.py tests/test_fund_routes.py
git commit -m "feat(fund): API /api/fund/* (stratégies, aperçu, ordres, correction, recherche, catalogue)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9 : Page Simulation (ticket d'ordre + portefeuilles) et retrait de l'ancien simulateur

**Files:**
- Create: `patrick/patrick/webapp/i18n_fund.py`, `patrick/tests/test_fund_simulate_page.py`
- Modify: `patrick/patrick/webapp/i18n.py`, `patrick/patrick/webapp/fund_routes.py`, `patrick/patrick/webapp/app.py` (retrait), `patrick/patrick/webapp/static/patrick.css`
- Rewrite: `patrick/patrick/webapp/templates/simulate.html`, `patrick/patrick/webapp/static/simulate.js`
- Rename + trim: `patrick/tests/test_simulate_webapp.py` → `patrick/tests/test_runs_trials_api.py`

**Interfaces:**
- Consumes (Tasks 7, 8) : `service.overview`, `service.current_date`, `fund_routes.futures_payload`, `/api/fund/quote`, `/api/fund/strategies`, `/api/fund/strategies/{id}/orders`, `/api/fund/instruments/search`.
- Produces : route `GET /simulate?strategy=<id>&placed=1` (contexte du gabarit : `strategies` = instantanés, `selected_id`, `placed`, `today`, `futures`) ; `i18n_fund.FUND_STRINGS` / `FUND_JS_KEYS` (**toutes** les chaînes des deux pages, y compris celles de `/fonds` utilisées à la Task 10) ; `STRINGS` fusionné ; clés JS exposées via `i18n.js_strings`.

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_simulate_page.py` :

```python
"""Page /simulate : ticket d'ordre en haut, portefeuilles par stratégie en dessous (rendu serveur)."""
from __future__ import annotations

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"
XSS_ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_page_without_a_strategy_offers_to_create_one(client):
    resp = client.get("/simulate")
    assert resp.status_code == 200
    assert "Aucune stratégie." in resp.text and 'id="new-strategy-dialog"' in resp.text
    assert 'id="ticket-form"' not in resp.text


def test_page_shows_the_ticket_then_the_portfolios_below(client):
    sid = fs.make_strategy(client)
    other = fs.make_strategy(client, "Actions PEA", wrapper="PEA", initial_capital=50_000)
    fs.place(client, sid)
    html = client.get(f"/simulate?strategy={other}").text
    assert html.index('id="ticket-form"') < html.index("Portefeuilles par stratégie")
    assert f'<option value="{other}" data-opened="2026-01-05" selected>' in html
    assert html.count('name="instrument_kind"') == 4 and 'value="future"' in html and 'value="cfd"' in html
    assert 'name="side"' in html and 'name="fees_mode"' in html and 'id="f-date"' in html
    assert 'value="2026-01-16" max="2026-01-16"' in html                  # date du ticket : aujourd'hui, pas au-delà
    assert html.count('class="account-card"') == 2 and f'href="/fonds?strategy={sid}"' in html
    assert "Macro CTO" in html and "Actions PEA" in html and "Position ouverte." not in html
    es = next(f for f in fs.json_script(html, "futures-data") if f["root"] == "ES")
    assert es["contracts"][0]["symbol"] == "ESH26.CME" and es["margin"] > 0
    assert "Position ouverte." in client.get(f"/simulate?strategy={sid}&placed=1").text


def test_page_exposes_the_js_strings_in_both_languages_and_loads_its_script(client):
    fs.make_strategy(client)
    html = client.get("/simulate").text
    strings = fs.json_script(html, "i18n-data")
    assert strings["fund_pv_day"] == "Jour d'exécution" and strings["fund_leverage_cap"] == "plafond {cap}:1"
    assert '<script src="/static/simulate.js"></script>' in html
    english = client.get("/simulate?lang=en").text
    assert fs.json_script(english, "i18n-data")["fund_pv_day"] == "Execution day"
    assert "Order ticket" in english and "Portfolios by strategy" in english


def test_strategy_names_are_escaped(client):
    sid = fs.make_strategy(client, XSS)
    fs.place(client, sid)
    html = client.get("/simulate").text
    assert XSS_ESCAPED in html and XSS not in html


def test_the_page_script_uses_only_exposed_and_defined_strings(client):
    import re

    from patrick.webapp import i18n

    js = client.get("/static/simulate.js").text
    used = set(re.findall(r"""['"](fund_[a-z_]+)['"]""", js))
    assert used <= set(i18n.STRINGS), used - set(i18n.STRINGS)
    exposed = set(i18n.js_strings("fr"))
    assert used <= exposed, used - exposed
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_simulate_page.py -q -W ignore
```

Résultat attendu : échecs (l'ancienne page `/simulate` n'a ni ticket ni chaînes `fund_*`).

- [ ] **Step 3 : Chaînes FR/EN et fusion dans `i18n.py`**

Créer `patrick/patrick/webapp/i18n_fund.py` :

```python
"""Chaînes FR/EN des pages Simulation et Fonds (chantier 1). Fusionnées dans
`i18n.STRINGS` ; `FUND_JS_KEYS` complète `i18n.js_strings` (clés lues par
simulate.js / fonds.js via `window.I18N`)."""
from __future__ import annotations


def _s(fr: str, en: str) -> dict[str, str]:
    return {"fr": fr, "en": en}


FUND_STRINGS: dict[str, dict[str, str]] = {
    # navigation
    "nav_fonds": _s("Fonds", "LP Fund"),
    "nav_simulate": _s("Simulation", "Simulation"),

    # /simulate : ticket
    "fund_sim_title": _s("Simulation", "Simulation"),
    "fund_sim_subtitle": _s(
        "Ouvre des positions long ou short sur des instruments classiques, rattachées à une stratégie. Prix de marché ; frais saisis ou estimés.",
        "Open long or short positions on classic instruments, attached to a strategy. Market prices; fees typed or estimated."),
    "fund_new_strategy": _s("Nouvelle stratégie", "New strategy"),
    "fund_no_strategy": _s("Aucune stratégie.", "No strategy yet."),
    "fund_no_strategy_hint": _s("Crée une stratégie (capital, enveloppe PEA ou CTO) pour pouvoir passer des ordres.",
                                "Create a strategy (capital, PEA or CTO wrapper) to place orders."),
    "fund_ticket_title": _s("Ticket d'ordre", "Order ticket"),
    "fund_field_strategy": _s("Stratégie", "Strategy"),
    "fund_field_kind": _s("Instrument", "Instrument"),
    "fund_kind_equity": _s("Action", "Stock"),
    "fund_kind_etf": _s("ETF", "ETF"),
    "fund_kind_future": _s("Future", "Future"),
    "fund_kind_cfd": _s("CFD", "CFD"),
    "fund_field_symbol": _s("Ticker Yahoo", "Yahoo ticker"),
    "fund_field_root": _s("Produit", "Product"),
    "fund_field_contract": _s("Échéance", "Expiry"),
    "fund_field_side": _s("Sens", "Side"),
    "fund_side_long": _s("Long (achat)", "Long (buy)"),
    "fund_side_short": _s("Short (vente)", "Short (sell)"),
    "fund_side_short_blocked": _s("Vente à découvert impossible sur action/ETF : passer par un CFD ou un future.",
                                  "Short selling a stock/ETF is not possible: use a CFD or a future."),
    "fund_field_quantity": _s("Quantité", "Quantity"),
    "fund_field_amount": _s("ou montant (€)", "or amount (€)"),
    "fund_field_contracts": _s("Nombre de contrats", "Number of contracts"),
    "fund_field_units": _s("Taille (unités)", "Size (units)"),
    "fund_field_leverage": _s("Levier", "Leverage"),
    "fund_leverage_cap": _s("plafond {cap}:1", "cap {cap}:1"),
    "fund_field_stop": _s("Stop (prix)", "Stop (price)"),
    "fund_field_target": _s("Objectif (prix)", "Target (price)"),
    "fund_field_date": _s("Date d'exécution", "Execution date"),
    "fund_field_manual_price": _s("Saisir le prix", "Type the price"),
    "fund_field_price": _s("Prix", "Price"),
    "fund_field_fees": _s("Frais", "Fees"),
    "fund_fees_estimated": _s("Estimés", "Estimated"),
    "fund_fees_manual": _s("Manuels (€)", "Manual (€)"),
    "fund_submit": _s("Ouvrir la position", "Open the position"),
    "fund_preview_title": _s("Aperçu", "Preview"),
    "fund_preview_empty": _s("Renseigne le ticket pour voir l'aperçu.", "Fill in the ticket to see the preview."),
    "fund_pv_day": _s("Jour d'exécution", "Execution day"),
    "fund_pv_price": _s("Prix d'exécution", "Execution price"),
    "fund_pv_fx": _s("Taux de change", "Exchange rate"),
    "fund_pv_quantity": _s("Quantité", "Quantity"),
    "fund_pv_notional": _s("Notionnel", "Notional"),
    "fund_pv_margin": _s("Marge bloquée", "Margin held"),
    "fund_pv_fees": _s("Frais", "Fees"),
    "fund_pv_fees_detail": _s("commission {c} · spread {s} · change {x}", "commission {c} · spread {s} · FX {x}"),
    "fund_pv_cash_after": _s("Cash après ordre", "Cash after order"),
    "fund_pv_power_after": _s("Liquidités disponibles après", "Available funds after"),
    "fund_pv_provisional": _s("cours du jour, provisoire", "today's quote, provisional"),
    "fund_pv_manual": _s("prix saisi", "typed price"),
    "fund_blocking_title": _s("Ordre refusé", "Order refused"),
    "fund_warnings_title": _s("À vérifier", "To check"),
    "fund_placed": _s("Position ouverte.", "Position opened."),
    "fund_portfolios_title": _s("Portefeuilles par stratégie", "Portfolios by strategy"),
    "fund_card_cash": _s("cash", "cash"),
    "fund_card_positions": _s("{n} position(s)", "{n} position(s)"),
    "fund_card_open_fund": _s("Voir dans Fonds", "View in Fund"),
    "fund_dlg_title": _s("Nouvelle stratégie", "New strategy"),
    "fund_field_name": _s("Nom", "Name"),
    "fund_field_wrapper": _s("Enveloppe", "Wrapper"),
    "fund_wrapper_cto": _s("CTO — tous instruments, marge", "CTO — all instruments, margin"),
    "fund_wrapper_pea": _s("PEA — long seulement, titres en euro", "PEA — long only, euro securities"),
    "fund_field_capital": _s("Capital de départ (€)", "Starting capital (€)"),
    "fund_field_opened": _s("Ouverte le", "Opened on"),
    "fund_btn_cancel": _s("Annuler", "Cancel"),
    "fund_btn_create": _s("Créer", "Create"),

    # /fonds
    "fund_title": _s("Fonds", "LP Fund"),
    "fund_subtitle": _s("Toutes les stratégies : valeur, performance, positions. Clique une stratégie pour ouvrir son détail.",
                        "Every strategy: value, performance, positions. Click a strategy to open its detail."),
    "fund_new_position": _s("Nouvelle position", "New position"),
    "fund_total_nav": _s("Valeur du fonds", "Fund value"),
    "fund_total_nav_hint": _s("Somme des {n} stratégie(s) non archivée(s).", "Sum of the {n} non-archived strategies."),
    "fund_total_capital": _s("Capital total", "Total capital"),
    "fund_total_capital_hint": _s("Capitaux de départ cumulés.", "Cumulated starting capital."),
    "fund_total_pnl": _s("P&L total", "Total P&L"),
    "fund_strategies_title": _s("Stratégies", "Strategies"),
    "fund_col_strategy": _s("Stratégie", "Strategy"),
    "fund_col_wrapper": _s("Enveloppe", "Wrapper"),
    "fund_col_nav": _s("Valeur", "Value"),
    "fund_col_pnl": _s("P&L", "P&L"),
    "fund_col_exposure": _s("Exposition", "Exposure"),
    "fund_col_leverage": _s("Levier", "Leverage"),
    "fund_col_margin": _s("Marge", "Margin"),
    "fund_col_positions": _s("Positions", "Positions"),
    "fund_table_footer": _s("Valorisation au dernier cours de clôture Yahoo Finance, en euros ; positions ouvertes uniquement dans la colonne Positions.",
                            "Valued at the last Yahoo Finance close, in euros; the Positions column counts open positions only."),
    "fund_panel_close": _s("Fermer", "Close"),
    "fund_panel_meta": _s("Ouverte le {start} · capital de départ {capital}", "Opened on {start} · starting capital {capital}"),
    "fund_act_rename": _s("Renommer", "Rename"),
    "fund_act_archive": _s("Archiver", "Archive"),
    "fund_act_delete_strategy": _s("Supprimer la stratégie", "Delete strategy"),
    "fund_confirm_delete_strategy": _s("Supprimer cette stratégie, toutes ses positions et tous ses ordres ?",
                                       "Delete this strategy with all its positions and orders?"),
    "fund_rename_prompt": _s("Nouveau nom de la stratégie", "New strategy name"),
    "fund_alert_margin": _s("Marge : la valeur nette est passée sous 50 % de la marge requise ({n} jour(s), dès le {first}). Un courtier aurait liquidé des positions.",
                            "Margin: net value fell below 50% of the required margin ({n} day(s), from {first}). A broker would have closed positions."),

    # KPI du panneau
    "fund_kpi_nav": _s("Valeur (NAV)", "Value (NAV)"),
    "fund_kpi_pnl": _s("P&L total", "Total P&L"),
    "fund_kpi_realized": _s("Réalisé", "Realized"),
    "fund_kpi_latent": _s("Latent", "Unrealized"),
    "fund_kpi_fees": _s("Frais cumulés", "Cumulated fees"),
    "fund_kpi_dividends": _s("Dividendes", "Dividends"),
    "fund_kpi_financing": _s("Financement CFD", "CFD financing"),
    "fund_kpi_vol": _s("Volatilité annualisée", "Annualized volatility"),
    "fund_kpi_sharpe": _s("Sharpe", "Sharpe"),
    "fund_kpi_dd": _s("Drawdown max", "Max drawdown"),
    "fund_kpi_gross": _s("Exposition brute", "Gross exposure"),
    "fund_kpi_net": _s("Exposition nette", "Net exposure"),
    "fund_kpi_leverage": _s("Levier brut", "Gross leverage"),
    "fund_kpi_margin": _s("Marge utilisée", "Margin used"),
    "fund_kpi_power": _s("Liquidités disponibles", "Available funds"),
    "fund_kpi_cash": _s("Cash", "Cash"),
    "fund_hint_nav": _s("Cash + actions/ETF au cours + P&L latent des CFD.", "Cash + stocks/ETFs at market + CFD unrealized P&L."),
    "fund_hint_pnl": _s("Valeur moins capital de départ ; en % du capital.", "Value minus starting capital; in % of capital."),
    "fund_hint_realized": _s("Gains et pertes des quantités déjà sorties (futures : variation réglée).", "Gains and losses on quantities already sold (futures: settled variation)."),
    "fund_hint_latent": _s("Positions ouvertes, au dernier cours.", "Open positions at the last price."),
    "fund_hint_fees": _s("Commissions, spreads et change de tous les ordres.", "Commissions, spreads and FX on every order."),
    "fund_hint_dividends": _s("Crédités à la date ex-dividende, sans retenue.", "Credited on the ex-dividend date, no withholding."),
    "fund_hint_financing": _s("Coût net du financement overnight ; négatif = reçu.", "Net overnight financing cost; negative = received."),
    "fund_hint_vol": _s("Écart-type des rendements quotidiens de la valeur × √252.", "Std. dev. of daily value returns × √252."),
    "fund_hint_sharpe": _s("Sans taux sans risque ; indicatif sur un historique court.", "No risk-free rate; indicative on a short history."),
    "fund_hint_dd": _s("Plus forte baisse depuis un sommet de la valeur.", "Largest fall from a peak of the value."),
    "fund_hint_gross": _s("Somme des notionnels en valeur absolue / valeur.", "Sum of absolute notionals / value."),
    "fund_hint_net": _s("Notionnels long moins short / valeur.", "Long minus short notionals / value."),
    "fund_hint_leverage": _s("Exposition brute divisée par la valeur.", "Gross exposure divided by value."),
    "fund_hint_margin": _s("Marge initiale des futures et CFD ouverts.", "Initial margin of open futures and CFDs."),
    "fund_hint_power": _s("Cash + P&L latent des CFD − marge utilisée.", "Cash + CFD unrealized P&L − margin used."),
    "fund_hint_cash": _s("Marge bloquée comprise.", "Margin held included."),
    "fund_chart_title": _s("Évolution de la valeur", "Value over time"),
    "fund_chart_nav": _s("Valeur", "Value"),
    "fund_chart_capital": _s("Capital de départ", "Starting capital"),

    # positions
    "fund_pos_title": _s("Positions ouvertes", "Open positions"),
    "fund_pos_closed_title": _s("Positions fermées", "Closed positions"),
    "fund_pos_none": _s("Aucune position ouverte.", "No open position."),
    "fund_pcol_instrument": _s("Instrument", "Instrument"),
    "fund_pcol_side": _s("Sens", "Side"),
    "fund_pcol_qty": _s("Qté", "Qty"),
    "fund_pcol_entry": _s("Entrée", "Entry"),
    "fund_pcol_price": _s("Cours", "Price"),
    "fund_pcol_fx": _s("Devise · change", "Currency · FX"),
    "fund_pcol_value": _s("Valeur €", "Value €"),
    "fund_pcol_pnl": _s("P&L", "P&L"),
    "fund_pcol_fx_effect": _s("dont change €", "of which FX €"),
    "fund_pcol_margin": _s("Marge €", "Margin €"),
    "fund_pcol_levels": _s("Stop · Objectif", "Stop · Target"),
    "fund_pcol_period": _s("Période", "Period"),
    "fund_pcol_status": _s("Statut", "Status"),
    "fund_pcol_action": _s("Action", "Action"),
    "fund_expiry": _s("éch. {date}", "exp. {date}"),
    "fund_quality_continuous": _s("Série continue : sauts de roll non corrigés.", "Continuous series: roll jumps not corrected."),
    "fund_status_open": _s("Ouverte", "Open"),
    "fund_status_closed": _s("Fermée", "Closed"),
    "fund_status_stop": _s("Stop touché", "Stop hit"),
    "fund_status_target": _s("Objectif atteint", "Target reached"),
    "fund_status_expired": _s("Échue", "Expired"),
    "fund_act_adjust": _s("Ajuster", "Adjust"),
    "fund_act_correct": _s("Corriger", "Correct"),
    "fund_act_delete": _s("Supprimer", "Delete"),
    "fund_confirm_delete_position": _s("Supprimer cette position et tous ses ordres ?", "Delete this position and all its orders?"),
    "fund_adj_action": _s("Action", "Action"),
    "fund_adj_increase": _s("Renforcer", "Increase"),
    "fund_adj_reduce": _s("Alléger", "Reduce"),
    "fund_adj_close": _s("Fermer", "Close"),
    "fund_adj_modify": _s("Modifier stop / objectif / levier", "Modify stop / target / leverage"),
    "fund_adj_apply": _s("Valider", "Apply"),
    "fund_price_market": _s("cours du jour", "market price"),
    "fund_orders_title": _s("Historique des ordres", "Order history"),
    "fund_orders_footer": _s("* prix ou frais saisi à la main.", "* price or fees typed by hand."),
    "fund_action_open": _s("Ouverture", "Open"),
    "fund_action_increase": _s("Renfort", "Increase"),
    "fund_action_reduce": _s("Allègement", "Reduce"),
    "fund_action_close": _s("Clôture", "Close"),
    "fund_action_modify": _s("Modification", "Modify"),
}

FUND_JS_KEYS: tuple[str, ...] = (
    "fund_side_short_blocked", "fund_preview_empty", "fund_leverage_cap", "fund_blocking_title",
    "fund_warnings_title", "fund_pv_day", "fund_pv_price", "fund_pv_fx", "fund_pv_quantity",
    "fund_pv_notional", "fund_pv_margin", "fund_pv_fees", "fund_pv_fees_detail", "fund_pv_cash_after",
    "fund_pv_power_after", "fund_pv_provisional", "fund_pv_manual", "fund_rename_prompt",
)
```

Brancher dans `patrick/patrick/webapp/i18n.py` :

```bash
$PY - <<'PYEOF'
from pathlib import Path
p = Path("patrick/webapp/i18n.py")
s = p.read_text(encoding="utf-8")
old = "from starlette.requests import Request\n"
assert s.count(old) == 1
s = s.replace(old, old + "\nfrom patrick.webapp.i18n_fund import FUND_JS_KEYS, FUND_STRINGS\n")
old = "\n\ndef get_lang(request: Request) -> str:"
assert s.count(old) == 1
s = s.replace(old, "\n\n# Pages Simulation et Fonds (webapp/i18n_fund.py) ; leurs chaînes écrasent la clé homonyme nav_simulate.\n"
              "STRINGS.update(FUND_STRINGS)\n\n\ndef get_lang(request: Request) -> str:")
old = '"cmdk_empty", "wealth_import_preview",'
assert s.count(old) == 1
s = s.replace(old, '"cmdk_empty", *FUND_JS_KEYS, "wealth_import_preview",')
p.write_text(s, encoding="utf-8")
PYEOF
```

- [ ] **Step 4 : Route de la page**

Dans `patrick/patrick/webapp/fund_routes.py`, insérer le bloc suivant **juste avant** la ligne `    # ---------------------------------------------------------------- API` (la Task 10 y ajoutera `/fonds`) :

```python
    # -------------------------------------------------------------- pages
```

```python
    @app.get("/simulate")
    def simulate_page(request: Request, strategy: str | None = None, placed: int = 0):
        today = service.current_date()
        data = _call(service.overview, today)
        return templates.TemplateResponse(request, "simulate.html", {
            "strategies": data["strategies"], "selected_id": strategy, "placed": bool(placed),
            "today": today.isoformat(), "futures": futures_payload(today), **context(request)})
```

- [ ] **Step 5 : Gabarit, JavaScript et CSS de la page**

Remplacer entièrement `patrick/patrick/webapp/templates/simulate.html` par :

```html
{% extends "base_v2.html" %}
{% from "_components.html" import sparkline, empty_state %}
{% block title %}PATRICK — {{ t('fund_sim_title') }}{% endblock %}

{# Refonte Simulation (chantier 1) : ticket d'ordre en haut, portefeuilles par
   stratégie en dessous. Toutes les écritures passent par /api/fund/*
   (webapp/fund_routes.py) ; l'aperçu est calculé par le serveur à chaque
   modification du ticket (/api/fund/quote), jamais par le navigateur. #}

{% block content %}
<div class="page-header">
  <div>
    <h1 class="page-title">{{ t('fund_sim_title') }}</h1>
    <p class="page-subtitle">{{ t('fund_sim_subtitle') }}</p>
  </div>
  <div class="page-actions">
    <button type="button" class="btn-secondary" data-open-dialog="new-strategy-dialog">{{ icon('plus') }} {{ t('fund_new_strategy') }}</button>
  </div>
</div>

<div id="fund-flash" class="banner hidden" role="status"></div>
{% if placed %}<div class="banner banner-info" role="status">{{ t('fund_placed') }}</div>{% endif %}

{% if strategies %}
<section class="card fund-ticket" aria-labelledby="ticket-title">
  <h2 id="ticket-title">{{ t('fund_ticket_title') }}</h2>
  <div class="fund-ticket-grid">
    <form id="ticket-form" class="form" autocomplete="off" data-today="{{ today }}">
      <label>{{ t('fund_field_strategy') }}
        <select name="strategy_id" id="f-strategy">
          {% for s in strategies %}
          <option value="{{ s.strategy.strategy_id }}" data-opened="{{ s.strategy.opened_on }}"{% if s.strategy.strategy_id == selected_id %} selected{% endif %}>{{ s.strategy.name }} · {{ s.strategy.wrapper }}</option>
          {% endfor %}
        </select>
      </label>

      <fieldset class="fund-choice">
        <legend>{{ t('fund_field_kind') }}</legend>
        {% for key in ['equity', 'etf', 'future', 'cfd'] %}
        <label class="checkbox"><input type="radio" name="instrument_kind" value="{{ key }}"{% if loop.first %} checked{% endif %}> {{ t('fund_kind_' ~ key) }}</label>
        {% endfor %}
      </fieldset>

      <label data-kinds="equity etf cfd">{{ t('fund_field_symbol') }}
        <input type="text" name="symbol" id="f-symbol" list="f-symbol-list" placeholder="MC.PA · AAPL · ^GSPC · EURUSD=X" maxlength="40">
        <datalist id="f-symbol-list"></datalist>
      </label>
      <div class="subgrid" data-kinds="future" hidden>
        <label>{{ t('fund_field_root') }} <select name="root" id="f-root"></select></label>
        <label>{{ t('fund_field_contract') }} <select name="contract" id="f-contract"></select></label>
      </div>

      <fieldset class="fund-choice">
        <legend>{{ t('fund_field_side') }}</legend>
        <label class="checkbox"><input type="radio" name="side" value="long" checked> {{ t('fund_side_long') }}</label>
        <label class="checkbox"><input type="radio" name="side" value="short"> {{ t('fund_side_short') }}</label>
      </fieldset>

      <div class="subgrid" data-kinds="equity etf">
        <label>{{ t('fund_field_quantity') }} <input type="number" name="quantity" min="1" step="1"></label>
        <label>{{ t('fund_field_amount') }} <input type="number" name="amount" min="0" step="any"></label>
      </div>
      <div class="subgrid" data-kinds="future" hidden>
        <label>{{ t('fund_field_contracts') }} <input type="number" name="contracts" min="1" step="1"></label>
      </div>
      <div class="subgrid" data-kinds="cfd" hidden>
        <label>{{ t('fund_field_units') }} <input type="number" name="units" min="0" step="any"></label>
        <label>{{ t('fund_field_leverage') }} <input type="number" name="leverage" id="f-leverage" min="1" step="any">
          <span class="hint" id="f-leverage-hint"></span></label>
      </div>
      <div class="subgrid" data-kinds="future cfd" hidden>
        <label>{{ t('fund_field_stop') }} <input type="number" name="stop" min="0" step="any"></label>
        <label>{{ t('fund_field_target') }} <input type="number" name="target" min="0" step="any"></label>
      </div>

      <div class="subgrid">
        <label>{{ t('fund_field_date') }} <input type="date" name="date" id="f-date" value="{{ today }}" max="{{ today }}"></label>
        <label class="checkbox"><input type="checkbox" name="manual_price" id="f-manual-price"> {{ t('fund_field_manual_price') }}</label>
        <label>{{ t('fund_field_price') }} <input type="number" name="price" id="f-price" min="0" step="any" disabled></label>
      </div>

      <fieldset class="fund-choice">
        <legend>{{ t('fund_field_fees') }}</legend>
        <label class="checkbox"><input type="radio" name="fees_mode" value="estimated" checked> {{ t('fund_fees_estimated') }}</label>
        <label class="checkbox"><input type="radio" name="fees_mode" value="manual"> {{ t('fund_fees_manual') }}</label>
        <input type="number" name="fees" id="f-fees" min="0" step="any" disabled aria-label="{{ t('fund_fees_manual') }}">
      </fieldset>

      <button type="submit" class="btn" id="ticket-submit" disabled>{{ t('fund_submit') }}</button>
    </form>

    <aside id="ticket-preview" class="fund-preview" aria-live="polite" aria-label="{{ t('fund_preview_title') }}">
      <p class="hint">{{ t('fund_preview_empty') }}</p>
    </aside>
  </div>
</section>
{% else %}
{{ empty_state(t('fund_no_strategy'), t('fund_no_strategy_hint')) }}
{% endif %}

<section class="card" aria-labelledby="portfolios-title">
  <div class="card-head"><h2 id="portfolios-title">{{ t('fund_portfolios_title') }}</h2></div>
  {% if strategies %}
  <div class="account-grid">
    {% for s in strategies %}{% set k = s.kpis %}
    <article class="account-card">
      <div class="row">
        <span class="account-type">{{ s.strategy.wrapper }}</span>
        <span class="spacer"></span>
        <a href="/fonds?strategy={{ s.strategy.strategy_id }}">{{ t('fund_card_open_fund') }}</a>
      </div>
      <div class="account-name">{{ s.strategy.name }}</div>
      <div class="account-value">{{ k.nav | eur }}</div>
      <div class="hint">
        <span class="{{ 'pos' if k.pnl >= 0 else 'neg' }}">{{ k.pnl | eur }} · {{ k.pnl_pct | pct(1, true) }}</span>
        · {{ t('fund_card_cash') }} {{ k.cash | eur }} · {{ t('fund_card_positions', n=k.n_open_positions) }}
      </div>
      {{ sparkline(s.series | map(attribute='nav') | list) }}
    </article>
    {% endfor %}
  </div>
  {% else %}
  <p class="hint">{{ t('fund_no_strategy') }}</p>
  {% endif %}
</section>

<dialog id="new-strategy-dialog" class="modal">
  <form class="form" id="new-strategy-form">
    <h2>{{ t('fund_dlg_title') }}</h2>
    <label>{{ t('fund_field_name') }} <input type="text" name="name" required maxlength="120"></label>
    <div class="subgrid">
      <label>{{ t('fund_field_wrapper') }}
        <select name="wrapper">
          <option value="CTO">{{ t('fund_wrapper_cto') }}</option>
          <option value="PEA">{{ t('fund_wrapper_pea') }}</option>
        </select>
      </label>
      <label>{{ t('fund_field_capital') }} <input type="number" name="initial_capital" required min="1" step="any" value="100000"></label>
    </div>
    <label>{{ t('fund_field_opened') }} <input type="date" name="opened_on" required value="{{ today }}" max="{{ today }}"></label>
    <div class="row" style="justify-content:flex-end">
      <button type="button" class="btn-secondary" data-close-dialog>{{ t('fund_btn_cancel') }}</button>
      <button type="submit" class="btn">{{ t('fund_btn_create') }}</button>
    </div>
  </form>
</dialog>

<script id="futures-data" type="application/json">{{ futures | tojson }}</script>
<script src="/static/simulate.js"></script>
{% endblock %}
```

Remplacer entièrement `patrick/patrick/webapp/static/simulate.js` par :

```javascript
/* Page /simulate : ticket d'ordre avec aperçu serveur en direct + création de stratégie.
   Aucun calcul métier dans le navigateur : chaque modification du ticket appelle
   POST /api/fund/quote ; « Ouvrir la position » appelle POST /api/fund/strategies/{id}/orders
   avec la graine des frais et l'identifiant de position de l'aperçu (le montant
   affiché est celui qui est enregistré). Tout le texte dynamique passe par
   textContent : noms et motifs viennent de la base ou de Yahoo. */
(function () {
    "use strict";

    var I18N = window.I18N || {};
    function tr(key, fallback, params) {
        var s = I18N[key] || fallback || key;
        return params ? s.replace(/\{(\w+)\}/g, function (m, k) { return params[k] !== undefined ? params[k] : m; }) : s;
    }
    var flash = document.getElementById("fund-flash");
    function say(text, kind) {
        if (!flash) { window.alert(text); return; }
        flash.textContent = text;
        flash.className = "banner " + (kind === "error" ? "banner-error" : "banner-info");
        flash.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    async function call(url, method, body) {
        var res = await fetch(url, {
            method: method || "POST",
            headers: { "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        var data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (!res.ok) {
            var err = new Error(typeof data.detail === "string" ? data.detail : "HTTP " + res.status);
            err.blocking = data.detail && data.detail.blocking ? data.detail.blocking : null;
            throw err;
        }
        return data;
    }
    function num(v, digits) {
        if (v === null || v === undefined) return "—";
        return Number(v).toLocaleString("fr-FR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
    }
    function money(v) { return num(v, 2) + " €"; }

    /* ---- dialogs ---- */
    document.querySelectorAll("[data-open-dialog]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var d = document.getElementById(btn.getAttribute("data-open-dialog"));
            if (d && d.showModal) d.showModal();
        });
    });
    document.querySelectorAll("[data-close-dialog]").forEach(function (btn) {
        btn.addEventListener("click", function () { var d = btn.closest("dialog"); if (d) d.close(); });
    });

    /* ---- nouvelle stratégie ---- */
    var newForm = document.getElementById("new-strategy-form");
    if (newForm) {
        newForm.addEventListener("submit", async function (ev) {
            ev.preventDefault();
            var fd = new FormData(newForm);
            try {
                var res = await call("/api/fund/strategies", "POST", {
                    name: fd.get("name"), wrapper: fd.get("wrapper"),
                    initial_capital: fd.get("initial_capital"), opened_on: fd.get("opened_on"),
                });
                window.location.href = "/simulate?strategy=" + encodeURIComponent(res.strategy_id);
            } catch (e) {
                var d = newForm.closest("dialog");
                if (d) d.close();
                say(e.message, "error");
            }
        });
    }

    /* ---- ticket ---- */
    var form = document.getElementById("ticket-form");
    if (!form) return;
    var futures = JSON.parse(document.getElementById("futures-data").textContent || "[]");
    var box = document.getElementById("ticket-preview");
    var submit = document.getElementById("ticket-submit");
    var rootSel = document.getElementById("f-root");
    var contractSel = document.getElementById("f-contract");
    var levInput = document.getElementById("f-leverage");
    var levHint = document.getElementById("f-leverage-hint");
    var lastQuote = null, timer = null, searchTimer = null, seq = 0;
    var ticketPosition = null;      // identifiant de position de l'aperçu : garde les frais estimés stables entre deux rafraîchissements

    function kind() { return form.querySelector('input[name="instrument_kind"]:checked').value; }
    function option(sel, label, value) {
        var o = document.createElement("option");
        o.value = value;
        o.textContent = label;
        sel.appendChild(o);
    }
    function fillContracts() {
        contractSel.textContent = "";
        var f = futures.filter(function (x) { return x.root === rootSel.value; })[0];
        (f ? f.contracts : []).forEach(function (c) { option(contractSel, c.label + " (" + c.expiry + ")", c.year + "-" + c.month); });
    }
    function fillRoots() {
        rootSel.textContent = "";
        futures.forEach(function (f) { option(rootSel, f.root + " — " + f.name, f.root); });
        fillContracts();
    }
    function applyKind() {
        var k = kind();
        form.querySelectorAll("[data-kinds]").forEach(function (el) {
            el.hidden = el.getAttribute("data-kinds").split(" ").indexOf(k) === -1;
        });
        var cash = k === "equity" || k === "etf";
        var short = form.querySelector('input[name="side"][value="short"]');
        short.disabled = cash;
        short.parentElement.title = cash ? tr("fund_side_short_blocked") : "";
        if (cash) form.querySelector('input[name="side"][value="long"]').checked = true;
    }
    function applyStrategy() {
        var opt = form.strategy_id.options[form.strategy_id.selectedIndex];
        form.date.min = opt ? opt.getAttribute("data-opened") : "";
    }
    function present(v) { return v !== null && v !== undefined && String(v).trim() !== ""; }

    /* Requête du ticket, ou null tant qu'il manque l'identification de l'instrument. */
    function request() {
        var fd = new FormData(form), k = kind();
        var req = { strategy_id: fd.get("strategy_id"), action: "open", instrument_kind: k, side: fd.get("side"),
                    date: fd.get("date") || undefined, fees_mode: fd.get("fees_mode"), spec: {} };
        if (k === "future") {
            if (!present(fd.get("root")) || !present(fd.get("contract"))) return null;
            var ym = String(fd.get("contract")).split("-");
            req.spec.root = fd.get("root");
            req.spec.year = Number(ym[0]);
            req.spec.month = Number(ym[1]);
            req.quantity = fd.get("contracts");
        } else {
            if (!present(fd.get("symbol"))) return null;
            req.symbol = String(fd.get("symbol")).trim();
        }
        if (k === "equity" || k === "etf") {
            req.quantity = fd.get("quantity");
            req.amount = fd.get("amount");
        }
        if (k === "cfd") {
            req.quantity = fd.get("units");
            req.spec.leverage = fd.get("leverage");
        }
        if (k === "future" || k === "cfd") {
            req.spec.stop = fd.get("stop");
            req.spec.target = fd.get("target");
        }
        if (ticketPosition) req.position_id = ticketPosition;
        if (fd.get("manual_price") && present(fd.get("price"))) req.price = fd.get("price");
        if (req.fees_mode === "manual") req.fees = fd.get("fees");
        return req;
    }

    function row(list, label, value) {
        var dt = document.createElement("dt"), dd = document.createElement("dd");
        dt.textContent = label;
        dd.textContent = value;
        dd.className = "pk-mono";
        list.appendChild(dt);
        list.appendChild(dd);
    }
    function messages(cls, title, items) {
        if (!items || !items.length) return;
        var div = document.createElement("div"), strong = document.createElement("strong"), ul = document.createElement("ul");
        div.className = "banner " + cls;
        strong.textContent = title;
        items.forEach(function (m) { var li = document.createElement("li"); li.textContent = m; ul.appendChild(li); });
        div.appendChild(strong);
        div.appendChild(ul);
        box.appendChild(div);
    }
    function renderEmpty() {
        lastQuote = null;
        box.textContent = "";
        var p = document.createElement("p");
        p.className = "hint";
        p.textContent = tr("fund_preview_empty");
        box.appendChild(p);
        submit.disabled = true;
    }
    function renderPreview(q) {
        lastQuote = q;
        box.textContent = "";
        var p = q.preview;
        if (p) {
            var dl = document.createElement("dl");
            dl.className = "fund-preview-list";
            row(dl, tr("fund_pv_day"), p.exec_day + (p.provisional ? " · " + tr("fund_pv_provisional") : ""));
            row(dl, tr("fund_pv_price"), p.price === null ? "—" :
                num(p.price, 4) + " " + p.currency + (p.price_source === "manual" ? " (" + tr("fund_pv_manual") + ")" : ""));
            if (p.currency !== "EUR") row(dl, tr("fund_pv_fx"), num(p.fx_rate, 5));
            row(dl, tr("fund_pv_quantity"), num(p.quantity, 4));
            if (p.notional_local !== null) {
                row(dl, tr("fund_pv_notional"), num(p.notional_local, 2) + " " + p.currency +
                    (p.currency !== "EUR" ? " ≈ " + money(p.notional_base) : ""));
            }
            if (p.margin_required !== null) row(dl, tr("fund_pv_margin"), money(p.margin_required));
            row(dl, tr("fund_pv_fees"), money(p.fees.total));
            row(dl, tr("fund_pv_cash_after"), money(p.cash_after));
            row(dl, tr("fund_pv_power_after"), money(p.buying_power_after));
            box.appendChild(dl);
            ticketPosition = p.position_id;
            if (p.fees.source === "estimated") {
                var detail = document.createElement("p");
                detail.className = "hint";
                detail.textContent = tr("fund_pv_fees_detail", "", { c: money(p.fees.commission), s: money(p.fees.spread), x: money(p.fees.fx) });
                box.appendChild(detail);
            }
            if (p.leverage_cap) {
                levInput.max = p.leverage_cap;
                levHint.textContent = tr("fund_leverage_cap", "", { cap: p.leverage_cap });
            }
        }
        messages("banner-error", tr("fund_blocking_title"), q.blocking);
        messages("banner-warning", tr("fund_warnings_title"), q.warnings);
        submit.disabled = !q.ok;
    }
    function renderError(message) {
        renderPreview({ ok: false, blocking: [message], warnings: [], preview: null });
    }

    async function refresh() {
        var mine = ++seq, req = request();
        if (!req) { renderEmpty(); return; }
        try {
            var q = await call("/api/fund/quote", "POST", req);
            if (mine === seq) renderPreview(q);
        } catch (e) {
            if (mine === seq) renderError(e.message);
        }
    }
    function schedule() {
        window.clearTimeout(timer);
        submit.disabled = true;
        timer = window.setTimeout(refresh, 300);
    }

    /* Suggestions de tickers (Yahoo) pendant la saisie. */
    form.symbol.addEventListener("input", function () {
        window.clearTimeout(searchTimer);
        var q = form.symbol.value.trim();
        if (q.length < 2) return;
        searchTimer = window.setTimeout(async function () {
            try {
                var res = await fetch("/api/fund/instruments/search?q=" + encodeURIComponent(q) + "&kind=" + kind());
                var data = await res.json();
                var list = document.getElementById("f-symbol-list");
                list.textContent = "";
                (data.results || []).forEach(function (r) {
                    var o = document.createElement("option");
                    o.value = r.symbol;
                    o.label = r.name + (r.exchange ? " · " + r.exchange : "");
                    list.appendChild(o);
                });
            } catch (e) { /* suggestions facultatives */ }
        }, 250);
    });

    form.addEventListener("input", schedule);
    form.addEventListener("change", function (ev) {
        if (ev.target.name === "instrument_kind") applyKind();
        if (ev.target.name === "root") fillContracts();
        if (ev.target.name === "strategy_id") applyStrategy();
        if (ev.target.id === "f-manual-price") form.price.disabled = !ev.target.checked;
        if (ev.target.name === "fees_mode") form.fees.disabled = form.fees_mode.value !== "manual";
        schedule();
    });
    form.addEventListener("submit", async function (ev) {
        ev.preventDefault();
        if (!lastQuote || !lastQuote.ok) return;
        var req = request(), p = lastQuote.preview;
        if (!req) return;
        req.position_id = p.position_id;
        if (p.fees.source === "estimated") req.fee_seed = p.fees.seed;
        submit.disabled = true;
        try {
            await call("/api/fund/strategies/" + encodeURIComponent(req.strategy_id) + "/orders", "POST", req);
            window.location.href = "/simulate?strategy=" + encodeURIComponent(req.strategy_id) + "&placed=1";
        } catch (e) {
            say((e.blocking || [e.message]).join(" · "), "error");
            submit.disabled = false;
        }
    });

    fillRoots();
    applyKind();
    applyStrategy();
    renderEmpty();
})();
```

Ajouter à la fin de `patrick/patrick/webapp/static/patrick.css` :

```css

/* ---- Simulation (refonte chantier 1) : ticket d'ordre et aperçu ---- */
[data-kinds][hidden] { display: none; }
.fund-ticket-grid { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(280px, 1fr); gap: var(--space-lg); align-items: start; }
.fund-preview {
  position: sticky; top: calc(var(--topbar-h) + var(--space-md));
  padding: var(--space-md); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface-2);
}
.fund-preview-list { display: grid; grid-template-columns: auto 1fr; gap: 6px var(--space-md); margin: 0 0 var(--space-md); font-size: 13px; }
.fund-preview-list dt { color: var(--text-2); }
.fund-preview-list dd { margin: 0; text-align: right; }
.fund-choice { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-xs) var(--space-md); }
.fund-choice legend { padding: 0 var(--space-xs); }
@media (max-width: 900px) {
  .fund-ticket-grid { grid-template-columns: 1fr; }
  .fund-preview { position: static; }
}
```

- [ ] **Step 6 : Retirer l'ancien simulateur de `app.py` et ses tests**

Les routes `GET /simulate`, `POST /api/simulate` et `GET /api/simulate/{id}` disparaissent (le moteur `patrick/simulate/` et la table `simulation` restent pour le chantier 3). `GET /api/runs/{run_id}/trials` est conservée (générique, réutilisée au chantier 3).

```bash
$PY - <<'PYEOF'
from pathlib import Path
p = Path("patrick/webapp/app.py")
s = p.read_text(encoding="utf-8")
a0, a1 = s.index('@app.get("/simulate")'), s.index('@app.get("/api/phase9/journal")')
s = s[:a0] + s[a1:]
b0, b1 = s.index("_SIM_PARAM_FIELDS = set("), s.index("def main() -> None:")
s = s[:b0] + s[b1:]
old = "from patrick.simulate import engine as sim_engine\n"
assert s.count(old) == 1
s = s.replace(old, "")
assert "sim_engine" not in s and '"/simulate"' not in s
p.write_text(s, encoding="utf-8")

# l'ancien test de page devient un test de l'API des essais (seule route conservée)
import subprocess
subprocess.run(["git", "mv", "tests/test_simulate_webapp.py", "tests/test_runs_trials_api.py"], check=True)
t = Path("tests/test_runs_trials_api.py")
s = t.read_text(encoding="utf-8")
doc_end = s.index('"""', 3) + 3
s = ('"""API `GET /api/runs/{run_id}/trials` : essais d\'un run terminé, dont le gagnant (`is_best`). Route conservée\n'
     'après le retrait de l\'ancien simulateur : le mode ML du chantier 3 s\'appuiera dessus."""') + s[doc_end:]
i0, i1 = s.index("def test_simulate_page_lists_done_run"), s.index("def test_api_list_trials_returns_best_trial")
j0 = s.index("def test_api_simulate_end_to_end")
s = s[:i0] + s[i1:j0].rstrip() + "\n"
t.write_text(s, encoding="utf-8")
PYEOF
```

- [ ] **Step 7 : Vérifier**

```bash
$PY -m pytest tests/test_fund_simulate_page.py tests/test_fund_routes.py tests/test_runs_trials_api.py tests/test_nav_registry.py -q -W ignore
$PY -m ruff check patrick tests/test_fund_simulate_page.py tests/test_runs_trials_api.py
node --check patrick/webapp/static/simulate.js
```

Résultat attendu : tests verts, ruff propre (corriger d'éventuels imports devenus inutiles dans `test_runs_trials_api.py`), `node --check` sans sortie.

- [ ] **Step 8 : Commit**

```bash
git add -A patrick/webapp tests/test_fund_simulate_page.py tests/test_runs_trials_api.py
git commit -m "feat(fund): page Simulation (ticket d'ordre, aperçu serveur, portefeuilles) ; retrait de l'ancien simulateur" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 10 : Page Fonds (panneau de détail) et retrait de l'ancien simulateur patrimoine

**Files:**
- Create: `patrick/patrick/webapp/templates/fonds.html`, `patrick/patrick/webapp/templates/_fund_panel.html`, `patrick/patrick/webapp/static/fonds.js`, `patrick/tests/test_fund_fonds_page.py`
- Modify: `patrick/patrick/webapp/fund_routes.py`, `patrick/patrick/webapp/nav_registry.py`, `patrick/patrick/webapp/icons.py`, `patrick/patrick/webapp/static/patrick.css`, `patrick/patrick/webapp/wealth_routes.py`, `patrick/patrick/webapp/static/wealth.js`, `patrick/tests/test_nav_registry.py`, `patrick/tests/test_wealth_signal_replay.py`, la spec (§11)
- Delete: `patrick/patrick/webapp/templates/patrimoine_simulation.html`

**Interfaces:**
- Consumes (Tasks 7, 9) : `service.overview`, `service.strategy_snapshot`, `service.current_date`, les chaînes de `i18n_fund`, `/api/fund/strategies/{id}` (PATCH/DELETE), `/api/fund/strategies/{id}/orders`, `/api/fund/orders/{id}`, `/api/fund/positions/{id}`.
- Produces : `GET /fonds?strategy=<id>` (contexte : `strategies`, `fund`, `selected_id`) ; `GET /api/fund/strategies/{id}/panel` → fragment HTML `_fund_panel.html` (contexte : `snap`, `today`) ; `GET /patrimoine-simulation` → redirection 308 vers `/fonds` ; entrée de navigation `fonds` (catégorie `simulation`, ordre 20, clé `nav_fonds`).

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_fonds_page.py` :

```python
"""Page /fonds et fragment /api/fund/strategies/{id}/panel : rendu serveur, échappement, i18n, navigation."""
from __future__ import annotations

import re

import fund_support as fs
import pytest
from fastapi.testclient import TestClient

from patrick.webapp import i18n, i18n_fund, nav_registry
from patrick.webapp.app import app

XSS = "<script>alert(1)</script>"
XSS_ESCAPED = "&lt;script&gt;alert(1)&lt;/script&gt;"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PATRICK_DB_PATH", str(tmp_path / "patrick.db"))
    fs.install(monkeypatch)
    fs.freeze_today(monkeypatch)
    return TestClient(app)


def test_fonds_page_lists_strategies_and_totals(client):
    assert "Aucune stratégie." in client.get("/fonds").text
    a = fs.make_strategy(client)
    fs.make_strategy(client, "Actions PEA", wrapper="PEA", initial_capital=50_000)
    fs.place(client, a)
    html = client.get(f"/fonds?strategy={a}").text
    assert html.count('class="fund-row') == 2 and f'data-strategy-id="{a}"' in html
    assert "Valeur du fonds" in html and "Capital total" in html and "150 000,00 €" in html
    assert 'id="fund-panel"' in html and '<script src="/static/fonds.js"></script>' in html
    assert fs.json_script(html, "fund-selected") == a and 'class="fund-row is-selected"' in html
    assert fs.json_script(client.get("/fonds").text, "fund-selected") is None


def test_fonds_page_is_available_in_english(client):
    fs.make_strategy(client)
    fund = client.get("/fonds?lang=en").text
    assert "LP Fund" in fund and "Fund value" in fund and "Valeur du fonds" not in fund


def test_the_old_wealth_simulator_url_redirects_to_the_fund_page(client):
    resp = client.get("/patrimoine-simulation", follow_redirects=False)
    assert resp.status_code == 308 and resp.headers["location"] == "/fonds"
    assert client.get("/patrimoine-simulation").url.path == "/fonds"


def test_navigation_lists_fonds_in_the_simulation_category_and_lights_it_up(client):
    entries = [e.slug for e in nav_registry.entries_for("simulation")]
    assert entries == ["simulate", "fonds"]
    side = client.get("/fonds").text
    assert 'href="/fonds"' in side and 'href="/patrimoine-simulation"' not in side
    current = re.findall(r'<a href="([^"]+)"[^>]*aria-current="page"', side)
    assert current == ["/fonds"]
    assert "/patrimoine-simulation" not in nav_registry.registered_routes()
    assert nav_registry.is_non_page_route("/patrimoine-simulation")


def test_strategy_names_are_escaped_on_the_fund_page_and_in_the_panel(client):
    sid = fs.make_strategy(client, XSS)
    fs.place(client, sid)
    for url in ("/fonds", f"/api/fund/strategies/{sid}/panel"):
        html = client.get(url).text
        assert XSS_ESCAPED in html, url
        assert XSS not in html, url


def test_panel_for_a_strategy_without_positions(client):
    sid = fs.make_strategy(client)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "Aucune position ouverte." in html and f'href="/simulate?strategy={sid}"' in html
    assert "Valeur (NAV)" in html and "Historique des ordres (0)" in html
    assert "Positions fermées" not in html and "data-form=" not in html
    assert client.get("/api/fund/strategies/str_missing/panel").status_code == 404


def test_panel_shows_kpis_chart_positions_and_per_position_forms(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, instrument_kind="equity", symbol="AAPL", quantity=10)
    fs.place(client, sid, instrument_kind="future", side="short", quantity=1, date="2026-01-08",
             spec={"root": "ES", "year": 2026, "month": 12, "stop": 7000})
    fs.place(client, sid, instrument_kind="cfd", symbol="^GSPC", quantity=2, date="2026-01-09", spec={"leverage": 10})
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    for label in ("Valeur (NAV)", "Réalisé", "Latent", "Frais cumulés", "Volatilité annualisée", "Drawdown max",
                  "Exposition brute", "Levier brut", "Marge utilisée", "Liquidités disponibles", "Cash"):
        assert label in html, label
    chart = fs.json_script(html, "fund-chart-data")
    assert chart["capital"] == 100_000 and len(chart["series"]) > 5
    assert html.count('class="fund-position"') == 3 and html.count('data-form="adjust"') == 3
    assert html.count('data-form="correct"') == 3 and html.count('data-act="delete-position"') == 3
    assert "AAPL" in html and "ESZ26.CME" in html and "^GSPC" in html and "USD · " in html
    assert "éch. 2026-12-18" in html and "10:1" in html and "S 7" in html            # échéance, levier, stop
    assert html.count('value="modify"') == 2                                          # future et CFD seulement
    assert html.count('name="leverage"') == 2                                         # CFD : ajustement et correction
    assert "taux de référence USD" in html                                            # note affichée (FRED non configuré)
    assert 'id="fund-chart"' in html


def test_panel_lists_closed_positions_and_the_order_history(client):
    sid = fs.make_strategy(client)
    pid = fs.place(client, sid, quantity=4)["preview"]["position_id"]
    client.post(f"/api/fund/strategies/{sid}/orders", json={"action": "close", "position_id": pid, "date": "2026-01-12"})
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "Positions fermées" in html and "Fermée" in html and "2026-01-07 → 2026-01-12" in html
    assert "Historique des ordres (2)" in html and "Ouverture" in html and "Clôture" in html
    assert "Aucune position ouverte." in html and 'class="fund-position"' not in html


def test_panel_flags_manual_prices_and_fees_in_the_history(client):
    sid = fs.make_strategy(client)
    fs.place(client, sid, price=650, fees_mode="manual", fees=3)
    html = client.get(f"/api/fund/strategies/{sid}/panel").text
    assert "650 *" in html.replace(" ", " ") and "3,00 € *" in html


def test_no_untranslated_key_leaks_into_the_pages_in_either_language(client):
    sid = fs.make_strategy(client)
    pid = fs.place(client, sid, instrument_kind="cfd", symbol="^GSPC", quantity=2, spec={"leverage": 10})["preview"][
        "position_id"]
    fs.place(client, sid, symbol="AAPL", quantity=5, date="2026-01-08")
    client.post(f"/api/fund/strategies/{sid}/orders", json={"action": "close", "position_id": pid, "date": "2026-01-12"})
    for lang in ("fr", "en"):
        for url in ("/simulate", "/fonds", f"/api/fund/strategies/{sid}/panel"):
            html = re.sub(r'<script id="i18n-data".*?</script>', "", client.get(f"{url}{'&' if '?' in url else '?'}lang={lang}").text,
                          flags=re.DOTALL)
            assert re.findall(r"\bfund_[a-z_]+\b", html) == [], (url, lang)


def test_dynamic_label_families_are_all_translated():
    expected = {f"fund_kind_{k}" for k in ("equity", "etf", "future", "cfd")}
    expected |= {f"fund_side_{s}" for s in ("long", "short")}
    expected |= {f"fund_status_{s}" for s in ("open", "closed", "stop", "target", "expired")}
    expected |= {f"fund_action_{a}" for a in ("open", "increase", "reduce", "close", "modify")}
    assert expected <= set(i18n_fund.FUND_STRINGS)
    for key, entry in i18n_fund.FUND_STRINGS.items():
        assert entry["fr"] and entry["en"], key
    assert set(i18n.STRINGS) >= set(i18n_fund.FUND_STRINGS)


def test_the_fund_script_uses_only_exposed_and_defined_strings(client):
    js = client.get("/static/fonds.js").text
    used = set(re.findall(r"""['"](fund_[a-z_]+)['"]""", js)) | set(re.findall(r"""I18N\.(fund_[a-z_]+)""", js))
    assert used <= set(i18n.STRINGS), used - set(i18n.STRINGS)
    assert used <= set(i18n.js_strings("fr")), used - set(i18n.js_strings("fr"))
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_fonds_page.py -q -W ignore
```

Résultat attendu : échecs (pas de route `/fonds`).

- [ ] **Step 3 : Routes de la page, du panneau et de la redirection**

Dans `patrick/patrick/webapp/fund_routes.py` : (a) ajouter l'import

```python
from fastapi.responses import RedirectResponse
```

juste sous `from fastapi import FastAPI, HTTPException, Request` ; (b) insérer le bloc suivant **après** la fonction `simulate_page` et **avant** la ligne `    # ---------------------------------------------------------------- API`, suivi d'une ligne vide :

```python
    @app.get("/fonds")
    def fonds_page(request: Request, strategy: str | None = None):
        data = _call(service.overview, service.current_date())
        return templates.TemplateResponse(request, "fonds.html", {
            "strategies": data["strategies"], "fund": data["fund"], "selected_id": strategy,
            **context(request)})

    @app.get("/patrimoine-simulation")
    def legacy_wealth_simulation_page():
        """Ancienne page « Simulateur patrimoine » : remplacée par /fonds."""
        return RedirectResponse("/fonds", status_code=308)

    @app.get("/api/fund/strategies/{strategy_id}/panel")
    def api_strategy_panel(request: Request, strategy_id: str):
        """Fragment HTML (rendu serveur, échappé) du détail d'une stratégie pour /fonds."""
        today = service.current_date()

        def run(conn):
            return service.strategy_snapshot(conn, _require_strategy(conn, strategy_id), today)
        return templates.TemplateResponse(request, "_fund_panel.html", {
            "snap": _call(run), "today": today.isoformat(), **context(request)})
```

- [ ] **Step 4 : Gabarits, JavaScript et CSS**

Créer `patrick/patrick/webapp/templates/fonds.html` :

```html
{% extends "base_v2.html" %}
{% from "_components.html" import metric, empty_state %}
{% block title %}PATRICK — {{ t('fund_title') }}{% endblock %}

{# Page Fonds (chantier 1) : toutes les stratégies, total consolidé en tête.
   Un clic sur une ligne charge le panneau de détail (fragment HTML rendu par
   le serveur : /api/fund/strategies/{id}/panel -> _fund_panel.html, échappé
   par Jinja) sous le tableau. L'ajout d'une position se fait sur /simulate. #}

{% block content %}
<div class="page-header">
  <div>
    <h1 class="page-title">{{ t('fund_title') }}</h1>
    <p class="page-subtitle">{{ t('fund_subtitle') }}</p>
  </div>
  <div class="page-actions">
    <a class="btn" href="/simulate">{{ icon('plus') }} {{ t('fund_new_position') }}</a>
  </div>
</div>

<div id="fund-flash" class="banner hidden" role="status"></div>

{% if strategies %}
<div class="metric-grid">
  {{ metric(t('fund_total_nav'), fund.nav | eur, t('fund_total_nav_hint', n=fund.n_strategies), "neutral") }}
  {{ metric(t('fund_total_capital'), fund.capital | eur, t('fund_total_capital_hint'), "neutral") }}
  {{ metric(t('fund_total_pnl'), fund.pnl | eur, fund.pnl_pct | pct(1, true), "neutral") }}
</div>

<section class="card" aria-labelledby="fund-table-title">
  <div class="card-head"><h2 id="fund-table-title">{{ t('fund_strategies_title') }}</h2></div>
  <div class="table-scroll">
    <table class="data-table fund-table">
      <thead>
        <tr>
          <th>{{ t('fund_col_strategy') }}</th>
          <th>{{ t('fund_col_wrapper') }}</th>
          <th class="num pk-mono">{{ t('fund_col_nav') }}</th>
          <th class="num pk-mono">{{ t('fund_col_pnl') }}</th>
          <th class="num pk-mono">{{ t('fund_col_exposure') }}</th>
          <th class="num pk-mono">{{ t('fund_col_leverage') }}</th>
          <th class="num pk-mono">{{ t('fund_col_margin') }}</th>
          <th class="num pk-mono">{{ t('fund_col_positions') }}</th>
        </tr>
      </thead>
      <tbody>
        {% for s in strategies %}{% set k = s.kpis %}
        <tr class="fund-row{% if s.strategy.strategy_id == selected_id %} is-selected{% endif %}" data-strategy-id="{{ s.strategy.strategy_id }}"
            tabindex="0" role="button" aria-controls="fund-panel">
          <td>{{ s.strategy.name }}</td>
          <td><span class="tag">{{ s.strategy.wrapper }}</span></td>
          <td class="num pk-mono">{{ k.nav | eur }}</td>
          <td class="num pk-mono"><span class="{{ 'pos' if k.pnl >= 0 else 'neg' }}">{{ k.pnl | eur }} · {{ k.pnl_pct | pct(1, true) }}</span></td>
          <td class="num pk-mono">{{ k.gross_exposure_pct | pct(0) }}</td>
          <td class="num pk-mono">{{ k.leverage | qty }}×</td>
          <td class="num pk-mono">{{ k.margin_used | eur(0) }}</td>
          <td class="num pk-mono">{{ k.n_open_positions }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <p class="table-footer">{{ t('fund_table_footer') }}</p>
</section>

<section id="fund-panel" class="card fund-panel" hidden aria-live="polite"></section>
{% else %}
{{ empty_state(t('fund_no_strategy'), t('fund_no_strategy_hint')) }}
{% endif %}

<script id="fund-selected" type="application/json">{{ selected_id | tojson }}</script>
<script src="/static/fonds.js"></script>
{% endblock %}
```

Créer `patrick/patrick/webapp/templates/_fund_panel.html` :

```html
{% from "_components.html" import metric %}
{# Fragment « détail d'une stratégie » de /fonds (rendu serveur, échappé par Jinja ;
   injecté tel quel par fonds.js). `snap` = fund.service.strategy_snapshot. #}
{% set s = snap.strategy %}{% set k = snap.kpis %}
{% set open_positions = snap.positions | selectattr('status', 'equalto', 'open') | list %}
{% set closed_positions = snap.positions | rejectattr('status', 'equalto', 'open') | list %}
<div class="card-head">
  <h2>{{ s.name }} <span class="tag">{{ s.wrapper }}</span></h2>
  <div class="row">
    <button type="button" class="btn-ghost" data-act="rename" data-strategy-id="{{ s.strategy_id }}" data-name="{{ s.name }}">{{ t('fund_act_rename') }}</button>
    <button type="button" class="btn-ghost" data-act="archive" data-strategy-id="{{ s.strategy_id }}">{{ t('fund_act_archive') }}</button>
    <button type="button" class="btn-ghost" data-act="delete-strategy" data-strategy-id="{{ s.strategy_id }}"
            data-confirm="{{ t('fund_confirm_delete_strategy') }}">{{ t('fund_act_delete_strategy') }}</button>
    <button type="button" class="btn-secondary" data-act="close-panel">{{ t('fund_panel_close') }}</button>
  </div>
</div>
<p class="hint">{{ t('fund_panel_meta', start=s.opened_on, capital=(k.capital | eur)) }}</p>

{% for n in snap.notes %}<div class="banner banner-warning">{{ n }}</div>{% endfor %}
{% for v in snap.violations %}<div class="banner banner-error">{{ v }}</div>{% endfor %}
{% if snap.alert_days %}<div class="banner banner-warning">{{ t('fund_alert_margin', n=snap.alert_days | length, first=snap.alert_days[0]) }}</div>{% endif %}

<div class="metric-grid">
  {{ metric(t('fund_kpi_nav'), k.nav | eur, t('fund_hint_nav'), "neutral") }}
  {{ metric(t('fund_kpi_pnl'), (k.pnl | eur) ~ ' · ' ~ (k.pnl_pct | pct(1, true)), t('fund_hint_pnl'), "neutral") }}
  {{ metric(t('fund_kpi_realized'), k.realized | eur, t('fund_hint_realized'), "neutral") }}
  {{ metric(t('fund_kpi_latent'), k.latent | eur, t('fund_hint_latent'), "neutral") }}
  {{ metric(t('fund_kpi_fees'), k.fees | eur, t('fund_hint_fees'), "neutral") }}
  {{ metric(t('fund_kpi_dividends'), k.dividends | eur, t('fund_hint_dividends'), "neutral") }}
  {{ metric(t('fund_kpi_financing'), k.financing | eur, t('fund_hint_financing'), "neutral") }}
  {{ metric(t('fund_kpi_vol'), k.volatility | pct(1), t('fund_hint_vol'), "neutral") }}
  {{ metric(t('fund_kpi_sharpe'), k.sharpe | qty, t('fund_hint_sharpe'), "neutral") }}
  {{ metric(t('fund_kpi_dd'), k.max_drawdown | pct(1), t('fund_hint_dd'), "neutral") }}
  {{ metric(t('fund_kpi_gross'), k.gross_exposure_pct | pct(0), t('fund_hint_gross'), "neutral") }}
  {{ metric(t('fund_kpi_net'), k.net_exposure_pct | pct(0), t('fund_hint_net'), "neutral") }}
  {{ metric(t('fund_kpi_leverage'), (k.leverage | qty) ~ '×', t('fund_hint_leverage'), "neutral") }}
  {{ metric(t('fund_kpi_margin'), k.margin_used | eur, t('fund_hint_margin'), "neutral") }}
  {{ metric(t('fund_kpi_power'), k.buying_power | eur, t('fund_hint_power'), "neutral") }}
  {{ metric(t('fund_kpi_cash'), k.cash | eur, t('fund_hint_cash'), "neutral") }}
</div>

<h3>{{ t('fund_chart_title') }}</h3>
<div class="drift-legend">
  <span class="drift-legend-item"><span class="drift-legend-swatch" style="background: var(--brand)"></span>{{ t('fund_chart_nav') }}</span>
  <span class="drift-legend-item"><span class="drift-legend-swatch" style="background: var(--text-3)"></span>{{ t('fund_chart_capital') }}</span>
</div>
<div class="chart-wrap"><canvas id="fund-chart" class="chart-canvas" role="img" aria-label="{{ t('fund_chart_title') }}"></canvas></div>
<script id="fund-chart-data" type="application/json">{{ {"series": snap.series, "capital": k.capital} | tojson }}</script>

<h3>{{ t('fund_pos_title') }} <span class="hint">({{ open_positions | length }})</span></h3>
{% if open_positions %}
<div class="table-scroll">
  <table class="data-table fund-positions">
    <thead>
      <tr>
        <th>{{ t('fund_pcol_instrument') }}</th><th>{{ t('fund_pcol_side') }}</th>
        <th class="num pk-mono">{{ t('fund_pcol_qty') }}</th><th class="num pk-mono">{{ t('fund_pcol_entry') }}</th>
        <th class="num pk-mono">{{ t('fund_pcol_price') }}</th><th>{{ t('fund_pcol_fx') }}</th>
        <th class="num pk-mono">{{ t('fund_pcol_value') }}</th><th class="num pk-mono">{{ t('fund_pcol_pnl') }}</th>
        <th class="num pk-mono">{{ t('fund_pcol_fx_effect') }}</th><th class="num pk-mono">{{ t('fund_pcol_margin') }}</th>
        <th>{{ t('fund_pcol_levels') }}</th><th></th>
      </tr>
    </thead>
    <tbody>
      {% for p in open_positions %}
      {% set opening = snap.orders | selectattr('position_id', 'equalto', p.position_id) | selectattr('action', 'equalto', 'open') | first %}
      <tr class="fund-position">
        <td>
          <span class="pk-mono">{{ p.symbol }}</span> <span class="tag">{{ t('fund_kind_' ~ p.kind) }}</span>
          {% if p.expiry %}<span class="hint">{{ t('fund_expiry', date=p.expiry) }}</span>{% endif %}
          {% if p.leverage and p.kind == 'cfd' %}<span class="hint">{{ p.leverage | qty }}:1</span>{% endif %}
          {% if p.price_quality %}<span class="tag" title="{{ t('fund_quality_continuous') }}">!</span>{% endif %}
        </td>
        <td>{{ t('fund_side_' ~ p.side) }}</td>
        <td class="num pk-mono">{{ p.quantity | qty }}</td>
        <td class="num pk-mono">{{ p.avg_entry | qty }}</td>
        <td class="num pk-mono">{{ p.last_price | qty }}</td>
        <td class="pk-mono">{{ p.currency }}{% if p.currency != s.base_currency %} · {{ p.fx_open | qty }} → {{ p.fx_now | qty }}{% endif %}</td>
        <td class="num pk-mono">{{ p.value_base | eur }}</td>
        <td class="num pk-mono"><span class="{{ 'pos' if p.pnl >= 0 else 'neg' }}">{{ p.pnl | eur }} · {{ p.pnl_pct | pct(1, true) }}</span></td>
        <td class="num pk-mono">{{ p.fx_effect | eur }}</td>
        <td class="num pk-mono">{{ p.margin | eur(0) }}</td>
        <td class="pk-mono">{% if p.stop %}S {{ p.stop | qty }}{% endif %}{% if p.target %} · O {{ p.target | qty }}{% endif %}{% if not p.stop and not p.target %}—{% endif %}</td>
        <td class="fund-actions">
          <button type="button" class="btn-ghost" data-act="toggle" data-target="adj-{{ p.position_id }}">{{ t('fund_act_adjust') }}</button>
          {% if opening %}<button type="button" class="btn-ghost" data-act="toggle" data-target="cor-{{ p.position_id }}">{{ t('fund_act_correct') }}</button>{% endif %}
          <button type="button" class="btn-ghost" data-act="delete-position" data-position-id="{{ p.position_id }}"
                  data-confirm="{{ t('fund_confirm_delete_position') }}">{{ t('fund_act_delete') }}</button>
        </td>
      </tr>
      <tr class="fund-form-row" id="adj-{{ p.position_id }}" hidden>
        <td colspan="12">
          <form class="form fund-inline-form" data-form="adjust" data-strategy-id="{{ s.strategy_id }}"
                data-position-id="{{ p.position_id }}" data-kind="{{ p.kind }}">
            <div class="subgrid">
              <label>{{ t('fund_adj_action') }}
                <select name="action">
                  <option value="increase">{{ t('fund_adj_increase') }}</option>
                  <option value="reduce">{{ t('fund_adj_reduce') }}</option>
                  <option value="close">{{ t('fund_adj_close') }}</option>
                  {% if p.kind in ('future', 'cfd') %}<option value="modify">{{ t('fund_adj_modify') }}</option>{% endif %}
                </select>
              </label>
              <label data-actions="increase reduce">{{ t('fund_field_quantity') }} <input type="number" name="quantity" min="0" step="any"></label>
              <label>{{ t('fund_field_date') }} <input type="date" name="date" value="{{ today }}" min="{{ s.opened_on }}" max="{{ today }}"></label>
              <label data-actions="increase reduce close">{{ t('fund_field_price') }} <input type="number" name="price" min="0" step="any" placeholder="{{ t('fund_price_market') }}"></label>
              <label data-actions="increase reduce close">{{ t('fund_field_fees') }}
                <select name="fees_mode"><option value="estimated">{{ t('fund_fees_estimated') }}</option><option value="manual">{{ t('fund_fees_manual') }}</option></select>
              </label>
              <label data-actions="increase reduce close">{{ t('fund_fees_manual') }} <input type="number" name="fees" min="0" step="any"></label>
              {% if p.kind in ('future', 'cfd') %}
              <label data-actions="modify">{{ t('fund_field_stop') }} <input type="number" name="stop" min="0" step="any" value="{{ p.stop if p.stop else '' }}"></label>
              <label data-actions="modify">{{ t('fund_field_target') }} <input type="number" name="target" min="0" step="any" value="{{ p.target if p.target else '' }}"></label>
              {% endif %}
              {% if p.kind == 'cfd' %}
              <label data-actions="modify">{{ t('fund_field_leverage') }} <input type="number" name="leverage" min="1" step="any" value="{{ p.leverage }}"></label>
              {% endif %}
            </div>
            <p class="fund-form-error banner banner-error" hidden></p>
            <div class="row"><button type="submit" class="btn">{{ t('fund_adj_apply') }}</button></div>
          </form>
        </td>
      </tr>
      {% if opening %}
      <tr class="fund-form-row" id="cor-{{ p.position_id }}" hidden>
        <td colspan="12">
          <form class="form fund-inline-form" data-form="correct" data-order-id="{{ opening.order_id }}" data-kind="{{ p.kind }}">
            <div class="subgrid">
              <label>{{ t('fund_field_quantity') }} <input type="number" name="quantity" min="0" step="any" value="{{ opening.quantity }}"></label>
              <label>{{ t('fund_field_date') }} <input type="date" name="date" value="{{ opening.ts }}" min="{{ s.opened_on }}" max="{{ today }}"></label>
              <label>{{ t('fund_field_price') }} <input type="number" name="price" min="0" step="any" placeholder="{{ t('fund_price_market') }}"></label>
              <label>{{ t('fund_field_fees') }}
                <select name="fees_mode"><option value="estimated">{{ t('fund_fees_estimated') }}</option><option value="manual">{{ t('fund_fees_manual') }}</option></select>
              </label>
              <label>{{ t('fund_fees_manual') }} <input type="number" name="fees" min="0" step="any" value="{{ opening.fees if opening.fees_source == 'manual' else '' }}"></label>
              {% if p.kind in ('future', 'cfd') %}
              <label>{{ t('fund_field_stop') }} <input type="number" name="stop" min="0" step="any" value="{{ opening.spec.stop if opening.spec.stop else '' }}"></label>
              <label>{{ t('fund_field_target') }} <input type="number" name="target" min="0" step="any" value="{{ opening.spec.target if opening.spec.target else '' }}"></label>
              {% endif %}
              {% if p.kind == 'cfd' %}
              <label>{{ t('fund_field_leverage') }} <input type="number" name="leverage" min="1" step="any" value="{{ opening.spec.leverage }}"></label>
              {% endif %}
            </div>
            <p class="fund-form-error banner banner-error" hidden></p>
            <div class="row"><button type="submit" class="btn">{{ t('fund_adj_apply') }}</button></div>
          </form>
        </td>
      </tr>
      {% endif %}
      {% endfor %}
    </tbody>
  </table>
</div>
{% else %}
<p class="hint">{{ t('fund_pos_none') }} <a href="/simulate?strategy={{ s.strategy_id }}">{{ t('fund_new_position') }}</a></p>
{% endif %}

{% if closed_positions %}
<h3>{{ t('fund_pos_closed_title') }} <span class="hint">({{ closed_positions | length }})</span></h3>
<div class="table-scroll">
  <table class="data-table">
    <thead>
      <tr>
        <th>{{ t('fund_pcol_instrument') }}</th><th>{{ t('fund_pcol_side') }}</th><th>{{ t('fund_pcol_period') }}</th>
        <th>{{ t('fund_pcol_status') }}</th><th class="num pk-mono">{{ t('fund_pcol_pnl') }}</th>
        <th class="num pk-mono">{{ t('fund_kpi_fees') }}</th>
        <th></th>
      </tr>
    </thead>
    <tbody>
      {% for p in closed_positions %}
      <tr>
        <td><span class="pk-mono">{{ p.symbol }}</span> <span class="tag">{{ t('fund_kind_' ~ p.kind) }}</span></td>
        <td>{{ t('fund_side_' ~ p.side) }}</td>
        <td class="pk-mono">{{ p.opened_on }} → {{ p.closed_on }}</td>
        <td>{{ t('fund_status_' ~ p.status) }}</td>
        <td class="num pk-mono"><span class="{{ 'pos' if p.pnl >= 0 else 'neg' }}">{{ p.pnl | eur }} · {{ p.pnl_pct | pct(1, true) }}</span></td>
        <td class="num pk-mono">{{ p.fees | eur }}</td>
        <td class="fund-actions">
          <button type="button" class="btn-ghost" data-act="delete-position" data-position-id="{{ p.position_id }}"
                  data-confirm="{{ t('fund_confirm_delete_position') }}">{{ t('fund_act_delete') }}</button>
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endif %}

<details class="fund-orders">
  <summary>{{ t('fund_orders_title') }} ({{ snap.orders | length }})</summary>
  <div class="table-scroll">
    <table class="data-table">
      <thead>
        <tr>
          <th>{{ t('fund_field_date') }}</th><th>{{ t('fund_pcol_action') }}</th><th>{{ t('fund_pcol_instrument') }}</th>
          <th>{{ t('fund_pcol_side') }}</th><th class="num pk-mono">{{ t('fund_pcol_qty') }}</th>
          <th class="num pk-mono">{{ t('fund_pcol_price') }}</th><th class="num pk-mono">{{ t('fund_kpi_fees') }}</th>
        </tr>
      </thead>
      <tbody>
        {% for o in snap.orders | reverse %}
        <tr>
          <td class="pk-mono">{{ o.ts }}</td><td>{{ t('fund_action_' ~ o.action) }}</td>
          <td class="pk-mono">{{ o.symbol }}</td><td>{{ t('fund_side_' ~ o.side) }}</td>
          <td class="num pk-mono">{{ o.quantity | qty }}</td>
          <td class="num pk-mono">{{ o.price | qty }}{% if o.price_source == 'manual' %} *{% endif %}</td>
          <td class="num pk-mono">{{ o.fees | eur }}{% if o.fees_source == 'manual' %} *{% endif %}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  <p class="table-footer">{{ t('fund_orders_footer') }}</p>
</details>
```

Créer `patrick/patrick/webapp/static/fonds.js` :

```javascript
/* Page /fonds : un clic sur une stratégie charge son panneau (fragment HTML rendu par
   le serveur, échappé : GET /api/fund/strategies/{id}/panel), puis :
   - graphique de la valeur (canvas HiDPI, couleurs lues dans les jetons CSS au dessin) ;
   - Ajuster / Corriger / Supprimer une position, renommer / archiver / supprimer la stratégie,
     tous via /api/fund/* ; les refus de règle (422) s'affichent dans le formulaire. */
(function () {
    "use strict";
    var panel = document.getElementById("fund-panel");
    if (!panel) return;

    var I18N = window.I18N || {};
    var flash = document.getElementById("fund-flash");
    var rows = Array.prototype.slice.call(document.querySelectorAll(".fund-row"));
    var current = null;
    var MONO = getComputedStyle(document.documentElement).getPropertyValue("--mono").trim() || "monospace";

    function token(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }
    function say(text, kind) {
        if (!flash) { window.alert(text); return; }
        flash.textContent = text;
        flash.className = "banner " + (kind === "error" ? "banner-error" : "banner-info");
        flash.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    async function call(url, method, body) {
        var res = await fetch(url, {
            method: method || "POST",
            headers: { "Content-Type": "application/json" },
            body: body === undefined ? undefined : JSON.stringify(body),
        });
        var data = {};
        try { data = await res.json(); } catch (e) { data = {}; }
        if (!res.ok) {
            var err = new Error(typeof data.detail === "string" ? data.detail : "HTTP " + res.status);
            err.blocking = data.detail && data.detail.blocking ? data.detail.blocking : null;
            throw err;
        }
        return data;
    }
    function reload(id) { window.location.href = "/fonds" + (id ? "?strategy=" + encodeURIComponent(id) : ""); }

    /* ---- graphique : valeur contre capital ---- */
    function drawChart() {
        var canvas = document.getElementById("fund-chart"), dataEl = document.getElementById("fund-chart-data");
        if (!canvas || !dataEl) return;
        var data = JSON.parse(dataEl.textContent), pts = data.series || [];
        var ratio = window.devicePixelRatio || 1;
        var w = Math.max(280, Math.round(canvas.getBoundingClientRect().width || 600)), h = 260;
        canvas.style.height = h + "px";
        canvas.width = Math.round(w * ratio);
        canvas.height = Math.round(h * ratio);
        var ctx = canvas.getContext("2d");
        ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
        ctx.clearRect(0, 0, w, h);
        if (pts.length < 2) return;
        var vals = pts.map(function (p) { return p.nav; }).concat([data.capital]);
        var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
        if (min === max) { min -= 1; max += 1; }
        var t0 = new Date(pts[0].t).getTime(), t1 = new Date(pts[pts.length - 1].t).getTime();
        if (t1 === t0) t1 = t0 + 86400000;
        var padL = 78, padR = 14, padT = 12, padB = 26;
        function x(t) { return padL + (new Date(t).getTime() - t0) / (t1 - t0) * (w - padL - padR); }
        function y(v) { return padT + (1 - (v - min) / (max - min)) * (h - padT - padB); }
        ctx.font = "11px " + MONO;
        ctx.textAlign = "right";
        ctx.textBaseline = "middle";
        for (var i = 0; i <= 4; i++) {
            var v = min + (max - min) * i / 4, yy = Math.round(y(v)) + 0.5;
            ctx.strokeStyle = token("--chart-grid");
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(padL, yy); ctx.lineTo(w - padR, yy); ctx.stroke();
            ctx.fillStyle = token("--ink-text-2");
            ctx.fillText(Math.round(v).toLocaleString("fr-FR") + " €", padL - 8, yy);
        }
        ctx.textBaseline = "alphabetic";
        ctx.textAlign = "left";
        ctx.fillText(pts[0].t, padL, h - 7);
        ctx.textAlign = "right";
        ctx.fillText(pts[pts.length - 1].t, w - padR, h - 7);
        ctx.strokeStyle = token("--text-3");
        ctx.lineWidth = 1;
        ctx.setLineDash([5, 4]);
        ctx.beginPath(); ctx.moveTo(padL, y(data.capital)); ctx.lineTo(w - padR, y(data.capital)); ctx.stroke();
        ctx.setLineDash([]);
        ctx.strokeStyle = token("--brand");
        ctx.lineWidth = 1.8;
        ctx.beginPath();
        pts.forEach(function (p, k) { if (k === 0) ctx.moveTo(x(p.t), y(p.nav)); else ctx.lineTo(x(p.t), y(p.nav)); });
        ctx.stroke();
        canvas.setAttribute("aria-label", "Valeur de " + Math.round(pts[0].nav).toLocaleString("fr-FR") + " € le " + pts[0].t +
            " à " + Math.round(pts[pts.length - 1].nav).toLocaleString("fr-FR") + " € le " + pts[pts.length - 1].t);
    }
    window.addEventListener("patrick:themechange", drawChart);
    var resizeTimer = null;
    window.addEventListener("resize", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(drawChart, 150);
    });

    /* ---- panneau ---- */
    function mark() {
        rows.forEach(function (r) { r.classList.toggle("is-selected", r.getAttribute("data-strategy-id") === current); });
    }
    function open(id) {
        current = id;
        mark();
        panel.hidden = false;
        panel.textContent = "";
        var loading = document.createElement("p");
        loading.className = "hint";
        loading.textContent = "…";
        panel.appendChild(loading);
        fetch("/api/fund/strategies/" + encodeURIComponent(id) + "/panel")
            .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(function (html) {
                if (current !== id) return;
                panel.innerHTML = html;          // fragment rendu serveur, échappé par Jinja
                drawChart();
                panel.scrollIntoView({ block: "nearest", behavior: "smooth" });
            })
            .catch(function () { if (current === id) loading.textContent = "—"; });
    }
    function close() { current = null; mark(); panel.hidden = true; panel.textContent = ""; }

    rows.forEach(function (r) {
        function go() { open(r.getAttribute("data-strategy-id")); }
        r.addEventListener("click", go);
        r.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    });

    /* ---- formulaires en ligne : champs visibles selon l'action choisie ---- */
    function syncActions(form) {
        var select = form.elements.action;
        if (!select) return;
        form.querySelectorAll("[data-actions]").forEach(function (el) {
            el.hidden = el.getAttribute("data-actions").split(" ").indexOf(select.value) === -1;
        });
    }
    function present(v) { return v !== null && v !== undefined && String(v).trim() !== ""; }
    function showError(form, lines) {
        var box = form.querySelector(".fund-form-error");
        if (!box) return;
        box.textContent = lines.join(" · ");
        box.hidden = false;
    }
    function specOf(form) {
        var spec = {};
        ["stop", "target", "leverage"].forEach(function (name) {
            if (form.elements[name]) spec[name] = form.elements[name].value;
        });
        return spec;
    }
    async function submitAdjust(form) {
        var f = form.elements, action = f.action.value;
        var req = { action: action, position_id: form.getAttribute("data-position-id"), date: f.date.value };
        if (action === "increase" || action === "reduce") req.quantity = f.quantity.value;
        if (action !== "modify") {
            if (present(f.price.value)) req.price = f.price.value;
            req.fees_mode = f.fees_mode.value;
            if (req.fees_mode === "manual") req.fees = f.fees.value;
        } else {
            req.spec = specOf(form);
        }
        await call("/api/fund/strategies/" + encodeURIComponent(form.getAttribute("data-strategy-id")) + "/orders", "POST", req);
    }
    async function submitCorrect(form) {
        var f = form.elements;
        var req = { quantity: f.quantity.value, date: f.date.value, fees_mode: f.fees_mode.value, spec: specOf(form) };
        if (present(f.price.value)) req.price = f.price.value;
        if (req.fees_mode === "manual") req.fees = f.fees.value;
        await call("/api/fund/orders/" + encodeURIComponent(form.getAttribute("data-order-id")), "PATCH", req);
    }

    panel.addEventListener("change", function (e) {
        var form = e.target.closest("form[data-form]");
        if (form && e.target.name === "action") syncActions(form);
    });
    panel.addEventListener("submit", async function (e) {
        var form = e.target.closest("form[data-form]");
        if (!form) return;
        e.preventDefault();
        try {
            if (form.getAttribute("data-form") === "adjust") await submitAdjust(form); else await submitCorrect(form);
            reload(current);
        } catch (err) {
            showError(form, err.blocking || [err.message]);
        }
    });
    panel.addEventListener("click", async function (e) {
        var btn = e.target.closest("[data-act]");
        if (!btn) return;
        var act = btn.getAttribute("data-act");
        try {
            if (act === "close-panel") { close(); return; }
            if (act === "toggle") {
                var target = document.getElementById(btn.getAttribute("data-target"));
                if (target) {
                    target.hidden = !target.hidden;
                    var form = target.querySelector("form[data-form]");
                    if (form) syncActions(form);
                }
                return;
            }
            if (btn.hasAttribute("data-confirm") && !window.confirm(btn.getAttribute("data-confirm"))) return;
            if (act === "delete-position") {
                await call("/api/fund/positions/" + encodeURIComponent(btn.getAttribute("data-position-id")), "DELETE");
                reload(current);
            } else if (act === "delete-strategy") {
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "DELETE");
                reload(null);
            } else if (act === "archive") {
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "PATCH", { archived: true });
                reload(null);
            } else if (act === "rename") {
                var name = window.prompt(I18N.fund_rename_prompt || "", btn.getAttribute("data-name") || "");
                if (name === null || !name.trim()) return;
                await call("/api/fund/strategies/" + encodeURIComponent(btn.getAttribute("data-strategy-id")), "PATCH", { name: name.trim() });
                reload(current);
            }
        } catch (err) {
            say((err.blocking || [err.message]).join(" · "), "error");
        }
    });

    var pre = document.getElementById("fund-selected");
    var wanted = pre ? JSON.parse(pre.textContent) : null;
    if (wanted && rows.some(function (r) { return r.getAttribute("data-strategy-id") === wanted; })) open(wanted);
})();
```

Ajouter à la fin de `patrick/patrick/webapp/static/patrick.css` :

```css

/* ---- Fonds (refonte chantier 1) : tableau des stratégies et panneau de détail ---- */
.fund-form-row[hidden], .fund-form-error[hidden], .fund-inline-form label[hidden] { display: none; }
.fund-row { cursor: pointer; }
.fund-row:hover, .fund-row.is-selected { background: var(--surface-2); }
.fund-row:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.fund-panel { margin-top: var(--space-lg); }
.fund-panel h3 { margin: var(--space-lg) 0 var(--space-sm); }
.fund-actions { white-space: nowrap; text-align: right; }
.fund-inline-form { padding: var(--space-sm) 0; }
.fund-form-row > td { background: var(--surface-2); }
.fund-orders { margin-top: var(--space-lg); }
.fund-orders summary { cursor: pointer; font-weight: 600; }
```

- [ ] **Step 5 : Navigation : `Fonds` remplace « Simulateur patrimoine »**

```bash
$PY - <<'PYEOF'
from pathlib import Path

def edit(path, pairs):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:60])
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")

edit("patrick/webapp/nav_registry.py", [
    ('''    # SIMULATION -- rejouer des signaux deja produits (jamais de re-entrainement).
    NavEntry("simulate", "Simulateur", "/simulate", "simulation", 10, "nav_simulate"),
    # Roadmap bloc 4 : rejouer les signaux sur un patrimoine (URL a plat, cf.
    # PATRIMOINE ci-dessous : `/simulate/...` allumerait aussi `/simulate`).
    NavEntry("patrimoine_simulation", "Simulateur patrimoine", "/patrimoine-simulation", "simulation", 20,
             "nav_patrimoine_simulation"),
''', '''    # SIMULATION -- ouvrir des positions fictives (ticket d'ordres) puis suivre les strategies du fonds.
    NavEntry("simulate", "Simulation", "/simulate", "simulation", 10, "nav_simulate"),
    NavEntry("fonds", "Fonds", "/fonds", "simulation", 20, "nav_fonds"),
'''),
    ('''    "/runs/{run_id}/download/{artifact}",
})''', '''    "/runs/{run_id}/download/{artifact}",
    "/patrimoine-simulation",   # redirection permanente vers /fonds (ancienne page « Simulateur patrimoine »)
})'''),
])
edit("patrick/webapp/icons.py", [('"patrimoine_simulation": "briefcase",', '"fonds": "briefcase",')])
edit("tests/test_nav_registry.py", [('    ("/simulate", "/simulate"),\n', '    ("/simulate", "/simulate"),\n    ("/fonds", "/fonds"),\n')])
PYEOF
```

- [ ] **Step 6 : Retirer l'ancien simulateur patrimoine (page, API de rejeu, JavaScript, test)**

`wealth/signal_replay.py` et ses tests unitaires restent (réutilisés au chantier 3) ; seuls la page, la route `POST /api/wealth/accounts/{id}/replay`, le bloc JavaScript et le test d'API disparaissent.

```bash
git rm patrick/webapp/templates/patrimoine_simulation.html
$PY - <<'PYEOF'
from pathlib import Path

p = Path("patrick/webapp/wealth_routes.py")
s = p.read_text(encoding="utf-8")
a0 = s.index('    @app.get("/patrimoine-simulation")')
a1 = s.index("    # ---------------------------------------------------------------- API")
s = s[:a0] + s[a1:]
b0 = s.index('    @app.post("/api/wealth/accounts/{account_id}/replay")')
b1 = s.index('    @app.post("/api/wealth/accounts")')
s = s[:b0] + s[b1:]
for old, new in (("from patrick.simulate import engine as sim_engine\n", ""),
                 ("from patrick.wealth import importer, ledger, service, signal_replay, symbols\n",
                  "from patrick.wealth import importer, ledger, service, symbols\n")):
    assert s.count(old) == 1, old
    s = s.replace(old, new)
assert "sim_engine" not in s and "signal_replay" not in s
p.write_text(s, encoding="utf-8")

p = Path("patrick/webapp/static/wealth.js")
s = p.read_text(encoding="utf-8")
a0 = s.index("    /* ---- patrimoine replay (/patrimoine-simulation) ---- */")
a1 = s.rindex("})();")
p.write_text(s[:a0].rstrip() + "\n" + s[a1:], encoding="utf-8")

p = Path("tests/test_wealth_signal_replay.py")
s = p.read_text(encoding="utf-8")
p.write_text(s[: s.index("def test_replay_api_end_to_end")].rstrip() + "\n", encoding="utf-8")

# spec §11 : le fragment HTML du panneau
p = Path("../docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md")
s = p.read_text(encoding="utf-8")
old = "| `DELETE /api/fund/positions/{id}` | Supprimer une position entière. |"
assert s.count(old) == 1
s = s.replace(old, old + "\n| `GET /api/fund/strategies/{id}/panel` | Fragment HTML (rendu serveur, échappé) du détail d'une stratégie pour `/fonds`. |")
p.write_text(s, encoding="utf-8")
PYEOF
node --check patrick/webapp/static/wealth.js && node --check patrick/webapp/static/fonds.js
```

- [ ] **Step 7 : Vérifier**

```bash
$PY -m pytest tests/test_fund_fonds_page.py tests/test_fund_simulate_page.py tests/test_fund_routes.py tests/test_nav_registry.py tests/test_wealth_signal_replay.py tests/test_wealth_webapp.py tests/test_wealth.py -q -W ignore
$PY -m ruff check patrick tests/test_fund_fonds_page.py tests/test_wealth_signal_replay.py
```

Résultat attendu : tests verts ; ruff propre (retirer les imports devenus inutiles de `test_wealth_signal_replay.py` si ruff en signale). `test_no_orphan_page_route` passe : `/fonds` est une entrée de navigation, `/patrimoine-simulation` figure dans `NON_PAGE_ROUTES`, le panneau est sous `/api/`.

- [ ] **Step 8 : Commit**

```bash
git add -A patrick tests ../docs/superpowers/specs/2026-10-03-fonds-simulation-socle-design.md
git commit -m "feat(fund): page Fonds (stratégies, KPI, positions, ajustements) ; retrait du simulateur patrimoine" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 11 : Contrôle du catalogue, documentation, vérification complète

**Files:**
- Create: `patrick/scripts/check_fund_catalog.py`, `patrick/tests/test_fund_catalog_check.py`
- Modify: `patrick/README.md`, `patrick/ARCHITECTURE.md`, `design-system/patrick/MASTER.md`, éventuellement `patrick/patrick/fund/instruments.py` (retrait des racines que Yahoo ne sert pas)

**Interfaces:**
- Consumes : `instruments.FUTURES_CATALOG`, `instruments.listed_contracts`, `prices.download_bars`, `service.current_date`.
- Produces : `scripts/check_fund_catalog.py` : `check(download=None) -> {racine: [symboles servis]}` et `main() -> int` (code 1 si une racine n'a aucun contrat servi).

- [ ] **Step 1 : Écrire le test qui échoue**

Créer `patrick/tests/test_fund_catalog_check.py` :

```python
"""`scripts/check_fund_catalog.py` : le rapport liste les contrats servis et signale les racines sans données."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import fund_support as fs
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_fund_catalog.py"


@pytest.fixture
def script(monkeypatch):
    fs.freeze_today(monkeypatch)
    spec = importlib.util.spec_from_file_location("check_fund_catalog", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_report_lists_served_contracts_and_empty_roots(script):
    def download(symbol, start=None):
        return fs.fake_download("ESZ26.CME") if symbol.startswith("ESH26") else (None, None)

    report = script.check(download)
    assert report["ES"] == ["ESH26.CME"] and report["CL"] == [] and set(report) >= {"ES", "CL", "NG", "GC"}


def test_main_exits_with_1_when_a_root_has_no_contract(script, monkeypatch, capsys):
    monkeypatch.setattr(script.prices, "download_bars", lambda symbol, start=None: (None, None))
    assert script.main() == 1
    out = capsys.readouterr().out
    assert "AUCUN CONTRAT SERVI" in out and "À retirer du catalogue" in out


def test_main_exits_with_0_when_every_root_is_served(script, monkeypatch, capsys):
    monkeypatch.setattr(script.prices, "download_bars", lambda symbol, start=None: fs.fake_download("ESZ26.CME"))
    assert script.main() == 0
    assert "OK" in capsys.readouterr().out
```

- [ ] **Step 2 : Vérifier l'échec**

```bash
$PY -m pytest tests/test_fund_catalog_check.py -q -W ignore
```

Résultat attendu : erreur (script absent).

- [ ] **Step 3 : Créer le script**

Créer `patrick/scripts/check_fund_catalog.py` :

```python
"""Contrôle MANUEL (réseau) du catalogue de futures de la page Simulation : chaque racine
doit avoir au moins un contrat côté Yahoo Finance parmi les premiers contrats cotés.
Une racine sans contrat servi est à retirer de `patrick/fund/instruments.py` (ou à corriger).

Usage, depuis `patrick/` avec le venv du projet :
    python scripts/check_fund_catalog.py
Code de sortie 1 si une racine n'a aucun contrat servi."""
from __future__ import annotations

import sys

from patrick.fund import instruments, prices, service


def check(download=None) -> dict[str, list[str]]:
    """{racine: [symboles servis]} pour les 3 premiers contrats cotés de chaque racine."""
    download = download or prices.download_bars
    today = service.current_date()
    report: dict[str, list[str]] = {}
    for root in instruments.FUTURES_CATALOG:
        served = []
        for contract in instruments.listed_contracts(root, today, n=3):
            df, _currency = download(contract["symbol"])
            if df is not None and not df.empty:
                served.append(contract["symbol"])
        report[root] = served
    return report


def main() -> int:
    report = check()
    for root, served in report.items():
        print(f"{root:5s} {('OK  ' + ', '.join(served)) if served else 'AUCUN CONTRAT SERVI'}")
    missing = [root for root, served in report.items() if not served]
    if missing:
        print("À retirer du catalogue ou à corriger : " + ", ".join(missing))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4 : Vérifier le test, puis contrôler le catalogue réel (réseau)**

```bash
$PY -m pytest tests/test_fund_catalog_check.py -q -W ignore
$PY scripts/check_fund_catalog.py
```

Résultat attendu de la seconde commande : une ligne par racine. Pour chaque racine marquée `AUCUN CONTRAT SERVI`, retirer son entrée de `FUTURES_CATALOG` dans `patrick/patrick/fund/instruments.py` (les micro-contrats `MES`, `MNQ`, `MCL`, `MGC` sont les plus susceptibles de manquer), puis relancer `$PY scripts/check_fund_catalog.py` jusqu'au code de sortie 0. Les tests s'appuient seulement sur `ES`, `CL`, `NG`, `GC`, servis par Yahoo au 2026-10-03.

- [ ] **Step 5 : Mettre à jour la documentation**

```bash
$PY - <<'PYEOF'
from pathlib import Path

def edit(path, pairs):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert s.count(old) == 1, (path, old[:70])
        s = s.replace(old, new)
    p.write_text(s, encoding="utf-8")

edit("README.md", [
    ("Pages (nav: Synthèse · Lancer · Historique · Univers · Simulateur · Phase 9):",
     "Pages (nav: Synthèse · Lancer · Historique · Univers · Simulation · Fonds · Phase 9):"),
    ("- `/simulate` — position-sizing/backtest simulator on a trained model.",
     "- `/simulate` — order ticket: open long/short paper positions (stock/ETF, future, CFD) on a strategy\n"
     "  (capital, PEA or CTO wrapper) at a chosen execution date, with market prices and typed or estimated\n"
     "  fees; portfolios by strategy below the ticket.\n"
     "- `/fonds` (EN: LP Fund) — every strategy with portfolio KPIs (P&L in € and %, currency and FX effect,\n"
     "  value chart); click one to adjust, correct or close its positions."),
])
edit("ARCHITECTURE.md", [
    ("| `simulate/` | Moteur de simulation P&L théorique à partir des prédictions persistées (jamais de ré-entraînement), utilisé par `/simulate`. |",
     "| `fund/` | Stratégies, ordres et valorisation de positions fictives (action/ETF, future, CFD) : `engine.py` (rejeu des ordres jour par jour), `service.py` (aperçu et passage d'ordres), `prices.py` (cotations persistantes), `rules.py` (PEA/CTO), `fees.py`, `instruments.py`, `kpis.py`, `store.py` — pages `/simulate` et `/fonds`. |\n"
     "| `simulate/` | Moteur de simulation P&L théorique à partir des prédictions persistées (jamais de ré-entraînement). Plus de page depuis la refonte Simulation/Fonds : réutilisé par le mode ML du chantier 3. |"),
    ("d'ensemble cible×horizon) et `/simulate`.", "d'ensemble cible×horizon), `/simulate` (ticket d'ordres) et `/fonds`."),
])
edit("../design-system/patrick/MASTER.md", [
    ("| `simulation` | SIMULATION | Rejouer des signaux déjà produits (jamais de ré-entraînement). |",
     "| `simulation` | SIMULATION | Ouvrir des positions fictives (ticket d'ordres) et suivre les stratégies du fonds. |"),
])
PYEOF
git diff --stat
```

- [ ] **Step 6 : Suite rapide complète et lint**

```bash
$PY -m pytest -q -m "not slow" -W ignore
$PY -m ruff check .
```

Résultat attendu : toute la suite rapide passe (environ 2 minutes) et `All checks passed!`. Si un test hors périmètre échoue, vérifier d'abord s'il échoue aussi sur `main` (dans le dépôt principal, `cd /c/Users/leonp/PATRICK/patrick`) avant d'y toucher.

- [ ] **Step 7 : Vérification manuelle dans le navigateur (cotations réelles, base temporaire)**

Utiliser une base temporaire pour ne pas migrer la vraie base avant la fusion :

```bash
export PATRICK_DB_PATH="$(mktemp -d)/patrick.db"
$PY -m uvicorn patrick.webapp.app:app --port 8765
```

Puis, avec le navigateur intégré (`preview_start` avec `url: http://127.0.0.1:8765/simulate`), vérifier :

1. `/simulate` : créer une stratégie CTO de 100 000 € ouverte il y a 3 mois ; préparer un achat de `MC.PA` (quantité 3) : l'aperçu affiche prix, frais estimés, cash restant ; changer la date, le montant des frais ne saute pas entre deux rafraîchissements ; « Ouvrir la position » → bandeau « Position ouverte ».
2. Future : choisir `ES` et un contrat coté ; l'aperçu affiche marge et notionnel ; un levier CFD au-dessus du plafond est refusé avec le motif.
3. PEA : créer une stratégie PEA ; une action en USD (`AAPL`) est refusée (« titres cotés en euro seulement »), un short aussi.
4. `/fonds?strategy=<id>` : le panneau s'ouvre, le graphique se dessine, Ajuster (alléger, fermer, modifier stop/objectif), Corriger et Supprimer fonctionnent ; une quantité trop grande affiche le refus dans le formulaire.
5. Affichage mobile (`resize_window` en `mobile`) : pas de défilement horizontal de la page ; remettre `desktop` ensuite.
6. `read_console_messages` : aucune erreur JavaScript. Arrêter le serveur (`Ctrl+C`).

- [ ] **Step 8 : Commit**

```bash
git add patrick/scripts/check_fund_catalog.py tests/test_fund_catalog_check.py patrick/fund README.md ARCHITECTURE.md ../design-system/patrick/MASTER.md
git commit -m "feat(fund): contrôle du catalogue de futures, documentation, vérification complète" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9 : Intégration (skill `superpowers:finishing-a-development-branch`)**

Points propres à ce dépôt :
- La branche `feature/fonds-socle` modifie `app.py` et `i18n.py`, que le dépôt principal a **non commités** (autre chantier : contrôles de runs). Avant de fusionner dans `main`, attendre que ce chantier soit commité, puis fusionner ; résoudre les conflits éventuels sur `i18n.py`/`app.py` en gardant les deux jeux de modifications.
- La migration `0029_fund.sql` s'applique à la **vraie** base au prochain démarrage du serveur après la fusion. Selon la mémoire du projet, le serveur et le worker se lancent depuis le PowerShell de Léon, jamais depuis l'application Claude, et aucune maintenance de base ne se fait pendant un run : redémarrer `patrick serve` quand aucun run n'est en cours.
- Chaînes laissées volontairement : les clés `sim_*` et `nav_patrimoine_simulation` de `i18n.py`, ainsi que les termes de glossaire `wealth_simulation*`, ne sont plus utilisées ; leur suppression est un nettoyage séparé.
- Marges, commissions et spreads sont indicatifs (spec §8, §15) ; la liste des paires de devises majeures (limites ESMA) est à relire par l'utilisateur.
- Après la fusion : `git worktree remove ../PATRICK-fonds` puis `git branch -d feature/fonds-socle`.
