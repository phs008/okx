# AGENTS.md

## 0. Always conversation in korean

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:
- State assumptions explicitly when they matter.
- If multiple interpretations exist, present them.
- If a simpler approach exists, say so.
- If something is truly unclear, ask before changing behavior.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No configurability that was not requested.
- Match the existing code style.

## 3. Surgical Changes

Touch only what is needed.

- Do not refactor unrelated code.
- Do not revert user changes.
- Remove only unused code introduced by your own changes.
- Every changed line should trace directly to the user request.

## 4. Goal-Driven Execution

Define success criteria and verify before claiming completion.

For multi-step tasks, use a short plan:

```text
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
3. [Step] -> verify: [check]
```

## 5. Project Work Agreement

- Prefer existing utilities and patterns before adding new code.
- Add dependencies only when explicitly requested.
- Keep diffs small, reviewable, and reversible.
- Run focused tests or the smallest useful validation after changes.
- Final reports should include changed files, verification, and remaining risks when relevant.
