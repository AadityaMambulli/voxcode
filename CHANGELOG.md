# Changelog

## Unreleased

- Added cross-harness push-to-talk dictation with configurable function-key
  activation and safe no-auto-submit defaults.
- MCP model preload now uses cached model snapshots with local-only loading, so
  a running MCP server does not initiate a model download during `listen`.
- Added versioned configuration files with sparse, explicit persistence.
- Legacy configuration files without `config_version` no longer apply saved default
  audio, VAD, model, or numeric device settings. They retain language and voice
  enablement, and `voxcode setup` can create a current configuration.
- Audio devices are persisted by name and host API so indexes can change safely.
