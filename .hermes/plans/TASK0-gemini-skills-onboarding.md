# Task 0 投喂包 — 熟悉 `.agents/skills`（只读，不改业务代码）

> 复制下面「投喂正文」整段到 Antigravity / Gemini。  
> 本 Task **禁止**修改 `backend/` `frontend/` `tests/` 业务实现。

---

## 投喂正文（复制开始）

```text
你是本仓库的实现助手。当前是 Task 0：只读熟悉 Agent Skills 与项目规范入口，不写业务代码。

【目标】
在开始 1.0 双云实现前，建立对 `.agents/skills`、specs、plan 的正确心智模型，并输出一份简短「我会怎么遵守」的确认书。

【允许】
- 读取：`.agents/**`、`specs/**`、`.hermes/plans/2026-07-23_111953-v1-env-to-runnable.md`、`README.md`、`UPGRADE_ROADMAP.md`
- 只读查看目录结构（list/glob）
- 如需确认 Python/pytest 是否存在，可运行只读命令：`python --version`、`ls`、`pytest tests/ -q`（若环境未装好，记录失败即可，不要修）

【禁止】
- 修改任何业务代码或配置（backend/ frontend/ tests/ pyproject/ requirements 等）
- git commit / git add / 改 .gitignore
- 安装全局软件、删除数据、调用需要 API key 的云接口
- 扩大范围到实现 Provider

【必读顺序】
1. `.agents/README.md`
2. `.agents/SOURCES.md`
3. `.agents/skills/kb-v1-discipline/SKILL.md`
4. `.agents/skills/karpathy-guidelines/SKILL.md`
5. `.agents/skills/test-driven-development/SKILL.md`（可略读细节，抓住 Iron Law）
6. `.agents/skills/verification-before-completion/SKILL.md`
7. `.agents/skills/precise-git/SKILL.md`
8. `.agents/skills/rag-honesty/SKILL.md`
9. `.agents/skills/humanizer/SKILL.md`（知用途即可，可略读后半长文）
10. `.agents/skills/remove-ai-flavor-zh/SKILL.md`
11. `.agents/skills/frontend-design/SKILL.md`（知反模板 UI；纯后端可略）
12. `.agents/skills/anti-slop-ui/SKILL.md`
13. `.agents/skills/systematic-debugging/SKILL.md`（知道何时用）
14. `.agents/skills/requesting-code-review/SKILL.md`（知道完成 Task 后要自检）
15. `.agents/rules/00-sdd-hard-gates.md`（若存在）
16. `specs/README.md`（索引）
17. plan 文首「共享理解」+「阶段总览」：
    `.hermes/plans/2026-07-23_111953-v1-env-to-runnable.md`

【输出（必须用这个结构，中文）】
## Skills 清单
用表格列出你读到的每个 skill：name | 一句话用途 | 何时必须加载

## 真源优先级
用你自己的话写 4 行：代码 / specs / plan / skills 谁听谁的

## 今日 1.0 冻结
列出至少 5 条「今日不做」

## Git 红线
列出至少 4 条禁止项

## RAG 诚实红线
列出至少 4 条禁止宣称/禁止行为

## 完成定义
完成一个实现 Task 前，你必须具备哪些「证据」（命令/输出）

## 确认
最后一行写：
「Task 0 完成；未改业务代码；准备接收 Task 1。」
若有环境问题，单独一节 ## 环境备注

【验收】
- 未出现业务文件 diff（或 diff 为空）
- 输出覆盖上述全部章节
- 未声称已实现双云 Provider
```

## 投喂正文（复制结束）

---

## 你（用户）如何验收 Task 0

- [ ] Gemini 回复含完整章节  
- [ ] `git status` 无业务文件被改（允许无变更；若它改了 `.agents` 以外内容 → 打回）  
- [ ] 冻结列表与 plan 一致  
- [ ] 通过后，向 Grok 要 **Task 1 投喂包**

## 给 Grok 的下一句

Task 0 通过后发：`Task 0 过了，发 Task 1`
