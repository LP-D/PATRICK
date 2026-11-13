"""Un job retiré de la file sans avoir tourné emporte sa note de relance (`relaunch_log`) ; celles des jobs qui ont tourné restent."""
from __future__ import annotations

from patrick.tracking import jobs as jobs_db
from patrick.tracking import relaunch_stats


def _logged(conn) -> set[str]:
    return {row[0] for row in conn.execute("SELECT job_id FROM relaunch_log")}


def _queue_with_notes(conn) -> tuple[str, str, str]:
    kept, dropped, other = (jobs_db.enqueue_job(conn, "{}") for _ in range(3))
    for job_id in (kept, dropped, other):
        relaunch_stats.record_relaunch(conn, job_id, "run_parent", "overfit", "batch")
    return kept, dropped, other


def test_deleting_a_queued_job_forgets_its_relaunch_note(conn):
    kept, dropped, other = _queue_with_notes(conn)

    assert jobs_db.delete_queued_job(conn, dropped) is True

    assert _logged(conn) == {kept, other}
    assert jobs_db.delete_queued_job(conn, "job_inconnu") is False and _logged(conn) == {kept, other}


def test_clearing_the_queue_keeps_the_notes_of_jobs_that_ran(conn):
    """Le job en cours garde sa note ; celui d'un challenger battu puis élagué aussi, par la ligne de son duel."""
    running, _, _ = _queue_with_notes(conn)
    conn.execute("UPDATE job SET status = 'running' WHERE job_id = ?", (running,))
    relaunch_stats.record_relaunch(conn, "job_elague", "run_parent", "overfit", "batch")
    relaunch_stats.record_duel(conn, job_id="job_elague", run_id="run_battu", target="AAPL", horizon=1,
                               decision={"decision": "champion_wins", "criterion": "AUC_dir"})
    relaunch_stats.record_relaunch(conn, "job_orphelin", "run_parent", "overfit", "batch")     # reste d'un lot déjà vidé
    conn.commit()

    assert jobs_db.clear_queued_jobs(conn) == 2

    assert _logged(conn) == {running, "job_elague"}
    assert relaunch_stats.suggestion_stats(conn)["by_key"]["overfit"]["n"] == 1
