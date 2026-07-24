# 产品范围与非目标（Product Scope）

## 1. 产品一句话

自托管 **个人（可演进小团队）知识库**：管理资料、异步向量化、带引用的检索问答。

## 2. 当前目标（In scope）

- 笔记 / 文件 / 链接 CRUD  
- 可恢复入库与错误可见  
- 多格式解析（务实级别）  
- 用户隔离的语义检索  
- 后端 RAG 对话（SSE + citations）  
- 推理后端可配置（Ollama / 云兼容 API）
- Streamlit 可用 UI  
- 规范与可评估的演进（specs + plans + eval）

## 3. 明确非目标（Out of scope — 现在）

| 项 | 原因 |
|----|------|
| 完整 Agent 框架（工具循环、自主规划） | 与 CRUD+RAG 定位不符 |
| 自研 Agent Memory 内核 | 与 RAG 知识记忆重复；Hermes 侧另有工作记忆 |
| 复杂「常用数据权重/热度排序」系统 | 小库收益低，易马太效应；优先检索与内容质量 |
| 宣称级 HNSW 调优 | 未作为一等实现前不承诺 |
| OCR / 老 .ppt / 完美 Office 还原 | 后续迭代 |
| 企业级 IdP、复杂审批流 | 通用化后期再谈 |
| K8s/多区域多活 | 属其他作品集线 |

## 4. 「记忆」产品决策

```text
知识记忆     → 本仓库向量库 + SQL（做）
对话短上下文 → history 窗口 + FE session（做）
会话落库     → 可选，命名 conversation（以后）
Agent 记忆   → 不做；若整合 Hermes，用 Hermes 自带 memory + 本库当外脑
```

## 5. 「权重」产品决策

- **默认：不加**使用频率权重引擎。  
- 允许以后：  
  - 资源级 `boost` / 人工 pin  
  - 极轻的 cite_count 加分  
  - 新鲜度排序  
- 前提：已有评估集，能证明排序问题而非召回问题。

## 6. 通用化方向（不否决，但分阶段）

见：`.hermes/plans/*personal-to-universal-kb*.md`

顺序摘要：评估与拒答 → hybrid → 治理 → workspace → 解析增强 → 部署 → UI。

## 7. 对外表述检查

发布 README/简历/演示前自检：

- [ ] 是否把 fork 叙事说成「完全从零且无许可约束」？  
- [ ] 是否把 pptx 抽字说成完整 PPT 理解？  
- [ ] 是否把 ANN 钩子说成 HNSW 引擎？  
- [ ] 是否把 Streamlit 说成已完成企业级门户？  

以上夸大均不符合本 spec。
