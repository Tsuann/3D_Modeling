# OrangePi Camera Node

This directory is the handoff package for developing the OrangePi 5 Ultra USB camera node on its Linux desktop system.

The node should expose the same LAN HTTP contract as the ESP32-S3 and K230 nodes:

```text
GET  /status
POST /capture
```

On `POST /capture`, the node captures one JPEG frame from the USB camera and uploads raw JPEG bytes to the Windows capture console:

```text
POST /api/upload?camera_id=cam_orangepi&session_id=...&format=jpg&width=...&height=...&timestamp_ms=...
Content-Type: image/jpeg
Body: JPEG bytes
```

## Quick Start On OrangePi

Clone or pull the repository:

```bash
git clone https://github.com/Tsuann/3D_Modeling.git
cd 3D_Modeling/orangepi_node
```

Install system dependencies:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip python3-opencv v4l-utils
```

Create the Python environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

If `python3-opencv` from apt is not visible inside the venv, either run without a venv or install OpenCV with pip:

```bash
python -m pip install opencv-python-headless
```

Check USB camera devices:

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

Edit local config if needed:

```bash
cp config.example.json config.local.json
nano config.local.json
```

Run the node:

```bash
source .venv/bin/activate
python -m orangepi_camera_node.app
```

Default service URL:

```text
http://ORANGEPI_IP:8080
```

## Windows Capture Console Setup

On Windows, edit:

```text
F:\Project\3D_Modeling\capture_console\device_registry.json
```

Set the OrangePi device:

```json
{
  "camera_id": "cam_orangepi",
  "name": "OrangePi USB Camera",
  "type": "orangepi_usb",
  "base_url": "http://ORANGEPI_IP:8080",
  "enabled": true
}
```

Use the Windows LAN IP in the upload URL, not `127.0.0.1`:

```powershell
python -m capture_console.cli ping
python -m capture_console.cli capture --session-id orangepi_test001 --upload-url http://WINDOWS_LAN_IP:8000/api/upload
python -m capture_console.cli check orangepi_test001
```

## Local OrangePi Tests

Status:

```bash
curl http://127.0.0.1:8080/status
```

Capture and upload to Windows:

```bash
curl -X POST http://127.0.0.1:8080/capture \
  -H 'Content-Type: application/json' \
  -d '{
    "session_id": "orangepi_manual_001",
    "camera_id": "cam_orangepi",
    "upload_url": "http://WINDOWS_LAN_IP:8000/api/upload",
    "requested_format": "jpg"
  }'
```

## Development Notes

- Keep raw camera images minimally processed.
- Prefer recording real width/height over forcing every camera to the same resolution at this stage.
- If camera open fails, verify `/dev/video*`, camera permissions, and whether another app is using the camera.
- If upload fails, verify the Windows capture console server is running on `0.0.0.0:8000` and the Windows firewall allows LAN access.
