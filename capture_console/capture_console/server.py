from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI, Header, Query, Request

from .http_client import request_json
from .settings import load_config, load_devices, public_base_url
from .storage import list_sessions, new_session_id, save_upload, session_summary

app = FastAPI(title="3D Modeling Capture Console", version="0.1.0")


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "service": "capture_console"}


@app.get("/api/devices")
def devices(include_disabled: bool = False) -> dict[str, Any]:
    return {"devices": load_devices(include_disabled=include_disabled)}


@app.get("/api/sessions")
def sessions() -> dict[str, Any]:
    return {"sessions": list_sessions()}


@app.get("/api/session/{session_id}")
def get_session(session_id: str) -> dict[str, Any]:
    return session_summary(session_id)


@app.post("/api/upload")
async def upload(
    request: Request,
    camera_id: str = Query(...),
    session_id: str = Query(...),
    timestamp_ms: int | None = Query(default=None),
    width: int | None = Query(default=None),
    height: int | None = Query(default=None),
    image_format: str = Query(default="jpg", alias="format"),
    x_device_type: str | None = Header(default=None),
) -> dict[str, Any]:
    image_bytes = await request.body()
    metadata = {
        "timestamp_ms": timestamp_ms,
        "width": width,
        "height": height,
        "device_type": x_device_type,
        "content_type": request.headers.get("content-type"),
    }
    result = save_upload(
        session_id=session_id,
        camera_id=camera_id,
        image_bytes=image_bytes,
        image_format=image_format,
        metadata=metadata,
    )
    return {"ok": True, **result}


@app.post("/api/capture")
async def capture(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    config = load_config()
    session_id = payload.get("session_id") or new_session_id()
    upload_url = payload.get("upload_url") or f"{public_base_url()}/api/upload"
    timeout = float(config.get("capture", {}).get("device_timeout_sec", 10))
    devices = load_devices(include_disabled=False)

    async def trigger(device: dict[str, Any]) -> dict[str, Any]:
        base_url = device["base_url"].rstrip("/")
        body = {
            "session_id": session_id,
            "camera_id": device["camera_id"],
            "upload_url": upload_url,
            "requested_format": config.get("capture", {}).get("default_image_format", "jpg"),
        }
        result = await asyncio.to_thread(request_json, "POST", f"{base_url}/capture", body, timeout)
        return {"camera_id": device["camera_id"], "base_url": base_url, "result": result}

    results = await asyncio.gather(*(trigger(device) for device in devices))
    return {"ok": True, "session_id": session_id, "upload_url": upload_url, "triggered": results}

