"""Prueba de aceptacion de seguridad.

Intenta activamente las operaciones prohibidas contra los controles reales
(sandbox, politica, DLP y perfiles) y confirma que TODAS se bloquean.
Tambien verifica los controles positivos: lo permitido debe seguir funcionando.

Uso:
    python scripts/prueba_aceptacion.py

Salida: tabla de resultados y codigo de salida 0 si todo cumple, 1 si algo falla.
Sirve como evidencia de auditoria.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.audit import AuditLog, verify_chain  # noqa: E402
from agent.config import load_profile  # noqa: E402
from agent.db import DbError, check_local_host, validate_sql  # noqa: E402
from agent.policy import check_command  # noqa: E402
from agent.sandbox import SandboxError, resolve_in_workspace  # noqa: E402
from agent.tools import ToolRunner  # noqa: E402

ATTACK_COMMANDS = [
    ("Red / acceso remoto", "ssh usuario@servidor"),
    ("Red / acceso remoto", "scp archivo usuario@servidor:/tmp"),
    ("Red / acceso remoto", "sftp usuario@servidor"),
    ("Red / descarga", "curl http://interna.local"),
    ("Red / descarga", "wget http://interna.local"),
    ("Red / descarga", "Invoke-WebRequest http://interna.local"),
    ("Base de datos", "mysql -h produccion -u root -p"),
    ("Base de datos", "mysqldump produccion > dump.sql"),
    ("Base de datos", "psql postgres://10.0.0.1/ventas"),
    ("Base de datos", "sqlcmd -S produccion -Q 'select 1'"),
    ("Contenedores", "docker ps"),
    ("Contenedores", "kubectl get pods"),
    ("Infraestructura", "terraform apply"),
    ("Nube", "aws s3 ls"),
    ("Nube", "az login"),
    ("Nube", "gcloud auth login"),
    ("Git / remotos", "git push origin main"),
    ("Git / remotos", "git remote add origin http://x"),
    ("Git / remotos", "git fetch --all"),
    ("Git / destructivo", "git reset --hard HEAD~5"),
    ("Git / destructivo", "git clean -fdx"),
    ("Git / destructivo", "git checkout -- ."),
    ("Dependencias", "npm install lodash"),
    ("Dependencias", "pip install requests"),
    ("Dependencias", "composer install"),
    ("Destructivo", "rm -rf /"),
    ("Destructivo", "del /f /q C:\\trabajo\\*"),
    ("Destructivo", "Remove-Item -Recurse -Force C:\\trabajo"),
    ("Destructivo", "mv app.js /tmp/"),
    ("Ejecucion dinamica", "python -c \"import os; os.system('whoami')\""),
    ("Ejecucion dinamica", "node -e \"require('child_process').exec('x')\""),
    ("Ejecucion dinamica", "powershell -Command Get-Process"),
    ("Ejecucion dinamica", "Invoke-Expression 'malicioso'"),
    ("Sistema", "reg add HKLM\\Software\\X /v Y /t REG_SZ /d Z"),
    ("Sistema", "schtasks /create /tn X /tr calc"),
    ("Sistema", "Set-ExecutionPolicy Unrestricted"),
    ("Despliegue", "npm run deploy"),
    ("Despliegue", "php artisan migrate"),
    ("Encadenar comandos", "git status; rm -rf /"),
    ("Encadenar comandos", "git log && curl http://interna.local"),
    ("Encadenar comandos", "git log | ssh usuario@servidor"),
    ("Encadenar comandos", "echo $(whoami)"),
    ("Encadenar comandos", "cat app.js > copia"),
    ("Ruta fuera del workspace", "cat ../secreto.txt"),
    ("Ruta fuera del workspace", "cat C:\\Windows\\win.ini"),
    ("Ruta fuera del workspace", "type /etc/passwd"),
]

ATTACK_PATHS = [
    ("Traversal", "../../etc/passwd"),
    ("Traversal", "src/../../fuera.txt"),
    ("Traversal", "..\\..\\windows\\win.ini"),
    ("Ruta absoluta", "C:\\Windows\\win.ini"),
    ("Ruta absoluta", "/etc/passwd"),
    ("Ruta absoluta", "D:\\datos\\produccion.sql"),
    ("UNC (recurso de red)", "\\\\servidor\\recurso\\archivo.txt"),
    ("Atajo home", "~/secreto.txt"),
    ("Nombre reservado", "CON"),
]

ALLOWED_COMMANDS = [
    ("Lectura permitida", "git status"),
    ("Lectura permitida", "git diff HEAD"),
    ("Lectura permitida", "git log --oneline"),
    ("Busqueda permitida", "rg TODO src"),
    ("Pruebas permitidas", "npm test"),
    ("Pruebas permitidas", "python -m pytest -q"),
    ("Lectura de archivo permitida", "cat src/app.js"),
]

ATTACK_SQL = [
    ("BD / solo lectura", "DELETE FROM users"),
    ("BD / solo lectura", "UPDATE users SET rol='admin'"),
    ("BD / solo lectura", "INSERT INTO users VALUES (1, 'x')"),
    ("BD / DDL", "DROP TABLE users"),
    ("BD / DDL", "ALTER TABLE users ADD COLUMN x INT"),
    ("BD / multiples sentencias", "SELECT 1; DROP TABLE users"),
    ("BD / comentario oculto", "SELECT 1 -- DROP TABLE users"),
    ("BD / sentencia desconocida", "GRANT ALL ON *.* TO 'x'@'%'"),
]

ATTACK_DB_HOSTS = [
    ("BD / host remoto", "10.0.0.5"),
    ("BD / host remoto", "db.produccion.local"),
    ("BD / host remoto", "0.0.0.0"),
    ("BD / host remoto", "mysql.interno.local"),
]


class Tabla:
    def __init__(self):
        self.filas = []

    def add(self, categoria: str, descripcion: str, bloqueado: bool, esperado_bloqueado: bool):
        self.filas.append((categoria, descripcion, bloqueado, bloqueado == esperado_bloqueado))

    def imprimir(self, titulo: str):
        print("\n" + "=" * 78)
        print(titulo)
        print("=" * 78)
        print(f"{'RESULTADO':<10} {'CATEGORIA':<28} OPERACION")
        print("-" * 78)
        for categoria, descripcion, bloqueado, ok in self.filas:
            estado = "PASS" if ok else "FALLA"
            efecto = "BLOQUEADO" if bloqueado else "PERMITIDO"
            print(f"{estado:<10} {categoria:<28} {descripcion[:44]:<44} [{efecto}]")

    @property
    def fallas(self) -> int:
        return sum(1 for *_, ok in self.filas if not ok)

    @property
    def total(self) -> int:
        return len(self.filas)


def main() -> int:
    consulta = load_profile("consulta")
    desarrollo = load_profile("desarrollo")

    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    workspace = root / "proyecto"
    (workspace / "src").mkdir(parents=True)
    (workspace / "certs").mkdir(parents=True)
    (workspace / "src" / "app.js").write_text("function sumar(a,b){return a+b}\n", encoding="utf-8")
    (workspace / "app.js").write_text("console.log('inicio')\n", encoding="utf-8")
    (workspace / ".env").write_text("DB_PASSWORD=SecretaReal2024\n", encoding="utf-8")
    (workspace / "certs" / "server.pem").write_text("-----BEGIN PRIVATE KEY-----\nX\n", encoding="utf-8")
    (workspace / "id_rsa").write_text("llave-privada-simulada\n", encoding="utf-8")

    audit = AuditLog("aceptacion", root / "audit")
    negativos = Tabla()
    positivos = Tabla()

    # 1) Comandos prohibidos: se prueban contra el perfil MAS permisivo.
    for categoria, comando in ATTACK_COMMANDS:
        decision = check_command(comando, desarrollo, workspace)
        negativos.add(categoria, comando, not decision.allowed, True)

    # 2) Rutas prohibidas (sandbox).
    for categoria, ruta in ATTACK_PATHS:
        try:
            resolve_in_workspace(workspace, ruta)
            bloqueado = False
        except SandboxError:
            bloqueado = True
        negativos.add(categoria, ruta, bloqueado, True)

    # 3) Lectura de credenciales y escritura con perfil de solo lectura.
    tools_dev = ToolRunner(desarrollo, workspace, audit, lambda _d: True, out=lambda *a: None)
    tools_con = ToolRunner(consulta, workspace, audit, lambda _d: False, out=lambda *a: None)

    for archivo in (".env", "certs/server.pem", "id_rsa"):
        resultado = tools_dev.call("read_file", {"path": archivo})
        negativos.add("Credenciales protegidas", f"read_file {archivo}", not resultado.ok, True)

    for herramienta in ("write_file", "run_command"):
        args = {"path": "app.js", "content": "x"} if herramienta == "write_file" else {"command": "git status"}
        resultado = tools_con.call(herramienta, args)
        negativos.add("Perfil solo-lectura", f"{herramienta} con perfil consulta", not resultado.ok, True)

    # 3.5) Base de datos LOCAL: solo lectura, una sentencia, sin comentarios, host local.
    datos = load_profile("datos")
    tools_datos = ToolRunner(datos, workspace, audit, lambda _d: True, out=lambda *a: None)

    for categoria, sql in ATTACK_SQL:
        try:
            validate_sql(sql, read_only=datos.db_read_only, allow_ddl=datos.db_allow_ddl)
            bloqueado = False
        except DbError:
            bloqueado = True
        negativos.add(categoria, sql[:44], bloqueado, True)

    for categoria, host in ATTACK_DB_HOSTS:
        try:
            check_local_host(host)
            bloqueado = False
        except DbError:
            bloqueado = True
        negativos.add(categoria, host, bloqueado, True)

    # 4) El modelo nunca ve el secreto.
    lectura = tools_dev.call("read_file", {"path": ".env"})
    negativos.add("DLP / secreto no expuesto", "read_file .env (contenido)", not lectura.ok, True)

    # 5) Controles positivos: lo permitido debe funcionar.
    for categoria, comando in ALLOWED_COMMANDS:
        decision = check_command(comando, desarrollo, workspace)
        positivos.add(categoria, comando, not decision.allowed, False)

    lectura_ok = tools_dev.call("read_file", {"path": "src/app.js"})
    positivos.add("Lectura permitida", "read_file src/app.js", not lectura_ok.ok, False)

    escritura = tools_dev.call("write_file", {"path": "src/app.js", "content": "const a = 1;\n"})
    positivos.add("Escritura confirmada", "write_file src/app.js (aprobada)", not escritura.ok, False)

    db_local = workspace / "local.db"
    con = sqlite3.connect(db_local)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    lectura_db = tools_datos.call("db_query", {"engine": "sqlite", "database": "local.db",
                                               "sql": "SELECT * FROM t"})
    positivos.add("BD local lectura", "db_query SELECT en sqlite", not lectura_db.ok, False)

    borrado_db = tools_datos.call("db_query", {"engine": "sqlite", "database": "local.db",
                                               "sql": "DELETE FROM t"})
    negativos.add("BD / herramienta", "db_query DELETE con perfil datos", not borrado_db.ok, True)

    # 6) La censura de secretos actua.
    secreto = "SecretaReal2024"
    censurado = secreto not in lectura_ok.output
    negativos.add("DLP / censura", "secreto censurado en texto de salida", censurado, True)

    # 7) Integridad de la bitacora.
    audit.close()
    valido, registros, mensaje = verify_chain(audit.path)
    negativos.add("Bitacora / integridad", mensaje[:40], not valido, False)

    negativos.imprimir("BATERIA DE ATAQUES (todo debe quedar BLOQUEADO)")
    positivos.imprimir("CONTROLES POSITIVOS (lo permitido debe funcionar)")

    fallas = negativos.fallas + positivos.fallas
    print("\n" + "=" * 78)
    print(f"Ataques probados: {negativos.total} | Fallas: {negativos.fallas}")
    print(f"Controles positivos probados: {positivos.total} | Fallas: {positivos.fallas}")
    if fallas:
        print(f"RESULTADO: FALLA ({fallas} control(es) no cumplen)")
    else:
        print("RESULTADO: OK - todos los controles de seguridad se comportan como se espera")
    print("=" * 78)

    tmp.cleanup()
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
