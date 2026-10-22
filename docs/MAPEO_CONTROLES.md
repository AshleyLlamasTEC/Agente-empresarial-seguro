# Mapeo de controles: requisito -> implementacion -> evidencia

Este documento permite a auditoria ir de un control declarado a la linea de
codigo que lo implementa y a la prueba que lo demuestra.

## A. Sin salida de datos a la nube

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Solo Ollama local | `agent/ollama_client.py: _validate_host` | prueba `test_rechaza_modelo_en_la_nube` |
| Rechazo de modelos cloud | `agent/config.py: assert_model_is_local` | `test_rechaza_modelo_en_la_nube` |
| Sin proveedores remotos en opencode | `opencode-integration/opencode.json` (`enabled_providers`) | revision de config |
| Sin telemetria de opencode | `opencode-integration/opencode.json` (`share: disabled`) | revision de config |

## B. Sin acceso a produccion

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Clientes de BD bloqueados | `agent/policy.py: BASE_DENY_PATTERNS` | `test_bloquea_herramientas_de_red_y_produccion` |
| Herramientas de red bloqueadas | idem | idem |
| Despliegue/migracion bloqueados | idem | `test_bloquea_instalacion_de_dependencias` |
| Rutas de produccion bloqueadas | `agent/policy.py: check_path` | revision + perfil `path_deny_globs` |

## C. Confinamiento al workspace

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Sin escapes por `..` | `agent/sandbox.py: resolve_in_workspace` | `test_bloquea_traversal` |
| Sin rutas absolutas | idem | `test_bloquea_rutas_absolutas` |
| Sin UNC ni `~` | idem | `test_bloquea_unc_y_home` |
| Sin nombres reservados | idem | `test_bloquea_nombres_reservados` |

## D. Control de comandos

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Deny by default | `agent/policy.py: check_command` | `test_consulta_no_permite_ningun_comando` |
| Lista blanca | `profiles/*.json: commands_allow` | `test_desarrollo_permite_comando_lectura` |
| Sin encadenar | `agent/policy.py: SHELL_METACHARACTERS` | `test_bloquea_encadenamiento_de_comandos` |
| Sin ejecucion dinamica | `BASE_DENY_PATTERNS` | `test_bloquea_ejecucion_dinamica` |
| Sin `shell=True` | `agent/tools.py: subprocess.run` | revision de codigo |
| Entorno saneado | `agent/tools.py: safe_env` | revision de codigo |

## E. Proteccion de datos

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Archivos de credenciales bloqueados | `agent/dlp.py: is_sensitive_path` | `test_detecta_archivos_sensibles` |
| Censura de secretos | `agent/dlp.py: redact` | `test_censura_contrasenas`, `test_censura_claves_de_api` |
| El modelo no ve secretos | `agent/tools.py: _read_file` | `test_secretos_censurados_antes_de_llegar_al_modelo` |
| Registro de censura | `agent/tools.py` -> bitacora (`secretos_censurados`) | revision de bitacora |

## F. Supervision humana

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Confirmacion obligatoria si hay escritura | `agent/config.py: validate_profile` | `test_rechaza_escritura_sin_confirmacion` |
| Cada escritura se confirma | `agent/tools.py: _write_file` | `test_escritura_rechazada_por_el_operador` |
| Cada comando se confirma | `agent/tools.py: _run_command` | revision + bitacora |
| Simulacion sin efectos | `--dry-run` | `test_dry_run_no_escribe` |

## G. Integridad y trazabilidad

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Bitacora encadenada | `agent/audit.py: AuditLog.record` | `test_cadena_valida` |
| Deteccion de alteracion | `agent/audit.py: verify_chain` | `test_detecta_manipulacion` |
| Deteccion de borrado | idem | `test_detecta_borrado_de_registro` |
| Respaldo antes de escribir | `agent/tools.py: _write_file` | `test_escritura_aprobada_con_respaldo` |
| Identidad del operador | `agent/audit.py: session_start` | revision de bitacora |

