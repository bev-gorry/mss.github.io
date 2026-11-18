"""Export reconstructions as small web copies for the interactive point cloud viewers.

Usage:
    python3 scripts/export_pointclouds.py <VSLAMLAB_EVALUATION>/colored/sskall-s01      # baselines (ssk-s01)
    python3 scripts/export_pointclouds.py --full <run folder> <key>                     # Joint Reconstructions
        e.g. --full <VSLAMLAB_EVALUATION>/exp_ssk_full_joint_cs100/SESOKO/sskall-full sesoko
             --full <VSLAMLAB_EVALUATION>/exp_eff_full_ours/EIFFEL/effall-full eiffel

Full mode reads a run folder's colmap_00000/{points3D,images,cameras}.txt, which hold the original image colours,
and rgb_exp.csv (image -> session). It writes static/pointclouds/full_<key>.ply and full_<key>_cams.json in the
same formats as below.

Baselines mode:

Input (per method, made by multi-session-sfm/vis/color_subsets_all_methods.sh):
    <method>/model/points3D.txt   points, session-tinted colours and tracks (which images observe each point)
    <method>/model/images.txt     camera poses
    <method>/model/cameras.txt    intrinsics (frustum shape)
    */model/colmap_image_list_<session>.txt   image -> session (written for the joint runs)
Output in static/pointclouds/:
    s01_<key>.ply         binary PLY: float32 x y z, uchar red green blue (original image colour),
                          uchar session (0-2: seen by that session only, 3: several sessions, 255: unknown)
    s01_<key>_cams.json   per camera: session index and frustum (apex + 4 image corners), same frame

Original colours are recovered by inverting the session tint of the coloured models (colour = 0.6 * original +
0.4 * tint, the tint being the session colour of a point seen by one session, grey otherwise), which is exact up to
+-2 levels of rounding. The viewer applies its own (adjustable) session tint from the session code.

Each cloud is put in a normalised frame so the viewer can start from the same view for every method: centred,
rotated so the reef plane is horizontal (PCA) with the cameras above it, scaled to unit radius. The methods live in
different frames and scales (MapAnything is arbitrary), so each is normalised on its own. Needs only numpy.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

OUT_DIR = Path(__file__).resolve().parents[1] / "static" / "pointclouds"
MAX_POINTS = 150_000    # keeps every file <= ~2.4 MB; only MapAnything (2M points) is subsampled
FRUSTUM_DEPTH = 0.035   # frustum length in the normalised (unit radius) frame
FULL_MAX_POINTS = 400_000   # ~6 MB per full dataset
FULL_FRUSTUM_DEPTH = 0.006  # full surveys: thousands of cameras over a much larger area, so smaller frustums
PREFIX = "s01"
# page key -> folder name in the colored/ output
METHODS = {"ours": "ours", "colmap": "colmap", "icp": "icp", "bufferx": "buffer", "mapanything": "mapanything"}

# must match vis/color_pointcloud_sessions.py (sessions sorted by name: 1st blue, 2nd yellow, 3rd pink)
SESSION_COLOURS = np.array([[106, 178, 212], [243, 201, 9], [227, 119, 194]], dtype=np.float32)
GREY = np.array([127, 127, 127], dtype=np.float32)
ALPHA_TINT = 0.4
MULTIPLE, UNKNOWN = 3, 255   # session codes besides 0-2


def quat_to_R(qw, qx, qy, qz) -> np.ndarray:
    """COLMAP world-to-camera rotation from its quaternion."""
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ])


def session_of_images(src: Path) -> dict[str, int]:
    """Image file name -> session index, from the colmap_image_list_<session>.txt files of any joint run."""
    lists = sorted(src.glob("*/model/colmap_image_list_*.txt"))
    if not lists:
        sys.exit(f"no colmap_image_list_<session>.txt found under {src}/*/model/")
    sessions = sorted({p.stem.removeprefix("colmap_image_list_") for p in lists})
    of = {}
    for p in lists:
        s = sessions.index(p.stem.removeprefix("colmap_image_list_"))
        for line in open(p):
            if line.strip():
                of[Path(line.strip()).name] = s
    print(f"sessions: {', '.join(f'{i}={s}' for i, s in enumerate(sessions))}")
    return of


def read_cameras(model: Path) -> tuple[dict, dict]:
    """Return (camera id -> (w, h, fx, fy, cx, cy)) and (image id -> (R, t, camera id, name))."""
    intrinsics = {}
    for line in open(model / "cameras.txt"):
        if line.startswith("#") or not line.strip():
            continue
        t = line.split()
        w, h = float(t[2]), float(t[3])
        p = list(map(float, t[4:]))
        if t[1] in ("SIMPLE_PINHOLE", "SIMPLE_RADIAL", "RADIAL"):
            fx = fy = p[0]
            cx, cy = p[1], p[2]
        else:                                   # PINHOLE, OPENCV, ...: fx fy cx cy first
            fx, fy, cx, cy = p[:4]
        intrinsics[int(t[0])] = (w, h, fx, fy, cx, cy)
    images = {}
    with open(model / "images.txt") as f:
        lines = (l for l in f if not l.startswith("#"))
        pose_lines = [l for i, l in enumerate(lines) if i % 2 == 0]   # pose lines alternate with 2D-point lines
    for line in pose_lines:
        t = line.split()
        if len(t) < 10:
            continue
        R = quat_to_R(*map(float, t[1:5]))
        images[int(t[0])] = (R, np.array(list(map(float, t[5:8]))), int(t[8]), Path(t[9]).name)
    return intrinsics, images


def read_points(model: Path, image_session: dict[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points, their recovered original colours and session codes."""
    xyz, tinted, tints, codes = [], [], [], []
    for line in open(model / "points3D.txt"):
        if line.startswith("#") or not line.strip():
            continue
        t = line.split()
        xyz.append(t[1:4])
        tinted.append(t[4:7])
        seen = {image_session[int(i)] for i in t[8::2] if int(i) in image_session}
        tints.append(SESSION_COLOURS[next(iter(seen))] if len(seen) == 1 else GREY)
        codes.append(next(iter(seen)) if len(seen) == 1 else MULTIPLE if seen else UNKNOWN)
    xyz = np.array(xyz, dtype=np.float64)
    tinted = np.array(tinted, dtype=np.float32)
    # invert colour = uint8(0.6 * original + 0.4 * tint); +0.5 undoes the truncation on average
    original = (tinted + 0.5 - ALPHA_TINT * np.array(tints)) / (1 - ALPHA_TINT)
    return xyz, np.clip(np.round(original), 0, 255).astype(np.uint8), np.array(codes, dtype=np.uint8)


