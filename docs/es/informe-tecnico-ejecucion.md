# Informe técnico de ejecución: agente autónomo de fiabilidad para Physical AI

## Resumen ejecutivo

El proyecto propuesto es un **agente autónomo de fiabilidad para cámaras y pipelines de percepción**. El sistema observa una webcam, cámara RTSP u origen ONVIF; mide la salud del transporte, la calidad visual y el rendimiento de una tarea downstream; detecta degradaciones; solicita a NVIDIA Nemotron un diagnóstico y un plan estructurado; valida el plan mediante políticas deterministas; ejecuta únicamente acciones reversibles; y conserva el cambio solo si una verificación posterior demuestra una mejora.

El producto no debe presentarse como otro monitor de CCTV. Ya existen soluciones comerciales que detectan desenfoque, obstrucción, iluminación deficiente, cambios de posición, indisponibilidad y deterioro de imagen. La diferenciación defendible es cerrar el ciclo **detección → diagnóstico causal → acción segura → verificación task-aware → rollback**, dirigido a sistemas Physical AI que dependen de una percepción fiable.[^1][^2][^3][^4]

La arquitectura seguirá el patrón MAPE-K: Monitor, Analyze, Plan y Execute sobre una base de conocimiento compartida. Este patrón separa el sistema gestionado del sistema de adaptación y se utiliza ampliamente en software autónomo y sistemas ciberfísicos. Nemotron participará en Analyze/Plan, pero no tendrá autoridad directa sobre la cámara: una policy gate determinista validará cada acción y el verificador decidirá si se confirma o revierte.[^5][^6][^7]

El desarrollo se divide en **doce fases con puertas de salida obligatorias**. Ninguna fase puede darse por terminada porque “la demo parece funcionar”: deberá producir evidencia reproducible, artefactos versionados y métricas que cumplan condiciones de aceptación. Los umbrales incluidos en este documento son objetivos internos iniciales; deberán recalibrarse con datos reales de la cámara y no interpretarse como valores científicos universales.

## Definición del producto

### Propuesta de valor

> Un supervisor abierto y autónomo para pipelines de visión que detecta cuándo una cámara deja de ser útil, diagnostica la causa con NVIDIA Nemotron, ejecuta correcciones limitadas y demuestra cuantitativamente si recuperó la capacidad de percepción.

### Usuario objetivo

- Ingenieros de robótica y visión desplegando cámaras en edge.
- Equipos de operaciones responsables de flotas de cámaras IP.
- Integradores de pipelines DeepStream, OpenCV, ROS 2 o aplicaciones industriales.
- Equipos de mantenimiento que necesitan convertir síntomas visuales en incidencias accionables.

### Trabajo principal

El sistema debe responder cinco preguntas:

1. ¿El stream está vivo y entrega frames nuevos?
2. ¿La imagen mantiene una calidad suficiente para la tarea?
3. ¿Qué causa explica mejor la degradación observada?
4. ¿Qué acción reversible y autorizada puede corregirla?
5. ¿La acción mejoró realmente el sistema o debe revertirse?

### Fuera de alcance

- Control libre de robots o actuadores peligrosos.
- Limpieza física automática de la lente.
- Entrenamiento de un foundation model.
- Gestión empresarial completa de miles de cámaras.
- Sustitución de un NVR como Frigate, Shinobi o Agent DVR.
- Envío continuo de vídeo a Token Factory.
- Ajustes irreversibles decididos por el LLM.

## Base científica

### Mantenimiento task-aware

El precedente académico más próximo es *Monitoring and Adapting the Physical State of a Camera for Autonomous Vehicles*. El trabajo propone un framework de automantenimiento, estima blur y ruido en tiempo real y reajusta parámetros de cámara atendiendo al rendimiento de una aplicación downstream. Su hallazgo operativo más importante es que la relación entre un parámetro de cámara, la calidad visual y el rendimiento de la tarea puede ser no lineal y no monótona; por ello, maximizar una única métrica de nitidez o luminosidad no garantiza mejorar la detección de objetos.[^8][^9]

El repositorio asociado ofrece una base de código para estudiar estimación de blur y ruido, y debe evaluarse antes de reimplementar esos componentes. Existe además un repositorio separado para estimar fuentes de ruido a partir de la imagen y los metadatos de cámara.[^10][^11][^12]

### Blur

La varianza del Laplaciano puede servir como indicador local barato, pero no como decisión definitiva. El sistema debe combinarla con densidad de bordes, comparación relativa contra el baseline y una métrica perceptual. CPBD modela la probabilidad perceptual de detectar blur en los bordes, mientras que Crété-Roffet estima cuánto cambia una imagen al volver a desenfocarla.[^13][^14][^15]

### Obstrucción y suciedad

La obstrucción parcial puede detectarse con métricas sencillas por región y selección de características basada en la separación entre distribuciones limpias y obstruidas. Para extensiones de aprendizaje, WoodScape ofrece cámaras fisheye y anotaciones de soiling, y TiledSoilingNet formula la contaminación por regiones para reducir complejidad. La partición de datos deberá hacerse por secuencia o sesión, no por frames aleatorios, porque se han señalado riesgos de fuga al distribuir imágenes consecutivas entre entrenamiento y prueba.[^16][^17][^18][^19]

### Freeze y loops

Una diferencia casi nula entre frames puede indicar congelación, pero también una escena genuinamente estática. La literatura recomienda una segunda etapa que distinga frames repetidos, imágenes estáticas transmitidas y escenas estáticas reales. El hashing temporal permite detectar frames repetidos y pequeños loops con menor coste que comparar cada píxel de ventanas largas.[^20][^21]

### Movimiento de cámara

