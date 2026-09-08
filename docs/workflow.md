# Development workflow

The end-to-end loop for doing work in this repo, and the skills that enforce it.

`docs/Project-Skills.md` documents each skill in detail. This document is about
the *order* they go in, what each gate is for, and what the durable artefacts
are. Read this first; read that one when you need a specific skill's flags and
output.

All skills are prefixed `sl-` and invoked as `/sl-<name>`.

---

## The short version

```
TODO.md item
    │
    ▼
/sl-spec ──────────► docs/development/<slug>-spec.md
    │                                    ▲
    │  ◄── review gate: Simon approves ──┘
    ▼
/sl-build ─────────► one step │ test first │ diff │ explain │ prove │ approve
    │                         └── repeat until every step is ticked ──┘
    │
    ▼
review (/code-review, /security-review, /sl-micropython-nasa-power-of-ten)
    │
    ▼
/sl-findings ──────► docs/development/findings.md
    │                open or fixed P0/P1 blocks the merge
    ▼
/sl-ready-to-commit ──► /sl-commit ──► git flow feature finish
```

Nothing skips a gate to save time. The gates are the reason the loop exists.

---

## Durable artefacts

State lives in files, not in a conversation. Every one of these survives a
cleared context, and every one of them is the reason a session can be resumed
rather than restarted.

| File | Owner | What it holds |
| --- | --- | --- |
| `TODO.md` | Simon | Every outstanding task, in priority order. The source of truth for implementation status. |
| `docs/development/<slug>-spec.md` | `/sl-spec`, then Simon | What we agreed to build: scope, protocol decision, build steps, how it gets proven. |
| `docs/development/<slug>-log.md` | `/sl-build` | What actually happened: measurements, theories tried and spent, dead ends. One log per task. |
| `docs/development/findings.md` | `/sl-findings` | Confirmed defects with permanent IDs, severity and status. |
| `docs/architecture.md` | Simon | Authoritative design: protocol, mux, boot/update, process boundaries. |
| `docs/configuration.md` | Simon | Every environment variable and config setting across all three components. |
| `CHANGELOG.md` | whoever ships | User-visible changes and decisions worth keeping. |

Rule of thumb: if the next session would have to rediscover it, it belongs in a
file before the session ends.

---

## Phase 1 — Spec

**`/sl-spec "<TODO item>"`**

Takes one `TODO.md` item and turns it into `docs/development/<slug>-spec.md`.

What it does that matters:

- **Sizes the work and splits it.** Anything spanning robot + gateway +
  dashboard is almost always too big for one spec; it gets split along the
  component boundary with the contract between them as the first sub-task.
- **Settles the protocol decision first, and stops for sign-off.** For anything
  robot-facing: can an existing OTAmpy/URST command carry this? If not, which
  channel and why? This is the one decision that is expensive to unwind after
  code exists, so it is signed off on its own, before the rest of the spec is
  even written.
- **Writes small build steps**, each naming its test and an observable "done
  when" that `/sl-build` can actually check.
- **Red-teams its own draft** before Simon sees it, and reports what the
  critique changed.

Ends at a review gate. Simon edits the spec file directly; the spec is the
contract, so it is worth arguing with at this stage rather than mid-build.

**Skip the spec** for a change small enough to show and explain in one diff. The
loop is for work that needs it, not ceremony for its own sake.

---

## Phase 2 — Build

**`/sl-build`**

Creates the `git flow` feature branch and works the spec's steps in order, one
at a time. Per step:

1. **Test first** (`.agents/AGENTS.md` mandates TDD) — watch it fail for the
   right reason.
2. **Implement just that step** — the smallest change that satisfies its
   "done when".
3. **Show the diff**, not the files.
4. **Explain and prove** — one line per changed file, plus the actual evidence
   the "done when" is met.
5. **Run the gate** — `python3 .agents/scripts/pre_flight_check.py`, which
   mirrors all four CI jobs. Check its exit code.
6. **Tick the step off** in the spec file, so progress survives a cleared
   context.
7. **Stop** and offer: continue · commit checkpoint · walk me through it · stop
   here.

Resuming after a cleared context is just reading the spec: the ticked boxes say
what is done, `git status` and `git log` say what is committed.

### Hardware discipline

Any step touching the robot obeys the rules in `CLAUDE.md`, which `/sl-build`
enforces rather than merely mentioning:

- **Channel 1 must be quiet** before any HIL check. A dashboard tab open is
  enough to make `bin/robot-hil-check` false-fail.
