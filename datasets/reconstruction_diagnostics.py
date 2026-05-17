from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CAMERAS = ("cam_esp32s3", "cam_k230", "cam_orangepi")
PAIRINGS = (
    ("cam_esp32s3", "cam_k230"),
    ("cam_esp32s3", "cam_orangepi"),
    ("cam_k230", "cam_orangepi"),
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def load_image(path: Path, max_width: int | None = None) -> np.ndarray:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    if max_width and image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        image = cv2.resize(image, (max_width, int(round(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    return image


def image_stats(image: np.ndarray) -> dict[str, Any]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {
        "width": int(image.shape[1]),
        "height": int(image.shape[0]),
        "mean_luma": float(np.mean(gray)),
        "std_luma": float(np.std(gray)),
        "overexposed_ratio": float(np.mean(gray >= 245)),
        "underexposed_ratio": float(np.mean(gray <= 10)),
        "laplacian_var": float(cv2.Laplacian(gray, cv2.CV_64F).var()),
    }


def detect_sift(image: np.ndarray) -> tuple[list[cv2.KeyPoint], np.ndarray | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create(nfeatures=3000)
    return sift.detectAndCompute(gray, None)


def match_descriptors(left: np.ndarray | None, right: np.ndarray | None) -> dict[str, Any]:
    if left is None or right is None or len(left) < 2 or len(right) < 2:
        return {"raw_matches": 0, "good_matches": 0}
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    matches = matcher.knnMatch(left, right, k=2)
    good = []
    for first, second in matches:
        if first.distance < 0.75 * second.distance:
            good.append(first)
    return {"raw_matches": len(matches), "good_matches": len(good)}


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": math.nan, "max": math.nan, "mean": math.nan}
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def make_contact_sheet(records: list[dict[str, Any]], output_path: Path, max_width: int = 360) -> None:
    selected_sessions = []
    sessions = sorted({record["session_id"] for record in records})
    if not sessions:
        return
    for index in sorted({0, len(sessions) // 2, len(sessions) - 1}):
        selected_sessions.append(sessions[index])

    rows = []
    for session_id in selected_sessions:
        row_images = []
        for camera_id in CAMERAS:
            record = next(
                item for item in records if item["session_id"] == session_id and item["camera_id"] == camera_id
            )
            image = load_image(Path(record["image"]), max_width=max_width)
            cv2.putText(
                image,
                f"{session_id} {camera_id}",
                (10, 26),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (0, 0, 255),
                2,
                cv2.LINE_AA,
            )
            row_images.append(image)
        target_height = max(image.shape[0] for image in row_images)
        padded = []
        for image in row_images:
            pad = target_height - image.shape[0]
            if pad > 0:
                image = cv2.copyMakeBorder(image, 0, pad, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))
            padded.append(image)
        rows.append(cv2.hconcat(padded))
    target_width = max(row.shape[1] for row in rows)
    padded_rows = []
    for row in rows:
        pad = target_width - row.shape[1]
        if pad > 0:
            row = cv2.copyMakeBorder(row, 0, 0, 0, pad, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        padded_rows.append(row)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), cv2.vconcat(padded_rows))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run feature and image-quality diagnostics on an exported dataset.")
    parser.add_argument("--dataset-dir", default="datasets/object_test_001", type=Path)
    parser.add_argument("--sample-every", default=3, type=int, help="Analyze every Nth session for feature matching.")
    args = parser.parse_args()

    manifest = read_json(args.dataset_dir / "manifest.json")
    records = manifest["records"]
    by_session: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        by_session.setdefault(record["session_id"], {})[record["camera_id"]] = record

    feature_rows = []
    descriptor_cache: dict[str, np.ndarray | None] = {}
    keypoint_cache: dict[str, int] = {}
    stats_rows = []
    sampled_sessions = sorted(by_session)[:: max(args.sample_every, 1)]

    for session_id in sampled_sessions:
        for camera_id in CAMERAS:
            record = by_session[session_id][camera_id]
            image_path = Path(record["image"])
            image = load_image(image_path)
            stats = image_stats(image)
            keypoints, descriptors = detect_sift(image)
            descriptor_cache[f"{session_id}/{camera_id}"] = descriptors
            keypoint_cache[f"{session_id}/{camera_id}"] = len(keypoints)
            stats_rows.append({"session_id": session_id, "camera_id": camera_id, **stats})
            feature_rows.append(
                {
                    "session_id": session_id,
                    "camera_id": camera_id,
                    "sift_keypoints": len(keypoints),
                    **stats,
                }
            )

    pair_rows = []
    for session_id in sampled_sessions:
        for left, right in PAIRINGS:
            match_stats = match_descriptors(
                descriptor_cache.get(f"{session_id}/{left}"),
                descriptor_cache.get(f"{session_id}/{right}"),
            )
            pair_rows.append(
                {
                    "session_id": session_id,
                    "left_camera": left,
                    "right_camera": right,
                    "left_keypoints": keypoint_cache.get(f"{session_id}/{left}", 0),
                    "right_keypoints": keypoint_cache.get(f"{session_id}/{right}", 0),
                    **match_stats,
                }
            )

    by_camera_summary = {}
    for camera_id in CAMERAS:
        rows = [row for row in feature_rows if row["camera_id"] == camera_id]
        by_camera_summary[camera_id] = {
            "sampled_images": len(rows),
            "sift_keypoints": summarize([row["sift_keypoints"] for row in rows]),
            "laplacian_var": summarize([row["laplacian_var"] for row in rows]),
            "overexposed_ratio": summarize([row["overexposed_ratio"] for row in rows]),
        }

    pair_summary = {}
    for left, right in PAIRINGS:
        rows = [row for row in pair_rows if row["left_camera"] == left and row["right_camera"] == right]
        pair_summary[f"{left}__{right}"] = {
            "sampled_pairs": len(rows),
            "good_matches": summarize([row["good_matches"] for row in rows]),
            "raw_matches": summarize([row["raw_matches"] for row in rows]),
        }

    output_dir = args.dataset_dir / "diagnostics"
    make_contact_sheet(records, output_dir / "contact_sheet.jpg")
    report = {
        "dataset_dir": str(args.dataset_dir),
        "sample_every": args.sample_every,
        "sampled_sessions": sampled_sessions,
        "camera_summary": by_camera_summary,
        "pair_summary": pair_summary,
        "features": feature_rows,
        "pair_matches": pair_rows,
        "notes": [
            "This is a reconstruction-readiness diagnostic, not a final 3D reconstruction.",
            "For fixed cameras with a moving or rotating object, traditional SfM must avoid matching static background as the object moves.",
        ],
    }
    write_json(output_dir / "reconstruction_diagnostics.json", report)
    print(json.dumps(
        {
            "ok": True,
            "output_dir": str(output_dir),
            "sampled_sessions": len(sampled_sessions),
            "camera_summary": by_camera_summary,
            "pair_summary": pair_summary,
            "contact_sheet": str(output_dir / "contact_sheet.jpg"),
        },
        indent=2,
        ensure_ascii=False,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
