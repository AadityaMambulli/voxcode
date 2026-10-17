---
description: Explain how to configure voxcode devices and language.
---

Tell the user to pre-warm the server before the first voice call:

```powershell
$env:MCP_TIMEOUT = "120000"
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/__GITHUB_OWNER__/voxcode.git" voxcode doctor
```

`MCP_TIMEOUT` is Claude Code's documented global stdio-MCP startup timeout,
in milliseconds. Then tell the user to run `voxcode setup` in the environment
where the microphone and speakers are available. Do not select or approve
devices on the user's behalf.
