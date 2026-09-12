#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地演示网关 · 接口测试（stdlib unittest）

真起一个 demo/server.py 子进程，用 UTF-8 请求打全部接口——不依赖浏览器、不联网。

    python -m unittest discover -s tests -t .
    python tests/test_demo_server.py

注：用 PowerShell 的 Invoke-RestMethod 手工验证中文入参会被 PS 5.1 的 body 编码弄坏
（中文变问号 → 种子相同 → 两个账号数据看起来一样）。浏览器与下面的测试客户端都发 UTF-8，不受影响。
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "demo", "server.py")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def call(port, path, payload=None, timeout=60):
    url = "http://127.0.0.1:%d%s" % (port, path)
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


class TestDemoServer(unittest.TestCase):
    proc = None
    port = None

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, SERVER, "--port", str(cls.port), "--no-browser"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                st, _ = call(cls.port, "/api/health", timeout=3)
                if st == 200:
                    return
            except Exception:
                time.sleep(0.3)
            if cls.proc.poll() is not None:
                out = cls.proc.stdout.read().decode("utf-8", "replace")
                raise AssertionError("演示网关未起来，退出码 %s：\n%s" % (cls.proc.returncode, out))
        raise AssertionError("演示网关 30 秒内未就绪")

    @classmethod
    def tearDownClass(cls):
        if cls.proc and cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    # ---- 页面 ----
    def test_root_serves_v2_shell(self):
        st, body = call(self.port, "/")
        self.assertEqual(st, 200)
        self.assertIn('class="screen"', body, "根路由应默认返回 v2 三屏壳")
        self.assertIn("visitor-oauth-btn", body, "v2 壳应含现场访客 OAuth 自测入口")

    def test_index_served_with_two_entries(self):
        st, body = call(self.port, "/classic")
        self.assertEqual(st, 200)
        self.assertIn("账号诊断", body)
        self.assertIn("贴入式内容分析", body)
        self.assertIn("/api/analyze", body)
        for bad in ("http://cdn", "https://cdn", "unpkg", "jsdelivr"):
            self.assertNotIn(bad, body, "演示页必须离线自包含，不得引用外部 CDN")

    def test_index_escapes_user_content(self):
        st, body = call(self.port, "/classic")
        self.assertIn("function esc(", body, "贴入内容必须经转义后再进 DOM")

    # ---- 状态 ----
    def test_status(self):
        st, body = call(self.port, "/api/status")
        self.assertEqual(st, 200)
        s = json.loads(body)
        self.assertTrue(s["ok"] and s["offline"])
        self.assertGreaterEqual(s["prescription_rules"], 10)
        # 账号清单 = 4 个合成对照 + 本机 data/real/ 里的真实账号（本机有真数据时才有，别的机器上本来就没有）
        synth = [k for k, v in s["archetypes"].items() if v.get("kind") == "synth"]
        real = [k for k, v in s["archetypes"].items() if v.get("kind") == "real"]
        self.assertEqual(sorted(synth), sorted(["polluted", "newbie", "vertical", "omnivore"]))
        self.assertTrue(all(s["archetypes"][k]["label"].startswith("合成·") for k in synth),
                        "合成对照必须带「合成·」前缀，不能和真实账号混在一起分不清")
        ds = s["data_source"]
        if ds["mode"] == "real":
            self.assertTrue(real, "真实模式下账号清单里必须有真实账号项")
            self.assertEqual(real, [a["id"] for a in ds["accounts"]], "清单键必须逐个对上一个账号")
            self.assertEqual(ds["default"], ds["accounts"][0]["id"], "默认账号 = 清单第一个")
        else:
            self.assertFalse(real, "合成模式下不该有真实账号项")
        self.assertIn("rules_slot", s)
        self.assertIn(s["rules_slot"]["source"], ("content_rules.json", "content_rules.local.json",
                                                 "content_rules.default.json"))

    # ---- 入口一：账号诊断 ----
    def test_diagnose_full_chain(self):
        st, body = call(self.port, "/api/diagnose",
                        {"user": "演示账号甲", "archetype": "polluted", "days": 30})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertTrue(d["ok"])
        self.assertEqual(d["meta"]["user"], "演示账号甲", "中文用户名必须原样回传（UTF-8 往返）")
        self.assertEqual(d["meta"]["data_kind"], "合成演示数据（非真实账号数据）")
        self.assertIn("数据锚点", "数据锚点%s" % d["meta"]["time_anchor"])
        self.assertEqual(len(d["prescriptions"]), 15)
        self.assertIn("## 一、", d["report_md"])
        self.assertIn("## 七、", d["report_md"])
        for r in d["prescriptions"]:
            self.assertTrue(r["signal"] and r["module"] and r["actions"] and r["basis"] and r["falsify"],
                            "处方缺字段：%s" % r.get("id"))
            self.assertTrue(r["title"], "处方必须有诊断项标题：%s" % r.get("id"))

    def test_diagnose_different_users_differ(self):
        """不同用户名 → 不同数据（防的是种子串味的静默错误）"""
        a = json.loads(call(self.port, "/api/diagnose", {"user": "甲甲甲", "archetype": "polluted"})[1])
        b = json.loads(call(self.port, "/api/diagnose", {"user": "乙乙乙", "archetype": "polluted"})[1])
        self.assertEqual(a["meta"]["user"], "甲甲甲")
        self.assertEqual(b["meta"]["user"], "乙乙乙")
        self.assertNotEqual(a["signals"]["baseline"]["interact_mean"],
                            b["signals"]["baseline"]["interact_mean"])

    def test_diagnose_reproducible(self):
        p = {"user": "复现账号", "archetype": "omnivore", "days": 60}
        a = json.loads(call(self.port, "/api/diagnose", p)[1])
        b = json.loads(call(self.port, "/api/diagnose", p)[1])
        self.assertEqual(a["signals"], b["signals"])
        self.assertEqual([r["id"] for r in a["prescriptions"]], [r["id"] for r in b["prescriptions"]])

    def test_diagnose_rejects_bad_archetype(self):
        st, body = call(self.port, "/api/diagnose", {"user": "x", "archetype": "../../etc/passwd"})
        self.assertEqual(st, 400)
        self.assertIn("未知账号类型", json.loads(body)["error"])

    def test_diagnose_clamps_extreme_params(self):
        st, body = call(self.port, "/api/diagnose",
                        {"user": "边界账号", "archetype": "newbie", "days": 99999, "n": -5})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertLessEqual(d["meta"]["days"], 365)
        self.assertGreaterEqual(d["meta"]["n_records"], 20)

    # ---- 入口二：贴入式分析 ----
    def test_analyze_happy(self):
        good = ("为什么你收藏了 300 篇干货，一篇也没用上？\n\n先说结论：收藏不是学习。\n\n"
                "我去年也这样：收藏夹 300 多篇，真正复用的不到 5 篇。\n\n"
                "三步法：第一步先问用途；第二步写一句我会用它做什么；第三步每周清一次收藏夹。\n\n"
                "这个方法的边界要说清楚：对工具型内容有效。\n\n你最近一次真正用掉收藏，是哪一篇？")
        st, body = call(self.port, "/api/analyze", {"title": "收藏夹复用", "text": good})
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertIsNotNone(d["score"])
        self.assertTrue(d["m4"]["components"])
        self.assertIn("markdown", d)
        self.assertIn("校验规则插槽", d["markdown"])

    def test_analyze_blank_is_friendly(self):
        st, body = call(self.port, "/api/analyze", {"text": "   \n  "})
        self.assertEqual(st, 400)
        self.assertIn("内容为空", json.loads(body)["error"])

    def test_analyze_too_long(self):
        st, body = call(self.port, "/api/analyze", {"text": "长" * 200001})
        self.assertEqual(st, 400)
        self.assertIn("过长", json.loads(body)["error"])

    def test_analyze_script_injection_not_executed(self):
        st, body = call(self.port, "/api/analyze",
                        {"text": "<script>alert(1)</script> 正文一段话，用来验证转义。"})
        self.assertEqual(st, 200)
        d = json.loads(body)          # 原样返回也必须仍是合法 JSON（不破结构）
        self.assertIsNotNone(d["score"])
        # 关键防线在页面侧：所有贴入内容先 esc() 再进 DOM（见 test_index_escapes_user_content）

    def test_analyze_without_account_authorization(self):
        """贴入式入口不得要求任何凭证/账号字段"""
        st, _ = call(self.port, "/api/analyze", {"text": "一段普通正文，不需要账号，也不需要授权。"})
        self.assertEqual(st, 200)

    # ---- 边界 ----
    def test_unknown_route_404(self):
        st, _ = call(self.port, "/api/nope")
        self.assertEqual(st, 404)
        st2, _ = call(self.port, "/api/nope", {})
        self.assertEqual(st2, 404)

    def test_bad_json_body(self):
        req = urllib.request.Request("http://127.0.0.1:%d/api/analyze" % self.port,
                                     data=b"{not json", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=10)
            self.fail("坏 JSON 应当被拒绝")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            self.assertIn("JSON", e.read().decode("utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
