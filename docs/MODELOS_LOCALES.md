# Modelos locales recomendados (Ollama)

El agente **solo** usa modelos locales de Ollama. Esta guia ayuda a elegir el
modelo segun tu equipo. No hay una respuesta unica: la mejor eleccion depende de
la VRAM de tu GPU y de la RAM.

> Regla absoluta: **nunca** uses modelos con sufijo `-cloud` (por ejemplo
> `deepseek-v3.1:671b-cloud`). Envian tus datos a un servidor externo y el agente
> los rechaza de todas formas (`agent/config.py: assert_model_is_local`).

## Elegir por hardware

| VRAM de GPU | Modelo recomendado | Comando | Nota |
|---|---|---|---|
| 8 GB (p. ej. RTX 4070 Laptop) | `qwen2.5-coder:7b` | `ollama pull qwen2.5-coder:7b` | Entra completo en la GPU; rapido y suficiente |
| 8 GB, casos dificiles | `qwen2.5-coder:14b` | `ollama pull qwen2.5-coder:14b` | Mejor calidad; parte en CPU, mas lento |
| 12-16 GB | `qwen2.5-coder:14b` o `qwen3:8b` | `ollama pull qwen3:8b` | 14B completo en GPU |
| 16 GB (sin GPU) | `gpt-oss:20b` | `ollama pull gpt-oss:20b` | Bueno, pero exige RAM y paciencia |
| 24 GB | `qwen3-coder:30b` | `ollama pull qwen3-coder:30b` | Referencia 2026 para codigo (MoE, ~3.3B activos) |

## Panorama 2026 (para codigo)

- **`qwen3-coder:30b`** — el modelo de codigo local de referencia de 2026
  (Mixture-of-Experts: ~3.3B parametros activos, contexto largo). Necesita
  ~17-18 GB en Q4: **no cabe** en una GPU de 8 GB.
- **`qwen2.5-coder:7b`** — la mejor relacion calidad/velocidad para portatiles y
  GPUs de 8 GB. Es el valor por defecto del agente.
- **`qwen3:8b`** — muy buen seguimiento de instrucciones y formato (util para que
  el modelo respete el protocolo JSON del agente).
- **`deepseek-coder-v2:16b`** — alternativa competente (~8.9 GB en Q4).
- **`devstral`** (Mistral, 24B) — orientado a tareas agenticas; requiere mas VRAM.

Los modelos con sufijo `-cloud`, o los que se ejecutan en un proveedor externo
(por ejemplo **Muse Spark** de OpenCode Zen), **no son locales** y no deben usarse
con informacion de la empresa.

## Como se usa el modelo

1. Descargalo una vez:

   ```powershell
   ollama pull qwen2.5-coder:7b
   ```

2. El perfil ya declara el modelo por defecto. Para usar otro sin editar el
   perfil:

   ```powershell
   python -m agent.cli ask --profile desarrollo --model qwen2.5-coder:14b `
     --workspace C:\trabajo\proyecto-copia "Analiza el proyecto"
   ```

3. Comprueba que Ollama responde y que ciudad de modelos tienes disponible:

   ```powershell
   python -m agent.cli models
   ```

   La salida marca con `CLOUD (prohibido para trabajo)` cualquier modelo en la
   nube que tengas listado.

## Consejos

- Si el agente "no respeta el formato", un modelo de 7B bien instruido
  (`qwen2.5-coder:7b`) suele bastar; sube a `qwen3:8b` o `:14b` si sigue fallando.
- Los modelos pequenos alucinan rutas y numeros de linea: el agente obliga a
  citar el archivo y el hallazgo, y **tu** confirmas cada cambio.
- Vigila el consumo: `ollama ps` muestra que modelo esta cargado en memoria.
