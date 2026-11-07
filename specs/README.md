# specs/: 项目规范索引

本目录是 **wenjv（问据）** 知识库仓库的规范（spec）统一入口。  
实现细节以代码为准；发生冲突时：**可运行代码 > 本目录 > 历史记录**。

## 文档列表

| 文件 | 内容 |
|------|------|
| [architecture.md](./architecture.md) | 分层、双存储、进程与目录约定 |
| [api-conventions.md](./api-conventions.md) | HTTP/API、鉴权、SSE、错误与版本习惯 |
| [rag-and-retrieval.md](./rag-and-retrieval.md) | 解析、切块、检索、对话、评分语义 |
| [data-and-jobs.md](./data-and-jobs.md) | 模型、状态机、可恢复任务 |
| [security.md](./security.md) | 密钥、上传、多用户隔离、AGPL 注意 |
| [coding-conventions.md](./coding-conventions.md) | 代码风格、测试、提交、禁止事项 |
| [product-scope.md](./product-scope.md) | 产品边界：记忆、权重与非目标 |
| [git-and-ai-hygiene.md](./git-and-ai-hygiene.md) | Git 提交、密钥安全与验证门禁规范 |
| [adr/0001-lance-vs-pgvector.md](./adr/0001-lance-vs-pgvector.md) | ADR 0001: 嵌入式 LanceDB 选型决策 |

## 相关外部文档

| 路径 | 说明 |
|------|------|
| [`../README.md`](../README.md) | 用户安装与使用说明 |
| [`../docs/UPGRADE_ROADMAP.md`](../docs/UPGRADE_ROADMAP.md) | 已完成的分阶段改造清单 |
| [`../LICENSE`](../LICENSE) | AGPL-3.0 许可证全文 |

## 维护约定

1. **专注约束与决策**：规范文档记录明确的技术约束与设计决策，操作指南查阅相关部署与演练文档。  
2. **文档同步更新**：调整架构或 API 契约时，必须同步更新对应的 spec 文档。  
3. **新增规范管理**：新增规范文件统一放入本目录并在本索引表中登记。  
4. **品牌与命名规范**：项目统一对外使用 wenjv（问据）自托管知识库名称，配置目录与数据库文件的历史路径用于向下兼容探测。  
5. **工程质量把控**：代码开发严格遵循 `git-and-ai-hygiene.md`（精确 add、原子提交、真实验证、禁止强推与泄密）。

## 全局设计原则

- **聚焦核心场景**：以轻量自托管底座为核心，逐步按需演进扩展。  
- **双存储分工**：SQLite 维护权威实体元数据与异步任务表；向量库负责文本切块语义召回。  
- **对话收口后端**：RAG 编排统一通过后端 `POST /chat` 接口流式分发，前端不直连大模型服务。  
- **保持技术诚实**：严禁宣称未经实现与验证的能力（例如未经门禁评测的特定索引优化或扫描件无损解析）。
