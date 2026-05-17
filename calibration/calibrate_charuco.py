from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CAMERAS = ("cam_esp32s3", "cam_k230", "cam_orangepi")


def make_board() -> cv2.aruco.CharucoBoard:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_5X5_50)
    board = cv2.aruco.CharucoBoard((11, 8), 0.020, 0.015, dictionary)
    board.setLegacyPattern(True)
    return board


def as_jsonable(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {key: as_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [as_jsonable(item) for item in value]
    return value


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(as_jsonable(data), file, indent=2, ensure_ascii=False)


def find_sessions(captures_dir: Path, prefix: str) -> list[Path]:
    return sorted(path for path in captures_dir.glob(f"{prefix}*") if path.is_dir())


def detect_image(board: cv2.aruco.CharucoBoard, image_path: Path) -> dict[str, Any]:
    image = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return {"ok": False, "error": "image could not be read", "image_path": str(image_path)}

    detector = cv2.aruco.CharucoDetector(board)
    charuco_corners, charuco_ids, marker_corners, marker_ids = detector.detectBoard(image)
    marker_count = 0 if marker_ids is None else int(len(marker_ids))
    corner_count = 0 if charuco_ids is None else int(len(charuco_ids))

    if charuco_ids is None or charuco_corners is None or corner_count == 0:
        return {
            "ok": False,
            "image_path": str(image_path),
            "image_size": [int(image.shape[1]), int(image.shape[0])],
            "marker_count": marker_count,
            "charuco_count": 0,
            "error": "no charuco corners detected",
        }

    obj_points, img_points = board.matchImagePoints(charuco_corners, charuco_ids)
    return {
        "ok": True,
        "image_path": str(image_path),
        "image_size": [int(image.shape[1]), int(image.shape[0])],
        "marker_count": marker_count,
        "charuco_count": corner_count,
        "charuco_ids": charuco_ids.reshape(-1).astype(int),
        "obj_points": obj_points.astype(np.float32),
        "img_points": img_points.astype(np.float32),
    }


def reprojection_error(
    obj_points: list[np.ndarray],
    img_points: list[np.ndarray],
    rvecs: list[np.ndarray],
    tvecs: list[np.ndarray],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
) -> float:
    total_error = 0.0
    total_points = 0
    for obj, img, rvec, tvec in zip(obj_points, img_points, rvecs, tvecs):
        projected, _ = cv2.projectPoints(obj, rvec, tvec, camera_matrix, dist_coeffs)
        error = cv2.norm(img, projected, cv2.NORM_L2)
        total_error += error * error
        total_points += len(obj)
    if total_points == 0:
        return math.inf
    return math.sqrt(total_error / total_points)


def calibrate_intrinsics(camera_id: str, detections: list[dict[str, Any]], min_corners: int) -> dict[str, Any]:
    valid = [item for item in detections if item["ok"] and item["charuco_count"] >= min_corners]
    if len(valid) < 5:
        return {
            "ok": False,
            "camera_id": camera_id,
            "valid_views": len(valid),
            "error": "not enough valid views",
        }

    image_size = tuple(valid[0]["image_size"])
    obj_points = [item["obj_points"] for item in valid]
    img_points = [item["img_points"] for item in valid]

    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points,
        img_points,
        image_size,
        None,
        None,
    )
    mean_error = reprojection_error(obj_points, img_points, rvecs, tvecs, camera_matrix, dist_coeffs)

    return {
        "ok": True,
        "camera_id": camera_id,
        "image_size": list(image_size),
        "valid_views": len(valid),
        "total_corners": int(sum(item["charuco_count"] for item in valid)),
        "rms": float(rms),
        "mean_reprojection_error_px": float(mean_error),
        "camera_matrix": camera_matrix,
        "dist_coeffs": dist_coeffs,
        "used_sessions": [item["session_id"] for item in valid],
    }


def invert_transform(transform: np.ndarray) -> np.ndarray:
    inverse = np.eye(4, dtype=np.float64)
    inverse[:3, :3] = transform[:3, :3].T
    inverse[:3, 3] = -inverse[:3, :3] @ transform[:3, 3]
    return inverse


def solve_board_pose(item: dict[str, Any], intrinsic: dict[str, Any]) -> np.ndarray | None:
    camera_matrix = np.array(intrinsic["camera_matrix"], dtype=np.float64)
    dist_coeffs = np.array(intrinsic["dist_coeffs"], dtype=np.float64)
    ok, rvec, tvec = cv2.solvePnP(
        item["obj_points"],
        item["img_points"],
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        return None
    rotation, _ = cv2.Rodrigues(rvec)
    transform = np.eye(4, dtype=np.float64)
    transform[:3, :3] = rotation
    transform[:3, 3] = tvec.reshape(3)
    return transform


def average_rotation(rotations: list[np.ndarray]) -> np.ndarray:
    matrix = np.mean(np.stack(rotations), axis=0)
    u, _, vt = np.linalg.svd(matrix)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return rotation


def build_extrinsics(
    by_session: dict[str, dict[str, dict[str, Any]]],
    intrinsics: dict[str, dict[str, Any]],
    reference_camera: str,
    min_corners: int,
) -> dict[str, Any]:
    poses: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
    for session_id, session_items in by_session.items():
        for camera_id, item in session_items.items():
            if not item["ok"] or item["charuco_count"] < min_corners:
                continue
            intrinsic = intrinsics.get(camera_id)
            if not intrinsic or not intrinsic.get("ok"):
                continue
            pose = solve_board_pose(item, intrinsic)
            if pose is not None:
                poses[session_id][camera_id] = pose

    relative: dict[str, dict[str, Any]] = {}
    ref_to_cam_samples: dict[str, list[np.ndarray]] = defaultdict(list)
    for session_id, session_poses in poses.items():
        if reference_camera not in session_poses:
            continue
        ref_pose = session_poses[reference_camera]
        for camera_id, cam_pose in session_poses.items():
            if camera_id == reference_camera:
                continue
            ref_to_cam = cam_pose @ invert_transform(ref_pose)
            ref_to_cam_samples[camera_id].append(ref_to_cam)

    for camera_id, samples in ref_to_cam_samples.items():
        rotations = [sample[:3, :3] for sample in samples]
        translations = np.stack([sample[:3, 3] for sample in samples], axis=0)
        rotation = average_rotation(rotations)
        translation = np.mean(translations, axis=0)
        transform = np.eye(4, dtype=np.float64)
        transform[:3, :3] = rotation
        transform[:3, 3] = translation
        translation_std = np.std(translations, axis=0)
        rvec, _ = cv2.Rodrigues(rotation)
        relative[camera_id] = {
            "ok": True,
            "reference_camera": reference_camera,
            "camera_id": camera_id,
            "sample_count": len(samples),
            "transform_reference_to_camera": transform,
            "rotation_vector": rvec.reshape(3),
            "translation_m": translation,
            "translation_std_m": translation_std,
        }

    relative[reference_camera] = {
        "ok": True,
        "reference_camera": reference_camera,
        "camera_id": reference_camera,
        "sample_count": 0,
        "transform_reference_to_camera": np.eye(4, dtype=np.float64),
        "rotation_vector": np.zeros(3, dtype=np.float64),
        "translation_m": np.zeros(3, dtype=np.float64),
        "translation_std_m": np.zeros(3, dtype=np.float64),
    }
    return {"reference_camera": reference_camera, "cameras": relative}


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate the three-camera rig from ChArUco captures.")
    parser.add_argument("--captures-dir", default="capture_console/captures", type=Path)
    parser.add_argument("--session-prefix", default="calib_")
    parser.add_argument("--output-dir", default="calibration/output", type=Path)
    parser.add_argument("--min-corners", default=12, type=int)
    parser.add_argument("--reference-camera", default="cam_k230", choices=CAMERAS)
    args = parser.parse_args()

    board = make_board()
    sessions = [
        session
        for session in find_sessions(args.captures_dir, args.session_prefix)
        if session.name[: len(args.session_prefix)] == args.session_prefix and session.name[len(args.session_prefix) :].isdigit()
    ]
    if not sessions:
        raise SystemExit(f"No sessions found under {args.captures_dir} with prefix {args.session_prefix!r}")

    by_camera: dict[str, list[dict[str, Any]]] = {camera_id: [] for camera_id in CAMERAS}
    by_session: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    detection_rows = []

    for session in sessions:
        for camera_id in CAMERAS:
            image_path = session / "raw" / f"{camera_id}.jpg"
            item = detect_image(board, image_path)
            item["session_id"] = session.name
            item["camera_id"] = camera_id
            by_camera[camera_id].append(item)
            by_session[session.name][camera_id] = item
            detection_rows.append(
                {
                    "session_id": session.name,
                    "camera_id": camera_id,
                    "ok": item["ok"],
                    "markers": item.get("marker_count", 0),
                    "charuco_corners": item.get("charuco_count", 0),
                    "image_size": item.get("image_size"),
                    "error": item.get("error", ""),
                }
            )

    intrinsics = {
        camera_id: calibrate_intrinsics(camera_id, detections, args.min_corners)
        for camera_id, detections in by_camera.items()
    }
    extrinsics = build_extrinsics(by_session, intrinsics, args.reference_camera, args.min_corners)

    pair_counts: dict[str, int] = {}
    for left in CAMERAS:
        for right in CAMERAS:
            if left >= right:
                continue
            pair_counts[f"{left}__{right}"] = sum(
                1
                for session_items in by_session.values()
                if session_items[left]["ok"]
                and session_items[right]["ok"]
                and session_items[left]["charuco_count"] >= args.min_corners
                and session_items[right]["charuco_count"] >= args.min_corners
            )

    report = {
        "ok": all(item.get("ok") for item in intrinsics.values()),
        "board": {
            "squares_x": 11,
            "squares_y": 8,
            "square_length_m": 0.020,
            "marker_length_m": 0.015,
            "dictionary": "DICT_5X5_50",
            "legacy_pattern": True,
        },
        "sessions": [session.name for session in sessions],
        "min_corners": args.min_corners,
        "detection_summary": {
            camera_id: {
                "valid_views": sum(1 for item in detections if item["ok"] and item["charuco_count"] >= args.min_corners),
                "detected_views": sum(1 for item in detections if item["ok"]),
                "max_corners": max((item.get("charuco_count", 0) for item in detections), default=0),
            }
            for camera_id, detections in by_camera.items()
        },
        "pair_valid_view_counts": pair_counts,
        "intrinsics": intrinsics,
        "extrinsics": extrinsics,
        "detections": detection_rows,
    }

    write_json(args.output_dir / "calibration_report.json", report)
    for camera_id, intrinsic in intrinsics.items():
        write_json(args.output_dir / "intrinsics" / f"{camera_id}.json", intrinsic)
    write_json(args.output_dir / "extrinsics" / "rig_extrinsics.json", extrinsics)

    print(json.dumps(as_jsonable({
        "ok": report["ok"],
        "output_dir": str(args.output_dir),
        "detection_summary": report["detection_summary"],
        "pair_valid_view_counts": pair_counts,
        "intrinsics": {
            camera_id: {
                "ok": item.get("ok"),
                "valid_views": item.get("valid_views"),
                "rms": item.get("rms"),
                "mean_reprojection_error_px": item.get("mean_reprojection_error_px"),
            }
            for camera_id, item in intrinsics.items()
        },
        "extrinsics": {
            camera_id: {
                "sample_count": item.get("sample_count"),
                "translation_m": item.get("translation_m"),
                "translation_std_m": item.get("translation_std_m"),
            }
            for camera_id, item in extrinsics["cameras"].items()
        },
    }), indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
