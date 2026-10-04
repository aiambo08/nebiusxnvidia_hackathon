---
name: ra-dev-session
description: "Protocolo de sesión de desarrollo para el repo Physical AI Reliability Agent (aiambo08/nebiusxnvidia_hackathon): arrancar, implementar, testear, commitear con Gate, push y handoff. Úsala al continuar, programar o arreglar algo en ese repo. No para revisar si una fase está aprobada (usa ra-phase-gate-review)."
metadata:
  author: aiambo08
  version: '1.0'
  perplexity:
    connectors:
      - id: github_mcp_direct
        reason: Push, estado de CI y metadatos del repositorio.
---

# Sesión de desarrollo — Reliability Agent

Repo: `https://github.com/aiambo08/nebiusxnvidia_hackathon` (público, rama `main`, Apache-2.0).
Habla con el usuario en español; código, docs, commits y UI del repo en **inglés**.

## Arranque (antes de tocar código)

1. Clona o actualiza en `/home/user/workspace/repo`; push/pull con la credencial `github`.
2. Lee `AGENTS.md`, `docs/agents/PROJECT_STATE.md`, `docs/agents/TASKS.md` y la sección de la
   fase activa en `docs/phases-and-gates.md`.
3. Configura identidad local si falta: `user.name aiambo08`,
   `user.email 189237800+aiambo08@users.noreply.github.com`.
4. Instala: `pip install -e ".[dev,api]"` y ejecuta `python3 -m pytest -q` para tener línea base.
   Hecho cuando sabes qué fase avanza la tarea y los tests de partida pasan.

## Reglas que cambian el comportamiento

- El LLM nunca ejecuta: toda acción pasa por `policy/gate.py` → `actions/executor.py`
  (snapshot, timeout, rollback). Para acciones nuevas usa la skill `ra-safe-action`.
- Umbrales, IDs de modelo y precios solo en `configs/default.yaml`; nunca en lógica.
- Nunca relajes un umbral ni un test para que pase. Si el umbral es incorrecto, ADR en
  `docs/adr/` + evidencia de benchmark.
- Gasto cero: sin servicios de pago ni endpoints dedicados. Las llamadas reales a Token Factory
  solo con `pytest -m live` o scripts `spike_*`, y avisando al usuario del coste.
- Nunca simules pasos humanos: crear la API key, subir el vídeo a YouTube, enviar en Devpost.
- Etiqueta todo resultado como SIMULATION o REAL HARDWARE.
- Respeta propiedad por rol (tabla en `AGENTS.md`); contratos (`contracts/models.py`) solo con ADR.

## Cierre (cada cambio)

1. `python3 -m ruff check .` (ruff en `~/.local/bin` si no está en PATH) y `python3 -m pytest -q`:
   ambos en verde. Un fallo de test que revele un bug real se arregla en el código, no en el test.
2. Commits pequeños, Conventional Commits, cuerpo con el porqué y última línea `Gate: F<n>`.
3. Actualiza `docs/agents/PROJECT_STATE.md`, `TASKS.md` y, si hubo decisión, `DECISIONS.md`.
4. `git push`, espera la CI (`gh run list --limit 1`, `gh run view <id>`) y corrige si falla.
   Hecho cuando la CI de `main` está en verde (tests ubuntu/windows × 3.11/3.12 + gitleaks).
5. Si otra persona o agente sigue, deja el bloque HANDOFF de `AGENTS.md`.

## Informe al usuario

Breve, en español: qué cambió (commits), qué está verificado por tests/CI y qué queda pendiente
o requiere acción humana. No digas que una fase está superada salvo con evidencia
(ver `ra-phase-gate-review`).
