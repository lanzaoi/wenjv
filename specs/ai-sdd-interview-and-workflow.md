# AI 辅助开发（SDD）× 面试题库 × 简历 STAR

> 面向：初级开发者如何在本仓库**规范地驾驭 AI**，并把「不是瞎 vibe」写进简历。  
> 原则：**你是导航员（navigator），AI 是驾驶员（driver）；规格与验证是方向盘和仪表盘。**

---

## 0. 三个概念先对齐（面试必问）

| 概念 | 英文 | 一句话 | 本项目对应 |
|------|------|--------|------------|
| Vibe coding | vibe coding | 对话里随口要功能、边生成边改，快但不稳 | 探索阶段可用 |
| Spec-Driven Development | SDD | 先写清 What/Why/验收，再让 AI 按规格实现 | `specs/` + `.hermes/plans/` |
| AI Agent | agent | 能规划、调工具、循环直到目标的系统 | **产品**里我们做 RAG 不是全自动 Agent；**开发过程**里可用 Agent |

**简历正确姿态（推荐）：**

> 不是「精通 vibe coding 狂写代码」，而是  
> **「在 AI 辅助下用 SDD：规格 → 计划 → 小步实现 → 可重复验证 → 文档回写」**。

业界共识（2025–2026）：纯 vibe 适合原型；可维护交付要 **living specs（活规格）** 约束 AI。

---

## 1. 在本项目里如何「驾驭」AI（可执行流程）

### 1.1 四级工件（缺一不可）

```text
① specs/          稳定约束（什么允许/禁止）     ← 宪法
② .hermes/plans/  可执行任务切片 + 验收        ← 施工图
③ 代码 + tests/   实现与自动化验证              ← 建筑
④ eval/ / 手工清单 行为与质量回归（RAG 尤需）   ← 质检
```

AI 每轮只被允许动 **当前 Task**；不得「顺手重构全世界」。

### 1.2 标准开发循环（SDD 四拍）

```text
Specify  →  Plan  →  Implement  →  Verify  →  (Update specs)
   ↑______________________________________________|
```

| 步骤 | 你做什么 | AI 做什么 | 本仓库落点 |
|------|----------|-----------|------------|
| Specify | 写清目标、非目标、验收 | 可帮起草，你拍板 | `specs/*.md` |
| Plan | 拆 2–5 分钟级任务 | 写 plan 文件 | `.hermes/plans/*` |
| Implement | 一次只开一个 Task | 改指定路径 | `backend/` `web/` |
| Verify | 规定命令与期望 | 跑测、修到绿 | `pytest`、ad-hoc、Redoc |
| Update | 行为变了就改 spec | 提醒你同步文档 | `specs/` + README |

### 1.3 给 AI 的「安全带」提示词模板

复制即用：

```text
你是本仓库的实现助手，不是产品负责人。

约束：
1. 先读 specs/README.md 与相关 specs；冲突时以 specs 为准。
2. 只做我指定的 Task：<Task 名称>；禁止扩大范围。
3. 改动文件限制在：<路径列表>。
4. 先写/补测试或验证脚本，再写实现（能测的必须测）。
5. 完成后给出：改了什么、如何验证、是否需更新 specs。
6. 禁止：编造 HNSW/已支持能力、提交密钥、大范围格式化无关文件。

验收命令：
- pytest tests/ -q
- <额外命令>
期望：<passed 条件>
```

### 1.4 人机分工（面试很加分）

| 必须人做 | 可交给 AI |
|----------|-----------|
| 产品边界、非目标 | 样板代码、样板测试 |
| 架构选型签字 | 按 plan 改多文件 |
| 安全与许可判断 | 重构命名（小范围） |
| 验收是否「真的对」 | 跑命令、修语法 |
| 简历叙事是否诚实 | 起草文档 |

### 1.5 初级最容易翻车的点（自检）

- [ ] 有没有 **无 spec 就让 AI 连写 3 小时**？  
- [ ] 有没有 **只看「代码像对的」不跑验证**？  
- [ ] 有没有把 AI 幻觉能力写进 README？  
- [ ] 有没有 git 历史全是「update stuff」无法回溯 Task？  
- [ ] 有没有 specs 与代码已经漂移？

---

## 2. 面试题库（AI Agent / RAG / 工程化 / SDD）

分轨准备：**A 基础 RAG**（你项目最贴）· **B Agent** · **C 系统与工程** · **D SDD/AI 协作** · **E 行为题**。  
每题给 **答题要点 + 本项目锚点**（没有的就说「规划/非目标」）。

### A. RAG 基础与进阶

