# Troubleshooting

Each entry starts from what you see, says what usually causes it, and ends with the fix. Before anything else, run
`/plainspoken:doctor` (or `python3 <plugin>/lib/run.py doctor --host <host>`), which checks `python3`, the plugin
files, the reports folder, the config and the commands the judges use, then lists each problem with its fix. It
changes nothing.

## "plainspoken needs Python 3.11 or newer; this python3 is …"

The `python3` on your PATH is older than 3.11, so every command prints this one line and exits with code 2, and the
lint after each edit prints a single "plainspoken lint skipped" line instead of crashing.

Install Python 3.11 or newer and make it the `python3` your app runs. plainspoken needs nothing beyond the
standard library.

## The lint after each edit says nothing

A clean result is silent, and only a change in a file's result is reported, so a second edit with the same findings
says nothing new. If even a fresh tell gets no reply, look for one of these:
- `[lint_watch] mode = "off"` in `.plainspoken/config.toml`, which turns it off completely.
- A file it doesn't watch. `[lint_watch] paths` sets the files and beats the plugin's `targets` option; with
  neither set, it watches `**/*.md`.

Check `[lint_watch]` in `.plainspoken/config.toml`, or run `/plainspoken:setup` to see what's on and turn lint after
edits back on.

## The check ends with INCOMPLETE

An input is missing or stale. Usually the draft, its profile or the ruleset changed after the judges read it, and
their saved verdicts no longer match the file, so the merge refuses to give a result from them.

Run the check again. If it's still INCOMPLETE after one rerun, the report quotes merge's problem lines, and those
name the judge or file to look at.

## The publish gate warns that "nothing is gated"

The gate's strictness is set to warn or block, but the project config has no list of files for it to cover, so on
each push it only tells you that it has nothing to check. Add that list to `.plainspoken/config.toml`:

    [gate]
    paths = ["content/**/*.md"]

The gate is a guardrail against pushing unchecked writing by accident, not a security boundary.

## Codex hooks don't run

Codex runs a plugin's hooks only after you trust them, and until you do, nothing lints your edits or checks a push.
Open `/hooks` in Codex, review plainspoken's hooks and trust them.

If they ran before and stopped after an update, that's expected. Since Codex 0.164.0, the trust is tied to a hash of
every file in the plugin, so each plainspoken update, even one that doesn't touch the hooks, puts them back to
"needs review" (Codex reports "plugin contents changed; hook approval required"). Trust them again in `/hooks`. Even with them trusted, run the check skill yourself before
anything goes out, because Codex calls its tool hooks a guardrail rather than a complete boundary.

## The tool-call check never says anything

It's off until you turn it on: `setup --host <host> --tool-call warn` (with `--scope user` for Hermes), or
`[tool_call] mode` in a config file. `doctor` shows the mode and where it came from. Once on, it stays quiet for a
clean text, a tool on the shipped skip list (search, memory, code hosts, task trackers, browser and data tools, and
lookups such as `get_…` and `list_…`), an argument under 25 prose words, and anything it doesn't read as prose. Add
a tool back with `[tool_call] include`. A config it can't read turns it off; `doctor` names the problem. In Codex,
check that its hooks are trusted in `/hooks`.

## Hermes asks me to confirm the install, or wants `--force`

Hermes scans a plugin before it installs or updates it, and a "caution" rating asks you to confirm, but over SSH or
in a script, where it can't ask, it stops instead.

Review the findings it lists, then confirm, or add `--force` where it can't ask. The warning that the repo root has
no `plugin.yaml` is expected, because the Hermes manifest sits in `.hermes-plugin/`.

## Hermes doesn't pick up a new release

Hermes checks for a new release once a day, but it doesn't apply one unless you've turned on its automatic apply
setting, so a release can wait there until you update it by hand. Check now with `hermes plugins check-updates`,
apply it with `hermes plugins update plainspoken`, then start a new session. A commit you pinned with `--ref` stays
where it is when you update, and [install](install.md) explains how to move it.

## A skill doesn't start on its own

Only four skills start on their own (check, humanize, write and plain-language), so the one you expected may be
one of the nine that run only when you call them, or a rule in your project's settings may deny it. Look for a
`Skill(plainspoken:<name>)` deny rule in `.claude/settings.json`.

Type its slash command, for example `/plainspoken:check post.md`, which works even for a denied skill. To let a
denied skill start on its own again, remove its deny rule.

## Reports can't be saved

The project folder, or the reports folder inside it, isn't writable, and `doctor` shows this as a warning on its
reports folder line, with the folder it couldn't write. Make that folder writable, or run from a project folder you
can write to.

## "no profile" or "profile … not found"

plainspoken never falls back to a default profile without saying so. It looks, in order, at the `--profile` flag,
the `PLAINSPOKEN_PROFILE` variable, `.plainspoken/config.toml` (a matching `[engine] profiles` entry, then
`[engine] profile`) and the plugin's profile option. A name it can't find in your project's profiles folder or among
the profiles that ship with the plugin is an error, and the message lists the folders it searched.

Check the name's spelling against `.plainspoken/profiles/<name>.toml`, or set `[engine] profile = "default"` to use
the shipped profile. `python3 <plugin>/lib/run.py config profile-for <file>` prints the profile one file gets.

## Claims never reach PASS

Only `claims status` says PASS, and only after the isolated `claims-checker` agent has reviewed the current article
and ledger. Editing either one makes the status INCOMPLETE until the checker has reviewed it again, and a claim with no pinned
passage in a saved source keeps it INCOMPLETE too.

Save each source's text under `.plainspoken/sources/`, pin the passages, then run `/plainspoken:claims` again so the
checker reviews the current files. More in [claims and reader value](claims-and-reader-value.md).

## The integrity check flags my own data

The integrity hook flags a prominent number with no linked source, such as a statistic in a chart, the TL;DR block
or the frontmatter description. When the number is your own data, mark it with an `<!-- integrity:allow -->`
comment inside or beside the chart, or just above the TL;DR, or with `# integrity: allow` in the frontmatter. Record
it as a `first_hand` claim in the ledger too.

## Still stuck?

Run `/plainspoken:doctor` and copy what it prints. Then
[open an issue](https://github.com/littlebearapps/plainspoken/issues/new/choose) with that output, your host and the
plainspoken version, or see [SUPPORT.md](../SUPPORT.md) for other ways to get help.