El cambio de campo de visión debe estimarse mediante correspondencias geométricas y homografía robusta, no únicamente por diferencia global. Las correspondencias se degradan con iluminación, clima, estación, dirección solar, motion blur, obstrucción y cambios de viewpoint. En consecuencia, el sistema debe mantener referencias múltiples por cámara y modo operativo.[^22][^23]

### Arquitectura autónoma

MAPE-K divide un sistema adaptativo en Monitor, Analyze, Plan y Execute, todos apoyados en conocimiento compartido del sistema, su entorno, objetivos y políticas. En este proyecto:[^24][^25]

- **Monitor:** captura frames, telemetría y estado downstream.
- **Analyze:** fusiona señales y confirma incidentes.
- **Plan:** Nemotron propone diagnóstico, acción y verificación.
- **Execute:** el backend valida y ejecuta la acción.
- **Knowledge:** SQLite conserva baselines, capacidades, incidentes, planes, métricas y resultados.

## Arquitectura objetivo

```text
Webcam / archivo / RTSP / ONVIF
              │
              ▼
     Capture + Watchdog
              │
    ┌─────────┴──────────┐
    ▼                    ▼
Transport metrics     Visual probes
FPS, jitter, age,     blur, exposure,
drops, reconnects     freeze, occlusion,
                      FOV drift, noise
    └─────────┬──────────┘
              ▼
    Temporal fusion + FSM
              │
              ▼
     Structured incident
              │
              ▼
 NVIDIA Nemotron / Token Factory
 diagnosis + action proposal + test
              │
              ▼
       Deterministic policy gate
              │
              ▼
     Executor / reversible action
              │
              ▼
   Verification window + task score
         │                 │
      improve          no improve
         │                 │
       commit           rollback
         └────────┬────────┘
                  ▼
       Audit log + dashboard
```

### Principios no negociables

- La detección primaria funciona sin conexión a la nube.
- Nemotron se invoca solo tras confirmar un incidente.
- El LLM nunca ejecuta acciones directamente.
- Toda acción automática pertenece a una allowlist y tiene límites.
- Se captura el estado anterior antes de modificar configuración.
- Toda acción tiene criterio de éxito, timeout y rollback.
- El sistema conserva evidencia antes/después.
- El gasto tiene soft cap y hard cap.
- Una caída de Token Factory degrada el sistema a monitor local, no detiene la captura.

## Contratos de datos

### Telemetría por ventana

```json
{
  "camera_id": "assembly_cam_01",
  "window_start": "ISO-8601",
  "window_seconds": 5,
  "transport": {
    "capture_fps": 29.7,
    "frame_age_ms_p95": 74,
    "dropped_frames": 2,
    "reconnect_count": 0
  },
  "visual": {
    "brightness_p50": 108.2,
    "black_pixel_ratio": 0.01,
    "white_pixel_ratio": 0.02,
    "laplacian_variance_p50": 187.4,
    "blur_effect_p50": 0.18,
    "edge_density_p50": 0.21,
    "temporal_mse_p50": 14.2,
    "repeated_hash_ratio": 0.0
  },
  "geometry": {
    "match_count": 174,
    "homography_inlier_ratio": 0.81,
    "translation_px": 1.9,
    "rotation_deg": 0.2
  },
  "task": {
    "name": "reference_object_detection",
    "success_rate": 0.94,
    "confidence_p50": 0.86,
    "latency_ms_p95": 38
  }
}
```

### Incidente confirmado

```json
{
  "incident_id": "uuid",
  "camera_id": "assembly_cam_01",
  "state": "confirmed",
  "candidate_faults": ["focus_drift", "lens_occlusion"],
  "evidence": [],
  "baseline_ref": "baseline-version",
  "current_config": {},
  "capabilities": [],
  "allowed_actions": [],
  "budget_remaining_usd": 24.31
}
```

### Plan de Nemotron

```json
{
  "schema_version": "1.0",
  "diagnosis": "focus_drift",
  "confidence": 0.91,
  "evidence_refs": ["visual.blur_effect", "task.confidence_p50"],
  "alternatives": ["motion_blur"],
  "action": {
    "name": "trigger_autofocus",
    "arguments": {}
  },
  "verification": {
    "window_seconds": 15,
    "primary_metric": "task.success_rate",
    "minimum_relative_improvement": 0.10,
    "guard_metrics": ["transport.capture_fps", "task.latency_ms_p95"]
  },
  "human_message": "Probable pérdida de foco sin cambio geométrico."
}
```

### Resultado de acción

```json
{
  "incident_id": "uuid",
  "action": "trigger_autofocus",
  "previous_state": {},
  "execution_status": "success",
  "verification_status": "committed",
  "before": {},
  "after": {},
  "rollback_available": true,
  "token_usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost_usd": 0.0
  }
}
```

## Máquina de estados

| Estado | Entrada | Salida permitida | Restricción |
|---|---|---|---|
| `HEALTHY` | Métricas normales | `SUSPECT` | No invocar LLM |
| `SUSPECT` | Desviación inicial | `HEALTHY`, `CONFIRMED` | Exigir persistencia |
| `CONFIRMED` | Evidencia suficiente | `DIAGNOSING`, `SAFE_MODE` | Crear snapshot inmutable |
| `DIAGNOSING` | Incidente estructurado | `PLANNED`, `NEEDS_HUMAN` | JSON validado |
| `PLANNED` | Acción propuesta | `ACTING`, `REJECTED` | Policy gate obligatoria |
| `ACTING` | Plan aprobado | `VERIFYING`, `FAILED` | Guardar configuración anterior |
| `VERIFYING` | Acción completada | `RECOVERED`, `ROLLING_BACK` | Ventana de observación |
| `ROLLING_BACK` | Sin mejora/regresión | `ROLLED_BACK`, `NEEDS_HUMAN` | Rollback idempotente |
| `RECOVERED` | Gate superado | `HEALTHY` | Registrar evidencia |
| `NEEDS_HUMAN` | Sin acción segura | `HEALTHY`, `CLOSED` | No repetir llamadas sin cambios |

