# Ruleset changelog

Ruleset versions are separate from the plugin version. Every report records the ruleset version it used.

## 4.4.0 (2026-10-31)

- **Rule 7d skips its no-long-sentence test in short pieces (#148):** new threshold `staccato_long_min_words = 150`.
  A piece under 150 words (counted as 12f counts them, the words in its rhythm sentences) gets only 7d's short-run
  test, whatever its content type, the way social posts already did. That covers a narrative profile's
  `long_sentence_headings` sections too. The FAQ test, the narrative run-and-no-long test and rule 7 don't change,
  and a piece of 150 words or more is checked exactly as before. A profile that sets the key to 0 gets the old
  behaviour back.
- **Why:** in a two-paragraph email the only fix the no-long test can ask for is a padded sentence, which is the
  pressure #73 is about. The issue's 121-word email got 7d for having no sentence over 25 words, and the plain fix
  was to keep it as it was.
- **The engine half:** a greeting that opens a piece ("Hi Sam,") and a sign-off that closes it ("Cheers, Alex") no
  longer count as 7d sentences, so a short email can't reach the five-sentence run on its greeting. That's a
  separate engine commit, not a ruleset key.
- **Measured effect (lint only, no model calls):** on the verdict-diff corpus, 149 of 276 texts change, all of them
  golden cases under 150 words. 7d WARNs go from 155 to 5, and 114 texts move from WARN to CLEAN; no other rule
  changes. The five 7d WARNs left are the run-form judge-review cases, so no golden case goes stale. On the 718
  saved campaign pieces (rounds 1 to 8, deduplicated), 7d WARNs go from 618 to 139: emails 50 to 0, text messages
  38 to 0, long-form pieces 60 to 60. No piece gains a finding, and rule 7 stays at 4.
- **What goes stale:** saved lint reports, judge results and kept-WARN justifications made under 4.3.0 read as
  stale and ask for a re-check, which is right, because a 7d WARN someone justified may no longer fire. The file's
  bytes change, so a pending kaizen proposal rebases.
- Added by hand, not through `kaizen apply`, with the version bump because results change. The owner approves by
  merging the pull request.

## Claims rubric revision (2026-10-30; ruleset version unchanged)

- **A pinned claim is judged on its passage (#77):** a claim whose text and locations say no more than its pinned
  passages passes, however it's reworded. A finding against a pinned claim quotes the article's words that go
  beyond the passage, and wording the checker would only have put differently isn't one. In the round-8 long-form
  runs the same offer wording passed in one piece and was blocked in two others, and an unchanged sentence passed
  one checker run and was blocked in the next.
- **A brief's lines about the piece are sources (#77):** its call to action, offer, audience and tone lines are the
  owner's word. A call to action pinned to such a line may invite every reader in the article's own words, unless
  the line narrows who it's for; only a term the line doesn't give (a price, length, deadline, what follows, a
  wider offer) is a finding. A round-8 checker blocked a call to action the brief named as the piece's call to
  action. The claims skill's evidence rules now say to pin the call to action to that line.
- New golden cases `CL-brief-005` and `CL-brief-006` (provisional). The rubric's hash changes, so an earlier
  `<key>.claims-check.json` reads as `checker result stale (rubric changed)` until the checker runs again. Not yet
  measured with `eval claims` (a paid run). The owner approves by merging the pull request.

## Engine change (2026-10-28; ruleset version unchanged)

- **Social caps merge as the stricter value (#104):** a cap (a `*_max` key) in a content type's layer, such as
  `[thresholds.social]`, now merges with the profile's value as the stricter of the two. Before, it replaced it, so
  a profile with `em_dash_max = 0` got the social cap of 1 in every short post, including every draft under 300
  words piped to `check -`. A profile that loosens a cap still never lifts a social one. Social keys that aren't
  caps (`conversational_block`, `uniform_sentence_run`, `staccato_short_run`, `staccato_short_len`) still replace
  the profile's value, and no `*_min` floor is in a content-type layer. Default-profile results don't change.
- **New threshold `en_dash_max` (#104):** rule 1 also counts en dashes against their own cap, separately from
  `em_dash_max`. The default is -1 (any negative value means no limit), so no result changes until a profile sets
  it. Once set, every en dash counts, number ranges included (`9am–6pm`, `2020–2026`): a writer who caps en dashes
  at 0 doesn't use them, and the issue asks for `9am–6pm` to be flagged then. A profile that keeps en-dash ranges
  sets a cap with room for them. The key is added to `[thresholds."default"]` by hand, not through `kaizen apply`,
  because it starts at no limit and changes no result; the owner approves by merging the fix PR. The file's bytes
  change, so a pending proposal's `base_sha256` no longer matches and `kaizen apply` rebases it.

## Register checklist change (2026-10-27; ruleset version unchanged)

`data/register-checklist.toml` isn't part of the ruleset, so `kaizen apply` doesn't govern it and the version stays.
A checklist change goes in by ordinary pull request, with a line here per changed item and at least one text it
should flag and one it shouldn't in `tests/test_register.py`. The owner approved these changes on 27 Oct 2026.

- **R7 First contact, the easy no:** judged by the message's shape. It passes when any ask is small, specific and
  optional, or there's no ask. It flags when declining is made awkward (a big or vague ask, a deadline, guilt) or
  stock reassurance is stacked ("no cost, no obligation, no reply needed"). One plain "no worries if not" stays
  fine. "Has no easy no" is gone from `flag_when`.
- **R7 First contact, sales scaffolding:** also flags a message that runs observation → credentials → offer → ask
  even though each sentence passes, holds back the useful part to get a reply, or asks for more than it gives.
  New worked example 4 in `skills/register-check/references/examples.md`; example 2 now names its stacked
  reassurance.
- **R8 Follow-up:** the same two clauses for a later note: it holds back the useful part to get a reply, or asks
  for more than it gives.
- **R7 First contact, a preference stated as an error:** also flags a message that presents the writer's taste
  about the reader's material as a mistake. The write skill's research gate
  (`skills/write/references/research-gate.md`) now checks that premise before such a message is drafted.
- **R2 Outcome promises:** also flags an outcome outside the writer's control presented as waiting only on more
  evidence ("not until I've seen the numbers"). The matching line is in the control principle,
  `skills/copy-audit/references/principle.md` "Truth and control".

## Engine change (2026-10-21; ruleset version unchanged)

- **Rule 12f, opening repetition scales with length (#25):** the limit is now `opening_top3_max` plus 3/n, where
  n is the number of sentences counted. The top three openers always cover at least 3 of n sentences, so the flat
  0.25 failed short pieces on length alone. Measured on 13 long first-person blog posts (model-drafted,
  human-edited): a 300-word window read 0.12 above its whole post, 500 words 0.08, 1,000 words 0.03 (62 prose
  extracts from human-written READMEs: 0.09, 0.05, 0.02). Paragraph SD read at most 10% low and MATTR (raw TTR
  below the 500-word window) never tripped there, so neither changes; nor do burstiness and the MATTR WARN.
  Effect on the 2+-trips WARN: windows of posts whose whole text is clean fired 50% at 300 words, 33% at 500 and
  21% at 1,000, and now fire 6%, 10% and 8%; the whole posts are unchanged (1 of 13). Campaign pieces of
  300–499 words: 18 of 22 before, 5 after. At 2,500 words the limit rises by about 0.02. The threshold value and
  the ruleset version are unchanged; the owner approves by merging the round-4 fix PR.

## Comment revision (2026-10-19; ruleset version unchanged)

- **Stale forward references:** comments only, so no rule, threshold or list changes and no version bump
  (the same as earlier comment-only fixes). `rules.toml` no longer points at a Phase 3 rule reference in
  `guides/` (none ships) or says social severities arrive with the adapt skill (they aren't modelled; that needs a
  kaizen proposal). The three `data/locales/en-*.toml` headers no longer promise a Phase 3 spelling-preference
  check (none ships). The file's bytes change, so a pending proposal's `base_sha256` no longer matches and
  `kaizen apply` rebases it.

## 4.3.0 (2026-10-19)

- KZ-20261019-b9d6bb: rule 12d, add (trigger: owner). rule 12d: add (a FAQ-only run threshold for 12d, the narrow knob calibrate turns when the evidence sits in FAQ sections; the same value as paragraph_uniform_run, so no change until evidenc…
- Evidence: design_gap 12d has no FAQ-only knob
- Approved by owner.
- **Rule 12d, FAQ-only run (`paragraph_uniform_faq_run`):** the run length 12d needs when a run starts in a
  FAQ section (the same test as the `faq` section facet), so calibrate's narrow knob can loosen 12d for FAQ answers
  alone when the evidence sits there, as `staccato_faq_short_run` does for 7d. It starts at 4, the value of
  `paragraph_uniform_run`, so nothing fires differently until kaizen evidence turns it. Added through the new
  `threshold_add` edit kind. The approval is the owner's 19 Oct 2026 plan decision ("all recommendations
  approved"); the implementing agent transcribed the decision line.

## 4.2.0 (2026-10-19)

- KZ-20261019-9fd6de: rule 33, add (trigger: owner). rule 33: add (owner review sheet 2: count stock significance phrases like rule 2b, shadow first): add rule 33 (Stock significance phrases) with list stock_significance and threshold stock_signi…
- Evidence: golden J3-12c-006 J3-12c-008; owner_note sheet 2, J3-12c-008
- Approved by owner.
- **Rule 33, stock significance phrases (shadow, report only):** counts phrases such as "far-reaching
  implications" and "pivotal moment" (list `stock_significance`) like rule 2b: one is fine, 2 or more
  (`stock_significance_warn`) is a WARN once promoted. From the owner's review sheet 2 (18 Oct 2026): `J3-12c-008`
  isn't a 12c tell, but the phrase reads a bit telly and a better sentence names who it affects. Kept out of 12c so
  that rule stays a scale test. Promotion only through kaizen with evidence. The approval is the owner's 19 Oct
  2026 plan decision ("all recommendations approved"); the implementing agent transcribed the decision line.

## Rubric revision (2026-10-19; ruleset version unchanged)

- **Rule 12c (J3), size test:** a narrow scope doesn't excuse an inflated size. Big significance language
  about one local thing (one school, one shop, one event) needs evidence that the change reaches across much of
  it; one or two small changes are a fail even though the scope is narrow. The earlier scope test is unchanged: a
  narrow claim with matching evidence still passes. Prompted by the owner-confirmed `J3-12c-009`, which Claude Opus
  passed in 3 of 3 runs while all four panel models that answered failed it. Approved by the owner on 19 Oct 2026.
  Claude Opus after the change: J3 60/60 in 2 of 2 runs, `J3-12c-009` a fail in both, every other 12c case on its
  label. No panel re-run.

## Delivery rubric (2026-10-19; ruleset version unchanged)

- **New rubric `data/rubrics/delivery.md`:** the isolated `delivery-checker` agent's rubric for the
  reader-value delivery gate: the seven items (`outcome` … `start_here`) ported from the host's pre-publish delivery
  gate, verbatim-evidence rules and the reply schema. `<key>.delivery.json` binds its hash, so a later edit makes
  earlier delivery records stale. The reading of the success-and-stop item for history and commentary contracts is
  plainspoken's own and is labelled as such.

## Claims rubric revision (2026-10-19; ruleset version unchanged)

- **Verbatim evidence:** a finding's `evidence` is at least three words. `claims record` marks shorter
  evidence unverified, because one or two common words are found almost anywhere. The rubric's hash changes, so an
  earlier `<key>.claims-check.json` reads as `checker result stale (rubric changed)` until the checker runs again.
- **Severity names `scope_stretch`:** the class (a location that says more than the claim's ledger `text`)
  is listed under `blocking`, beside the location-level entailment failures ("What to check" item 6). The rubric's
  hash changes again, with the same effect on earlier checker records.

## Rubric revision (2026-10-18, second; ruleset version unchanged)

- **Rule 12c (J3):** a scope test. Judge the stated scale against the scope the sentence itself names; when the
  article's evidence covers that scope, it's a pass even for a listed phrase. Prompted by `J3-12c-006`, which two
  to three panel models flagged per run while Claude passed it.
- **Rule 17 (J3):** what the reader already knows comes from the passage. When the text expects the reader to do
  the thing, an analogy for its basics talks down; when it says its reader is new, a plain analogy can help.
  Prompted by the owner-confirmed `J3-17-001`, which GLM passed in both panel runs.
- New golden minimal pairs `J3-12c-007`/`-008` and `J3-17-007`/`-008` (provisional). Claude Opus after the
  change: J3 59/59 in 2 of 2 runs. Approved by the owner on 18 Oct 2026.

## Rubric revision (2026-10-18, ruleset version unchanged)

- **Rule 27 (J3):** a marketing "optimise" that belongs to someone else (a vendor's pitch, a quote) passes when
  the writer doubts, tests or deflates it. The writer's own paraphrase (indirect speech), or reporting the phrase
  and carrying on in the same frame, still fails.
  Approved by the owner on 18 Oct 2026 after all six judges flagged the confirmed pass `J3-27-003`.
  `rules.toml` is untouched (`kaizen apply` edits only the ruleset file); reports pin the rubric by its
  `rubric_sha256`. New golden minimal pair `J3-27-007` (fail). Claude Opus after the change: J3 55/55 in 2 of 2 runs, JR
  unchanged (its one miss, `JR-12d-001`, predates this).

## 4.1.0 (2026-10-10)

- Every rule carries `era`; new rules also carry `models` and a cited `source`.
- Findings report a per-1,000-word rate per rule (`rates_per_1k`).
- Five **shadow** rules (report only, never block, outside merge coverage): 28 salience flags,
  29 sincerity markers, 30 signposting openers, 31 gotcha framing, 32 newer model-era words. Sources in
  `data/rules.toml`. Promotion needs a kaizen proposal with evidence and human approval (Phase 5).
- Proposed for review (not changed): rule 21, synonym cycling. humanizer 3.1.0 dropped it as a human habit.
- Correction (2026-10-19): the drop was in humanizer **v3.0.0** (2026-09-06), not 3.1.0; 3.1.0 inherited
  it. The review (`docs/acceptance/rule-21-review.md`) found no fire on real writing; the owner's decision, 19 Oct
  2026, is to keep rule 21 unchanged. No ruleset change.

## 4.0.0 (2026-10-10)

- Ported from the author's earlier private ruleset (v4). Site-scoped rules became profile-scoped (now `PB` and
  `NR-1…6`); the site's banned phrases moved to profiles; `[aliases]`, `judge_may_block`, `[thresholds.social]`
  and `[spelling] expand` added.
