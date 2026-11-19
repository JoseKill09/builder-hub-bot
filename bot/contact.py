"""Contacto: los usuarios escriben al propietario (idea, error, pregunta…) y él responde desde el bot.

Mismo diseño que el contacto de Topicast: conversaciones con hilo, bandeja con filtros, respuestas rápidas,
notas, destacados, retirar la última respuesta (48 h), resolver (y avisar) y bloquear. Texto o una imagen
en las dos direcciones. La tarjeta del aviso en el chat de cada admin se mantiene al día sola.
"""
from __future__ import annotations

import json
import logging
import time

from . import config, db
from .ui import Screen, edit, esc, send

log = logging.getLogger(__name__)

KINDS = ["idea", "bug", "question", "other"]
KIND_ICON = {"idea": "💡", "bug": "🐞", "question": "❓", "other": "✉️"}
ST_ICON = {"open": "🟡", "answered": "✅", "closed": "🔒"}
PER_HOUR = 6
JOIN_WINDOW = 72 * 3600
RETRACT_WINDOW = 48 * 3600
WAIT: dict[int, dict] = {}

TT = {
    "es": {
        "kind": {"idea": "Idea o sugerencia", "bug": "Error", "question": "Pregunta", "other": "Otro"},
        "st": {"open": "Abierta", "answered": "Respondida", "closed": "Resuelta"},
        "title": "Contacto", "intro": "Escribe al propietario de Builder Hub: ideas, errores, dudas… Te responderá aquí mismo.",
        "which": "¿De qué se trata?", "mine": "📨 Mis mensajes", "back": "⬅️ Atrás", "menu": "🏠 Menú", "cancel": "✖️ Cancelar",
        "ask": "Escríbelo en un mensaje. Puedes mandar texto o una imagen (con pie si quieres).", "your_reply": "Tu respuesta",
        "thanks_t": "¡Gracias!", "thanks": "Mensaje enviado. Te avisaré aquí cuando haya respuesta.",
        "mine_t": "Mis mensajes", "mine_intro": "Tus conversaciones con el propietario.", "mine_none": "Todavía no has escrito nada.",
        "new": " · nueva", "write": "✏️ Escribir", "reply": "↩️ Responder", "you": "👤 Tú", "team": "💬 Propietario",
        "answer_t": "Respuesta del propietario", "solved_t": "Tu mensaje está resuelto", "solved": "Si no lo está del todo, contesta y lo vemos.",
        "closed": "El contacto está cerrado por ahora.", "too_many": "Has mandado muchos mensajes seguidos. Espera un poco, por favor.",
        "empty": "Escribe algo o manda una imagen.", "not_yours": "Esa conversación no es tuya.", "gone": "Ese mensaje ya no existe.",
        "unavailable": "El contacto no está disponible.",
        # admin
        "inbox": "Soporte", "counts": "{o} {open} abiertas · {a} {answered} respondidas · {c} {closed} resueltas · ⭐ {starred}",
        "inbox_none": "No hay mensajes aquí.", "quick": "⚡ Respuestas rápidas", "blocked_btn": "⛔ Bloqueados",
        "cont_in": "↪️ Continúa en #{id}", "user_blocked": "🚫 Usuario bloqueado", "note": "📝 Nota", "you_admin": "💬 Tú", "retracted": " · retirada",
        "go_last": "↪️ Ir al último", "fast": "⚡ Rápidas", "reopen": "🔓 Reabrir", "solve": "✅ Resolver", "solve_tell": "📣 Resolver y avisar",
        "star": "⭐ Destacar", "unstar": "☆ Quitar destacado", "note_btn": "📝 Nota", "retract": "🗑 Retirar mi última respuesta",
        "profile": "👤 Perfil", "block": "🚫 Bloquear", "unblock": "✅ Desbloquear", "inbox_btn": "💬 Bandeja",
        "ask_reply": "Escribe la respuesta (texto o una imagen con pie).", "ask_note": "Escribe la nota (solo la ves tú). Manda «-» para quitarla.",
        "ask_quick": "Escribe la respuesta rápida. La primera línea será su título.",
        "quick_pick": "Toca una para enviarla tal cual.", "quick_none": "No tienes respuestas rápidas. Créalas en Soporte → ⚡ Respuestas rápidas.",
        "quick_manage": "Textos que usas a menudo para contestar en un toque. Toca una para borrarla.", "none_yet": "Ninguna todavía.",
        "add": "➕ Nueva", "blocked_t": "Usuarios bloqueados", "blocked_intro": "No pueden usar el bot ni escribir al contacto. Toca uno para desbloquearlo.",
        "nobody": "Nadie bloqueado.", "sent": "Respuesta enviada.", "undeliverable": "No se pudo entregar: la persona ha bloqueado el bot.",
        "no_retract": "No hay ninguna respuesta reciente que retirar.", "self_block": "No puedes bloquearte a ti mismo.",
        "max_quick": "Ya tienes 40 respuestas rápidas.", "new_msg": "Mensaje nuevo",
    },
    "en": {
        "kind": {"idea": "Idea or suggestion", "bug": "Bug", "question": "Question", "other": "Other"},
        "st": {"open": "Open", "answered": "Answered", "closed": "Solved"},
        "title": "Contact", "intro": "Write to the owner of Builder Hub: ideas, bugs, questions… You'll get the answer right here.",
        "which": "What is it about?", "mine": "📨 My messages", "back": "⬅️ Back", "menu": "🏠 Menu", "cancel": "✖️ Cancel",
        "ask": "Write it in one message. You can send text or an image (with a caption if you like).", "your_reply": "Your reply",
        "thanks_t": "Thank you!", "thanks": "Message sent. I'll let you know here when there is an answer.",
        "mine_t": "My messages", "mine_intro": "Your conversations with the owner.", "mine_none": "You haven't written anything yet.",
        "new": " · new", "write": "✏️ Write", "reply": "↩️ Reply", "you": "👤 You", "team": "💬 Owner",
        "answer_t": "Answer from the owner", "solved_t": "Your message is solved", "solved": "If it isn't quite solved, reply and we'll look at it.",
        "closed": "Contact is closed for now.", "too_many": "You've sent many messages in a row. Please wait a bit.",
        "empty": "Write something or send an image.", "not_yours": "That conversation isn't yours.", "gone": "That message no longer exists.",
        "unavailable": "Contact is not available.",
        "inbox": "Support", "counts": "{o} {open} open · {a} {answered} answered · {c} {closed} solved · ⭐ {starred}",
        "inbox_none": "No messages here.", "quick": "⚡ Quick replies", "blocked_btn": "⛔ Blocked",
        "cont_in": "↪️ Continues in #{id}", "user_blocked": "🚫 User blocked", "note": "📝 Note", "you_admin": "💬 You", "retracted": " · retracted",
        "go_last": "↪️ Go to latest", "fast": "⚡ Quick", "reopen": "🔓 Reopen", "solve": "✅ Solve", "solve_tell": "📣 Solve and notify",
        "star": "⭐ Star", "unstar": "☆ Unstar", "note_btn": "📝 Note", "retract": "🗑 Retract my last reply",
        "profile": "👤 Profile", "block": "🚫 Block", "unblock": "✅ Unblock", "inbox_btn": "💬 Inbox",
        "ask_reply": "Write the reply (text or an image with a caption).", "ask_note": "Write the note (only you see it). Send «-» to remove it.",
        "ask_quick": "Write the quick reply. Its first line will be the title.",
        "quick_pick": "Tap one to send it as is.", "quick_none": "You have no quick replies. Create them in Support → ⚡ Quick replies.",
        "quick_manage": "Texts you often use to answer in one tap. Tap one to delete it.", "none_yet": "None yet.",
        "add": "➕ New", "blocked_t": "Blocked users", "blocked_intro": "They can't use the bot or write to contact. Tap one to unblock.",
        "nobody": "Nobody blocked.", "sent": "Reply sent.", "undeliverable": "Couldn't deliver: the person blocked the bot.",
        "no_retract": "There is no recent reply to retract.", "self_block": "You can't block yourself.",
        "max_quick": "You already have 40 quick replies.", "new_msg": "New message",
    },
}


