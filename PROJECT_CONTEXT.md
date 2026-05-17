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

OrangePi preparation on 2026-05-17:

- Created `orangepi_node` for the OrangePi 5 Ultra Linux desktop environment.
- Added a FastAPI + OpenCV USB camera node prototype:
  - `orangepi_node/orangepi_camera_node/app.py`
  - `orangepi_node/config.json`
  - `orangepi_node/config.example.json`
  - `orangepi_node/requirements.txt`
  - `orangepi_node/run.sh`
  - `orangepi_node/README.md`
  - `orangepi_node/ORANGEPI_CODEX_HANDOFF.md`
- OrangePi node contract matches the other devices: `GET /status`, `POST /capture`, JPEG upload to Windows `/api/upload`.
- Default OrangePi service URL will be `http://ORANGEPI_IP:8080`.
- Default OrangePi capture config: `camera_id=cam_orangepi`, `camera_index=0`, `1280x720`, JPEG quality `95`, warmup frames `3`.
- Recommended OrangePi first steps:
  1. Clone/pull `https://github.com/Tsuann/3D_Modeling.git`.
  2. Open `orangepi_node/ORANGEPI_CODEX_HANDOFF.md` in VS Code/Codex.
  3. Install `python3-opencv`, `v4l-utils`, FastAPI, and Uvicorn.
  4. Run `python -m orangepi_camera_node.app`.
  5. Test `curl http://127.0.0.1:8080/status`.
  6. Enable `cam_orangepi` in Windows `capture_console/device_registry.json` once the OrangePi IP is known.
- OrangePi node has passed local syntax compile on Windows, but has not yet been validated on OrangePi hardware or with a real USB camera.
- OrangePi hardware validation on 2026-05-17:
  - Device URL: `http://192.168.31.38:8080`.
  - Windows LAN upload URL used successfully: `http://192.168.31.174:8000/api/upload`.
  - `GET /status` returned OK with `camera_id=cam_orangepi`, `ip=192.168.31.38`, `camera_index=1`, `camera_device=/dev/video1`, `camera_source=/dev/video1`, `1280x720`, `capture_backend=v4l2`, `fourcc=MJPG`, `camera_fps=30`, and `format=jpg`.
  - Manual `POST /capture` succeeded for `session_id=orangepi_hw_001`: `1280x720`, `91826` bytes, `elapsed_ms=1375`, upload response `HTTP/1.1 200 OK`, saved JPEG passed `capture_console.cli check`.
  - 10-shot OrangePi direct stability test succeeded: 10/10 `/capture` responses returned `ok=true`; 10/10 uploads returned `HTTP/1.1 200 OK`; 10/10 saved JPEGs passed `capture_console.cli check`.
  - 10-shot stats: image size range `91763-93165` bytes; device-reported elapsed range `1144-1383 ms`.

Three-device joint capture validation on 2026-05-17:

- All three enabled devices responded to `capture_console.cli ping` with `ok=true`:
  - `cam_esp32s3` at `http://192.168.31.250`, `640x480`.
  - `cam_k230` at `http://192.168.31.92`, `800x480`, display ready.
  - `cam_orangepi` at `http://192.168.31.38:8080`, `/dev/video1`, `1280x720`, MJPG.
- Single joint capture succeeded for `session_id=multi_hw_001`: all three devices returned success, all three uploads completed, and all three saved JPEGs passed `capture_console.cli check`.
- 30-shot joint stability test succeeded for sessions `multi_stability_001` through `multi_stability_030`: 30/30 capture commands returned `ok=true`, 30/30 sessions had 3 saved JPEG files, and 30/30 sessions passed `capture_console.cli check`.
- 30-shot saved image stats:
  - `cam_esp32s3`: 30 files, `640x480`, size range `7442-7827` bytes, average `7726.2` bytes.
  - `cam_k230`: 30 files, `800x480`, size range `105508-159717` bytes, average `134926` bytes.
  - `cam_orangepi`: 30 files, `1280x720`, size range `93385-96766` bytes, average `94770.3` bytes.
- 30-shot device-reported elapsed ranges from capture responses:
  - `cam_k230`: `175-987 ms`.
  - `cam_orangepi`: `1129-1327 ms`.
  - ESP32 response does not currently report `elapsed_ms`.

