import unittest
from pathlib import Path

from agent.dlp import is_sensitive_path, redact


class TestDlp(unittest.TestCase):
    def test_censura_contrasenas(self):
        clean, count = redact('DB_PASSWORD="super-secreta-123"')
        self.assertGreater(count, 0)
        self.assertNotIn("super-secreta-123", clean)
        self.assertIn("REDACTADO", clean)

    def test_censura_claves_de_api(self):
        for sample in (
            "api_key: sk-abcdefghijklmnopqrstuvwx",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "Authorization: Bearer abcdefghijklmnop12345",
        ):
            with self.subTest(muestra=sample):
                clean, count = redact(sample)
                self.assertGreater(count, 0)
                self.assertIn("REDACTADO", clean)

    def test_censura_cadenas_de_conexion(self):
        clean, count = redact("mysql://root:clave123@10.0.0.5:3306/ventas")
        self.assertGreater(count, 0)
        self.assertNotIn("clave123", clean)

    def test_censura_llave_privada(self):
        sample = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n-----END RSA PRIVATE KEY-----"
        clean, count = redact(sample)
        self.assertGreater(count, 0)
        self.assertNotIn("MIIEowIBAAKCAQEA", clean)

    def test_texto_normal_no_se_modifica(self):
        sample = "def suma(a, b):\n    return a + b\n"
        clean, count = redact(sample)
        self.assertEqual(count, 0)
        self.assertEqual(clean, sample)

    def test_detecta_archivos_sensibles(self):
        for candidate in (".env", ".env.local", "server.pem", "id_rsa", "secrets.yml",
                          "credentials.json", "appsettings.production.json"):
            with self.subTest(archivo=candidate):
                sensitive, reason = is_sensitive_path(Path(candidate))
                self.assertTrue(sensitive, f"{candidate} deberia ser sensible")
                self.assertTrue(reason)

    def test_no_marca_codigo_normal(self):
        for candidate in ("src/app.py", "README.md", "package.json", "index.js"):
            with self.subTest(archivo=candidate):
                sensitive, _ = is_sensitive_path(Path(candidate))
                self.assertFalse(sensitive)


if __name__ == "__main__":
    unittest.main()
