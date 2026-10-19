import json
import tempfile
import unittest
from pathlib import Path

from agent.audit import AuditLog, verify_chain


class TestAuditChain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_cadena_valida(self):
        with AuditLog("consulta", self.dir) as audit:
            audit.record("tool_call", {"tool": "read_file", "ok": True})
            audit.record("task_finish", {"iteraciones": 3})
            path = audit.path
        ok, count, message = verify_chain(path)
        self.assertTrue(ok, message)
        self.assertGreaterEqual(count, 4)  # session_start + 2 + session_end

    def test_detecta_manipulacion(self):
        with AuditLog("consulta", self.dir) as audit:
            audit.record("tool_call", {"tool": "read_file", "ok": True})
            path = audit.path

        lines = path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[1])
        record["data"]["ok"] = False  # alteracion maliciosa
        lines[1] = json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, _, message = verify_chain(path)
        self.assertFalse(ok)
        self.assertIn("alterado", message.lower())

    def test_detecta_borrado_de_registro(self):
        with AuditLog("consulta", self.dir) as audit:
            audit.record("a", {"n": 1})
            audit.record("b", {"n": 2})
            audit.record("c", {"n": 3})
            path = audit.path

        lines = path.read_text(encoding="utf-8").splitlines()
        del lines[2]  # se elimina un registro intermedio
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, _, message = verify_chain(path)
        self.assertFalse(ok)
        self.assertIn("rota", message.lower())

    def test_archivo_inexistente(self):
        ok, count, _ = verify_chain(self.dir / "nada.jsonl")
        self.assertFalse(ok)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
