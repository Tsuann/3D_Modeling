# Capture Console Demo

这是三摄像头 3D 重建项目的 Windows 端采集控制台雏形。当前版本包含：

- FastAPI 服务：接收设备上传图片、管理 session、触发设备采集。
- CLI 工具：启动服务、查看设备、触发采集、检查采集文件。
- 预留硬件接口：ESP32-S3、K230、OrangePi 只需实现 `/status` 和 `/capture`。

## 安装

```powershell
cd F:\Project\3D_Modeling\capture_console
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 启动服务

```powershell
python -m capture_console.cli server
```

默认服务地址：

```text
http://127.0.0.1:8000
```

局域网设备上传时，应使用 Windows 主机在局域网中的 IP，例如：

```text
http://192.168.1.10:8000/api/upload
```

## CLI 示例

```powershell
python -m capture_console.cli devices --all
python -m capture_console.cli ping
python -m capture_console.cli capture --session-id test001 --upload-url http://你的Windows局域网IP:8000/api/upload
python -m capture_console.cli sessions
python -m capture_console.cli check latest
```

## 设备端需要实现的接口

### `GET /status`

返回示例：

```json
{
  "ok": true,
  "camera_id": "cam_esp32s3",
  "model": "esp32s3_ov3660"
}
```

### `POST /capture`

Windows 会发送：

```json
{
  "session_id": "session_20260517_153000",
  "camera_id": "cam_esp32s3",
  "upload_url": "http://192.168.1.10:8000/api/upload",
  "requested_format": "jpg"
}
```

设备收到后拍照，并把 JPEG 二进制上传到：

```text
POST /api/upload?camera_id=cam_esp32s3&session_id=session_20260517_153000&format=jpg&width=1024&height=768&timestamp_ms=1710000000000
Content-Type: image/jpeg
Body: JPEG bytes
```

## 保存结构

```text
captures/
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

## 下一步建议

1. 修改 `device_registry.json`，填入真实 IP，并把对应设备的 `enabled` 改为 `true`。
2. 先让每个设备单独跑通 `/status`。
3. 再实现 `/capture` 和图片上传。
4. 连续采集 50-100 次，检查丢图率和文件完整性。

