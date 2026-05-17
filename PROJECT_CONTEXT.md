# 3D Modeling Project Context

This file is the shared project memory for all sessions working under:

```text
F:\Project\3D_Modeling
```

Update this file whenever hardware, software, interface, or progress changes.

## Project Goal

Build a low-cost multi-camera visual 3D reconstruction system using three heterogeneous camera nodes.

Initial target:

```text
Three fixed cameras capture a static object or small static scene.
The Windows host receives synchronized-ish images, stores them by session,
then later runs calibration and offline reconstruction.
```

The first milestone is not real-time 3D. The first milestone is stable image acquisition over LAN.

## Hardware

Current hardware:

- Windows development host with RTX 2060
- OrangePi 5 Ultra + USB camera
- ESP32-S3 + OV3660 camera
- K230 board + matching camera

Expected roles:

- Windows host: central controller, image receiver, session manager, quality check, later calibration and reconstruction.
- OrangePi 5 Ultra: stronger edge camera node for USB camera acquisition.
- ESP32-S3 + OV3660: lightweight camera node, Arduino-based, suitable for still JPEG capture and upload.
- K230 + camera: MicroPython/CanMV-based camera node, suitable for still JPEG capture and upload, with room for later preprocessing.

## Current Technical Route

Phase 1:

```text
Camera nodes -> LAN HTTP -> Windows capture console -> session folders
```

Phase 2:

```text
OpenCV calibration -> camera intrinsics/extrinsics -> undistorted images
```

Phase 3:

```text
COLMAP / Meshroom / OpenMVG + OpenMVS -> point cloud / mesh / textured model
```

Possible future experiments:

- DUSt3R / MASt3R for camera pose or matching assistance
- NeRF / 3D Gaussian Splatting for realistic view synthesis
- Better hardware synchronization
- Web UI for capture preview and session management

## Windows Capture Console

Created directory:

```text
F:\Project\3D_Modeling\capture_console
```

Current implementation:

- FastAPI backend
- Python CLI
- Device registry
- Session-based image storage
- Basic image file check

Important files:

```text
capture_console/README.md
capture_console/config.json
capture_console/device_registry.json
capture_console/capture_console/server.py
capture_console/capture_console/cli.py
capture_console/capture_console/storage.py
capture_console/capture_console/quality.py
```

Installed local virtual environment:

```text
capture_console/.venv
```

Run server:

```powershell
cd F:\Project\3D_Modeling\capture_console
.\.venv\Scripts\Activate.ps1
python -m capture_console.cli server
```

Useful CLI commands:

```powershell
python -m capture_console.cli devices --all
python -m capture_console.cli ping
python -m capture_console.cli capture --session-id test001 --upload-url http://YOUR_WINDOWS_LAN_IP:8000/api/upload
python -m capture_console.cli sessions
python -m capture_console.cli check latest
```

Validation already done:

- Python compile check passed.
- FastAPI app imports successfully inside `.venv`.
- `/health` returned OK.
- `/api/upload` accepted JPEG bytes.
- Demo upload saved under `capture_console/captures/demo_validation`.
- CLI `check demo_validation` passed.

## Device Interface Contract

Each camera node should expose:

```text
GET /status
POST /capture
```

### GET /status

Example response:

```json
{
  "ok": true,
  "camera_id": "cam_esp32s3",
  "model": "esp32s3_ov3660"
}
```

### POST /capture

Windows capture console sends JSON:

```json
{
  "session_id": "session_20260517_153000",
  "camera_id": "cam_esp32s3",
  "upload_url": "http://192.168.1.10:8000/api/upload",
  "requested_format": "jpg"
}
```

Device behavior:

1. Receive request.
2. Capture one JPEG image.
3. Upload raw JPEG bytes to Windows.
4. Return status JSON.

### Upload To Windows

Device uploads image with:

```text
POST /api/upload?camera_id=cam_esp32s3&session_id=session_20260517_153000&format=jpg&width=1024&height=768&timestamp_ms=1710000000000
Content-Type: image/jpeg
Body: JPEG bytes
```

Recommended metadata:

