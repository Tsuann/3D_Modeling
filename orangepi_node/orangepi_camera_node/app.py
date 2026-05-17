from __future__ import annotations

import json
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATHS = (ROOT / "config.local.json", ROOT / "config.json", ROOT / "config.example.json")

app = FastAPI(title="OrangePi Camera Node", version="0.1.0")


def load_config() -> dict[str, Any]:
    for path in CONFIG_PATHS:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("missing config file")


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def timestamp_ms() -> int:
    return int(time.time() * 1000)


def open_camera(config: dict[str, Any]) -> cv2.VideoCapture:
    index = int(config.get("camera_index", 0))
    backend = str(config.get("capture_backend", "auto")).lower()
    if backend == "v4l2":
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    else:
        cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        raise RuntimeError(f"failed to open camera index {index}")

    width = int(config.get("width", 0) or 0)
    height = int(config.get("height", 0) or 0)
    if width > 0:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height > 0:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def capture_jpeg(config: dict[str, Any]) -> tuple[bytes, int, int]:
    cap = open_camera(config)
    try:
        warmup_frames = int(config.get("warmup_frames", 3))
        frame = None
        ok = False
        for _ in range(max(1, warmup_frames + 1)):
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.05)
        if not ok or frame is None:
            raise RuntimeError("failed to read frame from camera")

        height, width = frame.shape[:2]
        quality = int(config.get("jpeg_quality", 95))
        encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
        ok, encoded = cv2.imencode(".jpg", frame, encode_params)
        if not ok:
            raise RuntimeError("failed to encode jpeg")
        return encoded.tobytes(), width, height
    finally:
        cap.release()


def build_upload_url(upload_url: str, params: dict[str, Any]) -> str:
    separator = "&" if urllib.parse.urlparse(upload_url).query else "?"
    return upload_url + separator + urllib.parse.urlencode(params)


def upload_jpeg(upload_url: str, jpeg: bytes, params: dict[str, Any]) -> tuple[bool, str]:
    url = build_upload_url(upload_url, params)
    request = urllib.request.Request(
        url,
        data=jpeg,
        headers={
            "Content-Type": "image/jpeg",
            "X-Device-Type": "orangepi_usb",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=15) as response:
        status_line = f"HTTP/{response.version / 10:.1f} {response.status} {response.reason}"
        response.read()
        return 200 <= response.status < 300, status_line


@app.get("/status")
def status() -> dict[str, Any]:
    config = load_config()
    return {
        "ok": True,
        "camera_id": config.get("camera_id", "cam_orangepi"),
        "model": config.get("model", "orangepi_usb_opencv"),
        "ip": local_ip(),
        "camera_index": config.get("camera_index", 0),
        "width": config.get("width"),
        "height": config.get("height"),
        "format": "jpg",
    }


@app.post("/capture")
def capture(payload: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    session_id = payload.get("session_id")
    upload_url = payload.get("upload_url")
    camera_id = payload.get("camera_id") or config.get("camera_id", "cam_orangepi")
    requested_format = payload.get("requested_format", "jpg")

    if not session_id:
        raise HTTPException(status_code=400, detail="missing session_id")
    if not upload_url:
        raise HTTPException(status_code=400, detail="missing upload_url")
    if requested_format not in ("jpg", "jpeg"):
        raise HTTPException(status_code=400, detail="unsupported requested_format")

    start = time.monotonic()
    try:
        jpeg, width, height = capture_jpeg(config)
        ts_ms = timestamp_ms()
        upload_ok, upload_status = upload_jpeg(
            upload_url,
            jpeg,
            {
                "camera_id": camera_id,
                "session_id": session_id,
                "format": "jpg",
                "width": width,
                "height": height,
                "timestamp_ms": ts_ms,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "ok": upload_ok,
        "camera_id": camera_id,
        "session_id": session_id,
        "bytes": len(jpeg),
        "width": width,
        "height": height,
        "timestamp_ms": ts_ms,
        "elapsed_ms": elapsed_ms,
        "upload_status": upload_status,
    }


def main() -> None:
    config = load_config()
    uvicorn.run(
        "orangepi_camera_node.app:app",
        host=str(config.get("host", "0.0.0.0")),
        port=int(config.get("port", 8080)),
        reload=False,
    )


if __name__ == "__main__":
    main()