class ContactError(Exception):
    pass


def tt(lang: str, key: str):
    return TT.get(lang, TT["en"]).get(key, TT["en"].get(key, key))


def B(t_, d=None, **kw):
    b = {"t": t_, **kw}
    if d:
        b["d"] = d
    return b


def cut(s, n: int) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt(ts) -> str:
    return time.strftime("%d/%m %H:%M", time.localtime(ts or 0))


def is_admin(uid: int) -> bool:
    return uid in config.ADMIN_IDS


def admin_lang(aid: int) -> str:
    return (db.get_user(aid) or {}).get("lang") or "es"


# ───────────── datos ─────────────
def get(fid: int):
    return db.q("SELECT * FROM feedback WHERE id=?", (int(fid),), one=True)


def must(fid: int, lang: str) -> dict:
    f = get(fid)
    if not f:
        raise ContactError(tt(lang, "gone"))
    return f


def child(f: dict):
    return db.q("SELECT id FROM feedback WHERE reply_to=? AND user_id=? ORDER BY id DESC LIMIT 1", (f["id"], f["user_id"]), one=True)


LATEST = "NOT EXISTS (SELECT 1 FROM feedback c WHERE c.reply_to = feedback.id AND c.user_id = feedback.user_id)"


def open_conversation(uid: int):
    return db.q(f"""SELECT id FROM feedback WHERE user_id=? AND status<>'closed' AND created>? AND {LATEST}
                    ORDER BY id DESC LIMIT 1""", (uid, int(time.time()) - JOIN_WINDOW), one=True)


