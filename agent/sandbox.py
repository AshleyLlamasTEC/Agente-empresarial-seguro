"""Sandbox de rutas: confina toda operacion de archivos al workspace.

Reglas (deny by default):
  1. Nada fuera de la raiz del workspace.
  2. Sin escapes por '..', rutas absolutas ni UNC (\\\\servidor\\recurso).
  3. Sin enlaces simbolicos que apunten fuera del workspace.
  4. Sin nombres reservados de Windows ni flujos alternativos (ADS: 'archivo:stream').
"""

from __future__ import annotations

import os
import re
from pathlib import Path

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

DRIVE_ABSOLUTE = re.compile(r"^[A-Za-z]:")


class SandboxError(Exception):
    """Operacion de archivo rechazada por el sandbox."""


def _has_null(value: str) -> bool:
    return "\x00" in value or "\0" in value


def _check_components(path: Path, workspace: Path) -> None:
    for part in path.parts:
        stem = Path(part).stem.upper()
        if stem in WINDOWS_RESERVED:
            raise SandboxError(f"Nombre reservado de Windows no permitido: {part!r}")


def resolve_in_workspace(workspace: Path, candidate: str, must_exist: bool = False) -> Path:
    """Resuelve 'candidate' y garantiza que quede dentro de 'workspace'."""
    if candidate is None:
        raise SandboxError("Ruta vacia no permitida.")
    raw = str(candidate).strip()
    if not raw:
        raise SandboxError("Ruta vacia no permitida.")
    if _has_null(raw):
        raise SandboxError("Ruta con caracteres nulos no permitida.")

    normalized = raw.replace("\\", "/")

    if normalized.startswith("//"):
        raise SandboxError(f"Rutas UNC no permitidas: {raw}")
    if normalized.startswith("~"):
        raise SandboxError(f"Rutas con '~' no permitidas: {raw}")

    root = Path(workspace).resolve()

    if DRIVE_ABSOLUTE.match(normalized) or normalized.startswith("/"):
        target = Path(raw)
    else:
        if re.match(r"^[A-Za-z]::", normalized):
            raise SandboxError(f"Flujo alternativo (ADS) no permitido: {raw}")
        target = root / raw

    resolved = Path(os.path.normpath(target.resolve()))

    try:
        resolved.relative_to(root)
    except ValueError:
        raise SandboxError(
            f"Ruta fuera del workspace bloqueada: {resolved} (workspace: {root})"
        ) from None

    _check_components(resolved, root)

    if must_exist and not resolved.exists():
        raise SandboxError(f"La ruta no existe: {resolved}")

    return resolved


def is_inside(path: Path, workspace: Path) -> bool:
    try:
        Path(os.path.normpath(Path(path).resolve())).relative_to(Path(workspace).resolve())
        return True
    except ValueError:
        return False


def looks_like_path(token: str) -> bool:
    """Heuristica para decidir si un argumento de comando es una ruta."""
    if not token or token.startswith("-"):
        return False
    cleaned = token.strip("'\"")
    if cleaned.startswith("~") or cleaned.startswith("//"):
        return True
    if DRIVE_ABSOLUTE.match(cleaned):
        return True
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        return True
    if "/" in cleaned or "\\" in cleaned:
        return True
    return False
