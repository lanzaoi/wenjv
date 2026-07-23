# 驾驭 AI：Git 与工程卫生（AI Hygiene）

> **你是导航员，AI 是驾驶员。**  
> 规格决定方向，Git/测试决定能不能上路。  
> 本文是 `ai-sdd-interview-and-workflow.md` 的**操作细则**，冲突时以更严者为准。

---

## 1. 总原则

1. **范围锁定**：一次只做一个 Task；未点名的文件默认不许动。  
2. **可审计**：每个合并单元必须能回答「改了什么、为何改、怎么证明」。  
3. **人签字**：commit message、是否 push、是否扩大范围——**人决定**。  
4. **诚实验证**：区分 smoke / unit / e2e；禁止把「AI 说通过」当通过。  
5. **规格同步**：行为变了必须改 `specs/`（或显式写明暂不改的原因）。

---

## 2. 开工前（给 AI 的强制上下文）

每次委派实现，提示中至少包含：

```text
- 只做 Task：<名称>
- 允许修改路径：<列表>
- 禁止：无关 reformat、git add .、force push、写真实密钥、扩大范围
- 验收：<pytest 或其它命令 + 期望>
- 先读：specs/README.md 与相关 specs
```

AI 若要求扩大范围 → **先停，人批准后再开新 Task**。

---

## 3. Git 纪律（AI 默认禁止，除非人明确授权）

### 3.1 禁止（高危）

| 命令/行为 | 原因 |
|-----------|------|
| `git push --force` / `--force-with-lease`（未授权） | 毁协作历史 |
| `git reset --hard` | 丢本地工作 |
| `git clean -fd` | 删未跟踪文件 |
| 改已推送 commit 的 `amend`/`rebase` | 历史灾难 |
| 修改全局 `git config` | 污染环境 |
| 无说明删除 `.git` | 不可逆 |

### 3.2 默认允许（仍建议人确认后执行）

- `git status` / `git diff` / `git log`（只读）  
- 在**人要求提交时**：`git add <精确路径>` + `git commit`  
- 创建/切换**功能分支**（人指定分支名时）

### 3.3 暂存规则

```text
禁止默认： git add .
推荐：     git add path/to/file1 path/to/file2
提交前：   git status
           git diff
           git diff --cached
```

检查清单：

- [ ] 无 `.env`、密钥、venv、`__pycache__`、本地 db、巨型二进制  
- [ ] 无「顺手」全文件格式化  
- [ ] 无把 `hermes-verify-*.py` 临时脚本误提交（应在 Temp 或用完即删）  
- [ ] 无把计划外文件混入  

### 3.4 Commit message 规范

格式：

```text
<type>: <简明中文或英文摘要>

可选正文：
- 为什么
- 如何验证（命令）
```

| type | 用途 |
|------|------|
| `feat` | 新能力 |
| `fix` | 修 bug |
| `docs` | 仅文档/specs |
| `test` | 仅测试 |
| `refactor` | 行为不变的结构整理 |
| `chore` | 杂务（gitignore、依赖小改） |
| `perf` | 性能 |

**坏例子：** `update` `fix stuff` `AI changes` `wip`  
**好例子：** `feat: add durable job retry endpoint`  
**好例子：** `docs: add AI git hygiene spec`

规则：

- **一个 commit 一个意图**（功能与纯 docs 尽量拆开）。  
- message **人可让 AI 起草，人改后再生效**。  
- 禁止用 commit 当垃圾堆：「顺便」删无关文件。

### 3.5 分支

```text
feat/<topic>
fix/<topic>
docs/<topic>
```

- 避免 `aaa` `test` `ai` 这类名。  
- 个人项目也建议：**不直接在 main 堆 50 个无意义 commit**（至少逻辑上按 Task 分）。

---

## 4. 改完后的人机验收门禁（合并前）

按顺序执行：

```text
1. 看 diff      — 是否越界？是否泄密？
2. 跑约定测试  — 命令与退出码为准
3. 手摸关键路径 — 若涉及 API/上传/权限
4. 更新 specs   — 若行为/边界变了
5. 再 commit    — 精确 add + 规范 message
```

