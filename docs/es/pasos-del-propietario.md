# Pasos de entrega para Aibo (Windows PowerShell)

**Todas las acciones de esta guía son human-only.** No se han creado API keys, grabaciones, vídeo,
etiquetas de release ni envíos de Devpost por este agente. Sustituye los valores de ejemplo por los
reales; nunca pegues una clave.

## 1. Actualizar e instalar

**Human-only.** Desde la carpeta del repositorio, en PowerShell:

```powershell
git status --short
git pull --ff-only
if (-not (Test-Path .venv)) { py -3.11 -m venv .venv }
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -e ".[dev,api]"
pytest -q
git rev-parse --short HEAD
git status --short
```

Esperado: `git pull --ff-only` actualiza sin conflicto, la instalación editable termina sin error,
y pytest muestra su resumen real (`N passed`, más cualquier skip/xfail del commit). Si `git status`
muestra cambios antes del pull, para y pregunta; no los descartes. Pega de vuelta el SHA, la versión
de Python, la última línea de pytest y el estado final de Git. No compartas `.env`, su contenido ni
claves.

## 2. Prueba de archivo sintético y grabaciones F4 REAL HARDWARE

La primera parte es solo una prueba local del flujo de archivo; **no es evidencia F4 ni REAL
HARDWARE**. Genera un video artificial breve en la carpeta temporal y llama a `record_clip` sin
`--split`, así que no entra al índice F4:

```powershell
$env:F12_SYNTHETIC = Join-Path $env:TEMP "f12-synthetic-dry-run.avi"
@'
import os
import cv2
import numpy as np

path = os.environ["F12_SYNTHETIC"]
writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30.0, (160, 120))
if not writer.isOpened():
    raise SystemExit("MJPG writer unavailable")
for index in range(1200):
    frame = np.full((120, 160, 3), 48, dtype=np.uint8)
    x = index % 150
    cv2.rectangle(frame, (x, 30), (x + 10, 90), (200, 180, 40), -1)
    writer.write(frame)
writer.release()
print(path)
'@ | python -
python scripts/record_clip.py --uri $env:F12_SYNTHETIC --seconds 0.000001 --warmup 0.01 --session f12-synthetic-smoke
```

Esperado: JSON con `"uri_kind": "file"`, un valor `frames` mayor que cero y un archivo bajo
`benchmarks/data/`; no debe aparecer un mensaje `added ... to ...sessions.yaml`. No uses este clip
para degradaciones, métricas, formularios o claims de hardware. La comprobación realizada en Linux
terminó con código 0 y registró 1 frame sintético; no midió rendimiento F4.

**Human-only:** conecta la webcam, elige escenas variadas y no incluyas personas salvo cuando
pruebes una oclusión planificada. Revisa `docs/evaluation.md` y confirma los flags con
`python scripts/record_clip.py --help` y `python scripts/run_benchmark.py --help`. El protocolo
requiere un ID `dev` nuevo y al menos seis IDs `test` únicos, cada uno con 330 s. No uses IDs ya
presentes en `benchmarks/manifests/sessions.yaml`; no sobrescribas clips.

```powershell
$Conditions = "textured desk, daylight, nobody in frame"
$DevSession = "sNNN" # reemplaza por un ID dev nuevo
python scripts/record_clip.py --uri 0 --seconds 330 --session $DevSession --split dev --conditions $Conditions
$TestSession = "sMMM" # reemplaza por un ID test nuevo; repite con seis IDs únicos
python scripts/record_clip.py --uri 0 --seconds 330 --session $TestSession --split test --conditions $Conditions
python -m benchmarks.build_manifests
python -m benchmarks.make_degraded --all
python scripts/run_benchmark.py
```

Esperado: cada grabación real devuelve JSON con el ID, hash SHA-256, frames, FPS, resolución,
duración y `uri_kind: webcam`; con `--split` añade la sesión al índice. `build_manifests` escribe
los manifiestos F4; `make_degraded --all` regenera degradaciones sintéticas verificando hashes;
`run_benchmark` crea el informe Markdown/JSON y sale con código cero solo si los gates que juzga
pasan. Pega los IDs y hashes, las rutas de informes y el resumen del benchmark; no subas vídeos
privados.

La CLI acepta un archivo sintético para probar `record_clip` **sin** `--split`; el modo F4
`--split test` exige una cámara o un stream y rechaza archivos por diseño. No añadas un archivo
sintético al índice F4 ni lo presentes como evidencia REAL HARDWARE. Las opciones y el dry run
anterior se verificaron localmente; solo comprueban el flujo de archivo, no los gates F4 ni el
hardware.

## 3. Prueba de webcam en el dashboard

