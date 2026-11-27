"""Requêtes SQL d'écriture assemblées avec des noms dynamiques (AM15 du 25/11) : liste blanche relue.

Une requête qui colle des noms de colonnes ou de tables dans du texte (`f"UPDATE t SET {sets}"`) n'est sûre que si ces noms viennent
d'une liste fermée, jamais d'une saisie. Chaque constructeur ci-dessous a été relu le 25/11 : ses noms viennent d'une liste de
colonnes du module ou d'un ensemble `allowed` vérifié avant la requête. Un NOUVEAU constructeur fait échouer ce test : le relire, puis
l'ajouter ici avec la raison."""
from __future__ import annotations

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "patrick"

# fichier -> raison (relue le 25/11)
REVIEWED: dict[str, str] = {
    "earnings/store.py": "UPDATE earn_batch_item : clés filtrées par `allowed` ; INSERT earn_calendar : `_CAL_COLS` du module",
    "fund/limit_orders.py": "UPDATE fund_limit_order : `_update` refuse toute clé hors `_UPDATABLE`",
    "fund/share.py": "ON CONFLICT DO UPDATE : colonnes fixes du module",
    "wealth/share.py": "tables de `TABLES` (constante du module), colonnes lues du schéma local (PRAGMA) et croisées avec le fichier reçu",
    "fund/store.py": "UPDATE fund_strategy : `allowed` ; fund_order : `_ORDER_COLUMNS` ; `_NOW` constante",
    "fund/systematic.py": "DELETE : seulement des marques `?`",
    "storage/cache_eviction.py": "DELETE FROM {table} : tables d'une liste fixe du module",
    "tracking/champions.py": "DELETE FROM {table} : tables d'une liste fixe du module",
    "tracking/jobs.py": "UPDATE job : fragments littéraux `col = ?` écrits dans la fonction",
    "tracking/prediction_archive.py": "DELETE/INSERT prediction : `COLUMNS` du module, clause WHERE de marques `?`",
    "wealth/ledger.py": "UPDATE wealth_account : clés filtrées (`champ(s) non modifiable(s)`)",
}

_WRITE = re.compile(r'f"(?:UPDATE|INSERT|DELETE|REPLACE)\b[^"]*\{|f"[^"]*\bSET \{')


def test_every_dynamic_write_query_is_in_the_reviewed_list():
    found = set()
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if _WRITE.search(text):
            found.add(path.relative_to(PKG).as_posix())
    new = sorted(found - set(REVIEWED))
    assert not new, f"requête d'écriture assemblée non relue : {new} (relire la provenance des noms, puis l'ajouter à REVIEWED)"


def test_the_reviewed_list_has_no_stale_entry():
    stale = [f for f in REVIEWED if not (PKG / f).is_file() or not _WRITE.search((PKG / f).read_text(encoding="utf-8"))]
    assert not stale, f"entrée périmée : {stale}"