def sessions_from_rgb_csv(run: Path) -> dict[str, int]:
    """Image file name -> session index, from the run's rgb_exp.csv (sessions sorted by name, as the paper colours)."""
    rows = list(csv.DictReader(open(run / "rgb_exp.csv")))
    sessions = sorted({r["sequence_name"] for r in rows})
    print(f"sessions: {', '.join(f'{i}={s}' for i, s in enumerate(sessions))}")
    return {Path(r["path_rgb_0"]).name: sessions.index(r["sequence_name"]) for r in rows}


def read_points_full(model: Path, image_session: dict[int, int]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Points, their stored (original) colours and session codes. Like read_points, without un-tinting."""
    xyz, rgb, codes = [], [], []
    for line in open(model / "points3D.txt"):
        if line.startswith("#") or not line.strip():
            continue
        t = line.split()
        xyz.append(t[1:4])
        rgb.append(t[4:7])
        seen = {image_session[int(i)] for i in t[8::2] if int(i) in image_session}
        codes.append(next(iter(seen)) if len(seen) == 1 else MULTIPLE if seen else UNKNOWN)
    return np.array(xyz, dtype=np.float64), np.array(rgb, dtype=np.uint8), np.array(codes, dtype=np.uint8)


def frustums(intrinsics: dict, images: dict) -> tuple[np.ndarray, np.ndarray]:
    """Per camera: centre (N, 3) and unit-depth directions to the 4 image corners (N, 4, 3), world frame."""
    centres, corners = [], []
    for R, t, cam_id, _ in images.values():
        w, h, fx, fy, cx, cy = intrinsics[cam_id]
        # image corners at depth 1 in camera coordinates (x right, y down, z forward)
        pix = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float64)
        cam = np.column_stack([(pix[:, 0] - cx) / fx, (pix[:, 1] - cy) / fy, np.ones(4)])
        centres.append(-R.T @ t)
        corners.append(cam @ R)                 # rows: R^T @ corner, camera -> world directions
    return np.array(centres), np.array(corners)


def normalise(xyz, centres, dirs):
    """Centre, rotate so the plane normal is +z with cameras above, scale to unit radius."""
    centre = np.median(xyz, axis=0)
    p = xyz - centre
    # PCA: eigenvectors sorted by variance; the smallest-variance axis is the reef plane's normal
    _, vecs = np.linalg.eigh(np.cov(p.T))
    R = vecs[:, ::-1].T                        # rows: largest, middle, smallest axis -> x, y, z
    if np.linalg.det(R) < 0:                   # keep a proper rotation (no mirroring)
        R[1] *= -1
    c = (centres - centre) @ R.T
    if len(c) and np.median(c[:, 2]) < 0:      # cameras look down at the reef: put them on +z
        R = np.diag([1.0, -1.0, -1.0]) @ R     # 180 deg about x, still a proper rotation
    p = p @ R.T
    c = (centres - centre) @ R.T
    d = dirs @ R.T                             # directions rotate but don't translate
    scale = np.linalg.norm(p, axis=1).max()    # whole cloud (outliers already dropped) inside the unit sphere
    return (p / scale).astype(np.float32), c / scale, d


def write_ply(path: Path, xyz: np.ndarray, rgb: np.ndarray, session: np.ndarray) -> None:
    header = (f"ply\nformat binary_little_endian 1.0\nelement vertex {len(xyz)}\n"
              "property float x\nproperty float y\nproperty float z\n"
              "property uchar red\nproperty uchar green\nproperty uchar blue\n"
              "property uchar session\nend_header\n")
    data = np.empty(len(xyz), dtype=[("x", "<f4"), ("y", "<f4"), ("z", "<f4"), ("r", "u1"), ("g", "u1"),
                                     ("b", "u1"), ("s", "u1")])
    data["x"], data["y"], data["z"] = xyz.T
    data["r"], data["g"], data["b"] = rgb.T
    data["s"] = session
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        data.tofile(f)


def export(name, xyz, rgb, session, intrinsics, images, image_session, rng, max_points, frustum_depth):
    """Clip, subsample, normalise and write <name>.ply and <name>_cams.json to OUT_DIR."""
    n_in = len(xyz)
    # drop stray points so they don't dominate the scale and the initial view
    lo, hi = np.percentile(xyz, 1, axis=0), np.percentile(xyz, 99, axis=0)
    keep = np.all((xyz >= lo) & (xyz <= hi), axis=1)
    xyz, rgb, session = xyz[keep], rgb[keep], session[keep]
    if len(xyz) > max_points:
        idx = rng.choice(len(xyz), max_points, replace=False)
        xyz, rgb, session = xyz[idx], rgb[idx], session[idx]

    centres, dirs = frustums(intrinsics, images)
    xyz, centres, dirs = normalise(xyz, centres, dirs)
    # the 4 image corners frustum_depth in front of each camera (dirs have unit depth along the optical axis,
    # so all frustums have the same depth)
    corners = centres[:, None, :] + frustum_depth * dirs
    cams = [{"s": image_session.get(i, -1),
             "f": np.round(np.vstack([c, k]), 4).ravel().tolist()}      # apex then 4 corners: 15 numbers
            for i, c, k in zip(images, centres, corners)]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ply = OUT_DIR / f"{name}.ply"
    write_ply(ply, xyz, rgb, session)
    (OUT_DIR / f"{name}_cams.json").write_text(json.dumps(cams, separators=(",", ":")))
    print(f"{name:16s} {n_in:>9,d} -> {len(xyz):>7,d} points, {len(cams):4d} cameras, "
          f"{ply.stat().st_size / 1e6:.1f} MB")


def main(src: Path) -> None:
    """Baselines: every method's coloured ssk-s01 model."""
    name_session = session_of_images(src)
    rng = np.random.default_rng(0)             # fixed seed: re-exports give identical files
    for key, folder in METHODS.items():
        model = src / folder / "model"
        intrinsics, images = read_cameras(model)
        image_session = {i: name_session[v[3]] for i, v in images.items() if v[3] in name_session}
        xyz, rgb, session = read_points(model, image_session)
        export(f"{PREFIX}_{key}", xyz, rgb, session, intrinsics, images, image_session, rng,
               MAX_POINTS, FRUSTUM_DEPTH)


def main_full(run: Path, key: str) -> None:
    """Joint Reconstructions: one full-dataset run (Ours)."""
    model = run / "colmap_00000"
    name_session = sessions_from_rgb_csv(run)
    intrinsics, images = read_cameras(model)
    image_session = {i: name_session[v[3]] for i, v in images.items() if v[3] in name_session}
    xyz, rgb, session = read_points_full(model, image_session)
    export(f"full_{key}", xyz, rgb, session, intrinsics, images, image_session, np.random.default_rng(0),
           FULL_MAX_POINTS, FULL_FRUSTUM_DEPTH)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--full":
        main_full(Path(sys.argv[2]), sys.argv[3])
    elif len(sys.argv) == 2:
        main(Path(sys.argv[1]))
    else:
        sys.exit(__doc__)
