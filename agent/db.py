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
from dataclasses import dataclass
from pathlib import Path

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
READ_KEYWORDS = {"select", "explain", "with", "show", "describe", "desc", "pragma",
                 "values", "table"}
WRITE_KEYWORDS = {"insert", "update", "delete", "replace", "upsert", "merge", "call", "do"}
DDL_KEYWORDS = {"create", "drop", "alter", "truncate", "rename", "grant", "revoke",
                "attach", "detach", "vacuum", "reindex", "analyze"}


class DbError(Exception):
    """Sentencia o destino no permitido."""


@dataclass
class SqlDecision:
    sql: str
    kind: str  # "read" | "write" | "ddl"


def _first_keyword(sql: str) -> str:
    match = re.match(r"\s*([A-Za-z_]+)", sql)
    return match.group(1).lower() if match else ""


def validate_sql(sql: str, read_only: bool = True, allow_ddl: bool = False) -> SqlDecision:
    """Valida y clasifica una sentencia. Lanza DbError si no es admisible."""
    if not isinstance(sql, str) or not sql.strip():
        raise DbError("Falta la sentencia SQL.")
    if "\x00" in sql:
        raise DbError("La sentencia contiene caracteres nulos.")

    cuerpo = sql.strip()
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
              sql: str, timeout: int, env: dict):
    """Ejecuta en MySQL local usando el cliente `mysql` (sin shell)."""
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
        "--default-character-set=utf8mb4",
        "-e",
        sql,
    ]
    child_env = dict(env)
    if password:
        child_env["MYSQL_PWD"] = password
    try:
        completed = subprocess.run(argv, env=child_env, capture_output=True, text=True,
                                   errors="replace", timeout=timeout, shell=False)
    except FileNotFoundError:
        raise DbError("No se pudo ejecutar el cliente 'mysql'.")
    except subprocess.TimeoutExpired:
        return False, f"Tiempo agotado ({timeout}s).", 0

    salida = (completed.stdout or "").strip()
    errores = (completed.stderr or "").strip()
    if completed.returncode != 0:
        return False, errores or f"El cliente devolvio el codigo {completed.returncode}.", 0
    filas = max(len(salida.splitlines()) - 1, 0) if salida else 0
    texto = salida or "(sin filas)"
    if errores:
        texto += f"\n[aviso] {errores}"
    return True, texto, filas
