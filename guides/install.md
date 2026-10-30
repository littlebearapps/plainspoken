# Installing plainspoken

This guide is for anyone setting plainspoken up. It covers what you need, how to install it in each app, how
updates and pinning work, how to check it worked and how to remove it again.

- [What you need](#what-you-need)
- [Claude Code and Cowork](#claude-code-and-cowork)
- [Codex](#codex)
- [Hermes Agent](#hermes-agent)
- [claude.ai and ChatGPT chat](#claudeai-and-chatgpt-chat)
- [Hooks outside Claude Code](#hooks-outside-claude-code)
- [Check it worked](#check-it-worked)
- [Uninstall](#uninstall)

## What you need

Python 3.11 or newer, available as `python3`. plainspoken uses the standard library only, so there's nothing else to
install. With an older `python3`, the lint-watch hook skips with one line, and the command-line tool the skills call
prints one line saying so and exits 2:

    plainspoken needs Python 3.11 or newer; this python3 is …

A hook is a script the app runs by itself at a set moment, such as straight after a file is saved. Lint-watch is the
hook that runs plainspoken's fixed pattern checks (the lint) on each draft you edit.

## Claude Code and Cowork

Install it from the Little Bear Apps marketplace:

    /plugin marketplace add littlebearapps/lba-plugins
    /plugin install plainspoken@lba-plugins

In Cowork, add the same marketplace and install the same plugin. The writing nudge, the drafting rule, the session
brief and lint after edits all run there too (see [the optional pieces](configuration.md#optional-pieces)).

### Updates and pinning

The marketplace entry pins a release: it names one fixed version, so a new version reaches you when that entry moves
to the next release. [CHANGELOG.md](../CHANGELOG.md) lists every release.

Claude Code keeps background auto-update off for third-party marketplaces until you turn it on. Either:

- in `/plugin`, open **Marketplaces**, select `lba-plugins` and choose **Enable auto-update**; or
- set `"autoUpdate": true` on the marketplace's `extraKnownMarketplaces` entry in a project's
  `.claude/settings.json`.

### Project or user scope

Install it into the project that uses it, unless you want it everywhere:

    claude plugin install plainspoken@lba-plugins --scope project

At user scope, the lint-watch hook lints every Markdown edit in every project you open, and records a kaizen event
(the record of what the checks flagged) for each one.

## Codex

The Codex CLI and the ChatGPT desktop app read the same marketplace:

    codex plugin marketplace add littlebearapps/lba-plugins
    codex plugin add plainspoken@lba-plugins

Then start a new session and call the skills with `$` instead of `/`: `$plainspoken:check`, `$plainspoken:humanize`
and the rest. ChatGPT Work runs the plugin the way Codex does, so pass `--host codex` to setup and doctor there.

Codex runs a plugin's hooks only after you trust them: open `/hooks` in Codex and trust plainspoken's. Until you do,
no lint, nudge or gate runs. Since Codex 0.164.0 the trust covers every file in the plugin, so you trust them again
after each plainspoken update.

The skills are written for Claude Code, so Codex gets a short note on how to run them there, which each skill points
to: [hosts/codex.md](../hosts/codex.md). The judges and checkers (the separate model runs that review a draft) start
with a fresh context, from a prompt built by `run.py agent-prompt`.

## Hermes Agent

    hermes plugins install littlebearapps/plainspoken --enable

Hermes scans a plugin before it installs it. Hermes v0.22 rates plainspoken "safe": it lists medium and low findings
(the engine runs Python, and the docs show commands) but no high ones, so the install doesn't stop to ask. If your
Hermes rates it "caution", it asks you to confirm. Over SSH or in a script, where it can't ask, review the findings
and add `--force`.

Then start a new session (or `/reset`). Hermes loads `.hermes-plugin/`, which registers the skills as
`plainspoken:<name>` and tells the model where the plugin lives. The install also warns that the repo root has no
`plugin.yaml`. That's expected: the Hermes manifest sits in `.hermes-plugin/`.

To add it to one Hermes profile only, name the profile first:

    hermes -p <profile> plugins install littlebearapps/plainspoken --enable

How the skills run in Hermes, and how it starts the judges: [hosts/hermes.md](../hosts/hermes.md).

### Updates and pinning

This install follows the `stable` branch, which only moves when a release ships.

- Hermes checks for a new commit once a day (`plugins.auto_update_check_hours`).
- `hermes plugins check-updates` checks now, and Hermes Desktop shows an **Update** button.
- `hermes plugins update plainspoken` applies the update. Hermes scans it again: a "safe" rating applies without
  asking, so `plugins.auto_apply: true` can apply it unattended. A "caution" rating asks "Update anyway?" and needs
  `--force` where it can't ask.

To stay on one release instead, pin its full commit with `--ref <sha>`. Hermes takes no tags or branches there.
`update` then leaves it alone, and `install --force --ref <new-sha>` moves it to another release.

## claude.ai and ChatGPT chat

These apps have no shell, so the lint, the judges and the hooks don't run there. What you can use is a short drafting
rule pasted into the app's settings. Print it from any copy of the plugin:

    python3 <plugin>/lib/run.py setup --host claude-ai
    python3 <plugin>/lib/run.py setup --host chatgpt

Each prints where to paste the text (claude.ai: your personal preferences or a Project's instructions; ChatGPT:
custom instructions or a Project's instructions), then the text. Its host-check lines go to stderr, so they stay out
of what you copy. The pasted rule is guidance the model follows, not a check: a "check" in chat is the model's own
read.

## Hooks outside Claude Code

In Codex and Hermes, lint and the claims integrity check run after each edit, and so does the optional writing
nudge. Codex runs them only after you trust them in `/hooks`, and again after each plainspoken update.

Since 0.12.0, both also run the publish gate (taking its strictness from `[gate] strictness` only), the shell write
guard and the kaizen nudge. An older installed copy has none of those three, so run the check yourself before
anything goes out. In Hermes the gate covers the `terminal` tool: a deny blocks the command, a warn is posted to you
and the command runs, and the kaizen nudge is posted to you at the end of a turn.

Neither host has the kaizen backstop, the hook that counts agent runs, because their hooks never see a plainspoken
agent finish. Neither has install-time settings: pick a profile with `[engine] profile` in
`.plainspoken/config.toml`, and turn the optional pieces on with `/plainspoken:setup`
([configuration.md](configuration.md)). In Hermes, the agents' read-only sandbox is an instruction they follow, not a
sandbox the app enforces.

## Check it worked

Run `/plainspoken:doctor` (`$plainspoken:doctor` in Codex), or the command underneath it:

    python3 <plugin>/lib/run.py doctor --host claude-code     # or codex, hermes, claude-ai, chatgpt

It checks `python3`, the plugin's files, the config and the commands the judges use, and marks each line `ok`,
`WARN` or `not checked`. It changes nothing and exits 0 even with warnings. What a script can't see, such as the
agent's own tools or Codex's hook trust, stays `not checked`, and the skill asks the agent to say whether it has
them. More detail: [Host setup](configuration.md#host-setup).

## Uninstall

First remove the lines setup wrote, while the plugin is still there to run it. Use the host and scope you set it up
with (for example `claude-code` and `project`):

    python3 <plugin>/lib/run.py setup --host <host> --scope <scope> --remove

It deletes only the lines setup wrote; anything you added to the config file by hand stays. For claude.ai or
ChatGPT chat, delete the text you pasted.

Then remove the plugin with the app's own command:

- **Claude Code:** `claude plugin uninstall plainspoken@lba-plugins`, adding `--scope project` (or `local`) if you
  installed it there; the default is `user`. It also deletes the plugin's data folder, which holds the edit hooks'
  state, unless you add `--keep-data`. To drop the marketplace as well: `claude plugin marketplace remove
  lba-plugins`.
- **Cowork:** remove it the way you added it.
- **Codex:** `codex plugin remove plainspoken@lba-plugins`, which uninstalls it and removes its local cache. To drop
  the marketplace as well: `codex plugin marketplace remove lba-plugins`.
- **Hermes Agent:** remove it with Hermes' own plugin command (`hermes plugins --help` lists it).

Your reports, ledger, claim ledgers and profiles stay in each project's `.plainspoken/` folder. Delete that folder
if you want them gone, after copying out any profile or config you want to keep. Every file plainspoken writes there
is listed in [docs/report-contract.md](../docs/report-contract.md).
