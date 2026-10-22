"""Acceso a base de datos LOCAL unicamente.

Reglas de esta capa:
- Solo se permite loopback (127.0.0.1 / localhost / ::1). Cualquier otro host
  se bloquea, aunque venga en los argumentos.
- Una sola sentencia por consulta, sin comentarios SQL.
- Clasificacion estricta: lectura / escritura / DDL. El perfil decide que se
  permite; por defecto SOLO lectura.
- Todo se ejecuta sin shell, con entorno saneado, y se registra en la bitacora.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
READ_KEYWORDS = {"select", "explain", "with", "show", "describe", "desc", "pragma",
                 "values", "table"}
WRITE_KEYWORDS = {"insert", "update", "delete", "replace", "upsert", "merge", "call", "do"}
DDL_KEYWORDS = {"create", "drop", "alter", "truncate", "rename", "grant", "revoke",
                "attach", "detach", "vacuum", "reindex", "analyze"}

_KIND_RANK = {"read": 0, "write": 1, "ddl": 2}

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Tokens que permiten leer/escribir archivos, ejecutar codigo o agotar el servidor.
# Se bloquean en CUALQUIER posicion de la sentencia, no solo al inicio.
_FORBIDDEN_SUBSTRINGS = (
    "load_file", "into outfile", "into dumpfile", "load data",
    "xp_cmdshell", "sp_executesql", "openrowset", "opendatasource",
    "sys_exec", "sys_eval", "into @", "procedure analyse",
)

# Llamadas a funciones peligrosas (se buscan con parentesis).
_FORBIDDEN_CALLS = (
    "benchmark", "sleep", "get_lock", "release_lock", "updatexml",
    "extractvalue", "analyse",
)

# Palabras que convierten una sentencia aparentemente de lectura en escritura/DDL
# (p. ej. "WITH x AS (...) DELETE FROM t"). Se excluyen las que son funciones
# (REPLACE(...), TRUNCATE(...)) gracias al lookahead de parentesis.
_DML_TOKEN = re.compile(
    r"\b(insert|update|delete|replace|merge|upsert|create|drop|alter|truncate|"
    r"rename|grant|revoke|attach|detach|vacuum|reindex|analyze|call|do|into)\b"
    r"(?!\s*\()",
    re.I,
)


class DbError(Exception):
    """Sentencia o destino no permitido."""


@dataclass
class SqlDecision:
    sql: str
    kind: str  # "read" | "write" | "ddl"


def _first_keyword(sql: str) -> str:
    match = re.match(r"\s*([A-Za-z_]+)", sql)
    return match.group(1).lower() if match else ""


def validate_sql(sql: str, read_only: bool = True, allow_ddl: bool = False,
                 engine: str = "sqlite") -> SqlDecision:
    """Valida y clasifica una sentencia. Lanza DbError si no es admisible.

    La clasificacion es conservadora: se revisa la sentencia COMPLETA (no solo la
    primera palabra) para detectar escrituras escondidas en CTEs, `INTO`, etc.
    """
    if not isinstance(sql, str) or not sql.strip():
        raise DbError("Falta la sentencia SQL.")
    if "\x00" in sql:
        raise DbError("La sentencia contiene caracteres nulos.")

    cuerpo = sql.strip()
    if _CONTROL_CHARS.search(cuerpo):
        raise DbError("La sentencia contiene caracteres de control no permitidos.")

    if engine == "mysql":
        # El cliente `mysql` interpreta comandos de cliente (\g, \!, source...).
        if "\\" in cuerpo or "\n" in cuerpo or "\r" in cuerpo:
            raise DbError("En MySQL la sentencia debe ser una sola linea y sin '\\'.")

    if "--" in cuerpo or "/*" in cuerpo or "*/" in cuerpo:
        raise DbError("No se permiten comentarios SQL.")
    if cuerpo.endswith(";"):
        cuerpo = cuerpo[:-1].rstrip()
    if ";" in cuerpo:
        raise DbError("Solo se permite una sentencia por consulta.")

    keyword = _first_keyword(cuerpo)
    if not keyword:
        raise DbError("No se pudo identificar la sentencia SQL.")
    if keyword in DDL_KEYWORDS:
        kind = "ddl"
    elif keyword in WRITE_KEYWORDS:
        kind = "write"
    elif keyword in READ_KEYWORDS:
        kind = "read"
    else:
        raise DbError(f"Sentencia no permitida: '{keyword}'. Usa SELECT/EXPLAIN o algo conocido.")

    plano = " ".join(cuerpo.split())
    bajo = plano.lower()
    for token in _FORBIDDEN_SUBSTRINGS:
        if token in bajo:
            raise DbError(f"Contenido prohibido en la sentencia: '{token}'.")
    for nombre in _FORBIDDEN_CALLS:
        if re.search(rf"\b{nombre}\s*\(", bajo):
            raise DbError(f"Funcion prohibida en la sentencia: '{nombre}'.")

    for match in _DML_TOKEN.finditer(plano):
        oculto = match.group(1).lower()
        candidato = "ddl" if oculto in DDL_KEYWORDS else "write"
        if _KIND_RANK[candidato] > _KIND_RANK[kind]:
            kind = candidato

    if kind == "ddl" and not allow_ddl:
        raise DbError("Las sentencias DDL (CREATE/DROP/ALTER/...) estan prohibidas por politica.")
    if read_only and kind != "read":
        raise DbError("Este perfil solo permite consultas de lectura (SELECT/EXPLAIN/SHOW/PRAGMA).")
    return SqlDecision(cuerpo, kind)


def check_local_host(host: str) -> str:
    if not isinstance(host, str) or host.strip().lower() not in LOCAL_HOSTS:
        raise DbError(f"Host de base de datos no local, bloqueado: {host!r}.")
    return host.strip()


def mysql_client() -> str | None:
    return shutil.which("mysql")


def format_rows(columns, rows, max_rows: int) -> str:
    header = " | ".join(str(c) for c in columns)
    body = "\n".join(" | ".join("" if v is None else str(v) for v in row) for row in rows)
    text = f"{header}\n{'-' * min(len(header), 80)}\n{body}" if header else body
    if rows and len(rows) >= max_rows:
        text += f"\n... [se mostraron las primeras {max_rows} filas]"
    return text


def run_sqlite(database, sql: str, read_only: bool, timeout: int, max_rows: int):
    """Ejecuta en SQLite (libreria estandar). Devuelve (ok, texto, filas)."""
    path = Path(database)
    if not path.is_file():
        raise DbError(f"No existe la base SQLite: {path}")
    mode = "ro" if read_only else "rw"
    con = sqlite3.connect(f"file:{path.as_posix()}?mode={mode}", uri=True, timeout=timeout)
    try:
        con.execute(f"PRAGMA busy_timeout = {int(timeout) * 1000}")
        cur = con.cursor()
        cur.execute(sql)
        if cur.description:
            columns = [d[0] for d in cur.description]
            rows = cur.fetchmany(max_rows)
            return True, format_rows(columns, rows, max_rows), len(rows)
        con.commit()
        return True, f"Sentencia ejecutada. Filas afectadas: {cur.rowcount}", max(cur.rowcount, 0)
    finally:
        con.close()


def run_mysql(host: str, port: int, user: str, password: str, database: str,
              sql: str, timeout: int, env: dict, max_bytes: int = 262144):
    """Ejecuta en MySQL local usando el cliente `mysql` (sin shell).

    La salida se lee de forma acotada: si el resultado excede `max_bytes` se corta
    el proceso, para que un SELECT enorme no agote la memoria.
    """
    exe = mysql_client()
    if not exe:
        raise DbError("No se encontro el cliente 'mysql' en el PATH.")
    argv = [
        exe,
        f"--host={host}",
        f"--port={int(port)}",
        f"--user={user}",
        f"--database={database}",
        "--batch",
        "--raw",
        "--quick",
        "--default-character-set=utf8mb4",
        "-e",
        sql,
    ]
    child_env = dict(env)
    if password:
        child_env["MYSQL_PWD"] = password

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errfh:
        try:
            proc = subprocess.Popen(argv, env=child_env, stdout=subprocess.PIPE,
                                    stderr=errfh, text=True, encoding="utf-8",
                                    errors="replace", shell=False, bufsize=1)
        except FileNotFoundError:
            raise DbError("No se pudo ejecutar el cliente 'mysql'.")

        lineas: list[str] = []
        total = 0
        cortado = False
        try:
            assert proc.stdout is not None
            for linea in proc.stdout:
                lineas.append(linea)
                total += len(linea.encode("utf-8", "replace"))
                if total >= max_bytes:
                    cortado = True
                    break
            if cortado:
                proc.kill()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return False, f"Tiempo agotado ({timeout}s).", 0

        errfh.seek(0)
        errores = (errfh.read() or "").strip()

    if proc.returncode != 0 and not cortado:
        return False, errores or f"El cliente devolvio el codigo {proc.returncode}.", 0

    salida = "".join(lineas).strip()
    filas = max(len(salida.splitlines()) - 1, 0) if salida else 0
    texto = salida or "(sin filas)"
    if cortado:
        texto += f"\n... [resultado truncado a {total} bytes]"
    if errores:
        texto += f"\n[aviso] {errores}"
    return True, texto, filas
