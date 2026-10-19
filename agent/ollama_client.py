"""Cliente Ollama estrictamente local.

Controles:
  1. Solo se permite loopback (127.0.0.1 / localhost / ::1). Cualquier otro
     host se rechaza en el constructor.
  2. Se rechazan modelos con marca de nube (sufijo '-cloud', etc.).
  3. Timeout y tamano de respuesta acotados.
  4. Sin TLS remoto ni proxies.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .config import CLOUD_MARKERS

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
ALLOWED_SCHEMES = {"http", "https"}
REMOTE_PROVIDERS = {"openai", "anthropic", "google", "groq", "openrouter", "mistral", "cohere", "deepseek"}


class OllamaError(Exception):
    pass


class SecurityPolicyError(Exception):
    pass


class OllamaClient:
    def __init__(self, model: str, host: str = "http://127.0.0.1:11434", timeout: int = 120):
        self.host = self._validate_host(host)
        self.model = self._validate_model(model)
        self.timeout = timeout

    @staticmethod
    def _validate_host(host: str) -> str:
        host = (host or "").strip().rstrip("/")
        if not host:
            host = "http://127.0.0.1:11434"
        parsed = urlparse(host)
        if parsed.scheme not in ALLOWED_SCHEMES:
            raise SecurityPolicyError(f"Esquema no permitido: {parsed.scheme!r}")
        hostname = (parsed.hostname or "").lower()
        if hostname not in LOOPBACK_HOSTS:
            raise SecurityPolicyError(
                f"Host remoto bloqueado: {hostname!r}. Este agente solo habla con Ollama local "
                "(127.0.0.1 / localhost)."
            )
        if parsed.username or parsed.password:
            raise SecurityPolicyError("No se permiten credenciales embebidas en la URL.")
        port = parsed.port or 11434
        return f"{parsed.scheme}://{hostname}:{port}"

    @staticmethod
    def _validate_model(model: str) -> str:
        model = (model or "").strip()
        if not model:
            raise SecurityPolicyError("Se requiere un modelo local explicito.")
        low = model.lower()
        for marker in CLOUD_MARKERS:
            if marker in low:
                raise SecurityPolicyError(
                    f"Modelo con marca de nube rechazado: '{model}'. Solo modelos locales."
                )
        prefix = low.split(":", 1)[0]
        if prefix in REMOTE_PROVIDERS:
            raise SecurityPolicyError(f"Proveedor remoto rechazado: '{prefix}'.")
        return model

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.host}{endpoint}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise OllamaError(f"Ollama respondio HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OllamaError(
                f"No se pudo contactar a Ollama en {self.host}. "
                f"Verifica que el servicio este activo. Detalle: {exc.reason}"
            ) from exc

    def _get(self, endpoint: str) -> dict:
        request = urllib.request.Request(f"{self.host}{endpoint}", method="GET")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise OllamaError(f"Ollama no disponible en {self.host}: {exc.reason}") from exc

    def is_available(self) -> bool:
        try:
            self._get("/api/tags")
            return True
        except OllamaError:
            return False

    def list_models(self) -> list[str]:
        data = self._get("/api/tags")
        return sorted(m.get("name", "") for m in data.get("models", []))

    def has_model(self) -> bool:
        try:
            names = self.list_models()
        except OllamaError:
            return False
        base = self.model.split(":")[0]
        return any(name == self.model or name.split(":")[0] == base for name in names)

    def chat(self, messages: list[dict], temperature: float = 0.1, max_tokens: int = 2048) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        data = self._post("/api/chat", payload)
        message = data.get("message") or {}
        content = message.get("content", "")
        if not isinstance(content, str):
            raise OllamaError("Respuesta inesperada de Ollama (sin campo 'content').")
        return content
