#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 信号层：把创作数据（JSONL）压成一组**可判定的数值信号**

为什么单独一层：
  · 诊断层（`zhihu_diagnose.py`）输出给人读的报告；处方层（`prescribe.py`）需要机器可判定的数字。
  · 把「算数」集中在这里，处方规则只做「阈值 → 动作」的判断，两层都能单独测（见 `tests/`）。

口径纪律（与诊断层一致，不许放宽）：
  · **同期对照**：基线取「近期窗口」，不取全量——全量基线会被历史爆款拉高，得出反向结论。
  · **数据内锚点**：以数据里最新一条的时间为「现在」，输出与墙钟无关（同名/同数据可复现）。
  · **不知道就标不知道**：粉丝数、曝光量、小时级点击率公开接口不提供——本层不猜、不填。

用法：
    python scripts/signals.py --in data/contents.jsonl [--days 30] [--out signals.json]
"""
import argparse
import datetime
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import zhihu_diagnose as zd  # noqa: E402  （复用题材词表 / CTA 词表，单一真源）

SCHEMA = "kanshan.signals/1"
MIN_RECENT_FOR_BASELINE = 8   # 近期窗口样本不足时回退全量，并在 notes 里声明
MIN_GROUP_N = 3               # 分组对比（题材/形态/星期）的最小样本数，低于此不出结论

TITLE_QUESTION = re.compile(r"[?？]|为什么|怎么办|如何|该不该|是不是|值不值|要不要|吗$")


def interact(it):
    """互动总量 = 赞 + 评 + 藏（三列公开接口原值，不做加权猜测）"""
    return (it.get("LikeCount") or 0) + (it.get("CommentCount") or 0) + (it.get("FavoriteCount") or 0)


def attach_dt(items):
    """给原始条目补 dt；CreatedAt<=0 或缺失的行按无效丢弃（避免 1970 年污染年度分组）"""
    out, dropped = [], 0
    for it in items:
        if not isinstance(it, dict):
            dropped += 1
            continue
        try:
            ts = int(it.get("CreatedAt") or 0)
        except (TypeError, ValueError):
            dropped += 1
            continue
        if ts <= 0:
            dropped += 1
            continue
        it = dict(it)
        it["dt"] = datetime.datetime.fromtimestamp(ts)
        out.append(it)
    return out, dropped


def load_items(path):
    """读 JSONL（坏行降级复用诊断层实现，行为一致）"""
    return zd.load(path)


def group_stats(subset):
    n = len(subset)
    if not n:
        return {"n": 0, "interact_mean": 0.0, "like_mean": 0.0, "like_max": 0,
                "zero_like_rate": 0.0, "has_comment_rate": 0.0, "interact_median": 0.0}
    ints = [interact(x) for x in subset]
    likes = [x.get("LikeCount") or 0 for x in subset]
    comments = [x.get("CommentCount") or 0 for x in subset]
    return {
        "n": n,
        "interact_mean": sum(ints) / n,
        "interact_median": statistics.median(ints),
        "like_mean": sum(likes) / n,
        "like_max": max(likes),
        "zero_like_rate": sum(1 for x in likes if x == 0) / n,
        "has_comment_rate": sum(1 for x in comments if x > 0) / n,
    }


def _pct(new, base):
    """相对变化率；base<=0 时返回 None（不制造无意义的百分比）"""
    if not base or base <= 0:
        return None
    return (new - base) / base


def _topic_of(it):
    text = (it.get("Title") or "") + " " + (it.get("Summary") or "")
    hits = [g for g, p in zd.TOPIC_PATTERNS.items() if re.search(p, text, re.I)]
    return hits[0] if hits else None


def extract(items, days=30, source="", user=""):
    """核心入口：items 需已带 dt（用 attach_dt）。缺少 dt 时自动补，避免调用方踩 KeyError"""
    items = list(items or [])
    if items and "dt" not in items[0]:
        items, _ = attach_dt(items)
    items = sorted(items, key=lambda x: x["dt"])
    if not items:
        raise ValueError("无有效数据（文件为空或全部行损坏）")

    now = items[-1]["dt"]                     # 数据内锚点
    recent = [it for it in items if (now - it["dt"]).days <= days] or items
    notes = []

    base_pool, base_kind = recent, "近期窗口对照"
    if len(recent) < MIN_RECENT_FOR_BASELINE:
        base_pool, base_kind = items, "全量（近期样本不足，已声明回退）"
        notes.append("近期窗口仅 %d 条（<%d），基线回退为全量——对照强度下降，结论方向可采信、数值不当精确"
                     % (len(recent), MIN_RECENT_FOR_BASELINE))
    baseline = group_stats(base_pool)
    base_mean = baseline["interact_mean"]

    latest = items[-1]
    latest_ratio = (interact(latest) / base_mean) if base_mean > 0 else None

    # ---- 发布节奏：用数据内部的相邻间隔，避免与墙钟耦合（可复现）----
    times = sorted(it["dt"] for it in recent)
    deltas = [(times[i] - times[i - 1]).total_seconds() / 86400.0 for i in range(1, len(times))]
    median_gap = statistics.median(deltas) if deltas else None
    last_gap = deltas[-1] if deltas else None
    # 「间隔偏离」只在间隔真以天为单位时才成立：同日多条发布（中位间隔 <12 小时）会让比值失真（实测坑）
    gap_reliable = bool(median_gap is not None and median_gap >= 0.5 and last_gap is not None and last_gap >= 1.0)
    gap_ratio = (last_gap / median_gap) if (gap_reliable and median_gap > 0) else None

    # ---- 内容形态效率（近期）----
    types = {}
    for it in recent:
        types.setdefault(it.get("ContentType") or "unknown", []).append(it)
    type_rows = []
    for t, v in types.items():
        row = group_stats(v)
        row["type"] = t
        row["share"] = len(v) / len(recent)
        type_rows.append(row)
    type_rows.sort(key=lambda r: -r["n"])

    # ---- 题材效率（近期 + 全量占比）----
    topic_rows = []
    for g in zd.TOPIC_PATTERNS:
        sub = [it for it in recent if _topic_of(it) == g]
        row = group_stats(sub)
        row["topic"] = g
        row["share"] = len(sub) / len(recent)
        topic_rows.append(row)
    topic_rows.sort(key=lambda r: -r["n"])
    top_topic = next((r for r in topic_rows if r["n"] >= MIN_GROUP_N), None)
    best_topic = max((r for r in topic_rows if r["n"] >= MIN_GROUP_N),
                     key=lambda r: r["interact_mean"], default=None)

    # ---- 篇幅同期对照 ----
    withsum = [it for it in recent if (it.get("Summary") or "").strip()]
    length = {"n": len(withsum), "median": None, "short": None, "long": None, "diff_pct": None}
    if withsum:
        lens = sorted(len(it.get("Summary") or "") for it in withsum)
        med = lens[len(lens) // 2]
        short = [it for it in withsum if len(it.get("Summary") or "") < med]
        long_ = [it for it in withsum if len(it.get("Summary") or "") >= med]
        length.update({"median": med, "short": group_stats(short), "long": group_stats(long_)})
        if short and long_:
            length["diff_pct"] = _pct(length["long"]["interact_mean"], length["short"]["interact_mean"])

    # ---- CTA 话术同期对照 ----
    a = [it for it in recent if re.search(zd.CTA_PATTERN, it.get("Summary") or "")]
    b = [it for it in recent if not re.search(zd.CTA_PATTERN, it.get("Summary") or "")]
    cta = {"with": group_stats(a), "without": group_stats(b), "diff_pct": None}
    if a and b:
        cta["diff_pct"] = _pct(cta["with"]["interact_mean"], cta["without"]["interact_mean"])

    # ---- 标题风格同期对照 ----
    q = [it for it in recent if TITLE_QUESTION.search(it.get("Title") or "")]
    s = [it for it in recent if not TITLE_QUESTION.search(it.get("Title") or "")]
    title_style = {"question": group_stats(q), "statement": group_stats(s), "diff_pct": None}
    if q and s:
        title_style["diff_pct"] = _pct(title_style["question"]["interact_mean"],
                                       title_style["statement"]["interact_mean"])

    # ---- 互动结构：评论占比（讨论场是否形成）----
    cm = sum(it.get("CommentCount") or 0 for it in recent)
    it_sum = sum(interact(it) for it in recent)
    comment_share = (cm / it_sum) if it_sum > 0 else 0.0

    # ---- 风格稳定性（互动量的变异系数）----
    ints = [interact(it) for it in recent]
    cv = None
    if len(ints) >= 2 and base_mean > 0:
        cv = statistics.pstdev(ints) / base_mean
        stability = round(100 * (1 - min(1.0, cv)))
    else:
        stability = 0 if not ints else 100

    # ---- 星期效率（强势发布日）----
    wd_names = ["一", "二", "三", "四", "五", "六", "日"]
    buckets = {i: [] for i in range(7)}
    for it in recent:
        buckets[it["dt"].weekday()].append(it)
    wd_rows = [{"weekday": i, "name": "周" + wd_names[i], "n": len(v),
                "interact_mean": group_stats(v)["interact_mean"]} for i, v in buckets.items()]
    eligible = [r for r in wd_rows if r["n"] >= MIN_GROUP_N]
    best_wd = max(eligible, key=lambda r: r["interact_mean"]) if (eligible and len(recent) >= 14) else None
    weekday = {
        "rows": wd_rows,
        "best": best_wd["weekday"] if best_wd else None,
        "best_name": best_wd["name"] if best_wd else None,
        "best_n": best_wd["n"] if best_wd else 0,
        "lift": (best_wd["interact_mean"] / base_mean) if (best_wd and base_mean > 0) else None,
    }

    # ---- 历史爆款污染程度（提醒用，不参与基线）----
    old = [it for it in items if (now - it["dt"]).days > days]
    pollution = {
        "old_n": len(old),
        "old_like_max": max((it.get("LikeCount") or 0) for it in old) if old else 0,
    }
    recent_like_mean = baseline["like_mean"]
    pollution["ratio"] = (pollution["old_like_max"] / recent_like_mean) if recent_like_mean > 0 else None

    # ---- 数据新鲜度（墙钟，仅作提示，不参与判定）----
    freshness_days = (datetime.date.today() - now.date()).days

    notes.append("数据锚点（数据内最新一条）：%s · 墙钟距今天数：%d" % (now.date(), freshness_days))
    notes.append("基线口径：%s（%d 条，互动均值 %.1f）" % (base_kind, baseline["n"], base_mean))
    notes.append("平台不提供的量：粉丝数 / 曝光量 / 小时级点击率 / 完播——本层不推断、不填数")

    return {
        "schema": SCHEMA,
        "source": source,
        "user": user,
        "days": days,
        "n_total": len(items),
        "n_recent": len(recent),
        "span_first": items[0]["dt"].date().isoformat(),
        "span_last": now.date().isoformat(),
        "freshness_days": freshness_days,
        "baseline": baseline,
        "baseline_kind": base_kind,
        "latest": {
            "title": (latest.get("Title") or "")[:60],
            "type": latest.get("ContentType"),
            "interact": interact(latest),
            "like": latest.get("LikeCount") or 0,
            "comment": latest.get("CommentCount") or 0,
            "fav": latest.get("FavoriteCount") or 0,
            "ratio_vs_baseline": latest_ratio,
        },
        "gap": {
            "last_gap_days": last_gap,
            "median_gap_days": median_gap,
            "gap_ratio": gap_ratio,
            "gap_reliable": gap_reliable,
            "per_week": (len(recent) / days * 7.0) if days else None,
        },
        "types": type_rows,
        "topics": topic_rows,
        "top_topic": top_topic,
        "best_topic": best_topic,
        "length": length,
        "cta": cta,
        "title_style": title_style,
        "article_share": sum(1 for it in recent if it.get("ContentType") == "article") / len(recent),
        "comment_share": comment_share,
        "stability": stability,
        "stability_cv": cv,
        "weekday": weekday,
        "pollution": pollution,
        "notes": notes,
    }


def extract_from_file(path, days=30, user=""):
    items = load_items(path)
    items, dropped = attach_dt(items)
    if dropped:
        print("[!] 已跳过 CreatedAt 无效/非对象行 %d 行（优雅降级）" % dropped)
    return extract(items, days=days, source=path, user=user)


def main():
    ap = argparse.ArgumentParser(description="看山 · 信号层（JSONL → 数值信号）")
    ap.add_argument("--in", dest="src", required=True, help="contents JSONL 路径")
    ap.add_argument("--days", type=int, default=30, help="近期窗口（天）")
    ap.add_argument("--user", default="", help="用户名（缺省取数据内 AuthorName）")
    ap.add_argument("--out", default=None, help="输出 signals JSON（缺省只打印）")
    a = ap.parse_args()

    try:
        items = attach_dt(load_items(a.src))[0]
    except OSError as e:
        print("[!] 读不了数据文件：%s" % e)
        print("    先用 scripts/zhihu_fetch.py 拉本人数据，或 scripts/demo_synth.py --user <名> 造合成数据")
        return 1
    if not items:
        print("[!] 无有效数据（文件为空或全部行损坏）")
        return 1

    user = (a.user or "").strip() or ((items[0].get("AuthorName") or "").strip() or "未标注")
    sig = extract(items, days=a.days, source=a.src, user=user)
    body = json.dumps(sig, ensure_ascii=False, indent=2)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(body + "\n")
        print("[+] 信号 -> %s" % a.out)
    b = sig["baseline"]
    print("用户=%s 窗口=%d天 近期=%d条 基线互动均值=%.1f 最新/基线=%s 稳定性=%d"
          % (user, sig["days"], sig["n_recent"], b["interact_mean"],
             ("%.2f" % sig["latest"]["ratio_vs_baseline"]) if sig["latest"]["ratio_vs_baseline"] is not None else "n/a",
             sig["stability"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