def thread(fid: int) -> list[dict]:
    f0 = get(fid)
    if not f0:
        return []
    root = f0
    for _ in range(50):
        if not root["reply_to"]:
            break
        up = get(root["reply_to"])
        if not up or up["user_id"] != f0["user_id"]:
            break
        root = up
    ids, todo = [root["id"]], [root["id"]]
    for _ in range(50):
        if not todo:
            break
        marks = ",".join("?" * len(todo))
        rows = db.q(f"SELECT id FROM feedback WHERE user_id=? AND reply_to IN ({marks})", (f0["user_id"], *todo))
        todo = [r["id"] for r in rows if r["id"] not in ids]
        ids += todo
    marks = ",".join("?" * len(ids))
    msgs = db.q(f"SELECT * FROM feedback WHERE id IN ({marks})", ids)
    reps = db.q(f"SELECT * FROM feedback_replies WHERE feedback_id IN ({marks})", ids)
    items = [{"who": "user", "id": m["id"], "text": m["text"] or "", "file": bool(m["file_id"]), "at": m["created"] or 0} for m in msgs]
    items += [{"who": "owner", "id": r["feedback_id"], "text": r["text"] or "", "photo": bool(r["photo"]),
               "retracted": bool(r["retracted"]), "at": r["created"] or 0} for r in reps]
    return sorted(items, key=lambda m: (m["at"], 0 if m["who"] == "user" else 1))


def counts() -> dict:
    one = lambda w: db.q(f"SELECT count(*) n FROM feedback WHERE {w} AND {LATEST}", one=True)["n"]  # noqa: E731
    return {"open": one("status='open'"), "answered": one("status='answered'"), "closed": one("status='closed'"), "starred": one("starred=1")}


def open_count() -> int:
    return counts()["open"]


def name_of(uid: int) -> dict:
    u = db.get_user(uid) or {}
    return {"name": u.get("name") or f"#{uid}", "username": u.get("username"), "blocked": bool(u.get("blocked"))}


def last_retractable(fid: int):
    return db.q("SELECT * FROM feedback_replies WHERE feedback_id=? AND retracted=0 AND created>? ORDER BY id DESC LIMIT 1",
                (fid, int(time.time()) - RETRACT_WINDOW), one=True)


# ───────────── pantallas del usuario ─────────────
def start_screen(lang: str) -> Screen:
    k = tt(lang, "kind")
    return (Screen().h("✉️", tt(lang, "title")).p(tt(lang, "intro")).p(tt(lang, "which"))
            .row(B(f"💡 {k['idea']}", "ctk:idea"), B(f"🐞 {k['bug']}", "ctk:bug"))
            .row(B(f"❓ {k['question']}", "ctk:question"), B(f"✉️ {k['other']}", "ctk:other"))
            .row(B(tt(lang, "mine"), "fm"), B(tt(lang, "back"), "m")))


