from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_DIR / "config.json"
DEVICE_REGISTRY_PATH = PROJECT_DIR / "device_registry.json"


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return default or {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_config() -> dict[str, Any]:
    return load_json(CONFIG_PATH)


def captures_dir() -> Path:
    config = load_config()
    configured = config.get("storage", {}).get("captures_dir", "captures")
    path = Path(configured)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_base_url() -> str:
    config = load_config()
    server = config.get("server", {})
    host = server.get("host", "127.0.0.1")
    if host == "0.0.0.0":
        host = "127.0.0.1"
    return f"http://{host}:{server.get('port', 8000)}"


def load_devices(include_disabled: bool = False) -> list[dict[str, Any]]:
    registry = load_json(DEVICE_REGISTRY_PATH, {"devices": []})
    devices = registry.get("devices", [])
    if include_disabled:
        return devices
    return [device for device in devices if device.get("enabled", True)]