Calibration preview on 2026-05-17:

- Captured `calib_preview_001` with all three devices.
- `capture_console.cli check calib_preview_001` passed for all three saved JPEGs.
- Visual review:
  - `cam_esp32s3`: Charuco board visible, but lower in frame and relatively small/soft; for formal calibration, move the board closer/larger in the ESP32 view when possible.
  - `cam_k230`: Charuco board clearly visible.
  - `cam_orangepi`: Charuco board clearly visible.
- Board text visible in OrangePi frame indicates an `8x11` board, checker size `20 mm`, marker size `15 mm`, ArUco dictionary `DICT_5X5`.
- Added `capture_console.cli calib-collect` for interactive calibration capture:
  - Example formal collection command: `python -m capture_console.cli calib-collect --count 40 --upload-url http://192.168.31.174:8000/api/upload --stop-on-failure`.
  - The command waits for Enter before each capture, auto-increments session IDs like `calib_001`, triggers all enabled devices, checks the saved images, and prints a final summary.
  - Automatic mode is available with `--auto --delay-sec 3`.
  - End-to-end script test passed for `calib_script_test_001`: 3/3 images saved and checked.

Calibration progress on 2026-05-17:

- User captured 40 formal calibration sessions, `calib_001` through `calib_040`; each session has 3 saved raw JPEGs.
- Added `calibration/calibrate_charuco.py` for OpenCV Charuco calibration.
- Board configuration used by the script:
  - OpenCV `CharucoBoard((11, 8), 0.020, 0.015, DICT_5X5_50)`.
  - `legacy_pattern=True`.
  - This matches the physical board text showing `8x11`, checker size `20 mm`, marker size `15 mm`, dictionary `DICT_5X5`.
- First calibration run with `--min-corners 12` wrote outputs under `calibration/output`:
  - `cam_esp32s3`: 7 valid views, RMS about `0.977 px`.
  - `cam_k230`: 30 valid views, RMS about `1.163 px`.
  - `cam_orangepi`: 40 valid views, RMS about `1.139 px`.
  - Pair valid view counts: ESP32/K230 `3`, ESP32/OrangePi `7`, K230/OrangePi `30`.
- Diagnostic run with `--min-corners 6` wrote outputs under `calibration/output_min6`:
  - `cam_esp32s3`: 10 valid views, RMS about `0.955 px`.
  - `cam_k230`: 30 valid views, RMS about `1.163 px`.
  - `cam_orangepi`: 40 valid views, RMS about `1.139 px`.
  - Pair valid view counts: ESP32/K230 `6`, ESP32/OrangePi `10`, K230/OrangePi `30`.
- Interpretation:
  - K230 and OrangePi calibration data is usable.
  - ESP32 data is currently sparse; its intrinsic result is only a rough first pass, and ESP32 extrinsics are not stable enough for final rig calibration.
  - Best ESP32 detections were around `calib_017`, `calib_018`, `calib_020`, `calib_022`, `calib_023`, and `calib_024`; future supplemental captures should mimic those board positions but add more left/right/up/down variation.
- Supplemental calibration captures were added for `calib_041` through `calib_070`; each session has 3 saved raw JPEGs.
- User noted two expected limitations:
  - ESP32 camera quality/resolution is much weaker than K230 and OrangePi, so its Charuco detection quality will naturally be worse.
  - ESP32 and K230 are close to the same line of sight, so direct ESP32/K230 common calibration views are hard to collect.
- Updated calibration with all `calib_001` through `calib_070`:
  - `calibration/output_updated` with `cam_k230` as reference:
    - `cam_esp32s3`: 27 valid views, RMS about `1.115 px`.
    - `cam_k230`: 39 valid views, RMS about `1.179 px`.
    - `cam_orangepi`: 69 valid views, RMS about `1.237 px`.
    - Pair valid view counts: ESP32/K230 `4`, ESP32/OrangePi `27`, K230/OrangePi `38`.
  - `calibration/output_updated_orangepi_ref` with `cam_orangepi` as reference is preferred for current geometry:
    - ESP32 to OrangePi uses 27 direct common views.
    - K230 to OrangePi uses 38 direct common views.
    - This avoids relying on the weak ESP32/K230 direct pair.
  - Preferred current calibration outputs:
    - `calibration/output_updated_orangepi_ref/calibration_report.json`
    - `calibration/output_updated_orangepi_ref/intrinsics/*.json`
    - `calibration/output_updated_orangepi_ref/extrinsics/rig_extrinsics.json`

