from __future__ import annotations

from pathlib import Path


def basic_image_check(image_path: Path) -> dict[str, object]:
    size = image_path.stat().st_size if image_path.exists() else 0
    suffix = image_path.suffix.lower()
    issues: list[str] = []
    if size == 0:
        issues.append("empty_file")
    if suffix not in {".jpg", ".jpeg", ".png"}:
        issues.append("unexpected_extension")
    return {
        "path": str(image_path),
        "size_bytes": size,
        "extension": suffix.lstrip("."),
        "ok": not issues,
        "issues": issues,
    }

