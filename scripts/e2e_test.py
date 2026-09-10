#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 端到端验收测试：任意用户名都能完成任务（synth → diagnose → 处方 → 贴入式分析）

回答的问题：**是不是任意用户名都能走完 数据→诊断报告→处方 全流程，且贴入一段内容不靠账号授权也能出分析？**
覆盖：
  A 组（原 13 项，保持不动）：中英/emoji/超长/注入样式/空白/空串 × 4 原型 + 坏行降级 + 缺文件友好报错
      + 同名复现性 + 真实样本回归（`--real`）
  B 组（新增）：处方引擎链路完整性 + 贴入式分析（好稿/风险稿/纯链接/纯空白）+ 贴入边界（超长/注入）
      + 校验规则插槽（换规则文件即生效，证明规则没写死在代码里）+ 本地演示网关接口 + 单元测试套件

用法：python scripts/e2e_test.py [--real <contents.jsonl 路径>]
退出码：0 = 全部通过；1 = 有失败项
"""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
WORK = os.path.join(ROOT, "data", "e2e")

# (用户名, 原型) 矩阵：4 原型都覆盖 + 各种奇怪用户名
CASES = [
    ("judge_demo", "polluted"),
    ("测试用户甲", "polluted"),
    ("🔥山友", "vertical"),
    ("a" * 64, "omnivore"),
    ("'; DROP TABLE users;--", "polluted"),
    ("  ", "newbie"),
    ("", "omnivore"),
    ("正常用户-2026", "vertical"),
    ("<script>alert(1)</script>", "newbie"),
]

# 真实样本回归（可选：--real <contents.jsonl 路径>，不写死任何机器路径）
REAL = None


def run(args):
    p = subprocess.run([PY] + args, capture_output=True, cwd=ROOT)
    return p.returncode, (p.stdout + p.stderr).decode("utf-8", errors="replace")


def sections(md_path):
    with open(md_path, encoding="utf-8") as f:
        body = f.read()
    n = sum(1 for i in range(1, 8) if "## %s、" % "一二三四五六七八九"[i - 1] in body)
    return n, body


# ---------------------------------------------------------------- B 组检查
def check_prescribe(work, run):
    """处方引擎：每个原型都出 ≥10 条，且每条链路完整、依据文件真实存在、无规则异常"""
    bad, total, exc = [], None, 0
    for arch in ("polluted", "newbie", "vertical", "omnivore"):
        src = os.path.join(work, "src_rx_%s.jsonl" % arch)
        out = os.path.join(work, "rx_%s" % arch)
        run([os.path.join(HERE, "demo_synth.py"), "--user", "处方验收", "--archetype", arch, "--out", src])
        rc, o = run([os.path.join(HERE, "prescribe.py"), "--in", src, "--out", out, "--json",
                     os.path.join(out, "prescribe.json")])
        jp = os.path.join(out, "prescribe.json")
        if rc != 0 or not os.path.exists(jp):
            bad.append("%s rc=%d" % (arch, rc))
            continue
        with open(jp, encoding="utf-8") as f:
            data = json.load(f)
        rxs = data["prescriptions"]
        total = len(rxs) if total is None else total
        if len(rxs) < 10:
            bad.append("%s 仅 %d 条" % (arch, len(rxs)))
        for r in rxs:
            if not (r.get("signal") and r.get("module") and r.get("actions") and r.get("basis")):
                bad.append("%s %s 缺字段" % (arch, r.get("id")))
            if "规则执行异常" in r.get("signal", ""):
                exc += 1
            basis = os.path.join(ROOT, r.get("basis", ""))
            if not os.path.exists(basis):
                bad.append("%s %s 依据文件不存在：%s" % (arch, r.get("id"), r.get("basis")))
    note = "原型4 × 每条 %s 条处方 · 异常 %d · %s" % (total, exc, "无缺项" if not bad else "；".join(bad[:3]))
    return ("处方引擎链路（4 原型 ≥10 条/完整链路）", not bad and not exc and (total or 0) >= 10, note)


GOOD_PASTE = """为什么你收藏了 300 篇干货，一篇也没用上？

