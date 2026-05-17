from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .http_client import request_json
from .quality import basic_image_check
from .settings import PROJECT_DIR, load_config, load_devices, public_base_url
from .storage import list_sessions, session_summary


def print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def check_session(session_id: str) -> dict[str, object]:
    summary = session_summary(session_id)
    checks = [basic_image_check(Path(image["image_path"])) for image in summary["images"]]
    return {"session_id": session_id, "checks": checks, "ok": all(item["ok"] for item in checks)}


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

    result = check_session(session_id)
    print_json(result)
    return 0 if result["ok"] else 1


def run_numbered_collection(args: argparse.Namespace, *, title: str, ready_message: str) -> int:
    devices = load_devices(include_disabled=False)
    expected_count = len(devices)
    completed = []
    failed = []

    print(f"{title}: {args.count} sessions")
    print(f"Enabled devices: {expected_count} ({', '.join(device['camera_id'] for device in devices)})")
    print(f"Session pattern: {args.prefix}<number>, starting at {args.start:03d}")
    if args.upload_url:
        print(f"Upload URL: {args.upload_url}")
    print(ready_message)
    print("Type q and press Enter to stop early.")

    for index in range(args.start, args.start + args.count):
        session_id = f"{args.prefix}{index:03d}"

        if args.auto:
            print(f"\n[{session_id}] Capturing in {args.delay_sec:g}s...")
            time.sleep(args.delay_sec)
        else:
            answer = input(f"\n[{session_id}] Ready? ")
            if answer.strip().lower() in {"q", "quit", "exit", "stop"}:
                print("Stopped by user.")
                break

        payload = {"session_id": session_id}
        if args.upload_url:
            payload["upload_url"] = args.upload_url

        capture_result = request_json("POST", f"{args.server.rstrip('/')}/api/capture", payload, timeout=args.timeout_sec)
        check_result = check_session(session_id)
        image_count = len(check_result["checks"])
        ok = bool(capture_result.get("ok")) and bool(check_result["ok"]) and image_count == expected_count

        if ok:
            completed.append(session_id)
            print(f"[{session_id}] OK: {image_count}/{expected_count} images saved and checked")
            continue

        failed.append(session_id)
        print(f"[{session_id}] FAILED")
        print_json({"capture": capture_result, "check": check_result, "expected_images": expected_count})
        if args.stop_on_failure:
            break

    result = {
        "ok": not failed,
        "completed": completed,
        "failed": failed,
        "completed_count": len(completed),
        "failed_count": len(failed),
    }
    print("\nSummary:")
    print_json(result)
    return 0 if result["ok"] else 1


def cmd_calib_collect(args: argparse.Namespace) -> int:
    return run_numbered_collection(
        args,
        title="Calibration collection",
        ready_message="Move the calibration board, hold it steady, then press Enter.",
    )


def cmd_collect(args: argparse.Namespace) -> int:
    return run_numbered_collection(
        args,
        title="Object collection",
        ready_message="Adjust the object or turntable pose, hold it steady, then press Enter.",
    )


def add_collection_arguments(parser: argparse.ArgumentParser, *, default_prefix: str, default_count: int) -> None:
    parser.add_argument("--server", default=public_base_url(), help="Capture service URL.")
    parser.add_argument("--upload-url", help="Override upload URL passed to devices.")
    parser.add_argument("--prefix", default=default_prefix, help="Session id prefix.")
    parser.add_argument("--start", type=int, default=1, help="First session number.")
    parser.add_argument("--count", type=int, default=default_count, help="Number of sessions to collect.")
    parser.add_argument("--timeout-sec", type=float, default=20, help="Capture command timeout.")
    parser.add_argument("--auto", action="store_true", help="Capture automatically instead of waiting for Enter.")
    parser.add_argument("--delay-sec", type=float, default=3, help="Delay between automatic captures.")
    parser.add_argument("--stop-on-failure", action="store_true", help="Stop after the first failed capture/check.")


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

    collect = subparsers.add_parser("collect", help="Interactively collect object image sessions.")
    add_collection_arguments(collect, default_prefix="object_", default_count=60)
    collect.set_defaults(func=cmd_collect)

    calib = subparsers.add_parser("calib-collect", help="Interactively collect calibration image sessions.")
    add_collection_arguments(calib, default_prefix="calib_", default_count=40)
    calib.set_defaults(func=cmd_calib_collect)

    parser.epilog = f"Project directory: {PROJECT_DIR}"
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
