# Channel-mux scaffold: direct-by-default + separate mux example set — spec

**TODO item:** `[ ] 3. Scaffold direct-by-default + separate mux example set.` (under
"Channel-mux mode: opt-in on both ends" in `TODO.md`)
**Status:** approved
**Components:** `src/otampy/` (host CLI: `cli.py`), `src/otampy/device/examples/` (device scaffold), docs
**Dev log:** `docs/development/channel-mux-scaffold-log.md` (created by `/sl-build`)

## Goal

After this ships, a fresh `otampy init` followed by `otampy deploy` produces a
working device: `otampy ping` returns `PONG` with no flags. The shipped
`boot.py`/`main.py` scaffold is **direct mode** again — `OTA` owns the raw UART,
no outer channel frame — matching the CLI's own default. The shared-UART
(`SerialMux`) pattern still ships, but as a **separate, opt-in example set**
selected with `otampy init --mux`, and its `boot.py`/`main.py` keep `SerialMux`.
`protocol.md`, `architecture.md`, `README.md`, `src/otampy/device/README.md` and
`CHANGELOG.md` describe the two scaffolds and the end-to-end mux feature
(sub-tasks 1 + 2 + 3) accurately, with no lingering pre-`6f2bd1b` claims.

## In scope

- Restore `src/otampy/device/examples/boot.py` and `main.py` to direct mode
  (byte-identical to `6f2bd1b~1` — there have been no non-mux changes to either
  file since).
- New `src/otampy/device/examples/shared-uart/` set: `boot.py`, `main.py`,
  `configota.example.py` — the current mux versions of `boot.py`/`main.py`
  relocated here, plus a config template.
- `pyproject.toml` package-data glob widened so the subdirectory ships in the
  wheel.
- `otampy init --mux / --no-mux` flag; when neither is given in an interactive
  run, a `y/N` prompt. `--mux` sources the three files from `shared-uart/`.
  Default (no flag, non-interactive) stays direct.
- A syntax/`ast.parse` smoke test over every file in both example sets, plus
  assertions that the default set never references `SerialMux`/`mux.` and the
  `shared-uart` set always does.
- Docs: `protocol.md` §1.1/§1.3 wording check, `architecture.md` Integration
  Guide (add a short "Sharing the UART" subsection), `README.md` (tree, `init`
  section, options table), `src/otampy/device/README.md`, and a new
  `## [Unreleased]` `CHANGELOG.md` section covering sub-tasks 1 + 2 + 3.

## Out of scope

- Any wire-format or URST change — the frame contract was settled and built in
  sub-tasks 1 and 2; this sub-task ships no new bytes on the wire.
- Exposing channel ids / `min_tx_gap_ms` as CLI options — device defaults
  suffice (deferred, noted in `channel-mux-cli-mode-log.md`).
- `deploy` gaining a shared-UART mode — `deploy` is direct-only raw-port human
  provisioning by the signed-off protocol decision; the repo fallback in
  `deploy._resolve_deploy_paths` keeps reading the flat `examples/*.py`.
- Reconciling the flat `examples/configota.py` (deploy fallback, carries
  `OTA_JOURNAL_FILE`) vs `examples/configota.example.py` (init source)
  divergence — pre-existing, unrelated to this task.
- Consolidating `diff-drive-robot/gateway/src/mux_host.py` onto the host codec —
  tracked in that repo's `TODO.md`.

## Protocol decision

Already signed off (2026-09-08, in `TODO.md`): no URST change; the mux is a
framing layer *below* URST; `COBS(channel_id ‖ inner_URST_frame) ‖ 0x00`;
channel 0 = OTA/URST, channel 1 = application (best-effort); direct mode is the
default on both ends; `deploy` stays direct-only. Sub-tasks 1 and 2 implemented
and documented it (`docs/protocol.md` §1.3, `src/otampy/channel.py`, the `--mux`
CLI wiring). **This sub-task adds no new protocol surface** — it only changes
which scaffold `init` writes and aligns the docs. No further sign-off required.

## Data and contracts

- **`src/otampy/device/examples/` (flat) = the direct-mode default set.**
  Consumed by `otampy init` (via `configota.example.py`) and by
  `deploy._resolve_deploy_paths`'s repo fallback (`boot.py`, `main.py`,
  `configota.py`). **Load-bearing:** these two consumers both read the flat
  files by fixed name; the revert must not rename or move them.
- **`src/otampy/device/examples/shared-uart/` = the opt-in mux set.** Contains
  `boot.py`, `main.py`, `configota.example.py`. `boot.py`/`main.py` **must**
  keep `from otampy.mux import SerialMux` and `OTA(mux.ota_port, …)` (explicit
  TODO requirement). Byte-identical framing to today's shipped mux scaffold, so
  existing mux users are unaffected.
