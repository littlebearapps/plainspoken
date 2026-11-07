# Roadmap

This page shows where plainspoken is heading. It's not a commitment: priorities can change as the evals come in,
and nothing here has a date. For what has already shipped, see [CHANGELOG.md](CHANGELOG.md).

## Now: 0.14.0

0.13.0 was released in November 2026; [CHANGELOG.md](CHANGELOG.md) lists what it brought. Most of 0.14.0's smaller fixes
are on `main` and ship with it, with ruleset 4.5.0. Still to do:

- The cost of checking a long post: judges finding old tells late
  ([#200](https://github.com/littlebearapps/plainspoken/issues/200)), judge input pasted into every round
  ([#205](https://github.com/littlebearapps/plainspoken/issues/205)) and the four-judge round a kept WARN can cost
  ([#188](https://github.com/littlebearapps/plainspoken/issues/188)).
- Rule 7d's joins that still add a reason ([#73](https://github.com/littlebearapps/plainspoken/issues/73)), and
  showing an added "so" to the owner ([#215](https://github.com/littlebearapps/plainspoken/issues/215)).
- Smaller designs: calibrate's evidence ([#212](https://github.com/littlebearapps/plainspoken/issues/212)), a route
  for published pieces ([#204](https://github.com/littlebearapps/plainspoken/issues/204)), frontmatter and FAQs
  ([#208](https://github.com/littlebearapps/plainspoken/issues/208)), private text in voice profiles
  ([#210](https://github.com/littlebearapps/plainspoken/issues/210)), a claim kind that pins a promise to the brief
  ([#178](https://github.com/littlebearapps/plainspoken/issues/178)), and whether a brief's instructions reached the
  piece ([#216](https://github.com/littlebearapps/plainspoken/issues/216)).
- Fixes on `main` that a paid long-form round still has to confirm: report asks
  ([#75](https://github.com/littlebearapps/plainspoken/issues/75)), report wording
  ([#163](https://github.com/littlebearapps/plainspoken/issues/163)) and small eval fixes
  ([#191](https://github.com/littlebearapps/plainspoken/issues/191)).
- One wording for when a short piece gets the lint only
  ([#149](https://github.com/littlebearapps/plainspoken/issues/149)), and install steps still to confirm on live hosts
  ([#123](https://github.com/littlebearapps/plainspoken/issues/123)).

## Before v1.0

v1.0 waits on evidence that plainspoken does what it says on real, long pieces. What's left:

- **Open issue [#75](https://github.com/littlebearapps/plainspoken/issues/75).** In round 11, one long-form report in
  nine still asked the owner to check something the engine doesn't list. It's fixed when the count is zero.
- **More evidence on rewrite quality.** A blind reader test that puts plainspoken's drafts beside the author's own
  unassisted writing, read by a model panel, alongside the existing blind reads of rewrites.

## After v1.0 (being considered)

None of these is planned yet:

- An editor agent that can rewrite a passage, not only cut what's wrong with it.
- The human tier of the blind reader test, where people rather than models try to tell plainspoken's drafts from
  the author's own.
- A listing in the Hermes Agent plugin catalogue, which needs a `plugin.yaml` at the repository root.

## Have an idea?

[Open a feature request](https://github.com/littlebearapps/plainspoken/issues/new?template=feature_request.yml), or
use the kaizen forms if a check flags the wrong thing or misses a tell ([CONTRIBUTING.md](CONTRIBUTING.md) explains
which is which).
