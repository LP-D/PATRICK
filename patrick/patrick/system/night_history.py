"""Frise des dernières nuits (VI10 du 26/11) : durée de chaque étape sur les 30 dernières nuits, pour voir laquelle s'allonge.

Le journal de nuit (`runs/nightly.log`) mêle les quelques lignes de PowerShell (« == étape : python … », « termine (code 0) en 434 s ») et des
centaines de Mo de sortie des prédictions. On le lit par blocs en ne gardant que les lignes utiles (débuts de nuit, débuts d'étape,
fins d'étape) : quelques secondes même pour un journal de plusieurs Go (avant la rotation du 25/11). Le résultat est mis en cache par
taille et date du fichier : la page Santé ne relit rien tant que le journal n'a pas bougé.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from patrick.system.night_status import _clean, repo_runs_dir

_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$")
_START = "===== passage de nuit"
_STEP = re.compile(r"^== (.+?) : python ")
_DONE = re.compile(r"termine \(code (-?\d+)\) en ([\d\s \xa0]+) s")
_KEEP = (b"===== passage de nuit", b"== ", b"termine (code")
CHUNK = 8 * 1024 * 1024
_cache: dict = {}


def _scan(path: Path, start: int) -> tuple[list[str], int]:
    """Lignes utiles à partir de l'octet `start` ; renvoie aussi l'octet où reprendre (début de la dernière ligne incomplète)."""
    out: list[str] = []
    rest = b""
    pos = start
    with open(path, "rb") as f:
        f.seek(start)
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            pos += len(block)
            block = rest + block
            lines = block.split(b"\n")
            rest = lines.pop()
            for raw in lines:
                if any(k in raw for k in _KEEP):
                    out.append(raw.replace(b"\x00", b"").decode("utf-8", errors="replace"))
    return out, pos - len(rest)


def _useful_lines(path: Path) -> list[str]:
    """Le journal ne fait que grandir entre deux rotations : on ne relit que la fin ajoutée depuis la dernière lecture (30 s pour 2,8 Go
    la première fois, une fraction de seconde ensuite). Un fichier plus petit qu'avant (rotation) est relu en entier."""
    size = path.stat().st_size
    seen = _cache.get("scan")
    if not seen or seen["path"] != str(path) or size < seen["offset"]:
        seen = {"path": str(path), "offset": 0, "lines": []}
    new, offset = _scan(path, seen["offset"])
    seen = {"path": str(path), "offset": offset, "lines": seen["lines"] + new}
    _cache["scan"] = seen
    return seen["lines"]


def parse_nights(lines: list[str], limit: int = 30) -> list[dict]:
    """`[{"started", "steps": [{"name", "start", "seconds", "code"}]}]`, les plus récentes en dernier (au plus `limit`)."""
    nights: list[dict] = []
    for raw in lines:
        m = _LINE.match(_clean(raw))
        if not m:
            continue
        when, text = m.group(1), m.group(2)
        if _START in text:
            nights.append({"started": when, "steps": []})
            continue
        if not nights:
            continue
        sm = _STEP.match(text)
        if sm:
            nights[-1]["steps"].append({"name": sm.group(1), "start": when, "seconds": None, "code": None})
            continue
        dm = _DONE.search(text)
        if dm and nights[-1]["steps"] and nights[-1]["steps"][-1]["code"] is None:
            step = nights[-1]["steps"][-1]
            step["code"] = int(dm.group(1))
            step["seconds"] = int(re.sub(r"\D", "", dm.group(2)) or 0)
    return nights[-limit:]


def history(runs_dir: Path | None = None, limit: int = 30) -> list[dict]:
    """Les dernières nuits du journal de ce PC, avec leur position dans la frise (`offset` et `seconds` de chaque étape en heures)."""
    path = (runs_dir or repo_runs_dir()) / "nightly.log"
    try:
        st = path.stat()
    except OSError:
        return []
    key = (str(path), st.st_size, st.st_mtime_ns, limit)
    if _cache.get("key") != key:
        _cache.update(key=key, value=_layout(parse_nights(_useful_lines(path), limit)))
    return _cache["value"]


def _layout(nights: list[dict]) -> list[dict]:
    out = []
    for night in nights:
        t0 = dt.datetime.strptime(night["started"], "%Y-%m-%d %H:%M:%S").astimezone()
        steps = []
        for s in night["steps"]:
            start = dt.datetime.strptime(s["start"], "%Y-%m-%d %H:%M:%S").astimezone()
            steps.append({**s, "offset_h": round((start - t0).total_seconds() / 3600, 3),
                          "hours": round((s["seconds"] or 0) / 3600, 3), "failed": s["code"] not in (0, None)})
        total = max((s["offset_h"] + s["hours"] for s in steps), default=0.0)
        out.append({"started": night["started"], "steps": steps, "total_h": round(total, 2)})
    return out
