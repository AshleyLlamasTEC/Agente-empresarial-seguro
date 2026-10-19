# Manual de uso - Agente Empresarial Seguro

Version: 1.1.0
Dirigido a: operadores del agente (desarrolladores, TI, soporte tecnico).
Documentos relacionados: `GUIA_INSTALACION.md`, `POLITICA_DE_SEGURIDAD.md`,
`CHECKLIST_AUDITORIA.md`.

---

## 1. Proposito

Este manual explica **como usar correctamente** el Agente Empresarial Seguro:
que comandos existen, que hace cada uno, que se espera como salida, que esta
permitido, que esta prohibido y como manejar los bloqueos.

Uno de los controles mas importantes es el propio operador: el agente es
deliberadamente conservador, pero la decision final de aprobar o rechazar es
humana.

---

## 2. Requisitos previos

| Requisito | Detalle |
|-----------|---------|
| Python | 3.10 o superior. Sin dependencias externas. |
| Ollama | Instalado y corriendo en `http://127.0.0.1:11434`. |
| Modelo local | `ollama pull qwen2.5-coder:7b` |
| Workspace | Una COPIA local del proyecto, nunca un recurso de red. |
| Aislamiento | VPN desconectada. Sin acceso a produccion. |

Antes de la primera sesion del dia, ejecuta el diagnostico (seccion 5.1).

---

## 3. Conceptos basicos

### 3.1 Perfiles

Un **perfil** define que puede y que no puede hacer el agente. Son archivos
JSON versionados en `profiles/`: cambiarlos deja registro y requiere
justificacion.

| Perfil | Escritura | Comandos | Base de datos | Uso |
|--------|-----------|----------|---------------|-----|
| `consulta` | No | No | No | Entender, diagnosticar, proponer |
| `desarrollo` | Si (con confirmacion) | Lista blanca | No | Aplicar correcciones |
| `datos` | Si (con confirmacion) | Lista blanca | Solo lectura (local) | Probar consultas sobre una copia |

**Usa siempre `consulta` primero.** Es el que tiene cero capacidad de alterar
nada.

### 3.2 Workspace

Es la **unica** carpeta a la que el agente tiene acceso. Todo lo que quede
fuera (otras carpetas, unidades de red, la ruta original del proyecto) es
inaccesible por diseno: no es una recomendacion, es un bloqueo tecnico.

### 3.3 Confirmacion humana

Con el perfil `desarrollo`, cada escritura y cada comando se detienen y piden
tu aprobacion con `s/N`. Nada se aplica sin que tu escribas `s`.

### 3.4 Modo simulacion (`--dry-run`)

Recorre todo el flujo pero **no escribe ni ejecuta nada**. Muestra exactamente
lo que haria. Es la forma correcta de empezar cualquier sesion de correccion.

### 3.5 Bitacora

Cada accion queda registrada en un archivo `.jsonl` con hash encadenado. Sirve
como evidencia de auditoria y para demostrar que no fue alterada.

### 3.6 Censura de secretos (DLP)

Si un archivo contiene contrasenas, tokens, cadenas de conexion o llaves
privadas, el agente los sustituye por `***REDACTADO***` **antes** de que el
modelo los vea. En consola veras la nota `[secretos censurados: N]`.

### 3.7 Identidad del agente (arranca en blanco)

El agente **no trae identidad ni datos del usuario**: al instalarlo no tiene
nombre y no sabe con quien habla. La primera vez se configura:

```powershell
python -m agent.cli setup
```

Se guarda `identity.json` en la raiz del repo (nombre del agente, nombre de la
persona, notas y tono). Es un archivo **privado**: esta en `.gitignore` y no se
sube. Mientras no se configure, el agente lo dice con serenidad y no inventa
nombres ni datos. El tono por defecto es respetuoso y sereno (Zen).

### 3.8 Base de datos local (solo la copia)

El agente puede **consultar** una base de datos, pero unicamente una **copia
local** y por medio de la herramienta `db_query`:

- Solo hosts locales: `127.0.0.1`, `localhost`, `::1`. Un host remoto se rechaza.
- Motores: **SQLite** (siempre disponible) y **MySQL** (requiere el cliente
  `mysql` en el PATH).
- Por defecto **solo lectura**: `SELECT`, `EXPLAIN` y `PRAGMA`. Escribir o
  cambiar el esquema exige activarlo a proposito (`--db-write`, `--db-ddl`).
