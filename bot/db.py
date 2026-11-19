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
CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, app TEXT, name TEXT,
  current_vid INTEGER, created INTEGER, updated INTEGER, UNIQUE(user_id, app)
);
CREATE TABLE IF NOT EXISTS versions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER, seq INTEGER, label TEXT,
  sha256 TEXT, size INTEGER, filename TEXT, file_id TEXT, store TEXT, store_chat INTEGER, store_msg INTEGER,
  changelog TEXT, no_rollback_before TEXT, destructive INTEGER DEFAULT 0,
  created INTEGER, published INTEGER
);
CREATE INDEX IF NOT EXISTS idx_versions_project ON versions(project_id, seq);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, text TEXT, file_id TEXT,
  reply_to INTEGER, status TEXT DEFAULT 'open', starred INTEGER DEFAULT 0, note TEXT,
  notify TEXT DEFAULT '{}', created INTEGER, answered_at INTEGER, closed_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id, created);
CREATE TABLE IF NOT EXISTS feedback_replies (
  id INTEGER PRIMARY KEY AUTOINCREMENT, feedback_id INTEGER, admin_id INTEGER, text TEXT, photo TEXT,
  mids TEXT DEFAULT '[]', retracted INTEGER DEFAULT 0, created INTEGER
);
CREATE TABLE IF NOT EXISTS fb_quick (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, text TEXT, uses INTEGER DEFAULT 0);
"""
MIGRATIONS = [
    "ALTER TABLE deploys ADD COLUMN kind TEXT DEFAULT 'publish'",
    "ALTER TABLE deploys ADD COLUMN version_id INTEGER",
    "ALTER TABLE users ADD COLUMN blocked_at INTEGER",
    "ALTER TABLE projects ADD COLUMN slug TEXT DEFAULT ''",
    "ALTER TABLE projects ADD COLUMN token_enc TEXT",
    "ALTER TABLE projects ADD COLUMN access TEXT DEFAULT 'none'",  # none | saved | lost
    "ALTER TABLE projects ADD COLUMN access_at INTEGER",
]


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(Path(config.DATA_DIR) / "builder-hub.db", check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(SCHEMA)
        for m in MIGRATIONS:
            try:
                _conn.execute(m)
            except sqlite3.OperationalError:
                pass        # ya estaba
        _conn.commit()
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
    now = int(time.time())
    run("""INSERT INTO users(id,blocked,created,blocked_at) VALUES(?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET blocked=excluded.blocked, blocked_at=excluded.blocked_at""",
        (uid, int(blocked), now, now if blocked else None))


def blocked_list():
    return q("SELECT id, name, username FROM users WHERE blocked=1 ORDER BY blocked_at DESC, id LIMIT 100")


# ── despliegues (sin tokens)
def deploy_start(uid: int, app: str, kind: str = "publish") -> int:
    return run("INSERT INTO deploys(user_id,app,status,created,kind) VALUES(?,?,?,?,?)", (uid, app, "started", int(time.time()), kind))


def deploy_version(did: int, vid: int) -> None:
    run("UPDATE deploys SET version_id=? WHERE id=?", (vid, did))


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


# ── proyectos y versiones (sin tokens: solo el ID público de la app)
def project_get(pid: int):
    return q("SELECT * FROM projects WHERE id=?", (pid,), one=True)


def project_by_app(uid: int, app: str):
    return q("SELECT * FROM projects WHERE user_id=? AND app=?", (uid, app), one=True)


def project_upsert(uid: int, app: str, name: str) -> dict:
    now = int(time.time())
    run("""INSERT INTO projects(user_id,app,name,created,updated) VALUES(?,?,?,?,?)
           ON CONFLICT(user_id,app) DO UPDATE SET updated=excluded.updated,
           name=CASE WHEN excluded.name<>'' THEN excluded.name ELSE projects.name END""", (uid, app, name or "", now, now))
    return project_by_app(uid, app)


def project_set_current(pid: int, vid: int) -> None:
    run("UPDATE projects SET current_vid=?, updated=? WHERE id=?", (vid, int(time.time()), pid))


def projects_of(uid: int):
    return q("""SELECT p.*, v.label cur_label, (SELECT count(*) FROM versions x WHERE x.project_id=p.id) n
                FROM projects p LEFT JOIN versions v ON v.id=p.current_vid
                WHERE p.user_id=? ORDER BY p.updated DESC LIMIT 30""", (uid,))


def versions_of(pid: int):
    return q("SELECT * FROM versions WHERE project_id=? ORDER BY seq", (pid,))


def version_get(vid: int):
    return q("SELECT * FROM versions WHERE id=?", (vid,), one=True)


def version_by_sha(pid: int, sha: str):
    return q("SELECT * FROM versions WHERE project_id=? AND sha256=? ORDER BY seq DESC LIMIT 1", (pid, sha), one=True)


def version_add(pid: int, **v) -> int:
    seq = (q("SELECT max(seq) m FROM versions WHERE project_id=?", (pid,), one=True)["m"] or 0) + 1
    now = int(time.time())
    return run("""INSERT INTO versions(project_id,seq,label,sha256,size,filename,file_id,store,store_chat,store_msg,
                  changelog,no_rollback_before,destructive,created,published) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (pid, seq, v.get("label") or f"#{seq}", v["sha256"], v.get("size", 0), v.get("filename", ""), v["file_id"],
                v.get("store", "chat"), v.get("store_chat"), v.get("store_msg"), v.get("changelog", ""),
                v.get("no_rollback_before", ""), int(bool(v.get("destructive"))), now, now))


