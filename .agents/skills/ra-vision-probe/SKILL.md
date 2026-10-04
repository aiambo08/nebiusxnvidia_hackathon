---
name: ra-vision-probe
description: "Crear, calibrar o depurar probes de visión y reglas de fallo del Reliability Agent (oscuridad, blur, congelación, oclusión, FOV, tarea ArUco): contrato ProbeResult, umbrales en config, latencia y falsos positivos. Úsala para 'detecta este fallo', 'hay falsos positivos', 'ajusta umbrales'. No para generar datasets de benchmark (ra-fault-benchmark)."
metadata:
  author: aiambo08
  version: '1.0'
---

# Probes de visión y reglas de fallo

Flujo: `probes/*.py` → `probes/runner.py` (`ProbeRunner.analyse`, `WindowAggregator`) →
`TelemetryWindow` → `incidents/fusion.py::classify_window` (reglas + z-score robusto MAD de
`baselines/robust.py`) → `IncidentTracker` (histéresis HEALTHY→SUSPECT→CONFIRMED).

## Reglas

- Cada probe devuelve `ProbeResult` (`probes/base.py`): score, evidencia, calidad de medida y
  motivo `unknown` cuando no puede medir (p. ej. imagen negra → blur desconocido). Nunca devuelvas
  un valor inventado cuando la medida no es fiable.
- Todo umbral vive en `configs/default.yaml` (`probes`, `faults`, `fusion`). Cambiar uno que afecte
  a una gate exige ADR + informe de benchmark; nunca lo cambies solo para que pase un test.
- La baseline no aprende durante SUSPECT/CONFIRMED/ACTING/VERIFYING.
- Las métricas de imagen no bastan como criterio de éxito: la detección ArUco es no monótona con
  el blur (falla con kernel 9, vuelve a detectar con 21–31). Valida siempre contra la tarea.
- Explicaciones causales: un fallo puede explicar otros (blackout explica oclusión y blur); mantén
  la supresión en `classify_window` cuando añadas reglas.

## Checklist para una probe o regla nueva

1. Implementa la medida en `probes/<area>.py` con NumPy/OpenCV, sobre `downscale(to_gray(...))`.
   Probes de textura sobre imagen normalizada por brillo; geometría sobre `cv2.equalizeHist`.
2. Agrégala en `ProbeRunner.analyse` y en el campo correspondiente de `VisualMetrics`
   (cambio de contrato → ADR).
3. Añade la regla en `classify_window` con umbral en `faults.<fallo>` de la config.
4. Tests en `tests/unit/test_probes.py` y `tests/unit/test_baseline_fusion.py`: caso positivo,
   caso negativo legítimo (escena estática, cambio de luz suave, cámara sana pero oscura) y
   determinismo. Usa `tests.conftest.make_window` y `SyntheticSource(seed=...)`.
5. Latencia: `python scripts/bench_probes.py` — p95 ≤ 40 ms a 720p (Gate F3). Si sube, baja la
   frecuencia (`geometry.every_n_frames`) antes que la resolución.
6. Comprueba que `ra-demo all` sigue terminando cada escenario como antes
   (`tests/e2e/test_scenarios.py`).

Hecho cuando los tests nuevos y los e2e pasan y la latencia sigue bajo el límite.

## Depurar un falso positivo

Reproduce con el escenario o un manifiesto sembrado, imprime las métricas de la ventana
(`ra-demo live -v` o el evento `incident` en el event store), identifica qué condición de la regla
se cumplió y corrige la causa (normalización, requisito adicional, supresión causal) con un test
de regresión que falle antes del arreglo. Etiqueta los hallazgos como SIMULATION o REAL HARDWARE.
