# voxcode implementation plan

Status: M3 implementation complete. M4 documentation and CI work remains out of
scope for this milestone.

## Project goal

Build `voxcode`, a local-first voice mode for terminal coding agents:

- Python package and CLI, using the existing `.venv` and no global Python changes.
- Real microphone, speech-to-text, and speech output on Windows first.
- Claude Code plugin and stdio MCP server sharing the same core implementation.
- No telemetry, API keys, paid APIs, or audio persistence unless debugging is enabled.
- Voice input is untrusted text and must never approve permissions automatically.

## Repository and runtime decisions

- Keep all files under the repository root, which was verified as
  `C:\Users\mambu\OneDrive\Desktop\MyProjects\voxcode`.
- Use a `src/voxcode/` Python package and a `pyproject.toml` console-script entry
  point named `voxcode`.
- Keep the package's base dependencies small; put speech recognition dependencies
  behind a `stt` extra.
- Set the STT-supported Python range to `>=3.10,<3.14`. `doctor` will report an
  explicit warning/failure for unsupported Python versions rather than silently
  attempting an incompatible install.
- Use TOML in the platform user configuration directory, with environment variables
  taking precedence over file values. Never hardcode a user or repository path.
- Use the configured device when available, then the OS default, then the first
  available device.
- Use the OS default input/output devices when no device is configured. `voxcode
  devices` will show one host API (WASAPI on Windows), `doctor` will report the
  chosen defaults, and `setup` will provide optional saved device selection.
- Keep microphone capture scoped to an explicit `listen` operation and display a
  visible recording indicator.
- Implement real backends by default. Test fakes are available only through an
  explicit `--fake` test/CI path; hardware tests use a separate `hardware` marker.
- TTS selection is an ordered fallback: Piper, Windows SAPI, macOS `say`, then
  `espeak-ng`. The selected engine and the reason for fallback will be reported.
- The default STT model is `small`, CPU `int8`, downloaded on first use with visible
  progress.
- STT models are loaded lazily, cached models are silent by default, and a shared
  server engine remains in memory for the server lifetime. `--verbose` enables
  cached-model loading timing.
- STT language defaults to auto-detect and can be pinned through configuration,
  `VOXCODE_LANGUAGE`, setup, or MCP configuration.
- Use one shared core service for CLI and MCP so device selection, state, VAD,
  timing, errors, and TTS reporting do not diverge.
- Use WebRTC VAD for auto-stop when the `vad` extra is installed, with the
  configured fixed-seconds duration as an automatic fallback when VAD is
  unavailable. The maximum listen duration remains bounded.
- VAD also has a bounded initial-silence timeout and an energy gate so ambient
  microphone noise does not keep an otherwise silent listen open indefinitely.
- Use a relative marketplace plugin source (`./plugins/voxcode`) so
  `/plugin marketplace add ./` works before the repository is hosted. A GitHub
  owner is therefore not needed for local validation. If a hosted source later
  requires an owner placeholder, use exactly one clearly marked placeholder and
  replace it with `scripts/set_owner.py`; do not hardcode an owner in local setup.

## Verified Claude Code documentation

The source index was fetched first:

