#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 小时级采样器：把「累计计数快照」定时采样 → 差分出小时级曲线（日度卡数据源）

为什么需要它：
  官方 `me contents` 只给每篇内容的**此刻累计计数**（Like/Comment/Favorite），不提供
  小时级曲线（signals.py 口径红线同样声明）。本脚本用「定时采样 + 差分」近似出小时级
  增量——纯本地、只调开放平台免费额度、不推断平台没有的指标。

用法：
    python scripts/sampler.py --once                       # 单次采样（追加快照行）
    python scripts/sampler.py --once --limit 20            # 只采样最近 20 篇
    python scripts/sampler.py --loop --interval 1800       # 循环采样（每 30 分钟）
    python scripts/sampler.py --diff                       # 快照差分 → 每篇小时增量表
    python scripts/sampler.py --diff --hours 48            # 看最近 48 小时

快照格式（data/samples/snapshots.jsonl，每行一条）：
    {"schema": "kanshan.sample/1", "ts": <unix秒>, "url": "...", "title": "...",
     "content_type": "...", "like": N, "comment": N, "favorite": N}

纪律：
  · 只记录平台公开返回的计数，不猜不填（不知道就标不知道）。
  · 采样是「累计值快照」；差分前的增量恒为 0 属正常，曲线随采样天数变厚。
  · 每次采样只拉第一页（最近 limit 篇），对免费额度友好。
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.environ.get("LOCALAPPDATA", "") or os.environ.get("HOME", ""),
                   "ZhihuCLI", "current", "zhihu-cli.exe")
DEFAULT_OUT = os.path.join(HERE, os.pardir, "data", "samples", "snapshots.jsonl")
SCHEMA = "kanshan.sample/1"


def fetch_latest(limit):
    """拉最近 limit 篇内容（复用 fetch.py 的 CLI 调用口径）。返回 (items, err)。"""
    if not os.path.exists(CLI):
        return [], "未找到 zhihu-cli：%s" % CLI
    try:
        p = subprocess.run([CLI, "me", "contents", "--type", "all", "--sort", "ts",
                            "--order", "desc", "--offset", "0", "--limit", str(limit)],
                           capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return [], "zhihu-cli 超时（120s）"
    except OSError as e:
        return [], "zhihu-cli 启动失败：%s" % e
    try:
        d = json.loads(p.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return [], "zhihu-cli 输出不是 JSON（大概率未授权）"
    if d.get("Code") != 0:
        return [], "API error: %s" % d.get("Message")
    return (d.get("Data") or {}).get("Items") or [], ""


def sample_once(out_path, limit):
    items, err = fetch_latest(limit)
    if err:
        print("[!] %s" % err)
        return 1
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    ts = int(time.time())
    n = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for it in items:
            url = it.get("Url") or it.get("Id") or ""
            if not url:
                continue
            f.write(json.dumps({
                "schema": SCHEMA, "ts": ts, "url": url,
                "title": (it.get("Title") or "")[:80],
                "content_type": it.get("ContentType") or "",
                "like": it.get("LikeCount") or 0,
                "comment": it.get("CommentCount") or 0,
                "favorite": it.get("FavoriteCount") or 0,
            }, ensure_ascii=False) + "\n")
            n += 1
    print("[+] %s 采样 %d 篇 -> %s" % (
        datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), n, out_path))
    return 0


def diff(out_path, hours):
    """快照 → 每篇每小时增量（相邻采样点差分，挂到后一采样点的小时槽）。"""
    if not os.path.exists(out_path):
        print("[!] 还没有快照文件：%s（先跑 --once）" % out_path)
        return 1
    rows = []
    with open(out_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 坏行降级
    if len(rows) < 2:
        print("[!] 快照只有 %d 行，差分至少要 2 轮采样——等下一轮再跑 --diff" % len(rows))
        return 1

    since = time.time() - hours * 3600
    by_url = {}
    for r in rows:
        if r.get("ts", 0) < since:
            continue
        by_url.setdefault(r.get("url", ""), []).append(r)

    L = ["# 小时级增量差分（最近 %d 小时 · %d 篇有采样）" % (hours, len(by_url)), ""]
    rounds = {}
    for pts in by_url.values():
        pts.sort(key=lambda x: x["ts"])
        for p in pts:
            t = datetime.datetime.fromtimestamp(p["ts"]).strftime("%m-%d %H:%M")
            rounds[t] = rounds.get(t, 0) + 1
    L.append("采样轮次：%s" % "、".join("%s(%d篇)" % (t, c) for t, c in sorted(rounds.items())))
    if len(rounds) < 2:
        L.append("")
        L.append("> ⚠️ 目前只有 %d 轮采样——差分至少需要 2 轮。等计划任务跑出下一轮后再看本表。" % len(rounds))
    L.append("")
    any_gain = False
    for url, pts in sorted(by_url.items(), key=lambda kv: -(kv[1][-1]["ts"] if kv[1] else 0)):
        pts.sort(key=lambda x: x["ts"])
        if len(pts) < 2:
            continue
        title = pts[0].get("title") or url
        L.append("## %s" % title)
        L.append("")
        L.append("| 时间(点) | 赞增量 | 评增量 | 藏增量 |")
        L.append("|---|---|---|---|")
        prev = pts[0]
        for cur in pts[1:]:
            dl = cur["like"] - prev["like"]
            dc = cur["comment"] - prev["comment"]
            df = cur["favorite"] - prev["favorite"]
            if dl or dc or df:
                any_gain = True
            t = datetime.datetime.fromtimestamp(cur["ts"]).strftime("%m-%d %H:%M")
            L.append("| %s | %+d | %+d | %+d |" % (t, dl, dc, df))
        last = pts[-1]
        L.append("")
        L.append("最新累计：赞 %d · 评 %d · 藏 %d（采样 %d 轮，首轮 %s）" % (
            last["like"], last["comment"], last["favorite"], len(pts),
            datetime.datetime.fromtimestamp(pts[0]["ts"]).strftime("%m-%d %H:%M")))
        L.append("")
    if not any_gain:
        L.append("> 注：窗口内计数零变化（采样尚未跨过内容自然增长期）——增量恒为 0 属正常，")
        L.append("> 不推断平台未提供的指标；曲线随采样天数变厚。")
    print("\n".join(L))
    return 0


def main():
    ap = argparse.ArgumentParser(description="看山 · 小时级采样器")
    ap.add_argument("--once", action="store_true", help="单次采样")
    ap.add_argument("--loop", action="store_true", help="循环采样（配 --interval）")
    ap.add_argument("--interval", type=int, default=1800, help="循环间隔秒数（默认 1800=30 分钟）")
    ap.add_argument("--limit", type=int, default=50, help="每次采样最近 N 篇（默认 50，只拉第一页）")
    ap.add_argument("--diff", action="store_true", help="差分输出小时增量表（不采样）")
    ap.add_argument("--hours", type=int, default=24, help="差分回看窗口小时数（默认 24）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="快照文件路径")
    a = ap.parse_args()
    out = os.path.abspath(a.out)

    if a.diff:
        return diff(out, a.hours)
    if a.loop:
        print("[~] 循环采样：每 %d 秒一轮，Ctrl+C 停止" % a.interval)
        while True:
            sample_once(out, a.limit)
            time.sleep(a.interval)
    if a.once:
        return sample_once(out, a.limit)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