Object capture workflow on 2026-05-17:

- Added `capture_console.cli collect` for non-calibration object/scene capture.
- The command shares the same capture/check loop as `calib-collect`, but defaults to `object_` session IDs and object-oriented prompts.
- Example interactive command:
  - `python -m capture_console.cli collect --prefix object_test_ --start 1 --count 60 --upload-url http://192.168.31.174:8000/api/upload --stop-on-failure`
- Example automatic command:
  - `python -m capture_console.cli collect --prefix object_test_ --start 1 --count 60 --auto --delay-sec 3 --upload-url http://192.168.31.174:8000/api/upload --stop-on-failure`
- End-to-end script test passed for `object_script_test_001`: 3/3 images saved and checked.

Object dataset progress on 2026-05-17:

- User captured `object_test_001` through `object_test_060`; each session has 3 saved raw JPEGs.
- Full `capture_console.cli check` pass: 60/60 sessions OK, 180/180 images OK.
- Added `datasets/export_capture_dataset.py` to export numbered capture sessions into a reconstruction dataset.
- Exported `datasets/object_test_001`:
  - `images/`: 180 flattened JPEGs, 60 per camera.
  - `metadata/`: per-image metadata JSON files.
  - `calibration/`: copied from preferred `calibration/output_updated_orangepi_ref`.
  - `manifest.json`: dataset manifest with source session/camera mapping.
- Quick visual review of `object_test_001`:
  - ESP32, K230, and OrangePi all see the object.
  - OrangePi view has the object relatively small and a bright desk reflection/overexposed area, which may reduce feature matching quality.

Reconstruction progress on 2026-05-17:

- No `colmap`, `meshroom_batch`, or OpenMVG executables were found on PATH.
- Chocolatey has `meshroom 2025.1.0`, but `choco install meshroom -y` failed because the shell was not elevated and Chocolatey could not access its `C:\ProgramData\chocolatey\lib` lock/lib-bad paths.
- Installed user-level `pycolmap 4.0.4` from official PyPI successfully.
- Added `datasets/reconstruction_diagnostics.py`:
  - Ran diagnostics on `datasets/object_test_001` with `--sample-every 3`.
  - Output: `datasets/object_test_001/diagnostics/reconstruction_diagnostics.json`.
  - Contact sheet: `datasets/object_test_001/diagnostics/contact_sheet.jpg`.
  - SIFT feature summary showed K230 has the clearest images, ESP32 is weaker, OrangePi has significant overexposed desk area.
  - Cross-camera good matches are low: ESP32/K230 average about `7.55`, ESP32/OrangePi average about `4.15`, K230/OrangePi average about `18.85` on sampled sessions.
- Added `reconstruction/pycolmap_reconstruct.py`:
  - First K230-only pycolmap sparse run output: `reconstruction/object_test_001_cam_k230`.
  - Result: 1 sparse model, 5/60 registered images, 163 sparse points, mean reprojection error about `0.335 px`.
  - Exported PLY: `reconstruction/object_test_001_cam_k230/sparse_points.ply`.
  - Cropped K230 run output: `reconstruction/object_test_001_cam_k230_crop`.
  - Cropped result was worse: 2 registered images, 6 sparse points.
- Added `reconstruction/triangulate_known_rig.py`:
  - `object_test_001` had too few cross-camera matches for triangulation.
  - Best sampled K230/OrangePi match session was `object_test_052`.
  - Known-rig triangulation for `object_test_052` succeeded with 17 sparse points.
  - Output PLY: `reconstruction/object_test_001_known_rig_052/object_test_052_sparse_known_rig.ply`.
