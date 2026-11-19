"""Llamadas al CLI oficial `tgcloud` y lectura de su salida.

El token solo viaja en la variable de entorno TGCLOUD_TOKEN del proceso hijo: nunca en argumentos,
archivos ni registros. Cualquier cosa con forma de token que aparezca en la salida se enmascara.
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"app\d+:[A-Za-z0-9_-]{8,}")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\r")


def mask(text: str) -> str:
    return TOKEN_RE.sub(lambda m: m.group(0).split(":")[0] + ":***", text or "")


def app_id(token: str) -> str:
    return token.split(":", 1)[0]


def looks_like_token(text: str) -> bool:
    return bool(re.fullmatch(r"app\d+:[A-Za-z0-9_-]{16,}", (text or "").strip()))


@dataclass
class Result:
    code: int
    out: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Cli:
    def __init__(self, binary: str = "tgcloud", timeout: int = 180):
        self.binary = binary
        self.timeout = timeout

    async def run(self, args: list[str], cwd: str, token: str, timeout: int | None = None) -> Result:
        env = {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "HOME": cwd,                       # nada del usuario del contenedor
            "TGCLOUD_TOKEN": token,
            "NO_COLOR": "1", "FORCE_COLOR": "0", "CI": "1", "TERM": "dumb",
        }
        proc = await asyncio.create_subprocess_exec(
            *self.binary.split(), *args, "--no-pager", cwd=cwd, env=env,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        try:
            raw, _ = await asyncio.wait_for(proc.communicate(), timeout or self.timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return Result(124, "timeout")
        text = ANSI_RE.sub("", raw.decode("utf-8", errors="replace"))
        return Result(proc.returncode or 0, mask(text))

    async def fetch(self, cwd, token):
        return await self.run(["fetch"], cwd, token)

    async def status(self, cwd, token):
        return await self.run(["status"], cwd, token)

    async def schema_plan(self, cwd, token):
        return await self.run(["migrate", "--local", "--dry-run"], cwd, token)

    async def push(self, cwd, token):
        return await self.run(["push"], cwd, token, timeout=600)

    async def migrate(self, cwd, token, allow_destructive: bool):
        return await self.run(["migrate", "--yes" if allow_destructive else "--safe"], cwd, token, timeout=600)

    async def webhook(self, cwd, token):
        return await self.run(["webhook"], cwd, token)

    async def run_endpoint(self, cwd, token, name: str, payload: str = "{}"):
        """Ejecuta en los servidores de Telegram (no aquí) un endpoint local, sin subirlo."""
        return await self.run(["run", f"endpoints/{name}", payload], cwd, token, timeout=60)


# ───────────── lectura de la salida ─────────────
@dataclass
class Status:
    revision: int | None = None
    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    static_lines: list[str] = field(default_factory=list)
    stray: list[str] = field(default_factory=list)


_SECTIONS = {
    "new": re.compile(r"^New\b", re.I),
    "modified": re.compile(r"^Modified\b", re.I),
    "deleted": re.compile(r"^Deleted\b", re.I),
    "static": re.compile(r"^Static\b", re.I),
    "stray": re.compile(r"^(Stray|Not deployed|Ignored)\b", re.I),
}


def parse_status(text: str) -> Status:
    """Lee la salida de `tgcloud status`. Tras la cabecera «Static (…)», las secciones son de la web."""
    st = Status()
    m = re.search(r"Local revision:\s*(\d+)", text)
    if m:
        st.revision = int(m.group(1))
    current = None
    in_static = False
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            head = line.strip()
            if _SECTIONS["static"].match(head):
                in_static, current = True, None
                continue
            current = None
            for key in ("new", "modified", "deleted", "stray"):
                if _SECTIONS[key].match(head):
                    current = key
                    break
            continue
        item = line.strip()
        if in_static and current:
            st.static_lines.append(f"{current}: {item}")
        elif current in ("new", "modified", "deleted", "stray"):
            getattr(st, current).append(item)
    return st


@dataclass
class SchemaPlan:
    none: bool = False
    safe: list[str] = field(default_factory=list)          # +
    destructive: list[str] = field(default_factory=list)   # ✗ (borrados)
    manual: list[str] = field(default_factory=list)        # ~ / ! (hay que hacerlo a mano)
    undocumented: list[str] = field(default_factory=list)  # ? (en la base de datos pero no en schema.js: no se toca)
    raw: str = ""


def parse_schema_plan(text: str) -> SchemaPlan:
    sp = SchemaPlan(raw=text)
    if re.search(r"No schema changes|in sync", text, re.I) and not re.search(r"changes:", text):
        sp.none = True
        return sp
    for line in text.splitlines():
        m = re.match(r"^\s{1,4}([+✗~!?])\s+(\S.*?)\s{2,}(.+?)\s*$", line)
        if not m:
            continue
        sym, obj, what = m.groups()
        item = f"{obj} — {what}"
        if sym == "+":
            sp.safe.append(item)
        elif sym == "✗":
            sp.destructive.append(item)
        elif sym == "?":
            sp.undocumented.append(obj)
        else:
            sp.manual.append(item)
    if not (sp.safe or sp.destructive or sp.manual):
        sp.none = True
    return sp


def unmanaged_static(status_text: str) -> bool:
    """El bot tiene una Mini App publicada que este proyecto no gestiona (se quedará como está)."""
    return "does not manage" in status_text


def parse_push(text: str) -> dict:
    url = re.search(r"Static:\s*(https?://\S+)", text)
    return {"static_url": url.group(1) if url else None, "schema_pending": "Schema out of sync" in text}


def parse_webhook(text: str) -> dict:
    allowed = re.search(r"allowed updates:\s*(.+)", text)
    err = re.search(r"last error:\s*(.+)", text, re.I)
    return {
        "in_sync": "in sync" in text and "out of sync" not in text.lower(),
        "allowed": [a.strip() for a in allowed.group(1).split(",")] if allowed and "(none)" not in allowed.group(1) else [],
        "error": err.group(1).strip() if err else None,
    }
