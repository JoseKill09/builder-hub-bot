"""SQLite sencillo. NUNCA se guardan tokens: de cada despliegue solo el ID público de la app (app123…)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from . import config

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT, username TEXT, lang TEXT,
  blocked INTEGER DEFAULT 0, created INTEGER, last_seen INTEGER
);
CREATE TABLE IF NOT EXISTS deploys (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, app TEXT, status TEXT,
  summary TEXT, error TEXT, created INTEGER, finished INTEGER
);
CREATE INDEX IF NOT EXISTS idx_deploys_user ON deploys(user_id, created);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(Path(config.DATA_DIR) / "builder-hub.db", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
    return _conn


def q(sql: str, args=(), one=False):
    with _lock:
        cur = conn().execute(sql, args)
        rows = [dict(r) for r in cur.fetchall()]
        conn().commit()
    return (rows[0] if rows else None) if one else rows


def run(sql: str, args=()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        conn().commit()
        return cur.lastrowid


# ── ajustes
def setting(key: str):
    row = q("SELECT value FROM settings WHERE key=?", (key,), one=True)
    return json.loads(row["value"]) if row else config.DEFAULTS.get(key)


def set_setting(key: str, value) -> None:
    run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))


# ── usuarios
def touch_user(u) -> dict:
    now = int(time.time())
    name = " ".join(x for x in (u.first_name, u.last_name) if x) or (u.username or str(u.id))
    lang = (u.language_code or "en")[:2]
    run("""INSERT INTO users(id,name,username,lang,created,last_seen) VALUES(?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username, last_seen=excluded.last_seen""",
        (u.id, name, u.username, lang, now, now))
    return q("SELECT * FROM users WHERE id=?", (u.id,), one=True)


def get_user(uid: int):
    return q("SELECT * FROM users WHERE id=?", (uid,), one=True)


def set_lang(uid: int, lang: str) -> None:
    run("UPDATE users SET lang=? WHERE id=?", (lang, uid))


def set_blocked(uid: int, blocked: bool) -> None:
    run("INSERT INTO users(id,blocked,created) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET blocked=excluded.blocked",
        (uid, int(blocked), int(time.time())))


def blocked_list():
    return q("SELECT id, name, username FROM users WHERE blocked=1 ORDER BY id")


# ── despliegues (sin tokens)
def deploy_start(uid: int, app: str) -> int:
    return run("INSERT INTO deploys(user_id,app,status,created) VALUES(?,?,?,?)", (uid, app, "started", int(time.time())))


def deploy_finish(did: int, status: str, summary: dict | None = None, error: str = "") -> None:
    run("UPDATE deploys SET status=?, summary=?, error=?, finished=? WHERE id=?",
        (status, json.dumps(summary or {}, ensure_ascii=False), error[:2000], int(time.time()), did))


def deploys_today(uid: int) -> int:
    since = int(time.time()) - 86400
    return q("SELECT count(*) n FROM deploys WHERE user_id=? AND created>=? AND status='published'", (uid, since), one=True)["n"]


def my_deploys(uid: int, limit: int = 10):
    return q("SELECT * FROM deploys WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit))


def stats() -> dict:
    week = int(time.time()) - 7 * 86400
    one = lambda sql, a=(): q(sql, a, one=True)["n"]  # noqa: E731
    return {
        "users": one("SELECT count(*) n FROM users"),
        "active7": one("SELECT count(*) n FROM users WHERE last_seen>=?", (week,)),
        "blocked": one("SELECT count(*) n FROM users WHERE blocked=1"),
        "published7": one("SELECT count(*) n FROM deploys WHERE status='published' AND created>=?", (week,)),
        "failed7": one("SELECT count(*) n FROM deploys WHERE status IN ('failed','invalid') AND created>=?", (week,)),
        "apps": one("SELECT count(DISTINCT app) n FROM deploys WHERE status='published'"),
    }
