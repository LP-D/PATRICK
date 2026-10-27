"""Texte complet des communiqués, procès-verbaux et discours de banque centrale.

Les flux RSS ne donnent qu'un titre et une phrase (80 à 160 caractères en moyenne pour la Fed et la BoE) : le ton « faucon /
colombe » (`central_bank.py`) y trouve zéro expression, donc aucune valeur. Pour ces seules nouvelles (`source_kind =
central_bank`), on lit la page liée et on en garde le corps de l'article.

Règles :
- seules les pages **https** dont l'hôte est celui d'un flux `central_bank` (ou l'un de ses sous-domaines) sont lues : un lien
  glissé dans un flux ne fait jamais lire un site arbitraire ;
- le texte est lu une fois (table `news_body`) ; un échec est retenté `MAX_ATTEMPTS` fois puis abandonné (le ton se calcule alors
  sur le titre et le résumé du flux) ;
- le texte de la page est celui publié à la date de la nouvelle : il ne modifie pas `known_at` (la nouvelle n'est pas plus
  tôt visible parce qu'on a lu sa page plus tard).
Extraction : le premier conteneur trouvé parmi `<div id="article">` (Fed), `<article>`, `<main>` (BoE) ; sans conteneur, rien n'est
gardé (on ne prend pas toute la page : menus et bandeaux fausseraient le ton).
"""
from __future__ import annotations

import re
import sqlite3
import time
import urllib.parse
from html.parser import HTMLParser

import pandas as pd

MAX_CHARS = 150_000
MAX_ATTEMPTS = 3
PAUSE_S = 0.4
MAX_SECONDS = 240.0
DEFAULT_LIMIT = 60                       # pages lues par collecte : l'arriéré se résorbe sur quelques passages

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})
_SKIP = frozenset({"script", "style", "noscript", "nav", "header", "footer", "aside", "form", "button", "svg", "template",
                   "select", "iframe"})
