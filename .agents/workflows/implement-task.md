# Workflow: implement-task

Title: implement-task  
Description: Implement only the current Task with TDD discipline and evidence-based report. No scope expansion.

## Steps

1. Load and follow:
   - `.agents/skills/kb-v1-discipline/SKILL.md`
   - `.agents/skills/karpathy-guidelines/SKILL.md`
   - `.agents/skills/test-driven-development/SKILL.md` (for behavior changes)
   - `.agents/skills/precise-git/SKILL.md`
   - If touching RAG/chat/embeddings/docs claims: `.agents/skills/rag-honesty/SKILL.md`
2. Read the user-provided Task block: objective, allowed paths, forbidden paths, verify commands.
3. Read only the specs/plan sections named in the Task.
4. Implement **only** that Task. If blocked or need broader paths: STOP and ask the user.
5. Prefer RED→GREEN for behavior code. Do not delete/skip tests to go green.
6. Run the Task's verification commands. Capture exit codes and key output lines.
7. Do **not** git commit unless the user explicitly authorized commit in this message.
8. Finish with the report template from kb-v1-discipline (做了什么 / 路径 / 未做 / 验证 / 文档 / 风险).
9. Do not start the next Task. Do not claim "ready to merge" or final LGTM.
