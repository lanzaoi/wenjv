# 编码与工程约定（Coding Conventions）

## 1. 语言与运行

- Python **3.11+**  
- 格式：与现有文件保持一致（不强制全库 reformat 大爆炸）。  
- 新文件：类型提示适度；公开 service 函数优先注解。

## 2. 依赖

- 业务依赖写入 `requirements.txt`（与 `pyproject.toml` dynamic 一致）。  
- 新增重型依赖需有明确理由；**避免**为一点切块再引入半套 Agent 框架。  
- LangChain：仅允许薄胶水（splitter/embeddings/可选 loader）；新逻辑优先 stdlib + httpx + 自有 service。

## 3. 代码放置

- 路由按域进 `backend/api/routers/`。  
- 跨路由用例进 `backend/api/services/`。  
- 解析进 `backend/parsers/`。  
- 不要把秘密写进仓库；示例用占位符。

## 4. 异步

- FastAPI handler 可 async。  
- CPU/阻塞（重解析、部分客户端）使用 `asyncio.to_thread` 或既有 worker，避免堵事件循环。  
- 与 DB 会话：注意生命周期，勿跨 task 共享乱用 session。

## 5. 测试

- 最低：`pytest tests/test_smoke_architecture.py`  
- 新行为：优先单测纯函数（RRF、build_messages、parser 夹具）。  
- 无 Ollama 时：mock 外部调用；不把「必须连本机大模型」当单元测试前提。  
- 验证话术区分：**冒烟通过 ≠ 生产 E2E 全绿**。

## 6. 日志

- 使用项目 `backend.core.logging` 获取 logger。  
- 任务失败打 clear 错误；成功路径避免刷屏。

## 7. Git 与提交（建议）

- 小步提交；subject 清晰：`fix:`, `feat:`, `docs:`, `refactor:`, `test:`  
- 不提交：`venv/`、`.env` 真密钥、本地 DB、大型二进制模型。  
- 不改写无关历史。

## 8. 文档同步

行为变更时更新：

1. 对应 `specs/*.md`  
2. 必要时 `README.md`  
3. 长期任务更新 `UPGRADE_ROADMAP.md` 或 `.hermes/plans/*`

## 9. 禁止清单

- 禁止在默认路径绕过租户过滤做「全局向量扫描」。  
- 禁止静默吞掉入库异常并标 finished。  
- 禁止把 AGPL 项目描述成无 copyleft 约束。  
- 禁止为了演示伪造 HNSW/评估数据。