- Una sola sentencia por vez y **sin comentarios** (evita trucos de ocultamiento).
- El resultado se limita a `db_max_rows` filas y pasa por la censura de secretos.
- Cada consulta pide tu confirmacion y queda en la bitacora (`db_query`).

> La base de datos **de produccion no se toca nunca**: no es alcanzable (host
> remoto bloqueado) y no debe haber credenciales reales en la maquina.

---

## 4. Instalacion rapida

```powershell
cd C:\trabajo\agente-empresarial-seguro
Copy-Item .env.example .env
ollama pull qwen2.5-coder:7b
```

Detalle completo en `GUIA_INSTALACION.md`.

---

## 5. Comandos, uno por uno

La forma general es:

```
python -m agent.cli <comando> [banderas]
```

> Las banderas van **despues** del nombre del comando.

### 5.1 `doctor` - diagnostico previo (obligatorio)

```powershell
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia
```

Verifica: version de Python, validez del perfil, que el modelo sea local y este
descargado, que Ollama responda, que el workspace exista, que se pueda escribir
la bitacora y si hay credenciales sueltas en el proyecto.

Salida esperada (extracto):

```
[1] Python: 3.13.14
    [ok] Version compatible.
[2] Perfil
    [ok] 'consulta' cargado. Modo: SOLO LECTURA
[3] Poliza de datos (modelo local)
    [ok] Host validado como loopback: http://127.0.0.1:11434
    [ok] El modelo qwen2.5-coder:7b esta descargado.
RESULTADO: OK. El agente puede operar bajo este perfil.
```

**Regla:** si no termina en `RESULTADO: OK`, **no operes**. Corrige primero.

La seccion `[6] Aislamiento de red` es de verificacion manual: el agente no
puede comprobar por ti que la VPN este desconectada ni que no existan
credenciales reales. Confirmalo tu.

### 5.2 `profiles` - ver los perfiles disponibles

```powershell
python -m agent.cli profiles
```

Salida esperada:

```
  - consulta     [SOLO LECTURA    ] modelo=qwen2.5-coder:7b
  - desarrollo   [lectura/escritura] modelo=qwen2.5-coder:7b
  - datos        [lectura/escritura] modelo=qwen2.5-coder:7b | BD: solo lectura (local)
```

### 5.3 `models` - ver los modelos locales

```powershell
python -m agent.cli models
```

Lista los modelos de Ollama y marca con `CLOUD (prohibido para trabajo)`
cualquier modelo remoto. **Nunca operes con un modelo marcado como CLOUD.**

### 5.4 `ask` - ejecutar una tarea

```powershell
# Analisis, solo lectura (recomendado para empezar)
python -m agent.cli ask --profile consulta --workspace C:\trabajo\proyecto-copia `
  "Revisa el proyecto, lista los defectos y prioriza los cinco mas importantes"
```

Salida esperada (forma):

```
[i] Bitacora de auditoria: C:\...\audit\20260101T120000Z-consulta-1234.jsonl
[consulta] Tarea: Revisa el proyecto...
[consulta] Modelo local: qwen2.5-coder:7b | Herramientas: list_dir, read_file, grep
[1] list_dir: {"path": "."}
   -> OK
[2] read_file: {"path": "app.js", "start_line": 1, "end_line": 200}
   -> OK
[consulta] Terminado en 6 iteracion(es).

=================== RESULTADO FINAL ===================
(informe del agente)
```

Sin tarea, entra en modo interactivo:

```powershell
python -m agent.cli ask --profile consulta --workspace C:\trabajo\proyecto-copia
tarea> analiza el modulo de pagos
tarea> salir
```

### 5.5 `ask` en modo simulacion (obligatorio antes de escribir)

```powershell
python -m agent.cli ask --profile desarrollo --workspace C:\trabajo\proyecto-copia --dry-run `
  "Corrige el defecto de promedio() en app.js"
```

El agente muestra cada escritura propuesta precedida de `[SIMULACION]` y **no
toca el disco**. Revisa las propuestas; si te convencen, ejecuta sin `--dry-run`.

### 5.6 `ask` aplicando cambios (con confirmacion)

```powershell
python -m agent.cli ask --profile desarrollo --workspace C:\trabajo\proyecto-copia `
  "Corrige el defecto de promedio() en app.js"
