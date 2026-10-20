# Changelog

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
