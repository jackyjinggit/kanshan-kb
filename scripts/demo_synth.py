#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 任意用户名合成数据生成器（测试/演示用，脱敏 by construction）

为什么需要它：
  1. 真实数据只覆盖 happy path；边界（任意用户名、爆款污染、脏行）需要可控合成数据来测；
  2. 公开演示不能带真实身份数据（TODO §四 红线2）——合成数据天然合规。

用法：
    python scripts/demo_synth.py --user 张三 --archetype polluted
    python scripts/demo_synth.py --user "任意字符串🔥" --n 300 --corrupt 5

原型（archetype）：
    newbie    新手：量少、互动低、只近段
    polluted  爆款污染：早年 1-2 条大爆款 + 近期高产量低互动（看山核心场景）
    vertical  垂类专注：80%+ 内容集中在一个题材
    omnivore  杂食：题材均匀铺开

字段形状对齐 zhihu_fetch.py 实测 JSONL：
    AuthorName/ContentType/Url/CreatedAt(unix)/LikeCount/CommentCount/FavoriteCount/Title/Summary
同用户名 → 同数据（seed 由用户名派生），测试可复现。
"""
import argparse
import datetime
import hashlib
import json
import os
import random
import re
import sys

# ---- 题材池（词表与 zhihu_diagnose.TOPIC_PATTERNS 对齐，保证各分组能点亮）----
GENRES = {
    "AI/科技": [
        "大模型落地这一年：我看到的 AI 真实生产力",
        "Agent 智能体编排的工程实践与坑",
        "DeepSeek 开源之后，算法岗会过剩吗",
        "写给产品经理的 LLM 入门：从 GPT 说起",
        "算力焦虑：中小企业怎么用得起 AI",
        "代码助手实测：编程效率到底提升多少",
    ],
    "影视/动漫": [
        "国产动画的工业化转折点",
        "从票房看观众口味的变化",
        "导演剪辑权之争：影视行业的隐性规则",
        "影院变局之后，电影发行的新玩法",
        "国漫番剧的年更困境怎么破",
        "中国科幻电影走到哪一步了",
    ],
    "游戏": [
        "黑神话之后：国产 3A 的下一站",
        "从 Steam 愿望单看独立游戏冷启动",
        "主机大战新阶段：索尼微软任天堂的牌",
        "手游买量的尽头是什么",
        "LOL 电竞观赛入门指南",
        "王者荣耀的社交裂变机制拆解",
    ],
    "社会/民生": [
        "年轻人为什么开始关注房价租金比",
        "裁员潮下的简历自救指南",
        "消费降级还是分级：一份品牌观察",
        "外卖平台的佣金结构怎么算",
        "直播带货的公司化生存",
        "工资跑不赢通胀：普通人的对策",
    ],
    "文史/知识": [
        "读三国：曹操的用人术对今天的启发",
        "小说的开头为什么难写",
        "哲学入门的阅读顺序建议",
        "经典重读：我们为什么还需要诗",
        "历史写作中的材料取舍",
        "传统思想如何翻译成现代语言",
    ],
}
GENRE_KEYS = list(GENRES)

# CTA 词表 = zhihu_diagnose.CTA_PATTERN 的字面词（避免误触发/漏触发）
CTA_PHRASES = ["多关注不迷路。", "关注我，下期继续拆。", "看这篇的人也可以看看完整版。",
               "详见我整理的长文。", "也不花钱，点个赞就好。"]
S_POOL = ["先说结论。", "这个问题要分两层看。", "我踩过坑，所以写下来。",
          "数据和体感可能有出入。", "先给背景。", "核心矛盾在供需错配。",
          "方法论比结论更重要。", "举一个身边的例子。", "这里容易被人误读。"]
FILLER = ["展开讲：第一步看数据，第二步定边界，第三步才谈动作。",
          "补充一段反面案例，说明为什么通行做法在这里失效。",
          "给出三条例证，分别来自公开数据、同行讨论和个人实践。",
          "这里省略一半论证过程，结论的适用条件在文末。",
          "再多说一层：同样的做法放到不同体量的账号上结果会反过来。"]

ARCH_DEFAULTS = {"newbie": 60, "polluted": 320, "vertical": 180, "omnivore": 240}
NEWEST = datetime.datetime(2026, 9, 1, 12, 0, 0)  # 锚定最新一条，输出与墙钟无关


def seed_of(user, override=None):
    if override is not None:
        return int(override)
    return int(hashlib.md5(user.encode("utf-8")).hexdigest()[:8], 16)


def pick_type(rng):
    r = rng.random()
    if r < 0.62:
        return "answer"
    if r < 0.84:
        return "article"
    if r < 0.94:
        return "pin"
    return "question"


def make_summary(rng, with_cta):
    cls = rng.random()
    if cls < 0.4:
        sents = rng.sample(S_POOL, 1)
    elif cls < 0.8:
        sents = rng.sample(S_POOL, 2) + [rng.choice(FILLER)]
    else:
        sents = rng.sample(S_POOL, 3) + rng.choices(FILLER, k=rng.randint(2, 4))
    if with_cta:
        sents.append(rng.choice(CTA_PHRASES))
    return "".join(sents)


def make_item(rng, user, genre, ts, likes, i):
    return {
        "AuthorName": user,
        "ContentType": pick_type(rng),
        "Url": "https://www.zhihu.com/synth/%d" % i,
        "CreatedAt": int(ts),
        "LikeCount": likes,
        "CommentCount": max(0, int(likes * rng.uniform(0.05, 0.2)) + rng.randint(0, 2)),
        "FavoriteCount": max(0, int(likes * rng.uniform(0.1, 0.4))),
        "Title": rng.choice(GENRES[genre]),
        "Summary": make_summary(rng, rng.random() < 0.3),
    }


def gen(user, archetype, n, rng):
    base = NEWEST.timestamp()
    items = []
    if archetype == "newbie":
        span = 150
        for i in range(n):
            ts = base - rng.uniform(0, span) * 86400
            likes = rng.randint(0, 3) if rng.random() < 0.9 else rng.randint(4, 15)
            items.append(make_item(rng, user, rng.choice(GENRE_KEYS), ts, likes, i))
    elif archetype == "polluted":
        span = 2100
        # 老号也在持续更新：近 45 天必须有量，否则「同期窗口」无从对照（全量均值被早年爆款拉高才是本型的看点）
        n_recent = max(10, int(n * 0.25))
        for i in range(n_recent):
            ts = base - rng.uniform(0, 45) * 86400
            likes = min(int(rng.paretovariate(1.8) * 3), 40)
            items.append(make_item(rng, user, rng.choice(GENRE_KEYS), ts, likes, i))
        for i in range(n_recent, n):
            ts = base - rng.uniform(60, span) * 86400
            likes = min(int(rng.paretovariate(1.8) * 3), 40)
            items.append(make_item(rng, user, rng.choice(GENRE_KEYS), ts, likes, i))
        for j in range(2):  # 早年大爆款（同期对照要剔除的"污染源"）
            ts = base - rng.uniform(1200, 2000) * 86400
            items.append(make_item(rng, user, rng.choice(GENRE_KEYS), ts,
                                   rng.randint(2000, 5000), 1000 + j))
    elif archetype == "vertical":
        span, genre = 800, GENRE_KEYS[hash(user) % 5]
        for i in range(n):
            ts = base - rng.uniform(0, span) * 86400
            g = genre if rng.random() < 0.82 else rng.choice(GENRE_KEYS)
            likes = min(int(rng.expovariate(1 / 30)), 150)
            items.append(make_item(rng, user, g, ts, max(likes, 1), i))
    else:  # omnivore
        span = 1100
        for i in range(n):
            ts = base - rng.uniform(0, span) * 86400
            likes = min(int(rng.paretovariate(1.5) * 8), 250)
            items.append(make_item(rng, user, rng.choice(GENRE_KEYS), ts, likes, i))
    return items


def corrupt(items, k, rng):
    """注入 k 行损坏数据（压力预案③的测试样本）：半数 CreatedAt=0，半数非法 JSON 行"""
    out = list(items)
    half = k // 2
    for _ in range(half):
        bad = dict(out[rng.randrange(len(out))])
        bad["CreatedAt"] = 0
        out.insert(rng.randrange(len(out)), bad)
    for _ in range(k - half):
        out.insert(rng.randrange(len(out)), "not-json{")
    return out


def safe_name(user):
    s = re.sub(r'[\\/:*?"<>|\s]+', "_", user).strip("_")
    return s[:40] or "anon"


def main():
    ap = argparse.ArgumentParser(description="看山 · 任意用户名合成数据生成器")
    ap.add_argument("--user", required=True, help="任意用户名（中英/emoji/空串均可）")
    ap.add_argument("--archetype", choices=list(ARCH_DEFAULTS), default="polluted")
    ap.add_argument("--n", type=int, default=None, help="条数（缺省按原型）")
    ap.add_argument("--out", default=None, help="输出（缺省 data/synth_<用户>.jsonl）")
    ap.add_argument("--corrupt", type=int, default=0, help="注入损坏行数（测健壮性）")
    ap.add_argument("--seed", type=int, default=None, help="覆盖随机种子（缺省由用户名派生）")
    a = ap.parse_args()

    user = (a.user or "").strip() or "匿名用户"
    n = a.n or ARCH_DEFAULTS[a.archetype]
    rng = random.Random(seed_of(a.user or "", a.seed))
    out = a.out or os.path.join("data", "synth_%s.jsonl" % safe_name(user))

    items = gen(user, a.archetype, n, rng)
    if a.corrupt > 0:
        items = corrupt(items, a.corrupt, rng)

    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for it in items:
            f.write((it if isinstance(it, str) else json.dumps(it, ensure_ascii=False)) + "\n")

    likes_total = sum(it.get("LikeCount", 0) for it in items if isinstance(it, dict))
    print("[+] 用户=%r 原型=%s 条数=%d（含损坏 %d）总赞=%d" % (user, a.archetype, len(items), a.corrupt, likes_total))
    print("[+] 输出 -> %s" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