- **`pyproject.toml` `[tool.setuptools.package-data]`:** `otampy =
  ["device/examples/*.py"]` → `["device/examples/*.py",
  "device/examples/shared-uart/*.py"]` (or `device/examples/**/*.py`).
  **Load-bearing:** without this, `otampy init --mux` works from a repo checkout
  but raises for pip-installed users because
  `importlib.resources.files("otampy").joinpath("device","examples","shared-uart", …)`
  is not packaged. The init test must exercise the packaged-resource path.
- **`otampy init` flag:** `--mux / --no-mux` (Click `is_flag` pair, default
  `None`). Resolution: explicit flag wins; else if `stdin.isatty()` prompt
  `Shared UART (channel-mux) mode? [y/N]`; else direct. No config key, no env
  var — `init` is a one-shot scaffold action, not a persistent mode (unlike the
  CLI's `mux` setting from sub-task 2).
- No new `configota.py` settings. The `shared-uart` `configota.example.py` may
  carry a commented `# mux = SerialMux(uart, min_tx_gap_ms=20)  # see CHANGELOG`
  hint but sets nothing by default.

## Device cost

Device-facing, but scaffold code only — no library hot path changes.

- The reverted default `main.py` loop drops the per-tick `mux.service()` call
  and the `mux.poll_app()` in `do_application_stuff` — it is *cheaper* than the
  current shipped default (one fewer method call and buffer scan per ~100 ms
  tick), and identical to the pre-`6f2bd1b` loop that ran in production.
- The `shared-uart` `main.py` is byte-identical to today's shipped mux loop —
  no change to its cost.
- No new constants. Channel ids remain `mux.DEFAULT_OTA_CHANNEL` /
  `DEFAULT_APP_CHANNEL` on the device.
- No new blocking operations; watchdog interaction unchanged.

## Build steps

- [ ] **1. Split the scaffold: direct default + `shared-uart/` set**
  - What changes:
    - `src/otampy/device/examples/boot.py`, `main.py` → restore to
      `git show 6f2bd1b~1:…` content (direct mode).
    - New `src/otampy/device/examples/shared-uart/boot.py`, `main.py` → the
      current (mux) content of those two files, moved verbatim.
    - New `src/otampy/device/examples/shared-uart/configota.example.py` → copy
      of the flat `configota.example.py` plus a commented `min_tx_gap_ms` hint.
    - `pyproject.toml` package-data glob widened for the subdirectory.
    - New `tests/test_examples.py`: `ast.parse` every `*.py` under both example
      dirs; assert the flat `boot.py`/`main.py` contain neither `SerialMux` nor
      `mux.`; assert both `shared-uart` scripts contain `SerialMux` and
      `mux.ota_port`.
  - Test: `tests/test_examples.py` (new).
  - Done when: `uv run pytest tests/test_examples.py` passes;
    `grep -R "SerialMux" src/otampy/device/examples/*.py` is empty;
    `grep -l "SerialMux" src/otampy/device/examples/shared-uart/{boot,main}.py`
    lists both.

- [ ] **2. `otampy init --mux` selects the shared-UART set**
  - What changes:
    - `src/otampy/cli.py` `init`: add `--mux/--no-mux` flag (default `None`);
      resolve to a boolean (flag → prompt if TTY → `False`); when true, source
      the three files from the `shared-uart` package resource instead of the
      flat one. `configota.example.py` still lands as `configota.py`. Console
      output states which scaffold was written.
    - `tests/test_cli.py`: `test_init_mux_flag_scaffolds_shared_uart` (asserts
      `SerialMux` in the generated `boot.py`), `test_init_default_is_direct_mode`
      (asserts it is not), `test_init_mux_prompt_yes` (interactive `input=`).
  - Test: `tests/test_cli.py` (additions).
  - Done when: `otampy init --mux <dir>` writes a `boot.py` containing
    `SerialMux`; `otampy init <dir>` (no flag, non-interactive) writes one that
    does not; the new tests pass under `uv run pytest`; the init test resolves
    the file through `importlib.resources` (packaged path), not a repo-relative
    path.

- [ ] **3. Documentation + CHANGELOG**
  - What changes:
    - `docs/protocol.md`: confirm §1.1 / §1.3 read correctly now that the
      default scaffold is direct (the text already claims this — verify, adjust
      the "the shipped `boot.py`/`main.py` scaffold both do" clause and the §1.1
      "This is the pattern the shared-UART example set uses" line, and reference
      `otampy init --mux`).
    - `docs/architecture.md`: the Integration Guide already shows direct-mode
      `OTA(uart, …)` — add a short **"Sharing the UART with application code"**
      subsection pointing at `otampy init --mux`, the `shared-uart/` set and
      `protocol.md` §1.3.
    - `README.md`: update the `examples/` line in the layout tree; the `init`
      section (mention `--mux`); the command table row for `init`; ensure the
      "Shared-UART (channel-mux) mode" bullet references `init --mux`.
    - `src/otampy/device/README.md`: note the two example sets and when to pick
      the mux one.
    - `CHANGELOG.md`: new `## [Unreleased]` section covering the whole
      channel-mux feature — the host `ChannelCodec`/`ChannelSerial` (sub-task 1),
      the `--mux`/`OTAMPY_MUX`/`mux` config/`otampy mux` command (sub-task 2),
      this scaffold split (sub-task 3), and a **Compatibility** note: a device
      deployed from the `6f2bd1b` mux scaffold with a plain CLI was silently
      timing out; recover by either `otampy --mux …` / `otampy mux --enable`, or
      re-running `otampy init` (no `--mux`) + `otampy deploy` for direct mode.
  - Test: none — documentation. (Run the repo's markdown/lint step if any.)
  - Done when: `grep -RnE "double-wrap|pre-6f2bd1b|routes to an unknown channel"
    docs README.md` finds only historical/dev-log context, not current
    guidance; `CHANGELOG.md` has an `[Unreleased]` block naming all three
    sub-tasks; `architecture.md` mentions `otampy init --mux`.

## Verification

- **Host:** `python3 .agents/scripts/pre_flight_check.py` (or the repo's
  equivalent — `uv run pytest` + `ruff`) green after each step. Per-step:
  `uv run pytest tests/test_examples.py tests/test_cli.py -k init`.
- **Packaging:** `uv build` then, in a scratch venv,
  `python -c "import importlib.resources as r;
  print(r.files('otampy').joinpath('device','examples','shared-uart','boot.py').read_text()[:40])"`
  — proves the subdir ships.
- **Hardware (Simon, one pass):** from a clean checkout —
  1. `otampy init /tmp/otderdir` (no flag) → `otampy deploy --device-dir /tmp/otderdir`
     → hard `mpremote connect PORT reset`, let it settle → `otampy ping` returns
     `PONG` with **no** `--mux`.
  2. `otampy init --mux /tmp/otmux` → deploy → reset + settle →
     `otampy ping` times out (silent, expected) but `otampy --mux ping` returns
     `PONG`.
  Follow the `CLAUDE.md` USB/mpremote reset+settle discipline; verify via the
  real radio/OTA link, not more USB pokes.
- **Manual:** `otampy init --mux` then read the generated `boot.py` — it must
  still say `SerialMux` and `OTA(mux.ota_port, …)`.

## Risks and open questions

- **`--all-files` deploy sweep.** `deploy._all_user_deploy_entries` would
  include a `shared-uart/` subdirectory if a user pointed `--device-dir` at
  `src/otampy/device/examples` *and* passed `--all-files`. Dev-only path; note
  it in the build log, don't fix here (that flat dir is a repo fallback, not a
  user project).
- **Prompt in `init`.** `init` already has one interactive prompt (project
  directory). Adding a second must not break the non-interactive `runner.invoke`
  tests that pass an explicit path — gate the prompt on `stdin.isatty()` and
  cover both branches.
- **Existing mux deployments.** Devices flashed from the `6f2bd1b` scaffold keep
  running mux after this change; the only fix is CLI-side (`--mux`) or a
  re-init. The CHANGELOG Compatibility note is the mitigation — make it
  explicit.
- **`configota` template drift.** The `shared-uart/configota.example.py` starts
  as a copy of the flat one; if the flat template later changes, both must move
  together. Note in `src/otampy/device/README.md`.

## Notes for the build

- The revert is exactly `git show 6f2bd1b~1:src/otampy/device/examples/boot.py`
  and `…/main.py` — verified there are **no** non-mux commits touching either
  file since `6f2bd1b`.
- Findings ledger is `MERGE CLEAR` (F-01..F-03 closed); nothing outstanding in
  this area.
- Related: `docs/development/channel-mux-opt-in-log.md` (sub-task 1),
  `docs/development/channel-mux-cli-mode-log.md` (sub-task 2 — its closing note
  explicitly says sub-task 3 "must keep the shared-UART `boot.py` on
  `SerialMux`").
- `otampy init` copies via `importlib.resources.files("otampy").joinpath(
  "device", "examples", …)` today (`cli.py:3089`); extend that join with the
  `shared-uart` segment when `--mux` is set rather than introducing a second
  resource lookup pattern.
- The device examples are not currently syntax-checked anywhere; step 1's
  `tests/test_examples.py` closes that gap for both sets at once.

## What the critique changed

- Merged the planned "revert" and "add shared-uart set" into one step — the mux
  content simply relocates, so it is one coherent move with a still-readable
  diff, and splitting them would leave step 1 with a scaffold that matches
  neither mode cleanly.
- Added the `pyproject.toml` package-data glob as an explicit **load-bearing**
  contract item and a packaging verification step — it is the one easy-to-miss
  change that passes in-repo and breaks for pip users.
- Added the `--all-files` deploy-sweep edge case and the `init` double-prompt
  risk after walking `deploy.py` and the existing `init` tests.
- Added the CHANGELOG **Compatibility** note as a named done-when: without it,
  users with a `6f2bd1b` mux device get no guidance on why `ping` still fails.
- Confirmed no protocol sign-off gate is needed — the wire contract was settled
  in sub-tasks 1/2 and this ships no new bytes — so the spec cites the decision
  rather than re-opening it.
