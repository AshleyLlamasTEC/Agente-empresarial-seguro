import tempfile
import unittest
from pathlib import Path

from agent.sandbox import SandboxError, looks_like_path, resolve_in_workspace


class TestSandbox(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self._tmp.name).resolve()
        (self.ws / "src").mkdir()
        (self.ws / "src" / "app.py").write_text("print(1)", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_permite_rutas_internas(self):
        resolved = resolve_in_workspace(self.ws, "src/app.py", must_exist=True)
        self.assertEqual(resolved, (self.ws / "src" / "app.py").resolve())

    def test_bloquea_traversal(self):
        for candidate in ("../secreto.txt", "src/../../secreto.txt", "..\\..\\windows\\win.ini"):
            with self.subTest(ruta=candidate):
                with self.assertRaises(SandboxError):
                    resolve_in_workspace(self.ws, candidate)

    def test_bloquea_rutas_absolutas(self):
        for candidate in ("C:\\Windows\\win.ini", "/etc/passwd", "D:\\datos\\prod.sql"):
            with self.subTest(ruta=candidate):
                with self.assertRaises(SandboxError):
                    resolve_in_workspace(self.ws, candidate)

    def test_bloquea_unc_y_home(self):
        for candidate in ("\\\\servidor\\recurso\\archivo.txt", "~/documentos/nota.txt"):
            with self.subTest(ruta=candidate):
                with self.assertRaises(SandboxError):
                    resolve_in_workspace(self.ws, candidate)

    def test_bloquea_nombres_reservados(self):
        with self.assertRaises(SandboxError):
            resolve_in_workspace(self.ws, "CON")

    def test_bloquea_ruta_vacia(self):
        with self.assertRaises(SandboxError):
            resolve_in_workspace(self.ws, "   ")

    def test_heuristica_de_rutas(self):
        self.assertTrue(looks_like_path("../x"))
        self.assertTrue(looks_like_path("C:\\x"))
        self.assertTrue(looks_like_path("src/app.py"))
        self.assertFalse(looks_like_path("--flag"))
        self.assertFalse(looks_like_path("status"))


if __name__ == "__main__":
    unittest.main()
