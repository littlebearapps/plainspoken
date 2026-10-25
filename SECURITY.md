# Security policy

plainspoken is made by Little Bear Apps. This page says which versions get fixes, how to report a problem
privately and what counts as one.

## Supported versions

| Version | Supported |
|---|---|
| Latest release | Yes |
| Older releases | No |

Only the latest release gets security fixes, so please update before you report. Your version is `version` in
the plugin's `.claude-plugin/plugin.json`.

## Reporting a vulnerability

Don't open a public issue, pull request or discussion for a security problem. Report it privately, by either:

- email to [security@littlebearapps.com](mailto:security@littlebearapps.com), or
- [GitHub Security Advisories](https://github.com/littlebearapps/plainspoken/security/advisories/new).

Include:

- what you found and what it lets someone do;
- the plainspoken version;
- the host you ran it in (Claude Code, Cowork, Codex or Hermes Agent) and that host's version;
- your Python version (`python3 --version`);
- the steps to reproduce it.

Redact anything private first. If the problem only shows up with a real draft, a voice profile or a kaizen ledger,
send a made-up example that reproduces it, or describe the shape of the text instead of pasting it.

## Response timeline

| Step | Target |
|---|---|
| Acknowledgement | Within 48 hours |
| Initial assessment | Within 5 business days |
| Fix for critical issues | Within 7 days |
| Public disclosure | After the fix is released |

## What runs where

plainspoken runs inside Claude Code, Cowork, Codex or Hermes Agent, on your own machine. Its engine is Python with
the standard library only, and the checks run offline: the lint, the hooks, the claims recheck and the kaizen ledger
make no network calls. Two things go online, and only when you start them:

- the kaizen adapters for GitHub and Trello, once you configure them: they open one issue or card per proposal and
  read the decisions posted on it;
- the paid evals, which call models only when you start a run by hand.

The judges and checkers are agents that your host runs, like any other agent it starts.

## Scope

In scope:

- the engine (`lib/plainspoken`) and its CLI, `lib/run.py`;
- the hooks, including the publish gate and the write guard;
- the instructions in the skills and agents, where they could lead the host to run, read or write something the
  docs say they don't;
- the leak guard;
- the kaizen adapters.

The reports that matter most:

- a hook or CLI command that runs code, reads or writes outside the project, or follows a symlink it shouldn't;
- a check, gate or claims result that reports PASS when it shouldn't;
- text from a draft, a source or a review reaching a place the docs say it never goes (the kaizen ledger with
  excerpts off, a public log, an issue or card).

Out of scope:

- The host apps themselves. Report a problem in Claude Code, Cowork, Codex or Hermes Agent to its maker.
- Getting around the publish gate on purpose. The gate is a guardrail against pushing unchecked writing by
  accident, not a security boundary ([docs/claude-code-facts.md](docs/claude-code-facts.md), section 6).
- An agent editing a file on Hermes Agent, or on Codex when it runs as a `spawn_agent` rather than a separate
  read-only `codex exec`. There the agents' read-only rule is an instruction the model follows, not a sandbox (see
  [hosts/codex.md](hosts/codex.md) and [hosts/hermes.md](hosts/hermes.md)).

## Disclosure

Please allow time for the problem to be investigated and fixed before you disclose it, and don't use it beyond
what you need to show it.
