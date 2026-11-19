"""Versiones de los proyectos (lógica pura, sin Telegram ni base de datos).

- `peek(zip)`: lee del ZIP, sin descomprimirlo, el nombre, la versión y el CHANGELOG.
- `changelog_since(texto, versión)`: las novedades más nuevas que la versión publicada.
- `rollback_check(...)`: anti-rollback. Dice si se puede volver a una versión anterior y por qué no.
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

MANIFEST = "builderhub.json"
CHANGELOG = "CHANGELOG.md"
_MAX_META = 256 * 1024
_VER = re.compile(r"^##\s*\[?v?(\d+(?:\.\d+)*)\]?(.*)$", re.M)


def vkey(label: str | None) -> tuple | None:
    """'1.10' → (1, 10). None si la etiqueta no es numérica (p. ej. '#3')."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (label or "").strip(), re.I)
    if not m:
        return None
    parts = [int(x) for x in m.group(1).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def cmp(a: str | None, b: str | None) -> int | None:
    """-1, 0, 1 o None si no se pueden comparar."""
    ka, kb = vkey(a), vkey(b)
    if ka is None or kb is None:
        return None
    return (ka > kb) - (ka < kb)


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Meta:
    name: str = ""
    version: str = ""                 # etiqueta: builderhub.json → 1.er «## X.Y» del CHANGELOG → ''
    changelog: str = ""
    no_rollback_before: str = ""
    root: str = ""
    problems: list[str] = field(default_factory=list)


def _root(names: list[str]) -> str:
    tops = {PurePosixPath(n).parts[0] for n in names if n and not n.startswith("__MACOSX")}
    if len(tops) == 1:
        top = next(iter(tops))
        if any(n.startswith(top + "/") for n in names):
            return top
    return ""


def peek(zip_path: str | Path, filename: str = "") -> Meta:
    """Solo lee dos archivos pequeños; si algo falla devuelve lo que pueda (la validación de verdad es otra)."""
    meta = Meta()
    try:
        with zipfile.ZipFile(zip_path) as z:
            infos = {i.filename: i for i in z.infolist() if not i.is_dir()}
            meta.root = _root(list(infos))
            pre = meta.root + "/" if meta.root else ""

            def read(name: str) -> str:
                info = infos.get(pre + name)
                if not info or info.file_size > _MAX_META or info.flag_bits & 0x1:
                    return ""
                return z.read(info).decode("utf-8", errors="replace")

            raw = read(MANIFEST)
            if raw:
                try:
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        meta.name = str(data.get("name") or "")[:60].strip()
                        meta.version = str(data.get("version") or "")[:20].strip()
                        meta.no_rollback_before = str(data.get("no_rollback_before") or "")[:20].strip()
                except ValueError:
                    meta.problems.append("manifest_json")
            meta.changelog = read(CHANGELOG)[:20000]
    except (zipfile.BadZipFile, OSError, RuntimeError):
        meta.problems.append("zip")
    if not meta.version and meta.changelog:
        m = _VER.search(meta.changelog)
        if m:
            meta.version = m.group(1)
    if not meta.name:
        base = meta.root or re.sub(r"\.zip$", "", filename or "", flags=re.I)
        meta.name = re.sub(r"[-_ ]v?\d+(\.\d+)*$", "", base)[:60].strip()
    return meta


# ───────────── CHANGELOG ─────────────
def blocks(text: str) -> list[tuple[str, str]]:
    """[(versión, bloque)] en el orden del archivo (lo más nuevo arriba)."""
    out = []
    for part in re.split(r"^(?=##\s)", text or "", flags=re.M):
        if part.startswith("##"):
            m = _VER.match(part)
            out.append((m.group(1) if m else "", part.strip()))
    return out


def own_block(text: str, label: str | None) -> list[tuple[str, str]]:
    """El bloque del CHANGELOG de esa versión (o el primero si no aparece)."""
    bl = blocks(text)
    for v, b in bl:
        if label and v and cmp(v, label) == 0:
            return [(v, b)]
    return bl[:1]


def changelog_since(text: str, cur: str | None, limit: int = 8) -> list[tuple[str, str]]:
    """Bloques más nuevos que `cur`. Sin `cur` (o si no se puede comparar), solo el primero."""
    bl = blocks(text)
    if not bl:
        return []
    if not cur or vkey(cur) is None:
        return bl[:1]
    out = []
    for v, b in bl:
        c = cmp(v, cur)
        if c is not None and c <= 0:
            break
        out.append((v, b))
    return out[:limit]


def changelog_between(text: str, older: str | None, newer: str | None, limit: int = 8) -> list[tuple[str, str]]:
    """Bloques con older < versión <= newer (lo que se pierde al volver de `newer` a `older`)."""
    out = []
    for v, b in blocks(text):
        if cmp(v, newer) == 1:
            continue
        c = cmp(v, older)
        if c is None or c <= 0:
            if c is not None:
                break
            continue
        out.append((v, b))
    return out[:limit]


def block_lines(block: str, max_lines: int = 14) -> tuple[str, list[str]]:
    """(título, líneas) de un bloque «## X.Y — fecha» para mostrarlo en el chat."""
    lines = [x.rstrip() for x in block.splitlines()]
    head = re.sub(r"^#+\s*", "", lines[0]).strip() if lines else ""
    body = []
    for raw in lines[1:]:
        s = raw.strip()
        if not s:
            continue
        s = re.sub(r"^#{3,6}\s+", "", s)
        s = re.sub(r"^[-*•]\s+", "• ", s)
        if raw[:1] in (" ", "\t") and s.startswith("• "):
            s = "  ↳ " + s[2:]
        body.append(s)
    if len(body) > max_lines:
        body = body[:max_lines] + ["…"]
    return head, body


# ───────────── anti-rollback ─────────────
@dataclass
class Rollback:
    downgrade: bool = False
    blocked: list[str] = field(default_factory=list)    # (etiqueta que lo declara, piso) → no se puede
    floor: str = ""                                     # versión más antigua a la que se puede volver
    data_loss: list[str] = field(default_factory=list)  # versiones que borraron datos (aviso, no bloqueo)

    @property
    def ok(self) -> bool:
        return not self.blocked


def _floor_seq(versions: list[dict], declared: str) -> int | None:
    """Número de orden mínimo permitido por un «no_rollback_before»."""
    for v in versions:
        if v["label"] == declared:
            return v["seq"]
    k = vkey(declared)
    if k is None:
        return None
    ok = [v["seq"] for v in versions if vkey(v["label"]) is not None and vkey(v["label"]) >= k]
    return min(ok) if ok else None


def rollback_check(versions: list[dict], current_seq: int | None, target_label: str = "", target_seq: int | None = None) -> Rollback:
    """versions: [{seq, label, no_rollback_before, destructive}] de un proyecto.

    Bajar = volver a una versión guardada con número de orden menor que la publicada, o subir un ZIP
    cuya etiqueta es menor que la publicada. Se bloquea si alguna versión entre medias declara
    `no_rollback_before` por encima del destino; se avisa si alguna borró datos de la base de datos.
    """
    res = Rollback()
    cur = next((v for v in versions if v["seq"] == current_seq), None)
    if not cur:
        return res
    if target_seq is not None:
        if target_seq >= cur["seq"]:
            return res
        between = [v for v in versions if target_seq < v["seq"] <= cur["seq"]]
    else:
        c = cmp(target_label, cur["label"])
        if c is None or c >= 0:
            return res
        between = [v for v in versions if v["seq"] <= cur["seq"] and cmp(v["label"], target_label) == 1]
        if not between:
            between = [cur]
    res.downgrade = True
    tseq = target_seq
    floors = []
    for v in between:
        nrb = (v.get("no_rollback_before") or "").strip()
        if not nrb:
            continue
        fs = _floor_seq(versions, nrb)
        too_old = (tseq < fs) if (tseq is not None and fs is not None) else (cmp(target_label, nrb) == -1)
        if too_old:
            res.blocked.append(v["label"])
            floors.append(nrb)
    for v in between:
        if v.get("destructive"):
            res.data_loss.append(v["label"])
    if floors:
        res.floor = max(floors, key=lambda x: vkey(x) or ())
    return res


def floor_of(versions: list[dict], current_seq: int | None) -> tuple[str, int | None]:
    """(etiqueta del piso, número de orden) vigente para la versión publicada: no se puede bajar de ahí."""
    best = (None, None)
    for v in versions:
        if current_seq is not None and v["seq"] > current_seq:
            continue
        nrb = (v.get("no_rollback_before") or "").strip()
        if not nrb:
            continue
        fs = _floor_seq(versions, nrb)
        if fs is not None and (best[1] is None or fs > best[1]):
            best = (nrb, fs)
    return best[0] or "", best[1]
