# API 约定 (API Conventions)

## 1. 基础规范

- 架构风格：RESTful 资源模型配合关键 RPC 动作（如 search、chat、retry）。
- 数据格式：全链路统一采用 JSON 交互（`/chat` 采用 SSE 事件流，事件负载为 JSON）。
- 接口契约：以服务运行生成的 Redoc（`/redoc`）交互式文档为契约准则；修改接口行为时，代码实现与接口文档必须同步更新保持一致。
- 路由挂载：统一在 `backend/main.py` 完成生命周期与路由前缀装配。

## 2. 鉴权与租户上下文

- 受保护接口请求头：`Authorization: Bearer <jwt>`。
- 依赖注入提取主体：通过 `current_active_user` 注入当前用户对象。
- 租户作用域限制：所有业务查询与数据操作均在底层强制过滤当前用户的 `user_id`。
- 状态码定义：
  - `401 Unauthorized`：未提供有效凭证或 Token 已过期
  - `403 Forbidden`：凭证有效但操作超出当前角色权限边界

## 3. 主要路由模块

| 路由前缀 | 模块职责 |
|----------|----------|
| `/auth` | 注册、登录认证、当前用户信息与凭证刷新 |
| `/file` | 文件上传、处理状态查询、下载及笔记实体管理 |
| `/links` | 网页链接提交、列表查询、状态跟踪与内容抓取 |
| `/documents` | 文本切块语义检索与混合检索 |
| `/jobs` | 异步持久化任务查询与执行状态跟踪 |
| `/chat` | 基于知识库依据的 SSE 流式问答与模型列表查询 |
| `/ping` | 服务健康探测接口 |

## 4. 异步入库模式

- 耗时上传与内容提交接口返回 `202 Accepted` 并附带任务凭据。
- 客户端标准交互时序：
  1. 调用上传接口获取任务 ID 或文件标识
  2. 轮询 `/file/status/{filename}` 或 `/jobs/{id}` 查询处理进度
  3. 获取到 `finished` / `succeeded` 成功状态，或解析失败返回的 `failed` 状态及 `error_message`
- 严禁在主请求线程中同步执行大文本切块与模型向量推理。

## 5. 检索接口 `POST /documents/search`

请求参数格式：

- `prompt`：检索查询文本
- `window_size`：召回候选切块数量 Top-K
- `include_sources` / `exclude_sources`：指定包含或排除的源文件名称列表
- `source_type`：可选过滤源类型（note / file / link）

响应结构包含切块文本、`score`（几何距离值）以及来源元数据（文件名、页码、知识源类型等）。向量距离数值切勿直接当成百分比匹配度展示。

## 6. 对话流式接口 `POST /chat` (SSE)

### 请求参数

- `question`：当前提问内容
- `model`：指定对话模型名称
- `window_size`：参考切块检索窗口大小
- `source_type`：限定知识源类别
- `use_rag`：是否启用知识库检索增强
- `history`：多轮对话上下文历史数组 `[{role, content}]`（客户端维护滑动窗口截断）

### 事件流类型

```text
data: {"type":"citations","citations":[...]}
data: {"type":"token","content":"..."}
data: {"type":"done"}
data: {"type":"error","message":"..."}
```

行为约定：

- 前端默认通过后端 SSE 进行流式输出，确保鉴权与 RAG 编排收敛在服务端。
- `use_rag=true` 时，生成结果必须具备可溯源性（包含 citations 依据事件）。
- **已实装空命中拒答机制**：当检索无命中且 `RAG_REFUSE_ON_EMPTY=true` 时，后端直接返回无依据提示事件并终结流，不调用大语言模型，有效抑制无依据的幻觉生成。

## 7. 错误处理与状态映射

- 参数校验失败：返回 `422 Unprocessable Entity` 或 `400 Bad Request`，附带清晰的验证错误明细。
- 目标资源不存在：返回 `404 Not Found`。
- 上传体积超限或文件类型不合法：返回 `400 Bad Request` 或 `413 Payload Too Large`。
- 服务端内部异常：记录完整服务端日志，向客户端返回规范的 `500` 错误，严禁向外部泄漏内部堆栈或系统密钥。

## 8. 版本控制与演进

- 接口设计遵循向前兼容原则，建议通过新增可选字段并逐步废弃旧字段进行平滑过渡。
- 涉及破坏性变更时，必须在 `specs/` 与 `README.md` 中详细记录变更影响。

## 9. 前端接口调用规范

- 前端接口调用统一封装在 `web/src/api/client.js` 中，便于集中管理 Token 注入、超时控制与通用错误拦截。
- 禁止在各个 UI 组件内分散定义 API Base URL 或重复拼接鉴权请求头。
