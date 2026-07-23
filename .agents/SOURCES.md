# Agent Skills — Sources

Vendored / adapted into `.agents/skills/` for local Antigravity/Gemini use.

| Skill | Origin | License (upstream) | Notes |
|-------|--------|--------------------|-------|
| karpathy-guidelines | [multica-ai/andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) | MIT (see upstream) | Behavioral guidelines |
| test-driven-development | [obra/superpowers](https://github.com/obra/superpowers) | See upstream repo | TDD |
| verification-before-completion | obra/superpowers | See upstream | Evidence before "done" |
| requesting-code-review | obra/superpowers | See upstream | Review discipline |
| systematic-debugging | obra/superpowers | See upstream | Root-cause debugging |
| precise-git | **This project** | Same as repo (AGPL-3.0 codebase) | From `specs/git-and-ai-hygiene.md` |
| rag-honesty | **This project** | Same as repo | From product/rag specs |
| kb-v1-discipline | **This project** | Same as repo | 1.0 freeze + report template |
| humanizer | [blader/humanizer](https://github.com/blader/humanizer) | MIT | EN anti-AI prose |
| remove-ai-flavor-zh | [B1lli/remove-ai-flavor-writing-skill](https://github.com/B1lli/remove-ai-flavor-writing-skill) | See upstream | ZH 去 AI 味；folder name `remove-ai-flavor-zh` |
| frontend-design | [anthropics/skills](https://github.com/anthropics/skills) `frontend-design` | See upstream LICENSE.txt | Anti generic web UI |
| anti-slop-ui | **This project** | Same as repo | 禁黑金/紫渐变；Streamlit 工具气质 |

Upstream copies may be trimmed later; do not assume they are kept byte-identical forever.  
Project skills always defer to `specs/` when claims about product behavior conflict.
