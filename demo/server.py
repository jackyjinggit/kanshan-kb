#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 本地演示网关（stdlib only，离线可跑）

两条入口，对应现场演示的两个场景：
  ① 账号诊断：/api/diagnose  —— 授权账号的真实数据（或合成对照）→ 七节诊断报告 + 处方单（信号→模块→动作→依据）
  ② 贴入式分析：/api/analyze  —— **不需要任何账号授权**，贴一段内容就能出分析

真实数据（多账号）：把 zhihu-cli 拉取的 contents_*.jsonl 放进 data/real/ 即自动全部加载，
一个文件 = 一个账号；默认选最近拉取的那份。**换账号 = 多一个文件**，不改代码、不重启。

安全与边界（重要）：
  - 只绑定 127.0.0.1（本机），不对外暴露；不读任何凭证文件、不访问网络。
  - 不接受客户端传文件路径（无任意文件读取面）；账号只能在本机启动时指定/发现。
  - 请求体上限 4MB，超限直接拒绝；所有返回均为 UTF-8 JSON。
  - 合成账号的数据是**脚本生成的演示数据**；真实账号只读本机 jsonl，不入库、不上传，报告里标注来源。

用法：
    python demo/server.py            # 默认 http://127.0.0.1:8699（data/real/ 有数据即真实模式）
    python demo/server.py --port 9000 --no-browser
    python demo/server.py --data data/real/contents_a_20260910.jsonl --data-user 甲 \
                          --data data/real/contents_b_20260910.jsonl --data-user 乙
