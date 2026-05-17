import gc
import time
import socket
import network

try:
    import ujson as json
except ImportError:
    import json

from media.sensor import *
from media.display import *
from media.media import *

from config import (
    WIFI_SSID,
    WIFI_PASSWORD,
    CAMERA_ID,
    MODEL,
    DEVICE_TYPE,
    SERVER_HOST,
    SERVER_PORT,
    SENSOR_ID,
    IMAGE_WIDTH,
    IMAGE_HEIGHT,
    JPEG_QUALITY,
    DISPLAY_ENABLED,
    DISPLAY_MODE,
    DISPLAY_TO_IDE,
    DISPLAY_WIDTH,
    DISPLAY_HEIGHT,
    DISPLAY_QUALITY,
    DISPLAY_FPS,
    PREVIEW_ENABLED,
    PREVIEW_INTERVAL_MS,
    CONNECT_TIMEOUT_SEC,
)


CAMERA_CHN = CAM_CHN_ID_0
_sensor = None
_camera_ready = False
_camera_error = ""
_display_ready = False
_display_error = ""
_wlan = None
_loop_counter = 0
_last_preview_ms = 0


def log(message):
    print("[K230] " + str(message))


def log_error(stage, exc):
    print("[K230][ERROR] " + stage + ": " + str(exc))


def is_eagain(exc):
    if getattr(exc, "errno", None) == 11:
        return True
    if getattr(exc, "args", None) and len(exc.args) > 0 and exc.args[0] == 11:
        return True
    return str(exc).find("EAGAIN") >= 0


def json_response(sock, status_code, payload):
    body = json.dumps(payload)
    reason = "OK" if status_code == 200 else "ERROR"
    headers = (
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Connection: close\r\n"
        "Content-Length: %d\r\n"
        "\r\n"
    ) % (status_code, reason, len(body))
    send_all(sock, headers.encode())
    send_all(sock, body.encode())


def text_response(sock, status_code, text):
    reason = "OK" if status_code == 200 else "ERROR"
    headers = (
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: text/plain\r\n"
        "Connection: close\r\n"
        "Content-Length: %d\r\n"
        "\r\n"
    ) % (status_code, reason, len(text))
    send_all(sock, headers.encode())
    send_all(sock, text.encode())


def send_all(sock, data):
    view = memoryview(data)
    sent = 0
    while sent < len(data):
        count = sock.send(view[sent:])
        if count is None:
            count = 0
        if count <= 0:
            raise RuntimeError("socket send failed")
        sent += count


def set_timeout(sock, seconds):
    try:
        sock.settimeout(seconds)
        log("socket timeout set: " + str(seconds))
    except Exception as exc:
        log("socket settimeout unavailable: " + str(exc))


def url_encode(value):
    value = str(value)
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    out = ""
    for ch in value:
        if ch in safe:
            out += ch
        else:
            out += "%%%02X" % ord(ch)
    return out


def parse_http_url(url):
    if not url.startswith("http://"):
        raise ValueError("only http:// upload_url is supported")
    rest = url[7:]
    slash = rest.find("/")
    if slash < 0:
        host_port = rest
        path = "/"
    else:
        host_port = rest[:slash]
        path = rest[slash:]

    colon = host_port.find(":")
    if colon >= 0:
        host = host_port[:colon]
        port = int(host_port[colon + 1 :])
    else:
        host = host_port
        port = 80
    return host, port, path


def now_ms():
    try:
        return int(time.time() * 1000)
    except Exception:
        return time.ticks_ms()


def connect_wifi():
    global _wlan
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)

    if not sta.isconnected():
        log("connecting wifi: " + WIFI_SSID)
        sta.connect(WIFI_SSID, WIFI_PASSWORD)
        start = time.time()
        while not sta.isconnected():
            if time.time() - start > CONNECT_TIMEOUT_SEC:
                raise RuntimeError("wifi connect timeout")
            time.sleep(1)

    _wlan = sta
    log("wifi connected, ifconfig=" + str(sta.ifconfig()))
    return sta


