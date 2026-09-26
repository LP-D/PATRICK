"""`worker._to_native`: the job result must be STRICT JSON (browser `JSON.parse`)."""
from __future__ import annotations


def test_to_native_maps_infinities_to_null_for_strict_json():
    import json

    import numpy as np

    from patrick.worker import _to_native

    out = _to_native({"a": float("inf"), "b": np.float64(-np.inf), "c": [np.nan, 1.5], "d": np.int64(3)})
    assert out == {"a": None, "b": None, "c": [None, 1.5], "d": 3}
    json.dumps(out, allow_nan=False)
