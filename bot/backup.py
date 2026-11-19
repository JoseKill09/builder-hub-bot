"""Copias de los ZIP publicados.

Cada versión publicada queda guardada en Telegram, no en el NAS:
- con canal de copias (Panel → 📦 Copias): el bot reenvía el ZIP al canal privado por su file_id (sin volver a subirlo);
- sin canal: se recuerda el file_id del ZIP que mandó el usuario (sigue sirviendo mientras Telegram conserve el archivo).
Para restaurar se descarga solo esa versión a la carpeta temporal, se comprueba su SHA-256 y se borra al terminar.
"""
from __future__ import annotations

import logging
from pathlib import Path

from . import db
from .versions import sha256_file

log = logging.getLogger(__name__)


class BackupError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code        # missing | corrupt | download


def channel() -> int | None:
    v = db.setting("backup_chat")
    try:
        return int(v) if v else None
    except (TypeError, ValueError):
        return None


async def store(bot, vid: int, user_file_id: str, caption: str) -> str:
    """Guarda la versión en el canal si hay uno. Devuelve 'channel' o 'chat'."""
    ch = channel()
    if not ch:
        return "chat"
    try:
        m = await bot.send_document(ch, document=user_file_id, caption=caption[:1000], parse_mode="HTML",
                                    disable_notification=True)
        db.version_store(vid, "channel", m.document.file_id, ch, m.message_id)
        return "channel"
    except Exception as e:  # noqa: BLE001
        log.warning("copia al canal %s falló: %s", ch, e)
        return "chat"


async def fetch(bot, version: dict, dest: Path) -> Path:
    """Descarga la versión y comprueba que es exactamente la que se publicó."""
    if not version.get("file_id"):
        raise BackupError("missing")
    try:
        f = await bot.get_file(version["file_id"])
        await f.download_to_drive(str(dest))
    except Exception as e:  # noqa: BLE001
        log.info("descarga de la versión %s falló: %s", version.get("id"), e)
        dest.unlink(missing_ok=True)
        raise BackupError("missing" if "not found" in str(e).lower() or "invalid" in str(e).lower() else "download") from e
    if sha256_file(dest) != version.get("sha256"):
        dest.unlink(missing_ok=True)
        raise BackupError("corrupt")
    return dest


async def check_channel(bot, chat_id: int) -> str | None:
    """None si el bot puede publicar en ese canal; si no, el motivo."""
    try:
        chat = await bot.get_chat(chat_id)
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id, me.id)
    except Exception as e:  # noqa: BLE001
        return str(e)[:200]
    if chat.type not in ("channel", "supergroup", "group"):
        return "not_channel"
    if member.status not in ("administrator", "creator"):
        return "not_admin"
    if chat.type == "channel" and not getattr(member, "can_post_messages", False):
        return "no_post"
    return None


async def delete_copies(bot, copies: list[tuple[int, int]]) -> int:
    """Borra del canal las copias de un proyecto eliminado. Devuelve cuántas se borraron."""
    n = 0
    for chat, msg in copies:
        try:
            await bot.delete_message(chat, msg)
            n += 1
        except Exception as e:  # noqa: BLE001
            log.info("no pude borrar la copia %s/%s: %s", chat, msg, e)
    return n
