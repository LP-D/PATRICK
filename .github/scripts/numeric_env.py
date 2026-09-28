"""Prints the runner's numeric environment as a GitHub annotation (readable on
the run page and through the check-runs API): the CPU and what it selects,
the OpenBLAS kernel and numpy's SIMD level -- what the golden master of
`run_pipeline` depends on (patrick/tests/test_run_pipeline_golden.py)."""
import platform

import scipy.linalg  # noqa: F401 -- loads scipy's own OpenBLAS
import threadpoolctl
from numpy._core import _multiarray_umath as mu

try:
    with open("/proc/cpuinfo") as f:
        cpu = next(line.split(":", 1)[1].strip() for line in f if line.startswith("model name"))
except (OSError, StopIteration):
    cpu = platform.processor()
blas = sorted({f"{lib['internal_api']}:{lib.get('architecture')}"
               for lib in threadpoolctl.threadpool_info() if lib["user_api"] == "blas"})
enabled = [feat for feat in mu.__cpu_dispatch__ if mu.__cpu_features__.get(feat)]
print(f"::notice title=numeric environment::cpu={cpu} | blas={blas} | "
      f"numpy dispatch={list(mu.__cpu_dispatch__)} enabled={enabled}")
