# Report-file contract

Every file the engine writes for one article lives in one reports directory (default `.plainspoken/reports/` under
the current project; `--reports DIR` changes it). File names start with the article's key:

    key = <file stem>-<first 8 hex of sha256(project-relative POSIX path)>

Each file, what writes it, and what it's bound to:

- `<key>.lint.json`: written by `check`; bound to article_sha256, profile_sha256, ruleset_version, content_type.
- `<key>.J1.judge.json` … `<key>.J4.judge.json`: written by `judge-record --group Jn` (or `--all` for all four);
  bound to article_sha256, profile_sha256, ruleset_version (stamped from the current lint).
- `<key>.justify.json`: written by `justify --template --write` (then filled in by the check skill); bound to
  article_sha256.
- `<key>.JR.judge.json`: written by `judge-record --group JR`; bound to article_sha256 + justify_sha256,
  profile_sha256, ruleset_version.
- `<key>.report.json`: written by `merge`; bound to everything above.
- `<key>.reply.json`: written by the check skill (all four judge replies one after another, or one reply on a
  retry or for JR), deleted by `judge-record --from`; bound to nothing (scratch).
- `<key>.claims.json`: written by `claims status`; bound to article_sha256, ledger_sha256 (the status, its reasons,
  the gaps and the checker record it read).
