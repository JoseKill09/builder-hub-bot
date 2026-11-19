"""Perfil del bot: nombre, descripciones, comandos (es/en) y foto de perfil.

Los textos y comandos se ponen solos al arrancar (solo si cambiaron). La foto, desde 🛡 Panel → 🎨 Perfil del bot
(setMyProfilePhoto, JPG). La imagen del chat vacío («description picture») solo se puede poner en @BotFather:
está en brand/banner-*.png.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
from telegram import BotCommand

from . import config

log = logging.getLogger(__name__)
BRAND_DIR = Path(__file__).resolve().parent.parent / "brand"

NAME = "Builder Hub"
SHORT = {
    "es": "Publica tu bot de Telegram Serverless desde cualquier IA: mándame el ZIP y lo subo, con versiones y vuelta atrás.",
    "en": "Ship your Telegram Serverless bot from any AI chat: send the ZIP and I publish it, with versions and rollback.",
}
DESCRIPTION = {
    "es": ("Builder Hub publica en tu bot de Telegram Serverless el proyecto que te prepare tu IA (Claude, ChatGPT, Gemini…). "
           "No necesitas ordenador ni terminal.\n\n"
           "📦 Mándame el ZIP\n🔎 Lo reviso y te enseño qué cambia\n✅ Lo publico en tu bot\n"
           "🗂 Guardo cada versión para volver atrás\n\n"
           "Tu código no se ejecuta aquí: corre en los servidores de Telegram."),
    "en": ("Builder Hub publishes the project your AI (Claude, ChatGPT, Gemini…) prepares to your Telegram Serverless bot. "
           "No computer or terminal needed.\n\n"
           "📦 Send me the ZIP\n🔎 I check it and show you what changes\n✅ I publish it to your bot\n"
           "🗂 I keep every version so you can go back\n\n"
           "Your code doesn't run here: it runs on Telegram's servers."),
}
COMMANDS = {
    "es": [("start", "Menú principal"), ("projects", "Mis proyectos y versiones"), ("prompt", "Prompt para tu IA"),
           ("contact", "Escribir al propietario"), ("help", "Seguridad y privacidad"), ("cancel", "Cancelar lo que esté en marcha")],
    "en": [("start", "Main menu"), ("projects", "My projects and versions"), ("prompt", "Prompt for your AI"),
           ("contact", "Write to the owner"), ("help", "Security and privacy"), ("cancel", "Cancel what is running")],
}


async def apply(bot, with_photo: bool = False) -> tuple[list[str], str]:
    """Pone el perfil. Devuelve (lo que se cambió, error)."""
    done, err = [], ""
    try:
        for code in ("", "es", "en"):
            lang = code or "en"
            cur = await bot.get_my_short_description(language_code=code or None)
            if cur.short_description != SHORT[lang]:
                await bot.set_my_short_description(SHORT[lang], language_code=code or None)
                done.append(f"short:{lang if code else 'default'}")
            cur = await bot.get_my_description(language_code=code or None)
            if cur.description != DESCRIPTION[lang]:
                await bot.set_my_description(DESCRIPTION[lang], language_code=code or None)
                done.append(f"description:{lang if code else 'default'}")
            want = [BotCommand(c, d) for c, d in COMMANDS[lang]]
            cur = await bot.get_my_commands(language_code=code or None)
            if [(c.command, c.description) for c in cur] != COMMANDS[lang]:
                await bot.set_my_commands(want, language_code=code or None)
                done.append(f"commands:{lang if code else 'default'}")
        cur = await bot.get_my_name()
        if cur.name != NAME:
            await bot.set_my_name(NAME)
            done.append("name")
        if with_photo:
            await set_photo()
            done.append("photo")
    except Exception as e:  # noqa: BLE001
        err = str(e)[:300]
        log.info("perfil: %s", err)
    return done, err


async def set_photo() -> None:
    """setMyProfilePhoto (Bot API 9.x): JPG subido como archivo; python-telegram-bot 21 aún no lo trae."""
    photo = BRAND_DIR / "profile.jpg"
    async with httpx.AsyncClient(timeout=60) as cl:
        r = await cl.post(f"https://api.telegram.org/bot{config.BOT_TOKEN}/setMyProfilePhoto",
                          data={"photo": json.dumps({"type": "static", "photo": "attach://pic"})},
                          files={"pic": ("profile.jpg", photo.read_bytes(), "image/jpeg")})
    body = r.json()
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or f"HTTP {r.status_code}")