def ask_screen(lang: str, kind: str | None, reply_to: int | None = None) -> Screen:
    title = tt(lang, "your_reply") if reply_to else tt(lang, "kind").get(kind or "other", "")
    return (Screen().h(KIND_ICON.get(kind or "other", "✉️"), title).p(tt(lang, "ask"))
            .row(B(tt(lang, "cancel"), f"fu:{reply_to}" if reply_to else "ct")))


def mine_screen(lang: str, uid: int) -> Screen:
    rows = db.q(f"SELECT * FROM feedback WHERE user_id=? AND {LATEST} ORDER BY COALESCE(answered_at, created) DESC LIMIT 15", (uid,))
    s = Screen().h("📨", tt(lang, "mine_t")).p(tt(lang, "mine_intro"))
    if not rows:
        s.quote(tt(lang, "mine_none"))
    for r in rows:
        th = [m for m in thread(r["id"]) if not m.get("retracted")]
        first = th[0]["text"] if th else r["text"]
        new = tt(lang, "new") if th and th[-1]["who"] == "owner" and r["status"] == "answered" else ""
        s.row(B(f"{KIND_ICON.get(r['kind'], '✉️')} {ST_ICON.get(r['status'], '')} {cut(first or '📎', 30)}{new}", f"fu:{r['id']}"))
    return s.row(B(tt(lang, "write"), "ct"), B(tt(lang, "back"), "m"))


def user_thread_screen(lang: str, uid: int, fid: int) -> Screen:
    f = must(fid, lang)
    if f["user_id"] != uid:
        raise ContactError(tt(lang, "not_yours"))
    nxt = child(f)
    if nxt:
        return user_thread_screen(lang, uid, nxt["id"])
    s = Screen().h(KIND_ICON.get(f["kind"], "✉️"), tt(lang, "kind").get(f["kind"], "")).p(f"{ST_ICON[f['status']]} {tt(lang, 'st')[f['status']]}")
    for m in [x for x in thread(fid) if not x.get("retracted")][-12:]:
        s.p(f"{tt(lang, 'you') if m['who'] == 'user' else tt(lang, 'team')} · {fmt(m['at'])}")
        if m["who"] == "user":
            s.quote(esc(cut(m["text"], 700)) + (" 📎" if m.get("file") else "") or "📎")
        else:
            s.p(("🖼 " if m.get("photo") else "") + esc(cut(m["text"], 700)) or "🖼")
    return s.row(B(tt(lang, "reply"), f"fur:{fid}"), B(tt(lang, "mine"), "fm"))


# ───────────── pantallas del admin ─────────────
def card(lang: str, fid: int, in_card: bool = True) -> Screen:
    f = get(fid)
    if not f:
        return Screen().h("⚠️", tt(lang, "gone")).row(B(tt(lang, "inbox_btn"), "fb:open"))
    who = name_of(f["user_id"])
    nxt = child(f)
    st = tt(lang, "cont_in").format(id=nxt["id"]) if nxt else f"{ST_ICON[f['status']]} {tt(lang, 'st')[f['status']]}"
    s = (Screen().h(KIND_ICON.get(f["kind"], "✉️"), f"{'⭐ ' if f['starred'] else ''}{tt(lang, 'kind').get(f['kind'], '')}")
         .p(f"{esc(who['name'])}{' (@' + esc(who['username']) + ')' if who['username'] else ''} · ID <code>{f['user_id']}</code> · #{f['id']}")
         .p(st))
    if who["blocked"]:
        s.p(tt(lang, "user_blocked"))
    if f["note"]:
        s.quote(f"{tt(lang, 'note')}: {esc(cut(f['note'], 500))}")
    for m in thread(f["id"])[-12:]:
        if m["who"] == "user":
            s.p(f"👤 {esc(cut(who['name'], 30))} · {fmt(m['at'])}")
            s.quote(esc(cut(m["text"], 700)) + (" 📎" if m.get("file") else "") or "📎")
        else:
            s.p(f"{tt(lang, 'you_admin')} · {fmt(m['at'])}{tt(lang, 'retracted') if m.get('retracted') else ''}")
            s.p(("🖼 " if m.get("photo") else "") + esc(cut(m["text"], 700)) or "🖼")
    if nxt:
        s.row(B(tt(lang, "go_last"), f"fv:{nxt['id']}", style="primary"))
    else:
        s.row(B(tt(lang, "reply"), f"fr:{f['id']}", style="primary"), B(tt(lang, "fast"), f"fq:{f['id']}"))
        if f["status"] == "closed":
            s.row(B(tt(lang, "reopen"), f"fo:{f['id']}"))
        else:
            s.row(B(tt(lang, "solve"), f"fc:{f['id']}"), B(tt(lang, "solve_tell"), f"fcn:{f['id']}"))
    s.row(B(tt(lang, "unstar") if f["starred"] else tt(lang, "star"), f"fs:{f['id']}"), B(tt(lang, "note_btn"), f"fn:{f['id']}"))
    rep = last_retractable(f["id"])
    if rep and json.loads(rep["mids"] or "[]"):
        s.row(B(tt(lang, "retract"), f"frx:{f['id']}"))
    prof = B(tt(lang, "profile"), url=f"https://t.me/{who['username']}") if who["username"] else None
    blk = None
    if not is_admin(f["user_id"]):
        blk = B(tt(lang, "unblock"), f"fub:{f['user_id']}:{f['id']}") if who["blocked"] else B(tt(lang, "block"), f"fbn:{f['user_id']}:{f['id']}", style="danger")
    s.row(prof, blk)
    return s.row(B(tt(lang, "inbox_btn"), "fb:open") if in_card else B(tt(lang, "back"), "fb:open"))


