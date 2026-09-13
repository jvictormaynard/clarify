# Contributor and agent guide

- Production Qt code and QML assets: `clarify/desktop/`.
- React/Tauri Settings: `desktop/`.
- Provider, storage, and workflow contracts: focused Python modules at the root.
- `app.py` and `spikes/` support legacy compatibility and historical measurements;
  do not add product features there or remove persisted-data migrations blindly.
- Read `CONTRIBUTING.md` and `docs/architecture.md` before structural changes.
- Use the pinned requirements and npm/Cargo lockfiles. Runtime Qt needs
  `PySide6-Essentials`, not the full `PySide6`/Addons distribution.
- Keep tests isolated from real profiles, microphones, provider keys and audio.
- Run Python unit tests and the relevant Settings tests after changes. Packaging
  changes also require the Windows build and embedded-payload checks.
- Never include `.env`, local configuration, keys or recordings in commits.
- A passing CI is not manual Windows acceptance. Follow the repository release
  procedure and document open gates before publishing.