def init_display():
    global _display_ready, _display_error
    if not DISPLAY_ENABLED:
        _display_error = ""
        return
    if _display_ready:
        return

    log(
        "initializing display: mode=%s size=%dx%d to_ide=%s"
        % (DISPLAY_MODE, DISPLAY_WIDTH, DISPLAY_HEIGHT, DISPLAY_TO_IDE)
    )
    try:
        if DISPLAY_MODE == "LCD":
            Display.init(
                Display.ST7701,
                width=DISPLAY_WIDTH,
                height=DISPLAY_HEIGHT,
                to_ide=DISPLAY_TO_IDE,
                quality=DISPLAY_QUALITY,
            )
        elif DISPLAY_MODE == "HDMI":
            Display.init(
                Display.LT9611,
                width=DISPLAY_WIDTH,
                height=DISPLAY_HEIGHT,
                to_ide=DISPLAY_TO_IDE,
                quality=DISPLAY_QUALITY,
            )
        elif DISPLAY_MODE == "VIRT":
            Display.init(
                Display.VIRT,
                width=DISPLAY_WIDTH,
                height=DISPLAY_HEIGHT,
                fps=DISPLAY_FPS,
                quality=DISPLAY_QUALITY,
            )
        else:
            raise ValueError("unsupported DISPLAY_MODE: " + str(DISPLAY_MODE))
        _display_ready = True
        _display_error = ""
        log("display init done")
    except Exception as exc:
        _display_ready = False
        _display_error = str(exc)
        log_error("init_display", exc)


def show_debug_frame(img):
    global _display_error
    if not DISPLAY_ENABLED or not _display_ready:
        return
    try:
        Display.show_image(img, x=0, y=0)
        log("display frame shown")
    except Exception as exc:
        _display_error = str(exc)
        log_error("show_debug_frame", exc)


def update_preview_if_needed(force=False):
    global _last_preview_ms
    if not PREVIEW_ENABLED or not DISPLAY_ENABLED:
        return
    now = time.ticks_ms()
    if not force and time.ticks_diff(now, _last_preview_ms) < PREVIEW_INTERVAL_MS:
        return
    try:
        sensor = init_camera()
        img = sensor.snapshot(chn=CAMERA_CHN)
        if img:
            show_debug_frame(img)
            _last_preview_ms = now
    except Exception as exc:
        log_error("preview", exc)


def init_camera():
    global _sensor, _camera_ready, _camera_error
    if _camera_ready:
        return _sensor

    log("initializing sensor")
    try:
        sensor = Sensor(id=SENSOR_ID)
        log("sensor object created, id=" + str(SENSOR_ID))
        sensor.reset()
        log("sensor reset done")
        sensor.set_framesize(chn=CAMERA_CHN, width=IMAGE_WIDTH, height=IMAGE_HEIGHT)
        log("sensor framesize set: %dx%d" % (IMAGE_WIDTH, IMAGE_HEIGHT))
        sensor.set_pixformat(Sensor.RGB888, chn=CAMERA_CHN)
        log("sensor pixformat set: RGB888")
        init_display()
        MediaManager.init()
        log("media manager init done")
        sensor.run()
        log("sensor run done")
        time.sleep_ms(500)
    except Exception as exc:
        _camera_error = str(exc)
        log_error("init_camera", exc)
        raise

    _sensor = sensor
    _camera_ready = True
    _camera_error = ""
    log("sensor ready: %dx%d" % (IMAGE_WIDTH, IMAGE_HEIGHT))
    return sensor


