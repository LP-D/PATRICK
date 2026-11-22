"""Small numeric helpers shared across the package."""
from __future__ import annotations

import math


def is_nan(value) -> bool:
    """True only for a floating-point NaN (Python or numpy float). False for
    None, integers, strings -- exactly the semantics of the `v != v` idiom it
    replaces (ruff PLR0124), without comparing a value with itself."""
    try:
        return math.isnan(value)
    except TypeError:
        return False