```

Antes de cada cambio veras un bloque como este:

```
======================================================================
CONFIRMACION REQUERIDA
----------------------------------------------------------------------
MODIFICAR C:\trabajo\proyecto-copia\app.js
--- contenido propuesto ---
function promedio(valores) {
  if (valores.length === 0) return 0;
  ...
}
---------------------------
----------------------------------------------------------------------
Aplicar? [s/N]:
```

- Escribe `s` + Enter para aplicar.
- Escribe `n` + Enter (o solo Enter) para rechazar.

Al aplicar, el agente crea un **respaldo** y lo informa:

```
Modificado: C:\trabajo\proyecto-copia\app.js
Respaldo: C:\...\audit\backups\app.js.20260101T120500.bak
```

### 5.7 `verify-audit` - comprobar la integridad de la bitacora

```powershell
python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<sesion>.jsonl
```

Salida esperada:

```
[ok] Cadena integra: 42 registros verificados.
```

Si aparece `[x] Registro alterado` o `[x] Cadena rota`: **deten el uso y reporta
a seguridad de la informacion**.

### 5.8 `setup` - configurar la identidad del agente

```powershell
python -m agent.cli setup                 # asistente interactivo (primer uso)
python -m agent.cli setup --show          # ver la identidad actual
python -m agent.cli setup --reset         # borrarla y volver al estado en blanco
```

Tambien puedes hacerlo sin asistente:

```powershell
python -m agent.cli setup --agent-name "Kaizen" --user-name "Alex" --note "Trabaja en soporte"
```

Con `setup` el agente deja de estar en blanco: aprende su nombre, tu nombre y el
tono con el que debe conversar. Nada de esto viaja por red; queda solo en tu
equipo. `doctor` muestra en la seccion `[7] Identidad` si ya esta configurada.

### 5.9 `rollback` - deshacer cambios de una sesion

Vuelve un archivo (o toda una sesion) al estado **anterior** a la escritura, a
partir de los respaldos que la bitacora ya guardo. Verifica el hash antes y
despues, y solo actua dentro del workspace.

```powershell
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --list
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --last
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --session 20260101T120000Z
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --file app.js
```

Salida esperada (forma):

```
PLAN DE ROLLBACK
  RESTAURAR C:\trabajo\proyecto-copia\app.js   (respaldo: app.js.20260101T120500.bak)
CONFIRMACION REQUERIDA
  hash actual:  f6305c06...
  hash destino: 10d9b704...
Aplicar? [s/N]:
```

- `--list` solo muestra el plan (no cambia nada).
- `--dry-run` tambien simula sin tocar el disco.
- Cada restauracion queda en la bitacora; el rollback tambien es reversible.

### 5.10 `ask` con base de datos local (perfil `datos`)

```powershell
python -m agent.cli ask --profile datos --workspace C:\trabajo\proyecto-copia `
  "Con SQLite, revisa local.db y dime cuantos usuarios hay"
```

El agente pedira confirmacion por cada sentencia. La base nunca se toca en
`--dry-run`, y un `DELETE`/`UPDATE`/`INSERT` se rechaza salvo que uses
`--db-write` (y el DDL exige `--db-ddl`), siempre sobre la copia local.

Para MySQL local, define las credenciales por variables de entorno (no se
escriben en la linea de comandos ni en la bitacora):

```powershell
$env:AGENT_DB_USER = "root"                 # por defecto: root
$env:AGENT_DB_PASSWORD = "..."              # se pasa via MYSQL_PWD
```

SQLite no necesita credenciales: basta con indicar el archivo `.db`/`.sqlite`
dentro del workspace.

---

## 6. Banderas disponibles

| Bandera | Efecto | Cuando usarla |
|---------|--------|---------------|
| `--profile <nombre>` | Elige el perfil | Siempre explicito |
| `--workspace <ruta>` | Carpeta permitida | Siempre explicito |
| `--model <nombre>` | Sobrescribe el modelo del perfil | Solo modelos locales |
| `--host <url>` | Endpoint de Ollama | Solo `127.0.0.1` (lo demas se rechaza) |
| `--audit-dir <ruta>` | Donde guardar la bitacora | Si no quieres el valor por defecto |
| `--dry-run` | Simula sin efectos | Primera pasada de cualquier tarea |
| `--no-shell` | Desconecta la ejecucion de comandos | Revision de solo lectura |
| `--no-write` | Desconecta la escritura | Analisis profundo sin riesgo |
| `--no-db` | Desconecta el acceso a base de datos | Cuando la tarea no toca datos |
| `--db-write` | Permite escribir en la BD local (con confirmacion) | Migraciones de prueba en la copia |
| `--db-ddl` | Permite DDL (CREATE/DROP/ALTER) en la BD local | Rehacer el esquema de la copia |
| `--yes` | Omite confirmaciones | **Solo** combinado con `--dry-run` |

