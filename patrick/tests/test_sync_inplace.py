"""Fusion du partage EN PLACE et export sans cache (2026-10-10).

Avant : la fusion copiait la base locale (27 Go) dans un fichier de travail, puis en faisait une sauvegarde de plus, et
échouait sur un disque presque plein en laissant un fichier de 25 Go ; la publication copiait elle aussi toute la base
(90 % de caches ré-ajustables). Maintenant : une transaction directement dans la base locale, une sauvegarde seulement
si le disque la permet, des erreurs de disque expliquées, et des caches qui ne sont pas publiés."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from test_sync_auto import PC, pcs  # noqa: F401  (fixture)

from patrick import sync, sync_merge


def _two_pcs_with_a_share(pcs):  # noqa: F811
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)
    pc2.seed(["b1"])
    pc2.use()
    return pc1, pc2, share


def test_the_merge_works_in_place_without_a_work_copy(pcs):  # noqa: F811
    _pc1, pc2, share = _two_pcs_with_a_share(pcs)
    seen = []
    real = sync_merge.merge_databases

    def spy(dst, src, **kw):
        seen.append((dst, kw.get("fast")))
        assert not Path(dst + ".merging").exists()
        return real(dst, src, **kw)

    sync_merge.merge_databases, original = spy, sync_merge.merge_databases
    try:
        out = pc2.auto(share, only="pull")
    finally:
        sync_merge.merge_databases = original

    assert seen == [(pc2.db, False)]                      # la base locale elle-même, journal normal (pas de mode « jetable »)
    assert pc2.runs() == {"a1", "b1"}
    assert out["merge"]["new_run_ids"] == ["a1"] and out["merge"]["backup"]
    assert not Path(pc2.db + ".merging").exists()


def test_the_share_is_read_in_place_and_left_untouched(pcs):  # noqa: F811
    _pc1, pc2, share = _two_pcs_with_a_share(pcs)
    before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in share.iterdir()}
    pc2.auto(share, only="pull")
    after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in share.iterdir()}
    assert before == after


def test_the_full_backup_is_skipped_when_the_disk_cannot_hold_it(pcs, monkeypatch):  # noqa: F811
    _pc1, pc2, share = _two_pcs_with_a_share(pcs)
    monkeypatch.setattr(sync, "_backup_affordable", lambda *a, **k: (False, "sauvegarde complète ignorée : test"))
    out = pc2.auto(share, only="pull")
    assert pc2.runs() == {"a1", "b1"}
    assert out["merge"]["backup"] is None and "ignorée" in out["merge"]["backup_skipped"]
    assert out["merge"]["champion_snapshot"] and Path(out["merge"]["champion_snapshot"]).exists()


def test_a_nearly_full_disk_stops_the_merge_before_touching_anything(pcs, monkeypatch):  # noqa: F811
    _pc1, pc2, share = _two_pcs_with_a_share(pcs)
    monkeypatch.setattr(sync, "_free_bytes", lambda path: 10 * 1024 * 1024)       # 10 Mo libres
    with pytest.raises(sync.SyncError, match="Disque presque plein|Espace disque insuffisant"):
        sync.merge(str(share), **{k: v for k, v in pc2.kw.items() if k in ("db_path", "store_root", "models_dir", "backup_dir")})
    assert pc2.runs() == {"b1"}


def test_a_disk_full_error_from_sqlite_is_explained(pcs, monkeypatch):  # noqa: F811
    _pc1, pc2, share = _two_pcs_with_a_share(pcs)

    def boom(*a, **k):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(sync_merge, "merge_databases", boom)
    with pytest.raises(sync.SyncError) as exc:
        sync.merge(str(share), **{k: v for k, v in pc2.kw.items() if k in ("db_path", "store_root", "models_dir", "backup_dir")})
    assert "feature_cache" in str(exc.value) and "sauvegardes" in str(exc.value)
    assert pc2.runs() == {"b1"}


def _add_caches(path: str) -> None:
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(vol_model_cache)")]
    assert cols, "table vol_model_cache attendue"
    conn.close()


def test_caches_are_not_published_unless_asked(pcs):  # noqa: F811
    pc1, _pc2, share = pcs
    pc1.seed(["a1"])
    conn = sqlite3.connect(pc1.db)
    info = {r[1]: r for r in conn.execute("PRAGMA table_info(vol_model_cache)")}
    values = {c: ("x" if (info[c][2] or "").upper().startswith(("TEXT", "VAR")) else 1) for c in info}
    conn.execute(f"INSERT INTO vol_model_cache ({', '.join(info)}) VALUES ({', '.join('?' for _ in info)})", list(values.values()))
    conn.commit()
    n_local = conn.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0]
    conn.close()
    assert n_local == 1

    pc1.auto(share)                                                    # publication par défaut
    pc3 = share.parent / "check.db"
    sync.merge(str(share), db_path=str(pc3), store_root=str(share.parent / "s"), models_dir=str(share.parent / "m"),
               backup_dir=str(share.parent / "b"))
    conn = sqlite3.connect(pc3)
    assert conn.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM run").fetchone()[0] == 1
    conn.close()

    share2 = share.parent / "share_with_caches"
    sync.push(str(share2), db_path=pc1.db, store_root=str(share.parent / "none"), models_roots=[], include_caches=True)
    pc4 = share.parent / "check2.db"
    sync.merge(str(share2), db_path=str(pc4), store_root=str(share.parent / "s2"), models_dir=str(share.parent / "m2"),
               backup_dir=str(share.parent / "b2"))
    conn = sqlite3.connect(pc4)
    assert conn.execute("SELECT COUNT(*) FROM vol_model_cache").fetchone()[0] == 1
    conn.close()


def test_the_publication_builds_a_lean_export_table_by_table(pcs, monkeypatch):  # noqa: F811
    pc1, _pc2, share = pcs
    pc1.seed(["a1", "a2"])
    calls = []
    real = sync._export_research_copy

    def spy(src, work, **kw):
        calls.append(kw)
        return real(src, work, **kw)

    monkeypatch.setattr(sync, "_export_research_copy", spy)
    out = pc1.auto(share)
    assert out["actions"] and pc1.runs() == {"a1", "a2"}
    assert calls == [{"include_personal": False, "include_caches": False}]
