#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""贴入式内容分析 · 单元/边界测试（stdlib unittest）

    python -m unittest discover -s tests -t . -v
    python tests/test_content_analyze.py

覆盖边界：空输入、纯空白、纯链接、超长文本、含敏感词、HTML/脚本注入、规则文件缺失/替换、不可评分语义
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import content_analyze as ca  # noqa: E402

RULES, RULES_SRC, IS_EX = ca.load_rules()

GOOD = """为什么你收藏了 300 篇干货，一篇也没用上？

先说结论：收藏不是学习，收藏只是把焦虑存了个盘。

我去年也这样：收藏夹 300 多篇，真正复用的不到 5 篇。数据来自我自己的导出记录（共 312 条）：
- 当天处理的，复用率 41%
- 3 天后处理的，复用率 6%

所以我用一个三步法替代了「先收藏再说」：第一步，立刻问这条能用在哪个正在进行的事情上；第二步，当场写一句「我会用它做什么」；第三步，每周清一次收藏夹。

这个方法的边界要说清楚：它对工具型内容有效，对观点型内容不太适用。

你最近一次把收藏的内容真正用掉，是哪一篇？
"""

RISK = ("全网最好的理财方法，100% 稳赚，我保证你月入过万。加微信 zhuanqian888 拉你进群，"
        "扫码进群还有福利。这个方子能彻底根治失眠，药到病除。三天学会，保证学会。"
        "有问题打 13812345678。详见 https://example.com/post 。那些脑残杠精别来。")


class TestHappyPath(unittest.TestCase):
    def setUp(self):
        self.r = ca.analyze(GOOD, title="收藏夹复用", rules=RULES, rules_source=RULES_SRC, is_example=IS_EX)

    def test_schema_and_score(self):
        self.assertEqual(self.r["schema"], "kanshan.content_analysis/1")
        self.assertIsNotNone(self.r["score"])
        self.assertGreaterEqual(self.r["score"], 55)
        self.assertIn(self.r["grade"], ("优", "良"))

    def test_four_m4_components_all_present(self):
        for comp in ("hook", "emotion", "punch", "anchor"):
            d = self.r["m4"]["components"][comp]
            self.assertIn("score", d)
            self.assertLessEqual(d["score"], d["max"])
            self.assertTrue(d["hits"] or d["missed"], "要素必须给出命中或未命中说明")

    def test_structure_and_compliance_and_slot(self):
        self.assertTrue(self.r["structure"])
        self.assertIn("self_check", self.r["m10"])
        self.assertGreaterEqual(self.r["rules_source"]["m10_rule_count"], 5)
        self.assertGreaterEqual(self.r["rules_source"]["m4_feature_count"], 10)

    def test_md_render_has_six_sections(self):
        md = ca.render_md(self.r)
        for sec in ("## 一、内容概览", "## 二、M4 爆款要素体检", "## 三、结构诊断",
                    "## 四、M10 合规风险自查", "## 五、校验规则插槽", "## 六、失效条件"):
            self.assertIn(sec, md)

    def test_report_states_limits(self):
        md = ca.render_md(self.r)
        self.assertIn("不预测阅读量", md)
        self.assertIn("不构成平台判定", md)


class TestBoundaries(unittest.TestCase):
    def _run(self, text, **kw):
        return ca.analyze(text, rules=RULES, rules_source=RULES_SRC, is_example=IS_EX, **kw)

    def test_empty_and_whitespace_raise(self):
        for bad in ("", "   ", "\n\n\t \r\n", "　　"):
            with self.assertRaises(ValueError):
                self._run(bad)

    def test_pure_link_not_scored_zero(self):
        r = self._run("https://zhuanlan.zhihu.com/p/123456789")
        self.assertIsNone(r["score"], "纯链接输入必须「不可评分」，不能给 0 分冒充结论")
        self.assertEqual(r["grade"], "不可评分")
        self.assertTrue(any(f["id"] == "ST-09" for f in r["structure"]))

    def test_link_with_short_text_not_scored(self):
        r = self._run("看这个 https://example.com/a  好文")
        self.assertIsNone(r["score"])

    def test_super_long_text_truncated_and_flagged(self):
        text = "这是一段用于超长测试的正文内容。" * 4000      # ~64000 字
        r = self._run(text)
        self.assertEqual(r["overview"]["chars_raw"], len(text))
        self.assertLessEqual(r["overview"]["chars_effective"], ca.MAX_ANALYZE_CHARS)
        self.assertTrue(any("仅分析前" in n for n in r["notes"]))
        md = ca.render_md(r)
        self.assertIn("仅分析前", md)

    def test_html_script_injection_survives(self):
        text = "<script>alert(1)</script><img src=x onerror=alert(2)>\n" + GOOD
        r = self._run(text)
        self.assertIsNotNone(r["score"])
        md = ca.render_md(r)          # 渲染不崩；转义是呈现层职责（demo 页面对贴入内容做转义）
        self.assertIn("M4 爆款要素体检", md)

    def test_sensitive_content_flags_high_risk(self):
        r = self._run(RISK)
        names = {h["name"]: h for h in r["m10"]["hits"]}
        self.assertIn("私域导流/联系方式", names)
        self.assertIn("收益/投资承诺", names)
        self.assertIn("医疗健康断言", names)
        self.assertEqual(names["私域导流/联系方式"]["level"], "高")
        self.assertGreaterEqual(r["m10"]["high"], 3)

    def test_high_risk_sorts_first(self):
        r = self._run(RISK)
        levels = [h["level"] for h in r["m10"]["hits"]]
        self.assertEqual(levels, sorted(levels, key=lambda x: ca.LEVEL_ORDER[x]))

    def test_short_content_hint(self):
        r = self._run("今天天气不错。")
        self.assertTrue(any(f["id"] == "ST-06" for f in r["structure"]))

    def test_unsegmented_long_text_flagged(self):
        r = self._run("这是一句没有分段的话。" * 60)          # 约 660 字单段
        ids = [f["id"] for f in r["structure"]]
        self.assertIn("ST-01", ids)

    def test_emoji_and_mixed_language_not_crashing(self):
        r = self._run(GOOD + "\n\n🎉 emoji test 🚀 mixed 中英 text.\n")
        self.assertGreaterEqual(r["overview"]["emoji"], 2)


