# Dictamen de seguridad

## Por que el Agente Empresarial Seguro no representa una amenaza para la empresa

Version: 1.1.0
Preparado para: Gerencia, Seguridad de la Informacion y Auditoria.
Documentos de soporte: `POLITICA_DE_SEGURIDAD.md`, `MODELO_DE_AMENAZAS.md`,
`MAPEO_CONTROLES.md`, `MANUAL_DE_USO.md`.

---

## 1. Conclusion ejecutiva

El Agente Empresarial Seguro es una herramienta de asistencia tecnica que se
ejecuta **integamente dentro del equipo de trabajo**, sin conexion a servicios
externos, sin acceso a ambientes productivos y sin capacidad de actuar sobre
nada fuera de una carpeta de copia autorizada.

Su riesgo no es "bajo por confianza", sino **bajo por construccion**: las
restricciones estan implementadas en el codigo y se pueden **comprobar de forma
independiente** ejecutando un conjunto de pruebas automatizadas, sin necesidad
de creer en la palabra de quien lo desarrollo.

Los tres hechos que sostienen este dictamen:

1. **No existe ruta de salida de datos.** El agente solo se comunica con
   `127.0.0.1` (Ollama local). Cualquier otro destino se rechaza antes de
   enviar informacion. No incluye clientes de red, de base de datos ni de
   servicios en la nube.
2. **No existe ruta hacia produccion.** Los clientes de base de datos
   (`mysql`, `psql`, `sqlcmd`, ...), las herramientas de red (`ssh`, `curl`,
   `scp`, ...), los contenedores y los despliegues estan prohibidos por lista
   negra. Las rutas con `prod`/`produccion` estan bloqueadas.
3. **Nada con efectos ocurre sin autorizacion humana.** Con el perfil de
   escritura, cada cambio y cada comando se detienen y exigen confirmacion
   explicita del operador. Ademas, toda accion queda en una bitacora con
   encadenamiento criptografico que delata cualquier alteracion.

**Recomendacion:** autorizar su uso con las condiciones del apartado 10.

---

## 2. Que es y que no es

| Es | No es |
|----|-------|
| Un asistente local de analisis y correccion de codigo | Un servicio en la nube |
| Una herramienta de apoyo a una persona | Un sistema autonomo de decision |
| Una copia de trabajo aislada | Un agente conectado a los sistemas de la empresa |
| Una bitacora de evidencia | Un proceso sin supervision |
| 2 836 lineas de Python revisables | Caja negra de un proveedor externo |

---

## 3. Invariantes de diseno

Estas cuatro afirmaciones se sostienen en cualquier ejecucion, sin excepciones
configurables:

1. **Deny by default.** Lo que no esta explicitamente permitido, se niega. Si
   una regla no existe, la respuesta es "no".
2. **Modelo local obligatorio.** El cliente HTTP valida el destino y rechaza
   cualquier host que no sea `127.0.0.1`/`localhost`, ademas de rechazar
   modelos con marca de nube.
3. **Confianza cero en el modelo de IA.** Las decisiones de seguridad **no**
   dependen de lo que el modelo de lenguaje "decida" ni de que se porte bien.
   Aunque el modelo pidiera algo peligroso, el sandbox y la politica lo
   rechazan. Esto neutraliza tecnicas de inyeccion de instrucciones desde el
   propio codigo analizado.
4. **Todo con efectos es reversible y auditable.** Cada escritura genera un
   respaldo previo y un registro con hash antes/despues.

---

## 4. Por que no representa una amenaza

### A. No existe ruta hacia produccion

El agente no incorpora ningun cliente de base de datos ni de red. Ejecutar
`mysql`, `psql`, `ssh`, `curl`, `kubectl`, `aws` o `deploy` esta prohibido por
lista negra; ademas ninguna herramienta de red existe en su catalogo.

*Evidencia:* `agent/policy.py`, pruebas `test_bloquea_herramientas_de_red_y_produccion`
y `test_bloquea_instalacion_de_dependencias`.

*Limite honesto:* si un comando permitido (por ejemplo `npm test`) contuviera
codigo que intentara conectarse a produccion, el agente no lo impediria por si
mismo. Esto se cubre con el aislamiento de red del apartado 9 y esta declarado
como riesgo residual R1.

