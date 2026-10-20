import importlib.util
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MEDIA_DIR = REPO_ROOT / "docs" / "media"
GALLERY_SCRIPT = REPO_ROOT / "scripts" / "render_fault_gallery.py"
IMAGE_SUFFIXES = {".gif", ".jpeg", ".jpg", ".png", ".webp"}


@pytest.fixture(scope="module")
def gallery_module():
    spec = importlib.util.spec_from_file_location("render_fault_gallery", GALLERY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_gallery_shape_dtype_and_determinism(gallery_module):
    first = gallery_module.render_gallery()
    second = gallery_module.render_gallery()

    assert gallery_module.TILE_W == 320
    assert gallery_module.GALLERY_COLS == 3
    assert gallery_module.TILE_PAD == 6
    assert len(gallery_module.TILES) == 6

    tile_height = gallery_module.TILE_W * 3 // 4
    rows = (len(gallery_module.TILES) + gallery_module.GALLERY_COLS - 1) // (
        gallery_module.GALLERY_COLS
    )
    expected_shape = (
        rows * (tile_height + 2 * gallery_module.TILE_PAD),
        gallery_module.GALLERY_COLS
        * (gallery_module.TILE_W + 2 * gallery_module.TILE_PAD),
        3,
    )
    assert first.shape == expected_shape
    assert first.dtype == np.uint8
    assert np.array_equal(first, second)


def test_dark_tile_is_darker_and_overexposure_is_brighter_than_healthy(gallery_module):
    healthy_args = next(tile for tile in gallery_module.TILES if tile[1] is None)
    dark_args = next(tile for tile in gallery_module.TILES if tile[1] == "dark")
    overexposure_args = next(
        tile for tile in gallery_module.TILES if tile[1] == "overexpose"
    )

    healthy = gallery_module.render_tile(*healthy_args)
    dark = gallery_module.render_tile(*dark_args)
    overexposure = gallery_module.render_tile(*overexposure_args)

    assert dark.mean() < healthy.mean() * 0.3
    assert overexposure.mean() > healthy.mean()


def test_gallery_cli_writes_a_readable_png(gallery_module, tmp_path):
    output = tmp_path / "fault-gallery.png"

    assert gallery_module.main(["--out", str(output)]) == 0
    assert output.is_file()
    decoded = gallery_module.cv2.imread(str(output))
    assert decoded is not None
    assert decoded.dtype == np.uint8
    assert decoded.shape == gallery_module.render_gallery().shape


def test_committed_gallery_matches_fresh_render(gallery_module):
    committed = cv2.imread(str(MEDIA_DIR / "fault-gallery.png"))
    assert committed is not None
    assert np.array_equal(committed, gallery_module.render_gallery())


def test_readme_media_images_are_labeled_simulation():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert re.search(r"^## See it \(SIMULATION\)$", readme, re.MULTILINE)
    references = re.findall(r"!\[([^\]]+)\]\((docs/media/[^)\s]+)\)", readme)
    assert references
    for alt_text, reference in references:
        assert "SIMULATION" in alt_text, reference


def test_readme_media_spend_and_speed_captions_are_current():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    provenance = (MEDIA_DIR / "README.md").read_text(encoding="utf-8")
    # N1: the spend covers the seven captured live calls, not the stale six.
    assert "$0.0008336" in readme
    assert "$0.0008336" in provenance
    assert "$0.00071" not in readme
    # N2: the GIFs play at real speed (500 ms frame delay), downscaled to 800x500;
    # the captions must not claim 2x.
    assert "800×500" in readme
    assert "800×500" in provenance
    assert "2×" not in readme and "2x" not in readme
    assert "2×" not in provenance and "2x" not in provenance


def test_readme_media_links_exist_and_all_assets_are_referenced():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    provenance = (MEDIA_DIR / "README.md").read_text(encoding="utf-8")
    references = re.findall(r"\]\((docs/media/[^)\s]+)\)", readme)

    assert references
    for reference in references:
        assert (REPO_ROOT / reference).is_file(), reference

    media_text = f"{readme}\n{provenance}"
    assets = [
        path
        for path in MEDIA_DIR.rglob("*")
        if path.is_file() and path.name != "README.md"
    ]
    assert assets
    for asset in assets:
        assert asset.name in media_text, f"unreferenced media asset: {asset.name}"


def test_readme_media_images_do_not_exceed_500_kib():
    images = [
        path
        for path in MEDIA_DIR.rglob("*")
        if path.is_file() and path.suffix.casefold() in IMAGE_SUFFIXES
    ]

    assert images
    for image in images:
        assert image.stat().st_size <= 500 * 1024, image
