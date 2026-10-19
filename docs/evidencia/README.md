# Evidencia de pruebas — Agente Empresarial Seguro

Esta carpeta reúne la evidencia reproducible de que el agente funciona y de que
sus controles de seguridad están activos. Cada archivo se generó ejecutando el
comando indicado; nada está escrito a mano.

| Archivo | Qué demuestra | Cómo se regenera |
| --- | --- | --- |
| `01_doctor.txt` | El entorno está listo: Python, Ollama, modelo local y perfiles disponibles. | `python -X utf8 -m agent.cli doctor` |
| `02_pruebas_unitarias.txt` | Las 98 pruebas automatizadas de política, sandbox, DLP, auditoría, bucle, identidad, rollback y base de datos local pasan. | `python -X utf8 -m unittest discover -s tests -t .` |
| `03_prueba_aceptacion.txt` | Batería de ataques: 76 intentos de evasión bloqueados (0 fallas) y 10 controles positivos correctos. | `python -X utf8 scripts/prueba_aceptacion.py` |
| `04_escritura_real.txt` | Ciclo completo real: `--dry-run` no modifica el archivo; con confirmación humana (`s`) sí lo modifica. | Ver sección "Reproducir la sesión de escritura". |
| `05_verificacion.txt` | Respaldo automático, hashes SHA-256 antes/después, integridad de la bitácora y la diferencia aplicada. | Ver sección "Reproducir la sesión de escritura". |
| `06_rollback.txt` | El cambio aplicado se deshace desde el respaldo: el archivo vuelve a su estado original con hash verificado. | Ver sección "Reproducir el rollback". |

## Reproducir la sesión de escritura

El workspace y la bitácora viven fuera del repositorio, en una carpeta temporal,
para no mezclar pruebas con código:

```powershell
$dst = "$env:TEMP\opencode\proyecto-prueba"
$aud = "$env:TEMP\opencode\auditoria"
Remove-Item -Recurse -Force $dst,$aud -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $dst | Out-Null
Copy-Item -Recurse -Force .\examples\demo-proyecto\* $dst
```

Paso 1 — simulación (no debe tocar el archivo):

```powershell
python -X utf8 -m agent.cli ask --profile desarrollo --workspace $dst --audit-dir $aud `
  --dry-run "Corrige en app.js el ciclo for de la funcion promedio: debe usar i < valores.length en lugar de i <= valores.length. Escribe el archivo completo."
```

Paso 2 — escritura real (el agente pedirá confirmación; responder `s`):

```powershell
python -X utf8 -m agent.cli ask --profile desarrollo --workspace $dst --audit-dir $aud `
  "Corrige en app.js el ciclo for de la funcion promedio: debe usar i < valores.length en lugar de i <= valores.length. Escribe el archivo completo."
```

Paso 3 — comprobar el resultado y la integridad:

```powershell
Select-String -Path "$dst\app.js" -Pattern "i < valores.length"
$f = Get-ChildItem "$aud\*.jsonl" | Sort-Object LastWriteTime | Select-Object -Last 1
python -X utf8 -m agent.cli verify-audit --file $f.FullName
```

## Reproducir el rollback

Sobre el mismo workspace del paso anterior (ya con el cambio aplicado):

```powershell
python -X utf8 -m agent.cli rollback --workspace $dst --audit-dir $aud --list
python -X utf8 -m agent.cli rollback --workspace $dst --audit-dir $aud
Select-String -Path "$dst\app.js" -Pattern "i <= valores.length"
```

El primer comando solo muestra el plan; el segundo pide confirmación (`s`) y
restaura el respaldo. Al final el archivo vuelve a tener `i <= valores.length`
(defecto original), con el hash verificado antes y después.

## Qué observar

- En el paso 1 el resultado final dice que **el cambio fue simulado y no se
  escribió nada**; el archivo conserva el defecto `i <= valores.length`.
- En el paso 2 aparece el bloque `CONFIRMACION REQUERIDA` con el contenido
  propuesto; solo tras responder `s` se aplica el cambio.
- `05_verificacion.txt` muestra:
  - un respaldo `.bak` creado **antes** de modificar,
  - los hashes `sha256_before` y `sha256_after` distintos (el archivo cambió),
  - `[ok] Cadena integra` tras verificar la bitácora encadenada.

## Nota sobre el modelo

El modelo usado es `qwen2.5-coder:7b`, que corre **localmente** en
`127.0.0.1:11434`. El agente no llama a ningún servicio en la nube; un intento de
apuntar a un host remoto se rechaza (ver `03_prueba_aceptacion.txt`).
