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
