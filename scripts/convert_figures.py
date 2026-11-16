"""Convert the paper's figures (overleaf repo) into web-sized images for the project page.

Usage:
    python3 scripts/convert_figures.py /path/to/overleaf_multi-session-sfm/figures

PDFs are rasterised with poppler's `pdftoppm`; every image is then trimmed of white
borders, resized to at most MAX_WIDTH px wide and saved to static/images/.
Photos/renders are saved as JPEG (small); line-art diagrams and plots as PNG (sharp).
Re-run whenever the paper figures change.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

OUT_DIR = Path(__file__).resolve().parents[1] / "static" / "images"
MAX_WIDTH = 1600
# smaller caps for figures shown in narrow columns
WIDTH_OVERRIDES = {"gps_sesoko.png": 800, "gps_eiffel.png": 800, "s01_warped.jpg": 800, "recon_sesoko.jpg": 1000}
PDF_DPI = 300

# output name -> source file in the overleaf figures folder
FIGURES = {
    # Hero + method
    "teaser.jpg": "teaser-300dpi-compressed.pdf",
    "pipeline.png": "pipeline_v2.pdf",
    # Datasets / the problem
    "gps_sesoko.png": "gps_trajectories_okinawa_meters-crop.pdf",
    "images_sesoko.jpg": "trajectory_images_sesoko-300dpi-compressed.pdf",
    "gps_eiffel.png": "gps_trajectories_eiffel_meters_161820-crop.pdf",
    "images_eiffel.jpg": "trajectory_images_eiffel-300dpi-compressed.pdf",
    # Our full joint reconstructions
    "recon_sesoko.jpg": "sskall-full_colored_cropped.pdf",
    "recon_eiffel.jpg": "effall-full_colored_cropped.pdf",
    # Baseline comparison on ssk-s01 (one image per method and row of the paper figure)
    "s01_query.jpg": "pair_01_8312297_to_8315088_query.png",
    "s01_warped.jpg": "warped_images_001_8312297_to_8315088.pdf",
    # Supporting plot
    "matching_time.png": "feature_matching_time.pdf",
}
# method key on the page -> (point cloud, reprojection overlay, footprints) file suffixes
METHODS = {
    "colmap": ("colmap", "colmap", "3d_colmap"),
    "mapanything": ("mapanything", "mapanything", "3d_mapanything"),
    "icp": ("icp", "colmap_icp", "3d_colmap_icp"),
    "bufferx": ("buffer", "colmap_buffer_x", "3d_colmap_buffer_x"),
    "ours": ("ours", "ours", "3d_ours"),
}
for key, (cloud, pair, footprint) in METHODS.items():
    FIGURES[f"s01_cloud_{key}.jpg"] = f"sskall-s01_{cloud}.png"
    FIGURES[f"s01_pair_{key}.jpg"] = f"pair_01_8312297_to_8315088_{pair}.png"
    FIGURES[f"s01_footprint_{key}.jpg"] = f"pair_01_8312297_to_8315088_{footprint}.png"



def load(src: Path) -> Image.Image:
    """Open a raster image, or rasterise the first page of a PDF."""
    if src.suffix.lower() != ".pdf":
        return Image.open(src).convert("RGB")
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "page"
        subprocess.run(["pdftoppm", "-png", "-r", str(PDF_DPI), "-singlefile", str(src), str(prefix)],
                       check=True)
        return Image.open(f"{prefix}.png").convert("RGB")


def trim_white(im: Image.Image, pad: int = 8) -> Image.Image:
    """Crop near-white borders (the paper PNGs have generous margins), keeping a small pad."""
    bg = Image.new("RGB", im.size, (255, 255, 255))
    # threshold the difference so JPEG-ish noise in the margins doesn't block the crop
    diff = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 12 else 0)
    box = diff.getbbox()
    if box is None:
        return im
    l, t, r, b = box
    return im.crop((max(l - pad, 0), max(t - pad, 0), min(r + pad, im.width), min(b + pad, im.height)))


def main(fig_dir: Path) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for out_name, src_name in FIGURES.items():
        im = trim_white(load(fig_dir / src_name))
        width = WIDTH_OVERRIDES.get(out_name, MAX_WIDTH)
        if im.width > width:
            im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
        out = OUT_DIR / out_name
        if out.suffix == ".jpg":
            im.save(out, quality=85, optimize=True, progressive=True)
        else:
            im.save(out, optimize=True)
        print(f"{src_name:60s} -> {out.name} {im.size} {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
