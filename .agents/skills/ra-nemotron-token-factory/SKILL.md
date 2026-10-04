---
name: ra-nemotron-token-factory
description: "Integrar, probar y controlar el gasto de NVIDIA Nemotron en Nebius Token Factory para el Reliability Agent: verificar IDs de modelo, prompts versionados, salida JSON, spikes, fallback y presupuesto de 30 USD. Úsala para cambiar planner o prompt, elegir modelo o estimar coste. No para acciones de dispositivo (ra-safe-action)."
metadata:
  author: aiambo08
  version: '1.0'
---

# Nemotron en Token Factory

Código: `src/reliability_agent/nemotron/` (`client.py`, `planner.py`, `budget.py`,
`prompts/diagnose_v1.md`). Config: bloques `planner`, `nebius`, `budget` de `configs/default.yaml`.
API OpenAI-compatible en `https://api.tokenfactory.nebius.com/v1/`; la clave va solo en
`NEBIUS_API_KEY` dentro de `.env` y nunca se imprime ni se commitea.

## Límites que no se negocian

- Gasto total ≤ 30 USD de crédito del hackathon, sin tarjeta ni endpoints dedicados.
  Topes de cliente: soft 23 (sin llamadas no esenciales), demo 25 (solo demo), hard 27 (cero llamadas).
- Nemotron solo se llama tras un incidente CONFIRMED, ≤ `max_calls_per_incident` (2), con caché
  por firma del incidente. Es asesor: su salida es un `NemotronPlan` validado y luego pasa por la
  policy gate; nunca ejecuta.
- El paquete al modelo solo lleva métricas numéricas, enums y acciones permitidas; texto libre de
  la cámara truncado y marcado no confiable. Nunca se envía vídeo ni imágenes.
- Timeout o circuit breaker abierto → plan local `needs_human`; la monitorización no se bloquea.

## Tareas

**Verificar modelos (Gate F0).** Ejecuta `python scripts/list_models.py`. Si un ID de
`nebius.models` sale `NOT AVAILABLE`, actualiza config y precios (catálogo público
`https://tokenfactory.nebius.com/model-catalog.md`), registra el motivo en
`docs/adr/ADR-002-model-selection.md`. Nunca escribas IDs ni precios en código.

**Cambiar el prompt.** No edites `diagnose_v1.md` en sitio: crea `diagnose_v2.md`, cambia
`planner.prompt_version`, añade/ajusta tests en `tests/unit/test_planner_budget.py` (con cliente
falso) y compara v1 vs v2 en el spike antes de adoptarlo. La versión queda registrada en cada uso.

**Spike en vivo (cuesta céntimos — avisa al usuario antes).**
`python scripts/spike_nemotron.py --n 20 [--tier reasoning]` → `runs/spikes/nemotron.jsonl`.
Gate F1: ≥ 19/20 respuestas válidas y proyección de 300 diagnósticos ≤ 23 USD.
Test en vivo opcional: `pytest -m live`.

**Informe de gasto (sin red).** Ejecuta
`python <skill>/scripts/budget_report.py --repo /home/user/workspace/repo` para ver gasto por
modelo y versión de prompt, coste medio y margen hasta cada tope. Es una estimación: el saldo
autoritativo es la consola de Nebius; pide al usuario que lo compruebe antes de la demo.

**Elegir modelo.** Tier rápido (Nano / 3.5 Lightning) por defecto; Super solo si hay ambigüedad
(varias causas candidatas o confianza baja). Ultra no se usa salvo ADR con justificación de coste.
Si `json_schema` falla, el cliente cae a `json_object` una vez por modelo; anota en
`docs/feedback.md` cualquier comportamiento de la plataforma (sirve para el requisito de feedback).

## Comprobación final

`python3 -m pytest -q tests/unit/test_planner_budget.py tests/adversarial` en verde, ningún secreto
en el diff (`git diff | grep -i "api_key\|bearer"` vacío) y `docs/budget.md` actualizado si cambian
topes o modelos.
