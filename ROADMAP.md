# Roadmap

This page shows where plainspoken is heading. It's not a commitment: priorities can change as the evals come in,
and nothing here has a date. For what has already shipped, see [CHANGELOG.md](CHANGELOG.md).

## Now: 0.12.0

0.12.0 brings the remaining hooks to Codex and Hermes Agent and makes reports harder to misread:

- The publish gate, the write guard and the kaizen nudge now run in Codex and Hermes Agent, not only in Claude Code
  and Cowork.
- `/plainspoken:doctor` checks an install and changes nothing, and `/plainspoken:setup` warns about host problems
  it finds.
- A lint report says which fields of a post it read, gives its BLOCK and WARN counts, and says "lint only" when the
  judges haven't run. It never says CLEAN above a WARN.
- On Hermes Agent, block-mode integrity findings reach the model, and a hook that couldn't run says so instead of
  looking clean.
- The claims step treats any result for a client as sensitive, named or not, and humanize reads your voice profile
  when you use it on its own.
- The publish gate says nothing is gated when it's set to warn or block but has no paths to gate.
- The docs gain one voice profile for every kind of writing, a report-only route for checking a draft without
  changing it, and the Hermes Agent launch flags.
- For maintainers: a drift check for judge and trigger evals, and a CI job that shows how a change moves the lint's
  verdicts on a fixed public set of texts.

## Before v1.0

v1.0 waits on evidence that plainspoken does what it says on real, long pieces. What's left:

- **A long-form eval round on 0.12.0.** Long pieces drafted with and without the plugin, several runs each, read
  blind by model readers, to confirm the fixes since 0.11.0 hold up outside the unit tests. The same round re-runs
  the per-skill smoke tests and checks the new Codex and Hermes Agent hooks on real installs.
- **Open issue [#75](https://github.com/littlebearapps/plainspoken/issues/75).** In one long-form run of nine,
  write's report asked the owner to check lines the engine didn't list as needing them. The round above counts how
  often it happens; it's fixed when the count is zero or those lines are recorded so the engine lists them.
- **Open issue [#104](https://github.com/littlebearapps/plainspoken/issues/104).** A voice profile that allows no
  em dashes still lets one through in a short post, because the social cap replaces the profile's stricter one, and
  en dashes aren't counted at all.
- **More evidence on rewrite quality.** A blind reader test that puts plainspoken's drafts beside the author's own
  unassisted writing, read by a model panel, alongside the existing blind reads of rewrites.

## After v1.0 (being considered)

None of these is planned yet:

- An editor agent that can rewrite a passage, not only cut what's wrong with it.
- The human tier of the blind reader test, where people rather than models try to tell plainspoken's drafts from
  the author's own.
- A listing in the Hermes Agent plugin catalog, which needs a `plugin.yaml` at the repository root.

## Have an idea?

[Open a feature request](https://github.com/littlebearapps/plainspoken/issues/new?template=feature_request.yml), or
use the kaizen forms if a check flags the wrong thing or misses a tell ([CONTRIBUTING.md](CONTRIBUTING.md) explains
which is which).
