"""Reference reruns (^GSPC and the others) take hours on PC A (Windows): a
system sleep mid-run suspends the process, Yahoo/FRED connections time out
on resume and the worker's job is reaped as stale. `keep_awake` asks
Windows to stay awake while a run executes (SetThreadExecutionState,
ES_CONTINUOUS | ES_SYSTEM_REQUIRED -- the display may still turn off) and
always releases the request, even when the run fails. No-op elsewhere."""
from __future__ import annotations

import pytest

from patrick import keep_awake as ka
from patrick import worker


class _FakeKernel32:
    def __init__(self):
        self.calls = []

    def SetThreadExecutionState(self, flags):
        self.calls.append(flags)
        return 0x80000000


def test_windows_request_is_set_then_released_even_on_failure(monkeypatch):
    fake = _FakeKernel32()
    monkeypatch.setattr(ka.sys, "platform", "win32")
    monkeypatch.setattr(ka, "_kernel32", lambda: fake)
    with pytest.raises(RuntimeError), ka.keep_awake() as active:
        assert active is True
        raise RuntimeError("run failed")
    assert fake.calls == [ka.ES_CONTINUOUS | ka.ES_SYSTEM_REQUIRED, ka.ES_CONTINUOUS]


def test_no_op_outside_windows(monkeypatch):
    monkeypatch.setattr(ka.sys, "platform", "linux")
    monkeypatch.setattr(ka, "_kernel32", lambda: pytest.fail("no Win32 call on Linux"))
    with ka.keep_awake() as active:
        assert active is False


def test_worker_runs_every_job_inside_keep_awake(monkeypatch):
    seen = []

    class _Guard:
        def __enter__(self):
            seen.append("enter")
            return True

        def __exit__(self, *exc):
            seen.append("exit")
            return False

    monkeypatch.setattr(worker, "keep_awake", lambda *a, **k: _Guard())

    def fake_run(*a, **k):
        seen.append("run")
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "run_pipeline", fake_run)
    monkeypatch.setattr(worker.jobs_db, "update_job_progress", lambda *a, **k: None)
    monkeypatch.setattr(worker.jobs_db, "finish_job", lambda *a, **k: None)
    monkeypatch.setattr(worker, "_estimate_total", lambda c: 1)

    class _Capture:
        def __init__(self, *a):
            pass

        def write(self, text):
            return len(text)

        def flush(self):
            pass

        def final_flush(self):
            pass

    monkeypatch.setattr(worker, "_ProgressCapture", _Capture)
    job = {"job_id": "j1", "config_json": '{"objective": {"target_symbol": "^GSPC"}}'}
    worker._run_one_job(None, job, pid=1)
    assert seen == ["enter", "run", "exit"]