- [Claude Code documentation index](https://code.claude.com/docs/llms.txt)

The index-listed pages and linked reference pages were fetched and read:

- [Plugins overview](https://code.claude.com/docs/en/plugins/overview.md)
- [Create a plugin](https://code.claude.com/docs/en/plugins/create.md)
- [Add plugin components](https://code.claude.com/docs/en/plugins/components.md)
- [Create a marketplace](https://code.claude.com/docs/en/plugins/create-marketplace.md)
- [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference.md)
- [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference.md)
- [Install and manage plugins](https://code.claude.com/docs/en/plugins/install.md)
- [Publish and distribute a plugin](https://code.claude.com/docs/en/plugins/publish.md)
- [Skills](https://code.claude.com/docs/en/skills.md)
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide.md)
- [Hooks reference](https://code.claude.com/docs/en/hooks.md)
- [MCP reference](https://code.claude.com/docs/en/mcp.md)
- [MCP quickstart](https://code.claude.com/docs/en/mcp-quickstart.md)

The pages were retrieved on 2026-10-16. Claude Code can change independently of
voxcode, so M3's validator will use the installed Claude CLI as the authoritative
runtime check in addition to these documented rules.

## Verified marketplace schema

Source: [Create a marketplace](https://code.claude.com/docs/en/plugins/create-marketplace.md)
and [Marketplace reference](https://code.claude.com/docs/en/plugins/marketplace-reference.md).

`<marketplace-root>/.claude-plugin/marketplace.json` is the marketplace file.
The documented required top-level fields are:

- `name`
- `owner`
- `plugins`

The documented example establishes these shapes:

```json
{
  "name": "my-marketplace",
  "description": "Plugins for my team",
  "owner": {
    "name": "Your Name"
  },
  "plugins": [
    {
      "name": "my-first-plugin",
      "source": "./plugins/my-first-plugin",
      "description": "A greeting plugin to learn the basics"
    }
  ]
}
```

Verified plugin-entry facts:

- Each entry requires `name` and `source`.
- `description` is a supported entry field.
- A relative path is resolved from the marketplace root, not from
  `.claude-plugin/`; `./plugins/voxcode` is therefore the correct local layout.
- Relative paths containing `..` fail validation.
- Other documented source types include `github`, `git-subdir`, `url`, `archive`,
  `npm`, and `command`; remote source fields will not be used for local testing.
- The marketplace entry name and the plugin manifest name should be identical.
- `claude plugin validate ./` validates JSON, required fields, and plugin entries.
- Local installation is documented as:
  `claude plugin marketplace add ./`
  followed by
  `claude plugin install voxcode@voxcode`.

The complete field table for every marketplace metadata and source field was not
needed for the local relative-source design; M3 will validate only fields used by
voxcode and record the installed Claude CLI version.

## Verified plugin manifest schema

Source: [Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference.md).

The manifest is optional, but when present it is
`.claude-plugin/plugin.json` under the plugin root. Other components stay at the
plugin root, not inside `.claude-plugin/`.

Verified top-level facts:

- `name` is the only required manifest field and should be kebab-case.
- Supported metadata fields include `displayName`, `version`, `description`,
  `author`, `homepage`, `repository`, `license`, `keywords`, `metadata`, and
  `defaultEnabled`.
- `author` requires `name` and may include `email` and `url`.
- Component fields include `skills`, `commands`, `agents`, `hooks`, `mcpServers`,
  `lspServers`, and `outputStyles`; the manifest reference defines their accepted
  path/object forms.
- Plugin component paths are relative to the plugin root and must remain inside it.
- `hooks` may be a JSON path, inline event map, or an array of those forms.
  A hooks file has a top-level `hooks` wrapper; inline configuration does not.
- `mcpServers` may be a JSON path, bundle path/URL, inline map, or an array.
  A plugin can also use root `.mcp.json`; later server declarations replace earlier
  declarations with the same name.
- `${CLAUDE_PLUGIN_ROOT}` is the documented stable way for plugin components to
  refer to files shipped by the plugin.
- `claude plugin validate <plugin-directory>` is the authoritative manifest check;
  `--strict` turns warnings into failures.

Planned manifest shape (to be implemented and validated in M3):

```json
{
  "name": "voxcode",
  "version": "0.1.0",
  "description": "Local-first voice mode for coding agents",
  "author": {
    "name": "voxcode maintainers"
  },
  "license": "MIT",
  "skills": "./skills/",
  "commands": "./commands/",
  "hooks": "./hooks/hooks.json",
  "mcpServers": "./.mcp.json"
}
```

The exact final metadata will be checked with the installed CLI before M3 is
declared complete.

## Verified skill schema and layout

Source: [Skills](https://code.claude.com/docs/en/skills.md) and
[Add plugin components](https://code.claude.com/docs/en/plugins/components.md).

- A skill is `<plugin>/skills/<skill-name>/SKILL.md`.
- `SKILL.md` has YAML frontmatter between `---` markers and Markdown instructions.
- `description` in frontmatter tells Claude when to load the skill.
- The skill can also be invoked directly; plugin skills are namespaced as
  `/voxcode:<skill-name>`.
- New work should use skills rather than the older flat `commands/` form, though
  command files remain supported.
- Plugin skills are available wherever the plugin is enabled.

Decision: ship one voice-mode skill with short spoken-reply rules, code/path
redaction, text confirmation for destructive actions, and a post-task `listen`
instruction when voice mode is on. Slash-command UX will use the documented
plugin command/skill namespace rather than assuming unverified global commands.

## Verified hook schema and Stop behavior

Source: [Hooks guide](https://code.claude.com/docs/en/hooks-guide.md),
[Hooks reference](https://code.claude.com/docs/en/hooks.md), and the plugin
manifest reference.

- Hook configuration is an event-name map under a top-level `hooks` object in a
  hooks file.
- Each event maps to matcher groups containing a `matcher` and a `hooks` array.
- A command handler uses `"type": "command"` and a command string.
- `Stop` is a documented lifecycle event fired when Claude finishes responding.
- Plugin hooks are packaged in `hooks/hooks.json` or through the manifest's
  `hooks` field.
- Hook commands receive JSON on stdin according to the hooks reference and can
  be implemented as platform-appropriate executables.

Decision: the Stop hook will invoke a repository-shipped cross-platform Python
helper through the plugin root, strip Markdown/code/secrets before calling
`voxcode speak`, and fail visibly if the helper cannot run. It will not infer
permissions or approve actions. M3 must verify the exact Stop input fields against
the installed Claude CLI and hook reference before relying on them.

## Verified MCP schema and transport decision

Source: [MCP reference](https://code.claude.com/docs/en/mcp.md),
[MCP quickstart](https://code.claude.com/docs/en/mcp-quickstart.md), and
[Plugin manifest reference](https://code.claude.com/docs/en/plugins/manifest-reference.md).

- Local stdio MCP servers are supported and run as local processes.
- The CLI form is `claude mcp add [options] <name> -- <command> [args...]`;
  the `--` separates Claude options from server arguments.
- Plugin-provided MCP configuration can be a root `.mcp.json` or a manifest
  `mcpServers` declaration.
- Plugin MCP command arguments may use `${CLAUDE_PLUGIN_ROOT}`.
- Claude Code supplies `CLAUDE_PROJECT_DIR` to spawned local stdio servers.

Decision: ship a root `.mcp.json` that launches the Python module via the
repository/plugin environment without hardcoded absolute paths. The server will
expose exactly `listen(timeout_s)`, `speak(text, interrupt=false)`,
`stop_speaking()`, `voice_status()`, and `voice_config(...)`, all routed through
the shared core.

## Documentation limitations and unverified items

M3 launch decision: the plugin's `.mcp.json` uses `uvx` with a PEP 508 Git
dependency and the `audio`, `stt`, `vad`, and `mcp` extras. The repository owner
is the single `__GITHUB_OWNER__` placeholder, replaced by
`scripts/set_owner.py` before a GitHub release. This avoids requiring a
stranger's local `.venv` after the repository is published. Claude's
`${CLAUDE_PLUGIN_ROOT}` is verified for files shipped inside the copied plugin,
but the fetched docs do not verify `uvx` behavior or guarantee that a
marketplace copy contains the marketplace root and its `src/` tree; that
networked launch was not run here.

M3 local-development decision: `scripts/dev_mode.py on` rewrites the plugin MCP
and Stop-hook commands to absolute paths inside this checkout's `.venv`;
`scripts/dev_mode.py off` restores the committed uvx launch exactly. The
repository validator refuses to pass while the dev marker exists. For a
first networked launch, Claude Code's documented `MCP_TIMEOUT` environment
variable can be set to `120000` milliseconds, and `voxcode doctor` is the
documented pre-warm command. Heavy audio and STT imports remain inside
`create_server`; the top-level MCP module only imports the protocol server
wrapper, so model loading remains lazy until the first `listen` call.

Fix K hook behavior: Stop summaries use the first final-response paragraph,
remove configurable boilerplate labels (defaulting to `Skipped`, `Risk`,
`Verified`, `Note`, and `Next`), and cap spoken text at approximately 200
characters on a sentence boundary. The hook writes metadata-only JSONL when
`VOXCODE_HOOK_LOG` is set and uses a 30-second command timeout. The official
hooks reference fetched for this milestone documents hook configuration and
async behavior but did not state a default timeout or process-lifetime
guarantee; the timeout is therefore explicit in the plugin configuration.

These are intentionally not presented as verified:

1. `https://code.claude.com/docs/en/plugins/marketplaces.md` returned HTTP 404.
2. `https://code.claude.com/docs/en/plugins/reference.md` returned HTTP 404.
   The actual index-linked pages are `create-marketplace.md`,
   `marketplace-reference.md`, and `manifest-reference.md`, which were used
   instead.
3. The docs do not establish which installed Claude Code versions support every
   newest manifest field, so M3 will run the local installed CLI validator and
   avoid optional fields unless validated.
4. The fetched docs identify the Stop event and stdin JSON contract, but this
   research pass did not establish a stable field that represents the complete
   final assistant reply across all Claude Code versions. M3 will inspect the
   current hooks reference/CLI behavior and use only verified fields.
5. No claim is made here that Claude Code itself, Piper, faster-whisper, or any
   audio device works; those are M1/M2 runtime tests and must be reported with
   real command output.

## Milestone execution order

### M1: audio core and CLI

Implement configuration, device enumeration/selection, real sounddevice capture,
VAD plus fixed-duration mode, faster-whisper STT, TTS fallback engines, voice
state, and the `devices`, `speak`, `listen`, `test`, `doctor`, `setup`, `config`,
and `voice on|off` commands. Add fake unit tests and `-m hardware` tests.
Run all feasible tests and quote actual output, then stop for manual commands.

### M2: MCP

The stdio server and all five tools are implemented in `voxcode-mcp`. The
end-to-end fake-backend stdio test calls every tool, and a hardware-marked test
launches the real server and exercises TTS. Stop after real test output.

### M3: Claude Code plugin

Add commands/skills, the Stop hook, `.mcp.json`, manifests, and
`scripts/validate_manifests.py`. Validate locally with the installed Claude CLI,
test `/plugin marketplace add ./`, and provide exact install expectations. Stop.

### M4: documentation and CI

Add the README, MIT license, contribution/community/security documents, changelog,
templates, and GitHub Actions for Ruff, mypy, pytest with `--fake` on Linux/macOS/
Windows, and manifest validation. Stop.

### M5: experimental wrapper

Add `voxcode-wrap` for non-MCP harnesses, clearly labeled experimental, with no
change to the supported MCP/plugin path.
