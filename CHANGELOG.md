# Changelog

## [0.10.0](https://github.com/littlebearapps/plainspoken/compare/v0.9.0...v0.10.0) (2026-10-22)


### Features

* **check:** add --no-record, a read-only lint that records no kaizen events ([a64ebc8](https://github.com/littlebearapps/plainspoken/commit/a64ebc8e81fd9e13958391a0dd181c2f7e5c74a9)), closes [#1](https://github.com/littlebearapps/plainspoken/issues/1)
* **check:** record all four judge replies in one call with `judge-record --all` ([d30fb14](https://github.com/littlebearapps/plainspoken/commit/d30fb144a662896f8557c85914868e1e8910f292)), closes [#28](https://github.com/littlebearapps/plainspoken/issues/28)
* **claims:** brief as a saved source, `claims stamp`, and a plain edit/record order ([9c02702](https://github.com/littlebearapps/plainspoken/commit/9c02702efed7a623a44db18f144379eb0146a6e6)), closes [#31](https://github.com/littlebearapps/plainspoken/issues/31)


### Bug Fixes

* **check:** name only the tripped 12f slop metrics, with values and limits ([1ae3365](https://github.com/littlebearapps/plainspoken/commit/1ae3365d844a2b3422291debec5301b6cebde225)), closes [#26](https://github.com/littlebearapps/plainspoken/issues/26)
* **check:** one fix rule (cut, join, split or restate) that the 7d and 12f remedies fit ([36ecffd](https://github.com/littlebearapps/plainspoken/commit/36ecffdaa71fa61d917344024facab04e74eb3cd)), closes [#30](https://github.com/littlebearapps/plainspoken/issues/30)
* **check:** say which edits are fix passes and report from run.py status ([ed25d24](https://github.com/littlebearapps/plainspoken/commit/ed25d2438dafd7193b3b45bc703dbe4f6005b73c)), closes [#29](https://github.com/littlebearapps/plainspoken/issues/29)
* **check:** scale the 12f opening-repetition limit with length ([ba8bcbb](https://github.com/littlebearapps/plainspoken/commit/ba8bcbb7f7acaac8d7f32684a281e121701565f3)), closes [#25](https://github.com/littlebearapps/plainspoken/issues/25)
* **eval:** count numbers in words, and list derived numbers apart from new ones ([14996f1](https://github.com/littlebearapps/plainspoken/commit/14996f13b8f99a43fb1abbb4e3acd0d3aecbe9ae)), closes [#33](https://github.com/littlebearapps/plainspoken/issues/33)
* **evals:** grade only the piece between the markers, and drop the club name from the netball facts ([a003eea](https://github.com/littlebearapps/plainspoken/commit/a003eea9d48b2853f08bcf23ac18e5bbd23c360d)), closes [#34](https://github.com/littlebearapps/plainspoken/issues/34)
* **kaizen:** apply --target profile edits the proposal's own profile ([e99a2a1](https://github.com/littlebearapps/plainspoken/commit/e99a2a1df6ab7cf8c033582b87f00e8f0b882ca2)), closes [#2](https://github.com/littlebearapps/plainspoken/issues/2)
* **skills:** run the profile call as an explicit first step, not a load-time command ([d668820](https://github.com/littlebearapps/plainspoken/commit/d6688202f2acacb696ec5bb089dc8126b0659e5f)), closes [#12](https://github.com/littlebearapps/plainspoken/issues/12)
* **write:** raise a length the sources can't carry before drafting, and report the real word count ([f405242](https://github.com/littlebearapps/plainspoken/commit/f405242070c7a24a11034b4e30c265405f4a02da)), closes [#32](https://github.com/littlebearapps/plainspoken/issues/32)
* **write:** report the check and claims results from the engine, never from memory ([0e08d3f](https://github.com/littlebearapps/plainspoken/commit/0e08d3f7c0d47b40cb386a1eedcfca13525fea16)), closes [#24](https://github.com/littlebearapps/plainspoken/issues/24)
* **write:** run claims before the check, so claims edits don't force a second round of judges ([36c9e4a](https://github.com/littlebearapps/plainspoken/commit/36c9e4a4258d7f1ce28eab88e26653ccb32821f8)), closes [#27](https://github.com/littlebearapps/plainspoken/issues/27)
* **write:** the short-piece lint never stands in for write's check and claims steps ([d2c215b](https://github.com/littlebearapps/plainspoken/commit/d2c215b32bbf290540eef555168c7a133e5f3e81)), closes [#23](https://github.com/littlebearapps/plainspoken/issues/23)

## [0.9.0](https://github.com/littlebearapps/plainspoken/compare/v0.8.0...v0.9.0) (2026-10-21)


### Features

* long-form asks go to write with the full check; write never skips its check and claims steps ([#20](https://github.com/littlebearapps/plainspoken/issues/20)) ([cf1a1a7](https://github.com/littlebearapps/plainspoken/commit/cf1a1a7b9a4d04de4d68d5f8869a33fbb432bc6f))

## [0.8.0](https://github.com/littlebearapps/plainspoken/compare/v0.7.0...v0.8.0) (2026-10-21)


### Features

* tuned humanize, write and check from the pre-v1.0 eval campaign; drafting, long-form and fix eval suites ([#17](https://github.com/littlebearapps/plainspoken/issues/17)) ([5717832](https://github.com/littlebearapps/plainspoken/commit/57178320ca211540c3360041ba28c0cc45786af4))

## [0.7.0](https://github.com/littlebearapps/plainspoken/compare/v0.6.1...v0.7.0) (2026-10-21)


### Features

* writing nudge, drafting rule, setup, hooks in Codex and Hermes, humanize trigger fix ([#14](https://github.com/littlebearapps/plainspoken/issues/14)) ([b7e883f](https://github.com/littlebearapps/plainspoken/commit/b7e883f9885d13adb993a6d3e22547e99ac75330))

## [0.6.1](https://github.com/littlebearapps/plainspoken/compare/v0.6.0...v0.6.1) (2026-10-21)


### Bug Fixes

* **tests:** keep shell Trello credentials out of the CLI tests ([ac48aec](https://github.com/littlebearapps/plainspoken/commit/ac48aecf22f8a971fc4150b10cea498055f5e0ff))

## [0.6.0](https://github.com/littlebearapps/plainspoken/compare/v0.5.0...v0.6.0) (2026-10-20)

### Highlights

plainspoken now installs in Codex and Hermes Agent as well as Claude Code. The same skills, agents and engine run in
all three; each new host gets a short note on how to run the skills there (`hosts/codex.md`, `hosts/hermes.md`), and
the judges and checkers run as separate one-shot processes with a fresh context, built by `run.py agent-prompt`.

- **Codex:** `codex plugin marketplace add littlebearapps/lba-plugins`, then `codex plugin add plainspoken@lba-plugins`.
- **Hermes Agent:** `hermes plugins install littlebearapps/plainspoken --enable`. Hermes rates the plugin "caution"
  and asks you to confirm; over SSH or in a script, review the findings and add `--force`.
- Not yet outside Claude Code: the hooks (lint after each edit, publish gate, kaizen nudges) and the install-time
  settings. Run the check yourself before anything goes out.

### Features

* install in Codex and Hermes Agent ([875c23e](https://github.com/littlebearapps/plainspoken/commit/875c23ed872fa74cc1b4662ce0df17dad75138c1))


### Bug Fixes

* clear the Hermes install scan's avoidable HIGH findings ([987afd5](https://github.com/littlebearapps/plainspoken/commit/987afd567b94d623679b78fd11157bd6fea0d444))

## 0.5.0 — first public release (2026-10-20)

plainspoken is a Claude Code plugin that helps Claude write like a person: specific, honest and plain, in a stated
voice, with every claim traceable to a saved source. It checks drafts for the patterns that make text read as
machine-written, explains each finding, and only ever fixes by removing the pattern. It runs on Python 3.11+ with the
standard library only. This is the first public release, under the MIT licence.

### Skills

- **check:** lints a draft, sends it to four isolated judges, merges their verdicts and runs up to two removal-only
  fix passes. It ends on PASS, FAIL, UNRESOLVED or INCOMPLETE. A WARN is fixed or kept with a one-line reason that an
  isolated reviewer (JR) accepts or rejects.
- **humanize:** rewrites a draft without a full check, from a pattern catalogue adapted from blader/humanizer (MIT).
- **write, plain-language, voice, copy-audit, register-check, adapt:** draft from notes, make writing plainer (with
  the `cold-reader` agent for long texts), build a voice profile from your own samples, audit buyer-facing copy
  against its evidence, flag a message that reads wrong for its kind, and draft platform versions of a post. Nothing
  is ever posted or sent.
- **claims:** a claim ledger per article. Every number, quote, name and date is pinned to a passage in a source you
  saved; only the isolated `claims-checker` agent can turn the result into PASS.
- **reader-value:** a contract for the reader's benefit before drafting, and an isolated `delivery-checker` agent
  that checks the draft delivers it.
- **kaizen:** improves the checks from your verdicts (see below).

### Engine

- Ruleset 4.3.0: 55 rules, each checked by the lint, a judge or both, some in shadow (report only) until evidence
  promotes them. Per-content-type caps for articles and social posts, and en-AU, en-GB and en-US word lists.
- Voice profiles in TOML, a shipped neutral default, and per-folder profiles (`[engine] profiles` globs).
- A quotation that runs over several sentences stays quoted, so its words never count against the writer.
- Reports follow a documented contract with a JSON schema, are written atomically and stamp the command that wrote
  them. Every file is listed in `docs/report-contract.md`.
- Hooks: lint-watch after each edit, an integrity check for unsourced statistics in charts, TL;DRs and frontmatter,
  an opt-in publish gate on `git push`, an opt-in session brief, and a quiet kaizen nudge. All are off or silent
  until there's something to say, and hooks add no always-on tokens.

### Judges

- Four isolated judge groups (J1–J4) for the patterns a lint can't settle, plus JR for justifications. Each judge
  reads in a fresh context, returns strict JSON and is bound to the lint's profile and ruleset, so a verdict from an
  older draft or ruleset counts as stale.

### Kaizen

- A local ledger of what the checks flagged and what you did about it: hashes, rule ids and section kinds, with no
  raw text unless you switch excerpts on.
- `calibrate` proposes at most three ruleset or profile changes from that evidence; `mine` compares model drafts
  with a human corpus. Nothing changes until a person posts an `APPROVE:` line and runs `kaizen apply`, which
  refuses a stale proposal and records each change in a changelog (`data/RULESET-CHANGELOG.md` for the ruleset).
- Proposals go to a local file by default, or to a GitHub issue or Trello card if you configure one.

### Evals

- A 232-case golden set with held-out cases, a cross-vendor judge panel, rewrite evals against a no-plugin baseline,
  trigger evals for the skills, ablations of the optional pieces, and a blind reader test. The unit tests and the
  golden-set validation are free and run in CI; paid runs need a person's OK. Results so far are in
  `docs/acceptance/p6-evals.md`.

### Tooling

- A leak guard that keeps private names out of the repo. Its list lives outside the repo, hits are logged by
  position rather than by name, and names can be stored as keyed hashes.
- Link, frontmatter, release-version and always-on token-budget checks, and a portable export of the skills.
