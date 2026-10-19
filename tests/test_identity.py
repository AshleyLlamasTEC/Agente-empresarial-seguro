"""Pruebas de la identidad configurable (agente en blanco por defecto)."""

import json
import tempfile
import unittest
from pathlib import Path

from agent.config import load_profile
from agent.identity import (IDENTITY_PATH, Identity, IdentityError, blank_identity,
                            load_identity, reset_identity, save_identity,
                            validate_identity)
from agent.prompts import build_system_prompt, identity_block


class TestIdentidadEnBlanco(unittest.TestCase):
    def test_repo_empieza_sin_identidad(self):
        """El repositorio NO trae identity.json: el agente arranca en blanco."""
        self.assertFalse(IDENTITY_PATH.exists(),
                         "No debe existir identity.json en el repositorio.")

    def test_blank_no_configurada(self):
        identidad = blank_identity()
        self.assertFalse(identidad.configured)
        self.assertFalse(identidad.has_user)
        self.assertEqual(identidad.agent_name, "")

    def test_load_sin_archivo_devuelve_blanco(self):
        identidad = load_identity(Path("no-existe-jamas.json"))
        self.assertFalse(identidad.configured)

    def test_sin_datos_del_usuario_de_fabrica(self):
        """No hay ningun dato personal precargado."""
        identidad = blank_identity()
        self.assertEqual(identidad.user_name, "")
        self.assertEqual(identidad.user_notes, [])


class TestPersistencia(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "identity.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_guardar_y_cargar(self):
        original = Identity(agent_name="Kaizen", user_name="Alex",
                            user_notes=["Prefiere respuestas breves"], tone="zen")
        save_identity(original, self.path)
        cargada = load_identity(self.path)
        self.assertTrue(cargada.configured)
        self.assertEqual(cargada.agent_name, "Kaizen")
        self.assertEqual(cargada.user_name, "Alex")
        self.assertEqual(cargada.user_notes, ["Prefiere respuestas breves"])

    def test_reset(self):
        save_identity(Identity(agent_name="Kaizen"), self.path)
        self.assertTrue(reset_identity(self.path))
        self.assertFalse(load_identity(self.path).configured)
        self.assertFalse(reset_identity(self.path))

    def test_json_invalido(self):
        self.path.write_text("{no es json", encoding="utf-8")
        with self.assertRaises(IdentityError):
            load_identity(self.path)

    def test_tono_por_defecto(self):
        self.path.write_text(json.dumps({"agent_name": "Kaizen"}), encoding="utf-8")
        cargada = load_identity(self.path)
        self.assertIn("respetuoso", cargada.tone.lower())


class TestValidacion(unittest.TestCase):
    def test_campos_no_permitidos(self):
        with self.assertRaises(IdentityError):
            validate_identity({"agent_name": "x", "password": "1234"})

    def test_notas_como_texto_se_convierte(self):
        identidad = validate_identity({"agent_name": "Kaizen", "user_notes": "una nota"})
        self.assertEqual(identidad.user_notes, ["una nota"])

    def test_limite_de_longitud(self):
        identidad = validate_identity({"agent_name": "a" * 500})
        self.assertLessEqual(len(identidad.agent_name), 60)


class TestPrompt(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile("consulta")

    def test_prompt_en_blanco_no_inventa_nombre(self):
        texto = build_system_prompt(self.profile, "C:/ws", "- list_dir", blank_identity())
        self.assertIn("IDENTIDAD (sin configurar)", texto)
        self.assertIn("NO conoces ningun dato", texto)
        self.assertIn("python -m agent.cli setup", texto)

    def test_prompt_con_identidad(self):
        identidad = Identity(agent_name="Kaizen", user_name="Alex",
                             user_notes=["Trabaja en soporte"], tone="respetuoso y zen")
        texto = build_system_prompt(self.profile, "C:/ws", "- list_dir", identidad)
        self.assertIn("Tu nombre es Kaizen", texto)
        self.assertIn("Alex", texto)
        self.assertIn("Trabaja en soporte", texto)

    def test_tono_siempre_presente(self):
        texto = build_system_prompt(self.profile, "C:/ws", "- list_dir", blank_identity())
        self.assertIn("Tono", texto)
        self.assertIn("Zen", texto)

    def test_identity_block_sin_identidad(self):
        bloque = "\n".join(identity_block(None))
        self.assertIn("sin configurar", bloque)


if __name__ == "__main__":
    unittest.main()
