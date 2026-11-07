"""Markdown -> HTML pour les cours (sous-ensemble : titres, paragraphes, gras / italique / code, liens, listes, tableaux, citations, blocs de code, règles,
formules `$..$` et `$$..$$` converties en MathML par `latex_lite`). Pas de dépendance externe.

Sécurité : TOUT texte est échappé ; seules les balises `<sup>` et `<sub>` sont conservées ; un lien n'est cliquable que s'il pointe vers `http(s)://` ou une ancre
`#...` (un lien vers un fichier du dépôt devient du code, jamais un lien mort ; `javascript:` n'est jamais un lien).
"""
from __future__ import annotations

import re
import unicodedata
from html import escape

from patrick.knowledge import latex_lite

_INLINE = re.compile(
    r"""(?P<code>`[^`\n]+`)
      |(?<!\\)\$(?P<math>[^$\n]+?)\$
      |\*\*(?P<bold>.+?)\*\*
      |(?<![\w*])\*(?P<em>[^\s*](?:[^*\n]*?[^\s*])?)\*(?![\w*])
      |\[(?P<ltext>[^\]\n]+)\]\((?P<lurl>[^)\s]+)\)
      |<(?P<tag>sup|sub)>(?P<tagbody>[^<\n]*)</(?P=tag)>
      |\\(?P<esc>[\\`*_{}\[\]()#+\-.!$|])""",
    re.VERBOSE,
)
_FENCE = re.compile(r"^```")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def slugify(text: str) -> str:
    text = re.sub(r"[`$*_\\{}]", "", text)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "section"


def _link(label: str, url: str) -> str:
    inner = inline(label)
    if url.startswith(("https://", "http://")):
        return f'<a href="{escape(url, quote=True)}" rel="noopener noreferrer" target="_blank">{inner}</a>'
    if url.startswith("#"):
        return f'<a href="{escape(url, quote=True)}">{inner}</a>'
    if url.lower().startswith(("javascript:", "data:", "vbscript:")):
        return inner
    return f"<code>{escape(re.sub(chr(96), '', label))}</code>"             # lien vers un fichier du dépôt : un nom, pas un lien


