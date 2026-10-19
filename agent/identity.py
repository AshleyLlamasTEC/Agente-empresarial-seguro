"""Identidad del agente (opcional y local).

El agente NO trae identidad ni datos del usuario de fabrica: empieza en blanco.
La identidad se crea en el primer uso con:

    python -m agent.cli setup

Se guarda en `identity.json`, en la raiz del repositorio, y esta excluido del
control de versiones (`.gitignore`) porque contiene datos personales. En el
repositorio solo vive `identity.example.json`, que es una plantilla vacia.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IDENTITY_PATH = REPO_ROOT / "identity.json"

MAX_NAME = 60
MAX_NOTE = 300
MAX_NOTES = 40

TONO_POR_DEFECTO = "respetuoso y sereno (Zen)"


class IdentityError(Exception):
    """Identidad invalida."""


@dataclass
class Identity:
    agent_name: str = ""
    user_name: str = ""
    user_notes: list[str] = field(default_factory=list)
    tone: str = ""
    language: str = "es"

    @property
    def configured(self) -> bool:
        """Hay identidad configurada cuando al menos el nombre del agente existe."""
        return bool(self.agent_name.strip())

    @property
    def has_user(self) -> bool:
        return bool(self.user_name.strip() or self.user_notes)

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "user_name": self.user_name,
            "user_notes": list(self.user_notes),
            "tone": self.tone or TONO_POR_DEFECTO,
            "language": self.language or "es",
        }


def blank_identity() -> Identity:
    return Identity(tone=TONO_POR_DEFECTO)


def _clean(value, limit: int) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def validate_identity(raw: dict, source: str = "identity.json") -> Identity:
    if not isinstance(raw, dict):
        raise IdentityError(f"La identidad ({source}) no es un objeto JSON.")

    permitidos = {"agent_name", "user_name", "user_notes", "tone", "language"}
    desconocidos = set(raw) - permitidos
    if desconocidos:
        raise IdentityError(f"Campos no permitidos en {source}: {sorted(desconocidos)}")

    notas = raw.get("user_notes") or []
    if isinstance(notas, str):
        notas = [notas]
    if not isinstance(notas, list):
        raise IdentityError("'user_notes' debe ser una lista de textos.")

    return Identity(
        agent_name=_clean(raw.get("agent_name"), MAX_NAME),
        user_name=_clean(raw.get("user_name"), MAX_NAME),
        user_notes=[_clean(n, MAX_NOTE) for n in notas[:MAX_NOTES] if _clean(n, MAX_NOTE)],
        tone=_clean(raw.get("tone"), MAX_NOTE) or TONO_POR_DEFECTO,
        language=_clean(raw.get("language"), 10) or "es",
    )


def load_identity(path: Path | None = None) -> Identity:
    """Carga la identidad. Si no existe, devuelve una en blanco (sin error)."""
    file = Path(path) if path else IDENTITY_PATH
    if not file.is_file():
        return blank_identity()
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IdentityError(f"El archivo {file.name} no es JSON valido: {exc}") from exc
    return validate_identity(raw, file.name)


def save_identity(identity: Identity, path: Path | None = None) -> Path:
    file = Path(path) if path else IDENTITY_PATH
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(identity.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return file


def reset_identity(path: Path | None = None) -> bool:
    """Borra la identidad para volver al estado en blanco."""
    file = Path(path) if path else IDENTITY_PATH
    if file.is_file():
        file.unlink()
        return True
    return False