def capture_jpeg():
    log("capture requested")
    sensor = init_camera()
    log("taking snapshot")
    img = sensor.snapshot(chn=CAMERA_CHN)
    if not img:
        raise RuntimeError("sensor snapshot failed")

    width = img.width()
    height = img.height()
    log("snapshot done: %dx%d" % (width, height))
    show_debug_frame(img)
    jpg = img.compress(quality=JPEG_QUALITY)
    if not jpg:
        raise RuntimeError("jpeg compress failed")
    log("jpeg compressed: " + str(len(jpg)) + " bytes")

    gc.collect()
    return jpg, width, height


def upload_jpeg_once(upload_url, camera_id, session_id, jpg, width, height, timestamp_ms):
    host, port, path = parse_http_url(upload_url)
    separator = "&" if path.find("?") >= 0 else "?"
    path = (
        path
        + separator
        + "camera_id="
        + url_encode(camera_id)
        + "&session_id="
        + url_encode(session_id)
        + "&format=jpg"
        + "&width="
        + str(width)
        + "&height="
        + str(height)
        + "&timestamp_ms="
        + str(timestamp_ms)
    )

    addr = socket.getaddrinfo(host, port)[0][-1]
    log("upload connect: " + str(addr))
    sock = socket.socket()
    try:
        set_timeout(sock, 8)
        sock.connect(addr)
        log("upload connected")
        headers = (
            "POST %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Content-Type: image/jpeg\r\n"
            "X-Device-Type: %s\r\n"
            "Connection: close\r\n"
            "Content-Length: %d\r\n"
            "\r\n"
        ) % (path, host, port, DEVICE_TYPE, len(jpg))
        send_all(sock, headers.encode())
        send_all(sock, jpg)
        log("upload body sent")

        response = b""
        while True:
            chunk = sock.recv(256)
            if not chunk:
                break
            response += chunk
            if len(response) > 1024:
                break
        first_line = response.split(b"\r\n", 1)[0]
        ok = first_line.find(b" 2") > 0
        log("upload response: " + (first_line.decode() if first_line else "empty"))
        return ok, first_line.decode() if first_line else ""
    finally:
        sock.close()
        log("upload socket closed")


def upload_jpeg(upload_url, camera_id, session_id, jpg, width, height, timestamp_ms):
    last_status = ""
    for attempt in range(1, 3):
        log("upload begin attempt %d: %s" % (attempt, upload_url))
        try:
            ok, status = upload_jpeg_once(
                upload_url, camera_id, session_id, jpg, width, height, timestamp_ms
            )
        except Exception as exc:
            ok = False
            status = str(exc)
            log_error("upload attempt %d" % attempt, exc)
        last_status = status
        if ok:
            return True, status
        time.sleep_ms(200)
    return False, last_status


def parse_request(conn):
    log("reading http request")
    data = b""
    header_end = -1
    delimiter_len = 0
    while header_end < 0:
        log("waiting for request bytes, current=" + str(len(data)))
        chunk = conn.recv(512)
        if not chunk:
            log("client closed before headers complete")
            break
        log("received chunk bytes: " + str(len(chunk)))
        data += chunk
        header_end = data.find(b"\r\n\r\n")
        delimiter_len = 4
        if header_end < 0:
            header_end = data.find(b"\n\n")
            delimiter_len = 2
        if len(data) > 8192:
            break

    if header_end < 0:
        raise ValueError("bad http request")

    header_bytes = data[:header_end]
    body = data[header_end + delimiter_len :]
    lines = header_bytes.decode().splitlines()
    method, path, _version = lines[0].split(" ", 2)
    log("request line: " + lines[0])

    content_length = 0
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())

    log("content length: " + str(content_length))
    while len(body) < content_length:
        log("waiting for body bytes: %d/%d" % (len(body), content_length))
        chunk = conn.recv(content_length - len(body))
        if not chunk:
            break
        log("received body chunk bytes: " + str(len(chunk)))
        body += chunk

    log("request body bytes: " + str(len(body)))
    return method, path, body


