"""Bitacora de auditoria con encadenamiento de hashes (append-only).

Cada registro incluye el hash del registro anterior. Si alguien edita o borra
una linea, la verificacion de la cadena falla. Esto es lo que permite demostrar
a auditoria que la bitacora no fue manipulada.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import getpass
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64


def _canonical(record: dict) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _digest(record_without_hash: dict) -> str:
    return hashlib.sha256(_canonical(record_without_hash).encode("utf-8")).hexdigest()


def default_audit_dir() -> Path:
    override = os.environ.get("AGENT_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    return home / ".agente-empresarial" / "audit"


class AuditLog:
    def __init__(self, profile_name: str, audit_dir: Path | None = None, session_id: str | None = None):
        self.directory = Path(audit_dir) if audit_dir else default_audit_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id = session_id or stamp
        self.path = self.directory / f"{stamp}-{profile_name}-{os.getpid()}.jsonl"
        self._seq = 0
        self._prev = GENESIS
        self._fh = self.path.open("a", encoding="utf-8", newline="\n")
        self.record(
            "session_start",
            {
                "profile": profile_name,
                "usuario": _safe_user(),
                "equipo": platform.node(),
                "sistema": f"{platform.system()} {platform.release()}",
                "python": platform.python_version(),
                "pid": os.getpid(),
            },
        )

    def record(self, event: str, data: dict | None = None) -> dict:
        self._seq += 1
        base = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "session": self.session_id,
            "event": event,
            "prev": self._prev,
            "data": data or {},
        }
        digest = _digest(base)
        base["hash"] = digest
        self._fh.write(_canonical(base) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())
        self._prev = digest
        return base

    def close(self) -> None:
        if not self._fh.closed:
            self.record("session_end", {})
            self._fh.close()

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "desconocido"


def verify_chain(path: Path) -> tuple[bool, int, str]:
    """Recorre la bitacora y valida el encadenamiento.

    Devuelve (valido, registros_leidos, mensaje).
    """
    path = Path(path)
    if not path.is_file():
        return False, 0, f"No existe el archivo: {path}"

    prev = GENESIS
    count = 0
    try:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                stored = record.pop("hash", None)
                if record.get("prev") != prev:
                    return False, count, f"Cadena rota en la linea {lineno}: 'prev' no coincide."
                recomputed = _digest(record)
                if stored != recomputed:
                    return False, count, f"Registro alterado en la linea {lineno}."
                prev = stored
                count += 1
    except json.JSONDecodeError as exc:
        return False, count, f"JSON invalido en la linea {count + 1}: {exc}"

    return True, count, f"Cadena integra: {count} registros verificados."
