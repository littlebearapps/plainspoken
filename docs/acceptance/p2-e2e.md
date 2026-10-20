# Phase 2 end-to-end acceptance

Date: 2026-10-10. Claude Code CLI 2.1.296 (`claude --version`), Linux, `claude -p` on the subscription.
`PLUGIN` below is the local checkout of this repo on branch `feature/p2-skills`, loaded with `--plugin-dir` (no install
step). Scratch project: `/tmp/ps-e2e` (a fresh `git init`, no `.plainspoken/config.toml`, so profile `default`, the
gate off and `targets` at its default). Nothing from the scratch project is committed.

Result: **two runs, both ended `PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -`.** Run 1 found a defect in
the check skill (judge replies couldn't be recorded as written); it was fixed and run 2 went through with no permission
denials.

## Fixture

`post.md`, 431 words by `wc -w` (the lint counts 400 prose words). Planted tells: a five-em-dash run (r1), banned
words "delve", "robust", "seamless", "pivotal" and verb "leverage" (r2), "It's worth noting that" and "Furthermore"
(r4a), a staged "wasn't just a tooling problem — it was a trust problem" plus "The lesson isn't about apps at all. It's
about…" (r7c), "Importantly," (r26), "In conclusion" and "Hope this helps!" (r11).

<details><summary>Fixture text</summary>

```markdown
---
title: Why our team stopped using spreadsheets for rosters
---

# Why our team stopped using spreadsheets for rosters

For six years the club kept its volunteer roster in one shared spreadsheet. It had 14 tabs, three colour codes nobody remembered the meaning of, and a single person who knew how the formulas worked. When she moved to Ballarat last March, the roster broke within a fortnight.

It's worth noting that the spreadsheet was never the real problem. The problem was that the roster lived in one head. Furthermore, the club had no written process for swapping shifts, so every change happened by text message and half of them never reached the sheet.

This wasn't just a tooling problem — it was a trust problem. Volunteers stopped checking the sheet — they assumed it was wrong — and turned up whenever they felt like it — which meant two people on the canteen one week and nobody the next — and the committee spent every Tuesday night ringing around.

We decided to delve into the options. We looked at three paid rostering apps, one free one, and the idea of simply printing the roster and pinning it to the clubroom door. The paid apps were robust and seamless, but each wanted $9 a user a month, and with 42 volunteers that came to more than the canteen makes in a good month.

The pivotal moment came when one of the parents suggested we leverage the club's existing group chat. Everyone was already in it. Nobody needed a login. A pinned message with the week's roster, edited in place, did most of what the paid apps promised.

Here's what we changed:

- **One owner per week.** A different committee member owns the roster each week, so the knowledge spreads.
- **Swaps in the chat, not in private.** If you swap, you post it, and the owner updates the pinned message.
- **A printed copy on the door.** For the people who don't read the chat, which is more of them than you'd think.

It hasn't been perfect. Two Saturdays in May the pinned message was out of date because the owner was away, and we had a short canteen shift. But the Tuesday night phone calls have stopped, and that alone was worth it.

Importantly, none of this cost anything. The lesson isn't about apps at all. It's about not letting one volunteer carry the whole club in their head.

In conclusion, if your club's roster depends on one person, write down how it works before they leave. Hope this helps!
```

</details>

## Commands

```bash
cd /tmp/ps-e2e
# run 1 (stream-json only to keep a transcript; the brief's command is otherwise unchanged, prompt first)
claude -p "/plainspoken:check post.md" --plugin-dir "$PLUGIN" --permission-mode acceptEdits \
  --output-format stream-json --verbose \
  --allowedTools "Bash(python3 $PLUGIN/lib/run.py *)" Agent Read Edit Write > run1.jsonl
# fix (below), restore post.md from the original, move run 1's reports aside, then run 2 with only the Bash rule:
claude -p "/plainspoken:check post.md" --plugin-dir "$PLUGIN" --permission-mode acceptEdits \
  --output-format stream-json --verbose \
  --allowedTools "Bash(python3 $PLUGIN/lib/run.py *)" > run2.jsonl
ls .plainspoken/reports/
python3 "$PLUGIN/lib/run.py" paths post.md
```

The brief's last line, `run.py paths post.md --plugin-profile default`, exits 2 (`unrecognized arguments`): `paths`
doesn't take that flag, by design (check SKILL.md says so). The command above drops it.

## Run 1 (2 min 39 s, 44 turns)

- Lint: `BLOCK` (r1, r2 ×4, r4a ×2, r12f WARN, candidates for r2 "leverage", r6, r11, r26).
- Four `plainspoken:tells-judge` subagents ran in one message, each given only its judge-input line.
- **Defect.** Recording the replies with the skill's heredoc (`judge-record … <<'EOF' {…} EOF`) was refused twice by
  Claude Code's shell check: `Contains brace with quote character (expansion obfuscation)`. The allowed-tools rule
  for `run.py` doesn't cover it; non-interactively it's a denial, and interactively it would be a permission prompt on
  every judge. The model worked round it by writing each reply to `/tmp/ps-judges/Jn.json` (outside the project) and
  running `judge-record … < file`; a `for g in J1 J2 J3 J4` loop over those was also refused (`A variable in this
  command can't be checked before it runs`), so it ran them one by one.
- Merge: `FAIL · coverage 41/41 · BLOCK 1, 2, 4a · WARN 11, 12f, 26, 7c · unresolved 11, 12f, 26, 7c`.
- Fix pass 1 via `/plainspoken:humanize` (4 Edits), then lint, judges (four more), record, merge:
  `PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -`.
- Files: `post-8bf39f52.lint.json`, `.J1.judge.json` … `.J4.judge.json`, `.report.json`.

## The fix

`judge-record` gains `--from FILE`: it reads the reply from that file and deletes it, whether or not it records, so
the next judge's Write creates a fresh file (the Write tool won't overwrite a file it hasn't read). `paths` now prints
a `reply` path (`<key>.reply.json` in the reports directory, scratch). Check SKILL.md step 4 now says: write the JSON
object unchanged to the `reply` path, then `judge-record FILE --group Jn --from <reply path>`, one judge at a time,
and never put the JSON in the command. Tests: `tests/test_cli.py` (`--from` consumes the file, a rejected reply is
removed too, a missing file exits 2), `tests/test_report_contract.py` (the `reply` path), `tests/test_skills.py`
(step 4 uses `--from`, no heredoc). `docs/report-contract.md` lists the reply file.

## Run 2 (3 min 16 s, 56 turns, `permission_denials: []`)

- Same first lint and merge as run 1: `FAIL · coverage 41/41 · BLOCK 1, 2, 4a · WARN 11, 12f, 26, 7c · …`.
- Every reply went Write → `judge-record --from` → recorded; no denials.
- Fix pass 1 (one Write of the whole file) → merge `UNRESOLVED · coverage 41/41 · BLOCK - · WARN 12f · unresolved 12f`
  (opening share 0.261 over 0.25, paragraph SD 14.6 under 25).
- Fix pass 2 (one Edit: two sentences joined with a colon) → merge
  **`PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -`**. Both fix passes were used; nothing was justified, so
  the JR path didn't run.
- Files in `.plainspoken/reports/`: `post-8bf39f52.lint.json`, `post-8bf39f52.J1.judge.json` …
  `post-8bf39f52.J4.judge.json`, `post-8bf39f52.report.json`. No `reply.json` left behind.

## Did lint-watch fire on the fix-pass edits?

Yes, as far as can be seen from outside. stream-json doesn't show PostToolUse context, so the evidence is indirect:
- The hook's de-dupe state (`$CLAUDE_PLUGIN_DATA/lint-watch-state.json`, under `~/.claude/plugins/data/plainspoken-inline/`)
  held 4 keys after run 1 (4 Edits of `post.md`) and 6 after run 2 (its 1 Write + 1 Edit). Its mtime matched the last
  edit of each run to the second. The reply-file Writes (`.json`, not a target) added nothing.
- In run 2 the model said, straight after each fix and before running `check` itself: "the hook's lint now shows no
  BLOCKs" and "That cleared r12f: opening share is now 0.227".
- Fallback: running `hooks/lint_watch.py` by hand on the final `post.md` (Edit event on stdin, a scratch
  `CLAUDE_PLUGIN_DATA`) printed a `PostToolUse` `additionalContext` with the lint summary, `CLEAN`.

## Surprises

- **The heredoc denial** above: the one defect, fixed.
- **The fixer reads the engine to beat a metric.** In both runs, with r12f open, the model grepped `data/rules.toml`
  and `lib/plainspoken/metrics.py` for the thresholds and then edited to get under them (run 2's whole fix pass 2 was
  a colon join to move the opener share from 0.261 to 0.227). Nothing new was added, so it stayed within
  remove-only, but it is optimising the number rather than the reading. Worth a kaizen look, not a fix here.
- **Judge severity labels drift.** J1 labelled 5b and 5d `WARN` in one round and `BLOCK` in another. Merge takes
  severity from `data/rules.toml` (a judge can only raise a judge-blockable rule to BLOCK), so the result can't
  change; the runner flagged it itself.
- **`judged_at` is a placeholder** (`2026-10-10T00:00:00Z`) in every reply; the judge has no clock. Nothing reads it.
- **Cuts the user may want back.** The run-2 summary listed every phrase it removed outright ("robust and seamless",
  the trust-problem line, the closing lesson) and told the user to restore them in their own words if wanted. That's
  the intended behaviour.
- Cost: about USD 2.19 (run 1) and 2.80 (run 2) as reported by `claude -p`, on the subscription.

Not tested here: the publish gate (`strictness` stays `watch` under `--plugin-dir`, see `docs/claude-code-facts.md`
§2), `--content-type social`, the justify/JR path, and an installed (not `--plugin-dir`) plugin.
