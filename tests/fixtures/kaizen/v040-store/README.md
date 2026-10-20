# A proposal store written by v0.4.0

`kaizen/proposals/` and `ledger/2026-10.jsonl` were written by the released v0.4.0 plugin's own code, not this
checkout's. `tests/test_proposals.py` (`V040Store`) copies them into a temporary project's `.plainspoken/` and checks
the current code still reads them (including the later `superseded` state).

## How it was made (2026-10-19)

In a scratch project with `.plainspoken/config.toml` set to `[kaizen] adapter = "file"`, run with the installed
v0.4.0 plugin's `lib/` on `sys.path` and nothing from this checkout:

1. `calibrate.materialise` made four `fp` / `loosen` proposals against a copy of v0.4.0's `data/rules.toml`
   (ruleset 4.1.0): rule 1 `em_dash_max`, rule 23 `filler_warn`, rule 25 `vague_quantifier_warn` and rule 2b
   `claude_warn_total`, each one step up. `proposals.save` stored them and `adapters.send` wrote each `.md` through
   the file adapter.
2. Decision lines went below each file's marker: B (rule 23) `APPROVE`, C (rule 25) `REJECT`, D (rule 2b)
   `APPROVE`; A (rule 1) was left without one. v0.4.0's `kaizen decisions` recorded them in the ledger.
3. v0.4.0's `kaizen apply` applied D to the rules copy (4.1.0 → 4.2.0), logging its `apply` event.

So the store holds one proposal of each state: pending (A), approved and not applied (B), rejected (C) and applied
(D). The approver is a placeholder name; nothing here comes from a real project.