def inbox_screen(lang: str, status: str = "open") -> Screen:
    where = {"open": "status='open'", "answered": "status='answered'", "closed": "status='closed'", "starred": "starred=1"}.get(status, "status='open'")
    rows = db.q(f"SELECT * FROM feedback WHERE {where} AND {LATEST} ORDER BY starred DESC, COALESCE(answered_at, created) DESC, id DESC LIMIT 10")
    c = counts()
    s = Screen().h("💬", tt(lang, "inbox")).p(tt(lang, "counts").format(o=ST_ICON["open"], a=ST_ICON["answered"], c=ST_ICON["closed"], **c))
    if not rows:
        s.quote(tt(lang, "inbox_none"))
    for r in rows:
        s.row(B(f"{'⭐' if r['starred'] else ''}{KIND_ICON.get(r['kind'], '✉️')} {cut(name_of(r['user_id'])['name'], 14)}: {cut(r['text'] or '📎', 22)}", f"fv:{r['id']}"))
    tab = lambda k, label: B(f"{'• ' if status == k else ''}{label}", f"fb:{k}")  # noqa: E731
    return (s.row(tab("open", "🟡"), tab("answered", "✅"), tab("closed", "🔒"), tab("starred", "⭐"))
            .row(B(tt(lang, "quick"), "fql"), B(tt(lang, "blocked_btn"), "fbl"))
            .row(B(tt(lang, "back"), "adm")))


def quick_screen(lang: str, fid: int | None = None) -> Screen:
    rows = db.q("SELECT * FROM fb_quick ORDER BY uses DESC, id DESC LIMIT 40")
    s = Screen().h("⚡", tt(lang, "quick"))
    if fid:
        s.p(tt(lang, "quick_pick"))
        if not rows:
            s.quote(tt(lang, "quick_none"))
        for r in rows:
            s.row(B(f"⚡ {cut(r['title'], 30)}", f"fqs:{fid}:{r['id']}"))
        return s.row(B(tt(lang, "back"), f"fv:{fid}"))
    s.p(tt(lang, "quick_manage"))
    if not rows:
        s.quote(tt(lang, "none_yet"))
    for r in rows:
        s.row(B(f"🗑 {cut(r['title'], 26)} · {r['uses']}×", f"fqd:{r['id']}"))
    return s.row(B(tt(lang, "add"), "fqa", style="success"), B(tt(lang, "back"), "fb:open"))


def blocked_screen(lang: str) -> Screen:
    s = Screen().h("⛔", tt(lang, "blocked_t")).p(tt(lang, "blocked_intro"))
    rows = db.blocked_list()
    if not rows:
        s.quote(tt(lang, "nobody"))
    for u in rows:
        s.row(B(f"✅ {cut(u['name'] or str(u['id']), 24)} · {u['id']}", f"fub:{u['id']}:0"))
    return s.row(B(tt(lang, "back"), "fb:open"))