- Interpretation:
  - The pipeline can now run diagnostics, pycolmap sparse SfM, and calibrated-rig triangulation.
  - Current object dataset is not sufficient for a strong mesh/reconstruction because the object is small in the frame, the background/table dominates many features, OrangePi has a bright reflection, and cross-camera object matches are sparse.
  - For the next capture, improve by making the object larger in K230/OrangePi views, reducing desk glare, using a larger/more textured object, adding a matte non-repeating background, or adding a controlled turntable with known angle increments and masks.

Object retry dataset and reconstruction on 2026-05-17:

- User captured `object_retry_001` through `object_retry_080`; each session has 3 saved raw JPEGs.
- Full `capture_console.cli check` pass: 80/80 sessions OK, 240/240 images OK.
- Exported `datasets/object_retry_001`:
  - `images/`: 240 flattened JPEGs, 80 per camera.
  - `metadata/`: per-image metadata JSON files.
  - `calibration/`: copied from preferred `calibration/output_updated_orangepi_ref`.
  - `manifest.json`: dataset manifest with source session/camera mapping.
- Ran diagnostics:
  - Output: `datasets/object_retry_001/diagnostics/reconstruction_diagnostics.json`.
  - Contact sheet: `datasets/object_retry_001/diagnostics/contact_sheet.jpg`.
  - Visual quality improved versus `object_test_001`: object is larger, desk glare is much lower, and background is cleaner.
  - OrangePi overexposure improved strongly: sampled mean overexposed ratio about `0.00072` versus previous about `0.05865`.
  - Cross-camera feature matches are still sparse: sampled K230/OrangePi good matches average about `13.15`, ESP32/OrangePi about `5.15`, ESP32/K230 about `6.6`.
- Ran K230-only pycolmap on `datasets/object_retry_001`:
  - Output: `reconstruction/object_retry_001_cam_k230`.
  - Result: 1 sparse model, 3/80 registered images, 9 sparse points, mean reprojection error about `0.086 px`.
  - Exported PLY: `reconstruction/object_retry_001_cam_k230/sparse_points.ply`.
- Later algorithm review found a pycolmap configuration issue:
  - The first `pycolmap_reconstruct.py` run used pycolmap `CameraMode.AUTO`, which created separate camera intrinsics per image.
  - For a single physical camera image sequence, this should be `CameraMode.SINGLE`.
  - Updated `reconstruction/pycolmap_reconstruct.py` to support `--camera-mode` and `--matcher`.
  - Re-ran K230 with `--camera-mode single --matcher exhaustive`:
    - Output: `reconstruction/object_retry_001_cam_k230_single_exhaustive`.
    - Result: 2/80 registered images, 262 sparse points, mean reprojection error about `0.193 px`.
    - Exported PLY/viewer: `reconstruction/object_retry_001_cam_k230_single_exhaustive/sparse_points.ply` and `.viewer.html`.
  - Re-ran K230 with `--camera-mode single --matcher sequential`:
    - Output: `reconstruction/object_retry_001_cam_k230_single_sequential`.
    - Result: 2/80 registered images, 263 sparse points, mean reprojection error about `0.217 px`.
  - Interpretation after fix: the algorithm configuration bug was real and improved point count, but most frames still fail to register because the dataset violates standard static-scene SfM assumptions: cameras are fixed, the object rotates/moves, the background is static, and the object has repetitive/symmetric texture.
- User suggested a better reconstruction direction: use calibrated three-view silhouettes to build a coarse layered/voxel shape, then fill/carve from other views instead of relying on sparse feature SfM.
- Implemented first `visual hull / space carving` prototype:
  - Added `reconstruction/visual_hull.py`.
  - Uses median background estimation over the dataset, foreground masks per camera, calibrated camera projection, and voxel carving.
  - Ran on `object_retry_041` with `--extent 0.45 --resolution 96`.
  - Output: `reconstruction/object_retry_001_visual_hull_041/object_retry_041_visual_hull.ply`.
  - Viewer: `reconstruction/object_retry_001_visual_hull_041/object_retry_041_visual_hull.viewer.html`.
  - Result: 3648 occupied voxel points, a much denser coarse shape than the sparse SfM points.
  - Mask overlays saved under `reconstruction/object_retry_001_visual_hull_041/masks`.
  - Current mask issues: K230 includes some shadow; OrangePi includes object plus some mat/table edge, so the hull may be too fat/noisy.
  - Interpretation: the visual hull route matches this fixed multi-camera setup better than vanilla SfM and should be the next main optimization path.
