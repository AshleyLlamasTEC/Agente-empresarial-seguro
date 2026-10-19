"""Carga y validacion de perfiles (consulta / desarrollo).

Los perfiles son archivos JSON versionables en el repositorio: son la
evidencia documental de que permisos tiene el agente y por que.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

CLOUD_MARKERS = ("-cloud", ":cloud", "/cloud", "gpt-", "claude", "gemini", "grok")

MIN_ITERATIONS, MAX_ITERATIONS = 1, 50
MAX_FILESIZE_FLOOR = 1024
MAX_FILESIZE_CEILING = 20 * 1024 * 1024


class ConfigError(Exception):
    """Configuracion invalida o insegura."""


@dataclass(frozen=True)
class Profile:
    name: str
    description: str
    model: str
    allow_write: bool
    allow_shell: bool
    require_confirmation: bool
    max_iterations: int
    max_file_bytes: int
    max_output_chars: int
    command_timeout_seconds: int
    commands_allow: tuple[str, ...]
    commands_deny: tuple[str, ...]
    path_deny_names: tuple[str, ...]
    path_deny_globs: tuple[str, ...]
    allow_db: bool = False
    db_read_only: bool = True
    db_allow_ddl: bool = False
    db_max_rows: int = 200

    @property
    def read_only(self) -> bool:
        return not self.allow_write and not self.allow_shell

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "model": self.model,
            "allow_write": self.allow_write,
            "allow_shell": self.allow_shell,
            "require_confirmation": self.require_confirmation,
            "max_iterations": self.max_iterations,
            "max_file_bytes": self.max_file_bytes,
            "max_output_chars": self.max_output_chars,
            "command_timeout_seconds": self.command_timeout_seconds,
            "commands_allow": list(self.commands_allow),
            "commands_deny": list(self.commands_deny),
            "path_deny_names": list(self.path_deny_names),
            "path_deny_globs": list(self.path_deny_globs),
            "allow_db": self.allow_db,
            "db_read_only": self.db_read_only,
            "db_allow_ddl": self.db_allow_ddl,
            "db_max_rows": self.db_max_rows,
        }


def _as_tuple(value, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"El campo '{field_name}' debe ser una lista.")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"El campo '{field_name}' solo admite texto no vacio.")
        out.append(item.strip())
    return tuple(out)


def assert_model_is_local(model: str) -> str:
    """Bloquea cualquier modelo que implique salida de datos a la nube."""
    if not isinstance(model, str) or not model.strip():
        raise ConfigError("El campo 'model' es obligatorio.")
    model = model.strip()
    low = model.lower()
    for marker in CLOUD_MARKERS:
        if marker in low:
            raise ConfigError(
                f"Modelo rechazado por politica de datos: '{model}'. "
                "Solo se permiten modelos locales de Ollama."
            )
    return model


def validate_profile(raw: dict, source: str) -> Profile:
    if not isinstance(raw, dict):
        raise ConfigError(f"El perfil {source} no es un objeto JSON.")

    allowed_keys = {
        "name", "description", "model", "allow_write", "allow_shell",
        "require_confirmation", "max_iterations", "max_file_bytes",
        "max_output_chars", "command_timeout_seconds", "commands_allow",
        "commands_deny", "path_deny_names", "path_deny_globs",
        "allow_db", "db_read_only", "db_allow_ddl", "db_max_rows",
    }
    unknown = set(raw) - allowed_keys
    if unknown:
        raise ConfigError(f"El perfil {source} tiene campos no permitidos: {sorted(unknown)}")

    name = raw.get("name")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", name or ""):
        raise ConfigError(f"Nombre de perfil invalido en {source}.")

    iterations = int(raw.get("max_iterations", 12))
    if not MIN_ITERATIONS <= iterations <= MAX_ITERATIONS:
        raise ConfigError(f"'max_iterations' debe estar entre {MIN_ITERATIONS} y {MAX_ITERATIONS}.")

    max_file = int(raw.get("max_file_bytes", 200_000))
    if not MAX_FILESIZE_FLOOR <= max_file <= MAX_FILESIZE_CEILING:
        raise ConfigError("'max_file_bytes' fuera de rango permitido.")

    timeout = int(raw.get("command_timeout_seconds", 60))
    if not 1 <= timeout <= 600:
        raise ConfigError("'command_timeout_seconds' debe estar entre 1 y 600.")

    allow_write = bool(raw.get("allow_write", False))
    allow_shell = bool(raw.get("allow_shell", False))
    require_confirmation = bool(raw.get("require_confirmation", True))

    if allow_write and not require_confirmation:
        raise ConfigError(
            "Un perfil con escritura habilitada debe exigir confirmacion humana "
            "('require_confirmation': true)."
        )

    commands_allow = _as_tuple(raw.get("commands_allow"), "commands_allow")
    if allow_shell and not commands_allow:
        raise ConfigError("Un perfil con shell habilitado requiere una lista blanca no vacia.")

    allow_db = bool(raw.get("allow_db", False))
    db_read_only = bool(raw.get("db_read_only", True))
    db_allow_ddl = bool(raw.get("db_allow_ddl", False))
    if db_allow_ddl and db_read_only:
        raise ConfigError("'db_allow_ddl' requiere 'db_read_only': false (se contradicen).")
    db_max_rows = int(raw.get("db_max_rows", 200))
    if not 1 <= db_max_rows <= 5000:
        raise ConfigError("'db_max_rows' debe estar entre 1 y 5000.")

    return Profile(
        name=name,
        description=str(raw.get("description", "")).strip(),
        model=assert_model_is_local(raw.get("model", "")),
        allow_write=allow_write,
        allow_shell=allow_shell,
        require_confirmation=require_confirmation,
        max_iterations=iterations,
        max_file_bytes=max_file,
        max_output_chars=int(raw.get("max_output_chars", 12_000)),
        command_timeout_seconds=timeout,
        commands_allow=commands_allow,
        commands_deny=_as_tuple(raw.get("commands_deny"), "commands_deny"),
        path_deny_names=_as_tuple(raw.get("path_deny_names"), "path_deny_names"),
        path_deny_globs=_as_tuple(raw.get("path_deny_globs"), "path_deny_globs"),
        allow_db=allow_db,
        db_read_only=db_read_only,
        db_allow_ddl=db_allow_ddl,
        db_max_rows=db_max_rows,
    )


def load_profile(name: str, profiles_dir: Path | None = None) -> Profile:
    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,30}", name or ""):
        raise ConfigError(f"Nombre de perfil invalido: {name!r}")
    directory = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    path = directory / f"{name}.json"
    if not path.is_file():
        available = sorted(p.stem for p in directory.glob("*.json"))
        raise ConfigError(f"Perfil '{name}' no encontrado en {directory}. Disponibles: {available}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"El perfil {path.name} no es JSON valido: {exc}") from exc
    return validate_profile(raw, path.name)


def available_profiles(profiles_dir: Path | None = None) -> list[str]:
    directory = Path(profiles_dir) if profiles_dir else PROFILES_DIR
    return sorted(p.stem for p in directory.glob("*.json"))


def env_defaults() -> dict:
    return {
        "host": os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").strip(),
        "model": os.environ.get("OLLAMA_MODEL", "").strip(),
        "audit_dir": os.environ.get("AGENT_AUDIT_DIR", "").strip(),
        "workspace": os.environ.get("AGENT_WORKSPACE", "").strip(),
    }
