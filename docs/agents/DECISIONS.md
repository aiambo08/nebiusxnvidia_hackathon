# Decision log (short form)

| Date | Decision | Why | Who |
|---|---|---|---|
| 2026-10-04 | Physical AI track, camera reliability agent | Owner's career focus; zero hardware cost (webcam) | Aibo |
| 2026-10-04 | Apache-2.0 license | Hackathon requires OSI license; patent grant | Aibo |
| 2026-10-04 | Downstream task = ArUco reference marker detection | Free, deterministic, sensitive to blur/dark/occlusion; no training | Architecture |
| 2026-10-04 | Crété-Roffet blur metric implemented in-house (numpy/OpenCV) | Avoid scikit-image dependency; small, testable | Vision |
| 2026-10-04 | Text-only Nemotron with structured metrics | Catalog lists Nemotron 3 as text2text; cheaper | Nebius |
| 2026-10-05 | Disable Nemotron thinking (`chat_template_kwargs.enable_thinking=false`) | Default reasoning consumed all output tokens → 0/20 valid; off → 20/20 (ADR-002) | Nebius |
| 2026-10-05 | Demo runs on native Windows, laptop integrated webcam (RTX 4060 laptop); phone camera as second source over RTSP | Avoids WSL2 USB passthrough; phone stream exercises the RTSP path of F1 | Aibo |
| 2026-10-05 | Authorised: bounded, reversible pipeline action (gamma/gain before the downstream task) as fallback when the webcam exposes no UVC controls | Integrated webcams often lack exposure/focus control; needs ADR + `ra-safe-action` review before use | Aibo |
| 2026-10-05 | ArUco marker shown on the phone screen (fixed brightness, auto-brightness off) | No printer available | Aibo |
| 2026-10-05 | Gate adjustments accepted: F1 adds cost/latency bound; feature freeze 25 Oct to leave 26–28 Oct for video + Devpost | Analysis of the technical report | Aibo |
| 2026-10-04 | Verification must use the downstream task, not "blur went down" | Measured: ArUco detection on the synthetic scene fails at Gaussian k=9 but succeeds again at k=21–31 (non-monotonic), matching Wischow et al. | Vision |