def inline(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(escape(text[pos:m.start()]))
        pos = m.end()
        kind = m.lastgroup
        if m.group("code"):
            out.append(f"<code>{escape(m.group('code')[1:-1])}</code>")
        elif m.group("math") is not None:
            out.append(latex_lite.math_element(m.group("math"), display=False))
        elif m.group("bold") is not None:
            out.append(f"<strong>{inline(m.group('bold'))}</strong>")
        elif m.group("em") is not None:
            out.append(f"<em>{inline(m.group('em'))}</em>")
        elif m.group("ltext") is not None:
            out.append(_link(m.group("ltext"), m.group("lurl")))
        elif m.group("tag"):
            out.append(f"<{m.group('tag')}>{escape(m.group('tagbody'))}</{m.group('tag')}>")
        elif m.group("esc"):
            out.append(escape(m.group("esc")))
        else:                                                                 # pragma: no cover (groupes exhaustifs)
            out.append(escape(m.group(0)))
        del kind
    out.append(escape(text[pos:]))
    return "".join(out)


def _split_row(line: str) -> list[str]:
    """Découpe une ligne de tableau sur `|` hors code et hors formule : `$|x|$` et `` `a|b` `` restent entiers."""
    cells, cur = [], []
    in_code = in_math = False
    s = line.strip()
    s = s.removeprefix("|")
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            cur.append(s[i:i + 2])
            i += 2
            continue
        if ch == "`" and not in_math:
            in_code = not in_code
        elif ch == "$" and not in_code:
            in_math = not in_math
        if ch == "|" and not in_code and not in_math:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    cells.append("".join(cur).strip())
    return cells


class _Doc:
    def __init__(self, text: str) -> None:
        self.lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self.i = 0
        self.html: list[str] = []
        self.toc: list[dict] = []
        self.ids: dict[str, int] = {}

    def anchor(self, text: str) -> str:
        base = slugify(text)
        n = self.ids.get(base, 0) + 1
        self.ids[base] = n
        return base if n == 1 else f"{base}-{n}"

    def run(self) -> None:
        while self.i < len(self.lines):
            line = self.lines[self.i]
            if not line.strip():
                self.i += 1
            elif _FENCE.match(line):
                self.code()
            elif line.strip().startswith("$$"):
                self.display_math()
            elif _HEADING.match(line):
                self.heading()
            elif _HR.match(line):
                self.html.append("<hr>")
                self.i += 1
            elif line.lstrip().startswith(">"):
                self.quote()
            elif line.lstrip().startswith("|") and self.i + 1 < len(self.lines) and _SEPARATOR.match(self.lines[self.i + 1]):
                self.table()
            elif _UL.match(line) or _OL.match(line):
                self.list_block()
            else:
                self.paragraph()

    def heading(self) -> None:
        m = _HEADING.match(self.lines[self.i])
        level, text = len(m.group(1)), m.group(2)
        ident = self.anchor(text)
        plain = re.sub(r"\$([^$]*)\$", r"\1", text).replace("`", "")
        self.toc.append({"level": level, "id": ident, "text": plain})
        self.html.append(f'<h{level} id="{ident}">{inline(text)}<a class="anchor" href="#{ident}" aria-label="Lien vers cette section">#</a></h{level}>')
        self.i += 1

    def code(self) -> None:
        self.i += 1
        body = []
        while self.i < len(self.lines) and not _FENCE.match(self.lines[self.i]):
            body.append(self.lines[self.i])
            self.i += 1
        self.i += 1
        self.html.append(f'<pre class="code-block"><code>{escape(chr(10).join(body))}</code></pre>')

    def display_math(self) -> None:
        first = self.lines[self.i].strip()
        if first.count("$$") >= 2 and len(first) > 4:
            body = first[2:first.rindex("$$")]
            self.i += 1
        else:
            body_lines = [first[2:]] if first[2:].strip() else []
            self.i += 1
            while self.i < len(self.lines):
                line = self.lines[self.i]
                self.i += 1
                if "$$" in line:
                    head = line[:line.index("$$")]
                    if head.strip():
                        body_lines.append(head)
                    break
                body_lines.append(line)
            body = "\n".join(body_lines)
        self.html.append(f'<div class="math-block">{latex_lite.math_element(body, display=True)}</div>')

    def quote(self) -> None:
        body = []
        while self.i < len(self.lines) and self.lines[self.i].lstrip().startswith(">"):
            body.append(re.sub(r"^\s*>\s?", "", self.lines[self.i]))
            self.i += 1
        sub = _Doc("\n".join(body))
        sub.ids = self.ids
        sub.run()
        self.html.append("<blockquote>" + "".join(sub.html) + "</blockquote>")

    def table(self) -> None:
        header = _split_row(self.lines[self.i])
        self.i += 2
        rows = []
        while self.i < len(self.lines) and self.lines[self.i].lstrip().startswith("|"):
            rows.append(_split_row(self.lines[self.i]))
            self.i += 1
        width = len(header)
        head = "".join(f'<th scope="col">{inline(c)}</th>' for c in header)
        body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in (r + [""] * width)[:width]) + "</tr>" for r in rows)
        self.html.append(f'<div class="table-scroll"><table class="data-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')

    def list_block(self) -> None:
        ordered = bool(_OL.match(self.lines[self.i])) and not _UL.match(self.lines[self.i])
        pattern = _OL if ordered else _UL
        items: list[str] = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            m = pattern.match(line)
            if m:
                items.append(m.group(2).strip())
                self.i += 1
            elif line.strip() and line.startswith((" ", "\t")) and items and not _UL.match(line) and not _OL.match(line):
                items[-1] += " " + line.strip()                                # ligne de continuation d'un élément
                self.i += 1
            else:
                break
        tag = "ol" if ordered else "ul"
        self.html.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>")

    def paragraph(self) -> None:
        body = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            starts_block = (not line.strip() or _FENCE.match(line) or _HEADING.match(line) or _HR.match(line) or line.lstrip().startswith((">", "$$"))
                            or _UL.match(line) or _OL.match(line)
                            or (line.lstrip().startswith("|") and self.i + 1 < len(self.lines) and _SEPARATOR.match(self.lines[self.i + 1])))
            if body and starts_block:
                break
            body.append(line.strip())
            self.i += 1
        self.html.append(f"<p>{inline(' '.join(body))}</p>")


def render(text: str) -> tuple[str, list[dict]]:
    """`(html, plan)` : le HTML du document et son plan (`[{level, id, text}]`, un par titre)."""
    doc = _Doc(text)
    doc.run()
    return "\n".join(doc.html), doc.toc
