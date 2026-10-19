# Guia de instalacion en la maquina de trabajo

Esta guia asume Windows 10/11. El agente no requiere permisos de administrador
salvo para instalar Ollama.

## Paso 0 - Aislamiento previo (obligatorio)

Antes de instalar nada:

1. Desconecta la VPN.
2. Verifica que no puedas alcanzar produccion (por ejemplo, que no resuelva el
   host de la base de datos productiva).
3. Crea una carpeta de trabajo fuera de recursos de red, por ejemplo:
   `C:\trabajo\`
4. Copia el proyecto a `C:\trabajo\proyecto-copia`. **Nunca** trabajes sobre la
   ruta compartida ni sobre el repositorio oficial.

## Paso 1 - Python

Requiere Python 3.10 o superior.

```powershell
python --version
```

No hay dependencias que instalar: el agente usa solo la libreria estandar.

## Paso 2 - Ollama y el modelo local

1. Descarga e instala Ollama desde <https://ollama.com/download>.
2. Verifica que el servicio responde:

```powershell
ollama list
```

3. Descarga un modelo **local** especializado en codigo:

```powershell
ollama pull qwen2.5-coder:7b
```

Si la maquina tiene poca memoria, usa `qwen2.5-coder:3b`. Si tiene 16 GB o mas
de VRAM, `qwen2.5-coder:14b` da mejores resultados.

> NUNCA uses modelos con sufijo `-cloud` (por ejemplo
> `deepseek-v3.1:671b-cloud`): envian informacion a un servidor externo y el
> agente los rechaza de todas formas.

## Paso 3 - El agente

Copia el repositorio a la maquina (por el medio autorizado) y situate en su
carpeta:

```powershell
cd C:\trabajo\agente-empresarial-seguro
```

Copia la configuracion de ejemplo:

```powershell
Copy-Item .env.example .env
```

Edita `.env` si necesitas cambiar el modelo o el puerto de Ollama.

Define la identidad del agente. No trae nombre ni datos de nadie de fabrica; se
configura la primera vez y queda en `identity.json` (privado, no se sube):

```powershell
python -m agent.cli setup
```

## Paso 4 - Diagnostico

```powershell
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia
```

Debe terminar en `RESULTADO: OK`. Los cuatro puntos de la seccion 6 son de
verificacion manual: confirmalos uno por uno. La seccion `[7] Identidad` te dice
si el agente ya tiene nombre y datos o si sigue en blanco.

## Paso 5 - Prueba de humo (sin riesgo)

```powershell
python -m agent.cli ask --profile consulta --workspace examples\demo-proyecto `
  "Revisa app.js y lista los defectos"
```

Verifica que:
- El agente lee archivos y responde.
- Cualquier intento de escribir es bloqueado (perfil de solo lectura).

## Paso 6 - Sesion real

```powershell
# Analisis (solo lectura)
python -m agent.cli ask --profile consulta --workspace C:\trabajo\proyecto-copia `
  "Lista los defectos y prioriza los cinco mas importantes"

# Primera sesion de correccion: SIMULAR
python -m agent.cli ask --profile desarrollo --workspace C:\trabajo\proyecto-copia --dry-run `
  "Corrige el defecto de promedio() en app.js"

# Correccion real (pide confirmacion en cada cambio)
python -m agent.cli ask --profile desarrollo --workspace C:\trabajo\proyecto-copia `
  "Corrige el defecto de promedio() en app.js"
```

## Paso 7 - Evidencia

```powershell
New-Item -ItemType Directory -Force C:\trabajo\evidencia | Out-Null

python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia |
  Out-File C:\trabajo\evidencia\doctor.txt

python -m unittest discover -s tests -t . -v 2>&1 |
  Out-File C:\trabajo\evidencia\pruebas.txt

python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<sesion>.jsonl |
  Out-File C:\trabajo\evidencia\integridad.txt
```

## Uso diario

| Situacion | Perfil | Bandera |
|-----------|--------|---------|
| Entender codigo, diagnosticar | `consulta` | - |
| Proponer cambios sin aplicar | `desarrollo` | `--dry-run` |
| Aplicar cambios controlados | `desarrollo` | - |
| Probar consultas sobre la copia local | `datos` | - |
| Deshabilitar comandos | `desarrollo` | `--no-shell` |
| Deshabilitar escritura | `desarrollo` | `--no-write` |
| Deshacer los cambios de una sesion | (cualquiera) | `rollback` |
| Deshabilitar base de datos | `datos` | `--no-db` |

## Reversion segura

Antes de integrar cualquier cambio puedes volver atras. Solo se restauran
respaldos ya existentes y dentro del workspace:

```powershell
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --list
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia
```

`--list` muestra el plan sin tocar nada; sin `--list` pide confirmacion (`s`) y
verifica el hash antes y despues.

## Problemas frecuentes

| Sintoma | Causa probable | Solucion |
|---------|----------------|----------|
| "Ollama no responde" | Servicio detenido | Ejecuta `ollama serve` |
| "El modelo no esta descargado" | Falta el pull | `ollama pull qwen2.5-coder:7b` |
| "Host remoto bloqueado" | `OLLAMA_HOST` apunta fuera | Usa `http://127.0.0.1:11434` |
| "Ruta fuera del workspace" | Se intento acceder fuera | Es el comportamiento correcto |
| "Ejecutable no esta en la lista blanca" | Comando no permitido | Agregalo al perfil solo con justificacion |

## Desinstalacion

El agente no instala servicios ni deja rastros fuera de:

- La carpeta del repositorio.
- El directorio de bitacoras (`%USERPROFILE%\.agente-empresarial\audit`).
- Los respaldos dentro de la bitacora.

Basta con borrar esas carpetas. Ollama se desinstala desde "Agregar o quitar
programas".