先说结论：收藏不是学习，收藏只是把焦虑存了个盘。

我去年也这样：收藏夹 300 多篇，真正复用的不到 5 篇。数据来自我自己的导出记录：
- 当天处理的，复用率 41%
- 3 天后处理的，复用率 6%

所以我用一个三步法替代了「先收藏再说」：第一步，立刻问这条能用在哪个正在进行的事情上；
第二步，当场写一句「我会用它做什么」；第三步，每周清一次收藏夹。

这个方法的边界要说清楚：它对工具型内容有效，对观点型内容不太适用。

你最近一次把收藏的内容真正用掉，是哪一篇？
"""

RISK_PASTE = ("全网最好的理财方法，100% 稳赚，我保证你月入过万。加微信 zhuanqian888 拉你进群。"
              "这个方子能彻底根治失眠，药到病除。有问题打 13812345678。详见 https://example.com/post 。")


def check_paste_in(work, run):
    """贴入式分析：不需要账号授权，贴一段内容就能出分析；坏输入优雅降级"""
    out = []
    an = os.path.join(HERE, "content_analyze.py")

    def one(text, *extra):
        return run([an, "--text", text] + list(extra))

    # 好稿：能评分，且四要素与结构/合规诊断齐备
    rc, o = one(GOOD_PASTE, "--json", os.path.join(work, "an_good.json"))
    try:
        with open(os.path.join(work, "an_good.json"), encoding="utf-8") as f:
            d = json.load(f)
        comps = d["m4"]["components"]
        ok = (rc == 0 and d["score"] and d["score"] >= 55 and len(comps) == 4
              and d["structure"] and "self_check" in d["m10"] and "失效条件" in o)
        out.append(("贴入式分析·好稿可评分", ok, "rc=%d 得分=%s（%s）要素=%d 结构项=%d"
                    % (rc, d["score"], d["grade"], len(comps), len(d["structure"]))))
    except Exception as e:
        out.append(("贴入式分析·好稿可评分", False, "读不到结果：%s" % e))

    # 风险稿：命中高危合规项
    rc, o = one(RISK_PASTE, "--json", os.path.join(work, "an_risk.json"))
    try:
        with open(os.path.join(work, "an_risk.json"), encoding="utf-8") as f:
            d = json.load(f)
        ok = rc == 0 and d["m10"]["high"] >= 2
        out.append(("贴入式分析·风险稿命中高危险", ok, "rc=%d 高危=%d 条" % (rc, d["m10"]["high"])))
    except Exception as e:
        out.append(("贴入式分析·风险稿命中高危险", False, "读不到结果：%s" % e))

    # 纯链接：不可评分（而不是 0 分），并显式给出原因
    rc, o = one("https://zhuanlan.zhihu.com/p/123456789")
    out.append(("贴入式分析·纯链接不可评分", rc == 0 and "不可评分" in o and "ST-09" in o,
                "rc=%d 不可评分=%s" % (rc, "不可评分" in o)))

    # 纯空白：rc=1 + 友好提示（不裸崩）
    rc, o = one("   \n\t  ")
    out.append(("贴入式分析·纯空白友好报错", rc == 1 and "内容为空" in o and "Traceback" not in o,
                "rc=%d 无裸栈=%s" % (rc, "Traceback" not in o)))

    # 超长（6 万字）：截断分析 + 显式标注
    # 注意：不能把 6 万字塞进命令行参数（Windows 命令行上限 32k），必须走 --file
    long_txt = os.path.join(work, "paste_long.txt")
    with open(long_txt, "w", encoding="utf-8") as f:
        f.write("这是一段用于超长测试的正文内容。" * 4000)
    rc, o = run([an, "--file", long_txt])
    out.append(("贴入式分析·超长文本截断标注", rc == 0 and "仅分析前" in o,
                "rc=%d 有截断标注=%s" % (rc, "仅分析前" in o)))

    # HTML/脚本注入：不崩，仍出结论
    rc, o = one("<script>alert(1)</script><img src=x onerror=alert(2)>\n" + GOOD_PASTE)
    out.append(("贴入式分析·注入内容不崩", rc == 0 and "M4" in o,
                "rc=%d 仍出结论=%s" % (rc, "M4" in o)))
    return out


def check_rules_slot(work, run):
    """校验规则插槽：换规则文件即生效 → 证明规则没写死在代码里（设计组可直接接管）"""
    rp = os.path.join(work, "rules_test.json")
    with open(os.path.join(HERE, "rules", "content_rules.default.json"), encoding="utf-8") as f:
        rules = json.load(f)
    rules["version"] = "e2e-probe"
    rules["m4"]["hook"] = [{"id": "H-T", "label": "验收探针钩子", "pattern": "验收探针关键词",
                            "weight": 30, "hint": "e2e 专用"}]
    rules["m10"]["rules"] = [{"id": "R-T", "name": "验收探针风险词", "level": "高",
                              "pattern": "验收探针风险词", "advice": "删掉",
                              "basis": "M10_合规与风险/README.md"}]
    with open(rp, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)
    rc, o = run([os.path.join(HERE, "content_analyze.py"), "--rules", rp,
                 "--text", "验收探针关键词开头的一段正文，用来验证规则插槽。验收探针风险词在这里。"])
    ok = rc == 0 and "验收探针钩子" in o and "验收探针风险词" in o and "e2e-probe" in o
    return ("校验规则插槽（换规则文件即生效）", ok, "rc=%d 自定义命中=%s" % (rc, ok))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def check_demo_server():
    """本地演示网关：真起进程打三个接口（中文入参走 UTF-8，与浏览器一致）"""
    port = _free_port()
    proc = subprocess.Popen([PY, os.path.join(ROOT, "demo", "server.py"),
                             "--port", str(port), "--no-browser"],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT)
    base = "http://127.0.0.1:%d" % port

    def call(path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(base + path, data=data,
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    try:
        for _ in range(40):
            try:
                if call("/api/health")[0] == 200:
                    break
            except Exception:
                time.sleep(0.25)
        else:
            return ("本地演示网关（页面+两接口）", False, "30 秒内未就绪")

        st_page, body = urllib.request.urlopen(base + "/", timeout=10).status, urllib.request.urlopen(base + "/", timeout=10).read()
        st1, s = call("/api/status")
        st2, d = call("/api/diagnose", {"user": "验收账号甲", "archetype": "polluted", "days": 30})
        st3, a = call("/api/analyze", {"text": GOOD_PASTE})
        ok = (st_page == 200 and b"\xe8\xb4\xa6\xe5\x8f\xb7\xe8\xaf\x8a\xe6\x96\xad" in body  # 「账号诊断」UTF-8
              and s["ok"] and s["offline"]
              and len(d["prescriptions"]) >= 10 and d["meta"]["user"] == "验收账号甲"
              and a.get("score") is not None)
        return ("本地演示网关（页面+两接口）", ok,
                "页面=%s 诊断处方=%d 条 贴入得分=%s 中文往返=%s"
                % (st_page, len(d["prescriptions"]), a.get("score"), d["meta"]["user"] == "验收账号甲"))
    except Exception as e:
        return ("本地演示网关（页面+两接口）", False, "异常：%s" % str(e)[:90])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_unit_suite(run):
    """单元/边界测试套件全绿"""
    rc, o = run(["-m", "unittest", "discover", "-s", "tests", "-t", "."])
    tail = [l for l in o.splitlines() if l.startswith("Ran ") or l.strip() == "OK"]
    return ("单元/边界测试套件", rc == 0 and "OK" in o, "rc=%d %s" % (rc, " / ".join(tail)))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", default=None, help="可选：真实 contents.jsonl 路径，跑回归")
    REAL = ap.parse_args().real
    os.makedirs(WORK, exist_ok=True)
    results = []

    def record(name, ok, note):
        results.append((name, ok, note))
        print("%s %-28s %s" % ("✅" if ok else "❌", name, note))

    # 1) 用户名 × 原型矩阵
    for i, (user, arch) in enumerate(CASES):
        name = "用户%02d %r/%s" % (i, user[:12], arch)
        src = os.path.join(WORK, "src_%02d.jsonl" % i)
        outdir = os.path.join(WORK, "diag_%02d" % i)
        rc1, o1 = run([os.path.join(HERE, "demo_synth.py"), "--user", user,
                       "--archetype", arch, "--out", src])
        rc2, o2 = run([os.path.join(HERE, "zhihu_diagnose.py"), "--in", src,
                       "--out", outdir, "--user", user])
        md = os.path.join(outdir, "diagnose.md")
        if rc1 != 0 or rc2 != 0 or not os.path.exists(md):
            record(name, False, "synth rc=%d diagnose rc=%d" % (rc1, rc2))
            continue
        n, body = sections(md)
        expect = user.strip() or "匿名用户"
        head_ok = ("用户：%s" % expect) in body
        record(name, n == 7 and head_ok, "7节=%d 报告头含用户名=%s" % (n, head_ok))

    # 2) 坏行降级（压力预案③）
    src = os.path.join(WORK, "src_corrupt.jsonl")
    run([os.path.join(HERE, "demo_synth.py"), "--user", "脏数据测试", "--corrupt", "7", "--out", src])
    rc, o = run([os.path.join(HERE, "zhihu_diagnose.py"), "--in", src,
                 "--out", os.path.join(WORK, "diag_corrupt")])
    record("坏行降级(7行损坏)", rc == 0 and "已跳过" in o, "rc=%d 降级提示=%s" % (rc, "已跳过" in o))

    # 3) 缺文件友好报错（不裸崩）
    rc, o = run([os.path.join(HERE, "zhihu_diagnose.py"), "--in",
                 os.path.join(WORK, "不存在.jsonl"), "--out", os.path.join(WORK, "diag_none")])
    record("缺文件友好报错", rc == 1 and "读不了数据文件" in o and "Traceback" not in o,
           "rc=%d 无裸栈=%s" % (rc, "Traceback" not in o))

    # 4) 同用户名复现性（同 seed 同输出）
    a1, a2 = os.path.join(WORK, "rep1.jsonl"), os.path.join(WORK, "rep2.jsonl")
    run([os.path.join(HERE, "demo_synth.py"), "--user", "复现测试", "--out", a1])
    run([os.path.join(HERE, "demo_synth.py"), "--user", "复现测试", "--out", a2])
    h1 = hashlib.md5(open(a1, "rb").read()).hexdigest()
    h2 = hashlib.md5(open(a2, "rb").read()).hexdigest()
    record("同名复现性", h1 == h2, "md5一致=%s" % (h1 == h2))

    # 5) 真实样本回归（48 条实测 JSONL）
    if REAL and os.path.exists(REAL):
        rc, o = run([os.path.join(HERE, "zhihu_diagnose.py"), "--in", REAL,
                     "--out", os.path.join(WORK, "diag_real")])
        record("真实样本回归", rc == 0, "rc=%d" % rc)
    else:
        record("真实样本回归", True, "（样本不存在，跳过）")

    # ---------------- B 组：处方引擎 / 贴入式分析 / 演示网关 / 单元套件 ----------------
    record(*check_prescribe(WORK, run))

    for name, ok, note in check_paste_in(WORK, run):
        record(name, ok, note)

    record(*check_rules_slot(WORK, run))
    record(*check_demo_server())
    record(*check_unit_suite(run))

    ok_n = sum(1 for _, v, _ in results if v)
    print("\n== 验收汇总：%d/%d 通过 ==" % (ok_n, len(results)))
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
