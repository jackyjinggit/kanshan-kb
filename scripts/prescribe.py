#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 处方引擎（P0-3）：异常信号 → M 模块 → 具体动作 → 依据

回答的问题：**拿到一组信号，下一步到底干什么？**
（诊断层回答「发生了什么」，本层回答「所以做什么」，每条都带数据锚点与失效条件。）

设计约束：
  1. **不编数字**：所有信号文案里的数字都来自 `signals.py` 的实测值，缺失即写「样本不足」，不估。
  2. **不做反向结论**：全部对比走「同期窗口」，与诊断层同一口径。
  3. **规则族必须出结论**：每个规则族无论数据偏向哪边都给出**一条**处方（含「当前不是瓶颈，别在这里花时间」
     这种负向处方）——避免「没命中就什么都不说」导致用户空手而归。
  4. 阈值集中在 `RULES` 里，改阈值不改逻辑；动作文案由内容组按 M 模块方法 md 迭代。

用法：
    python scripts/prescribe.py --in data/contents.jsonl [--days 30] [--user 名] [--out out/] [--json out.json]
    python scripts/prescribe.py --in signals.json          # 也吃 signals.py 的输出
"""
import argparse
import datetime
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import signals as sg  # noqa: E402

SEVERITY_ORDER = {"高": 0, "中": 1, "低": 2}

MODULE_NAMES = {
    "M1": "定位与赛道选择", "M2": "人设与账号包装", "M3": "选题方法论",
    "M4": "内容生产与爆款公式", "M5": "平台算法与分发机制", "M6": "发布与冷启动运营",
    "M7": "粉丝增长与互动运营", "M8": "数据复盘与迭代", "M9": "变现路径", "M10": "合规与风险",
}


def basis_of(module):
    """依据指针：指向仓库内 M 模块 README（方法 md 由内容组填充后，此处换成具体方法文件）"""
    for name in os.listdir(os.path.dirname(HERE)):
        if name.startswith(module + "_") and os.path.isdir(os.path.join(os.path.dirname(HERE), name)):
            return "%s/README.md" % name
    return "%s/README.md" % module


def _rx(rid, module, severity, signal, actions, falsify, basis_note=""):
    return {
        "id": rid,
        "module": module,
        "module_name": MODULE_NAMES.get(module, module),
        "severity": severity,
        "signal": signal,
        "actions": actions,
        "basis": basis_of(module),
        "basis_note": basis_note or ("方法论层：%s（骨架在库，方法 md 由内容组按工单填充后升级依据精度）"
                                     % MODULE_NAMES.get(module, module)),
        "falsify": falsify,
    }


def _pct(x):
    return "n/a" if x is None else "%d%%" % round(abs(x) * 100)


# ---------------------------------------------------------------- 规则族
def rx01_dispatch(s):
    """M5 分发通道：最新一篇相对自身基线"""
    r = s["latest"]["ratio_vs_baseline"]
    if r is None:
        return _rx("RX-01", "M5", "中",
                   "基线互动均值为 0（近期 %d 条全零互动），无法判定分发状态" % s["baseline"]["n"],
                   ["先确认数据完整性：是否抓到了真实互动字段（赞/评/藏）",
                    "若确为零互动，按「冷启动」处理：先发 3 篇同题材内容建立样本，再谈优化"],
                   "若补齐互动字段后出现非零值 → 本条作废，按新基线重跑")
    if r >= 1.5:
        return _rx("RX-01", "M5", "高",
                   "最新一篇互动 %d，为基线（%.1f）的 %.2f 倍——超基线 1.5 倍以上通常意味着推荐流放量（关注流只给基数量级）"
                   % (s["latest"]["interact"], s["baseline"]["interact_mean"], r),
                   ["48 小时内复制本篇结构发姊妹篇（推荐流已验证该选题带宽）",
                    "把本篇评论区高赞观点置顶，接住推荐流二次回访",
                    "将本篇选题关键词加入选题库，标记「推荐流验证款」"],
                   "若姊妹篇互动回落到基线以下 → 说明命中来自选题而非结构，改用选题复制而非结构复制")
    if r <= 0.6:
        return _rx("RX-01", "M5", "高",
                   "最新一篇互动 %d，仅为基线（%.1f）的 %.2f 倍——低于自身常态。曝光不足 or 点击率低公开接口不可得，**不硬编原因**"
                   % (s["latest"]["interact"], s["baseline"]["interact_mean"], r),
                   ["24 小时内改标题为疑问式并补数据出处（可干预变量优先，先动标题不动正文）",
                    "对照选题矩阵：本篇选题是否在你历史高互动选题带宽内",
                    "若 48 小时后仍低于基线 50%，止损转复盘，不追加投入"],
                   "若改标题后仍无变化 → 变量非标题，回炉测发布时段与题材")
    return _rx("RX-01", "M5", "低",
               "最新一篇互动 %d，为基线的 %.2f 倍——处于常态区间，无异常信号" % (s["latest"]["interact"], r),
               ["保持当前结构，不因单篇波动改打法",
                "做一次单变量小测（只动标题或只动篇幅），为下一轮迭代取证据"],
               "若连续 3 篇均落在常态区间 → 说明需要换变量（选题/形态），而非微调")


def rx02_weekday(s):
    """M6 强势发布日"""
    w = s["weekday"]
    if not w["best"]:
        return _rx("RX-02", "M6", "低",
                   "星期维度无足够样本（近期 %d 条，单日最少需 3 条）——不排除有强势日，只是**现在测不出来**"
                   % s["n_recent"],
                   ["先累积到每星期至少 3 条再判定，避免在噪声上过拟合",
                    "期间固定一个发布日（如周三），保持其他变量不变以便后续归因"],
                   "样本补齐后若某日提升 ≥1.5 倍 → 升为「高」优先级处理")
    lift = w["lift"] or 0
    if lift >= 1.5:
        return _rx("RX-02", "M6", "高",
                   "%s 均值是整体基线的 %.2f 倍（该日 %d 篇真实样本）" % (w["best_name"], lift, w["best_n"]),
                   ["把%s固定为主推发布日" % w["best_name"],
                    "发布时间叠加晚间高峰 20:00-22:00",
                    "连续验证 3 周后写入账号发布 SOP；若第 4 周失效，视为噪声剔除"],
                   "若主推日连续 3 周低于基线 → 上一轮结论属小样本噪声，回炉重测")
    if lift >= 1.15:
        return _rx("RX-02", "M6", "中",
                   "%s 略高于基线（%.2f 倍，%d 篇），是**弱信号**而非结论" % (w["best_name"], lift, w["best_n"]),
                   ["本周仍按%s发布，但暂不写进 SOP" % w["best_name"],
                    "再收集 3-4 周同类样本，提升到 ≥1.5 倍再固化"],
                   "若后续样本把它压回 1.1 倍以下 → 判定无星期效应")
    return _rx("RX-02", "M6", "低",
               "各星期均值差异不显著（最佳 %s 仅 %.2f 倍基线）——发布日不是当前瓶颈" % (w["best_name"], lift),
               ["不要在星期维度继续调参（边际收益低）",
                "把优化火力转向「题材 × 形态」组合（见 RX-05 / RX-09）"],
               "若某周出现 ≥1.5 倍异常且可复现 → 重新纳入本规则")


def rx03_cadence(s):
    """M6 发布节奏"""
    g = s["gap"]
    per_week = g["per_week"]
    if not g.get("gap_reliable"):
        return _rx("RX-03", "M6", "低",
                   "发布间隔无法以天为单位判定（近期 %d 条中多条同日发布；中位间隔 %.2f 天）——**样本内部密度差异过大，间隔比值失真，本层不出结论**"
                   % (s["n_recent"], g["median_gap_days"] if g["median_gap_days"] is not None else -1),
                   ["改按「周产量」记账（当前约 %.1f 篇/周），周维度比篇间隔更稳定" % per_week,
                    "连续 4 周记录周产量与周均互动，用周粒度判定节奏是否失控",
                    "同日多篇不必强行合并——只看周总量与互动是否同步"],
                   "若数据里出现 ≥1 天的真实断档，本规则自动升级为间隔判定")
    if g["gap_ratio"] is not None and g["gap_ratio"] >= 1.6:
        return _rx("RX-03", "M6", "高",
                   "最近一篇距今间隔 %.1f 天，是自身中位间隔（%.1f 天）的 %.2f 倍——节奏正在偏离读者的关注衰减窗口"
                   % (g["last_gap_days"], g["median_gap_days"], g["gap_ratio"]),
                   ["72 小时内补发 1 篇（优先回答形态：生产成本低于文章）",
                    "用历史最佳篇的结构做模板，降低重启成本",
                    "先保频率后保质量：恢复节奏后再谈选题升级"],
                   "若补发后 7 天均值未回到基线 → 说明掉的是权重而非节奏，转评估账号分发状态")
    if g["gap_ratio"] is not None and g["gap_ratio"] <= 0.5:
        idx = (s["baseline"]["interact_mean"] / s["latest"]["interact"]) if s["latest"]["interact"] > 0 else None
        return _rx("RX-03", "M6", "中",
                   "最近发布很密：末次间隔 %.1f 天 vs 中位 %.1f 天（%.2f 倍），近期约 %.1f 篇/周%s"
                   % (g["last_gap_days"], g["median_gap_days"], g["gap_ratio"], per_week,
                      "；但基线互动均值仅 %.1f，需警惕摊薄" % s["baseline"]["interact_mean"] if idx else ""),
                   ["抽最近 2 周做质量对照：密集期的互动均值是否低于此前同长度周期",
                    "若低 → 频率减半、每篇多花一轮打磨（宁少勿平）",
                    "若平 → 保持频率，问题在选题而非产能"],
                   "若减半后均值无提升 → 摊薄假设不成立，频率不是主因")
    return _rx("RX-03", "M6", "低",
               "发布节奏稳定（末次间隔 %.1f 天，中位 %.1f 天，约 %.1f 篇/周）"
               % (g["last_gap_days"] if g["last_gap_days"] is not None else -1,
                  g["median_gap_days"] if g["median_gap_days"] is not None else -1, per_week),
               ["把当前频率写进 SOP（含固定发布时段）",
                "节奏稳定的前提下，把腾出的注意力投入单篇质量（钩子与前 3 段）"],
               "若连续 2 周断更 → 回到「高」优先级")


def rx04_title(s):
    """M3 标题风格"""
    d = s["title_style"]["diff_pct"]
    q, st = s["title_style"]["question"], s["title_style"]["statement"]
    if d is None:
        return _rx("RX-04", "M3", "低", "标题风格两组样本不足（疑问式 %d / 陈述式 %d），无法对照" % (q["n"], st["n"]),
                   ["两类标题各再发 3 篇，凑齐可比样本"],
                   "样本齐后若差异 ≥20% → 按胜出风格统一")
    if d >= 0.2:
        return _rx("RX-04", "M3", "中",
                   "疑问式标题均值高出陈述式 %s（%.1f vs %.1f，样本 %d/%d）"
                   % (_pct(d), q["interact_mean"], st["interact_mean"], q["n"], st["n"]),
                   ["新篇标题统一疑问式（为什么/怎么办/值不值）",
                    "同选题做双标题小范围 A/B：一篇回答一篇文章",
                    "胜出风格写入内容 SOP，异常时再验证"],
                   "若统一后 2 周均值未升 → 标题非因果，回炉测选题带宽")
    if d <= -0.2:
        return _rx("RX-04", "M3", "中",
                   "陈述式标题均值高出疑问式 %s（%.1f vs %.1f）——你的读者吃「结论前置」"
                   % (_pct(d), st["interact_mean"], q["interact_mean"]),
                   ["新篇标题统一陈述式：把结论/数字放进标题前半句",
                    "避免把标题写成悬念句（与你的读者预期不符）",
                    "保留 20% 疑问式做对照组，防结论过期"],
                   "若读者画像变化或平台规则调整 → 重新对照")
    return _rx("RX-04", "M4", "低",
               "标题风格差异不显著（%.1f vs %.1f，差异 %s < 20%%）——标题不是当前瓶颈"
               % (q["interact_mean"], st["interact_mean"], _pct(d)),
               ["停止在标题句式上反复调参",
                "把优化点前移到正文前 3 句（钩子）与选题本身"],
               "若出现单篇异常波动，再复查标题贡献")


def rx05_form(s):
    """M5 内容形态效率"""
    rows = [r for r in s["types"] if r["n"] >= sg.MIN_GROUP_N]
    if len(rows) < 2:
        return _rx("RX-05", "M5", "低",
                   "可比形态不足（近期满足样本门槛的形态 %d 种）——形态效率暂无法对照" % len(rows),
                   ["补足第二形态样本（每形态 ≥3 篇）后再判定",
                    "期间按最省成本形态（回答）稳定产出"],
                   "样本补齐后若差异 ≥25% → 按胜出形态切换主战场")
    rows.sort(key=lambda r: -r["interact_mean"])
    top, second = rows[0], rows[1]
    d = (top["interact_mean"] - second["interact_mean"]) / second["interact_mean"] if second["interact_mean"] > 0 else None
    if d is None and top["interact_mean"] > 0:
        return _rx("RX-05", "M5", "高",
                   "[%s] 互动均值 %.1f，对照组 [%s] 均值为 0.0（%d 篇）——对照组零互动，无法算相对差，按绝对差处理"
                   % (top["type"], top["interact_mean"], second["type"], second["n"]),
                   ["主战场切到 [%s]：每周 ≥3 篇" % top["type"],
                    "把零互动的 [%s] 当作「读者不接受的形态」记录进 SOP（不删，留作对照）" % second["type"],
                    "90 天后复检：若对照组仍为 0，形态差异即成立"],
                   "若对照组换选题后起量 → 差异来自选题而非形态")
    if d is not None and d >= 0.25:
        return _rx("RX-05", "M5", "高",
                   "[%s] 互动均值 %.1f，高出 [%s] %.1f 的 %s（样本 %d / %d）"
                   % (top["type"], top["interact_mean"], second["type"], second["interact_mean"],
                      _pct(d), top["n"], second["n"]),
                   ["主战场切到 [%s]：每周 ≥3 篇" % top["type"],
                    "[%s] 降级为引流位（附领域钩子指向主形态）" % second["type"],
                    "90 天后复检形态差是否收敛，收敛则说明是平台波动"],
                   "若切换后新形态均值回落到旧形态水平 → 差异来自内容质量而非形态")
    if d is None:
        return _rx("RX-05", "M5", "低",
                   "两组形态互动均值均为 0（[%s] / [%s]）——形态维度暂时测不出差异，需先解决零互动问题"
                   % (top["type"], second["type"]),
                   ["先按 RX-01 / RX-12 解决单篇零互动，再回到形态对照"],
                   "若某形态先起量，本规则自动转「形态差异」分支")
    return _rx("RX-05", "M5", "中",
               "形态效率差异不足 25%%（[%s] %.1f vs [%s] %.1f）——形态不是当前瓶颈"
               % (top["type"], top["interact_mean"], second["type"], second["interact_mean"]),
               ["维持双形态：回答吃推荐/搜索双入口，文章吃长尾沉淀",
                "把火力移到选题（RX-09）与开头钩子（RX-04 无结论时的替代项）"],
               "若某形态连续 5 篇低于另一形态 30% → 重新纳入切换决策")


def rx06_comment(s):
    """M7 讨论场域"""
    cs = s["comment_share"]
    if cs < 0.06:
        return _rx("RX-06", "M7", "高",
                   "评论仅占互动总量 %.1f%%（低于 6%% 健康线）——读者「赞了就走」，没有形成讨论场" % (cs * 100),
                   ["每篇结尾加一个**可争议的具体问题**（不是「你怎么看」）",
                    "发布后 1 小时内自己置顶一条补充观点，给评论区定调",
                    "回复前 5 条评论（早期互动率会被算法二次放大）"],
                   "若评论占比升到 8% 而互动总量不升 → 说明该账号的互动主要在赞，改测收藏动机")
    if cs >= 0.12:
        return _rx("RX-06", "M7", "低",
                   "评论占互动总量 %.1f%%（高于 12%%）——讨论场健康，属稀缺状态" % (cs * 100),
                   ["把高赞评论发展成下一篇选题（读者已经把需求写在评论区）",
                    "挑 3-5 位高频评论者做「共创选题池」，形成 UGC 共创"],
                   "若评论量突然下滑而赞量不变 → 检查是否关了评论区或内容变敏感")
    return _rx("RX-06", "M7", "中",
               "评论占互动总量 %.1f%%——介于 6%%-12%% 之间，有讨论但未成场" % (cs * 100),
               ["目标把评论占比推到 8%：结尾问题 + 置顶补充两件套先做 5 篇看效果",
                "记录每篇「首评出现时间」，验证早期互动放大假设"],
               "若 5 篇后无变化 → 读者结构与内容调性不匹配，转 M2 人设层排查")


def rx07_stability(s):
    """M2 风格稳定性"""
    v = s["stability"]
    cv = s.get("stability_cv")
    cv_txt = "（变异系数 CV=%.2f，>1 说明波动幅度超过均值本身）" % cv if cv is not None else ""
    if s["n_recent"] < 10:
        return _rx("RX-07", "M2", "低",
                   "近期样本仅 %d 条，稳定性指数 %d/100 不具统计意义（样本不足）" % (s["n_recent"], v),
                   ["累积到 ≥10 篇再判定风格稳定性",
                    "期间固定同一内容框架产出，避免人为制造波动"],
                   "样本补齐后指数 <40 → 升级为「高」优先级处理")
    if v < 40:
        return _rx("RX-07", "M2", "高",
                   "风格稳定性指数 %d/100%s——互动在你自己的内容间大起大落，账号尚未形成稳定内容带宽，读者预期漂移" % (v, cv_txt),
                   ["砍掉互动后 50%% 分位以下的选题类型（用真实分布，不凭感觉）",
                    "固定 1 个内容框架连续产出 6 篇再评估",
                    "人设签名 / 置顶内容与高互动选题对齐"],
                   "若固定框架 6 篇后指数升到 60+ 而均值未升 → 稳定性本身不是增长变量，只是可预期性")
    if v >= 70:
        return _rx("RX-07", "M2", "低",
                   "风格稳定性指数 %d/100——内容带宽稳定，读者预期一致" % v,
                   ["进入放大阶段：复制胜出框架并适度提高频率（每次 +1 篇/周，观察 2 周）",
                    "把「稳定框架」写成可交接的模板，便于系列化产出"],
                   "若提频后指数跌破 50 → 回到原频率，说明产能上限已到")
    return _rx("RX-07", "M2", "中",
               "风格稳定性指数 %d/100（中性区间）——框架初步成型但仍有波动" % v,
               ["挑出波动最大的 3 篇，找出与稳定篇的结构差异（开头/篇幅/题材）",
                "把这 3 个差异点写进发布前自检清单"],
               "若差异点无法归纳 → 波动来自外部流量分配，非内容可控变量")


def rx08_longtail(s):
    """M5 搜索长尾资产"""
    a = s["article_share"]
    if a < 0.2:
        return _rx("RX-08", "M5", "中",
                   "近期文章占比 %.0f%%（低于 20%%）——缺独立 URL 的长尾资产，内容只吃推荐流的短期流量" % (a * 100),
                   ["文章标题植入 1 个具体搜索词（如「宋代 外卖 考据」这类可被检索的组合）",
                    "把高赞回答升级为文章，标题重写为搜索句式",
                    "每周 1 篇「常青题」文章，只服务搜索流、不看短期互动"],
                   "若 8 周后搜索来源内容仍未起量 → 该题材搜索需求本身不足，换题材验证")
    if a >= 0.5:
        return _rx("RX-08", "M5", "中",
                   "近期文章占比 %.0f%%——长尾资产充足，但需确认回答形态（推荐流入口）是否被放弃" % (a * 100),
                   ["补 2-3 篇高关注问题的回答，测推荐流入口是否仍有效",
                    "文章末尾挂相关回答链接，形成站内互链"],
                   "若回答形态互动明显高于文章 → 说明推荐流入口权重更高，回补回答产能")
    return _rx("RX-08", "M5", "低",
               "文章占比 %.0f%%——形态结构均衡（推荐流短期 + 搜索长尾兼顾）" % (a * 100),
               ["保持当前配比，按季度复检搜索词排名",
                "把表现最好的文章做成系列，吃同一批搜索词"],
               "若搜索流量占比连续下滑 → 复核标题关键词是否被平台重写")


def rx09_topic_focus(s):
    """M3 题材聚焦度"""
    t = s["top_topic"]
    if not t:
        return _rx("RX-09", "M3", "中",
                   "无单一题材达到最小样本（%d 篇）——题材维度无法给出效率结论" % sg.MIN_GROUP_N,
                   ["接下来 5 篇固定同一题材，建立可对照的题材样本",
                    "用同一题材写 3 种不同角度，测的是角度而非题材"],
                   "样本齐后若某题材均值明显领先 → 产能向该题材倾斜")
    share = t["share"]
    if share < 0.35:
        return _rx("RX-09", "M3", "高",
                   "最大题材 [%s] 仅占近期产能 %.0f%%（%d 篇）——产能分散，账号标签难以成形"
                   % (t["topic"], share * 100, t["n"]),
                   ["收敛到 2 个题材，合计占 80% 产能（其余转为试探位）",
                    "建选题矩阵：题材 × 角度 × 形态，避免同题重复消耗",
                    "连续 12 篇垂直后观察平台标签是否变化（对应 M6 打标签机制）"],
                   "若收敛 12 篇后互动未升 → 分散不是主因，回炉测单篇质量")
    if share >= 0.6:
        return _rx("RX-09", "M3", "中",
                   "最大题材 [%s] 占近期产能 %.0f%%——聚焦度高，同时存在题材枯竭风险" % (t["topic"], share * 100),
                   ["建「相邻题材延伸带」：与主题材共享读者的 2-3 个邻域题材，做低比例试探",
                    "把主题材拆成子话题清单，延长可持续产出周期"],
                   "若邻域试探互动明显低于主题材 → 读者只认主题材，维持高聚焦并控节奏")
    return _rx("RX-09", "M3", "低",
               "最大题材 [%s] 占 %.0f%%——聚焦度合理（35%%-60%% 区间）" % (t["topic"], share * 100),
               ["保持当前题材配比，按季度复检",
                "主题材内继续做角度细分，避免同质化"],
               "若主题材均值下滑 30% 以上 → 题材进入衰减期，启动邻域迁移")


def rx10_length(s):
    """M4 篇幅"""
    L = s["length"]
    if not L["median"] or not L["short"] or not L["long"]:
        return _rx("RX-10", "M4", "低", "可对照的篇幅样本不足（有摘要的近期内容 %d 条）" % L["n"],
                   ["补齐摘要字段或按正文长度重新采集后再判定"],
                   "字段补齐后若长/短差异 ≥25% → 按胜出篇幅写 SOP")
    d = L["diff_pct"]
    if d is not None and d >= 0.25:
        return _rx("RX-10", "M4", "中",
                   "长于中位（≥%d 字）的均值高出短于中位组 %s（%.1f vs %.1f）"
                   % (L["median"], _pct(d), L["long"]["interact_mean"], L["short"]["interact_mean"]),
                   ["新篇写到中位以上（≥%d 字），但控制在 1.5 倍中位内（防拖沓）" % L["median"],
                    "把「信息密度」当门槛：加长必须加增量信息，不是加水"],
                   "若加长后完读/互动未升 → 长度非因果，读者吃的是信息量")
    if d is not None and d <= -0.25:
        return _rx("RX-10", "M4", "中",
                   "短于中位（<%d 字）的均值高出长文组 %s（%.1f vs %.1f）"
                   % (L["median"], _pct(d), L["short"]["interact_mean"], L["long"]["interact_mean"]),
                   ["新篇压到中位以下（<%d 字），结论前置、砍掉铺垫" % L["median"],
                    "长内容拆成系列，用「上/下篇」承接深度读者"],
                   "若压短后均值未升 → 说明长文读者被筛掉了，属结构差异而非长度")
    return _rx("RX-10", "M4", "低",
               "长/短两组差异不显著（%.1f vs %.1f，%s）-——篇幅不是当前瓶颈"
               % (L["long"]["interact_mean"], L["short"]["interact_mean"], _pct(d)),
               ["按选题需要自由决定篇幅，不设固定字数指标",
                "把注意力放到开头 3 句与选题本身"],
               "若某篇幅区间连续 5 篇明显偏离 → 重新对照")


def rx11_cta(s):
    """M6 引导话术（CTA）"""
    d = s["cta"]["diff_pct"]
    w, wo = s["cta"]["with"], s["cta"]["without"]
    if d is None:
        return _rx("RX-11", "M6", "低",
                   "CTA 两组样本不足（含 %d 篇 / 不含 %d 篇），无法对照引导效果" % (w["n"], wo["n"]),
                   ["后续 6 篇里固定 3 篇带引导、3 篇不带，凑齐对照样本"],
                   "样本齐后若差异 ≥30% → 按结论决定保留或弱化")
    if d <= -0.3:
        return _rx("RX-11", "M6", "高",
                   "含引导话术组均值比不含组低 %s（%.1f vs %.1f，%d vs %d 篇）——引导可能产生反作用"
                   % (_pct(d), w["interact_mean"], wo["interact_mean"], w["n"], wo["n"]),
                   ["下 5 篇停用显性引导话术（关注/看专栏），改由内容本身收尾",
                    "若必须引导，放到文末最后一行且只保留一句",
                    "两周后复测：含/不含两组差异是否收敛"],
                   "若停用后均值未升 → 引导不是原因，差异来自选题分布（做分层对照）")
    if d >= 0.3:
        return _rx("RX-11", "M6", "中",
                   "含引导话术组均值高出 %s（%.1f vs %.1f）——引导在你这儿是正收益" % (_pct(d), w["interact_mean"], wo["interact_mean"]),
                   ["把有效引导话术固定为 1-2 句模板，前移到结尾前一段",
                    "话术里给出「看什么」的具体承诺，而非泛泛求关注"],
                   "若话术长期复用的边际效果递减 → 每季度换一次表达，不做频率加码")
    return _rx("RX-11", "M6", "低",
               "引导话术无显著作用（%.1f vs %.1f，差异 %s）" % (w["interact_mean"], wo["interact_mean"], _pct(d)),
               ["保留现有引导（无害），但不要在语气上加重",
                "把有限精力放到评论场域（RX-06）这种更高杠杆的位置"],
               "若平台规则调整引导尺度 → 立即复查合规性")


def rx12_review(s):
    """M8 复盘闭环与数据纪律"""
    z = s["baseline"]["zero_like_rate"]
    if z >= 0.5:
        return _rx("RX-12", "M8", "高",
                   "近期零赞率 %.0f%%——一半以上内容无人点赞，效率问题已不是单篇问题" % (z * 100),
                   ["建周复盘表（只记 3 列：篇名 / 互动 / 选题类型），先让问题可见",
                    "本周期**只看近期窗口**效率，禁止用全量均值自我安慰（历史爆款会拉高假象）",
                    "从零赞内容里归纳共性（题材/标题/发布日），下一轮针对性避开"],
                   "若归纳不出共性 → 零赞由分发波动导致，转评估账号权重而非内容")
    return _rx("RX-12", "M8", "中",
               "近期零赞率 %.0f%%、有评论率 %.0f%%——建立固定复盘节奏可进一步提升命中率"
               % (z * 100, s["baseline"]["has_comment_rate"] * 100),
               ["每周固定拆解 2 篇（1 篇最佳 / 1 篇最差），各写 3 条原因假设",
                "对每条假设设计下一次单变量验证（只改一个变量）",
                "月度把有效假设沉淀进内容 SOP，无效假设显式作废（避免清单越来越长）"],
               "若复盘 4 周后结论无法复现 → 说明样本周期过短，延长到 8 周再判")


def rx13_allocation(s):
    """M1/M9 产能与效率对齐"""
    top, best = s["top_topic"], s["best_topic"]
    if not top or not best:
        return _rx("RX-13", "M1", "中", "题材样本不足，产能错配无法判定（需每题材 ≥%d 篇）" % sg.MIN_GROUP_N,
                   ["先按当前赛道假设连续产出 5 篇，建立可对照样本"],
                   "样本齐后若效率最高题材与产能最大题材不一致 → 按 RX-09 迁移产能")
    if top["topic"] != best["topic"] and best["interact_mean"] >= top["interact_mean"] * 1.3:
        return _rx("RX-13", "M1", "高",
                   "产能最大的题材 [%s]（%.0f%%）不是效率最高的题材 [%s]（均值 %.1f vs %.1f）——产能与效率错配"
                   % (top["topic"], top["share"] * 100, best["topic"], best["interact_mean"], top["interact_mean"]),
                   ["把不超过三成的产能迁到 [%s]，连续实验 4 周（保留原题材主线，避免账号标签断裂）" % best["topic"],
                    "实验期只改题材一个变量，其余（篇幅/形态/发布日）保持不变",
                    "4 周后按实测决定是否把主线整体迁移"],
                   "若迁移后 [%s] 均值回落到原水平 → 差异来自单篇爆款而非题材，撤回迁移" % best["topic"])
    if top["topic"] != best["topic"]:
        return _rx("RX-13", "M1", "低",
                   "产能最大题材 [%s] 与效率最高题材 [%s] **不同**，但效率差不足 30%%（%.1f vs %.1f）——差异不足以支撑产能迁移"
                   % (top["topic"], best["topic"], best["interact_mean"], top["interact_mean"]),
                   ["维持现有产能分配（迁移成本 > 预期收益）",
                    "每季度复检一次：若效率差扩到 30% 以上再迁"],
                   "若 [%s] 的样本量补到 10 篇以上仍领先 30%% → 迁移条件成立" % best["topic"])
    return _rx("RX-13", "M1", "低",
               "产能最大题材 [%s] 与效率最高题材 [%s] 一致——产能压在了对的地方" % (top["topic"], best["topic"]),
               ["继续加注该题材，同时按 RX-09 做邻域试探防枯竭",
                "把该题材的成功结构固化为模板（可交接、可复用）"],
               "若该题材均值连续 3 个月下滑 → 题材进入衰减，启动迁移预案")


def rx14_pollution(s):
    """M8 口径纪律：历史爆款污染"""
    p = s["pollution"]
    if p["ratio"] is not None and p["ratio"] >= 3:
        return _rx("RX-14", "M8", "中",
                   "历史（窗口外 %d 篇）最高赞 %d，是近期均值 %.1f 的 %.0f 倍——全量均值会被它拉高，属于典型爆款污染"
                   % (p["old_n"], p["old_like_max"], s["baseline"]["like_mean"], p["ratio"]),
                   ["所有效率结论只用「同期窗口」口径，禁用全量均值比高低",
                    "拆解那篇老爆款的可复用要素（钩子/结构/选题），看是否可复制",
                    "把「污染源」单独标注，复盘时不与近期内容混算"],
                   "若老爆款为外部事件驱动（热点/大V转发）→ 复制性低，只作口径警示不作方法依据")
    return _rx("RX-14", "M8", "低",
               "历史爆款污染不显著（窗口外最高赞 %d vs 近期均值 %.1f）——口径干净"
               % (p["old_like_max"], s["baseline"]["like_mean"]),
               ["保持同期对照口径，按季度复检是否出现新的污染源"],
               "若新的高赞爆款出现 → 立即把窗口基线与之分离")


def rx15_compliance(s):
    """M10 合规自查（代理信号）"""
    cta_n = s["cta"]["with"]["n"]
    total = s["n_recent"] or 1
    guide_share = cta_n / total
    if guide_share >= 0.5:
        return _rx("RX-15", "M10", "中",
                   "近期 %.0f%% 的内容带显性引导话术（%d/%d）——平台对「连续发布含大量导流信息」有扣分红线，需自查"
                   % (guide_share * 100, cta_n, total),
                   ["用 `scripts/content_analyze.py` 逐篇过 M10 合规规则（导流/联系方式/绝对化用语）",
                    "引导话术降到 30%% 以下的内容占比，保留在真正需要的篇目",
                    "发布前 30 秒自检：是否有外链导流、联系方式、承诺性表述"],
                   "本信号基于摘要中的引导词命中，属**代理信号**；若抽样人工复核未发现导流 → 降级为提示")
    return _rx("RX-15", "M10", "低",
               "未发现导流话术密集（含引导话术 %d/%d 篇），无平台红线预警信号" % (cta_n, total),
               ["发布前保留 30 秒自检习惯（红线：连续 3 天发 <100 字或大量导流会触发创作行为分扣减）",
                "涉及医疗/金融/法律结论时标注信息来源与适用边界"],
               "本层只做关键词级自查，不构成平台判定；平台规则变动须重新核实，不沿用旧笔记")


RULES = [("RX-01", rx01_dispatch), ("RX-02", rx02_weekday), ("RX-03", rx03_cadence),
         ("RX-04", rx04_title), ("RX-05", rx05_form), ("RX-06", rx06_comment),
         ("RX-07", rx07_stability), ("RX-08", rx08_longtail), ("RX-09", rx09_topic_focus),
         ("RX-10", rx10_length), ("RX-11", rx11_cta), ("RX-12", rx12_review),
         ("RX-13", rx13_allocation), ("RX-14", rx14_pollution), ("RX-15", rx15_compliance)]

# 规则族标题（呈现层用：卡片标题/总览表；改规则语义时同步改这里）
RULE_TITLES = {
    "RX-01": "分发表现：最新一篇 vs 自身基线",
    "RX-02": "强势发布日：一周里的产能节奏",
    "RX-03": "发布节奏：间隔与稳定性",
    "RX-04": "标题风格：提问式还是陈述式",
    "RX-05": "内容形态效率：回答 / 文章 / 想法",
    "RX-06": "讨论场域：评论区有没有被经营",
    "RX-07": "数据稳定性：单篇波动 vs 结构性问题",
    "RX-08": "长尾资产：收藏沉淀与搜索价值",
    "RX-09": "题材聚焦度：账号标签是否成形",
    "RX-10": "篇幅：写长还是写短",
    "RX-11": "引导话术（CTA）：有没有反作用",
    "RX-12": "复盘闭环：数据纪律与记录习惯",
    "RX-13": "产能分配：力气花在效率最高的地方了吗",
    "RX-14": "口径纪律：历史爆款有没有污染判断",
    "RX-15": "合规自查：公开规范下的风险信号",
}


def prescribe(sig):
    """signals dict → 处方列表（每条含 信号/模块/动作/依据/失效条件）"""
    out = []
    for rid, fn in RULES:
        try:
            item = fn(sig)
        except Exception as exc:                      # 单条规则出错不拖垮整份处方单（但必须显式暴露）
            item = _rx(rid, "M8", "中",
                       "规则执行异常，本条已跳过：%s" % str(exc)[:120],
                       ["请附脱敏数据样本反馈，修复后重跑（其余 %d 条处方不受影响）" % (len(RULES) - 1)],
                       "本异常本身即缺陷信号；修复后本条恢复判定")
        item["id"] = rid
        item["title"] = RULE_TITLES.get(rid, rid)
        item["rule"] = fn.__name__
        out.append(item)
    out.sort(key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), r["id"]))
    return out


def summarize(sig, rxs):
    hi = [r for r in rxs if r["severity"] == "高"]
    return {
        "user": sig.get("user") or "未标注",
        "n_total": sig["n_total"],
        "n_recent": sig["n_recent"],
        "days": sig["days"],
        "baseline_interact_mean": sig["baseline"]["interact_mean"],
        "latest_ratio": sig["latest"]["ratio_vs_baseline"],
        "total": len(rxs),
        "high": len(hi),
        "medium": len([r for r in rxs if r["severity"] == "中"]),
        "low": len([r for r in rxs if r["severity"] == "低"]),
        "top_actions": [r["actions"][0] for r in hi[:3]],
    }


def render_md(sig, rxs):
    s = summarize(sig, rxs)
    L = ["# 看山处方单（用户：%s · 生成 %s）" % (s["user"], datetime.date.today()),
         "数据锚点: %s（数据内最新一条）· 近期窗口 %d 天 · 样本 %d 条（全量 %d 条）"
         % (sig["span_last"], sig["days"], sig["n_recent"], sig["n_total"]),
         "基线互动均值: %.1f · 最新一篇/基线: %s"
         % (s["baseline_interact_mean"],
            ("%.2f 倍" % s["latest_ratio"]) if s["latest_ratio"] is not None else "无法判定"),
         "",
         "## 处方总览（%d 条：高 %d / 中 %d / 低 %d）" % (s["total"], s["high"], s["medium"], s["low"]),
         "| 编号 | 诊断项 | 模块 | 优先 | 异常信号（摘） | 动作数 |",
         "|---|---|---|---|---|---|"]
    for r in rxs:
        sig_txt = r["signal"].replace("|", "／")
        if len(sig_txt) > 46:
            sig_txt = sig_txt[:46] + "…"
        L.append("| %s | %s | %s %s | %s | %s | %d |"
                 % (r["id"], r.get("title", ""), r["module"], r["module_name"],
                    r["severity"], sig_txt, len(r["actions"])))
    L.append("")
    L.append("## 处方详情")
    for r in rxs:
        L += ["",
              "### %s · %s　[%s %s] %s" % (r["id"], r.get("title", ""),
                                           r["module"], r["module_name"], r["severity"]),
              "- **异常信号**：%s" % r["signal"],
              "- **对应模块**：%s %s" % (r["module"], r["module_name"]),
              "- **具体动作**："]
        L += ["  %d. %s" % (i, a) for i, a in enumerate(r["actions"], 1)]
        L += ["- **依据**：`%s`（%s）" % (r["basis"], r["basis_note"]),
              "- **失效条件**：%s" % r["falsify"]]
    L += ["", "## 口径与全局失效条件",
          "- 全部对比均为**同期窗口对照**（近期 %d 天），非 A/B 实验：方向可采信，倍数不当精确预测" % sig["days"],
          "- 平台不提供的量（粉丝数/曝光量/小时级点击率/完播）本单不推断、不填数；缺失处写「样本不足」",
          "- 若按处方调整后指标未改善 → 该变量非因果，回炉重测其他变量（每条处方的失效条件即回炉路径）",
          "- 处方条数 = 规则族数：每条规则族无论数据偏向哪边都出结论，含「当前非瓶颈、别在这里花时间」的负向处方"]
    L += ["", "## 数据说明"]
    L += ["- %s" % n for n in sig.get("notes", [])]
    return "\n".join(L)


def prescribe_from_items(items, days=30, user=""):
    sig = sg.extract(items, days=days, user=user)
    rxs = prescribe(sig)
    return sig, rxs


def prescribe_from_file(path, days=30, user=""):
    """path 可为 JSONL，也可为 signals.py 产出的 signals.json"""
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            sig = json.load(f)
        if sig.get("schema") != sg.SCHEMA:
            raise ValueError("不是看山信号文件（schema=%s）" % sig.get("schema"))
        if user:
            sig["user"] = user
        return sig, prescribe(sig)
    items, _ = sg.attach_dt(sg.load_items(path))
    if not items:
        raise ValueError("无有效数据（文件为空或全部行损坏）")
    user = (user or "").strip() or ((items[0].get("AuthorName") or "").strip() or "未标注")
    return prescribe_from_items(items, days=days, user=user)


def main():
    ap = argparse.ArgumentParser(description="看山 · 处方引擎（信号 → 模块 → 动作）")
    ap.add_argument("--in", dest="src", required=True, help="contents JSONL 或 signals.json")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--user", default="")
    ap.add_argument("--out", default=None, help="输出目录（写 prescribe.md / prescribe.json）")
    ap.add_argument("--json", dest="json_out", default=None, help="处方 JSON 输出路径")
    a = ap.parse_args()

    try:
        sig, rxs = prescribe_from_file(a.src, days=a.days, user=a.user)
    except OSError as e:
        print("[!] 读不了数据文件：%s" % e)
        print("    先用 scripts/zhihu_fetch.py 拉本人数据，或 scripts/demo_synth.py --user <名> 造合成数据")
        return 1
    except ValueError as e:
        print("[!] %s" % e)
        return 1

    md = render_md(sig, rxs)
    print(md)
    payload = {"schema": "kanshan.prescriptions/1", "summary": summarize(sig, rxs),
               "signals": sig, "prescriptions": rxs}
    if a.out:
        os.makedirs(a.out, exist_ok=True)
        with open(os.path.join(a.out, "prescribe.md"), "w", encoding="utf-8") as f:
            f.write(md)
        with open(os.path.join(a.out, "prescribe.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n[+] 处方单 -> %s" % os.path.join(a.out, "prescribe.md"))
        print("[+] 处方 JSON -> %s" % os.path.join(a.out, "prescribe.json"))
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("[+] 处方 JSON -> %s" % a.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
