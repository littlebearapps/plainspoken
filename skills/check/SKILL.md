---
name: check
description: "Checks a draft for AI writing tells with a fixed lint and four isolated judges, then fixes, never adding. Use before an article, page, email, post or script goes out, and whenever asked if any text, even one line, sounds like AI."
argument-hint: <file> [--content-type social]
allowed-tools: Bash(python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py *), Write(.plainspoken/reports/*.reply.json), Edit(.plainspoken/reports/*.justify.json)
---

# plainspoken check

> Running in Codex or Hermes Agent? Read `../../hosts/codex.md` or `../../hosts/hermes.md` (relative to this
> skill's folder) once before step 1. In Claude Code, skip this note.

Core rules (these hold for the whole run):
- The engine decides. You run `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py <subcommand>` and act on its exit codes;
  you never score, merge or name report files yourself (`run.py paths <file>` prints every path).
- Judges are `plainspoken:tells-judge` subagents. They are read-only; you record their replies with `judge-record`.
- A fix cuts, joins or splits sentences, or restates plainly, using only what the text already says. You never edit
  an article to add a fact, number, name, quote, example, opinion or detail that isn't already in the text or given
  by the user. You never edit or add `anti-ai-allow` markers.
- At most two fix passes, and fix passes come before justify: justify only what you keep after the last fix pass.
  Before the judges start you may fix lint findings once, the same way, then rerun step 1; no judge has read that
  text, so it isn't a fix pass. Once the judges start, every edit to FILE is a fix pass (after justify or JR too),
  and step 1 follows it. INCOMPLETE means an input is missing or stale: rerun what merge names, without editing the article; that rerun is
  not a fix pass. Still INCOMPLETE after one rerun → stop and report merge's problem lines.
- Exit codes: `check` 0 = no BLOCK, 1 = BLOCKs found (carry on), 2 = bad input (stop and report the message).
  `merge` 0 = PASS, 1 = read the status line (INCOMPLETE, FAIL or UNRESOLVED). For `merge`, `justify` and
  `judge-record`, exit 2 means stop and report the engine's message (only `judge-input` has its own exit-2 step).
- Run every call from the same working directory (the project root); report files are keyed to it.

Active profile (injected when this skill loads):
!`python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py profile --plugin-profile '${user_config.profile}' || true`

Below, `RUN` means `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py`. These calls take
`--plugin-profile '${user_config.profile}'` (single quotes, exactly so): check, judge-input, merge, justify, status
and profile. `paths` and `judge-record` don't take it (argparse rejects it there with exit 2). `FILE` is the first
argument; quote it in every command (`"drafts/my post.md"`). Pass `--content-type social` to `check` when the user
asks for it or the file is a social post. When the project gives files their own profile (`[engine] profiles` in
`.plainspoken/config.toml`), every call that takes FILE uses FILE's profile by itself; the summary injected above is
the project's default (`RUN config profile-for FILE` prints FILE's).
Subcommands used: run.py check, run.py judge-input, run.py judge-record, run.py merge, run.py justify, run.py paths,
run.py status.

## Steps

1. **Lint.** `RUN check FILE --plugin-profile '${user_config.profile}'` (plus `--content-type social` if needed). Exit 2 → stop with its message.
2. **Judge input.** `RUN judge-input FILE --plugin-profile '${user_config.profile}'`. It prints four JSON lines, J1 to J4. Exit 2 → rerun step 1 once.
3. **Judges.** In ONE message, start four `plainspoken:tells-judge` subagents, one per line. Each prompt is: "Judge
   this. Your input:" followed by that line verbatim. Nothing else: no file contents, no opinion, no hint about who
   wrote it.
4. **Record**, one judge at a time. Take only the JSON object of the reply (its first `{` to its last `}`): drop any
   code fence or trailing agent metadata. Save it unchanged as a file at the `reply` path from
   `RUN paths FILE`, then run `RUN judge-record FILE --group Jn --from <reply path>`, which records it and deletes the
   reply file. The JSON never goes in a shell command (no heredoc, no echo): the shell check refuses it there.
   Exit 1 (invalid or stale) → start that one judge again once ("no current lint" → rerun step 1 first); a second
   failure → stop and report the reason.
5. **Merge.** `RUN merge FILE --plugin-profile '${user_config.profile}'`. PASS → step 8. INCOMPLETE → rerun exactly
   what its `problem:` and `missing verdicts:` lines name, then merge again (once). FAIL → step 6. UNRESOLVED → step 6
   for WARNs you'll fix, step 7 for WARNs you'll keep.
6. **Fix pass** (at most two in the whole run). Use `/plainspoken:humanize` on FILE with the list of failing rules
   and their evidence from `RUN paths FILE` → the `report` file. If it can't be started (the project may deny it),
   follow `${CLAUDE_PLUGIN_ROOT}/skills/humanize/SKILL.md` yourself. Fix every BLOCK and every failing WARN under
   the fix rule above. Then go back to step 1 (the hash changed, so all four judges rerun). When both passes are
   spent and merge still says FAIL → step 8 and report it. If it says UNRESOLVED → step 7, then step 8.
7. **Justify what you kept** (after the last fix pass you'll make). When no BLOCK remains but a WARN still fails and you have a real reason to keep it,
   follow `references/fix-or-justify.md` (template → fill → review input → one JR judge → record → merge). A JR
   reject leaves the rule UNRESOLVED: fix it, or rewrite the reason once.
8. **Report.** Run `RUN status FILE --plugin-profile '${user_config.profile}'` and give its `check:` lines exactly
   as printed (its claims lines and exit code aren't this skill's). `INCOMPLETE (stale …)` means FILE changed after
   the last merge: that edit was a fix pass, so run steps 1 to 5 again without editing, then report. Then say how
   many fix passes ran, BLOCKs, justified WARNs (accepted / rejected), anything unresolved, and the report file's path. A WARN kept without an accepted justification is
   UNRESOLVED, never passed. If the run stopped early, say which step and quote the engine's message.
   Merge has already captured the verdicts in the kaizen ledger, so don't record them again.

If the person disagrees with a finding, or you had to work around a step, record it:
`run.py kaizen dismiss|uphold …`, or say so in your report (`/plainspoken:kaizen`).
