# plainspoken docs

Every guide for plainspoken, grouped by what you're trying to do. If you're new here, start with the
[main README](../README.md) for what the plugin does, then follow [install](install.md) for the app you use.

## Get started

- [Install and update](install.md): every host, updates, pinning a release, the Hermes install scan and uninstalling.
- [Configuration](configuration.md): the project config, plugin options, optional pieces and host checks.

## Using it

- [Checking a draft](checking.md): `check`, `humanize` and `plain-language`, what each status means and the
  report-only route.
- [Claims and reader value](claims-and-reader-value.md): the claim ledger, saved sources, the integrity hook and the
  reader-value contract.
- [Voice profiles](voice-profiles.md): describe how you write, build a profile from your samples and switch it on.
- [Kaizen](kaizen.md): how the checks learn from your verdicts, and how a proposed change gets approved and applied.

## Hosts

- [Codex](../hosts/codex.md): how the skills, agents and hooks run in Codex.
- [Hermes Agent](../hosts/hermes.md): how the skills, agents and hooks run in Hermes Agent.

## Reference

- [Report contract](../docs/report-contract.md): every file plainspoken writes and what it's bound to.
- [Claude Code facts](../docs/claude-code-facts.md): host behaviour the plugin relies on, each probed and dated.
- [Evals](evals.md): what each eval measures, what it costs and how to run it.
- [Evidence method](evidence-method.md): how evidence is captured, quoted and retired.
- [Australian English](locale-en-AU.md): the en-AU wording and spelling guide.
- [Acceptance runs](../docs/acceptance/): the recorded acceptance and eval results.

## Help

- [FAQ](faq.md): short answers to the questions new users ask first.
- [Troubleshooting](troubleshooting.md): a symptom, its cause and the fix.
- [Changelog](../CHANGELOG.md): what changed in each release.
- [Roadmap](../ROADMAP.md): what's planned next.
- [Support](../SUPPORT.md): where to ask for help.
- [Contributing](../CONTRIBUTING.md) and [security](../SECURITY.md).

## Where things live

Everything plainspoken writes goes under `.plainspoken/` in the project root, which is the nearest folder, going
up from where you are, that holds a plainspoken config or a git repository.
`python3 <plugin>/lib/run.py paths <draft>` prints the exact paths for one draft.

| What | Where |
|---|---|
| Project settings | `.plainspoken/config.toml` |
| User-wide settings (nudge, rule, lint after edits only) | `~/.config/plainspoken/config.toml` |
| Your voice profiles | `.plainspoken/profiles/<name>.toml` |
| Check reports | `.plainspoken/reports/` |
| Kaizen ledger | `.plainspoken/ledger/` |
| Kaizen proposals (file adapter) | `.plainspoken/kaizen/proposals/` |
| Claim ledgers | `.plainspoken/claims/` |
| Saved source text for claims | `.plainspoken/sources/` |
| Reader-value contracts | `.plainspoken/reader-value/` |

Add `.plainspoken/` to your `.gitignore` so reports and hook state stay out of commits. To keep the settings and
profiles tracked, use:

    .plainspoken/*
    !.plainspoken/config.toml
    !.plainspoken/profiles/
