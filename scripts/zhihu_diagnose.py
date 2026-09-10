#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 诊断层：把创作数据变成可执行的结论（全部同期对照）

用法：
    python scripts/zhihu_diagnose.py --in data/contents.jsonl [--out out/] [--days 60]

核心纪律：**同期对照**。直接拿全量比会被历史爆款污染，得出反向结论。
每条结论都附方法与失效条件，可证伪。
"""
import argparse, json, os, re, sys, datetime
from collections import Counter, defaultdict

TOPIC_PATTERNS = {
    "AI/科技": r"AI|人工智能|Agent|智能体|大模型|LLM|GPT|OpenAI|DeepSeek|Claude|模型|算力|算法|代码|coding|编程",
    "影视/动漫": r"电影|影视|动画|国漫|番剧|导演|演员|剧|影院|票房|封神|流浪地球",
    "游戏": r"游戏|黑神话|王者荣耀|LOL|英雄联盟|刺客信条|Steam|主机|手游|索尼|微软|任天堂",
    "社会/民生": r"房价|就业|涨租|工资|裁员|消费|经济|企业|公司|品牌|直播|外卖",
    "文史/知识": r"历史|三国|曹操|文学|小说|诗|哲学|思想|文化|经典|阅读",
}
CTA_PATTERN = r"多关注|关注我|看专栏|也不花钱|不要钱|我的专栏|详见我的"


def load(path):
    """逐行读取：坏行跳过并计数（压力预案③：恶意/损坏输入优雅降级，不裸崩）；
    CreatedAt<=0 的行无效（避免 1970 年污染年度分组）。"""
    items, bad, epoch0 = [], 0, 0
    with open(path, encoding="utf-8") as f:
        for lineno, l in enumerate(f, 1):
            if not l.strip():
                continue
            try:
                it = json.loads(l)
            except json.JSONDecodeError:
                bad += 1
                if bad <= 3:
                    print("[!] 第 %d 行不是合法 JSON，已跳过（坏行降级不中断）" % lineno)
                continue
            if not isinstance(it, dict) or int(it.get("CreatedAt") or 0) <= 0:
                epoch0 += 1
                continue
            it["dt"] = datetime.datetime.fromtimestamp(int(it["CreatedAt"]))
            items.append(it)
    if bad or epoch0:
        print("[!] 已跳过：坏行 %d 行、CreatedAt 无效 %d 行（优雅降级）" % (bad, epoch0))
    return items


def stat(subset, label):
    n = len(subset)
    if not n:
        return "%s: 0 条" % label
    lk = [it.get("LikeCount") or 0 for it in subset]
    cm = [it.get("CommentCount") or 0 for it in subset]
    fv = [it.get("FavoriteCount") or 0 for it in subset]
    zero = sum(1 for x in lk if x == 0)
    has_c = sum(1 for x in cm if x > 0)
    return ("%s | %d条 赞:总%d 均%.1f 最大%d | 评:总%d 均%.1f | 藏:总%d 均%.1f | 零赞率%.0f%% 有评论率%.0f%%"
            % (label, n, sum(lk), sum(lk) / n, max(lk), sum(cm), sum(cm) / n,
               sum(fv), sum(fv) / n, zero * 100.0 / n, has_c * 100.0 / n))


def build_report(items, days=60, user=None, src_label="(未标注来源)"):
    """生成七节诊断报告（CLI 与 demo 服务共用同一实现，避免两套口径）"""
    now = max(it["dt"] for it in items)
    recent = [it for it in items if (now - it["dt"]).days <= days]

    user = (user or "").strip() or ((items[0].get("AuthorName") or "").strip() or "未标注")
    L = ["# 看山诊断报告（用户：%s · 生成 %s）" % (user, datetime.date.today()),
         "数据源: %s（%d 条，%s ~ %s）" % (src_label, len(items),
                                          min(it["dt"] for it in items).date(), now.date()),
         ""]

    L.append("## 一、年度节奏（看趋势，不看总量）")
    by_year = defaultdict(list)
    for it in items:
        by_year[it["dt"].year].append(it)
    for y in sorted(by_year):
        L.append("  " + stat(by_year[y], "%d年" % y))

    L += ["", "## 二、近期窗口（避开历史爆款污染）"]
    for d in (7, 30, days, 365):
        L.append("  " + stat([it for it in items if (now - it["dt"]).days <= d], "近%d天" % d))

    L += ["", "## 三、内容类型效率"]
    by_type = defaultdict(list)
    for it in items:
        by_type[it.get("ContentType")].append(it)
    for t, v in sorted(by_type.items(), key=lambda kv: -len(kv[1])):
        L.append("  [%s] " % t + stat(v, "全量"))
        r = [x for x in v if (now - x["dt"]).days <= days]
        if r:
            L.append("       " + stat(r, "近%d天" % days))

    L += ["", "## 四、题材效率（产能压对地方了吗）"]
    for g, p in TOPIC_PATTERNS.items():
        sub = [it for it in items if re.search(p, (it.get("Title") or "") + " " + (it.get("Summary") or ""), re.I)]
        if sub:
            L.append("  " + stat(sub, g))
    L.append("  【近期产能占比】")
    for g, p in TOPIC_PATTERNS.items():
        n = sum(1 for it in recent if re.search(p, (it.get("Title") or "") + " " + (it.get("Summary") or ""), re.I))
        L.append("    %-10s %3d条 = %.0f%%" % (g, n, n * 100.0 / max(len(recent), 1)))

    L += ["", "## 五、篇幅同期对照（写长还是写短）"]
    r2 = [it for it in recent if (it.get("Summary") or "").strip()]
    if r2:
        lens = sorted(len(i.get("Summary") or "") for i in r2)
        med = lens[len(lens) // 2]
        for cond, lab in ((lambda x: len(x.get("Summary") or "") < med, "短于中位"),
                          (lambda x: len(x.get("Summary") or "") >= med, "长于中位")):
            L.append("  " + stat([i for i in r2 if cond(i)], lab))
        L.append("  中位摘要长度 = %d 字" % med)

    L += ["", "## 六、CTA 话术同期对照（引导有没有反作用）"]
    A = [i for i in recent if re.search(CTA_PATTERN, i.get("Summary") or "")]
    B = [i for i in recent if not re.search(CTA_PATTERN, i.get("Summary") or "")]
    L.append("  " + stat(A, "含引导话术"))
    L.append("  " + stat(B, "不含引导话术"))

    L += ["", "## 七、失效条件（可证伪，务必读）",
          "- 篇幅/题材/CTA 均为**观察性相关**，非 A/B 实验；方向可采信，倍数不当精确预测",
          "- 若按结论调整后指标未改善 → 说明该变量非因果，回炉重测其他变量",
          "- 题材分组用正则匹配，存在归类重叠，方向性结论可靠"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", default=os.path.join("data", "contents.jsonl"))
    ap.add_argument("--out", default="out")
    ap.add_argument("--days", type=int, default=60, help="近期窗口（天）")
    ap.add_argument("--user", default=None, help="用户名（缺省取数据内 AuthorName，无则『未标注』）")
    a = ap.parse_args()

    try:
        items = load(a.src)
    except OSError as e:
        print("[!] 读不了数据文件：%s" % e)
        print("    先用 scripts/zhihu_fetch.py 拉取本人数据，或 scripts/demo_synth.py --user <任意用户名> 造测试数据")
        return 1
    if not items:
        print("[!] 无有效数据（文件为空或全部行损坏）"); return 1
    os.makedirs(a.out, exist_ok=True)

    md = build_report(items, days=a.days, user=a.user, src_label=a.src)
    out_md = os.path.join(a.out, "diagnose.md")
    open(out_md, "w", encoding="utf-8").write(md)
    print(md)
    print("\n[+] 报告 -> %s" % out_md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
