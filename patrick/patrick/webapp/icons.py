"""Inline SVG icon set for the webapp (design system v3, MASTER.md).

Paths are copied verbatim from Lucide (lucide-static 1.48.0, ISC licence,
https://lucide.dev) -- one consistent stroke-based set, as MASTER.md's
pre-delivery checklist requires (no emoji, no mixed sets). Rendered
server-side through the `icon()` Jinja global so that no page depends on a
client-side icon font or an external request.

Keys are PATRICK's own semantic names (a nav slug or a UI role), not
Lucide's file names, so swapping a glyph never touches a template.
"""
from __future__ import annotations

from markupsafe import Markup

ICONS: dict[str, str] = {
    "dashboard": '<rect width="7" height="9" x="3" y="3" rx="1"/> <rect width="7" height="5" x="14" y="3" rx="1"/> <rect width="7" height="9" x="14" y="12" rx="1"/> <rect width="7" height="5" x="3" y="16" rx="1"/>',
    "launch": '<path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/> <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09"/> <path d="M9 12a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.4 22.4 0 0 1-4 2z"/> <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 .05 5 .05"/>',
    "history": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/> <path d="M3 3v5h5"/> <path d="M12 7v5l4 2"/>',
    "target": '<circle cx="12" cy="12" r="10"/> <line x1="22" x2="18" y1="12" y2="12"/> <line x1="6" x2="2" y1="12" y2="12"/> <line x1="12" x2="12" y1="6" y2="2"/> <line x1="12" x2="12" y1="22" y2="18"/>',
    "freshness": '<ellipse cx="12" cy="5" rx="9" ry="3"/> <path d="M3 5V19A9 3 0 0 0 15 21.84"/> <path d="M21 5V8"/> <path d="M21 12L18 17H22L19 22"/> <path d="M3 12A9 3 0 0 0 14.59 14.87"/>',
    "phase9": '<path d="M14 2v6a2 2 0 0 0 .245.96l5.51 10.08A2 2 0 0 1 18 22H6a2 2 0 0 1-1.755-2.96l5.51-10.08A2 2 0 0 0 10 8V2"/> <path d="M6.453 15h11.094"/> <path d="M8.5 2h7"/>',
    "universe": '<circle cx="12" cy="12" r="10"/> <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/> <path d="M2 12h20"/>',
    "commodities": '<path d="M12 3q1 4 4 6.5t3 5.5a1 1 0 0 1-14 0 5 5 0 0 1 1-3 1 1 0 0 0 5 0c0-2-1.5-3-1.5-5q0-2 2.5-4"/>',
    "macro": '<path d="M10 18v-7"/> <path d="M11.119 2.205a2 2 0 0 1 1.762 0l7.84 3.846A.5.5 0 0 1 20.5 7h-17a.5.5 0 0 1-.22-.949z"/> <path d="M14 18v-7"/> <path d="M18 18v-7"/> <path d="M3 22h18"/> <path d="M6 18v-7"/>',
    "equities": '<path d="M10 12h4"/> <path d="M10 8h4"/> <path d="M14 21v-3a2 2 0 0 0-4 0v3"/> <path d="M6 10H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-2"/> <path d="M6 21V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v16"/>',
    "portfolio": '<path d="M21 12c.552 0 1.005-.449.95-.998a10 10 0 0 0-8.953-8.951c-.55-.055-.998.398-.998.95v8a1 1 0 0 0 1 1z"/> <path d="M21.21 15.89A10 10 0 1 1 8 2.83"/>',
    "simulate": '<path d="M3 3v16a2 2 0 0 0 2 2h16"/> <path d="m19 9-5 5-4-4-3 3"/>',
    "wallet": '<path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1"/> <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4"/>',
    "movements": '<path d="M8 3 4 7l4 4"/> <path d="M4 7h16"/> <path d="m16 21 4-4-4-4"/> <path d="M20 17H4"/>',
    "search": '<path d="m21 21-4.34-4.34"/> <circle cx="11" cy="11" r="8"/>',
    "sun": '<circle cx="12" cy="12" r="4"/> <path d="M12 2v2"/> <path d="M12 20v2"/> <path d="m4.93 4.93 1.41 1.41"/> <path d="m17.66 17.66 1.41 1.41"/> <path d="M2 12h2"/> <path d="M20 12h2"/> <path d="m6.34 17.66-1.41 1.41"/> <path d="m19.07 4.93-1.41 1.41"/>',
    "moon": '<path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401"/>',
    "sidebar": '<rect width="18" height="18" x="3" y="3" rx="2"/> <path d="M9 3v18"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "info": '<circle cx="12" cy="12" r="10"/> <path d="M12 16v-4"/> <path d="M12 8h.01"/>',
    "command": '<path d="M15 6v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3"/>',
    "ok": '<circle cx="12" cy="12" r="10"/> <path d="m16 9-5.5 5.5L8 12"/>',
    "error": '<circle cx="12" cy="12" r="10"/> <line x1="12" x2="12" y1="8" y2="12"/> <line x1="12" x2="12.01" y1="16" y2="16"/>',
    "warning": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/> <path d="M12 9v4"/> <path d="M12 17h.01"/>',
    "gauge": '<path d="m12 14 4-4"/> <path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "briefcase": '<path d="M12 12h.01"/> <path d="M16 6V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/> <path d="M22 13a18.15 18.15 0 0 1-20 0"/> <rect width="20" height="14" x="2" y="6" rx="2"/>',
    "scale": '<path d="M12 3v18"/> <path d="m19 8 3 8a5 5 0 0 1-6 0zV7"/> <path d="M3 7h1a17 17 0 0 0 8-2 17 17 0 0 0 8 2h1"/> <path d="m5 8 3 8a5 5 0 0 1-6 0zV7"/> <path d="M7 21h10"/>',
    "trending-up": '<path d="M16 7h6v6"/> <path d="m22 7-8.5 8.5-5-5L2 17"/>',
    "trending-down": '<path d="M16 17h6v-6"/> <path d="m22 17-8.5-8.5-5 5L2 7"/>',
    "activity": '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2"/>',
    "file": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/> <path d="M14 2v5a1 1 0 0 0 1 1h5"/> <path d="M10 9H8"/> <path d="M16 13H8"/> <path d="M16 17H8"/>',
    "external": '<path d="M15 3h6v6"/> <path d="M10 14 21 3"/> <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    "close": '<path d="M18 6 6 18"/> <path d="m6 6 12 12"/>',
    "menu": '<path d="M4 5h16"/> <path d="M4 12h16"/> <path d="M4 19h16"/>',
    "clock": '<path d="M16 14v2.2l1.6 1"/> <path d="M16 2v3"/> <path d="M21 7.338V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h2.338"/> <path d="M3 9h5.859"/> <path d="M8 2v3"/> <circle cx="16" cy="16" r="6"/>',
    "layers": '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/> <path d="M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12"/> <path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17"/>',
    "predictions": '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/> <path d="M20 2v4"/> <path d="M22 4h-4"/> <circle cx="4" cy="20" r="2"/>',
    "event": '<rect x="3" y="3" width="18" height="18" rx="2"/> <path d="M16 2v3"/> <path d="M3 9h18"/> <path d="M8 2v3"/> <path d="M17 13h-6"/> <path d="M13 17H7"/> <path d="M7 13h.01"/> <path d="M17 17h.01"/>',
    "drag": '<circle cx="9" cy="12" r="1"/> <circle cx="9" cy="5" r="1"/> <circle cx="9" cy="19" r="1"/> <circle cx="15" cy="12" r="1"/> <circle cx="15" cy="5" r="1"/> <circle cx="15" cy="19" r="1"/>',
    "plus": '<path d="M5 12h14"/> <path d="M12 5v14"/>',
    "trash": '<path d="M10 11v6"/> <path d="M14 11v6"/> <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/> <path d="M3 6h18"/> <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
    "upload": '<path d="M12 3v12"/> <path d="m17 8-5-5-5 5"/> <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>',
    "shield": '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/> <path d="m9 12 2 2 4-4"/>',
    "eye": '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/> <circle cx="12" cy="12" r="3"/>',
    "research": '<path d="M6 18h8"/> <path d="M3 22h18"/> <path d="M14 22a7 7 0 1 0 0-14h-1"/> <path d="M9 14h2"/> <path d="M9 12a2 2 0 0 1-2-2V6h6v4a2 2 0 0 1-2 2Z"/> <path d="M12 6V3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3"/>',
    "languages": '<path d="m5 8 6 6"/> <path d="m4 14 6-6 2-3"/> <path d="M2 5h12"/> <path d="M7 2h1"/> <path d="m22 22-5-10-5 10"/> <path d="M14 18h6"/>',
}

# Nav slug -> icon key (nav_registry entries carry no presentation data).
NAV_ICONS: dict[str, str] = {
    "synthese": "dashboard",
    "launch": "launch",
    "runs": "history",
    "predictions": "predictions",
    "data_freshness": "freshness",
    "phase9": "phase9",
    "universe": "universe",
    "commodities": "commodities",
    "macro": "macro",
    "equities": "equities",
    "portfolio": "portfolio",
    "simulate": "simulate",
    "event_study": "event",
    "patrimoine": "wallet",
    "mouvements": "movements",
}


def icon(name: str, size: int = 16, cls: str = "") -> Markup:
    """`<svg>` for `name` (unknown names render an empty, correctly sized
    box rather than raising: a missing glyph must never break a page)."""
    body = ICONS.get(name, "")
    classes = f"icon {cls}".strip()
    return Markup(
        f'<svg class="{classes}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" '
        f'aria-hidden="true" focusable="false">{body}</svg>'
    )


def nav_icon(slug: str, size: int = 16) -> Markup:
    return icon(NAV_ICONS.get(slug, "layers"), size)
