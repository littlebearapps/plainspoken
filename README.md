# plainspoken

A writing plugin that helps an AI agent write like a person: specific, honest, plain,
in a stated voice, with every claim traceable. Built for Claude Code; it also installs in Codex and Hermes Agent
(see [Codex and Hermes Agent](#codex-and-hermes-agent)).

Status: v0.7. It has:
- the anti-AI check and humanize skills, with four isolated judges;
- language skills (write, plain-language, voice, copy-audit, register-check, adapt), with the cold-reader agent;
- claims integrity and reader value (claims, reader-value), with the claims-checker and delivery-checker agents and
  the integrity hook;
- the kaizen loop: a ledger of what the checks flagged and what you did, calibrate, and approval-gated `kaizen apply`;
- evals: a 232-case golden set, a cross-vendor judge panel, rewrite evals, a smoke case per skill, a blind reader
  test and ablations;
- optional pieces you switch on with `/plainspoken:setup`: a writing nudge, a drafting rule, and lint after each
  edit in Claude Code, Codex and Hermes Agent.

A production host has already moved its own checks over to it.

Next:
- **v1.0.0:** one accept item is left: the rewrite-quality eval against a no-plugin baseline. Its first run
  (20 Oct 2026) showed no difference, because the model never started `humanize` on those prompts. v0.7 widens
  humanize's trigger wording, adds a slash arm (`--tag rewrite-slash`) and lint-counts both arms
  (`eval rewrite-delta`), so the re-run can show a difference if there is one. The tier-2 blind reader test runs
  after v1.0, once samples of the author's unassisted writing exist; tier 1, with human readers, comes later.
- **Smaller fixes:** a read-only lint mode for `check` that records no kaizen events
  ([#1](https://github.com/littlebearapps/plainspoken/issues/1)), and `kaizen apply --target profile` editing the
  proposal's own profile rather than the one the project resolves now
  ([#2](https://github.com/littlebearapps/plainspoken/issues/2)).
- **After v1.0:** an editor agent that can rewrite, not only cut. The publish gate and the kaizen nudges for Codex
  and Hermes Agent.

## Use

Requirements: Claude Code and Python 3.11+ as `python3` (standard library only). With an older `python3`, the
lint-watch hook skips with one line, and the CLI the skills call won't start.

Install it from the Little Bear Apps marketplace:

    /plugin marketplace add littlebearapps/lba-plugins
    /plugin install plainspoken@lba-plugins

The marketplace entry pins a release (v0.5.0 now), so a new version reaches you when that entry moves to the next
release. Background auto-update is off for third-party marketplaces until you turn it on: in `/plugin`, open
**Marketplaces**, select `lba-plugins` and choose **Enable auto-update** (or set `"autoUpdate": true` on the
marketplace's `extraKnownMarketplaces` entry in a project's `.claude/settings.json`).

Install it into the project that uses it (`claude plugin install plainspoken@lba-plugins --scope project`) unless
you want it everywhere. At user scope, the lint-watch hook lints every Markdown edit in every project you open.

### Codex and Hermes Agent

The same skills, agents and engine install in two more hosts. The skills are written for Claude Code, so each host
gets a short note on how to run them there, which the skills point to: [`hosts/codex.md`](hosts/codex.md) and
[`hosts/hermes.md`](hosts/hermes.md). In both, the judges and checkers run as separate one-shot processes with a
fresh context (`codex exec --sandbox read-only`, `hermes chat -q`), built by `run.py agent-prompt`.

Codex (CLI and the ChatGPT desktop app; it reads the same marketplace):

    codex plugin marketplace add littlebearapps/lba-plugins
    codex plugin add plainspoken@lba-plugins

Then start a new session and use `$plainspoken:check`, `$plainspoken:humanize` and the rest.

Hermes Agent:

    hermes plugins install littlebearapps/plainspoken --enable

Hermes scans a plugin before it installs it. It rates plainspoken "caution", mostly because the skills carry
Claude Code's load-time commands (`` !`python3 …` ``) and the engine runs Python, so it asks you to confirm. Over
SSH or in a script, where it can't ask, it refuses: review the findings and add `--force`. Then start a new session
(or `/reset`). Hermes loads `.hermes-plugin/`, which registers the skills as `plainspoken:<name>` and tells the
model where the plugin lives. To add it to one Hermes profile only, name the
profile first: `hermes -p <profile> plugins install littlebearapps/plainspoken --enable`. The install also warns
that the repo root has no `plugin.yaml`; that's expected, because the Hermes manifest sits in `.hermes-plugin/`.

Updates: this install follows the `stable` branch, which only moves when a release ships. Hermes checks for a new
commit once a day (`plugins.auto_update_check_hours`), `hermes plugins check-updates` checks now, and Hermes
Desktop shows an **Update** button. Apply it with `hermes plugins update plainspoken`. The update is scanned
again and asks "Update anyway?" for the same caution rating; add `--force` where it can't ask, such as a cron job.
For the same reason `plugins.auto_apply: true` doesn't update plainspoken yet: unattended updates don't accept a
caution rating. To stay on one release instead, pin its full commit with `--ref <sha>` (Hermes takes no tags or
branches there); `update` then leaves it alone, and `install --force --ref <new-sha>` moves it.

Hooks outside Claude Code: lint and the claims integrity check after each edit, and the optional writing nudge, run
in both (Codex runs plugin hooks only after you trust them: `/hooks` in Codex). Still missing: the publish gate and
the kaizen nudges, so run the check yourself before anything goes out; the install-time settings (pick a profile
with `[engine] profile` in `.plainspoken/config.toml`, and turn the optional pieces on with `/plainspoken:setup`);
and an enforced read-only sandbox for the agents in Hermes, where it's an instruction they follow.

Check a draft:

    /plainspoken:check post.md
    /plainspoken:check thread.md --content-type social

The check lints the file, sends it to four isolated judges, merges their verdicts and runs up to two fix passes
that cut, join or restate and never add a fact. It ends with PASS, FAIL, UNRESOLVED or INCOMPLETE, and writes its
files to `.plainspoken/reports/` in the project you run it from.

Run the CLI from anywhere in the project: it finds the project root (the nearest folder with
`.plainspoken/config.toml` or `.git`).

Rewrite a draft without a full check:

    /plainspoken:humanize post.md

Draft from your notes, or make writing plainer:

    /plainspoken:write notes.md
    /plainspoken:plain-language page.md --rewrite

For a text over about 600 words, or when you ask, plain-language hands it to the `cold-reader` agent. The agent reads
it once in a fresh context, as the reader your profile names, and reports in JSON where it got lost, which words it
didn't know and what it would do next. It never rewrites.

The other eight skills run only when you call them:

    /plainspoken:voice build samples/*.md                       # build a voice profile from your own writing
    /plainspoken:copy-audit hero.md                             # audit buyer-facing copy against the evidence
    /plainspoken:register-check email.md --kind follow-up       # flag a message that reads wrong for its kind (flags only)
    /plainspoken:adapt post.md linkedin bluesky                 # draft platform versions of a post (drafts only, nothing is posted)
    /plainspoken:claims post.md                                 # verify every number, quote, name and date against saved sources
    /plainspoken:reader-value outline post.md                   # set the reader's benefit before drafting (deliver checks it after)
    /plainspoken:kaizen review                                  # the proposed ruleset changes waiting for your decision
    /plainspoken:setup                                          # turn the writing nudge, drafting rule and lint after edits on or off

`write`, `check`, `humanize` and `plain-language` also start on their own when a request fits. `voice`, `copy-audit`,
`register-check`, `adapt`, `claims`, `reader-value`, `kaizen` and `setup` run only when you call them.

### Claims and reader value

Two manual skills keep a piece honest about what it says and what it gives the reader. `write` uses both: it runs
the reader-value outline before it drafts, and the claims skill on the saved draft.

    /plainspoken:reader-value outline drafts/hot-water.md   # the contract, before drafting; parks a piece with no honest benefit
    /plainspoken:reader-value deliver drafts/hot-water.md   # an isolated reviewer: does the draft deliver the contract?
    /plainspoken:claims drafts/hot-water.md                 # claim ledger + pinned passages + the isolated claims checker

The claims skill never fetches: you save each source's text under `.plainspoken/sources/` (the `sources_dir`), and
`claims pin` finds the passage in it or refuses. A source outside that folder, or the article itself, never counts.
The ledger (`.plainspoken/claims/<key>.claims.toml`, or `.claims.json`; `paths` prints it) holds one status per
claim. Only `claims status` says PASS, and only after the isolated `claims-checker` agent has reviewed the current
article and ledger. A changed article or ledger means INCOMPLETE until it's checked again. The reader-value contract
lives at `.plainspoken/reader-value/<draft stem>.reader-value.toml`. In deliver mode the isolated `delivery-checker`
agent reads the draft against that contract in a fresh context, and `reader-value deliver` records its verdicts in
`<key>.delivery.json`, bound to the draft, contract and rubric hashes. Only that reviewer's reply can make the result
PASS. Where no subagent can run, the writer's own reading is recorded as a self-check (`--reviewer self-check`): it
keeps a FAIL, and a PASS reading becomes INCOMPLETE. `reader-value status` reads the record back: STALE once the
draft, contract or rubric has changed, and PASS only for a current pass from the isolated reviewer.

The skills call these CLI subcommands (`python3 lib/run.py <subcommand>`; each prints its own `--help`):

- `claims hash | validate | candidates | gaps | pin | recheck | scaffold | status | checker-input | record`: hash
  the article, validate a ledger, list the values and quotes in an article and the ones the ledger misses, pin a
  passage in a saved source, recheck every pin offline, write a starter ledger, report the status, print the
  checker's input, and record its reply.
- `reader-value validate | modules | template | deliver-input | deliver | status`: validate a contract, check an
  article's `<!-- module:NAME -->` blocks, print a starter contract, print the delivery reviewer's input, record its
  reply, and read the delivery record back against the current files.
- `status <draft>`: the last saved check and claims status lines and the reader-value contract path, read back
  without running or writing anything, so `write`'s report quotes them. A check or claims step that never ran, or ran
  on an older version of the draft, shows as INCOMPLETE; it exits 0 only when both say PASS.

**The integrity hook.** After each Write or Edit of a target file, a PostToolUse hook flags prominent numbers that
nothing sources: a statistic in a chart, in the `> **TL;DR:**` block or in the frontmatter description with no link
to a source. Your own data takes an `<!-- integrity:allow -->` comment inside or beside the chart, or just above the
TL;DR (a marker inside a chart covers that chart, never the TL;DR), or `# integrity: allow` in the frontmatter, and a
`first_hand` claim in the ledger. When the file has a claim ledger, the hook lists the ledger's gaps instead.
It says nothing when there's nothing to flag; in warn mode it repeats itself only when a file's result changes.

Settings for all three go in `.plainspoken/config.toml`:

    [claims]
    ledger_dir = ".plainspoken/claims"     # relative to the project root
    sources_dir = ".plainspoken/sources"   # where saved source text lives
    regulated_matrix = "docs/regulated-claims.md"  # your own regulated-claims list; unset means none (the plugin ships none)
    platforms_extra = ["Acme Portal"]      # platform names to treat as claims, on top of the shipped list

    [reader_value]
    cta_phrases = ["book a site visit"]    # your own calls to action, which can never count as reader value

    [integrity]
    mode = "warn"                          # off | warn (the default) | block
    paths = ["content/**/*.md"]            # files the hook checks; unset means the targets option, else **/*.md

`block` returns a block decision on every edit while findings remain: the edit is saved, and Claude is told to fix
it before going on. Every claims report file is listed in `docs/report-contract.md`.

### Kaizen: improving the checks from your verdicts

The checks keep a ledger of what they flagged and what you did about it, in `.plainspoken/ledger/`: hashes, ruleset
words and section kinds, never your text unless you switch excerpts on. Tell it when a finding is wrong or right, or
when it missed something, and it proposes ruleset changes from that evidence. Nothing changes until a person approves
a proposal and runs `kaizen apply`.

    /plainspoken:kaizen dismiss post.md      # a finding is wrong (uphold: it's right; missed: a tell it didn't flag)
    /plainspoken:kaizen calibrate            # propose at most 3 changes from the ledger (never applies them)
    /plainspoken:kaizen decisions            # read the decisions people made, then `apply` an approved one
    /plainspoken:kaizen report --share       # anonymised counts to paste into an upstream issue

Proposals go to a file in `.plainspoken/kaizen/proposals/` by default, or to a GitHub issue or Trello card when you
set `[kaizen] adapter` and `[kaizen] approvers` in `.plainspoken/config.toml`. You decide by posting one plain line,
`APPROVE: <your name>: <reason>` or `REJECT: …`; the plugin never writes one. A Stop hook shows a one-line nudge when
proposals are waiting or calibrate is due, and adds nothing to Claude's context. The whole loop, what's stored and
what isn't: [guides/kaizen.md](guides/kaizen.md). Every file it writes: `docs/report-contract.md`.

### Voice profiles

A profile describes the voice the skills draft and check in. Copy `templates/voice-profile.toml` to
`.plainspoken/profiles/<name>.toml` and edit it, or run `/plainspoken:voice build` on five to ten of your own
writing samples. Activate it with `[engine] profile = "<name>"` in `.plainspoken/config.toml`.

Plugin options (set when you install or enable the plugin):

- `targets`: the globs the lint-watch hook checks after each Write or Edit. Default `**/*.md`.
- `strictness`: what the publish gate does on `git push`. `watch` (the default) does nothing, `warn` warns, and
  `block` refuses a push unless every gated file has a current PASS. The gate is a guardrail against accidental
  pushes of unchecked writing, not a security boundary (limits: `docs/claude-code-facts.md` section 6).

If you use the gate with a profile other than `default`, set `[engine] profile` in `.plainspoken/config.toml` as well.
The project config wins everywhere (skills, hooks, CLI). An installed copy's hooks see the plugin settings, but a
session that loads the plugin with `--plugin-dir` gives them none (`docs/claude-code-facts.md` section 11).

Project settings go in `.plainspoken/config.toml`, which beats the plugin option:

    [engine]
    profile = "default"          # a profile name, or a path to a profile TOML

    [gate]
    paths = ["content/**/*.md"]  # the files the publish gate checks; unset means it checks nothing
    strictness = "block"         # watch | warn | block; beats the plugin option; a value it can't read gives a warning and the push goes ahead, unless block is known

### Host setup

A project that already has its own checks can narrow what plainspoken does. Everything below goes in
`.plainspoken/config.toml`:

    [engine]
    profile = "default"                                  # files no entry below matches
    profiles = [                                         # first match wins
      { glob = "docs/**", profile = "technical" },       # a profile name, or a path relative to .plainspoken/
      { glob = "posts/**", profile = "profiles/essay.toml" },
    ]

    [lint_watch]
    mode = "on"                    # "off": the hook lints, says and records nothing
    paths = ["posts/**/*.md"]      # the files it lints; beats the plugin's targets option; unset means **/*.md

    [kaizen]
    capture_sources = ["check", "merge", "judge"]   # drop lint-watch events; default all four

- **One voice per folder.** Each `[engine] profiles` glob is matched against the file's path from the project root.
  `check`, `merge`, `judge-input`, `justify`, the lint-watch hook and the publish gate all use the file's own
  profile; `python3 <plugin>/lib/run.py config profile-for <file>` prints it, and the skills pass it to the calls that
  don't take a file. `--profile` and `PLAINSPOKEN_PROFILE` still come first.
- **Skills only when asked.** To stop Claude starting a skill by itself while keeping the slash command, deny the
  Skill tool for it in the project's `.claude/settings.json`:

      {
        "permissions": {
          "deny": ["Skill(plainspoken:write)", "Skill(plainspoken:check)",
                   "Skill(plainspoken:humanize)", "Skill(plainspoken:plain-language)"]
        }
      }

  `/plainspoken:write …` still runs (probed with Claude Code 2.1.303: `docs/claude-code-facts.md` section 11). Asking
  for a denied skill in plain words no longer works: type its slash command. When a skill hands over to a denied one
  (write to check, check to humanize), it reads that skill's file and follows its steps instead.

Every report file, and what each one is bound to, is listed in `docs/report-contract.md`. Add `.plainspoken/` to
your `.gitignore` so reports and hook state stay out of commits; to keep the project settings tracked, use:

    .plainspoken/*
    !.plainspoken/config.toml
    !.plainspoken/profiles/

## Optional: the writing nudge, the drafting rule and the session brief

All of these are off by default and add 0 tokens until you switch them on. `/plainspoken:setup` turns them on or
off for the app you're in and shows what's on; underneath it runs
`python3 <plugin>/lib/run.py setup --host <host> [--scope project|user] [--nudge on|off] [--rule on|off]
[--lint-watch on|off] [--dry-run | --remove | --status]`. It edits one config file, the project's
`.plainspoken/config.toml` or the user-wide `~/.config/plainspoken/config.toml`, marks every line it writes, and
`--remove` deletes only those lines.

| Piece | What it does | Where it runs |
|---|---|---|
| Writing nudge (`[nudge] mode = "on"`) | When a prompt asks for an email, a text, a post, a script, a page or a rewrite that sounds like a person, one line names the plainspoken step that fits: lint a short piece on stdin (`check -`), use write (draft, full check, fix) for a long one, use humanize for a rewrite. Chat, code and slash commands don't trigger it | Claude Code and Cowork (`UserPromptSubmit`), Codex CLI, app and ChatGPT Work (`UserPromptSubmit`), Hermes (`pre_llm_call`) |
| Drafting rule (`[rule] enabled = true`) | Every session starts with a short rule: whenever something people will read is drafted, use plainspoken. It's added by the plugin with this install's paths, so it never goes stale after an update, and it only applies where plainspoken is installed | Claude Code and Cowork |
| Lint after edits (`[lint_watch] mode`, on by default) | After a draft file is saved, the lint's findings come straight back | Claude Code, Cowork, Codex, Hermes |
| Paste-in text (`setup --host claude-ai` or `chatgpt`) | The same rule as text to paste into the app's personal preferences, custom instructions or a project's instructions | claude.ai chat, ChatGPT chat (neither runs hooks) |
| Session brief (`[brief] enabled = true`) | A short writing brief (at most 800 characters) at session start and in each subagent, never in plainspoken's own agents | Claude Code and Cowork |
| Output style (`/output-style plainspoken`) | The same guidance as an output style, for the main conversation only | Claude Code |

A project's config wins over the user-wide file, and the user-wide file wins over the Claude Code options (`nudge`,
`rule`). The user-wide file holds only `[nudge]`, `[rule]` and `[lint_watch]`.

The session brief and the output style aren't on by default yet: the Phase 6 ablation (21 drafts, 2026-10-16) gave no
lint evidence for either, and with 3 drafts per variant that's only a hint. The blind reader test decides.

## Evals

The evals measure whether the plugin does what it says: the judges against a held-out golden set, the skills'
triggers, rewrites against a no-plugin baseline, ablations of the optional pieces, and a blind reader test. CI runs
the unit tests for the free ones on every pull request and validates the golden set; the rest run on a Claude plan
or are billed, and a person OKs each billed run. What each one measures, what it costs and how to run it:
[guides/evals.md](guides/evals.md).

**Results so far** (`docs/acceptance/p6-evals.md`):
- On the golden set, Claude Opus as judge meets the 0.8 bar in every group in 3 of 3 runs. That's an upper bound,
  because most cases were built and labelled by Claude.
- A five-vendor panel judged all 226 cases then in the set through OpenRouter for US$3.86: GLM-5.3, GPT-6 Luna
  (J1–J4 only), Gemini 3.8 Flash, DeepSeek V4.1 Flash and Muse Glimmer 30B.
  - Its majority vote was right on 222 of 225 decided cases.
  - On the 17 cases backed by the owner's own decisions, DeepSeek got 16 right and Claude 15.
- Four other models were screened and left out: Cohere Command A+, Inception Mercury 2.5, Writer Palmyra X5 and
  Mistral Large 4.
- The blind reader test hasn't run yet. Its tier-2 run is the remaining v1.0.0 item, and it needs samples of the
  author's unassisted writing.

**Always-on token cost.** Measured 2026-10-19 with Claude Code CLI 2.1.303: `claude --plugin-dir . plugin details
plainspoken` reports `Always-on: ~1,042 tok`. That figure counts the seven manual-only skills (about 560 tokens),
whose descriptions Claude Code keeps out of context (`docs/claude-code-facts.md` section 7). Without them,
`python3 -m scripts.dev.token_budget .` reports 482 tokens, against a budget of 500 (the delivery-checker agent added
about 30; shorter cold-reader, tells-judge and humanize descriptions took about 15 off). Hooks add none. In v0.7 it's
486: humanize's wider trigger wording, paid for by a shorter tells-judge description; the setup skill is manual-only.
(`claude plugin details plainspoken` without `--plugin-dir` only finds an installed copy.)

## Develop

Work happens on `main`: open pull requests against it, and release-please cuts releases from it. The default
branch, `stable`, holds the latest release only; the release workflow moves it (`.github/workflows/stable.yml`), so
never open a pull request against it.

    claude --plugin-dir .                 # load for one session
    claude plugin validate . --strict     # manifest + components
    python3 -m unittest discover -s tests # tests (stdlib only)
    python3 scripts/dev/leak_guard.py     # no private names (see below)
    python3 scripts/dev/check_links.py .  # no links outside the plugin
    python3 scripts/dev/lint_frontmatter.py
    PYTHONPATH=lib python3 -m plainspoken check <file> --profile default   # lint one file

The leak guard fails on any name that must never appear in the repo. `data/leak-denylist.txt` holds only generic
patterns; the names themselves live in a private list kept outside the repo, in the file `PLAINSPOKEN_LEAK_LIST`
points at. CI on this repo reads that list from a repository secret, fails when the secret is missing, and logs a
hit as `private#<line>`, never the name. A fork, a pull request from a fork or a local run without the variable
skips the private list with one notice line and checks the rest.

A name can also be stored as a keyed hash (HMAC-SHA256), so it never sits anywhere in plaintext. That's optional.
The key comes from `PLAINSPOKEN_LEAK_KEY` or a git-ignored `.leak-guard-key`; without it, a run that meets keyed
entries ends on `SKIPPED (no key)`, never a clean result. The guard doesn't scan git-ignored files, and
`python3 -m scripts.dev.leak_guard --help` lists the options. To hash or convert a name, pass `-` for the term
(`--convert -`): it's read from stdin, without echo at a terminal, so the name stays out of shell history and `ps`.

Security problems: see [SECURITY.md](SECURITY.md). Licence: MIT ([LICENSE](LICENSE)); third-party notices are in
[NOTICE.md](NOTICE.md).

Acceptance runs and the report contract: see `docs/acceptance/` and `docs/report-contract.md`.
