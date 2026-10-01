"""Conservative CPU/RAM cap shared by the pipeline's parallel stages."""
from __future__ import annotations

import os

import psutil

_RESERVE_BYTES = 1024**3
_WORKER_BASE_BYTES = 512 * 1024**2


def cap_workers(requested: int, task_count: int | None = None, input_bytes: int = 0,
                available_bytes: int | None = None) -> int:
    """Bound workers by CPU, task count, and estimated per-worker memory.

    The stages run sequentially, so each stage may use its own configured
    worker count; this shared cap prevents either stage exceeding the same
    machine RAM budget.
    """
    if requested <= 1:
        return 1
    cpu_cap = os.cpu_count() or 1
    task_cap = max(1, task_count) if task_count is not None else cpu_cap
    available = available_bytes if available_bytes is not None else psutil.virtual_memory().available
    per_worker = max(_WORKER_BASE_BYTES, max(0, input_bytes) * 4 + 256 * 1024**2)
    memory_cap = max(1, (max(0, available - _RESERVE_BYTES)) // per_worker)
    return max(1, min(requested, cpu_cap, task_cap, memory_cap))
