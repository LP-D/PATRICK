"""`sync.merge` / `sync.auto` : deux PC qui travaillent chacun de leur côté convergent vers la même base
sans jamais perdre un run, et ne republient que quand il y a du neuf. Chaque « PC » a sa base, son état
(`PATRICK_SETTINGS_PATH`) et ses dossiers; le partage est un simple dossier."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from test_sync_merge import _seed

from patrick import sync
from patrick.tracking import db as trackdb


class PC:
    def __init__(self, tmp_path: Path, name: str, monkeypatch):
        self.name, self.monkeypatch = name, monkeypatch
        self.dir = tmp_path / name
        self.dir.mkdir()
        self.db = str(self.dir / "patrick.db")
        self.kw = {"db_path": self.db, "store_root": str(self.dir / "store"), "models_dir": str(self.dir / "models"),
                   "models_roots": [], "backup_dir": str(self.dir / "backups")}

    def use(self) -> PC:
        self.monkeypatch.setenv("PATRICK_SETTINGS_PATH", str(self.dir / "settings.json"))
        return self

    def seed(self, runs, **kw) -> PC:
        _seed(Path(self.db), runs, snapshot=f"snap_{self.name}", **kw)
        return self

    def auto(self, share: Path, **kw) -> dict:
        self.use()
        return sync.auto(str(share), **{**self.kw, **kw})

    def runs(self) -> set[str]:
        conn = sqlite3.connect(self.db)
        try:
            return {r[0] for r in conn.execute("SELECT run_id FROM run")}
        finally:
            conn.close()


@pytest.fixture
def pcs(tmp_path, monkeypatch):
    share = tmp_path / "share"
    return PC(tmp_path, "pc1", monkeypatch), PC(tmp_path, "pc2", monkeypatch), share


def _remote_runs(tmp_path: Path, share: Path) -> int:
    return json.loads((share / "manifest.json").read_text(encoding="utf-8"))["runs"]


def test_first_auto_publishes_when_the_share_is_empty(pcs):
    pc1, _, share = pcs
    pc1.seed(["a1", "a2"])

    out = pc1.auto(share)

    assert [a.split(" :")[0] for a in out["actions"]] == ["publication"]
    assert (share / "manifest.json").exists()
    assert sync.status(str(share), db_path=pc1.db)["need_push"] is False


def test_two_pcs_converge_without_losing_any_run(pcs, tmp_path):
    pc1, pc2, share = pcs
    pc1.seed(["a1", "a2"])
    pc2.seed(["b1"])

    pc1.auto(share)                                   # le partage reçoit a1, a2
    out2 = pc2.auto(share)                            # PC2 fusionne puis republie l'union
    assert [a.split(" :")[0] for a in out2["actions"]] == ["fusion", "publication"]
    assert pc2.runs() == {"a1", "a2", "b1"}
    assert _remote_runs(tmp_path, share) == 3

    published_at = json.loads((share / "manifest.json").read_text(encoding="utf-8"))["created_at"]
    out1 = pc1.auto(share)                            # PC1 récupère b1; rien de neuf à republier
    assert [a.split(" :")[0] for a in out1["actions"]] == ["fusion"]
    assert pc1.runs() == pc2.runs() == {"a1", "a2", "b1"}
    assert json.loads((share / "manifest.json").read_text(encoding="utf-8"))["created_at"] == published_at

    # Stable : plus rien à faire, ni d'un côté ni de l'autre.
    assert pc1.auto(share) == {"actions": [], "skipped": []}
    assert pc2.auto(share) == {"actions": [], "skipped": []}


def test_a_new_local_run_is_published_and_reaches_the_other_pc(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)
    pc2.auto(share)                                   # PC2 (base vide) reçoit a1
    assert pc2.runs() == {"a1"}

    conn = trackdb.connect(pc1.db)
    trackdb.create_run(conn, "a_new", "T_new", 5, "snap_pc1", json.dumps({}), "cfg", "sha", 1)
    conn.close()

    assert [a.split(" :")[0] for a in pc1.auto(share)["actions"]] == ["publication"]
    pc2.auto(share)
    assert pc2.runs() == {"a1", "a_new"}


def test_nothing_is_done_when_nothing_changed(pcs):
    pc1, _, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)

    assert pc1.auto(share) == {"actions": [], "skipped": []}


def test_a_push_is_refused_while_the_share_holds_unmerged_data(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    pc1.auto(share)

    out = pc2.auto(share, only="push")                # PC2 n'a pas fusionné a1 : ne doit pas écraser le partage

    assert out["actions"] == [] and "pas encore fusionnées" in out["skipped"][0]
    assert _remote_runs(None, share) == 1


def test_nothing_is_merged_or_published_while_a_job_is_running(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)
    pc2.seed(["b1"])
    conn = sqlite3.connect(pc2.db)
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'running')")
    conn.commit()
    conn.close()

    out = pc2.auto(share)

    assert out["actions"] == [] and any("entraînement" in s for s in out["skipped"])
    assert pc2.runs() == {"b1"}


def test_merge_is_blocked_while_the_database_is_open(pcs):
    if sync.os.name != "nt":
        pytest.skip("détection d'ouverture par renommage : Windows")
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)
    pc2.seed(["b1"])
    held = sqlite3.connect(pc2.db)                    # PATRICK ouvert sur cette base
    held.execute("SELECT 1 FROM run").fetchall()
    try:
        out = pc2.auto(share, only="pull")
    finally:
        held.close()

    assert out["actions"] == [] and "ouvert" in out["skipped"][0]
    assert pc2.runs() == {"b1"}


def test_merge_keeps_a_backup_and_restores_models_under_the_new_ids(pcs, tmp_path):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    models = tmp_path / "pc1_models"
    models.mkdir()
    conn = sqlite3.connect(pc1.db)
    (models / "a1_lgbm.joblib").write_bytes(b"modele-a1")
    conn.execute("UPDATE trial SET artifact_path = ? WHERE run_id = 'a1' AND algo = 'lgbm'",
                 (str(models / "a1_lgbm.joblib"),))
    conn.commit()
    conn.close()
    pc1.auto(share, models_roots=[str(tmp_path)])
    pc2.seed(["b1"])

    out = pc2.auto(share, only="pull")

    assert out["merge"]["models"] == 1 and out["merge"]["backup"]
    conn = sqlite3.connect(pc2.db)
    (path,) = [r[0] for r in conn.execute("SELECT artifact_path FROM trial WHERE run_id = 'a1' AND algo = 'lgbm'")]
    new_id = conn.execute("SELECT trial_id FROM trial WHERE run_id = 'a1' AND algo = 'lgbm'").fetchone()[0]
    conn.close()
    assert Path(path).read_bytes() == b"modele-a1"
    assert Path(path).parent.name == str(new_id)          # rangé sous l'identifiant local, pas celui de l'autre PC


def test_dry_run_leaves_the_local_database_untouched(pcs, tmp_path):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)
    pc2.seed(["b1"])
    pc2.use()

    res = sync.merge(str(share), dry_run_to=str(tmp_path / "preview.db"), **{k: v for k, v in pc2.kw.items()
                                                                              if k in ("db_path",)})

    assert res["runs_after"] == 2 and pc2.runs() == {"b1"}
    assert not Path(pc2.db + ".merging").exists()


def test_status_reports_what_auto_would_do(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc1.use()
    first = sync.status(str(share), db_path=pc1.db)
    assert first["remote"] is None and first["need_push"] and not first["need_pull"]

    pc1.auto(share)
    pc2.seed(["b1"])
    pc2.use()
    second = sync.status(str(share), db_path=pc2.db)
    assert second["need_pull"] and second["need_push"] and second["remote"]["runs"] == 1


def test_fingerprint_ignores_personal_tables_and_runtime_state(pcs):
    pc1, _, _ = pcs
    pc1.seed(["a1"])
    before = sync.fingerprint(pc1.db)
    conn = sqlite3.connect(pc1.db)
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('x', 'perso', 'PEA', 'real')")
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j9', '{}', 'done')")
    conn.commit()
    conn.close()
    assert sync.fingerprint(pc1.db) == before

    conn = trackdb.connect(pc1.db)
    trackdb.create_run(conn, "a2", "T", 5, "snap_pc1", json.dumps({}), "cfg", "sha", 1)
    conn.close()
    assert sync.fingerprint(pc1.db) != before


def test_auto_rejects_an_unknown_half(pcs):
    pc1, _, share = pcs
    with pytest.raises(sync.SyncError):
        pc1.auto(share, only="both")


def _wealth(pc: PC) -> list[tuple]:
    conn = sqlite3.connect(pc.db)
    try:
        return conn.execute("SELECT account_id FROM wealth_account ORDER BY 1").fetchall()
    finally:
        conn.close()


def _published_personal(share: Path) -> bool:
    return json.loads((share / "manifest.json").read_text(encoding="utf-8"))["personal_included"]


def test_the_reference_pc_publishes_its_wealth_and_the_other_pc_adopts_it(pcs):
    ref, other, share = pcs
    ref.seed(["a1"], wealth="acc_ref")
    other.seed(["b1"], wealth="acc_other")
    ref.use()
    sync.settings_mod.save({sync.KEY_WEALTH_REFERENCE: True})

    out = ref.auto(share)
    assert "patrimoine inclus" in out["actions"][0] and _published_personal(share)

    out2 = other.auto(share)                                 # l'autre PC fusionne, adopte, puis republie sans patrimoine
    assert "patrimoine du PC de référence adopté" in out2["actions"][0]
    assert _wealth(other) == [("acc_ref",)]                  # le sien est remplacé par celui de la référence
    assert other.runs() == {"a1", "b1"}
    assert not _published_personal(share)                    # une publication non-référence n'écrase pas le patrimoine

    out3 = ref.auto(share)                                   # la référence fusionne b1 mais garde son patrimoine
    assert [a.split(" :")[0] for a in out3["actions"]] == ["fusion"]
    assert _wealth(ref) == [("acc_ref",)] and ref.runs() == {"a1", "b1"}


def test_a_wealth_change_on_the_reference_pc_triggers_a_publication(pcs):
    ref, other, share = pcs
    ref.seed(["a1"], wealth="acc_ref")
    ref.use()
    sync.settings_mod.save({sync.KEY_WEALTH_REFERENCE: True})
    ref.auto(share)
    assert ref.auto(share) == {"actions": [], "skipped": []}

    conn = sqlite3.connect(ref.db)
    conn.execute("INSERT INTO wealth_account (account_id, name, kind, mode) VALUES ('acc_new', 'neuf', 'CTO', 'real')")
    conn.commit()
    conn.close()

    assert [a.split(" :")[0] for a in ref.auto(share)["actions"]] == ["publication"]
    other.auto(share)
    assert _wealth(other) == [("acc_new",), ("acc_ref",)]


def test_without_a_reference_pc_each_pc_keeps_its_own_wealth(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"], wealth="acc_1")
    pc2.seed(["b1"], wealth="acc_2")

    pc1.auto(share)
    pc2.auto(share)

    assert not _published_personal(share)
    assert _wealth(pc1) == [("acc_1",)] and _wealth(pc2) == [("acc_2",)]
