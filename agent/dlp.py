"""Proteccion de datos (DLP) basica.

Dos funciones:
  1. is_sensitive_path(): bloquea la lectura de archivos de credenciales.
  2. redact(): censura secretos antes de que el texto salga hacia el modelo.

Nota de auditoria: esta capa reduce el riesgo de fuga, no lo elimina. La
garantia fuerte es que el modelo corre en 127.0.0.1 y que no existen
credenciales reales en la maquina del agente.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from pathlib import Path

SENSITIVE_NAMES = (
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.pfx", "*.p12", "*.keystore",
    "*.jks", "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*", "id_dsa",
    ".npmrc", ".netrc", ".pgpass", ".my.cnf", ".git-credentials", ".htpasswd",
    "credentials", "credentials.*", "secrets.*", "*.secret", "*.secrets",
    "*.kdbx", "*.ovpn", "*.publishsettings", "*.mobileprovision",
    "appsettings.production.json", "appsettings.prod.json", "wp-config.php",
    "settings.py", "local.settings.json", "secrets.yml", "secrets.yaml", "*.jwk",
)

SENSITIVE_DIRS = (
    ".ssh", ".aws", ".azure", ".gnupg", ".kube", ".docker", ".config/gcloud",
)


def is_sensitive_path(path: Path, extra_names=()) -> tuple[bool, str]:
    name = path.name.lower()
    parts = [p.lower() for p in path.parts]

    for denied in tuple(SENSITIVE_NAMES) + tuple(extra_names):
        if fnmatch(name, denied.lower()):
            return True, f"archivo de credenciales ({denied})"

    for denied_dir in SENSITIVE_DIRS:
        if any(part == denied_dir.split("/")[-1] for part in parts):
            return True, f"directorio de credenciales ({denied_dir})"

    return False, ""


_VALUE = r"(\"[^\"]*\"|'[^']*'|[^\s,;)]+)"
_BOUNDARY = r"(^|[^A-Za-z0-9])"

REDACTION_RULES = [
    (re.compile(
        r"(?i)" + _BOUNDARY + r"(password|passwd|pwd|contrasena|contraseña)\s*[:=]\s*" + _VALUE
    ), r"\1\2=***REDACTADO***"),
    (re.compile(
        r"(?i)" + _BOUNDARY
        + r"(api[_-]?key|apikey|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token)"
        + r"\s*[:=]\s*" + _VALUE
    ), r"\1\2=***REDACTADO***"),
    (re.compile(r"(?i)" + _BOUNDARY + r"(tokens?|credenciales?)\s*[:=]\s*(\"[^\"]{8,}\"|'[^']{8,}'|[A-Za-z0-9\-_.]{16,})"),
     r"\1\2=***REDACTADO***"),
    (re.compile(r"(?i)(bearer)\s+[A-Za-z0-9._\-]{12,}"), r"\1 ***REDACTADO***"),
    (re.compile(r"\bsk-[A-Za-z0-9\-_]{16,}\b"), "sk-***REDACTADO***"),
    (re.compile(r"\bAKIA[0-9A-Z]{12,}\b"), "AKIA***REDACTADO***"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "ghp_***REDACTADO***"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\b"),
     "***JWT_REDACTADO***"),
    (re.compile(r"(?i)(mysql|postgres(?:ql)?|mongodb|redis|mssql|sqlserver|amqp)://[^\s:/@]+:[^\s@]+@"),
     r"\1://***REDACTADO***@"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
     "***LLAVE_PRIVADA_REDACTADA***"),
    (re.compile(r"(?i)((?:server|data source)\s*=\s*[^;\s]+;[\s\S]{0,120}?(?:password|pwd)\s*=\s*[^;\s]+)"),
     "***CADENA_DE_CONEXION_REDACTADA***"),
]


def redact(text: str) -> tuple[str, int]:
    """Devuelve (texto, numero de sustituciones)."""
    if not text:
        return text, 0
    total = 0
    result = text
    for pattern, replacement in REDACTION_RULES:
        result, count = pattern.subn(replacement, result)
        total += count
    return result, total
