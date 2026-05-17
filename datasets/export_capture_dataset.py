from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from typing import Any


CAMERAS = ("cam_esp32s3", "cam_k230", "cam_orangepi")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def find_numbered_sessions(captures_dir: Path, prefix: str) -> list[Path]:
    pattern = re.compile(rf"^{re.escape(prefix)}\d+$")
    return sorted(path for path in captures_dir.iterdir() if path.is_dir() and pattern.match(path.name))


def copy_if_exists(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Export capture_console sessions into a reconstruction dataset.")
    parser.add_argument("--captures-dir", default="capture_console/captures", type=Path)
    parser.add_argument("--session-prefix", default="object_test_")
    parser.add_argument("--output-dir", default="datasets/object_test_001", type=Path)
    parser.add_argument("--calibration-dir", default="calibration/output_updated_orangepi_ref", type=Path)
    parser.add_argument("--copy-calibration", action="store_true", default=True)
    args = parser.parse_args()

    sessions = find_numbered_sessions(args.captures_dir, args.session_prefix)
    if not sessions:
        raise SystemExit(f"No numbered sessions found for prefix {args.session_prefix!r} under {args.captures_dir}")

    images_dir = args.output_dir / "images"
    metadata_dir = args.output_dir / "metadata"
    calibration_target_dir = args.output_dir / "calibration"
    records = []
    missing = []

    for session in sessions:
        for camera_id in CAMERAS:
            source_image = session / "raw" / f"{camera_id}.jpg"
            source_meta = session / "meta" / f"{camera_id}.json"
            image_name = f"{session.name}_{camera_id}.jpg"
            meta_name = f"{session.name}_{camera_id}.json"
            target_image = images_dir / image_name
            target_meta = metadata_dir / meta_name

            if not copy_if_exists(source_image, target_image):
                missing.append(str(source_image))
                continue
            metadata = read_json(source_meta) if source_meta.exists() else {}
            metadata.update(
                {
                    "dataset_image": str(target_image),
                    "source_session": session.name,
                    "source_camera": camera_id,
                }
            )
            write_json(target_meta, metadata)
            records.append(
                {
                    "session_id": session.name,
                    "camera_id": camera_id,
                    "image": str(target_image),
                    "metadata": str(target_meta),
                    "width": metadata.get("width"),
                    "height": metadata.get("height"),
                    "size_bytes": metadata.get("size_bytes"),
                }
            )

    if args.copy_calibration:
        if args.calibration_dir.exists():
            if calibration_target_dir.exists():
                shutil.rmtree(calibration_target_dir)
            shutil.copytree(args.calibration_dir, calibration_target_dir)
        else:
            missing.append(str(args.calibration_dir))

    manifest = {
        "dataset": args.output_dir.name,
        "session_prefix": args.session_prefix,
        "session_count": len(sessions),
        "camera_ids": list(CAMERAS),
        "image_count": len(records),
        "expected_image_count": len(sessions) * len(CAMERAS),
        "calibration_source": str(args.calibration_dir),
        "calibration_copied_to": str(calibration_target_dir) if args.copy_calibration else None,
        "records": records,
        "missing": missing,
        "ok": not missing and len(records) == len(sessions) * len(CAMERAS),
    }
    write_json(args.output_dir / "manifest.json", manifest)

    print(json.dumps({key: manifest[key] for key in (
        "ok",
        "dataset",
        "session_count",
        "image_count",
        "expected_image_count",
        "calibration_copied_to",
        "missing",
    )}, indent=2, ensure_ascii=False))
    return 0 if manifest["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
