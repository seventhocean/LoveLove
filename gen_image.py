#!/usr/bin/env python3
"""YY AI 生图命令行工具。

凭据从同目录 gen-image.env 或环境变量读取，不写在代码里。

用法:
    ./gen_image.py "a cat on a windowsill"
    ./gen_image.py "..." -m seedream-5.5（A） -s 1024x1536 -o out/cat.png
    ./gen_image.py "..." --list-models
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV_FILE = HERE / "gen-image.env"

DEFAULT_MODEL = "gpt-image-1"
DEFAULT_SIZE = "1024x1024"


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
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            # 环境变量优先于文件
            if not cfg.get(k):
                cfg[k] = v
    missing = [k for k in ("YYT_BASE_URL", "YYT_API_KEY") if not cfg.get(k)]
    if missing:
        sys.exit(f"缺少配置: {', '.join(missing)}（检查 {ENV_FILE} 或环境变量）")
    return cfg


def headers(cfg: dict[str, str]) -> dict[str, str]:
    h = {
        "Authorization": f"Bearer {cfg['YYT_API_KEY']}",
        "Content-Type": "application/json",
    }
    if cfg.get("YYT_ACTOR_HEADER"):
        h["x-openai-actor-authorization"] = cfg["YYT_ACTOR_HEADER"]
    return h


def request_json(cfg: dict[str, str], path: str, payload: dict | None, timeout: int) -> dict:
    url = cfg["YYT_BASE_URL"].rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers=headers(cfg), method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:800]
        sys.exit(f"HTTP {e.code} {url}\n{body}")
    except urllib.error.URLError as e:
        sys.exit(f"连接失败 {url}: {e.reason}")


def list_models(cfg: dict[str, str]) -> None:
    d = request_json(cfg, "/models", None, 30)
    for m in d.get("data", []):
        print(f"{m.get('id')}")


def save_image(item: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        out.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as r:
            out.write_bytes(r.read())
    else:
        sys.exit(f"响应里没有图片数据，字段: {list(item.keys())}")


def generate(cfg, prompt, model, size, out, n, timeout, retries) -> None:
    payload = {"model": model, "prompt": prompt, "n": n, "size": size}
    for attempt in range(1, retries + 1):
        t0 = time.time()
        try:
            d = request_json(cfg, "/images/generations", payload, timeout)
        except SystemExit:
            if attempt == retries:
                raise
            print(f"第 {attempt} 次失败，{3 * attempt}s 后重试…", file=sys.stderr)
            time.sleep(3 * attempt)
            continue
        items = d.get("data") or []
        if not items:
            sys.exit(f"响应无 data: {json.dumps(d)[:400]}")
        for i, item in enumerate(items):
            target = out if n == 1 else out.with_name(f"{out.stem}-{i + 1}{out.suffix}")
            save_image(item, target)
            print(f"已保存 {target}  ({target.stat().st_size / 1024:.0f} KB, "
                  f"{time.time() - t0:.1f}s, model={model}, size={size})")
        return


def main() -> None:
    p = argparse.ArgumentParser(description="YY AI 生图")
    p.add_argument("prompt", nargs="?", help="画面描述")
    p.add_argument("-m", "--model", default=DEFAULT_MODEL)
    p.add_argument("-s", "--size", default=DEFAULT_SIZE)
    p.add_argument("-o", "--out", default="out/image.png")
    p.add_argument("-n", "--num", type=int, default=1)
    p.add_argument("-t", "--timeout", type=int, default=300, help="单次请求超时秒数")
    p.add_argument("-r", "--retries", type=int, default=2)
    p.add_argument("--list-models", action="store_true")
    a = p.parse_args()

    cfg = load_env()
    if a.list_models:
        list_models(cfg)
        return
    if not a.prompt:
        p.error("需要 prompt")
    generate(cfg, a.prompt, a.model, a.size, Path(a.out), a.num, a.timeout, a.retries)


if __name__ == "__main__":
    main()