- **`mpremote` for dev transfers** (`/dev/ttyACM0`), `upd` through the gateway
  only when testing channel 0 / OTA behaviour (`/dev/ttyUSB0`). Different ports;
  an `mpremote` deploy does not require stopping the gateway.
- **Every `mpremote` session — including a read-only `fs ls` — parks the board
  and stops `main.py`.** There is no harmless quick check. Every session ends
  with one genuine hard `mpremote connect <port> reset`, then the device is left
  alone to restart undisturbed.
- **Verify recovery through the application channel** — WebSocket telemetry or
  an OTA command over the real radio link — not more USB pokes. Prefer
  `/sl-robot-device-deploy-verify`, which enforces the whole sequence.
- **Never `deploy` from a skill.** Raw-port provisioning is human-run only.
- **Do not trust a single hardware measurement.** A degrading radio imitates
  software bugs, and has faked several in one session. Power-cycle, re-baseline,
  and measure with something that counts every frame before believing an A/B.

---

## Phase 3 — Review and findings

Run whichever reviews fit the change:

| Review | Use for |
| --- | --- |
| `/code-review` | Correctness and quality on the branch diff |
| `/security-review` | Anything touching the gateway, the WebSocket bridge, or a bind address |
| `/sl-micropython-nasa-power-of-ten` | Device firmware, before anything safety-relevant ships |
| `/simplify` | Reuse and altitude cleanups once the behaviour is right |

**`/sl-findings add`** records what they turned up in
`docs/development/findings.md`.

Two rules make the ledger worth having:

- **Only confirmed defects get an ID.** A finding needs a concrete code path, a
  violated architectural boundary, a failing check, or reproducible observed
  behaviour. Everything else goes in the Risks section — no ID, blocks nothing.
  A ledger full of speculation stops being read, and then it stops working.
- **Findings have consequences.** An open *or* `fixed` P0/P1 blocks the merge.
  `fixed` still blocks, because a repair is not trusted until a pass that did
  not write it has re-reviewed it. A fix never closes its own finding.

Severity: **P0** unsafe/destructive/data-losing · **P1** wrong in a normal path
or a security issue · **P2** wrong in an edge case or a real maintenance hazard ·
**P3** minor. Anything that could put the robot into uncommanded motion is P0.
So is anything that would expose a service beyond `127.0.0.1` without
authentication.

Clear the blockers with **`/sl-findings fix <ID>`** — one finding per approval
cycle, never bulk — then **`/sl-findings review`** to re-review the repairs so
they can close. **`/sl-findings gate`** answers the single question "is a merge
blocked?".

Only Simon sets `accepted`.

---

## Phase 4 — Land

1. **`/sl-findings gate`** — must report `MERGE CLEAR`.
2. **`/sl-ready-to-commit`** — ruff check, ruff format, test parseability. For
   the full CI mirror including every Node package, use
   `python3 .agents/scripts/pre_flight_check.py`.
3. **Update `TODO.md`** — remove the completed item; the commit is the record.
   Update `CHANGELOG.md` if the change is user-visible or a decision worth
   keeping.
4. **`/sl-commit`** — semantic, scoped message. No `Co-Authored-By` trailer.
5. **`git flow feature finish <slug>`**.

The spec and dev log stay in `docs/development/` as the record of what was
agreed and what happened.

---

## Where the other skills fit

Not everything is part of the feature loop.

**Before you start**
`/sl-robot-system-health-check` (is the environment sane?) ·
`/sl-robot-gateway-control status` · `/sl-robot-check` (is the robot alive?)

**During**
`/sl-robot-device-deploy-verify` (deploy with the reset+settle discipline) ·
`/sl-robot-dashboard-full-cycle` · `/sl-mpremote` ·
`/sl-micropython-speed-optimization` (anything in a loop or an ISR)

**Upstream dependencies**
`/sl-rollout-urst-release` after Simon runs `release.sh` on urst-mpy or otampy ·
`/sl-changes` to generate their release notes · `/sl-robot-device-sync-lib`

**Maintenance**
`/sl-improve-system` (mission memories and skills) ·
`/sl-backup-claude-config` · `/sl-blog`

---

## When you get stuck

The 1-3-1 technique from `.agents/AGENTS.md`, at any phase:

1. State **one** clearly defined problem.
2. Propose **three** concrete options.
3. Give **one** recommendation, and say why.

Then wait. Do not implement any option before Simon confirms which one.
