# Phase 4 claims end-to-end acceptance

Date: 2026-10-14. Claude Code CLI 2.1.296 (`claude --version`), Linux, `claude -p` on the subscription (not
`claude plugin eval`). `PLUGIN` below is the local checkout of this repo on branch `feature/p4-claims`, loaded with
`--plugin-dir` (no install step). Scratch project `/tmp/ps-p4-e2e`: a fresh `git init` with
`.plainspoken/config.toml` holding `[engine] profile = "default"`. Nothing from the scratch project is committed
except the fixture copies below.

Result: **the second run ended `claims: PASS · checker: PASS (1 warning)`.** The first run ended `claims: BLOCKED`,
which was the right answer: the fixture had six sentences no saved source supported, and the skill left them for the
owner instead of passing them. The second run applied the owner's decisions and passed. The apostrophe escape
(`'\''`) worked under the Bash allow rule. Three defects are listed below; none is fixed here.

## Fixtures

All invented, in `tests/fixtures/claims/e2e/`:

- `tool-library-first-year.md`: about 400 words on a made-up community tool library's first year. It has an opening
  date, 214 members, 380 tools, 1,146 loans, nine tools written off, a $3,200 council grant, a derived "about five
  loans per member", one quote from a made-up volunteer coordinator ("We've had more drills borrowed…"), and two
  platform-behaviour claims about a made-up booking platform, ExampleLend (a reminder email two days before a loan is
  due; no text messages on the free plan). Some sentences say more than the sources do, on purpose or not: a
  "borrowed shed" with a "roller door", "most of those were small jobs", what volunteers saw "every Saturday morning",
  a lost tile cutter, the library using ExampleLend at all, and volunteers ringing late borrowers.
- `sources/northbank-annual-report-2026.txt`: the library's made-up annual report (dates, counts, the grant, the
  quote with its apostrophe, next year's opening hours).
- `sources/examplelend-help-reminders.txt`: the made-up platform's help page on reminders.

Both sources were placed in `.plainspoken/sources/` before the run, and the prompt said so (no web access needed).

## Commands

```bash
rm -rf /tmp/ps-p4-e2e && mkdir -p /tmp/ps-p4-e2e/.plainspoken/sources /tmp/ps-p4-e2e/posts && cd /tmp/ps-p4-e2e
git init -q && printf '[engine]\nprofile = "default"\n' > .plainspoken/config.toml
cp "$PLUGIN"/tests/fixtures/claims/e2e/tool-library-first-year.md posts/
cp "$PLUGIN"/tests/fixtures/claims/e2e/sources/*.txt .plainspoken/sources/
# run 1
claude -p "/plainspoken:claims posts/tool-library-first-year.md" --plugin-dir "$PLUGIN" --permission-mode acceptEdits \
  --append-system-prompt "The sources for this article are already saved under .plainspoken/sources/ (…their URLs…). \
There is no web access in this run and none is needed: pin from those saved files." \
  --output-format stream-json --verbose \
  --allowedTools "Bash(python3 $PLUGIN/lib/run.py *)" Agent Read Edit Write > run-claims.jsonl
# run 2: the same command, with the owner's decisions on the six blocking claims in --append-system-prompt
```

The owner's decisions for run 2 (given as the owner, in the prompt): cut C009, C011 and C023; end the C003 sentence
after "envy"; cut "so the volunteers ring anyone who is more than a week late" from C018; and don't say which system
the library uses (C015): present ExampleLend as one example of an online lending platform.

## Run 1 (6 min 32 s, 51 turns, about USD 2.55, no permission denials)

- `paths`, then Read on the article, the four references and both saved sources, then `claims scaffold` (5 candidates,
  each `blocking`).
- Five Edits to the article before pinning, each narrowing a sentence to what the report says: "opened its roller door
  … in a borrowed shed" → "opened … in a shed"; "wrote them off in February rather than keep chasing" → "the library's
  committee wrote them off in February 2026"; "That's a loss rate most lenders would envy" → "…I'd guess most lenders
  would envy"; "The library ran on a $3,200 grant" → "A $3,200 grant … covered …", with "Donations of tools did the
  rest." cut; "I'd turn the reminder on" → "I'd use a reminder like this"; and "As I see it" added to the closing line.
  Each change is a `removed` claim with a `resolution` in the ledger.
- Ten `claims pin` calls, one Bash call each, all accepted. The quote passage was pinned as
  `--passage '"We'\''ve had more drills borrowed than any other tool, by a long way. Ladders came second, …'`: **the
  `'\''` escape passed the `Bash(python3 $PLUGIN/lib/run.py *)` allow rule** and the engine found the passage.
- Wrote the ledger with the Write tool (11 verified, 1 derived, 4 opinion, 6 blocking with owner resolutions,
  5 removed), `claims gaps` → `claims: no gaps`, `claims hash`, Edit for the hash and `checked_at`, `claims validate`
  (exit 1: the six owner-decision claims, as expected), `claims recheck` (all `ok`).
- `claims checker-input` → one `plainspoken:claims-checker` agent, prompt exactly `Check this. Your input:` plus the
  object. Reply saved with Write, `claims record` → `BLOCKED · 7 finding(s): 6 blocking, 1 warning(s) · 0 with
  unverified evidence`. The warning was the undated free-plan claim; the skill added "As of October 2026" (a qualifier,
  not a new fact: the help page was saved that day), re-ran gaps, hash, validate, recheck, checker-input and a second
  checker, read the old reply before overwriting it (as `claude-code.md` says), and recorded
  `BLOCKED · 6 finding(s): 3 blocking, 3 warning(s)`.
