# Antigravity 多代理自监督操作手册

> 目标：让 Gemini **实现** 与 **审查** 分离，用命令输出当证据，而不是同一上下文里「我觉得 LGTM」。  
> 配合：`.agents/skills/*`、`.hermes/plans/*`、`specs/*`

---

## 1. 原则（先背这 5 条）

1. **实现者不能当唯一验收人** — 审查必须新开 agent / 新会话，或至少新开一条不带实现碎碎念的对话。  
2. **审查只看产物** — diff + 验收命令输出 + Task 原文；不看实现者的长篇自辩。  
3. **一次一个 Task** — 多代理不是多人一起改全世界。  
4. **证据 > 自称** — `pytest` / curl / 手工清单；没输出 = 没完成。  
5. **人仍是终裁** — 合并、扩 scope、持有 key、commit 授权归你。

错误示范：一个窗口里写「你既是 coder 又是 reviewer，做完自己 review」→ 几乎必吹。

---

## 2. 推荐角色（2～3 个就够）

| 角色 | 职责 | 加载 skill（建议） | 禁止 |
|------|------|-------------------|------|
| **Implementer** | 只做当前 Task | `kb-v1-discipline` `karpathy-guidelines` `test-driven-development` `precise-git`；动 RAG 加 `rag-honesty` | 宣称最终 LGTM；擅自下一 Task |
| **Verifier** | 跑约定命令、核对门禁清单 | `verification-before-completion` `kb-v1-discipline` | 大改业务（最多记问题列表） |
| **Reviewer** | 读 diff + Task，找越界/假绿/泄密/与 specs 冲突 | `requesting-code-review` `rag-honesty` `precise-git` | 无证据 LGTM；顺手重构 |

可合并：**Verifier + Reviewer = 同一「监工」agent**（仍须**新会话**）。

今日 1.0 **不要**上 5 个角色（架构师/安全官/产品经理…）——噪声大、互相推诿。

---

## 3. 标准流水线（每个 Task 循环）

```text
你
  │ 粘贴 Task N 投喂包
  ▼
[Agent A · Implementer]  →  /wf-implement-task
  │ 改代码、跑测、按模板汇报
  │ 交出：改动路径 + 命令输出 +「未做」
  ▼
你（30 秒）
  │ git status / 是否越界？有无 .env？
  ▼
[Agent B · Reviewer] 新会话  →  /wf-review-diff
  │ 只给：Task 原文 + git diff + 实现者验证输出
  │ 输出：passed true/false + blocking issues
  ▼
若 false → 回到 A（或新 A），只修 blocking，最多 2 轮
若 true  → 你勾 DoD；要下一 Task 找 Grok 要投喂包
```

**受控自修循环**（可选，仍单 Task 内）：

```text
/wf-fix-until-green
- 最多 N=5 轮
- 每轮必须重新跑验收命令
- 禁止删测试变绿
- 5 轮仍红 → STOP，把日志交还给你/Grok
```

---

## 4. 在 Antigravity 里怎么点（实操）

### 4.1 准备

1. 打开本仓库为 workspace。  
2. 确认 `.agents/skills` 可见；Rules 里 **Always On**：`.agents/rules/00-sdd-hard-gates.md`。  
3. 在 **Workflows** 面板添加 workspace workflows（内容见同目录 `workflows/*.md` 或下方附录）。  
   - 名称建议：`implement-task`、`review-diff`、`fix-until-green`  
   - 调用：`/implement-task` 等（以你 UI 显示的 slash 为准）

### 4.2 开两个 Agent（或两次对话）

| 窗口 | 用途 | 首次消息 |
|------|------|----------|
| A | 实现 | 完整 Task 投喂包 + `按 /implement-task 执行` |
| B | 审查 | **不要**把 A 的思考过程粘进去；只贴 Task 约束 + `git diff` + A 的验证输出 + `按 /review-diff 执行` |

Manager 多 workspace 并行时：**禁止**两个 Implementer 同时改同一批文件。

### 4.3 你每次最少做什么

- 发 Task 前：确认是「一个 Task」不是「做完 1.0」。  
- A 完成后：`git diff --stat` 扫一眼路径。  
- B 完成后：blocking 为 0 再要 Task N+1。  
- 密钥与 commit：仍是你的事。

---

## 5. 提示词碎片（可拼进投喂包）

### Implementer 头

```text
角色：Implementer only。
遵守 .agents/skills/kb-v1-discipline 与 karpathy-guidelines。
做完后不要说「可以合并」；只按汇报模板输出，并列出你跑过的命令与结果。
不要开始 Task 范围外的下一个功能。
```

### Reviewer 头

```text
角色：Independent Reviewer。你没有参与实现。
只根据：Task 原文、git diff、验证命令输出 做判断。
加载 requesting-code-review + verification-before-completion 精神。
禁止无证据 LGTM。
输出 JSON：
{
  "passed": false,
  "blocking": ["..."],
  "non_blocking": ["..."],
  "scope_violations": ["..."],
  "evidence_gaps": ["..."],
  "summary": "一句话"
}
任一项 blocking / scope_violations / 关键 evidence_gaps 非空 → passed=false。
```

### 修轮（A 收到 B 的 false）

```text
角色：Implementer。只修复 Reviewer 的 blocking 列表，禁止顺手重构。
修完重跑验收命令，用同一汇报模板；不要争辩 non_blocking。
```

---

## 6. 和 Grok 的分工（你现在的设定）

| 谁 | 做什么 |
|----|--------|
| Grok | 出 plan、Task 投喂包、必要时仲裁「是否扩 scope」 |
| Gemini A | 实现 |
| Gemini B | 审查 |
| 你 | 贴包、开双窗、终验、key、commit |

Grok **不必**每轮代看完整 diff；你可只在 B 与 A 打架或 DoD 争议时把摘要丢回 Grok。

---

## 7. 失败模式与对策

| 现象 | 对策 |
|------|------|
| B 无脑 LGTM | 强制 JSON；缺 evidence → passed=false；换新会话重审 |
| A/B 改同一文件撕扯 | 同时只一个写者；B 默认只读 |
| 多代理讨论架构 1 小时 | 拉回 Task 白名单；架构争议交 Grok/人 |
| 自修 10 轮仍红 | 停；缩小 Task 或回 Grok |
| 加载 12 个 skill 全开 | Implementer 只开纪律+TDD；文案 skill 仅文档 Task |

---

## 8. 最小可执行（今天就能用）

不配 Workflow UI 也能做：

1. 窗口 A：贴 Task 1 投喂包。  
2. 完成后你复制 `git diff` 与 pytest 输出。  
3. 窗口 B：**新聊**，贴 Reviewer 头 + Task 原文 + diff + 输出。  
4. `passed=true` 再向下。

这就是「多智能体自己监督自己」的可靠形态：**互监，而非一人分饰两角自嗨**。
