# Research references (curated)

Full annotated list: `docs/es/informe-tecnico-ejecucion.md` → References.

| Topic | Reference | How we use it |
|---|---|---|
| Task-aware camera self-maintenance | Wischow et al., arXiv:2112.05456 · github.com/MaikWischow/Camera-Condition-Monitoring | Verify on the downstream task, not on image quality alone |
| Noise vs metadata | github.com/MaikWischow/Noise-Source-Estimation | Future: gain/exposure vs observed noise consistency |
| Perceptual blur | Crété-Roffet et al. 2007 (hal-00232709) | `probes/sharpness.py::blur_effect` |
| Blur (CPBD) | Narvekar & Karam 2011 (PubMed 21447451) | Phase-2 candidate |
| Partial obstruction | DLR elib 194592 | Per-cell single-value metrics |
| Soiling | TiledSoilingNet (arXiv:2007.00801), WoodScape (arXiv:1905.01489) | Tile-level occlusion; split by sequence |
| Freeze vs static | LTU diva2:1229525; IST temporal discontinuities | Bit-exact repeat + hash + timestamps |
| Feature matching drift | DTIC AD1039794; arXiv:2308.09949 | Multiple references per lighting mode |
| MAPE-K | Brun et al. (LNCS 7475); VU Amsterdam MAPE-K analyses | Architecture (ADR-001) |
| Token Factory API | docs.tokenfactory.nebius.com (quickstart, JSON mode) | Client + `response_format` |
