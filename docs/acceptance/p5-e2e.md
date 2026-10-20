# Phase 5 end-to-end acceptance (kaizen)

Date: 2026-10-14 (UTC; ledger timestamps are UTC). Claude Code CLI 2.1.299 (`claude --version`), Linux, `claude -p` on
the subscription (no API spend, no `claude plugin eval`). `<plugin>` is the local checkout of this repo on branch
`feature/p5-kaizen`, loaded with `--plugin-dir` (no install step). `<scratch>` is a fresh `git init` project under
`/tmp`. Nothing from it is committed.

Result: **the loop ran end to end.** check → ledger (lint + judge events, no excerpts) → dismiss → calibrate (one
file proposal) → hand-written `APPROVE:` → decisions → apply `--dry-run` → apply to a scratch copy of the ruleset,
which went to 4.2.0 with a changelog entry. The plugin's own `data/rules.toml` stayed byte-identical. The Stop nudge
showed up after calibrate and not after the decision. `calibrate` and `apply` were denied in `-p` mode until granted
explicitly. Nine `claude -p` runs in all, including the backstop probe.

## Gates (step 1)

| Command | Result |
|---|---|
| `python3 -m unittest discover -s tests -t .` | 1777 tests, OK (skipped=2), 152 s |
| `python3 scripts/dev/leak_guard.py .` | exit 1: 6 hits, all in gitignored `evals/results/*/aggregate-result.json` (local-only paid-eval output, not tracked), 1 suppressed (`tests/test_rubric.py:44`) |
| `python3 scripts/dev/check_links.py .` | exit 0, 0 bad links |
| `python3 scripts/dev/lint_frontmatter.py .` | exit 0 |
| `python3 scripts/dev/check_release_version.py` | exit 0 |
| `claude plugin validate . --strict` | `✔ Validation passed` |
| `python3 -m scripts.dev.token_budget .` | always-on 465 + hooks 0 = 465 tokens (budget 500); manual-only skills left out, kaizen 80 among them |
| parity harness against the original private engine (its tests and a read-only real run; the harness has since been removed) | 7 tests OK; exit 0: ruleset 4.1.0 · 37 compared, 0 skipped · 0 with unallowed differences |

`git -C <plugin> check-ignore -v evals/results/…` confirms `.gitignore:4:evals/results/`.

## Scratch project

```
<scratch>/.plainspoken/config.toml     [engine] profile = "default" · [kaizen] adapter = "file" (all else default)
<scratch>/drafts/post.md               invented 231-word draft (below)
<scratch>/ruleset/rules.toml           copy of <plugin>/data/rules.toml (sha256 61bca4c2…cd615f, same as the plugin's)
<scratch>/ruleset/RULESET-CHANGELOG.md copy of <plugin>/data/RULESET-CHANGELOG.md
```

<details><summary>Fixture draft</summary>

```markdown
---
title: What I learned moving the bakery's orders off email
---

# What I learned moving the bakery's orders off email

For three years the bakery took wholesale orders by email. Four cafes, two delis and a school canteen sent their orders whenever they remembered, and Maria read every one at 4 am before the first bake.

Furthermore, nobody had a record of what had been ordered last week. When the school canteen said it had asked for six loaves and got four, there was no way to check. Moreover, the emails arrived in three different inboxes.

We decided to delve into the options. The paid ordering systems were robust and seamless — but each wanted $40 a month — and the cafes would have needed logins — which none of them wanted.

What we did instead was a shared order form with one row per customer per day. Maria checks it at 4 am. The customers fill it in by 8 pm the night before. If a row is empty, she rings them.

It hasn't been perfect. Twice in the first month a cafe forgot and we baked from the previous week's numbers. But the arguments about who ordered what have stopped, and Maria gets an extra half hour of sleep.

In conclusion, if your orders live in your inbox, put them somewhere everyone can see. Hope this helps!
```

</details>

Every run below is from `<scratch>`, prompt first, with `--plugin-dir <plugin> --permission-mode acceptEdits
--output-format stream-json --verbose` and stdin from `/dev/null`. Only the prompt and `--allowedTools` vary.