- Implemented a more robust visual hull variant after user suggested a "cut circle" / filled-layer workflow:
  - Updated `reconstruction/visual_hull.py` with:
    - `--min-cameras` for N-of-3 silhouette voting.
    - `--distance-margin` for boundary tolerance using signed distance fields.
    - `--largest-component` to remove floating outlier voxel islands.
  - Strict 3/3 run on `object_retry_041`: 3648 occupied voxels.
  - Robust 2/3 + 4 px margin + largest-component run on `object_retry_041`: 19340 occupied voxels.
  - Robust output: `reconstruction/object_retry_001_visual_hull_041_robust/object_retry_041_visual_hull.ply`.
  - Robust viewer: `reconstruction/object_retry_001_visual_hull_041_robust/object_retry_041_visual_hull.viewer.html`.
  - Also ran representative robust visual hulls at lower resolution for `object_retry_001`, `object_retry_041`, and `object_retry_080`:
    - `object_retry_001`: 16544 voxels.
    - `object_retry_041`: 11169 voxels.
    - `object_retry_080`: 12506 voxels.
  - Interpretation: each three-view session can quickly produce a filled coarse solid. To fuse all object rotations into a final common model, the pipeline needs known or estimated rotation angle/axis per session; otherwise each session represents the object in a different orientation.
- Added further confidence/background experiments:
  - Updated `reconstruction/visual_hull.py` with `--mask-mode bg|color|hybrid`, `--seed-bbox-pad`, and `--uncertain-margin`.
  - `hybrid` mask uses color seeds plus background subtraction to remove stable background while keeping non-orange object parts connected to the colored object.
  - Confidence-style run on `object_retry_041`:
    - Output: `reconstruction/object_retry_001_visual_hull_041_confidence/object_retry_041_visual_hull.ply`.
    - Viewer: `reconstruction/object_retry_001_visual_hull_041_confidence/object_retry_041_visual_hull.viewer.html`.
    - Result: 43540 voxels with `min_cameras=2`, `distance_margin=3`, `uncertain_margin=6`, largest component.
  - Seed-box constrained run:
    - Output: `reconstruction/object_retry_001_visual_hull_041_seedbox/object_retry_041_visual_hull.ply`.
    - Viewer: `reconstruction/object_retry_001_visual_hull_041_seedbox/object_retry_041_visual_hull.viewer.html`.
    - Result: 40657 voxels.
  - Pure color segmentation was tested but over-selected similarly colored background objects, so color alone is not reliable.
  - Current best next data step: capture an explicit empty-background session with the object removed and all cameras fixed, e.g. `background_empty_001`; then run visual hull with `--background-session background_empty_001` for much cleaner foreground masks.
- Ran known-rig triangulation on best sampled K230/OrangePi match session `object_retry_029`:
  - Output PLY: `reconstruction/object_retry_001_known_rig_029/object_retry_029_sparse_known_rig.ply`.
  - Result: 6 sparse points from K230/OrangePi; ESP32/OrangePi had no RANSAC inliers.
- Interpretation:
  - The second dataset is visually better, but the object is a small orange speaker with repetitive mesh texture and symmetry, which confuses traditional SIFT/SfM matching.
  - Traditional photogrammetry still cannot produce a useful mesh from this dataset.
  - Next best options are: add high-contrast non-repeating texture/markers to the object, capture with a fixed camera and a known turntable angle pipeline, segment/mask the object before matching, or try a learning-based method that is less dependent on sparse SIFT matches.

Visual hull update after explicit empty-background capture:

