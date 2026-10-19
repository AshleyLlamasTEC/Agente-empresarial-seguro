# Agente Empresarial Seguro

Agente de IA **100% local** para analizar y corregir codigo en una **copia de
trabajo**, con controles verificables y bitacora de auditoria. No usa nube, no
toca produccion y no depende de herramientas externas.

```
                       +-------------------------------------------+
                       |            MAQUINA DEL TRABAJO            |
                       |                                           |
  Operador  <--------> |  agente/cli.py  <---- 127.0.0.1 ----> Ollama
   (humano)   confirma |        |                                  |
                       |        +--> Sandbox (solo el workspace)    |
                       |        +--> Politica (lista blanca)        |
                       |        +--> DLP (censura de secretos)      |
                       |        +--> Bitacora encadenada (auditoria)|
                       |                                           |
                       |  Sin VPN | Sin red corporativa | Sin prod |
                       +-------------------------------------------+
```

## Que hace

- **Perfil `consulta`** (solo lectura): diagnostica defectos, explica codigo y
  propone arreglos. No puede escribir ni ejecutar comandos.
- **Perfil `desarrollo`** (lectura/escritura): aplica cambios **con tu
  confirmacion** y ejecuta comandos de una lista blanca.
- **Perfil `datos`** (copia local): permite consultar una base de datos **local**
  (SQLite o MySQL en `127.0.0.1`), siempre en solo lectura y con confirmacion.
- **Rollback**: deshace los cambios de escritura de una sesion desde los respaldos
  de la bitacora, verificando el hash antes y despues.

## Flags utiles

| Flag | Efecto |
|---|---|
| `--dry-run` | Simula: no escribe, no ejecuta, no toca la base de datos |
| `--yes` | Omite la confirmacion humana (usar solo con `--dry-run`) |
| `--no-write` | Deshabilita la escritura de archivos |
| `--no-db` | Deshabilita el acceso a base de datos |
| `--db-write` | Permite escribir en la base de datos local (con confirmacion) |
| `--db-ddl` | Permite DDL (CREATE/DROP/ALTER) en la base de datos local |
| `--model` | Modelo de Ollama a usar en esta sesion |

## Requisitos

