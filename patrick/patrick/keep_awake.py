"""Keep Windows awake while a run executes.

Reference reruns take hours on PC A: a system sleep mid-run suspends the
process, Yahoo/FRED connections time out on resume and the worker's job is
reaped as stale. `SetThreadExecutionState(ES_CONTINUOUS |
ES_SYSTEM_REQUIRED)` asks Windows not to sleep for as long as the calling
thread keeps the request; the display may still turn off. It does NOT
override a closed laptop lid, an explicit Sleep/Shut down, or a Windows
Update restart -- see `docs/ops/veille-windows-runs-de-reference.md` for the
checks to run on PC A. No-op on any other platform.
"""
from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _kernel32():
    import ctypes

    return ctypes.windll.kernel32


@contextlib.contextmanager
def keep_awake() -> Iterator[bool]:
    """Yields True when the request was accepted by Windows."""
    if sys.platform != "win32":
        yield False
        return
    kernel32 = _kernel32()
    accepted = bool(kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED))
    try:
        yield accepted
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)
