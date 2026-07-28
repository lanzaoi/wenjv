# API 约定（API Conventions）

## 1. 基线

- 风格：REST 资源 + 少量 RPC 式动作（如 search、chat、retry）。  
- 数据交换：JSON（`/chat` 为 SSE 文本流，事件负载仍为 JSON）。  
- 文档：运行中的 **Redoc**（`/redoc`）为契约真源；改行为先改实现再对文档。  
- 前缀挂载见 `backend/main.py`。

## 2. 鉴权

- 需要登录的接口：`Authorization: Bearer <jwt>`。  
- 依赖：`current_active_user`（或等价）。  
- 所有业务查询默认 **仅当前用户数据**（未来 workspace 则 + membership）。  
- 401：未认证或 token 无效；403：已认证但无权限（workspace 角色等）。

## 3. 主要路由前缀

| 前缀 | 职责 |
|------|------|
| `/auth` | 注册、登录、用户、JWT |
| `/file` | 上传、笔记、文件状态与下载 |
| `/links` | 链接提交与管理 |
| `/documents` | 检索 |
| `/jobs` | 入库任务查询（及规划中的 retry） |
| `/chat` | RAG 对话 SSE、模型列表 |
| `/ping` | 健康检查 |

## 4. 异步入库

- 上传/提交类接口优先 **202 Accepted**（或项目既有等价语义）+ 可轮询状态。  
- 客户端应：  
  1. 拿到资源 id / filename  
  2. 轮询 `status` 或 `/jobs/{id}`  
  3. 以 `finished/succeeded` 或 `failed` + `error_message` 结束  

禁止：同步在请求线程内做完整 embedding 当作唯一路径（会拖垮 API）。

## 5. 检索 `POST /documents/search`

建议字段（以实现/schema 为准）：

- `prompt`：查询文本  
- `window_size`：Top-K  
- `include_sources` / `exclude_sources`  
- `source_type`：可选 note/file/link  

响应文档条目应尽量包含：

- 文本片段、`score`、来源 meta（filename、page、source、source_type 等）

**Score：** 不得假定为 0–1 相似度百分比；见 `rag-and-retrieval.md`。

## 6. 对话 `POST /chat`（SSE）

### 请求（逻辑字段）

- `question`（必填）  
- `model`、`window_size`、`source_type`、`include_sources`、`exclude_sources`  
- `use_rag`：是否检索  
- `history`：可选，最近多轮 `{role, content}`（前端截断，默认量级 ~8）

### 事件类型

```text
data: {"type":"citations","citations":[...]}
data: {"type":"token","content":"..."}
data: {"type":"done"}
data: {"type":"error","message":"..."}
```

约定：

- 默认路径：前端走后端 SSE，失败才可降级。  
- `use_rag=true` 时，回答应 **可追溯**（有 citations 或明确拒答）。  
- 规划中的强化：无命中时不调用 LLM，直接拒答（见升级 plan G1）。

## 7. 错误响应

- 校验失败：4xx + 可读 detail。  
- 业务找不到：404。  
- 上传类型/大小：400/413 等，与 `security.md` 一致。  
- 5xx：记录日志；不向客户端泄漏堆栈与密钥。

## 8. 版本与兼容

- 暂无 URL 版本前缀（`/v1`）除非对外多客户端被迫需要。  
- 破坏性变更：在 `specs/` 与 README 记录；尽量先加字段再弃用。

## 9. 前端调用

- `web/src/api/client.js` 为 API 客户端集中处；新增接口优先写这里。  
- 禁止在多个组件复制两套 base URL 与 header 逻辑。
