"""Un despliegue de principio a fin: conectar → cargar ZIP → plan → publicar → limpiar.

Cada trabajo vive en su carpeta temporal (WORK_DIR/job-…) y el token solo existe en memoria,
dentro del objeto. cleanup() borra la carpeta y olvida el token.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import cli as C
from .validate import DEFAULT_HANDLERS, Report, validate
from .zipsafe import ZipError, extract


class DeployError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


MENU_TEXT = {"es": "Abrir", "en": "Open"}
MENU_JS = """import { api } from 'sdk';
export default async function (input) {
  const cur = await api.getChatMenuButton({});
  if (cur && cur.type === 'web_app') return 'kept';
  await api.setChatMenuButton({ menu_button: { type: 'web_app', text: String(input.text || 'Open').slice(0, 16), web_app: { url: String(input.url) } } });
  return 'set';
}
"""


@dataclass
class Plan:
    report: Report
    status: C.Status
    schema: C.SchemaPlan
    unmanaged_static: bool = False
    skipped: list[str] = field(default_factory=list)
    stripped_root: str | None = None

    @property
    def nothing_to_do(self) -> bool:
        return not (self.status.new or self.status.modified or self.status.deleted or self.status.static_lines
                    or self.schema.safe or self.schema.destructive)


@dataclass
class Outcome:
    ok: bool
    static_url: str | None = None
    migrated: str = ""            # '', 'safe', 'all'
    migrate_out: str = ""
    webhook: dict = field(default_factory=dict)
    menu: str = ""                # '', 'set' (activado ahora), 'kept' (el bot ya tenía uno), 'failed'
    error: str = ""


class Job:
    def __init__(self, user_id: int, token: str, work_root: str | Path, cli: C.Cli):
        self.id = uuid.uuid4().hex[:10]
        self.user_id = user_id
        self._token = token.strip()
        self.app = C.app_id(self._token)
        self.cli = cli
        self.dir = Path(work_root) / f"job-{self.id}"
        self.project = self.dir / "p"
        self.created = time.time()
        self.handlers = list(DEFAULT_HANDLERS)
        self.lang = "en"
        self.revision: int | None = None
        self.deployed_modules = 0
        self.plan: Plan | None = None
        self.state = "new"

    # ── 1) conectar: comprueba el token y trae el estado de la nube
    async def connect(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.project / ".tgcloud").mkdir(parents=True, exist_ok=True)
        r = await self.cli.fetch(str(self.project), self._token)
        if not r.ok:
            low = r.out.lower()
            code = "token_bad" if any(w in low for w in ("401", "unauthor", "invalid token", "token", "403")) else "cloud_error"
            raise DeployError(code, r.out[-600:])
        m = re.search(r"(\d+) modules \(revision (\d+)\)", r.out)
        if m:
            self.deployed_modules, self.revision = int(m.group(1)), int(m.group(2))
        try:
            caps = json.loads((self.project / ".tgcloud" / "capabilities.json").read_text("utf-8"))
            for d in caps.get("directories", []):
                if d.get("name") == "handlers" and d.get("allowed_names"):
                    self.handlers = list(d["allowed_names"])
        except (OSError, ValueError):
            pass
        self.state = "await_zip"

    # ── 2) cargar el ZIP, validarlo y preparar el plan
    async def load_zip(self, zip_path: str | Path, *, max_total_mb: int = 50, check_syntax: bool = True) -> Plan:
        # Se vacía lo de un ZIP anterior (sin tocar .tgcloud/).
        for child in self.project.iterdir():
            if child.name != ".tgcloud":
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        try:
            ex = extract(zip_path, self.project, max_total=max_total_mb * 1048576)
        except ZipError as exc:
            raise DeployError(exc.code, json.dumps(exc.info, ensure_ascii=False)) from exc
        report = validate(self.project, self.handlers, check_syntax=check_syntax)
        st = C.Status()
        sp = C.SchemaPlan(none=True)
        unmanaged = False
        if not report.errors:
            rs = await self.cli.status(str(self.project), self._token)
            if not rs.ok:
                raise DeployError("cloud_error", rs.out[-600:])
            st = C.parse_status(rs.out)
            unmanaged = C.unmanaged_static(rs.out)
            if (self.project / "tgcloud" / "schema.js").exists():
                rp = await self.cli.schema_plan(str(self.project), self._token)
                sp = C.parse_schema_plan(rp.out) if rp.ok else C.SchemaPlan(manual=[rp.out[-300:]])
        self.plan = Plan(report, st, sp, unmanaged, ex.skipped, ex.stripped_root)
        self.state = "planned" if not report.errors else "await_zip"
        return self.plan

    # ── 3) publicar
    async def publish(self, allow_destructive: bool = False) -> Outcome:
        if self.state != "planned" or not self.plan:
            raise DeployError("no_plan")
        self.state = "publishing"
        r = await self.cli.push(str(self.project), self._token)
        if not r.ok:
            self.state = "planned"
            code = "conflict" if "revision" in r.out.lower() or "pull" in r.out.lower() else "push_failed"
            return Outcome(False, error=code + ": " + r.out[-800:])
        info = C.parse_push(r.out)
        # Si la Mini App no cambió, `push` no imprime su URL; es siempre https://<app>.tgcloud.ai/
        url = info["static_url"] or (f"https://{self.app}.tgcloud.ai/" if self.plan.report.static_dir else None)
        out = Outcome(True, static_url=url)
        sp = self.plan.schema
        if info["schema_pending"] or sp.safe or sp.destructive:
            mode_all = allow_destructive and bool(sp.destructive)
            m = await self.cli.migrate(str(self.project), self._token, mode_all)
            out.migrated = "all" if mode_all else "safe"
            out.migrate_out = m.out[-800:]
            if not m.ok:
                out.ok = False
                out.error = "migrate_failed: " + m.out[-800:]
        w = await self.cli.webhook(str(self.project), self._token)
        out.webhook = C.parse_webhook(w.out) if w.ok else {}
        if out.ok and out.static_url and (self.plan.report.static_dir or self.plan.status.static_lines):
            out.menu = await self._activate_menu(out.static_url)
        self.state = "done" if out.ok else "planned"
        return out

    async def _activate_menu(self, url: str) -> str:
        """Deja el botón de menú del bot apuntando a su Mini App (si el bot no tiene ya uno propio).

        El fragmento corre en los servidores de Telegram con `tgcloud run`; se escribe, se ejecuta y se borra:
        no forma parte del proyecto subido ni corre en el NAS.
        """
        ep = self.project / "tgcloud" / "endpoints"
        f = ep / "bhmenu.js"
        try:
            ep.mkdir(parents=True, exist_ok=True)
            f.write_text(MENU_JS, encoding="utf-8")
            r = await self.cli.run_endpoint(str(self.project), self._token, "bhmenu", json.dumps({"url": url, "text": MENU_TEXT.get(self.lang, "Open")}))
        except Exception:  # noqa: BLE001
            return "failed"
        finally:
            f.unlink(missing_ok=True)
        if not r.ok:
            return "failed"
        return "kept" if "kept" in r.out else "set" if "set" in r.out else "failed"

    def secret(self) -> str:
        """Solo para guardarlo cifrado cuando el usuario elige «Recordar acceso»."""
        return self._token

    # ── 4) limpiar: se borra todo y se olvida el token
    def cleanup(self) -> None:
        self._token = ""
        shutil.rmtree(self.dir, ignore_errors=True)
        self.state = "closed"
