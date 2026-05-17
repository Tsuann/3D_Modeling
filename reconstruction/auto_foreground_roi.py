from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


CAMERAS = ("cam_esp32s3", "cam_k230", "cam_orangepi")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def resolve_image_path(dataset_dir: Path, captures_dir: Path, session_id: str, camera_id: str) -> Path:
    dataset_path = dataset_dir / "images" / f"{session_id}_{camera_id}.jpg"
    if dataset_path.exists():
        return dataset_path
    capture_path = captures_dir / session_id / "raw" / f"{camera_id}.jpg"
    if capture_path.exists():
        return capture_path
    return dataset_path


def load_image(dataset_dir: Path, captures_dir: Path, session_id: str, camera_id: str) -> np.ndarray:
    path = resolve_image_path(dataset_dir, captures_dir, session_id, camera_id)
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Could not read {path}")
    return image


def shadow_mask(image: np.ndarray, background: np.ndarray, shadow_drop: int) -> np.ndarray:
    image_hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    background_hsv = cv2.cvtColor(background, cv2.COLOR_BGR2HSV)
    image_v = image_hsv[:, :, 2].astype(np.int16)
    background_v = background_hsv[:, :, 2].astype(np.int16)
    sat_delta = cv2.absdiff(image_hsv[:, :, 1], background_hsv[:, :, 1])
    hue_delta = cv2.absdiff(image_hsv[:, :, 0], background_hsv[:, :, 0])
    hue_delta = np.minimum(hue_delta, 180 - hue_delta)
    darker = background_v - image_v >= shadow_drop
    similar_color = (sat_delta < 45) & (hue_delta < 12)
    return (darker & similar_color).astype(np.uint8) * 255


def clean_change_mask(
    image: np.ndarray,
    background: np.ndarray,
    threshold: int,
    shadow_drop: int,
    suppress_shadows: bool,
    center_roi_x: float,
    center_roi_y: float,
) -> tuple[np.ndarray, np.ndarray]:
    diff = cv2.absdiff(image, background)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    if suppress_shadows:
        shadows = shadow_mask(image, background, shadow_drop)
        mask[shadows > 0] = 0
    roi = center_roi_mask(mask.shape, center_roi_x, center_roi_y)
    mask = cv2.bitwise_and(mask, roi)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask, gray


