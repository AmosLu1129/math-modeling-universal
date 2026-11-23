#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 Word 97-2003 .doc 附件中还原内嵌图片（JPEG/PNG/EMF/WMF/DIB）。

背景（2011 国赛 B 实测教训）：textutil 转 docx/html 会**静默丢图**；无
LibreOffice/Word 可用时，直接解析 OLE `Data` 流里的 OfficeArt Blip 记录还原原图，
再交给视觉判读，否则题面图件信息全部丢失。

用法：
    python doc_extract_images.py input/problem.doc --out work/problem_pages/doc_images
    python doc_extract_images.py input/problem.doc --out /tmp/docimg --render-emf

流程：
    1) olefile 逐条扫描 OLE 流（Data / 1Table / 0Table / WordDocument ≥1KB 的都扫）
    2) 识别 OfficeArt 记录头（inst/ver 2B + recType 2B + recLen 4B），取
       F01A=EMF / F01B=WMF / F01C=PICT / F01D=JPEG / F01E=PNG / F01F=DIB 的 blip
    3) JPEG/PNG 在 payload 内按魔数截取；EMF 按 uid16B + tag + metafile header
       （compression=0x04 时 zlib 解压）还原，还原结果以 EMF 签名 " EMF"（偏移 40）校验
    4) --render-emf 时调 npm 包 `emf-to-png`（WASM libemf2svg+resvg）把 EMF 渲染成
       PNG 供视觉判读；drawio/qlmanage 对 EMF 均不可靠，勿用

输出：outdir 下按发现顺序命名 img_01.jpg / img_02.emf …，另写 manifest.json
（来源流、偏移、类型、大小、md5）。重复内容按 md5 去重。

验证记录：2026-08-28 用 2011 国赛 B 真实附件 problem.doc 回归，还原的 JPEG 与 EMF
和当时人工提取产物 md5 逐字节一致（fig_attachment1_jpeg.jpg / fig_attachment1_emf.emf）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

BLIP_TYPES = {
    0xF01A: "emf",
    0xF01B: "wmf",
    0xF01C: "pict",
    0xF01D: "jpg",
    0xF01E: "png",
    0xF01F: "dib",
}

PNG_SIG = b"\x89PNG\r\n\x1a\n"
JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"
EMF_SIG = b" EMF"  # EMF 头第 40 字节起的签名
WMF_PLACEABLE = b"\xd7\xcd\xc6\x9a"
BMP_INFOHDR = b"\x28\x00\x00\x00"  # BITMAPINFOHEADER（biSize=40）首 4 字节


def md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def extract_jpeg(payload: bytes) -> bytes | None:
    start = payload.find(JPEG_SOI)
    if start < 0:
        return None
    end = payload.rfind(JPEG_EOI)
    if end <= start:
        return None
    data = payload[start : end + 2]
    return data if len(data) > 512 else None


def extract_png(payload: bytes) -> bytes | None:
    start = payload.find(PNG_SIG)
    if start < 0:
        return None
    end = payload.find(b"IEND", start)
    if end < 0:
        return None
    data = payload[start : end + 8]  # IEND + 4B CRC
    return data if len(data) > 512 else None


def extract_emf(payload: bytes) -> bytes | None:
    # 压缩路径：uid16B + tag1B + metafile header 后是 zlib 流；逐偏移试解，
    # 以输出偏移 40 处含 " EMF" 签名且首 4 字节 iType=1 为准。
    limit = min(len(payload) - 8, 96)
    for skip in range(16, limit):
        try:
            out = zlib.decompressobj().decompress(payload[skip:])
        except zlib.error:
            continue
        if len(out) > 1024 and out.find(EMF_SIG) == 40:
            itype, = struct.unpack_from("<I", out, 0)
            if itype == 1:
                return out
    # 未压缩路径：直接在 payload 里找 EMF 头（iType=1 且偏移 40 处是签名）
    pos = payload.find(EMF_SIG)
    while pos >= 40:
        start = pos - 40
        itype, nsize = struct.unpack_from("<II", payload, start)
        if itype == 1 and nsize >= 88:
            return payload[start:]
        pos = payload.find(EMF_SIG, pos + 1)
    return None


def extract_wmf(payload: bytes) -> bytes | None:
    pos = payload.find(WMF_PLACEABLE)
    if pos >= 0:
        data = payload[pos:]
        return data if len(data) > 512 else None
    # 标准 WMF：01 00 09 00 开头（mtHeader=1, mtVersion=9）
    pos = payload.find(b"\x01\x00\x09\x00")
    if pos >= 0:
        data = payload[pos:]
        return data if len(data) > 512 else None
    return None


def extract_dib(payload: bytes) -> bytes | None:
    pos = payload.find(BMP_INFOHDR)
    if pos < 0:
        return None
    header_size, = struct.unpack_from("<I", payload, pos)
    if header_size != 40:
        return None
    dib = payload[pos:]
    # 补 BITMAPFILEHEADER（14B）：bfType + 文件大小 + 保留 + bfOffBits
    fh = b"BM" + struct.pack("<IHHI", 14 + len(dib), 0, 0, 14 + header_size)
    data = fh + dib
    return data if len(data) > 512 else None