## Plan por fases

## Fase 0 — Cumplimiento y congelación de alcance

### Objetivo

Transformar las reglas de la hackathon y las restricciones económicas en requisitos verificables antes de escribir funcionalidad. La entrega debe usar en runtime Token Factory o Nebius AI Cloud y al menos un modelo abierto de NVIDIA, además de cumplir los artefactos públicos exigidos por la competición.[^26][^27]

### Trabajo

- Crear `docs/compliance-matrix.md`.
- Confirmar desde la cuenta el endpoint, modelo Nemotron disponible, modalidad, tool calling, formato estructurado y precios.
- Ejecutar una llamada mínima autenticada y registrar `model_id`, uso y coste.
- Fijar el coste máximo del proyecto: 30 USD promocionales y 0 USD adicionales.
- Congelar el MVP: una cámara, cinco fallos, tres acciones, una tarea downstream.
- Definir licencia compatible para el repositorio propio.
- Inventariar licencias de todo código o dataset externo antes de incorporarlo.

### Entregables

- Matriz requisito → implementación → evidencia.
- Prueba de llamada a Nemotron sin incluir secretos.
- Registro de arquitectura ADR-001.
- Presupuesto y política de corte.
- Lista explícita de funcionalidades fuera de alcance.

### Puerta F0

La fase pasa solo si:

- Existe una llamada runtime exitosa a un modelo NVIDIA accesible con las credenciales disponibles.
- El identificador se obtiene o verifica contra la API actual; no se asume desde documentación antigua.
- El coste estimado de una ejecución se registra.
- No hay ningún servicio de pago obligatorio.
- El MVP puede ejecutarse localmente con hardware ya disponible.
- Cada requisito oficial tiene una evidencia prevista.
- Las dependencias críticas tienen licencia revisada.

### Bloqueo

No avanzar si el modelo exigido no está disponible, los créditos no se aplican, una dependencia crítica impone pago, o el diseño necesita hardware que no se posee. En ese caso se cambia modelo, adaptador o alcance antes de continuar.

## Fase 1 — Spikes de viabilidad

### Objetivo

Eliminar tempranamente las incertidumbres que podrían invalidar el proyecto.

### Spikes

1. Capturar webcam durante 30 minutos sin bloqueo.
2. Leer un archivo y un stream RTSP local mediante la misma interfaz.
3. Calcular las métricas principales en tiempo real.
4. Inyectar freeze, blur y oscuridad de forma reproducible.
5. Enviar un incidente JSON a Nemotron y validar la respuesta.
6. Ejecutar una acción simulada y restaurar su estado anterior.
7. Medir el coste de 20 diagnósticos representativos.

### Entregables

- `spikes/capture-report.md`.
- Notebook o script de benchmark, no usado como producción.
- Primer esquema Pydantic.
- Primer simulador de fallos.
- Tabla de latencia y coste.

### Puerta F1

- Captura continua de 30 minutos sin crash ni crecimiento de memoria superior al 10% después del warm-up.
- Al menos 95% de los intervalos de un segundo producen telemetría válida.
- Blur, oscuridad y freeze son visibles y detectables en pruebas controladas.
- Al menos 19 de 20 respuestas de Nemotron cumplen el esquema tras un máximo de un reintento de reparación.
- La acción simulada puede aplicarse y revertirse dos veces de forma idempotente.
- El coste proyectado de 300 diagnósticos cabe dentro de 23 USD.

### Bloqueo

Si falla cualquiera de los tres caminos críticos —captura, respuesta estructurada o rollback— no se inicia el producto completo. Se simplifica la interfaz hasta conseguir una ruta vertical funcional.

## Fase 2 — Ingestión y observabilidad

### Objetivo

Construir una fuente fiable de frames y telemetría. Frigate demuestra la utilidad de exponer salud funcional, FPS y procesos watchdog, mientras que DeepStream mide rendimiento end-to-end incluyendo captura, decode, preprocesamiento, inferencia y postprocesamiento.[^28][^29][^30]

### Componentes

- `CameraSource` abstracta.
- Adaptadores `WebcamSource`, `FileSource` y `RTSPSource`.
- Ring buffer limitado.
- Watchdog de frame age.
- Reconexión con backoff y jitter.
- Métricas de FPS, frame age, dropped frames, decode errors y reconnects.
- Timestamps monotónicos separados del timestamp de origen.
- Health endpoint y exportación JSON.

### Puerta F2

- Webcam, archivo y RTSP local pasan la misma suite contractual.
- Una desconexión RTSP simulada se detecta en menos de 5 segundos.
- El adaptador intenta reconectar sin bloquear el proceso principal.
- Tras recuperar el stream, vuelve a producir telemetría en menos de 15 segundos.
- El ring buffer no crece sin límite.
- Los tests demuestran que un stream congelado puede seguir “conectado”; por tanto, transporte y contenido se informan por separado.
- Cobertura de tests del paquete de ingestión ≥ 80% en líneas y ≥ 75% en ramas.

### Condición de no avance

No se implementan detectores visuales sobre una captura inestable. Cualquier pérdida silenciosa de frames, timestamp ambiguo o reconexión bloqueante debe resolverse primero.

## Fase 3 — Monitores visuales

### Objetivo

Generar señales simples, explicables y suficientemente rápidas antes de utilizar modelos complejos.

### Detectores mínimos

- Oscuridad y blackout.
- Sobreexposición y clipping.
- Blur/focus degradation.
- Freeze y loop corto.
- Obstrucción total/parcial.
- Desplazamiento de campo de visión.

### Implementación

