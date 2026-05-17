# K230 CanMV Camera Node

这个目录存放庐山派 K230 CanMV 摄像头节点代码，用于接入项目里的 Windows `capture_console`。

## 功能

- 连接 2.4G Wi-Fi。
- 提供 `GET /status`。
- 提供 `POST /capture`。
- 每次 capture 拍摄一张 JPEG，并上传到 Windows `/api/upload`。
- 每次 capture 后将当前画面显示到 3.1 寸 LCD，并同步显示到 CanMV IDE 帧缓冲区。

接口契约与 `PROJECT_CONTEXT.md` 保持一致：

```text
GET  /status
POST /capture
```

`POST /capture` 请求示例：

```json
{
  "session_id": "session_20260517_153000",
  "camera_id": "cam_k230",
  "upload_url": "http://192.168.1.10:8000/api/upload",
  "requested_format": "jpg"
}
```

## 部署

1. 用 CanMV IDE 打开 `K230_canMV`。
2. 修改 `config.py`：

```python
WIFI_SSID = "你的2.4G WiFi名称"
WIFI_PASSWORD = "你的WiFi密码"
SERVER_PORT = 80
```

默认相机和显示配置：

```python
IMAGE_WIDTH = 800
IMAGE_HEIGHT = 480
DISPLAY_ENABLED = True
DISPLAY_MODE = "LCD"
DISPLAY_TO_IDE = True
DISPLAY_WIDTH = 800
DISPLAY_HEIGHT = 480
PREVIEW_ENABLED = True
PREVIEW_INTERVAL_MS = 300
```

3. 将 `config.py` 和 `main.py` 上传到 K230。
4. 运行 `main.py`，串口里会打印设备 IP。
5. 将这个 IP 写入 Windows 端：

```json
{
  "camera_id": "cam_k230",
  "base_url": "http://K230_IP",
  "enabled": true
}
```

## Windows 联调

在 Windows 主机启动 capture console：

```powershell
cd F:\Project\3D_Modeling\capture_console
.\.venv\Scripts\Activate.ps1
python -m capture_console.cli server
```

另开终端测试：

```powershell
python -m capture_console.cli ping
python -m capture_console.cli capture --session-id k230_test001 --upload-url http://你的Windows局域网IP:8000/api/upload
python -m capture_console.cli check k230_test001
```

## 注意

- 庐山派板载 RTL8189FTV Wi-Fi 只支持 2.4G，不支持 5G 或双频合一网络。
- 默认摄像头接口是 CSI2，所以 `SENSOR_ID = 2`。
- 当前默认分辨率是 `800x480`，与 3.1 寸 LCD 一致，JPEG 质量 `95`。如果后续更重视采集分辨率，可再改回 `1024x768` 并关闭实时预览。
- 显示初始化必须在 `MediaManager.init()` 之前完成，代码已经按这个顺序处理。
- 当前显示策略是启动后定时刷新预览，同时每次 capture 后也刷新最后一帧。
- 如果没有接 3.1 寸屏幕，可把 `DISPLAY_MODE` 改为 `"VIRT"` 只在 CanMV IDE 中显示，或把 `DISPLAY_ENABLED` 改为 `False` 关闭显示。
- 当前仅支持 `http://` 上传地址，不支持 HTTPS。

## 参考资料

- [无线网络](https://wiki.lckfb.com/zh-hans/lushan-pi-k230/network/wifi.html)
- [使用摄像头](https://wiki.lckfb.com/zh-hans/lushan-pi-k230/image-recog/use-sensor.html)
- [显示画面](https://wiki.lckfb.com/zh-hans/lushan-pi-k230/image-recog/display.html)
