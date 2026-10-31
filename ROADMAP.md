# Roadmap

This page shows where plainspoken is heading. It's not a commitment: priorities can change as the evals come in,
and nothing here has a date. For what has already shipped, see [CHANGELOG.md](CHANGELOG.md).

## Now: 0.13.0

0.12.0 was released on 30 October 2026; [CHANGELOG.md](CHANGELOG.md) lists what it brought. 0.13.0 is being worked
out from the round-8 evals and from feedback on a Hermes Agent install:

- `status` says what made a check stale, and shows whether the draft delivers its reader-value contract
  ([#151](https://github.com/littlebearapps/plainspoken/issues/151)).
- One copy-paste block to run the four judges on Hermes Agent
  ([#150](https://github.com/littlebearapps/plainspoken/issues/150)), and one wording for when a short piece gets
  the lint only ([#149](https://github.com/littlebearapps/plainspoken/issues/149)).
- The writing nudge no longer reads a quoted example inside a question as a request
  ([#146](https://github.com/littlebearapps/plainspoken/issues/146)).
- `meaning-diff` lists the numbers, limits and promises a fix dropped or changed, for the owner to check
  ([#147](https://github.com/littlebearapps/plainspoken/issues/147)).
- Rule 7d no longer asks a piece under 150 words for a long sentence, and doesn't count a greeting or sign-off as a
  sentence, so short emails and texts stop getting rhythm warnings
  ([#148](https://github.com/littlebearapps/plainspoken/issues/148); ruleset 4.4.0).
- `judge-input` lints the draft itself when its saved lint is out of date and prints the lint, so it can't be skipped
  before the judges run ([#162](https://github.com/littlebearapps/plainspoken/issues/162)).

These three are built and wait for the paid checks in the next eval round.

## Before v1.0

v1.0 waits on evidence that plainspoken does what it says on real, long pieces. What's left:

- **A long-form eval round on 0.12.0.** Long pieces drafted with and without the plugin, several runs each, read
  blind by model readers, to confirm the fixes since 0.11.0 hold up outside the unit tests. The same round re-runs
  the per-skill smoke tests and checks the new Codex and Hermes Agent hooks on real installs.
- **Open issue [#75](https://github.com/littlebearapps/plainspoken/issues/75).** In round 8, two long-form runs of
  nine had write's report ask the owner to check lines the engine didn't list as needing them. 0.12.0's report guard
  catches both of those kinds of ask; the next round counts again. It's fixed when the count is zero or those lines
  are recorded so the engine lists them.
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
