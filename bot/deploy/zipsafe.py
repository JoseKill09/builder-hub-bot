"""Extrae un ZIP de forma segura.

- Rechaza rutas absolutas, «..», enlaces simbólicos y nombres raros.
- Topes de tamaño total, por archivo y de número de archivos (contra «bombas ZIP»).
- Si todo cuelga de una única carpeta raíz, la quita (es lo normal al comprimir una carpeta).
- Se salta lo que nunca debe subirse: node_modules/, .tgcloud/, .git/, .env*, __MACOSX/…
"""
from __future__ import annotations

import os
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SKIP_DIRS = {"node_modules", ".tgcloud", ".git", "__MACOSX", ".idea", ".vscode", ".DS_Store"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


class ZipError(Exception):
    """Error pensado para enseñárselo al usuario (texto en el campo .code)."""

    def __init__(self, code: str, **info):
        super().__init__(code)
        self.code = code
        self.info = info


@dataclass
class Extracted:
    files: list[str] = field(default_factory=list)       # rutas relativas extraídas
    skipped: list[str] = field(default_factory=list)     # se saltaron a propósito
    total_bytes: int = 0
    stripped_root: str | None = None


def _clean_name(name: str) -> PurePosixPath | None:
    name = name.replace("\\", "/")
    if name.endswith("/"):
        return None                                      # carpeta
    p = PurePosixPath(name)
    if p.is_absolute() or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise ZipError("zip_path", name=name)
    if any(part in ("..", "") for part in p.parts):
        raise ZipError("zip_path", name=name)
    if any(ord(ch) < 32 for ch in name):
        raise ZipError("zip_path", name=name)
    return p


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return info.create_system == 3 and stat.S_ISLNK(mode)


def extract(zip_path: str | os.PathLike, dest: str | os.PathLike, *, max_total: int = 50 * 1024 * 1024,
            max_file: int = 15 * 1024 * 1024, max_files: int = 3000) -> Extracted:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise ZipError("zip_bad") from exc
    with zf:
        infos = []
        for info in zf.infolist():
            p = _clean_name(info.filename)
            if p is None:
                continue
            if _is_symlink(info):
                raise ZipError("zip_symlink", name=info.filename)
            if info.flag_bits & 0x1:
                raise ZipError("zip_encrypted")
            infos.append((p, info))
        if not infos:
            raise ZipError("zip_empty")
        if len(infos) > max_files:
            raise ZipError("zip_too_many", n=len(infos), max=max_files)

        # ¿Todo dentro de una sola carpeta raíz? Se quita.
        roots = {p.parts[0] for p, _ in infos}
        strip = None
        if len(roots) == 1 and all(len(p.parts) > 1 for p, _ in infos):
            strip = next(iter(roots))

        out = Extracted(stripped_root=strip)
        total = 0
        for p, info in infos:
            parts = p.parts[1:] if strip else p.parts
            rel = PurePosixPath(*parts)
            if any(part in SKIP_DIRS for part in rel.parts[:-1]) or rel.name in SKIP_FILES \
                    or rel.name.startswith(".env") or rel.parts[0] in SKIP_DIRS:
                out.skipped.append(str(rel))
                continue
            if info.file_size > max_file:
                raise ZipError("zip_file_big", name=str(rel), mb=max_file // 1048576)
            total += info.file_size
            if total > max_total:
                raise ZipError("zip_too_big", mb=max_total // 1048576)
            target = dest.joinpath(*rel.parts)
            if not str(target.resolve()).startswith(str(dest.resolve()) + os.sep):
                raise ZipError("zip_path", name=str(rel))
            target.parent.mkdir(parents=True, exist_ok=True)
            # Se copia por trozos y se vuelve a comprobar el tamaño real (la cabecera puede mentir).
            written = 0
            with zf.open(info) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_file:
                        raise ZipError("zip_file_big", name=str(rel), mb=max_file // 1048576)
                    dst.write(chunk)
            out.files.append(str(rel))
            out.total_bytes += written
        return out