- `camera_id`
- `session_id`
- `timestamp_ms`
- `width`
- `height`
- `format`
- Optional `X-Device-Type` header

## Storage Layout

Windows stores captures as:

```text
capture_console/captures/
  session_xxx/
    raw/
      cam_esp32s3.jpg
      cam_k230.jpg
      cam_orangepi.jpg
    meta/
      cam_esp32s3.json
      cam_k230.json
      cam_orangepi.json
```

Raw images should always be preserved. Any preprocessing should write to a separate folder later.

## Preprocessing Policy

Early stage preprocessing should be minimal.

Allowed early:

- Consistent image format, preferably JPG quality 90-95
- Consistent or recorded resolution
- Timestamp and camera ID metadata
- Basic file integrity checks
- Later: undistortion after calibration

Avoid early:

- AI upscaling
- Beauty filters
- Strong denoising or sharpening
- Cropping without preserving raw images
- Different enhancement styles per camera

## Device Registry

Edit this file when hardware IPs are known:

```text
capture_console/device_registry.json
```

Set `enabled` to `true` for devices currently being tested.

Default placeholders:

```text
cam_esp32s3  -> http://192.168.1.101
cam_k230     -> http://192.168.1.102
cam_orangepi -> http://192.168.1.103
```

## Development Notes

ESP32-S3 plan:

- Use Arduino.
- Implement Wi-Fi connection.
- Implement `GET /status`.
- Implement `POST /capture`.
- Capture JPEG from OV3660.
- Upload JPEG bytes to Windows `/api/upload`.
- Start with moderate resolution such as 800x600 or 1024x768.

ESP32-S3 progress on 2026-05-17:

- Reused `CameraWebServer` instead of creating a new Arduino project.
- Kept the original preview web server and GET `/capture` JPEG endpoint.
- Added capture console fields to GET `/status`: `ok`, `camera_id`, `model`, and `ip`.
- Added POST `/capture` for the Windows console contract.
- POST `/capture` accepts JSON with `session_id`, `camera_id`, `upload_url`, and `requested_format`.
- Device captures one JPEG frame and uploads it to `upload_url` with query metadata: `camera_id`, `session_id`, `format`, `width`, `height`, and `timestamp_ms`.
- Upload request uses `Content-Type: image/jpeg` and `X-Device-Type: esp32s3`.
- Fixed ESP32 URL encoding so session ids such as `test001` are saved under the intended session path instead of ASCII-number directory names.
- Stability check passed: 30/30 consecutive ESP32 captures uploaded successfully to Windows, and 30/30 saved JPEGs passed `capture_console.cli check`.
- Observed ESP32 capture output during the stability check: 640x480 JPEG, about 13.6 KB per image, about 0.8-1.4 seconds per capture/upload.

K230 plan:

- Use MicroPython / CanMV.
- Implement equivalent status, capture, upload workflow.
- Keep first version simple: still JPEG capture, no heavy preprocessing.

K230 progress on 2026-05-17:

- Created `K230_canMV`.
- Added CanMV MicroPython prototype files:
  - `K230_canMV/config.py`
  - `K230_canMV/main.py`
  - `K230_canMV/README.md`
