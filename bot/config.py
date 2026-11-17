"""Configuración desde el entorno (.env). Los ajustes que cambian a menudo viven en la base de datos (panel)."""
import os
from pathlib import Path


def _ids(name: str) -> set[int]:
    return {int(x) for x in os.environ.get(name, "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = _ids("ADMIN_IDS")                    # pueden usar el panel (límites, bloqueos, registro)
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
WORK_DIR = Path(os.environ.get("WORK_DIR", "/tmp/builder-hub"))
TGCLOUD_BIN = os.environ.get("TGCLOUD_BIN", "tgcloud")
RICH_MESSAGES = os.environ.get("RICH_MESSAGES", "1") != "0"
REPO_URL = os.environ.get("REPO_URL", "https://github.com/JoseKill09/builder-hub-bot")
HANDBOOK_URL = os.environ.get("HANDBOOK_URL", "https://github.com/JoseKill09/telegram-serverless-handbook")
JOB_TTL = int(os.environ.get("JOB_TTL", "900"))           # segundos que vive un despliegue sin terminar
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL", "2"))   # despliegues a la vez (CPU del servidor)

# Valores por defecto de los ajustes del panel
DEFAULTS = {
    "open": True,          # cualquiera puede usar el bot
    "max_zip_mb": 20,      # Telegram deja a los bots descargar hasta 20 MB
    "daily_limit": 20,     # despliegues por usuario y día
}