_BLOCK = frozenset({"p", "div", "li", "br", "tr", "section", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "table", "ul", "ol"})
_SPACE = re.compile(r"[ \t\r\f\v ]+")
_BLANKS = re.compile(r"\n\s*\n+")
_PRIORITY = ("id_article", "article", "main")
_TAIL_MARKERS = frozenset({"Other news", "Related news", "Related content", "Back to top"})     # pied de page BoE collé au corps
_MINUTES_LINK = re.compile(r'href="([^"]*/monetarypolicy/fomcminutes\d{8}\.htm)"', re.IGNORECASE)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._open: dict[str, tuple[str, int]] = {}      # type de conteneur -> (balise, profondeur)
        self.parts: dict[str, list[str]] = {k: [] for k in _PRIORITY}
        self._done: set[str] = set()
        self._skip_depth = 0

    def _kinds(self, tag: str, attrs) -> list[str]:
        found = []
        if tag == "article":
            found.append("article")
        if tag == "main":
            found.append("main")
        if tag == "div" and dict(attrs).get("id") == "article":
            found.append("id_article")
        return found

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br":
                self._emit("\n")
            return
        # profondeur : on compte les balises de même nom que celle du conteneur déjà ouvert, avant d'en ouvrir un nouveau
        for kind, (open_tag, depth) in list(self._open.items()):
            if tag == open_tag:
                self._open[kind] = (open_tag, depth + 1)
        for kind in self._kinds(tag, attrs):
            if kind not in self._open and kind not in self._done:
                self._open[kind] = (tag, 1)
        if tag in _SKIP:
            self._skip_depth += 1
        elif tag in _BLOCK:
            self._emit("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if tag in _SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK:
            self._emit("\n")
        for kind, (open_tag, depth) in list(self._open.items()):
            if tag == open_tag:
                if depth <= 1:
                    del self._open[kind]
                    self._done.add(kind)
                else:
                    self._open[kind] = (open_tag, depth - 1)

    def handle_data(self, data):
        self._emit(data)

    def _emit(self, text: str) -> None:
        if self._skip_depth:
            return
        for kind in self._open:
            self.parts[kind].append(text)


def extract_text(html: str, max_chars: int = MAX_CHARS) -> str:
    """Corps de l'article d'une page de banque centrale, en paragraphes séparés par une ligne ; `""` si aucun conteneur connu."""
    parser = _Extractor()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001, S110 -- HTML malformé : on garde ce qui a été lu avant l'erreur
        pass
    for kind in _PRIORITY:
        raw = "".join(parser.parts[kind])
        text = _clean(raw)
        if text:
            return text[:max_chars]
    return ""


def _clean(raw: str) -> str:
    lines = [_SPACE.sub(" ", line).strip() for line in raw.split("\n")]
    kept = []
    for line in lines:
        if line in _TAIL_MARKERS:
            break
        if line:
            kept.append(line)
    return _BLANKS.sub("\n", "\n".join(kept)).strip()


def minutes_link(html: str, page_url: str) -> str | None:
    """Lien vers le procès-verbal complet quand la page n'est que le communiqué qui l'annonce (Fed : `fomcminutesAAAAMMJJ.htm`)."""
    m = _MINUTES_LINK.search(html or "")
    return urllib.parse.urljoin(page_url, m.group(1)) if m else None


def allowed_hosts(feeds) -> set[str]:
    """Hôtes des flux `central_bank` : les seuls dont on lit les pages."""
    hosts = set()
    for feed in feeds:
        if feed.kind == "central_bank":
            host = urllib.parse.urlsplit(feed.url).hostname
            if host:
                hosts.add(host.lower())
    return hosts


def readable_url(url: str | None, hosts: set[str]) -> bool:
    if not url:
        return False
    parts = urllib.parse.urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    base = host.removeprefix("www.")
    return any(base == h.removeprefix("www.") or base.endswith("." + h.removeprefix("www.")) for h in hosts)


def pending(conn: sqlite3.Connection, limit: int = DEFAULT_LIMIT) -> list[tuple[int, str | None]]:
    """(identifiant, url) des nouvelles de banque centrale sans page lue (ou dont la lecture a échoué moins de MAX_ATTEMPTS fois),
    les plus récentes d'abord."""
    rows = conn.execute(
        "SELECT i.item_id, i.url FROM news_item i LEFT JOIN news_body b ON b.item_id = i.item_id "
        "WHERE i.source_kind = 'central_bank' AND (b.item_id IS NULL OR (b.status = 'failed' AND b.attempts < ?)) "
        "ORDER BY MAX(i.published_at, i.first_seen_at) DESC, i.item_id DESC LIMIT ?", (MAX_ATTEMPTS, int(limit))).fetchall()
    return [(int(r[0]), r[1]) for r in rows]


def fetch_bodies(conn: sqlite3.Connection, feeds, fetch, now=None, limit: int = DEFAULT_LIMIT, pause_s: float = PAUSE_S,
                 sleep=time.sleep, max_seconds: float = MAX_SECONDS, clock=time.monotonic) -> dict:
    """Lit la page des nouvelles de banque centrale en attente. Renvoie {"fetched", "failed", "skipped"}. S'arrête après
    `max_seconds` : les pages restantes seront lues à la collecte suivante."""
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    hosts = allowed_hosts(feeds)
    counts = {"fetched": 0, "failed": 0, "skipped": 0}
    first = True
    started = clock()
    for item_id, url in pending(conn, limit):
        if clock() - started > max_seconds:
            break
        if not readable_url(url, hosts):
            _save(conn, item_id, stamp, "skipped", None, attempts=0)
            counts["skipped"] += 1
            continue
        if not first:
            sleep(pause_s)
        first = False
        previous = conn.execute("SELECT attempts FROM news_body WHERE item_id = ?", (item_id,)).fetchone()
        attempts = (previous[0] if previous else 0) + 1
        try:
            html = fetch(url)
            text = extract_text(html)
            link = minutes_link(html, url)
            if link and readable_url(link, hosts):
                sleep(pause_s)
                try:
                    text = extract_text(fetch(link)) or text
                except Exception:  # noqa: BLE001, S110 -- le communiqué seul reste exploitable
                    pass
        except Exception as exc:  # noqa: BLE001 -- frontière réseau : une page illisible n'arrête pas la collecte
            _save(conn, item_id, stamp, "failed", None, attempts=attempts, error=str(exc)[:200])
            counts["failed"] += 1
            continue
        if text:
            _save(conn, item_id, stamp, "ok", text, attempts=attempts)
            counts["fetched"] += 1
        else:
            _save(conn, item_id, stamp, "failed", None, attempts=attempts, error="aucun corps d'article reconnu")
            counts["failed"] += 1
    return counts


def _save(conn, item_id: int, stamp: str, status: str, text: str | None, attempts: int, error: str | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO news_body (item_id, fetched_at, status, text, attempts, error) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(item_id) DO UPDATE SET fetched_at = excluded.fetched_at, status = excluded.status, "
            "text = excluded.text, attempts = excluded.attempts, error = excluded.error",
            (item_id, stamp, status, text, attempts, error))


def load_bodies(conn: sqlite3.Connection) -> dict[int, tuple[str, str | None]]:
    """{item_id: (statut, texte)} de toutes les pages connues."""
    return {int(i): (s, t) for i, s, t in conn.execute("SELECT item_id, status, text FROM news_body")}


def load_body_texts(conn: sqlite3.Connection, ids) -> dict[int, str]:
    """{item_id: texte} des pages lues parmi `ids`."""
    ids = [int(i) for i in ids]
    out: dict[int, str] = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        marks = ",".join("?" for _ in chunk)
        for i, t in conn.execute(f"SELECT item_id, text FROM news_body WHERE status = 'ok' AND item_id IN ({marks})", chunk):
            out[int(i)] = t or ""
    return out


def tone_ready_ids(conn: sqlite3.Connection) -> set[int]:
    """Nouvelles dont le ton peut se calculer : page lue, ou jamais lisible (hôte refusé, échecs répétés)."""
    rows = conn.execute("SELECT item_id FROM news_body WHERE status IN ('ok', 'skipped') OR attempts >= ?", (MAX_ATTEMPTS,))
    return {int(r[0]) for r in rows}
