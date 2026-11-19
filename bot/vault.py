"""Tokens recordados (solo si el usuario elige «Recordar acceso»), cifrados con Fernet (AES-128 + HMAC).

La clave sale de la variable SECRET_KEY si existe; si no, se crea una vez en data/vault.key (permisos 600).
Sin la clave, la base de datos no sirve para sacar ningún token. Un token descifrado solo vive en memoria.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from . import config

_f: Fernet | None = None


def _fernet() -> Fernet:
    global _f
    if _f is None:
        key = os.environ.get("SECRET_KEY", "").strip().encode()
        if not key:
            path = Path(config.DATA_DIR) / "vault.key"
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(Fernet.generate_key())
            key = path.read_bytes().strip()
        try:
            _f = Fernet(key)
        except (ValueError, TypeError):
            # SECRET_KEY que no es una clave Fernet: se deriva una de su SHA-256.
            _f = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key).digest()))
    return _f


def seal(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def unseal(blob: str | None) -> str | None:
    if not blob:
        return None
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except (InvalidToken, ValueError):
        return None
