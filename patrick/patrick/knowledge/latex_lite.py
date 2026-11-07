"""LaTeX -> MathML pour le sous-ensemble utilisé par les cours (pas de dépendance : KaTeX/MathJax auraient exigé un fichier vendu ou le réseau).

MathML est affiché nativement par les navigateurs actuels. Le convertisseur ne lève jamais d'exception : une entrée mal équilibrée est refermée, une commande
inconnue devient un `<mtext class="tex-unknown">` et est renvoyée dans la liste `unknown` (un test vérifie que les cours n'en contiennent aucune).
Tout texte est échappé : du HTML écrit dans une formule reste du texte.
"""
from __future__ import annotations

import re
from html import escape

GREEK = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ϵ", "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π", "rho": "ρ", "sigma": "σ", "varsigma": "ς", "tau": "τ",
    "upsilon": "υ", "phi": "ϕ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
}
GREEK_UPPER = {"Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω"}
OPERATORS = {
    "times": "×", "cdot": "·", "pm": "±", "mp": "∓", "approx": "≈", "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠", "sim": "∼",
    "propto": "∝", "in": "∈", "notin": "∉", "to": "→", "rightarrow": "→", "leftarrow": "←", "Rightarrow": "⇒", "Longrightarrow": "⟹", "mid": "∣", "ldots": "…",
    "dots": "…", "cdots": "⋯", "equiv": "≡", "cap": "∩", "cup": "∪", "subset": "⊂", "forall": "∀", "exists": "∃", "otimes": "⊗", "oplus": "⊕", "circ": "∘",
    "ast": "∗", "star": "⋆", "perp": "⊥", "ll": "≪", "gg": "≫", "partial": "∂", "nabla": "∇", "lceil": "⌈", "rceil": "⌉", "lfloor": "⌊", "rfloor": "⌋",
    "lvert": "|", "rvert": "|", "lVert": "‖", "rVert": "‖", "langle": "⟨", "rangle": "⟩", "div": "÷", "land": "∧", "lor": "∨", "neg": "¬", "simeq": "≃",
    "cong": "≅", "asymp": "≍", "top": "⊤", "intercal": "⊤",
}
SYMBOLS = {"infty": "∞", "ell": "ℓ", "hbar": "ℏ", "emptyset": "∅", "prime": "′"}      # opérandes (pas des opérateurs)
BIG_OPERATORS = {"sum": "∑", "prod": "∏", "int": "∫", "bigcup": "⋃", "bigcap": "⋂"}
FUNCTIONS = {"ln", "log", "exp", "sin", "cos", "tan", "min", "max", "arg", "Pr", "lim", "sup", "inf", "det", "dim", "gcd", "cov", "var", "corr", "sgn"}
SIZERS = {"big", "Big", "bigg", "Bigg", "bigl", "bigr", "Bigl", "Bigr", "biggl", "biggr", "Biggl", "Biggr", "left", "right", "middle", "displaystyle", "textstyle", "limits", "nolimits"}
SPACES = {"quad": "1em", "qquad": "2em", ",": "0.1667em", ";": "0.2778em", ":": "0.2222em", " ": "0.25em", "enspace": "0.5em"}
ACCENTS = {"hat": "^", "widehat": "^", "bar": "¯", "overline": "¯", "tilde": "˜", "widetilde": "˜", "dot": "˙", "ddot": "¨", "vec": "→", "check": "ˇ"}
STYLES = {"mathbf": "bold", "boldsymbol": "bold", "bm": "bold", "mathbb": "double-struck", "mathcal": "script", "mathit": "italic", "mathsf": "sans-serif"}
TEXT_COMMANDS = {"text", "textrm", "texttt", "textbf", "textit", "mbox", "mathrm"}
LITERAL_ESCAPES = {"%": "%", "_": "_", "#": "#", "&": "&", "$": "$"}

_TOKEN = re.compile(r"\\([A-Za-z]+)|\\([^A-Za-z])|([{}^_&'])|(\s+)|(\d+)|([A-Za-z])|(.)", re.DOTALL)


