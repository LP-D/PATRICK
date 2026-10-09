"""Garde-fous de traduction des gabarits.

1. chaque clé `t('clé')` utilisée dans un gabarit existe (une faute de frappe afficherait la clé brute à l'écran) ;
2. FR et EN ont les mêmes champs `{n}` et chaque appel fournit tous les champs du texte (sinon `KeyError` au rendu) ;
3. plus de français en dur dans les gabarits convertis, et le reste des gabarits ne peut pas en gagner (cliquet).
"""
from __future__ import annotations

import re
import string
from pathlib import Path

from patrick.webapp.i18n import STRINGS

TEMPLATES = Path(__file__).resolve().parents[1] / "patrick" / "webapp" / "templates"
_FILLED_BY_MACRO = {"rows_more", "vocab_count"}   # `{n}` remplacé par data_table, resp. par vocabulary.js
_CALL = re.compile(r"(?<![\w.])_?t\(\s*(['\"])([A-Za-z0-9_]+)\1")


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def _call_kwargs(source: str, start: int) -> set[str]:
    """Noms des arguments nommés de l'appel dont la parenthèse ouvrante est à `start`."""
    depth, names, i, n = 0, set(), start, len(source)
    quote = None
    token_start = start + 1
    while i < n:
        c = source[i]
        if quote:
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                break
        elif c == "," and depth == 1:
            token_start = i + 1
        elif c == "=" and depth == 1 and source[i + 1: i + 2] != "=" and source[i - 1] not in "!<>=":
            name = source[token_start:i].strip()
            if re.fullmatch(r"\w+", name):
                names.add(name)
        i += 1
    return names


def _template_sources():
    for path in sorted(TEMPLATES.glob("*.html")):
        yield path, path.read_text(encoding="utf-8")


def test_every_template_key_exists_and_receives_its_fields():
    problems = []
    for path, source in _template_sources():
        for m in _CALL.finditer(source):
            key = m.group(2)
            if key.endswith("_") or key in _FILLED_BY_MACRO:   # préfixe de clé dynamique ; libellé complété par la macro
                continue
            if key not in STRINGS:
                problems.append(f"{path.name}: clé inconnue {key!r}")
                continue
            paren = source.index("(", m.start())
            kwargs = _call_kwargs(source, paren)
            for lang in ("fr", "en"):
                missing = _fields(STRINGS[key][lang]) - kwargs
                if missing:
                    problems.append(f"{path.name}: {key!r} [{lang}] attend {sorted(missing)} (reçu {sorted(kwargs)})")
    assert not problems, "\n".join(problems[:40])


def test_french_and_english_share_the_same_placeholders():
    problems = [k for k, v in STRINGS.items() if "fr" in v and "en" in v and _fields(v["fr"]) != _fields(v["en"])]
    assert not problems, f"champs différents entre FR et EN : {problems[:30]}"


# ---------------------------------------------------------------- français en dur
_FR = re.compile(
    r"[àâçéèêëîïôùûœÀÉÈ]|\b(le|la|les|des|du|de|un|une|et|ou|pour|sur|avec|dans|par|est|sont|pas|aucun|aucune|cette|ce|ces|"
    r"cible|cibles|modèle|modèles|données|lancer|voir|rang|candidats|couverture)\b", re.IGNORECASE)
# Gabarits pas encore entièrement traduits : nombre maximal de textes français en dur (ne peut que diminuer).
_BUDGET = {
    "_components.html": 1,   # valeur par défaut des macros (importées sans contexte : t() y est indisponible)
}


def _blank(text: str, pattern: str, flags: int = 0) -> str:
    return re.sub(pattern, lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=flags)


def _hardcoded_french(source: str) -> int:
    text = _blank(source, r"\{#.*?#\}|<!--.*?-->|<script.*?</script>|<style.*?</style>", re.DOTALL)
    visible = _blank(text, r"\{\{.*?\}\}|\{%.*?%\}|<[^>]+>", re.DOTALL)
    count = sum(1 for line in visible.splitlines() if len(line.strip()) > 3 and _FR.search(line))
    for m in re.finditer(r"\{\{.*?\}\}|\{%.*?%\}", text, flags=re.DOTALL):
        expr = re.sub(r"\b_?t\(\s*(['\"])[^'\"]*\1[^)]*\)", "", m.group(0))
        for a, b in re.findall(r"\"([^\"]{4,})\"|'([^']{4,})'", expr):
            lit = a or b
            if _FR.search(lit) and not lit.startswith(("/", "#")) and not re.fullmatch(r"[\w\-./ ]+", lit):
                count += 1
    # attributs lus à l'écran ou par un lecteur d'écran (info-bulles, libellés d'accessibilité, confirmations)
    for value in re.findall(r'(?:aria-label|title|placeholder|data-tip|data-confirm|alt)="([^"]*)"', text):
        if re.search(r"[àâçéèêëîïôùûœÀÉÈ]", value) and not re.search(r"_?t\(", value):
            count += 1
    return count


def test_no_new_hardcoded_french_in_templates():
    over = []
    for path, source in _template_sources():
        found = _hardcoded_french(source)
        budget = _BUDGET.get(path.name, 0)
        if found > budget:
            over.append(f"{path.name}: {found} texte(s) français en dur (budget {budget}) -> utiliser t('clé') + i18n_legacy.py / i18n_pages.py")
    assert not over, "\n".join(over)