- Calcular métricas por frame, pero decidir sobre ventanas temporales.
- Analizar globalmente y en una cuadrícula de regiones.
- Normalizar contra baseline por cámara.
- Combinar Laplaciano, `blur_effect` y densidad de bordes.
- Combinar MSE temporal, hashes, timestamps y frame counter para freeze.
- Usar ORB/AKAZE, matching, RANSAC y homografía para desplazamiento.
- Mantener máscaras de regiones dinámicas.
- Separar detectores fotométricos y geométricos.

### Puerta F3

Sobre un conjunto inicial de al menos 10 ejecuciones por fallo:

- Recall ≥ 0.90 para blackout, freeze, blur fuerte y obstrucción fuerte.
- Precision ≥ 0.85 por detector.
- Cero falsos positivos de freeze en una escena estática de 20 minutos con captura correcta.
- Cero falsos positivos de cámara movida durante el paso de una persona en al menos 20 ensayos.
- Latencia p95 del conjunto de probes ≤ 40 ms por frame a 720p cuando se muestrea a 5 FPS analíticos.
- Cada detector devuelve puntuación, evidencia, calidad de la medición y motivo de `unknown`.
- Los umbrales están en configuración, no codificados en lógica.

### Bloqueo

Un detector que no cumple precisión mínima no puede disparar acciones. Puede mantenerse como señal experimental, pero debe etiquetarse y excluirse del camino automático.

## Fase 4 — Dataset y benchmark reproducible

### Objetivo

Sustituir impresiones visuales por evidencia repetible.

### Dataset interno

Cada escenario debe guardar:

- Fuente y configuración.
- Estado limpio previo.
- Tipo, intensidad, inicio y final del fallo.
- Acción correcta o `needs_human`.
- Frames de evidencia permitidos.
- Telemetría completa.
- Score downstream.
- Semilla de transformación cuando corresponda.

### Inyección de fallos

- Gaussian blur progresivo.
- Motion blur horizontal y vertical.
- Oscuridad y sobreexposición.
- Obstrucción opaca y semitransparente.
- Frame freeze.
- Loop de 4 y 8 frames.
- Caída de FPS.
- Delay y jitter.
- Desconexión RTSP.
- Rotación y traslación.
- Cambio legítimo de iluminación.
- Escena estática.

### Métricas

- Precision, recall, F1 por fallo.
- Falsas alarmas por hora.
- Tiempo de detección.
- Calidad de calibración de confianza.
- Cobertura de tipos de fallo.
- Coste computacional.

### Puerta F4

- Al menos 15 ejecuciones independientes por cada uno de los cinco fallos del MVP.
- Al menos 30 minutos de condiciones normales variadas.
- División por sesión, nunca por frames aleatorios consecutivos.
- Dataset versionado mediante manifiestos y hashes.
- Un comando reconstruye todas las degradaciones sintéticas.
- Un comando produce un informe de benchmark.
- F1 macro ≥ 0.85 para los cinco fallos del MVP.
- Falsas alarmas ≤ 1 por hora en condiciones normales del banco de pruebas.
- Ninguna métrica publicada proviene de datos de entrenamiento reutilizados como prueba.

### Bloqueo

No avanzar al razonamiento con LLM si todavía no existe un detector local defendible. El LLM no debe utilizarse para ocultar señales deficientes.

## Fase 5 — Baseline adaptativo y fusión temporal

### Objetivo

Convertir métricas ruidosas en incidentes estables.

### Diseño

- Baselines por cámara, resolución y modo de iluminación.
- Mediana y MAD para escalado robusto.
- Ventanas deslizantes.
- Histéresis entre entrada y salida de incidente.
- Persistencia mínima por tipo de fallo.
- Cooldown después de una acción.
- Estado `UNKNOWN` cuando la medición no es fiable.
- Baseline congelado durante incidentes para evitar aprender el fallo como normalidad.

Una puntuación robusta inicial puede definirse como:

\[
z_t = \frac{|x_t - \operatorname{median}(X)|}{1.4826\operatorname{MAD}(X)+\epsilon}
\]

### Puerta F5

- La calibración se completa automáticamente con datos limpios y produce una versión de baseline.
- El baseline no se actualiza durante `SUSPECT`, `CONFIRMED`, `ACTING` o `VERIFYING`.
- Tras reinicio, estado y baseline se recuperan desde persistencia.
- Dos ejecuciones con los mismos eventos producen la misma secuencia de estados.
- La histéresis reduce al menos 50% los cambios repetidos de estado respecto al detector frame a frame.
- Los cinco fallos alcanzan `CONFIRMED`; los cambios legítimos incluidos en el benchmark regresan a `HEALTHY` sin invocar Nemotron.

### Bloqueo

Si el estado oscila o el baseline se contamina, se detiene la integración de acciones. Un actuador conectado a un detector inestable multiplicaría los fallos.

## Fase 6 — Integración Nemotron

### Objetivo

Añadir diagnóstico causal y planificación mediante un modelo NVIDIA alojado en Nebius Token Factory. Token Factory expone una API compatible con OpenAI; el patrón de tool calling consiste en que el modelo propone una herramienta y el cliente ejecuta la función.[^31][^32][^33]

### Responsabilidad del modelo

- Ordenar hipótesis causales.
- Relacionar señales visuales, transporte y tarea.
- Elegir entre acciones explícitamente disponibles.
- Definir una prueba de verificación.
- Explicar la decisión con referencias a campos del incidente.

### Prohibiciones

- No inventar herramientas.
- No modificar argumentos fuera de los rangos anunciados.
- No ejecutar código.
- No recibir secretos.
- No recibir vídeo completo.
- No ser la única fuente de detección.

### Controles

- JSON Schema estricto.
- Temperatura baja.
- Timeout.
- Máximo de un retry de reparación de formato.
- Cache por firma de incidente.
- Circuit breaker.
- Registro de modelo, prompt version, tokens, latencia y coste.
- Respuesta local `needs_human` si falla la nube.

