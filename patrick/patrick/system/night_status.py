"""État de la dernière tâche de nuit (`scripts/nightly_run.ps1`), lu dans la fin de `runs/nightly.log` et le marqueur du cycle des fonds.

Statuts :
- `ok` : le cycle des fonds est allé au bout (marqueur `runs/funds-cycle.json` du jour de la nuit) et chaque étape hors prédictions a fini
  avec le code 0 ;
- `partial` : cycle des fonds fait, mais une étape (sauvegarde, synchronisation, actualités…) a échoué ;
- `failed` : le cycle des fonds n'a pas été atteint ;
- `running` : nuit commencée, pas encore finie (journal écrit il y a moins d'une heure) ;
- `missed` : aucune nuit depuis plus de 36 heures (PC éteint, tâche désinstallée) ;
- `unknown` : pas de journal (autre PC, première installation).

Les passes de prédictions (`daily_predict.py`) sortent avec le code 1 dès qu'UNE prédiction sur des centaines échoue : ce code ne fait pas
une nuit « partielle », seul le marqueur du cycle des fonds compte pour elles. Le journal fait des millions de lignes : seule la fin est lue.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

TAIL_BYTES = 2_000_000
STALE_HOURS = 36
RUNNING_GRACE_S = 3600
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo          # le journal est écrit en heure locale (Get-Date)
_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (.*)$")
_START = "===== passage de nuit"
_STEP = re.compile(r"^== (.+?) : python ")
_DONE = re.compile(r"termine \(code (-?\d+)\)")


def repo_runs_dir() -> Path:
    """`runs/` du dossier de l'application (celui de `nightly_run.ps1` : le parent de `scripts/`)."""
    return Path(__file__).resolve().parents[2] / "runs"


MAX_SCAN_BYTES = 400_000_000          # une nuit écrit des centaines de Mo de sortie de prédictions : on remonte jusqu'à son début


def _tail_lines(path: Path) -> list[str]:
    """Lignes depuis le début de la DERNIÈRE nuit : lecture à rebours par tranches de `TAIL_BYTES` jusqu'à la ligne de début (au plus
    `MAX_SCAN_BYTES`)."""
    marker = _START.encode("utf-8")
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = pos = f.tell()
        chunks: list[bytes] = []
        while pos > 0 and size - pos < MAX_SCAN_BYTES:
            step = min(TAIL_BYTES, pos)
            pos -= step
            f.seek(pos)
            chunks.insert(0, f.read(step))
            joined = b"".join(chunks[:2])                     # la ligne de début peut chevaucher deux tranches
            if marker in joined:
                break
    data = b"".join(chunks)
    cut = data.rfind(marker)
    if cut > 0:
        cut = data.rfind(b"\n", 0, cut) + 1
        data = data[cut:]
    return data.decode("utf-8", errors="replace").splitlines()


def _clean(raw: str) -> str:
    """Le journal mêle la sortie UTF-16 de Python et les lignes UTF-8 de PowerShell : une ligne « termine » commence souvent par un octet
    nul (constaté sur le vrai journal, 24/11), que `strip()` ne retire pas."""
    return raw.replace("\x00", "").replace("\ufeff", "").strip()


def _local(text: str) -> dt.datetime:
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL_TZ)


def parse_last_night(lines: list[str]) -> dict | None:
    """Étapes de la DERNIÈRE nuit du journal : début, fin, `[{"name", "code"}]`. None si aucune nuit dans ces lignes."""
    start_idx = None
    for i in range(len(lines) - 1, -1, -1):
        if _START in lines[i]:
            start_idx = i
            break
    if start_idx is None:
        return None
    m = _LINE.match(_clean(lines[start_idx]))
    started = _local(m.group(1)) if m else None
    steps: list[dict] = []
    ended = None
    for raw in lines[start_idx + 1:]:
        lm = _LINE.match(_clean(raw))
        if not lm:
            continue
        text = lm.group(2)
        sm = _STEP.match(text)
        if sm:
            steps.append({"name": sm.group(1), "code": None})
            continue
        dm = _DONE.search(text)
        if dm and steps and steps[-1]["code"] is None:
            steps[-1]["code"] = int(dm.group(1))
        if text.startswith("== fin"):
            ended = _local(lm.group(1))
    return {"started": started, "ended": ended, "steps": steps}


def night_status(runs_dir: Path | None = None, now: dt.datetime | None = None) -> dict:
    """Statut de la dernière nuit (voir l'en-tête), avec ses étapes en échec. Heures locales, comme le journal."""
    runs_dir = runs_dir or repo_runs_dir()
    now = now or dt.datetime.now(LOCAL_TZ)
    log = runs_dir / "nightly.log"
    if not log.is_file():
        return {"status": "unknown"}
    night = parse_last_night(_tail_lines(log))
    if night is None or night["started"] is None:
        return {"status": "unknown"}
    started = night["started"]
    fmt = "%Y-%m-%dT%H:%M"                                     # heure locale, comme le journal (affichée telle quelle)
    out = {"started": started.strftime(fmt), "ended": night["ended"].strftime(fmt) if night["ended"] else None}
    if (now - started).total_seconds() > STALE_HOURS * 3600:
        return {**out, "status": "missed"}
    if night["ended"] is None:
        age = now.timestamp() - log.stat().st_mtime
        if age < RUNNING_GRACE_S:
            return {**out, "status": "running"}
    stamp = runs_dir / "funds-cycle.json"
    if stamp.is_file():
        try:
            stamp_day = json.loads(stamp.read_text(encoding="utf-8")).get("day")
        except (OSError, ValueError):
            stamp_day = None
        night_days = {started.date().isoformat(), (started.date() + dt.timedelta(days=1)).isoformat()}
        funds_ok = stamp_day in night_days
    else:
        # Nuit lancée par une version d'avant le marqueur (24/11) : l'étape des fonds a fini d'elle-même (0, ou 1 = quelques prédictions en
        # échec) ou non. Pas de fausse alerte tant que la nuit n'écrit pas encore le marqueur.
        funds_steps = [s for s in night["steps"] if "fonds" in s["name"]]
        funds_ok = bool(funds_steps) and all(s["code"] in (0, 1) for s in funds_steps[-1:])
    failed = [s["name"] for s in night["steps"] if s["code"] not in (0, None) and "predictions" not in s["name"]]
    status = "failed" if not funds_ok else "partial" if failed else "ok"
    return {**out, "status": status, "funds_cycle": funds_ok, "failed_steps": failed, "steps": night["steps"]}