# ───────────── acciones ─────────────
async def sync_card(bot, fid: int) -> None:
    f = get(fid)
    if not f:
        return
    for aid, mid in json.loads(f["notify"] or "{}").items():
        try:
            await edit(bot, int(aid), int(mid), card(admin_lang(int(aid)), fid), fallback_send=False)
        except Exception as e:  # noqa: BLE001
            log.info("tarjeta %s: %s", fid, e)


async def submit(bot, uid: int, lang: str, kind: str, text: str, file_id: str | None, reply_to: int | None) -> dict:
    if not config.ADMIN_IDS:
        raise ContactError(tt(lang, "unavailable"))
    if not is_admin(uid) and not db.setting("contact_open"):
        raise ContactError(tt(lang, "closed"))
    text = (text or "").strip()[:3000]
    if not text and not file_id:
        raise ContactError(tt(lang, "empty"))
    recent = db.q("SELECT count(*) n FROM feedback WHERE user_id=? AND created>?", (uid, int(time.time()) - 3600), one=True)["n"]
    if recent >= PER_HOUR and not is_admin(uid):
        raise ContactError(tt(lang, "too_many"))
    if reply_to:
        prev = get(reply_to)
        if not prev or prev["user_id"] != uid:
            raise ContactError(tt(lang, "not_yours"))
        kind = prev["kind"]
        nxt = child(prev)
        if nxt:
            reply_to = nxt["id"]
    else:
        oc = open_conversation(uid)
        reply_to = oc["id"] if oc else None
    if kind not in KINDS:
        kind = "other"
    fid = db.run("INSERT INTO feedback(user_id,kind,text,file_id,reply_to,status,created) VALUES(?,?,?,?,?,?,?)",
                 (uid, kind, text, file_id, reply_to, "open", int(time.time())))
    notify = {}
    for aid in config.ADMIN_IDS:
        if aid == uid:
            continue
        try:
            if file_id:
                await bot.send_photo(aid, photo=file_id, caption=f"#{fid}", disable_notification=True)
            mid = await send(bot, aid, card(admin_lang(aid), fid))
            if mid:
                notify[str(aid)] = mid
        except Exception as e:  # noqa: BLE001
            log.info("aviso de contacto a %s: %s", aid, e)
    db.run("UPDATE feedback SET notify=? WHERE id=?", (json.dumps(notify), fid))
    if reply_to:
        await sync_card(bot, reply_to)
    return get(fid)


async def reply(bot, admin: int, lang: str, fid: int, text: str, photo: str | None = None) -> None:
    f = must(fid, lang)
    text = (text or "").strip()[:3500]
    if not text and not photo:
        raise ContactError(tt(lang, "empty"))
    ul = (db.get_user(f["user_id"]) or {}).get("lang") or "en"
    mids = []
    try:
        if photo:
            mids.append((await bot.send_photo(f["user_id"], photo=photo, disable_notification=True)).message_id)
        s = (Screen().h("💬", tt(ul, "answer_t")).quote(esc(cut(f["text"], 300)) or "📎").p(esc(text) or "🖼")
             .row(B(tt(ul, "reply"), f"fur:{f['id']}"), B(tt(ul, "mine"), "fm")))
        mid = await send(bot, f["user_id"], s)
        if mid:
            mids.append(mid)
    except Exception as e:  # noqa: BLE001
        raise ContactError(tt(lang, "undeliverable")) from e
    now = int(time.time())
    db.run("INSERT INTO feedback_replies(feedback_id,admin_id,text,photo,mids,created) VALUES(?,?,?,?,?,?)",
           (f["id"], admin, text, photo, json.dumps(mids), now))
    db.run("UPDATE feedback SET status='answered', answered_at=? WHERE id=?", (now, f["id"]))
    await sync_card(bot, f["id"])


