# voxcode

`voxcode` is a free, local-first voice mode for terminal coding agents. Audio
capture, speech recognition, and speech output run locally; voice data does not
go to a model provider. That means the voice layer works with proxies, offline
coding workflows after the model is cached, and free-tier model accounts.

## 60-second quickstart

Use Python 3.10-3.13 and install the package with the audio, speech-to-text,
VAD, and MCP extras:

```powershell
uv pip install "voxcode[audio,stt,vad,mcp]"
```

### Claude Code plugin

Inside Claude Code, add the published marketplace and install the plugin:

```text
/plugin marketplace add AadityaMambulli/voxcode
/plugin install voxcode@voxcode
```

provides voice commands, the MCP server, and a Stop hook. The MCP server uses
local audio and speech recognition; it does not send audio or transcripts to a
paid voice API.

### Push-to-talk from any terminal harness

```powershell
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/AadityaMambulli/voxcode.git" voxcode ptt
```

On Windows, hold **F9**, speak, and release it. The transcript is typed into
the focused window. Enter is not pressed by default.

The first run downloads the local faster-whisper model. Later runs use the
cached snapshot. `voxcode ptt` loads the model once at startup and refuses to
download a missing model without asking first; use `voxcode ptt --yes` to
accept the download non-interactively.

### First-run model download

The `small` speech model is 486,215,847 bytes (486 MB / 463.7 MiB). It is downloaded once into
the Hugging Face cache, can resume after an interruption, and is the only
network use in the voice path. Audio and transcripts are not sent to the model
provider. Pre-download and verify it before opening Claude Code:

```powershell
uvx --from "voxcode[audio,stt,vad,mcp] @ git+https://github.com/OWNER/voxcode.git" voxcode download-model --model small
```

The command prints progress, the downloaded size and cache location, and then
loads the model locally with network access disabled to verify it. If you start
the Claude Code MCP server first, it begins the same background download and
temporarily returns a `downloading_model` status from `listen`.

## Per-harness setup

### Claude Code

Install the plugin using the commands above. Use `/voxcode:voice-setup` to
pre-warm the local model and configure audio, then `/voxcode:voice-on` to
enable voice mode. The plugin's MCP server is the recommended integration.

### Codex CLI

Install the package in the active environment and run the standalone listener:

```powershell
uv pip install "voxcode[audio,stt,vad,mcp]"
voxcode ptt
```

Codex-specific integration is untested; use PTT with the Codex prompt window
and keep `ptt_auto_submit = false`.

### Gemini CLI

Install the package and run `voxcode ptt` in a second terminal. Gemini CLI
integration is untested. The standalone PTT path does not require Gemini API
access or a voice API.

### OpenCode

Install the package and run `voxcode ptt` in a second terminal. OpenCode
integration is untested. An MCP configuration can be built around
`voxcode-mcp`, but this repository has only been tested with Claude Code.

## Configuration

The file location is shown by `voxcode config --path`. Environment variables
override file values.

| Setting | Default | Environment variable | Purpose |
|---|---:|---|---|
| `input_device_name` | OS default | — | Saved microphone name |
| `output_device_name` | OS default | — | Saved speaker name |
| `sample_rate` | `16000` | `VOXCODE_SAMPLE_RATE` | Requested capture rate |
| `channels` | `1` | `VOXCODE_CHANNELS` | Capture channels |
| `model` | `"small"` | `VOXCODE_MODEL` | Faster-whisper model |
| `compute_type` | `"int8"` | `VOXCODE_COMPUTE_TYPE` | CPU inference type |
| `vad_mode` | `"auto"` | `VOXCODE_VAD_MODE` | Auto-stop or fixed recording |
| `fixed_seconds` | `4.0` | `VOXCODE_FIXED_SECONDS` | Maximum/fixed recording duration |
| `silence_seconds` | `1.0` | `VOXCODE_SILENCE_SECONDS` | VAD trailing silence |
| `language` | auto-detect | `VOXCODE_LANGUAGE` | Optional language such as `en` |
| `voice_enabled` | `false` | `VOXCODE_VOICE_ENABLED` | Claude voice mode state |
| `ptt_key` | `"F9"` | `VOXCODE_PTT_KEY` | Function-key hotkey, F1-F24 |
| `ptt_mode` | `"hold"` | `VOXCODE_PTT_MODE` | `"hold"` or `"toggle"` |
| `ptt_auto_submit` | `false` | `VOXCODE_PTT_AUTO_SUBMIT` | Press Enter after typing |
| `ptt_beep` | `false` | `VOXCODE_PTT_BEEP` | Start/stop beep |
| `ptt_max_chars` | `2000` | `VOXCODE_PTT_MAX_CHARS` | Transcript typing cap |

## Troubleshooting

- **Microphone permission:** grant the terminal/Python permission to use the
  microphone in Windows Privacy settings, then run `voxcode doctor`.
- **Wrong device:** run `voxcode devices`; use `voxcode setup` to save a device
  by name. Device indexes can change after reconnecting hardware.
- **Unsupported Python:** use Python 3.10, 3.11, 3.12, or 3.13. Python 3.15
  does not have the required ctranslate2 wheels for the STT extra.
- **Slow first run:** the model is downloaded once and loaded locally. Use
  `voxcode doctor` and then wait for the model cache to finish.
- **F9 conflict:** choose another function key with `ptt_key = "F10"` or an
  environment override. Bare letter keys are rejected.
- **Elevated windows:** Windows security boundaries can prevent a non-elevated
  process from typing into an elevated target. Run both applications at the
  same elevation when appropriate.
- **Notepad versus terminals:** test first in Notepad. Terminals may interpret
  Unicode input, focus changes, or control characters differently. PTT never
  presses Enter unless explicitly enabled.

## Safety and support status

Voice input is untrusted input equivalent to typed text. PTT does not approve
permissions, execute commands, or press Enter by default. Audio is not saved
unless debugging is explicitly added.

This project has been tested only on Windows with Claude Code. macOS, Linux,
Wayland, Codex CLI, Gemini CLI, and OpenCode are untested. The non-Windows PTT
path reports that it is not supported yet rather than pretending to work.
