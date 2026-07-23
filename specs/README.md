# specs/ — 项目规范索引

本目录是**个人知识库**仓库的规范（spec）统一入口。  
实现细节以代码为准；发生冲突时：**可运行代码 > 本目录 > 历史聊天**。

## 文档列表

| 文件 | 内容 |
|------|------|
| [architecture.md](./architecture.md) | 分层、双存储、进程与目录约定 |
| [api-conventions.md](./api-conventions.md) | HTTP/API、鉴权、SSE、错误与版本习惯 |
| [rag-and-retrieval.md](./rag-and-retrieval.md) | 解析、切块、检索、对话、评分语义 |
| [data-and-jobs.md](./data-and-jobs.md) | 模型、状态机、可恢复任务 |
| [security.md](./security.md) | 密钥、上传、多用户隔离、AGPL 注意 |
| [coding-conventions.md](./coding-conventions.md) | 代码风格、测试、提交、禁止事项 |
| [product-scope.md](./product-scope.md) | 产品边界：记忆/权重/非目标 |
| [ai-sdd-interview-and-workflow.md](./ai-sdd-interview-and-workflow.md) | SDD 驾驭 AI、面试题库、简历 STAR |
| [git-and-ai-hygiene.md](./git-and-ai-hygiene.md) | Git/提交/密钥/验证门禁（驾驭 AI 细则） |

## 相关但不放在 specs/ 的文档

| 路径 | 为何单独放 |
|------|------------|
| [`../README.md`](../README.md) | 用户向安装与使用说明 |
| [`../UPGRADE_ROADMAP.md`](../UPGRADE_ROADMAP.md) | 已完成的分阶段改造清单 |
| [`../.hermes/plans/`](../.hermes/plans/) | 可执行升级计划（如个人→通用知识库） |
| [`../LICENSE`](../LICENSE) | AGPL-3.0 全文 |

## 维护约定

1. **只写约束与决策**，不写长篇教程（教程可链到 plan/学习笔记）。  
2. 改架构或 API 行为时，**同步更新对应 spec**。  
3. 新增规范文件：放入本目录并在本索引表登记。  
4. 对外叙事：本项目为自托管知识库作品；包名/配置目录中的历史标识仅兼容用。  
5. **驾驭 AI：** 每次实现遵循 `git-and-ai-hygiene.md`（精确 add、原子提交、真实验证、禁止强推与泄密）。

## 快速原则（全局）

- **YAGNI**：先个人高效底座，再 workspace/hybrid/UI 大件。  
- **双存储**：SQLite = 权威元数据与任务；向量库 = 语义召回。  
- **对话收口后端**：RAG 生成以 `POST /chat` 为准，前端不直连模型为默认路径。  
- **诚实表述**：不宣称未落地的能力（如「已用 HNSW」「完美 PPT 解析」）。
