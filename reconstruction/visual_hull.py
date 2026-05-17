from __future__ import annotations

import argparse
import json
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


def camera_data(calibration_dir: Path, camera_id: str) -> dict[str, np.ndarray]:
    intrinsic = read_json(calibration_dir / "intrinsics" / f"{camera_id}.json")
    extrinsic = read_json(calibration_dir / "extrinsics" / "rig_extrinsics.json")["cameras"][camera_id]
    world_to_camera = np.array(extrinsic["transform_reference_to_camera"], dtype=np.float64)
    camera_to_world = np.linalg.inv(world_to_camera)
    return {
        "k": np.array(intrinsic["camera_matrix"], dtype=np.float64),
        "dist": np.array(intrinsic["dist_coeffs"], dtype=np.float64),
        "world_to_camera": world_to_camera,
        "camera_to_world": camera_to_world,
        "center": camera_to_world[:3, 3],
    }


def dataset_sessions(dataset_dir: Path) -> list[str]:
    manifest = read_json(dataset_dir / "manifest.json")
    return sorted({record["session_id"] for record in manifest["records"]})


def build_background(dataset_dir: Path, captures_dir: Path, camera_id: str, sessions: list[str], max_frames: int = 31) -> np.ndarray:
    selected = sessions[:: max(1, len(sessions) // max_frames)][:max_frames]
    frames = [load_image(dataset_dir, captures_dir, session_id, camera_id) for session_id in selected]
    stack = np.stack(frames, axis=0)
    return np.median(stack, axis=0).astype(np.uint8)


def load_backgrounds(
    dataset_dir: Path,
    captures_dir: Path,
    sessions: list[str],
    background_session: str | None,
) -> dict[str, np.ndarray]:
    if background_session:
        return {camera_id: load_image(dataset_dir, captures_dir, background_session, camera_id) for camera_id in CAMERAS}
    return {camera_id: build_background(dataset_dir, captures_dir, camera_id, sessions) for camera_id in CAMERAS}


def color_seed_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    orange_1 = cv2.inRange(hsv, np.array([0, 55, 45]), np.array([24, 255, 255]))
    orange_2 = cv2.inRange(hsv, np.array([170, 55, 45]), np.array([179, 255, 255]))
    cyan = cv2.inRange(hsv, np.array([75, 35, 55]), np.array([105, 255, 255]))
    seed = cv2.bitwise_or(cv2.bitwise_or(orange_1, orange_2), cyan)
    kernel = np.ones((5, 5), np.uint8)
    seed = cv2.morphologyEx(seed, cv2.MORPH_OPEN, kernel)
    seed = cv2.morphologyEx(seed, cv2.MORPH_CLOSE, kernel, iterations=2)
    return seed


def focus_seed_mask(seed: np.ndarray, image: np.ndarray, bg_mask: np.ndarray, max_components: int = 3) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((seed > 0).astype(np.uint8), 8)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    candidates = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < 150:
            continue
        component = labels == label
        bg_overlap = float(np.count_nonzero(bg_mask[component]) / area)
        if bg_overlap < 0.04:
            continue
        mean_saturation = float(np.mean(hsv[:, :, 1][component]))
        score = area * bg_overlap * max(mean_saturation, 1.0)
        candidates.append((score, label))

    focused = np.zeros_like(seed)
    if not candidates:
        return focused

    candidates.sort(reverse=True)
    best_score = candidates[0][0]
    for score, label in candidates[:max_components]:
        if score < best_score * 0.25:
            continue
        focused[labels == label] = 255
    kernel = np.ones((7, 7), np.uint8)
    return cv2.morphologyEx(focused, cv2.MORPH_CLOSE, kernel, iterations=2)


def keep_components_touching_seed(mask: np.ndarray, seed: np.ndarray, min_area: int) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    clean = np.zeros_like(mask)
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        component = labels == label
        if np.count_nonzero(seed[component]) > 0:
            clean[component] = 255
    return clean


def seed_bbox_mask(seed: np.ndarray, pad: int) -> np.ndarray:
    points = cv2.findNonZero(seed)
    allowed = np.zeros_like(seed)
    if points is None:
        return allowed
    x, y, width, height = cv2.boundingRect(points)
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(seed.shape[1], x + width + pad)
    bottom = min(seed.shape[0], y + height + pad)
    allowed[top:bottom, left:right] = 255
    return allowed


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


def box_roi_mask(shape: tuple[int, int], box: dict[str, float]) -> np.ndarray:
    height, width = shape
    normalized = bool(box.get("normalized", False))
    if normalized:
        x = int(round(float(box["x"]) * width))
        y = int(round(float(box["y"]) * height))
        box_width = int(round(float(box["width"]) * width))
        box_height = int(round(float(box["height"]) * height))
    else:
        x = int(round(float(box["x"])))
        y = int(round(float(box["y"])))
        box_width = int(round(float(box["width"])))
        box_height = int(round(float(box["height"])))
    left = max(0, x)
    top = max(0, y)
    right = min(width, x + box_width)
    bottom = min(height, y + box_height)
    mask = np.zeros((height, width), dtype=np.uint8)
    if right > left and bottom > top:
        mask[top:bottom, left:right] = 255
    return mask


def load_roi_config(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None:
        return {}
    data = read_json(path)
    if "cameras" in data:
        data = data["cameras"]
    return {camera_id: data[camera_id] for camera_id in CAMERAS if camera_id in data}


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


def suppress_dark_shadow_regions(image: np.ndarray, mask: np.ndarray, seed: np.ndarray, value_max: int, saturation_max: int) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    protected = cv2.dilate(seed, np.ones((13, 13), np.uint8), iterations=1) > 0
    dark_shadow = (hsv[:, :, 2] <= value_max) & (hsv[:, :, 1] <= saturation_max) & ~protected
    clean = mask.copy()
    clean[dark_shadow] = 0
    return clean


def foreground_mask(
    image: np.ndarray,
    background: np.ndarray,
    threshold: int,
    mode: str,
    seed_bbox_pad: int,
    suppress_shadows: bool,
    shadow_drop: int,
    center_roi_x: float,
    center_roi_y: float,
    roi_mask: np.ndarray | None,
    shadow_value_max: int,
    shadow_saturation_max: int,
) -> np.ndarray:
    diff = cv2.absdiff(image, background)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    _, bg_mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    seed = color_seed_mask(image)
    roi = center_roi_mask(gray.shape, center_roi_x, center_roi_y)
    if roi_mask is not None:
        roi = cv2.bitwise_and(roi, roi_mask)
    bg_mask = cv2.bitwise_and(bg_mask, roi)
    seed = cv2.bitwise_and(seed, roi)
    if suppress_shadows:
        shadows = shadow_mask(image, background, shadow_drop)
        bg_mask[(shadows > 0) & (seed == 0)] = 0
    focused_seed = focus_seed_mask(seed, image, bg_mask)
    if np.count_nonzero(focused_seed) > 0:
        seed = focused_seed

    if mode == "color":
        mask = seed
    elif mode == "hybrid":
        expanded = cv2.dilate(bg_mask, np.ones((9, 9), np.uint8), iterations=1)
        if seed_bbox_pad >= 0:
            expanded = cv2.bitwise_and(expanded, seed_bbox_mask(seed, seed_bbox_pad))
        mask = keep_components_touching_seed(expanded, seed, min_area=300)
    else:
        mask = bg_mask

    mask = suppress_dark_shadow_regions(image, mask, seed, shadow_value_max, shadow_saturation_max)
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    clean = np.zeros_like(mask)
    for contour in contours:
        if cv2.contourArea(contour) >= 300:
            cv2.drawContours(clean, [contour], -1, 255, cv2.FILLED)
    return cv2.bitwise_and(clean, roi)


def neighbor_count_3d(volume: np.ndarray) -> np.ndarray:
    padded = np.pad(volume.astype(np.uint8), 1, mode="constant")
    count = np.zeros_like(volume, dtype=np.uint8)
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                count += padded[
                    1 + dx : 1 + dx + volume.shape[0],
                    1 + dy : 1 + dy + volume.shape[1],
                    1 + dz : 1 + dz + volume.shape[2],
                ]
    return count


def erode3d(volume: np.ndarray, min_neighbors: int = 18) -> np.ndarray:
    return volume & (neighbor_count_3d(volume) >= min_neighbors)


def dilate3d(volume: np.ndarray, min_neighbors: int = 1) -> np.ndarray:
    return volume | (neighbor_count_3d(volume) >= min_neighbors)


def smooth_volume(volume: np.ndarray, iterations: int, open_iterations: int) -> np.ndarray:
    support = volume.copy()
    result = volume.copy()
    for _ in range(open_iterations):
        result = erode3d(result, min_neighbors=10)
        result = dilate3d(result, min_neighbors=1) & support
    for _ in range(iterations):
        neighbors = neighbor_count_3d(result)
        result = ((result & (neighbors >= 6)) | (~result & support & (neighbors >= 18))) & support
    return keep_largest_component(result)


def volume_grid(center: np.ndarray, extent: float, resolution: int) -> np.ndarray:
    axis = np.linspace(-extent / 2, extent / 2, resolution)
    return np.array(np.meshgrid(axis, axis, axis, indexing="xy")).reshape(3, -1).T + center


def points_from_volume(volume: np.ndarray, center: np.ndarray, extent: float, resolution: int) -> np.ndarray:
    grid = volume_grid(center, extent, resolution)
    return grid[volume.reshape(-1)]


def regularize_shape_volume(volume: np.ndarray, center: np.ndarray, extent: float, resolution: int, mode: str) -> tuple[np.ndarray, str]:
    if mode == "none" or np.count_nonzero(volume) < 8:
        return volume, "none"
    points = points_from_volume(volume, center, extent, resolution)
    prior = shape_prior(points)
    selected_mode = mode
    if mode == "auto":
        classification = prior.get("classification", "")
        if classification == "elongated_or_cylindrical":
            selected_mode = "cylinder"
        elif classification in {"compact_regular", "relatively_regular"}:
            selected_mode = "ellipsoid"
        else:
            selected_mode = "box"

    pca_center = np.array(prior["center_m"], dtype=np.float64)
    axes = np.array(prior["principal_axes"], dtype=np.float64)
    local = (volume_grid(center, extent, resolution) - pca_center) @ axes.T
    occupied_local = (points - pca_center) @ axes.T
    half_extents = np.maximum(np.max(np.abs(occupied_local), axis=0), 1e-9)

    if selected_mode == "box":
        primitive = np.all(np.abs(local) <= half_extents, axis=1)
    elif selected_mode == "cylinder":
        radius = float(np.percentile(np.linalg.norm(occupied_local[:, 1:3], axis=1), 82))
        primitive = (np.abs(local[:, 0]) <= half_extents[0]) & (np.linalg.norm(local[:, 1:3], axis=1) <= radius)
    else:
        normalized = local / half_extents
        primitive = np.sum(normalized * normalized, axis=1) <= 1.0

    regularized = primitive.reshape(volume.shape) & volume
    if np.count_nonzero(regularized) == 0:
        return volume, "none_empty_fallback"
    return keep_largest_component(regularized), selected_mode


def mask_centroid(mask: np.ndarray) -> tuple[float, float] | None:
    moments = cv2.moments(mask)
    if moments["m00"] <= 0:
        return None
    return moments["m10"] / moments["m00"], moments["m01"] / moments["m00"]


def pixel_ray(camera: dict[str, np.ndarray], pixel: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    point = np.array([[[pixel[0], pixel[1]]]], dtype=np.float64)
    norm = cv2.undistortPoints(point, camera["k"], camera["dist"]).reshape(2)
    direction_camera = np.array([norm[0], norm[1], 1.0], dtype=np.float64)
    direction_camera /= np.linalg.norm(direction_camera)
    direction_world = camera["camera_to_world"][:3, :3] @ direction_camera
    direction_world /= np.linalg.norm(direction_world)
    return camera["center"], direction_world


def closest_point_to_rays(rays: list[tuple[np.ndarray, np.ndarray]]) -> np.ndarray:
    a = np.zeros((3, 3), dtype=np.float64)
    b = np.zeros(3, dtype=np.float64)
    identity = np.eye(3)
    for origin, direction in rays:
        projection = identity - np.outer(direction, direction)
        a += projection
        b += projection @ origin
    return np.linalg.solve(a, b)


def project_points(points: np.ndarray, camera: dict[str, np.ndarray], image_shape: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    homog = np.c_[points, np.ones(len(points))]
    cam = (camera["world_to_camera"] @ homog.T).T[:, :3]
    in_front = cam[:, 2] > 0.02
    norm = cam[:, :2] / cam[:, 2:3]
    pixels, _ = cv2.projectPoints(
        np.c_[norm, np.ones(len(norm))],
        np.zeros(3),
        np.zeros(3),
        camera["k"],
        camera["dist"],
    )
    pixels = pixels.reshape(-1, 2)
    width, height = image_shape[1], image_shape[0]
    inside = (
        in_front
        & (pixels[:, 0] >= 0)
        & (pixels[:, 0] < width)
        & (pixels[:, 1] >= 0)
        & (pixels[:, 1] < height)
    )
    return pixels, inside


def carve(
    masks: dict[str, np.ndarray],
    images: dict[str, np.ndarray],
    cameras: dict[str, dict[str, np.ndarray]],
    center: np.ndarray,
    extent: float,
    resolution: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grid = volume_grid(center, extent, resolution)
    keep = np.ones(len(grid), dtype=bool)
    for camera_id in CAMERAS:
        pixels, inside = project_points(grid, cameras[camera_id], masks[camera_id].shape)
        x = np.clip(np.round(pixels[:, 0]).astype(int), 0, masks[camera_id].shape[1] - 1)
        y = np.clip(np.round(pixels[:, 1]).astype(int), 0, masks[camera_id].shape[0] - 1)
        in_mask = masks[camera_id][y, x] > 0
        keep &= inside & in_mask
    points = grid[keep]
    return color_points(points, images, cameras), points, keep.reshape((resolution, resolution, resolution))


def robust_carve(
    masks: dict[str, np.ndarray],
    images: dict[str, np.ndarray],
    cameras: dict[str, dict[str, np.ndarray]],
    center: np.ndarray,
    extent: float,
    resolution: int,
    min_cameras: int,
    distance_margin: float,
    largest_component: bool,
    uncertain_margin: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    grid = volume_grid(center, extent, resolution)
    votes = np.zeros(len(grid), dtype=np.int16)
    score = np.zeros(len(grid), dtype=np.float32)

    distance_maps = {}
    for camera_id, mask in masks.items():
        inside = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, 5)
        outside = cv2.distanceTransform((mask == 0).astype(np.uint8), cv2.DIST_L2, 5)
        distance_maps[camera_id] = inside - outside

    for camera_id in CAMERAS:
        pixels, visible = project_points(grid, cameras[camera_id], masks[camera_id].shape)
        x = np.clip(np.round(pixels[:, 0]).astype(int), 0, masks[camera_id].shape[1] - 1)
        y = np.clip(np.round(pixels[:, 1]).astype(int), 0, masks[camera_id].shape[0] - 1)
        signed_distance = distance_maps[camera_id][y, x]
        accepted = visible & (signed_distance >= -distance_margin)
        uncertain = visible & (np.abs(signed_distance) <= uncertain_margin)
        accepted |= uncertain
        votes += accepted.astype(np.int16)
        score += np.clip(signed_distance, -30, 30)

    keep = votes >= min_cameras
    if largest_component:
        keep = keep_largest_component(keep.reshape((resolution, resolution, resolution))).reshape(-1)

    points = grid[keep]
    return color_points(points, images, cameras), points, keep.reshape((resolution, resolution, resolution))


def keep_largest_component(volume: np.ndarray) -> np.ndarray:
    volume_u8 = volume.astype(np.uint8)
    visited = np.zeros_like(volume_u8, dtype=bool)
    best_component: list[tuple[int, int, int]] = []
    neighbors = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
    filled = np.argwhere(volume_u8 > 0)
    shape = volume_u8.shape

    for start in map(tuple, filled):
        if visited[start]:
            continue
        stack = [start]
        visited[start] = True
        component = []
        while stack:
            point = stack.pop()
            component.append(point)
            for dx, dy, dz in neighbors:
                nxt = (point[0] + dx, point[1] + dy, point[2] + dz)
                if (
                    0 <= nxt[0] < shape[0]
                    and 0 <= nxt[1] < shape[1]
                    and 0 <= nxt[2] < shape[2]
                    and volume_u8[nxt]
                    and not visited[nxt]
                ):
                    visited[nxt] = True
                    stack.append(nxt)
        if len(component) > len(best_component):
            best_component = component

    result = np.zeros_like(volume_u8, dtype=bool)
    for point in best_component:
        result[point] = True
    return result


def color_points(
    points: np.ndarray,
    images: dict[str, np.ndarray],
    cameras: dict[str, dict[str, np.ndarray]],
) -> np.ndarray:
    colors = np.zeros((len(points), 3), dtype=np.uint8)
    if len(points):
        color_sum = np.zeros((len(points), 3), dtype=np.float64)
        color_count = np.zeros(len(points), dtype=np.float64)
        for camera_id in CAMERAS:
            pixels, inside = project_points(points, cameras[camera_id], images[camera_id].shape[:2])
            x = np.clip(np.round(pixels[:, 0]).astype(int), 0, images[camera_id].shape[1] - 1)
            y = np.clip(np.round(pixels[:, 1]).astype(int), 0, images[camera_id].shape[0] - 1)
            rgb = images[camera_id][y, x, ::-1].astype(np.float64)
            color_sum[inside] += rgb[inside]
            color_count[inside] += 1
        color_count[color_count == 0] = 1
        colors = np.clip(color_sum / color_count[:, None], 0, 255).astype(np.uint8)
    return colors


def write_ply(path: Path, points: np.ndarray, colors: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii") as file:
        file.write("ply\nformat ascii 1.0\n")
        file.write(f"element vertex {len(points)}\n")
        file.write("property float x\nproperty float y\nproperty float z\n")
        file.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        file.write("end_header\n")
        for point, color in zip(points, colors):
            file.write(f"{point[0]:.6f} {point[1]:.6f} {point[2]:.6f} {int(color[0])} {int(color[1])} {int(color[2])}\n")


def write_masks(output_dir: Path, session_id: str, images: dict[str, np.ndarray], masks: dict[str, np.ndarray]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for camera_id in CAMERAS:
        overlay = images[camera_id].copy()
        overlay[masks[camera_id] > 0] = (0.45 * overlay[masks[camera_id] > 0] + np.array([0, 100, 255]) * 0.55).astype(np.uint8)
        cv2.imwrite(str(output_dir / f"{session_id}_{camera_id}_mask.jpg"), masks[camera_id])
        cv2.imwrite(str(output_dir / f"{session_id}_{camera_id}_overlay.jpg"), overlay)


def shape_prior(points: np.ndarray) -> dict[str, Any]:
    if len(points) < 8:
        return {"classification": "insufficient_points", "point_count": int(len(points))}
    center = points.mean(axis=0)
    centered = points - center
    covariance = np.cov(centered.T)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    axes = eigenvectors[:, order]
    local = centered @ axes
    extents = local.max(axis=0) - local.min(axis=0)
    extents = np.maximum(extents, 1e-9)
    major, middle, minor = extents.tolist()
    major_middle = major / middle
    middle_minor = middle / minor
    major_minor = major / minor

    if major_minor < 1.45:
        classification = "compact_regular"
    elif middle_minor > 2.2:
        classification = "flat_or_plate_like"
    elif major_middle > 1.45 and middle_minor < 1.45:
        classification = "elongated_or_cylindrical"
    elif major_minor < 2.2:
        classification = "relatively_regular"
    else:
        classification = "irregular_or_partial"

    radial = np.linalg.norm(local[:, 1:3], axis=1)
    roughness_ratio = float(np.std(radial) / max(np.mean(radial), 1e-9))
    return {
        "classification": classification,
        "center_m": center.tolist(),
        "principal_extents_m": extents.tolist(),
        "extent_ratios": {
            "major_middle": float(major_middle),
            "middle_minor": float(middle_minor),
            "major_minor": float(major_minor),
        },
        "principal_axes": axes.T.tolist(),
        "roughness_proxy": roughness_ratio,
        "surface_hint": "rough_or_partial" if roughness_ratio > 0.42 else "smooth_or_regular",
    }


def camera_support(points: np.ndarray, masks: dict[str, np.ndarray], cameras: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    support: dict[str, Any] = {}
    if len(points) == 0:
        return {camera_id: {"projected": 0, "inside_mask": 0, "inside_mask_ratio": 0.0} for camera_id in CAMERAS}
    for camera_id in CAMERAS:
        pixels, visible = project_points(points, cameras[camera_id], masks[camera_id].shape)
        x = np.clip(np.round(pixels[:, 0]).astype(int), 0, masks[camera_id].shape[1] - 1)
        y = np.clip(np.round(pixels[:, 1]).astype(int), 0, masks[camera_id].shape[0] - 1)
        in_mask = visible & (masks[camera_id][y, x] > 0)
        projected = int(np.count_nonzero(visible))
        inside_mask = int(np.count_nonzero(in_mask))
        support[camera_id] = {
            "projected": projected,
            "inside_mask": inside_mask,
            "inside_mask_ratio": float(inside_mask / projected) if projected else 0.0,
        }
    return support


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a rough calibrated multi-view visual hull from silhouettes.")
    parser.add_argument("--dataset-dir", default="datasets/object_retry_001", type=Path)
    parser.add_argument("--captures-dir", default="capture_console/captures", type=Path)
    parser.add_argument("--calibration-dir", default="datasets/object_retry_001/calibration", type=Path)
    parser.add_argument("--session-id", default="object_retry_041")
    parser.add_argument("--background-session", help="Optional empty-scene session id for clean background subtraction.")
    parser.add_argument("--output-dir", default="reconstruction/object_retry_001_visual_hull", type=Path)
    parser.add_argument("--threshold", type=int, default=28)
    parser.add_argument("--mask-mode", default="hybrid", choices=("bg", "color", "hybrid"))
    parser.add_argument("--seed-bbox-pad", type=int, default=90, help="Limit hybrid mask growth to seed bounding box plus this many pixels. Use -1 to disable.")
    parser.add_argument("--extent", type=float, default=0.45, help="Voxel cube side length in meters.")
    parser.add_argument("--resolution", type=int, default=96, help="Voxel resolution per axis.")
    parser.add_argument("--min-cameras", type=int, default=3, help="Minimum camera silhouette votes required.")
    parser.add_argument("--distance-margin", type=float, default=0, help="Allowed pixels outside a silhouette boundary.")
    parser.add_argument("--uncertain-margin", type=float, default=0, help="Pixels near a silhouette boundary treated as uncertain/accepted.")
    parser.add_argument("--largest-component", action="store_true", help="Keep only the largest connected voxel component.")
    parser.add_argument("--suppress-shadows", action="store_true", help="Remove shadow-like darker pixels before silhouette cleanup.")
    parser.add_argument("--shadow-drop", type=int, default=28, help="Minimum value drop used by --suppress-shadows.")
    parser.add_argument("--shadow-value-max", type=int, default=82, help="Dark low-saturation pixels below this value are removed unless close to the object color seed.")
    parser.add_argument("--shadow-saturation-max", type=int, default=95, help="Low saturation threshold used by dark shadow cleanup.")
    parser.add_argument("--center-roi-x", type=float, default=1.0, help="Keep only this centered width fraction before mask cleanup.")
    parser.add_argument("--center-roi-y", type=float, default=1.0, help="Keep only this centered height fraction before mask cleanup.")
    parser.add_argument("--roi-config", type=Path, help="Optional per-camera ROI box JSON. Areas outside the box are ignored.")
    parser.add_argument("--volume-smooth-iterations", type=int, default=0, help="Constrained majority smoothing iterations for the occupied voxel volume.")
    parser.add_argument("--volume-open-iterations", type=int, default=0, help="Constrained 3D opening iterations to remove isolated voxels and small spikes.")
    parser.add_argument("--regularize-shape", default="none", choices=("none", "auto", "ellipsoid", "cylinder", "box"), help="Fit a regular primitive and keep only the part inside the visual hull boundary.")
    args = parser.parse_args()

    sessions = dataset_sessions(args.dataset_dir)
    cameras = {camera_id: camera_data(args.calibration_dir, camera_id) for camera_id in CAMERAS}
    backgrounds = load_backgrounds(args.dataset_dir, args.captures_dir, sessions, args.background_session)
    images = {camera_id: load_image(args.dataset_dir, args.captures_dir, args.session_id, camera_id) for camera_id in CAMERAS}
    roi_config = load_roi_config(args.roi_config)
    roi_masks = {
        camera_id: box_roi_mask(images[camera_id].shape[:2], roi_config[camera_id]) if camera_id in roi_config else None
        for camera_id in CAMERAS
    }
    masks = {
        camera_id: foreground_mask(
            images[camera_id],
            backgrounds[camera_id],
            args.threshold,
            args.mask_mode,
            args.seed_bbox_pad,
            args.suppress_shadows,
            args.shadow_drop,
            args.center_roi_x,
            args.center_roi_y,
            roi_masks[camera_id],
            args.shadow_value_max,
            args.shadow_saturation_max,
        )
        for camera_id in CAMERAS
    }

    rays = []
    centroids = {}
    for camera_id in CAMERAS:
        centroid = mask_centroid(masks[camera_id])
        centroids[camera_id] = centroid
        if centroid is not None:
            rays.append(pixel_ray(cameras[camera_id], centroid))
    if len(rays) < 2:
        raise SystemExit("Not enough foreground masks to estimate object center.")
    center = closest_point_to_rays(rays)

    if args.min_cameras == len(CAMERAS) and args.distance_margin <= 0 and not args.largest_component:
        colors, points, volume = carve(masks, images, cameras, center, args.extent, args.resolution)
    else:
        colors, points, volume = robust_carve(
            masks,
            images,
            cameras,
            center,
            args.extent,
            args.resolution,
            args.min_cameras,
            args.distance_margin,
            args.largest_component,
            args.uncertain_margin,
        )
    raw_point_count = int(len(points))
    regularized_shape = "none"
    if args.volume_smooth_iterations > 0 or args.volume_open_iterations > 0:
        volume = smooth_volume(volume, args.volume_smooth_iterations, args.volume_open_iterations)
    if args.regularize_shape != "none":
        volume, regularized_shape = regularize_shape_volume(volume, center, args.extent, args.resolution, args.regularize_shape)
    if (
        args.volume_smooth_iterations > 0
        or args.volume_open_iterations > 0
        or args.regularize_shape != "none"
    ):
        points = points_from_volume(volume, center, args.extent, args.resolution)
        colors = color_points(points, images, cameras)
    output_ply = args.output_dir / f"{args.session_id}_visual_hull.ply"
    write_ply(output_ply, points, colors)
    write_masks(args.output_dir / "masks", args.session_id, images, masks)

    summary = {
        "ok": len(points) > 0,
        "session_id": args.session_id,
        "background_session": args.background_session,
        "output_ply": str(output_ply),
        "point_count": int(len(points)),
        "center_reference_m": center.tolist(),
        "extent_m": args.extent,
        "resolution": args.resolution,
        "mask_mode": args.mask_mode,
        "seed_bbox_pad": args.seed_bbox_pad,
        "min_cameras": args.min_cameras,
        "distance_margin": args.distance_margin,
        "uncertain_margin": args.uncertain_margin,
        "largest_component": args.largest_component,
        "suppress_shadows": args.suppress_shadows,
        "shadow_drop": args.shadow_drop,
        "shadow_value_max": args.shadow_value_max,
        "shadow_saturation_max": args.shadow_saturation_max,
        "center_roi_x": args.center_roi_x,
        "center_roi_y": args.center_roi_y,
        "roi_config": str(args.roi_config) if args.roi_config else None,
        "raw_point_count": raw_point_count,
        "volume_smooth_iterations": args.volume_smooth_iterations,
        "volume_open_iterations": args.volume_open_iterations,
        "regularize_shape": args.regularize_shape,
        "regularized_shape": regularized_shape,
        "fill_ratio": float(np.count_nonzero(volume) / volume.size),
        "mask_pixels": {camera_id: int(np.count_nonzero(mask)) for camera_id, mask in masks.items()},
        "centroids": centroids,
        "camera_support": camera_support(points, masks, cameras),
        "shape_prior": shape_prior(points),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "visual_hull_summary.json").open("w", encoding="utf-8") as file:
        json.dump(summary, file, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