---

## 7. Uso correcto: reglas del operador

### 7.1 Haz esto

1. Ejecuta `doctor` al empezar.
2. Empieza con el perfil `consulta`.
3. Antes de escribir, una pasada con `--dry-run`.
4. Da tareas **especificas** y con archivo concreto.
5. Lee cada confirmacion antes de aprobar.
6. Verifica el resultado (revisa el diff, corre las pruebas).
7. Registra la evidencia al terminar (seccion 10).
8. Integra los cambios por el flujo normal de revision de codigo.

### 7.2 No hagas esto

| Prohibido | Por que |
|-----------|---------|
| Apuntar el workspace a produccion, staging o una ruta de red | Fuera de politica |
| Usar cualquier modelo marcado como `CLOUD` | Envia datos a un tercero |
| Aprobar cambios que no entiendes | Rompe el control humano |
| Usar `--yes` en modo real | Elimina la supervision |
| Dejar `.env`, `*.pem` o llaves en la maquina | Riesgo de exposicion |
| Modificar `profiles/` o el codigo de seguridad sin justificar | Rompe la trazabilidad |
| Ignorar un bloqueo y buscarle la vuelta | Es un hallazgo de seguridad |

---

## 8. Como dar buenas instrucciones

El agente responde mejor a tareas concretas y verificables.

| Pobre | Mejor |
|-------|-------|
| "arregla el proyecto" | "Revisa app.js y dime que hace la funcion promedio()" |
| "esta mal" | "En promedio(), el ciclo usa `<=` y deberia ser `<`: corrigelo" |
| "optimiza todo" | "Busca todas las funciones que puedan dividir entre cero y listalas" |
| "hazlo bonito" | "Aplica el estilo de codigo del resto del archivo a la funcion nueva" |

Reglas de oro:

1. **Un objetivo por tarea.** Tareas compuestas producen resultados confusos.
2. **Nombra archivos y funciones.** Reduce las vueltas de exploracion.
3. **Pide evidencia.** "Cita archivo y linea" fuerza respuestas verificables.
4. **Pide el arreglo, no solo el diagnostico.** Y apruebalo por separado.
5. **Si algo sale mal, detente.** No insistas con variaciones de la misma orden.

---

## 9. Bloqueos y errores

Un bloqueo **no es una falla**: es un control funcionando. Queda registrado.

| Mensaje | Significado | Que hacer |
|---------|-------------|-----------|
| `BLOQUEADO: Ruta fuera del workspace` | Intento de salir de la carpeta permitida | Revisa que el archivo este dentro del workspace |
| `BLOQUEADO: Comando esta en la lista negra` | Comando prohibido (`curl`, `ssh`, `mysql`, ...) | No hay vuelta: usa otra estrategia |
| `BLOQUEADO: Ejecutable no esta en la lista blanca` | No declarado en el perfil | Justificar y agregar al perfil si procede |
| `BLOQUEADO: Archivo protegido` | Es un archivo de credenciales | No debe leerse; retiralo de la copia |
| `BLOQUEADO: Host de base de datos no local` | Intento de conectar a un host remoto | Solo se admite la copia local |
| `BLOQUEADO: Escritura en BD en modo solo lectura` | `DELETE`/`UPDATE`/`INSERT` sin habilitarlo | Usa solo lectura; si es imprescindible, `--db-write` |
| `BLOQUEADO: DDL no permitido` | `CREATE`/`DROP`/`ALTER` sin habilitarlo | Usa `--db-ddl` solo sobre la copia |
| `BLOQUEADO: Una sola sentencia por consulta` | Intento de encadenar SQL con `;` | Divide la consulta |
| `Metacaracter de shell prohibido` | Intentaba encadenar con `;`, `&&`, `\|` | Prohibido; pide cambios via escritura de archivo |
| `Ollama no responde` | Servicio detenido | Ejecuta `ollama serve` |
| `El modelo no esta descargado` | Falta el pull | `ollama pull qwen2.5-coder:7b` |
| `Host remoto bloqueado` | `OLLAMA_HOST` apunta fuera | Usa `http://127.0.0.1:11434` |
| `Tu respuesta no fue JSON valido` | El modelo se desvio del formato | El agente se autocorrige; si es recurrente, usa un modelo mayor |
| `Se alcanzo el limite de iteraciones` | La tarea era vaga o muy grande | Divide la tarea en partes |

