"""Visuels des fonds calculés côté serveur (26/11) : treemap des positions (VI2), carte de corrélation (VI4), nuage risque / rendement (VI6).

Tout est rendu en SVG ou en HTML dans les gabarits, sans bibliothèque : la disposition « squarified » (Bruls, Huizing et van Wijk, 2000) range
les rectangles pour qu'ils restent proches du carré (lisibles), la corrélation est ordonnée par regroupement hiérarchique pour que les
blocs de positions qui bougent ensemble sautent aux yeux.
"""
from __future__ import annotations

import math


def _worst(row: list[float], w: float) -> float:
    s = sum(row)
    if s <= 0 or w <= 0:
        return math.inf
    return max(max(w * w * r / (s * s), (s * s) / (w * w * r)) for r in row)


def squarify(values: list[float], x: float, y: float, w: float, h: float) -> list[tuple[float, float, float, float]]:
    """Rectangles (x, y, largeur, hauteur) proportionnels à `values` (positifs, dans l'ordre décroissant de préférence)."""
    total = sum(values)
    if total <= 0 or not values:
        return []
    scale = w * h / total
    areas = [v * scale for v in values]
    out: list[tuple[float, float, float, float]] = []
    row: list[float] = []
    i = 0
    while i < len(areas):
        side = min(w, h)
        candidate = [*row, areas[i]]
        if not row or _worst(candidate, side) <= _worst(row, side):
            row = candidate
            i += 1
            continue
        x, y, w, h = _place(row, x, y, w, h, out)
        row = []
    if row:
        _place(row, x, y, w, h, out)
    return out


def _place(row, x, y, w, h, out):
    s = sum(row)
    if w >= h:                                   # colonne à gauche
        col_w = s / h if h else 0
        yy = y
        for a in row:
            hh = a / col_w if col_w else 0
            out.append((x, yy, col_w, hh))
            yy += hh
        return x + col_w, y, w - col_w, h
    row_h = s / w if w else 0                    # rangée en haut
    xx = x
    for a in row:
        ww = a / row_h if row_h else 0
        out.append((xx, y, ww, row_h))
        xx += ww
    return x, y + row_h, w, h - row_h


def position_tiles(positions: list[dict], nav: float, width: float = 640, height: float = 220) -> list[dict]:
    """Treemap des positions ouvertes : surface = exposition (notionnel pour un dérivé), couleur = sens du P&L, intensité = son ampleur."""
    items = []
    for p in positions:
        if p.get("status") != "open" or not p.get("symbol"):
            continue
        exposure = abs(float(p.get("value_base") or 0.0))
        if exposure < 1e-9:
            exposure = abs(float(p.get("quantity") or 0.0)) * float(p.get("last_price") or 0.0) * float(p.get("fx_now") or 1.0)
        if exposure > 0:
            items.append((exposure, p))
    items.sort(key=lambda t: -t[0])
    rects = squarify([e for e, _ in items], 0, 0, width, height)
    tiles = []
    for (exposure, p), (x, y, w, h) in zip(items, rects, strict=True):
        pct = p.get("pnl_pct")
        tiles.append({"symbol": p["symbol"], "side": p.get("side"), "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1),
                      # en % de la boîte : les tuiles sont des blocs HTML (texte jamais étiré, quelle que soit la largeur de l'écran)
                      "left": round(100 * x / width, 2), "top": round(100 * y / height, 2),
                      "wpc": round(100 * w / width, 2), "hpc": round(100 * h / height, 2),
                      "weight": exposure / nav if nav else None, "pnl": p.get("pnl"), "pnl_pct": pct,
                      "tone": "up" if (p.get("pnl") or 0) >= 0 else "down",
                      "alpha": round(0.35 + 0.65 * min(1.0, abs(pct or 0.0) / 0.10), 2)})
    return tiles


def correlation(series: dict, min_obs: int = 60) -> dict | None:
    """Corrélation des rendements quotidiens (dernière année), ordonnée par regroupement hiérarchique. `{symbols, matrix, n}`."""
    import numpy as np
    import pandas as pd

    rets = {s: v.dropna().pct_change().dropna().tail(252) for s, v in series.items() if v is not None and len(v.dropna()) > min_obs}
    if len(rets) < 2:
        return None
    frame = pd.DataFrame(rets).dropna()
    if len(frame) < min_obs:
        return None
    corr = frame.corr()
    order = list(corr.columns)
    if len(order) > 2:
        from scipy.cluster.hierarchy import leaves_list, linkage
        from scipy.spatial.distance import squareform
        dist = np.sqrt(np.clip(0.5 * (1 - corr.to_numpy()), 0, None))
        np.fill_diagonal(dist, 0)
        order = [order[i] for i in leaves_list(linkage(squareform(dist, checks=False), method="average"))]
    corr = corr.loc[order, order]
    return {"symbols": order, "matrix": [[round(float(v), 2) for v in row] for row in corr.to_numpy()], "n": len(frame)}


def risk_return_points(strategies: list[dict], width: float = 640, height: float = 260, pad: float = 40) -> dict | None:
    """Nuage risque / rendement des stratégies : x = volatilité annualisée, y = rendement depuis l'ouverture, rayon ~ racine de la valeur."""
    pts = [(s["strategy"]["name"], s["kpis"].get("volatility"), s["kpis"].get("pnl_pct"), s["kpis"].get("nav") or 0.0)
           for s in strategies if s.get("kpis") and s["kpis"].get("volatility") is not None and s["kpis"].get("pnl_pct") is not None]
    if len(pts) < 2:
        return None
    xs, ys, navs = [p[1] for p in pts], [p[2] for p in pts], [p[3] for p in pts]
    x0, x1 = 0.0, max(xs) * 1.1 or 1.0
    y0, y1 = min(min(ys), 0.0), max(max(ys), 0.0)
    span = (y1 - y0) or 1.0
    y0, y1 = y0 - 0.08 * span, y1 + 0.08 * span
    big = max(navs) or 1.0

    def px(v):
        return pad + (v - x0) / (x1 - x0) * (width - 2 * pad)

    def py(v):
        return height - pad - (v - y0) / (y1 - y0) * (height - 2 * pad)
    dots = [{"name": n, "vol": v, "ret": r, "nav": a, "cx": round(px(v), 1), "cy": round(py(r), 1),
             "r": round(4 + 10 * math.sqrt(max(a, 0) / big), 1), "tone": "up" if r >= 0 else "down"} for n, v, r, a in pts]
    for d in dots:                                # nom à droite de la bulle, ou à gauche près du bord droit
        d["label_left"] = d["cx"] > width - pad - 120
        d["label"] = d["name"] if len(d["name"]) <= 22 else d["name"][:21] + "…"
    xticks = [{"v": v, "x": round(px(v), 1)} for v in (0.0, max(xs) / 2, max(xs))]
    yticks = [{"v": v, "y": round(py(v), 1)} for v in sorted({min(ys), 0.0, max(ys)})]
    return {"dots": dots, "width": width, "height": height, "pad": pad, "zero_y": round(py(0.0), 1), "x_max": x1, "y_min": y0, "y_max": y1,
            "xticks": xticks, "yticks": yticks}
