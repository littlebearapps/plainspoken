# The kaizen loop

plainspoken's checks will sometimes be wrong: a rule fires on writing that's fine, or misses a tell a person can
see. The kaizen loop records what the checks flagged and what people did about it, and turns that record into
proposed ruleset changes. A proposal changes nothing until a person approves it and someone runs `kaizen apply`.

Everything here runs from `/plainspoken:kaizen <mode>` (manual only) or the CLI, `python3 lib/run.py kaizen …`.
Each subcommand prints its own `--help`.

## 1. Capture

Capture happens as you work, without a separate step:

- `check` records one `fired` event per BLOCK or WARN finding, with `--no-save` and `--out` too. When it saves a new
  lint for an edited article, it also records a `fixed` event for each finding the edit removed. For a one-off look
  that shouldn't count as evidence, `check --no-record` prints the lint and records nothing: no event, no report,
  and the snapshots already there stay as they are. A draft linted on stdin (`check -`) records nothing either.
- The lint-watch hook records `fired` when a file's result changes after an edit.
- `merge` records each judge's own verdict, whether the judge agreed with the lint on rules both look at, and each
  justification the JR judge accepted or rejected. An INCOMPLETE merge, and a judge reply `judge-record` refuses,
  are logged as friction.
- You record your own verdicts: `kaizen dismiss` (a finding is wrong; `--from-snapshot` reaches a finding a fix
  pass removed: `check` keeps the check before the last one for this), `kaizen uphold` (it's right),
  `kaizen missed` (a tell the check didn't flag, picked from the `kaizen diff` hunks), and `kaizen published`
  (which findings are still in the article you published).
- The backstop hook counts each run of a plainspoken agent once, so `kaizen report` can compare the judge replies
  that came back with the ones that were recorded.

Every other skill ends with a reminder: if you disagree with a finding, or Claude had to work around a step, record
it or say so.

**What's stored.** The ledger lives in `.plainspoken/ledger/` (one file per month, plus `friction.jsonl`). An event
holds hashes (of the finding's text, the article and its project-relative path), the ruleset words a finding matched
(an entry from a ruleset list, never your sentence), the kind of section it sat in (`faq`, `question`, `intro` or
`other`), and metric names. The only free text is a reason a person types for a dismissal, an uphold, a missed tell
or a decision, cut to 200 characters. Short excerpts (up to 120 characters) are stored only when you switch them on
with `[kaizen] excerpts = true` (or the plugin option, when the project config doesn't say).

**What's never stored.** Your article text (unless excerpts are on), judge evidence, justification reasons, the
judges' replies, and file paths. Friction lines hold an engine message with any file names and values taken out.

`[kaizen] capture = false` in `.plainspoken/config.toml` turns capture off. To keep some sources and drop others, list
the ones to keep in `[kaizen] capture_sources` (default all four: `check`, `merge`, `judge` and `lint-watch`; `judge`
covers `judge-record`'s rejected replies and the agent-run count). For example, `capture_sources = ["check",
"merge", "judge"]` stops the lint-watch hook recording `fired` events for every Markdown file you save. A capture
problem never changes what a command prints or its exit code: it adds one `plainspoken: kaizen capture skipped: …`
line on stderr.

With `check` capture off (either way), `check` saves no snapshot (`<key>.checked.md`, what `kaizen diff` compares
against), and the next `check` deletes the snapshots in its reports folder. Until then, and for any snapshot older
than the last `check` with capture off, `kaizen diff`, `missed` and `published` ignore the snapshot and say so:
edits made while capture was off were never recorded. Run `check` again with capture on for a fresh one.

## 2. Metrics

`kaizen report` prints one row per rule with any events: fires, documents, fixed, justified, JR accepted and
rejected, dismissed, upheld, missed and survived to publication, with the rates worked out from them. There's no
overall score, on purpose: a single number invites tuning the number rather than the writing.

The counts are **distinct spans, not events**. A span is one finding in one document. The lint-watch hook and repeated
merges record the same finding many times, and a finding that comes back after a fix is still the same span, so
each one counts once. `--since` and `--until` narrow the window.

The effective false-positive rate is dismissals plus JR-accepted `false_positive` justifications, less upholds, over
fires. The report also shows unreadable ledger lines (skipped, never fatal) and the friction counts.

## 3. Triggers

`kaizen calibrate` reads the ledger and looks for these, in this order (one candidate per rule):

1. **Stuck**: a BLOCK a person dismissed as `unfixable`. Fixes never add content, so if cutting, joining or
   restating can't clear a BLOCK, the rule needs to change. The proposal demotes it.
2. **False positives**: 20 or more fires with an effective false-positive rate over 10%. The proposal loosens a
   threshold, or demotes or shadows the rule when there's no threshold to turn.
3. **Missed**: the same rule or pattern recorded as missed in 2 or more documents. The proposal asks for a review.
4. **Kept**: a WARN rule justified, or kept to publication, in 3 or more documents. The proposal loosens it. A rule
   only the judges check counts as kept to publication when the published text still holds the span the judge
   quoted.
5. **Dormant**: a rule that hasn't fired in 90 days, on a ledger at least that old. The proposal starts retiring it.

**Narrow knobs first.** Where the evidence points at one corner of a rule, the proposal changes that corner rather
than the whole rule: a threshold for FAQ sections only when at least half the evidence spans sit in FAQs, or the words
themselves added to a list when the evidence is about particular words. The broad threshold is the fallback. The knobs
are listed in `data/kaizen.toml`.

A rejected proposal isn't made again for the same rule and action for 60 days.

## 4. Proposals

Each calibrate run stores at most 3 new proposals in `.plainspoken/kaizen/proposals/` (a `.json` file each, and a
`.md` file for the file adapter). Each shows the edit as a diff and its effect on your corpus (`[kaizen] corpus`).
Calibrate never applies anything. It sends each proposal through the adapter `[kaizen] adapter` names:

- `file` (the default): the `.md` file is where you decide.
- `github`: one issue per proposal, in `[kaizen.github] repo`.
- `trello`: one card per proposal, on `[kaizen.trello] list_id`.

`github` and `trello` need `[kaizen] approvers`, the people whose decisions count. Creating that issue or card is the
plugin's only outward write. The skill asks you before the first one in a project, and before each calibrate run
after that, because calibrate also re-sends any proposal it couldn't send before.

`kaizen review` lists what's waiting.

## 5. Decisions

You decide a proposal by posting your decision as its own comment on the issue or card, or as its own line below
the marker in the `.md` file. A decision is **one plain line**:

    APPROVE: <your name>: <reason>
    REJECT: <your name>: <reason>

At most 300 characters, capitals exactly as shown, a colon and a space, then the reason. No formatting: no markdown,
HTML, code, block quotes or links, no emoji (`:shortcode:` or keycap), no struck-out letters, no second line. Quote
marks and typographic dashes in the reason are fine. Anything else isn't read as a decision. A comment that starts
like one but breaks the rule is reported as needing a repost, with the proposal it's on, until you post a plain
decision after it. In the file adapter, only the lines below the last marker count.

In the file adapter, every non-blank line below the marker must be a decision line like that, or nothing below it
counts for that proposal. Edited or hidden comments never count either: to change your mind, post a new one. The
latest decision wins, and an approval can be withdrawn until the proposal is applied.

Then run `kaizen decisions`, which reads the decisions and records them in the ledger. It never sends anything.

**Who typed it.** An approval on github or trello comes from an account. If an agent can also use that account's
credentials, the engine can't tell whether a person typed the comment. Keep that in mind when you name approvers,
and don't let an agent post decisions. The kaizen skill never writes one, even when asked.

## 6. Apply

`kaizen apply <id> --dry-run` prints the diff and writes nothing. `kaizen apply <id>` makes the edit. A ruleset edit
bumps the ruleset version and adds an entry to `RULESET-CHANGELOG.md` beside the ruleset; a profile edit adds one to
`.plainspoken/kaizen/CHANGELOG.md`. Each entry names who approved it. It refuses, and writes nothing, when:

- there's no approval recorded, or the latest decision is a rejection;
- the proposal is stale: a value it edits changed since calibrate made it, or another proposal for its rule was
  applied since (that spent the evidence it rests on). A real apply (not `--dry-run`) then
  marks it **superseded**. That's its only write: the proposal is closed, needs no decision, and calibrate can
  propose for the rule again once new evidence builds. `kaizen review` lists it for one calibrate cycle. A change
  elsewhere in the file doesn't count: the edit is applied to the current file, and apply says it was rebased;
- the proposal file was edited by hand;
- it has already been applied;
- it's a review proposal, which carries no edit;
- the edit would leave a profile your project config names unloadable (removing a rule its `[rules] disabled`
  lists): take the rule out of that list first. The proposal stays approved;
- the file or its changelog can't be written. Both are written to temporary files first and then renamed, so a
  failure there changes nothing. Only a failure between the two renames leaves the edit in without its changelog
  entry, and apply reports that as applied, naming the changelog it couldn't write.

Where it writes: the ruleset of a plainspoken checkout (`--rules <path>`, or the plugin's own when it's a git
checkout), or, for a threshold-only proposal, a profile in your project (`--target profile`). It won't write into an
installed plugin's own files. With `--target profile`, apply edits the profile the proposal was made for, by its
`[profile] name`, not the one the project resolves when you run it (`PLAINSPOKEN_PROFILE`, `[engine] profile`), so in
a project with per-folder `[engine] profiles` the edit lands in the profile whose evidence it rests on. That profile
must be a file in your project: one your config names, or one in `.plainspoken/profiles/`. When it isn't (the
plugin's own `default`, or a file since deleted or renamed), when two project files share its name, or when the
proposal names no profile (calibrate had none to resolve), apply refuses, naming the profile, and writes nothing.
If you use the installed plugin, send the evidence upstream instead (section 9). It never edits the rubrics: when it
removes a judged rule, it names the rubric section left behind, for you to delete in the same change.

## 7. Retiring a rule

A dormant rule is retired in steps, one per calibrate cycle (28 days) after the last step was applied:

1. **deprecate**: the rule still runs, and the ruleset marks it as on its way out;
2. **shadow** (lint rules): it still runs, but its findings are informational only and never block;
3. **remove**: it's taken out of the ruleset.

A removal that would leave an alias pointing at nothing, or a knob in `data/kaizen.toml` for a rule that's gone,
becomes a review proposal instead. Those need a pull request by hand.

## 8. Mining new tells

`kaizen mine` looks for phrases and habits that model drafts use far more than people do. The skill has fresh
subagents write drafts from the fixed briefs in `evals/briefs/` (the brief and nothing else, each brief twice, since a
model needs at least 10 drafts to be mined), saves them by month and model, then compares them with a human corpus
you supply (`--corpus`, or `[kaizen] human_corpus`). For now the drafts come from Claude models only; other vendors'
models come later. At most 5 candidates are kept, each tagged with the
model it came from. Mined proposals stay local: they're never sent to github or trello, and you approve them in
their `.md` file. The recipe is in the skill's `references/mining.md`.

## 9. Sharing upstream

`kaizen report --share` prints counts only, as JSON: the plugin and ruleset versions, the window, and each rule's
counts. No profile name, document ids, hashes, ruleset words, reasons, excerpts or paths. Paste it into an issue on
the plugin's repository if you'd like a change made upstream. The skill shows it to you and never files it.

## 10. Limits

- Ledger lines are appended with one write each, so two sessions writing at once don't mix their lines. On a
  network file system (NFS), appends aren't guaranteed to stay whole.
- If calibrate sends a proposal to github or trello and then can't save the proposal file, the next calibrate may
  open a second issue or card for it. It says so when it happens: note the reference it printed.
- The Stop hook shows a one-line nudge, at most once per session for each message, when proposals await a decision or
  calibrate is due (no run in 30 days, and 50 or more new distinct events since the last one, or since the ledger
  began when calibrate has never run). It never adds anything to Claude's context.
