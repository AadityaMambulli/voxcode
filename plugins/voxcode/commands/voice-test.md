---
description: Test voxcode speech input and output.
---

Call the `voxcode` MCP `speak` tool with a short test phrase, then wait for
the `listen` tool result with a bounded timeout. Only report success if both
tool results succeed. If `listen` returns a non-null `error`, report that
failure verbatim and do not claim the test succeeded.
