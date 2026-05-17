# OrangePi Codex Handoff

You are continuing the 3D Modeling project on the OrangePi Linux desktop.

Read these files first:

```text
../PROJECT_CONTEXT.md
README.md
config.example.json
orangepi_camera_node/app.py
```

Goal:

Implement and validate the OrangePi USB camera node so Windows `capture_console` can trigger still-image capture over LAN.

Required contract:

```text
GET  /status
POST /capture
```

Expected `GET /status` fields:

```json
{
  "ok": true,
  "camera_id": "cam_orangepi",
  "model": "orangepi_usb_opencv",
  "ip": "ORANGEPI_IP",
  "camera_index": 0
}
```

Expected `POST /capture` body from Windows:

```json
{
  "session_id": "session_20260517_153000",
  "camera_id": "cam_orangepi",
  "upload_url": "http://WINDOWS_LAN_IP:8000/api/upload",
  "requested_format": "jpg"
}
```

Device behavior:

1. Capture one frame from USB camera.
2. Encode JPEG with quality 95 unless config says otherwise.
3. Upload raw JPEG bytes to `upload_url` with query metadata:

```text
camera_id
session_id
format=jpg
width
height
timestamp_ms
```

4. Return JSON including `ok`, `camera_id`, `session_id`, `width`, `height`, `bytes`, `elapsed_ms`, and `upload_status`.

Suggested validation:

1. `curl http://127.0.0.1:8080/status`
2. Trigger one local `POST /capture` to Windows.
3. On Windows, run `python -m capture_console.cli check orangepi_manual_001`.
4. Enable only `cam_orangepi` in `device_registry.json` and run `capture_console.cli ping`.
5. Run 30 captures and record success/failure in `PROJECT_CONTEXT.md`.

Do not commit captured images or `.venv`.
