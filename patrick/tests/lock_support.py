"""Un second processus Python qui tient un verrou de `patrick.system.interprocess_lock` (tests du verrou et du pilote des fonds)."""
from __future__ import annotations

import subprocess
import sys
import textwrap

HOLDER = textwrap.dedent("""
    import sys
    from patrick.system.interprocess_lock import file_lock
    with file_lock(sys.argv[1]):
        print("held", flush=True)
        sys.stdin.read()            # tient le verrou jusqu'à la fermeture de son entrée
""")


class Holder:
    """Un autre processus Python qui tient le verrou `path` tant que le bloc `with` est ouvert."""

    def __init__(self, path):
        self.path = str(path)

    def __enter__(self):
        self.proc = subprocess.Popen([sys.executable, "-c", HOLDER, self.path], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
        assert self.proc.stdout.readline().strip() == "held"
        return self

    def __exit__(self, *exc):
        self.proc.stdin.close()
        self.proc.wait(timeout=30)