- Python 3.10 o superior (sin dependencias: solo libreria estandar).
- [Ollama](https://ollama.com/download) con un modelo local:
  `ollama pull qwen2.5-coder:7b`

## Inicio rapido

```bash
# 1. Diagnostico de cumplimiento (no ejecuta nada)
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia

# 2. Analisis de solo lectura
python -m agent.cli ask --profile consulta --workspace C:\trabajo\proyecto-copia \
  "Revisa el proyecto, lista los defectos y propone arreglos"

# 3. Correccion con confirmacion en cada cambio
python -m agent.cli ask --profile desarrollo --workspace C:\trabajo\proyecto-copia \
  "Corrige el defecto de promedio() en app.js"

# 4. Verificar que la bitacora no fue alterada
python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<archivo>.jsonl

# 5. Deshacer los cambios de la ultima sesion (desde los respaldos)
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia --list
python -m agent.cli rollback --workspace C:\trabajo\proyecto-copia
```

Sin tarea, `ask` entra en modo interactivo. `--dry-run` simula sin escribir ni
ejecutar nada (ideal para la primera sesion).

## Base de datos local

Con el perfil `datos` el agente puede **consultar** una copia local de la base de
datos, nunca produccion:

```bash
# Solo lectura (por defecto): SELECT / EXPLAIN / PRAGMA
python -m agent.cli ask --profile datos --workspace C:\trabajo\copia `
  "Con SQLite, revisa local.db y dime cuantos usuarios hay"
```

- Solo hosts locales (`127.0.0.1`, `localhost`, `::1`); los remotos se bloquean.
- Una sola sentencia, sin comentarios; el dry-run no toca la base.
- El SELECT se limita a `db_max_rows` filas y pasa por la censura de secretos.
- Cada sentencia queda registrada en la bitacora (`db_query`).
- `--db-write` habilita escritura y `--db-ddl` habilita DDL, ambos con tu
  confirmacion explicita y sobre la copia local.

Para MySQL local, las credenciales se pasan por entorno y nunca viajan en la
bitacora: `AGENT_DB_USER` (por defecto `root`) y `AGENT_DB_PASSWORD`.

## Primer uso: identidad del agente

El agente **arranca en blanco**: no tiene nombre y no sabe nada de la persona con
quien habla. Nada de esto viene de fabrica; se define la primera vez:

```bash
python -m agent.cli setup
```

`setup` guarda `identity.json` en la raiz del repositorio (nombre del agente,
nombre de la persona, notas y tono de conversacion). Ese archivo es privado:
esta en `.gitignore` y **no se sube**. En el repositorio solo vive la plantilla
vacia `identity.example.json`.

```bash
python -m agent.cli setup --show     # ver la identidad actual
python -m agent.cli setup --reset    # borrarla y volver al estado en blanco
```

Hasta que se configure, el agente responde con serenidad que aun no tiene
identidad, sin inventar nombres ni datos. El tono por defecto es **respetuoso y
sereno (Zen)**.

## Controles de seguridad

| # | Control | Como se implementa |
|---|---------|--------------------|
| 1 | Sin acceso a la nube | El cliente HTTP solo acepta `127.0.0.1`/`localhost`; los modelos con marca de nube se rechazan (`agent/ollama_client.py`) |
| 2 | Sin acceso a produccion | Denylist de `ssh`, `curl`, `mysql`, `kubectl`, `aws`, `deploy`, `migrate`, etc. y de rutas con `prod`/`produccion` (`agent/policy.py`) |
| 3 | Confinamiento al workspace | Toda ruta se resuelve y valida; se bloquean `..`, absolutas, UNC, `~` y enlaces que escapan (`agent/sandbox.py`) |
| 4 | Sin encadenar comandos | Se prohiben `; & \| ` ` $ > <` y saltos de linea (`agent/policy.py`) |
| 5 | Lista blanca de comandos | Solo se ejecuta lo declarado en el perfil; todo lo demas se niega |
| 6 | Sin instalar dependencias | `npm install`, `pip install`, `composer install`, etc. bloqueados |
| 7 | Sin comandos destructivos | `rm`, `del`, `mv`, `git reset`, `git clean`, `git push` bloqueados |
| 8 | Proteccion de credenciales | `.env`, `*.pem`, `*.key`, `id_rsa`, `credentials*` no se pueden leer (`agent/dlp.py`) |
| 9 | Censura de secretos | Contrasenas, tokens, cadenas de conexion y llaves privadas se redactan antes de llegar al modelo (`agent/dlp.py`) |
| 10 | Confirmacion humana | Cada escritura y cada comando requiere tu `s/N` (perfil `desarrollo`) |
| 11 | Respaldo automatico | Cada archivo modificado se copia antes de escribirse (`audit/backups/`) |
| 12 | Entorno saneado | Los comandos reciben solo variables de entorno seguras (`agent/tools.py`) |
| 13 | Bitacora encadenada | Cada registro incluye el hash del anterior; alterarlo rompe la cadena (`agent/audit.py`) |
| 14 | Deny by default | Lo que no esta explicitamente permitido, se niega |
| 15 | Base de datos solo local | Solo `127.0.0.1`/`localhost`/`::1`; una sentencia, sin comentarios, sin DDL por defecto (`agent/db.py`) |
| 16 | Rollback verificado | Restaura respaldos solo dentro del workspace y comprueba el hash antes/despues (`agent/rollback.py`) |
| 17 | Identidad privada | `identity.json` es local y no se sube; arranca en blanco (`agent/identity.py`) |

## Estructura

```
agent/
  cli.py              Interfaz de linea de comandos
  config.py           Carga y valida perfiles
  identity.py         Identidad configurable (en blanco por defecto)
  policy.py           Lista blanca/negra de comandos y rutas
  sandbox.py          Confinamiento al workspace
  dlp.py              Proteccion y censura de datos
  db.py               Acceso a base de datos local (SQLite/MySQL)
  rollback.py         Deshacer escrituras desde los respaldos
  ollama_client.py    Cliente Ollama solo-local
  tools.py            Herramientas (list_dir, read_file, grep, write_file, run_command, db_query)
  agent.py            Bucle pensar-actuar-observar
  audit.py            Bitacora encadenada por hash
profiles/             consulta.json, desarrollo.json, datos.json
identity.example.json Plantilla de identidad (identity.json es privado)
tests/                98 pruebas automatizadas
docs/                 Politica, amenazas, instalacion, checklist, mapeo, modelos
opencode-integration/ Perfiles equivalentes para opencode (opcional)
examples/demo-proyecto/ Proyecto con defectos para probar sin riesgo
```

## Pruebas

```bash
python -m unittest discover -s tests -t . -v
```

Cubren: intentos de escape del sandbox, comandos peligrosos, censura de
secretos, integridad de la bitacora, el bucle del agente (con modelo simulado,
sin necesidad de Ollama), la identidad, el rollback y el acceso a base de datos
local.

## Documentacion para auditoria

- `docs/MANUAL_DE_USO.md` - instructivo de uso correcto paso a paso.
- `docs/JUSTIFICACION_DE_SEGURIDAD.md` - dictamen: por que es seguro y no es amenaza.
- `docs/POLITICA_DE_SEGURIDAD.md` - reglas, alcance y prohibiciones.
- `docs/MODELO_DE_AMENAZAS.md` - riesgos identificados y su mitigacion.
- `docs/MAPEO_CONTROLES.md` - control -> codigo -> evidencia.
- `docs/GUIA_INSTALACION.md` - instalacion paso a paso en la maquina de trabajo.
- `docs/CHECKLIST_AUDITORIA.md` - lista de verificacion y evidencia a recabar.
- `docs/MODELOS_LOCALES.md` - que modelo de Ollama elegir segun tu equipo.

## Limitaciones honestas

Este agente **no es un sandbox del sistema operativo**. La lista blanca reduce
el riesgo, pero los comandos ejecutados (por ejemplo `npm test`) pueden correr
codigo arbitrario del proyecto. Por eso el aislamiento real debe aportarlo el
entorno: sin VPN, sin credenciales de produccion y sobre una copia. Ver
`docs/MODELO_DE_AMENAZAS.md`, seccion "Riesgos residuales".
