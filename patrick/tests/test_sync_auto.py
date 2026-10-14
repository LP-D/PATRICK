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
from patrick.fund import store as fund_store
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
        sync.settings_mod.save({sync.KEY_PC_NAME: self.name})      # deux PC de test ne portent pas le même nom d'hôte
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


# --- fonds : chaque PC publie les siens dans un fichier à lui, tous fusionnent par union ------------------------

def _fund(pc: PC, name: str) -> str:
    conn = trackdb.connect(pc.db)
    try:
        sid = fund_store.create_strategy(conn, name, "CTO", 100_000, "2026-01-05")
        fund_store.insert_order(conn, {"strategy_id": sid, "position_id": "pos_a", "ts": "2026-01-07", "action": "open",
                                       "instrument_kind": "equity", "symbol": "MC.PA", "side": "long", "quantity": 4.0,
                                       "price": 700.0, "price_source": "market", "currency": "EUR", "fx_rate": 1.0,
                                       "fees": 1.0, "fees_source": "estimated", "fee_seed": 7, "spec": {}, "note": None})
        return sid
    finally:
        conn.close()


def _funds(pc: PC) -> dict[str, str]:
    conn = sqlite3.connect(pc.db)
    try:
        return dict(conn.execute("SELECT strategy_id, name FROM fund_strategy"))
    finally:
        conn.close()


def _fund_files(share: Path) -> list[str]:
    return sorted(p.name for p in share.glob("funds-*"))


def test_funds_created_on_two_pcs_end_up_on_both(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    s1, s2 = _fund(pc1, "Fonds de PC1"), _fund(pc2, "Fonds de PC2")

    out1 = pc1.auto(share)
    assert any(a.startswith("fonds publiés") for a in out1["actions"])
    out2 = pc2.auto(share)
    assert any(a.startswith("fonds") and "importé" in a for a in out2["actions"])
    pc1.auto(share)

    assert _funds(pc1) == _funds(pc2) == {s1: "Fonds de PC1", s2: "Fonds de PC2"}
    assert _fund_files(share) == ["funds-pc1.db.gz", "funds-pc1.json", "funds-pc2.db.gz", "funds-pc2.json"]


def test_funds_flow_even_while_a_training_blocks_the_research_sync(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    sid = _fund(pc1, "Créé pendant un entraînement")
    pc1.auto(share)
    conn = sqlite3.connect(pc2.db)
    conn.execute("INSERT INTO job (job_id, config_json, status) VALUES ('j1', '{}', 'running')")
    conn.commit()
    conn.close()

    out = pc2.auto(share)

    assert "un entraînement est en cours" in " ".join(out["skipped"])        # la recherche attend...
    assert pc2.runs() == {"b1"} and _funds(pc2) == {sid: "Créé pendant un entraînement"}      # ...pas les fonds


def test_the_non_reference_pc_keeps_its_funds_when_it_adopts_the_reference_wealth(pcs):
    """Incident du 14/10 : la référence publie un patrimoine SANS fonds; l'autre PC l'adoptait en effaçant les siens."""
    ref, other, share = pcs
    ref.seed(["a1"], wealth="acc_ref")
    other.seed(["b1"], wealth="acc_other")
    mine = _fund(other, "Mon portefeuille")
    ref.use()
    sync.settings_mod.save({sync.KEY_WEALTH_REFERENCE: True})
    ref.auto(share)

    out = other.auto(share)

    assert "patrimoine du PC de référence adopté" in " ".join(out["actions"])
    assert _wealth(other) == [("acc_ref",)]
    assert _funds(other) == {mine: "Mon portefeuille"}
    ref.auto(share)
    assert _funds(ref) == {mine: "Mon portefeuille"}                          # et la référence le reçoit aussi


def test_a_deleted_strategy_disappears_on_the_other_pc(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    sid = _fund(pc1, "Éphémère")
    pc1.auto(share)
    pc2.auto(share)
    assert sid in _funds(pc2)
    conn = trackdb.connect(pc1.db)
    fund_store.delete_strategy(conn, sid)
    conn.close()

    pc1.auto(share)
    out = pc2.auto(share)

    assert _funds(pc1) == _funds(pc2) == {}
    assert any("supprimé" in a for a in out["actions"])


def test_funds_are_published_only_when_they_change_and_never_empty(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    pc1.auto(share)
    assert _fund_files(share) == []                                          # aucun fonds : aucun fichier

    _fund(pc1, "Premier")
    assert any(a.startswith("fonds publiés") for a in pc1.auto(share)["actions"])
    stamp = (share / "funds-pc1.json").read_text(encoding="utf-8")
    assert pc1.auto(share) == {"actions": [], "skipped": []}                 # rien de neuf : rien n'est réécrit
    assert (share / "funds-pc1.json").read_text(encoding="utf-8") == stamp


def test_an_unfinished_or_corrupt_funds_file_is_skipped_and_retried(pcs):
    pc1, pc2, share = pcs
    pc1.seed(["a1"])
    pc2.seed(["b1"])
    sid = _fund(pc1, "Fonds")
    pc1.auto(share)
    good = (share / "funds-pc1.db.gz").read_bytes()
    (share / "funds-pc1.db.gz").write_bytes(good[: len(good) // 2])          # OneDrive n'a pas fini de recopier

    out = pc2.auto(share)

    assert any(s.startswith("fonds") for s in out["skipped"]) and _funds(pc2) == {}
    assert pc2.runs() == {"a1", "b1"}                                        # la recherche n'est pas gênée
    (share / "funds-pc1.db.gz").write_bytes(good)
    pc2.auto(share)
    assert _funds(pc2) == {sid: "Fonds"}


def test_the_funds_stage_upgrades_an_older_database_by_itself(pcs):
    """La tâche horaire peut passer avant que PATRICK (donc la migration 0033) n'ait ouvert la base."""
    pc1, _, share = pcs
    pc1.seed(["a1"])
    pc1.auto(share)                                           # la recherche est à jour : rien d'autre n'ouvrira la base
    sid = _fund(pc1, "Déjà là")
    conn = sqlite3.connect(pc1.db)
    conn.execute("ALTER TABLE fund_strategy DROP COLUMN updated_at")
    conn.execute("DROP TABLE fund_deleted")
    conn.execute("DELETE FROM schema_version WHERE version >= 33")
    conn.commit()
    conn.close()

    out = {"actions": [], "skipped": []}
    pc1.use()
    sync._funds_stage(str(share), pc1.db, str(pc1.dir / "backups"), out)

    assert any(a.startswith("fonds publiés") for a in out["actions"]), out
    assert _funds(pc1) == {sid: "Déjà là"}