"""
import argparse
import datetime
import json
import os
import random
import re
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


# ---- 真实数据模式：读本机 zhihu-cli 拉取的 contents.jsonl，只读、不入库、不联网 ----
# 「换账号」的工程形态：data/real/ 里再多一个 jsonl（各自授权、各自文件），页面账号清单自动多一项。
# 一次可并存多个账号；默认选中最近拉取的那份。
# ⚠️ zhihu-cli 不返回账号身份（auth status 只有掩码，capabilities 只有命令表）→ 账号名只能由人给
#    （--data-user，或文件名里的标签），否则只能显示兜底名「本人账号」。
REAL = {"accounts": []}
REAL_DIR = os.path.join(ROOT, "data", "real")


def _account_from_path(path, label=""):
    """一个真实账号 = 一份 jsonl。id 用文件名（唯一）。
    没给名字时**不拿文件名当人名用**，一律叫「本人账号」，文件名标签只作括号里的区分：
    contents_zhihu_20260910.jsonl → 「本人账号（zhihu）」；同页多账号时靠这个括号分得清。"""
    p = os.path.abspath(path)
    base = os.path.basename(p)
    stem = base[:-6] if base.endswith(".jsonl") else base
    if stem.startswith("contents_"):
        stem = stem[len("contents_"):]
    m = re.match(r"^(?P<name>.+?)_(?P<d>\d{8})$", stem)
    tag = (m.group("name") if m else stem).strip()
    derived = "本人账号（%s）" % tag if tag else "本人账号"
    return {"id": base, "path": p, "label": (label or derived)[:40],
            "cache": None, "mtime": 0.0, "bad": 0, "n": 0, "newest": ""}


def load_real(acct):
    """读一个账号的 contents.jsonl（逐行 JSON）。带 mtime 缓存：重新拉数后自动生效，不用重启。"""
    st = os.stat(acct["path"])
    if acct["cache"] is not None and acct["mtime"] == st.st_mtime:
        return acct["cache"]
    items, bad = [], 0
    with open(acct["path"], encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                it = json.loads(line)
            except json.JSONDecodeError:
                bad += 1                      # 坏行降级，不裸崩（与 zhihu_diagnose.load 同口径）
                continue
            if isinstance(it, dict) and int(it.get("CreatedAt") or 0) > 0:
                items.append(it)
    items, _ = sg.attach_dt(items)
    items.sort(key=lambda x: x.get("CreatedAt") or 0, reverse=True)
    newest = ""
    if items:
        newest = datetime.datetime.fromtimestamp(max(int(i["CreatedAt"]) for i in items)).strftime("%Y-%m-%d")
    acct.update({"cache": items, "mtime": st.st_mtime, "bad": bad, "n": len(items), "newest": newest})
    return items


def find_account(key):
    """按账号 id（文件名）或显示名取账号；'real'/空 = 默认账号。找不到返回 None。"""
    if not REAL["accounts"]:
        return None
    if not key or key == "real":
        return REAL["accounts"][0]
    for a in REAL["accounts"]:
        if key in (a["id"], a["label"]):
            return a
    return None


def real_source():
    """数据来源说明（给页面用）：合成 / 真实（可多账号并存）一眼可辨。"""
    if not REAL["accounts"]:
        return {"mode": "synth"}
    d = REAL["accounts"][0]                    # 默认账号 = 最近拉取的那份
    return {"mode": "real", "default": d["id"], "user": d["label"],
            "file": os.path.basename(d["path"]), "n": d["n"], "bad": d["bad"], "newest": d["newest"],
            "accounts": [{"id": a["id"], "label": a["label"], "file": os.path.basename(a["path"]),
                          "n": a["n"], "newest": a["newest"], "bad": a["bad"]} for a in REAL["accounts"]]}


def real_archetypes():
    """真实模式下的账号清单：每个已拉取的真实账号一项（默认第一个）；合成原型保留作「对照」，
    标签明确带「合成·」前缀——真实与合成混在一页里，必须一眼分得清。"""
    out = {}
    for i, a in enumerate(REAL["accounts"]):
        out[a["id"]] = {"label": "%s · %d 条%s" % (a["label"], a["n"], "（默认）" if i == 0 else ""),
                        "desc": "%s · 最新 %s · 与合成数据跑的是同一套引擎" % (os.path.basename(a["path"]), a["newest"]),
                        "kind": "real"}
    for k, v in ARCHETYPES.items():
        out[k] = {"label": "合成·" + v["label"],
                  "desc": "对照用：" + v["desc"] + "（脚本合成，不是真实账号）",
                  "kind": "synth"}
    return out


def build_diagnosis_real(days, acct):
    """某个真实账号 → 七节诊断 + 信号 + 处方（与合成路径同一个引擎，只有数据来源不同）"""
    items = load_real(acct)
    if not items:
        raise ValueError("真实数据文件里没有可用记录：%s" % acct["path"])
    label = "真实数据（zhihu-cli 拉取 · %s · %d 条 · %s）" % (os.path.basename(acct["path"]), len(items), acct["newest"])
    md = zd.build_report(items, days=days, user=acct["label"], src_label=label)
    sig = sg.extract(items, days=days, user=acct["label"])
    rxs = pr.prescribe(sig)
    return {
        "schema": "kanshan.demo_diagnosis/1",
        "meta": {
            "user": acct["label"], "archetype": acct["id"],
            "archetype_label": "%s（真实账号 · zhihu-cli 拉取）" % acct["label"],
            "days": days, "n_records": len(items),
            "data_kind": label,
            "time_anchor": sig["span_last"],
            "dropped_rows": acct["bad"],
        },
        "report_md": md,
        "signals": sig,
        "prescriptions": rxs,
        "summary": pr.summarize(sig, rxs),
    }


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
    def _cors(self):
        """只对 file:// 直开 / 沙箱预览（Origin: null）放行；
        其他站点（真实域名）一律不给 CORS 头 → 外站读不到本机数据。"""
        if self.headers.get("Origin") == "null":
            self.send_header("Access-Control-Allow-Origin", "null")
            self.send_header("Vary", "Origin")

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
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
    def do_OPTIONS(self):
        """预检：双击打开 index.html（Origin: null）时 POST JSON 会先发预检，这里放行。"""
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

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
                "archetypes": real_archetypes() if REAL["accounts"] else ARCHETYPES,
                "severity_hint": SEVERITY_HINT,
                "data_source": real_source(),
                "disclaimer": (
                    "当前为**真实数据模式**：本机已授权账号（%d 个）的 zhihu-cli 拉取数据，只在本地读取、不上传；"
                    "平台不提供的指标（粉丝/曝光/小时级点击率/完播）本工具不推断" % len(REAL["accounts"])
                    if REAL["accounts"] else
                    "演示数据为脚本合成的示例数据，不代表任何真实账号；平台不提供的指标（粉丝数/曝光量/小时级点击率）本工具不推断"),
            })
        return self._send(404, {"ok": False, "error": "未知路径 %s" % path})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        data, err = self._read_json()
        if err:
            return self._send(400, {"ok": False, "error": err})

        if path == "/api/diagnose":
            # 真实账号：archetype 传账号 id（或 "real" = 默认账号）→ 走真实数据；传合成原型 → 走合成对照
            if REAL["accounts"]:
                acct = find_account(str(data.get("archetype") or "real"))
                if acct is not None:
                    try:
                        rdays = max(7, min(365, int(data.get("days") or 30)))
                    except (TypeError, ValueError):
                        rdays = 30
                    try:
                        return self._send(200, dict(build_diagnosis_real(rdays, acct), ok=True))
                    except Exception as e:
                        return self._send(500, {"ok": False, "error": "真实数据诊断失败：%s" % e})
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
    ap.add_argument("--data", action="append", default=[], metavar="PATH",
                    help="真实数据：本机 contents.jsonl（可重复给，一个账号一份；zhihu-cli 拉取）")
    ap.add_argument("--data-dir", default="", metavar="DIR",
                    help="真实数据目录，默认扫 data/real/*.jsonl（每个文件 = 一个账号，自动全部加载）")
    ap.add_argument("--data-user", action="append", default=[], metavar="NAME|<文件名>=<显示名>",
                    help="账号显示名；多账号用 <文件名>=<显示名> 指名。不给我就按文件名标，再退到「本人账号」")
    a = ap.parse_args()

    labels, plains = {}, []
    for v in a.data_user:
        v = (v or "").strip()
        if not v:
            continue
        if "=" in v:
            k, _, nm = v.partition("=")
            labels[os.path.basename(k.strip())] = nm.strip()[:40]
        else:
            plains.append(v[:40])

    paths = [os.path.abspath(p) for p in a.data]
    explicit = bool(paths)                     # --data 的先后即用户意图，不重排；目录扫描才按「最近拉取」排
    if not paths:
        d = os.path.abspath(a.data_dir) if a.data_dir else REAL_DIR
        if os.path.isdir(d):
            paths = [os.path.abspath(os.path.join(d, f)) for f in sorted(os.listdir(d)) if f.endswith(".jsonl")]
    for p in paths:
        if not os.path.isfile(p):
            print("[!] 找不到数据文件：%s" % p)
            return 2
    # 只给名字不给文件名时按 --data 顺序一一对应；**目录扫描时不做位置配对**（免得把名字贴到错的账号上），
    # 目录扫描下只在只有一个文件时才接受一个名字。
    if plains and a.data:
        pos = plains[:len(paths)]
    elif plains and len(paths) == 1:
        pos = [plains[0]]
    else:
        pos = []
    for i, p in enumerate(paths):
        base = os.path.basename(p)
        given = labels.get(base, "") or (pos[i] if i < len(pos) else "")
        ac = _account_from_path(p, given)
        if not load_real(ac):                      # 顺带算出 n / newest
            print("[!] %s 里没有可用记录（每行需含 CreatedAt/LikeCount 等原始字段）——已跳过" % base)
            continue
        if not given:                              # 没给名字 → 试从记录里找 AuthorName，再退到文件名标签
            names = {}
            for it in ac["cache"][:200]:
                nm = (it.get("AuthorName") or "").strip()
                if nm:
                    names[nm] = names.get(nm, 0) + 1
            if names:
                ac["label"] = max(names, key=names.get)[:40]
        REAL["accounts"].append(ac)
    if not explicit:                           # 目录扫描：默认 = 最近拉取的那份（刚拉的号自动排第一）
        REAL["accounts"].sort(key=lambda x: os.stat(x["path"]).st_mtime, reverse=True)
    if a.host not in ("127.0.0.1", "localhost"):
        print("[!] 演示网关只允许绑定本机地址（收到 %s）——防止把本地服务暴露到网络上" % a.host)
        return 2

    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    url = "http://%s:%d/" % (a.host, a.port)
    print("=" * 62)
    print(" 看山 · 本地演示网关已启动（离线，不访问网络）")
    print(" 地址: %s" % url)
    print(" 停止: Ctrl+C")
    if REAL["accounts"]:
        print(" 数据: 真实数据模式 · %d 个账号（默认 = 最近拉取的那份）" % len(REAL["accounts"]))
        for i, x in enumerate(REAL["accounts"]):
            print("   %s%s · %d 条 · 最新 %s · %s"
                  % ("★ " if i == 0 else "   ", x["label"], x["n"], x["newest"], os.path.basename(x["path"])))
        print(" 说明: ①账号诊断（真实账号） ②贴入式分析（无需账号授权）")
        print(" 加账号: python scripts/zhihu_fetch.py --out data/real/contents_<账号标签>_<日期>.jsonl")
    else:
        print(" 说明: ①账号诊断（合成演示数据，演示/回归用） ②贴入式分析（无需账号授权）")
        print(" 换真数据: 把 zhihu-cli 拉取的文件放进 data/real/ 即自动加载（也可 --data <路径>）")
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
