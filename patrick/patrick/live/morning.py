"""Résumé du matin lisible sur téléphone (FO28 du 25/11) : une page HTML autonome, sans montant ni compte, déposée dans un dossier.

Le serveur de PATRICK n'écoute que sur ce PC : un téléphone ne peut pas l'ouvrir. Après les prédictions, `patrick morning --to <dossier>`
écrit `patrick-matin.html` dans un dossier synchronisé (Drive, OneDrive) : la dernière direction de chaque champion (cible, horizon, sens,
P(hausse), date du signal), triée par conviction. Aucune donnée personnelle : ni fonds, ni patrimoine, ni chemin de fichier.
"""
from __future__ import annotations

import datetime as dt
import html
import sqlite3
from pathlib import Path

FILE_NAME = "patrick-matin.html"


def latest_signals(conn: sqlite3.Connection, limit: int = 60) -> list[dict]:
    rows = conn.execute(
        "SELECT c.target, c.horizon, p.ts, p.y_pred, p.p_up FROM champion c JOIN prediction p ON p.trial_id = c.trial_id AND p.split = 'live' "
        "WHERE p.ts = (SELECT MAX(p2.ts) FROM prediction p2 WHERE p2.trial_id = c.trial_id AND p2.split = 'live')").fetchall()
    out = [{"target": t, "horizon": int(h), "day": str(ts)[:10], "up": float(y) >= 2, "p_up": p} for t, h, ts, y, p in rows]
    out.sort(key=lambda r: -abs((r["p_up"] if r["p_up"] is not None else 0.5) - 0.5))
    return out[:limit]


def _pct(p) -> str:
    return "—" if p is None else f"{p * 100:.0f} %"


def render(signals: list[dict], now: dt.datetime | None = None, name_of=None) -> str:
    now = now or dt.datetime.now()  # noqa: DTZ005 -- heure locale lue par l'utilisateur
    name_of = name_of or (lambda s: s)
    rows = "".join(
        f"<tr><td>{html.escape(name_of(s['target']))}</td><td>{s['horizon']} j</td>"
        f"<td class=\"{'up' if s['up'] else 'down'}\">{'▲ hausse' if s['up'] else '▼ baisse'}</td>"
        f"<td>{_pct(s['p_up'])}</td><td>{s['day']}</td></tr>"
        for s in signals)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PATRICK · matin</title><style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#0b0b0c;color:#ededed}}h1{{font-size:18px}}table{{width:100%;border-collapse:collapse;font-size:14px}}
td,th{{padding:6px 4px;border-bottom:1px solid #2a2a2e;text-align:left}}.up{{color:#3fb950}}.down{{color:#f85149}}p{{color:#9a9aa0;font-size:12px}}
@media (prefers-color-scheme: light){{body{{background:#fff;color:#111}}td,th{{border-color:#e5e5e5}}.up{{color:#1a7f37}}.down{{color:#cf222e}}}}
</style></head><body><h1>Signaux du matin</h1><p>Mis à jour le {now:%d/%m/%Y à %H:%M} · {len(signals)} champion(s), triés par conviction.
Une probabilité n'est pas une certitude ; rien ici n'est un conseil.</p>
<table><thead><tr><th>Actif</th><th>Horizon</th><th>Sens</th><th>P(hausse)</th><th>Signal du</th></tr></thead><tbody>{rows}</tbody></table>
</body></html>"""


def write(conn: sqlite3.Connection, folder: str, name_of=None) -> Path:
    dest = Path(folder)
    if not dest.is_dir():
        raise FileNotFoundError(f"dossier introuvable : {folder}")
    path = dest / FILE_NAME
    tmp = path.with_suffix(".html.tmp")
    tmp.write_text(render(latest_signals(conn), name_of=name_of), encoding="utf-8")
    tmp.replace(path)
    return path
