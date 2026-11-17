"""Comprueba que un proyecto extraído cumple las reglas de Telegram Serverless antes de subirlo.

Devuelve una lista de avisos: level = 'error' (no se puede publicar) | 'warn' (se puede, pero conviene mirarlo).
Cada aviso lleva un código (para traducirlo) y datos; también un texto en inglés para devolvérselo a la IA.
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

SDK_MODULES = {"sdk", "sdk/db", "sdk/api", "sdk/fetch"}
ENDPOINT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Si el servidor no nos da la lista, se usa esta (CLI 0.2.0, 17-11-2026).
DEFAULT_HANDLERS = [
    "message", "edited_message", "stopped_message_generation", "channel_post", "edited_channel_post",
    "business_connection", "business_message", "edited_business_message", "deleted_business_messages",
    "inline_query", "chosen_inline_result", "callback_query", "widget_query", "shared_widget_query",
    "guest_message", "shipping_query", "pre_checkout_query", "purchased_paid_media", "subscription",
    "message_reaction", "message_reaction_count", "poll", "poll_answer", "my_chat_member", "chat_member",
    "chat_join_request", "chat_boost", "removed_chat_boost", "managed_bot",
]
STATIC_EXT = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".map", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".avif", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".txt", ".xml", ".webmanifest", ".wasm", ".mp3", ".mp4",
    ".webm", ".ogg", ".wav", ".pdf", ".csv", ".md",
}
IMPORT_RE = re.compile(
    r"""(?:^|[;\s])(?:import\s+(?:[\w*{}\s,$]+\s+from\s+)?|export\s+(?:\*|\{[^}]*\})\s+from\s+)(['"])([^'"]+)\1""",
    re.M,
)
DYNAMIC_IMPORT_RE = re.compile(r"""\bimport\s*\(""")
REQUIRE_RE = re.compile(r"""\brequire\s*\(\s*['"]""")
FK_RE = re.compile(r"""\.references\s*\(|\bforeignKey\s*\(""")


@dataclass
class Issue:
    level: str          # error | warn
    code: str
    file: str = ""
    detail: str = ""
    hint_en: str = ""   # explicación en inglés para pegársela a la IA


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    modules: list[str] = field(default_factory=list)   # módulos que se subirán (tgcloud/…)
    static_dir: str | None = None
    static_files: int = 0
    config: dict = field(default_factory=dict)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warn"]

    def add(self, level, code, file="", detail="", hint_en=""):
        self.issues.append(Issue(level, code, file, detail, hint_en))

    def for_ai(self) -> str:
        """Lista de problemas en inglés, lista para pegarla en el chat de la IA."""
        lines = ["Builder Hub could not deploy the project. Fix these problems and send a new ZIP:"]
        for i in self.issues:
            where = f" ({i.file})" if i.file else ""
            lines.append(f"- [{i.level.upper()}]{where} {i.hint_en or i.code}{(': ' + i.detail) if i.detail else ''}")
        return "\n".join(lines)


def strip_jsonc(text: str) -> str:
    """Quita comentarios // y /* */ (fuera de cadenas) y comas finales de un JSONC."""
    out, i, n, in_str, quote = [], 0, len(text), False, ""
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                in_str = False
            i += 1
            continue
        if ch in "\"'":
            in_str, quote = True, ch
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def read_config(root: Path, report: Report) -> dict:
    for name in ("tgcloud.jsonc", "tgcloud.json"):
        p = root / name
        if p.exists():
            try:
                cfg = json.loads(strip_jsonc(p.read_text("utf-8")) if name.endswith("c") else p.read_text("utf-8"))
            except (ValueError, UnicodeDecodeError) as exc:
                report.add("error", "config_bad", name, str(exc)[:120], f"{name} is not valid JSON/JSONC")
                return {}
            if not isinstance(cfg, dict):
                report.add("error", "config_bad", name, "", f"{name} must be a JSON object")
                return {}
            if (root / "tgcloud.jsonc").exists() and (root / "tgcloud.json").exists():
                report.add("error", "config_both", "", "", "Use tgcloud.jsonc OR tgcloud.json, not both")
            return cfg
    return {}


def _static_source(cfg: dict) -> str | None:
    st = cfg.get("static")
    if isinstance(st, str):
        return st
    if isinstance(st, dict) and isinstance(st.get("source"), str):
        return st["source"]
    return None


def _node_check(files: list[Path], node: str = "node") -> list[tuple[Path, str]]:
    """`node --check` de cada módulo como ESM (se copia con extensión .mjs)."""
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            dst = Path(tmp) / "m.mjs"
            dst.write_bytes(f.read_bytes())
            try:
                r = subprocess.run([node, "--check", str(dst)], capture_output=True, text=True, timeout=20)
            except (OSError, subprocess.TimeoutExpired) as exc:
                bad.append((f, f"no se pudo comprobar: {exc}"))
                continue
            if r.returncode != 0:
                msg = "\n".join(line for line in (r.stderr or "").splitlines()
                                if line.strip() and not line.startswith("Node.js") and str(dst) not in line
                                and not line.lstrip().startswith("at "))
                bad.append((f, msg.strip()[:600]))
    return bad


def validate(root: str | Path, handlers_allowed: list[str] | None = None, *, node: str = "node",
             check_syntax: bool = True) -> Report:
    root = Path(root)
    report = Report()
    handlers_allowed = handlers_allowed or DEFAULT_HANDLERS
    tg = root / "tgcloud"
    cfg = read_config(root, report)
    report.config = cfg

    if not tg.is_dir():
        hint = "The ZIP must contain a tgcloud/ folder with handlers/, endpoints/, lib/ and schema.js"
        if (root / "handlers").is_dir() or (root / "schema.js").exists():
            report.add("error", "old_layout", "", "", hint + " (move handlers/, lib/ and schema.js inside tgcloud/)")
        else:
            report.add("error", "no_tgcloud", "", "", hint)
        return report

    js_files: list[Path] = []
    for p in sorted(tg.rglob("*")):
        if p.is_dir():
            continue
        rel = p.relative_to(root).as_posix()
        inner = p.relative_to(tg).parts
        if p.suffix != ".js":
            report.add("warn", "not_js", rel, "", "Only .js files inside tgcloud/ are deployed; this file is ignored")
            continue
        top = inner[0]
        if len(inner) == 1:
            if inner[0] != "schema.js":
                report.add("error", "stray_js", rel, "", "Only schema.js may live directly in tgcloud/; move this file to lib/, handlers/ or endpoints/")
                continue
        elif top == "handlers":
            if len(inner) > 2:
                report.add("error", "handlers_nested", rel, "", "handlers/ must be flat (no subfolders)")
                continue
            name = p.stem
            if name not in handlers_allowed:
                report.add("error", "handler_name", rel, name,
                           f"handlers/{name}.js is not a Telegram update type. Valid names: {', '.join(handlers_allowed)}")
                continue
            if not p.read_text("utf-8", errors="replace").strip():
                report.add("warn", "handler_empty", rel, "", "Empty handler: that update type will be ignored")
        elif top == "endpoints":
            if len(inner) > 2:
                report.add("error", "endpoints_nested", rel, "", "endpoints/ must be flat (no subfolders)")
                continue
            if not ENDPOINT_NAME.match(p.stem):
                report.add("error", "endpoint_name", rel, p.stem, "Endpoint names must be like JavaScript identifiers (letters, digits, _), not starting with a digit")
                continue
        elif top != "lib":
            report.add("error", "stray_js", rel, "", "Only lib/ (subfolders allowed), handlers/ and endpoints/ may contain modules inside tgcloud/")
            continue
        js_files.append(p)
        report.modules.append(rel)

    if not any(m.startswith("tgcloud/handlers/") for m in report.modules) and not any(m.startswith("tgcloud/endpoints/") for m in report.modules):
        report.add("warn", "no_handlers", "", "", "There are no handlers or endpoints: the bot will not react to anything")

    # Importaciones y reglas del entorno
    for p in js_files:
        rel = p.relative_to(root).as_posix()
        src = p.read_text("utf-8", errors="replace")
        for _q, spec in IMPORT_RE.findall(src):
            if spec in SDK_MODULES:
                continue
            if spec.startswith("."):
                if not spec.endswith(".js"):
                    report.add("error", "import_ext", rel, spec, f"Relative import '{spec}' must end in .js")
                    continue
                target = (p.parent / spec).resolve()
                if not str(target).startswith(str(tg.resolve())):
                    report.add("error", "import_outside", rel, spec, f"Import '{spec}' points outside tgcloud/")
                elif not target.exists():
                    report.add("error", "import_missing", rel, spec, f"Import '{spec}' points to a file that does not exist")
            elif spec.startswith("lib/") or spec in ("schema",):
                if not (tg / (spec + ".js")).exists():
                    report.add("error", "import_missing", rel, spec, f"Module '{spec}' does not exist")
            elif spec.startswith("sdk"):
                report.add("error", "import_sdk", rel, spec, f"'{spec}' is not part of the SDK (use sdk, sdk/db, sdk/api or sdk/fetch)")
            else:
                report.add("error", "import_npm", rel, spec, f"'{spec}' looks like an npm package: npm packages are not available at runtime")
        if DYNAMIC_IMPORT_RE.search(src):
            report.add("warn", "dynamic_import", rel, "", "Dynamic import() is not documented for Serverless; prefer static imports")
        if REQUIRE_RE.search(src):
            report.add("error", "require", rel, "", "require() does not exist: use ES module imports")
        if "process.env" in src:
            report.add("warn", "process_env", rel, "", "process.env does not exist at runtime; store settings in the database")
        if rel == "tgcloud/schema.js" and FK_RE.search(src):
            report.add("error", "foreign_key", rel, "", "Foreign keys are not supported: .references() and foreignKey() throw; use plain integer columns")
        if not re.search(r"\bexport\s+default\b", src) and ("/handlers/" in rel or "/endpoints/" in rel):
            report.add("error", "no_default_export", rel, "", "Handlers and endpoints must have an `export default` function")

    if check_syntax and js_files:
        for f, msg in _node_check(js_files, node=node):
            report.add("error", "syntax", f.relative_to(root).as_posix(), msg, "JavaScript syntax error")

    # Mini App (archivos estáticos)
    src = _static_source(cfg)
    if src:
        sd = (root / src).resolve()
        if not str(sd).startswith(str(root.resolve())) or not sd.is_dir():
            report.add("error", "static_missing", "tgcloud.jsonc", src, f"static.source '{src}' must be a folder inside the ZIP with the built Mini App")
        else:
            report.static_dir = src
            files = [f for f in sd.rglob("*") if f.is_file()]
            report.static_files = len(files)
            if not (sd / "index.html").exists():
                report.add("warn", "static_no_index", src, "", "The Mini App folder has no index.html")
            if (sd / "api").exists():
                report.add("error", "static_api", f"{src}/api", "", "/api/ is reserved for endpoints: do not put files there")
            for f in files:
                if f.suffix.lower() not in STATIC_EXT:
                    report.add("warn", "static_ext", f.relative_to(root).as_posix(), "", "Unusual file type in the Mini App folder")
            if (sd / "package.json").exists() or (sd / "src").is_dir() and not (sd / "index.html").exists():
                report.add("warn", "static_unbuilt", src, "", "It looks like source code, not the built Mini App: Serverless does not run your build")
    elif (root / "dist").is_dir() or (root / "webapp").is_dir():
        report.add("warn", "static_unset", "", "", "There is a dist/ or webapp/ folder but tgcloud.jsonc has no \"static\": it will not be published")
    return report
