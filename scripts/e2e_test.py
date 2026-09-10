#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 端到端验收测试：任意用户名都能完成任务（synth → diagnose 全链）

回答的问题：**是不是任意用户名都能走完 数据→诊断报告 全流程？**
覆盖：中英/emoji/超长/注入样式/空白/空串 × 4 种原型 + 坏行降级 + 缺文件友好报错 + 同名复现性。

用法：python scripts/e2e_test.py
退出码：0 = 全部通过；1 = 有失败项
"""
import hashlib
import os
import subprocess
import sys

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
    n = sum(1 for i in range(1, 8) if "## %s、" % "一二三四五六七"[i - 1] in body)
    return n, body


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

    ok = sum(1 for _, v, _ in results if v)
    print("\n== 验收汇总：%d/%d 通过 ==" % (ok, len(results)))
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
