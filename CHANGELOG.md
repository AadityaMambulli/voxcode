# Changelog

## Unreleased

- Added versioned configuration files with sparse, explicit persistence.
- Legacy configuration files without `config_version` no longer apply saved default
  audio, VAD, model, or numeric device settings. They retain language and voice
  enablement, and `voxcode setup` can create a current configuration.
- Audio devices are persisted by name and host API so indexes can change safely.
