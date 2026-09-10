#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 数据接入层：拉取知乎本人全量创作 → JSONL

用法：
    python scripts/zhihu_fetch.py [--out data/contents.jsonl] [--max-pages 40]

前置：已配置 Access Secret（zhihu-cli auth set --secret-stdin）
依赖：zhihu-cli（知乎开放平台 CLI）；纯本地，调用开放平台免费额度
"""
import argparse, json, os, subprocess, sys, time

CLI = os.path.join(os.environ.get("LOCALAPPDATA", "") or os.environ.get("HOME", ""),
                   "ZhihuCLI", "current", "zhihu-cli.exe")


def fetch(offset, limit=50):
    try:
        p = subprocess.run([CLI, "me", "contents", "--type", "all", "--sort", "ts",
                            "--order", "desc", "--offset", str(offset), "--limit", str(limit)],
                           capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"Code": -1, "Message": "zhihu-cli 超时（120s），稍后重试"}
    except OSError as e:
        return {"Code": -1, "Message": "zhihu-cli 启动失败：%s" % e}
    try:
        return json.loads(p.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {"Code": -1, "Message": "zhihu-cli 输出不是 JSON——大概率未授权，请先执行 zhihu-cli auth set --secret-stdin"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join("data", "contents.jsonl"))
    ap.add_argument("--max-pages", type=int, default=40)
    a = ap.parse_args()

    if not os.path.exists(CLI):
        print("[!] 未找到 zhihu-cli：%s" % CLI)
        print("    请先安装 zhihu-cli 并完成授权：zhihu-cli auth set --secret-stdin（详见 README 快速开始）")
        return 1

    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    items, offset, page = [], 0, 0
    while page < a.max_pages:
        page += 1
        d = fetch(offset)
        if d.get("Code") != 0:
            print("[!] API error:", d.get("Message"))
            msg = str(d.get("Message") or "")
            if "auth" in msg.lower() or "token" in msg.lower() or "401" in msg:
                print("    授权提示：zhihu-cli auth set --secret-stdin 后重跑本脚本")
            break
        data = d.get("Data") or {}
        batch = data.get("Items") or []
        items.extend(batch)
        paging = data.get("Paging") or {}
        print("page %d: +%d (total %d)" % (page, len(batch), len(items)))
        if paging.get("IsEnd") or not paging.get("NextOffset") or paging.get("NextOffset") == offset:
            break
        offset = paging["NextOffset"]
        time.sleep(0.3)

    with open(a.out, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    print("[+] %d items -> %s" % (len(items), a.out))


if __name__ == "__main__":
    sys.exit(main())
