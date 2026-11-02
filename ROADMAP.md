# Roadmap

This page shows where plainspoken is heading. It's not a commitment: priorities can change as the evals come in,
and nothing here has a date. For what has already shipped, see [CHANGELOG.md](CHANGELOG.md).

## Now: 0.14.0

0.13.0 was released in November 2026; [CHANGELOG.md](CHANGELOG.md) lists what it brought. 0.14.0 picks up what it left
open:

- Rerun the blind readers, which fell in round 8 and haven't been checked since
  ([#195](https://github.com/littlebearapps/plainspoken/issues/195)).
- Fixes for rule 7d that still add a reason or lengthen a sentence
  ([#73](https://github.com/littlebearapps/plainspoken/issues/73)), and a claim kind that pins a promise or exclusion
  to the brief ([#178](https://github.com/littlebearapps/plainspoken/issues/178)).
- Write reports: asks the engine doesn't list ([#75](https://github.com/littlebearapps/plainspoken/issues/75)), and
  engine lines restated in the report's own words
  ([#163](https://github.com/littlebearapps/plainspoken/issues/163)).
- The check's cost and order: the lint step ([#162](https://github.com/littlebearapps/plainspoken/issues/162)), the
  rubric's 7d clause ([#187](https://github.com/littlebearapps/plainspoken/issues/187)) and the four-judge round a
  kept WARN can cost ([#188](https://github.com/littlebearapps/plainspoken/issues/188)).
- `status` says what made a check stale, and shows the delivery result
  ([#151](https://github.com/littlebearapps/plainspoken/issues/151)).
- One copy-paste block to run the four judges on Hermes Agent
  ([#150](https://github.com/littlebearapps/plainspoken/issues/150)), and one wording for when a short piece gets
  the lint only ([#149](https://github.com/littlebearapps/plainspoken/issues/149)).
- Short emails linted as social posts by the hook route
  ([#190](https://github.com/littlebearapps/plainspoken/issues/190)), small eval fixes
  ([#191](https://github.com/littlebearapps/plainspoken/issues/191)), and install steps still to confirm on live hosts
  ([#123](https://github.com/littlebearapps/plainspoken/issues/123)).

## Before v1.0

v1.0 waits on evidence that plainspoken does what it says on real, long pieces. What's left:

- **A current blind reader number.** Rounds 9 and 10 checked the fixes in long-form runs but didn't run the readers,
  so the last reading is round 8's ([#195](https://github.com/littlebearapps/plainspoken/issues/195)).
- **Open issue [#75](https://github.com/littlebearapps/plainspoken/issues/75).** In round 10, all three long-form
  reports opened with words before the status block, which the report guard doesn't catch. It's fixed when the count
  is zero.
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
