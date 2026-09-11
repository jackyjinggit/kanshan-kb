#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 三卡数据层：月卡（战略）/ 周卡（战术）/ 日卡（执行）→ 呈现层 JSON

为什么单独一层：
  产品设计（产品设计_看山.md §5.2）的核心创新 = 月/周/天三档时间轴颗粒度。
  诊断层（zhihu_diagnose）输出给人读的七节报告；本层把同一批信号组装成**卡片结构**，
  供 demo 前端可视化。全部字段可追溯到 signals.py 的既有信号，不造新数。

口径纪律（与 signals 一致）：
  · 数据内锚点：以数据最新一条为「现在」，输出与墙钟无关。
  · 不知道标不知道：无曝光/无小时级官方数据——日卡曲线来自**本地采样差分**
    （scripts/sampler.py），无采样数据时用合成游走并标「合成·」。
  · 目标对齐分 V1 为三因子口径（聚焦/稳定/节奏），权重可证伪——不是平台官方指标。

用法（供 demo/server.py 调用）：
    cards.month_card(sig, goal_text)
    cards.week_card(items, sig)
    cards.day_card(snap_path=..., seed_user=...)
"""
import argparse
import datetime
import json
import os
import random
import statistics
import subprocess

SCHEMA = "kanshan.cards/1"
# 分发节点先验（社区通用节奏，非平台官方承诺；日卡里作为标注线呈现）
DAY_NODES = [{"hour": 10, "label": "早班车推荐"},
             {"hour": 14, "label": "午间二次分发"},
             {"hour": 20, "label": "晚间活跃高峰"}]
CADENCE_BASE_WEEKLY = 4.0   # 目标客群（产品设计 §1：月更 4 篇以上）的节奏基准


def month_card(sig, goal_text=None):
    """月卡：目标对齐分（V1 三因子）+ 稳定性 + 最佳/最差动作 + 下月调整。"""
    best_topic = sig.get("best_topic") or {}
    top_topic = sig.get("top_topic") or {}
    stability = sig.get("stability") or 0
    per_week = (sig.get("gap") or {}).get("per_week") or 0.0
    focus = (best_topic.get("share") or top_topic.get("share") or 0.0)
    focus_score = min(focus / 0.6, 1.0) * 100            # 聚焦度：头部题材占比 60% 记满分
    cadence_score = min(per_week / CADENCE_BASE_WEEKLY, 1.0) * 100
    goal_score = round(0.4 * focus_score + 0.4 * stability + 0.2 * cadence_score)

    # 最佳/最差动作：题材、形态、星期三个维度里挑均值最高/最低（样本足的组）
    candidates = []
    for r in sig.get("topics") or []:
        if r.get("n", 0) >= 3:
            candidates.append(("题材·%s" % r.get("topic", "?"), r["interact_mean"]))
    for r in sig.get("types") or []:
        if r.get("n", 0) >= 3:
            candidates.append(("形态·%s" % r.get("type", "?"), r["interact_mean"]))
    for d in (sig.get("weekday") or {}).get("rows", []):
        if d.get("n", 0) >= 3:
            candidates.append(("星期·%s" % d.get("name", "?"), d["interact_mean"]))
    candidates.sort(key=lambda x: -x[1])
    top_actions = [{"action": name, "interact_mean": round(m, 1)} for name, m in candidates[:3]]
    worst_action = {"action": candidates[-1][0], "interact_mean": round(candidates[-1][1], 1)} if candidates else None

    return {
        "schema": SCHEMA, "card": "month",
        "goal": {
            "text": goal_text or "（未填写目标——对齐分按三因子默认口径，填写目标后语义更准）",
            "score": goal_score,
            "factors": {"topic_focus": round(focus_score), "stability": stability,
                        "cadence": round(cadence_score)},
            "note": "V1 口径：0.4×聚焦 + 0.4×稳定 + 0.2×节奏（聚焦=头部题材占比/60%，节奏=周更/4 篇）"
                    "——三因子权重可证伪，多账号复核后应再校准",
        },
        "stability": stability,
        "top_actions": top_actions,
        "worst_action": worst_action,
        "next_step": "复制胜出框架并 +1 篇/周（RX-07 稳定路径）；砍掉互动后 50 分位以下选题",
    }


def week_card(items, sig):
    """周卡：最近 7 天逐日聚合 + 最好一天 + 最有效形态 + 节奏建议。"""
    if not items:
        return {"schema": SCHEMA, "card": "week", "days7": [], "note": "无数据"}
    now = items[-1]["dt"]
    days7 = []
    for offset in range(6, -1, -1):
        day = (now - datetime.timedelta(days=offset)).date()
        sub = [it for it in items if it["dt"].date() == day]
        days7.append({
            "date": day.isoformat(),
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][day.weekday()],
            "n": len(sub),
            "interact": sum((it.get("LikeCount") or 0) + (it.get("CommentCount") or 0)
                            + (it.get("FavoriteCount") or 0) for it in sub),
        })
    active = [d for d in days7 if d["n"] > 0]
    best_day = max(active, key=lambda d: d["interact"]) if active else None
    type_rows = [r for r in (sig.get("types") or []) if r.get("n", 0) >= 3]
    top_type = max(type_rows, key=lambda r: r["interact_mean"], default=None)
    return {
        "schema": SCHEMA, "card": "week",
        "days7": days7,
        "best_day": {"date": best_day["date"], "weekday": best_day["weekday"],
                     "interact": best_day["interact"]} if best_day else None,
        "top_type": ({"type": top_type["type"], "interact_mean": round(top_type["interact_mean"], 1)}
                     if top_type else None),
        "rhythm": "把下周主发布位放在 %s（本周实证最好的一天）；间隔保持 %s 天中位节奏"
                  % (best_day["weekday"] if best_day else "已验证时段",
                     (sig.get("gap") or {}).get("median_gap_days") or "—"),
        "opportunities_note": "机会分 Top3 需站内搜索 API（撞题/缺口值），离线模式此栏显示缓存或「待官方连接」",
    }


def _snap_series(snap_path, hours=24):
    """从采样快照取最近 hours 小时内增量最大的一篇内容 → [(ts, like)] 序列。"""
    if not snap_path or not os.path.exists(snap_path):
        return None, None
    since = datetime.datetime.now().timestamp() - hours * 3600
    by_url = {}
    with open(snap_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("ts", 0) >= since:
                by_url.setdefault(r.get("url", ""), []).append(r)
    best, best_gain = None, -1
    for url, pts in by_url.items():
        pts.sort(key=lambda x: x["ts"])
        if len(pts) < 2:
            continue
        gain = pts[-1]["like"] - pts[0]["like"]
        if gain > best_gain:
            best, best_gain = pts, gain
    if not best or len(best) < 2:
        return None, None
    t0 = best[0]["ts"]
    series = [{"t": round((p["ts"] - t0) / 3600.0, 2), "like": p["like"],
               "clock": datetime.datetime.fromtimestamp(p["ts"]).strftime("%H:%M")} for p in best]
    return series, best[0].get("title") or best[0].get("url", "")


def _synth_series(seed_user, hours=24, base=40):
    """合成 24h 累计赞曲线：三个分发节点抬升 + 随机游走。仅演示形态，标「合成·」。"""
    rng = random.Random("daycard:%s" % seed_user)
    base_hour = datetime.datetime.now().hour
    points, like = [], 0
    for h in range(0, hours + 1):
        bump = 0
        for node in DAY_NODES:
            if abs(h - node["hour"]) <= 1:
                bump += rng.randint(3, 8)          # 节点效应
        like += bump + rng.choice((0, 0, 0, 1, 2))  # 基线自然增长
        points.append({"t": h, "like": like, "clock": "%02d:00" % ((base_hour + h) % 24)})
    return points, "合成演示内容"


CLI_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "") or os.environ.get("HOME", ""),
                        "ZhihuCLI", "current", "zhihu-cli.exe")


def opportunity_card(topic_query, limit=6):
    """周卡机会分：用官方 search API 查同题供给密度（每次调用花 1 次 zhihu_search 额度，按需触发）。

    口径声明：设计参考的「缺口值 = 浏览数/回答数」需要浏览数——官方 search 不返回浏览数，
    故本卡降级为「同题供给密度」口径：结果少=供给缺口（蓝海）；结果多且高赞集中=竞争激烈。
    判定是启发式，非平台官方指标——失效条件见返回体。
    """
    if not topic_query or not topic_query.strip():
        return {"schema": SCHEMA, "card": "opportunity", "error": "缺少选题关键词"}
    topic_query = topic_query.strip()[:60]
    if not os.path.exists(CLI_PATH):
        return {"schema": SCHEMA, "card": "opportunity", "error": "未找到 zhihu-cli，机会分需官方搜索 API（待连接）"}
    try:
        p = subprocess.run([CLI_PATH, "search", "zhihu", "--query", topic_query,
                            "--count", str(limit)], capture_output=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"schema": SCHEMA, "card": "opportunity", "error": "搜索失败：%s" % str(e)[:80]}
    try:
        d = json.loads(p.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"schema": SCHEMA, "card": "opportunity", "error": "搜索输出异常（检查授权）"}
    if d.get("Code") != 0:
        return {"schema": SCHEMA, "card": "opportunity", "error": "API error: %s" % d.get("Message")}
    items = (d.get("Data") or {}).get("Items") or []
    ups = sorted(((it.get("VoteUpCount") or 0) for it in items), reverse=True) if items else []
    top = ups[0] if ups else 0
    n = len(items)
    if n == 0:
        verdict, advice = "蓝海", "站内几乎无同题——值得写，但先确认需求真实存在（搜索词换 2-3 个变体再核一次）"
    elif n <= 2 and top < 500:
        verdict, advice = "供给缺口", "同题少且无高赞垄断——可写，角度选你的实证经验切入"
    elif top >= 2000:
        verdict, advice = "头部垄断", "已有高赞标杆——除非有显著增量信息，否则换子角度或升级问题粒度"
    else:
        verdict, advice = "可竞争", "有供给无垄断——拼角度差异化与开头钩子（M3 选题矩阵过一遍再动笔）"
    return {
        "schema": SCHEMA, "card": "opportunity",
        "query": topic_query, "found": n, "top_upvote": top,
        "titles": [{"title": (it.get("Title") or "")[:60],
                    "upvote": it.get("VoteUpCount") or 0,
                    "type": it.get("ContentType") or ""} for it in items[:limit]],
        "verdict": verdict, "advice": advice,
        "note": "口径=同题供给密度（官方 search 不返回浏览数，缺口值降级）；每次查询花 1 次 zhihu_search 额度",
        "falsify": "判定阈值（0/2/2000）为启发式初值，用你账号的后续表现复核后应再校准",
    }


def day_card(snap_path=None, seed_user="演示账号"):
    """日卡：24h 曲线（真实采样优先，合成兜底）+ velocity + 节点标注 + 归因 + 下一步。"""
    series, title = _snap_series(snap_path)
    source = "real"
    if not series:
        series, title = _synth_series(seed_user)
        source = "synth"
    deltas = [(series[i]["like"] - series[i - 1]["like"], series[i]) for i in range(1, len(series))]
    v_max = max(deltas, key=lambda x: x[0], default=None)
    velocity = None
    if v_max and v_max[0] > 0:
        velocity = {"delta": v_max[0], "clock": v_max[1].get("clock"),
                    "note": "单位时间最大增量（velocity）出现在 %s 时段" % v_max[1].get("clock")}
    # 归因：只对落在节点窗口内的增量给「节点效应」解释（可信度中）；其余不硬编
    attributions = []
    for d, p in deltas:
        if d <= 0:
            continue
        hour = int(str(p.get("clock", "00:00")).split(":")[0])
        hit = next((n for n in DAY_NODES if abs(hour - n["hour"]) <= 1), None)
        if hit:
            attributions.append({"clock": p.get("clock"), "delta": d,
                                 "cause": "%s窗口内增量（节点效应）" % hit["label"],
                                 "confidence": "中"})
        else:
            attributions.append({"clock": p.get("clock"), "delta": d,
                                 "cause": "外部因素，不硬编原因", "confidence": "标不知道"})
    next_action = ("节点前 30 分钟内互动已启动 → 追加一条补充观点置顶" if velocity else
                   "发布后暂无增量（采样仍在进行）→ 保持观察，勿急于改动")
    return {
        "schema": SCHEMA, "card": "day",
        "source": source,
        "source_label": ("真实采样（scripts/sampler.py 差分）· %s" % title if source == "real"
                         else "合成·演示曲线（脚本游走，非真实账号数据）"),
        "title": title,
        "nodes": DAY_NODES,
        "points": series,
        "velocity": velocity,
        "attributions": attributions,
        "next_action": next_action,
        "falsify": "节点效应为先验假设：若多日数据显示增量时段与节点窗口无关 → 推翻节点标注，改用本账号实证时段",
    }
