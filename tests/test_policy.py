import tempfile
import unittest
from pathlib import Path

from agent.config import ConfigError, load_profile, validate_profile
from agent.policy import check_command


class TestPolicyCommands(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.consulta = load_profile("consulta")
        cls.desarrollo = load_profile("desarrollo")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def test_consulta_no_permite_ningun_comando(self):
        decision = check_command("git status", self.consulta, self.ws)
        self.assertFalse(decision.allowed)
        self.assertIn("lista blanca", decision.reason)

    def test_desarrollo_permite_comando_lectura(self):
        self.assertTrue(check_command("git status", self.desarrollo, self.ws).allowed)
        self.assertTrue(check_command("npm test", self.desarrollo, self.ws).allowed)
        self.assertTrue(check_command("python -m pytest -q", self.desarrollo, self.ws).allowed)

    def test_bloquea_encadenamiento_de_comandos(self):
        for candidate in (
            "git status; rm -rf /",
            "git status && del /f /q *",
            "git log | ssh user@host",
            "echo $(whoami)",
            "cat archivo > copia",
            "git status `id`",
        ):
            with self.subTest(comando=candidate):
                self.assertFalse(check_command(candidate, self.desarrollo, self.ws).allowed)

    def test_bloquea_herramientas_de_red_y_produccion(self):
        for candidate in (
            "ssh usuario@servidor",
            "scp archivo usuario@servidor:/tmp",
            "curl http://interna.local",
            "wget http://interna.local",
            "mysql -h produccion -u root -p",
            "mysqldump produccion > dump.sql",
            "psql postgres://prod/db",
            "kubectl get pods",
            "docker ps",
            "aws s3 ls",
            "az login",
            "Invoke-WebRequest http://x",
            "powershell -Command dir",
        ):
            with self.subTest(comando=candidate):
                self.assertFalse(check_command(candidate, self.desarrollo, self.ws).allowed)

    def test_bloquea_git_que_muta_o_toca_remotos(self):
        for candidate in (
            "git push origin main",
            "git remote add origin http://x",
            "git fetch --all",
            "git pull",
            "git reset --hard",
            "git clean -fd",
            "git checkout .",
        ):
            with self.subTest(comando=candidate):
                self.assertFalse(check_command(candidate, self.desarrollo, self.ws).allowed)

    def test_bloquea_instalacion_de_dependencias(self):
        for candidate in (
            "npm install lodash",
            "npm i lodash",
            "pip install requests",
            "composer install",
            "dotnet restore",
        ):
            with self.subTest(comando=candidate):
                self.assertFalse(check_command(candidate, self.desarrollo, self.ws).allowed)

    def test_bloquea_ejecucion_dinamica(self):
        for candidate in (
            "python -c \"import os; os.system('x')\"",
            "node -e \"require('child_process')\"",
            "Invoke-Expression 'x'",
            "Start-Process cmd",
        ):
            with self.subTest(comando=candidate):
                self.assertFalse(check_command(candidate, self.desarrollo, self.ws).allowed)

    def test_bloquea_argumentos_de_ruta_fuera_del_workspace(self):
        self.assertFalse(check_command("cat ../secreto.txt", self.desarrollo, self.ws).allowed)
        self.assertFalse(check_command("cat C:\\Windows\\win.ini", self.desarrollo, self.ws).allowed)
        self.assertFalse(check_command("type /etc/passwd", self.desarrollo, self.ws).allowed)

    def test_permite_argumentos_dentro_del_workspace(self):
        (self.ws / "src").mkdir()
        (self.ws / "src" / "app.py").write_text("print(1)", encoding="utf-8")
        self.assertTrue(check_command("cat src/app.py", self.desarrollo, self.ws).allowed)

    def test_bloquea_comando_vacio_o_largo(self):
        self.assertFalse(check_command("", self.desarrollo, self.ws).allowed)
        self.assertFalse(check_command("git " + "a" * 600, self.desarrollo, self.ws).allowed)


class TestProfileValidation(unittest.TestCase):
    def _base(self, **overrides):
        raw = {
            "name": "prueba",
            "description": "perfil de prueba",
            "model": "qwen2.5-coder:7b",
            "allow_write": False,
            "allow_shell": False,
            "require_confirmation": True,
            "commands_allow": [],
            "commands_deny": [],
            "path_deny_names": [],
            "path_deny_globs": [],
        }
        raw.update(overrides)
        return raw

    def test_rechaza_modelo_en_la_nube(self):
        with self.assertRaises(ConfigError):
            validate_profile(self._base(model="deepseek-v3.1:671b-cloud"), "test")

    def test_rechaza_escritura_sin_confirmacion(self):
        with self.assertRaises(ConfigError):
            validate_profile(self._base(allow_write=True, require_confirmation=False), "test")

    def test_rechaza_shell_sin_lista_blanca(self):
        with self.assertRaises(ConfigError):
            validate_profile(self._base(allow_shell=True, commands_allow=[]), "test")

    def test_rechaza_campos_desconocidos(self):
        with self.assertRaises(ConfigError):
            validate_profile(self._base(campo_peligroso=True), "test")

    def test_rechaza_nombre_de_perfil_invalido(self):
        with self.assertRaises(ConfigError):
            validate_profile(self._base(name="Perfil Malo"), "test")


if __name__ == "__main__":
    unittest.main()
