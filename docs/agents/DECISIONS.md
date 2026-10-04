# Decision log (short form)

| Date | Decision | Why | Who |
|---|---|---|---|
| 2026-10-04 | Physical AI track, camera reliability agent | Owner's career focus; zero hardware cost (webcam) | Aibo |
| 2026-10-04 | Apache-2.0 license | Hackathon requires OSI license; patent grant | Aibo |
| 2026-10-04 | Downstream task = ArUco reference marker detection | Free, deterministic, sensitive to blur/dark/occlusion; no training | Architecture |
| 2026-10-04 | Crété-Roffet blur metric implemented in-house (numpy/OpenCV) | Avoid scikit-image dependency; small, testable | Vision |
| 2026-10-04 | Text-only Nemotron with structured metrics | Catalog lists Nemotron 3 as text2text; cheaper | Nebius |
