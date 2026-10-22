# Modelo de amenazas

Metodologia: identificacion de activos, amenazas y mitigaciones, mas el
reconocimiento explicito de **riesgos residuales**.

## 1. Activos a proteger

| Activo | Sensibilidad |
|--------|--------------|
| Base de datos de produccion | Critica |
| Codigo fuente del proyecto | Alta |
| Credenciales, tokens y llaves | Critica |
| Datos personales de clientes/empleados | Alta |
| Reputacion y continuidad operativa | Crítica |

## 2. Limites de confianza

```
[ Operador humano ] --confirma--> [ Agente ] --solo localhost--> [ Ollama ]
                                    |
                                    +--> [ Copia del proyecto ]  (permiso total)
                                    |
                                    X    [ Produccion ]  (sin ruta de acceso)
                                    X    [ Red corporativa ]  (sin ruta de acceso)
                                    X    [ Internet ]  (bloqueado por politica)
```

## 3. Amenazas y mitigaciones

### T1 - Fuga de datos al proveedor del modelo
**Vector:** configurar un modelo en la nube y enviar codigo/secretos.
**Mitigacion:** el cliente valida el host (solo loopback) y rechaza modelos con
marca de nube; los perfiles no admiten modelos remotos; la censura DLP actua
antes del envio.
**Evidencia:** `agent/ollama_client.py`, `agent/config.py`, pruebas
`test_rechaza_modelo_en_la_nube`, `test_secretos_censurados_antes_de_llegar_al_modelo`.

### T2 - Acceso a produccion
**Vector:** que el agente ejecute `mysql`, `ssh`, `kubectl` o un despliegue.
**Mitigacion:** lista negra explicita de clientes de BD, herramientas de red,
contenedores y despliegue; perfiles con lista blanca de comandos; rutas con
`prod`/`produccion` bloqueadas.
**Evidencia:** `agent/policy.py`, pruebas `test_bloquea_herramientas_de_red_y_produccion`.

### T3 - Escritura/lectura fuera del workspace
**Vector:** `..`, rutas absolutas, rutas UNC, enlaces simbolicos.
**Mitigacion:** toda ruta se normaliza y debe quedar dentro del workspace; se
rechazan UNC, `~`, rutas absolutas y nombres reservados de Windows.
**Evidencia:** `agent/sandbox.py`, pruebas `test_bloquea_traversal`,
`test_bloquea_rutas_absolutas`, `test_bloquea_unc_y_home`.

### T4 - Inyeccion de comandos
**Vector:** encadenar `;`, `&&`, `|`, sustitucion `$()` o redirecciones.
**Mitigacion:** prohibicion de metacaracteres; ejecucion sin `shell=True`
(lista de argumentos); entorno saneado para el proceso hijo.
**Evidencia:** `agent/policy.py`, `agent/tools.py`, prueba `test_bloquea_encadenamiento_de_comandos`.

### T5 - Destruccion de datos del proyecto
**Vector:** `rm -rf`, `git reset --hard`, `git clean -fd`, sobrescribir archivos.
**Mitigacion:** comandos destructivos prohibidos; toda escritura requiere
confirmacion y genera respaldo con hash previo.
**Evidencia:** `agent/policy.py`, `agent/tools.py`, prueba `test_escritura_aprobada_con_respaldo`.

### T6 - Exposicion de credenciales
**Vector:** leer `.env`, `*.pem`, `id_rsa` o cadenas de conexion.
**Mitigacion:** lista de nombres protegidos; ademas censura de patrones de
secretos en cualquier texto que salga hacia el modelo.
**Evidencia:** `agent/dlp.py`, pruebas `test_detecta_archivos_sensibles`, `test_censura_contrasenas`.

### T7 - Accion no autorizada sin supervision
**Vector:** que el agente modifique o ejecute sin intervencion humana.
**Mitigacion:** `require_confirmation: true` obligatorio si hay escritura;
`--dry-run` para simular; el perfil `consulta` no tiene escritura ni shell.
**Evidencia:** `agent/config.py` (validacion), `agent/tools.py`.

### T8 - Borrado o alteracion de la bitacora
**Vector:** editar los registros para ocultar una accion.
**Mitigacion:** encadenamiento por hash: cada registro incluye el hash del
anterior; cualquier alteracion o borrado rompe la verificacion.
**Evidencia:** `agent/audit.py`, pruebas `test_detecta_manipulacion`,
`test_detecta_borrado_de_registro`.

