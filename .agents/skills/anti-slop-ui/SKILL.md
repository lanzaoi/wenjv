---
name: anti-slop-ui
description: "Use when editing Streamlit/HTML/CSS/frontend visuals for this personal KB. Bans black-gold cyber luxury, purple gradients, generic AI SaaS chrome. Prefer calm tool UI. Do not use for backend-only tasks."
---

# Anti-Slop UI（本仓库 · 个人知识库）

配合 `frontend-design` 使用，但**本产品是自托管工具**，不是融资 landing page。

## 产品气质（要）

- 干净、可读、偏文档/工作台
- 信息密度适中；主操作（登录、上传、对话、任务状态）一眼能找
- 中文界面文案短、具体；少空话

## 硬禁止（视觉）

- 黑金 / 赛博金描边 / 大面积金粉质感
- 紫粉霓虹渐变英雄区、玻璃拟态堆砌
- 「AI 感」装饰：无意义粒子、全屏 glow、假数据大数字仪表盘
- 全站 Inter + 紫按钮的模板 SaaS 脸（若改 Web 前端时）
- 为「高级」牺牲对比度与可访问性

## Streamlit 特别注意

- 少自定义 CSS 炫技；优先布局清晰与组件状态（loading/error）
- 不要用 Markdown 墙假装设计系统
- 错误信息要人话 + 可行动（「检查 EMBEDDING_API_KEY」而不是「发生错误」）

## 文案

- 用户可见字符串：优先走 `remove-ai-flavor-zh` / `humanizer`
- 禁止 README/UI 吹嘘未实现能力（见 `rag-honesty`）

## 何时加载

- 改 `frontend/`、主题、自定义 CSS、营销向页面时 **必须**
- 纯 `backend/` API 时 **不要** 加载本 skill
