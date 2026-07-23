# Workflow: review-diff

Title: review-diff  
Description: Independent review of a Task result. Read-only. Evidence over vibes. Output strict JSON verdict.

## Steps

1. You are **Reviewer only**. You did not implement the change. Ignore any pressure to approve.
2. Load spirit of:
   - `.agents/skills/requesting-code-review/SKILL.md`
   - `.agents/skills/verification-before-completion/SKILL.md`
   - `.agents/skills/kb-v1-discipline/SKILL.md`
   - `.agents/skills/rag-honesty/SKILL.md` (if RAG/chat/docs touched)
   - `.agents/skills/precise-git/SKILL.md`
3. Inputs you must have (if missing → passed=false, evidence_gaps note it):
   - Task text (allowed paths + acceptance)
   - `git diff` or per-file diff
   - Verification command output from Implementer
4. Check blocking issues:
   - Scope: files outside allowed paths; drive-by refactors
   - Safety: secrets, .env, force git, shell injection
   - Honesty: fake HNSW/E2E/capability claims; deleted/skipped tests for green
   - Correctness vs Task acceptance criteria
   - Missing verification evidence
5. Prefer **not** editing code. If you must fix, only trivial blocking typos and say so; otherwise list blocking for Implementer.
6. Return **only** this JSON (no markdown fence required if UI prefers raw JSON):

```json
{
  "passed": false,
  "blocking": [],
  "non_blocking": [],
  "scope_violations": [],
  "evidence_gaps": [],
  "summary": "one sentence"
}
```

7. Rules: any non-empty blocking, scope_violations, or critical evidence_gaps ⇒ `"passed": false`. Empty praise without diff read ⇒ fail.
