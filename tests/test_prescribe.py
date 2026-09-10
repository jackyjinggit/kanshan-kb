#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""处方引擎单元/边界测试（stdlib unittest，无外部依赖）

    python -m unittest discover -s tests -v
    python tests/test_prescribe.py

覆盖：正常信号、零互动账号、单条数据、极端均值、缺字段、全规则可执行性（防规则内文案格式化异常）
"""
import ast
import datetime
import os
import random
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import demo_synth  # noqa: E402
import prescribe as pr  # noqa: E402
import signals as sg  # noqa: E402

TODAY = demo_synth.NEWEST


def mk(items_kwargs_list):
    """构造内部结构的 items（字段口径与 zhihu 公开接口一致：ContentType / CreatedAt(unix)）"""
    out = []
    for i, kw in enumerate(items_kwargs_list):
        it = {"Title": kw.get("title", "标题%d" % i), "ContentType": kw.get("type", "answer"),
              "CreatedAt": int(kw.get("ts", TODAY).timestamp()), "LikeCount": kw.get("like", 0),
              "CommentCount": kw.get("comment", 0), "FavoriteCount": kw.get("fav", 0),
              "Summary": kw.get("summary", "内容摘要，用来占位长度统计"), "AuthorName": kw.get("user", "测试账号"),
              "TopicTitle": kw.get("topic", "AI/科技")}
        out.append(it)
    return out


def sig_of(items, days=30, user="测试账号"):
    its, _ = sg.attach_dt(items)
    return sg.extract(its, days=days, user=user)


class TestRulesRunEverywhere(unittest.TestCase):
    """任何输入下，15 条规则族都必须给出结论且不抛异常（含格式化异常）"""

    def _assert_clean(self, items, label):
        sig = sig_of(items)
        rxs = pr.prescribe(sig)
        self.assertEqual(len(rxs), len(pr.RULES), "%s：规则族数应等于规则条数" % label)
        for r in rxs:
            self.assertNotIn("规则执行异常", r["signal"], "%s：%s 抛异常 -> %s" % (label, r["id"], r["signal"]))
            self.assertTrue(r["signal"].strip(), "%s：%s 信号文案为空" % (label, r["id"]))
            self.assertTrue(r["actions"], "%s：%s 缺少动作" % (label, r["id"]))
            self.assertTrue(r["falsify"].strip(), "%s：%s 缺少失效条件" % (label, r["id"]))
            self.assertIn(r["module"], {"M%d" % i for i in range(1, 11)})
        ids = [r["id"] for r in rxs]
        self.assertEqual(len(ids), len(set(ids)), "%s：处方编号重复" % label)
        return rxs

    def test_all_archetypes(self):
        for user, arch in [("甲", "polluted"), ("乙", "newbie"), ("丙", "vertical"), ("丁", "omnivore")]:
            rng = random.Random(demo_synth.seed_of(user))
            items = demo_synth.gen("演示账号%s" % user, arch, demo_synth.ARCH_DEFAULTS[arch], rng)
            self._assert_clean(items, "archetype:%s" % arch)

    def test_all_zero_interactions(self):
        self._assert_clean(mk([{"like": 0, "comment": 0, "fav": 0} for _ in range(20)]), "zero-interaction")

    def test_single_item(self):
        self._assert_clean(mk([{"like": 3, "comment": 1, "fav": 0}]), "single")

    def test_extreme_values(self):
        items = mk([{"like": 10 ** 9, "comment": 10 ** 8, "fav": 10 ** 7},
                    {"like": 0, "comment": 0, "fav": 0},
                    {"like": 1, "comment": 0, "fav": 0}])
        self._assert_clean(items, "extreme")

    def test_min_n_guards_no_false_positives(self):
        """样本不足时，规则必须走「样本不足」分支而不是编结论"""
        sig = sig_of(mk([{"like": 5, "comment": 0, "fav": 0}]))
        rxs = {r["id"]: r for r in pr.prescribe(sig)}
        blob = rxs["RX-02"]["signal"] + rxs["RX-04"]["signal"] + rxs["RX-05"]["signal"] + rxs["RX-07"]["signal"]
        self.assertIn("样本", blob)


class TestPrescriptionContent(unittest.TestCase):
    def test_min_ten_prescriptions_per_account(self):
        """验收线：每个账号 ≥10 条处方；实际 = 规则族数（15）"""
        rng = random.Random(demo_synth.seed_of("验收账号"))
        items = demo_synth.gen("验收账号", "polluted", 320, rng)
        sig, rxs = pr.prescribe_from_items(items, days=30, user="验收账号")
        self.assertGreaterEqual(len(rxs), 10)
        self.assertEqual(len(rxs), len(pr.RULES))

    def test_every_prescription_has_chain(self):
        """每条处方必须完整：信号 → 模块 → 动作 → 依据"""
        rng = random.Random(1)
        items = demo_synth.gen("链路账号", "vertical", 180, rng)
        sig, rxs = pr.prescribe_from_items(items, days=30, user="链路账号")
        for r in rxs:
            self.assertTrue(r["signal"])
            self.assertTrue(r["module"].startswith("M"))
            self.assertTrue(r["actions"] and all(a.strip() for a in r["actions"]))
            self.assertTrue(r["basis"].endswith("README.md"))
            self.assertTrue(os.path.exists(os.path.join(ROOT, r["basis"])),
                            "%s 的依据文件不存在：%s" % (r["id"], r["basis"]))

    def test_symptom_branches_opposite_accounts(self):
        """同一规则在相反数据下必须给出相反处方（防止规则永远只说一句话）"""
        base = [{"like": 100, "comment": 10, "fav": 5} for _ in range(12)]
        # 最新一篇远低于基线
        low = [dict(x) for x in base]
        low.append({"like": 1, "comment": 0, "fav": 0,
                    "ts": TODAY + datetime.timedelta(days=1)})
        sig_low = sig_of(mk(low))
        # 最新一篇远超基线
        high = [dict(x) for x in base]
        high.append({"like": 600, "comment": 40, "fav": 20,
                     "ts": TODAY + datetime.timedelta(days=1)})
        sig_high = sig_of(mk(high))

        rx_low = {r["id"]: r for r in pr.prescribe(sig_low)}["RX-01"]
        rx_high = {r["id"]: r for r in pr.prescribe(sig_high)}["RX-01"]
        self.assertIn("低于自身常态", rx_low["signal"])
        self.assertIn("推荐流放量", rx_high["signal"])
        self.assertEqual(rx_low["severity"], "高")
        self.assertEqual(rx_high["severity"], "高")
        self.assertNotEqual(rx_low["actions"][0], rx_high["actions"][0])

    def test_no_fabricated_metrics(self):
        """不得出现平台不提供的指标（粉丝数/曝光量/点击率/完播）作为事实断言"""
        rng = random.Random(3)
        items = demo_synth.gen("口径账号", "omnivore", 240, rng)
        sig, rxs = pr.prescribe_from_items(items, days=30, user="口径账号")
        blob = " ".join(r["signal"] + "".join(r["actions"]) for r in rxs)
        for forbidden in ("曝光量约为", "粉丝数达到", "完播率", "点击率为"):
            self.assertNotIn(forbidden, blob)

    def test_json_roundtrip_via_signals_file(self):
        import json
        import tempfile
        rng = random.Random(demo_synth.seed_of("信号文件账号"))
        items = demo_synth.gen("信号文件账号", "vertical", 180, rng)
        sig, rxs = pr.prescribe_from_items(items, days=30, user="信号文件账号")
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "s.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(sig, f, ensure_ascii=False)
            sig2, rxs2 = pr.prescribe_from_file(p, days=30, user="")
            self.assertEqual([r["id"] for r in rxs], [r["id"] for r in rxs2])
            self.assertEqual([r["signal"] for r in rxs], [r["signal"] for r in rxs2])

    def test_rejects_foreign_json(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump({"schema": "someone.else/1"}, f)
            with self.assertRaises(ValueError):
                pr.prescribe_from_file(p)


class TestSignalsLayer(unittest.TestCase):
    def test_data_internal_time_anchor(self):
        """时间锚点必须来自数据本身（最新一条），与墙钟无关 → 可复现"""
        items = mk([{"like": 1, "ts": TODAY - datetime.timedelta(days=i)} for i in range(30)])
        sig = sg.extract(sg.attach_dt(items)[0], days=30, user="锚点账号")
        self.assertTrue(sig["span_last"].startswith("2026-09-01"),
                        "最新一条应为合成数据的 2026-09-01，而不是墙钟日期：%s" % sig["span_last"])

    def test_bad_lines_dropped(self):
        its = [{"CreatedAt": 0, "LikeCount": 1}, {"CreatedAt": None, "LikeCount": 1},
               {"CreatedAt": "坏值", "LikeCount": 1}]
        kept, dropped = sg.attach_dt(its)
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 3)

    def test_extract_accepts_items_without_dt(self):
        """原始条目（只有 CreatedAt）直接喂 extract 不应崩（自动补 dt）"""
        items = [{"Title": "t%d" % i, "ContentType": "answer", "Summary": "摘要内容占位",
                  "CreatedAt": int((TODAY - datetime.timedelta(days=i)).timestamp()),
                  "LikeCount": i, "CommentCount": 0, "FavoriteCount": 0} for i in range(10)]
        sig = sg.extract(items, days=30, user="裸条目账号")
        self.assertEqual(sig["n_recent"], 10)

    def test_extract_deterministic(self):
        rng = random.Random(demo_synth.seed_of("复现账号"))
        items = demo_synth.gen("复现账号", "polluted", 320, rng)
        a = sg.extract(sg.attach_dt(items)[0], days=30, user="复现账号")
        b = sg.extract(sg.attach_dt(items)[0], days=30, user="复现账号")
        self.assertEqual(a, b)
        self.assertEqual(a["schema"], "kanshan.signals/1")


def _all_account_runs():
    """4 原型 × 2 用户名 = 8 个账号的 (signals, prescriptions)"""
    out = {}
    for arch in demo_synth.ARCH_DEFAULTS:
        for u in ("演示账号甲", "演示账号乙"):
            rng = random.Random(demo_synth.seed_of(u))
            items = demo_synth.gen(u, arch, demo_synth.ARCH_DEFAULTS[arch], rng)
            out[(arch, u)] = pr.prescribe_from_items(items, days=30, user=u)
    return out


class TestStatesAndGrouping(unittest.TestCase):
    """状态分组：15 个规则族必然全跑（覆盖清单），但只有命中的才进行动清单"""

    def test_every_prescription_has_valid_state(self):
        for key, (sig, rxs) in _all_account_runs().items():
            for r in rxs:
                self.assertIn(r["state"], pr.VALID_STATES,
                              "%s %s 状态非法：%r" % (key, r["id"], r.get("state")))

    def test_groups_partition_all_rules(self):
        for key, (sig, rxs) in _all_account_runs().items():
            g = pr.group_by_state(rxs)
            self.assertEqual(len(rxs), len(pr.RULES), "%s：规则族数变了" % (key,))
            self.assertEqual(sum(len(v) for v in g.values()), len(rxs),
                             "%s：分组后有处方丢失" % (key,))

    def test_negative_prescriptions_stay_out_of_action_list(self):
        """「不是瓶颈/样本不足」的条目不得混进行动清单，否则清单又被撑回固定条数"""
        for key, (sig, rxs) in _all_account_runs().items():
            hits = set(pr.hit_ids(rxs))
            self.assertEqual(hits, set(pr.hit_ids(rxs)), "%s：命中集合不稳定" % (key,))
            for r in rxs:
                if r["state"] != "alert":
                    self.assertNotIn(r["id"], hits, "%s：%s 非命中却进了行动清单" % (key, r["id"]))

    def test_every_rule_branch_declares_state(self):
        """静态闸门：prescribe.py 里每个 _rx(...) 调用点都必须显式声明状态

        漏标的分支只在真正跑到时才 TypeError——静态检查才拦得住没跑到的分支。
        """
        path = os.path.join(ROOT, "scripts", "prescribe.py")
        with open(path, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src)
        lines = src.splitlines()
        missing, bad = [], []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_rx":
                if lines[node.lineno - 1].strip().startswith("def _rx"):
                    continue
                a = node.args
                st = a[3].value if len(a) > 3 and isinstance(a[3], ast.Constant) else None
                if st is None:
                    missing.append(node.lineno)
                elif st not in pr.VALID_STATES:
                    bad.append((node.lineno, st))
        self.assertEqual(missing, [], "这些 _rx 调用点没标状态：%s" % missing)
        self.assertEqual(bad, [], "状态取值非法：%s" % bad)
        self.assertGreaterEqual(len(pr.RULES), 10)

    def test_markdown_sections_follow_states(self):
        """处方单必须按状态分节呈现，且行动清单只收录命中项"""
        sig, rxs = _all_account_runs()[("newbie", "演示账号甲")]
        md = pr.render_md(sig, rxs)
        self.assertIn("本期行动清单", md)
        self.assertIn("已排除", md)
        for r in rxs:
            if r["state"] == "alert":
                self.assertIn(r["id"], md[md.index("## 一、"):md.index("## 二、")] if "## 二、" in md else md)


class TestAccountDifferentiation(unittest.TestCase):
    """「换几个账号也要各自出不同的建议」——行动清单必须随账号变，否则演示就是套模板"""

    def test_action_lists_differ_across_accounts(self):
        seen = {}
        for arch in demo_synth.ARCH_DEFAULTS:
            for u in ("演示账号甲", "演示账号乙"):
                rng = random.Random(demo_synth.seed_of(u))
                items = demo_synth.gen(u, arch, demo_synth.ARCH_DEFAULTS[arch], rng)
                sig, rxs = pr.prescribe_from_items(items, days=30, user=u)
                seen[(arch, u)] = tuple(pr.hit_ids(rxs))
        self.assertEqual(len(set(seen.values())), len(seen),
                         "8 个账号应得到 8 套不同清单，实为 %d 套：%s" % (len(set(seen.values())), seen))
        for arch in demo_synth.ARCH_DEFAULTS:
            self.assertNotEqual(seen[(arch, "演示账号甲")], seen[(arch, "演示账号乙")],
                                "%s：同原型只换用户名却得到同一份清单" % arch)
        counts = set(len(v) for v in seen.values())
        self.assertGreater(len(counts), 1, "命中条数恒定，说明清单没随账号变：%s" % counts)

    def test_action_list_is_a_proper_subset(self):
        """行动清单必须是规则族的真子集（不是「15 条换个顺序」）"""
        rng = random.Random(demo_synth.seed_of("演示账号甲"))
        items = demo_synth.gen("演示账号甲", "newbie", demo_synth.ARCH_DEFAULTS["newbie"], rng)
        sig, rxs = pr.prescribe_from_items(items, days=30, user="演示账号甲")
        hits = set(pr.hit_ids(rxs))
        self.assertGreaterEqual(len(hits), 1)
        self.assertLess(len(hits), len(pr.RULES))

    def test_headline_differs_per_account(self):
        hl = []
        for arch in demo_synth.ARCH_DEFAULTS:
            rng = random.Random(demo_synth.seed_of("演示账号甲"))
            items = demo_synth.gen("演示账号甲", arch, demo_synth.ARCH_DEFAULTS[arch], rng)
            sig, rxs = pr.prescribe_from_items(items, days=30, user="演示账号甲")
            s = pr.summarize(sig, rxs)
            self.assertEqual(s["alerts"], len(pr.hit_ids(rxs)))
            hl.append(s["headline"])
        self.assertGreater(len(set(hl)), 1, "结论句不应四个原型完全相同")


if __name__ == "__main__":
    unittest.main(verbosity=2)
