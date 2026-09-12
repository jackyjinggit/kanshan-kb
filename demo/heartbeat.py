# -*- coding: utf-8 -*-
"""看山 demo 心跳守护：探活 127.0.0.1:8699，挂了自动拉起。
用法：pythonw demo/heartbeat.py   （无窗口常驻；停止=任务管理器结束 pythonw）
设计：触发式探活（每 30s 一次 HTTP GET /api/health），不占资源；拉起失败连续 5 次才告警写日志。
凭证：不读不写任何密钥；启动环境变量由 启动_现场模式.bat 提供。"""
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOG = os.path.join(ROOT, "out", "heartbeat.log")
PORT = os.environ.get("KANSHAN_PORT", "8699")
URL = "http://127.0.0.1:%s/api/health" % PORT


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("%s %s\n" % (datetime.now().strftime("%m-%d %H:%M:%S"), msg))


def alive():
    try:
        with urllib.request.urlopen(URL, timeout=4) as r:
            return r.status == 200
    except Exception:
        return False


def spawn():
    """用 console 版 python + CREATE_NO_WINDOW：pythonw 无 stdout 会让 server 的 print 直接崩。"""
    py = sys.executable.replace("pythonw.exe", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    subprocess.Popen([py, os.path.join(HERE, "server.py"), "--port", PORT, "--no-browser"],
                     cwd=ROOT, creationflags=0x08000000,  # CREATE_NO_WINDOW
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    log("heartbeat 启动（探活 %s）" % URL)
    fails = 0
    while True:
        if alive():
            fails = 0
        else:
            fails += 1
            log("探活失败 x%d -> 拉起" % fails)
            spawn()
            time.sleep(6)
            if alive():
                log("拉起成功")
                fails = 0
            elif fails >= 5:
                log("连续 5 次拉起失败——请人工检查（凭证/端口占用/依赖）")
                fails = 0
        time.sleep(30)


if __name__ == "__main__":
    main()
