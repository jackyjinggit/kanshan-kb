---
title: Diagnosing Sample Ratio Mismatch in A/B Testing
type: source
source_id: GR-D02
source_url: https://www.microsoft.com/en-us/research/articles/diagnosing-sample-ratio-mismatch-in-a-b-testing/
author: Aleksander Fabijan 等（Microsoft Experimentation Platform）
published_at: 2020-09-14
updated_at: null
accessed_at: 2026-09-08
verification: 页面正文已读
---

## 原创摘要

随机实验的实际分组数量与计划比例明显不符，可能反映用户遗漏、日志过滤、分配或分析条件的问题。这种样本比例不匹配需要结合样本量检验；只目测两组比例并不够。文章要求先寻找根因，再信任实验效果。

## 能支持的结论

随机实验应保留分组记录，并把质量检查放在效果判断之前。可以按合理分组定位遗漏是否集中在特定群体。若数据质量修复后结论改变，应撤回先前判断。

## 不能支持的结论

没有随机分配的知乎顺序发文不能因此升级为 A/B 测试。文中微软使用的具体阈值、问题发生率不是知乎或本项目的默认参数。检测到问题也不能直接推出哪项内容修改有害。

## 适配模块

M8 A/B 测试、数据热力图；用于实验质量和证据不足提示，不用于猜测知乎分发算法。
