#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看山 · 离线预渲染（无服务、无网络、双击即看）

把 3 个演示账号的诊断+处方 与 2 个贴入式分析示例**预先算好、嵌进一个 HTML**，
用于现场兜底：没有 Python、起不了服务、断网也能演示完整链路。

用法：
    python scripts/prerender_demo.py                      # 默认写 out/preview/
    python scripts/prerender_demo.py --out <目录或 html 文件>

产出：<out>/看山copilot_离线演示_预渲染.html（单文件，零外部依赖）
口径：演示数据全部为**合成数据**；页面内明确标注；数据锚点取数据内最新一条（可复现）。
"""
import argparse
import datetime
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import content_analyze as ca        # noqa: E402
import demo_synth as ds             # noqa: E402
import prescribe as pr              # noqa: E402
import signals as sg                # noqa: E402
import zhihu_diagnose as zd         # noqa: E402

CASES = [
    ("演示账号·老号", "polluted", 30),
    ("演示账号·垂类", "vertical", 30),
    ("演示账号·新手", "newbie", 30),
]

PASTES = [
    ("示例一：结构较好的稿子", "为什么你收藏了 300 篇干货，一篇也没用上？",
     "为什么你收藏了 300 篇干货，一篇也没用上？\n\n先说结论：收藏不是学习，收藏只是把焦虑存了个盘。\n\n"
     "我去年也这样：收藏夹 300 多篇，真正复用的不到 5 篇。数据来自我自己的导出记录（共 312 条）：\n"
     "- 当天处理的，复用率 41%\n- 3 天后处理的，复用率 6%\n\n"
     "所以我用一个三步法替代了「先收藏再说」：第一步，立刻问这条能用在哪个正在进行的事情上；"
     "第二步，当场写一句「我会用它做什么」；第三步，每周清一次收藏夹。\n\n"
     "这个方法的边界要说清楚：它对工具型内容有效，对观点型内容不太适用。\n\n"
     "你最近一次把收藏的内容真正用掉，是哪一篇？\n"),
    ("示例二：风险词较多的稿子", "全网最好的理财方法",
     "全网最好的理财方法，100% 稳赚，我保证你月入过万。加微信 zhuanqian888 拉你进群，扫码进群还有福利。"
     "这个方子能彻底根治失眠，药到病除。三天学会，保证学会。有问题打 13812345678。"
     "详见 https://example.com/post 。那些脑残杠精别来。"),
]


def build_case(user, archetype, days):
    rng = random.Random(ds.seed_of(user))
    items, _ = sg.attach_dt(ds.gen(user, archetype, ds.ARCH_DEFAULTS.get(archetype, 240), rng))
    sig = sg.extract(items, days=days, user=user)
    rxs = pr.prescribe(sig)
    md = zd.build_report(items, days=days, user=user,
                         src_label="合成演示数据（脚本生成，非任何真实账号数据）")
    return {
        "user": user, "archetype": archetype,
        "archetype_label": {"polluted": "被历史爆款污染的老号", "vertical": "垂类深耕号",
                            "newbie": "新手号（样本少）"}.get(archetype, archetype),
        "days": days, "signals": sig, "prescriptions": rxs, "report_md": md,
    }


def build_paste(label, title, text):
    rules, src, is_ex = ca.load_rules()
    r = ca.analyze(text, title=title, rules=rules, rules_source=src, is_example=is_ex)
    r["_label"] = label
    r["_text"] = text
    r["_markdown"] = ca.render_md(r)
    return r


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>看山 · 创作校准引擎（离线预渲染演示）</title>
<style>
  :root{--bg:#0f1216;--panel:#171c22;--panel2:#1e242c;--line:#2a323c;--fg:#e8edf3;
        --dim:#96a3b2;--accent:#4ea1ff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}
  header{padding:18px 22px 12px;border-bottom:1px solid var(--line);background:var(--panel)}
  h1{margin:0 0 4px;font-size:19px}
  .sub{color:var(--dim);font-size:13px}
  .tabs{display:flex;gap:8px;flex-wrap:wrap;padding:12px 22px 0;background:var(--panel);border-bottom:1px solid var(--line)}
  .tab{padding:9px 16px;border:1px solid var(--line);border-bottom:none;border-radius:8px 8px 0 0;
       background:var(--panel2);color:var(--dim);cursor:pointer;font-size:14px}
  .tab.on{background:var(--bg);color:var(--fg);font-weight:600;border-color:var(--accent)}
  main{padding:20px 22px 40px;max-width:1180px}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:700}
  .b-高{background:rgba(224,82,74,.16);color:#ff8880;border:1px solid rgba(224,82,74,.5)}
  .b-中{background:rgba(224,162,74,.16);color:#f0b866;border:1px solid rgba(224,162,74,.5)}
  .b-低{background:rgba(74,158,224,.16);color:#7bbcff;border:1px solid rgba(74,158,224,.5)}
  .sum{display:flex;gap:16px;flex-wrap:wrap;background:var(--panel2);border:1px solid var(--line);
       border-radius:10px;padding:12px 14px;font-size:14px;margin-bottom:10px}
  .flag{background:rgba(224,162,74,.12);border:1px solid rgba(224,162,74,.45);border-radius:10px;
        padding:10px 13px;font-size:13px;margin:10px 0}
  .cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px;margin-top:12px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 15px}
  .card h4{margin:0 0 8px;font-size:14.5px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .card .sig{font-size:13.5px;margin:6px 0}
  .card ul{margin:6px 0 6px 18px;padding:0}
  .card li{margin:3px 0;font-size:13.5px}
  .card .mod{color:var(--accent);font-size:13px;font-weight:600}
  .card .basis,.card .fals{color:var(--dim);font-size:12.5px;margin-top:6px}
  details{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 15px;margin-top:16px}
  summary{cursor:pointer;font-weight:600}
  .md{white-space:pre-wrap;word-break:break-word;font:13px/1.7 Consolas,"Courier New",monospace;
      margin-top:10px;color:#dbe4ee}
  .scorebar{height:9px;border-radius:999px;background:var(--panel2);overflow:hidden;margin:4px 0 10px}
  .scorebar i{display:block;height:100%;background:linear-gradient(90deg,#4ea1ff,#2b8a5b)}
  table{width:100%;border-collapse:collapse;font-size:13px;margin:8px 0}
  th,td{border:1px solid var(--line);padding:6px 9px;text-align:left;vertical-align:top}
  th{background:var(--panel2);color:var(--dim)}
  .k{color:var(--dim)}
  footer{margin-top:26px;padding-top:14px;border-top:1px solid var(--line);color:var(--dim);font-size:12.5px}
  .hide{display:none}
</style>
</head>
<body>
<header>
  <h1>看山 · 创作校准引擎 <span class="badge b-低">离线预渲染 · 单文件</span></h1>
  <div class="sub">下面全部内容在生成时已算好：无需 Python、无需联网、无需账号授权。生成时间 __GENERATED__</div>
</header>
<div class="tabs" id="tabs"></div>
<main>
  <section id="paneAcct">
    <div class="flag">数据说明：演示账号数据由 <code>scripts/demo_synth.py</code> <b>合成生成</b>（现场演示与回归测试专用），不是任何真实账号数据。真实入口：本人授权数据 → 同一套引擎。</div>
    <div id="acctOut"></div>
  </section>
  <section id="panePaste" class="hide"><div id="pasteOut"></div></section>
  <footer>
    平台不提供的量（粉丝数 / 曝光量 / 小时级点击率 / 完播）本工具不推断、不填数；缺失处写「样本不足」。<br>
    M10 合规项为公开规范整理的自查提示，不构成平台判定。近期窗口样本 &lt; 8 条时自动回退全量基线并在报告内声明。<br>
    数据锚点取数据内最新一条（非墙钟时间）→ 同一份数据任何时候跑，结论一致。
  </footer>
</main>
<script>
"use strict";
const DATA = __DATA__;
const $ = (id) => document.getElementById(id);
function esc(s){return String(s==null?"":s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
  .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;");}
function inline(s){return s.replace(/\*\*([^*]+)\*\*/g,"<b>$1</b>").replace(/`([^`]+)`/g,"<code>$1</code>");}

function rxCard(r){
  return '<div class="card"><h4><span class="badge b-'+esc(r.severity)+'">'+esc(r.severity)+'</span>'+
    '<span>'+esc(r.id)+" · "+esc(r.title||"")+'</span></h4>'+
    '<div class="sig"><span class="k">异常信号：</span>'+inline(esc(r.signal))+'</div>'+
    '<div class="mod">对应模块：'+esc(r.module)+'（'+esc(r.module_name||"")+'）</div>'+
    '<div class="k">具体动作：</div><ul>'+(r.actions||[]).map(a=>"<li>"+inline(esc(a))+"</li>").join("")+'</ul>'+
    '<div class="basis">依据：'+esc(r.basis)+'</div>'+
    '<div class="fals">失效条件：'+inline(esc(r.falsify))+'</div></div>';
}

function renderCase(c){
  const cnt={}; c.prescriptions.forEach(r=>cnt[r.severity]=(cnt[r.severity]||0)+1);
  let h='<div class="sum"><span>账号：<b>'+esc(c.user)+'</b>（'+esc(c.archetype_label)+'）</span>'+
    '<span>样本：<b>'+c.signals.n_total+'</b> 条（近期窗口 <b>'+c.signals.n_recent+'</b> 条）</span>'+
    '<span>数据锚点：<b>'+esc(c.signals.span_last)+'</b></span>'+
    '<span>处方：<b>'+c.prescriptions.length+'</b> 条（高 '+(cnt["高"]||0)+' / 中 '+(cnt["中"]||0)+' / 低 '+(cnt["低"]||0)+'）</span></div>';
  if(c.signals.n_recent < 8){
    h+='<div class="flag">近期窗口样本不足 8 条 → 引擎自动回退全量基线并已在报告内声明：节奏/稳定性类结论不可采信。</div>';
  }
  h+='<div class="cards">'+c.prescriptions.map(rxCard).join("")+'</div>';
  h+='<details><summary>展开完整七节诊断报告</summary><div class="md">'+esc(c.report_md)+'</div></details>';
  return h;
}

function renderPaste(p){
  const comps=(p.m4&&p.m4.components)||{};
  let h='<div class="sum"><span>示例：<b>'+esc(p._label)+'</b></span>'+
    '<span>有效字数：<b>'+p.overview.chars_effective+'</b>（原文 '+p.overview.chars_raw+'）</span>'+
    '<span>M4 得分：<b>'+(p.score==null?"不可评分":p.score+"/100")+'</b>（'+esc(p.grade)+'）</span>'+
    '<span>M10 风险：<b>'+p.m10.high+'</b> 高 / '+p.m10.medium+' 中</span></div>';
  if(p.score!=null){
    h+='<div class="cards">';
    ["hook","emotion","punch","anchor"].forEach(function(k){
      const c=comps[k]; if(!c) return;
      const pct=c.max?Math.round(c.score*100/c.max):0;
      h+='<div class="card"><h4>'+esc(c.label)+' <span class="badge b-低">'+c.score+' / '+c.max+'</span></h4>'+
        '<div class="scorebar"><i style="width:'+pct+'%"></i></div><ul>'+
        (c.hits||[]).map(x=>"<li>命中 "+esc(x.id)+" "+esc(x.label)+"</li>").join("")+
        (c.missed||[]).map(x=>'<li class="k">未命中 '+esc(x.id)+" "+esc(x.label)+"</li>").join("")+
        '</ul></div>';
    });
    h+='</div>';
  } else {
    h+='<div class="flag">该输入<b>不可评分</b>（没有可分析的正文）。这不是 0 分，而是「给不出分数」。</div>';
  }
  if((p.structure||[]).length){
    h+='<h3>结构诊断</h3><table><tr><th>编号</th><th>级别</th><th>发现</th><th>建议</th></tr>'+
      p.structure.map(f=>"<tr><td>"+esc(f.id)+"</td><td><span class='badge b-"+esc(f.level)+"'>"+esc(f.level)+
        "</span></td><td>"+esc(f.name)+"——"+inline(esc(f.evidence))+"</td><td>"+inline(esc(f.advice))+"</td></tr>").join("")+
      "</table>";
  }
  if((p.m10.hits||[]).length){
    h+='<h3>M10 合规风险自查</h3><table><tr><th>级别</th><th>编号</th><th>命中</th><th>出现</th><th>改法</th></tr>'+
      p.m10.hits.map(x=>"<tr><td><span class='badge b-"+esc(x.level)+"'>"+esc(x.level)+"</span></td><td>"+esc(x.id)+
        "</td><td>"+esc(x.name)+"</td><td>"+x.n+" 处</td><td>"+inline(esc(x.advice))+"</td></tr>").join("")+"</table>";
  }
  h+='<details><summary>展开完整分析报告（含校验规则插槽与失效条件）</summary><div class="md">'+esc(p._markdown)+'</div></details>';
  return h;
}

const TABS=DATA.cases.map((c,i)=>({name:"① "+c.archetype_label,render:()=>renderCase(c),pane:"acct"}))
  .concat(DATA.pastes.map(p=>({name:"② "+p._label,render:()=>renderPaste(p),pane:"paste"})));
$("tabs").innerHTML=TABS.map((t,i)=>'<div class="tab'+(i===0?" on":"")+'" data-i="'+i+'">'+esc(t.name)+'</div>').join("");
function show(i){
  document.querySelectorAll(".tab").forEach(x=>x.classList.toggle("on",+x.dataset.i===i));
  const t=TABS[i];
  $("paneAcct").classList.toggle("hide",t.pane!=="acct");
  $("panePaste").classList.toggle("hide",t.pane!=="paste");
  $(t.pane==="acct"?"acctOut":"pasteOut").innerHTML=t.render();
}
document.querySelectorAll(".tab").forEach(x=>x.onclick=()=>show(+x.dataset.i));
show(0);
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="看山 · 离线预渲染（单文件 HTML）")
    ap.add_argument("--out", default=os.path.join(ROOT, "out", "preview"),
                    help="输出目录，或直接给 .html 路径")
    a = ap.parse_args()

    cases = [build_case(u, arch, days) for u, arch, days in CASES]
    pastes = [build_paste(label, title, text) for label, title, text in PASTES]
    data = {"schema": "kanshan.prerender/1",
            "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "cases": cases, "pastes": pastes}

    html = PAGE.replace("__GENERATED__", data["generated"]) \
               .replace("__DATA__", json.dumps(data, ensure_ascii=False))

    out = a.out
    if out.lower().endswith(".html"):
        path = out
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    else:
        os.makedirs(out, exist_ok=True)
        path = os.path.join(out, "看山copilot_离线演示_预渲染.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)

    print("[+] 离线预渲染 -> %s（%.0f KB）" % (path, os.path.getsize(path) / 1024.0))
    for c in cases:
        cnt = {}
        for r in c["prescriptions"]:
            cnt[r["severity"]] = cnt.get(r["severity"], 0) + 1
        print("    账号 %-14s %-12s 样本 %3d/%3d 处方 %2d 条（高%d/中%d/低%d）"
              % (c["user"], c["archetype_label"], c["signals"]["n_recent"], c["signals"]["n_total"],
                 len(c["prescriptions"]), cnt.get("高", 0), cnt.get("中", 0), cnt.get("低", 0)))
    for p in pastes:
        print("    贴入 %-18s 得分 %s（%s）· M10 高 %d / 中 %d"
              % (p["_label"], p["score"], p["grade"], p["m10"]["high"], p["m10"]["medium"]))
    print("    打开方式：双击该 HTML 即可（无服务、无网络、无依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