### T9 - Manipulacion desde el propio proyecto analizado
**Vector:** un archivo del proyecto (o una dependencia) contiene instrucciones
maliciosas ("prompt injection") que tratan de convencer al agente de saltarse
reglas.
**Mitigacion:** los controles son de codigo, no del prompt: aunque el modelo lo
intente, el sandbox y la politica rechazan la accion y la registran. Ademas el
agente solo ejecuta lo que el operador confirma.
**Evidencia:** `agent/tools.py` (la decision no depende del modelo),
`agent/policy.py`.

### T10 - Exfiltracion o dano a traves de la base de datos
**Vector:** conectar a un motor remoto (produccion), leer/escribir archivos desde
SQL (`LOAD_FILE`, `INTO OUTFILE`), agotar el servidor (`SLEEP`, `BENCHMARK`) o
colar una escritura en una CTE (`WITH ... DELETE`).
**Mitigacion:** solo hosts locales (`check_local_host`); motor por herramienta
dedicada (`db_query`), no por comando; una sentencia sin comentarios; clasificacion
sobre la sentencia COMPLETA; funciones peligrosas prohibidas; en MySQL una sola
linea sin `\` (comandos de cliente); solo lectura por defecto; DDL y escritura
requieren bandera explicita y confirmacion por sentencia; salida acotada en filas
y bytes; SQL censurado en la bitacora.
**Evidencia:** `agent/db.py`, `agent/tools.py`, pruebas `test_host_remoto_bloqueado`,
`test_bloquea_lectura_de_archivos`, `test_bloquea_denegacion_de_servicio`,
`test_bloquea_escritura_oculta_en_cte`, `test_mysql_sin_comandos_de_cliente`.

### T11 - Encubrimiento mediante el rollback
**Vector:** usar `rollback` para revertir una escritura y ocultar que ocurrio, o
manipular la bitacora para que restaure un respaldo ajeno.
**Mitigacion:** el rollback verifica la cadena antes de aplicar; solo restaura
respaldos que esten dentro de `backups/` de la bitacora; confinado al workspace;
verifica el hash antes y despues; deja su propio registro en la bitacora.
**Evidencia:** `agent/rollback.py`, `agent/cli.py`, pruebas
`test_bitacora_manipulada_cancela_rollback`, `test_respaldo_fuera_de_auditoria_se_omite`.

## 4. Riesgos residuales (declaracion honesta)

| # | Riesgo residual | Por que existe | Que hacer |
|---|-----------------|----------------|-----------|
| R1 | El agente no es un sandbox de SO | Los comandos permitidos (`npm test`) ejecutan codigo del proyecto | Aislar la maquina: sin VPN, sin credenciales de produccion, sobre una copia |
| R2 | Un comando de la lista blanca podria tener efectos | `npm run <script>` puede hacer cualquier cosa | Usar `--dry-run` y revisar `package.json` antes de habilitar scripts |
| R3 | La censura DLP es heuristica | Puede no detectar formatos de secreto desconocidos | No tener secretos reales en la maquina |
| R4 | El modelo local puede alucinar | Limitacion de los LLM | El operador valida; el agente no tiene autoridad final |
| R5 | Un operador podria aprobar algo indebido | El humano es parte del control | Bitacora con identidad y responsable documentado |
| R6 | Extraccion de datos por el prompt | El modelo podria repetir codigo leido | El modelo es local; no hay destino externo |
| R7 | La copia de la BD puede tener datos reales | "Copia" no garantiza datos anonimizados | Anonimizar o usar datos de prueba; recordar que la escritura sigue requiriendo confirmacion |
| R8 | El rollback no cubre lo que no se respaldo | Reescribe desde respaldos existentes | Revisar `--list` antes de aplicar; el rollback no inventa estados |
| R9 | `identity.json` puede contener datos personales | El operador escribe su nombre | El archivo es local y esta en `.gitignore`; no se versiona ni se sube |

## 5. Controles compensatorios obligatorios del entorno

Estos NO los puede garantizar el agente y son responsabilidad de TI/operador:

1. La maquina no tiene VPN activa ni acceso a produccion.
2. El proyecto es una copia local, no un recurso compartido de red.
3. No hay credenciales reales en la maquina.
4. La salida de red esta restringida salvo `127.0.0.1:11434`.
5. La bitacora se conserva y se revisa periodicamente.
