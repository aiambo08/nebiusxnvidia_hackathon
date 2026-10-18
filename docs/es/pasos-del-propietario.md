# Pasos de entrega para Aibo (Windows PowerShell)

**Todas las acciones de esta guía son human-only.** No se han creado API keys, grabaciones, vídeo,
etiquetas de release ni envíos de Devpost por este agente. Sustituye los valores de ejemplo por los
reales; nunca pegues una clave.

## 1. Actualizar e instalar

**Human-only.** Desde la carpeta del repositorio, en PowerShell:

```powershell
git pull
if (-not (Test-Path .venv)) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev,api]"
pytest -q
```

Esperado: instalación editable sin errores y un resumen de pytest. Pega de vuelta el SHA de
`git rev-parse --short HEAD`, la versión de `python --version` y la última línea de pytest.
No compartas `.env`.

## 2. Grabaciones F4 REAL HARDWARE y benchmark

**Human-only:** conecta la webcam, elige escenas variadas y no incluyas personas salvo cuando
pruebes una oclusión planificada. Revisa `docs/evaluation.md` y el `--help` antes de grabar.
Usa un ID nuevo que no aparezca en `benchmarks/manifests/sessions.yaml`; no sobrescribas clips.

```powershell
$Session = "sNNN" # reemplaza por un ID único
python scripts/record_clip.py --uri 0 --seconds 330 --session $Session --split test --conditions "scene and lighting conditions"
python -m benchmarks.build_manifests
python -m benchmarks.make_degraded --all
python scripts/run_benchmark.py
```

Esperado: `record_clip` guarda un clip ignorado por Git y añade hash, frames, FPS, duración y
condiciones al índice; `build_manifests` escribe manifiestos F4; `make_degraded --all` regenera
degradaciones sintéticas verificando hashes; `run_benchmark` crea el informe Markdown/JSON y sale
con código cero solo si los gates que juzga pasan. Pega el ID de sesión, hashes de clips, ubicación
de informes y resumen del benchmark; no subas vídeos privados.

La ruta de prueba con archivo sintético y las opciones se validaron en este entorno antes de
publicar esta guía; úsala solo para comprobar la CLI, no como evidencia REAL HARDWARE.

## 3. Prueba de webcam en el dashboard

**Human-only.** Activa el entorno virtual y ejecuta:

```powershell
ra-demo dashboard --live --uri 0
```

Abre `http://127.0.0.1:8000/`. Esperado: fuente webcam y etiqueta REAL HARDWARE; sin API key,
el modo local debe explicarse y no debe aparentar una llamada live. Pega si la webcam abrió,
el modo mostrado y cualquier error (sin claves ni URI privados).

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

**Human-only.** Sigue `docs/demo-script.md`; confirma la etiqueta SIMULATION/REAL HARDWARE,
mantén la clave fuera de cámara, cierra notificaciones, usa silencio o audio autorizado y muestra
la entrada física real. Sube el vídeo como público a YouTube y pega la URL en
`docs/devpost.md` y la matriz de cumplimiento. No se afirma que exista hasta que lo hagas.

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