### B. La informacion de la empresa no sale del equipo

El unico destino de red es `127.0.0.1:11434`. El cliente rechaza el host en el
constructor, antes de enviar un solo byte. Ademas:

- No hay telemetria del agente.
- No hay integracion con proveedores de IA externos.
- Los secretos detectados se censuran antes de salir hacia el modelo.

*Evidencia:* `agent/ollama_client.py: _validate_host`, `agent/dlp.py`,
pruebas `test_rechaza_modelo_en_la_nube` y
`test_secretos_censurados_antes_de_llegar_al_modelo`.

### C. No puede salir de la carpeta autorizada

Toda ruta se normaliza y se verifica que quede dentro del workspace. Se
bloquean: `..`, rutas absolutas (`C:\...`, `/etc/...`), rutas UNC
(`\\servidor\recurso`), el atajo `~`, enlaces simbolicos que escapan y nombres
reservados de Windows.

*Evidencia:* `agent/sandbox.py`, pruebas `test_bloquea_traversal`,
`test_bloquea_rutas_absolutas`, `test_bloquea_unc_y_home`.

### D. Ninguna accion con efectos ocurre sin autorizacion humana

- El perfil `consulta` **no puede escribir ni ejecutar comandos**: no es una
  opcion que se pueda activar, es ausencia de capacidad.
- El perfil `desarrollo` exige `require_confirmation: true`. La validacion
  **falla al arrancar** si alguien intenta configurar escritura sin
  confirmacion.

*Evidencia:* `agent/config.py: validate_profile`, pruebas
`test_rechaza_escritura_sin_confirmacion`,
`test_escritura_rechazada_por_el_operador`.

### E. Toda accion es trazable y la bitacora no se puede alterar en silencio

Cada registro incluye el hash SHA-256 del registro anterior. Si alguien edita,
agrega o borra una linea, la verificacion de la cadena falla. Esto permite
demostrar que la evidencia es autentica.

*Evidencia:* `agent/audit.py`, pruebas `test_cadena_valida`,
`test_detecta_manipulacion`, `test_detecta_borrado_de_registro`.

La bitacora registra identidad del operador, equipo, versiones, cada comando
ejecutado, cada archivo leido (con su hash) y cada escritura (con hash
antes/despues y ruta del respaldo).

### F. No tiene capacidades destructivas ni de escalada

Prohibido por diseno: `rm`, `del`, `mv`, `git reset --hard`, `git clean -fd`,
`git push`, `git remote`, `format`, `reg add`, `schtasks`, `netsh`,
`Set-ExecutionPolicy`, `Invoke-Expression`, `Start-Process`, `powershell`,
`python -c`, `node -e`, instalacion global de paquetes. No hay herramienta de
borrado en el catalogo del agente.

*Evidencia:* `agent/policy.py`, pruebas `test_bloquea_git_que_muta_o_toca_remotos`,
`test_bloquea_ejecucion_dinamica`.

### G. Se puede verificar sin confiar en quien lo desarrollo

Auditoria puede reproducir las 98 pruebas automatizadas y ver el resultado. No
se requiere revisar las 2 836 lineas leyendolas completas: las pruebas
**intentan activamente** los escenarios de riesgo (escapar del sandbox,
encadenar comandos, leer credenciales, alterar la bitacora) y demuestran que
fallan.

*Evidencia:* `tests/`, comando de verificacion en el apartado 10.

---

## 5. Matriz: amenaza -> control -> evidencia