| # | 问题 | 答题要点 | 本项目锚点 |
|---|------|----------|------------|
| A1 | 什么是 RAG？为何还要 RAG？ | 检索外部知识再生成；减幻觉、可更新、可引用 | `/documents/search` + `/chat` |
| A2 | 长上下文模型是否取代 RAG？ | 成本、噪声、权限、更新、引用；长上下文互补 | 知识在库不在 prompt 永久堆 |
| A3 | RAG 核心组件？ | 解析、切块、embed、索引、检索、重排、生成、引用 | parsers → chunk → lance → chat |
| A4 | embedding 是什么？换模型要注意？ | 向量语义；维度与模型绑定；常需重建索引 | `EMBEDDINGS_MODEL/DIMENSION` |
| A5 | chunk 怎么选？ | 太大噪声/太碎失语境；按文档类型；overlap | RecursiveCharacterTextSplitter |
| A6 | 如何减少幻觉？ | 强制引用、无命中拒答、温度、评测 | citations SSE；plan 中拒答 |
| A7 | score 是相似度吗？ | 可能是 distance；勿当百分比 | specs/rag-and-retrieval.md |
| A8 | 元数据过滤为何重要？ | 多租户、安全、source_type | user_id / belongs_to |
| A9 | hybrid 检索？ | 向量+关键词（BM25/FTS）融合如 RRF | plan G1，待做可诚实说 |
| A10 | 如何评估 RAG？ | 黄金集、命中率、引用率、人工抽检 | eval plan G0 |
| A11 | 文档更新如何保持一致？ | 删旧向量再写；任务状态；最终一致 | note update 路径 |
| A12 | 解析失败怎么办？ | 显式 failed + error，禁止假成功 | job error_message |
| A13 | ANN / HNSW / IVF 区别？ | 近似近邻；图 vs 倒排量化；小数据可 flat | 诚实：尽力 IVF_PQ，非 HNSW 营销 |
| A14 | 何时不用 RAG？ | 纯闲聊、无私域知识、强推理无资料 | `use_rag=false` |
| A15 | LangChain 一定要用吗？ | 胶水可选；核心可自研 | 本项目低使用率胶水 |

### B. AI Agent

| # | 问题 | 答题要点 | 本项目锚点 |
|---|------|----------|------------|
| B1 | Agent 与 Chatbot 区别？ | 工具、循环、状态、终止条件 | 产品=RAG 应用；开发可用 Agent |
| B2 | ReAct / Plan-Execute？ | 推理-行动交替 vs 先计划后执行 | 开发：plan 文件再实现 |
| B3 | 工具（Tool）设计原则？ | 原子、可校验、权限、超时 | 若 Hermes 接 KB：search/chat API |
| B4 | Agent 记忆分层？ | 工作/情节/语义/程序 | 产品：语义=向量库；不做 Agent Memory |
| B5 | 如何防 Agent 失控？ | 步数上限、人审、白名单工具、预算 | SDD 限制 Task 范围 |
| B6 | 多 Agent 何时用？ | 分工明确、可并行；否则过设计 | 开发可委派；产品 YAGNI |
| B7 | 如何评估 Agent？ | 任务成功率、工具调用正确率、成本、延迟 | 开发：pytest + checklist |
| B8 | HITL 是什么？ | Human-in-the-loop 关键步骤人工确认 | 入库失败人工 retry |
| B9 | Agent 与 RAG 关系？ | RAG 常作 Agent 的一个工具 | 本库 API 可被 Agent 调用 |
| B10 | MCP 是什么？ | 给 Agent 接工具/资源的协议 | Ralph≠MCP；Hermes 可有工具生态 |

### C. 系统与后端工程（AI 项目常问）

| # | 问题 | 答题要点 | 本项目锚点 |
|---|------|----------|------------|
| C1 | 设计一个个人/团队知识库 | 摄入、存储、检索、生成、权限、观测 | 整仓架构 |
| C2 | 为何入库异步？ | 解析/embed 慢；202+任务；可恢复 | durable_jobs |
| C3 | 队列用内存还是 DB？ | 持久化、重启、重试 | IngestionJob |
| C4 | SSE vs WebSocket？ | 单向服务器推 vs 双向 | `/chat` SSE |
| C5 | 如何做租户隔离？ | SQL + 向量 filter 双强制 | user_id |
| C6 | 上传安全？ | 白名单、大小、路径消毒 | config + utils |
| C7 | 密钥怎么管？ | env、不进 git、默认密钥告警 | SECRET_KEY |
| C8 | 观测什么指标？ | 任务失败率、检索延迟、TTFT、零命中率 | 日志；plan 中 query_logs |
| C9 | SQLite 上限？ | 并发写、团队规模；何时 Postgres | 个人默认 OK |
| C10 | AGPL 意味着什么？ | 网络分发/SaaS 源码义务 | LICENSE |