### 4.1 验证话术（禁止虚假）

| 可说 | 不可说 |
|------|--------|
| `pytest tests/ -q` → 4 passed | 「全部测试通过」若只有冒烟 |
| ad-hoc 脚本 passed=N | 「生产 E2E 全绿」未跑 Ollama/真库 |
| 某接口 Redoc 可点通 | 「安全审计完成」 |

### 4.2 测试红灯

- 禁止删断言、盲目 `@skip`、空 `except` 只为变绿。  
- 若测试过时：改测试并说明**行为约定是否变化**。

---

## 5. 密钥、隐私、许可

- 真实 `SECRET_KEY` / Token / 账号 **永不入仓**。  
- 日志与 commit 中不出现 Bearer token 全文。  
- 不添加与 AGPL 冲突的「闭源声明」。  
- 示例配置只用占位符。

---

## 6. 依赖与环境

- 新增 import：同步 `requirements.txt`（或说明 dev-only）。  
- 禁止无必要的大版本狂欢升级。  
- 不把本机绝对路径写死进库（用配置/环境变量）。  
- Windows 用户路径与 POSIX 脚本差异要注明。

---

## 7. 代码层「AI 味」清理

提交前应尽量没有：

- 未使用 import / 死代码 / 大段注释掉的旧实现  
- `except:` 裸吞异常  
- 重复注册路由、重复工具函数  
- 与 specs 矛盾的「临时能力宣称」  
- 无关文件的 permission 或 line-ending 整文件抖动  

---

## 8. 文档漂移

| 变更类型 | 必须更新 |
|----------|----------|
| API 字段/事件 | `specs/api-conventions.md` + 如有 README API 表 |
| 架构分层/目录 | `specs/architecture.md` |
| RAG/解析/索引能力 | `specs/rag-and-retrieval.md`、`product-scope.md` |
| 安全行为 | `specs/security.md` |
| 仅流程 | 本文或 `ai-sdd-interview-and-workflow.md` |

**禁止：** plan 里「未做」写进 README「已支持」。

---

## 9. 给 AI 的完成汇报模板（强制结构）

AI 结束实现时应用此结构（人更好 review）：

```text
## 做了什么
- ...

## 改动路径
- path1
- path2

## 未做 / 故意不做
- ...

## 验证
- 命令：...
- 结果：...

## 文档
- [ ] 无需改 specs
- [ ] 已改：specs/xxx.md

## 风险
- ...
```

---

## 10. 一页检查单（每次合并勾选）

**范围**

- [ ] 未超出批准路径  
- [ ] 无「顺便」大重构  

**Git**

- [ ] 未使用危险 git 命令  
- [ ] 未 `git add .`  
- [ ] diff 无密钥与垃圾文件  
- [ ] commit message 符合 type 规范  

**质量**

- [ ] 约定测试已跑且结果真实  
- [ ] 失败路径/权限过滤未明显回退  
- [ ] specs/README 与能力一致  

**产品诚实**

- [ ] 无虚假 HNSW/Memory/权重等宣称  

---

## 11. 简历可用表述（诚实版）

> 在 AI 辅助开发中执行 Git 与验证门禁：按 Task 精确暂存与原子提交、禁止盲加与强推、密钥与本地产物隔离，并以 pytest/specs 对照 diff 验收，避免不可审计的 vibe 交付。

---

## 12. 相关文件

| 文件 | 关系 |
|------|------|
| `specs/ai-sdd-interview-and-workflow.md` | SDD 总流程与面试 |
| `specs/coding-conventions.md` | 代码与依赖 |
| `specs/product-scope.md` | 能力边界 |
| `specs/security.md` | 密钥与安全 |
| `.gitignore` | 未跟踪物黑名单（改忽略规则要审慎） |

---

**记住：** 驾驭 AI 的最高信号不是生成速度，而是 **diff 干净、提交可读、验证可复核、文档不撒谎**。