def version_touch(vid: int, destructive: bool = False) -> None:
    run("UPDATE versions SET published=?, destructive=MAX(destructive,?) WHERE id=?", (int(time.time()), int(destructive), vid))


def version_store(vid: int, store: str, file_id: str, chat: int | None, msg: int | None) -> None:
    run("UPDATE versions SET store=?, file_id=?, store_chat=?, store_msg=? WHERE id=?", (store, file_id, chat, msg, vid))


def slug(name: str) -> str:
    import re
    return re.sub(r"[^0-9a-z]+", "", (name or "").lower())


def project_set_slug(pid: int, name: str) -> None:
    if slug(name):
        run("UPDATE projects SET slug=? WHERE id=?", (slug(name), pid))


def projects_matching(uid: int, name: str):
    s = slug(name)
    return q("SELECT * FROM projects WHERE user_id=? AND slug=? AND slug<>'' ORDER BY updated DESC", (uid, s)) if s else []


def project_save_token(pid: int, enc: str) -> None:
    run("UPDATE projects SET token_enc=?, access='saved', access_at=? WHERE id=?", (enc, int(time.time()), pid))


def project_forget_token(pid: int) -> None:
    run("UPDATE projects SET token_enc=NULL, access='none', access_at=? WHERE id=?", (int(time.time()), pid))


def project_access_lost(pid: int) -> None:
    run("UPDATE projects SET token_enc=NULL, access='lost', access_at=? WHERE id=?", (int(time.time()), pid))


def project_history(uid: int, app: str, limit: int = 20):
    return q("""SELECT d.*, v.label FROM deploys d LEFT JOIN versions v ON v.id=d.version_id
                WHERE d.user_id=? AND d.app=? ORDER BY d.id DESC LIMIT ?""", (uid, app, limit))


def project_delete(uid: int, pid: int) -> dict:
    """Borra el proyecto, sus versiones, su historial y su acceso. Devuelve las copias del canal a borrar."""
    p = project_get(pid)
    if not p or p["user_id"] != uid:
        return {}
    vs = versions_of(pid)
    copies = [(v["store_chat"], v["store_msg"]) for v in vs if v["store"] == "channel" and v["store_chat"] and v["store_msg"]]
    n_dep = q("SELECT count(*) n FROM deploys WHERE user_id=? AND app=?", (uid, p["app"]), one=True)["n"]
    run("DELETE FROM versions WHERE project_id=?", (pid,))
    run("DELETE FROM deploys WHERE user_id=? AND app=?", (uid, p["app"]))
    run("DELETE FROM projects WHERE id=?", (pid,))
    return {"name": p["name"] or p["app"], "app": p["app"], "versions": len(vs), "deploys": n_dep, "copies": copies}
