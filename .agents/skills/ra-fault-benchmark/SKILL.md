---
name: ra-fault-benchmark
description: "Construir y ejecutar el benchmark reproducible del Reliability Agent: grabar sesiones de webcam, inyectar fallos sembrados con manifiestos, split por sesión, métricas por fallo, ablaciones e informe. Úsala para 'crea el dataset', 'evalúa el agente', 'tabla de resultados', fases F4 y F10. No para crear probes nuevas (ra-vision-probe)."
metadata:
  author: aiambo08
  version: '1.0'
---

# Benchmark de fallos

Protocolo completo: `docs/evaluation.md`. Herramientas: `benchmarks/injectors/faults.py`
(espaciales: gaussian_blur, motion_blur_h/v, dark, overexpose, occlude_opaque/semi, rotate,
translate, lighting_change; temporales: freeze, loop4, loop8, fps_drop, delay_jitter),
`benchmarks/make_degraded.py`, manifiestos en `benchmarks/manifests/`.

## Reglas

- Vídeo crudo del usuario solo en local (`benchmarks/data/`, ignorado por git); nunca lo subas al
  repo ni a Token Factory. Se commitean manifiestos, hashes e informes.
- Split por **sesión**, nunca por frames consecutivos aleatorios (fuga de datos tipo WoodScape).
- Cada ejecución queda definida por su manifiesto (fuente + sha256, fallo, intensidad, frames
  inicio/fin, semilla, fallo y acción esperados o `needs_human`). Mismo manifiesto → mismo vídeo.
- Incluye negativos: escena estática, cambio de luz legítimo, cámara sana. Sin negativos no se
  puede medir falsas alarmas por hora.
- Las llamadas a Nemotron en el benchmark cuestan crédito: usa el planner `rules` para barridos y
  Nemotron solo en el subconjunto acordado con el usuario, vigilando `budget_report.py` de
  `ra-nemotron-token-factory`.

## Checklist

1. El usuario graba sesiones limpias (`s001…`) con el marcador ArUco visible; calcula sha256.
2. Crea un manifiesto por (sesión × fallo × intensidad) partiendo de
   `benchmarks/manifests/example-dark-001.yaml`; ≥ 3 intensidades por fallo MVP.
3. Genera los clips: `python -m benchmarks.make_degraded <manifest> <out.avi>`.
4. Ejecuta el agente sobre cada clip (`OpenCVSource` con ruta de archivo) y guarda el event store
   por ejecución.
5. Calcula por fallo: precisión/recall/F1, falsas alarmas/hora, tiempo de detección y de
   recuperación, % acciones confirmadas, % rollbacks correctos, delta de tarea antes/después,
   llamadas y USD por incidente, % respuestas válidas.
6. Compara con los mínimos de la tabla F10 de `docs/phases-and-gates.md` (macro F1 ≥ 0.85,
   ≤ 1 falsa alarma/h, recuperación ≥ 85 %, rollback 100 %, ≥ 98 % respuestas válidas).
   Métrica principal: % de incidentes con la capacidad downstream recuperada sin intervención
   humana y sin regresión.
7. Ablaciones F10: solo detector local · detector + Nemotron sin acciones · bucle completo · sin
   métrica downstream · baseline única · caída de Token Factory · fallo de stream durante acción.
8. Escribe `benchmarks/reports/<fecha>-<nombre>.md` (la carpeta está en `.gitignore`: añádelo
   con `git add -f`) con tabla generada desde los event stores, nunca tecleada a mano, commit del código exacto
   (`git rev-parse HEAD`), manifiestos usados y limitaciones; etiqueta SIMULATION vs REAL HARDWARE.

Hecho cuando otra persona puede regenerar la tabla con un comando desde los manifiestos y el
informe está commiteado con `Gate: F4` o `Gate: F10`. Evaluation ejecuta el benchmark de forma
independiente del autor del cambio evaluado.
