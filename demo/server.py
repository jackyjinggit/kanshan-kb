#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 本地演示网关（stdlib only，离线可跑）

两条入口，对应现场演示的两个场景：
  ① 账号诊断：/api/diagnose  —— 合成演示账号 → 七节诊断报告 + 处方单（信号→模块→动作→依据）
  ② 贴入式分析：/api/analyze  —— **不需要任何账号授权**，贴一段内容就能出分析

安全与边界（重要）：
  - 只绑定 127.0.0.1（本机），不对外暴露；不读任何凭证文件、不访问网络。
  - 不接受客户端传文件路径（无任意文件读取面）；只按「演示账号类型」在内存在造数据。
  - 请求体上限 4MB，超限直接拒绝；所有返回均为 UTF-8 JSON。
  - 数据全部是**合成演示数据**，不是任何真实账号数据；报告内已标注。

用法：
    python demo/server.py            # 默认 http://127.0.0.1:8699
    python demo/server.py --port 9000 --no-browser
"""
import argparse
import json
import os
import random
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import content_analyze as ca        # noqa: E402
import demo_synth as ds             # noqa: E402
import prescribe as pr              # noqa: E402
import signals as sg                # noqa: E402
import zhihu_diagnose as zd         # noqa: E402

MAX_BODY = 4 * 1024 * 1024
MAX_TEXT = 200000
INDEX = os.path.join(HERE, "index.html")

ARCHETYPES = {
    "polluted": {"label": "被历史爆款污染的老号", "desc": "数据里有早年爆款，全量均值会被拉高——正好演示「同期对照」为什么必要"},
    "newbie": {"label": "新手号（样本少）", "desc": "近期样本不足，规则会走「样本不足」分支而不是硬编结论"},
    "vertical": {"label": "垂类深耕号", "desc": "单题材高集中，产能与效率基本对齐"},
    "omnivore": {"label": "多题材杂食号", "desc": "产能分散，账号标签难以成形"},
}

SEVERITY_HINT = {"高": "先做这个", "中": "本周内做", "低": "保持/不必花时间"}


def build_diagnosis(user, archetype, days, n):
    """合成演示数据 → 七节诊断 + 信号 + 处方（全内存，不落盘、不碰真实数据）"""
    rng = random.Random(ds.seed_of(user))
    items = ds.gen(user, archetype, n, rng)
    items, _ = sg.attach_dt(items)
    md = zd.build_report(items, days=days, user=user,
                         src_label="合成演示数据（脚本生成，非任何真实账号数据）")
    sig = sg.extract(items, days=days, user=user)
    rxs = pr.prescribe(sig)
    return {
        "schema": "kanshan.demo_diagnosis/1",
        "meta": {
            "user": user, "archetype": archetype,
            "archetype_label": ARCHETYPES.get(archetype, {}).get("label", archetype),
            "days": days, "n_records": len(items),
            "data_kind": "合成演示数据（非真实账号数据）",
            "time_anchor": sig["span_last"],
        },
        "report_md": md,
        "signals": sig,
        "prescriptions": rxs,
        "summary": pr.summarize(sig, rxs),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "KanshanDemo/0.1"

    # ---- 基础工具 ----
    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "Content-Length 不合法"
        if n > MAX_BODY:
            return None, "请求体过大（>%d MB）" % (MAX_BODY // 1024 // 1024)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8", errors="replace") or "{}"), None
        except json.JSONDecodeError as e:
            return None, "不是合法 JSON：%s" % e

    def log_message(self, fmt, *args):      # 精简日志
        sys.stderr.write("[demo] %s - %s\n" % (self.address_string(), fmt % args))

    # ---- 路由 ----
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            if not os.path.isfile(INDEX):
                return self._send(500, {"ok": False, "error": "缺少 index.html"})
            with open(INDEX, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/health":
            return self._send(200, {"ok": True})
        if path == "/api/status":
            _rules, src, is_ex = ca.load_rules()
            return self._send(200, {
                "ok": True,
                "offline": True,
                "python": sys.version.split()[0],
                "engines": {
                    "diagnose": "七节诊断报告（同期对照）",
                    "signals": sg.SCHEMA,
                    "prescribe": "处方引擎，%d 条规则族（每条都出结论）" % len(pr.RULES),
                    "analyze": "贴入式内容分析（无需账号授权）",
                },
                "prescription_rules": len(pr.RULES),
                "rules_slot": {
                    "source": os.path.basename(src),
                    "is_example": is_ex,
                    "note": "规则由设计组填；把文件放到 scripts/rules/content_rules.json 即自动接管，无需改代码",
                },
                "archetypes": ARCHETYPES,
                "severity_hint": SEVERITY_HINT,
                "disclaimer": "演示数据为脚本合成的示例数据，不代表任何真实账号；平台不提供的指标（粉丝数/曝光量/小时级点击率）本工具不推断",
            })
        return self._send(404, {"ok": False, "error": "未知路径 %s" % path})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        data, err = self._read_json()
        if err:
            return self._send(400, {"ok": False, "error": err})

        if path == "/api/diagnose":
            arche = str(data.get("archetype") or "polluted")
            if arche not in ARCHETYPES:
                return self._send(400, {"ok": False, "error": "未知账号类型：%s" % arche})
            user = (str(data.get("user") or "").strip() or "演示账号")[:32]
            try:
                days = max(7, min(365, int(data.get("days") or 30)))
            except (TypeError, ValueError):
                days = 30
            try:
                n = max(20, min(400, int(data.get("n") or ds.ARCH_DEFAULTS.get(arche, 240))))
            except (TypeError, ValueError):
                n = ds.ARCH_DEFAULTS.get(arche, 240)
            try:
                return self._send(200, dict(build_diagnosis(user, arche, days, n), ok=True))
            except Exception as e:                      # 演示不裸崩：错误也要是可读的
                return self._send(500, {"ok": False, "error": "诊断失败：%s" % e})

        if path == "/api/analyze":
            text = data.get("text") or ""
            if not isinstance(text, str):
                return self._send(400, {"ok": False, "error": "text 必须是字符串"})
            if len(text) > MAX_TEXT:
                return self._send(400, {"ok": False,
                                        "error": "正文过长（%d 字 > %d 字上限）" % (len(text), MAX_TEXT)})
            title = (str(data.get("title") or "").strip() or "")[:80]
            try:
                rules, src, is_ex = ca.load_rules()
                r = ca.analyze(text, title=title, rules=rules, rules_source=src, is_example=is_ex)
            except ValueError as e:
                return self._send(400, {"ok": False, "error": str(e),
                                        "hint": "贴入 ≥30 字的正文文本；纯空白/纯链接无法分析"})
            except Exception as e:
                return self._send(500, {"ok": False, "error": "分析失败：%s" % e})
            r["ok"] = True
            r["markdown"] = ca.render_md(r)
            return self._send(200, r)

        return self._send(404, {"ok": False, "error": "未知接口 %s" % path})


def main():
    ap = argparse.ArgumentParser(description="看山 · 本地演示网关")
    ap.add_argument("--host", default="127.0.0.1", help="只能绑本机（默认 127.0.0.1）")
    ap.add_argument("--port", type=int, default=8699)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.host not in ("127.0.0.1", "localhost"):
        print("[!] 演示网关只允许绑定本机地址（收到 %s）——防止把本地服务暴露到网络上" % a.host)
        return 2

    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("=" * 62)
    print(" 看山 · 本地演示网关已启动（离线，不访问网络）")
    print(" 地址: %s" % url)
    print(" 停止: Ctrl+C")
    print(" 说明: ①账号诊断（合成演示数据） ②贴入式分析（无需账号授权）")
    print("=" * 62)
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[+] 演示网关已停止")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
