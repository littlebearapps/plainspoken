# Phase 3 end-to-end acceptance

Date: 2026-10-12. Claude Code CLI 2.1.296 (`claude --version`), Linux, `claude -p` on the subscription (not
`claude plugin eval`). `PLUGIN` below is the local checkout of this repo on branch `feature/p3-language`, loaded with
`--plugin-dir` (no install step). Scratch project `/tmp/ps-p3-e2e`: a fresh `git init` with
`.plainspoken/config.toml` holding `[engine] profile = "default"`. Nothing from the scratch project is committed.

Result: **both runs reached their expected endings.** The write run ended
`PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -` after one fix pass; the register-check run ended
`Flags only. You decide what to send.` The one defect (shell loops refused) was fixed in the write skill's notes. The
brief probe confirmed the `SubagentStart` `agent_type` value.

## Fixtures

Both invented. `notes.md`: about 120 words of notes on a repair café's first month (opening date, 63 items in,
41 fixed, 15 not fixable, 7 sent home for parts, a dead soldering iron, a lost sign-in clipboard, what the volunteers
asked for, a $400 grant that covers insurance only). `email.md`: a pushy follow-up from a café owner to a supplier
(three threats, a contradicting deadline, "Surely that's not too much to ask").

## Commands

```bash
rm -rf /tmp/ps-p3-e2e && mkdir -p /tmp/ps-p3-e2e/.plainspoken && cd /tmp/ps-p3-e2e
printf '[engine]\nprofile = "default"\n' > .plainspoken/config.toml
# run 1 (prompt first; stream-json only to keep a transcript)
claude -p "/plainspoken:write notes.md --type article" --plugin-dir "$PLUGIN" --permission-mode acceptEdits \
  --output-format stream-json --verbose \
  --allowedTools "Bash(python3 $PLUGIN/lib/run.py *)" Agent Read Edit Write Skill > run-write.jsonl
# run 2
claude -p "/plainspoken:register-check email.md --kind follow-up" --plugin-dir "$PLUGIN" --permission-mode acceptEdits \
  --output-format stream-json --verbose \
  --allowedTools "Bash(python3 $PLUGIN/lib/run.py *)" Read Write > run-reg.jsonl
ls .plainspoken/reports/
```

## Run 1: write (4 min 21 s, 59 turns, about USD 2.43)

- Listed its sources (`notes.md` only), filled the reader-brief stub (four answers), read the active profile with
  `profile --voice`, asked for anchors for five section types and got `(no anchors tagged '<tag>' in profile default)`
  each time, and said so in its report.
- Drafted to `.plainspoken/drafts/repair-cafe-first-month.md`, then started `plainspoken:check` through the Skill tool.
- First merge: `UNRESOLVED · coverage 41/41 · BLOCK - · WARN 7b, 7d · unresolved 7b, 7d`. One `humanize` pass (five
  Edits), four more judges, then
  **`PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -`**.
- Ended with the reader brief, a `Claims to verify` list (opening date has no year; the 63 total may or may not include
  the napkin count; "ongoing Saturdays 10 to 1" is an assumption) and `For kaizen` notes.
- It caught that 7 September was not a Saturday in 2026 and left the year out. It couldn't confirm the weekday with a
  command (see below), so it said so.
- Files in `.plainspoken/reports/`: `repair-cafe-first-month-917e1a8a.lint.json`, `.J1.judge.json` … `.J4.judge.json`,
  `.report.json`. No `reply.json` left behind.

### Defect found and fixed

Three Bash calls were refused, and the model recovered each time:

1. `cd <skill>/references && for f in *.md; do cat "$f"; done` (to read the references): "A variable in this command
   can't be checked before it runs".
2. `for t in opening explainer story list-intro closing; do run.py anchors --tag $t …; done`: the same refusal. It
   re-ran the five calls one at a time.
3. `python3 -c "import datetime; …"` (a weekday check): "This command requires approval". Nothing to fix; the
   allowed-tools list only covers `run.py`, by design. Filed as kaizen note K5.

Fix: `skills/write/SKILL.md` step 4 now says to make one `anchors` call per section type with no shell loop, and
`skills/write/references/claude-code.md` records the refusal and says to use Read for the reference files. The
assertion sits in `tests/test_skill_write.py` (`test_anchors_from_the_cli_and_missing_anchor_route`).

