# Boot-time recovery window reachability (F-10) — dev log

Narrative record for `failsafe-update-window-reachability-spec.md`. The spec is
the plan; this is what actually happened, including every hardware measurement
with the conditions it was taken under.

**Branch:** `feature/failsafe-update-boot-listen` (continued, not a new one —
the spec's prerequisites are the host-side F-10 fixes in `172d93c` / `269a25d`,
which are unmerged on that branch).

---

## 2026-09-10 — spec amendment before step 1: what a non-integer key means

The approved spec contradicted itself on a non-integer
`OTA_BOOT_RECOVERY_LISTEN_MS`. Step 1 required `_boot_mark_path` to return
`None` for it (marker disabled); step 3 required it to fall back to the default
8000 (wide window enabled). Both could not hold, and as written a typo would
disable the marker while still paying an 8 s window off the journal test.

The deeper look settled it on evidence rather than taste:

1. **A non-integer is a typo, not a config style.** `int("8000")` → 8000 and
   `int(8000.5)` → 8000 both succeed, so only genuine garbage (`None`, `"8s"`,
   `""`) ever reaches the fall-back.
2. **The repo had already decided the question three times**, once in the very
   function step 3 modifies:
   - `_run_boot_listen` / `OTA_BOOT_LISTEN_MS` — garbage → default 1000,
     `<= 0` → off.
   - `_run_default_update_loop` / `OTA_TIMEOUT_MS` — garbage → default 5000,
     `< 1` → default 5000 (no off-switch at all).
   - `restore.read_journal` — an unparseable first line is treated as
     `committing`, its docstring saying "fail safe, meaning restore
     everything".

   House rule: **an unparseable value falls back to the safe working default;
   only an explicit, in-range sentinel turns something off.**
3. Step 1's version was therefore fail-*closed*, and in the dangerous
   direction: `OTA_BOOT_RECOVERY_LISTEN_MS = "8s"` would silently remove the
   only radio recovery path, discovered when a device is bricked and will not
   answer. That is F-10 reintroduced through a config mistake.

**Resolved (Simon, 2026-09-10): option C.** `core._boot_recovery_window_ms`
becomes the single parse (garbage → 8000, `<= 0` → off); `_boot_mark_path`
returns `None` iff that is `<= 0`; step 3's `run()` calls it for the duration
rather than parsing the key a second time. A shared helper rather than just
fixing the wording, because step 3 needs the parsed duration anyway — two parse
sites is the drift that produced the contradiction in the first place.
