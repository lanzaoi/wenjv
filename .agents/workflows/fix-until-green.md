# Workflow: fix-until-green

Title: fix-until-green  
Description: Controlled fix loop inside ONE Task. Max N iterations. No fake green.

## Steps

1. Load `kb-v1-discipline`, `systematic-debugging`, `test-driven-development`, `verification-before-completion`.
2. Confirm the single acceptance command(s) for this Task (from user message). Default if unspecified: `pytest tests/ -q`.
3. Set `N = 5` max rounds (or user-specified lower).
4. Each round:
   a. Run acceptance commands.  
   b. If green → report success with output; STOP.  
   c. If red → root-cause briefly (systematic-debugging); minimal fix only within allowed paths.  
   d. Do **not** weaken tests, skip, or broad-catch exceptions to pass.  
5. After N failures: STOP. Output last errors + hypothesis + what you tried. Do not start unrelated Tasks.
6. No commit unless user authorized.
