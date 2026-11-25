"""Copie hors site chiffrée (FO30 du 25/11) : aller-retour fidèle, phrase fausse refusée, fichier tronqué refusé, rétention."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("cryptography")

from patrick.storage import offsite

PHRASE = "une phrase secrète assez longue"


def _db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE fonds (id INTEGER PRIMARY KEY, nom TEXT, valeur REAL)")
    conn.executemany("INSERT INTO fonds (nom, valeur) VALUES (?, ?)", [(f"Fonds {i} é", i * 1.5) for i in range(5000)])
    conn.commit()
    conn.close()


def test_a_copy_restores_exactly_and_says_nothing_without_the_phrase(tmp_path):
    src, dest = tmp_path / "patrick.db", tmp_path / "drive"
    dest.mkdir()
    _db(src)
    out = offsite.make_offsite_copy(str(src), str(dest), passphrase=PHRASE)
    data = Path(out["path"]).read_bytes()
    assert b"Fonds 1" not in data and data.startswith(offsite.MAGIC)
    restored = tmp_path / "restauree.db"
    offsite.restore_offsite_copy(out["path"], str(restored), passphrase=PHRASE)
    conn = sqlite3.connect(restored)
    assert conn.execute("SELECT COUNT(*), SUM(valeur) FROM fonds").fetchone() == (5000, sum(i * 1.5 for i in range(5000)))
    conn.close()


def test_a_wrong_phrase_or_a_truncated_file_is_refused(tmp_path):
    src, dest = tmp_path / "patrick.db", tmp_path / "drive"
    dest.mkdir()
    _db(src)
    out = offsite.make_offsite_copy(str(src), str(dest), passphrase=PHRASE)
    with pytest.raises(offsite.OffsiteError, match="phrase secrète fausse"):
        offsite.restore_offsite_copy(out["path"], str(tmp_path / "a.db"), passphrase="une autre phrase longue")
    truncated = tmp_path / "coupee.enc"
    truncated.write_bytes(Path(out["path"]).read_bytes()[:-100])
    with pytest.raises(offsite.OffsiteError):
        offsite.restore_offsite_copy(str(truncated), str(tmp_path / "b.db"), passphrase=PHRASE)


def test_short_phrase_missing_folder_and_existing_target_are_refused(tmp_path):
    src = tmp_path / "patrick.db"
    _db(src)
    with pytest.raises(offsite.OffsiteError, match="trop courte"):
        offsite.make_offsite_copy(str(src), str(tmp_path), passphrase="court")
    with pytest.raises(offsite.OffsiteError, match="introuvable"):
        offsite.make_offsite_copy(str(src), str(tmp_path / "absent"), passphrase=PHRASE)
    with pytest.raises(offsite.OffsiteError, match="existe déjà"):
        offsite.restore_offsite_copy("x.enc", str(src), passphrase=PHRASE)


def test_only_the_last_copies_are_kept(tmp_path, monkeypatch):
    src, dest = tmp_path / "patrick.db", tmp_path / "drive"
    dest.mkdir()
    _db(src)
    for i in range(4):
        (dest / f"patrick-2026010{i}-000000.db.gz.enc").write_bytes(b"old")
    offsite.make_offsite_copy(str(src), str(dest), passphrase=PHRASE, keep=2)
    assert len(list(dest.glob("patrick-*.enc"))) == 2
