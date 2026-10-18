# Security

## Reporting a vulnerability

Please do not disclose exploitable details in a public issue. Contact the
maintainers privately with the affected version, reproduction steps, impact,
and a proposed mitigation if available.

## Voice and typing safety

Voice input is untrusted input and must be treated like typed input. voxcode
never auto-approves permissions. Push-to-talk types into the currently focused
window and does not press Enter by default. Users should confirm the target
window before speaking and should avoid using non-elevated voxcode to type into
an elevated application.

voxcode does not send audio or transcripts to a telemetry service. Audio is
not written to disk unless an explicit debugging feature is added.
