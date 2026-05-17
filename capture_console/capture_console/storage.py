from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .settings import captures_dir


def new_session_id() -> str:
    return datetime.now().strftime("session_%Y%m%d_%H%M%S")


def session_dir(session_id: str) -> Path:
    safe_id = "".join(ch for ch in session_id if ch.isalnum() or ch in ("-", "_"))
    if not safe_id:
        raise ValueError("session_id cannot be empty")
    root = captures_dir() / safe_id
    (root / "raw").mkdir(parents=True, exist_ok=True)
    (root / "meta").mkdir(parents=True, exist_ok=True)
    return root


def save_upload(
    *,
    session_id: str,
    camera_id: str,
    image_bytes: bytes,
    image_format: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    root = session_dir(session_id)
    safe_camera = "".join(ch for ch in camera_id if ch.isalnum() or ch in ("-", "_"))
    extension = image_format.lower().lstrip(".") or "jpg"
    image_path = root / "raw" / f"{safe_camera}.{extension}"
    meta_path = root / "meta" / f"{safe_camera}.json"

    image_path.write_bytes(image_bytes)
    metadata = {
        **metadata,
        "session_id": session_id,
        "camera_id": camera_id,
        "format": extension,
        "size_bytes": len(image_bytes),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "image_path": str(image_path),
    }
    with meta_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)

    return {"image_path": str(image_path), "meta_path": str(meta_path), "metadata": metadata}


def list_sessions() -> list[dict[str, Any]]:
    root = captures_dir()
    sessions: list[dict[str, Any]] = []
    for path in sorted(root.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        raw_files = list((path / "raw").glob("*")) if (path / "raw").exists() else []
        sessions.append({"session_id": path.name, "image_count": len(raw_files), "path": str(path)})
    return sessions


def session_summary(session_id: str) -> dict[str, Any]:
    root = session_dir(session_id)
    raw_dir = root / "raw"
    meta_dir = root / "meta"
    images = []
    for image_path in sorted(raw_dir.glob("*")):
        meta_path = meta_dir / f"{image_path.stem}.json"
        metadata = {}
        if meta_path.exists():
            with meta_path.open("r", encoding="utf-8") as file:
                metadata = json.load(file)
        images.append({"camera_id": image_path.stem, "image_path": str(image_path), "metadata": metadata})
    return {"session_id": session_id, "path": str(root), "images": images}