**Human-only.** Activa el entorno virtual y ejecuta:

```powershell
ra-demo dashboard --live --uri 0
```

Abre `http://127.0.0.1:8000/`. Esperado: fuente webcam y etiqueta REAL HARDWARE; sin API key,
el modo local debe explicarse y no debe aparentar una llamada live. Pega si la webcam abrió,
el modo mostrado y cualquier error (sin claves ni URI privados).

Para el vídeo, cubre el objetivo de la cámara durante una entrada física visible. Esperado: un
incidente confirmado, un plan visible y una decisión del gate limitada a
`enter_safe_mode` / `request_manual_cleaning` / `needs_human`, seguida de un ticket o safe mode.
El adapter real no implementa control UVC/ONVIF de exposición/foco; no afirmes que la webcam
confirma un commit de exposición ni de autofocus. Mantén el badge REAL HARDWARE visible durante
esta toma.

## 4. Prueba con cinco usuarios

**Human-only; no rellenes resultados antes de observarlos.** Invita a cinco usuarios técnicos que
no construyeron el proyecto. Pídeles observar el flujo y responder: qué falló, cómo se detectó,
qué decidió Nemotron, qué acción se ejecutó, cómo se verificó la mejora y qué ocurre si empeora.
El observador no explica la respuesta durante la prueba.

Formulario por participante:

| Campo | Respuesta |
|---|---|
| Código anónimo del participante | |
| ¿Identificó el fallo? | |
| ¿Entendió las señales de detección? | |
| ¿Explicó el plan y la decisión del gate? | |
| ¿Identificó la acción ejecutada? | |
| ¿Entendió la verificación y commit/rollback? | |
| ¿Entendió el fallback local? | |
| Confusión o comentario literal | |

Pega el formulario completado y el protocolo seguido, sin datos personales innecesarios.

## 5. Grabar y publicar el vídeo

**Human-only.** Cada segmento debe llevar la etiqueta SIMULATION o REAL HARDWARE y el badge del
dashboard debe permanecer visible.

**SIMULATION:** desde el entorno virtual, inicia los escenarios:

```powershell
ra-demo dashboard --scenario dark --planner nemotron
ra-demo dashboard --scenario bad_action
```

Esperado: `dark` muestra exposición acotada y COMMITTED; `bad_action` muestra ROLLED BACK. La
grabación debe captar al menos una llamada Nemotron live exitosa usando `NEBIUS_API_KEY` en `.env`.
No muestres la clave. Si Token Factory falla, di “local mode—Token Factory unavailable”; el
fallback local no sustituye la llamada live requerida.

**REAL HARDWARE:** graba la webcam del propietario durante al menos 60 segundos:

```powershell
ra-demo dashboard --live --uri 0
```

Cubre el objetivo con la mano visible; espera el incidente, muestra el plan y el gate, y después
el ticket de limpieza o safe mode. En hardware real no se debe mostrar ni afirmar commit/rollback
de exposición o foco: ese control está demostrado solo en SIMULATION.

Sigue el resto de `docs/demo-script.md`; cierra notificaciones, usa silencio o audio autorizado y
mantén la entrada física en cuadro. No se incluye una secuencia stream-down/restart: no hay una
prueba del recorrido combinado por el dashboard live. Sube el vídeo como público a YouTube y pega
la URL en `docs/devpost.md` y la matriz de cumplimiento. No se afirma que exista hasta que lo hagas.

## 6. Etiqueta final

**Human-only; solo después de comprobar que el vídeo corresponde exactamente al commit que se
publicará.** Anota y verifica el SHA:

```powershell
$DemoCommit = (git rev-parse HEAD).Trim()
git show --no-patch --oneline $DemoCommit
git tag -a v1.0-submission -m "Physical AI Reliability Agent submission"
git push origin v1.0-submission
```

No ejecutes estos comandos hasta que vídeo y commit coincidan. Pega el SHA y confirma que la
etiqueta remota apunta al mismo commit.

## 7. Formulario de Devpost

**Human-only.** Copia los campos desde `docs/devpost.md`: Inspiration, What it does, How we built
it, Challenges, Accomplishments, What we learned, What's next, Built with, Track = Physical AI,
Feedback y Links. Sustituye el marcador de YouTube únicamente después de publicar el vídeo. Revisa
que las cifras y limitaciones coincidan con la lista Sources.

## 8. Comprobación en incógnito

**Human-only.** Abre una ventana privada sin sesión iniciada y comprueba el repositorio público,
los informes enlazados y el vídeo público. Confirma que no se requiere acceso privado y que los
enlaces abren la evidencia correcta. Pega la lista de enlaces revisados y el resultado de cada uno.
