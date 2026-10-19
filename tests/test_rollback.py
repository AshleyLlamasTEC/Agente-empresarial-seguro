"""Pruebas del rollback basado en respaldos y bitacora."""

import tempfile
import unittest
from pathlib import Path

from agent.audit import AuditLog
from agent.config import load_profile
from agent.rollback import (apply_actions, build_actions, load_records, sha256_of,
                            sessions_with_writes)
from agent.tools import ToolRunner


class TestRollback(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "proyecto"
        self.ws.mkdir()
        self.audit_dir = self.root / "audit"
        self.app = self.ws / "app.js"
        self.app.write_text("ORIGINAL\n", encoding="utf-8")
        self._audits = []

    def tearDown(self):
        for audit in self._audits:
            try:
                audit.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def _escribir(self, contenido, dry_run=False, confirmer=lambda _d: True):
        profile = load_profile("desarrollo")
        audit = AuditLog("desarrollo", self.audit_dir)
        self._audits.append(audit)
        tools = ToolRunner(profile, self.ws, audit, confirmer, out=lambda *a: None,
                           dry_run=dry_run)
        result = tools.call("write_file", {"path": "app.js", "content": contenido})
        audit.close()
        self._audits.remove(audit)
        return audit.path, result

    def _records(self):
        return load_records(sorted(self.audit_dir.glob("*.jsonl")))

    def test_restaura_al_estado_anterior(self):
        audit_path, result = self._escribir("MODIFICADO\n")
        self.assertTrue(result.ok)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "MODIFICADO\n")

        records = load_records([audit_path])
        sesion = sessions_with_writes(records)[0]
        acciones = build_actions(records, self.ws, session=sesion)
        self.assertEqual(len(acciones), 1)
        self.assertEqual(acciones[0].mode, "restore")

        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        aplicadas, omitidas = apply_actions(acciones, self.ws, audit2, lambda _d: True,
                                            out=lambda *a: None)
        self.assertEqual(len(aplicadas), 1)
        self.assertEqual(omitidas, [])
        self.assertEqual(self.app.read_text(encoding="utf-8"), "ORIGINAL\n")

    def test_borra_archivo_creado_en_la_sesion(self):
        profile = load_profile("desarrollo")
        audit = AuditLog("desarrollo", self.audit_dir)
        self._audits.append(audit)
        tools = ToolRunner(profile, self.ws, audit, lambda _d: True, out=lambda *a: None)
        tools.call("write_file", {"path": "nuevo.txt", "content": "hola\n"})
        creado = self.ws / "nuevo.txt"
        self.assertTrue(creado.exists())

        records = load_records([audit.path])
        acciones = build_actions(records, self.ws, file_name="nuevo.txt")
        self.assertEqual(acciones[0].mode, "delete")

        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        apply_actions(acciones, self.ws, audit2, lambda _d: True, out=lambda *a: None)
        self.assertFalse(creado.exists())

    def test_no_restaura_si_cambio_despues(self):
        audit_path, _ = self._escribir("V1\n")
        self.app.write_text("EDITADO A MANO\n", encoding="utf-8")

        records = load_records([audit_path])
        acciones = build_actions(records, self.ws)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        _, omitidas = apply_actions(acciones, self.ws, audit2, lambda _d: True,
                                    out=lambda *a: None)
        self.assertEqual(len(omitidas), 1)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "EDITADO A MANO\n")

    def test_force_restaura_aunque_haya_cambiado(self):
        audit_path, _ = self._escribir("V1\n")
        self.app.write_text("EDITADO A MANO\n", encoding="utf-8")

        records = load_records([audit_path])
        acciones = build_actions(records, self.ws)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        aplicadas, omitidas = apply_actions(acciones, self.ws, audit2, lambda _d: True,
                                            out=lambda *a: None, force=True)
        self.assertEqual(len(aplicadas), 1)
        self.assertEqual(omitidas, [])
        self.assertEqual(self.app.read_text(encoding="utf-8"), "ORIGINAL\n")

    def test_dry_run_no_toca_nada(self):
        audit_path, _ = self._escribir("V1\n")
        records = load_records([audit_path])
        acciones = build_actions(records, self.ws)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        apply_actions(acciones, self.ws, audit2, lambda _d: True, out=lambda *a: None,
                      dry_run=True)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "V1\n")

    def test_rechazo_del_operador(self):
        audit_path, _ = self._escribir("V1\n")
        records = load_records([audit_path])
        acciones = build_actions(records, self.ws)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        _, omitidas = apply_actions(acciones, self.ws, audit2, lambda _d: False,
                                    out=lambda *a: None)
        self.assertEqual(len(omitidas), 1)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "V1\n")

    def test_solo_ultima_escritura(self):
        self._escribir("V1\n")
        audit_path, _ = self._escribir("V2\n")
        records = load_records([audit_path])
        acciones = build_actions(records, self.ws, last_only=True)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        apply_actions(acciones, self.ws, audit2, lambda _d: True, out=lambda *a: None)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "V1\n")

    def test_sesion_completa_vuelve_al_original(self):
        self._escribir("V1\n")
        self._escribir("V2\n")
        self._escribir("V3\n")
        records = self._records()
        sesiones = sessions_with_writes(records)
        acciones = build_actions(records, self.ws, session=sesiones[0])
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        apply_actions(acciones, self.ws, audit2, lambda _d: True, out=lambda *a: None)
        self.assertEqual(self.app.read_text(encoding="utf-8"), "ORIGINAL\n")

    def test_bitacora_del_rollback_es_verificable(self):
        from agent.audit import verify_chain
        audit_path, _ = self._escribir("V1\n")
        records = load_records([audit_path])
        acciones = build_actions(records, self.ws)
        audit2 = AuditLog("rollback", self.audit_dir)
        self._audits.append(audit2)
        apply_actions(acciones, self.ws, audit2, lambda _d: True, out=lambda *a: None)
        audit2.close()
        self._audits.remove(audit2)
        ok, count, _ = verify_chain(audit2.path)
        self.assertTrue(ok)
        self.assertGreaterEqual(count, 2)


if __name__ == "__main__":
    unittest.main()
