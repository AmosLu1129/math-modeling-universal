#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献核验：批量校验 references.csv 中的 DOI / arXiv ID 是否真实存在。

用法：
    python verify_references.py --refs work/references.csv
    python verify_references.py --refs work/references.csv --offline   # 仅做格式校验

行为：
  - doi 列：调 Crossref API（https://api.crossref.org/works/<doi>）验证存在性，
    并返回标题首词与作者数（供人工比对，不硬判拼写）。
  - link 列含 arxiv.org：解析 arxiv ID，调 arXiv API 验证存在性与标题。
  - 输出每行状态：OK（存在）/ FAIL（404 不存在）/ WARN（网络或元数据不完整）。
  - 存在 FAIL 时退出码 1。

要求：pip install requests（setup_env.py --install 会装）；请求带 User-Agent 保持礼貌。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import requests
except Exception:
    requests = None  # type: ignore

UA = {"User-Agent": "math-modeling-verify (mailto:team@example.com)"}
ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^/\s?#]+)")


def check_doi(doi: str) -> tuple[str, str]:
    if not requests:
        return "WARN", "requests 未安装（先跑 setup_env.py --install）"
    try:
        r = requests.get(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}",
                         headers=UA, timeout=30)
        if r.status_code == 404:
            return "FAIL", "Crossref 未收录该 DOI"
        if r.status_code != 200:
            return "WARN", f"Crossref HTTP {r.status_code}"
        m = r.json().get("message", {})
        title = (m.get("title") or [""])[0][:60]
        n_author = len(m.get("author", []))
        year = None
        for f in ("published-print", "published-online", "issued"):
            if m.get(f, {}).get("date-parts"):
                year = m[f]["date-parts"][0][0]
                break
        return "OK", f"title: {title!r} | authors: {n_author} | year: {year}"
    except Exception as e:  # noqa: BLE001
        return "WARN", f"网络/解析错误: {e}"


def check_arxiv(link: str) -> tuple[str, str]:
    m = ARXIV_ID_RE.search(link)
    if not m:
        return "WARN", f"无法从 link 解析 arxiv ID: {link}"
    aid = m.group(1)
    if not requests:
        return "WARN", "requests 未安装"
    try:
        r = requests.get("https://export.arxiv.org/api/query",
                         params={"id_list": aid}, headers=UA, timeout=30)
        if r.status_code != 200:
            return "WARN", f"arXiv HTTP {r.status_code}"
        if "<entry>" not in r.text:
            return "FAIL", f"arXiv 未找到 ID {aid}"
        title = re.search(r"<title>(.*?)</title>", r.text, re.S)
        t = (title.group(1).strip()[:60] if title else "?")
        return "OK", f"title: {t!r}"
    except Exception as e:  # noqa: BLE001
        return "WARN", f"网络/解析错误: {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description="参考文献核验（Crossref + arXiv）")
    ap.add_argument("--refs", required=True, help="references.csv 路径")
    ap.add_argument("--offline", action="store_true", help="仅做格式校验，不联网")
    args = ap.parse_args()

    refs = Path(args.refs)
    if not refs.exists():
        print(f"[错误] references.csv 不存在: {refs}")
        return 2

    rows = list(csv.DictReader(refs.open(encoding="utf-8-sig")))
    print(f"待核验 {len(rows)} 条文献\n")
    fails = warns = 0
    for i, row in enumerate(rows, 1):
        doi = (row.get("doi") or "").strip()
        link = (row.get("link") or "").strip()
        title = (row.get("title") or "").strip()[:60]
        if args.offline:
            status, detail = "OK", "离线模式：仅格式检查"
            if doi and not re.match(r"^10\.\d{4,9}/.+", doi):
                status, detail = "FAIL", "DOI 格式异常"
            if not doi and not link:
                status, detail = "WARN", "无 DOI 且无 link"
        elif doi:
            status, detail = check_doi(doi)
        elif "arxiv.org" in link:
            status, detail = check_arxiv(link)
        else:
            status, detail = "WARN", "无 DOI 且无 arXiv 链接（人工核验标题）"
        if status == "FAIL":
            fails += 1
        if status == "WARN":
            warns += 1
        print(f"[{status:4s}] #{i} {title}")
        print(f"        {detail}")
        if not args.offline:
            time.sleep(0.4)  # 礼貌限速
    print(f"\n完成：{len(rows)} 条，FAIL={fails}，WARN={warns}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
