# voxcode

`voxcode` is a local-first voice mode for terminal coding agents. It uses local
audio, speech recognition, and speech output; it does not require an API key.

## Push-to-talk dictation

On Windows, start the long-running dictation listener:

```powershell
voxcode ptt
```

The default hotkey is **F9** in hold mode. Hold F9 while speaking, then release
it. voxcode records from the configured input device, transcribes with the
cached local faster-whisper model, and types the result into the currently
focused window using Unicode `SendInput`. It never presses Enter by default.

Configuration can be saved in the normal TOML config file:

```toml
[voxcode]
ptt_key = "F9"
ptt_mode = "hold"       # "hold" or "toggle"
ptt_auto_submit = false # set true only if Enter is wanted
ptt_beep = false
ptt_max_chars = 2000
```

`ptt_key` must be a function key (`F1` through `F24`); bare letter keys are
rejected so normal typing cannot accidentally start dictation. The STT model
is loaded once before the hotkey listener starts. PTT uses the local model
snapshot only and does not make a network request; run `voxcode listen` once
while online to populate the cache if needed.

### Safety

PTT types into whichever window is focused when the transcript is ready. Check
the target window before speaking, keep `ptt_auto_submit = false` unless
submitting is intentional, and treat the transcript as untrusted input. PTT
does not approve permissions or press Enter unless explicitly configured.

`voxcode doctor` reports whether the Windows hotkey can be registered. macOS,
Linux, and Wayland currently report that PTT is not supported yet and are
untested.
