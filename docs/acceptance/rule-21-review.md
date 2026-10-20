# Rule 21 review: synonym cycling

Date: 2026-10-19. Ruleset 4.2.0, branch `feature/pre-cutover`. Evidence only: no model calls, no paid calls, and
`data/rules.toml` is unchanged. The owner decides; the decision is applied (or not) afterwards through
`kaizen apply`.

Result: **rule 21 has never fired on real writing, and the judges get it right on the golden set.** Every number
below is small. The host's zero fires bound the real-text fire rate (95% upper bound about 20% of articles) but
say nothing about the judge's sensitivity on real text, because no true positive has ever been seen.

## The rule

- `data/rules.toml`: `id = "21"`, "Synonym cycling", `method = "judge"`, `group = "J2"`, `severity = "WARN"`,
  `era = "pre-2026"`, status active. Not in `[aliases]`.
- **No lint method.** There is no candidate pass, no threshold and no count, so lint fires are zero by
  construction. `data/kaizen.toml` says so: "a judged rule with no lint threshold, so it has no knob."
- Rubric (`data/rubrics/judges.md`, `### 21 Synonym cycling`): fail when one subject is renamed across nearby
  sentences for variety ("the tool… the platform… the solution… the system") where a human would repeat the name or
  use a pronoun; pass when each name is the natural one, or the different names mean different things.
- WARN means fix or justify. An unjustified WARN is UNRESOLVED, which blocks like a FAIL.
- Writers never see the rule (ban lists live in the checker only). The only writer-facing mention is advice in
  rule 12f's vocabulary-variety (MATTR) message: "reword the generic ones, without synonym cycling".

## The humanizer note

The repo's note (RULESET-CHANGELOG 4.1.0 and the original issue) says humanizer **3.1.0** (2026-09-28) dropped synonym
cycling. Checked against the upstream tags and release notes (blader/humanizer, read-only, 2026-10-19):

- **v2.11.1** (the last 2.x tag): pattern 11, "Changing names and repeating sentence openings", says "Use one
  clear name for the same subject", with a protagonist / main character / central figure / hero example.
- **v3.0.0 (2026-09-06): dropped.** The release notes: "Aligned with the current Wikipedia article. Dropped false
  ranges and synonym cycling, which Wikipedia now lists as a human habit and a historical indicator."
- **v3.1.0 (2026-09-28):** still absent. This is the version `skills/humanize` forks. Its pattern 7 keeps the
  repeated-openings half of the old pattern 11 and says "Do not ban the repeated word".

So the drop came in **3.0.0**, not 3.1.0; 3.1.0 inherited it. Upstream gives two reasons: humans do it too, and
it's a *historical* indicator, which matches the rule's `era = "pre-2026"`. I didn't read the Wikipedia article
itself; the claim is upstream's.

Side note, not acted on: upstream dropped "false ranges" in the same release for the same reason. That is
plainspoken's rule 16 ("From X to Y ranges").

## Golden cases

Eight cases, all `source = "constructed"`, all `status = "provisional"`. None is owner-confirmed or endorsed, and
none has changed since the golden set was created (so every run below scored the same text and labels).

| Case | Label | What it is |
|---|---|---|
| `J2-21-001` | fail | Hall booking notice: app / platform / solution / system for one app |
| `J2-21-002` | fail | Local history: baths / aquatic facility / swimming venue / leisure complex |
| `J2-21-003` | fail | Bakery: sourdough / loaf / bread / artisan product |
| `J2-21-004` | pass | Hard negative: two trailers and a van, different names for different things |
| `J2-21-005` | pass | Minimal pair of 001: one name plus pronouns |
| `J2-21-006` | pass | Minimal pair of 002: the name repeated |
| `JR-21-001` | accept | Justification holds: catalogue, newspaper archive and reading room are different services |
| `JR-21-002` | reject | Justification fails: one council app renamed app / platform / tool / solution |

Every J2 fail case renames its subject four ways. There is no two-name or borderline fail case.

One owner ruling bears on the rule indirectly. On `JR-12f-001` (owner-confirmed reject) the owner wrote that
swapping a recipe's working nouns for synonyms "would be worse" than the repetition 12f flags.