| Amenaza | Control que la impide | Evidencia verificable |
|---------|----------------------|----------------------|
| Enviar codigo o datos a un proveedor externo | Modelo local obligatorio; host validado como loopback | `ollama_client.py`, `test_rechaza_modelo_en_la_nube` |
| Conectarse a la base de datos de produccion | Lista negra de clientes de BD; perfiles sin herramientas de red | `policy.py`, `test_bloquea_herramientas_de_red_y_produccion` |
| Modificar produccion o desplegar | Prohibicion de `deploy`, `migrate`, `git push`, contenedores | `policy.py` |
| Leer o copiar credenciales | Lista de nombres protegidos + censura de contenido | `dlp.py`, `test_detecta_archivos_sensibles` |
| Salir de la carpeta de trabajo | Sandbox de rutas | `sandbox.py`, 4 pruebas de escape |
| Inyectar comandos maliciosos | Prohibicion de metacaracteres; ejecucion sin shell | `policy.py`, `test_bloquea_encadenamiento_de_comandos` |
| Destruir archivos del proyecto | Comandos destructivos prohibidos; respaldo previo | `tools.py`, `test_escritura_aprobada_con_respaldo` |
| Que la IA actue por su cuenta | Confirmacion obligatoria; perfil de solo lectura | `config.py`, `test_escritura_rechazada_por_el_operador` |
| Ocultar una accion indebida | Bitacora con hash encadenado | `audit.py`, `test_detecta_manipulacion` |
| Instalar software no autorizado | `npm install`, `pip install`, `winget`, `choco` bloqueados | `policy.py` |
| Que el proyecto analizado "convenza" a la IA de saltarse reglas | Los controles son de codigo, no del prompt | `tools.py`, `policy.py` |

---

## 6. Que NO puede hacer el agente (capacidades inexistentes)

Es importante distinguir entre "se le prohibe" y "no puede". Esto ultimo no
depende de la buena voluntad del modelo:

- No puede acceder a la red corporativa ni a internet.
- No puede conectarse a ninguna base de datos.
- No puede ejecutar contenedores ni herramientas de orquestacion.
- No puede leer ni escribir fuera de la carpeta autorizada.
- No puede borrar archivos ni directorios (no existe la capacidad).
- No puede instalar ni actualizar software.
- No puede publicar paquetes ni tocar repositorios remotos.
- No puede ejecutar codigo en linea (`python -c`, `node -e`).
- No puede modificar el registro de Windows ni el programador de tareas.
- No puede operar sin que el operador apruebe cada accion con efectos.
- No puede alterar su propia bitacora sin que se detecte.

---

## 7. Comparacion de riesgo: el escenario que esto sustituye

El riesgo real no es este agente; es la practica que se usa cuando no existe
una herramienta aprobada.

| Practica sin control | Riesgo | Este agente |
|----------------------|--------|-------------|
| Pegar codigo de la empresa en un chat de IA publico | **El codigo sale de la empresa a un tercero** (fuga permanente e irremediable) | El modelo corre local; nada sale |
| Pedirle a una IA en la nube que "arregle" y aplicar a ciegas | Cambios sin revision ni evidencia | Confirmacion humana + respaldo + bitacora |
| Copiar la base de datos productiva "para probar" | Exposicion de datos de clientes | Prohibido; solo datos sinteticos |
| Dar acceso de red al asistente | Ruta directa a produccion | Sin capacidad de red ni de BD |
| Confiar en que el asistente "no hara nada malo" | Sin pruebas ni trazabilidad | 98 pruebas + bitacora encadenada |

En terminos de riesgo de fuga de informacion, este agente es **estrictamente
mas seguro que cualquier asistente de IA en la nube**, sin importar cuan
reputado sea el proveedor: en la nube la informacion **necesariamente** sale
del control de la empresa; aqui, **estructuralmente**, no puede.

---

## 8. Riesgos residuales y controles compensatorios

Declararlos es parte de la seriedad del dictamen. Ninguno de estos riesgos
permite acceso a produccion ni exfiltracion de datos si se cumplen los
controles compensatorios.

| # | Riesgo residual | Control compensatorio obligatorio |
|---|-----------------|-----------------------------------|
| R1 | El agente no es un sandbox de sistema operativo: un comando permitido ejecuta codigo del proyecto | La maquina no tiene VPN ni acceso a produccion; el proyecto es una copia local |
| R2 | Un script de `package.json` podria tener efectos | Usar `--dry-run`; revisar los scripts antes de habilitarlos; no hay credenciales reales |
| R3 | La censura de secretos es heuristica y podria no detectar formatos desconocidos | No debe haber secretos reales en la maquina del agente |
| R4 | El modelo puede equivocarse o "alucinar" | El humano valida; el agente no tiene autoridad final ni acceso a sistemas reales |
| R5 | Un operador podria aprobar un cambio indebido | Bitacora con identidad; el operador es responsable de lo que aprueba |
| R6 | El equipo almacena bitacoras con informacion de codigo | Las bitacoras se guardan y custodian segun la politica de manejo de informacion |

