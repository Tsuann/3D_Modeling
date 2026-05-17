from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np


PAIRS = (("cam_k230", "cam_orangepi"), ("cam_esp32s3", "cam_orangepi"))


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def camera_params(calibration_dir: Path, camera_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    intrinsic = read_json(calibration_dir / "intrinsics" / f"{camera_id}.json")
    extrinsic = read_json(calibration_dir / "extrinsics" / "rig_extrinsics.json")["cameras"][camera_id]
    k = np.array(intrinsic["camera_matrix"], dtype=np.float64)
    dist = np.array(intrinsic["dist_coeffs"], dtype=np.float64)
    transform = np.array(extrinsic["transform_reference_to_camera"], dtype=np.float64)
    return k, dist, transform


def load_image(dataset_dir: Path, session_id: str, camera_id: str) -> np.ndarray:
    path = dataset_dir / "images" / f"{session_id}_{camera_id}.jpg"
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read image: {path}")
    return image


def detect_and_match(left: np.ndarray, right: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    sift = cv2.SIFT_create(nfeatures=4000)
    left_gray = cv2.cvtColor(left, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right, cv2.COLOR_BGR2GRAY)
    left_kp, left_desc = sift.detectAndCompute(left_gray, None)
    right_kp, right_desc = sift.detectAndCompute(right_gray, None)
    if left_desc is None or right_desc is None:
        return np.empty((0, 2), np.float32), np.empty((0, 2), np.float32)

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    knn = matcher.knnMatch(left_desc, right_desc, k=2)
    left_points = []
    right_points = []
    for first, second in knn:
        if first.distance < 0.72 * second.distance:
            left_points.append(left_kp[first.queryIdx].pt)
            right_points.append(right_kp[first.trainIdx].pt)
    return np.array(left_points, dtype=np.float32), np.array(right_points, dtype=np.float32)


def ransac_filter(left_points: np.ndarray, right_points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(left_points) < 8:
        return left_points[:0], right_points[:0]
    _, mask = cv2.findFundamentalMat(left_points, right_points, cv2.FM_RANSAC, 2.0, 0.99)
    if mask is None:
        return left_points[:0], right_points[:0]
    keep = mask.ravel().astype(bool)
    return left_points[keep], right_points[keep]


def triangulate_pair(
    left_image: np.ndarray,
    right_image: np.ndarray,
    left_k: np.ndarray,
    left_dist: np.ndarray,
    left_transform: np.ndarray,
    right_k: np.ndarray,
    right_dist: np.ndarray,
    right_transform: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    left_points, right_points = detect_and_match(left_image, right_image)
    raw_match_count = len(left_points)
    left_points, right_points = ransac_filter(left_points, right_points)
    inlier_count = len(left_points)
    if inlier_count < 2:
        return np.empty((0, 3), np.float64), np.empty((0, 3), np.uint8), {
            "raw_matches": raw_match_count,
            "inliers": inlier_count,
        }

    left_norm = cv2.undistortPoints(left_points.reshape(-1, 1, 2), left_k, left_dist).reshape(-1, 2)
    right_norm = cv2.undistortPoints(right_points.reshape(-1, 1, 2), right_k, right_dist).reshape(-1, 2)

    left_projection = left_transform[:3, :]
    right_projection = right_transform[:3, :]
    points_h = cv2.triangulatePoints(left_projection, right_projection, left_norm.T, right_norm.T).T
    points = points_h[:, :3] / points_h[:, 3:4]

    left_pixels = np.round(left_points).astype(int)
    left_pixels[:, 0] = np.clip(left_pixels[:, 0], 0, left_image.shape[1] - 1)
    left_pixels[:, 1] = np.clip(left_pixels[:, 1], 0, left_image.shape[0] - 1)
    colors = left_image[left_pixels[:, 1], left_pixels[:, 0], ::-1]

    finite = np.isfinite(points).all(axis=1)
    distance = np.linalg.norm(points, axis=1)
    keep = finite & (distance < 5.0)
    return points[keep], colors[keep], {
        "raw_matches": raw_match_count,
        "inliers": inlier_count,
        "kept_points": int(np.count_nonzero(keep)),
    }


def write_ply(path: Path, points: np.ndarray, colors: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as file:
        file.write("ply\n")
        file.write("format ascii 1.0\n")
        file.write(f"element vertex {len(points)}\n")
        file.write("property float x\n")
        file.write("property float y\n")
        file.write("property float z\n")
        file.write("property uchar red\n")
        file.write("property uchar green\n")
        file.write("property uchar blue\n")
        file.write("end_header\n")
        for point, color in zip(points, colors):
            file.write(
                f"{point[0]:.6f} {point[1]:.6f} {point[2]:.6f} "
                f"{int(color[0])} {int(color[1])} {int(color[2])}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Triangulate sparse points from a calibrated fixed camera rig.")
    parser.add_argument("--dataset-dir", default="datasets/object_test_001", type=Path)
    parser.add_argument("--calibration-dir", default="datasets/object_test_001/calibration", type=Path)
    parser.add_argument("--session-id", default="object_test_001")
    parser.add_argument("--output-dir", default="reconstruction/object_test_001_known_rig", type=Path)
    args = parser.parse_args()

    all_points = []
    all_colors = []
    pair_reports = []
    for left_camera, right_camera in PAIRS:
        left_image = load_image(args.dataset_dir, args.session_id, left_camera)
        right_image = load_image(args.dataset_dir, args.session_id, right_camera)
        left_k, left_dist, left_transform = camera_params(args.calibration_dir, left_camera)
        right_k, right_dist, right_transform = camera_params(args.calibration_dir, right_camera)
        points, colors, report = triangulate_pair(
            left_image,
            right_image,
            left_k,
            left_dist,
            left_transform,
            right_k,
            right_dist,
            right_transform,
        )
        all_points.append(points)
        all_colors.append(colors)
        pair_reports.append({"left_camera": left_camera, "right_camera": right_camera, **report})

    points = np.vstack(all_points) if all_points else np.empty((0, 3), np.float64)
    colors = np.vstack(all_colors) if all_colors else np.empty((0, 3), np.uint8)
    output_ply = args.output_dir / f"{args.session_id}_sparse_known_rig.ply"
    write_ply(output_ply, points, colors)

    summary = {
        "ok": len(points) > 0,
        "session_id": args.session_id,
        "output_ply": str(output_ply),
        "point_count": int(len(points)),
        "pairs": pair_reports,
        "note": "This is a sparse calibrated-rig triangulation for one object pose, not a fused full-object mesh.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "triangulation_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
