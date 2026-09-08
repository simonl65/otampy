# Findings ledger

The durable record of confirmed defects found by review. Maintained by the `sl-findings` skill (`/sl-findings`) — see `.agents/skills/sl-findings/SKILL.md` for the full rules, and `docs/workflow.md` for where this sits in the development loop.

Fed by `/code-review`, `/security-review`, `/sl-micropython-nasa-power-of-ten`, and anything `/sl-build` turns up while implementing.

## How to read this file

- **IDs (`F-01`) are permanent.** Never reused, never renumbered, even when a finding turns out to be invalid. When more than one branch is open, allocate new IDs from `git log develop -p -- docs/development/findings.md`, not from your branch's copy of this file.
- **Severity:** P0 unsafe/destructive/data-losing · P1 wrong in a normal path or a security issue · P2 wrong in an edge case or a real maintenance hazard · P3 minor.
- **Status:** `open` → `fixed` → `closed`, or `accepted` (Simon only) or `invalid` (with evidence).
- **An open or `fixed` P0/P1 blocks a merge.** `fixed` still blocks, because a repair is not trusted until a pass that did not write it has re-reviewed it.
- **Only confirmed defects appear above the Risks section.** A finding needs a concrete code path, a violated architectural boundary, a failing check, or reproducible observed behaviour. Everything else goes under Risks.

## Open

_None._

## Closed

_None._