def center_roi_mask(shape: tuple[int, int], scale_x: float, scale_y: float) -> np.ndarray:
    height, width = shape
    scale_x = float(np.clip(scale_x, 0.05, 1.0))
    scale_y = float(np.clip(scale_y, 0.05, 1.0))
    roi_width = int(round(width * scale_x))
    roi_height = int(round(height * scale_y))
    left = max(0, (width - roi_width) // 2)
    top = max(0, (height - roi_height) // 2)
    right = min(width, left + roi_width)
    bottom = min(height, top + roi_height)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[top:bottom, left:right] = 255
    return mask


def component_score(
    area: int,
    bbox: tuple[int, int, int, int],
    image_shape: tuple[int, int],
    mean_change: float,
    center_sigma: float,
) -> float:
    height, width = image_shape
    x, y, box_width, box_height = bbox
    cx = x + box_width / 2
    cy = y + box_height / 2
    nx = (cx - width / 2) / max(width / 2, 1)
    ny = (cy - height / 2) / max(height / 2, 1)
    center_distance = math.sqrt(nx * nx + ny * ny)
    center_weight = math.exp(-(center_distance * center_distance) / (2 * center_sigma * center_sigma))
    touches_edge = x <= 2 or y <= 2 or x + box_width >= width - 3 or y + box_height >= height - 3
    edge_weight = 0.18 if touches_edge else 1.0
    compactness = min(1.0, area / max(box_width * box_height, 1))
    return area * center_weight * edge_weight * (0.55 + compactness) * (1.0 + mean_change / 80.0)


def touches_image_edge(bbox: tuple[int, int, int, int], image_shape: tuple[int, int], margin: int) -> bool:
    height, width = image_shape
    x, y, box_width, box_height = bbox
    return x <= margin or y <= margin or x + box_width >= width - margin or y + box_height >= height - margin


def choose_components(
    mask: np.ndarray,
    diff_gray: np.ndarray,
    min_area_ratio: float,
    max_components: int,
    center_sigma: float,
    include_score_ratio: float,
    reject_edge_components: bool,
    edge_margin: int,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    image_area = mask.shape[0] * mask.shape[1]
    min_area = max(80, int(image_area * min_area_ratio))
    candidates: list[dict[str, Any]] = []

    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_area:
            continue
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        edge_touch = touches_image_edge((x, y, width, height), mask.shape, edge_margin)
        if reject_edge_components and edge_touch:
            continue
        component = labels == label
        mean_change = float(np.mean(diff_gray[component]))
        score = component_score(area, (x, y, width, height), mask.shape, mean_change, center_sigma)
        candidates.append(
            {
                "label": label,
                "area": area,
                "bbox": {"x": x, "y": y, "width": width, "height": height},
                "touches_edge": edge_touch,
                "mean_change": mean_change,
                "score": float(score),
            }
        )

    selected = np.zeros_like(mask)
    if not candidates:
        return selected, []

    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]
    best_box = best["bbox"]
    left = best_box["x"] - best_box["width"] * 0.6
    right = best_box["x"] + best_box["width"] * 1.6
    top = best_box["y"] - best_box["height"] * 0.6
    bottom = best_box["y"] + best_box["height"] * 1.6

    chosen = []
    for item in candidates:
        box = item["bbox"]
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        near_best = left <= cx <= right and top <= cy <= bottom
        strong = item["score"] >= best["score"] * include_score_ratio
        if item is best or (near_best and strong):
            chosen.append(item)
        if len(chosen) >= max_components:
            break

    for item in chosen:
        selected[labels == item["label"]] = 255

    kernel = np.ones((7, 7), np.uint8)
    selected = cv2.morphologyEx(selected, cv2.MORPH_CLOSE, kernel, iterations=2)
    return selected, chosen


def mask_bbox(mask: np.ndarray, pad: int) -> dict[str, int] | None:
    points = cv2.findNonZero(mask)
    if points is None:
        return None
    x, y, width, height = cv2.boundingRect(points)
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(mask.shape[1], x + width + pad)
    bottom = min(mask.shape[0], y + height + pad)
    return {"x": int(left), "y": int(top), "width": int(right - left), "height": int(bottom - top)}


def overlay_result(image: np.ndarray, mask: np.ndarray, box: dict[str, int] | None) -> np.ndarray:
    overlay = image.copy()
    overlay[mask > 0] = (0.45 * overlay[mask > 0] + np.array([0, 100, 255]) * 0.55).astype(np.uint8)
    if box:
        left, top = box["x"], box["y"]
        right, bottom = left + box["width"], top + box["height"]
        cv2.rectangle(overlay, (left, top), (right, bottom), (80, 255, 80), 2)
    return overlay


def detect_camera_foreground(
    image: np.ndarray,
    background: np.ndarray,
    threshold: int,
    shadow_drop: int,
    suppress_shadows: bool,
    center_roi_x: float,
    center_roi_y: float,
    min_area_ratio: float,
    max_components: int,
    center_sigma: float,
    include_score_ratio: float,
    reject_edge_components: bool,
    edge_margin: int,
    roi_pad: int,
) -> tuple[np.ndarray, dict[str, int] | None, list[dict[str, Any]], np.ndarray]:
    mask, diff_gray = clean_change_mask(
        image,
        background,
        threshold,
        shadow_drop,
        suppress_shadows,
        center_roi_x,
        center_roi_y,
    )
    selected, components = choose_components(
        mask,
        diff_gray,
        min_area_ratio,
        max_components,
        center_sigma,
        include_score_ratio,
        reject_edge_components,
        edge_margin,
    )
    box = mask_bbox(selected, roi_pad)
    return selected, box, components, diff_gray


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-detect object foreground ROI from fixed-camera empty background.")
    parser.add_argument("--dataset-dir", default="datasets/object_retry_001", type=Path)
    parser.add_argument("--captures-dir", default="capture_console/captures", type=Path)
    parser.add_argument("--session-id", default="object_retry_041")
    parser.add_argument("--background-session", default="background_empty_001")
    parser.add_argument("--output-dir", default="reconstruction/auto_foreground_roi", type=Path)
    parser.add_argument("--threshold", type=int, default=30)
    parser.add_argument("--suppress-shadows", action="store_true", default=True)
    parser.add_argument("--keep-shadows", action="store_false", dest="suppress_shadows")
    parser.add_argument("--shadow-drop", type=int, default=24)
    parser.add_argument("--center-roi-x", type=float, default=0.88)
    parser.add_argument("--center-roi-y", type=float, default=0.82)
    parser.add_argument("--min-area-ratio", type=float, default=0.00055)
    parser.add_argument("--max-components", type=int, default=5)
    parser.add_argument("--center-sigma", type=float, default=0.72)
    parser.add_argument("--include-score-ratio", type=float, default=0.16)
    parser.add_argument("--reject-edge-components", action="store_true", default=True)
    parser.add_argument("--keep-edge-components", action="store_false", dest="reject_edge_components")
    parser.add_argument("--edge-margin", type=int, default=8)
    parser.add_argument("--roi-pad", type=int, default=28)
    args = parser.parse_args()

    masks_dir = args.output_dir / "masks"
    overlays_dir = args.output_dir / "overlays"
    diffs_dir = args.output_dir / "diffs"
    masks_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)
    diffs_dir.mkdir(parents=True, exist_ok=True)

    roi_config: dict[str, Any] = {
        "description": f"Auto foreground ROI boxes for {args.session_id} using background {args.background_session}.",
        "source": {
            "session_id": args.session_id,
            "background_session": args.background_session,
            "threshold": args.threshold,
            "suppress_shadows": args.suppress_shadows,
            "shadow_drop": args.shadow_drop,
            "center_roi_x": args.center_roi_x,
            "center_roi_y": args.center_roi_y,
            "min_area_ratio": args.min_area_ratio,
            "max_components": args.max_components,
            "center_sigma": args.center_sigma,
            "include_score_ratio": args.include_score_ratio,
            "reject_edge_components": args.reject_edge_components,
            "edge_margin": args.edge_margin,
            "roi_pad": args.roi_pad,
        },
        "cameras": {},
    }
    summary = {"ok": True, "session_id": args.session_id, "background_session": args.background_session, "cameras": {}}

    for camera_id in CAMERAS:
        image = load_image(args.dataset_dir, args.captures_dir, args.session_id, camera_id)
        background = load_image(args.dataset_dir, args.captures_dir, args.background_session, camera_id)
        mask, box, components, diff_gray = detect_camera_foreground(
            image,
            background,
            args.threshold,
            args.shadow_drop,
            args.suppress_shadows,
            args.center_roi_x,
            args.center_roi_y,
            args.min_area_ratio,
            args.max_components,
            args.center_sigma,
            args.include_score_ratio,
            args.reject_edge_components,
            args.edge_margin,
            args.roi_pad,
        )
        if box is None:
            summary["ok"] = False
        else:
            roi_config["cameras"][camera_id] = box

        cv2.imwrite(str(masks_dir / f"{args.session_id}_{camera_id}_mask.jpg"), mask)
        cv2.imwrite(str(overlays_dir / f"{args.session_id}_{camera_id}_overlay.jpg"), overlay_result(image, mask, box))
        cv2.imwrite(str(diffs_dir / f"{args.session_id}_{camera_id}_diff.jpg"), diff_gray)

        summary["cameras"][camera_id] = {
            "ok": box is not None,
            "mask_pixels": int(np.count_nonzero(mask)),
            "roi": box,
            "components": components,
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "roi_config.json").open("w", encoding="utf-8") as file:
        json.dump(roi_config, file, indent=2, ensure_ascii=False)
    with (args.output_dir / "summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