class TestRulesSlot(unittest.TestCase):
    """规则插槽：换规则文件必须改变结论，且不需要改代码"""

    def test_custom_rules_override_default(self):
        custom = json.loads(json.dumps(RULES))
        custom["m4"]["hook"] = [{"id": "H9", "label": "自定义钩子", "pattern": "宇宙无敌", "weight": 30, "hint": "测试用"}]
        custom["m10"]["rules"] = [{"id": "R-99", "name": "自定义风险词", "level": "高",
                                   "pattern": "内部口令", "advice": "删除", "basis": "M10_合规与风险/README.md"}]
        custom["version"] = "test-custom"
        r = ca.analyze("宇宙无敌的写法。内部口令已泄露。", rules=custom, rules_source="content_rules.json", is_example=False)
        self.assertTrue(any(h["label"] == "自定义钩子" for h in r["m4"]["components"]["hook"]["hits"]))
        self.assertEqual(r["m10"]["hits"][0]["name"], "自定义风险词")
        self.assertEqual(r["rules_source"]["version"], "test-custom")
        md = ca.render_md(r)
        self.assertNotIn("当前使用的是**示例规则**", md)

    def test_missing_custom_path_falls_back(self):
        rules, src, is_ex = ca.load_rules(os.path.join(ROOT, "scripts", "rules", "不存在的规则.json"))
        self.assertTrue(os.path.isfile(src))
        self.assertTrue(is_ex, "指定路径不存在时应回退到示例规则并标记 is_example")
        self.assertIn("content_rules", os.path.basename(src))

    def test_default_rules_file_is_valid_json(self):
        with open(ca.DEFAULT_RULES, encoding="utf-8") as f:
            rules = json.load(f)
        for comp in ("hook", "emotion", "punch", "anchor"):
            self.assertTrue(rules["m4"][comp], "词表 %s 不能为空" % comp)
            for feat in rules["m4"][comp]:
                for key in ("id", "label", "pattern", "weight"):
                    self.assertIn(key, feat)
        for r in rules["m10"]["rules"]:
            for key in ("id", "name", "level", "pattern", "advice"):
                self.assertIn(key, r)
            self.assertIn(r["level"], ("高", "中", "低"))

    def test_example_rules_are_generic_not_internal(self):
        """公开库规则文件不得出现内部术语/本机路径（红线自检，防误提交）
        线索按碎片拼接，避免测试文件自身触发红线扫描"""
        with open(ca.DEFAULT_RULES, encoding="utf-8") as f:
            blob = f.read()
        probes = ["C:" + "\\Us" + "ers", "research" + "_work" + "space", "." + "work" + "buddy",
                  "跨" + "日交" + "接", "九" + "星"]
        for bad in probes:
            self.assertNotIn(bad, blob)


class TestCli(unittest.TestCase):
    def _cli(self, args, stdin=None):
        py = sys.executable
        p = subprocess.run([py, os.path.join(ROOT, "scripts", "content_analyze.py")] + args,
                           input=stdin, capture_output=True, text=True, encoding="utf-8",
                           cwd=ROOT, timeout=120)
        return p.returncode, (p.stdout or "") + (p.stderr or "")

    def test_text_argument(self):
        rc, out = self._cli(["--text", GOOD])
        self.assertEqual(rc, 0)
        self.assertIn("M4 爆款要素体检", out)

    def test_blank_returns_one_with_friendly_message(self):
        rc, out = self._cli(["--text", "   "])
        self.assertEqual(rc, 1)
        self.assertIn("内容为空", out)
        self.assertNotIn("Traceback", out)

    def test_missing_file_returns_one(self):
        rc, out = self._cli(["--file", os.path.join(ROOT, "data", "不存在.txt")])
        self.assertEqual(rc, 1)
        self.assertIn("读不了文件", out)
        self.assertNotIn("Traceback", out)

    def test_stdin_and_json_out(self):
        with tempfile.TemporaryDirectory() as d:
            jp = os.path.join(d, "an.json")
            rc, out = self._cli(["--stdin", "--json", jp], stdin=GOOD)
            self.assertEqual(rc, 0)
            with open(jp, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["schema"], "kanshan.content_analysis/1")
            self.assertIsNotNone(data["score"])

    def test_requires_one_source(self):
        rc, out = self._cli([])
        self.assertNotEqual(rc, 0)     # argparse 互斥且必填


if __name__ == "__main__":
    unittest.main(verbosity=2)
