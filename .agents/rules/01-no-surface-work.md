# No surface work

Surface completion is worse than admitting a gap. This rule lists things that look like progress but hide breakage.

## Fake green — forbidden

- Claiming "tests pass" without pasting the actual command output from this session.
- Weakening or deleting assertions so a failing test turns green.
- Bare `except: pass` or `except Exception: pass` to silence errors that should propagate.
- Running only `python -c "import backend"` and reporting "all tests pass".
- Whole-repo autoformat in a commit that also changes behavior (mixes signal with noise).
- Writing unimplemented capabilities into README, UI strings, or specs as if they exist.

## Verification grading

| Level | What it proves | What it does NOT prove |
|-------|---------------|----------------------|
| `python -c "import X"` | Module loads | Nothing about behavior |
| `pytest tests/ -q` (green) | Unit/integration suite passes | E2E user flow, live API |
| Manual E2E (documented steps + screenshots) | Full user path works | Regression on untouched paths |

State which level you ran. Do not conflate levels.

## Multi-agent review discipline

- The implementer agent must NOT give itself a final LGTM or "passed" verdict.
- Review must happen in a separate agent session that receives the diff and verification output (see workflow `review-diff`).
- A review that contains only praise and no diff evidence is itself a failure.

@../specs/git-and-ai-hygiene.md
