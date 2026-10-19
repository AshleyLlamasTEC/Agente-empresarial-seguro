"""Bucle del agente: piensa -> pide una accion -> ejecuta -> observa -> repite."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .prompts import build_system_prompt

FENCE_OPEN = re.compile(r"^```[a-zA-Z0-9_+-]*[ \t]*\r?\n")
FENCE_CLOSE = re.compile(r"\r?\n?```\s*$")
FENCE_BLOCK = re.compile(r"```[a-zA-Z0-9_+-]*[ \t]*\r?\n(.*?)```", re.DOTALL)

MAX_REPETICIONES = 3
MAX_CORRECCIONES = 3


def repair_json(text: str) -> str:
    """Repara los defectos mas comunes que producen los modelos pequenos.

    - Escapa saltos de linea y tabuladores crudos dentro de cadenas.
    - Elimina comas finales antes de un cierre.
    - Cierra llaves y corchetes que quedaron abiertos.
    """
    out: list[str] = []
    in_str = False
    escape = False
    stack: list[str] = []

    for ch in text:
        if escape:
            out.append(ch)
            escape = False
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str:
            if ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            elif ord(ch) < 0x20:
                out.append(" ")
            else:
                out.append(ch)
            continue
        if ch in "{[":
            stack.append(ch)
            out.append(ch)
            continue
        if ch in "}]":
            j = len(out) - 1
            while j >= 0 and out[j] in " \t\r\n":
                j -= 1
            if j >= 0 and out[j] == ",":
                del out[j]
            if stack:
                stack.pop()
            out.append(ch)
            continue
        out.append(ch)

    if in_str:
        out.append('"')
    result = "".join(out)

    closing = {"{": "}", "[": "]"}
    if stack:
        result += "".join(closing[c] for c in reversed(stack))
    return result


def iter_json_objects(text: str):
    """Genera las subcadenas con llaves balanceadas, respetando cadenas.

    Permite aislar el objeto JSON aunque despues venga un bloque de codigo.
    """
    stack: list[str] = []
    in_str = False
    escape = False
    start = None

    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if not stack:
                start = i
            stack.append(ch)
        elif ch == "}":
            if stack:
                stack.pop()
                if not stack and start is not None:
                    yield text[start: i + 1]
                    start = None


def extract_json(text: str) -> dict | None:
    """Extrae el primer objeto JSON valido de una respuesta del modelo."""
    if not text:
        return None

    stripped = text.strip()
    candidatos: list[str] = []

    if stripped.startswith("```"):
        inner = FENCE_OPEN.sub("", stripped)
        inner = FENCE_CLOSE.sub("", inner)
        candidatos.append(inner)

    candidatos.extend(iter_json_objects(text))
    candidatos.append(stripped)

    for candidato in candidatos:
        for intento in (candidato, repair_json(candidato)):
            try:
                data = json.loads(intento)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(data, dict):
                return data
    return None


def extract_fenced_content(text: str) -> str | None:
    """Devuelve el contenido de un bloque de codigo, ignorando los que son JSON."""
    if not text:
        return None
    mejores: list[str] = []
    for block in FENCE_BLOCK.findall(text):
        if not block.strip():
            continue
        if extract_json(block) is not None:
            continue
        mejores.append(block)
    if not mejores:
        return None
    elegido = max(mejores, key=len)
    return elegido.lstrip("\n").rstrip("\n") + "\n"


class Agent:
    def __init__(self, profile, workspace: Path, llm, tools, audit, out=print, identity=None):
        self.profile = profile
        self.workspace = Path(workspace).resolve()
        self.llm = llm
        self.tools = tools
        self.audit = audit
        self.out = out
        self.identity = identity

    def _system_prompt(self) -> str:
        return build_system_prompt(
            self.profile, str(self.workspace), self.tools.describe(), self.identity
        )

    def run(self, task: str) -> dict:
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": f"TAREA DEL OPERADOR:\n{task}"},
        ]
        self.audit.record("task_start", {"task": task, "perfil": self.profile.name,
                                         "workspace": str(self.workspace)})
        self.out(f"[{self.profile.name}] Tarea: {task}")
        self.out(f"[{self.profile.name}] Modelo local: {self.llm.model} | "
                 f"Herramientas: {', '.join(self.tools.available_tools())}")

        tool_calls = 0
        correcciones = 0
        última_respuesta = None
        repeticiones = 0

        for iteration in range(1, self.profile.max_iterations + 1):
            raw = self.llm.chat(messages)
            self.audit.record("model_response", {"iteracion": iteration,
                                                 "chars": len(raw or ""),
                                                 "resumen": (raw or "")[:2000]})
            action = extract_json(raw)

            if action is None:
                repeticiones = repeticiones + 1 if raw == última_respuesta else 1
                última_respuesta = raw
                correcciones += 1
                self.out(f"[{iteration}] Respuesta no parseable; se solicita correccion "
                         f"({correcciones}/{MAX_CORRECCIONES}).")

                if repeticiones >= MAX_REPETICIONES or correcciones > MAX_CORRECCIONES:
                    self.audit.record("task_abort", {"motivo": "respuesta invalida repetida",
                                                     "iteracion": iteration})
                    self.out("[!] El modelo repite una respuesta invalida. Se detiene para no "
                             "gastar recursos.")
                    return {
                        "answer": "El modelo local no logro producir una accion valida. "
                                  "Prueba con una instruccion mas especifica o un modelo mayor "
                                  "(por ejemplo qwen2.5-coder:14b).",
                        "iterations": iteration,
                        "tool_calls": tool_calls,
                        "status": "aborted",
                    }

                messages.append({"role": "assistant", "content": raw or ""})
                messages.append({
                    "role": "user",
                    "content": (
                        "Tu respuesta no fue un objeto JSON valido. Responde UNICAMENTE con un "
                        'objeto JSON con las claves "thought" y "action".\n'
                        "Si vas a escribir un archivo, NO pongas el contenido dentro del JSON: "
                        "envia solo la ruta y coloca el contenido en un bloque de codigo despues "
                        "del JSON."
                    ),
                })
                continue

            correcciones = 0
            última_respuesta = raw
            name = action.get("action")
            args = action.get("args") or {}
            if not isinstance(args, dict):
                args = {}

            if name == "write_file" and not str(args.get("content") or "").strip():
                contenido = extract_fenced_content(raw)
                if contenido is not None:
                    args = dict(args)
                    args["content"] = contenido
                    self.out("[i] Contenido del archivo tomado del bloque de codigo "
                             f"({len(contenido)} caracteres).")

            if name == "final":
                answer = str(action.get("answer", "")).strip()
                self.audit.record("task_finish", {"iteraciones": iteration, "tool_calls": tool_calls})
                self.out(f"[{self.profile.name}] Terminado en {iteration} iteracion(es).")
                return {"answer": answer, "iterations": iteration, "tool_calls": tool_calls,
                        "status": "ok"}

            self.out(f"[{iteration}] {name}: {json.dumps(args, ensure_ascii=False)[:160]}")

            result = self.tools.call(name, args)
            tool_calls += 1
            self.out("   -> " + ("OK" if result.ok else ("BLOQUEADO" if result.blocked else "ERROR")))

            messages.append({"role": "assistant", "content": raw or ""})
            messages.append({
                "role": "user",
                "content": f"RESULTADO DE {name}:\n{result.as_text()}",
            })

        self.audit.record("task_limit", {"iteraciones": self.profile.max_iterations})
        self.out("[!] Se alcanzo el limite de iteraciones.")
        return {
            "answer": "Se alcanzo el limite de iteraciones sin un resultado final. "
                      "Revisa la bitacora para ver el detalle.",
            "iterations": self.profile.max_iterations,
            "tool_calls": tool_calls,
            "status": "limit",
        }
