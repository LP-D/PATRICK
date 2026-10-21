"""Résumé des résultats de mutmut (`mutmut results --all true`) pour `.github/workflows/mutation.yml`.

Les journaux d'une exécution GitHub ne sont lisibles qu'avec un compte ; le résumé sort donc en annotation (lisible par l'API
publique) et dans le résumé de l'exécution : mutants par module et par statut, score, survivants nommés.

    python scripts/mutation_summary.py mutants/results.txt            # texte Markdown (résumé de l'exécution)
    python scripts/mutation_summary.py mutants/results.txt --annotation
    python scripts/mutation_summary.py --tail mutants/run.log --title "mutmut run"   # fin d'un journal, en annotation
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Un résultat : `    patrick.validation.fdr.x_nom__mutmut_3: survived` (les méthodes de classe portent des « ǁ »).
_RESULT = re.compile(r"^\s*(?P<module>[\w.]+)\.(?P<function>[^.\s:]+?)__mutmut_(?P<n>\d+): (?P<status>[a-z ]+?)\s*$")
CAUGHT = ("killed", "timeout", "segfault", "caught by type check")
UNCAUGHT = ("survived", "no tests", "suspicious")      # ce qu'aucun test ne protège (ou ne départage)
NOT_JUDGED = ("not checked", "skipped", "check was interrupted by user")


def parse(text: str) -> list[tuple[str, str, str]]:
    """(module, mutant complet, statut) pour chaque ligne de résultat ; le reste du texte est ignoré."""
    rows = []
    for line in text.splitlines():
        match = _RESULT.match(line)
        if match:
            name = f"{match['module']}.{match['function']}__mutmut_{match['n']}"
            rows.append((match["module"], name, match["status"]))
    return rows


def count_by_module(text: str) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for module, _name, status in parse(text):
        counts[module][status] += 1
    return {module: dict(c) for module, c in counts.items()}


def summarize(text: str, *, max_listed: int = 40) -> str:
    rows = parse(text)
    if not rows:
        return "Mutation : aucun résultat (mutmut n'a rien produit : voir le journal de l'étape « Mutate »)."
    per_module = count_by_module(text)
    total = Counter(status for _m, _n, status in rows)
    judged = sum(n for status, n in total.items() if status not in NOT_JUDGED)
    caught = sum(total[status] for status in CAUGHT)
    lines = [f"Mutation : {caught}/{judged} mutants attrapés ({round(100 * caught / judged) if judged else 0} %). "
             + ", ".join(f"{n} {status}" for status, n in sorted(total.items(), key=lambda kv: -kv[1])) + ".", ""]
    for module, c in sorted(per_module.items()):
        module_judged = sum(n for status, n in c.items() if status not in NOT_JUDGED)
        module_caught = sum(c.get(status, 0) for status in CAUGHT)
        if not module_judged:
            lines.append(f"- {module} : hors périmètre de cette exécution")
            continue
        lines.append(f"- {module} : {module_caught}/{module_judged} attrapés ("
                     + ", ".join(f"{n} {status}" for status, n in sorted(c.items(), key=lambda kv: -kv[1])) + ")")
    survivors = [name for _m, name, status in rows if status in UNCAUGHT]
    if survivors:
        lines += ["", "Non attrapés (à lire avec `mutmut show <nom>`) :"]
        lines += [f"  {name}" for name in survivors[:max_listed]]
        if len(survivors) > max_listed:
            lines.append(f"  … et {len(survivors) - max_listed} autres")
    return "\n".join(lines)


def annotation(text: str, *, title: str, level: str = "notice") -> str:
    """Une annotation GitHub (`::notice title=…::message`), sur une seule ligne : %, retour chariot et saut de ligne échappés."""
    message = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::{level} title={title}::{message}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("results", nargs="?", help="sortie de `mutmut results --all true`")
    parser.add_argument("--annotation", action="store_true", help="une annotation GitHub au lieu du texte")
    parser.add_argument("--tail", help="fichier dont la fin est émise en annotation (journal de `mutmut run`)")
    parser.add_argument("--title", default="mutation")
    parser.add_argument("--chars", type=int, default=3500)
    args = parser.parse_args(argv)
    if args.tail:
        path = Path(args.tail)
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else "(journal absent)"
        print(annotation(text[-args.chars:], title=args.title))
        return 0
    text = Path(args.results).read_text(encoding="utf-8", errors="replace") if args.results and Path(args.results).exists() else ""
    summary = summarize(text)
    print(annotation(summary[: args.chars], title=args.title) if args.annotation else summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
