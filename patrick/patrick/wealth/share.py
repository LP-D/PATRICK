"""Partage du patrimoine entre PC, SANS PC de référence : chaque PC publie le sien dans un petit fichier à lui
(`wealth-<pc>.db.gz`, voir `patrick.sync.core`) et fusionne ceux des autres LIGNE PAR LIGNE, comme un `git merge`
qui se résoudrait tout seul (migration 0062).

Identité : un compte par son `account_id`, un mouvement par son `uid` (le même sur tous les PC ; `movement_id` reste
un numéro propre à chaque base). Chaque ligne porte la date de sa dernière modification (`updated_at`) et une
suppression laisse une trace datée (`wealth_deleted`). Règles, dans une seule transaction :

- ligne absente d'ici : importée ;
- présente des deux côtés et différente : la version modifiée en dernier l'emporte ; à date égale, le même choix
  sur tous les PC (empreinte du contenu), pour qu'ils convergent ; la version écartée est sauvegardée en JSON ;
- supprimée ailleurs : supprimée ici, sauf si elle a été modifiée ici après la suppression (pour un compte, la
  modification la plus récente de ses mouvements compte aussi : un compte supprimé sur un PC pendant qu'on y
  ajoutait un mouvement sur l'autre revient, avec ses mouvements) ;
- même mouvement saisi sur deux PC avant leur échange (le même relevé importé des deux côtés) : reconnu au contenu
  (compte, date, type, titre, quantité, prix, montant, frais, taux, échéance) et rangé sous un seul identifiant (le
  plus petit des deux, choisi de la même façon sur chaque PC) au lieu d'être compté deux fois.

Quel que soit l'ordre des échanges, les PC aboutissent au même patrimoine. Les horloges des PC servent d'arbitre :
deux modifications de la même ligne à quelques secondes d'écart sur des PC mal réglés peuvent être départagées à
l'envers ; la version écartée reste dans la sauvegarde (`~/.patrick/backups/patrimoine_fusion_*.json`).

Passage depuis l'ancien partage (un PC de référence publiait, les autres l'adoptaient) : `adopt_wealth` remplace une
dernière fois le patrimoine d'un PC qui suivait la référence par celui qu'elle publie (voir `patrick.sync.core`).
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from patrick.core import paths
from patrick.tracking import db as trackdb

TABLES = ("wealth_account", "wealth_movement", "wealth_deleted")
MIN_SCHEMA = 62                                   # 0062 : `uid`, `updated_at`, `wealth_deleted`
# Contenu qui fait d'un mouvement « le même » sur deux PC qui l'ont saisi chacun de leur côté (la note n'en fait pas partie).
_SAME_MOVEMENT = ("account_id", "ts", "kind", "symbol", "quantity", "price", "amount", "fees", "rate", "maturity")
# Identifiant des mouvements antérieurs à la migration 0062 (ou insérés sans passer par `ledger`) : celui de la migration.
_LEGACY_UID_SQL = ("'mv_' || account_id || '_' || movement_id || '_' || "
                   "replace(replace(replace(created_at, ' ', 'T'), ':', ''), '-', '')")


class WealthShareError(RuntimeError):
    """Échange impossible (version de PATRICK trop ancienne ou trop récente...), expliqué à l'utilisateur."""


def _uri(path: str | Path, mode: str) -> str:
    return Path(path).resolve().as_uri() + f"?mode={mode}"


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _shared_columns(conn: sqlite3.Connection, table: str, *, skip: tuple[str, ...] = ()) -> list[str]:
    src = set(_columns(conn, "src", table))
    return [c for c in _columns(conn, "main", table) if c in src and c not in skip]