## H. Gobierno de la configuracion

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Perfiles versionados | `profiles/consulta.json`, `profiles/desarrollo.json`, `profiles/datos.json` | historial del repositorio |
| Perfil invalido no arranca | `agent/config.py: validate_profile` | `test_rechaza_campos_desconocidos`, `test_rechaza_nombre_de_perfil_invalido` |
| Diagnostico previo | `agent/cli.py: cmd_doctor` | salida de `doctor` firmada/fechada (seccion `[8] Base de datos`) |

## I. Base de datos local (solo la copia)

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Solo host local | `agent/db.py: check_local_host` | `test_host_remoto_bloqueado` |
| Sin produccion | idem (rechaza `10.0.0.5`, `db.produccion.local`, `0.0.0.0`) | prueba de aceptacion, categoria "BD / host remoto" |
| Solo lectura por defecto | `agent/db.py: validate_sql` | `test_escritura_bloqueada_en_solo_lectura` |
| DDL desactivado por defecto | idem | `test_ddl_bloqueado_por_defecto` |
| Una sola sentencia, sin comentarios | idem | `test_una_sola_sentencia`, `test_sin_comentarios` |
| Clasificacion sobre toda la sentencia | `agent/db.py: _DML_TOKEN` | `test_bloquea_escritura_oculta_en_cte` |
| Sin lectura/escritura de archivos | `agent/db.py: _FORBIDDEN_SUBSTRINGS` | `test_bloquea_lectura_de_archivos` |
| Sin funciones de denegacion | `agent/db.py: _FORBIDDEN_CALLS` | `test_bloquea_denegacion_de_servicio` |
| Sin comandos de cliente MySQL | `agent/db.py: validate_sql` (engine) | `test_mysql_sin_comandos_de_cliente` |
| Salida acotada (filas y bytes) | `run_sqlite` / `run_mysql` | `test_select_devuelve_filas` + revision de codigo |
| SQL censurado en la bitacora | `agent/tools.py: _safe_sql` | `test_registra_en_bitacora` |
| Sin acceso si el perfil no lo permite | `agent/tools.py: _db_query` | `test_perfil_sin_db_bloquea` |
| Confirmacion por sentencia | `agent/tools.py: _db_query` | `test_rechazo_del_operador` |
| Limite de filas y censura | `agent/db.py` + `agent/dlp.py` | `test_select_devuelve_filas` |
| Registro en bitacora | `agent/tools.py` -> `db_query`/`db_blocked`/`db_dry_run` | `test_registra_en_bitacora` |

## J. Reversion (rollback) e identidad

| Control | Implementacion | Evidencia |
|---------|----------------|-----------|
| Reversion desde respaldos | `agent/rollback.py: build_actions` | `tests/test_rollback.py` |
| Bitacora verificada antes de revertir | `agent/cli.py: cmd_rollback` | `test_bitacora_manipulada_cancela_rollback` |
| Respaldo solo desde `backups/` | `agent/rollback.py: build_actions(backups_root)` | `test_respaldo_fuera_de_auditoria_se_omite` |
| Confinado al workspace | `agent/rollback.py` + `agent/sandbox.py` | `test_rollback_fuera_del_workspace` |
| Verificacion de hash antes/despues | `agent/rollback.py: apply_actions` | `test_rollback_restaura_hash` |
| Bitacora del rollback | `agent/rollback.py` (perfil `rollback`) | `test_rollback_registra_en_bitacora` |
| Identidad en blanco por defecto | `agent/identity.py: blank` | `test_identidad_en_blanco` |
| Identidad privada (no versionada) | `.gitignore` + `identity.example.json` | revision de config |

## Como recabar la evidencia

```bash
# 1. Resultado del diagnostico (guardar salida)
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia > evidencia\doctor.txt

# 2. Pruebas automatizadas (guardar salida)
python -m unittest discover -s tests -t . -v > evidencia\pruebas.txt 2>&1

# 3. Integridad de cada bitacora de sesion
python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<sesion>.jsonl > evidencia\integridad.txt
```