async def retract(bot, lang: str, fid: int) -> int:
    f = must(fid, lang)
    rep = last_retractable(f["id"])
    if not rep:
        raise ContactError(tt(lang, "no_retract"))
    n = 0
    for mid in json.loads(rep["mids"] or "[]"):
        try:
            await bot.delete_message(f["user_id"], mid)
            n += 1
        except Exception:  # noqa: BLE001
            pass
    db.run("UPDATE feedback_replies SET retracted=1 WHERE id=?", (rep["id"],))
    left = db.q("SELECT * FROM feedback_replies WHERE feedback_id=? AND retracted=0 ORDER BY id DESC LIMIT 1", (f["id"],), one=True)
    status = "closed" if f["status"] == "closed" else "answered" if left else "open"
    db.run("UPDATE feedback SET status=?, answered_at=? WHERE id=?", (status, left["created"] if left else None, f["id"]))
    await sync_card(bot, f["id"])
    return n


async def close(bot, lang: str, fid: int, notify: bool) -> None:
    f = must(fid, lang)
    db.run("UPDATE feedback SET status='closed', closed_at=? WHERE id=?", (int(time.time()), f["id"]))
    if notify:
        ul = (db.get_user(f["user_id"]) or {}).get("lang") or "en"
        s = (Screen().h("✅", tt(ul, "solved_t")).quote(esc(cut(f["text"], 300)) or "📎").p(tt(ul, "solved"))
             .row(B(tt(ul, "reply"), f"fur:{f['id']}"), B(tt(ul, "mine"), "fm")))
        try:
            await send(bot, f["user_id"], s)
        except Exception:  # noqa: BLE001
            pass
    await sync_card(bot, f["id"])


async def reopen(bot, lang: str, fid: int) -> None:
    f = must(fid, lang)
    has = db.q("SELECT count(*) n FROM feedback_replies WHERE feedback_id=? AND retracted=0", (f["id"],), one=True)["n"]
    db.run("UPDATE feedback SET status=?, closed_at=NULL WHERE id=?", ("answered" if has else "open", f["id"]))
    await sync_card(bot, f["id"])


async def block(bot, lang: str, uid: int, blocked: bool, fid: int | None) -> None:
    if is_admin(uid):
        raise ContactError(tt(lang, "self_block"))
    db.set_blocked(uid, blocked)
    for r in db.q("SELECT id FROM feedback WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)):
        await sync_card(bot, r["id"])
    if fid:
        await sync_card(bot, fid)


# ───────────── botones y mensajes ─────────────
async def on_button(bot, uid: int, lang: str, msg: int | None, data: str) -> str | None:
    """Devuelve un aviso corto para el botón (o None). Lanza ContactError con mensajes para el usuario."""
    p = data.split(":")
    cmd = p[0]
    # usuario
    if cmd == "ct":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, start_screen(lang))
    elif cmd == "ctk":
        WAIT[uid] = {"mode": "new", "kind": p[1] if p[1] in KINDS else "other"}
        await edit(bot, uid, msg, ask_screen(lang, WAIT[uid]["kind"]))
    elif cmd == "fm":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, mine_screen(lang, uid))
    elif cmd == "fu":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, user_thread_screen(lang, uid, int(p[1])))
    elif cmd == "fur":
        f = must(int(p[1]), lang)
        if f["user_id"] != uid:
            raise ContactError(tt(lang, "not_yours"))
        WAIT[uid] = {"mode": "user_reply", "fid": f["id"]}
        await edit(bot, uid, msg, ask_screen(lang, f["kind"], f["id"]))
    elif not is_admin(uid):
        return None
    # admin
    elif cmd == "fb":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, inbox_screen(lang, p[1] if len(p) > 1 else "open"))
    elif cmd == "fv":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, card(lang, int(p[1]), in_card=False))
    elif cmd in ("fr", "fn"):
        fid = int(p[1])
        must(fid, lang)
        WAIT[uid] = {"mode": "admin_reply" if cmd == "fr" else "note", "fid": fid}
        await edit(bot, uid, msg, Screen().h("↩️" if cmd == "fr" else "📝", f"#{fid}")
                   .p(tt(lang, "ask_reply") if cmd == "fr" else tt(lang, "ask_note")).row(B(tt(lang, "cancel"), f"fv:{fid}")))
    elif cmd == "fq":
        await edit(bot, uid, msg, quick_screen(lang, int(p[1])))
    elif cmd == "fqs":
        q = db.q("SELECT * FROM fb_quick WHERE id=?", (int(p[2]),), one=True)
        if not q:
            raise ContactError(tt(lang, "gone"))
        await reply(bot, uid, lang, int(p[1]), q["text"])
        db.run("UPDATE fb_quick SET uses=uses+1 WHERE id=?", (q["id"],))
        await edit(bot, uid, msg, card(lang, int(p[1]), in_card=False))
        return tt(lang, "sent")
    elif cmd in ("fc", "fcn"):
        await close(bot, lang, int(p[1]), cmd == "fcn")
        await edit(bot, uid, msg, card(lang, int(p[1]), in_card=False))
    elif cmd == "fo":
        await reopen(bot, lang, int(p[1]))
        await edit(bot, uid, msg, card(lang, int(p[1]), in_card=False))
    elif cmd == "fs":
        f = must(int(p[1]), lang)
        db.run("UPDATE feedback SET starred=? WHERE id=?", (0 if f["starred"] else 1, f["id"]))
        await sync_card(bot, f["id"])
        await edit(bot, uid, msg, card(lang, f["id"], in_card=False))
    elif cmd == "frx":
        await retract(bot, lang, int(p[1]))
        await edit(bot, uid, msg, card(lang, int(p[1]), in_card=False))
    elif cmd in ("fbn", "fub"):
        fid = int(p[2]) if len(p) > 2 and p[2] != "0" else None
        await block(bot, lang, int(p[1]), cmd == "fbn", fid)
        await edit(bot, uid, msg, card(lang, fid, in_card=False) if fid else blocked_screen(lang))
    elif cmd == "fql":
        WAIT.pop(uid, None)
        await edit(bot, uid, msg, quick_screen(lang))
    elif cmd == "fqa":
        WAIT[uid] = {"mode": "quick_add"}
        await edit(bot, uid, msg, Screen().h("⚡", tt(lang, "quick")).p(tt(lang, "ask_quick")).row(B(tt(lang, "cancel"), "fql")))
    elif cmd == "fqd":
        db.run("DELETE FROM fb_quick WHERE id=?", (int(p[1]),))
        await edit(bot, uid, msg, quick_screen(lang))
    elif cmd == "fbl":
        await edit(bot, uid, msg, blocked_screen(lang))
    return None


