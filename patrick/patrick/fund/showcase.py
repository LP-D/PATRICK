"""Page vitrine d'un fonds (A26) : un fichier HTML autonome à montrer (CV, portfolio), sans aucun montant ni donnée personnelle.

Seuls des pourcentages et des ratios sortent : performance rebasée à 100, P&L en %, Sharpe, repli maximal, VaR, exposition, nombre de positions.
Ni capital, ni valeur en euros, ni ordre daté : une stratégie simulée se décrit par sa trajectoire, pas par un solde. Le graphique est un SVG
calculé ici (aucun script, aucune ressource externe) : le fichier s'ouvre hors ligne et s'imprime tel quel. Avertissement en pied de page :
simulation, pas une recommandation.
"""
from __future__ import annotations

import html
import math

W, H, PAD = 720, 240, 36


def _svg_curve(points: list[tuple[str, float]]) -> str:
    values = [v for _t, v in points if v is not None and math.isfinite(v)]
    if len(values) < 2:
        return ""
    lo, hi = min(values + [100.0]), max(values + [100.0])
    span = (hi - lo) or 1.0
    n = len(points) - 1

    def xy(i: int, v: float) -> tuple[float, float]:
        return PAD + (W - 2 * PAD) * i / n, H - PAD - (H - 2 * PAD) * (v - lo) / span

    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (_t, v) in enumerate(points) if v is not None
                    for x, y in [xy(i, v)])
    y100 = xy(0, 100.0)[1]
    first, last = html.escape(points[0][0]), html.escape(points[-1][0])
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Performance, base 100" xmlns="http://www.w3.org/2000/svg">'
            f'<line x1="{PAD}" x2="{W - PAD}" y1="{y100:.1f}" y2="{y100:.1f}" stroke="#999" stroke-dasharray="4 4"/>'
            f'<path d="{path}" fill="none" stroke="#e8890c" stroke-width="2"/>'
            f'<text x="{PAD}" y="{H - 10}" font-size="11" fill="#666">{first}</text>'
            f'<text x="{W - PAD}" y="{H - 10}" font-size="11" fill="#666" text-anchor="end">{last}</text>'
            f'<text x="{W - PAD + 4}" y="{y100 + 4:.1f}" font-size="11" fill="#666">100</text></svg>')


def _pct(v: float | None, d: int = 1) -> str:
    return "—" if v is None or not math.isfinite(v) else f"{v * 100:+.{d}f} %".replace(".", ",")


def _num(v: float | None, d: int = 2) -> str:
    return "—" if v is None or not math.isfinite(v) else f"{v:.{d}f}".replace(".", ",")


def render(snapshot: dict) -> str:
    """HTML autonome d'un instantané de stratégie (`fund.service.strategy_snapshot`)."""
    s, k = snapshot["strategy"], snapshot["kpis"]
    series = snapshot.get("series") or []
    base = next((p["nav"] for p in series if p.get("nav")), None)
    points = [(p["t"], 100 * p["nav"] / base if base and p.get("nav") is not None else None) for p in series]
    tail = k.get("tail") or {}
    rows = [("Performance (avant frais)", _pct(k.get("gross_pnl_pct"))), ("Performance (après frais)", _pct(k.get("pnl_pct"))),
            ("Sharpe annualisé", _num(k.get("sharpe"))), ("Repli maximal", _pct(-(k.get("max_drawdown") or 0)) if k.get("max_drawdown") else "—"),
            ("VaR 99 % sur un jour", _pct(-tail["var_evt"], 2) if tail.get("var_evt") else "—"),
            ("Volatilité annualisée", _pct(k.get("volatility")).lstrip("+")), ("Exposition brute", _pct(k.get("gross_exposure_pct"), 0).lstrip("+")),
            ("Positions ouvertes", str(k.get("n_open_positions", 0))), ("Séances simulées", str(k.get("n_sessions", 0)))]
    table = "".join(f"<tr><th>{html.escape(a)}</th><td>{html.escape(b)}</td></tr>" for a, b in rows)
    period = f"{html.escape(series[0]['t'])} → {html.escape(series[-1]['t'])}" if series else ""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(s['name'])} — PATRICK</title>
<style>
body {{ font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; color: #1a1a1a; background: #fff; max-width: 780px; margin: 32px auto; padding: 0 16px; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }} .sub {{ color: #666; margin: 0 0 20px; }}
svg {{ width: 100%; height: auto; border: 1px solid #eee; border-radius: 8px; }}
table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }} th, td {{ padding: 6px 8px; border-bottom: 1px solid #eee; text-align: left; }}
td {{ text-align: right; font-variant-numeric: tabular-nums; }} footer {{ color: #777; font-size: 12px; margin-top: 24px; }}
@media (prefers-color-scheme: dark) {{ body {{ background: #111; color: #eee; }} th, td {{ border-color: #333; }} svg {{ border-color: #333; }} }}
</style></head><body>
<h1>{html.escape(s['name'])}</h1>
<p class="sub">Stratégie simulée · {html.escape(str(s.get('wrapper') or ''))} · {period}</p>
{_svg_curve(points)}
<table>{table}</table>
<footer>Simulation par PATRICK, station de recherche quantitative personnelle : performances calculées sur des signaux de modèles et des cours
historiques, frais simulés. Aucun montant n'est publié. Ce document n'est ni un conseil en investissement ni une recommandation.</footer>
</body></html>
"""
