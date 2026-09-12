---
title: RFC 9700：OAuth 2.0 安全最佳实践
type: source
source_url: https://www.rfc-editor.org/rfc/rfc9700.html
author: IETF；T. Lodderstedt、J. Bradley、A. Labunets、D. Fett
published_at: 2025-01
updated_at: null
accessed_at: 2026-09-08
verification: 页面正文已读
---

## 原创摘要

RFC 9700 是 OAuth 2.0 的安全最佳实践文件。所读第 2.1 节强调重定向地址的严格匹配、跨站请求伪造防护及授权码流程安全，并讨论 PKCE 等机制。不同客户端类型和授权服务器能力存在前提，不能把标准建议直接写成某个平台已支持的接口参数。

## 能支持与不能支持

可支持 M10 在授权回调中验证会话关联，停止不匹配或重放请求，避免把 Token 暴露在浏览器可见 URL。不能证明知乎当前支持 PKCE、自动回传 state 或某种撤销端点；这些必须通过官方接入说明及实际测试确认。不能只添加一个随机参数就宣称 OAuth 已安全上线。

## 应用

适配 M10-02。检查每个防护步骤的实现及失败路径，以两账号隔离、过期和重放测试作为验收；不在研究卡中保存任何实际凭证。
