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
- A fix cuts, joins or splits sentences, or restates plainly, using only what the text already says. A join uses
  "and" or "but", or merges two sentences; it never adds a clause, detail or reason (such as "because …"). You never
  edit an article to add a fact, number, name, quote, example, opinion or detail that isn't already in the text or
  given by the user. You never edit or add `anti-ai-allow` markers.
- A rhythm fix (7, 7d) joins two neighbouring sentences with "and", "but", a comma or a semicolon, keeping their own
  words, or splits one. It never pads or restates to reach a length: no extra word to cross the line (an added "can"
  or "working"), no fact the text already gives said again, no "so" or "because". When no such join or split clears
  the line, keep the WARN (`--keep`, then step 7): an unresolved 7d is better than a padded sentence.
- At most two fix passes, and fix passes come before justify: justify only what you keep after the last fix pass.
  Before the judges start, step 1 fixes lint findings the same way in at most two lint-only passes; no judge has
  read that text, so they aren't fix passes. Once the judges start, every edit to FILE is a fix pass (after justify
  or JR too), and step 1 follows it. INCOMPLETE means an input is missing or stale: rerun what merge names, without editing the article; that rerun is
  not a fix pass. Still INCOMPLETE after one rerun → stop and report merge's problem lines.
- Exit codes: `check` 0 = no BLOCK, 1 = BLOCKs found (carry on), 2 = bad input (stop and report the message).
  `merge` 0 = PASS, 1 = read the status line (INCOMPLETE, FAIL or UNRESOLVED). For `merge`, `justify` and
  `judge-record`, exit 2 means stop and report the engine's message (only `judge-input` has its own exit-2 step).
- Run every call from the same working directory (the project root); report files are keyed to it.

**First, before any other step:** run
`python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py profile --plugin-profile '${user_config.profile}' --plugin-locale '${user_config.locale}'` and read what it prints.
That's the active profile the steps below use. If the call fails, carry on without it.

Below, `RUN` means `python3 ${CLAUDE_PLUGIN_ROOT}/lib/run.py`. These calls take
`--plugin-profile '${user_config.profile}'` (single quotes, exactly so): check, judge-input, merge, justify, status
and profile. `paths` and `judge-record` don't take it (argparse rejects it there with exit 2). `FILE` is the first
argument; quote it in every command (`"drafts/my post.md"`). Pass `--content-type social` to `judge-input` when the
user asks for it or the file is a social post. When the project gives files their own profile (`[engine] profiles` in
`.plainspoken/config.toml`), every call that takes FILE uses FILE's profile by itself; the first step's summary is
the project's default (`RUN config profile-for FILE` prints FILE's).

For a post or video with a title, caption and alt text, put each in the frontmatter and list its key in the profile's
`[document] visible_frontmatter_keys`, or keep alt text inline as `![alt](…)` in the body. The `read:` line under
the lint heading (`fields_read` in the JSON) shows what the lint read. The plugin checks only the text it's given,
never a platform's rendered version.

Asked only for a quick lint that shouldn't count as kaizen evidence? Run
`RUN check FILE --plugin-profile '${user_config.profile}' --no-record` and stop there.
Subcommands used: run.py check, run.py judge-input, run.py judge-record, run.py merge, run.py justify, run.py paths,
run.py status.

## Report only

When the person asks for findings without edits (the words must stay their own, or only a person may write the
outgoing text), follow this route. It overrides the fixing in the core rules and in steps 1, 2 and 5: you never
edit FILE, and its bytes stay unchanged.
- Steps 1 and 2: fix nothing, here or when a later step asks you to rerun step 1. The lint cuts long lists short
  ("… N more"), so take the rules from `judge-input`'s exit-1 list, which names every open line, and rerun step 1
  with `--keep <rule>` for each rule it names. Here exit 1 always means keep, and exit 3 always means rerun with
  `--ignore-claims`.
- Steps 3 to 5 as written. Then skip step 6 (fix pass) and step 7 (justify), never call `/plainspoken:humanize`,
  and go to step 8.
