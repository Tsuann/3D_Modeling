from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .http_client import request_json
from .quality import basic_image_check
from .settings import PROJECT_DIR, load_config, load_devices, public_base_url
from .storage import list_sessions, session_summary


def print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_server(_args: argparse.Namespace) -> int:
    import uvicorn

    config = load_config()
    server = config.get("server", {})
    uvicorn.run(
        "capture_console.server:app",
        host=server.get("host", "0.0.0.0"),
        port=int(server.get("port", 8000)),
        reload=False,
    )
    return 0


def cmd_devices(args: argparse.Namespace) -> int:
    print_json({"devices": load_devices(include_disabled=args.all)})
    return 0


def cmd_ping(_args: argparse.Namespace) -> int:
    results = []
    for device in load_devices(include_disabled=False):
        base_url = device["base_url"].rstrip("/")
        results.append(
            {
                "camera_id": device["camera_id"],
                "base_url": base_url,
                "result": request_json("GET", f"{base_url}/status", timeout=3),
            }
        )
    print_json({"results": results})
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    payload = {}
    if args.session_id:
        payload["session_id"] = args.session_id
    if args.upload_url:
        payload["upload_url"] = args.upload_url
    result = request_json("POST", f"{args.server.rstrip('/')}/api/capture", payload, timeout=20)
    print_json(result)
    return 0 if result.get("ok", False) else 1


def cmd_sessions(_args: argparse.Namespace) -> int:
    print_json({"sessions": list_sessions()})
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    session_id = args.session_id
    if session_id == "latest":
        sessions = list_sessions()
        if not sessions:
            print_json({"ok": False, "error": "no sessions found"})
            return 1
        session_id = sessions[0]["session_id"]

    summary = session_summary(session_id)
    checks = [basic_image_check(Path(image["image_path"])) for image in summary["images"]]
    print_json({"session_id": session_id, "checks": checks, "ok": all(item["ok"] for item in checks)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Windows capture console for the multi-camera 3D project.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    server = subparsers.add_parser("server", help="Start the FastAPI receiver/control service.")
    server.set_defaults(func=cmd_server)

    devices = subparsers.add_parser("devices", help="List registered devices.")
    devices.add_argument("--all", action="store_true", help="Include disabled devices.")
    devices.set_defaults(func=cmd_devices)

    ping = subparsers.add_parser("ping", help="Call /status on enabled devices.")
    ping.set_defaults(func=cmd_ping)

    capture = subparsers.add_parser("capture", help="Trigger enabled devices through the local service.")
    capture.add_argument("--server", default=public_base_url(), help="Capture service URL.")
    capture.add_argument("--session-id", help="Optional session id.")
    capture.add_argument("--upload-url", help="Override upload URL passed to devices.")
    capture.set_defaults(func=cmd_capture)

    sessions = subparsers.add_parser("sessions", help="List saved capture sessions.")
    sessions.set_defaults(func=cmd_sessions)

    check = subparsers.add_parser("check", help="Run basic file checks for a session.")
    check.add_argument("session_id", nargs="?", default="latest", help="Session id or 'latest'.")
    check.set_defaults(func=cmd_check)

    parser.epilog = f"Project directory: {PROJECT_DIR}"
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