Nemotron 3 Super se presenta como un modelo disponible en Token Factory para razonamiento y tool calling, pero la disponibilidad real, el identificador, las modalidades y el precio deben comprobarse desde la cuenta antes de congelar la implementación.[^34]

### Suite de evaluación

- 20 casos por tipo de fallo.
- Casos ambiguos blur vs motion blur.
- Oscuridad vs lente cubierta.
- Escena estática vs freeze.
- Saturación de pipeline vs cámara lenta.
- Prompt injection dentro de metadatos de cámara.
- Herramienta inexistente.
- Argumento fuera de rango.
- Falta de evidencia.
- Token Factory sin respuesta.

### Puerta F6

- ≥ 98% de respuestas válidas según el esquema después de un máximo de un retry.
- ≥ 90% de elección correcta entre las acciones permitidas en el conjunto dorado.
- 100% de acciones inventadas o argumentos fuera de rango rechazados por la policy gate.
- 0 ejecuciones directas desde texto libre.
- Timeout de nube no bloquea captura ni monitorización.
- La misma versión de prompt y modelo queda registrada en cada decisión.
- Coste medio medido compatible con el presupuesto total.
- El modo offline produce una escalación segura y útil.

### Bloqueo

Si la validez estructural o la selección de acciones no alcanzan el gate, Nemotron se limita a explicación y clasificación; la planificación automática permanece desactivada.

## Fase 7 — Executor y seguridad

### Objetivo

Ejecutar solo acciones de bajo riesgo, reversibles y observables.

### Acciones MVP

1. `restart_capture`.
2. `switch_stream_profile`.
3. `set_exposure_bounded` o `trigger_autofocus` si el dispositivo lo soporta.
4. `enter_safe_mode` como acción lógica.
5. `request_manual_cleaning` sin actuación física.

ONVIF permite exponer controles de imaging como exposición, foco, brillo y contraste cuando la cámara los soporta; las capacidades deben consultarse antes de habilitar herramientas. Los simuladores ONVIF/RTSP permiten probar estos caminos sin comprar una cámara adicional.[^35][^36][^37]

### Policy gate

Cada acción declara:

- Dispositivos compatibles.
- Preconditions.
- Rangos de argumentos.
- Rate limit.
- Cooldown.
- Estado previo que debe capturarse.
- Timeout.
- Criterio de éxito técnico.
- Función de rollback.
- Riesgo y autorización requerida.

### Puerta F7

- Cada acción tiene tests unitarios de validación y rollback.
- Los argumentos inválidos se rechazan antes de tocar el dispositivo.
- El estado anterior se persiste antes de ejecutar.
- Dos ejecuciones repetidas no producen corrupción.
- Una caída durante la acción permite recuperar o revertir en el siguiente inicio.
- Ninguna acción física de riesgo está disponible.
- 100 pruebas adversariales no consiguen saltarse allowlist, rangos o cooldown.
- Las acciones no soportadas terminan en `NEEDS_HUMAN`, no en una falsa confirmación.

### Bloqueo

No se conecta el executor al flujo automático mientras exista una acción sin rollback o sin prueba de idempotencia.

## Fase 8 — Verificación y rollback

### Objetivo

Demostrar que una intervención recuperó el servicio y no optimizó una métrica secundaria a costa de la tarea principal.

### Criterios

Cada plan define:

- Ventana de observación.
- Métrica primaria downstream.
- Métricas visuales de apoyo.
- Guardrails de FPS, latencia y estabilidad.
- Mejora mínima.
- Regresión máxima permitida.
- Timeout.

La promoción o rollback guiados por métricas constituyen un patrón habitual de cambios seguros: solo se mantiene una modificación cuando supera health gates observables; de lo contrario se revierte.[^38]

### Regla inicial de commit

Una acción se confirma si:

- La métrica primaria mejora al menos 10% relativo o vuelve al 95% de su baseline.
- Ningún guard metric empeora más de 10%.
- El incidente deja de estar confirmado durante dos ventanas consecutivas.
- No aparece un nuevo incidente de severidad igual o superior.

Estos porcentajes son parámetros iniciales del proyecto y deben calibrarse con el benchmark.

### Puerta F8

- Cada acción del MVP tiene una prueba completa de commit y otra de rollback.
- ≥ 85% de incidentes recuperables se resuelven sin intervención humana en el banco de pruebas.
- 100% de acciones que generan una regresión deliberada terminan en rollback o safe mode.
- El rollback restaura exactamente la configuración versionada anterior.
- El sistema distingue fallo de ejecución de ausencia de mejora.
- Se conserva un informe antes/después con métricas y evidencia.
- Reiniciar la aplicación durante `VERIFYING` no pierde la decisión pendiente.

### Bloqueo

Sin una métrica downstream fiable, el sistema solo puede recomendar acciones; no debe proclamarse “self-healing”.

## Fase 9 — Producto y experiencia de demo

### Objetivo

Hacer comprensible el ciclo autónomo en menos de tres minutos.

### Pantallas

- Estado en vivo de cámara y tarea.
- Métricas esenciales, no un panel saturado.
- Timeline de estados.
- Diagnóstico y evidencia de Nemotron.
- Acción propuesta, policy decision y ejecución.
- Comparación antes/después.
- Estado de commit o rollback.
- Tokens y coste acumulado.

### Puerta F9

Cinco usuarios técnicos que no hayan desarrollado el proyecto deben poder responder tras ver la demo:

- Qué falló.
- Cómo se detectó.
- Qué decidió Nemotron.
- Qué acción se ejecutó.
- Cómo se comprobó la mejora.
- Qué ocurriría si la acción empeorase el sistema.

Además:

- El flujo principal se completa en ≤ 90 segundos.
- Ninguna interacción manual es necesaria entre confirmación y verificación.
- La UI muestra claramente simulación frente a hardware real.
- Ningún secreto aparece en pantalla, logs o vídeo.
- Existe modo demo determinista con una fuente grabada, además de la webcam real.

