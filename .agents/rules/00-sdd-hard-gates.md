# SDD + 1.0 hard gates

You are an implementer for this repo, not the product owner.

Conflict order: runnable code > specs/ > .hermes/plans/ > chat.

1. Before coding, read `.agents/skills/kb-v1-discipline/SKILL.md` and the user's current Task block.
2. Only implement the current Task and paths listed by the user. No scope expansion.
3. Constitution index: `specs/README.md`. Follow `specs/git-and-ai-hygiene.md` for git.
4. Forbidden: `git add .`, force push, real secrets in git, deleting/skipping tests to go green, fake capability claims (HNSW optimized, perfect PPT, full E2E without evidence).
5. Before claiming done: run the stated verification commands and paste output (see skill verification-before-completion).
6. Today's 1.0 plan: `.hermes/plans/2026-07-23_111953-v1-env-to-runnable.md`. Freeze: no hybrid/Vue/Compose/productized refuse as scope creep.
7. Dual-cloud B0 only when Task says so; keep Ollama switchable; embedding model and dimension must match (e.g. bge-m3 → 1024).
8. Report with: 做了什么 / 改动路径 / 未做 / 验证命令与结果 / 是否需更新 specs / 风险.

@../specs/git-and-ai-hygiene.md
@../specs/product-scope.md
