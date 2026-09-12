---
title: "Data Quality: Fundamental Building Blocks for Trustworthy A/B testing Analysis"
type: source
source_id: GR-D01
source_url: https://www.microsoft.com/en-us/research/articles/data-quality-fundamental-building-blocks-for-trustworthy-a-b-testing-analysis/
author: Platina Liu、Wen Qin、Hao Ai、Jing Jin（Microsoft Experimentation Platform）
published_at: 2021-11-09
updated_at: null
accessed_at: 2026-09-08
verification: 页面正文已读
---

## 原创摘要

微软实验平台将数据质量视为效果判断的前提。字段缺失、重复、记录延迟或随机化单位关联错误，都会影响实验解释。缺失不只表现为 `null`，也可能被记录为零或其他默认值；按分组检查能暴露总量掩盖的问题。

## 能支持的结论

看山应先验收指标口径、时间戳、缺失覆盖和聚合层级，再生成解释。分组图表必须展示样本量，不能不断细分直到找到好看的结果。数据质量与业务效果应分别报告。

## 不能支持的结论

本文不提供知乎的统计延迟、推荐权重或统一最低阅读量。微软的实验实践不能证明任意创作者的小样本对比具有统计效力。项目自定异常阈值不能借此包装为平台规则。

## 适配模块

M8 指标矩阵、数据热力图、A/B 测试；作为数据验收依据，不作为内容增长案例。原文链接见元数据，正文不搬运。
