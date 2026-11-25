"""A16 : PDF de texte sans dépendance -- valide, accents français, pagination, titres."""
from __future__ import annotations

import re

from patrick.core.text_pdf import text_to_pdf


def test_a_text_report_becomes_a_valid_multi_page_pdf_with_french_accents():
    lines = ["# Rapport hebdomadaire", "Résultat réel : 52,3 % de bonnes directions (élevé ?)"] + [f"Ligne {i} — à vérifier" for i in range(120)]
    pdf = text_to_pdf("PATRICK — hebdo", lines)
    assert pdf.startswith(b"%PDF-1.4") and pdf.rstrip().endswith(b"%%EOF")
    assert b"/Count 3" in pdf or b"/Count 2" in pdf                       # pagination automatique
    assert "Résultat réel".encode("cp1252") in pdf                        # WinAnsi : les accents passent
    assert rb"\(" in pdf                                                    # parenthèses échappées
    xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    assert pdf[xref:xref + 4] == b"xref"                                   # table des références au bon endroit


def test_the_cross_reference_offsets_point_at_their_objects():
    pdf = text_to_pdf("t", ["# Titre", "corps"])
    xref = int(re.search(rb"startxref\n(\d+)", pdf).group(1))
    entries = re.findall(rb"(\d{10}) 00000 n ", pdf[xref:])
    for i, off in enumerate(entries, start=1):
        assert pdf[int(off):int(off) + len(f"{i} 0 obj")] == f"{i} 0 obj".encode()
