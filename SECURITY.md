# Security

## Reporting a vulnerability

Please report a security problem privately by email to hello@littlebearapps.com. Don't open a public issue,
pull request or discussion for it.

Include what you found, the version (`version` in `.claude-plugin/plugin.json`), how to reproduce it and what it
lets someone do. You'll get a reply to say it arrived, and another once it's fixed or ruled out.

## Scope

plainspoken runs inside Claude Code on your own machine. It makes no network calls of its own, except the optional
kaizen adapters (`github`, `trello`), which run only when you configure them, and the eval runners, which call
models only when you start a run by hand. Reports that matter most:

- a hook or CLI command that runs code, reads or writes outside the project, or follows a symlink it shouldn't;
- a check, gate or claims result that reports PASS when it shouldn't;
- text from a draft, a source or a review reaching a place the docs say it never goes (the kaizen ledger with
  excerpts off, a public log, an issue or card).

The publish gate is a guardrail against pushing unchecked writing by accident, not a security boundary
(`docs/claude-code-facts.md` section 6), so a way around it on purpose isn't a vulnerability.

## Supported versions

Only the latest release gets fixes.