- `<key>.claims-check.json`: written by `claims record` (the isolated claims checker's verified reply); bound to
  article_sha256, ledger_sha256, rubric_sha256, matrix_sha256 (the matrix file's hash, or `none`), recorded_at.
- `<key>.claims-reply.json`: written by the claims skill (the checker's raw reply, its JSON object only), read by
  `claims record --from`; bound to its own article_sha256 + ledger_sha256 + matrix_sha256, copied from
  `claims checker-input` (scratch; overwritten each round).
- `<key>.delivery.json`: written by `reader-value deliver --reviewer delivery-checker` (the isolated reviewer's
  verified reply) or `--reviewer self-check` (the writer's own reading); read back by `reader-value status`; bound to
  article_sha256, contract_sha256, rubric_sha256, reviewer, recorded_at.
- `<key>.delivery-reply.json`: written by the reader-value skill (the reviewer's raw reply, its JSON object only),
  read by `reader-value deliver --from`; bound to its own article_sha256 + contract_sha256, copied from
  `reader-value deliver-input` (scratch; overwritten each round).
- `<key>.checked.md`: written by `check`, only when kaizen capture is on for `check` and it saves `<key>.lint.json`
  (not with `--no-save`, `--no-record` or `--out`); bound to the article's exact bytes as checked, so its sha256 is
  the lint's article_sha256 (the snapshot `kaizen diff` reads).

Hash formats differ by file type. The lint, judge, justify and report files carry `article_sha256` as bare hex
(`3f2a…`); the claims files (`claims`, `claims-check`, `claims-reply`), the delivery files (`delivery`,
`delivery-reply`) and the ledger's `source_content_hash` carry `sha256:<hex>`. Compare a hash only with the same
field in a file of the same type, never across the two families.

`merge` treats a file as stale, and the report as INCOMPLETE, when its bound hashes or stamps don't match the article,
profile and ruleset now in use. `profile_sha256` covers the profile file and its calibration-notes file, so editing
either one invalidates the lint and every judge file. `judge-record` refuses a reply when there's no current lint.
`claims status` reads `<key>.claims-check.json` only when its bound hashes match the article and ledger on disk now,
and its `rubric_sha256` and `matrix_sha256` match the rubric and the configured matrix; otherwise the status can't be
PASS (`checker result stale`, `checker result stale (rubric changed)`, `checker result stale (matrix changed)`, or
`checker record unreadable` for a malformed file).
It also rechecks every pin of every claim that isn't `removed`: a `verified` claim with no `binding.passage`, a
passage missing from its saved source, a `passage_sha256` that doesn't match, an unreadable snapshot, a snapshot
outside `[claims] sources_dir` or that is the article itself (`snapshot_outside_sources`), a primary passage with no
`source_snapshot`, or a `derived` claim whose `derivation.inputs` names no live claim makes it INCOMPLETE.
`derivation.derived_from_external` (files or URLs a derivation used that aren't claims) is never read as claim ids;
a derivation with neither field is a validation error. A changed source that still holds the passage
(`source_changed`) and an additional passage on another page (`source_url`) are listed as `note: …` reasons and
don't stop a PASS. Only a PASS ends its reasons with `checker: PASS (n warnings)`; an INCOMPLETE or BLOCKED status
never does, though its `check` field still holds the record it read. When `claims status` can't report at all (exit
2: a configured matrix that isn't there, an unreadable article, an ambiguous ledger), it first rewrites
`<key>.claims.json` as INCOMPLETE, with the error as its one reason, so an earlier PASS never outlives the error.
`claims record` refuses to bind a reply to a stale ledger, or a reply whose own `article_sha256` / `ledger_sha256` /
`matrix_sha256` (copied from `claims checker-input`) are missing or not current (`stale reply`), and writes nothing.
A reply that isn't exactly one valid JSON object (two fenced blocks, a competing object in the prose, a duplicated
key) is recorded as INCOMPLETE (exit 2), unless it names an `article_sha256`, `ledger_sha256` or `matrix_sha256` other
than the current one: then it answered another version, and it's refused like a stale reply, with nothing written.
Each finding keeps `evidence_verified`; `unverified_evidence` counts the quotes under three words or found neither
in the article nor in a pinned passage, and any of them keeps the record from PASS.
`<key>.delivery.json` holds the delivery gate. Its `result` is PASS only when `reviewer` is `delivery-checker` (the
isolated agent), every item in `data/rubrics/delivery.md` passed (or is a permitted `n/a`) with its evidence found
verbatim in the draft, the reply said PASS and `modules.check` found nothing; any `fail` item or module finding makes
it FAIL, and anything else INCOMPLETE. A `reviewer = "self-check"` record keeps the writer's `reading` beside a
`result` that is FAIL or INCOMPLETE, never PASS. `reviewer` is the caller's declaration, not a proof: `deliver`
requires `--reviewer delivery-checker` or `--reviewer self-check` (no default, so leaving the flag out is a usage
error, exit 2), and it records what it's told, the same trust model as `claims record`. A host reads the gate with
`reader-value status <draft> [--contract PATH] [--json]`, never from `result` alone: it recomputes the draft,
contract and rubric hashes, prints STALE when any of them moved since the record was written (an old PASS never
stands for new text), and PASS only for a current record from `delivery-checker` that says PASS while the contract
still validates; otherwise FAIL or INCOMPLETE with its reasons. It exits 0 only for a current PASS, 2 when the
draft or contract can't be read, and writes nothing. `reader-value deliver`
refuses a reply whose hashes are missing or not current (`stale reply`, nothing written), records a malformed reply
as INCOMPLETE (exit 2) unless it names another version's hash, and records INCOMPLETE when the contract no longer
validates (exit 1). `reader-value deliver-input` refuses a contract that doesn't validate (exit 1), or that is the
draft itself (exit 2).
A ledger or `sources` path `paths` can't resolve (a malformed `[claims]` section) prints as `(unresolved: <reason>)`,
exit 0.
`check` also records what it found in the kaizen ledger (`[kaizen] ledger_dir`, default `.plainspoken/ledger`): one
`fired` event per BLOCK or WARN finding, and when it saves `<key>.lint.json`, one `fixed` event per BLOCK or WARN span
that the previous `<key>.lint.json` had and this check doesn't (same profile and ruleset, a different article hash).
`--no-save` still records `fired`; `--no-record` records nothing, saves no report (it refuses an `--out` that is
`<key>.lint.json`) and leaves the snapshots alone. The lint-watch hook records `fired` when a file's result changes.
An event holds hashes, ruleset words and section kinds, never article text unless `[kaizen] excerpts = true`. Capture
never changes a command's output or exit code: a capture error is one `plainspoken: kaizen capture skipped: …` line on
stderr, and `[kaizen] capture = false` turns it off. `[kaizen] capture_sources` keeps some sources (`check`, `merge`,
`judge`, `lint-watch`; default all four): a source left out writes no events and no friction (`check` then writes no
snapshot either, and `judge` drops `judge-record`'s friction and the backstop's count).

`merge` records what the judges decided once the report is written: each judge rule entry's own verdict (`fired`
for the judge's `fail`, `passed` for its `pass`), with facet `agree` on rules both the lint and a judge look at, and
each JR-reviewed justification as `justified:<kind>` then `jr_accept` or `jr_reject`. Judge evidence and
justification reasons are never stored, even with excerpts on. An INCOMPLETE merge logs `merge_incomplete` friction,
and a reply `judge-record` refuses logs `judge_reply_rejected` friction (both with the engine's message, file names
and values taken out). In `<key>.report.json`, each judge rule entry carries `judge_verdict`, the judge's own call,
beside `verdict`: when a lint BLOCK forces the verdict to `fail`, `judge_verdict` still says what the judge decided,
and that's what the ledger records.

The claims ledger isn't a report, but it's named with the same key: `<ledger_dir>/<key>.claims.toml` (or
`.claims.json`; `[claims] ledger_dir`, default `.plainspoken/claims`), so two articles with the same stem in
different folders never share a ledger. A ledger from before v0.5.0, named for the stem alone
(`<stem>.claims.toml`), is still used when there's no keyed one and its `source_file` is the article; one whose
`source_file` names another article belongs to that one, and one whose `source_file` names no file is an error that
says what to rename it to, never a silent pick. `python3 lib/run.py paths <article>` prints every path, the ledger's
included; callers never build names.

## Reading the report from a host

`data/schemas/report.schema.json` is the shape of `<key>.report.json`: every field, its type, and the status, verdict
and severity values. A v0.4.0 report validates against it. A new field means a schema change and a line here, and
the schema refuses keys it doesn't list, so validate with the schema shipped in the same plugin version; a reader that
doesn't validate should ignore keys it doesn't know. `merge` writes the report atomically (a temp file in the same
folder, then a rename), so a reader sees the old report or the new one, never half of one. The lint, judge and claims
files are written the same way.

**Use the same root.** The report key and the reports folder depend on the project root that `check` and `merge`
used: `CLAUDE_PROJECT_DIR` when it's the folder the command ran in or one of its parents, else the nearest folder up
that holds `.plainspoken/config.toml` or `.git`, else the folder itself. A reader must use that root too: run
`paths <article>` from it (or with the same `CLAUDE_PROJECT_DIR`) instead of building names. The report's `article`
field is the path exactly as it was given to `merge`, so it can be relative to the folder `merge` ran in. Treat it as
a label: find the report by its key, and check `article_sha256` against the file you already know.

**Check the report is current.** `python3 lib/run.py profile --json [<article>]` prints the stamps a report is bound
to:

    {"name": …, "path": …, "profile_sha256": …, "ruleset_version": …, "root": …}

With an article it reports that file's profile (its `[engine] profiles` match first, as `check` and `merge` resolve
it); without one, the project's profile. Pass the same `--profile` / `--plugin-profile` (or `PLAINSPOKEN_PROFILE`)
that `check` and `merge` got. `root` is the project root the command used. A report is current only when its
`article_sha256` is the sha256 of the article's bytes now and its `profile_sha256` and `ruleset_version` equal the
ones `profile --json` prints; otherwise rerun `check` and `merge` before trusting `status`.

## Host adapter notes (claims ledgers)

Two facts a host needs when it converts its own claim ledgers to plainspoken's:

- **Sign-off is `human_signoff`.** An owner's sign-off on a claim is the `human_signoff` block (`signed`,
  `signed_by`, `against_run`, `findings`, `wording`, `scope_note`). A host whose ledgers name that block another way
  (after the person who signs, say) maps it to `human_signoff` in its converter. The schema rejects any other key
  on a claim, so an unmapped block is a schema error, never a sign-off read silently. The signed `wording` must
  still appear in the article (the sign-off row under Text normalisation), or the sign-off is void.
- **A ledger without saved sources is INCOMPLETE.** `claims status` rechecks every pinned passage against its saved
  source, offline. A converted ledger whose bindings have no `source_snapshot` reports each such passage as
  `pin <claim id> unchecked: passage: no binding.source_snapshot, …`, and a `verified` claim with no
  `binding.passage` as having no pinned passage, so the status is INCOMPLETE, never PASS. That's by design: a pass
  needs a source the engine can read again. The host either saves each source's text under `[claims] sources_dir`
  and re-pins with `claims pin` (which records `source_snapshot` and both hashes), or reports those articles as
  INCOMPLETE.

## Kaizen files

Each path (under the project root), what writes it, and what it holds:

- `.plainspoken/ledger/YYYY-MM.jsonl`: written by `check`, `merge`, the lint-watch hook, `kaizen dismiss` / `uphold` /
  `missed` / `published` / `decisions` / `apply`, `calibrate`, `mine`; holds one event per line (schema v1, at most
  4,096 bytes), in the month of its own `ts` (UTC); appended with O_APPEND, never rewritten.
- `.plainspoken/ledger/friction.jsonl`: written on capture errors and by `merge`, `judge-record` and the backstop
  hook; holds `{v, ts, kind, source, detail}`, with kinds `merge_incomplete`, `judge_reply_rejected`,
  `agent_handback` (source: the agent type, detail empty), `capture_error` and `skill`.
- `.plainspoken/kaizen/proposals/<id>.json`: written by `kaizen calibrate`, `kaizen mine`; holds one proposal
  (`KZ-YYYYMMDD-xxxxxx`): its edits as a diff, the base ruleset hash, the corpus effect, the adapter and its ref; the
  id is a hash of the edits, so a hand edit makes `apply` refuse.
- `.plainspoken/kaizen/proposals/<id>.md`: written by the file adapter (every mined proposal, whatever the adapter);
  holds the proposal for a person to read, with decision lines below its marker; the plugin never writes a decision
  line.
- `.plainspoken/kaizen/last-calibrate.txt`: written by `kaizen calibrate`; holds when calibrate last ran, with or
  without proposals (the Stop nudge's clock).
- `.plainspoken/kaizen/CHANGELOG.md`: written by `kaizen apply --target profile`; holds one entry per applied profile
  change, naming the approver.
- `.plainspoken/kaizen/mining/<YYYY-MM>/<model id>/<brief stem>.md`: written by the kaizen skill (mining drafts);
  holds one draft per brief and model, read by `kaizen mine --drafts`.

`[kaizen] ledger_dir` (relative to the project root, default `.plainspoken/ledger`) moves the ledger month files and
`friction.jsonl`. `[kaizen] proposals_dir` (default `.plainspoken/kaizen`) moves `proposals/` (the `.json` and `.md`
files), `last-calibrate.txt` and the profile `CHANGELOG.md`. The mining folder doesn't move: the kaizen skill always
writes drafts under `.plainspoken/kaizen/mining/`, and `kaizen mine --drafts` names it. The ledger's decision events,
not the proposal files, say whether a proposal is approved. `RULESET-CHANGELOG.md`, beside the ruleset `kaizen apply`
edits, gets one entry per applied ruleset change. The loop in plain words, with what's stored and what isn't:
`guides/kaizen.md`.

## Text normalisation

The claims engine compares text in four places. Each one straightens typographic quotes and collapses whitespace, and
normalises only what's listed beyond that:

- **Pins** (`claims pin`, `claims recheck`), a passage against its saved source: nothing more; case and markdown link
  syntax count.
- **Evidence** (`claims record`), a checker's quote against the article and the pinned passages: it also ignores case,
  markdown link syntax (`[text](url)` reads as `text`), and `…` vs `...`.
- **Gaps** (`claims gaps`), an article value against the ledger: it also ignores case, thousands commas (`1,200` =
  `1200`), and `900M` vs `900 million` (also `b`/`billion`, `k`/`thousand`).
- **Sign-off** (`human_signoff.wording` against the article): nothing more; a case change voids the sign-off.