EXTRACTORS = {
    0xF01A: extract_emf,
    0xF01B: extract_wmf,
    0xF01D: extract_jpeg,
    0xF01E: extract_png,
    0xF01F: extract_dib,
}


def scan_stream(name: str, blob: bytes, seen: set[str]) -> list[dict]:
    """单流扫描：命中 blip 记录即提取；返回带数据的条目列表（md5 去重）。"""
    found: list[dict] = []
    n = len(blob)
    off = 0
    while off + 12 <= n:
        # 廉价预筛：OfficeArt blip 的 recType 低字节 0x1A–0x1F、高字节 0xF0
        if blob[off + 3] != 0xF0 or not (0x1A <= blob[off + 2] <= 0x1F):
            off += 1
            continue
        rtype, rlen = struct.unpack_from("<HI", blob, off + 2)
        if rtype not in BLIP_TYPES or rlen < 64 or off + 8 + rlen > n:
            off += 1
            continue
        payload = blob[off + 8 : off + 8 + rlen]
        data = EXTRACTORS[rtype](payload)
        if data:
            checksum = md5(data)
            if checksum not in seen:
                seen.add(checksum)
                found.append({
                    "stream": name,
                    "offset": off,
                    "type": f"0x{rtype:04X}",
                    "ext": BLIP_TYPES[rtype],
                    "size": len(data),
                    "md5": checksum,
                    "record_len": rlen,
                    "data": data,
                })
            off += 8 + rlen  # 命中则跳过整条记录，避免在图像数据里重复命中
        else:
            off += 1
    return found


def render_emf_files(emf_paths: list[Path], width: int) -> list[Path]:
    npx = shutil.which("npx")
    rendered: list[Path] = []
    for emf in emf_paths:
        out = emf.with_suffix(".png")
        if not npx:
            print(f"[warn] 未找到 npx，跳过渲染 {emf.name}（安装 node 后用 `npx emf-to-png` 重试）")
            continue
        # emf-to-png（WASM libemf2svg+resvg）是实测唯一可靠的 EMF 渲染通道；
        # EMF 原始尺寸往往只有几百 px，供 vision 判读需放大到 1600px 宽
        proc = subprocess.run(
            [npx, "emf-to-png", str(emf), str(out), "--width", str(width)],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode == 0 and out.exists() and out.stat().st_size > 1024:
            rendered.append(out)
            print(f"[render] {emf.name} -> {out.name}（{out.stat().st_size} B）")
        else:
            print(f"[warn] {emf.name} 渲染失败：{(proc.stderr or proc.stdout).strip()[:200]}")
    return rendered


def main() -> int:
    ap = argparse.ArgumentParser(description="从 .doc 提取内嵌图片（OfficeArt Blip 还原）")
    ap.add_argument("doc", type=Path, help="Word 97-2003 .doc 文件")
    ap.add_argument("--out", type=Path, required=True, help="输出目录")
    ap.add_argument("--render-emf", action="store_true", help="用 npx emf-to-png 渲染 EMF 为 PNG")
    ap.add_argument("--emf-width", type=int, default=1600, help="EMF 渲染目标宽度 px（默认 1600）")
    args = ap.parse_args()

    try:
        import olefile
    except ImportError:
        print("缺依赖：pip install olefile", file=sys.stderr)
        return 2
    if not args.doc.exists():
        print(f"文件不存在：{args.doc}", file=sys.stderr)
        return 2

    ole = olefile.OleFileIO(str(args.doc))
    stream_paths = [s for s in ole.listdir() if ole.get_size("/".join(s)) >= 1024]
    seen: set[str] = set()
    items: list[dict] = []
    for parts in stream_paths:
        name = "/".join(parts)
        items.extend(scan_stream(name, ole.openstream(parts).read(), seen))
    ole.close()

    if not items:
        print("未发现 OfficeArt blip 图片；若题面确有图，检查是否为 docx（改走 python-docx 或解 zip 的 media/）")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    emf_paths: list[Path] = []
    for i, item in enumerate(items, 1):
        path = args.out / f"img_{i:02d}.{item['ext']}"
        path.write_bytes(item["data"])
        item["file"] = path.name
        del item["data"]
        if item["ext"] == "emf":
            emf_paths.append(path)
        print(f"[extract] {path.name}  {item['ext'].upper()}  {item['size']} B  "
              f"stream={item['stream']} offset={item['offset']} md5={item['md5'][:12]}")

    rendered = render_emf_files(emf_paths, args.emf_width) if args.render_emf else []

    manifest = args.out / "manifest.json"
    manifest.write_text(
        json.dumps({"source": str(args.doc), "images": items,
                    "rendered": [p.name for p in rendered]},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"共 {len(items)} 张图 -> {args.out}（清单 {manifest.name}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
