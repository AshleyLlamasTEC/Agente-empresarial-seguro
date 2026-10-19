# Integracion con opencode (opcional)

Estos archivos replican los dos perfiles del agente dentro de **opencode**, por
si prefieres su interfaz (TUI) en lugar de la linea de comandos de Python.

## Que contiene

```
opencode-integration/
  opencode.json                    Config del proyecto (solo provider local)
  .opencode/agent/consulta.md      Agente de solo lectura
  .opencode/agent/desarrollo.md    Agente con edicion confirmada
```

## Instalacion

1. Copia `opencode.json` a la **raiz del proyecto de trabajo** (la copia local,
   no el repositorio oficial).
2. Copia la carpeta `.opencode/` al mismo nivel:
   ```
   C:\trabajo\proyecto-copia\opencode.json
   C:\trabajo\proyecto-copia\.opencode\agent\consulta.md
   C:\trabajo\proyecto-copia\.opencode\agent\desarrollo.md
   ```
3. Si hiciste cambios en la config, **cierra y vuelve a abrir opencode**: la
   configuracion se carga una sola vez al arrancar.

## Controles que aplica esta configuracion

| Control | Como |
|---------|------|
| Solo modelo local | `enabled_providers: ["ollama"]` |
| Sin proveedores en la nube | `disabled_providers` con la lista completa |
| Sin telemetria | `share: disabled` |
| Sin lectura fuera del proyecto | `external_directory: { "*": "deny" }` |
| Sin escritura por defecto | `permission.edit: "deny"` a nivel raiz |
| Sin comandos por defecto | `permission.bash: { "*": "deny" }` |
| Sin web | `webfetch` y `websearch` en `deny` |
| Sin subagentes | `task: "deny"` |
| Sin skills externas | `skill: "deny"` |
| Sin autoescritura de formato | `formatter: false`, `lsp: false` |

El agente `desarrollo` habilita `edit: ask` y una lista blanca de comandos
concretos; el orden de las reglas importa (la ultima coincidencia gana).

## Diferencia con el agente en Python

| Aspecto | Agente Python | opencode |
|---------|---------------|----------|
| Dependencia | Ninguna (stdlib) | opencode + Ollama |
| Bitacora encadenada por hash | Si | No (usa su propio historial) |
| Censura de secretos (DLP) | Si, antes del envio | No |
| Sandbox de rutas | Si, propio | Solo `external_directory` |
| Respaldo automatico | Si | No |
| Verificacion de integridad | `verify-audit` | No |

**Recomendacion:** para trabajo sujeto a auditoria, usa el agente en Python.
opencode es comodo, pero su modelo de permisos es mas grueso y no deja una
bitacora encadenada que puedas presentar como evidencia.

## Requisito previo

Ollama corriendo en `http://127.0.0.1:11434` con el modelo descargado:

```powershell
ollama pull qwen2.5-coder:7b
```
