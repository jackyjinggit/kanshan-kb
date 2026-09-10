#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 红线自动扫描器（2026-09-10）

把 TODO §四 / README §八 里"人工承诺"的红线变成可重复执行的检查。
用法：
    python scripts/redline_scan.py                 # 扫全仓（默认仓库根）
    python scripts/redline_scan.py --check-reports # 追加检查 out/ 下报告含"失效条件"
退出码：0 = 干净；1 = 有命中（可直接当提交前闸门：hit 则拒绝 commit/push）

词典分两层（2026-09-10 修订）：
  · **通用模式**（本文件内）：凭证样式一类与内部无关、对任何使用者都有意义的规则。
  · **私有模式**（本地未追踪文件 scripts/redline_patterns.local.json）：内部人员/本机账号/
    内部术语一类。**不进公开库**——否则脱敏工具自己就成了泄露源（本仓曾踩：词典随脚本入库，
    而扫描器又跳过自己，于是"扫描干净"与"名录公开"同时成立）。
    公开 clone 者只跑通用模式；持有私有词典的本机跑全套。
"""
import argparse
import io
import json
import os
import re
import sys

# ---- 通用红线词典（不含任何内部人名/账号/术语，可安全公开）----
DEFAULT_PATTERNS = {
    # 凭证样式（防手滑提交 key）
    "凭证样式": r"sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}",
}

# ---- 本地私有词典（不入库；新增内部人员/术语往这里加）----
LOCAL_PATTERNS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "redline_patterns.local.json")

# 扫描范围：文本类文件后缀（数据/产物目录整体跳过）
TEXT_EXTS = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".html", ".js", ".ts",
             ".jsonl", ".csv", ".toml", ".cfg", ".ini", ".sh", ".bat", ".ps1"}
SKIP_DIRS = {".git", "data", "out", "node_modules", "__pycache__", ".venv", "venv"}
SELF_NAME = os.path.basename(__file__)                      # 本文件自身跳过
SKIP_NAMES = {SELF_NAME, os.path.basename(LOCAL_PATTERNS_FILE)}  # 私有词典同样跳过（它必然自命中）


def load_patterns():
    """通用模式 + 本地私有模式（后者存在则合并）。"""
    patterns = dict(DEFAULT_PATTERNS)
    if os.path.isfile(LOCAL_PATTERNS_FILE):
        try:
            with io.open(LOCAL_PATTERNS_FILE, "r", encoding="utf-8") as f:
                local = json.load(f)
            n = 0
            for key, pat in local.items():
                if key.startswith("_") or not isinstance(pat, str):
                    continue          # 下划线开头的键是说明性字段
                patterns[key] = pat
                n += 1
            print(f"[info] 已加载本地私有词典 {os.path.basename(LOCAL_PATTERNS_FILE)}（{n} 类）")
        except (OSError, ValueError) as e:
            print(f"[warn] 本地私有词典读取失败（按通用模式继续）：{e}")
    else:
        print("[info] 无本地私有词典，仅运行通用模式（公开 clone 的预期状态）")
    return patterns


def iter_files(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if fn in SKIP_NAMES:
                continue
            ext = os.path.splitext(fn)[1].lower()
            if ext in TEXT_EXTS:
                yield os.path.join(dirpath, fn)


def scan_file(path: str, patterns: dict):
    """返回 [(类别, 行号, 行摘录)]"""
    hits = []
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for cat, pat in patterns.items():
                    if re.search(pat, line):
                        snippet = line.strip()
                        if len(snippet) > 80:
                            snippet = snippet[:80] + "…"
                        hits.append((cat, lineno, snippet))
                        break  # 一行最多报一次，避免刷屏
    except OSError as e:
        print(f"[warn] 读不了 {path}: {e}")
    return hits


def check_reports(root: str):
    """检查 out/ 下每份 .md 报告是否含『失效条件』章节（README §八 红线3）"""
    out_dir = os.path.join(root, "out")
    problems = []
    if not os.path.isdir(out_dir):
        return problems, 0
    n = 0
    for fn in os.listdir(out_dir):
        if not fn.endswith(".md"):
            continue
        n += 1
        path = os.path.join(out_dir, fn)
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            body = f.read()
        if "失效条件" not in body:
            problems.append(f"out/{fn}：报告缺少『失效条件』（README §八 红线3）")
    return problems, n


def main():
    ap = argparse.ArgumentParser(description="看山红线扫描器")
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    help="仓库根（默认：脚本上上级）")
    ap.add_argument("--check-reports", action="store_true",
                    help="追加检查 out/ 报告含失效条件")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    print(f"== 看山红线扫描 ==\n根目录: {root}\n")

    patterns = load_patterns()
    total_files = 0
    total_hits = 0
    for path in sorted(iter_files(root)):
        total_files += 1
        hits = scan_file(path, patterns)
        if hits:
            rel = os.path.relpath(path, root)
            for cat, lineno, snippet in hits:
                print(f"[HIT] {rel}:{lineno} ({cat}) {snippet}")
                total_hits += 1

    print(f"\n扫描文件数: {total_files}；红线命中: {total_hits}")

    if args.check_reports:
        problems, n = check_reports(root)
        print(f"\n报告失效条件检查: out/ 下 {n} 份 md；缺失效条件 {len(problems)} 份")
        for p in problems:
            print(f"[HIT] {p}")
        total_hits += len(problems)

    if total_hits == 0:
        print("结论: 干净（exit 0）")
        sys.exit(0)
    else:
        print(f"结论: 有 {total_hits} 处命中（exit 1）——提交前必须处理或明确豁免")
        sys.exit(1)


if __name__ == "__main__":
    main()
