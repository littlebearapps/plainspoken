# plainspoken

<p align="center">
  <strong>Write like a person, not an AI.</strong><br>
  A writing plugin for AI agents that finds the tells in a draft, cuts them out without adding facts, and keeps
  every claim traceable to a source.
</p>

<p align="center">
  <a href="https://github.com/littlebearapps/plainspoken/actions/workflows/ci.yml"><img src="https://github.com/littlebearapps/plainspoken/actions/workflows/ci.yml/badge.svg" alt="CI" /></a>
  <a href="https://github.com/littlebearapps/plainspoken/releases"><img src="https://img.shields.io/github/v/release/littlebearapps/plainspoken" alt="Latest release" /></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-MIT-blue" alt="Licence: MIT" /></a>
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> · <a href="#what-you-get">What you get</a> · <a href="#how-a-check-works">How a check works</a> · <a href="#documentation">Docs</a> · <a href="#contributing">Contributing</a>
</p>

---

AI drafts have tells: stock words, padded lists of three, sentences that all run the same length, claims nobody can
trace. plainspoken catches them in two ways. First a lint, a fixed set of rules that runs as plain code and gives
the same answer every time. Then four judges, each a separate reviewer that reads the draft in a fresh context and
never sees your session. When it fixes a draft, it cuts, joins or restates what's already there and never adds a
fact. It keeps a ledger of what it flagged and what you did about it, and proposes changes to its own rules from
your verdicts. Nothing changes until you approve. It works in Claude Code and Cowork, Codex and Hermes Agent.

## Quick start

You need Python 3.11 or newer as `python3`. plainspoken uses the standard library only, so there's nothing else to
install.

**Claude Code and Cowork.** Add the Little Bear Apps marketplace, then install:

    /plugin marketplace add littlebearapps/lba-plugins
    /plugin install plainspoken@lba-plugins

Install it into the project that uses it unless you want it everywhere, because at user scope the lint after each
edit checks every Markdown file you edit in every project you open:

    claude plugin install plainspoken@lba-plugins --scope project

**Codex** (CLI and the ChatGPT desktop app):

    codex plugin marketplace add littlebearapps/lba-plugins
    codex plugin add plainspoken@lba-plugins

Start a new session and call the skills as `$plainspoken:check`, `$plainspoken:humanize` and so on.

**Hermes Agent:**

    hermes plugins install littlebearapps/plainspoken --enable

Then start a new session (or `/reset`).

**claude.ai and ChatGPT chat.** Neither has a shell, so the lint, the judges and the hooks don't run there. From a
machine with the plugin, `python3 lib/run.py setup --host claude-ai` (or `--host chatgpt`) prints a short writing
rule to paste into the app's preferences or a project's instructions.

**Check it worked.** Run `/plainspoken:doctor`. It checks `python3`, the plugin files, the reports folder and the
config, marks each `ok`, `WARN` or `not checked`, and changes nothing.

**Check your first draft:**

    /plainspoken:check post.md

Updates, pinning a release, the Hermes install scan and uninstalling are in [guides/install.md](guides/install.md).

## What you get

Thirteen skills. Four start on their own when a request fits; the other nine run only when you call them, so their
descriptions stay out of your context.

| Skill | What it does | Starts |
|---|---|---|
| `check` | Lints a draft, sends it to four isolated judges and fixes what they find, never adding | on its own |
| `humanize` | Rewrites AI patterns out of a draft in your voice, without adding facts | on its own |
| `write` | Drafts from your notes or brief in your voice, then runs the check | on its own |
| `plain-language` | Rewrites or checks text so someone outside the field gets it on one read | on its own |
| `voice` | Builds a voice profile from your own writing samples, applies it or checks against it | when called |
| `copy-audit` | Audits buyer-facing copy line by line against the evidence | when called |
| `register-check` | Flags tone, pressure and consent problems in a message before you send it (flags only) | when called |
| `adapt` | Drafts platform versions of a post; nothing is posted | when called |
| `claims` | Checks every number, quote, name and date against sources you've saved | when called |
| `reader-value` | Sets what the reader gets before drafting, then checks the draft delivers it | when called |
| `kaizen` | Turns your verdicts on findings into proposed rule changes you approve or reject | when called |
| `setup` | Turns the optional pieces on or off, or prints the paste-in text for chat apps | when called |
| `doctor` | Checks what this app can run and lists what to fix; changes nothing | when called |

Four agents do the reviewing, each in a fresh context, read-only:
- `tells-judge`: the check's judges, one per group of tells, returning JSON verdicts with the exact text as evidence.
- `cold-reader`: reads a text once as the reader your profile names and reports where it got lost.
- `claims-checker`: reviews the claim ledger against the article and the saved sources.
- `delivery-checker`: reads a draft against its reader-value contract. Where no subagent can run, the writer's own
  reading is kept as a self-check, which can keep a FAIL but never makes a PASS.

Hooks run alongside: lint after each edit of a draft file, a claims integrity check that flags unsourced numbers,
a publish gate on `git push` (off until you set it), and an optional writing nudge and drafting rule you switch on
with `/plainspoken:setup`. The kaizen loop records what the checks flagged and what you did, and proposes ruleset
changes from that evidence ([guides/kaizen.md](guides/kaizen.md)).

## How a check works

1. **Lint.** Fixed rules run first and flag what they find, with the line and the exact text.
2. **Judges.** Four isolated judges read the draft for the tells a rule can't catch.
3. **Merge.** Their verdicts and the lint are combined into one result, and the merge proves that a judge covered
   every group of tells before it gives a status.