**Declaracion:** el agente **no sustituye** al aislamiento del entorno. Lo
complementa. Si se opera sobre la maquina equivocada, con la VPN conectada y
con credenciales reales, el riesgo lo aporta el entorno, no la herramienta.

---

## 9. Condiciones de uso recomendadas (a autorizar)

1. Operar **solo** sobre una copia local del proyecto.
2. Ejecutar **solo** en un equipo sin VPN activa y sin acceso a produccion.
3. No almacenar credenciales reales en ese equipo.
4. Usar **solo** modelos locales de Ollama; prohibido cualquier modelo con
   marca de nube.
5. Ejecutar el diagnostico (`doctor`) antes de cada sesion y conservar la salida.
6. Conservar las bitacoras y verificar su integridad al cierre de cada sesion.
7. Integrar los cambios al repositorio oficial **solo** mediante revision
   normal de codigo.
8. Cualquier cambio en los controles de seguridad requiere justificacion
   escrita, ejecucion de las pruebas y registro en el historial del repositorio.

---

## 10. Verificacion independiente por auditoria

Auditoria puede comprobar este dictamen sin confiar en el proveedor. Cuatro
comandos:

```powershell
# 1. Las pruebas de seguridad (98) deben pasar
python -m unittest discover -s tests -t . -v
#    Esperado: OK

# 2. El diagnostico de cumplimiento debe estar en verde
python -m agent.cli doctor --profile consulta --workspace C:\trabajo\proyecto-copia
#    Esperado: RESULTADO: OK

# 3. Ningun modelo en la nube esta en uso
python -m agent.cli models
#    Esperado: ningun modelo marcado CLOUD en uso

# 4. La bitacora de la sesion no fue alterada
python -m agent.cli verify-audit --file C:\trabajo\auditoria-agente\<sesion>.jsonl
#    Esperado: "[ok] Cadena integra: N registros verificados."
```

Prueba adicional (intento de fuga de datos): auditores pueden verificar que un
host remoto es rechazado.

```powershell
python -m agent.cli doctor --profile consulta --workspace . --host http://ejemplo.com
#    Esperado: "[x] Host remoto bloqueado"
```

Prueba adicional (intento de escape): pedir al agente leer un archivo de fuera
del workspace; debe responder `BLOQUEADO` y registrarlo en la bitacora.

---

## 11. Conclusion

El Agente Empresarial Seguro es una herramienta de asistencia local, acotada,
supervisada y auditable. No tiene acceso a ambientes productivos, no transmite
informacion fuera del equipo y no actua sin autorizacion de una persona. Sus
restricciones no dependen de la buena conducta del modelo de IA, sino de
controles de codigo comprobables de forma independiente.

El riesgo de no contar con una herramienta de este tipo es, en la practica,
mayor: empuja a los equipos a usar asistentes en la nube, donde la informacion
de la empresa **necesariamente** sale de su control.

Se somete a consideracion la autorizacion de su uso bajo las condiciones del
apartado 9.

---

## Anexo A - Matriz de responsabilidades

| Rol | Responsabilidad |
|-----|-----------------|
| Operador | Ejecutar `doctor`, revisar cada confirmacion, conservar evidencia |
| DueÃ±o del proyecto | Autorizar el uso sobre una copia y revisar los cambios |
| TI / Seguridad de la Informacion | Verificar el aislamiento del equipo y el cumplimiento de las condiciones |
| Auditoria | Ejecutar la verificacion independiente (apartado 10) y revisar bitacoras |
| Gerencia | Autorizar y revisar periodicamente el cumplimiento de las condiciones |

## Anexo B - Constancia

| | |
|---|---|
| Equipo | ______________________________ |
| Operador responsable | ______________________________ |
| Version del agente | 1.1.0 |
| Fecha de instalacion | ______________________________ |
| Autorizado por | ______________________________ |
| Firma y fecha | ______________________________ |
