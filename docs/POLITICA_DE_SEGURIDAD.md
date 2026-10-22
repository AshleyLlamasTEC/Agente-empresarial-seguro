# Politica de seguridad del Agente Empresarial Seguro

Version: 1.1.1
Ambito: uso del agente de IA local para analisis y correccion de codigo.
Aplicable a: cualquier persona que opere el agente en equipos de la empresa.

## 1. Objetivo

Permitir el uso de un asistente de IA para retomar y corregir proyectos con
defectos tecnicos, **sin riesgo para los datos de la empresa y sin acceso a
produccion**, con controles verificables y evidencia para auditoria.

## 2. Principios

1. **Aislamiento por defecto.** El agente solo ve una copia del proyecto.
2. **Deny by default.** Todo lo que no este expresamente permitido, se niega.
3. **Nada sale de la maquina.** El modelo de IA se ejecuta en `127.0.0.1`.
4. **El humano decide.** Las escrituras y los comandos requieren confirmacion.
5. **Todo queda registrado.** Cada accion genera un registro encadenado.
6. **Lo que no se puede demostrar, no se declara.** Los controles estan en el
   codigo y en las pruebas; no en la buena intencion del operador.

## 3. Alcance

Se autoriza el uso del agente para:

- Analizar codigo de una COPIA local de un proyecto.
- Identificar defectos, deuda tecnica y riesgos.
- Proponer y aplicar correcciones sobre esa copia.
- Ejecutar pruebas del proyecto sobre esa copia.

## 4. Prohibiciones expresas

Queda prohibido:

| # | Prohibicion |
|---|-------------|
| P1 | Apuntar el agente a produccion, staging o cualquier ambiente vivo. |
| P2 | Usar bases de datos productivas. Solo datos sinteticos o anonimizados. |
| P3 | Operar sobre carpetas compartidas de red o unidades mapeadas. |
| P4 | Usar modelos remotos o en la nube (OpenAI, Anthropic, Google, DeepSeek cloud, etc.). |
| P5 | Introducir credenciales reales en la maquina del agente. |
| P6 | Deshabilitar o modificar el sandbox, la politica de comandos, la proteccion de datos o la bitacora. |
| P7 | Ejecutar despliegues, migraciones o publicacion de paquetes. |
| P8 | Conectar la maquina a la VPN durante las sesiones del agente. |
| P9 | Copiar codigo o datos de la empresa a servicios externos. |

## 5. Reglas tecnicas obligatorias

1. El perfil `consulta` es **solo lectura**: no escribe ni ejecuta comandos.
2. El perfil `desarrollo` exige `require_confirmation: true`; no puede
   configurarse lo contrario (la validacion falla al arrancar).
3. Todo comando debe pertenecer a la lista blanca del perfil.
4. Todo comando con metacaracteres de shell (`; & | ` $ > <`) se rechaza.
5. Los archivos de credenciales nunca se leen ni se escriben.
6. Los secretos detectados en el contenido se censuran antes de enviarse al
   modelo.
7. Toda modificacion genera un respaldo previo.
8. La bitacora se escribe fuera del repositorio, en modo append-only.

## 6. Datos

| Categoria | Tratamiento |
|-----------|-------------|
| Codigo fuente | Copia local, no se transmite a terceros |
| Credenciales | Prohibidas en la maquina; bloqueadas y censuradas por el agente |
| Datos personales | No se cargan; si se requieren, usar datos sinteticos |
| Bitacoras de auditoria | Se conservan para revision; incluyen hash de integridad |
| Modelos de IA | Se ejecutan localmente; no hay llamadas a internet |

## 7. Responsabilidades

- **Operador:** ejecutar `doctor` antes de cada sesion, revisar cada
  confirmacion, no aprobar cambios que no entienda.
- **Dueño del proyecto:** autorizar el uso sobre una copia y revisar los
  cambios antes de integrarlos al repositorio oficial.
- **Auditoria/TI:** verificar los controles, revisar las bitacoras y validar el
  aislamiento de la maquina.

## 8. Revision

Todo cambio en esta politica o en los perfiles debe:
1. Justificarse por escrito.
2. Pasar las pruebas automatizadas (`python -m unittest discover -s tests -t .`).
3. Quedar registrado en el historial del repositorio.

## 9. Incumplimiento

El uso fuera de estas reglas constituye una violacion de la politica de
seguridad de la informacion de la empresa.
