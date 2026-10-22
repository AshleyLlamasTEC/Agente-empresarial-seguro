"""Herramientas del agente, todas mediadas por sandbox, politica y bitacora.

Cada operacion sigue el mismo flujo:
    validar ruta/entrada -> aplicar politica -> (confirmacion humana) -> ejecutar
    -> censurar secretos -> truncar -> registrar en bitacora
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import DbError, check_local_host, run_mysql, run_sqlite, validate_sql
from .dlp import is_sensitive_path, redact
from .policy import check_command, check_path
from .sandbox import SandboxError, resolve_in_workspace

DB_IDENTIFIER = re.compile(r"[A-Za-z0-9_.$-]{1,64}")


def _safe_sql(sql) -> str:
    """Censura secretos antes de guardar la sentencia en la bitacora."""
    if not isinstance(sql, str):
        return ""
    return redact(sql)[0]

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", ".nuxt", "target", ".idea", ".vscode", "coverage",
    ".pytest_cache", ".mypy_cache", ".tox", ".gradle", ".terraform", "vendor",
}
BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".pdf",
    ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dll", ".so", ".dylib",
    ".class", ".jar", ".war", ".pyc", ".pyo", ".woff", ".woff2", ".ttf", ".otf",
    ".mp3", ".mp4", ".avi", ".mov", ".sqlite", ".db", ".bin", ".iso", ".msi",
}

READ_ONLY_TOOLS = ("list_dir", "read_file", "grep")
WRITE_TOOLS = ("write_file",)
SHELL_TOOLS = ("run_command",)
DB_TOOLS = ("db_query",)

MAX_LIST_ENTRIES = 500
MAX_GREP_MATCHES = 200
MAX_GREP_PATTERN = 200
SAFE_ENV_KEYS = (
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC",
    "TEMP", "TMP", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
    "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "LANG", "LC_ALL",
    "PYTHONIOENCODING", "PYTHONUTF8",
)


@dataclass
class ToolResult:
    ok: bool
    output: str
    blocked: bool = False

    def as_text(self) -> str:
        prefix = "" if self.ok else ("BLOQUEADO: " if self.blocked else "ERROR: ")
        return f"{prefix}{self.output}"


def sha256_file(path: Path) -> str:
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncado: {len(text) - limit} caracteres omitidos]"


def safe_env() -> dict:
    env = {}
    for key in SAFE_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    env["AGENTE_MODO_SEGURO"] = "1"
    return env


class ToolRunner:
    def __init__(self, profile, workspace: Path, audit, confirmer, out=print,
                 dry_run: bool = False, backup_dir: Path | None = None):
        self.profile = profile
        self.workspace = Path(workspace).resolve()
        self.audit = audit
        self.confirmer = confirmer
        self.out = out
        self.dry_run = dry_run
        self.backup_dir = Path(backup_dir) if backup_dir else (audit.directory / "backups")

    # ---------------------------------------------------------------- catalogo
    def available_tools(self) -> tuple[str, ...]:
        tools = list(READ_ONLY_TOOLS)
        if self.profile.allow_write:
            tools += list(WRITE_TOOLS)
        if self.profile.allow_shell:
            tools += list(SHELL_TOOLS)
        if self.profile.allow_db:
            tools += list(DB_TOOLS)
        return tuple(tools)

    def describe(self) -> str:
        lines = [
            '- list_dir   args: {"path": "."}                 Lista archivos del workspace.',
            '- read_file  args: {"path": "archivo.py", "start_line": 1, "end_line": 200}',
            '                                                   Lee un archivo de texto.',
            '- grep       args: {"pattern": "texto", "path": ".", "glob": "*.py"}',
            '                                                   Busca patrones (regex) en el workspace.',
        ]
        if self.profile.allow_write:
            lines.append(
                '- write_file args: {"path": "archivo.py"} y el contenido en un bloque '
                "de codigo justo despues del JSON (recomendado), o bien "
                '{"path": "archivo.py", "content": "...con \\n escapados..."}. '
                "Requiere tu confirmacion."
            )
        if self.profile.allow_shell:
            allowed = ", ".join(self.profile.commands_allow)
            lines.append(
                '- run_command args: {"command": "git status"}   Ejecuta un comando de la lista '
                f"blanca: {allowed}. Sin encadenar, sin redirigir."
            )
        if self.profile.allow_db:
            modo = "solo lectura" if self.profile.db_read_only else "lectura y escritura"
            lines.append(
                '- db_query   args: {"engine": "sqlite", "database": "local.db", '
                '"sql": "SELECT * FROM users LIMIT 10"}   Base de datos LOCAL '
                f"({modo}). 'database' es la ruta del archivo .db/.sqlite RELATIVA al "
                "workspace (no inventes carpetas). Tambien engine 'mysql' con "
                "database/host/port/user. Una sentencia, sin comentarios. "
                "Requiere tu confirmacion."
            )
        lines.append('- final      args: {"answer": "texto"}          Termina y entrega el resultado.')
        return "\n".join(lines)

    # ---------------------------------------------------------------- despacho
    def call(self, name: str, args: dict) -> ToolResult:
        if not isinstance(args, dict):
            args = {}
        if name not in self.available_tools() and name != "final":
            result = ToolResult(False, f"Accion no disponible en el perfil "
                                       f"'{self.profile.name}': {name}", blocked=True)
            self.audit.record("tool_blocked", {"tool": name, "motivo": result.output, "args": args})
            return result

        handler = {
            "list_dir": self._list_dir,
            "read_file": self._read_file,
            "grep": self._grep,
            "write_file": self._write_file,
            "run_command": self._run_command,
            "db_query": self._db_query,
        }.get(name)

        if handler is None:
            return ToolResult(False, f"Accion desconocida: {name}", blocked=True)

        started = time.perf_counter()
        try:
            result = handler(args)
        except SandboxError as exc:
            result = ToolResult(False, str(exc), blocked=True)
        except Exception as exc:  # noqa: BLE001 - se reporta al modelo, no se propaga
            result = ToolResult(False, f"{type(exc).__name__}: {exc}")
        elapsed = round((time.perf_counter() - started) * 1000, 2)
        self.audit.record(
            "tool_call",
            {
                "tool": name,
                "args": args,
                "ok": result.ok,
                "blocked": result.blocked,
                "ms": elapsed,
            },
        )
        return result

    # ---------------------------------------------------------------- helpers
    def _resolve(self, raw_path: str, must_exist: bool = False) -> Path:
        return resolve_in_workspace(self.workspace, raw_path, must_exist=must_exist)

    def _guard(self, path: Path) -> ToolResult | None:
        sensitive, reason = is_sensitive_path(path, self.profile.path_deny_names)
        if sensitive:
            return ToolResult(False, f"Archivo protegido ({reason}): {path.name}", blocked=True)
        decision = check_path(path, self.profile)
        if not decision:
            return ToolResult(False, decision.reason, blocked=True)
        return None

    def _confirm(self, description: str) -> bool:
        if not self.profile.require_confirmation:
            return True
        return bool(self.confirmer(description))

    # ---------------------------------------------------------------- acciones
    def _list_dir(self, args: dict) -> ToolResult:
        target = self._resolve(args.get("path", "."), must_exist=True)
        if not target.is_dir():
            return ToolResult(False, f"No es un directorio: {target}")
        decision = check_path(target, self.profile)
        if not decision:
            return ToolResult(False, decision.reason, blocked=True)

        entries = []
        omitted = 0
        for entry in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
            if entry.name in SKIP_DIRS:
                omitted += 1
                continue
            sensitive, _ = is_sensitive_path(entry, self.profile.path_deny_names)
            if sensitive:
                entries.append(f"[PROTEGIDO] {entry.name}/" if entry.is_dir() else f"[PROTEGIDO] {entry.name}")
                continue
            if entry.is_dir():
                entries.append(f"{entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = -1
                entries.append(f"{entry.name}  ({size} bytes)")
            if len(entries) >= MAX_LIST_ENTRIES:
                entries.append(f"... [lista truncada a {MAX_LIST_ENTRIES} entradas]")
                break

        if not entries:
            return ToolResult(True, f"Directorio vacio: {target}")
        header = f"Contenido de {target} ({len(entries)} entradas):"
        if omitted:
            header += f" [carpetas ignoradas: {omitted}]"
        return ToolResult(True, header + "\n" + "\n".join(entries))

    def _read_file(self, args: dict) -> ToolResult:
        target = self._resolve(args.get("path", ""), must_exist=True)
        guard = self._guard(target)
        if guard:
            return guard
        if not target.is_file():
            return ToolResult(False, f"No es un archivo: {target}")

        size = target.stat().st_size
        if size > self.profile.max_file_bytes:
            return ToolResult(
                False,
                f"Archivo demasiado grande ({size} bytes > {self.profile.max_file_bytes}). "
                "Usa rangos de lineas o grep.",
            )

        start = max(1, int(args.get("start_line", 1) or 1))
        end = args.get("end_line")
        end = int(end) if end else None

        raw = target.read_text(encoding="utf-8", errors="replace")
        lines = raw.splitlines()
        window = lines[start - 1: end] if end else lines[start - 1:]

        redacted_count = 0
        body_lines = []
        for offset, line in enumerate(window, start=start):
            clean, count = redact(line)
            redacted_count += count
            body_lines.append(f"{offset:>5} | {clean}")

        body = truncate("\n".join(body_lines), self.profile.max_output_chars)
        note = f" [secretos censurados: {redacted_count}]" if redacted_count else ""
        self.audit.record(
            "read_file",
            {
                "path": str(target),
                "lineas": [start, start + len(window) - 1],
                "sha256": sha256_file(target),
                "secretos_censurados": redacted_count,
            },
        )
        return ToolResult(
            True,
            f"Archivo {target} (lineas {start}-{start + len(window) - 1} de {len(lines)}){note}\n{body}",
        )

    def _grep(self, args: dict) -> ToolResult:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            return ToolResult(False, "Falta 'pattern'.")
        if len(pattern) > MAX_GREP_PATTERN:
            return ToolResult(False, f"Patron demasiado largo (maximo {MAX_GREP_PATTERN}).")
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return ToolResult(False, f"Regex invalida: {exc}")

        root = self._resolve(args.get("path", "."), must_exist=True)
        if not root.is_dir():
            return ToolResult(False, f"La ruta de busqueda no es un directorio: {root}")

        glob = args.get("glob")
        from fnmatch import fnmatch

        matches: list[str] = []
        scanned = 0
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for filename in files:
                if glob and not fnmatch(filename, glob):
                    continue
                candidate = Path(current) / filename
                if candidate.suffix.lower() in BINARY_SUFFIXES:
                    continue
                sensitive, _ = is_sensitive_path(candidate, self.profile.path_deny_names)
                if sensitive:
                    continue
                try:
                    if candidate.stat().st_size > self.profile.max_file_bytes:
                        continue
                    content = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                scanned += 1
                for lineno, line in enumerate(content.splitlines(), start=1):
                    if regex.search(line):
                        clean, _ = redact(line.strip()[:300])
                        try:
                            shown = candidate.relative_to(self.workspace).as_posix()
                        except ValueError:
                            shown = str(candidate)
                        matches.append(f"{shown}:{lineno}: {clean}")
                        if len(matches) >= MAX_GREP_MATCHES:
                            break
                if len(matches) >= MAX_GREP_MATCHES:
                    break
            if len(matches) >= MAX_GREP_MATCHES:
                break

        if not matches:
            return ToolResult(True, f"Sin coincidencias para {pattern!r} ({scanned} archivos revisados).")
        body = truncate("\n".join(matches), self.profile.max_output_chars)
        return ToolResult(True, f"{len(matches)} coincidencias ({scanned} archivos revisados):\n{body}")

    def _write_file(self, args: dict) -> ToolResult:
        if not self.profile.allow_write:
            return ToolResult(False, "El perfil no permite escritura.", blocked=True)

        path_arg = args.get("path", "")
        content = args.get("content")
        if not isinstance(content, str):
            return ToolResult(
                False,
                "Falta el contenido del archivo. Recuerda el protocolo: envia el JSON "
                "solo con la ruta y coloca el contenido COMPLETO en un bloque de codigo "
                "justo despues del JSON, asi:\n"
                '{"thought": "...", "action": "write_file", "args": {"path": "app.js"}}\n'
                "```\n...contenido completo del archivo...\n```",
            )
        if len(content.encode("utf-8")) > self.profile.max_file_bytes:
            return ToolResult(False, "El contenido excede el tamano maximo permitido.")

        target = self._resolve(path_arg)
        guard = self._guard(target)
        if guard:
            return guard

        existed = target.exists()
        before_hash = sha256_file(target)
        preview = truncate(content, 1200)

        description = (
            f"{'MODIFICAR' if existed else 'CREAR'} {target}\n"
            f"--- contenido propuesto ---\n{preview}\n---------------------------"
        )

        if self.dry_run:
            self.audit.record("write_file_dry_run", {"path": str(target), "existed": existed})
            return ToolResult(
                True,
                "[SIMULACION EXITOSA] El operador activo el modo simulacion (--dry-run), "
                "por lo que NO se escribio nada. ESTO NO ES UN ERROR: es el comportamiento "
                "esperado.\n"
                f"{description}\n\n"
                "Reporta al operador el cambio propuesto como simulado y usa la accion "
                "'final' para cerrar.",
            )

        if not self._confirm(description):
            self.audit.record("write_file_denied_by_user", {"path": str(target)})
            return ToolResult(False, "El operador rechazo la escritura.", blocked=True)

        backup_path = ""
        if existed:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            try:
                relative = target.relative_to(self.workspace).as_posix().replace("/", "__")
            except ValueError:
                relative = target.name
            backup_path = str(self.backup_dir / f"{relative}.{stamp}.bak")
            shutil.copy2(target, backup_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
        after_hash = sha256_file(target)

        self.audit.record(
            "write_file",
            {
                "path": str(target),
                "existed": existed,
                "sha256_before": before_hash,
                "sha256_after": after_hash,
                "bytes": len(content.encode("utf-8")),
                "respaldo": backup_path,
            },
        )
        msg = f"{'Modificado' if existed else 'Creado'}: {target}"
        if backup_path:
            msg += f"\nRespaldo: {backup_path}"
        return ToolResult(True, msg)

    def _run_command(self, args: dict) -> ToolResult:
        if not self.profile.allow_shell:
            return ToolResult(False, "El perfil no permite ejecutar comandos.", blocked=True)

        command = args.get("command")
        if not isinstance(command, str):
            return ToolResult(False, "Falta 'command' (texto).")

        decision = check_command(command, self.profile, self.workspace)
        if not decision:
            self.audit.record("command_blocked", {"command": command, "motivo": decision.reason})
            return ToolResult(False, decision.reason, blocked=True)

        if self.dry_run:
            self.audit.record("command_dry_run", {"command": command, "argv": list(decision.argv)})
            return ToolResult(
                True,
                f"[SIMULACION EXITOSA] Modo simulacion activo: no se ejecuto nada. "
                f"NO ES UN ERROR. Se ejecutaria: {' '.join(decision.argv)}\n\n"
                "Reporta esto al operador y usa la accion 'final' para cerrar.",
            )

        if not self._confirm(f"EJECUTAR COMANDO en {self.workspace}:\n  {command}"):
            self.audit.record("command_denied_by_user", {"command": command})
            return ToolResult(False, "El operador rechazo la ejecucion.", blocked=True)

        started = time.perf_counter()
        try:
            completed = subprocess.run(
                list(decision.argv),
                cwd=str(self.workspace),
                env=safe_env(),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=self.profile.command_timeout_seconds,
                shell=False,
            )
        except FileNotFoundError:
            return ToolResult(False, f"Ejecutable no encontrado: {decision.argv[0]}")
        except subprocess.TimeoutExpired:
            self.audit.record("command_timeout", {"command": command})
            return ToolResult(False, f"Tiempo agotado ({self.profile.command_timeout_seconds}s).")

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        stdout, _ = redact(completed.stdout or "")
        stderr, _ = redact(completed.stderr or "")

        self.audit.record(
            "command_run",
            {
                "command": command,
                "argv": list(decision.argv),
                "returncode": completed.returncode,
                "ms": elapsed,
            },
        )

        body = f"$ {command}\n(codigo de salida: {completed.returncode}, {elapsed} ms)"
        if stdout.strip():
            body += "\n--- salida ---\n" + truncate(stdout.strip(), self.profile.max_output_chars)
        if stderr.strip():
            body += "\n--- errores ---\n" + truncate(stderr.strip(), self.profile.max_output_chars)
        return ToolResult(completed.returncode == 0, body)

    def _db_query(self, args: dict) -> ToolResult:
        if not self.profile.allow_db:
            return ToolResult(False, "El perfil no permite acceso a base de datos.", blocked=True)

        engine = str(args.get("engine", "sqlite")).strip().lower()
        sql = args.get("sql", "")
        if engine not in {"sqlite", "mysql"}:
            return ToolResult(False, "Motor no soportado. Usa 'sqlite' o 'mysql'.")

        try:
            decision = validate_sql(sql, read_only=self.profile.db_read_only,
                                    allow_ddl=self.profile.db_allow_ddl, engine=engine)
        except DbError as exc:
            self.audit.record("db_blocked", {"engine": engine, "motivo": str(exc),
                                             "sql": _safe_sql(sql)})
            return ToolResult(False, str(exc), blocked=True)

        try:
            if engine == "sqlite":
                db_path = self._resolve(args.get("database", ""), must_exist=True)
                guard = self._guard(db_path)
                if guard:
                    return guard
                target = f"sqlite://{db_path.name}"
                params = {"database": db_path}
            else:
                host = check_local_host(str(args.get("host") or "127.0.0.1"))
                try:
                    port = int(args.get("port") or 3306)
                except (TypeError, ValueError):
                    raise DbError("El puerto debe ser un numero.")
                if not 1 <= port <= 65535:
                    raise DbError("Puerto fuera de rango (1-65535).")
                user = str(args.get("user") or os.environ.get("AGENT_DB_USER") or "root")
                database = str(args.get("database") or "")
                if not DB_IDENTIFIER.fullmatch(database):
                    raise DbError("Nombre de base invalido o ausente.")
                if not DB_IDENTIFIER.fullmatch(user):
                    raise DbError("Usuario de base invalido.")
                password = os.environ.get("AGENT_DB_PASSWORD", "")
                target = f"mysql://{user}@{host}:{port}/{database}"
                params = {"host": host, "port": port, "user": user,
                          "password": password, "database": database}
        except DbError as exc:
            self.audit.record("db_blocked", {"engine": engine, "motivo": str(exc),
                                             "sql": _safe_sql(sql)})
            return ToolResult(False, str(exc), blocked=True)

        etiqueta = {"read": "LECTURA", "write": "ESCRITURA", "ddl": "DDL"}[decision.kind]
        sql_audit = _safe_sql(decision.sql)

        if self.dry_run:
            self.audit.record("db_dry_run", {"engine": engine, "target": target,
                                             "kind": decision.kind, "sql": sql_audit})
            return ToolResult(
                True,
                f"[SIMULACION EXITOSA] Modo simulacion activo: no se ejecuto nada. "
                f"NO ES UN ERROR.\nSe ejecutaria ({etiqueta}) en {target}:\n  {decision.sql}\n\n"
                "Reporta esto al operador y usa la accion 'final' para cerrar.",
            )

        descripcion = f"EJECUTAR SQL ({etiqueta}) en {target}:\n  {decision.sql}"
        if not self._confirm(descripcion):
            self.audit.record("db_denied_by_user", {"target": target, "sql": sql_audit})
            return ToolResult(False, "El operador rechazo la consulta.", blocked=True)

        started = time.perf_counter()
        try:
            if engine == "sqlite":
                ok, salida, filas = run_sqlite(params["database"], decision.sql,
                                               read_only=self.profile.db_read_only,
                                               timeout=self.profile.command_timeout_seconds,
                                               max_rows=self.profile.db_max_rows)
            else:
                ok, salida, filas = run_mysql(params["host"], params["port"], params["user"],
                                              params["password"], params["database"],
                                              decision.sql,
                                              timeout=self.profile.command_timeout_seconds,
                                              env=safe_env(),
                                              max_bytes=max(65536,
                                                            self.profile.max_output_chars * 4))
        except DbError as exc:
            self.audit.record("db_blocked", {"engine": engine, "target": target,
                                             "motivo": str(exc)})
            return ToolResult(False, str(exc), blocked=True)

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        salida, _ = redact(salida or "")
        self.audit.record(
            "db_query",
            {"engine": engine, "target": target, "kind": decision.kind,
             "sql": sql_audit, "rows": filas, "ok": ok, "ms": elapsed},
        )
        cuerpo = f"$ {decision.sql}\nen {target} ({etiqueta}, {elapsed} ms, filas: {filas})"
        if salida.strip():
            cuerpo += "\n--- resultado ---\n" + truncate(salida.strip(),
                                                        self.profile.max_output_chars)
        return ToolResult(ok, cuerpo)

