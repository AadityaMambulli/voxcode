---
description: Explain how to configure voxcode devices and language.
---

Tell the user to pre-warm the server before the first voice call:

```powershell
$env:MCP_TIMEOUT = "120000"
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/AadityaMambulli/voxcode.git" voxcode doctor
```

If the model is not cached, pre-download it once with:

```powershell
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/AadityaMambulli/voxcode.git" voxcode download-model --model small
```

The download is 486,215,847 bytes (486 MB / 463.7 MiB), resumable, and is the
only network use in the voice path. Then tell the user to run the following in the environment
where the microphone and speakers are available:

```powershell
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/AadityaMambulli/voxcode.git" voxcode setup
```

Do not select or approve devices on the user's behalf.
