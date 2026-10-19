"""Pruebas del bucle del agente con un modelo simulado.

No requieren Ollama: se inyecta un cliente falso para verificar que las
politicas se aplican antes de tocar el disco.
"""

import json
import tempfile
import unittest
from pathlib import Path

from agent.agent import Agent, extract_fenced_content, extract_json
from agent.audit import AuditLog
from agent.config import load_profile
from agent.tools import ToolRunner


class FakeLlm:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.model = "modelo-simulado:1b"
        self.vistos = []

    def chat(self, messages, **kwargs):
        self.vistos.append(messages)
        if not self.respuestas:
            return json.dumps({"thought": "fin", "action": "final", "answer": "sin guion"})
        return self.respuestas.pop(0)


def accion(action, **args):
    return json.dumps({"thought": "prueba", "action": action, "args": args})


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "proyecto"
        self.ws.mkdir()
        self.audit_dir = self.root / "audit"
        self._audits = []
        (self.ws / "app.js").write_text("function sumar(a,b){return a+b}\n", encoding="utf-8")

    def tearDown(self):
        for audit in self._audits:
            try:
                audit.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def _agent(self, profile_name, respuestas, confirmer=lambda _d: False, **kwargs):
        profile = load_profile(profile_name)
        audit = AuditLog(profile_name, self.audit_dir)
        self._audits.append(audit)
        tools = ToolRunner(profile, self.ws, audit, confirmer, out=lambda *a: None, **kwargs)
        llm = FakeLlm(respuestas)
        return Agent(profile, self.ws, llm, tools, audit, out=lambda *a: None), llm

    def test_flujo_lectura_y_final(self):
        agent, _ = self._agent("consulta", [
            accion("list_dir", path="."),
            accion("read_file", path="app.js"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Informe completo"}),
        ])
        result = agent.run("Analiza el proyecto")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["answer"], "Informe completo")
        self.assertEqual(result["tool_calls"], 2)

    def test_consulta_bloquea_escritura(self):
        agent, llm = self._agent("consulta", [
            accion("write_file", path="app.js", content="hackeado"),
            json.dumps({"thought": "listo", "action": "final", "answer": "No pude escribir"}),
        ])
        agent.run("Modifica app.js")

        contenido = (self.ws / "app.js").read_text(encoding="utf-8")
        self.assertEqual(contenido, "function sumar(a,b){return a+b}\n")

        observaciones = [m["content"] for m in llm.vistos[1] if m["role"] == "user"]
        self.assertTrue(any("BLOQUEADO" in obs for obs in observaciones))

    def test_escritura_rechazada_por_el_operador(self):
        agent, _ = self._agent("desarrollo", [
            accion("write_file", path="app.js", content="nuevo"),
        ], confirmer=lambda _d: False)
        agent.run("Modifica app.js")
        self.assertEqual((self.ws / "app.js").read_text(encoding="utf-8"),
                         "function sumar(a,b){return a+b}\n")

    def test_escritura_aprobada_con_respaldo(self):
        agent, _ = self._agent("desarrollo", [
            accion("write_file", path="app.js", content="console.log('ok')\n"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Aplicado"}),
        ], confirmer=lambda _d: True)
        result = agent.run("Corrige app.js")
        self.assertEqual(result["status"], "ok")
        self.assertEqual((self.ws / "app.js").read_text(encoding="utf-8"), "console.log('ok')\n")
        respaldos = list((self.audit_dir / "backups").glob("*.bak"))
        self.assertEqual(len(respaldos), 1)

    def test_dry_run_no_escribe(self):
        agent, _ = self._agent("desarrollo", [
            accion("write_file", path="app.js", content="cambio simulado"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Simulado"}),
        ], confirmer=lambda _d: True, dry_run=True)
        agent.run("Corrige app.js")
        self.assertEqual((self.ws / "app.js").read_text(encoding="utf-8"),
                         "function sumar(a,b){return a+b}\n")

    def test_comando_prohibido_no_se_ejecuta(self):
        agent, llm = self._agent("desarrollo", [
            accion("run_command", command="ssh usuario@produccion"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Bloqueado"}),
        ], confirmer=lambda _d: True)
        agent.run("Entra al servidor")
        observaciones = " ".join(m["content"] for m in llm.vistos[1] if m["role"] == "user")
        self.assertIn("BLOQUEADO", observaciones)

    def test_respuesta_no_json_se_corrige(self):
        agent, _ = self._agent("consulta", [
            "Claro, te ayudo con eso.",
            json.dumps({"thought": "listo", "action": "final", "answer": "Corregido"}),
        ])
        result = agent.run("Ping")
        self.assertEqual(result["answer"], "Corregido")

    def test_lectura_de_credenciales_bloqueada(self):
        (self.ws / ".env").write_text("DB_PASSWORD=real\n", encoding="utf-8")
        agent, llm = self._agent("consulta", [
            accion("read_file", path=".env"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Bloqueado"}),
        ])
        agent.run("Lee el .env")
        observaciones = " ".join(m["content"] for m in llm.vistos[1] if m["role"] == "user")
        self.assertIn("BLOQUEADO", observaciones)
        self.assertNotIn("real", observaciones)

    def test_secretos_censurados_antes_de_llegar_al_modelo(self):
        secreto = "SuperSecreta2024!"
        (self.ws / "config.js").write_text(
            f'const DB_PASSWORD = "{secreto}";\n'
            'const url = "mysql://root:claveReal123@10.0.0.50:3306/ventas_prod";\n',
            encoding="utf-8",
        )
        agent, llm = self._agent("consulta", [
            accion("read_file", path="config.js"),
            json.dumps({"thought": "listo", "action": "final", "answer": "Listo"}),
        ])
        agent.run("Lee config.js")

        visto_por_el_modelo = " ".join(
            m["content"] for messages in llm.vistos for m in messages if m["role"] in ("user", "system")
        )
        self.assertNotIn(secreto, visto_por_el_modelo)
        self.assertNotIn("claveReal123", visto_por_el_modelo)
        self.assertIn("REDACTADO", visto_por_el_modelo)

        contenidos = "".join(
            a.path.read_text(encoding="utf-8") for a in self._audits
        )
        self.assertIn("secretos_censurados", contenidos)
        self.assertNotIn(secreto, contenidos)


class TestExtractJson(unittest.TestCase):
    def test_json_plano(self):
        self.assertEqual(extract_json('{"action": "final"}'), {"action": "final"})

    def test_json_con_bloque_de_codigo(self):
        texto = '```json\n{"action": "final", "args": {}}\n```'
        self.assertEqual(extract_json(texto), {"action": "final", "args": {}})

    def test_json_embebido_en_texto(self):
        texto = 'Aqui va: {"action": "list_dir"} y ya.'
        self.assertEqual(extract_json(texto), {"action": "list_dir"})

    def test_sin_json(self):
        self.assertIsNone(extract_json("no hay nada aqui"))
        self.assertIsNone(extract_json(""))

    def test_repara_llave_faltante(self):
        """Caso real: qwen2.5-coder trunca el objeto JSON."""
        texto = '{"thought": "x", "action": "write_file", "args": {"path": "a.js", "content": "let a = 1;\\n}"}'
        reparado = extract_json(texto)
        self.assertIsNotNone(reparado)
        self.assertEqual(reparado["action"], "write_file")
        self.assertIn("let a = 1;", reparado["args"]["content"])

    def test_repara_saltos_de_linea_crudos(self):
        texto = '{"action": "write_file", "args": {"path": "a.js", "content": "linea1\nlinea2"}}'
        reparado = extract_json(texto)
        self.assertIsNotNone(reparado)
        self.assertEqual(reparado["args"]["content"], "linea1\nlinea2")

    def test_repara_coma_final(self):
        texto = '{"action": "final", "args": {"a": 1,},}'
        self.assertEqual(extract_json(texto), {"action": "final", "args": {"a": 1}})

    def test_extrae_bloque_de_codigo(self):
        texto = (
            '{"thought": "x", "action": "write_file", "args": {"path": "a.js"}}\n'
            "```javascript\nconst x = 1;\nconst y = 2;\n```"
        )
        contenido = extract_fenced_content(texto)
        self.assertIsNotNone(contenido)
        self.assertIn("const x = 1;", contenido)
        self.assertIn("const y = 2;", contenido)

    def test_no_confunde_el_json_con_contenido(self):
        texto = '```json\n{"action": "final", "answer": "ok"}\n```'
        self.assertIsNone(extract_fenced_content(texto))

    def test_caso_real_json_mas_bloque_de_codigo(self):
        """Caso observado con qwen2.5-coder:7b siguiendo el protocolo nuevo."""
        texto = (
            '{"thought": "Necesito corregir el ciclo", "action": "write_file", '
            '"args": {"path": "app.js"}}\n'
            "```javascript\nfunction promedio(v) {\n  return v.length;\n}\n```"
        )
        action = extract_json(texto)
        self.assertIsNotNone(action)
        self.assertEqual(action["action"], "write_file")
        self.assertEqual(action["args"]["path"], "app.js")
        contenido = extract_fenced_content(texto)
        self.assertIn("function promedio", contenido)


class TestProtocoloRobusto(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ws = self.root / "proyecto"
        self.ws.mkdir()
        self.audit_dir = self.root / "audit"
        self._audits = []
        (self.ws / "app.js").write_text("let a = 1;\n", encoding="utf-8")

    def tearDown(self):
        for audit in self._audits:
            try:
                audit.close()
            except Exception:
                pass
        self._tmp.cleanup()

    def _agent(self, respuestas, confirmer=lambda _d: True):
        profile = load_profile("desarrollo")
        audit = AuditLog("desarrollo", self.audit_dir)
        self._audits.append(audit)
        tools = ToolRunner(profile, self.ws, audit, confirmer, out=lambda *a: None)
        llm = FakeLlm(respuestas)
        return Agent(profile, self.ws, llm, tools, audit, out=lambda *a: None), llm

    def test_escritura_desde_bloque_de_codigo(self):
        respuesta = (
            '{"thought": "corrijo", "action": "write_file", "args": {"path": "app.js"}}\n'
            "```javascript\nconst corregido = true;\n```"
        )
        agent, _ = self._agent([
            respuesta,
            json.dumps({"thought": "listo", "action": "final", "answer": "Aplicado"}),
        ])
        result = agent.run("Corrige app.js")
        self.assertEqual(result["status"], "ok")
        self.assertEqual((self.ws / "app.js").read_text(encoding="utf-8"),
                         "const corregido = true;\n")

    def test_aborta_si_el_modelo_repite_respuesta_invalida(self):
        agent, llm = self._agent(["texto invalido sin json"] * 10)
        result = agent.run("Haz algo")
        self.assertEqual(result["status"], "aborted")
        self.assertLess(result["iterations"], 10)
        self.assertEqual(len(llm.vistos), 3)


if __name__ == "__main__":
    unittest.main()
