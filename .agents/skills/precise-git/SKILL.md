---
name: precise-git
description: "Use when staging, committing, or reporting git changes. Enforces precise path adds, conventional commits, and forbids dangerous git. Do not use for implementing features."
---

# Precise Git (本仓库)

真源细则：`specs/git-and-ai-hygiene.md`。冲突时以该文件更严者为准。

## 禁止（默认）

- `git add .` / `git add -A`（未获用户书面批准）
- `git push --force` / `--force-with-lease`（未授权）
- `git reset --hard`、`git clean -fd`
- 修改全局 `git config`
- 提交：`.env`、真密钥、`venv/`、`__pycache__`、本地 db、巨型二进制、临时 `hermes-verify-*`

## 允许

- 只读：`git status` / `diff` / `log`
- 用户明确要求提交时：`git add path1 path2`（精确路径）+ `git commit`

## Commit message

```text
<type>: <简明摘要>

可选：为何 / 如何验证
```

`type`: feat | fix | docs | test | refactor | chore | perf

坏例子：`update` / `fix stuff` / `wip`  
好例子：`feat: add openai-compatible embeddings provider`

## 提交前自检

- [ ] `git status` / `git diff` / `git diff --cached`
- [ ] 无密钥与垃圾文件
- [ ] 一个 commit 一个意图
- [ ] message 人可改后再生效（AI 只起草）

## 完成汇报若含 git

写明：暂存了哪些路径、未暂存什么、是否已 commit（默认未授权则不要 commit）。
