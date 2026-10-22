"""Pruebas del acceso a base de datos local (validacion y ejecucion)."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from agent.audit import AuditLog
from agent.config import load_profile
from agent.db import DbError, check_local_host, run_sqlite, validate_sql
from agent.tools import ToolRunner


class TestValidacionSQL(unittest.TestCase):
    def test_lectura_permitida(self):
        self.assertEqual(validate_sql("SELECT * FROM users", read_only=True).kind, "read")
        self.assertEqual(validate_sql("EXPLAIN SELECT 1", read_only=True).kind, "read")
        self.assertEqual(validate_sql("pragma table_info(users)", read_only=True).kind, "read")

    def test_escritura_bloqueada_en_solo_lectura(self):
        for sql in ("INSERT INTO t VALUES (1)", "UPDATE t SET a=1", "DELETE FROM t"):
            with self.assertRaises(DbError):
                validate_sql(sql, read_only=True)
            self.assertEqual(validate_sql(sql, read_only=False).kind, "write")

    def test_ddl_bloqueado_por_defecto(self):
        with self.assertRaises(DbError):
            validate_sql("DROP TABLE users", read_only=False)
        self.assertEqual(validate_sql("DROP TABLE users", read_only=False,
                                      allow_ddl=True).kind, "ddl")

    def test_una_sola_sentencia(self):
        with self.assertRaises(DbError):
            validate_sql("SELECT 1; SELECT 2", read_only=True)

    def test_sin_comentarios(self):
        with self.assertRaises(DbError):
            validate_sql("SELECT 1 -- oculto", read_only=True)
        with self.assertRaises(DbError):
            validate_sql("SELECT /* x */ 1", read_only=True)

    def test_punto_y_coma_final_permitido(self):
        self.assertEqual(validate_sql("SELECT 1;", read_only=True).sql, "SELECT 1")

    def test_sentencia_desconocida(self):
        with self.assertRaises(DbError):
            validate_sql("GOPHER everything", read_only=True)

    def test_caracteres_nulos(self):
        with self.assertRaises(DbError):
            validate_sql("SELECT 1\x00", read_only=True)


class TestSQLPeligroso(unittest.TestCase):
    def test_bloquea_lectura_de_archivos(self):
        for sql in ("SELECT LOAD_FILE('/etc/passwd')",
                    "SELECT * FROM t INTO OUTFILE '/tmp/x'",
                    "SELECT * FROM t INTO DUMPFILE '/tmp/x'",
                    "SELECT * FROM t INTO @variable"):
            with self.assertRaises(DbError):
                validate_sql(sql, read_only=True)

    def test_bloquea_denegacion_de_servicio(self):
        for sql in ("SELECT SLEEP(5)", "SELECT BENCHMARK(100000, MD5('x'))",
                    "SELECT GET_LOCK('a', 10)",
                    "SELECT EXTRACTVALUE(1, CONCAT(0x7e, VERSION()))"):
            with self.assertRaises(DbError):
                validate_sql(sql, read_only=True)

    def test_bloquea_escritura_oculta_en_cte(self):
        with self.assertRaises(DbError):
            validate_sql("WITH x AS (SELECT 1) DELETE FROM t", read_only=True)
        with self.assertRaises(DbError):
            validate_sql("WITH x AS (SELECT 1) UPDATE t SET a = 1", read_only=True)
        self.assertEqual(validate_sql("WITH x AS (SELECT 1) SELECT * FROM x",
                                      read_only=True).kind, "read")

    def test_mysql_sin_comandos_de_cliente(self):
        for sql in ("SELECT 1\n\\! calc", "SELECT 1 \\g", "SELECT 1 \\; "):
            with self.assertRaises(DbError):
                validate_sql(sql, read_only=True, engine="mysql")
        self.assertEqual(validate_sql("SELECT 'a\\b'", read_only=True,
                                      engine="sqlite").kind, "read")

    def test_funciones_de_lectura_no_se_confunden_con_escritura(self):
        self.assertEqual(
            validate_sql("SELECT REPLACE(nombre, 'a', 'b') FROM users",
                         read_only=True).kind, "read")
        self.assertEqual(
            validate_sql("SELECT TRUNCATE(precio, 2) FROM productos",
                         read_only=True).kind, "read")
        with self.assertRaises(DbError):
            validate_sql("SELECT * FROM users FOR UPDATE", read_only=True)

    def test_caracteres_de_control(self):
        with self.assertRaises(DbError):
            validate_sql("SELECT 1\x07", read_only=True)


class TestHost(unittest.TestCase):
    def test_host_local(self):
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertEqual(check_local_host(host), host)

    def test_host_remoto_bloqueado(self):
        for host in ("10.0.0.5", "db.empresa.com", "0.0.0.0.evil.com", ""):
            with self.assertRaises(DbError):
                check_local_host(host)


class TestSQLite(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "pruebas.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, nombre TEXT)")
        con.execute("INSERT INTO users (nombre) VALUES ('ana')")
        con.commit()
        con.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_select_devuelve_filas(self):
        ok, texto, filas = run_sqlite(self.db, "SELECT * FROM users", read_only=True,
                                      timeout=10, max_rows=50)
        self.assertTrue(ok)
        self.assertEqual(filas, 1)
        self.assertIn("ana", texto)

    def test_escritura_cuando_no_es_solo_lectura(self):
        ok, _, filas = run_sqlite(self.db, "INSERT INTO users (nombre) VALUES ('luis')",
                                  read_only=False, timeout=10, max_rows=50)
        self.assertTrue(ok)
        self.assertEqual(filas, 1)
        con = sqlite3.connect(self.db)
        total = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        con.close()
        self.assertEqual(total, 2)

    def test_base_inexistente(self):
        with self.assertRaises(DbError):
            run_sqlite(self.db.parent / "nada.db", "SELECT 1", read_only=True,
                       timeout=10, max_rows=10)


class TestHerramientaDbQuery(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "proyecto"
        self.ws.mkdir()
        self.audit_dir = self.root / "audit"
        self.db = self.ws / "local.db"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, nombre TEXT)")
        con.execute("INSERT INTO users (nombre) VALUES ('ana')")
        con.commit()
        con.close()
        self._audits = []

    def tearDown(self):
        for audit in self._audits:
            try:
                audit.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def _runner(self, profile_name="datos", confirmer=lambda _d: True):
        profile = load_profile(profile_name)
        audit = AuditLog(profile_name, self.audit_dir)
        self._audits.append(audit)
        return ToolRunner(profile, self.ws, audit, confirmer, out=lambda *a: None)

    def test_perfil_sin_db_bloquea(self):
        runner = self._runner("consulta")
        result = runner.call("db_query", {"engine": "sqlite", "database": "local.db",
                                          "sql": "SELECT 1"})
        self.assertTrue(result.blocked)

    def test_select_permitido_con_confirmacion(self):
        runner = self._runner()
        result = runner.call("db_query", {"engine": "sqlite", "database": "local.db",
                                          "sql": "SELECT * FROM users"})
        self.assertTrue(result.ok)
        self.assertIn("ana", result.output)

    def test_escritura_bloqueada_en_perfil_datos(self):
        runner = self._runner()
        result = runner.call("db_query", {"engine": "sqlite", "database": "local.db",
                                          "sql": "DELETE FROM users"})
        self.assertTrue(result.blocked)

    def test_rechazo_del_operador(self):
        runner = self._runner(confirmer=lambda _d: False)
        result = runner.call("db_query", {"engine": "sqlite", "database": "local.db",
                                          "sql": "SELECT * FROM users"})
        self.assertTrue(result.blocked)

    def test_host_remoto_bloqueado(self):
        runner = self._runner()
        result = runner.call("db_query", {"engine": "mysql", "database": "job_itm",
                                          "host": "10.0.0.9", "sql": "SELECT 1"})
        self.assertTrue(result.blocked)

    def test_puerto_invalido_bloqueado(self):
        runner = self._runner()
        result = runner.call("db_query", {"engine": "mysql", "database": "job_itm",
                                          "port": "abc", "sql": "SELECT 1"})
        self.assertTrue(result.blocked)
        result = runner.call("db_query", {"engine": "mysql", "database": "job_itm",
                                          "port": 99999, "sql": "SELECT 1"})
        self.assertTrue(result.blocked)

    def test_nombre_de_base_invalido_bloqueado(self):
        runner = self._runner()
        result = runner.call("db_query", {"engine": "mysql", "database": "../otra",
                                          "sql": "SELECT 1"})
        self.assertTrue(result.blocked)

    def test_fuera_del_workspace_bloqueado(self):
        afuera = self.root / "otra.db"
        sqlite3.connect(afuera).close()
        runner = self._runner()
        result = runner.call("db_query", {"engine": "sqlite", "database": "../otra.db",
                                          "sql": "SELECT 1"})
        self.assertTrue(result.blocked)

    def test_registra_en_bitacora(self):
        runner = self._runner()
        runner.call("db_query", {"engine": "sqlite", "database": "local.db",
                                 "sql": "SELECT * FROM users"})
        audit = self._audits[-1]
        audit.close()
        self._audits.remove(audit)
        contenido = audit.path.read_text(encoding="utf-8")
        self.assertIn("db_query", contenido)


if __name__ == "__main__":
    unittest.main()
