#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 基底图生成（机理/原理示意图可选项）。

用途：生成"无文字"的科学插图基底图，供 SVG 叠中文标注后合成论文机理图。
支持返回 b64_json 或 URL 的 OpenAI 兼容接口（中转站常用 URL）。
零依赖核心逻辑（仅 PNG 转换需 Pillow）；走标准代理环境变量（https_proxy 等）。

用法：
    OPENAI_API_KEY=... OPENAI_BASE_URL=https://api.xxx.com/v1 \
    python ai_figure_gen.py --prompt "..." --out base.png \
        --model gpt-image-2 --size 1536x1024,1024x1024 --quality low,medium --retries 4

已知坑（2026-08-12 实测收编）：
  - 中转站拦截官方 SDK User-Agent（403）→ 本脚本默认用浏览器 UA。
  - 中转网关 60s 硬超时 → high/medium 易被掐断，low 档实测可过；脚本自动按
    size × quality 降档重试。
  - 账号池满载返回 503 "No available compatible accounts" → 等待后自动重试。
  - 必须走代理（境外 IP）时，设 https_proxy/http_proxy 环境变量即可。
"""

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def post_json(url: str, payload: dict, api_key: str, timeout: int):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json",
                 "User-Agent": UA},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # RemoteDisconnected / timeout 等
        return 0, f"{type(e).__name__}: {e}"


def download(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def save(raw: bytes, out: str) -> None:
    if out.lower().endswith(".png"):
        try:
            from PIL import Image
        except ImportError:
            sys.exit("[错误] 输出 PNG 需要 Pillow：pip install pillow（或把 --out 后缀改为 .jpg）")
        Image.open(io.BytesIO(raw)).convert("RGB").save(out, "PNG")
    else:
        with open(out, "wb") as f:
            f.write(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 基底图生成（无文字科学插图）")
    ap.add_argument("--prompt", help="生成提示词")
    ap.add_argument("--prompt-file", help="提示词文件（与 --prompt 二选一）")
    ap.add_argument("--out", required=True, help="输出路径（.png 需 Pillow，.jpg 零依赖）")
    ap.add_argument("--model", default="gpt-image-2")
    ap.add_argument("--size", default="1536x1024,1024x1024",
                    help="逗号分隔的尺寸候选，按序尝试")
    ap.add_argument("--quality", default="low,medium",
                    help="逗号分隔的质量候选，按序尝试")
    ap.add_argument("--watermark", choices=["true", "false"], default=None,
                    help="是否带水印（火山 Seedream 默认 true；论文图建议 false）")
    ap.add_argument("--retries", type=int, default=3, help="完整轮数重试上限")
    ap.add_argument("--timeout", type=int, default=120, help="单请求超时（秒）")
    ap.add_argument("--sleep", type=int, default=20, help="每轮失败后等待秒数")
    args = ap.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if not api_key:
        sys.exit("[错误] 未设置 OPENAI_API_KEY")
    if args.prompt_file:
        with open(args.prompt_file, encoding="utf-8") as f:
            prompt = f.read().strip()
    else:
        prompt = args.prompt
    if not prompt:
        sys.exit("[错误] 需要 --prompt 或 --prompt-file")

    sizes = [s for s in args.size.split(",") if s]
    qualities = [q for q in args.quality.split(",") if q]
    if "seedream" in args.model.lower():
        # 火山 Seedream 要求 size ≥ 3,686,400 px（约 1920x1920 起）
        seed_sizes = ["2048x2048", "2560x1440", "1440x2560"]
        if args.size == "1536x1024,1024x1024":  # 未显式指定时
            sizes = seed_sizes
    url = base.rstrip("/") + "/images/generations"

    for attempt in range(1, args.retries + 1):
        for size in sizes:
            for q in qualities:
                print(f"[尝试 {attempt}/{args.retries}] {size} quality={q} ...",
                      file=sys.stderr)
                payload = {"model": args.model, "prompt": prompt, "n": 1,
                           "size": size, "quality": q}
                if args.watermark:
                    payload["watermark"] = args.watermark == "true"
                status, d = post_json(url, payload, api_key, args.timeout)
                if status != 200:
                    print(f"  -> HTTP {status}: {str(d)[:150]}", file=sys.stderr)
                    continue
                item = d["data"][0]
                if item.get("b64_json"):
                    raw = base64.b64decode(item["b64_json"])
                elif item.get("url"):
                    try:
                        raw = download(item["url"], args.timeout)
                    except Exception as e:
                        print(f"  下载失败: {e}", file=sys.stderr)
                        continue
                else:
                    print(f"未知响应格式: {item}", file=sys.stderr)
                    return 1
                save(raw, args.out)
                print(f"OK [{size} {q}] saved {args.out} ({len(raw)} bytes)")
                return 0
        print(f"本轮全部失败，等 {args.sleep}s 重试", file=sys.stderr)
        time.sleep(args.sleep)
    print("[失败] 所有尝试均未成功", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