| Run | Prompt | `--allowedTools` | Turns | Time | Denials | Reported cost (USD, subscription) |
|---|---|---|---|---|---|---|
| 1 | `/plainspoken:check drafts/post.md` | `Bash(python3 <plugin>/lib/run.py *)` | 27 | 104 s | 0 | 1.95 |
| 2 | `/plainspoken:kaizen dismiss drafts/post.md --rule 12d --kind false_positive --reason '…'` | none | 2 | 7 s | 0 | 0.33 |
| 3 | `/plainspoken:kaizen calibrate` | none | 4 | 13 s | 2 | 0.36 |
| 4 | `/plainspoken:kaizen calibrate` | `Bash(python3 <plugin>/lib/run.py kaizen calibrate*)` | 3 | 13 s | 0 | 0.05 |
| 5 | `/plainspoken:kaizen decisions` | none | 2 | 6 s | 0 | 0.32 |
| 6 | `/plainspoken:kaizen apply KZ-20261014-6dcaa4 --dry-run --rules ruleset/rules.toml` | none | 4 | 15 s | 2 | 0.37 |
| 7 | same as 6 | `Bash(python3 <plugin>/lib/run.py kaizen apply*)` | 3 | 11 s | 0 | 0.30 |
| 8 | `/plainspoken:kaizen apply KZ-20261014-6dcaa4 --rules ruleset/rules.toml. I have seen the dry-run diff (…) and I say go.` | `Bash(python3 <plugin>/lib/run.py kaizen apply*)` | 5 | 18 s | 0 | 0.39 |
| 9 | backstop probe: run 1 again against a logging copy of the plugin (section 7) | as run 1 | 27 | 116 s | 0 | 1.97 |

## 1. check → ledger

Run 1 went lint → four `plainspoken:tells-judge` subagents → `judge-record --from` ×4 → merge (FAIL) → one fix pass
via `/plainspoken:humanize` (one Write) → lint → four judges → record → merge:

```
PASS · coverage 41/41 · BLOCK - · WARN - · unresolved -
```

First lint: BLOCK r2 ×3 ("delve", "robust", "seamless"), BLOCK r4a ×2 ("Furthermore", "Moreover"), WARN r7d, WARN
r12d, candidates r6 and r11 ×2.

Ledger (`.plainspoken/ledger/2026-10.jsonl`), counted with a python3 one-liner over every line:

```
lines 58  distinct ids 58
excerpt keys: 0   reason keys: 0
('fix', 'lint', 'fixed') 7
('judge', 'judge:J1', 'fired') 1
('judge', 'judge:J1', 'passed') 9
('judge', 'judge:J2', 'passed') 14
('judge', 'judge:J3', 'passed') 14
('judge', 'judge:J4', 'passed') 6
('lint', 'lint', 'fired') 7
keys union:   actor doc_id doc_sha event facets id outcome profile rule ruleset_version severity span_hash ts v
facets union: agree form section term
```

Text check: `grep -c -i` for `Maria`, `bakery`, `canteen`, `In conclusion`, `post.md` and `drafts/` gives 0 in both
ledger files. `delve`, `robust`, `seamless`, `furthermore` and `moreover` appear twice each, always as
`"term":"…"` facets (a fired and a fixed event): these are ruleset list entries, which the schema allows.

`friction.jsonl` got 8 `{"kind":"agent_handback","source":"plainspoken:tells-judge","detail":""}` lines, one per
judge run (2 rounds × 4). `kaizen report` ends with `judge replies returned (backstop) 8 vs recorded 8`.

## 2. dismiss

The fix pass left the article with no BLOCK or WARN, only an r6 CANDIDATE, so there was nothing in the current check
to dismiss (see "Gaps found", G1). As the operator I restored the original draft (`git checkout drafts/post.md`) and
re-linted it with the engine directly (`python3 <plugin>/lib/run.py check drafts/post.md`, exit 1, the same findings
as the first lint). No model was involved. Then run 2, with no `--allowedTools`:

