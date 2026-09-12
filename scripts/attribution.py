#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""归因模块（attribution）· 任务板规格 v1 · 2026-09-12
====================================

输入：一组日粒度数据点（jsonl，每天一行）：
  {"date": "2026-08-30", "action": "publish", "title": "...", "delta_likes": 12, "comments": 2}
  - action ∈ publish(发文) / hotlist(上热榜) / none(无动作)（可扩展 interact 等）
  - delta_likes = 当日互动增量（涨跌，可负）
  - comments = 当日评论数（辅助信号）

输出：归因卡（每天一张）：
  {"date": ..., "cause": "一句话原因", "confidence": "高|中|低", "next_action": "...", "falsify": "..."}

判断规则（v1，任务板原文口径）：
  1. 涨 + 当天有明确动作（发文/上热榜）→ 归因到该动作；
     其中 delta 大且评论同步涨 → 可信度高；否则中。
  2. 跌/平 + 当天有动作 → 标「动作负效应待验证」，可信度低——不硬编「内容不行」。
  3. 当天无动作 → 「外部因素/波动」，可信度低（标不知道）。
  4. 全程零波动 → 提示样本期无信号，不出归因卡。

产品价值观：宁可标「不知道」，不硬编原因；每张卡带失效条件。

用法：
  python scripts/attribution.py --demo                 # 内置 50 天真实聚合样例（见 --from-real）
  python scripts/attribution.py --in data/real/contents_zhihu_20260910.jsonl --from-real --out out/attribution_demo.json
  python scripts/attribution.py --in my_points.jsonl --out out/attribution.json

