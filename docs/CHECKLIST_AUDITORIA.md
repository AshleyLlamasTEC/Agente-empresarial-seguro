# Checklist de auditoria

Se recomienda imprimir o guardar este documento firmado y fechado por sesion.

## Antes de la primera sesion

- [ ] Autorizacion por escrito del dueño del proyecto para usar IA sobre una copia.
- [ ] Confirmacion de TI: la maquina esta aislada (sin VPN, sin acceso a produccion).
- [ ] El proyecto usado es una COPIA local (no recurso compartido de red).
- [ ] No hay credenciales reales de produccion en la maquina.
- [ ] Ollama esta instalado y el modelo local descargado.
- [ ] `python -m agent.cli doctor` devuelve RESULTADO: OK.
- [ ] `python -m unittest discover -s tests -t .` devuelve OK.

## Antes de cada sesion

- [ ] La VPN esta desconectada.
- [ ] El workspace apunta a la copia local correcta (`--workspace`).
- [ ] El perfil elegido es el adecuado (`consulta` para analisis, `desarrollo` para corregir, `datos` para probar consultas locales).
- [ ] El numero de sesion y la bitacora quedan identificados.
- [ ] Si se usara la base de datos: es una COPIA local (no produccion) y el host es `127.0.0.1`/`localhost`.

## Durante la sesion

- [ ] Se usa el perfil `consulta` para el analisis inicial.
- [ ] Cada confirmacion (`s/N`) se lee antes de aprobar.
- [ ] Se evita aprobar cambios que no se entiendan.
- [ ] Ante algo inesperado, se cancela con `n` o `Ctrl+C`.
- [ ] Si hubo escritura o consultas, se registro el numero de sesion para un posible `rollback`.

## Antes de integrar cambios al repositorio oficial

- [ ] Los cambios fueron revisados por una persona.
- [ ] Si se uso `rollback`, la bitacora paso la verificacion de integridad antes de revertir.
- [ ] Las pruebas del proyecto pasan en la copia.
- [ ] No se integro ninguna credencial ni dato real.
- [ ] Los cambios se integran por el flujo normal (revision de codigo), no directo a produccion.

## Evidencia a conservar

- [ ] Salida de `doctor` (fecha y hora).
- [ ] Salida de las pruebas automatizadas.
- [ ] Archivos `.jsonl` de la bitacora de cada sesion.
- [ ] Resultado de `verify-audit` de cada bitacora.
- [ ] Respaldos generados (carpeta `audit/backups/`).
- [ ] Este checklist, firmado.

## Verificacion de integridad

```bash
python -m agent.cli verify-audit --file <bitacora>.jsonl
# Esperado: "[ok] Cadena integra: N registros verificados."
```

Si aparece `[x] Registro alterado` o `[x] Cadena rota`, la bitacora fue
manipulada: **detener el uso y reportar** a seguridad de la informacion.

## Que revisar en la bitacora

| Evento | Significado |
|--------|-------------|
| `session_start` | Identidad, equipo, version de Python |
| `task_start` | Tarea solicitada y workspace |
| `tool_call` | Herramienta usada, argumentos, duracion |
| `tool_blocked` | Intento rechazado por politica (revisar si es recurrente) |
| `command_blocked` | Comando prohibido intentado |
| `read_file` | Archivo leido, hash y numero de secretos censurados |
| `write_file` | Cambio aplicado, hash antes/despues y respaldo |
| `command_run` | Comando ejecutado y codigo de salida |
| `db_query` / `db_blocked` / `db_dry_run` | Consulta a la BD local ejecutada, bloqueada o simulada |
| `rollback` | Restauracion aplicada desde un respaldo (hash verificado) |
| `write_file_denied_by_user` / `command_denied_by_user` | El operador rechazo |
| `task_finish` | Cierre con numero de iteraciones y llamadas |