```
TOOL   python3 <plugin>/lib/run.py kaizen dismiss "drafts/post.md" --rule 12d --kind false_positive --reason 'short post, even paragraphs are fine here'; echo "exit=$?"
RESULT kaizen dismiss: recorded 1 event for post.md
         dismissed · rule 12d · WARN · span 7f2340f4d5f338f4 · kind false_positive, section intro
       exit=0
```

Ledger event (ids and hashes trimmed): `event override · actor human · outcome dismissed · rule 12d · WARN · facets
{section: intro, kind: false_positive} · reason "short post, even paragraphs are fine here"`, and no `excerpt`.
The skill's allowed-tools covered the call: no grant and no denial.

## 3. calibrate

Seeded with a small python3 script (`ledger.make_event` + `ledger.append`, settings from `config.kaizen_settings`):
25 `lint/fired` WARN events on rule 2b across 10 synthetic doc ids, and 4 `override/dismissed` events (`kind
false_positive`, reason "fine in this voice"), all timestamped 2 days ago. `kaizen report` then showed
`2b fires 25 · docs 10 · dism 4 · fp% 16%`.

**Run 3, no grant** (evidence that the per-subcommand grant matters):

```
TOOL   python3 <plugin>/lib/run.py kaizen calibrate; echo "EXIT=$?"
RESULT This Bash command contains multiple operations. The following part requires approval: python3 <plugin>/lib/run.py kaizen calibrate
TOOL   python3 <plugin>/lib/run.py kaizen calibrate
RESULT This command requires approval
permission_denials: 2 (both Bash, both kaizen calibrate)
```

Non-interactively the missing approval is a denial, not a prompt. Nothing was written: `.plainspoken/kaizen/` didn't
exist afterwards. The agent stopped at step 2 and said why. Its advice was to "allow `python3 <plugin>/lib/run.py
kaizen *`", which would pre-approve `apply` as well (see O2).

**Run 4, granted `Bash(python3 <plugin>/lib/run.py kaizen calibrate*)`:**

```
KZ-20261014-6dcaa4: rule 2b: loosen (effective false positives 16% over 25 fires): claude_warn_total 4 → 5
--- a/rules.toml
+++ b/rules.toml
@@ -4,7 +4,7 @@
 [thresholds."default"]
 em_dash_max = 3
-claude_warn_total = 4
+claude_warn_total = 5
  emitted to file .plainspoken/kaizen/proposals/KZ-20261014-6dcaa4.md

kaizen calibrate: 1 proposal stored; nothing was applied
```

Files: `.plainspoken/kaizen/proposals/KZ-20261014-6dcaa4.json`, `KZ-20261014-6dcaa4.md` and
`.plainspoken/kaizen/last-calibrate.txt` (`2026-10-14T14:05:02+00:00`). The `.md` carries the evidence (dismissed 4,
docs 10, effective_fp 0.16, fires 25, upheld 0), `Effect: corpus: not measured (no corpus)`, the diff, the decision
format and the marker `<!-- plainspoken: decisions go below this line -->`. Only the 2b trigger fired. 12d (1 fire,
1 dismissal) stays under the 20-fire floor, as it should.

## 4. The person's approval (by the operator, by hand)

```bash
printf '\nAPPROVE: Tester: e2e approval\n' >> .plainspoken/kaizen/proposals/KZ-20261014-6dcaa4.md
```

The agent under test wrote no decision line in any run.

## 5. decisions → apply

**Run 5** (no grant; `decisions` is in allowed-tools):

```
KZ-20261014-6dcaa4 approved by Tester: e2e approval
```

Ledger: `event decision · actor human · outcome approved · rule 2b · facets {by: Tester} · proposal
KZ-20261014-6dcaa4 · reason "e2e approval"`.

**Run 6, apply `--dry-run` with no grant.** The agent ran `kaizen decisions; …; kaizen review; …` (allowed, `no new
decisions` / `approved by Tester, not applied`), then `kaizen apply … --dry-run --rules ruleset/rules.toml`. That was
denied twice, the same way as run 3 (`contains multiple operations … requires approval`, then `This command requires
approval`). So even the dry run needs the grant. `ruleset/rules.toml` was unchanged.

**Run 7, dry run with `Bash(python3 <plugin>/lib/run.py kaizen apply*)`:**

```
-version = "4.1.0"
+version = "4.2.0"
 [thresholds."default"]