### D. SDD / AI 编程协作（体现「规范 vibe」）

| # | 问题 | 答题要点 | 你怎么答（结合本仓） |
|---|------|----------|----------------------|
| D1 | 什么是 vibe coding？风险？ | 无规格狂生成；债、漂移、不可维护 | 探索用；交付用 SDD |
| D2 | 什么是 SDD？ | Spec 先于 code；AI 按验收实现 | specs/ + plans/ |
| D3 | 规格和提示词谁重要？ | 规格是真源；提示词是操作手册 | specs 优先 |
| D4 | 如何让 AI 可控？ | 范围、路径、测试、禁止项、小步 | §1.3 模板 |
| D5 | AI 写的代码谁负责？ | **开发者**；AI 无签字权 | 你验证再合并 |
| D6 | 如何防止 AI 幻觉进生产？ | 验证门禁、诚实能力清单 | product-scope.md |
| D7 | 单测在 AI 流里角色？ | 验收契约；防回归 | test_smoke + 单测 |
| D8 | 多会话 AI 如何保持一致？ | 活规格进仓库 | specs 版本管理 |
| D9 | 何时不该用 AI？ | 不清需求、安全关键未理解、许可证不清 | 先学习清单 |
| D10 | 如何衡量 AI 辅助效率？ | 非只看行数：缺陷率、返工、交付周期 | Task 完成+测试绿 |

### E. 行为 / 项目深挖（STAR 向）

| # | 问题 |
|---|------|
| E1 | 讲一个你用 AI 却翻车再纠正的例子 |
| E2 | 你如何 code review AI 的输出？ |
| E3 | 文档/规格和代码冲突时你听谁的？ |
| E4 | 你怎么保证 Progressive 改造不把系统改塌？ |
| E5 | 如果面试官说你这是套模板项目你怎么回应？ |

---

## 3. 简历怎么写（避免踩雷）

### 3.1 不要写

- 「精通 vibe coding / 全自动 AI 写完项目」  
- 「自研 HNSW / 企业级 Agent 平台」（与事实不符）  
- 「零人工，AI 全包」  

### 3.2 建议项目标题

**wenjv（问据）自托管知识库（FastAPI + RAG）｜规范驱动的 AI 辅助工程实践**

### 3.3 技能条可写

- Spec-Driven Development / AI-assisted development with verification gates  
- FastAPI · SQLAlchemy · 异步任务 · Vector search · SSE  
- RAG：parse → chunk → embed → retrieve → grounded chat  
- 测试与回归：pytest 冒烟、评估集规划  

### 3.4 子弹示例（中英文各一，可改数字）

**中文：**

- 采用 **规格驱动（SDD）** 管理 AI 辅助开发：以 `specs/` 约束架构/API/RAG 边界，以可执行 plan 拆分任务，结合 pytest 与接口验收，降低多轮 AI 会话的需求漂移。  
- 设计并实现 **可恢复入库流水线**（任务表 + 重试/回收）与 **后端 RAG 对话 SSE（含 citations）**，将解析、向量化与生成解耦，避免请求线程阻塞。  
- 明确产品非目标（复杂热度权重、未验证 HNSW 宣称、Agent Memory 内核），保证能力表述与实现一致，便于评估与演进。

**English：**

- Practiced **spec-driven, AI-assisted delivery**: living specs + task plans + automated checks to keep agent/codegen changes scoped and verifiable.  
- Built durable ingestion jobs and backend RAG chat (SSE + citations) on FastAPI with tenant-aware vector retrieval.

---

## 4. STAR 故事库（直接背结构，填你的真实细节）

### STAR-1：用 SDD 管住 AI，完成分阶段改造

| 段 | 内容草稿 |
|----|----------|
| **S** Situation | wenjv 知识库要从能跑 Demo 升级为可维护的 CRUD+RAG；若纯对话指挥 AI，易范围膨胀、能力说不清。 |
| **T** Task | 建立可重复的人机协作流程，在有限时间内完成路由拆分、durable jobs、parsers、chat SSE 等，并保持可验证。 |
| **A** Action | ① 建立 `specs/`（架构/API/RAG/安全/范围）；② `.hermes/plans` 任务切片；③ 每任务限定路径与验收命令；④ pytest 冒烟 + ad-hoc 验证；⑤ 能力边界写入 product-scope（如 HNSW/权重/Memory）。 |
| **R** Result | 主链路可演示（上传→任务→检索→带引用对话）；文档与实现一致；返工集中在单 Task 而非全盘推翻。（*补你的耗时/模块数*） |

