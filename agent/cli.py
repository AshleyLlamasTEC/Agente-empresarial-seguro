"""Interfaz de linea de comandos del Agente Empresarial Seguro.

Uso:
    python -m agent.cli setup
    python -m agent.cli profiles
    python -m agent.cli models --host http://127.0.0.1:11434
    python -m agent.cli doctor --profile consulta --workspace C:\\trabajo\\proyecto
    python -m agent.cli ask --profile consulta --workspace C:\\trabajo\\proyecto "Analiza el proyecto"
    python -m agent.cli verify-audit --file .\\audit\\20260101T000000Z-consulta-1234.jsonl
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import __version__
from .agent import Agent
from .audit import AuditLog, default_audit_dir, verify_chain
from .config import (ConfigError, available_profiles, env_defaults, load_profile)
from .db import mysql_client
from .identity import (IDENTITY_PATH, Identity, IdentityError, TONO_POR_DEFECTO,
                       load_identity, reset_identity, save_identity)
from .ollama_client import OllamaClient, OllamaError, SecurityPolicyError
from .rollback import apply_actions, build_actions, load_records, sessions_with_writes
from .tools import ToolRunner


def _stdout(*parts) -> None:
    print(*parts, flush=True)


def _confirm_interactive(description: str) -> bool:
    print("\n" + "=" * 70)
    print("CONFIRMACION REQUERIDA")
    print("-" * 70)
    print(description)
    print("-" * 70)
    while True:
        answer = input("Aplicar? [s/N]: ").strip().lower()
        if answer in ("s", "si", "sí", "y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False


def _build(args) -> tuple:
    profile = load_profile(args.profile)
    if args.no_shell and profile.allow_shell:
        profile = dataclasses.replace(profile, allow_shell=False)
        _stdout("[i] Shell deshabilitado por --no-shell.")
    if args.no_write and profile.allow_write:
        profile = dataclasses.replace(profile, allow_write=False)
        _stdout("[i] Escritura deshabilitada por --no-write.")
    if getattr(args, "no_db", False) and profile.allow_db:
        profile = dataclasses.replace(profile, allow_db=False)
        _stdout("[i] Acceso a base de datos deshabilitado por --no-db.")
    if getattr(args, "db_write", False) and profile.allow_db and profile.db_read_only:
        profile = dataclasses.replace(profile, db_read_only=False)
        _stdout("[i] Escritura en base de datos habilitada por --db-write (con confirmacion).")
    if getattr(args, "db_ddl", False) and profile.allow_db:
        profile = dataclasses.replace(profile, db_read_only=False, db_allow_ddl=True)
        _stdout("[i] DDL habilitado por --db-ddl (solo local, con confirmacion).")
    return profile


def _workspace(args) -> Path:
    raw = args.workspace or env_defaults()["workspace"]
    if not raw:
        raise ConfigError("Indica --workspace (o la variable AGENT_WORKSPACE).")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"El workspace no existe o no es un directorio: {path}")
    return path


def _ask_line(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    answer = input(f"{prompt}{suffix}: ").strip()
    return answer or default


def _interactive_setup(actual: Identity) -> Identity:
    _stdout("\nResponde las preguntas. Enter vacio conserva lo actual.")
    agent_name = _ask_line("Nombre del agente", actual.agent_name)
    user_name = _ask_line("Tu nombre", actual.user_name)
    tone = _ask_line("Tono de conversacion", actual.tone or TONO_POR_DEFECTO)
    notas = list(actual.user_notes)
    _stdout("Notas que quieras que recuerde (una por linea; vacio para terminar):")
    while True:
        entrada = input("  nota> ").strip()
        if not entrada:
            break
        notas.append(entrada)
    return Identity(agent_name=agent_name, user_name=user_name, user_notes=notas,
                    tone=tone, language=actual.language or "es")


def cmd_setup(args) -> int:
    _stdout("=" * 72)
    _stdout("CONFIGURACION DE IDENTIDAD")
    _stdout("=" * 72)

    if args.reset:
        if reset_identity():
            _stdout("[ok] Identidad borrada. El agente vuelve a estar en blanco.")
        else:
            _stdout("[i] No habia identidad que borrar. Ya esta en blanco.")
        return 0

    actual = load_identity()

    if args.show:
        if not actual.configured:
            _stdout("[i] Sin identidad configurada (estado en blanco).")
        else:
            _stdout(f"Archivo: {IDENTITY_PATH}\n")
            _stdout(json.dumps(actual.to_dict(), ensure_ascii=False, indent=2))
        return 0

    _stdout("El agente empieza SIN identidad ni datos de la persona con quien habla.")
    _stdout(f"Lo que definas aqui se guarda en: {IDENTITY_PATH}")
    _stdout("Ese archivo es privado (esta en .gitignore): no se sube al repositorio.\n")

    por_banderas = any([args.agent_name, args.user_name, args.tone, args.note])
    if por_banderas:
        notas = list(actual.user_notes) + list(args.note or [])
        nueva = Identity(
            agent_name=args.agent_name or actual.agent_name,
            user_name=args.user_name or actual.user_name,
            user_notes=notas,
            tone=args.tone or actual.tone or TONO_POR_DEFECTO,
            language=actual.language or "es",
        )
    else:
        if not sys.stdin.isatty():
            _stdout("[i] Terminal no interactiva. Usa --agent-name, --user-name,")
            _stdout("    --tone y --note, o ejecuta 'setup' desde una terminal.")
            return 2
        try:
            nueva = _interactive_setup(actual)
        except (EOFError, KeyboardInterrupt):
            _stdout("\n[i] Configuracion cancelada. No se cambio nada.")
            return 130

    ruta = save_identity(nueva)
    _stdout("\n[ok] Identidad guardada en: " + str(ruta))
    _stdout(f"    Agente: {nueva.agent_name or '(sin nombre)'}")
    _stdout(f"    Persona: {nueva.user_name or '(sin nombre)'}")
    _stdout(f"    Tono: {nueva.tone}")
    if nueva.user_notes:
        _stdout(f"    Notas guardadas: {len(nueva.user_notes)}")
    _stdout("\nSugerencia: 'setup --show' para revisarla y 'setup --reset' para borrarla.")
    return 0


def _notice_if_blank(identity: Identity, allow_prompt: bool) -> Identity:
    """Avisa (y ofrece configurar) si el agente todavia no tiene identidad."""
    if identity.configured:
        return identity
    _stdout("[i] El agente no tiene identidad: no sabe su nombre ni quien eres.")
    _stdout("    Configurala cuando quieras con:  python -m agent.cli setup")
    if allow_prompt and sys.stdin.isatty():
        try:
            if input("    Configurar ahora? [s/N]: ").strip().lower() in ("s", "si", "sí", "y", "yes"):
                identity = _interactive_setup(identity)
                save_identity(identity)
                _stdout("[ok] Identidad guardada.")
        except (EOFError, KeyboardInterrupt):
            _stdout("")
    return identity


def cmd_profiles(args) -> int:
    _stdout(f"Perfiles disponibles en el repositorio ({len(available_profiles())}):")
    for name in available_profiles():
        profile = load_profile(name)
        modo = "SOLO LECTURA" if profile.read_only else "lectura/escritura"
        extra = ""
        if profile.allow_db:
            modo_db = "solo lectura" if profile.db_read_only else "lectura/escritura"
            extra = f" | BD: {modo_db} (local)"
        _stdout(f"  - {name:12s} [{modo:16s}] modelo={profile.model}{extra}")
        if profile.description:
            _stdout(f"    {profile.description}")
    return 0


def cmd_models(args) -> int:
    client = OllamaClient(model=args.model or "qwen2.5-coder:7b", host=args.host)
    if not client.is_available():
        _stdout(f"[x] Ollama no responde en {client.host}.")
        return 2
    models = client.list_models()
    _stdout(f"Modelos locales en {client.host} ({len(models)}):")
    for name in models:
        flag = "  <-- CLOUD (prohibido para trabajo)" if "cloud" in name.lower() else ""
        _stdout(f"  - {name}{flag}")
    _stdout("\nRecomendado para codigo: qwen2.5-coder:7b (o :14b si hay mas VRAM).")
    return 0


def cmd_doctor(args) -> int:
    _stdout("=" * 72)
    _stdout(f"AGENTE EMPRESARIAL SEGURO v{__version__} - DIAGNOSTICO DE CUMPLIMIENTO")
    _stdout("=" * 72)
    problemas = 0

    _stdout(f"\n[1] Python: {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        _stdout("    [x] Se requiere Python 3.10 o superior.")
        problemas += 1
    else:
        _stdout("    [ok] Version compatible.")

    _stdout("\n[2] Perfil")
    try:
        profile = load_profile(args.profile)
        _stdout(f"    [ok] '{profile.name}' cargado. Modo: "
                f"{'SOLO LECTURA' if profile.read_only else 'lectura/escritura'}")
        _stdout(f"    [ok] Modelo declarado: {profile.model} (validado como local)")
        _stdout(f"    [ok] Escritura: {profile.allow_write} | Shell: {profile.allow_shell} | "
                f"Confirmacion humana: {profile.require_confirmation}")
        _stdout(f"    [ok] Lista blanca de comandos: {len(profile.commands_allow)} ejecutables")
        if profile.allow_db:
            modo_db = "SOLO LECTURA" if profile.db_read_only else "lectura/escritura"
            _stdout(f"    [ok] Base de datos: habilitada ({modo_db}), DDL={profile.db_allow_ddl}")
    except ConfigError as exc:
        _stdout(f"    [x] {exc}")
        return 1

    _stdout("\n[3] Poliza de datos (modelo local)")
    try:
        client = OllamaClient(model=args.model or profile.model, host=args.host)
        _stdout(f"    [ok] Host validado como loopback: {client.host}")
        _stdout(f"    [ok] Modelo aceptado: {client.model}")
        if client.is_available():
            _stdout("    [ok] Ollama responde.")
            if client.has_model():
                _stdout(f"    [ok] El modelo {client.model} esta descargado.")
            else:
                _stdout(f"    [!] El modelo {client.model} no esta descargado. "
                        f"Ejecuta: ollama pull {client.model}")
                problemas += 1
        else:
            _stdout("    [x] Ollama no responde. Inicia el servicio (ollama serve).")
            problemas += 1
    except SecurityPolicyError as exc:
        _stdout(f"    [x] {exc}")
        problemas += 1

    _stdout("\n[4] Workspace")
    try:
        workspace = _workspace(args)
        _stdout(f"    [ok] Existe y es directorio: {workspace}")
        git_dir = workspace / ".git"
        _stdout(f"    {'[ok] Repositorio git detectado.' if git_dir.exists() else '[i] No es un repositorio git.'}")
        sospechosos = []
        for pattern in (".env", "*.pem", "*.key", "id_rsa", "credentials*", "secrets*"):
            sospechosos.extend(str(p.relative_to(workspace)) for p in workspace.rglob(pattern)
                               if p.is_file())
        if sospechosos:
            _stdout(f"    [!] Se encontraron {len(sospechosos)} archivos sensibles. "
                    "El agente los bloqueara, pero considera retirarlos de esta copia:")
            for item in sospechosos[:10]:
                _stdout(f"        - {item}")
        else:
            _stdout("    [ok] Sin archivos de credenciales detectados en el workspace.")
    except ConfigError as exc:
        _stdout(f"    [!] {exc}")
        problemas += 1

    _stdout("\n[5] Bitacora")
    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
        _stdout(f"    [ok] Directorio de bitacora accesible: {audit_dir}")
    except OSError as exc:
        _stdout(f"    [x] No se puede escribir la bitacora: {exc}")
        problemas += 1

    _stdout("\n[6] Aislamiento de red recomendado (verificacion manual)")
    _stdout("    [ ] La maquina no tiene VPN ni acceso a produccion.")
    _stdout("    [ ] El proyecto es una COPIA, no un recurso compartido de red.")
    _stdout("    [ ] No hay credenciales reales de produccion en esta maquina.")
    _stdout("    [ ] Salida de red restringida salvo 127.0.0.1:11434.")

    _stdout("\n[7] Identidad")
    try:
        identity = load_identity()
        if identity.configured:
            _stdout(f"    [ok] Nombre del agente: {identity.agent_name}")
            if identity.user_name:
                _stdout(f"    [ok] Persona: {identity.user_name}")
            else:
                _stdout("    [i] Nombre de la persona sin definir.")
            _stdout(f"    [ok] Tono: {identity.tone}")
            if identity.user_notes:
                _stdout(f"    [i] Notas guardadas: {len(identity.user_notes)}")
        else:
            _stdout("    [i] Sin identidad configurada (estado en blanco):")
            _stdout("        el agente no conoce su nombre ni datos de la persona.")
            _stdout("        Configura con: python -m agent.cli setup")
    except IdentityError as exc:
        _stdout(f"    [x] {exc}")
        problemas += 1

    _stdout("\n[8] Base de datos local")
    try:
        perfil_db = load_profile(args.profile)
        if perfil_db.allow_db:
            modo = "SOLO LECTURA" if perfil_db.db_read_only else "lectura/escritura"
            _stdout(f"    [ok] El perfil '{perfil_db.name}' permite base de datos ({modo}).")
            _stdout("    [ok] SQLite disponible (libreria estandar de Python).")
            cliente = mysql_client()
            if cliente:
                _stdout(f"    [ok] Cliente MySQL detectado: {cliente}")
            else:
                _stdout("    [i] Cliente 'mysql' no encontrado en PATH (solo afecta a MySQL).")
            _stdout("    [i] Solo se permite host local: 127.0.0.1 / localhost / ::1.")
            _stdout("    [i] Cada consulta requiere tu confirmacion y queda en la bitacora.")
        else:
            _stdout("    [i] Este perfil no permite base de datos.")
            _stdout("        Para pruebas con BD usa el perfil 'datos'.")
    except ConfigError as exc:
        _stdout(f"    [x] {exc}")
        problemas += 1

    _stdout("\n" + "=" * 72)
    if problemas:
        _stdout(f"RESULTADO: {problemas} punto(s) por atender antes de operar.")
    else:
        _stdout("RESULTADO: OK. El agente puede operar bajo este perfil.")
    _stdout("=" * 72)
    return 0 if problemas == 0 else 1


def cmd_ask(args) -> int:
    try:
        profile = _build(args)
        workspace = _workspace(args)
    except ConfigError as exc:
        _stdout(f"[x] {exc}")
        return 2

    try:
        client = OllamaClient(model=args.model or profile.model, host=args.host)
    except (SecurityPolicyError, Exception) as exc:  # noqa: BLE001
        _stdout(f"[x] {exc}")
        return 2

    if not client.is_available():
        _stdout(f"[x] Ollama no responde en {client.host}. Inicia el servicio con 'ollama serve'.")
        return 2

    audit_dir = Path(args.audit_dir) if args.audit_dir else None
    confirmer = _confirm_interactive if not args.yes else (lambda _d: True)

    try:
        identity = load_identity()
    except IdentityError as exc:
        _stdout(f"[x] {exc}")
        return 2
    identity = _notice_if_blank(identity, allow_prompt=(not args.task and not args.yes))

    with AuditLog(profile.name, audit_dir) as audit:
        _stdout(f"[i] Bitacora de auditoria: {audit.path}")
        tools = ToolRunner(profile, workspace, audit, confirmer, out=_stdout,
                           dry_run=args.dry_run)
        agent = Agent(profile, workspace, client, tools, audit, out=_stdout,
                      identity=identity)

        if args.task:
            result = agent.run(" ".join(args.task))
            _stdout("\n" + "=" * 72)
            _stdout("RESULTADO FINAL")
            _stdout("=" * 72)
            _stdout(result["answer"] or "(sin respuesta)")
            return 0

        _stdout("\nModo interactivo. Escribe tu tarea y Enter. 'salir' para terminar.")
        while True:
            try:
                task = input("\ntarea> ").strip()
            except (EOFError, KeyboardInterrupt):
                _stdout("")
                break
            if not task:
                continue
            if task.lower() in ("salir", "exit", "quit"):
                break
            result = agent.run(task)
            _stdout("\n--- respuesta ---")
            _stdout(result["answer"] or "(sin respuesta)")
        return 0


def _archivos_con_sesion(paths, session: str | None) -> list[Path]:
    """Devuelve las bitacoras que contienen registros de esa sesion."""
    if not session:
        return []
    encontrados: list[Path] = []
    for path in paths:
        if any(r.get("session") == session for r in load_records([path])):
            encontrados.append(path)
    return encontrados


def cmd_rollback(args) -> int:
    _stdout("=" * 72)
    _stdout("ROLLBACK - restaurar desde los respaldos de la bitacora")
    _stdout("=" * 72)

    workspace = _workspace(args)
    audit_dir = Path(args.audit_dir) if args.audit_dir else default_audit_dir()
    if not audit_dir.is_dir():
        _stdout(f"[x] No existe el directorio de bitacora: {audit_dir}")
        return 2

    files = sorted(audit_dir.glob("*.jsonl"))
    if not files:
        _stdout(f"[i] No hay bitacoras en {audit_dir}.")
        return 0

    records = load_records(files)
    session = args.session
    if session:
        if not any(r.get("session") == session for r in records):
            files = [f for f in files if f.stem == session]
            records = load_records(files)
            if not records:
                _stdout(f"[x] No se encontro la sesion '{args.session}'.")
                return 2
    else:
        sesiones = sessions_with_writes(records)
        if not sesiones:
            _stdout("[i] No hay escrituras registradas; nada que revertir.")
            return 0
        session = sesiones[-1]
        _stdout(f"[i] Sesion por defecto (la mas reciente): {session}")

    if args.file:
        _stdout(f"[i] Archivo objetivo: {args.file}")
    if args.last:
        _stdout("[i] Modo --last: solo la ultima escritura de cada archivo.")

    for path in _archivos_con_sesion(files, session):
        ok, _, mensaje = verify_chain(path)
        if not ok:
            _stdout(f"[x] Bitacora no confiable ({path.name}): {mensaje}")
            _stdout("[x] Rollback cancelado: la bitacora no pasa la verificacion de integridad.")
            return 3

    acciones = build_actions(records, workspace, session=session or None,
                             file_name=args.file or None, last_only=args.last,
                             backups_root=audit_dir / "backups")
    if not acciones:
        _stdout("[i] No se encontraron cambios que revertir con esos criterios.")
        return 0

    _stdout("")
    _stdout("PLAN DE ROLLBACK")
    _stdout("-" * 72)
    for action in acciones:
        extra = f"   (respaldo: {action.backup.name})" if action.backup else ""
        _stdout(f"  {action.label:9s} {action.target}{extra}")
    _stdout("-" * 72)

    if args.list:
        _stdout("[i] Solo listado (--list). No se cambio nada.")
        return 0

    if args.dry_run:
        _stdout("[i] Modo simulacion (--dry-run): no se cambia nada.")

    confirmer = _confirm_interactive if not args.yes else (lambda _d: True)
    with AuditLog("rollback", audit_dir) as audit:
        _stdout(f"[i] Bitacora del rollback: {audit.path}")
        aplicadas, omitidas = apply_actions(acciones, workspace, audit, confirmer,
                                            out=_stdout, dry_run=args.dry_run,
                                            force=args.force)

    _stdout("")
    _stdout("RESUMEN")
    _stdout(f"  aplicadas: {len(aplicadas)} | omitidas: {len(omitidas)}")
    for item in aplicadas:
        _stdout(f"  [ok] {item['modo']}: {item['target']}")
    for item in omitidas:
        _stdout(f"  [!] {item['motivo']}: {item['target']}")
    return 0 if not omitidas else 1


def cmd_verify_audit(args) -> int:
    ok, count, message = verify_chain(Path(args.file))
    _stdout(("[ok] " if ok else "[x] ") + message)
    return 0 if ok else 1


def _common_options() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", default="consulta",
                        help="Perfil a usar (consulta/desarrollo).")
    common.add_argument("--workspace", default="", help="Ruta del workspace permitido.")
    common.add_argument("--model", default="", help="Sobrescribe el modelo del perfil.")
    common.add_argument("--host", default=env_defaults()["host"],
                        help="URL de Ollama (solo loopback).")
    common.add_argument("--audit-dir", default=env_defaults()["audit_dir"],
                        help="Directorio de bitacora.")
    common.add_argument("--dry-run", action="store_true",
                        help="No escribe ni ejecuta: solo simula.")
    common.add_argument("--no-shell", action="store_true",
                        help="Deshabilita la ejecucion de comandos.")
    common.add_argument("--no-write", action="store_true", help="Deshabilita la escritura.")
    common.add_argument("--yes", action="store_true",
                        help="Omite la confirmacion humana (recomendado solo con --dry-run).")
    common.add_argument("--no-db", action="store_true",
                        help="Deshabilita el acceso a base de datos.")
    common.add_argument("--db-write", action="store_true",
                        help="Permite INSERT/UPDATE/DELETE/SELECT (siguen pidiendo confirmacion).")
    common.add_argument("--db-ddl", action="store_true",
                        help="Permite DDL (CREATE/DROP/ALTER). Usar con extremo cuidado.")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog="agente-empresarial-seguro",
        description="Agente local y confinado para auditoria y soporte de codigo.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("profiles", parents=[common], help="Lista los perfiles disponibles.")
    sub.add_parser("models", parents=[common], help="Lista los modelos locales de Ollama.")

    setup = sub.add_parser("setup",
                           help="Configura la identidad del agente (nombre, persona, tono).")
    setup.add_argument("--show", action="store_true", help="Muestra la identidad actual.")
    setup.add_argument("--reset", action="store_true",
                       help="Borra la identidad (vuelve al estado en blanco).")
    setup.add_argument("--agent-name", default="", help="Nombre del agente.")
    setup.add_argument("--user-name", default="", help="Nombre de la persona.")
    setup.add_argument("--tone", default="", help="Tono de conversacion.")
    setup.add_argument("--note", action="append", default=[],
                       help="Nota que el agente debe recordar (repetible).")
    sub.add_parser("doctor", parents=[common],
                   help="Diagnostico de cumplimiento previo a operar.")

    ask = sub.add_parser("ask", parents=[common], help="Ejecuta una tarea (o modo interactivo).")
    ask.add_argument("task", nargs="*", help="Tarea a ejecutar.")

    verify_audit = sub.add_parser("verify-audit", parents=[common],
                                  help="Verifica la integridad de una bitacora.")
    verify_audit.add_argument("--file", required=True, help="Ruta del archivo .jsonl")

    rollback = sub.add_parser("rollback", parents=[common],
                              help="Restaura archivos desde los respaldos de la bitacora.")
    rollback.add_argument("--session", default="",
                          help="Sesion a revertir (por defecto, la mas reciente).")
    rollback.add_argument("--file", default="", help="Revierte solo este archivo (por nombre).")
    rollback.add_argument("--last", action="store_true",
                          help="Solo la ultima escritura de cada archivo.")
    rollback.add_argument("--list", action="store_true", help="Muestra el plan y no cambia nada.")
    rollback.add_argument("--force", action="store_true",
                          help="Fuerza la restauracion aunque el archivo haya cambiado despues.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "profiles": cmd_profiles,
        "models": cmd_models,
        "setup": cmd_setup,
        "doctor": cmd_doctor,
        "ask": cmd_ask,
        "verify-audit": cmd_verify_audit,
        "rollback": cmd_rollback,
    }
    try:
        return handlers[args.command](args)
    except ConfigError as exc:
        _stdout(f"[x] Error de configuracion: {exc}")
        return 2
    except IdentityError as exc:
        _stdout(f"[x] Error de identidad: {exc}")
        return 2
    except OllamaError as exc:
        _stdout(f"[x] Error de Ollama: {exc}")
        return 2
    except KeyboardInterrupt:
        _stdout("\n[i] Interrumpido por el operador.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
