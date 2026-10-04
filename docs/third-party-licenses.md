# Third-party inventory

No third-party source code is vendored. Runtime dependencies (installed from PyPI):

| Component | Use | License | Reviewed |
|---|---|---|---|
| numpy | arrays | BSD-3-Clause | 2026-10-04 |
| opencv-python-headless | capture, probes, ArUco task | Apache-2.0 (OpenCV ≥ 4.5) / MIT wrapper | 2026-10-04 |
| pydantic | contracts | MIT | 2026-10-04 |
| PyYAML | config | MIT | 2026-10-04 |
| openai (Python SDK) | OpenAI-compatible client for Token Factory | Apache-2.0 | 2026-10-04 |
| httpx | model listing | BSD-3-Clause | 2026-10-04 |
| fastapi / uvicorn (optional) | API | MIT / BSD-3-Clause | 2026-10-04 |
| pytest, pytest-cov, ruff (dev) | tests/lint | MIT | 2026-10-04 |

Models (used as a service, not redistributed): NVIDIA Nemotron 3 family — NVIDIA Open Model
License; check the license URL returned by the catalog for the exact model used.

Candidates **not yet incorporated** (check license before copying anything):
- MaikWischow/Camera-Condition-Monitoring — blur/noise estimators (paper arXiv:2112.05456)
- MaikWischow/Noise-Source-Estimation
- 0x524A/onvif-go — ONVIF client + virtual camera simulator
- bugrauluyurt/onvif-devices — Docker ONVIF/RTSP simulators
- MediaMTX — local RTSP server for tests
- WoodScape / Dirty WoodScape datasets — **do not redistribute**; download locally only