- `claims status` → `claims: BLOCKED` with the six owner claims. The report listed each under "Needs the owner" with the
  decision it needs, said none were sensitive or regulated, and ended with the fixed last line.

## Run 2 (2 min 48 s, 35 turns, about USD 1.50, 4 permission denials, all recovered)

- Applied the decisions with four article Edits, then pinned a fuller ExampleLend passage for the new claim C030 ("…You
  can change the timing on paid plans."). It also renamed the heading "What the booking system does" to "What a booking
  system can do" and the `description` to match, so neither still implied the library uses ExampleLend, and said so in
  its report.
- Updated the ledger (six claims → `removed`, new verified C030, four anchors moved to the new heading) by Edit.
- `claims gaps` → no gaps, `claims hash`, `checked_at`, `claims validate` → `valid and fresh (no findings)`,
  `claims recheck` all `ok`, `checker-input`, one checker, Write, then:

```
claims-check: PASS · 1 finding(s): 0 blocking, 1 warning(s) · 0 with unverified evidence
  warning TOOL-LIBRARY-FIRST-YEAR-C024 opinion_embeds_fact: It needed a shed, a booking system that nags people politely
claims: PASS
  checker: PASS (1 warning)
```

- `claims status --json` counts: 12 verified, 1 derived, 4 opinion_or_inference, 11 removed; `gaps: []`.
- The warning (the closing line still implies the library's own system sends reminders) was reported for the owner and
  left alone, as a warning should be.

Files left in `.plainspoken/`: `claims/tool-library-first-year.claims.toml` (28 claims), `sources/` (the two inputs),
and in `reports/`: `tool-library-first-year-29fc9b72.claims.json` (status), `…claims-check.json` (the record) and
`…claims-reply.json` (the last reply). No other files.

## Defects found (not fixed here)

1. **No allowed way to read the clock for `checked_at`.** Step 5 asks for "now", but the allowed tools cover only the
   CLI. Run 1 got the time from `claims hash …; date --iso-8601=seconds` (allowed). In run 2,
   `…; TZ=Australia/Sydney date -Iseconds` and then `date -Iseconds` on its own were both refused ("This command
   requires approval"), and the model took the time from the pin fragment's `retrieved_at` instead and said so.
   Suggested fix: have the CLI supply it, e.g. `claims hash ARTICLE --stamp` printing both the hash and an ISO 8601
   `checked_at`, or a `claims bind ARTICLE` that writes `source_content_hash`, `checked_at` and `checked_by` into the
   ledger itself; then step 5 names that call.
2. **Bulk ledger edits push the model to a shell script.** After the heading rename, the model tried a `python3 - <<'EOF'`
   heredoc to move four anchors (refused: "Contains brace with quote character"), then wrote a helper to
   `/tmp/ps-scripts/anchors.py` and ran it with `&&` (refused: "multiple operations"), then made four Edits. It
   recovered, but `references/claude-code.md` could say "edit the ledger with Edit, one claim at a time; never a
   script" next to the existing no-loop rule.
3. **The checker invents classes and drifts in severity between rounds.** It filed `unsupported_claim` (both run-1
   rounds) and `opinion_embeds_fact` (run 2), neither in the rubric's list, and on unchanged text it moved C003, C011
   and C023 from `blocking` (round 1) to `warning` (round 2). Status was right both times (those claims were
   `blocking` in the ledger anyway), but the rubric has no class for "a ledgered claim with no support". Suggested fix:
   add `unsupported_claim` to the class list, and say that a claim the ledger already marks `blocking` needs no
   finding unless the checker disagrees with its resolution.

Smaller notes: the model chained read-only helpers onto CLI calls (`; ls`, `; echo "exit=$?"`, `; cat`) despite the
one-command rule; none was refused. `…claims-check.json` is written mode 0600 while the other reports are 0664.

## After the final fix wave (not re-run)

The paid E2E wasn't run again after the final fixes. What changed for this run's files, checked offline against the
scratch project:

- `claims status` now rechecks every pin and derivation. The run-2 ledger still passes those checks: every live
  verified claim is pinned to a saved source, `claims recheck` prints `ok` for each, and the derived claim's inputs
  are live. The run-2 article and ledger are kept as `tests/fixtures/claims/e2e/final/`, and
  `tests/test_cli_claims.py` (`EndToEndFixture`) shows they reach `claims: PASS` with a current checker record.
- The checker record is now bound to the rubric and the regulated-claims matrix too (`rubric_sha256`,
  `matrix_sha256`). The rubric changed in this wave, so run 2's record now reads
  `checker result stale (rubric changed)` and the status is INCOMPLETE until the checker runs again.
- The three defects above are addressed: `claims hash ARTICLE --stamp` prints a ready-to-paste `checked_at` (1);
  the claims skill's `references/claude-code.md` says ledger edits go through Edit only, never a heredoc or script,
  and nothing is chained onto a CLI call (2); the rubric now has a fixed class list with `unsupported_claim` and an
  `other` fallback, says a claim the ledger already marks `blocking` needs no finding unless the checker disagrees,
  and checks every location of a claim (3). `…claims-check.json` now follows the umask like the other reports.

## Not tested here

An installed (not `--plugin-dir`) plugin, a web fetch-and-save step (sources were pre-saved), a `--ledger PATH` run, a
JSON ledger, `human_signoff`, a regulated-claims matrix in the E2E fixture, and the paid trigger evals (run separately on 2026-10-14:
`p3-evals.md`). The comparison
against a host's own checker on real articles was run locally and is recorded privately by that host, not here.