async def on_message(bot, uid: int, lang: str, m) -> bool:
    """True si el mensaje era para el contacto."""
    w = WAIT.get(uid)
    if not w:
        return False
    text = (m.text or m.caption or "").strip()
    photo = m.photo[-1].file_id if m.photo else None
    if not text and not photo:
        await send(bot, uid, Screen().p(tt(lang, "empty")))
        return True
    WAIT.pop(uid, None)
    try:
        mode = w["mode"]
        if mode in ("new", "user_reply"):
            await submit(bot, uid, lang, w.get("kind", "other"), text, photo, w.get("fid"))
            await send(bot, uid, Screen().h("✅", tt(lang, "thanks_t")).p(tt(lang, "thanks"))
                       .row(B(tt(lang, "mine"), "fm"), B(tt(lang, "menu"), "m")))
        elif mode == "admin_reply" and is_admin(uid):
            await reply(bot, uid, lang, w["fid"], text, photo)
            await send(bot, uid, card(lang, w["fid"], in_card=False))
        elif mode == "note" and is_admin(uid):
            db.run("UPDATE feedback SET note=? WHERE id=?", (None if text == "-" else text[:1000], w["fid"]))
            await sync_card(bot, w["fid"])
            await send(bot, uid, card(lang, w["fid"], in_card=False))
        elif mode == "quick_add" and is_admin(uid):
            if db.q("SELECT count(*) n FROM fb_quick", one=True)["n"] >= 40:
                raise ContactError(tt(lang, "max_quick"))
            title, _, body = text.partition("\n")
            db.run("INSERT INTO fb_quick(title,text) VALUES(?,?)", (title[:40], (body.strip() or title)[:3500]))
            await send(bot, uid, quick_screen(lang))
    except ContactError as e:
        await send(bot, uid, Screen().h("⚠️", tt(lang, "title")).p(esc(str(e))).row(B(tt(lang, "menu"), "m")))
    return True
