"""A15 : résumé de fin de nuit -- seulement quand il y a quelque chose à signaler ; l'envoi ne fait jamais échouer la nuit."""
from __future__ import annotations

from patrick.fund import autopilot, store
from patrick.system import notify


def test_a_quiet_night_says_nothing(conn):
    assert notify.night_summary(conn, {"status": "ok", "started": "2026-11-23T23:00"}) == []


def test_a_partial_night_replaced_champions_and_a_halted_fund_are_reported(conn):
    conn.execute("INSERT INTO model_archive (target, horizon, run_id, role, decided_at) VALUES ('AAPL', 1, 'r0', 'replaced_champion', '2026-11-24 02:00:00')")
    conn.execute("INSERT INTO model_archive (target, horizon, run_id, role, decided_at) VALUES ('AAPL', 5, 'r9', 'replaced_champion', '2026-11-20 02:00:00')")
    sid = store.create_strategy(conn, "Fonds Prudent", "CTO", 10_000, "2026-01-05")
    autopilot.configure(conn, sid, {})
    stored = store.get_autopilot(conn, sid)
    store.set_autopilot(conn, sid, {**stored, "last_run": {"halted": {"drawdown": 0.21, "limit": 0.2}}})
    conn.commit()

    lines = notify.night_summary(conn, {"status": "partial", "started": "2026-11-23T23:00", "failed_steps": ["synchronisation"]})

    assert lines[0] == "Nuit : étapes en échec : synchronisation."
    assert "1 champion(s) remplacé(s)" in lines[1]                                       # celui d'avant la nuit ne compte pas
    assert "Fonds Prudent" in lines[2]


def test_the_toast_never_raises(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise OSError("pas de PowerShell")
    monkeypatch.setattr(subprocess, "run", boom)
    assert notify.toast("titre", "texte") is False
