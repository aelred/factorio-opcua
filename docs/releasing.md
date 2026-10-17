# Releasing

The mod and the bridge share one version: `mod/opc-io/info.json`,
`bridge/pyproject.toml` and `bridge/factorio_opc/__init__.py` must agree.
`python3 scripts/check-version.py` checks this, and CI runs it.

1. Bump the version in those three files (X.Y.Z, three numbers, as Factorio
   requires). If the RCON protocol changed, also bump `api.PROTO` in
   `mod/opc-io/lib/api.lua` and `PROTO` in `bridge/factorio_opc/game.py`.
2. Add a `## X.Y.Z` section to `CHANGELOG.md`; it becomes the release notes.
3. Commit, push, and wait for CI to pass on the default branch.
4. Tag and push:
   ```sh
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

The Release workflow then:
- checks that the tag matches the versions,
- runs the unit tests,
- builds `opc-io_X.Y.Z.zip` and the bridge's wheel and sdist,
- creates the GitHub release with those files attached.

Users install from the release:
- **The mod:** copy `opc-io_X.Y.Z.zip` into Factorio's `mods/` folder.
- **The bridge:** `pip install factorio_opc-X.Y.Z-py3-none-any.whl` (or
  `pipx install`).
- **Docker:** see `docs/docker.md`.