**Si el agente intenta algo prohibido, eso es informacion valiosa:** queda en la
bitacora (`tool_blocked`, `command_blocked`). No lo ocultes.

---

## 10. Rutina de una sesion completa

```
 1. Desconectar la VPN
 2. doctor --profile consulta            -> RESULTADO: OK
 3. ask --profile consulta "diagnostico" -> obtener el informe
 4. Priorizar los hallazgos (humano)
 5. ask --profile desarrollo --dry-run "arreglo N"
 6. Revisar las propuestas simuladas
 7. ask --profile desarrollo "arreglo N"  -> aprobar con 's' lo que entiendas
 8. Correr las pruebas del proyecto
 9. verify-audit --file <bitacora>.jsonl  -> "Cadena integra"
 10. rollback si algo salio mal         -> restaurar desde el respaldo
 11. Guardar evidencia (doctor, pruebas, integridad)
 12. Integrar por revision de codigo normal
```

### 10.1 Evidencia a guardar

```powershell
New-Item -ItemType Directory -Force C:\trabajo\evidencia | Out-Null
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia |
  Out-File C:\trabajo\evidencia\doctor.txt
python -m unittest discover -s tests -t . -v 2>&1 |
  Out-File C:\trabajo\evidencia\pruebas.txt
python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<sesion>.jsonl |
  Out-File C:\trabajo\evidencia\integridad.txt
```

### 10.2 Donde queda todo

| Que | Donde |
|-----|-------|
| Bitacoras | `%USERPROFILE%\.agente-empresarial\audit\` (o `--audit-dir`) |
| Respaldos | Subcarpeta `backups/` dentro de la bitacora |
| Evidencia | La carpeta que tu elijas (`C:\trabajo\evidencia`) |

---

## 11. Interpretar la bitacora

Cada linea es un registro JSON. Los eventos mas relevantes:

| Evento | Que significa |
|--------|---------------|
| `session_start` | Quien, en que equipo y con que version, empezo |
| `task_start` | Tarea pedida y workspace |
| `tool_call` | Herramienta usada, argumentos, duracion, exito |
| `tool_blocked` | Intento rechazado por politica |
| `command_blocked` | Comando prohibido intentado |
| `read_file` | Archivo leido, su hash y cuantos secretos se censuraron |
| `write_file` | Cambio aplicado, hash antes/despues y respaldo |
| `write_file_denied_by_user` | El operador dijo que no |
| `command_run` | Comando ejecutado y codigo de salida |
| `db_query` | Consulta a la base de datos local ejecutada |
| `db_blocked` | Consulta rechazada por politica (BD) |
| `db_dry_run` | Consulta simulada, sin tocar la base |
| `rollback` | Restauracion aplicada desde un respaldo |
| `task_finish` | Cierre, iteraciones y numero de llamadas |
| `session_end` | Fin de la sesion |

---

## 12. Preguntas frecuentes

**¿Puedo usarlo sobre el repositorio real?**
No. Solo sobre una copia local. Los cambios se integran despues por revision.

**¿Puede ver mi base de datos?**
Solo una **copia local** (perfil `datos`), en modo solo lectura y host local. La
base de produccion **no es alcanzable**: un host remoto se bloquea y las rutas
con `prod`/`produccion` estan prohibidas. No debe haber credenciales reales.

**¿Puede mandar mi codigo a internet?**
No. Solo habla con `127.0.0.1:11434`. Cualquier otro host se rechaza antes de
enviar nada.

**¿Puede borrar archivos?**
No. `rm`, `del`, `mv` estan prohibidos y no hay herramienta de borrado.

**¿Puede instalar cosas?**
No. `npm install`, `pip install`, `composer install` estan bloqueados.

**El agente propuso algo malo, ¿que hago?**
Rechaza con `n`. El intento queda en la bitacora. Reportalo si es grave.

**Aprobe algo por error, ¿como lo revierto?**
Usa `rollback` sobre la sesion: restaura el respaldo y verifica el hash antes y
despues. Tambien puedes tomar el archivo de `backups/` de la bitacora.

**¿Puedo ajustar los permisos?**
Si, editando `profiles/*.json`, pero con justificacion escrita y volviendo a
correr las pruebas (`python -m unittest discover -s tests -t .`).

**No entiendo el resultado, ¿es normal?**
Si. El agente ayuda, no decide. Pidele que lo explique en pasos o que cite las
lineas exactas.