def _tokenize(src: str) -> tuple[list[tuple[str, str]], list[bool]]:
    """Jetons `(type, valeur)` et, en parallèle, `True` quand une espace précédait le jeton (utile seulement dans `\text{...}`)."""
    out: list[tuple[str, str]] = []
    spaced: list[bool] = []
    pending = False
    for m in _TOKEN.finditer(src):
        cmd, esc, special, space, num, letter, other = m.groups()
        if space:
            pending = True
            continue
        spaced.append(pending)
        pending = False
        if cmd:
            out.append(("cmd", cmd))
        elif esc is not None:
            out.append(("esc", esc))
        elif special:
            out.append(({"{": "lb", "}": "rb", "^": "sup", "_": "sub", "&": "amp", "'": "prime"}[special], special))
        elif num:
            out.append(("num", num))
        elif letter:
            out.append(("letter", letter))
        else:
            out.append(("other", other))
    return out, spaced


def _mo(ch: str, stretchy: bool | None = None) -> str:
    extra = ' stretchy="false"' if stretchy is False else ""
    return f"<mo{extra}>{escape(ch)}</mo>"


def _row(items: list[str]) -> str:
    return items[0] if len(items) == 1 else "<mrow>" + "".join(items) + "</mrow>"


class _Parser:
    def __init__(self, src: str, display: bool) -> None:
        self.t, self.sp = _tokenize(src)
        self.i = 0
        self.display = display
        self.unknown: list[str] = []

    # ------------------------------------------------------------ outils
    def peek(self, k: int = 0) -> tuple[str, str] | None:
        return self.t[self.i + k] if self.i + k < len(self.t) else None

    def eat(self) -> tuple[str, str] | None:
        tok = self.peek()
        if tok is not None:
            self.i += 1
        return tok

    # ------------------------------------------------------------ séquences
    def sequence(self, stops: tuple[str, ...] = ()) -> list[str]:
        items: list[str] = []
        while self.i < len(self.t):
            kind, val = self.t[self.i]
            if kind in stops:
                break
            if kind == "cmd" and val == "end" and "end" in stops:
                break
            if kind == "esc" and val == "\\" and "newline" in stops:
                break
            if kind == "rb":                              # accolade fermante sans ouvrante : ignorée
                self.i += 1
                continue
            items.append(self.atom_with_scripts())
        return items

    def argument(self) -> str:
        """Un argument de commande : un groupe `{...}` ou un seul atome ; vide s'il manque."""
        tok = self.peek()
        if tok is None or tok[0] in ("rb", "amp"):
            return "<mrow></mrow>"
        if tok[0] == "lb":
            self.i += 1
            inner = self.sequence(("rb",))
            if self.peek() is not None:
                self.i += 1                              # l'accolade fermante
            return _row(inner) if inner else "<mrow></mrow>"
        return self.atom()

    def atom_with_scripts(self) -> str:
        base, kind = self.atom_kind()
        sub = sup = None
        primes = 0
        while True:
            tok = self.peek()
            if tok is None:
                break
            if tok[0] == "prime":
                primes += 1
                self.i += 1
            elif tok[0] == "sub" and sub is None:
                self.i += 1
                sub = self.argument()
            elif tok[0] == "sup" and sup is None:
                self.i += 1
                sup = self.argument()
            else:
                break
        if primes:
            prime = "<mo>" + "′" * primes + "</mo>"
            sup = prime if sup is None else f"<mrow>{prime}{sup}</mrow>"
        if sub is None and sup is None:
            return base
        over_under = kind in ("underbrace", "accent") or (kind == "bigop" and self.display) or kind == "limop"
        if over_under and kind != "accent":
            if sub is not None and sup is not None:
                return f"<munderover>{base}{sub}{sup}</munderover>"
            return f"<munder>{base}{sub}</munder>" if sub is not None else f"<mover>{base}{sup}</mover>"
        if sub is not None and sup is not None:
            return f"<msubsup>{base}{sub}{sup}</msubsup>"
        return f"<msub>{base}{sub}</msub>" if sub is not None else f"<msup>{base}{sup}</msup>"

    def atom(self) -> str:
        return self.atom_kind()[0]

    # ------------------------------------------------------------ atomes
    def atom_kind(self) -> tuple[str, str]:
        tok = self.eat()
        if tok is None:
            return "<mrow></mrow>", "normal"
        kind, val = tok
        if kind == "num":
            return self.number(val), "normal"
        if kind == "letter":
            return f"<mi>{val}</mi>", "normal"
        if kind == "lb":
            self.i -= 1
            return self.argument(), "normal"
        if kind in ("sub", "sup"):                       # indice/exposant sans base : base vide
            self.i -= 1
            return "<mrow></mrow>", "normal"
        if kind == "amp":
            return "", "normal"
        if kind == "prime":
            return "<mo>′</mo>", "normal"
        if kind == "esc":
            return self.escape_atom(val), "normal"
        if kind == "cmd":
            return self.command(val)
        return self.other(val), "normal"

    def number(self, digits: str) -> str:
        # « 1{,}38 » (virgule décimale à la française) reste un seul nombre
        a, b, c, d = self.peek(0), self.peek(1), self.peek(2), self.peek(3)
        if a and a[0] == "lb" and b and b == ("other", ",") and c and c[0] == "rb" and d and d[0] == "num":
            self.i += 4
            return f"<mn>{digits},{d[1]}</mn>"
        if a == ("other", ".") and b and b[0] == "num":
            self.i += 2
            return f"<mn>{digits}.{b[1]}</mn>"
        return f"<mn>{digits}</mn>"

    def other(self, ch: str) -> str:
        if ch == "-":
            return _mo("−")
        if ch in "()[]":
            return _mo(ch, stretchy=False)
        if ch in "+=<>|,;:/!*.~?":
            return _mo(ch)
        return f"<mtext>{escape(ch)}</mtext>"

    def escape_atom(self, ch: str) -> str:
        if ch in SPACES:
            return f'<mspace width="{SPACES[ch]}"/>'
        if ch == "!":
            return ""
        if ch in "{}":
            return _mo(ch, stretchy=False)
        if ch == "|":
            return _mo("‖")
        if ch == "\\":
            if self.peek() == ("other", "["):            # `\\[2pt]` : l'espacement optionnel est ignoré
                while self.i < len(self.t) and self.t[self.i] != ("other", "]"):
                    self.i += 1
                self.i += 1
            return '<mspace linebreak="newline"/>'
        if ch in LITERAL_ESCAPES:
            return f"<mo>{escape(LITERAL_ESCAPES[ch])}</mo>" if ch in "%&$#" else "<mo>_</mo>"
        return f"<mtext>{escape(ch)}</mtext>"

    def command(self, name: str) -> tuple[str, str]:
        if name in GREEK:
            return f"<mi>{GREEK[name]}</mi>", "normal"
        if name in GREEK_UPPER:
            return f'<mi mathvariant="normal">{GREEK_UPPER[name]}</mi>', "normal"
        if name in OPERATORS:
            return _mo(OPERATORS[name]), "normal"
        if name in SYMBOLS:
            return f"<mi>{SYMBOLS[name]}</mi>", "normal"
        if name in BIG_OPERATORS:
            return f'<mo largeop="true" movablelimits="true">{BIG_OPERATORS[name]}</mo>', "bigop"
        if name in FUNCTIONS:
            return f'<mi mathvariant="normal">{name}</mi>', "limop" if name in ("lim", "max", "min", "sup", "inf") and self.display else "normal"
        if name in SIZERS:
            if name in ("displaystyle", "textstyle", "limits", "nolimits"):
                return "", "normal"
            nxt = self.peek()
            if nxt == ("other", "."):                    # `\left.` : délimiteur nul
                self.i += 1
                return "", "normal"
            return self.atom_kind()
        if name in SPACES:
            return f'<mspace width="{SPACES[name]}"/>', "normal"
        if name in ("frac", "tfrac", "dfrac", "cfrac"):
            return f"<mfrac>{self.argument()}{self.argument()}</mfrac>", "normal"
        if name == "binom":
            return f'<mrow><mo>(</mo><mfrac linethickness="0">{self.argument()}{self.argument()}</mfrac><mo>)</mo></mrow>', "normal"
        if name == "sqrt":
            if self.peek() == ("other", "["):
                self.i += 1
                index = self.sequence_until_bracket()
                return f"<mroot>{self.argument()}{index}</mroot>", "normal"
            return f"<msqrt>{self.argument()}</msqrt>", "normal"
        if name in ACCENTS:
            return f'<mover accent="true">{self.argument()}<mo>{ACCENTS[name]}</mo></mover>', "accent"
        if name in STYLES:
            return f'<mstyle mathvariant="{STYLES[name]}">{self.argument()}</mstyle>', "normal"
        if name in TEXT_COMMANDS or name == "operatorname":
            text = self.text_argument()
            if name in ("mathrm", "operatorname"):
                return f'<mi mathvariant="normal">{escape(text)}</mi>', "limop" if text in ("lim", "max", "min") and self.display else "normal"
            return f"<mtext>{escape(text)}</mtext>", "normal"
        if name == "xrightarrow":
            return f"<mover><mo>→</mo>{self.argument()}</mover>", "normal"
        if name == "underbrace":
            return f"<munder>{self.argument()}<mo>⏟</mo></munder>", "underbrace"
        if name == "boxed":
            return f'<mrow class="tex-boxed">{self.argument()}</mrow>', "normal"
        if name == "begin":
            return self.environment(), "normal"
        if name == "end":
            self.text_argument()
            return "", "normal"
        self.unknown.append(name)
        return f'<mtext class="tex-unknown">\\{escape(name)}</mtext>', "normal"

    def sequence_until_bracket(self) -> str:
        items: list[str] = []
        while self.i < len(self.t) and self.t[self.i] != ("other", "]"):
            items.append(self.atom_with_scripts())
        if self.i < len(self.t):
            self.i += 1
        return _row(items) if items else "<mrow></mrow>"

    def text_argument(self) -> str:
        """Contenu textuel d'un groupe `{...}`, espaces d'origine compris (`\text{si AMC}`) ; sans groupe, le jeton suivant."""
        tok = self.peek()
        if tok is None or tok[0] != "lb":
            tok = self.eat()
            return tok[1] if tok else ""
        self.i += 1
        depth, out = 1, []
        while self.i < len(self.t):
            kind, val = self.t[self.i]
            space = self.sp[self.i]
            self.i += 1
            if kind == "lb":
                depth += 1
            elif kind == "rb":
                depth -= 1
                if depth == 0:
                    break
            if kind == "cmd" and val in ("quad", "qquad"):
                out.append(" ")
                continue
            if kind == "esc" and val in (",", ";", ":", " "):
                out.append(" ")
                continue
            out.append((" " if space and out else "") + val)
        return "".join(out).strip()

    # ------------------------------------------------------------ environnements
    def environment(self) -> str:
        env = self.text_argument().strip()
        if env not in ("cases",):
            self.unknown.append(f"begin:{env}")
        rows: list[list[str]] = [[]]
        cell: list[str] = []
        while self.i < len(self.t):
            tok = self.peek()
            if tok[0] == "cmd" and tok[1] == "end":
                self.i += 1
                self.text_argument()
                break
            if tok[0] == "amp":
                self.i += 1
                rows[-1].append(_row(cell) if cell else "<mrow></mrow>")
                cell = []
            elif tok == ("esc", "\\"):
                self.i += 1
                if self.peek() == ("other", "["):
                    while self.i < len(self.t) and self.t[self.i] != ("other", "]"):
                        self.i += 1
                    self.i += 1
                rows[-1].append(_row(cell) if cell else "<mrow></mrow>")
                cell = []
                rows.append([])
            else:
                cell.append(self.atom_with_scripts())
        if cell or rows[-1]:
            rows[-1].append(_row(cell) if cell else "<mrow></mrow>")
        rows = [r for r in rows if r]
        body = "".join("<mtr>" + "".join(f"<mtd>{c}</mtd>" for c in r) + "</mtr>" for r in rows)
        return f'<mrow><mo>{{</mo><mtable columnalign="left left">{body}</mtable></mrow>'


def to_mathml(src: str, display: bool = False) -> tuple[str, list[str]]:
    """Convertit une formule LaTeX en MathML (balises internes, sans l'élément `<math>`). Renvoie `(mathml, commandes_inconnues)`."""
    p = _Parser(src, display)
    items = p.sequence()
    return "".join(items), p.unknown


def math_element(src: str, display: bool = False) -> str:
    """L'élément `<math>` complet, prêt à être inséré dans une page ; l'original LaTeX reste dans `alttext` (lecteurs d'écran, copie)."""
    inner, _ = to_mathml(src, display)
    kind = ' display="block"' if display else ""
    return f'<math xmlns="http://www.w3.org/1998/Math/MathML"{kind} alttext="{escape(src.strip(), quote=True)}">{inner}</math>'