def _csv(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


def ensure_identities(db_path: str) -> int:
    """Donne un `uid` et un `updated_at` aux lignes qui n'en ont pas (insérées sans passer par `ledger`) ; renvoie le
    nombre de lignes complétées. À appeler avant d'exporter ou de fusionner."""
    conn = sqlite3.connect(_uri(db_path, "rw"), uri=True, timeout=60)
    try:
        with conn:
            n = conn.execute(f"UPDATE wealth_movement SET uid = {_LEGACY_UID_SQL} WHERE uid IS NULL").rowcount
            n += conn.execute("UPDATE wealth_movement SET updated_at = created_at WHERE updated_at IS NULL").rowcount
            n += conn.execute("UPDATE wealth_account SET updated_at = created_at WHERE updated_at IS NULL").rowcount
        return n
    finally:
        conn.close()


def has_wealth(db_path: str) -> bool:
    """Ce PC a-t-il un patrimoine (des comptes ou des traces de suppression) ? Lecture seule."""
    conn = sqlite3.connect(_uri(db_path, "ro"), uri=True)
    try:
        return bool(conn.execute(
            "SELECT (SELECT COUNT(*) FROM wealth_account) + (SELECT COUNT(*) FROM wealth_deleted)").fetchone()[0])
    finally:
        conn.close()


def fingerprint(db_path: str) -> str:
    """Empreinte du patrimoine (identités, dates de modification, suppressions). Lecture seule."""
    conn = sqlite3.connect(_uri(db_path, "ro"), uri=True)
    try:
        parts = [conn.execute("SELECT account_id, COALESCE(updated_at, created_at) FROM wealth_account ORDER BY 1").fetchall(),
                 conn.execute("SELECT COALESCE(uid, movement_id), account_id, COALESCE(updated_at, created_at) "
                              "FROM wealth_movement ORDER BY 1").fetchall(),
                 conn.execute("SELECT kind, uid, deleted_at FROM wealth_deleted ORDER BY 1, 2").fetchall()]
    finally:
        conn.close()
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()


def export_wealth(db_path: str, dest: str | Path) -> dict:
    """Écrit dans `dest` (fichier neuf) une base migrée qui ne contient que le patrimoine de `db_path`. Renvoie
    `{"accounts", "movements", "deleted"}`."""
    dest = Path(dest)
    if dest.exists():
        raise WealthShareError(f"{dest} existe déjà")
    ensure_identities(db_path)
    trackdb.connect(str(dest)).close()                     # schéma à jour, vide
    conn = sqlite3.connect(_uri(dest, "rwc"), uri=True, isolation_level=None)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("ATTACH DATABASE ? AS src", (_uri(db_path, "ro"),))
        conn.execute("BEGIN")
        for table in TABLES:
            cols = _csv(_shared_columns(conn, table))
            conn.execute(f'INSERT INTO main."{table}" ({cols}) SELECT {cols} FROM src."{table}"')
        conn.execute("COMMIT")
        out = {key: conn.execute(f"SELECT COUNT(*) FROM main.{table}").fetchone()[0]
               for key, table in (("accounts", "wealth_account"), ("movements", "wealth_movement"),
                                  ("deleted", "wealth_deleted"))}
        conn.execute("DETACH DATABASE src")
    finally:
        conn.close()
    return out


def _open(db_path: str, incoming: str | Path) -> sqlite3.Connection:
    """Connexion à `db_path` avec le fichier d'un autre PC attaché sous `src`, versions de schéma vérifiées."""
    ensure_identities(db_path)
    conn = sqlite3.connect(_uri(db_path, "rw"), uri=True, isolation_level=None, timeout=60)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")          # parents et enfants gérés à la main, vérifiés à la fin
        conn.execute("ATTACH DATABASE ? AS src", (_uri(incoming, "ro"),))
        mine = conn.execute("SELECT COALESCE(MAX(version), 0) FROM main.schema_version").fetchone()[0]
        theirs = conn.execute("SELECT COALESCE(MAX(version), 0) FROM src.schema_version").fetchone()[0]
        if theirs > mine:
            raise WealthShareError(f"Le patrimoine du partage est en version de schéma {theirs}, ce PC ne connaît que "
                                   f"{mine} : mets PATRICK à jour sur ce PC.")
        if theirs < MIN_SCHEMA:
            raise WealthShareError(f"Le patrimoine du partage vient d'une version trop ancienne de PATRICK (schéma {theirs}) : "
                                   "mets PATRICK à jour sur l'autre PC.")
    except BaseException:
        conn.close()
        raise
    return conn


def _rows(conn: sqlite3.Connection, schema: str, table: str, cols: list[str], key: str) -> dict[str, dict]:
    return {row[key]: row for row in (dict(zip(cols, r)) for r in conn.execute(f'SELECT {_csv(cols)} FROM {schema}."{table}"'))}


def _digest(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


def _wins(theirs: dict, mine: dict) -> bool:
    """La version de l'autre PC remplace-t-elle la nôtre ? La plus récente gagne ; à date égale, l'empreinte décide
    (le même choix sur les deux PC)."""
    if theirs == mine:
        return False
    a, b = theirs.get("updated_at") or "", mine.get("updated_at") or ""
    return a > b if a != b else _digest(theirs) > _digest(mine)


def _same_content(theirs: dict, mine: dict) -> bool:
    """Même ligne à la date de modification près (le même relevé importé sur les deux PC) : pas une modification."""
    return {**theirs, "updated_at": None} == {**mine, "updated_at": None}


def _apply(conn, table: str, key: str, theirs: dict, mine: dict, lost: list, why: str, label: str) -> bool:
    """Applique la version gagnante de l'autre PC sur une ligne présente des deux côtés ; renvoie True si c'est une vraie
    modification (comptée et sauvegardée). Seule la date diffère : on garde la plus récente, sans rien signaler."""
    if not _wins(theirs, mine):
        return False
    if _same_content(theirs, mine):
        conn.execute(f'UPDATE main."{table}" SET updated_at = ? WHERE "{key}" = ?', (theirs["updated_at"], theirs[key]))
        return False
    lost.append({"why": why, label: mine})
    _update(conn, table, key, theirs)
    return True


def _activity(account: dict, movements: dict[str, dict]) -> str:
    """Dernière modification d'un compte, celles de ses mouvements comprises."""
    stamps = [account.get("updated_at") or ""] + [m.get("updated_at") or "" for m in movements.values()
                                                  if m["account_id"] == account["account_id"]]
    return max(stamps)


def _same_key(mv: dict) -> tuple:
    return tuple(round(mv[c], 9) if isinstance(mv[c], float) else mv[c] for c in _SAME_MOVEMENT)


def _unify_duplicates(conn, mine: dict, theirs: dict, mine_del: dict, theirs_del: dict) -> int:
    """Même mouvement saisi des deux côtés avant l'échange : un seul identifiant (le plus petit des deux). Renvoie le
    nombre de doublons reconnus. `mine` et `theirs` sont mis à jour."""
    new_there = sorted(u for u in theirs if u not in mine and ("movement", u) not in mine_del)
    only_here = sorted(u for u in mine if u not in theirs and ("movement", u) not in theirs_del)
    pool: dict[tuple, list[str]] = defaultdict(list)
    for uid in only_here:
        pool[_same_key(mine[uid])].append(uid)
    found = 0
    for uid in new_there:
        candidates = pool.get(_same_key(theirs[uid]))
        if not candidates:
            continue
        local = candidates.pop(0)
        found += 1
        if uid < local:                                    # on prend leur identifiant
            conn.execute("UPDATE main.wealth_movement SET uid = ? WHERE uid = ?", (uid, local))
            mine[uid] = {**mine.pop(local), "uid": uid}
        else:                                              # ils prendront le nôtre à leur tour
            theirs[local] = {**theirs.pop(uid), "uid": local}
    return found


def _set_tombstone(conn, kind: str, uid: str, deleted_at: str, known: dict) -> None:
    if deleted_at > known.get((kind, uid), ""):
        conn.execute("INSERT OR REPLACE INTO main.wealth_deleted (kind, uid, deleted_at) VALUES (?, ?, ?)",
                     (kind, uid, deleted_at))
        known[(kind, uid)] = deleted_at


def _forget_tombstone(conn, kind: str, uid: str, known: dict) -> None:
    conn.execute("DELETE FROM main.wealth_deleted WHERE kind = ? AND uid = ?", (kind, uid))
    known.pop((kind, uid), None)


def _insert(conn, table: str, row: dict) -> None:
    cols = list(row)
    conn.execute(f'INSERT INTO main."{table}" ({_csv(cols)}) VALUES ({", ".join("?" * len(cols))})',
                 [row[c] for c in cols])


def _update(conn, table: str, key: str, row: dict) -> None:
    cols = [c for c in row if c != key]
    conn.execute(f'UPDATE main."{table}" SET {", ".join(f"{chr(34)}{c}{chr(34)} = ?" for c in cols)} WHERE "{key}" = ?',
                 [row[c] for c in cols] + [row[key]])


def _write_backup(lost: list[dict], backup_dir: str | Path, why: str) -> str | None:
    if not lost:
        return None
    os.makedirs(backup_dir, exist_ok=True)
    path = Path(backup_dir) / f"patrimoine_{why}_{datetime.now(UTC):%Y%m%d_%H%M%S_%f}.json"
    path.write_text(json.dumps(lost, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return str(path)


def merge_wealth(db_path: str, incoming: str | Path, *, backup_dir: str | Path | None = None) -> dict:
    """Fusionne dans `db_path` (en place, en UNE transaction) le patrimoine du fichier `incoming` (voir le module).
    Renvoie les compteurs `accounts_added`, `accounts_updated`, `accounts_deleted`, `movements_added`,
    `movements_updated`, `movements_deleted`, `duplicates` (mouvements saisis des deux côtés) et `backup` (fichier JSON
    des versions locales écartées, ou None)."""
    backup_dir = backup_dir or paths.backups_dir()
    conn = _open(db_path, incoming)
    try:
        out = dict.fromkeys(("accounts_added", "accounts_updated", "accounts_deleted", "movements_added",
                             "movements_updated", "movements_deleted", "duplicates"), 0)
        lost: list[dict] = []
        conn.execute("BEGIN IMMEDIATE")
        try:
            acc_cols = _shared_columns(conn, "wealth_account")
            mov_cols = _shared_columns(conn, "wealth_movement", skip=("movement_id",))
            accounts, their_accounts = (_rows(conn, s, "wealth_account", acc_cols, "account_id") for s in ("main", "src"))
            movements, their_movements = (_rows(conn, s, "wealth_movement", mov_cols, "uid") for s in ("main", "src"))
            deleted = {(k, u): d for k, u, d in conn.execute("SELECT kind, uid, deleted_at FROM main.wealth_deleted")}
            their_deleted = {(k, u): d for k, u, d in conn.execute("SELECT kind, uid, deleted_at FROM src.wealth_deleted")}

            out["duplicates"] = _unify_duplicates(conn, movements, their_movements, deleted, their_deleted)

            # 1) comptes : suppressions faites là-bas, puis leurs versions
            for (kind, aid), when in sorted(their_deleted.items()):
                if kind != "account":
                    continue
                if aid in accounts and _activity(accounts[aid], movements) <= when:
                    gone = [m for m in movements.values() if m["account_id"] == aid]
                    lost.append({"why": "compte supprimé sur l'autre PC", "account": accounts.pop(aid), "movements": gone})
                    for m in gone:
                        movements.pop(m["uid"])
                    conn.execute("DELETE FROM main.wealth_movement WHERE account_id = ?", (aid,))
                    conn.execute("DELETE FROM main.wealth_account WHERE account_id = ?", (aid,))
                    out["accounts_deleted"] += 1
                if aid not in accounts:
                    _set_tombstone(conn, "account", aid, when, deleted)
            for aid, row in sorted(their_accounts.items()):
                if aid in accounts:
                    if not _wins(row, accounts[aid]):
                        continue
                    if _apply(conn, "wealth_account", "account_id", row, accounts[aid], lost,
                              "compte modifié plus récemment sur l'autre PC", "account"):
                        out["accounts_updated"] += 1
                else:
                    if ("account", aid) in deleted:
                        if _activity(row, their_movements) <= deleted[("account", aid)]:
                            continue                       # supprimé ici après sa dernière modification là-bas
                        _forget_tombstone(conn, "account", aid, deleted)
                    _insert(conn, "wealth_account", row)
                    out["accounts_added"] += 1
                accounts[aid] = row

            # 2) mouvements : suppressions faites là-bas, puis leurs versions
            for (kind, uid), when in sorted(their_deleted.items()):
                if kind != "movement":
                    continue
                if uid in movements and (movements[uid].get("updated_at") or "") <= when:
                    lost.append({"why": "mouvement supprimé sur l'autre PC", "movement": movements.pop(uid)})
                    conn.execute("DELETE FROM main.wealth_movement WHERE uid = ?", (uid,))
                    out["movements_deleted"] += 1
                if uid not in movements:
                    _set_tombstone(conn, "movement", uid, when, deleted)
            for uid, row in sorted(their_movements.items()):
                if row["account_id"] not in accounts:
                    continue                               # son compte a été supprimé ici, et la suppression l'emporte
                if uid in movements:
                    if not _wins(row, movements[uid]):
                        continue
                    if _apply(conn, "wealth_movement", "uid", row, movements[uid], lost,
                              "mouvement modifié plus récemment sur l'autre PC", "movement"):
                        out["movements_updated"] += 1
                else:
                    if ("movement", uid) in deleted:
                        if (row.get("updated_at") or "") <= deleted[("movement", uid)]:
                            continue
                        _forget_tombstone(conn, "movement", uid, deleted)
                    _insert(conn, "wealth_movement", row)
                    out["movements_added"] += 1
                movements[uid] = row

            # Un compte fictif cloné d'un compte supprimé ne garde pas un lien mort (ON DELETE SET NULL, comme partout ailleurs).
            conn.execute("UPDATE main.wealth_account SET source_account_id = NULL WHERE source_account_id IS NOT NULL "
                         "AND source_account_id NOT IN (SELECT account_id FROM main.wealth_account)")
            orphans = conn.execute("PRAGMA main.foreign_key_check(wealth_movement)").fetchall()
            if orphans:
                raise WealthShareError(f"Patrimoine fusionné incohérent ({len(orphans)} mouvement(s) sans compte) : rien n'est écrit.")
            out["backup"] = _write_backup(lost, backup_dir, "fusion")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return out
    finally:
        conn.close()


def adopt_wealth(db_path: str, incoming: str | Path, *, backup_dir: str | Path | None = None) -> dict:
    """Remplace le patrimoine de `db_path` par celui du fichier `incoming` (passage à la fusion d'un PC qui suivait le
    PC de référence : sa copie n'a pas les traces des suppressions faites depuis sa dernière adoption, une fusion les
    ressusciterait). L'ancien est sauvegardé en JSON. Renvoie `{"accounts", "movements", "backup"}`."""
    backup_dir = backup_dir or paths.backups_dir()
    conn = _open(db_path, incoming)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            before = {table: [dict(zip(_columns(conn, "main", table), r))
                              for r in conn.execute(f'SELECT * FROM main."{table}"')] for table in TABLES}
            for table in reversed(TABLES):
                conn.execute(f'DELETE FROM main."{table}"')
            for table in TABLES:
                cols = _csv(_shared_columns(conn, table))
                conn.execute(f'INSERT INTO main."{table}" ({cols}) SELECT {cols} FROM src."{table}"')
            if conn.execute("PRAGMA main.foreign_key_check(wealth_movement)").fetchall():
                raise WealthShareError("Patrimoine du partage incohérent (mouvements sans compte) : rien n'est écrit.")
            backup = _write_backup([before] if any(before.values()) else [], backup_dir, "adoption")
            out = {"accounts": conn.execute("SELECT COUNT(*) FROM main.wealth_account").fetchone()[0],
                   "movements": conn.execute("SELECT COUNT(*) FROM main.wealth_movement").fetchone()[0],
                   "backup": backup}
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return out
    finally:
        conn.close()
