---
name: ra-hackathon-submission
description: "Preparar la entrega del Reliability Agent al Nebius x NVIDIA Global AI Hackathon (Physical AI): reglas, matriz de cumplimiento, vídeo, texto de Devpost, tag final y pasos humanos. Úsala para 'prepara la entrega', 'revisa que cumplimos las reglas', 'guion del vídeo'. No para programar funcionalidades."
metadata:
  author: aiambo08
  version: '1.0'
---

# Entrega del hackathon

Plazo: **30 oct 2026, 10:00 PDT = 18:00 Europe/Madrid**; objetivo interno 29 oct. Fuentes
oficiales (vuelve a leerlas en cada revisión, pueden cambiar):
`https://nebiusglobalaihackathon.devpost.com/rules` y
`https://nebiusglobalaihackathon.devpost.com/updates/46204-here-s-how-judging-works`.
Jurado: viabilidad pass/fail y luego 1–5 en implementación técnica, diseño, impacto potencial y
calidad de la idea (mismo peso).

## Pasos solo humanos (nunca los simules ni digas que están hechos)

Crear/rotar la API key, grabar y subir el vídeo público a YouTube, rellenar y enviar Devpost,
aceptar términos. Prepara todo lo demás y pide al usuario el enlace como evidencia.

## Checklist

1. **Reglas.** Lee las fuentes oficiales y compáralas con `docs/compliance-matrix.md`; si una
   regla cambió, actualiza la fila. Una fila es `done` solo si su evidencia es algo que un juez
   puede abrir (URL, ruta de archivo, minuto del vídeo).
2. **Requisitos duros.** Llamada en tiempo de ejecución a Token Factory con un modelo NVIDIA
   abierto (visible en código, logs y vídeo); repo público con licencia Apache-2.0 arriba; README
   con instalación y ejecución; sección de cómo se usan NVIDIA y Nebius; feedback en
   `docs/feedback.md`; proyecto creado en el periodo de envío (historial git).
3. **Vídeo** (`docs/demo-script.md`): < 3:00, YouTube público, sin música con copyright, ≥ 1 min de
   hardware real (webcam: tapar lente, apagar luz, desenfocar, mover). Debe verse: ID de modelo,
   tokens y coste, plan JSON, decisión de la policy gate, verificación y commit/rollback, etiqueta
   SIMULATION vs REAL HARDWARE. Sin secretos en pantalla.
4. **Reproducibilidad.** En un entorno limpio: `pip install -e ".[dev,api]"`, `pytest`,
   `ra-demo all` siguiendo solo el README. Cualquier paso que falte se arregla en el README.
5. **Resultados.** Las cifras del README/Devpost salen de informes en `benchmarks/reports/` o
   event stores, nunca escritas a mano; incluye limitaciones honestas.
6. **Gasto.** Confirma con el usuario el saldo de la consola de Nebius; gasto ≤ 30 USD y nada más.
7. **Congelación.** Tras el día 25 solo arreglos. Tag final `git tag -a v1.0-submission` que
   coincida con lo mostrado en el vídeo; enlaces probados en incógnito.
8. **Texto Devpost** (en inglés), con esta estructura:

```
Inspiration · What it does · How we built it (NVIDIA Nemotron on Nebius Token Factory,
MAPE-K loop, policy gate, verification) · Challenges · Accomplishments · What we learned ·
What's next · Built with · Links (repo, video)
```

Hecho cuando todas las filas de la matriz tienen evidencia, F12 de `docs/phases-and-gates.md`
está revisada con `ra-phase-gate-review` y al usuario solo le quedan los pasos humanos, listados
con el material listo para cada uno.
