from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import pycolmap
import cv2


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def parse_crop(value: str | None) -> tuple[int, int, int, int] | None:
    if not value:
        return None
    parts = [int(part.strip()) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("--crop must be formatted as x,y,width,height")
    x, y, width, height = parts
    if width <= 0 or height <= 0:
        raise ValueError("crop width and height must be positive")
    return x, y, width, height


def copy_or_crop_image(source: Path, target: Path, crop: tuple[int, int, int, int] | None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if crop is None:
        shutil.copy2(source, target)
        return
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {source}")
    x, y, width, height = crop
    x = max(0, min(x, image.shape[1] - 1))
    y = max(0, min(y, image.shape[0] - 1))
    right = max(x + 1, min(x + width, image.shape[1]))
    bottom = max(y + 1, min(y + height, image.shape[0]))
    cropped = image[y:bottom, x:right]
    cv2.imwrite(str(target), cropped)


def prepare_images(
    dataset_dir: Path,
    work_dir: Path,
    camera_id: str,
    crop: tuple[int, int, int, int] | None,
) -> list[dict[str, Any]]:
    manifest = read_json(dataset_dir / "manifest.json")
    records = [record for record in manifest["records"] if record["camera_id"] == camera_id]
    if not records:
        raise ValueError(f"No records found for camera {camera_id!r}")

    images_dir = work_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    prepared = []
    for record in records:
        source = dataset_dir / record["image"]
        if not source.exists():
            source = Path(record["image"])
        target_name = f"{record['session_id']}.jpg"
        target = images_dir / target_name
        copy_or_crop_image(source, target, crop)
        prepared.append({**record, "colmap_image_name": target_name, "colmap_image": str(target), "crop": crop})
    return prepared


def reconstruction_summary(reconstructions: dict[int, pycolmap.Reconstruction]) -> dict[str, Any]:
    models = []
    for model_id, reconstruction in reconstructions.items():
        models.append(
            {
                "model_id": model_id,
                "num_reg_images": reconstruction.num_reg_images(),
                "num_images": reconstruction.num_images(),
                "num_points3D": reconstruction.num_points3D(),
                "num_observations": reconstruction.compute_num_observations(),
                "mean_track_length": reconstruction.compute_mean_track_length(),
                "mean_reprojection_error": reconstruction.compute_mean_reprojection_error(),
            }
        )
    models.sort(key=lambda item: (item["num_reg_images"], item["num_points3D"]), reverse=True)
    return {"model_count": len(models), "models": models}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a first-pass pycolmap sparse reconstruction.")
    parser.add_argument("--dataset-dir", default="datasets/object_test_001", type=Path)
    parser.add_argument("--camera-id", default="cam_k230")
    parser.add_argument("--output-dir", default="reconstruction/object_test_001_cam_k230", type=Path)
    parser.add_argument("--crop", help="Optional x,y,width,height crop before reconstruction.")
    parser.add_argument("--camera-mode", default="single", choices=("auto", "single", "per_image"))
    parser.add_argument("--matcher", default="exhaustive", choices=("exhaustive", "sequential"))
    parser.add_argument("--sequential-overlap", type=int, default=10)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    if output_dir.exists():
        if not args.overwrite:
            raise SystemExit(f"Output directory already exists: {output_dir}. Pass --overwrite to replace it.")
        # Constrain recursive deletion to the current workspace reconstruction folder.
        workspace = Path.cwd().resolve()
        if workspace not in output_dir.parents:
            raise SystemExit(f"Refusing to overwrite outside workspace: {output_dir}")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    crop = parse_crop(args.crop)
    prepared_records = prepare_images(args.dataset_dir, output_dir, args.camera_id, crop)
    database_path = output_dir / "database.db"
    sparse_dir = output_dir / "sparse"
    sparse_dir.mkdir(parents=True, exist_ok=True)

    camera_mode = {
        "auto": pycolmap.CameraMode.AUTO,
        "single": pycolmap.CameraMode.SINGLE,
        "per_image": pycolmap.CameraMode.PER_IMAGE,
    }[args.camera_mode]
    pycolmap.extract_features(database_path, output_dir / "images", camera_mode=camera_mode)
    if args.matcher == "sequential":
        pairing_options = pycolmap.SequentialPairingOptions()
        pairing_options.overlap = args.sequential_overlap
        pycolmap.match_sequential(database_path, pairing_options=pairing_options)
    else:
        pycolmap.match_exhaustive(database_path)
    reconstructions = pycolmap.incremental_mapping(database_path, output_dir / "images", sparse_dir)

    summary = {
        "ok": bool(reconstructions),
        "dataset_dir": str(args.dataset_dir),
        "camera_id": args.camera_id,
        "output_dir": str(output_dir),
        "image_count": len(prepared_records),
        "crop": crop,
        "camera_mode": args.camera_mode,
        "matcher": args.matcher,
        "database": str(database_path),
        "sparse_dir": str(sparse_dir),
        **reconstruction_summary(reconstructions),
    }
    write_json(output_dir / "reconstruction_summary.json", summary)
    write_json(output_dir / "input_records.json", {"records": prepared_records})
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
