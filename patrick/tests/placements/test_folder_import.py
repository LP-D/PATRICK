"""Import automatique des relevés déposés dans un dossier (FO20 du 25/11)."""
from __future__ import annotations

from patrick.tracking import db as trackdb
from patrick.wealth import folder_import, ledger

CSV = "Date;Libellé;Montant\n02/01/2026;Virement reçu;1000,00\n05/01/2026;Virement reçu;250,00\n"


def test_new_statements_are_imported_once_and_put_away(tmp_path):
    (tmp_path / "releve-janvier.csv").write_text(CSV, encoding="utf-8")
    conn = trackdb.connect()
    try:
        acc = ledger.create_account(conn, "Compte titres", "CTO", "real", "EUR")
        account_id = acc["account_id"] if isinstance(acc, dict) else acc
        out = folder_import.run(conn, str(tmp_path), account_id)
        assert out["written"] == 2 and out["files"][0]["status"] == "ok"
        assert not list(tmp_path.glob("*.csv")) and len(list((tmp_path / "importés").glob("*.csv"))) == 1
        (tmp_path / "releve-bis.csv").write_text(CSV, encoding="utf-8")            # le même relevé redéposé : rien de neuf
        again = folder_import.run(conn, str(tmp_path), account_id)
        assert again["written"] == 0 and again["files"][0]["skipped"] == 2
    finally:
        conn.close()


def test_an_unreadable_file_goes_to_refused_with_its_reason(tmp_path):
    (tmp_path / "vide.csv").write_bytes(b"")
    conn = trackdb.connect()
    try:
        acc = ledger.create_account(conn, "Compte", "CTO", "real", "EUR")
        account_id = acc["account_id"] if isinstance(acc, dict) else acc
        out = folder_import.run(conn, str(tmp_path), account_id)
        assert out["files"][0]["status"] == "refused" and list((tmp_path / "refusés").glob("*.raison.txt"))
    finally:
        conn.close()
