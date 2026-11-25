"""Captures des pages principales sur la base de démonstration (AM17 du 25/11) : non-régression visuelle à l'œil, à chaque PR.

    python .github/scripts/page_screenshots.py <dossier de sortie>

Construit une base SYNTHÉTIQUE (`patrick/scripts/make_demo_db.py`), lance `patrick serve` dessus (sans worker ni rafraîchissement),
ouvre chaque page dans Chromium (Playwright) à 1280 px puis à 375 px, et écrit :

- une capture pleine page par page et par largeur (`<page>-desktop.png`, `<page>-mobile.png`) ;
- `rapport.md` : erreurs de la console, défilement horizontal à 375 px (règle des 320-375 px), page en erreur.

La tâche de CI qui l'appelle est informative (`continue-on-error`) : les captures sont publiées comme artefact pour être regardées
dans la PR ; le rapport signale ce qui mérite un coup d'œil. Rien n'est comparé au pixel près (les polices du système changent).
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ["/", "/predictions", "/runs", "/fonds", "/ml", "/rl", "/exploration", "/placements", "/sante", "/connaissances", "/reel",
         "/targets/%5EGSPC"]
WIDTHS = {"desktop": (1280, 900), "mobile": (375, 812)}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _demo_db(folder: Path) -> Path:
    spec = importlib.util.spec_from_file_location("make_demo_db", ROOT / "patrick" / "scripts" / "make_demo_db.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    path = folder / "patrick.db"
    module.build(str(path), dt.date(2026, 11, 13))
    return path


def _wait(port: int, timeout_s: float = 60) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise SystemExit("le serveur n'a pas répondu en 60 s")


def main(out_dir: str) -> int:
    from playwright.sync_api import sync_playwright

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="patrick-shots-"))
    env = {**os.environ, "PATRICK_DB_PATH": str(_demo_db(tmp)), "PATRICK_LIVE_REFRESH": "0", "PATRICK_NO_AUTO_WORKER": "1",
           "PATRICK_DATA_ROOT": str(tmp / "data"), "PATRICK_CACHE_ROOT": str(tmp / "cache"), "PATRICK_FEATURE_CACHE_ROOT": str(tmp / "fcache"),
           "PATRICK_SETTINGS_PATH": str(tmp / "settings.json"), "PATRICK_INSTRUMENT_LOOKUP": "0", "PATRICK_ADVICE_PREWARM": "0"}
    (tmp / "data").mkdir()
    port = _free_port()
    server = subprocess.Popen([sys.executable, "-m", "patrick.cli", "serve", "--port", str(port)], cwd=ROOT / "patrick", env=env)
    lines = ["# Captures des pages (base de démonstration)", "", "| page | largeur | statut | console | défilement horizontal |", "|---|---|---|---|---|"]
    try:
        _wait(port)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for name, (w, h) in WIDTHS.items():
                page = browser.new_page(viewport={"width": w, "height": h})
                errors: list[str] = []
                page.on("console", lambda msg, errs=errors: errs.append(msg.text) if msg.type == "error" else None)
                for url in PAGES:
                    errors.clear()
                    response = page.goto(f"http://127.0.0.1:{port}{url}", wait_until="networkidle", timeout=90_000)
                    page.wait_for_timeout(1500)                       # blocs différés et graphiques
                    overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    slug = url.strip("/").replace("/", "_").replace("%5E", "") or "accueil"
                    page.screenshot(path=str(out / f"{slug}-{name}.png"), full_page=True)
                    status = response.status if response else "?"
                    lines.append(f"| `{url}` | {name} | {status} | {len(errors)} {'⚠' if errors else ''} | "
                                 f"{str(overflow) + ' px ⚠' if overflow > 1 else 'non'} |")
                page.close()
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=30)
    (out / "rapport.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "captures"))