## Judge verdicts on the golden cases

Runs on disk (`.plainspoken/evals/*/replies.jsonl`, gitignored): only two of the thirteen runs include the rule 21
cases, the five-model panel and the two-model screen (both 2026-10-17, all 226 cases). The other eleven are J3,
JR-only or eight-case subsets with no rule 21 case. The Claude Opus runs of 2026-10-16 left reports, not replies:
runs 1 and 3 have per-rule rows; run 2 is derived from its group totals in `p6-evals.md` (J2 TPR and TNR 1.00, JR
misses only on 12d and 12f). One later Claude JR run (2026-10-18) is on disk.

| Judge | J2 fail cases caught | J2 pass cases passed | JR-21 correct |
|---|---|---|---|
| Claude Opus, 3 runs (run 2 inferred) | 9/9 | 9/9 | 6/6 (+ 2/2 in the 2026-10-18 JR run) |
| GLM 5.3 | 3/3 | 3/3 | 2/2 |
| GPT-6 Luna | 3/3 | 3/3 | 0/0 (refused both: "I cannot assist", scored as errors) |
| Gemini 3.8 Flash | 3/3 | 3/3 | 2/2 |
| DeepSeek v4.1 Flash | 3/3 | 3/3 | 2/2 |
| Muse Glimmer 30B | 3/3 | 3/3 | 2/2 |
| Command A Plus (screen only) | 2/3 (passed `J2-21-002`) | 3/3 | 1/2 (accepted `JR-21-002`) |
| Mercury 2.5 (screen only) | 3/3 | 3/3 | 2/2 |
| **All J2 verdicts** | **29/30** | **30/30** | **17/18 valid, 2 refusals** |

- **Accuracy:** 59/60 J2 verdicts and 17/18 valid JR verdicts match the labels. The production judge (Claude Opus)
  is 18/18 on J2 and 8/8 on JR, counting run 2 as inferred from its group totals (no per-rule rows survive).
- **Fire rate on the golden set:** 29 of 30 verdicts on fail cases fired; 0 of 30 on pass cases (including the
  hard negative) did.
- **Panel agreement:** unanimous on five of the six J2 cases across all eight models. On `J2-21-002` seven of
  eight agree; the dissent is the screen-only model, which isn't on the shipped panel. On JR the shipped panel and
  Claude are unanimous on both cases (GPT-6 Luna refused). The shipped five-model panel plus Claude is unanimous on
  all eight cases.
- The `p6-evals.md` caveat applies in full: the constructed cases "lean easy", so read these as an upper bound.

## Host pipeline (the host's own anti-AI reports)

Counted read-only by the host from its current reports and their git history. Only totals are recorded here.

| Measure | Count |
|---|---|
| Articles with an anti-AI report | 15 |
| Rule 21 J2 verdicts | 15 (one per article) |
| Fail verdicts (fires) | 0 (0 in the git history of those reports as well) |
| Lint spans | 0 (no lint method) |
| WARNs raised, so fixed or justified | 0 |
| Justify rate | undefined (0 of 0) |
| JR accept / reject on rule 21 | 0 / 0 |
| Runs where rule 21 caused FAIL, UNRESOLVED or REWRITE_ADVISED | 0 |

- **Fire rate:** 0/15 articles. The 95% Wilson upper bound is 0.20, so the real rate could still be up to about
  one article in five; 15 articles can't tell "rare" from "absent".
- **Sensitivity on real text is unmeasured.** No true positive has been seen, so nothing shows whether the judge
  would catch a real case.
- **False positives are unobserved, for the same reason.** The upstream worry (it flags a human habit) has no data
  behind it here either way.
- The host's writer guidance names synonym cycling as a tell, so the host's writer was told to avoid it. Part of
  the zero may be prevention. plainspoken's writer is never shown the rule, so the post-cutover rate may differ.
- The host's runs used the host's own judge, with the same rule text, not plainspoken's judge.
- This repo's local ledger has 207 rule 21 judge events, all passed, all on one document hash: repeated test and
  acceptance runs of one fixture. That is not evidence about the rule.

## Options

