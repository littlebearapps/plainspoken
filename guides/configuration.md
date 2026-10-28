# Configuring plainspoken

This guide is for anyone who wants to change what plainspoken does in a project. It lists every setting, where each
one lives, which one wins when two disagree, and the optional pieces you can switch on.

- [Where settings live](#where-settings-live)
- [Plugin options](#plugin-options)
- [The project config](#the-project-config)
- [The user-wide file](#the-user-wide-file)
- [How the profile is chosen](#how-the-profile-is-chosen)
- [Which English the skills write in](#which-english-the-skills-write-in)
- [Optional pieces](#optional-pieces)
- [The setup command](#the-setup-command)
- [Host setup](#host-setup)
- [Narrow what plainspoken does](#narrow-what-plainspoken-does)
- [Keep reports out of git](#keep-reports-out-of-git)

## Where settings live

Settings come from three places. When two set the same thing, the first one here wins:

1. **The project config**, `.plainspoken/config.toml` in the project. It wins everywhere: in the skills, the hooks
   and the command-line tool.
2. **The user-wide file**, `~/.config/plainspoken/config.toml`. It holds only `[nudge]`, `[rule]`,
   `[lint_watch]` and `[locale]`.
3. **The plugin options** you set when you install or enable the plugin in Claude Code. Codex and Hermes Agent have
   no plugin options, so there you use the two files.

The spelling locale has one more source, your voice profile, which sits between the two files: see
[Which English the skills write in](#which-english-the-skills-write-in).

The project is the nearest folder, from where you run a command upwards, that holds `.plainspoken/config.toml` or
`.git`. So you can run the CLI from anywhere inside it. Report files are keyed to that folder.

## Plugin options

Claude Code asks for these when you install or enable the plugin (`userConfig` in `.claude-plugin/plugin.json`).

| Option | What it sets | Default | Beaten by |
|---|---|---|---|
| `profile` | The voice profile: a name, or a path to a profile TOML. `default` uses the shipped default profile | `default` | `[engine] profile` |
| `locale` | The English variant the skills write in: `en-AU`, `en-GB` or `en-US`. The drafting skills and the register check read it; no lint rule or judge does | `en-AU` | `[locale] variant` in either file, or the voice profile's `locale` |
| `targets` | The globs the lint-watch hook checks after each Write or Edit | `**/*.md` | `[lint_watch] paths` |
| `nudge` | On: when a prompt asks for an email, post, script or other writing, a one-line reminder names the plainspoken step that fits | off | `[nudge] mode` |
| `rule` | On: every session starts with a short rule to use plainspoken whenever it drafts or rewrites something people will read | off | `[rule] enabled` |
| `strictness` | What the publish gate does on `git push`: `watch` reports only, `warn` warns, `block` refuses a push unless every gated file has a current PASS | `watch` | `[gate] strictness` |
| `ledger_excerpts` | Whether the kaizen ledger stores excerpts of your text. Off keeps raw text out of it (hashes only) | off | `[kaizen] excerpts` |
| `kaizen_adapter` | Where kaizen proposals go: `file` (Markdown in `.plainspoken/`), `github` (issues) or `trello` (cards). The project config supplies the IDs | `file` | `[kaizen] adapter` |

An outward `kaizen_adapter` (`github` or `trello`) with no `[kaizen] approvers` in the project config falls back to
`file`.

An installed copy's hooks see these options. A session that loads the plugin with `--plugin-dir` gives the hooks
none ([docs/claude-code-facts.md](../docs/claude-code-facts.md) section 11). If you use the publish gate with a
profile other than `default`, set `[engine] profile` in the project config as well.

## The project config

Everything below goes in `.plainspoken/config.toml`. Every key is optional.

### `[engine]`: the voice profile

    [engine]
    profile = "default"                                  # a profile name, or a path to a profile TOML; files no entry below matches
    profiles = [                                         # first match wins
      { glob = "docs/**", profile = "technical" },       # a profile name, or a path relative to .plainspoken/
      { glob = "posts/**", profile = "profiles/essay.toml" },
    ]

Each `profiles` glob is matched against the file's path from the project root. To make a profile, copy
`templates/voice-profile.toml` to `.plainspoken/profiles/<name>.toml` and edit it, or run `/plainspoken:voice build`
on five to ten of your own writing samples. How to lay it out: [guides/voice-profiles.md](voice-profiles.md).

### `[gate]`: the publish gate

The publish gate runs on `git push` and looks at the files you list. It's a guardrail against pushing unchecked
writing by accident, not a security boundary (its limits: [docs/claude-code-facts.md](../docs/claude-code-facts.md)
section 6).

    [gate]
    paths = ["content/**/*.md"]  # the files the gate checks
    strictness = "block"         # watch | warn | block; beats the plugin option

`warn` and `block` need `paths`. With none set, the gate only warns on each push that nothing is gated. If the
config can't be read, the gate warns and lets the push go, unless a readable `[gate] strictness` or the plugin
option says `block`. In Codex and Hermes, `[gate] strictness` is the only source of strictness.

### `[lint_watch]`: lint after each edit

    [lint_watch]
    mode = "on"                    # "off": the hook lints, says and records nothing
    paths = ["posts/**/*.md"]      # the files it lints; beats the plugin's targets option; unset means **/*.md

An empty `paths` list lints nothing.

### `[kaizen]`: capture sources

    [kaizen]
    capture_sources = ["check", "merge", "judge"]   # drop lint-watch events; default all four

The four sources are `check`, `merge`, `judge` and `lint-watch`. `capture = false` turns them all off. The rest of
`[kaizen]` (excerpts, adapter, approvers, folders, GitHub and Trello IDs) is in [guides/kaizen.md](kaizen.md).

### `[brief]`, `[nudge]` and `[rule]`: the optional pieces

    [brief]
    enabled = true    # the session brief (Claude Code and Cowork)

    [nudge]
    mode = "on"       # on | off

    [rule]
    enabled = true    # the drafting rule (Claude Code and Cowork)

What each does: [Optional pieces](#optional-pieces). `/plainspoken:setup` writes `[nudge]`, `[rule]` and
`[lint_watch]` for you.

### `[locale]`: which English the skills write in

    [locale]
    variant = "en-US"   # en-AU, en-GB or en-US

The same section works in the user-wide file. Who wins:
[Which English the skills write in](#which-english-the-skills-write-in).

### `[claims]`, `[reader_value]` and `[integrity]`

    [claims]
    ledger_dir = ".plainspoken/claims"     # relative to the project root
    sources_dir = ".plainspoken/sources"   # where saved source text lives
    regulated_matrix = "docs/regulated-claims.md"  # your own regulated-claims list; unset means none
    platforms_extra = ["Acme Portal"]      # platform names to treat as claims, on top of the shipped list

    [reader_value]
    cta_phrases = ["book a site visit"]    # your own calls to action, which never count as reader value

    [integrity]
    mode = "warn"                          # off | warn (the default) | block
    paths = ["content/**/*.md"]            # files the hook checks; unset means the targets option, else **/*.md

What these do: [guides/claims-and-reader-value.md](claims-and-reader-value.md).

## The user-wide file

`~/.config/plainspoken/config.toml` holds only `[nudge]`, `[rule]`, `[lint_watch]` and `[locale]`, the settings that
make sense outside a project. A project's own config wins over it, and it wins over the Claude Code options `nudge`,
`rule` and `locale`.
It can't choose a voice profile. Codex and Hermes, which have no plugin options, use it for these switches; Hermes
reads it because it runs plugins outside the project folder.

## How the profile is chosen

plainspoken never falls back to a profile silently. It takes the first of these that is set:

1. the `--profile` flag on a command;
2. the `PLAINSPOKEN_PROFILE` environment variable (a name or a full path), which beats every project's config;
3. the project config: the first `[engine] profiles` entry whose glob matches the file, then `[engine] profile`;
4. the `profile` plugin option.

With none of them, a command stops and tells you how to set one. To see the profile a file gets:

    python3 <plugin>/lib/run.py config profile-for <file>

`check`, `merge`, `judge-input`, `justify`, the lint-watch hook and the publish gate all use the file's own profile,
and the skills pass it to the calls that don't take a file.

## Which English the skills write in

The drafting skills (write, adapt, humanize, voice) and the register check's spelling item follow one English
variant: `en-AU`, `en-GB` or `en-US`. The lint and the judges don't read it, so changing it never changes a check
result or makes a saved report out of date. The first of these that is set wins:

1. `[locale] variant` in the project config: the audience of this body of writing, such as a US client's site
   written in your own voice;
2. `locale` under `[profile]` in the voice profile, when the profile sets one: the writer's own habit;
3. `[locale] variant` in the user-wide file;
4. the `locale` plugin option (Claude Code and Cowork);
5. `en-AU`.

The shipped default profile sets no locale, so the plugin option or a file decides it. A profile you copied from an
older default profile may still say `locale = "en-AU"`: delete that line if you'd rather follow the plugin option.
`python3 <plugin>/lib/run.py profile` prints the result and where it came from, as in `locale en-US (plugin option)`.
`doctor` shows it too, and when your system locale (`LANG`) names a different variant it says how to switch. It
never switches for you.

## Optional pieces

All of these are off by default and add 0 tokens until you switch them on, apart from lint after edits, which is on.

| Piece | What it does | Where it runs |
|---|---|---|
| Writing nudge (`[nudge] mode = "on"`) | When a prompt asks for an email, a text, a post, a script, a page or a rewrite that sounds like a person, one line names the plainspoken step that fits: lint a short piece on stdin (`check -`), use write (draft, full check, fix) for a long one, use humanize for a rewrite. Chat, code and slash commands don't trigger it | Claude Code and Cowork (`UserPromptSubmit`), Codex CLI, app and ChatGPT Work (`UserPromptSubmit`), Hermes (`pre_llm_call`) |
| Drafting rule (`[rule] enabled = true`) | Every session starts with a short rule: whenever something people will read is drafted, use plainspoken. The plugin adds it with this install's paths, so it never goes stale after an update, and it only applies where plainspoken is installed | Claude Code and Cowork |
| Lint after edits (`[lint_watch] mode`, on by default) | After a draft file is saved, the lint's findings come straight back | Claude Code, Cowork, Codex, Hermes |
| Paste-in text (`setup --host claude-ai` or `chatgpt`) | The same rule as text to paste into the app's personal preferences, custom instructions or a project's instructions | claude.ai chat, ChatGPT chat (neither runs hooks) |
| Session brief (`[brief] enabled = true`) | A short writing brief (at most 800 characters) at session start and in each subagent, never in plainspoken's own agents | Claude Code and Cowork |
| Output style (`/output-style plainspoken`) | The same guidance as an output style, for the main conversation only | Claude Code |

The session brief and the output style aren't on by default yet. The Phase 6 ablation (21 drafts, 2026-10-16) gave
no lint evidence for either, and with 3 drafts per variant that's only a hint. The blind reader test decides
([guides/evals.md](evals.md)).

## The setup command

`/plainspoken:setup` turns the nudge, the drafting rule and lint after edits on or off for the app you're in, and
shows what's on. Underneath it runs:

    python3 <plugin>/lib/run.py setup --host <host> [--scope project|user] [--nudge on|off] [--rule on|off]
        [--lint-watch on|off] [--locale en-AU|en-GB|en-US] [--dry-run | --remove | --status]

| Flag | What it does |
|---|---|
| `--host` | The app: `claude-code`, `codex` (also ChatGPT Work), `hermes`, `claude-ai` or `chatgpt`. The last two print the paste-in text and write nothing |
| `--scope` | `project` writes `.plainspoken/config.toml` here; `user` writes `~/.config/plainspoken/config.toml`. Use `user` for Hermes, because it runs plugins outside the project folder |
| `--nudge`, `--rule`, `--lint-watch` | `on` or `off`; one you leave out stays as it is. `--rule` is for Claude Code |
| `--locale` | Writes `[locale] variant`. For `claude-ai` and `chatgpt` it adds one line to the paste-in text instead, such as "Spell in American English (en-US)." |
| `--dry-run` | Print the change without writing it |
| `--remove` | Delete every line setup wrote to the file, and nothing else |
| `--status` | Print what's on now |

Setup edits one config file and marks every line it writes. It never edits `CLAUDE.md`, `AGENTS.md` or any other
instructions file, and it doesn't choose a voice profile.

## Host setup

`setup` ends with host checks for the app it's run for. When one finds a problem it prints it with its fix: a
`python3` older than 3.11, a reports folder its file permissions don't let it write, no `git` while the publish gate
is on, a config that doesn't parse, or no `hermes` on PATH. It does the same when a check can't run. A last line says
how many things `doctor` lists for you to confirm by hand. On a healthy machine it prints nothing more. The checks
never block setup or change what it writes.

`/plainspoken:doctor` (`python3 <plugin>/lib/run.py doctor --host <host>`) runs the same checks on their own and marks
each one `ok`, `WARN` or `not checked`. What a script can't see, such as the agent's own tools, Codex's hook trust or
the `hermes chat` flags, stays `not checked`, and the skill asks the agent to say whether it has them. The one
command it runs is `python3 --version`. `git`, `codex` and `hermes` are only looked up on PATH, because starting
`codex` or `hermes` writes files of their own. It exits 0 with warnings, and `--json` prints the checks as a list.

`--host claude-ai` or `chatgpt` says there's no shell in those apps, so the lint, the judges and the hooks don't run
there. Setup prints those lines on stderr, away from the text to paste. An older `python3` gets one line from every
command instead, `plainspoken needs Python 3.11 or newer; this python3 is …`, and exit 2.

## Narrow what plainspoken does

A project that already has its own checks can narrow what plainspoken does:

- **One voice per folder.** Give folders their own profile with `[engine] profiles` ([above](#engine-the-voice-profile)).
  `--profile` and `PLAINSPOKEN_PROFILE` still come first.
- **Lint fewer files, or none.** Set `[lint_watch] paths` to the files you want linted after each edit, or
  `mode = "off"`.
- **Record less.** Drop sources from `[kaizen] capture_sources`, for example `lint-watch`.
- **Skills only when asked.** To stop Claude starting a skill by itself while keeping its slash command, deny the
  Skill tool for it in the project's `.claude/settings.json`:

      {
        "permissions": {
          "deny": ["Skill(plainspoken:write)", "Skill(plainspoken:check)",
                   "Skill(plainspoken:humanize)", "Skill(plainspoken:plain-language)"]
        }
      }

  `/plainspoken:write …` still runs (probed with Claude Code 2.1.303:
  [docs/claude-code-facts.md](../docs/claude-code-facts.md) section 11). Asking for a denied skill in plain words no
  longer works, so type its slash command. When a skill hands over to a denied one (write to check, check to
  humanize), it reads that skill's file and follows its steps instead.

## Keep reports out of git

Add `.plainspoken/` to your `.gitignore` so reports and hook state stay out of commits. To keep the project settings
tracked, use:

    .plainspoken/*
    !.plainspoken/config.toml
    !.plainspoken/profiles/

A profile's anchors are verbatim text from your writing samples, so keep anything from a client's material out of a
profile you commit. Every report file, and what each one is bound to, is listed in
[docs/report-contract.md](../docs/report-contract.md).
