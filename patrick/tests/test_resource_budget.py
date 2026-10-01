from __future__ import annotations

from patrick.resource_budget import cap_workers


def test_worker_budget_is_limited_by_cpu_tasks_and_available_memory(monkeypatch):
    monkeypatch.setattr("patrick.resource_budget.os.cpu_count", lambda: 8)

    assert cap_workers(6, task_count=3, available_bytes=16 * 1024**3) == 3
    assert cap_workers(6, task_count=8, available_bytes=1024**3) == 1
    assert cap_workers(6, task_count=8, input_bytes=2 * 1024**3,
                       available_bytes=10 * 1024**3) == 1