**面试金句：**  
「我把 vibe 用在探索，把 SDD 用在交付；AI 加速手，规格和测试踩刹车。」

---

### STAR-2：双存储一致性与异步任务

| 段 | 内容草稿 |
|----|----------|
| **S** | 解析与 embedding 耗时长，同步 API 会超时；SQL 与向量易不一致。 |
| **T** | 入库可恢复、失败可观测。 |
| **A** | IngestionJob 状态机；worker 认领/重试/stale reclaim；失败写 error_message；更新笔记删旧向量再写。 |
| **R** | 重启不丢任务意图；前端可轮询状态；为后续通用知识库治理打底。 |

**对应面试题：** C2 C3 A11  

---

### STAR-3：RAG 可信（引用 / 拒答 / 诚实能力）

| 段 | 内容草稿 |
|----|----------|
| **S** | 纯 LLM 易幻觉；业务要可追溯。 |
| **T** | 对话必须能指向知识来源。 |
| **A** | 后端 `/chat` SSE 先发 citations；FE 优先走后端；spec 规定 score 语义与未做 HNSW 的表述；规划空检索拒答。 |
| **R** | 演示路径可展示引用；简历与 README 无虚假指标。 |

**对应面试题：** A6 A7 D6  

---

### STAR-4：AI 写错了你怎么拦（行为题神器）

| 段 | 内容草稿 |
|----|----------|
| **S** | AI 曾生成「看起来完整」但扩大范围或错误假设（例：暗示 HNSW 已上、或路由重复注册）。 |
| **T** | 在合并前发现并纠正。 |
| **A** | 对照 specs/product-scope；跑约定 pytest；必要时让 AI 只回滚该 Task；更新禁止项。 |
| **R** | 未把错误能力写进对外文档；形成「验证门禁」习惯。 |

---

### STAR-5：学习策略（初级加分）

| 段 | 内容草稿 |
|----|----------|
| **S** | 基础仍在补（HTTP/异步/向量直觉），不能假装全会。 |
| **T** | 边学边交付，避免被 PPT/HNSW 细节拖死。 |
| **A** | 学习清单按主链排序；非目标写进 spec；深度优化列入 plan 后期。 |
| **R** | 交付节奏稳定；面试能画清边界。 |

---

## 5. 30 天「面试 + 工程」最小计划

| 周 | 工程（驾驭 AI） | 面试 |
|----|-----------------|------|
| 1 | 熟读全部 `specs/`；能默写主链路 | A1–A8 口述 + 画架构图 |
| 2 | 独立完成 1 个 plan 小 Task（人审 AI） | C1–C5；STAR-1/2 录音 |
| 3 | 补 1 个测试 + 1 次故意让 AI 越界再驳回 | D 全组；STAR-4 |
| 4 | 模拟面试：项目深挖 45 分钟 | B 选 5 题；E 全组 |

---

## 6. 模拟面试官追问（准备好 20 秒答案）

1. 你的 specs 谁维护？多久更新一次？  
2. AI 和你意见冲突听谁的？  
3. 为什么不用全套 LangChain Agent？  
4. 向量库删了 SQL 还在会怎样？  
5. 如何证明改动没让检索变差？  
6. 如果只能保留三个工程实践，你留哪三个？  
   - **参考答：** 活规格、任务切片、验证门禁  

---

## 7. 与仓库文件的索引

| 文件 | 用途 |
|------|------|
| `specs/README.md` | 规范入口 |
| `specs/product-scope.md` | 非目标与诚实边界 |
| `specs/coding-conventions.md` | AI 也要遵守的工程红线 |
| `.hermes/plans/*` | SDD 的 Plan 层 |
| `tests/` | Verify 层 |
| 本文 | 面试 + 人机协作 meta 规范 |

---

## 8. 一句话收束

> **流行的不是「会叫 AI 写代码」，而是「会用规格、计划、验证驾驭 AI」。**  
> 本仓库已经具备 SDD 骨架；你的简历故事应是 **可控的 AI 辅助工程**，不是魔法生成。

---

### 附录：快速自测（每周日）

- [ ] 能否不打开聊天记录，只凭 specs 说明架构？  
- [ ] 能否指出上一次 AI 改动的验证命令？  
- [ ] STAR-1 能否 2 分钟讲完？  
- [ ] 是否有任何对外句子违反 product-scope？  
