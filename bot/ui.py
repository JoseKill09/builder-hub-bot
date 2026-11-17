"""Pantallas con Rich Messages y cascada de respaldo:
   1) rich_message con botones embebidos (<tg-button-row>)  2) rich_message + reply_markup  3) HTML clásico.
Si un nivel falla, se recuerda una hora para no repetir el error. Los textos ya vienen en HTML:
los valores dinámicos se escapan con esc() antes de meterlos.
"""
from __future__ import annotations

import html
import logging
import re
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden

from . import config

log = logging.getLogger(__name__)
esc = lambda s: html.escape(str(s if s is not None else ""), quote=True)  # noqa: E731
_level = {"n": 0, "until": 0.0}


class Screen:
    def __init__(self):
        self.blocks: list[tuple] = []
        self.rows: list[list[dict]] = []

    def h(self, icon, title): self.blocks.append(("h", f"{icon} {title}")); return self
    def p(self, text): self.blocks.append(("p", text)); return self
    def ul(self, items): items and self.blocks.append(("ul", list(items))); return self
    def kv(self, pairs): pairs and self.blocks.append(("kv", list(pairs))); return self
    def quote(self, text): self.blocks.append(("q", text)); return self
    def pre(self, text): self.blocks.append(("pre", text)); return self
    def foot(self, text): self.blocks.append(("f", text)); return self

    def row(self, *btns):
        r = [b for b in btns if b]
        if r:
            self.rows.append(r)
        return self

    def rich(self, embed: bool) -> str:
        out = []
        for b in self.blocks:
            k = b[0]
            if k == "h":
                out.append(f"<h3>{b[1]}</h3>")
            elif k == "p":
                out.append("".join(f"<p>{x}</p>" for x in str(b[1]).split("\n") if x.strip()))
            elif k == "ul":
                out.append("<ul>" + "".join(f"<li>{i}</li>" for i in b[1]) + "</ul>")
            elif k == "kv":
                out.append("<table>" + "".join(f"<tr><td>{a}</td><td><b>{v}</b></td></tr>" for a, v in b[1]) + "</table>")
            elif k == "q":
                out.append(f"<blockquote>{str(b[1]).replace(chr(10), '<br>')}</blockquote>")
            elif k == "pre":
                out.append(f"<pre>{esc(b[1])}</pre>")
            elif k == "f":
                out.append(f"<footer>{b[1]}</footer>")
        if embed:
            for r in self.rows:
                out.append("<tg-button-row>" + "".join(_rich_btn(x) for x in r) + "</tg-button-row>")
        return "".join(out)

    def classic(self) -> str:
        out = []
        for b in self.blocks:
            k = b[0]
            if k == "h":
                out.append(f"<b>{b[1]}</b>")
            elif k == "p":
                out.append(str(b[1]))
            elif k == "ul":
                out.append("\n".join(f"• {i}" for i in b[1]))
            elif k == "kv":
                out.append("\n".join(f"{a}: <b>{v}</b>" for a, v in b[1]))
            elif k == "q":
                out.append(f"<blockquote>{b[1]}</blockquote>")
            elif k == "pre":
                out.append(f"<pre>{esc(b[1])}</pre>")
            elif k == "f":
                out.append(f"<i>{b[1]}</i>")
        text = "\n\n".join(out)
        return text if len(text) < 4000 else text[:3990] + "…"

    def markup(self):
        if not self.rows:
            return None
        # El botón «copiar» solo existe en el formato rich: en el teclado clásico se omite
        # (el texto ya va en un bloque que se puede copiar).
        rows = [[InlineKeyboardButton(b["t"], url=b["url"]) if "url" in b else InlineKeyboardButton(b["t"], callback_data=b["d"])
                 for b in r if "copy" not in b] for r in self.rows]
        rows = [r for r in rows if r]
        return InlineKeyboardMarkup(rows) if rows else None


def _rich_btn(b: dict) -> str:
    st = f' style="{esc(b["style"])}"' if b.get("style") else ""
    if "url" in b:
        return f'<tg-button type="url"{st} url="{esc(b["url"])}">{esc(b["t"])}</tg-button>'
    if "copy" in b:
        return f'<tg-button type="copy_text"{st} text="{esc(b["copy"][:256])}">{esc(b["t"])}</tg-button>'
    return f'<tg-button type="callback_data"{st} data="{esc(b["d"])}">{esc(b["t"])}</tg-button>'


def _start() -> int:
    if not config.RICH_MESSAGES:
        return 2
    return _level["n"] if time.time() < _level["until"] else 0


def _remember(first: int, worked: int) -> None:
    if worked > first:
        _level.update(n=worked, until=time.time() + 3600)


def _fatal(e: Exception) -> bool:
    s = str(e).lower()
    return isinstance(e, Forbidden) or any(w in s for w in ("chat not found", "message to edit not found", "blocked"))


async def send(bot, chat_id: int, s: Screen) -> int | None:
    first = _start()
    for lv in range(first, 3):
        try:
            if lv == 2:
                m = await bot.send_message(chat_id, s.classic(), parse_mode="HTML", reply_markup=s.markup(),
                                           disable_web_page_preview=True)
                _remember(first, lv)
                return m.message_id
            params = {"chat_id": chat_id, "rich_message": {"html": s.rich(lv == 0)[:32000]}}
            if lv == 1 and s.markup():
                params["reply_markup"] = s.markup().to_dict()
            r = await bot.do_api_request("sendRichMessage", api_kwargs=params)
            _remember(first, lv)
            return r.get("message_id") if isinstance(r, dict) else getattr(r, "message_id", None)
        except Exception as e:  # noqa: BLE001
            if _fatal(e):
                raise
            log.info("envío nivel %s falló: %s", lv, e)
    return None


async def edit(bot, chat_id: int, msg_id: int | None, s: Screen) -> int | None:
    if not msg_id:
        return await send(bot, chat_id, s)
    first = _start()
    for lv in range(first, 3):
        try:
            if lv == 2:
                await bot.edit_message_text(s.classic(), chat_id=chat_id, message_id=msg_id, parse_mode="HTML",
                                            reply_markup=s.markup(), disable_web_page_preview=True)
            else:
                params = {"chat_id": chat_id, "message_id": msg_id, "rich_message": {"html": s.rich(lv == 0)[:32000]}}
                if lv == 1 and s.markup():
                    params["reply_markup"] = s.markup().to_dict()
                await bot.do_api_request("editMessageText", api_kwargs=params)
            _remember(first, lv)
            return msg_id
        except Exception as e:  # noqa: BLE001
            if "not modified" in str(e).lower():
                return msg_id
            if isinstance(e, BadRequest) and re.search(r"can't be edited|message to edit not found", str(e), re.I):
                break
            if _fatal(e):
                raise
            log.info("edición nivel %s falló: %s", lv, e)
    return await send(bot, chat_id, s)