## Fase 10 — Validación integral

### Objetivo

Medir el producto completo y comparar sus componentes.

### Experimentos

- Detector local sin LLM.
- Detector + Nemotron sin acciones.
- Ciclo completo con policy gate y rollback.
- Ablación sin métrica downstream.
- Ablación con un único baseline.
- Fallo de Token Factory.
- Fallo de RTSP durante una acción.
- Reinicio del proceso en cada estado.
- Prueba de 4 horas.

### Métricas finales

| Categoría | Métrica mínima |
|---|---:|
| Detección | F1 macro ≥ 0.85 |
| Operación normal | ≤ 1 falsa alarma/hora |
| Diagnóstico | ≥ 90% acción correcta en conjunto dorado |
| Seguridad | 100% acciones inválidas rechazadas |
| Recuperación | ≥ 85% de fallos recuperables |
| Rollback | 100% de regresiones inyectadas revertidas |
| Robustez | 4 horas sin crash ni fuga sostenida |
| Estructura LLM | ≥ 98% respuestas válidas |
| Presupuesto | gasto acumulado de desarrollo ≤ 23 USD antes de demo |
| Reproducibilidad | instalación limpia y demo con un comando documentado |

### Puerta F10

Todos los mínimos deben cumplirse o documentarse como limitación explícita. Los resultados deben generarse desde archivos de eventos y no introducirse manualmente en el README. Cualquier métrica inferior al objetivo obliga a reducir el alcance o desactivar la correspondiente automatización.

## Fase 11 — Hardening y seguridad

### Objetivo

Eliminar fallos de entrega, secretos y estados peligrosos.

### Checklist

- Secret scanning.
- Dependencias fijadas y SBOM opcional.
- `.env.example` sin credenciales.
- Logs estructurados con redacción.
- Rate limit de Token Factory.
- Soft cap de 23 USD, demo cap de 25 USD y hard cap de 27 USD.
- El saldo restante queda como margen y no se consume automáticamente.
- Manejo de 401, 429, 5xx y timeout.
- Backups de configuración.
- Revisión de licencias.
- Instalación desde cero.
- Pruebas en Windows/Linux según el entorno final.

### Puerta F11

- Un escáner no encuentra secretos.
- Sin API key, el producto inicia en modo local y explica la limitación.
- Al superar el soft cap, las llamadas no esenciales se desactivan.
- Al superar el hard cap lógico, ninguna llamada sale del cliente.
- Todas las dependencias utilizadas tienen licencia documentada.
- Un agente distinto al autor instala y ejecuta el proyecto siguiendo solo el README.
- El repositorio público no contiene vídeos privados, credenciales ni datasets redistribuidos ilegalmente.

## Fase 12 — Entrega

### Objetivo

Convertir el sistema validado en una candidatura verificable.

### Artefactos

- Repositorio público.
- README con problema, arquitectura, instalación, ejecución y limitaciones.
- Licencia.
- Diagrama del ciclo MAPE-K.
- Evidencia explícita de uso runtime de Nemotron/Token Factory.
- Tabla de experimentos.
- Vídeo público dentro del límite.
- Formulario de Devpost.
- Etiquetado de componentes previos y nuevos.

### Guion del vídeo

- 0:00–0:20 — Problema y usuario.
- 0:20–0:40 — Cámara y pipeline saludables.
- 0:40–1:05 — Fallo físico real.
- 1:05–1:30 — Señales y diagnóstico Nemotron.
- 1:30–1:55 — Policy gate y acción.
- 1:55–2:20 — Verificación y commit/rollback.
- 2:20–2:40 — Arquitectura, NVIDIA y Nebius.
- 2:40–2:55 — Resultados y coste.

### Puerta F12

- Un revisor nuevo reproduce el camino feliz.
- El vídeo demuestra hardware o entrada física real durante el tiempo exigido.
- La llamada runtime puede señalarse en código, logs y vídeo.
- Los enlaces funcionan en modo incógnito.
- El commit final está etiquetado y coincide con la demo.
- La matriz de cumplimiento no contiene celdas sin evidencia.
- La entrega se realiza con margen operativo, no en los últimos minutos.

## Plan temporal

| Semana | Fases | Resultado obligatorio |
|---|---|---|
| 1 | F0–F2 | Reglas verificadas, spike vertical e ingestión estable |
| 2 | F3–F5 | Detectores, dataset, benchmark y máquina de estados |
| 3 | F6–F8 | Nemotron, policy gate, acciones, verificación y rollback |
| 4 | F9–F12 | UI, validación, hardening, vídeo y entrega |

### Hitos de contingencia

- **Final del día 3:** llamada Nemotron + cámara + respuesta JSON.
- **Final del día 7:** captura estable e inyección de fallos.
- **Final del día 14:** monitor local defendible; si no, reducir de cinco a tres fallos.
- **Final del día 20:** un ciclo completo real; si no, convertir acciones no fiables en recomendaciones.
- **Final del día 25:** feature freeze.
- **Días restantes:** pruebas, documentación y vídeo.

## Organización multiagente

### Agentes

| Agente | Responsabilidad | No debe modificar |
|---|---|---|
| Arquitectura | Contratos, ADR y FSM | Implementaciones de probes |
| Ingestión | Fuentes, watchdog y RTSP | Prompts |
| Visión | Métricas y detectores | Executor |
| Evaluación | Dataset, inyección y benchmark | Umbrales de producción sin evidencia |
| Nebius | Cliente, esquemas, prompts y coste | Acciones físicas |
| Safety | Policy gate, rollback y adversarial tests | UI |
| Producto | Dashboard, README y vídeo | Lógica crítica |
| Integrador | Merge, CI y release | Nuevas features después del freeze |

