"""PDF de texte simple, sans dépendance (A16 : rapport hebdomadaire en PDF).

Un PDF minimal mais valide : police Helvetica standard (aucune police embarquée), encodage WinAnsi (= Windows-1252 : les lettres accentuées du
français y sont), A4, marges de 2 cm, retour à la ligne au mot près, pagination automatique, numéro de page en pied. Les titres (lignes « # »)
sont en gras et plus grands. Suffit pour un rapport de texte ; pas de tableaux ni d'images.
"""
from __future__ import annotations

import textwrap

PAGE_W, PAGE_H = 595.28, 841.89          # A4 en points
MARGIN = 56.7                            # 2 cm
BODY, TITLE = 10.5, 15.0
LEADING = 1.35
CHARS_PER_LINE = 92                      # Helvetica 10,5 pt sur 17 cm : largeur moyenne prudente


def _escape(text: str) -> bytes:
    raw = text.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _layout(lines: list[str]) -> list[list[tuple[str, float, bool]]]:
    """Lignes (texte, taille, gras) réparties en pages."""
    pages: list[list[tuple[str, float, bool]]] = [[]]
    y = PAGE_H - MARGIN
    for raw in lines:
        title = raw.startswith("#")
        text = raw.lstrip("#").strip() if title else raw.replace("**", "").rstrip()
        size = TITLE if title else BODY
        chunks = [text] if title else (textwrap.wrap(text, CHARS_PER_LINE, break_long_words=True) or [""])
        for chunk in chunks:
            step = size * LEADING + (6 if title else 0)
            if y - step < MARGIN + 20:
                pages.append([])
                y = PAGE_H - MARGIN
            pages[-1].append((chunk, size, title))
            y -= step
    return pages


def text_to_pdf(title: str, lines: list[str]) -> bytes:
    """Le PDF (octets) de `lines` ; `title` va dans les métadonnées."""
    pages = _layout(lines)
    objects: list[bytes] = []

    def add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    bold = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_id = len(objects) + 2 * len(pages) + 1           # numéro réservé à l'objet /Pages, écrit après les pages
    page_ids = []
    for n, page in enumerate(pages, start=1):
        ops = [b"BT"]
        y = PAGE_H - MARGIN
        for text, size, is_title in page:
            y -= size * LEADING + (6 if is_title else 0)
            ops.append(b"/F%d %.1f Tf 1 0 0 1 %.2f %.2f Tm (" % (2 if is_title else 1, size, MARGIN, y) + _escape(text) + b") Tj")
        ops.append(b"/F1 8 Tf 1 0 0 1 %.2f %.2f Tm (" % (PAGE_W - MARGIN - 40, MARGIN / 2) + _escape(f"{n} / {len(pages)}") + b") Tj")
        ops.append(b"ET")
        stream = b"\n".join(ops)
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (pages_id, PAGE_W, PAGE_H, content, font, bold)))
    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    assert add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids)) == pages_id
    info = add(b"<< /Title (" + _escape(title) + b") /Producer (PATRICK) >>")
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, catalog, info, xref)
    return bytes(out)