-claude_warn_total = 4
+claude_warn_total = 5
kaizen apply: dry run, nothing written (ruleset/rules.toml)
```

The agent showed the diff and asked for a go. It didn't apply.

**Run 8, the person's go in the prompt.** The agent ran decisions and review again, the dry run again, then:

```
kaizen apply: KZ-20261014-6dcaa4 applied to ruleset/rules.toml (ruleset 4.2.0); changelog ruleset/RULESET-CHANGELOG.md
kaizen review: no proposals waiting
```

Checks afterwards:
- `ruleset/rules.toml`: `version = "4.2.0"`, `claude_warn_total = 5` (2 lines changed).
- `ruleset/RULESET-CHANGELOG.md`, new top entry:
  ```
  ## 4.2.0 (2026-10-14)

  - KZ-20261014-6dcaa4: rule 2b, loosen (trigger: fp). rule 2b: loosen (effective false positives 16% over 25 fires): claude_warn_total 4 → 5
  - Evidence: dismissed 4; docs 10; effective_fp 0.16; facets kind {'false_positive': 4}; fires 25; upheld 0
  - Approved by Tester.
  ```
- Ledger: `event apply · actor engine · outcome applied · rule 2b · ruleset_version 4.2.0 · facets {by: Tester} ·
  proposal KZ-20261014-6dcaa4`.
- `<plugin>/data/rules.toml` and `<plugin>/data/RULESET-CHANGELOG.md`: sha256 the same before and after
  (`61bca4c2…cd615f` for the ruleset); `git status` in `<plugin>` clean.

## 6. Stop nudge

`claude -p` surfaces a Stop hook's `systemMessage` in stream-json as
`{"type":"system","subtype":"informational","content":"Stop says: …","level":"notice"}`. So this is observed
directly, not reconstructed by calling the hook by hand:

| Run | Ledger state at session end | Nudge |
|---|---|---|
| 1 (check) | 58 events, no calibrate yet | `Stop says: plainspoken: kaizen calibrate is due (58 new events since the last one) — /plainspoken:kaizen calibrate` |
| 2 (dismiss) | 59 | `… calibrate is due (59 new events …)` |
| 3 (calibrate denied) | 88 (after seeding) | `… calibrate is due (88 new events …)` |
| 4 (calibrate) | 1 proposal pending | `Stop says: plainspoken: 1 kaizen proposal(s) await a decision — /plainspoken:kaizen review` |
| 5–8 (after the decision) | approved, then applied | none (no `informational` line in any of the four) |

Per-session state (`kaizen-nudge-state.json` in the plugin data folder) held exactly one `shown` key for each of
sessions 1–4 and none for 5–8. As a cross-check after apply, the hook run directly
(`echo '{"session_id":"direct-after","hook_event_name":"Stop",…}' | CLAUDE_PROJECT_DIR=<scratch>
CLAUDE_PLUGIN_DATA=<tmp> python3 <plugin>/hooks/kaizen_nudge.py`) printed nothing and exited 0.

## 7. Backstop probe

Run 1's 8 `agent_handback` friction lines show the backstop fired for every judge run. They don't show which hook
event did it, so for run 9 I copied the plugin to `/tmp` and added one line to the copy's `hooks/kaizen_backstop.py`
only. It appends `hook_event_name`, `tool_name`, `agent_type`, an 8-character prefix of `agent_id` and the sorted
stdin keys to a log under `/tmp`. The repo wasn't touched. Run 9 was the same check on the same fixture in a second
scratch project. It ended `PASS · coverage 41/41`, with one fix pass and 8 judge runs.

```
8 × {"hook_event_name": "SubagentStop", "tool_name": null, "agent_type": "plainspoken:tells-judge", "agent_id": "a…", 
     "keys": ["agent_id", "agent_transcript_path", "agent_type", "background_tasks", "cwd", "effort",
              "hook_event_name", "last_assistant_message", "permission_mode", "prompt_id", "session_crons",
              "session_id", "stop_hook_active", "transcript_path"]}
