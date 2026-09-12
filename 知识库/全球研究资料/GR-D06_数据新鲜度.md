---
title: "[GA4] Data freshness"
type: source
source_id: GR-D06
source_url: https://support.google.com/analytics/answer/11198161?hl=en
author: Google Analytics Help
published_at: null
updated_at: null
accessed_at: 2026-09-08
verification: 页面正文已读；页面未显示发布日期和更新日期
---

## 原创摘要

Google Analytics 说明实时、日内和逐日处理的数据在可用时间与覆盖范围上存在差异。部分数据先到达，另一些随后补齐，报表在处理期间可能变化；不同报表也可能暂未同步。可见数字并不自动等于最终完整数字。

## 能支持的结论

看山应记录统计期间、采集时间、是否完整日和修订状态。比较两个窗口前先检查覆盖与新鲜度；当天尚未结束时，不把当前数与完整一天直接比较后断言下降。

## 不能支持的结论

GA4 的具体处理小时数不是知乎时效承诺，也不能解释任意知乎空值。空字段、权限不足、延迟与真实零值应分别核查；不知道原因时应保留未知。

## 适配模块

M8 指标矩阵与复盘窗口校验。来源只支持处理时效需要显式表达，不提供黑客松 API 的历史覆盖或返回字段保证。
