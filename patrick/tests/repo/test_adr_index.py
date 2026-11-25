"""Index des décisions d'architecture (AM29 du 25/11) : chaque ADR figure une fois dans `docs/adr/README.md`, numéros uniques.

Les numéros ont déjà glissé deux fois (0023 -> 0024, 0029 -> 0030) parce que deux branches écrivaient le même numéro : ce test le voit
à la PR, avant la fusion."""
from __future__ import annotations

import re
from pathlib import Path

ADR = Path(__file__).resolve().parents[3] / "docs" / "adr"
_FILE = re.compile(r"^(\d{4})-[a-z0-9-]+\.md$")
_ROW = re.compile(r"^\| \[(\d{4})\]\((\d{4}-[a-z0-9-]+\.md)\) \| (.+?) \| (\d{4}-\d{2}-\d{2}) \| (.+?) \|$")


def _files() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(ADR.glob("*.md")):
        m = _FILE.match(p.name)
        if m:
            assert m.group(1) not in out, f"numéro d'ADR en double : {m.group(1)} ({out.get(m.group(1))}, {p.name})"
            out[m.group(1)] = p.name
    return out


def _rows() -> list[tuple[str, str, str, str, str]]:
    return [m.groups() for line in (ADR / "README.md").read_text(encoding="utf-8").splitlines() if (m := _ROW.match(line))]


def test_adr_numbers_are_unique_and_follow_each_other():
    nums = sorted(int(n) for n in _files())
    assert nums == list(range(1, len(nums) + 1)), f"numéros manquants ou en trop : {nums}"


def test_every_adr_is_listed_once_in_the_index_with_its_own_file():
    files = _files()
    rows = _rows()
    listed = [r[0] for r in rows]
    assert sorted(listed) == sorted(files), f"index et fichiers diffèrent : absents de l'index {sorted(set(files) - set(listed))}, " \
                                            f"en trop {sorted(set(listed) - set(files))}"
    assert len(listed) == len(set(listed)), "un ADR figure deux fois dans l'index"
    for num, name, *_ in rows:
        assert files[num] == name, f"l'index de {num} pointe vers {name}, le fichier s'appelle {files[num]}"


def test_index_rows_are_in_number_order():
    listed = [int(r[0]) for r in _rows()]
    assert listed == sorted(listed)