```

- **SubagentStop fired once per judge run (8/8)**, with `agent_type` exactly `plainspoken:tells-judge` and a distinct
  `agent_id` each time. Friction got 8 lines.
- **PostToolUse(SubagentHandback) never fired.** No subagent in runs 1 or 9 called a tool named `SubagentHandback`.
  `tells-judge` has `tools: Read, Grep, Glob` and returns its reply as its final message. The PostToolUse entry is
  harmless (the dedupe by `agent_id` means it could never double-count), but SubagentStop alone is what counts the
  judges.
- SubagentStop stdin carries `last_assistant_message`, which is the judge's full reply, including evidence quotes from
  the article. The backstop reads only `agent_type` and `agent_id` and stores neither the message nor the id. That
  matters if anyone extends the hook later.

Recorded in `docs/claude-code-facts.md` §9.

## Gaps found

No engine bugs: every command did what its contract says. Two behaviours are worth routing:

- **G1. A finding the fix pass removed can't be dismissed.** `kaizen dismiss` only matches BLOCK or WARN findings in
  the current lint, the one whose `article_sha256` matches the file now. The check skill fixes before it reports, so a
  person reading run 1's summary ("I deleted 'robust and seamless'") and disagreeing has nothing to dismiss:
  `kaizen dismiss drafts/post.md --rule 2 --kind voice --reason '…'` on the fixed file gives `plainspoken: kaizen
  dismiss: rule 2 has no finding in the current check`, exit 1. That was checked with engine calls in a throwaway copy
  of `<scratch>`. Expected, from check SKILL.md's closing line ("If the person disagrees with a finding … `run.py
  kaizen dismiss`"): a way to dismiss a finding from the check's first lint, or from the `.checked.md` snapshot.
  Today the only route is to revert the fix and re-lint, which is what step 2 did.
- **G2. The agent chains `; echo "exit=$?"` onto CLI calls.** The kaizen reference says "one Bash call per command, and
  nothing chained onto a CLI call". In runs 2 and 4–8 the agent still appended `; echo "exit=$?"` to every call, and in
  runs 6–8 it chained `kaizen decisions; …; kaizen review; …` into one call. Claude Code allowed the chains when every
  part was pre-approved, so nothing broke. For `calibrate` and `apply` the chained form was what got denied first,
  which made the agent retry. The skill wording isn't being followed. Not an engine problem.

## Other observations

- **O1.** The changelog's evidence line prints the facets as a Python dict repr (`facets kind {'false_positive':
  4}`). It's readable but looks unfinished next to the rest of the entry. Cosmetic.
- **O2.** When `calibrate` was denied (run 3), the agent told the person to allow `run.py kaizen *`. That broad rule
  would pre-approve `apply` too, which removes the approval's second check. The reference could tell the agent to
  suggest only the one subcommand it needs (`kaizen calibrate*`).
- **O3.** Proposal ids and changelog dates use the UTC date (`KZ-20261014-…`, `## 4.2.0 (2026-10-14)`), while the
  scratch host's local date was already 15 October. That's consistent with the ledger's UTC timestamps.
- **O4.** `python3 scripts/dev/leak_guard.py --help` gives a traceback (`FileNotFoundError: '--help/data/leak-denylist.txt'`):
  the dev script takes its first argument as the root. It's dev tooling, not the CLI, so the no-traceback rule doesn't
  strictly apply.
- The skill's allowed-tools pre-approve the local subcommands in `-p` mode as well: `dismiss` and `decisions` ran with
  no `--allowedTools`.

Not tested here: the github and trello adapters (only `file` ran), `kaizen mine`, `published`, `diff`/`missed`,
`uphold`, `--target profile`, the stale-proposal refusal on a live run (unit-tested), and an installed (not
`--plugin-dir`) plugin, whose cache-write refusal therefore wasn't exercised.