--from-real：从 zhihu_fetch 抓的全量创作 jsonl 聚合出「最近 50 天」日粒度数据点
（按 CreatedAt 日分组：当日发文=action=publish，当日总赞差=delta_likes 近似口径见 NOTE）。
"""
import argparse
import datetime
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DAY_NODES_HOURS = None  # 预留：日内节点归因在 cards.day_card，本模块管日粒度


def load_points(path):
    pts = []
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if "date" in d and "delta_likes" in d:
                pts.append(d)
    pts.sort(key=lambda x: x["date"])
    return pts


def aggregate_from_real(path, days=50):
    """从 zhihu_fetch 全量创作 jsonl 聚合出日粒度数据点。

    口径 NOTE（诚实声明）：
    - LikeCount 是「抓取时点的累计值」，不是当日增量；用「同日多篇按抓取批次求和的变化」无法精确还原历史日增量。
    - 因此本聚合采用「按发布日分组」：当日发布的条目数 = action 强度；当日所有条目的当前赞合计 = 该日动作的最终回报（事后口径）。
    - delta_likes 用「该日条目赞合计」近似（事后回报），并在输出 note 里标注口径；真实「当日增量」需 sampler 快照差分（赛期数据积累后自动升级）。
    """
    by_day = defaultdict(lambda: {"items": 0, "likes": 0, "comments": 0, "titles": []})
    with open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                d = json.loads(ln)
            except json.JSONDecodeError:
                continue
            ts = d.get("CreatedAt") or 0
            if not ts:
                continue
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            g = by_day[day]
            g["items"] += 1
            g["likes"] += d.get("LikeCount") or 0
            g["comments"] += d.get("CommentCount") or 0
            if d.get("Title"):
                g["titles"].append(d["Title"][:40])
    days_sorted = sorted(by_day.keys())
    recent = days_sorted[-days:] if len(days_sorted) > days else days_sorted
    pts = []
    prev_likes = None
    for day in recent:
        g = by_day[day]
        if prev_likes is None:
            delta = g["likes"]
        else:
            delta = g["likes"] - prev_likes
        prev_likes = g["likes"]
        pts.append({
            "date": day,
            "action": "publish" if g["items"] else "none",
            "title": g["titles"][0] if g["titles"] else "",
            "delta_likes": delta,
            "comments": g["comments"],
            "items": g["items"],
            "_note": "事后口径：该日条目当前赞合计/差分，非实时日增量",
        })
    return pts


def _med_comment_floor(pts):
    """评论数中位数，作为『评论同步活跃』的地板线（v1 用简单中位数）。"""
    cs = sorted(p.get("comments") or 0 for p in pts)
    return cs[len(cs) // 2] if cs else 0


def attribute_points(pts):
    cards = []
    floor = _med_comment_floor(pts)
    for p in pts:
        act = (p.get("action") or "none").lower()
        d = p.get("delta_likes") or 0
        c = p.get("comments") or 0
        if d == 0 and act == "none":
            cards.append({"date": p["date"], "cause": "无动作且无波动——无信号日",
                          "confidence": "低", "next_action": "保持节奏，无需动作",
                          "falsify": "若连续多日零信号，检查数据源是否断流"})
            continue
        if d > 0 and act in ("publish", "hotlist"):
            label = "发布《%s》" % p.get("title", "") if act == "publish" else "登上热榜"
            if d >= 10 and c > floor:
                conf = "高"
                why = "涨 %d 且评论同步活跃（%d 条 > 中位数 %d）→ 归因到%s，信号可信" % (d, c, floor, label)
            else:
                conf = "中"
                why = "涨 %d 但互动单薄（评论 %d）→ 可能是%s+自然波动叠加，归因为主因、置信降档" % (d, c, label)
            cards.append({"date": p["date"], "cause": why, "confidence": conf,
                          "next_action": ("该类内容加做一条（同角度/同结构）；24h 后复采样验证是否复现"
                                          if conf == "高" else "同题材再发一条小成本试水，先别加大投入"),
                          "falsify": "若同结构下一篇不涨 → 推翻『结构归因』，转向选题/时机变量"})
        elif d < 0 and act in ("publish", "hotlist"):
            cards.append({"date": p["date"],
                          "cause": "跌 %d 且当天有动作——动作负效应待验证，不硬编『内容不行』" % d,
                          "confidence": "低",
                          "next_action": "对照同期同类内容的平均表现，单日下跌不下结论",
                          "falsify": "若同类内容连续 3 篇同期下跌 → 才升级为『题材/结构问题』"})
        elif act == "none":
            cards.append({"date": p["date"],
                          "cause": "当日无动作，涨跌 %d 判为外部因素/波动，不硬编原因" % d,
                          "confidence": "低",
                          "next_action": "无需响应；若连续放大，查热榜/竞品是否分流",
                          "falsify": "若后续发现当日实际有分发事件（如旧文被推荐）→ 补录事件后重算"})
        else:  # d>0 且 act==none 已被上一支覆盖；d<0 且 none 已覆盖；此处为防御分支
            cards.append({"date": p["date"], "cause": "数据不完整，无法归因",
                          "confidence": "低", "next_action": "补录当日动作清单后重跑",
                          "falsify": "—"})
    return cards


def main():
    ap = argparse.ArgumentParser(description="看山 · 归因模块（日粒度数据点 → 归因卡）")
    ap.add_argument("--in", dest="inp", help="数据点 jsonl（含 date/delta_likes 字段）")
    ap.add_argument("--from-real", action="store_true", help="输入是 zhihu_fetch 全量创作 jsonl，先聚合")
    ap.add_argument("--days", type=int, default=50, help="--from-real 取最近 N 天（默认 50）")
    ap.add_argument("--demo", action="store_true", help="直接用 data/real 真实账号跑演示（等价 --from-real）")
    ap.add_argument("--out", help="输出 json 路径（默认打印到 stdout）")
    args = ap.parse_args()

    src = args.inp
    if args.demo and not src:
        cand = os.path.join(ROOT, "data", "real")
        if os.path.isdir(cand):
            files = sorted(f for f in os.listdir(cand) if f.endswith(".jsonl"))
            if files:
                src = os.path.join(cand, files[-1])
    if not src:
        print("需要 --in <jsonl> 或 --demo 或 --from-real，见 --help", file=sys.stderr)
        sys.exit(1)

    if args.from_real or args.demo:
        pts = aggregate_from_real(src, days=args.days)
        mode = "real-aggregated"
    else:
        pts = load_points(src)
        mode = "points"

    cards = attribute_points(pts)
    result = {
        "schema": "kanshan.attribution/1",
        "mode": mode,
        "source": os.path.basename(src),
        "n_points": len(pts),
        "confidence_dist": {k: sum(1 for c in cards if c["confidence"] == k) for k in ("高", "中", "低")},
        "note": ("--from-real 口径：按发布日聚合的事后回报，非实时日增量；实时口径待 sampler 快照差分数据积累后升级"
                 if mode == "real-aggregated" else "输入即日粒度数据点"),
        "cards": cards,
        "falsify": "规则 v1 为演示口径：涨跌阈值 10 / 评论中位数地板均为启发式，用你账号后续表现复核后应再校准",
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("已写出 %s（%d 张归因卡，高/中/低=%s）" % (
            args.out, len(cards), "/".join(str(result["confidence_dist"][k]) for k in ("高", "中", "低"))))
    else:
        print(text)


if __name__ == "__main__":
    main()