### Protocolo

1. El arquitecto congela contratos.
2. Cada agente trabaja en rama y módulo propio.
3. Todo PR incluye tests y referencia al gate de fase.
4. Evaluación ejecuta benchmark independiente.
5. Safety revisa cualquier herramienta nueva.
6. El integrador no acepta cambios que reduzcan métricas sin ADR.
7. Un agente no puede declarar superado su propio gate sin evidencia generada por CI o benchmark.

### Regla de transición

Una fase pasa cuando existen simultáneamente:

- Código integrado.
- Tests verdes.
- Métricas por encima del umbral.
- Artefacto reproducible.
- Revisión de un agente distinto.
- Riesgos residuales documentados.

## Estructura del repositorio

```text
physical-ai-reliability/
├── apps/
│   ├── api/
│   └── dashboard/
├── src/
│   ├── capture/
│   ├── probes/
│   ├── baselines/
│   ├── incidents/
│   ├── nemotron/
│   ├── policy/
│   ├── actions/
│   ├── verification/
│   └── storage/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── adversarial/
│   └── e2e/
├── benchmarks/
│   ├── manifests/
│   ├── injectors/
│   └── reports/
├── configs/
├── docs/
│   ├── adr/
│   ├── compliance-matrix.md
│   ├── safety-model.md
│   └── evaluation.md
├── scripts/
├── .env.example
├── LICENSE
└── README.md
```

## Estrategia de costes

| Bolsa | Máximo | Uso |
|---|---:|---|
| Desarrollo | 12 USD | Prompts, errores y evaluación inicial |
| Evaluación | 7 USD | Conjunto dorado y pruebas adversariales |
| Ensayos de demo | 4 USD | Repeticiones controladas |
| Margen | 7 USD | Contingencias; no consumible por defecto |

### Controles

- Dos llamadas como máximo por incidente normal.
- Tercera llamada solo por discrepancia explícita.
- Caché por firma del incidente.
- JSON conciso, sin historial innecesario.
- No enviar vídeo continuo.
- Registro de tokens y coste estimado.
- Alertas al 50%, 70% y 80% del presupuesto.
- Corte lógico antes de agotar los créditos.

## Registro de riesgos

| Riesgo | Probabilidad | Impacto | Mitigación | Gate |
|---|---|---|---|---|
| Camera health parece poco novedoso | Alta | Alto | Posicionar ciclo self-healing task-aware | F0/F9 |
| Falsos positivos por iluminación | Alta | Alto | Baselines por modo y fusión temporal | F3–F5 |
| Escena estática clasificada como freeze | Media | Alto | Timestamps, hashes y ruido temporal | F3/F4 |
| Nemotron devuelve acción inválida | Media | Alto | JSON Schema y policy gate | F6/F7 |
| Acción empeora la tarea | Media | Alto | Verificación y rollback | F8 |
| Cámara no soporta controles | Alta | Medio | Capability discovery y simulador ONVIF | F1/F7 |
| Presupuesto agotado | Baja | Alto | Caps, cache y modo local | F6/F11 |
| Dependencia externa incompatible | Media | Medio | Auditoría de licencias | F0/F11 |
| Demo física poco estable | Media | Alto | Fuente grabada reproducible como backup | F9/F12 |
| Scope excesivo | Alta | Alto | Cinco fallos, tres acciones, una tarea | Todos |

## Criterio final de éxito

El proyecto puede considerarse funcional y competitivo solo si demuestra simultáneamente:

1. Una degradación física u operativa real.
2. Detección local reproducible.
3. Una llamada real a NVIDIA Nemotron en Token Factory.
4. Diagnóstico estructurado y explicable.
5. Acción limitada por políticas deterministas.
6. Verificación downstream antes/después.
7. Commit o rollback automático.
8. Evidencia auditable.
9. Coste dentro de los créditos disponibles.
10. Instalación reproducible desde un repositorio público.

Si solo se cumplen detección y alerta, el producto es un camera health monitor. Si también cumple diagnóstico, acción segura, verificación y rollback, se convierte en un **agente autónomo de fiabilidad para Physical AI**, que es la tesis técnica y competitiva que debe defender la candidatura.

---

## References

