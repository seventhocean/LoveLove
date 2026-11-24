#!/usr/bin/env python3
"""YY AI 生图网站 —— 本地服务端。

只用标准库，无第三方依赖。密钥仅存在于服务端进程内，不下发到浏览器。

    ./server.py              # http://127.0.0.1:8787
    ./server.py --port 9000
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "gen-image.env"
WEB_DIR = HERE / "web"
OUT_DIR = HERE / "out"
OUT_DIR.mkdir(exist_ok=True)

DEFAULT_MODEL = "gpt-image-1"
ALLOWED_SIZES = {"1024x1024", "1536x1024", "1024x1536"}
FALLBACK_MODELS = [
    "gpt-image-1",
    "gpt-image-1-seedream-5.5",
    "seedream-5.0-pro（A）",
    "seedream-5.5（A）",
]
MAX_PROMPT = 2000
UPSTREAM_TIMEOUT = 300
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


# ---------------------------------------------------------------- 配置

def load_env() -> dict[str, str]:
    cfg = {
        "YYT_BASE_URL": os.environ.get("YYT_BASE_URL", ""),
        "YYT_API_KEY": os.environ.get("YYT_API_KEY", ""),
        "YYT_ACTOR_HEADER": os.environ.get("YYT_ACTOR_HEADER", ""),
    }
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if not cfg.get(k.strip()):
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    return cfg


CFG = load_env()


def upstream(path: str, payload: dict | None = None, timeout: int = UPSTREAM_TIMEOUT) -> dict:
    url = CFG["YYT_BASE_URL"].rstrip("/") + path
    headers = {
        "Authorization": f"Bearer {CFG['YYT_API_KEY']}",
        "Content-Type": "application/json",
    }
    if CFG.get("YYT_ACTOR_HEADER"):
        headers["x-openai-actor-authorization"] = CFG["YYT_ACTOR_HEADER"]
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------- 生图

def save_item(item: dict, target: Path) -> None:
    if item.get("b64_json"):
        target.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as r:
            target.write_bytes(r.read())
    else:
        raise ValueError(f"响应无图片数据: {list(item.keys())}")


def generate(prompt: str, model: str, size: str, n: int) -> dict:
    t0 = time.time()
    payload = {"model": model, "prompt": prompt, "n": n, "size": size}
    d = upstream("/images/generations", payload, UPSTREAM_TIMEOUT)
    items = d.get("data") or []
    if not items:
        raise ValueError(f"上游未返回图片: {json.dumps(d)[:300]}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    results = []
    for i, item in enumerate(items):
        name = f"{stamp}-{os.urandom(3).hex()}{'-' + str(i + 1) if n > 1 else ''}.png"
        target = OUT_DIR / name
        save_item(item, target)
        results.append({"name": name, "url": f"/out/{name}",
                        "kb": round(target.stat().st_size / 1024)})
    return {"images": results, "elapsed": round(time.time() - t0, 1),
            "model": model, "size": size}


def recent(limit: int = 24) -> list[dict]:
    files = sorted(OUT_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": p.name, "url": f"/out/{p.name}",
             "kb": round(p.stat().st_size / 1024)} for p in files[:limit]]


# ---------------------------------------------------------------- HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = "YYImage/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {fmt % args}\n")

    # -- 工具
    def send_json(self, obj, code: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, cache: str = "no-cache"):
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    # -- GET
    def do_GET(self):
        route = self.path.split("?")[0]
        if route in ("/", "/index.html"):
            self.send_file(WEB_DIR / "index.html")
        elif route == "/api/models":
            try:
                ids = [m["id"] for m in upstream("/models", None, 30).get("data", [])]
            except Exception as e:
                ids = FALLBACK_MODELS
                sys.stderr.write(f"取模型列表失败，用内置列表: {e}\n")
            self.send_json({"models": ids or FALLBACK_MODELS, "default": DEFAULT_MODEL})
        elif route == "/api/recent":
            self.send_json({"images": recent()})
        elif route.startswith("/out/"):
            name = route[len("/out/"):]
            if not SAFE_NAME.match(name) or not name.endswith(".png"):
                self.send_error(400)
                return
            self.send_file(OUT_DIR / name, cache="max-age=3600")
        else:
            self.send_error(404)

    # -- POST
    def do_POST(self):
        if self.path.split("?")[0] != "/api/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self.send_json({"error": "请求体不是合法 JSON"}, 400)
            return

        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            self.send_json({"error": "提示词不能为空"}, 400)
            return
        if len(prompt) > MAX_PROMPT:
            self.send_json({"error": f"提示词超长（上限 {MAX_PROMPT} 字）"}, 400)
            return
        size = body.get("size") or "1024x1024"
        if size not in ALLOWED_SIZES:
            self.send_json({"error": f"不支持的尺寸: {size}"}, 400)
            return
        try:
            n = max(1, min(4, int(body.get("n") or 1)))
        except (TypeError, ValueError):
            n = 1
        model = (body.get("model") or DEFAULT_MODEL).strip()

        try:
            self.send_json(generate(prompt, model, size, n))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            self.send_json({"error": f"上游返回 HTTP {e.code}", "detail": detail}, 502)
        except urllib.error.URLError as e:
            self.send_json({"error": f"上游连接失败: {e.reason}"}, 502)
        except Exception as e:
            self.send_json({"error": f"生成失败: {e}"}, 500)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()

    if not CFG.get("YYT_API_KEY"):
        sys.exit(f"缺少 API Key，请检查 {ENV_FILE}")

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.daemon_threads = True
    print(f"生图网站已启动 → http://{a.host}:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)


if __name__ == "__main__":
    main()
