# `.agents/` — Antigravity / Gemini 工作区约定

本目录给 **Google Antigravity（Gemini）** 等兼容 Agent Skills 的工具使用。  
**产品与架构真源仍是仓库根下 `specs/`**；此处 skill 是操作纪律，不能覆盖 specs。

## 布局

```text
.agents/
  README.md                 # 本说明
  SOURCES.md                # 上游 skill 来源与许可
  skills/
    kb-v1-discipline/       # 本仓库 1.0 范围与汇报（项目定制）
    karpathy-guidelines/    # 少假设、外科手术式改动
    test-driven-development/
    verification-before-completion/
    requesting-code-review/
    systematic-debugging/
    precise-git/            # 项目定制 git 卫生
    rag-honesty/            # 项目定制 RAG 诚实
    humanizer/              # 英文去 AI 写作腔
    remove-ai-flavor-zh/    # 中文去 AI 味
    frontend-design/        # 有意图的 UI（反模板）
    anti-slop-ui/           # 本仓：禁黑金/紫渐变伪高级
  rules/                    # 可选；Antigravity Always-on 规则
```

## 技能怎么用（给模型）

1. 开工先读：`skills/kb-v1-discipline/SKILL.md` + 当前 Task 投喂包。  
2. 写/改行为代码：加载 `test-driven-development` + `karpathy-guidelines`。  
3. 声称完成前：加载 `verification-before-completion`，跑通命令再汇报。  
4. 动检索/chat/向量/解析文案：加载 `rag-honesty`。  
5. 暂存/提交：加载 `precise-git`（默认 **不要** commit，除非用户明确授权）。  
6. 修 bug：先 `systematic-debugging`，禁止盲打补丁。  
7. Task 结束后：可按 `requesting-code-review` 做自检清单（或等人开第二 agent）。  
8. 改 README/UI/产品中文案：加载 `remove-ai-flavor-zh`（中文）或 `humanizer`（英文）。  
9. 改 `frontend/` 视觉：加载 `anti-slop-ui`；若大改版式再加 `frontend-design`。  
10. **纯后端 Task 不要**加载 humanizer / frontend-design / anti-slop-ui（省上下文）。

## 与 specs / plan 的关系

| 路径 | 角色 |
|------|------|
| `specs/*` | 宪法（允许/禁止/API/RAG） |
| `.hermes/plans/*` | 今日施工图与 Task 切片 |
| `.agents/skills/*` | 怎么开车（纪律） |

## 不要

- 不要一次加载无关 skill 刷存在感  
- 不要把 skill 里的通用建议写成未实现的产品能力  
- 不要在未读 `kb-v1-discipline` 时扩大 1.0 范围  