def status_payload():
    ip = ""
    wifi_ok = False
    if _wlan:
        wifi_ok = _wlan.isconnected()
        if wifi_ok:
            ip = _wlan.ifconfig()[0]
    return {
        "ok": True,
        "camera_id": CAMERA_ID,
        "model": MODEL,
        "ip": ip,
        "wifi_connected": wifi_ok,
        "camera_ready": _camera_ready,
        "camera_error": _camera_error,
        "display_enabled": DISPLAY_ENABLED,
        "display_ready": _display_ready,
        "display_error": _display_error,
        "display_mode": DISPLAY_MODE,
        "display_to_ide": DISPLAY_TO_IDE,
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
        "format": "jpg",
    }


def handle_capture(body):
    try:
        request = json.loads(body.decode() if body else "{}")
    except Exception:
        raise ValueError("invalid json body")

    session_id = request.get("session_id", "")
    upload_url = request.get("upload_url", "")
    camera_id = request.get("camera_id", CAMERA_ID) or CAMERA_ID
    requested_format = request.get("requested_format", "jpg")
    log(
        "capture payload: session_id=%s camera_id=%s upload_url=%s format=%s"
        % (session_id, camera_id, upload_url, requested_format)
    )

    if not session_id:
        raise ValueError("missing session_id")
    if not upload_url:
        raise ValueError("missing upload_url")
    if requested_format not in ("jpg", "jpeg"):
        raise ValueError("unsupported requested_format")

    start = time.ticks_ms()
    jpg, width, height = capture_jpeg()
    timestamp_ms = now_ms()
    upload_ok, upload_status = upload_jpeg(
        upload_url, camera_id, session_id, jpg, width, height, timestamp_ms
    )
    elapsed_ms = time.ticks_diff(time.ticks_ms(), start)

    return {
        "ok": upload_ok,
        "camera_id": camera_id,
        "session_id": session_id,
        "bytes": len(jpg),
        "width": width,
        "height": height,
        "timestamp_ms": timestamp_ms,
        "elapsed_ms": elapsed_ms,
        "upload_status": upload_status,
    }


def serve_forever():
    global _loop_counter
    connect_wifi()
    if PREVIEW_ENABLED and DISPLAY_ENABLED:
        log("preview enabled, initializing camera/display before server loop")
        update_preview_if_needed(force=True)

    addr = socket.getaddrinfo(SERVER_HOST, SERVER_PORT)[0][-1]
    log("server bind addr: " + str(addr))
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(addr)
    server.listen(2)
    try:
        server.setblocking(False)
        log("server socket set to nonblocking mode")
    except Exception as exc:
        log("server setblocking unavailable: " + str(exc))
    log("http server listening on port " + str(SERVER_PORT))

    while True:
        _loop_counter += 1
        if _loop_counter % 40 == 0:
            log("server heartbeat, waiting for client")

        try:
            conn, remote = server.accept()
        except OSError as exc:
            if is_eagain(exc):
                update_preview_if_needed()
                time.sleep_ms(20)
                continue
            log_error("accept", exc)
            time.sleep_ms(500)
            continue

        log("client connected: " + str(remote))
        set_timeout(conn, 2)
        try:
            method, path, body = parse_request(conn)
            if method == "GET" and path.startswith("/status"):
                log("handling status")
                json_response(conn, 200, status_payload())
            elif method == "POST" and path.startswith("/capture"):
                log("handling capture")
                payload = handle_capture(body)
                json_response(conn, 200 if payload.get("ok") else 502, payload)
            else:
                log("not found: " + method + " " + path)
                text_response(conn, 404, "not found")
        except Exception as exc:
            log_error("request", exc)
            try:
                json_response(conn, 500, {"ok": False, "error": str(exc)})
            except Exception:
                pass
        finally:
            conn.close()
            log("client closed")
            gc.collect()


try:
    serve_forever()
finally:
    if _sensor:
        _sensor.stop()
    if _display_ready:
        Display.deinit()
    MediaManager.deinit()
