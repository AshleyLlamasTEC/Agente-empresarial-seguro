"""Rollback: revertir cambios usando los respaldos registrados en la bitacora.

Cada escritura queda en la bitacora con `sha256_before`, `sha256_after` y la
ruta del respaldo (`.bak`) creado antes de modificar. Con eso se puede devolver
un archivo (o una sesion completa) a como estaba antes, de forma verificable.

Seguridad:
- Solo se toca lo que este DENTRO del workspace.
- Antes de restaurar se comprueba que el archivo no haya cambiado despues; si
  cambio, se avisa y solo se aplica con `--force`.
- Toda restauracion se registra en una bitacora nueva (perfil `rollback`).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Action:
    target: Path
    mode: str            # "restore" | "delete" | "skip"
    backup: Path | None
    expected_sha: str    # hash actual esperado (el de despues de lo que se deshace)
    original_sha: str    # hash al que se volvera
    writes: int = 1
    note: str = ""

    @property
    def label(self) -> str:
        return {"restore": "RESTAURAR", "delete": "BORRAR", "skip": "OMITIR"}[self.mode]


def sha256_of(path: Path) -> str:
    path = Path(path)
    if not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_records(paths) -> list[dict]:
    """Lee una o varias bitacoras (.jsonl) y devuelve sus registros en orden."""
    records: list[dict] = []
    for path in paths:
        path = Path(path)
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return records


def write_events(records) -> list[dict]:
    return [r for r in records if r.get("event") == "write_file"]


def sessions_with_writes(records) -> list[str]:
    seen: list[str] = []
    for record in write_events(records):
        session = record.get("session")
        if session and session not in seen:
            seen.append(session)
    return seen


def build_actions(records, workspace: Path, session: str | None = None,
                  file_name: str | None = None, last_only: bool = False,
                  backups_root: Path | None = None) -> list[Action]:
    """Calcula que hay que hacer para deshacer los cambios seleccionados.

    Si se indica `backups_root`, solo se aceptan respaldos que esten dentro de esa
    carpeta (la de respaldos de la bitacora). Asi una bitacora manipulada no puede
    copiar archivos arbitrarios de la maquina hacia el workspace.
    """
    events = write_events(records)
    if session:
        events = [e for e in events if e.get("session") == session]
    if file_name:
        events = [e for e in events
                  if Path(e.get("data", {}).get("path", "")).name == file_name]

    by_target: dict[str, list[dict]] = {}
    for event in events:
        target = event.get("data", {}).get("path", "")
        if target:
            by_target.setdefault(target, []).append(event)

    actions: list[Action] = []
    for target, evs in by_target.items():
        first, last = evs[0].get("data", {}), evs[-1].get("data", {})
        base = last if last_only else first
        original = base.get("sha256_before", "")
        expected = last.get("sha256_after", "")
        backup_raw = base.get("respaldo") or ""
        backup = Path(backup_raw) if backup_raw else None
        note = ""

        if backup is not None and backup.is_file():
            if backups_root is not None and not _inside(backup, backups_root):
                mode = "skip"
                note = "el respaldo esta fuera del directorio de auditoria"
            else:
                mode = "restore"
        elif not original:
            mode = "delete"
        else:
            mode = "skip"
            note = "sin respaldo disponible"

        actions.append(Action(target=Path(target), mode=mode, backup=backup,
                              expected_sha=expected, original_sha=original,
                              writes=len(evs), note=note))
    return actions


def _inside(path: Path, workspace: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(workspace).resolve())
        return True
    except (ValueError, OSError):
        return False


def apply_actions(actions, workspace: Path, audit, confirmer, out=print,
                  dry_run: bool = False, force: bool = False) -> tuple[list, list]:
    """Aplica el plan. Devuelve (aplicadas, omitidas)."""
    workspace = Path(workspace).resolve()
    aplicadas: list[dict] = []
    omitidas: list[dict] = []

    for action in actions:
        if not _inside(action.target, workspace):
            omitidas.append({"target": str(action.target), "motivo": "fuera del workspace"})
            out(f"[x] Fuera del workspace, se omite: {action.target}")
            continue

        if action.mode == "skip":
            motivo = action.note or "sin respaldo disponible"
            omitidas.append({"target": str(action.target), "motivo": motivo})
            out(f"[!] {motivo}, se omite: {action.target}")
            continue

        current = sha256_of(action.target)
        if action.mode == "restore" and action.expected_sha and current != action.expected_sha:
            if not force:
                omitidas.append({"target": str(action.target),
                                 "motivo": "el archivo cambio despues del respaldo"})
                out(f"[!] {action.target.name} cambio despues; usa --force para forzar.")
                continue

        if action.mode == "delete" and not action.target.exists():
            omitidas.append({"target": str(action.target), "motivo": "ya no existe"})
            continue

        description = (
            f"{action.label} {action.target}\n"
            f"  escrituras deshechas: {action.writes}\n"
            f"  hash actual:  {current or '(no existe)'}\n"
            f"  hash destino: {action.original_sha or '(borrar)'}"
        )

        if dry_run:
            out(f"[simulacion] {description}")
            aplicadas.append({"target": str(action.target), "modo": action.mode, "simulado": True})
            continue

        if not confirmer(description):
            audit.record("rollback_denied_by_user", {"target": str(action.target)})
            omitidas.append({"target": str(action.target), "motivo": "rechazado por el operador"})
            continue

        try:
            if action.mode == "restore":
                shutil.copy2(action.backup, action.target)
            else:
                action.target.unlink()
        except OSError as exc:
            omitidas.append({"target": str(action.target), "motivo": f"error: {exc}"})
            out(f"[x] No se pudo aplicar en {action.target}: {exc}")
            continue

        after = sha256_of(action.target)
        audit.record(
            "rollback_restore" if action.mode == "restore" else "rollback_delete",
            {
                "target": str(action.target),
                "backup": str(action.backup) if action.backup else "",
                "sha256_after": after,
                "sha256_esperado": action.original_sha,
                "coincide": after == action.original_sha,
                "force": force,
            },
        )
        aplicadas.append({"target": str(action.target), "modo": action.mode,
                          "coincide": after == action.original_sha})

    return aplicadas, omitidas
