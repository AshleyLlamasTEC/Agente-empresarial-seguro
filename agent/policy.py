"""Motor de politica: decide si un comando o una ruta esta permitido.

Principio rector: DENY BY DEFAULT. Un comando solo se ejecuta si:
  1. No contiene metacaracteres de shell (sin encadenar, sin redirigir).
  2. No coincide con ningun patron de la lista negra (destructivo / red / produccion).
  3. Su ejecutable esta en la lista blanca del perfil.
  4. Todos sus argumentos que sean rutas quedan dentro del workspace.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from .sandbox import SandboxError, looks_like_path, resolve_in_workspace

# Metacaracteres que permiten encadenar o redirigir: se prohiben siempre.
SHELL_METACHARACTERS = {
    ";": "punto y coma (encadenar comandos)",
    "&": "ampersand (encadenar / background)",
    "|": "pipe (encadenar comandos)",
    "`": "backtick (ejecucion implicita)",
    "$": "dolar (interpolacion de variables)",
    ">": "redireccion de salida",
    "<": "redireccion de entrada",
    "\n": "salto de linea",
    "\r": "retorno de carro",
}

# Patrones prohibidos en TODOS los perfiles.
BASE_DENY_PATTERNS = [
    # Movimiento de datos / acceso remoto
    r"\bssh\b", r"\bscp\b", r"\bsftp\b", r"\brsync\b", r"\btelnet\b",
    r"\bnc(\.exe)?\b", r"\bncat\b", r"\bnetcat\b", r"\bplink\b", r"\bpsexec\b",
    r"\bwinrm\b", r"\bEnter-PSSession\b", r"\bNew-PSSession\b", r"\bInvoke-Command\b",
    r"\bcurl\b", r"\bwget\b", r"\bInvoke-WebRequest\b", r"\biwr\b", r"\bStart-BitsTransfer\b",
    r"\bftp\b", r"\btftp\b", r"\bBitsTransfer\b",
    # Contenedores / orquestacion / infraestructura
    r"\bdocker\b", r"\bdocker-compose\b", r"\bkubectl\b", r"\bhelm\b", r"\bpodman\b",
    r"\bterraform\b", r"\bansible\b", r"\bvagrant\b",
    # Nubes (fuga de datos)
    r"\baws\b", r"\baz\b", r"\bgcloud\b", r"\bgsutil\b", r"\boci\b", r"\bazcopy\b",
    # Clientes de base de datos (riesgo a produccion)
    r"\bmysql\b", r"\bmysqldump\b", r"\bmysqladmin\b", r"\bpsql\b", r"\bpg_dump\b",
    r"\bsqlcmd\b", r"\bsqlplus\b", r"\bmongosh?\b", r"\bredis-cli\b", r"\bsqlite3\b",
    # Publicacion de paquetes
    r"\bnpm\s+publish\b", r"\byarn\s+publish\b", r"\bpnpm\s+publish\b", r"\btwine\s+upload\b",
    r"\bnpm\s+install\s+(-g|--global)\b", r"\bpip\s+install\b", r"\bchoco\b", r"\bwinget\b",
    # Operaciones destructivas
    r"\brm\b", r"\brmdir\b", r"\brd\b", r"\bdel\b", r"\berase\b", r"\bRemove-Item\b",
    r"\bmv\b", r"\bmove\b", r"\bren\b", r"\bRename-Item\b", r"\bMove-Item\b",
    r"\bformat\b", r"\bmkfs\b", r"\bdiskpart\b", r"\btruncate\b", r"\bClear-Content\b",
    r"\bshutdown\b", r"\breboot\b", r"\bStop-Computer\b", r"\bRestart-Computer\b",
    # Git que mutan estado o tocan remotos
    r"\bgit\s+push\b", r"\bgit\s+remote\b", r"\bgit\s+clone\b", r"\bgit\s+fetch\b",
    r"\bgit\s+pull\b", r"\bgit\s+reset\b", r"\bgit\s+clean\b", r"\bgit\s+checkout\b",
    r"\bgit\s+restore\b", r"\bgit\s+rebase\b", r"\bgit\s+submodule\b", r"\bgit\s+config\b",
    r"\bgit\s+daemon\b", r"\bgit\s+filter-branch\b", r"\bgit\s+stash\s+(drop|clear)\b",
    r"\bgit\s+worktree\b", r"\bgit\s+gc\b", r"\bgit\s+prune\b",
    # Registro / sistema / persistencia
    r"\breg(\.exe)?\s+(add|delete|import|copy|save|restore)\b", r"\bschtasks\b",
    r"\bsc(\.exe)?\s+(create|config|delete|start|stop)\b", r"\bNew-Service\b",
    r"\bnet\s+use\b", r"\bnet\s+user\b", r"\bNew-PSDrive\b", r"\bmount\b", r"\bnetstat\b",
    r"\bnetsh\b", r"\biptables\b", r"\bufw\b", r"\bSet-ExecutionPolicy\b",
    # Despliegue / migraciones (riesgo directo a produccion)
    r"\bdeploy\b", r"\bmigrate\b", r"\brunserver\b", r"\bphp\s+artisan\b",
    r"\bnpm\s+run\s+(deploy|migrate|prod)\b", r"\bpm2\b", r"\bsupervisorctl\b",
    r"\bvagrant\s+up\b", r"\bfab\b", r"\bansible-playbook\b",
    # Ejecucion dinamica / evasion
    r"\bInvoke-Expression\b", r"\biex\b", r"\bStart-Process\b", r"\bcmd\s*/c\b",
    r"\bbash\s+-c\b", r"\bsh\s+-c\b", r"\bpowershell\b", r"\bpwsh\b",
    r"\bpython\s+-c\b", r"\bnode\s+-e\b", r"\bwmic\b",
]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    argv: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.allowed


def _compile_deny(patterns) -> list[re.Pattern]:
    compiled = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error:
            continue
    return compiled


def check_command(command: str, profile, workspace: Path) -> Decision:
    """Valida un comando contra el perfil. Devuelve la decision con su motivo."""
    if not isinstance(command, str):
        return Decision(False, "El comando debe ser texto.")

    cmd = command.strip()
    if not cmd:
        return Decision(False, "Comando vacio.")
    if len(cmd) > 500:
        return Decision(False, "Comando demasiado largo (maximo 500 caracteres).")

    for char, nombre in SHELL_METACHARACTERS.items():
        if char in cmd:
            return Decision(False, f"Metacaracter de shell prohibido: {nombre}.")

    deny_patterns = _compile_deny(BASE_DENY_PATTERNS) + _compile_deny(profile.commands_deny)
    for pattern in deny_patterns:
        if pattern.search(cmd):
            return Decision(False, f"Coincide con patron prohibido: {pattern.pattern}")

    try:
        argv = shlex.split(cmd, posix=(os.name != "nt"))
    except ValueError as exc:
        return Decision(False, f"Comando mal formado: {exc}")
    if not argv:
        return Decision(False, "Comando vacio.")

    program = Path(argv[0].strip("\"'")).name.lower()
    for suffix in (".exe", ".cmd", ".bat", ".com", ".ps1"):
        if program.endswith(suffix):
            program = program[: -len(suffix)]

    allow = {p.lower() for p in profile.commands_allow}
    if program not in allow:
        return Decision(
            False,
            f"Ejecutable '{program}' no esta en la lista blanca del perfil '{profile.name}'. "
            f"Permitidos: {sorted(allow)}",
        )

    for token in argv[1:]:
        if not looks_like_path(token):
            continue
        try:
            resolve_in_workspace(Path(workspace), token.strip("\"'"))
        except SandboxError as exc:
            return Decision(False, f"Argumento de ruta rechazado: {exc}")

    return Decision(True, "Comando permitido por la lista blanca.", tuple(argv))


def check_path(path: Path, profile) -> Decision:
    """Valida una ruta contra las listas de nombres/globs prohibidos del perfil."""
    from fnmatch import fnmatch

    name = path.name.lower()
    for denied in profile.path_deny_names:
        if fnmatch(name, denied.lower()):
            return Decision(False, f"Archivo protegido por politica de datos: {path.name}")

    full = path.as_posix().lower()
    for pattern in profile.path_deny_globs:
        if fnmatch(full, pattern.lower()) or fnmatch(name, pattern.lower()):
            return Decision(False, f"Ruta protegida por politica de datos: {path}")

    for part in path.parts:
        if part.lower() in {"prod", "produccion", "producción", "production"}:
            return Decision(False, f"Ruta marcada como produccion, bloqueada: {path}")

    return Decision(True, "Ruta permitida.")
