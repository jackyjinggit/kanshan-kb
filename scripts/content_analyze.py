#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 贴入式内容分析（无账号授权入口）

场景：评委/用户**没有任何账号数据授权**时，把一段内容贴进来就要能出分析。
所以本引擎只吃文本，不碰网络、不碰账号、不落任何凭据。

分析维度（对齐 M 模块）：
  1. 内容概览        字数 / 段落 / 句数 / 阅读时长 / 链接占比
  2. M4 爆款要素体检  3 秒钩子 · 情绪共鸣 · 干货密度 · 互动锚点（加权打分，规则词表外置）
  3. 结构诊断        段落长度分布 / 小标题 / 开头钩子位置 / 结尾锚点
  4. M10 合规风险     风险规则命中（高/中）+ 无法正则化的自查清单
  5. 校验规则插槽     规则来源与版本（规则由设计组填，**不写死在代码里**）
  6. 失效条件         本报告不能用来干什么，写清楚

用法：
    python scripts/content_analyze.py --file draft.md [--title "标题"]
    python scripts/content_analyze.py --text "正文……" --json out.json
    python scripts/content_analyze.py --stdin < draft.txt
    python scripts/content_analyze.py --file draft.md --rules scripts/rules/content_rules.json
"""
import argparse
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(HERE, "rules")
DEFAULT_RULES = os.path.join(RULES_DIR, "content_rules.default.json")
TRACKED_RULES = os.path.join(RULES_DIR, "content_rules.json")
LOCAL_RULES = os.path.join(RULES_DIR, "content_rules.local.json")

MAX_ANALYZE_CHARS = 20000        # 超长文本只分析前 N 字（护栏：避免极端输入拖垮现场演示）
TAIL_WINDOW = 150                # 结尾锚点判定窗口
MIN_SCORE_CHARS = 30             # 去链接后正文少于该字数 → 不评分（纯链接/空壳输入）
EVIDENCE_PAD = 16

LEVEL_ORDER = {"高": 0, "中": 1, "低": 2, "提示": 3}


# ---------------------------------------------------------------- 规则装载
def load_rules(explicit=None):
    """返回 (rules, source_path, is_example)。优先级：--rules > 正式 > 本地 > 示例"""
    for path, is_example in ((explicit, False), (TRACKED_RULES, False), (LOCAL_RULES, False), (DEFAULT_RULES, True)):
        if path and os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f), path, is_example
    raise FileNotFoundError("找不到任何规则文件（含示例）：%s" % DEFAULT_RULES)


def _compiled(rules):
    """把词表编译成正则（只编一次）"""
    out = {}
    for comp in ("hook", "emotion", "punch", "anchor"):
        items = []
        for feat in rules["m4"].get(comp, []):
            items.append((feat, re.compile(feat["pattern"], re.I)))
        out[comp] = items
    m10 = []
    for r in rules["m10"].get("rules", []):
        m10.append((r, re.compile(r["pattern"], re.I)))
    out["m10"] = m10
    return out


# ---------------------------------------------------------------- 基础度量
def _is_cjk(ch):
    return "\u4e00" <= ch <= "\u9fff"


def overview(text, rules):
    cfg = rules.get("structure", {})
    eff = re.sub(r"\s", "", text)
    links = re.findall(r"https?://\S+", text)
    link_chars = sum(len(u) for u in links)
    paras = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    sents = [s for s in re.split(r"[。！？!?；;\n]+", text) if s.strip()]
    cpm = cfg.get("reading_chars_per_minute", 400)
    emoji = sum(1 for ch in text if unicodedata.category(ch) == "So")
    return {
        "chars": len(text),
        "chars_effective": len(eff),
        "chars_cjk": sum(1 for ch in text if _is_cjk(ch)),
        "paragraphs": len(paras),
        "paragraph_lens": [len(re.sub(r"\s", "", p)) for p in paras],
        "sentences": len(sents),
        "reading_minutes": round(len(eff) / cpm, 1) if cpm else None,
        "links": len(links),
        "link_ratio": round(link_chars / max(1, len(eff)), 3),
        "emoji": emoji,
        "avg_sentence_chars": round(len(eff) / len(sents), 1) if sents else 0,
        "avg_paragraph_chars": round(sum(len(re.sub(r"\s", "", p)) for p in paras) / len(paras), 1) if paras else 0,
    }


def _snippet(text, m):
    a = max(0, m.start() - EVIDENCE_PAD)
    b = min(len(text), m.end() + EVIDENCE_PAD)
    s = re.sub(r"\s+", " ", text[a:b]).strip()
    return ("…" if a > 0 else "") + s + ("…" if b < len(text) else "")


def _match(text, pat):
    return list(pat.finditer(text))


def m4_score(text, rules, compiled):
    """M4 四要素加权打分（0-100，规则词表驱动）"""
    cfg = rules.get("structure", {})
    comps = rules["m4"]["components"]
    hook_window = cfg.get("hook_window_chars", 120)
    opening = text[:hook_window]
    tail = text[-TAIL_WINDOW:]
    windows = {"hook": opening, "emotion": text, "punch": text, "anchor": text}

    detail = {}
    scores = {}
    for comp in ("hook", "emotion", "punch", "anchor"):
        max_score = comps[comp]["max"]
        got = 0.0
        hits = []
        for feat, pat in compiled[comp]:
            scope = windows[comp]
            if feat.get("window") == "tail":
                scope = tail
            ms = _match(scope, pat)
            if not ms:
                continue
            n = len(ms)
            w = feat["weight"]
            if feat.get("per_hit"):
                w = min(n, feat.get("max_hits", 1)) * w
            got += w
            hits.append({"id": feat["id"], "label": feat["label"], "n": n,
                         "weight": feat["weight"], "score": round(min(w, max_score), 1),
                         "evidence": [_snippet(scope, m) for m in ms[:2]],
                         "hint": feat.get("hint", "")})
        scores[comp] = round(min(got, max_score), 1)
        detail[comp] = {"label": comps[comp]["label"], "max": max_score,
                        "score": scores[comp], "hits": hits,
                        "missed": [{"id": f["id"], "label": f["label"], "hint": f.get("hint", "")}
                                   for f, _p in compiled[comp] if f["id"] not in {h["id"] for h in hits}]}
    total = round(sum(scores.values()), 1)
    return {"total": total, "components": detail, "scores": scores,
            "hook_window_chars": hook_window, "tail_window": TAIL_WINDOW}


def grade(total):
    if total is None:
        return "不可评分"
    if total >= 75:
        return "优"
    if total >= 55:
        return "良"
    if total >= 35:
        return "中"
    return "弱"


def structure_check(text, ov, rules, m4):
    cfg = rules.get("structure", {})
    maxp = cfg.get("max_paragraph_chars", 200)
    subhead_min = cfg.get("subhead_min_chars", 800)
    short_post = cfg.get("short_post_chars", 100)
    findings = []
    lens = ov["paragraph_lens"]

    if lens:
        long_paras = [i + 1 for i, n in enumerate(lens) if n > maxp]
        if long_paras:
            findings.append({
                "id": "ST-01", "level": "中", "name": "长段落",
                "evidence": "第 %s 段超过 %d 字（最长 %d 字）" % ("/".join(map(str, long_paras[:5])), maxp, max(lens)),
                "advice": "把超过 %d 字的段落拆成 2-3 段；手机端一屏约 90-120 字，超过就丢读者" % maxp})
        if ov["chars_effective"] > 400 and len(lens) < 3:
            findings.append({
                "id": "ST-02", "level": "中", "name": "未分段",
                "evidence": "%d 字只分了 %d 段" % (ov["chars_effective"], len(lens)),
                "advice": "按语义拆段（每 1-3 句一段），分段的阅读完成率通常明显高于整块文本"})
    has_subhead = bool(re.search(r"^\s*(?:#{1,4}\s|\d+[、.]|[-*•]\s|\*\*[^*]{2,30}\*\*)", text, re.M)) or \
        bool(re.search(r"^.{2,18}[：:]\s*$", text, re.M))
    if ov["chars"] >= subhead_min and not has_subhead:
        findings.append({
            "id": "ST-03", "level": "中", "name": "长文无小标题",
            "evidence": "%d 字，未检出行级小标题或编号小节" % ov["chars"],
            "advice": "给每 300-500 字加一个小标题；小标题同时提升跳读体验和搜索命中"})
    if not m4["components"]["hook"]["hits"]:
        findings.append({
            "id": "ST-04", "level": "高", "name": "开头缺钩子",
            "evidence": "前 %d 字未命中任何钩子特征（提问/结论前置/反常识/数字/场景）" % m4["hook_window_chars"],
            "advice": "把最反常识的一句或最具体的一个数字挪到第一句；前两行决定读者是否点「展开」"})
    if not m4["components"]["anchor"]["hits"]:
        findings.append({
            "id": "ST-05", "level": "中", "name": "结尾无互动锚点",
            "evidence": "结尾 %d 字内无提问/引导/邀请讨论" % TAIL_WINDOW,
            "advice": "结尾加一个**具体**问题（不是「你怎么看」），评论量是分发二次放大的主要入口"})
    if ov["chars_effective"] < short_post:
        findings.append({
            "id": "ST-06", "level": "提示", "name": "短内容",
            "evidence": "去空白后仅 %d 字（低于 %d 字阈值）" % (ov["chars_effective"], short_post),
            "advice": "短内容可以发，但不要和导流话术叠加（平台公开规则：连续 3 天发 <100 字或含大量导流会扣创作行为分）"})
    if has_subhead and not any(f["id"] in ("ST-03",) for f in findings):
        findings.append({
            "id": "ST-07", "level": "低", "name": "结构清晰",
            "evidence": "检出小标题/编号小节，段落平均 %s 字" % ov["avg_paragraph_chars"],
            "advice": "保持该结构；把本篇的分段节拍记进模板"})
    if not findings:
        findings.append({"id": "ST-00", "level": "低", "name": "结构无显著问题",
                         "evidence": "段落长度、小标题、钩子、结尾锚点均未见明显缺陷",
                         "advice": "结构已达标，下一步优化选题与钩子的「具体度」"})
    findings.sort(key=lambda f: LEVEL_ORDER.get(f["level"], 9))
    return findings


def m10_check(text, rules, compiled):
    hits = []
    for rule, pat in compiled["m10"]:
        ms = _match(text, pat)
        if not ms:
            continue
        hits.append({"id": rule["id"], "name": rule["name"], "level": rule["level"],
                     "advice": rule["advice"], "basis": rule.get("basis", ""),
                     "n": len(ms), "evidence": [_snippet(text, m) for m in ms[:3]]})
    hits.sort(key=lambda h: LEVEL_ORDER.get(h["level"], 9))
    return {"hits": hits, "self_check": rules["m10"].get("self_check", []),
            "high": sum(1 for h in hits if h["level"] == "高"),
            "medium": sum(1 for h in hits if h["level"] == "中")}


# ---------------------------------------------------------------- 主分析
def analyze(text, title="", rules=None, rules_source=None, is_example=False):
    if text is None or not text.strip():
        raise ValueError("内容为空（只有空白/换行），没有可分析的正文")
    rules = rules or json.load(open(DEFAULT_RULES, encoding="utf-8"))
    compiled = _compiled(rules)

    notes = []
    body = text
    if len(text) > MAX_ANALYZE_CHARS:
        body = text[:MAX_ANALYZE_CHARS]
        notes.append("原文 %d 字，超过 %d 字上限：**仅分析前 %d 字**；下表「有效字数/段落/句数/段长」等统计同样只覆盖截断后的文本，未做全文统计"
                     % (len(text), MAX_ANALYZE_CHARS, MAX_ANALYZE_CHARS))

    ov = overview(body, rules)
    ov["chars_raw"] = len(text)
    de_linked = re.sub(r"https?://\S+", "", body)
    link_only = len(re.sub(r"\s", "", de_linked)) < MIN_SCORE_CHARS
    if link_only:
        notes.append("去链接后正文不足 %d 字：判定为「纯链接/空壳输入」，**M4 要素不给分**（给 0 分会误导）"
                     % MIN_SCORE_CHARS)

    m4 = m4_score(body, rules, compiled)
    struct = [{"id": "ST-09", "level": "高", "name": "纯链接输入",
               "evidence": "正文几乎只有链接（链接占比 %s）" % ov["link_ratio"],
               "advice": "贴入正文文本再分析；链接本身没有内容特征可评"}
              if link_only else None]
    struct = [f for f in struct if f] + structure_check(body, ov, rules, m4)
    m10 = m10_check(body, rules, compiled)

    total = None if link_only else m4["total"]
    result = {
        "schema": "kanshan.content_analysis/1",
        "title": title or "(未填标题)",
        "overview": ov,
        "m4": m4,
        "score": total,
        "grade": grade(total),
        "structure": struct,
        "m10": m10,
        "rules_source": {
            "path": os.path.basename(rules_source) if rules_source else "(内置示例)",
            "version": rules.get("version", "未标注"),
            "updated": rules.get("updated", "未标注"),
            "owner": rules.get("owner", "未标注"),
            "is_example": bool(is_example),
            "m4_feature_count": sum(len(rules["m4"].get(c, [])) for c in ("hook", "emotion", "punch", "anchor")),
            "m10_rule_count": len(rules["m10"].get("rules", [])),
            "m10_selfcheck_count": len(rules["m10"].get("self_check", [])),
        },
        "notes": notes,
    }
    return result


def _bar(score, maxv, width=10):
    filled = int(round(width * (score / maxv))) if maxv else 0
    return "█" * filled + "·" * (width - filled)


def render_md(r, rules_example_hint=True):
    ov, m4, m10 = r["overview"], r["m4"], r["m10"]
    L = ["# 看山 · 贴入式内容分析报告",
         "标题：%s ｜ 字数：%d（去空白 %d）｜ 段落：%d ｜ 预估阅读：%s 分钟"
         % (r["title"], ov["chars_raw"], ov["chars_effective"], ov["paragraphs"], ov["reading_minutes"]),
         ""]

    # 1 概览
    L += ["## 一、内容概览", "",
          "| 指标 | 值 | 指标 | 值 |", "|---|---|---|---|",
          "| 原文总字数 | %d | 分析范围有效字数 | %d |" % (ov["chars_raw"], ov["chars_effective"]),
          "| 中文字数 | %d | 段落数 | %d |" % (ov["chars_cjk"], ov["paragraphs"]),
          "| 句数 | %d | 平均句长 | %s 字 |" % (ov["sentences"], ov["avg_sentence_chars"]),
          "| 平均段长 | %s 字 | 最长段 | %s 字 |"
          % (ov["avg_paragraph_chars"], max(ov["paragraph_lens"]) if ov["paragraph_lens"] else 0),
          "| 链接数 | %d | 链接占比 | %s |" % (ov["links"], ov["link_ratio"]),
          "| 表情符号 | %d | 预估阅读 | %s 分钟 |" % (ov["emoji"], ov["reading_minutes"]),
          ""]

    # 2 M4
    score_txt = "## 二、M4 爆款要素体检：不可评分（输入无有效正文）" if r["score"] is None \
        else "## 二、M4 爆款要素体检（%s：%g 分 / 100 分）" % (r["grade"], r["score"])
    L += [score_txt,
          "",
          "口径：3 秒钩子 × 情绪共鸣 × 干货密度 × 互动锚点（M4 模块公式）；规则词表来自校验规则文件，非模型主观打分。",
          "",
          "| 要素 | 得分 | 占位 | 命中特征 |", "|---|---|---|---|"]
    for comp in ("hook", "emotion", "punch", "anchor"):
        d = m4["components"][comp]
        hit_labels = "、".join("%s×%d" % (h["label"], h["n"]) for h in d["hits"]) or "无"
        L.append("| %s | %g / %d | `%s` | %s |" % (d["label"], d["score"], d["max"], _bar(d["score"], d["max"]), hit_labels))
    L.append("")
    for comp in ("hook", "emotion", "punch", "anchor"):
        d = m4["components"][comp]
        L.append("**%s（%g/%d）**" % (d["label"], d["score"], d["max"]))
        if d["hits"]:
            for h in d["hits"]:
                L.append("- ✅ %s（命中 %d 次，+%s 分）：`%s`" % (h["label"], h["n"], h["score"], h["evidence"][0] if h["evidence"] else ""))
        for m in d["missed"][:3]:
            L.append("- ⬜ %s 未命中——%s" % (m["label"], m["hint"]))
        L.append("")

    # 3 结构
    L += ["## 三、结构诊断", ""]
    for f in r["structure"]:
        L += ["**[%s] %s · %s**" % (f["level"], f["id"], f["name"]),
              "- 证据：%s" % f["evidence"],
              "- 建议：%s" % f["advice"], ""]

    # 4 M10
    L += ["## 四、M10 合规风险自查", "",
          "自动命中：高 %d 条 / 中 %d 条" % (m10["high"], m10["medium"]), ""]
    if m10["hits"]:
        for h in m10["hits"]:
            L += ["**[%s] %s · %s（命中 %d 次）**" % (h["level"], h["id"], h["name"], h["n"]),
                  "- 原文：`%s`" % "` / `".join(h["evidence"]),
                  "- 改法：%s" % h["advice"],
                  "- 依据：`%s`" % h["basis"], ""]
    else:
        L += ["- ✅ 未命中风险规则（注意：只代表没踩到规则词表里的模式，不代表内容必然合规）", ""]
    L += ["**无法用规则判定、必须自查的项**", ""]
    for s in m10["self_check"]:
        L.append("- [ ] %s：%s（依据 `%s`）" % (s["name"], s["advice"], s.get("basis", "")))
    L.append("")

    # 5 规则插槽
    rs = r["rules_source"]
    L += ["## 五、校验规则插槽（规则由设计组填，不写死在代码里）",
          "",
          "| 项 | 值 |", "|---|---|",
          "| 规则文件 | `%s` |" % rs["path"],
          "| 版本 / 更新 | %s / %s |" % (rs["version"], rs["updated"]),
          "| 负责人 | %s |" % rs["owner"],
          "| M4 特征条数 | %d |" % rs["m4_feature_count"],
          "| M10 自动规则条数 | %d |" % rs["m10_rule_count"],
          "| M10 自查项条数 | %d |" % rs["m10_selfcheck_count"],
          "",
          "装载优先级：`--rules` 指定 > `scripts/rules/content_rules.json`（正式）> `content_rules.local.json`（本地私有）> `content_rules.default.json`（示例）",
          ""]
    if rs["is_example"] and rules_example_hint:
        L += ["> ⚠️ 当前使用的是**示例规则**（`content_rules.default.json`）：设计组的校验规则库尚未接入，",
              "> 本报告只代表示例词表口径。规则库到位后把文件放到 `scripts/rules/content_rules.json` 即可自动接管，**无需改代码**。", ""]

    # 6 失效条件
    L += ["## 六、失效条件与边界（本报告不能用来干什么）",
          "",
          "1. 本报告基于**文本特征**（词表命中 + 结构统计），不是平台数据：**不预测阅读量、不预测涨粉、不评估曝光**。",
          "2. 分数是「自比工具」：同一作者不同稿件之间比较有意义；跨领域横向比较无意义（词表偏好叙事与数据型内容）。",
          "3. 合规命中是启发式筛查，**不构成平台判定**；平台规则以官方最新公告为准，规则变动后旧结论作废。",
          "4. 规则库未接入时（示例规则），结论口径 = 示例词表，不可对外当作标准。",
          "5. 超长文本只分析前 %d 字；纯链接输入不给分。" % MAX_ANALYZE_CHARS,
          ]
    if r["notes"]:
        L += ["", "**本次分析的输入提示**", ""] + ["- %s" % n for n in r["notes"]]
    return "\n".join(L)


def analyze_file(path, title="", rules_path=None):
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
    rules, src, is_example = load_rules(rules_path)
    return analyze(text, title=title, rules=rules, rules_source=src, is_example=is_example)


def main():
    ap = argparse.ArgumentParser(description="看山 · 贴入式内容分析（无需账号授权）")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="直接贴入正文")
    src.add_argument("--file", help="从文本文件读取正文（.txt/.md）")
    src.add_argument("--stdin", action="store_true", help="从标准输入读取正文")
    ap.add_argument("--title", default="")
    ap.add_argument("--rules", default=None, help="指定规则文件（默认走装载优先级）")
    ap.add_argument("--out", default=None, help="报告输出路径（.md）")
    ap.add_argument("--json", dest="json_out", default=None, help="结果 JSON 输出路径")
    a = ap.parse_args()

    try:
        if a.stdin:
            text = sys.stdin.read()
            rules, srcp, is_ex = load_rules(a.rules)
            r = analyze(text, title=a.title, rules=rules, rules_source=srcp, is_example=is_ex)
        elif a.file:
            r = analyze_file(a.file, title=a.title, rules_path=a.rules)
        else:
            rules, srcp, is_ex = load_rules(a.rules)
            r = analyze(a.text, title=a.title, rules=rules, rules_source=srcp, is_example=is_ex)
    except OSError as e:
        print("[!] 读不了文件：%s" % e)
        return 1
    except ValueError as e:
        print("[!] %s" % e)
        print("    贴入正文文本（≥%d 字）再试；纯链接、纯空白无法分析。" % MIN_SCORE_CHARS)
        return 1

    md = render_md(r)
    print(md)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print("\n[+] 报告 -> %s" % a.out)
    if a.json_out:
        os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print("[+] JSON -> %s" % a.json_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