### A. Keep (WARN, judge-only, active)

- **Changes:** nothing.
- **Cost seen so far:** one verdict line in each J2 call; zero fix-or-justify work in 15 host articles.
- **Risk:** if the upstream reason is right, a fire on legitimate variation would cost a fix or a justification.
  None has happened. The rubric's pass clause and the JR accept path cover different names for different things,
  and every judge that answered accepted `JR-21-001`.
- **Retirement still happens on evidence:** kaizen's `dormant` trigger proposes `deprecated` after 90 days of
  ledger with no fire, then `remove` one 28-day cycle later (a judge rule can't go to shadow). The owner approves
  each step.

### B. Loosen ("WARN-only count")

The rule is already WARN, and a rule's severity can only be BLOCK or WARN (INFO is finding-level). Rule 21 has no
threshold, so there is no knob to turn. Loosening can only take one of two forms:

- **B1, a rubric edit that adds a count:** fail only when one subject gets three or more names in a paragraph, or
  when a rename is a generic category noun (platform, solution, system, facility). A normal commit with a
  RULESET-CHANGELOG line and no version bump (like earlier comment fixes), then a free Claude J2 re-run.
  **Measured effect: none.** Every golden fail case already has four names, and nothing fired on the host.
  **Risk:** a change made without evidence that also excuses a real two-name case.
- **B2, a "report, don't require fix-or-justify" mode for a judged WARN:** doesn't exist. It needs engine work in
  merge and coverage, with tests, before cutover. **Risk:** a new merge path for a rule that has never fired.

### C. Retire to shadow

**Not available as a data change.** The rules loader refuses shadow on any non-lint rule ("shadow rules are
lint-only"), and the judges skip shadow rules, so a shadow judge rule would never be asked about. In practice,
retiring means one of:

- **C1, `deprecated` now:** behaves exactly like active (first retirement step only), then removal later.
- **C2, remove now:** a `kaizen apply` `rule_remove` with a ruleset bump.
- **C3, build judge-shadow support:** new code and tests so a judge reports INFO outside merge coverage. It still
  pays for the verdict line, which is the only cost removal saves.

**Risk (C1/C2):** removes the only check on the opposite failure to rule 12f. 12f's lint pushes vocabulary
variety, its own message warns against synonym cycling, and the owner ruled on `JR-12f-001` that synonym swaps
would be worse. After removal nothing is recorded, so the decision can't be revisited on evidence.

## Recommendation

**A: keep rule 21 unchanged, and let the kaizen `dormant` trigger retire it on post-cutover ledger evidence.**

- It costs one verdict line per J2 call and, so far, no fix-or-justify work.
- The judges are accurate on the cases there are (59/60 J2 verdicts, production judge 18/18 and 8/8, with run 2
  inferred from its group totals), with no false fire on the hard negative.
- The upstream drop argues against blocking. The rule is already WARN, with a JR accept path for names that mean
  different things.
- Neither alternative has evidence behind it. B1 changes no measured outcome, B2 and C3 add engine code before
  cutover, and C removes the counterweight to 12f with no way to see what it would have caught.
- Upstream also calls it a historical (older-model) indicator. That is what the 90-day dormant trigger tests, on
  real ledger data and with the owner approving each step.

If the owner wants sensitivity measured rather than assumed, the cheapest step is an owner label on two or three
real passages, one of them a two-name rename, in the next golden review sheet.

## Corrections to record with the decision

- The humanizer drop was in **v3.0.0 (2026-09-06)**, not 3.1.0. RULESET-CHANGELOG 4.1.0 and the issue say 3.1.0.
  Recorded as a dated correction line under the 4.1.0 entry (the entry itself is left as written); the issue's closing
  comment carries it too.

## Decision (owner, 2026-10-19): keep

- **Rule 21 stays as it is:** WARN, judge-only (J2), active, rubric unchanged. No `data/rules.toml` change, no
  ruleset bump, no `kaizen apply`.
- Retirement, if it comes, goes through the kaizen `dormant` trigger on post-cutover ledger evidence, with the
  owner approving each step (option A above).
- The provenance is corrected to humanizer **v3.0.0**, as above.