## Run 2: register-check (44 s, 5 turns, about USD 0.38, no permission denials)

- Read the email, the checklist (`register-checklist --kind follow-up`) and ran the lint once.
- Six flags, each with a quote, a reason and a fix: R3 Pressure ×3 ("last chance", the double threat, "Surely that's
  not too much to ask"), R8 Follow-up ×2 (two different deadlines; the body doesn't stand alone), R12 Scope ×1 (what
  "the refund" covers). Then the lint line and **`Flags only. You decide what to send.`**
- File: `email-39f0263a.lint.json`. It wrote no rewrite and no report beyond the lint.

## Probe: `SubagentStart` `agent_type` for a plugin agent (carried from an earlier review)

Setup: a scratch copy of the repo at `/tmp/ps-probe-plugin` whose `hooks/session_brief.py` appended its raw stdin to a
log and logged when it emitted. The scratch project `/tmp/ps-p3-probe` had `[brief] enabled = true` in
`.plainspoken/config.toml`. Run: `/plainspoken:check note.md` with `--plugin-dir` on the copy (24 turns, no
permission denials). Nothing from the copy is committed.

Observed:
- One `SessionStart` event (`source: startup`, no `agent_type`): the hook **emitted** the brief.
- Four `SubagentStart` events, one per judge: `agent_type` was exactly **`plainspoken:tells-judge`** (plus `agent_id`,
  `session_id`, `prompt_id`, `cwd`, `transcript_path`). The hook **emitted nothing** for any of them.

So the `plainspoken:` prefix test in `hooks/session_brief.py` is correct and needed no change. Recorded in
`docs/claude-code-facts.md` section 8.

## Guards

- `python3 -m unittest discover -s tests -t .`: `Ran 815 tests … OK (skipped=2)`.
- `leak_guard.py .`: `leak-guard: 0 hit(s), 1 suppressed`. `check_links.py .`: `0 bad link(s)`. `lint_frontmatter.py`,
  `check_release_version.py`: clean. `claude plugin validate . --strict`: `✔ Validation passed`.
- The denylist grep from the brief, over the shipped folders: exit 1 (no hits).
- `git ls-files vendor-intake | wc -l`: 0.
- `docs/provenance.md` had 24 table rows then, one per adapted source file (historical: the public release
  replaced that table with a short note, and the source files were never shipped).

Token budget line:

    always-on 437 (manual-only left out: adapt 80, copy-audit 90, register-check 90, voice 70) + hooks 0 = 437 tokens (budget 500)

`claude --plugin-dir . plugin details plainspoken` (the harness's own estimate counts the manual-only skills too, so
its always-on figure is higher than the CI budget line above):

```
Component inventory
  Skills (8)  adapt, check, copy-audit, humanize, plain-language, register-check, voice, write
  Agents (2)  tells-judge, cold-reader
  Hooks (4)  SessionStart, SubagentStart, PostToolUse, PreToolUse  (harness-only — no model context cost)
  MCP servers (0)
  LSP servers (0)

Projected token cost
  Always-on:   ~767 tok   added to every session

Per-component (rounded)
  component       always-on  on-invoke
  register-check        ~90      ~1.3k
  adapt                 ~80      ~1.6k
  copy-audit            ~90      ~2.2k
  voice                 ~70      ~1.7k
  humanize              ~60      ~2.5k
  check                 ~90      ~1.6k
  plain-language        ~90      ~1.6k
  write                 ~90      ~1.8k
  tells-judge           ~60       ~840
  cold-reader           ~50       ~500
```

## Surprises

- **The write run is dear.** About USD 2.43 on the subscription: eight judge dispatches (two rounds of four) dominate.
- **7d and 7b fought the reader floor.** The model's own kaizen notes: 7d (a 25-plus-word sentence in each section)
  worked against a Year 7 reader, it padded two sentences to clear the counter, and 7b flagged an answer-first opener
  that `answer-first.md` asks for. Filed as K4 in `docs/kaizen-candidates.md`, not changed here (the ruleset changes
  only through `kaizen apply`).
- **The cold-reader agent was not exercised** by these runs; `write` doesn't call it. Its checks are the agent tests.

Not tested here: `voice`, `copy-audit`, `adapt` and `plain-language` end to end, an installed (not `--plugin-dir`)
plugin, and the paid trigger evals (run separately on 2026-10-14: `p3-evals.md`).
