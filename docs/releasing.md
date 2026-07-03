# Releasing OTAmpy

OTAmpy publishes one version containing the host CLI and a generated,
read-only copy of the MicroPython device library and project templates. The
canonical device source remains in `packages/device`; never maintain a second
hand-copied bundle under `packages/cli`.

The release checker creates the bundle in a temporary staging directory. A
plain `uv build --package otampy` from the workspace does not perform this
staging and must not be used to create publishable artifacts.

## Prerequisites

- Install `uv`.
- Have permission to publish the `otampy` project to the chosen package
  registry.
- Configure a project-scoped registry token or trusted publishing.
- Ensure a compatible `urst` release satisfying
  `urst>=1.0.0,<2.0.0` is already available from that registry.
- Begin with the intended release commit checked out and a clean worktree.

URST must be published first. The root workspace's Git source override is a
development convenience and is not included in OTAmpy's published metadata.
The final OTAmpy release check deliberately resolves URST from the registry.

## 1. Choose the version

Use semantic versioning:

- patch: compatible bug fixes;
- minor: compatible features;
- major: incompatible CLI, project-layout, protocol, or device API changes.

The host CLI and bundled device code share this one OTAmpy version.

Read the current version:

```bash
uv version --project packages/cli
```

Set the intended version, for example:

```bash
uv version --project packages/cli 1.1.0 --no-sync
uv lock
```

`packages/cli/pyproject.toml` is the source of truth. `uv.lock` records the
workspace package version and is expected to change when the version changes.

## 2. Prepare the release commit

Review user-facing documentation and release notes, then inspect the changes:

```bash
git diff --check
git status --short
```

Commit the version and release notes:

```bash
git add packages/cli/pyproject.toml uv.lock docs README.md
git commit -m "chore(release): prepare v1.1.0"
```

The release checker is strict by default and requires this clean worktree.

## 3–7. Run the automated release gate

From the repository root:

```bash
uv run python scripts/release_check.py
```

This single command:

1. runs `uv run ruff check .`;
2. runs the complete pytest suite;
3. stages `packages/cli` and copies only the canonical device library,
   `boot.py`, `main.py`, and `config.example.py` into a temporary package;
4. builds the sdist and wheel with workspace source overrides disabled;
5. inspects both archives for every expected device file and checks its hash
   against the canonical source;
6. rejects `config.py`, bytecode caches, the maintainer's home directory, and
   repository paths in the artifacts;
7. installs the wheel and its registry dependencies into a clean temporary
   virtual environment, runs `otampy init`, and runs
   `otampy deploy --dry-run --no-mip` against the new project.

Verified artifacts are left in `release-dist/`. Temporary staging,
installation, and sample-project directories are automatically removed.

Before publishing URST, OTAmpy can be fully preflighted against an explicit
local URST checkout:

```bash
uv run python scripts/release_check.py \
  --urst-source /path/to/urst-mpy
```

This option is for preflight only. The final check before publishing OTAmpy
must omit `--urst-source`; otherwise registry dependency resolution has not
been verified.

`--allow-dirty` exists only for developing the release checker. Do not use it
for a real release.

## 8. Inspect and publish

Confirm that `release-dist/` contains exactly one wheel and one source
distribution for the intended version:

```bash
find release-dist -maxdepth 1 -type f -printf '%f\n'
```

Publish those verified files:

```bash
uv publish release-dist/*
```

Supply credentials through trusted publishing, `UV_PUBLISH_TOKEN`, or uv's
supported authentication options. Never put a token in this repository or a
command committed to shell history.

Package versions are immutable after publication. If anything is wrong, fix
it, choose a new version, rerun the complete gate, and publish that version.

## 9. Verify the registry release

Use an isolated tool environment so the repository checkout cannot influence
the result:

```bash
uvx --refresh --from "otampy==1.1.0" otampy --help
```

In a temporary project, also verify the consumer workflow:

```bash
mkdir /tmp/otampy-release-verification
cd /tmp/otampy-release-verification
uv init
uv add "otampy==1.1.0"
uv run otampy init
uv run otampy deploy --dry-run --no-mip
```

The dry run must refer to the temporary project's `device/` files and the
installed `otampy/_device/lib` bundle, never this repository.

## 10. Tag the verified release

Return to the repository, create an annotated tag at the release commit, and
push it:

```bash
git tag -a v1.1.0 -m "OTAmpy 1.1.0"
git push origin develop
git push origin v1.1.0
```

Create the corresponding hosting-platform release and attach or link the
release notes. Do not attach artifacts built by any route other than
`scripts/release_check.py`.

## If the gate fails

- Missing URST from the registry: publish the compatible URST release first.
- Dirty worktree: commit or stash the changes, then rerun.
- Missing or mismatched bundle file: fix the canonical file under
  `packages/device`; do not edit generated staging content.
- Home/repository path detected: remove the machine-specific value from the
  source or build configuration.
- Clean-install or dry-run failure: treat it as a release blocker. Do not
  bypass the failing check.
