---
name: bible-ask
description: Answer a Bible question with the full multilingual workflow (Hebrew, Septuagint, Greek NT, WEB), with this session acting as the leader-agent and delegating to the specialist agents.
argument-hint: "\"<question>\" [--demo]"
disable-model-invocation: true
allowed-tools: Bash(uv run bible-rag *) Read Write Edit
---

Answer this question with the hierarchical Bible RAG workflow: **$ARGUMENTS**

Act as the **leader-agent** for this question:

1. Read `.claude/agents/leader-agent.md` and follow its workflow **exactly**, steps 0–7. That includes writing and checking `analysis.json`, the trace, and the confidence check.
2. Delegate to the specialists with the Agent tool: `english-retrieval-agent`, `hebrew-specialist-agent`, `septuagint-specialist-agent`, `greek-new-testament-agent`, `cross-reference-agent` and `synthesis-agent`. Send independent delegations in one message, in parallel. Never do a specialist's retrieval or translation yourself.
3. If `--demo` is present, use demo mode: status lines after each step, and the trace at the end.

This is the same workflow as `claude --agent leader-agent`, started from an ordinary session.
