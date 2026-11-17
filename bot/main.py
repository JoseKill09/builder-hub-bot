"""Builder Hub: bot mensajero que publica proyectos de Telegram Serverless.

Flujo: 🚀 Publicar → token de acceso (se borra el mensaje) → ZIP → revisión → ✅ Publicar → resultado.
El token vive solo en memoria (dentro del Job) y se olvida al terminar, cancelar o caducar.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from . import __version__, config, db
from .deploy import cli as C
from .deploy.job import DeployError, Job
from .i18n import lang_of, t
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
SEM = asyncio.Semaphore(config.MAX_PARALLEL)
SESSIONS: dict[int, dict] = {}     # uid → {job, step, msg, did, timer}
ADMIN_WAIT: dict[int, str] = {}


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def B(t_, d=None, **kw):
    b = {"t": t_, **kw}
    if d:
        b["d"] = d
    return b


# ───────────── sesiones ─────────────
def end_session(uid: int, status: str | None = None) -> None:
    s = SESSIONS.pop(uid, None)
    if not s:
        return
    if s.get("timer"):
        s["timer"].cancel()
    if s.get("job"):
        s["job"].cleanup()
    if status and s.get("did") and status != "keep":
        db.deploy_finish(s["did"], status)


async def _expire(app: Application, uid: int, lang: str) -> None:
    await asyncio.sleep(config.JOB_TTL)
    s = SESSIONS.get(uid)
    if not s:
        return
    end_session(uid, "expired")
    try:
        await send(app.bot, uid, Screen().h("⌛", "Builder Hub").p(t(lang, "expired")).row(B(t(lang, "btn_menu"), "m")))
    except Exception:  # noqa: BLE001
        pass


# ───────────── pantallas ─────────────
def home(lang: str, uid: int) -> Screen:
    s = Screen().h("🚀", t(lang, "home_title")).p(t(lang, "home_intro")).ul([f"{i}. {x}" for i, x in enumerate(t(lang, "home_steps"), 1)])
    s.row(B(t(lang, "btn_deploy"), "dep", style="primary"))
    s.row(B(t(lang, "btn_format"), "fmt"), B(t(lang, "btn_history"), "hist"))
    s.row(B(t(lang, "btn_help"), "help"), B(t(lang, "btn_lang"), "lang"))
    if is_admin(uid):
        s.row(B(t(lang, "btn_admin"), "adm"))
    return s.foot(f"Builder Hub {__version__}")


def format_screen(lang: str) -> Screen:
    return (Screen().h("📦", t(lang, "format_title")).p(t(lang, "format")).pre(t(lang, "format_tree"))
            .ul(t(lang, "format_rules")).p(t(lang, "format_ai"))
            .row(B(t(lang, "btn_prompt"), "prompt"))
            .row(B("📄 FORMAT.md", url=config.REPO_URL + "/blob/main/docs/FORMAT.md"), B("📚 Handbook", url=config.HANDBOOK_URL))
            .row(B(t(lang, "btn_back"), "m")))


def help_screen(lang: str) -> Screen:
    return Screen().h("🔒", t(lang, "help_title")).ul(t(lang, "help")).row(B("GitHub", url=config.REPO_URL), B(t(lang, "btn_back"), "m"))


def history_screen(lang: str, uid: int) -> Screen:
    rows = db.my_deploys(uid)
    s = Screen().h("🕘", t(lang, "history_title"))
    if not rows:
        s.p(t(lang, "history_none"))
    else:
        s.ul([f"{time.strftime('%d/%m %H:%M', time.localtime(r['created']))} · <code>{esc(r['app'])}</code> · {t(lang, 'st_' + r['status'])}" for r in rows])
    return s.row(B(t(lang, "btn_back"), "m"))


def admin_screen(lang: str) -> Screen:
    st = db.stats()
    return (Screen().h("🛡", t(lang, "admin_title")).p(esc(t(lang, "admin_stats", **st)))
            .kv([(t(lang, "admin_open"), t(lang, "yes") if db.setting("open") else t(lang, "no")),
                 (t(lang, "admin_zip"), f"{db.setting('max_zip_mb')} MB"),
                 (t(lang, "admin_daily"), str(db.setting("daily_limit")))])
            .row(B(t(lang, "btn_toggle_open"), "ao"))
            .row(B(t(lang, "btn_zip"), "az"), B(t(lang, "btn_daily"), "ad"))
            .row(B(t(lang, "btn_block"), "ab"), B(t(lang, "btn_unblock"), "au"))
            .row(B(t(lang, "btn_back"), "m")))


def plan_screen(lang: str, job: Job) -> Screen:
    p = job.plan
    st, sp, rep = p.status, p.schema, p.report
    s = Screen().h("🔎", t(lang, "plan_title"))
    if p.nothing_to_do:
        s.p(t(lang, "plan_nothing"))
    new, mod = len(st.new), len(st.modified)
    same = max(0, len([m for m in rep.modules]) - new - mod)
    s.p(t(lang, "plan_modules", new=new, mod=mod, same=same))
    if st.deleted:
        s.quote(t(lang, "plan_deleted", n=len(st.deleted)) + "\n" + "\n".join(f"<code>{esc(x)}</code>" for x in st.deleted[:12])
                + ("\n…" if len(st.deleted) > 12 else ""))
    if st.static_lines:
        s.p(t(lang, "plan_static", n=len(st.static_lines)))
    if p.unmanaged_static:
        s.p(t(lang, "plan_static_unmanaged"))
    if sp.safe:
        s.p(t(lang, "plan_tables_new", n=len(sp.safe)))
    if sp.destructive:
        s.quote(t(lang, "plan_tables_drop", n=len(sp.destructive)) + "\n" + "\n".join(esc(x) for x in sp.destructive[:10]))
    if sp.manual:
        s.quote(t(lang, "plan_tables_manual", n=len(sp.manual)) + "\n" + "\n".join(esc(x) for x in sp.manual[:6]))
    if sp.undocumented:
        s.p(t(lang, "plan_tables_other", n=len(sp.undocumented)))
    if rep.warnings:
        s.p(t(lang, "warns")).ul([f"<code>{esc(w.file)}</code> {esc(w.hint_en)}" if w.file else esc(w.hint_en) for w in rep.warnings[:8]])
    if not p.nothing_to_do:
        s.row(B(t(lang, "btn_publish"), "pub", style="success"))
        if sp.destructive:
            s.row(B(t(lang, "btn_publish_all"), "puball", style="danger"))
    return s.row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel"))


def invalid_screen(lang: str, job: Job) -> Screen:
    rep = job.plan.report
    return (Screen().h("⚠️", t(lang, "invalid_title", n=len(rep.errors))).p(t(lang, "invalid_intro"))
            .pre(rep.for_ai()[:3500])
            .row(B("📋 Copy", copy=rep.for_ai()[:256]))
            .row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))


# ───────────── comandos y botones ─────────────
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
    await send(context.bot, user["id"], home(lang, user["id"]))


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    end_session(user["id"], "cancelled")
    ADMIN_WAIT.pop(user["id"], None)
    await send(context.bot, user["id"], Screen().h("✖️", "Builder Hub").p(t(lang, "cancelled")).row(B(t(lang, "btn_menu"), "m")))


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
    try:
        if data == "m":
            await edit(bot, uid, msg, home(lang, uid))
        elif data == "prompt":
            await send_prompt(bot, uid, lang)
        elif data == "fmt":
            await edit(bot, uid, msg, format_screen(lang))
        elif data == "help":
            await edit(bot, uid, msg, help_screen(lang))
        elif data == "hist":
            await edit(bot, uid, msg, history_screen(lang, uid))
        elif data == "lang":
            lang = "en" if lang == "es" else "es"
            db.set_lang(uid, lang)
            await edit(bot, uid, msg, home(lang, uid))
        elif data == "dep":
            if uid in SESSIONS:
                toast = t(lang, "busy")
            elif not is_admin(uid) and db.deploys_today(uid) >= int(db.setting("daily_limit")):
                toast = t(lang, "limit", n=db.setting("daily_limit"))
            else:
                SESSIONS[uid] = {"step": "token", "msg": msg, "lang": lang,
                                 "timer": asyncio.create_task(_expire(context.application, uid, lang))}
                await edit(bot, uid, msg, Screen().h("🔑", t(lang, "ask_token_title")).p(t(lang, "ask_token"))
                           .quote(t(lang, "ask_token_safe")).row(B(t(lang, "btn_cancel"), "cancel")))
        elif data == "cancel":
            end_session(uid, "cancelled")
            await edit(bot, uid, msg, Screen().h("✖️", "Builder Hub").p(t(lang, "cancelled")).row(B(t(lang, "btn_menu"), "m")))
        elif data == "newzip":
            s = SESSIONS.get(uid)
            if s and s.get("job"):
                s["step"] = "zip"
                await edit(bot, uid, msg, Screen().h("📦", t(lang, "connected_title"))
                           .p(t(lang, "ask_zip", mb=db.setting("max_zip_mb"))).row(B(t(lang, "btn_cancel"), "cancel")))
        elif data in ("pub", "puball", "puball2"):
            s = SESSIONS.get(uid)
            if not s or not s.get("job") or s["job"].state != "planned":
                await edit(bot, uid, msg, home(lang, uid))
            elif data == "puball":
                await edit(bot, uid, msg, Screen().h("🛑", t(lang, "plan_title")).p(t(lang, "confirm_drop"))
                           .row(B(t(lang, "btn_confirm_drop"), "puball2", style="danger"), B(t(lang, "btn_back"), "back_plan")))
            else:
                await q.answer(t(lang, "publishing"))
                q = None
                await publish(bot, uid, lang, s, allow_destructive=(data == "puball2"))
        elif data == "back_plan":
            s = SESSIONS.get(uid)
            if s and s.get("job") and s["job"].plan:
                await edit(bot, uid, msg, plan_screen(lang, s["job"]))
        elif data in ("adm", "ao", "az", "ad", "ab", "au") and is_admin(uid):
            if data == "ao":
                db.set_setting("open", not db.setting("open"))
            elif data in ("az", "ad", "ab", "au"):
                ADMIN_WAIT[uid] = data
                await edit(bot, uid, msg, Screen().h("🛡", t(lang, "admin_title"))
                           .p(t(lang, "ask_user_id") if data in ("ab", "au") else t(lang, "ask_number")).row(B(t(lang, "btn_back"), "adm")))
                await q.answer()
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


async def publish(bot, uid: int, lang: str, s: dict, allow_destructive: bool) -> None:
    job: Job = s["job"]
    if not s.get("did"):
        s["did"] = db.deploy_start(uid, job.app)
    await edit(bot, uid, s.get("msg"), Screen().h("⏳", t(lang, "publishing")))
    async with SEM:
        out = await job.publish(allow_destructive=allow_destructive)
    if out.ok:
        sp = job.plan.schema
        lines = [t(lang, "published")]
        if out.static_url and (job.plan.report.static_dir or job.plan.status.static_lines):
            lines.append(t(lang, "pub_webapp", url=esc(out.static_url)))
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
        db.deploy_finish(s["did"], "published", {"modules": len(job.plan.report.modules), "migrated": out.migrated,
                                                 "deleted": len(job.plan.status.deleted)})
        screen = Screen().h("🎉", t(lang, "published_title")).ul(lines).quote(t(lang, "rotate")).row(B(t(lang, "btn_menu"), "m"))
        if out.static_url:
            screen.rows.insert(0, [B("📱 Mini App", url=out.static_url)])
        SESSIONS[uid]["did"] = None
        end_session(uid)
        await edit(bot, uid, s.get("msg"), screen)
    else:
        db.deploy_finish(s["did"], "failed", error=out.error)
        if out.error.startswith("conflict"):
            end_session(uid)
            await edit(bot, uid, s.get("msg"), Screen().h("⚠️", t(lang, "failed_title")).p(t(lang, "conflict")).row(B(t(lang, "btn_menu"), "m")))
            return
        await edit(bot, uid, s.get("msg"), Screen().h("⚠️", t(lang, "failed_title")).p(t(lang, "failed"))
                   .pre(out.error[-3000:]).row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))


# ───────────── mensajes ─────────────
async def send_prompt(bot, uid: int, lang: str) -> None:
    """Prompt corto para la IA (un solo mensaje, en el idioma del usuario); el completo lo lee la IA en GitHub."""
    text = (Path(__file__).resolve().parent.parent / "prompts" / f"chat-short.{'es' if lang == 'es' else 'en'}.md").read_text(encoding="utf-8")
    intro = ("Toca el bloque para copiarlo y pégalo en el chat de tu IA. Después cuéntale qué bot quieres."
             if lang == "es" else "Tap the block to copy it and paste it into your AI chat. Then tell it which bot you want.")
    await bot.send_message(uid, intro)
    await bot.send_message(uid, f"<pre>{esc(text.strip())}</pre>", parse_mode="HTML")


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Error: %s", C.mask(str(context.error)), exc_info=context.error)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, lang = await gate(update)
    if not user:
        return
    uid, m, bot = user["id"], update.effective_message, context.bot
    text = (m.text or "").strip()
    log.info("mensaje de %s (paso: %s, texto: %s, documento: %s)", uid, (SESSIONS.get(uid) or {}).get("step", "-"), bool(text), bool(m.document))

    # Panel: respuestas numéricas
    if uid in ADMIN_WAIT and is_admin(uid):
        what = ADMIN_WAIT.pop(uid)
        if text.isdigit():
            n = int(text)
            if what == "az":
                db.set_setting("max_zip_mb", max(1, min(20, n)))
            elif what == "ad":
                db.set_setting("daily_limit", max(1, min(1000, n)))
            elif what in ("ab", "au"):
                db.set_blocked(n, what == "ab")
        await send(bot, uid, admin_screen(lang))
        return

    s = SESSIONS.get(uid)
    # Un token pegado por error en cualquier momento: se borra siempre.
    if text and (C.TOKEN_RE.search(text) or BOT_TOKEN_RE.search(text)):
        try:
            await m.delete()
        except Exception:  # noqa: BLE001
            pass
    if not s:
        if text and BOT_TOKEN_RE.search(text):
            await send(bot, uid, Screen().h("⚠️", "Builder Hub").p(t(lang, "token_bot")))
        await send(bot, uid, home(lang, uid))
        return

    if s["step"] == "token":
        if BOT_TOKEN_RE.search(text) and not C.looks_like_token(text):
            await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "ask_token_title")).p(t(lang, "token_bot")).p(t(lang, "ask_token")).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        if not C.looks_like_token(text):
            await edit(bot, uid, s["msg"], Screen().h("🔑", t(lang, "ask_token_title")).p(t(lang, "token_format_bad")).p(t(lang, "ask_token")).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        s["msg"] = await edit(bot, uid, s["msg"], Screen().h("⏳", t(lang, "checking_token")))
        job = Job(uid, text, config.WORK_DIR, CLI)
        try:
            async with SEM:
                await job.connect()
        except DeployError as e:
            job.cleanup()
            key = "token_bad" if e.code == "token_bad" else "cloud_error"
            await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "ask_token_title")).p(t(lang, key)).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        s.update(job=job, step="zip", did=db.deploy_start(uid, job.app))
        await edit(bot, uid, s["msg"], Screen().h("📦", t(lang, "connected_title"))
                   .p(t(lang, "connected", app=esc(job.app), modules=job.deployed_modules, rev=job.revision if job.revision is not None else "—"))
                   .p(t(lang, "ask_zip", mb=db.setting("max_zip_mb"))).row(B(t(lang, "btn_cancel"), "cancel")))
        return

    if s["step"] == "zip":
        doc = m.document
        if not doc or not (doc.file_name or "").lower().endswith(".zip"):
            await send(bot, uid, Screen().h("📦", t(lang, "connected_title")).p(t(lang, "zip_needed")).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        max_mb = int(db.setting("max_zip_mb"))
        if (doc.file_size or 0) > max_mb * 1048576:
            await send(bot, uid, Screen().h("📦", t(lang, "connected_title")).p(t(lang, "zip_big", mb=max_mb)).row(B(t(lang, "btn_cancel"), "cancel")))
            return
        job: Job = s["job"]
        s["msg"] = await send(bot, uid, Screen().h("⏳", t(lang, "checking_zip")))
        zpath = job.dir / "upload.zip"
        f = await bot.get_file(doc.file_id)
        await f.download_to_drive(str(zpath))
        try:
            async with SEM:
                plan = await job.load_zip(zpath)
        except DeployError as e:
            try:
                info = json.loads(e.detail or "{}")
            except ValueError:
                info = {}
            key = e.code if e.code.startswith("zip_") else "cloud_error"
            await edit(bot, uid, s["msg"], Screen().h("⚠️", t(lang, "connected_title"))
                       .p(esc(t(lang, key, **{k: v for k, v in info.items()}))).row(B(t(lang, "btn_newzip"), "newzip"), B(t(lang, "btn_cancel"), "cancel")))
            return
        finally:
            zpath.unlink(missing_ok=True)
        if plan.report.errors:
            # Se apunta el intento con errores; si luego publica, se abre otra fila.
            if s.get("did"):
                db.deploy_finish(s["did"], "invalid", {"errors": len(plan.report.errors)})
                s["did"] = None
            await edit(bot, uid, s["msg"], invalid_screen(lang, job))
        else:
            await edit(bot, uid, s["msg"], plan_screen(lang, job))
        return
    await send(bot, uid, home(lang, uid))


def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit("Falta BOT_TOKEN en .env")
    config.WORK_DIR.mkdir(parents=True, exist_ok=True)
    db.conn()
    # Cualquier carpeta de trabajo de una ejecución anterior se borra al arrancar.
    for old in config.WORK_DIR.glob("job-*"):
        shutil.rmtree(old, ignore_errors=True)
    app = Application.builder().token(config.BOT_TOKEN).concurrent_updates(True).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler(["cancel", "cancelar"], cmd_cancel))
    app.add_error_handler(on_error)
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, on_message))
    log.info("Builder Hub %s arrancado", __version__)
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)


if __name__ == "__main__":
    main()