- User captured `background_empty_001` after removing the object; all three raw camera images exist under `capture_console/captures/background_empty_001/raw`.
- Updated `reconstruction/visual_hull.py`:
  - Added `--captures-dir` and fallback image loading so `--background-session background_empty_001` can read raw capture-console sessions directly, without manually exporting/copying the background into the dataset.
  - Added `--suppress-shadows` and `--shadow-drop` to remove shadow-like darker pixels before mask cleanup.
  - Added focused color-seed selection so hybrid masks keep only high-scoring moving/color components instead of every orange/brown background area.
  - Added `shape_prior` to `visual_hull_summary.json` using PCA extents/axis ratios for a rough regular/irregular/elongated/flat classification.
  - Added `camera_support` to show how many final voxels project inside each camera mask.
- Empty-background experiment on `object_retry_041`:
  - 2-of-3 robust run with focused mask and shadow suppression:
    - Output: `reconstruction/object_retry_001_visual_hull_041_emptybg_focused/object_retry_041_visual_hull.ply`
    - Viewer: `reconstruction/object_retry_001_visual_hull_041_emptybg_focused/object_retry_041_visual_hull.viewer.html`
    - Result: `104985` voxels.
    - Shape prior: `relatively_regular`, PCA extents about `0.509 x 0.375 x 0.291 m`.
    - Camera support ratios: ESP32 about `0.604`, K230 about `0.880`, OrangePi about `0.669`.
  - 3-of-3 strict run:
    - Output: `reconstruction/object_retry_001_visual_hull_041_emptybg_focused_3cam/object_retry_041_visual_hull.ply`
    - Viewer: `reconstruction/object_retry_001_visual_hull_041_emptybg_focused_3cam/object_retry_041_visual_hull.viewer.html`
    - Result: `17032` voxels.
    - Camera support ratios: ESP32 about `0.963`, K230 about `0.968`, OrangePi about `0.967`, confirming all three cameras are participating strongly.
- Interpretation:
  - The user-proposed route is feasible: start from a filled primitive/visual hull, classify rough shape, then cut/fill with multi-view silhouettes.
  - The current limiting factor is still 2D foreground segmentation. The `background_empty_001` overlays show background/person/desk-object/exposure differences between the object frame and the empty-background frame, so masks include some non-object regions even after shadow suppression.
  - For the next capture, empty background must be captured with all cameras fixed, no person/body parts in frame, no desk objects moved except removing the target object, and exposure/lighting kept as close as possible to object captures.
- User suggested cropping image edges / marking an object box because the object is mostly in the central area and background edge clutter is hurting masks.
- Updated `reconstruction/visual_hull.py` again:
  - Added `--center-roi-x` and `--center-roi-y` to ignore image borders before foreground masking.
  - Added `--roi-config` for per-camera object boxes.
  - Added `reconstruction/object_retry_041_roi.json` with hand-tuned ROI boxes for `object_retry_041`.
- ROI experiments with refreshed `background_empty_001`:
  - Center ROI only (`0.70 x 0.75`) reduced 2-of-3 result from the previous `104985` voxels to `54618` voxels.
  - Per-camera box ROI result:
    - 2-of-3 output: `reconstruction/object_retry_001_visual_hull_041_emptybg_boxroi_tight_2cam/object_retry_041_visual_hull.viewer.html`, `26575` voxels.
    - 3-of-3 output: `reconstruction/object_retry_001_visual_hull_041_emptybg_boxroi_tight_3cam/object_retry_041_visual_hull.viewer.html`, `10095` voxels.
    - 3-of-3 camera support ratios: ESP32 about `0.961`, K230 about `0.959`, OrangePi about `0.969`.
  - Interpretation: per-camera object ROI is clearly feasible and is currently the best low-cost improvement. It cuts image-edge clutter before 3D carving while preserving the object and its local shadow. Remaining errors are mostly inside-box background/shadow leakage, especially in ESP32 and K230.

Git sync:

- GitHub repository: `https://github.com/Tsuann/3D_Modeling.git`
- Branch: `main`
- Captured images and virtual environments are intentionally ignored by `.gitignore`.

## Next Milestones

1. ESP32-S3 Arduino device endpoint prototype.
2. K230 MicroPython device endpoint prototype.
3. OrangePi USB camera endpoint prototype.
4. Enable one device at a time in `device_registry.json`.
5. Run `ping` and `capture` from Windows console.
6. Collect 50-100 repeated captures and check reliability.
7. Add stronger image quality checks after real images exist.
8. Begin camera calibration workflow.
