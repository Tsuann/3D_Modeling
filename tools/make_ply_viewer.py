from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path
from typing import Any


PLY_TYPES = {
    "char": ("b", 1),
    "uchar": ("B", 1),
    "int8": ("b", 1),
    "uint8": ("B", 1),
    "short": ("h", 2),
    "ushort": ("H", 2),
    "int16": ("h", 2),
    "uint16": ("H", 2),
    "int": ("i", 4),
    "uint": ("I", 4),
    "int32": ("i", 4),
    "uint32": ("I", 4),
    "float": ("f", 4),
    "float32": ("f", 4),
    "double": ("d", 8),
    "float64": ("d", 8),
}


def parse_ply(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    header_end = data.index(b"end_header") + len(b"end_header")
    while header_end < len(data) and data[header_end] in b"\r\n":
        header_end += 1
    header = data[:header_end].decode("ascii", errors="replace")
    lines = header.splitlines()

    fmt = ""
    vertex_count = 0
    properties: list[tuple[str, str]] = []
    in_vertex = False
    for line in lines:
        parts = line.strip().split()
        if not parts:
            continue
        if parts[:1] == ["format"]:
            fmt = parts[1]
        elif parts[:2] == ["element", "vertex"]:
            vertex_count = int(parts[2])
            in_vertex = True
        elif parts[:1] == ["element"]:
            in_vertex = False
        elif in_vertex and parts[:1] == ["property"] and len(parts) == 3:
            properties.append((parts[2], parts[1]))

    if fmt == "ascii":
        body = data[header_end:].decode("ascii", errors="replace").splitlines()
        points = []
        for line in body[:vertex_count]:
            values = line.strip().split()
            if len(values) < len(properties):
                continue
            row = {name: value for (name, _), value in zip(properties, values)}
            points.append(
                {
                    "x": float(row.get("x", 0.0)),
                    "y": float(row.get("y", 0.0)),
                    "z": float(row.get("z", 0.0)),
                    "r": int(float(row.get("red", row.get("r", 255)))),
                    "g": int(float(row.get("green", row.get("g", 255)))),
                    "b": int(float(row.get("blue", row.get("b", 255)))),
                }
            )
        return {"source": str(path), "point_count": len(points), "points": points}

    if fmt != "binary_little_endian":
        raise ValueError(f"Only ascii and binary_little_endian PLY are supported, got {fmt!r}")

    struct_format = "<" + "".join(PLY_TYPES[prop_type][0] for _, prop_type in properties)
    row_size = struct.calcsize(struct_format)
    points = []
    for index in range(vertex_count):
        offset = header_end + index * row_size
        values = struct.unpack_from(struct_format, data, offset)
        row = {name: value for (name, _), value in zip(properties, values)}
        points.append(
            {
                "x": float(row.get("x", 0.0)),
                "y": float(row.get("y", 0.0)),
                "z": float(row.get("z", 0.0)),
                "r": int(row.get("red", row.get("r", 255))),
                "g": int(row.get("green", row.get("g", 255))),
                "b": int(row.get("blue", row.get("b", 255))),
            }
        )
    return {"source": str(path), "point_count": vertex_count, "points": points}


def html_template(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PLY Point Viewer</title>
  <style>
    :root {{
      color-scheme: dark;
      --bg: #0c0f10;
      --panel: #151a1c;
      --ink: #eef3ef;
      --muted: #96a39c;
      --accent: #ff7a3d;
      --line: #2a3432;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      background: radial-gradient(circle at 20% 0%, #202824 0, transparent 36rem), var(--bg);
      color: var(--ink);
      font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
      overflow: hidden;
    }}
    .shell {{
      display: grid;
      grid-template-columns: 320px 1fr;
      height: 100vh;
    }}
    aside {{
      border-right: 1px solid var(--line);
      background: color-mix(in srgb, var(--panel) 88%, transparent);
      padding: 24px;
    }}
    h1 {{
      margin: 0 0 16px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    .metric {{
      padding: 14px 0;
      border-top: 1px solid var(--line);
    }}
    .label {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .value {{
      margin-top: 6px;
      font-size: 16px;
      overflow-wrap: anywhere;
    }}
    button {{
      width: 100%;
      margin-top: 16px;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #1a0b04;
      padding: 11px 14px;
      font-weight: 700;
      cursor: pointer;
    }}
    .hint {{
      margin-top: 18px;
      color: var(--muted);
      line-height: 1.55;
      font-size: 13px;
    }}
    main {{ position: relative; min-width: 0; }}
    canvas {{ width: 100%; height: 100%; display: block; cursor: grab; }}
    canvas:active {{ cursor: grabbing; }}
    .badge {{
      position: absolute;
      right: 18px;
      bottom: 16px;
      color: var(--muted);
      font-size: 12px;
      background: rgba(0,0,0,.35);
      border: 1px solid var(--line);
      padding: 8px 10px;
    }}
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>PLY Point Viewer</h1>
      <div class="metric">
        <div class="label">Source</div>
        <div class="value" id="source"></div>
      </div>
      <div class="metric">
        <div class="label">Points</div>
        <div class="value" id="count"></div>
      </div>
      <div class="metric">
        <div class="label">Scale</div>
        <div class="value" id="scale"></div>
      </div>
      <button id="reset">Reset View</button>
      <p class="hint">拖拽旋转，滚轮缩放。当前点云很稀疏，所以看到几个彩色点是正常的，不是完整 mesh。</p>
    </aside>
    <main>
      <canvas id="canvas"></canvas>
      <div class="badge">drag rotate / wheel zoom</div>
    </main>
  </div>
  <script>
    const data = {payload_json};
    const points = data.points;
    document.getElementById('source').textContent = data.source;
    document.getElementById('count').textContent = points.length.toString();

    const canvas = document.getElementById('canvas');
    const ctx = canvas.getContext('2d');
    let yaw = -0.55, pitch = 0.35, zoom = 1;
    let dragging = false, lastX = 0, lastY = 0;

    const center = points.reduce((acc, p) => {{
      acc.x += p.x; acc.y += p.y; acc.z += p.z; return acc;
    }}, {{x:0,y:0,z:0}});
    if (points.length) {{ center.x /= points.length; center.y /= points.length; center.z /= points.length; }}
    const radius = Math.max(0.000001, ...points.map(p => Math.hypot(p.x-center.x, p.y-center.y, p.z-center.z)));

    function resize() {{
      canvas.width = canvas.clientWidth * devicePixelRatio;
      canvas.height = canvas.clientHeight * devicePixelRatio;
      render();
    }}
    function rotate(p) {{
      let x = p.x - center.x, y = p.y - center.y, z = p.z - center.z;
      const cy = Math.cos(yaw), sy = Math.sin(yaw);
      const cp = Math.cos(pitch), sp = Math.sin(pitch);
      const x1 = cy*x + sy*z;
      const z1 = -sy*x + cy*z;
      const y2 = cp*y - sp*z1;
      const z2 = sp*y + cp*z1;
      return {{x:x1, y:y2, z:z2}};
    }}
    function render() {{
      ctx.fillStyle = '#0c0f10';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      const size = Math.min(canvas.width, canvas.height);
      const scale = size * 0.36 * zoom / radius;
      document.getElementById('scale').textContent = zoom.toFixed(2) + 'x';
      const projected = points.map(p => {{
        const q = rotate(p);
        return {{
          x: canvas.width / 2 + q.x * scale,
          y: canvas.height / 2 - q.y * scale,
          z: q.z,
          color: `rgb(${{p.r}},${{p.g}},${{p.b}})`
        }};
      }}).sort((a,b) => a.z - b.z);
      for (const p of projected) {{
        ctx.beginPath();
        ctx.fillStyle = p.color;
        ctx.arc(p.x, p.y, Math.max(4, size * 0.006), 0, Math.PI * 2);
        ctx.fill();
      }}
    }}
    canvas.addEventListener('mousedown', e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; }});
    addEventListener('mouseup', () => dragging = false);
    addEventListener('mousemove', e => {{
      if (!dragging) return;
      yaw += (e.clientX - lastX) * 0.008;
      pitch += (e.clientY - lastY) * 0.008;
      pitch = Math.max(-1.45, Math.min(1.45, pitch));
      lastX = e.clientX; lastY = e.clientY;
      render();
    }});
    canvas.addEventListener('wheel', e => {{
      e.preventDefault();
      zoom *= Math.exp(-e.deltaY * 0.001);
      zoom = Math.max(0.08, Math.min(80, zoom));
      render();
    }}, {{passive:false}});
    document.getElementById('reset').addEventListener('click', () => {{ yaw = -0.55; pitch = 0.35; zoom = 1; render(); }});
    addEventListener('resize', resize);
    resize();
  </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a self-contained HTML viewer for a binary little-endian PLY point cloud.")
    parser.add_argument("ply", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    payload = parse_ply(args.ply)
    output = args.output or args.ply.with_suffix(".viewer.html")
    output.write_text(html_template(payload), encoding="utf-8")
    print(json.dumps({"ok": True, "points": payload["point_count"], "output": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
