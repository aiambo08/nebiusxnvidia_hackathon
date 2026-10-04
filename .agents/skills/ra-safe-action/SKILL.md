---
name: ra-safe-action
description: "Añadir o modificar una acción de remediación del Reliability Agent (exposición, enfoque, reinicio, perfil, tickets) o un adaptador de dispositivo UVC/ONVIF, con allowlist, límites tipados, snapshot, rollback y tests adversariales. Úsala para 'añade una acción', 'controla la exposición real', 'nuevo adaptador de cámara'. No para cambiar prompts de Nemotron."
metadata:
  author: aiambo08
  version: '1.0'
---

# Acción segura nueva

El rol Safety tiene veto sobre cualquier acción o herramienta nueva. Clases de riesgo
(`docs/safety-model.md`): **auto** (ajustes de imagen reversibles), **human** (solo crea ticket),
**forbidden** (actuación física fuera de ajustes de imagen, firmware, cambios irreversibles).
Si la acción pedida es forbidden, no la implementes: explica por qué y propón un ticket.

## Checklist (en este orden)

1. **Contrato.** Añade el miembro a `ActionName` en `contracts/models.py` (requiere ADR corto en
   `docs/adr/`, el contrato es v1.0) y, si diagnostica algo nuevo, a `FaultType`.
2. **Policy gate.** Registra un `ActionSpec` en `policy/gate.py` con descripción para el modelo,
   `ParamSpec` tipados con rango cerrado o `choices`, `requires=(<capacidad>,)`, cooldown y
   clase de riesgo. Sin parámetros libres de tipo string sin `choices`.
3. **Executor.** Implementa la rama en `Executor._apply` de `actions/executor.py`: lee el estado
   con `device.get_settings()`, el snapshot se persiste **antes** de aplicar, aplica de forma
   idempotente, clampa a límites del dispositivo y devuelve el estado nuevo. Acciones `human`
   no tocan el dispositivo.
4. **Dispositivo.** Si es hardware real, implementa `get_settings`/`apply_settings` y
   `capabilities()` en `capture/sources.py` (o un adaptador nuevo). Una capacidad no soportada
   debe lanzar `NotImplementedError` → el incidente acaba en NEEDS_HUMAN, nunca en éxito falso.
   Descubre capacidades en tiempo de ejecución; no asumas que la webcam soporta exposición manual.
5. **Planner local.** Si aplica, añade la regla en `RuleBasedPlanner` (`nemotron/planner.py`)
   para que el modo offline también la use.
6. **Verificación.** Define qué métrica debe mejorar en `verification/verifier.py` o en la
   especificación de la acción; la tarea downstream (ArUco) manda sobre métricas de imagen.
7. **Tests obligatorios:**
   - unit: argumentos válidos aplican; fuera de rango, tipo erróneo, NaN/inf y claves extra se
     rechazan **antes** de tocar el dispositivo; aplicar dos veces no corrompe; rollback restaura
     exactamente el snapshot (`tests/unit/test_policy_actions_verifier.py`).
   - adversarial: amplía `tests/adversarial/test_policy_fuzz.py` (nombres inventados, cooldown,
     rate limit, acción no ofrecida para el incidente).
   - e2e: escenario en `demo.py` + caso en `tests/e2e/test_scenarios.py` con commit y otro con
     rollback.
8. **Docs.** Fila en la tabla de `docs/safety-model.md`, marca la casilla F7/F8 solo si sus tests
   existen, commit con `Gate: F7`.

Hecho cuando `python3 -m pytest -q` y `ruff check .` están en verde y `ra-demo all` sigue
terminando cada escenario en el estado esperado.

## Errores ya vistos

- Comparar latencias sin tolerancia absoluta hacía revertir cambios buenos: usa
  `verification.guard_abs_tolerance` para métricas de guarda nuevas.
- Un tras-cambio de exposición puede disparar falsos `lens_occlusion`/`fov_shift`: las probes de
  textura y geometría trabajan sobre imagen normalizada/ecualizada; mantenlo.