1. [Alta Video camera health monitoring](https://www.avigilon.com/support/alta-video-health-monitoring) - Monitor camera health remotely with Alta Video. Detect faults early, maintain image integrity & keep...

2. [Camera Health Monitoring System | 95% Uptime | Agrex AI](https://www.agrexai.com/cctv-monitoring/) - Monitor CCTV camera health in real-time with Agrex AI. Get instant alerts on offline cameras, blurry...

3. [AI Camera Health Monitoring | Omnilert](https://www.omnilert.com/solutions/ai-camera-health-monitoring) - Omnilert's industry leading AI Camera Health Monitoring proactively detects blurry images, obstructi...

4. [Visual Camera Health - Immix](https://www.immixprotect.com/visual-camera-health2/) - Explore Immix Visual Camera Health and ensure optimal camera performance for monitoring services and...

5. [LNCS 7475 - A Design Space for Self-Adaptive Systems](https://people.cs.umass.edu/~brun/pubs/pubs/Brun13SEfSAS.pdf)

6. [Analysis of MAPE-K Loop in Self-adaptive Systems for Cloud ...](https://research.vu.nl/ws/files/331403865/Analysis_of_MAPE-K_Loop_in_Self-adaptive_Systems_for_Cloud_IoT_and_CPS.pdf)

7. [Modeling and Analyzing MAPE-K Feedback Loops for Self ...](https://cs.unibg.it/scandurra/papers/seams2015_cameraReady.pdf)

8. [Monitoring and Adapting the Physical State of a Camera for Autonomous Vehicles](http://arxiv.org/abs/2112.05456) - Autonomous vehicles and robots require increasingly more robustness and reliability to meet the dema...

9. [Motivation AI-based Blur and Noise Estimation Automatic ...](https://elib.dlr.de/191569/1/Poster_MaikWischow_A%20camera%20self-health-maintenance%20system%20based%20on%20sensor%20artificial%20intelligence.pdf)

10. [MaikWischow/Camera-Condition-Monitoring: Code basis ...](https://github.com/MaikWischow/Camera-Condition-Monitoring) - This repository contains the source code of the paper Monitoring and Adapting the Physical State of ...

11. [Camera Condition Monitoring and Readjustmentby means of Noise and Blur](https://arxiv.org/pdf/2112.05456v1.pdf)

12. [Noise Source Estimation (AISY, 2024)](https://github.com/MaikWischow/Noise-Source-Estimation) - MaikWischow/Noise-Source-Estimation: This repository contains the source code of the paper Real-time...

13. [A no-reference image blur metric based on the cumulative ... - PubMed](https://pubmed.ncbi.nlm.nih.gov/21447451/) - This paper presents a no-reference image blur metric that is based on the study of human blur percep...

14. [The Blur Effect: Perception and Estimation with a New No-Reference Perceptual Blur Metric](https://hal.science/hal-00232709/document)

15. [CPBD - Image, Video, and Usability Lab](https://ivulab.asu.edu/software/cpbd/) - This work presents a perceptual-based no-reference objective image sharpness metric (CPBD metric) ba...

16. [Partial Camera Obstruction Detection Using Single](https://elib.dlr.de/194592/1/Partial_Camera_Obstruction_Detection_Using_Single_Value_Image_Metrics_and_Data_Augmentation.pdf)

17. [Soiling detection for Advanced Driver Assistance Systems](https://arxiv.org/html/2511.09740v1)

18. [TiledSoilingNet: Tile-level Soiling Detection on Automotive Surround-view Cameras Using Coverage Metric](https://ar5iv.labs.arxiv.org/html/2007.00801) - Automotive cameras, particularly surround-view cameras, tend to get soiled by mud, water, snow, etc....

19. [WoodScape: A multi-task, multi-camera fisheye dataset for autonomous driving](https://arxiv.org/abs/1905.01489v1) - Fisheye cameras are commonly employed for obtaining a large field of view in surveillance, augmented...

20. [Automatic error detection and switching of](https://ltu.diva-portal.org/smash/get/diva2:1229525/FULLTEXT01.pdf)

21. [Automatic Detection of Temporal Discontinuities in Digital ...](https://fenix.tecnico.ulisboa.pt/downloadFile/563345090414176/Resumo.pdf)

22. [Characterizing Feature Matching Performance Over Long Time Periods](https://apps.dtic.mil/sti/tr/pdf/AD1039794.pdf)

23. [Scene-Aware Feature Matching](https://arxiv.org/html/2308.09949v2)

24. [MAPE-K Based Guidelines for Designing Reactive and Proactive Self-adaptive Systems](https://research.vu.nl/ws/portalfiles/portal/365761384/MAPE-K_Based_Guidelines_for_Designing_Reactive_and_Proactive_Self-adaptive_Systems.pdf)

25. [6. Insights Derived From The...](https://arxiv.org/html/2103.04112v2)

26. [Nebius x NVIDIA Global AI Hackathon: Build the next frontier ...](https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works) - Build the next frontier of AI on open infrastructure

27. [Nebius Build Week Hackathon in partnership with NVIDIA](https://nebius.com/events/nebius-nvidia-ai-builders-hackathon) - Teams will use Nebius AI Cloud, Serverless, Token Factory, Tavily and NVIDIA technologies to build p...

28. [Performance — DeepStream documentation](https://docs.nvidia.com/metropolis/deepstream/9.0/text/DS_Performance.html) - The measured performance represents end-to-end performance of the entire video analytic application ...

29. [Frequently Asked Questions - Frigate Docs](https://docs.frigate.video/troubleshooting/faqs/) - Fatal Python error: Bus error

30. [MQTT | Frigate](https://docs.frigate.video/integrations/mqtt/) - These are the MQTT messages generated by Frigate. The default topic_prefix is frigate, but can be ch...

31. [Nebius OpenAI-compatible inference API - Swagger UI](https://api.tokenfactory.nebius.com/docs)

32. [Function Calling | Nebius - trybrowzer.com](https://trybrowzer.com/docs/nebius/tokenfactory-function-calling) - Build the loop where a Token Factory model decides which of your functions to call, you execute them...

33. [dev.nebius.com · token-factoryToken Factory: inference API for open models - dev.nebius.com](https://dev.nebius.com/token-factory) - Build and scale faster on the purpose-built AI cloud, engineered from silicon to API.

34. [NVIDIA Nemotron 3 Super now available on Nebius Token ...](https://nebius.com/blog/posts/nemotron3-super-now-available) - Token Factory enables teams to move from model access to production deployment without managing GPU ...

35. [github.com › 0x524A › onvif-goGitHub - 0x524a/onvif-go: Modern Go library for ONVIF IP camera...](https://github.com/0x524A/onvif-go/) - Modern Go library for ONVIF IP camera integration - Control surveillance cameras with PTZ, streaming...

36. [bugrauluyurt/onvif-devices: Docker-based virtual ...](https://github.com/bugrauluyurt/onvif-devices) - Docker-based virtual ONVIF camera simulator using macvlan networking. Creates discoverable IP camera...

37. [python-onvif-zeep](https://github.com/FalkTannhaeuser/python-onvif-zeep) - Get information from your camera. To configure your camera, there are two ways to pass parameters to...

38. [Change Management: Canary Release and Rollback Strategies](https://www.sre.wang/en/posts/sre-change-management-canary-release/) - An in-depth exploration of change management from an SRE perspective, covering canary release, blue-...

