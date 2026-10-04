---
name: ra-phase-gate-review
description: "Auditar si una fase F0–F12 del Physical AI Reliability Agent puede pasar su puerta de calidad: contrastar cada condición de docs/phases-and-gates.md con evidencia real (tests, CI, informes, vídeo) y emitir veredicto. Úsala con '¿podemos pasar a la fase X?', 'revisa la gate', 'estado de fases'. No para implementar."
metadata:
  author: aiambo08
  version: '1.0'
---

# Revisión de puerta de fase

La fuente de verdad es `docs/phases-and-gates.md` en el repo. Una fase **no** se aprueba porque
la funcionalidad "parece funcionar": hace falta código integrado, tests, métricas mínimas,
evidencia reproducible y revisión por un rol distinto del autor.

## Procedimiento

1. Lee la sección de la fase pedida y la tabla de estado; lee `docs/agents/PROJECT_STATE.md`.
2. Para cada condición, busca evidencia verificable y clasifícala:
   - **PROBADA**: test concreto que pasa (cita `ruta::nombre_test`), job de CI en verde, informe
     commiteado (`spikes/`, `benchmarks/reports/`, `runs/spikes/*.jsonl` aportado por el usuario).
   - **PARCIAL**: solo evidencia SIMULATION cuando la condición exige hardware real o datos reales.
   - **ABIERTA**: sin evidencia, o requiere un paso humano.
   Ejecuta los tests citados (`python3 -m pytest -q <ruta>::<test>`); no confíes en el nombre.
3. Comprueba también: ningún umbral de `configs/default.yaml` se relajó sin ADR
   (`git log -p configs/`), y la CI de `main` está en verde.
4. Veredicto: **APROBADA** solo si todas las condiciones están PROBADAS; si no, **NO APROBADA**
   con la lista mínima de acciones para cerrarla, cada una con responsable (agente o usuario).
5. Si el usuario pide registrarlo: marca `[x]` solo las PROBADAS, cambia el estado de la tabla
   (`not started` → `scaffolded` → `in progress` → `passed`), commit `docs: gate F<n> review` con
   `Gate: F<n>`.

## Reglas específicas

- F0 necesita una llamada real a Token Factory y los IDs confirmados por
  `scripts/list_models.py`; sin la `NEBIUS_API_KEY` del usuario queda ABIERTA.
- F1: Nemotron ≥ 19/20 respuestas válidas (`scripts/spike_nemotron.py --n 20`) y captura de
  30 min con ≥ 95 % ventanas válidas y crecimiento de heap ≤ 10 % (`spikes/capture-report.md`).
- F3: latencia de probes p95 ≤ 40 ms a 720p en el hardware del usuario
  (`scripts/bench_probes.py`); la medida del sandbox es solo orientativa.
- Un informe generado con `--synthetic` nunca cuenta como evidencia de hardware real.
- F12 depende de pasos humanos (vídeo YouTube público, envío Devpost): márcalos ABIERTOS hasta
  que el usuario confirme con enlace.

## Formato de salida

```
Fase F<n> — <nombre>: NO APROBADA (7/10 condiciones probadas)
| Condición | Estado | Evidencia |
| ... | PROBADA | tests/unit/test_x.py::test_y (CI #123) |
Para cerrar: 1) ... (usuario)  2) ... (agente)
```