4. **Fix.** Up to two fix passes cut, join or restate. A WARN you keep needs a reason another reviewer accepts.
5. **Result.** PASS means no BLOCK is left and every kept WARN has an accepted reason. FAIL means a BLOCK is still
   there. UNRESOLVED means no BLOCK is left but a flagged WARN has no accepted reason. INCOMPLETE means a step is
   missing or stale, usually because the draft changed after a judge read it.

Ask for findings only and the check follows its report-only route, where it runs no fix passes, leaves your file as
it is and lists each BLOCK and WARN with its line.
Reports go to `.plainspoken/reports/` in the project you run it from. More detail: [guides/checking.md](guides/checking.md).

## Privacy

Checks run on your machine and post or send nothing. The judges are subagents of the app you already use. Kaizen
proposals go to a GitHub issue or a Trello card only if you set that up, and the paid evals call outside models only
when you run them. The kaizen ledger holds hashes and rule words, not your text, unless you switch excerpts on.

### What stays on disk

With kaizen excerpts off (the default), checking and editing a draft still leave these files (`<key>` is the
draft's report key; `python3 <plugin>/lib/run.py paths <draft>` prints every path):

- `.plainspoken/reports/<key>.lint.json`: each finding, with its excerpt copied word for word from the draft.
- `.plainspoken/reports/<key>.checked.md`: a full copy of the draft as it was checked.
- `.plainspoken/reports/<key>.prev.lint.json` and `<key>.prev.checked.md`: the same pair for the check before, from
  the second check of a changed draft on.
- `.plainspoken/ledger/YYYY-MM.jsonl`: the kaizen events (hashes, ruleset words and section kinds, none of the
  draft's text).
- `lint-watch-state.json` and `integrity-state.json`: the edit hooks' state, a hash of the last result for each
  session and project-relative path, in `$CLAUDE_PLUGIN_DATA`, or `.plainspoken/` when that isn't set.
- Sometimes, and none of them holds draft text: `.plainspoken/ledger/friction.jsonl` (a capture error, a refused
  judge reply, an incomplete merge, or a plainspoken agent finishing in Claude Code), `kaizen-backstop-state.json`
  (that agent's id, beside the hook state above), `kaizen-nudge-state.json` (once the Stop hook has said proposals
  wait or calibrate is due) and `.plainspoken/kaizen/capture-off.txt` (when check capture is off and a ledger exists).

The full check adds the judge, justification and report files, and the claims and reader-value skills add theirs
when you run them; each one is in [docs/report-contract.md](docs/report-contract.md). `check --no-record` saves no
report (unless `--out` names another file) and no snapshot. With `[kaizen] capture = false`, the next check deletes
the snapshots (the `.checked.md` and `.prev` files), saves no new ones and stamps the time in `capture-off.txt`; it
still saves the lint file.

## Documentation

Every guide, in one list: [guides/README.md](guides/README.md).

- **Get started:** [install and update](guides/install.md) · [configuration](guides/configuration.md)
- **Using it:** [checking a draft](guides/checking.md) · [claims and reader value](guides/claims-and-reader-value.md) ·
  [voice profiles](guides/voice-profiles.md) · [kaizen](guides/kaizen.md)
- **Hosts:** [Codex](hosts/codex.md) · [Hermes Agent](hosts/hermes.md)
- **Reference:** [report contract](docs/report-contract.md) · [Claude Code facts](docs/claude-code-facts.md) ·
  [evals](guides/evals.md) · [evidence method](guides/evidence-method.md) · [Australian English](guides/locale-en-AU.md)
- **Help:** [FAQ](guides/faq.md) · [troubleshooting](guides/troubleshooting.md) · [changelog](CHANGELOG.md) ·
  [roadmap](ROADMAP.md) · [support](SUPPORT.md)

## Status

plainspoken is before v1.0, so expect changes between releases. The latest release and what changed in each one are
in [CHANGELOG.md](CHANGELOG.md); what's planned next is in [ROADMAP.md](ROADMAP.md).

## Contributing

Found a bug or want a feature? [Open an issue](https://github.com/littlebearapps/plainspoken/issues/new/choose).
Three forms there feed the kaizen loop directly: **False positive** (a finding that's wrong), **Missed tell** (one
it didn't flag) and **Pattern proposal** (a new tell to catch).

To contribute code or docs, read [CONTRIBUTING.md](CONTRIBUTING.md). Report a vulnerability privately through
[SECURITY.md](SECURITY.md), and find help in [SUPPORT.md](SUPPORT.md).

## Acknowledgements

The `humanize` skill is adapted from [blader/humanizer](https://github.com/blader/humanizer) (MIT), whose pattern
catalogue it keeps verbatim. Exact attribution and the upstream licence are in [NOTICE.md](NOTICE.md).

## About Little Bear Apps

plainspoken is made by [Little Bear Apps](https://littlebearapps.com) ([GitHub](https://github.com/littlebearapps)),
and it's listed in the Little Bear Apps plugin marketplace, `littlebearapps/lba-plugins`, beside other tools such as
PitchDocs, a plugin that writes repo docs. Other public projects include
[Untether](https://github.com/littlebearapps/untether), a Telegram bridge for AI coding agents, and Outlook
Assistant, an MCP server for Outlook.

Questions: hello@littlebearapps.com. Security reports: security@littlebearapps.com (see [SECURITY.md](SECURITY.md)).

## Licence

[MIT](LICENSE) · made by [Little Bear Apps](https://littlebearapps.com) 🐶
