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

The `opencv-python-headless` wheel bundles FFmpeg (LGPL; see its
`LICENSE-3RD-PARTY.txt`), and NumPy bundles libgfortran (GPL with the runtime exception).
These notices apply if wheels are redistributed; this project does not redistribute wheels.

Models (used as a service, not redistributed): NVIDIA Nemotron 3 family — NVIDIA Open Model
License; check the license URL returned by the catalog for the exact model used.

Candidates **not yet incorporated** (check license before copying anything):
- MaikWischow/Camera-Condition-Monitoring — blur/noise estimators (paper arXiv:2112.05456)
- MaikWischow/Noise-Source-Estimation
- 0x524A/onvif-go — ONVIF client + virtual camera simulator
- bugrauluyurt/onvif-devices — Docker ONVIF/RTSP simulators
- MediaMTX — local RTSP server for tests
- WoodScape / Dirty WoodScape datasets — **do not redistribute**; download locally only

<!-- BEGIN GENERATED DEPENDENCY LICENSES -->
## Installed runtime and optional dependency distributions

Generated from `pyproject.toml` and installed distribution metadata. Transitive requirements are included; markers are resolved for Linux and win32.

Versions as resolved on the generating machine; --check compares names and licences.

| Name | Version | Licence | Homepage | Pulled in by |
|---|---|---|---|---|
| `annotated-doc` | 0.0.5 | MIT | https://github.com/fastapi/annotated-doc | api |
| `annotated-types` | 0.8.0 | MIT | https://github.com/annotated-types/annotated-types | api, runtime |
| `anyio` | 4.15.1 | MIT | https://anyio.readthedocs.io/en/latest/ | api, runtime |
| `certifi` | 2026.7.22 | MPL-2.0 | https://github.com/certifi/python-certifi | runtime |
| `click` | 8.5.0 | BSD-3-Clause | https://github.com/pallets/click/ | api |
| `colorama` | 0.4.6 | BSD License | https://github.com/tartley/colorama | dev |
| `coverage` | 7.16.2 | Apache-2.0 | https://github.com/coveragepy/coveragepy | dev |
| `fastapi` | 0.146.0 | MIT | https://github.com/fastapi/fastapi | api |
| `h11` | 0.16.0 | MIT | https://github.com/python-hyper/h11 | api, runtime |
| `httpcore` | 1.0.9 | BSD-3-Clause | https://www.encode.io/httpcore/ | runtime |
| `httpcore2` | 2.13.1 | BSD-3-Clause | https://github.com/pydantic/httpx2 | runtime |
| `httpx` | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx | runtime |
| `httpx2` | 2.13.1 | BSD-3-Clause | https://github.com/pydantic/httpx2 | runtime |
| `idna` | 3.20 | BSD-3-Clause | https://github.com/kjd/idna | api, runtime |
| `iniconfig` | 2.3.1 | MIT | https://github.com/pytest-dev/iniconfig | dev |
| `jiter` | 0.17.0 | MIT | https://github.com/pydantic/jiter/ | runtime |
| `numpy` | 2.4.6 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | https://numpy.org | runtime |
| `openai` | 3.35.1 | Apache-2.0 | https://github.com/openai/openai-python | runtime |
| `opencv-python-headless` | 5.0.0.93 | Apache 2.0 | https://github.com/opencv/opencv-python | runtime |
| `opentelemetry-api` | 1.45.1 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python/tree/main/opentelemetry-api | api |
| `packaging` | 26.3 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging | dev |
| `pluggy` | 1.7.0 | MIT | https://github.com/pytest-dev/pluggy | dev |
| `pydantic` | 2.14.1 | MIT | https://github.com/pydantic/pydantic | api, runtime |
| `pydantic_core` | 2.50.1 | MIT | https://github.com/pydantic/pydantic | api, runtime |
| `Pygments` | 2.21.0 | BSD-2-Clause | https://pygments.org | dev |
| `pytest` | 9.1.1 | MIT | https://docs.pytest.org/en/latest/ | dev |
| `pytest-cov` | 7.1.0 | MIT | https://github.com/pytest-dev/pytest-cov | dev |
| `PyYAML` | 6.0.3 | MIT | https://pyyaml.org/ | runtime |
| `ruff` | 0.17.1 | MIT | https://docs.astral.sh/ruff | dev |
| `sniffio` | 1.3.1 | MIT OR Apache-2.0 | https://github.com/python-trio/sniffio | runtime |
| `starlette` | 1.9.0 | BSD-3-Clause | https://github.com/Kludex/starlette | api |
| `truststore` | 0.10.5 | MIT | https://github.com/sethmlarson/truststore | runtime |
| `typing_extensions` | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions | api, runtime |
| `typing-inspection` | 0.4.4 | MIT | https://github.com/pydantic/typing-inspection | api, runtime |
| `uvicorn` | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ | api |

### Licence review flags

- `certifi` — `MPL-2.0` (copyleft)

### Manual licence overrides

- `colorama` — `BSD License`; source: `https://pypi.org/pypi/colorama/0.4.6/json`
<!-- END GENERATED DEPENDENCY LICENSES -->