- If `status` says `INCOMPLETE (stale …)`, FILE, its profile or the ruleset changed since merge (`status` doesn't
  say which): report INCOMPLETE with that line, and stop. Don't rerun steps 1 to 5.
- The report gives step 8's `check:` lines and lists each BLOCK and WARN with its line. Merge's status line names
  the rules; the lines are in the `report` file from `RUN paths FILE` (each rule's `findings` from the lint,
  `evidence` from a judge). Say plainly that nothing was fixed. Merge's FAIL or UNRESOLVED is the result: never
  call it a PASS while a BLOCK or failing WARN remains.

## Steps

1. **Lint and judge input.** `RUN judge-input FILE --plugin-profile '${user_config.profile}'` (plus
   `--content-type social` if needed). It lints FILE and prints the lint first (stderr), then four JSON lines, J1 to
   J4; read it in full, the lint first, and never send it, or any part of it, to `/dev/null` or cut it with a pipe.
   Never build or edit a JSON line. Exit 1 → it names lint lines still open. Before the first judges, fix its BLOCK
   and WARN lines under the fix rule and run step 1 again (at most two lint-only passes, counting a caller's, such
   as write step 6's), so the judges read a lint-clean draft. A line you leave (a WARN you have a real reason to
   keep, a 7d line the rhythm rule can't clear, one still there after two, or any once the judges have started) gets
   `--keep <rule>`, only for a rule the lint above printed: rerun step 1 with it. Justify a kept WARN in step 7
   rather than fix it: a fix after the judges means all four again. Exit 2 for a `--keep` for a rule with no open
   line → rerun step 1 once without it; any other exit 2 → stop with its message. Exit 3 → FILE has a claim ledger
   that isn't current, and it prints why. From write, finish the claims step (write steps 6 and 7 say how), then
   step 1 again. On its own, rerun step 1 with `--ignore-claims` and say so in step 8.
2. **Judge input.** Step 1 already printed it; this is the same call. Its four JSON lines go to step 3.
3. **Judges.** In ONE message, start four `plainspoken:tells-judge` subagents, one per line. Each prompt is: "Judge
   this. Your input:" followed by that line verbatim. Nothing else: no file contents, no opinion, no hint about who
   wrote it.
4. **Record** all four at once. From each reply take only its JSON object (its first `{` to its last `}`): drop any
   code fence or trailing agent metadata. In one Write, save the four objects unchanged, one after another, as the
   file at the `reply` path from `RUN paths FILE`. In the same message, run
   `RUN judge-record FILE --all --from <reply path> && RUN merge FILE --plugin-profile '${user_config.profile}'`
   (step 5); it records each reply and deletes the file. The JSON never goes in a shell command (no heredoc, no
   echo): the shell check refuses it there. Exit 1 names each judge it didn't record (invalid or stale): start just
   that judge again once ("no current lint" → rerun step 1 first; "input_digest" → rerun step 2 for its line),
   Write its reply alone to the same path and run `RUN judge-record FILE --group Jn --from <reply path>`, then
   merge; a second failure → stop and report the reason.
5. **Merge.** `RUN merge FILE --plugin-profile '${user_config.profile}'` (step 4 runs it once all four are
   recorded). PASS → step 8. INCOMPLETE → rerun exactly what its `problem:` and `missing verdicts:` lines name, then
   merge again (once). FAIL → step 6. UNRESOLVED → step 6 for WARNs you'll fix, step 7 for WARNs you'll keep.
6. **Fix pass** (at most two in the whole run). Use `/plainspoken:humanize` on FILE with the list of failing rules
   and their evidence from `RUN paths FILE` → the `report` file. If it can't be started (the project may deny it),
   follow `${CLAUDE_PLUGIN_ROOT}/skills/humanize/SKILL.md` yourself. Fix every BLOCK and every failing WARN under
   the fix rules above; a 7 or 7d WARN the rhythm rule can't clear goes to step 7 instead, never lengthened. Then
   go back to step 1 (the hash changed, so all four judges rerun). When both passes are spent and merge still says
   FAIL → step 8 and report it. If it says UNRESOLVED → step 7, then step 8.
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