- K230 prototype connects to 2.4G Wi-Fi, initializes the default CSI2 camera, serves `GET /status`, serves `POST /capture`, captures one JPEG, and uploads raw JPEG bytes to the Windows `/api/upload` endpoint with query metadata.
- Default K230 settings: `camera_id=cam_k230`, `SENSOR_ID=2`, `1024x768`, JPEG quality `95`, HTTP server port `80`.
- First LAN test reached K230 IP `192.168.31.92` by ICMP ping, but TCP port `80` was closed and `/status` timed out, so the board-side HTTP script was not running or had crashed before listening. Updated `main.py` to start HTTP after Wi-Fi and initialize the camera lazily on capture, with `camera_ready` / `camera_error` included in `/status`.
- K230 hardware validation on 2026-05-17:
  - Board IP: `192.168.31.92`.
  - Windows LAN upload URL used successfully: `http://192.168.31.174:8000/api/upload`.
  - `GET /status` returned OK with `camera_ready=false` before first capture.
  - Manual `POST /capture` succeeded for `session_id=k230_manual_002`: `1024x768`, `160968` bytes, upload response `HTTP/1.1 200 OK`.
  - Capture console CLI `capture` succeeded for `session_id=k230_cli_001`: `1024x768`, `160107` bytes, upload response `HTTP/1.1 200 OK`, saved JPEG passed `capture_console.cli check`.
  - CLI `ping` initially timed out because Python `urllib` respected the host proxy environment, while LAN devices should be contacted directly. Updated `capture_console/capture_console/http_client.py` to use `ProxyHandler({})`.
  - Retest after proxy bypass: `cam_k230` `ping` returned `ok=true`, `camera_ready=false`, `wifi_connected=true`, `ip=192.168.31.92`.
  - 10-shot K230 direct stability test: 10/10 JPEG files saved and passed `capture_console.cli check`. One `/capture` response returned HTTP 502 even though the image was saved, likely because K230 did not read the Windows `200 OK` upload response cleanly. Updated `K230_canMV/main.py` to set an upload socket timeout and retry upload once before returning failure.
  - 30-shot K230 stability retest after upload retry: 30/30 `/capture` responses returned `ok=true`; 30/30 raw JPEG + meta files were saved; 30/30 passed `capture_console.cli check`.
  - 30-shot stats: image size range `162966-170316` bytes, average `166901` bytes; device-reported elapsed range `252-2566 ms`, average `398 ms`. The first capture is slower because camera initialization happens lazily.
  - Final `capture_console.cli ping` showed `cam_k230` online with `camera_ready=true`. ESP32 remained enabled and timed out separately.
  - Added display support based on the LCKFB Display example. `K230_canMV/main.py` now imports `media.display`, initializes `Display.ST7701` with `to_ide=True` before `MediaManager.init()`, displays frames with `Display.show_image`, and reports `display_enabled`, `display_ready`, `display_error`, `display_mode`, and `display_to_ide` in `/status`.
  - First display attempt only refreshed after capture and used `select.poll()` in the HTTP loop. On physical K230/CanMV IDE, `select.poll()` raised `IDE interrupt`, causing a soft reboot. Removed `select.poll()`.
  - Current display/preview version uses nonblocking `server.accept()` and refreshes preview while idle. Default preview config: `IMAGE_WIDTH=800`, `IMAGE_HEIGHT=480`, `DISPLAY_ENABLED=True`, `DISPLAY_MODE="LCD"`, `DISPLAY_TO_IDE=True`, `DISPLAY_WIDTH=800`, `DISPLAY_HEIGHT=480`, `DISPLAY_QUALITY=80`, `PREVIEW_ENABLED=True`, `PREVIEW_INTERVAL_MS=300`.
  - The temporary `800x480` capture resolution matches the LCD and reduces memory/display pressure. If higher-resolution raw capture is needed later, implement separate preview and capture channels rather than showing `1024x768` directly on the `800x480` LCD.
  - Display/preview version validated on physical K230: LCD/CanMV IDE display works. `GET /status` returned `ok=true`, `camera_ready=true`, `display_ready=true`, `display_error=""`, response time about 2.04 seconds. `POST /capture` succeeded for `session_id=k230_display_capture_001`: `800x480`, `165104` bytes, upload response `HTTP/1.1 200 OK`, saved JPEG passed `capture_console.cli check`.

OrangePi plan:

- Use Linux + Python/OpenCV or GStreamer.
- Implement equivalent status, capture, upload workflow.
- USB camera likely becomes the most stable/high-quality early reference camera.

## Next Milestones

1. ESP32-S3 Arduino device endpoint prototype.
2. K230 MicroPython device endpoint prototype.
3. OrangePi USB camera endpoint prototype.
4. Enable one device at a time in `device_registry.json`.
5. Run `ping` and `capture` from Windows console.
6. Collect 50-100 repeated captures and check reliability.
7. Add stronger image quality checks after real images exist.
8. Begin camera calibration workflow.
