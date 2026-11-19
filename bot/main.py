"""Builder Hub: bot mensajero que publica proyectos de Telegram Serverless.

Flujos:
- 🚀 Publicar → token (se borra el mensaje) → ZIP → revisión → ✅ Publicar.
- ZIP directo al chat → novedades → token → revisión (novedades + cambios) → ✅ Actualizar / ✖️ Cancelar.
- 🗂 Mis proyectos → versiones → ⬅️ anterior / ➡️ siguiente / ↩️ restaurar (con anti-rollback) / 📥 descargar.
El token vive solo en memoria (dentro del Job) y se olvida al terminar, cancelar o caducar.
Los ZIP del chat no se borran nunca: solo se borra el mensaje que trae un token.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import __version__, backup, brand, config, contact, db, vault
from . import versions as V
from .deploy import cli as C
from .deploy.job import DeployError, Job
from .i18n import lang_of, t
from .jobqueue import FairQueue
from .ui import Screen, edit, esc, send

BOT_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")


class MaskSecrets(logging.Filter):
    """Ningún token (de Serverless o de la Bot API) llega a los registros."""

    def filter(self, record):
        msg = record.getMessage()
        clean = BOT_TOKEN_RE.sub("<bot-token>", C.mask(msg))
        if clean != msg:
            record.msg, record.args = clean, ()
        return True


logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
for h in logging.getLogger().handlers:
    h.addFilter(MaskSecrets())
logging.getLogger("httpx").setLevel(logging.WARNING)   # sus líneas llevan el token del bot en la URL
log = logging.getLogger("builder-hub")

CLI = C.Cli(config.TGCLOUD_BIN)
JOBQ = FairQueue(lambda: max(1, min(4, int(db.setting("parallel") or config.MAX_PARALLEL))))
SESSIONS: dict[int, dict] = {}     # uid → {kind, step, msg, lang, timer, job, zip, restore, ctx, did, busy}
ADMIN_WAIT: dict[int, str] = {}
CONTACT_CMDS = {"ct", "ctk", "fm", "fu", "fur", "fb", "fv", "fr", "fn", "fq", "fqs", "fc", "fcn", "fo", "fs", "frx",
                "fbn", "fub", "fql", "fqa", "fqd", "fbl"}


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def B(t_, d=None, **kw):
    b = {"t": t_, **kw}
    if d:
        b["d"] = d
    return b


def vlabel(label: str | None) -> str:
    if not label:
        return "—"
    return f"v{label}" if V.vkey(label) is not None else label


def hashtag(name: str, app: str) -> str:
    tag = re.sub(r"[^\w]+", "_", (name or "").lower()).strip("_")
    return "#" + (tag or app)


def fdate(ts) -> str:
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts or 0))


# ───────────── sesiones ─────────────
def _drop_zip(s: dict) -> None:
    z = s.get("zip") or {}
    if z.get("path"):
        Path(z["path"]).unlink(missing_ok=True)
        z["path"] = None


def end_session(uid: int, status: str | None = None) -> None:
    s = SESSIONS.pop(uid, None)
    if not s:
        return
    if s.get("timer"):
        s["timer"].cancel()
    for k in ("job", "pending_job"):
        if s.get(k):
            s[k].cleanup()
    _drop_zip(s)
    if status and s.get("did") and status != "keep":
        db.deploy_finish(s["did"], status)


async def _expire(app: Application, uid: int, lang: str) -> None:
    await asyncio.sleep(config.JOB_TTL)
    s = SESSIONS.get(uid)
    if not s or s.get("busy"):
        return
    end_session(uid, "expired")
    try:
        await send(app.bot, uid, Screen().h("⌛", "Builder Hub").p(t(lang, "expired")).row(B(t(lang, "btn_menu"), "m")))
    except Exception:  # noqa: BLE001
        pass


def new_session(app: Application, uid: int, lang: str, msg: int | None) -> dict:
    s = {"kind": "publish", "step": "token", "msg": msg, "lang": lang, "job": None, "zip": None, "restore": None,
         "ctx": None, "did": None, "busy": False, "expect": None, "remember": True, "saved": False, "pending_job": None,
         "timer": asyncio.create_task(_expire(app, uid, lang))}
    SESSIONS[uid] = s
    return s


def over_limit(uid: int) -> bool:
    return not is_admin(uid) and db.deploys_today(uid) >= int(db.setting("daily_limit"))


def queue_notice(bot, uid: int, s: dict):
    """Avisa de la posición en la cola editando el mensaje de estado."""
    async def cb(n: int) -> None:
        if n > 0:
            s["msg"] = await edit(bot, uid, s.get("msg"), Screen().h("⏳", "Builder Hub").p(t(s["lang"], "queued", n=n)))
    return cb


# ───────────── pantallas ─────────────
def home(lang: str, uid: int) -> Screen:
    s = (Screen().h("🚀", t(lang, "home_title")).p(t(lang, "home_intro"))
         .ul([f"{i}. {x}" for i, x in enumerate(t(lang, "home_steps"), 1)]).p(t(lang, "home_update")))
    s.row(B(t(lang, "btn_deploy"), "dep", style="primary"))
    s.row(B(t(lang, "btn_history"), "hist"), B(t(lang, "btn_format"), "fmt"))
    s.row(B(t(lang, "btn_contact"), "ct"), B(t(lang, "btn_help"), "help"))
    s.row(B(t(lang, "btn_lang"), "lang"), B(t(lang, "btn_admin"), "adm") if is_admin(uid) else None)
    return s.foot(f"Builder Hub {__version__}")


def format_screen(lang: str) -> Screen:
    return (Screen().h("📦", t(lang, "format_title")).p(t(lang, "format")).pre(t(lang, "format_tree"))
            .ul(list(t(lang, "format_rules")) + [t(lang, "format_meta")]).p(t(lang, "format_ai"))
            .row(B(t(lang, "btn_prompt"), "prompt"))
            .row(B("📄 FORMAT.md", url=config.REPO_URL + "/blob/main/docs/FORMAT.md"), B("📚 Handbook", url=config.HANDBOOK_URL))
            .row(B(t(lang, "btn_back"), "m")))


def help_screen(lang: str) -> Screen:
    return Screen().h("🔒", t(lang, "help_title")).ul(t(lang, "help")).row(B("GitHub", url=config.REPO_URL), B(t(lang, "btn_back"), "m"))


def log_screen(lang: str, uid: int) -> Screen:
    rows = db.my_deploys(uid, 15)
    s = Screen().h("🧾", t(lang, "log_title"))
    if not rows:
        s.p(t(lang, "history_none"))
    else:
        def st(r):
            if r["status"] == "published" and r.get("kind") == "restore":
                return t(lang, "st_restored")
            return t(lang, "st_" + r["status"])
        s.ul([f"{time.strftime('%d/%m %H:%M', time.localtime(r['created']))} · <code>{esc(r['app'])}</code> · {st(r)}" for r in rows])
    return s.row(B(t(lang, "btn_back"), "hist"))


def md(text: str) -> str:
    """Markdown mínimo de los CHANGELOG (negrita y código) a HTML, ya escapado."""
    s = esc(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", s)


def novelty_lines(blocks: list[tuple[str, str]]) -> list[str]:
    out = []
    for _, b in blocks:
        head, lines = V.block_lines(b)
        out.append(f"<b>{esc(head)}</b>")
        out += [md(x) for x in lines]
    return out


def _vdicts(vs: list[dict]) -> list[dict]:
    return [{"seq": v["seq"], "label": v["label"], "no_rollback_before": v["no_rollback_before"],
             "destructive": v["destructive"], "id": v["id"]} for v in vs]


def projects_screen(lang: str, uid: int) -> Screen:
    rows = db.projects_of(uid)
    s = Screen().h("🗂", t(lang, "projects_title"))
    if not rows:
        s.p(t(lang, "projects_none"))
    else:
        s.p(t(lang, "projects_intro"))
        for p in rows:
            s.row(B(f"🤖 {p['name'] or p['app']} · {vlabel(p['cur_label'])}", f"pv:{p['id']}"))
    return s.row(B(t(lang, "btn_log"), "hlog"), B(t(lang, "btn_back"), "m"))


def project_screen(lang: str, uid: int, pid: int) -> Screen:
    p = db.project_get(pid)
    if not p or p["user_id"] != uid:
        return Screen().h("⚠️", t(lang, "not_yours")).row(B(t(lang, "btn_back"), "hist"))
    vs = db.versions_of(pid)
    cur = next((v for v in vs if v["id"] == p["current_vid"]), None)
    floor, floor_seq = V.floor_of(_vdicts(vs), cur["seq"] if cur else None)
    s = (Screen().h("🤖", esc(p["name"] or p["app"]))
         .p(t(lang, "proj_info", app=esc(p["app"]), cur=esc(vlabel(cur["label"]) if cur else t(lang, "proj_none_cur")), n=len(vs))))
    acc = p.get("access") or "none"
    s.p(t(lang, "acc_saved") if acc == "saved" else t(lang, "acc_lost", date=fdate(p.get("access_at"))) if acc == "lost" else t(lang, "acc_none"))
    if floor:
        s.p(t(lang, "ar_floor", floor=esc(vlabel(floor))))
    lines = []
    for v in reversed(vs[-10:]):
        flags = t(lang, "flag_channel") if v["store"] == "channel" else t(lang, "flag_chat")
        if v["destructive"]:
            flags += t(lang, "flag_loss")
        if floor_seq is not None and v["seq"] < floor_seq:
            flags += t(lang, "flag_floor")
        mark = "▶️" if cur and v["id"] == cur["id"] else "▫️"
        lines.append(t(lang, "v_line", mark=mark, label=esc(vlabel(v["label"])), date=fdate(v["created"]), flags=flags))
    if lines:
        s.ul(lines).foot(t(lang, "legend"))
    for v in reversed(vs[-5:]):
        bl = V.own_block(v["changelog"] or "", v["label"])
        if bl:
            s.details(f"📖 {esc(vlabel(v['label']))}", novelty_lines(bl))
    if cur:
        prev = next((v for v in reversed(vs) if v["seq"] < cur["seq"]), None)
        nxt = next((v for v in vs if v["seq"] > cur["seq"]), None)
        row = []
        if prev:
            rb = V.rollback_check(_vdicts(vs), cur["seq"], prev["label"], prev["seq"])
            row.append(B(t(lang, "btn_locked", v=vlabel(prev["label"])), f"vv:{prev['id']}") if not rb.ok
                       else B(t(lang, "btn_prev", v=vlabel(prev["label"])), f"pr:{prev['id']}"))
        if nxt:
            row.append(B(t(lang, "btn_next", v=vlabel(nxt["label"])), f"pr:{nxt['id']}"))
        s.row(*row)
    others = list(reversed(vs[-6:]))
    for i in range(0, len(others), 3):
        s.row(*[B(("▶️ " if cur and v["id"] == cur["id"] else "") + vlabel(v["label"]), f"vv:{v['id']}") for v in others[i:i + 3]])
    s.row(B(t(lang, "btn_upd_this"), f"pu:{pid}", style="primary"), B(t(lang, "btn_dl_cur"), f"pd:{cur['id']}") if cur else None)
    s.row(B(t(lang, "btn_proj_hist"), f"ph:{pid}"), B(t(lang, "btn_forget"), f"pfa:{pid}") if acc == "saved" else None)
    s.row(B(t(lang, "btn_delete"), f"pdel:{pid}", style="danger"))
    return s.row(B(t(lang, "btn_back"), "hist"))


def project_history_screen(lang: str, uid: int, pid: int) -> Screen:
    p = db.project_get(pid)
    if not p or p["user_id"] != uid:
        return Screen().h("⚠️", t(lang, "not_yours")).row(B(t(lang, "btn_back"), "hist"))
    rows = db.project_history(uid, p["app"])
    s = Screen().h("🧾", t(lang, "hist_title", name=esc(p["name"] or p["app"])))
    if not rows:
        s.p(t(lang, "hist_none"))
    else:
        def st(r):
            if r["status"] == "published" and r.get("kind") == "restore":
                return t(lang, "st_restored")
            return t(lang, "st_" + r["status"]) if r["status"] else ""
        s.ul([f"{fdate(r['created'])} · {st(r)}" + (f" · <b>{esc(vlabel(r['label']))}</b>" if r.get("label") else "") for r in rows])
    return s.row(B(t(lang, "btn_back"), f"pv:{pid}"))


def own_version(uid: int, vid: int):
    v = db.version_get(vid)
    if not v:
        return None, None
    p = db.project_get(v["project_id"])
    if not p or p["user_id"] != uid:
        return None, None
    return v, p


def version_screen(lang: str, uid: int, vid: int) -> Screen:
    v, p = own_version(uid, vid)
    if not v:
        return Screen().h("⚠️", t(lang, "not_yours")).row(B(t(lang, "btn_back"), "hist"))
    vs = db.versions_of(p["id"])
    cur = next((x for x in vs if x["id"] == p["current_vid"]), None)
    s = (Screen().h("🏷", t(lang, "v_title", label=esc(vlabel(v["label"]))))
         .p(t(lang, "v_info", name=esc(p["name"] or p["app"]), date=fdate(v["created"]), sha=v["sha256"][:16] + "…")))
    can = True
    if cur and v["id"] == cur["id"]:
        s.p(t(lang, "v_current"))
        can = False
    elif cur:
        rb = V.rollback_check(_vdicts(vs), cur["seq"], v["label"], v["seq"])
        if not rb.ok:
            s.p(t(lang, "ar_blocked", floor=esc(vlabel(rb.floor)), by=", ".join(esc(vlabel(x)) for x in rb.blocked)))
            can = False
        elif rb.data_loss:
            s.p(t(lang, "ar_loss", labels=", ".join(esc(vlabel(x)) for x in rb.data_loss)))
        if v["seq"] < cur["seq"]:
            lose = V.changelog_between(cur["changelog"] or "", v["label"], cur["label"])
            if lose:
                s.details(t(lang, "undo", n=len(lose)), novelty_lines(lose))
    bl = V.own_block(v["changelog"] or "", v["label"])
    if bl:
        s.details(t(lang, "novelties", n=len(bl)), novelty_lines(bl), open_=True)
    if can:
        s.row(B(t(lang, "btn_restore", v=vlabel(v["label"])), f"pr:{v['id']}", style="primary"))
    return s.row(B(t(lang, "btn_dl"), f"pd:{v['id']}")).row(B(t(lang, "btn_back"), f"pv:{p['id']}"))


def admin_screen(lang: str) -> Screen:
    st = db.stats()
    ch = backup.channel()
    return (Screen().h("🛡", t(lang, "admin_title")).p(esc(t(lang, "admin_stats", **st)))
            .kv([(t(lang, "admin_open"), t(lang, "yes") if db.setting("open") else t(lang, "no")),
                 (t(lang, "admin_zip"), f"{db.setting('max_zip_mb')} MB"),
                 (t(lang, "admin_daily"), str(db.setting("daily_limit"))),
                 (t(lang, "admin_parallel"), str(JOBQ.limit())),
                 (t(lang, "admin_queue"), t(lang, "admin_queue_val", a=JOBQ.active, w=len(JOBQ.waiting))),
                 (t(lang, "admin_backup"), t(lang, "admin_backup_chat", id=ch) if ch else t(lang, "admin_backup_none")),
                 (t(lang, "admin_contact"), t(lang, "yes") if db.setting("contact_open") else t(lang, "no"))])
            .row(B(t(lang, "btn_support", n=contact.open_count()), "fb:open", style="primary"))
            .row(B(t(lang, "btn_toggle_open"), "ao"), B(t(lang, "btn_toggle_contact"), "aco"))
            .row(B(t(lang, "btn_zip"), "az"), B(t(lang, "btn_daily"), "ad"), B(t(lang, "btn_parallel"), "ap"))
            .row(B(t(lang, "btn_backup"), "ach"), B(t(lang, "btn_backup_off"), "achx") if ch else None)
            .row(B(t(lang, "btn_block"), "ab"), B(t(lang, "btn_unblock"), "au"))
            .row(B(t(lang, "btn_brand"), "abrand"))
            .row(B(t(lang, "btn_back"), "m")))


def ask_token_screen(lang: str, s: dict) -> Screen:
    z = s.get("zip")
    if s["kind"] == "restore" and z:
        return (Screen().h("🔑", t(lang, "ask_token_title")).p(t(lang, "rst_ready", label=esc(vlabel(z["meta"].version))))
                .quote(t(lang, "ask_token_safe")).row(B(t(lang, "btn_cancel"), "cancel")))
    exp = s.get("expect")
    if z:
        meta: V.Meta = z["meta"]
        ver = f" · {esc(vlabel(meta.version))}" if meta.version else ""
        sc = Screen().h("📦", t(lang, "ask_token_title_zip"))
        if exp:
            sc.p(t(lang, "for_project", name=esc(exp["name"]), app=esc(exp["app"])))
        else:
            sc.p(t(lang, "zip_received", name=esc(meta.name or z["name"]), ver=ver))
        bl = V.changelog_since(meta.changelog, None)
        if bl:
            sc.details(t(lang, "novelties", n=len(bl)), novelty_lines(bl))
        return sc.quote(t(lang, "ask_token_safe")).p(t(lang, "zip_kept")).row(B(t(lang, "btn_cancel"), "cancel"))
    if exp:
        return (Screen().h("📦", exp["name"]).p(t(lang, "upd_this", name=esc(exp["name"]))).row(B(t(lang, "btn_cancel"), "cancel")))
    return (Screen().h("🔑", t(lang, "ask_token_title")).p(t(lang, "ask_token"))
            .quote(t(lang, "ask_token_safe")).row(B(t(lang, "btn_cancel"), "cancel")))


def build_ctx(uid: int, s: dict, job: Job) -> dict:
    """Contexto de la revisión: proyecto, versión publicada, novedades y anti-rollback."""
    z = s["zip"]
    meta: V.Meta = z["meta"]
    proj = db.project_by_app(uid, job.app)
    vs = db.versions_of(proj["id"]) if proj else []
    cur = next((v for v in vs if proj and v["id"] == proj["current_vid"]), None)
    ctx = {"name": meta.name or (proj["name"] if proj else "") or job.app, "label": meta.version, "cur": cur,
           "same_sha": None, "same_label": False, "rb": V.Rollback(), "novel": [], "lose": []}
    if s["kind"] == "restore":
        tv = db.version_get(s["restore"]["vid"])
        ctx["name"] = (proj["name"] if proj else "") or ctx["name"]
        ctx["label"] = tv["label"]
        if cur:
            ctx["rb"] = V.rollback_check(_vdicts(vs), cur["seq"], tv["label"], tv["seq"])
            if tv["seq"] < cur["seq"]:
                ctx["lose"] = V.changelog_between(cur["changelog"] or "", tv["label"], cur["label"])
            else:
                ctx["novel"] = V.changelog_since(tv["changelog"] or "", cur["label"])
        return ctx
    if cur:
        ctx["same_sha"] = db.version_by_sha(proj["id"], z["sha"])
        ctx["same_label"] = bool(meta.version and meta.version == cur["label"] and cur["sha256"] != z["sha"])
        ctx["rb"] = V.rollback_check(_vdicts(vs), cur["seq"], meta.version) if meta.version else V.Rollback()
        if ctx["rb"].downgrade:
            ctx["lose"] = V.changelog_between(cur["changelog"] or "", meta.version, cur["label"])
        else:
            ctx["novel"] = V.changelog_since(meta.changelog, cur["label"])
    else:
        ctx["novel"] = V.changelog_since(meta.changelog, None)
    return ctx


def plan_screen(lang: str, s: dict) -> Screen:
    job: Job = s["job"]
    ctx = s["ctx"]
    p = job.plan
    st, sp, rep = p.status, p.schema, p.report
    cur = ctx["cur"]
    name, new = esc(ctx["name"]), esc(vlabel(ctx["label"]) if ctx["label"] else "")
    if s["kind"] == "restore":
        sc = Screen().h("↩️", t(lang, "rst_title", name=name, cur=esc(vlabel(cur["label"]) if cur else "—"), new=new))
    elif cur:
        sc = Screen().h("🔄", t(lang, "upd_title", name=name, cur=esc(vlabel(cur["label"])), new=new or "?"))
    else:
        sc = Screen().h("🆕", t(lang, "new_title", name=name, new=new))
    rb: V.Rollback = ctx["rb"]
    blocked = not rb.ok
    if rb.downgrade and s["kind"] != "restore" and cur:
        sc.p(t(lang, "downgrade", new=new, cur=esc(vlabel(cur["label"]))))
    if blocked:
        sc.p(t(lang, "ar_blocked", floor=esc(vlabel(rb.floor)), by=", ".join(esc(vlabel(x)) for x in rb.blocked)))
    if rb.downgrade and sp.manual:
        sc.p(t(lang, "ar_manual", list=esc("; ".join(sp.manual[:4]))))
        blocked = True
    if rb.data_loss:
        sc.p(t(lang, "ar_loss", labels=", ".join(esc(vlabel(x)) for x in rb.data_loss)))
    if ctx["same_label"]:
        sc.p(t(lang, "same_label", v=new))
    if ctx["same_sha"] and cur and ctx["same_sha"]["id"] == cur["id"]:
        sc.p(t(lang, "same_sha"))
    if ctx["novel"]:
        sc.details(t(lang, "novelties", n=len(ctx["novel"])), novelty_lines(ctx["novel"]), open_=len(ctx["novel"]) == 1)
    elif s["kind"] != "restore" and not s["zip"]["meta"].changelog:
        sc.p(t(lang, "novelties_none"))
    if ctx["lose"]:
        sc.details(t(lang, "undo", n=len(ctx["lose"])), novelty_lines(ctx["lose"]))
    sc.h("🔎", t(lang, "plan_title"))
    if p.nothing_to_do:
        sc.p(t(lang, "plan_nothing"))
    nw, mod = len(st.new), len(st.modified)
    same = max(0, len(rep.modules) - nw - mod)
    sc.p(t(lang, "plan_modules", new=nw, mod=mod, same=same))
    if st.deleted:
        sc.quote(t(lang, "plan_deleted", n=len(st.deleted)) + "\n" + "\n".join(f"<code>{esc(x)}</code>" for x in st.deleted[:12])
                 + ("\n…" if len(st.deleted) > 12 else ""))
    if st.static_lines:
        sc.p(t(lang, "plan_static", n=len(st.static_lines)))
    if p.unmanaged_static:
        sc.p(t(lang, "plan_static_unmanaged"))
    if sp.safe:
        sc.p(t(lang, "plan_tables_new", n=len(sp.safe)))
    if sp.destructive:
        sc.quote(t(lang, "plan_tables_drop", n=len(sp.destructive)) + "\n" + "\n".join(esc(x) for x in sp.destructive[:10]))
    if sp.manual:
        sc.quote(t(lang, "plan_tables_manual", n=len(sp.manual)) + "\n" + "\n".join(esc(x) for x in sp.manual[:6]))
    if sp.undocumented:
        sc.p(t(lang, "plan_tables_other", n=len(sp.undocumented)))
    if rep.warnings:
        sc.p(t(lang, "warns")).ul([f"<code>{esc(w.file)}</code> {esc(w.hint_en)}" if w.file else esc(w.hint_en) for w in rep.warnings[:8]])
    if not blocked and not p.nothing_to_do:
        if s["kind"] == "restore":
            label = t(lang, "btn_restore", v=vlabel(ctx["label"]))
        elif cur and ctx["label"]:
            label = t(lang, "btn_update", v=vlabel(ctx["label"]))
        else:
            label = t(lang, "btn_publish")
        sc.row(B(label, "pub", style="success"))
        if sp.destructive:
            sc.row(B(t(lang, "btn_publish_all"), "puball", style="danger"))
        if not s.get("saved"):
            sc.p(t(lang, "remember_hint"))
        sc.row(B(t(lang, "btn_remember_on") if s.get("remember") else t(lang, "btn_remember_off"), "rem"))
    return sc.row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel"))


def invalid_screen(lang: str, job: Job) -> Screen:
    rep = job.plan.report
    return (Screen().h("⚠️", t(lang, "invalid_title", n=len(rep.errors))).p(t(lang, "invalid_intro"))
            .pre(rep.for_ai()[:3500])
            .row(B("📋 Copy", copy=rep.for_ai()[:256]))
            .row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))


# ───────────── comandos ─────────────
async def gate(update: Update) -> tuple[dict | None, str]:
    u = update.effective_user
    known = db.get_user(u.id)
    lang = (known or {}).get("lang") or lang_of(u.language_code)
    if update.effective_chat.type != "private":
        return None, lang
    if not known and not db.setting("open") and not is_admin(u.id):
        await send(update.get_bot(), u.id, Screen().h("🚪", "Builder Hub").p(t(lang, "closed")))
        return None, lang
    user = db.touch_user(u)
    if user.get("blocked") and not is_admin(u.id):
        await send(update.get_bot(), u.id, Screen().h("⛔", "Builder Hub").p(t(lang, "blocked")))
        return None, lang
    return user, user.get("lang") or lang


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    ADMIN_WAIT.pop(user["id"], None)
    contact.WAIT.pop(user["id"], None)
    await send(context.bot, user["id"], home(lang, user["id"]))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    end_session(user["id"], "cancelled")
    ADMIN_WAIT.pop(user["id"], None)
    contact.WAIT.pop(user["id"], None)
    await send(context.bot, user["id"], Screen().h("✖️", "Builder Hub").p(t(lang, "cancelled")).row(B(t(lang, "btn_menu"), "m")))


async def cmd_screen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    uid = user["id"]
    name = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0].lower()
    if name in ("projects", "proyectos"):
        await send(context.bot, uid, projects_screen(lang, uid))
    elif name == "prompt":
        await send_prompt(context.bot, uid, lang)
    elif name in ("contact", "contacto"):
        contact.WAIT.pop(uid, None)
        await send(context.bot, uid, contact.start_screen(lang))
    elif name in ("help", "ayuda"):
        await send(context.bot, uid, help_screen(lang))


async def send_prompt(bot, uid: int, lang: str) -> None:
    """Prompt corto para la IA (un solo mensaje, en el idioma del usuario); el completo lo lee la IA en GitHub."""
    text = (Path(__file__).resolve().parent.parent / "prompts" / f"chat-short.{'es' if lang == 'es' else 'en'}.md").read_text(encoding="utf-8")
    intro = ("Toca el bloque para copiarlo y pégalo en el chat de tu IA. Después cuéntale qué bot quieres."
             if lang == "es" else "Tap the block to copy it and paste it into your AI chat. Then tell it which bot you want.")
    await bot.send_message(uid, intro)
    await bot.send_message(uid, f"<pre>{esc(text.strip())}</pre>", parse_mode="HTML")


# ───────────── botones ─────────────
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    user, lang = await gate(update)
    if not user:
        await q.answer()
        return
    uid, data = user["id"], q.data or ""
    msg = q.message.message_id if q.message else None
    bot = context.bot
    toast = None
    cmd, _, arg = data.partition(":")
    try:
        if cmd in CONTACT_CMDS:
            ADMIN_WAIT.pop(uid, None)
            try:
                toast = await contact.on_button(bot, uid, lang, msg, data)
            except contact.ContactError as e:
                toast = str(e)
        elif data == "m":
            contact.WAIT.pop(uid, None)
            await edit(bot, uid, msg, home(lang, uid))
        elif data == "prompt":
            await send_prompt(bot, uid, lang)
        elif data == "fmt":
            await edit(bot, uid, msg, format_screen(lang))
        elif data == "help":
            await edit(bot, uid, msg, help_screen(lang))
        elif data == "hist":
            await edit(bot, uid, msg, projects_screen(lang, uid))
        elif data == "hlog":
            await edit(bot, uid, msg, log_screen(lang, uid))
        elif cmd == "pv":
            await edit(bot, uid, msg, project_screen(lang, uid, int(arg)))
        elif cmd == "vv":
            await edit(bot, uid, msg, version_screen(lang, uid, int(arg)))
        elif cmd == "pd":
            toast = await download_version(bot, uid, lang, int(arg))
        elif cmd == "ph":
            await edit(bot, uid, msg, project_history_screen(lang, uid, int(arg)))
        elif cmd in ("pu", "pfa", "pdel", "pdel2"):
            p = db.project_get(int(arg))
            if not p or p["user_id"] != uid:
                toast = t(lang, "not_yours")
            elif cmd == "pu":
                if uid in SESSIONS:
                    toast = t(lang, "busy")
                elif over_limit(uid):
                    toast = t(lang, "limit", n=db.setting("daily_limit"))
                else:
                    ss = new_session(context.application, uid, lang, msg)
                    ss["expect"] = expect_of(p)
                    ss["step"] = "zip_first"
                    await edit(bot, uid, msg, ask_token_screen(lang, ss))
            elif cmd == "pfa":
                db.project_forget_token(p["id"])
                toast = t(lang, "forgot", name=p["name"] or p["app"])
                await edit(bot, uid, msg, project_screen(lang, uid, p["id"]))
            elif cmd == "pdel":
                n = len(db.versions_of(p["id"]))
                await edit(bot, uid, msg, Screen().h("🗑", t(lang, "del_title", name=esc(p["name"] or p["app"]))).p(t(lang, "del_confirm", n=n))
                           .row(B(t(lang, "btn_delete_yes"), f"pdel2:{p['id']}", style="danger")).row(B(t(lang, "btn_back"), f"pv:{p['id']}")))
            else:
                s0 = SESSIONS.get(uid)
                if s0 and (s0.get("expect") or {}).get("pid") == p["id"]:
                    if s0.get("busy"):
                        toast = t(lang, "busy")
                        return
                    end_session(uid, "cancelled")
                info = db.project_delete(uid, p["id"])
                c = await backup.delete_copies(bot, info.get("copies", []))
                await edit(bot, uid, msg, Screen().h("🗑", "Builder Hub")
                           .p(t(lang, "deleted", name=esc(info["name"]), v=info["versions"], c=c, d=info["deploys"]))
                           .row(B(t(lang, "btn_history"), "hist"), B(t(lang, "btn_menu"), "m")))
        elif cmd == "zp":
            ss = SESSIONS.get(uid)
            if ss and ss.get("zip") and ss.get("step") == "pick" and not ss.get("busy"):
                await q.answer()
                q = None
                ss["msg"] = msg
                if arg == "new":
                    ss["expect"], ss["step"] = None, "token"
                    await edit(bot, uid, msg, ask_token_screen(lang, ss))
                else:
                    p = db.project_get(int(arg))
                    if p and p["user_id"] == uid:
                        await use_project(bot, uid, lang, ss, p)
        elif data == "anyapp":
            ss = SESSIONS.get(uid)
            if ss and ss.get("pending_job") and not ss.get("busy"):
                await q.answer()
                q = None
                job, ss["pending_job"], ss["expect"] = ss["pending_job"], None, None
                ss["msg"] = msg
                await connect_with(bot, uid, lang, ss, job)
        elif data == "rem":
            ss = SESSIONS.get(uid)
            if ss and ss.get("ctx") and not ss.get("busy"):
                ss["remember"] = not ss.get("remember")
                await edit(bot, uid, msg, plan_screen(lang, ss))
        elif cmd == "pr":
            toast = await start_restore(context.application, uid, lang, msg, int(arg))
        elif data == "lang":
            lang = "en" if lang == "es" else "es"
            db.set_lang(uid, lang)
            await edit(bot, uid, msg, home(lang, uid))
        elif data == "dep":
            if uid in SESSIONS:
                toast = t(lang, "busy")
            elif over_limit(uid):
                toast = t(lang, "limit", n=db.setting("daily_limit"))
            else:
                s = new_session(context.application, uid, lang, msg)
                await edit(bot, uid, msg, ask_token_screen(lang, s))
        elif data == "cancel":
            s = SESSIONS.get(uid)
            if s and s.get("busy") and s.get("job") and s["job"].state == "publishing":
                toast = t(lang, "publishing")
            else:
                end_session(uid, "cancelled")
                await edit(bot, uid, msg, Screen().h("✖️", "Builder Hub").p(t(lang, "cancelled")).row(B(t(lang, "btn_menu"), "m")))
        elif data == "newzip":
            s = SESSIONS.get(uid)
            if s and s.get("job") and not s.get("busy"):
                s.update(step="zip", kind="publish", restore=None)
                await edit(bot, uid, msg, Screen().h("📦", t(lang, "connected_title"))
                           .p(t(lang, "ask_zip", mb=db.setting("max_zip_mb"))).row(B(t(lang, "btn_cancel"), "cancel")))
        elif data == "rbk":
            s = SESSIONS.get(uid)
            if s and s.get("job") and s.get("rb_vid") and not s.get("busy"):
                await q.answer()
                q = None
                s["msg"] = msg
                await restore_in_session(bot, uid, lang, s, s.pop("rb_vid"))
        elif data in ("pub", "puball", "puball2"):
            s = SESSIONS.get(uid)
            if not s or not s.get("job") or s["job"].state != "planned" or s.get("busy") or not s.get("ctx"):
                if not s:
                    await edit(bot, uid, msg, home(lang, uid))
            elif data == "puball":
                await edit(bot, uid, msg, Screen().h("🛑", t(lang, "plan_title")).p(t(lang, "confirm_drop"))
                           .row(B(t(lang, "btn_confirm_drop"), "puball2", style="danger"), B(t(lang, "btn_back"), "back_plan")))
            else:
                await q.answer(t(lang, "publishing"))
                q = None
                s["msg"] = msg
                await publish(bot, uid, lang, s, allow_destructive=(data == "puball2"))
        elif data == "back_plan":
            s = SESSIONS.get(uid)
            if s and s.get("job") and s["job"].plan and s.get("ctx"):
                await edit(bot, uid, msg, plan_screen(lang, s))
        elif data in ("adm", "ao", "aco", "az", "ad", "ap", "ab", "au", "ach", "achx", "abrand") and is_admin(uid):
            contact.WAIT.pop(uid, None)
            if data == "abrand":
                await q.answer()
                q = None
                done, err = await brand.apply(bot, with_photo=True)
                await send(bot, uid, Screen().h("🎨", t(lang, "admin_title"))
                           .p(t(lang, "brand_done", done=", ".join(done)) if not err else t(lang, "brand_fail", err=esc(err))).row(B(t(lang, "btn_back"), "adm")))
                return
            if data == "ao":
                db.set_setting("open", not db.setting("open"))
            elif data == "aco":
                db.set_setting("contact_open", not db.setting("contact_open"))
            elif data == "achx":
                db.set_setting("backup_chat", None)
            elif data in ("az", "ad", "ap", "ab", "au", "ach"):
                ADMIN_WAIT[uid] = data
                key = {"ab": "ask_user_id", "au": "ask_user_id", "ach": "ask_backup", "ap": "ask_parallel"}.get(data, "ask_number")
                await edit(bot, uid, msg, Screen().h("🛡", t(lang, "admin_title")).p(t(lang, key)).row(B(t(lang, "btn_back"), "adm")))
                return
            await edit(bot, uid, msg, admin_screen(lang))
        else:
            await edit(bot, uid, msg, home(lang, uid))
    finally:
        if q:
            try:
                await q.answer(toast[:190] if toast else None, show_alert=bool(toast))
            except Exception:  # noqa: BLE001
                pass


# ───────────── versiones: descargar y restaurar ─────────────
async def download_version(bot, uid: int, lang: str, vid: int) -> str | None:
    v, p = own_version(uid, vid)
    if not v:
        return t(lang, "not_yours")
    cap = (f"{esc(hashtag(p['name'], p['app']))} · <b>{esc(vlabel(v['label']))}</b> · <code>{esc(p['app'])}</code>\n"
           f"SHA-256 <code>{v['sha256'][:16]}…</code>")
    try:
        await bot.send_document(uid, document=v["file_id"], caption=cap, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        log.info("descarga de versión %s: %s", vid, e)
        return t(lang, "v_missing")
    return None


async def fetch_version(bot, uid: int, lang: str, s: dict, vid: int) -> bool:
    """Descarga la versión a la carpeta temporal, comprueba su SHA-256 y la deja en la sesión."""
    v = db.version_get(vid)
    dest = config.WORK_DIR / f"in-{uid}-{uuid.uuid4().hex[:8]}.zip"
    try:
        await backup.fetch(bot, v, dest)
    except backup.BackupError as e:
        await edit(bot, uid, s.get("msg"), Screen().h("⚠️", t(lang, "v_title", label=esc(vlabel(v["label"]))))
                   .p(t(lang, {"corrupt": "v_corrupt", "missing": "v_missing"}.get(e.code, "v_download")))
                   .row(B(t(lang, "btn_versions"), f"pv:{v['project_id']}")))
        return False
    meta = V.peek(dest, v["filename"] or "")
    meta.version = v["label"]
    _drop_zip(s)
    s["zip"] = {"path": dest, "file_id": v["file_id"], "name": v["filename"] or "", "size": v["size"], "sha": v["sha256"], "meta": meta}
    s["kind"], s["restore"] = "restore", {"vid": vid, "pid": v["project_id"]}
    return True


async def start_restore(app: Application, uid: int, lang: str, msg: int | None, vid: int) -> str | None:
    v, p = own_version(uid, vid)
    if not v:
        return t(lang, "not_yours")
    if uid in SESSIONS:
        return t(lang, "busy")
    if over_limit(uid):
        return t(lang, "limit", n=db.setting("daily_limit"))
    vs = db.versions_of(p["id"])
    cur = next((x for x in vs if x["id"] == p["current_vid"]), None)
    if cur:
        rb = V.rollback_check(_vdicts(vs), cur["seq"], v["label"], v["seq"])
        if not rb.ok:
            await edit(app.bot, uid, msg, version_screen(lang, uid, vid))
            return re.sub(r"<[^>]+>", "", t(lang, "ar_floor", floor=vlabel(rb.floor)))
    s = new_session(app, uid, lang, msg)
    s["msg"] = await edit(app.bot, uid, msg, Screen().h("⏳", t(lang, "checking_zip")))
    if not await fetch_version(app.bot, uid, lang, s, vid):
        end_session(uid)
        return None
    s["expect"] = expect_of(p)
    tok = vault.unseal(p.get("token_enc")) if p.get("access") == "saved" else None
    if tok:
        await connect_with(app.bot, uid, lang, s, Job(uid, tok, config.WORK_DIR, CLI), saved=True)
        return None
    await edit(app.bot, uid, s["msg"], ask_token_screen(lang, s))
    return None


async def restore_in_session(bot, uid: int, lang: str, s: dict, vid: int) -> None:
    """Volver a la versión que había tras un fallo, con el token que ya está en memoria."""
    s["msg"] = await edit(bot, uid, s.get("msg"), Screen().h("⏳", t(lang, "checking_zip")))
    if await fetch_version(bot, uid, lang, s, vid):
        await process_zip(bot, uid, lang, s)


# ───────────── conectar y elegir proyecto ─────────────
def expect_of(p: dict) -> dict:
    return {"pid": p["id"], "app": p["app"], "name": p["name"] or p["app"]}


async def connect_with(bot, uid: int, lang: str, s: dict, job: Job, saved: bool = False) -> None:
    """Conecta el trabajo (token escrito o guardado) y sigue: revisión si ya hay ZIP, o pedir el ZIP."""
    exp = s.get("expect")
    if exp and job.app != exp["app"]:
        if s["kind"] == "restore":
            job.cleanup()
            await edit(bot, uid, s["msg"], Screen().h("🔑", t(lang, "ask_token_title"))
                       .p(t(lang, "rst_wrong_app", got=esc(job.app), want=esc(exp["app"]))).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        if s.get("pending_job"):
            s["pending_job"].cleanup()
        s["pending_job"] = job
        await edit(bot, uid, s["msg"], Screen().h("🔑", t(lang, "ask_token_title"))
                   .p(t(lang, "wrong_app", got=esc(job.app), name=esc(exp["name"]), want=esc(exp["app"])))
                   .row(B(t(lang, "btn_any_app", got=job.app), "anyapp")).row(B(t(lang, "btn_cancel"), "cancel")))
        return
    s["busy"] = True
    try:
        async with JOBQ.slot(queue_notice(bot, uid, s)):
            msg_text = t(lang, "connecting", name=esc(exp["name"])) if saved and exp else t(lang, "checking_token")
            s["msg"] = await edit(bot, uid, s["msg"], Screen().h("⏳", "Builder Hub").p(msg_text))
            await job.connect()
    except DeployError as e:
        job.cleanup()
        if saved and exp and e.code == "token_bad":
            db.project_access_lost(exp["pid"])
            s["step"] = "token"
            await edit(bot, uid, s["msg"], Screen().h("⚠️", esc(exp["name"])).p(t(lang, "access_lost_now", name=esc(exp["name"])))
                       .quote(t(lang, "ask_token_safe")).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        key = "token_bad" if e.code == "token_bad" else "cloud_error"
        await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "ask_token_title")).p(t(lang, key)).row(B(t(lang, "btn_cancel"), "cancel")))
        return
    finally:
        s["busy"] = False
    if SESSIONS.get(uid) is not s:          # se canceló mientras esperaba
        job.cleanup()
        return
    s["job"], s["saved"] = job, saved
    proj = db.project_by_app(uid, job.app)
    if s.get("zip"):
        await process_zip(bot, uid, lang, s)
        return
    s["step"] = "zip"
    await edit(bot, uid, s["msg"], Screen().h("📦", t(lang, "connected_title"))
               .p(t(lang, "connected", app=esc(job.app), modules=job.deployed_modules, rev=job.revision if job.revision is not None else "—"))
               .p(t(lang, "ask_zip", mb=db.setting("max_zip_mb"))).row(B(t(lang, "btn_cancel"), "cancel")))


async def use_project(bot, uid: int, lang: str, s: dict, p: dict) -> None:
    """El ZIP (o la restauración) es para este proyecto: acceso guardado → directo; si no, pedir su token."""
    s["expect"] = expect_of(p)
    tok = vault.unseal(p.get("token_enc")) if p.get("access") == "saved" else None
    if tok:
        await connect_with(bot, uid, lang, s, Job(uid, tok, config.WORK_DIR, CLI), saved=True)
        return
    s["step"] = "token"
    await edit(bot, uid, s["msg"], ask_token_screen(lang, s))


def picker_screen(lang: str, s: dict, projs: list[dict]) -> Screen:
    meta: V.Meta = s["zip"]["meta"]
    ver = f" · {esc(vlabel(meta.version))}" if meta.version else ""
    sc = Screen().h("🗂", t(lang, "pick_title")).p(t(lang, "pick", name=esc(meta.name or s["zip"]["name"]), ver=ver))
    bl = V.changelog_since(meta.changelog, None)
    if bl:
        sc.details(t(lang, "novelties", n=len(bl)), novelty_lines(bl))
    for p in projs[:8]:
        sc.row(B(f"🤖 {p['name'] or p['app']} · {vlabel(p.get('cur_label'))}{' 🔑' if p.get('access') == 'saved' else ''}", f"zp:{p['id']}"))
    return sc.row(B(t(lang, "btn_other_bot"), "zp:new")).row(B(t(lang, "btn_cancel"), "cancel"))


async def route_zip(bot, uid: int, lang: str, s: dict) -> None:
    """Reconoce el proyecto del ZIP (por su nombre) entre los del usuario."""
    if s.get("expect"):
        p = db.project_get(s["expect"]["pid"])
        if p and p["user_id"] == uid:
            await use_project(bot, uid, lang, s, p)
            return
    meta: V.Meta = s["zip"]["meta"]
    matches = db.projects_matching(uid, meta.name)
    if len(matches) == 1:
        await use_project(bot, uid, lang, s, matches[0])
        return
    projs = db.projects_of(uid)
    if matches:
        ids = {m["id"] for m in matches}
        projs = [p for p in projs if p["id"] in ids]
    if projs:
        s["step"] = "pick"
        await edit(bot, uid, s["msg"], picker_screen(lang, s, projs))
        return
    s["step"] = "token"
    await edit(bot, uid, s["msg"], ask_token_screen(lang, s))


# ───────────── ZIP → revisión → publicar ─────────────
async def receive_zip(bot, uid: int, lang: str, m, s: dict | None, app: Application) -> None:
    doc = m.document
    max_mb = int(db.setting("max_zip_mb"))
    if m.caption and (C.TOKEN_RE.search(m.caption) or BOT_TOKEN_RE.search(m.caption)):
        await send(bot, uid, Screen().h("⚠️", "Builder Hub").p(t(lang, "zip_caption_token")))
    if (doc.file_size or 0) > max_mb * 1048576:
        await send(bot, uid, Screen().h("📦", "Builder Hub").p(t(lang, "zip_big", mb=max_mb)))
        return
    if s and s.get("busy"):
        await send(bot, uid, Screen().p(t(lang, "busy")))
        return
    if not s:
        if over_limit(uid):
            await send(bot, uid, Screen().h("📅", "Builder Hub").p(t(lang, "limit", n=db.setting("daily_limit"))))
            return
        s = new_session(app, uid, lang, None)
    s["lang"] = lang
    s["msg"] = await send(bot, uid, Screen().h("⏳", t(lang, "checking_zip")))
    dest = config.WORK_DIR / f"in-{uid}-{uuid.uuid4().hex[:8]}.zip"
    f = await bot.get_file(doc.file_id)
    await f.download_to_drive(str(dest))
    _drop_zip(s)
    s["zip"] = {"path": dest, "file_id": doc.file_id, "name": doc.file_name or "", "size": doc.file_size or dest.stat().st_size,
                "sha": V.sha256_file(dest), "meta": V.peek(dest, doc.file_name or "")}
    s["kind"], s["restore"] = "publish", None
    if s.get("job"):
        await process_zip(bot, uid, lang, s)
    else:
        await route_zip(bot, uid, lang, s)       # usa s["expect"] si se pulsó «📦 Actualizar» en un proyecto


async def process_zip(bot, uid: int, lang: str, s: dict) -> None:
    job: Job = s["job"]
    z = s["zip"]
    s["busy"] = True
    try:
        async with JOBQ.slot(queue_notice(bot, uid, s)):
            s["msg"] = await edit(bot, uid, s.get("msg"), Screen().h("⏳", t(lang, "checking_zip")))
            plan = await job.load_zip(z["path"])
    except DeployError as e:
        try:
            info = json.loads(e.detail or "{}")
        except ValueError:
            info = {}
        key = e.code if e.code.startswith("zip_") else "cloud_error"
        s["step"] = "zip"
        await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "connected_title"))
                   .p(esc(t(lang, key, **{k: v for k, v in info.items()}))).row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))
        return
    finally:
        s["busy"] = False
        if z.get("path"):
            Path(z["path"]).unlink(missing_ok=True)     # el proyecto ya está descomprimido en la carpeta del trabajo
            z["path"] = None
    if plan.report.errors:
        db.deploy_finish(db.deploy_start(uid, job.app, s["kind"]), "invalid", {"errors": len(plan.report.errors)})
        s["step"] = "zip"
        await edit(bot, uid, s["msg"], invalid_screen(lang, job))
        return
    s["step"] = "plan"
    s["ctx"] = build_ctx(uid, s, job)
    await edit(bot, uid, s["msg"], plan_screen(lang, s))


async def publish(bot, uid: int, lang: str, s: dict, allow_destructive: bool) -> None:
    job: Job = s["job"]
    ctx, z = s["ctx"], s["zip"]
    s["did"] = db.deploy_start(uid, job.app, s["kind"])
    s["busy"] = True
    try:
        async with JOBQ.slot(queue_notice(bot, uid, s)):
            s["msg"] = await edit(bot, uid, s.get("msg"), Screen().h("⏳", t(lang, "publishing")))
            job.lang = lang
            out = await job.publish(allow_destructive=allow_destructive)
    finally:
        s["busy"] = False
    sp = job.plan.schema
    cur = ctx["cur"]
    if not out.ok:
        db.deploy_finish(s["did"], "failed", error=out.error)
        s["did"] = None
        if out.error.startswith("conflict"):
            end_session(uid)
            await edit(bot, uid, s.get("msg"), Screen().h("⚠️", t(lang, "failed_title")).p(t(lang, "conflict")).row(B(t(lang, "btn_menu"), "m")))
            return
        sc = Screen().h("⚠️", t(lang, "failed_title")).p(t(lang, "failed")).pre(out.error[-3000:])
        if cur and (s["kind"] != "restore" or s["restore"]["vid"] != cur["id"]):
            s["rb_vid"] = cur["id"]
            sc.p(t(lang, "failed_rb", v=esc(vlabel(cur["label"]))))
            sc.row(B(t(lang, "btn_rollback", v=vlabel(cur["label"])), "rbk", style="primary"))
        await edit(bot, uid, s.get("msg"), sc.row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))
        return

    # ── versión: se apunta (y se guarda la copia) solo cuando ya está publicada
    destructive = out.migrated == "all" and bool(sp.destructive)
    proj = db.project_upsert(uid, job.app, ctx["name"] if ctx["name"] != job.app else "")
    stored = None
    if s["kind"] == "restore":
        vid = s["restore"]["vid"]
        db.version_touch(vid, destructive)
    else:
        same = db.version_by_sha(proj["id"], z["sha"])
        if same:
            vid = same["id"]
            db.version_touch(vid, destructive)
        else:
            meta: V.Meta = z["meta"]
            vid = db.version_add(proj["id"], label=meta.version, sha256=z["sha"], size=z["size"], filename=z["name"],
                                 file_id=z["file_id"], store="chat", changelog=meta.changelog,
                                 no_rollback_before=meta.no_rollback_before, destructive=destructive)
            v = db.version_get(vid)
            cap = (f"{esc(hashtag(proj['name'], job.app))} · <b>{esc(vlabel(v['label']))}</b> · <code>{esc(job.app)}</code>\n"
                   f"👤 <code>{uid}</code> · SHA-256 <code>{z['sha'][:16]}…</code>")
            stored = await backup.store(bot, vid, z["file_id"], cap)
    db.project_set_current(proj["id"], vid)
    db.project_set_slug(proj["id"], z["meta"].name if s["kind"] != "restore" else (proj["name"] or ""))
    db.deploy_version(s["did"], vid)
    if s.get("remember"):
        db.project_save_token(proj["id"], vault.seal(job.secret()))
    elif proj.get("access") == "saved":
        db.project_forget_token(proj["id"])
    v = db.version_get(vid)
    label = vlabel(v["label"])
    name = esc(proj["name"] or job.app)
    if s["kind"] == "restore":
        title = t(lang, "published_rst", name=name, v=esc(label))
    elif cur:
        title = t(lang, "published_upd", name=name, v=esc(label))
    else:
        title = t(lang, "published_new", name=name, v=esc(label))
    lines = [t(lang, "published")]
    if out.static_url and (job.plan.report.static_dir or job.plan.status.static_lines):
        lines.append(t(lang, "pub_webapp", url=esc(out.static_url)))
        if out.menu in ("set", "kept", "failed"):
            lines.append(t(lang, "pub_menu_" + out.menu))
    if out.webhook.get("allowed"):
        lines.append(t(lang, "pub_handlers", list=", ".join(esc(x) for x in out.webhook["allowed"])))
    if out.migrated == "all":
        lines.append(t(lang, "pub_migrated_all"))
    elif out.migrated == "safe":
        lines.append(t(lang, "pub_migrated_safe"))
        if sp.destructive:
            lines.append(t(lang, "pub_drop_skipped"))
    if out.webhook.get("error"):
        lines.append(t(lang, "pub_webhook_err", err=esc(out.webhook["error"])))
    if stored == "channel":
        lines.append(t(lang, "pub_saved_channel"))
    elif stored == "chat":
        lines.append(t(lang, "pub_saved_chat"))
    db.deploy_finish(s["did"], "published", {"modules": len(job.plan.report.modules), "migrated": out.migrated,
                                             "deleted": len(job.plan.status.deleted), "version": v["label"]})
    s["did"] = None
    screen = Screen().h("🎉", title).ul(lines)
    if ctx["novel"]:
        screen.details(t(lang, "novelties", n=len(ctx["novel"])), novelty_lines(ctx["novel"]))
    screen.quote(t(lang, "pub_access_saved") if s.get("remember") else t(lang, "rotate")).p(f"{esc(hashtag(proj['name'], job.app))} #{'restore' if s['kind'] == 'restore' else 'update'}")
    if out.static_url:
        screen.row(B("📱 Mini App", url=out.static_url))
    screen.row(B(t(lang, "btn_versions"), f"pv:{proj['id']}"), B(t(lang, "btn_menu"), "m"))
    end_session(uid)
    await edit(bot, uid, s.get("msg"), screen)


# ───────────── mensajes ─────────────
async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Error: %s", C.mask(str(context.error)), exc_info=context.error)


async def admin_input(bot, uid: int, lang: str, m, what: str) -> None:
    text = (m.text or "").strip()
    if what == "ach":
        origin = getattr(m, "forward_origin", None)
        chat_id = None
        if origin is not None and getattr(origin, "chat", None) is not None:
            chat_id = origin.chat.id
        elif re.fullmatch(r"-?\d{5,}", text):
            chat_id = int(text)
        why = await backup.check_channel(bot, chat_id) if chat_id else "?"
        if why:
            keys = {"not_admin": "why_not_admin", "no_post": "why_no_post", "not_channel": "why_not_channel"}
            why = t(lang, keys[why]) if why in keys else esc(why)
            await send(bot, uid, Screen().h("💾", t(lang, "admin_title")).p(t(lang, "backup_bad", why=why)).row(B(t(lang, "btn_back"), "adm")))
            return
        db.set_setting("backup_chat", chat_id)
        chat = await bot.get_chat(chat_id)
        await send(bot, uid, Screen().h("💾", t(lang, "admin_title")).p(t(lang, "backup_ok", title=esc(chat.title or chat_id))))
    elif text.lstrip("-").isdigit():
        n = int(text)
        if what == "az":
            db.set_setting("max_zip_mb", max(1, min(20, n)))
        elif what == "ad":
            db.set_setting("daily_limit", max(1, min(1000, n)))
        elif what == "ap":
            db.set_setting("parallel", max(1, min(4, n)))
            JOBQ.active += 1      # libera los que esperan si ahora caben más
            JOBQ.release()
        elif what in ("ab", "au") and not is_admin(n):
            db.set_blocked(n, what == "ab")
    await send(bot, uid, admin_screen(lang))


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    uid, m, bot = user["id"], update.effective_message, context.bot
    text = (m.text or "").strip()
    s = SESSIONS.get(uid)
    log.info("mensaje de %s (paso: %s, texto: %s, documento: %s)", uid, (s or {}).get("step", "-"), bool(text), bool(m.document))

    # Un token pegado en un mensaje de texto se borra siempre (los ZIP no se borran nunca).
    has_token = bool(text and (C.TOKEN_RE.search(text) or BOT_TOKEN_RE.search(text)))
    if has_token:
        try:
            await m.delete()
        except Exception:  # noqa: BLE001
            pass
    elif uid in ADMIN_WAIT and is_admin(uid) and not m.document:
        await admin_input(bot, uid, lang, m, ADMIN_WAIT.pop(uid))
        return
    elif not m.document and await contact.on_message(bot, uid, lang, m):
        return

    if m.document and (m.document.file_name or "").lower().endswith(".zip"):
        contact.WAIT.pop(uid, None)
        await receive_zip(bot, uid, lang, m, s, context.application)
        return

    if not s:
        if text and BOT_TOKEN_RE.search(text):
            await send(bot, uid, Screen().h("⚠️", "Builder Hub").p(t(lang, "token_bot")))
        await send(bot, uid, home(lang, uid))
        return

    if s.get("busy"):
        return
    if s["step"] == "zip_first":
        if not has_token:
            await send(bot, uid, Screen().p(t(lang, "zip_needed")).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        s["step"] = "token"           # pegó el token antes del ZIP: vale igual
    if s["step"] == "token":
        if BOT_TOKEN_RE.search(text) and not C.looks_like_token(text):
            await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "ask_token_title")).p(t(lang, "token_bot")).p(t(lang, "ask_token"))
                       .row(B(t(lang, "btn_cancel"), "cancel")))
            return
        if not C.looks_like_token(text):
            if m.document:
                await send(bot, uid, Screen().p(t(lang, "zip_needed")).row(B(t(lang, "btn_cancel"), "cancel")))
                return
            await edit(bot, uid, s["msg"], Screen().h("🔑", t(lang, "ask_token_title")).p(t(lang, "token_format_bad")).p(t(lang, "ask_token"))
                       .row(B(t(lang, "btn_cancel"), "cancel")))
            return
        await connect_with(bot, uid, lang, s, Job(uid, text, config.WORK_DIR, CLI))
        return

    if not has_token and s["step"] in ("zip", "plan", "pick"):
        await send(bot, uid, Screen().h("📦", t(lang, "connected_title")).p(t(lang, "zip_needed")).row(B(t(lang, "btn_cancel"), "cancel")))


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN en .env")
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    db.conn()
    # Cualquier resto de una ejecución anterior (carpetas de trabajo, ZIP descargados) se borra al arrancar.
    for old in list(config.WORK_DIR.glob("job-*")) + list(config.WORK_DIR.glob("in-*.zip")):
        shutil.rmtree(old, ignore_errors=True) if old.is_dir() else old.unlink(missing_ok=True)
    async def post_init(application: Application) -> None:
        try:
            await brand.apply(application.bot, with_photo=False)     # textos y comandos (la foto, desde el panel)
        except Exception as e:  # noqa: BLE001
            log.info("perfil del bot: %s", e)

    app = Application.builder().token(config.BOT_TOKEN).concurrent_updates(True).post_init(post_init).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["cancel", "cancelar"], cmd_cancel))
    app.add_handler(CommandHandler(["projects", "proyectos", "prompt", "contact", "contacto", "help", "ayuda"], cmd_screen))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))
    log.info("Builder Hub %s arrancado", __version__)
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
