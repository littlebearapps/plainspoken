# Phase 6 acceptance: evals, golden sets and hardening

Date: 2026-10-16. Claude Code CLI 2.1.300, Linux. Branch `feature/p6-evals`, stacked on `feature/p5-kaizen`.
Everything below that cost nothing ran on the Claude subscription (`claude -p`); the notional cost the CLI reports
is recorded, and nothing was billed. No paid run has been made: each needs the owner's OK.

## Where the accept line stands

| Accept item | Status |
|---|---|
| Judge TPR/TNR ≥ 0.8 per group, Claude | **Met on the `all` split in 3 of 3 runs**, with the caveats below |
| Judge TPR/TNR ≥ 0.8 per group, cross-family | **Not run.** Needs an OpenRouter key and the owner's OK (estimate below) |
| Trigger ≥ 0.8 | Met in Phase 3 (28/28, `docs/acceptance/p3-evals.md`); no skill description changed since, so not re-run |
| Rewrite delta positive against the baseline | **Not run.** `claude plugin eval . --tag rewrite` is a paid run |
| Tier-2 blind test run once | **Not run.** Needs the panel key and an author-writing corpus (see "Open") |

So Phase 6 is built and its free half is verified. v1.0.0-rc.1 waits on the paid half.

## The golden set

226 cases in `evals/golden/` (J1 40, J2 50, J3 54, J4 40, JR 42), each label balanced within its group.

- **2 confirmed** (an explicit owner ruling), **15 endorsed** (fixes or keeps the owner approved and shipped), **209
  provisional** (constructed). Human-backed texts are anonymised.
- Every case was labelled twice: once by the agent that wrote it, once by a separate agent that saw only the rubric
  and the text. They agreed on 226 of 226; 11 were marked low-confidence.
- Full agreement from one model family suggests the constructed cases lean easy. **Read the `all`-split numbers as an
  upper bound.** The owner's labelling sheet (25 cases, the doubtful ones first) is what turns provisional into
  confirmed.

## Claude judge validation (`eval judges --models claude-opus`)

Three runs of all 226 cases, each 226 calls, 0 errors, US$0 billed (notional US$5.99, 6.00 and 1.99).

| Group | TPR (all) | TNR (all) | Human-backed split |
|---|---|---|---|
| J1 | 0.95 → 0.90 → 0.90 | 1.00 | TPR 6/7 → 5/7 → 5/7 (no human passes) |
| J2 | 1.00 | 1.00 | 7/7 fails, 3/3 passes |
| J3 | 1.00 | 1.00 | none |
| J4 | 1.00 | 1.00 | none |
| JR (positive = reject) | 1.00 | 0.89 (17/19) | none |

Every group met the bar (TPR and TNR ≥ 0.8, errors ≤ 10%) in every run. The misses:

- **J1-5b-001, the one owner-confirmed tell, was missed in runs 2 and 3** after being caught in run 1. Claude runs at
  the CLI's default sampling, so the judge isn't deterministic on a borderline case. This is the most important
  number in the table: on the human-backed J1 cases the judge catches 5 of 7, below the bar.
- J1-26-003 (endorsed tell) was missed in all three runs. Both J1 misses were also low-confidence for the blind
  labeller.
- JR-12d-001 and JR-12f-001 (provisional accepts) were rejected in all three runs. The JR rubric says "when unsure,
  reject", and JR-12f-001 was low-confidence for the labeller too.

The full reports were kept outside the repo.

## Ablation (drafting harness, `claude-opus-5-5`)

**Finding first:** on the six generic mining briefs (`evals/briefs/`), every plugin-arm run stopped at the write
skill's research gate after about 2 turns ("I'm not allowed to fill them in from memory"), because those briefs ask
for facts they don't carry. The plain model wrote all six and invented the facts. The plugin refuses to fabricate
where the baseline doesn't. The ablation then used six self-contained briefs (`evals/ablation/briefs/`: the author's
notes carry every fact), the same input for every arm.

Plugin arms run with `--setting-sources project,local`, so the owner's own plugins, skills and CLAUDE.md don't load
(an unisolated plugin run cost US$3.02 notional against US$1.73 isolated). 21 drafts, about US$48 notional.

| Arm | Briefs | BLOCK-bearing | Em dash over cap | New numbers | WARN findings on the 3 shared briefs |
|---|---|---|---|---|---|
| none | 6 | 0 | 0 | 0 | 10 |
| plugin | 6 | 0 | 0 | 0 | 2 |
| plugin+style | 3 | 0 | 0 | 0 | 6 |
| plugin+brief | 3 | 0 | 0 | 0 | 3 |
| plugin+banlist | 3 | 0 | 0 | 0 | 0 (8 candidates) |

Opus 5.5 already avoids the hard tells on short pieces, so BLOCK counts can't tell the arms apart. WARN counts lean
toward the plugin, but 3 drafts per arm is a hint, and the plugin's own lint is grading the plugin's own output. Plan
item 6.7 says the reader test or the golden set decides, so **the defaults are unchanged** (output style and session
brief off, no ban list in drafting prompts) until a tier-2 blind run compares the arms.

## Costs of the paid runs still to do (dry-run estimates)

- `eval judges` on the default four (`glm`, `openai`, `gemini`, `deepseek`; the panel was revised on 2026-10-17 for
  writing quality per dollar; the comparison was kept outside the repo): 904
  calls, **≤ US$4.66**. The ceiling assumes 2,000 output tokens a call; the replies are a few hundred tokens of JSON,
  so the real bill should be about US$2–3. The first six-vendor panel's ceiling was US$19.97. Pilot first on
  `tests/fixtures/golden` with `--max-cost-usd 1`.
- `claude plugin eval . --tag rewrite` (6 cases × 2 arms × 1 run): about US$1–3 (P3's cases ran at US$0.07–0.27 each).
- The tier-2 blind run: about 20 pairs × 2 orders × 4 models; a dry run prices it once the pairs exist.

## Paid pilot (2026-10-17, owner's key, US$0.07 in total)

- 16 calls on the 4 fixture cases, plus single-call probes. Privacy routing works: every model answered with
  `data_collection = "deny"` and `zdr = true`. Real cost ≈ US$0.003 a call, so the 904-call judge run ≈ US$2.50.
- **Reply ceiling:** at 2,000 tokens, DeepSeek, Qwen and Muse Glimmer sometimes thought until the limit and never
  answered on a JR prompt. At 6,000 (now shipped) all answered correctly. Billing follows tokens actually written.
- **OpenAI on zero retention refuses the JR prompt.** GPT-6 Luna and GPT-5.6 Luna both returned a canned "I'm
  sorry, but I cannot assist" with 0 tokens counted when `zdr = true`, on a harmless parts-list case. The same call
  without ZDR (still `data_collection = "deny"`) answered normally, and both answered the J cases correctly on ZDR.
  The owner decides between OpenAI on the standard route and a replacement family.

## Cross-vendor judge run (2026-10-17, US$4.16 for this run, owner's key)

All 226 golden cases on the five-model panel, plus a screening and full run of two candidates. Every OpenRouter
call used `data_collection = "deny"`; the owner's account enforces zero retention.

| Model | Accuracy (answered) | Groups meeting the bar | Owner-backed cases right | Errors | US$ per call |
|---|---:|---|---:|---:|---:|
| DeepSeek V4.1 Flash | 0.97 | 5 of 5 | **16/17** | 1 | 0.0005 |
| Gemini 3.8 Flash | 0.98 | 5 of 5 | 13/17 | 0 | 0.0043 |
| GLM-5.3 | 0.96 | 5 of 5 | 11/17 | 5 | 0.0089 |
| GPT-6 Luna | 0.96 | 4 of 5 (JR blocked) | 13/17 | 41 (all JR) | 0.0003 |
| Muse Glimmer 30B | 0.92 | 3 of 5 (J2 TPR 0.74, JR TNR 0.79) | 9/17 | 0 | 0.0025 |
| *Cohere Command A+ (candidate)* | 0.83 | 1 of 5 | 8/17 | 11 | 0.0029 |
| *Inception Mercury 2.5 (candidate)* | 0.92 | 3 of 5 | 6/17 | 3 | 0.0004 |

For comparison, Claude Opus got 15/17 owner-backed cases in runs 2 and 3.

- **Majority vote** of the five panel models: 222 of 225 decided cases correct (98.7%). Swapping in Cohere or Mercury
  never improved it (96.4–98.7%), so neither joins. Writer Palmyra X5 (77% on a 40-case screen) and Mistral Large 4
  (its zero-retention host rate-limited 55 of 68 calls) were dropped at screening.
- **GPT-6 Luna on JR:** with account-level zero retention, its only route is Azure, which answers every JR prompt with
  a canned "I'm sorry, but I cannot assist" (0 tokens). The owner chose to keep account ZDR on and limit OpenAI to
  J1–J4 (`groups` in the panel). Switch to GPT-6.1 Luna once OpenRouter lists it.
- **GLM-5.3** sometimes thinks past 6,000 tokens (13 of 226). A retry at 16,000 recovered most; 2 still ran to
  16,000 and 3 returned malformed JSON. It's also the costliest per call.
- Cross-family accept item: met in full by DeepSeek, Gemini and GLM (TPR and TNR ≥ 0.8 in every group), and by the
  majority vote.

## Owner review of 25 cases (2026-10-18)

The owner worked through the 25-case sheet and agreed with the doubtful-case calls on every item. All 25 are now
`confirmed`, so the human-backed split grows from 17 cases (2 confirmed, 15 endorsed) to 35 (26 confirmed, 9
endorsed). Two labels changed:

- **`JR-12f-001` accept → reject.** The reason blames the recipe's working nouns, but the low vocabulary variety
  comes from one feeding step copied out word for word three times, which a delete-only pass could cut. Claude
  rejected it in all three runs, so Claude was right and the provisional label was wrong.
- **`J3-27-003` fail → pass.** The writer echoes a vendor's pitch ("is meant to help clubs optimise…") and then
  deflates it ("In practice…"), so the word is quoted for effect, not adopted.

Re-scoring the 2026-10-17 panel run against the new labels (same replies, no new calls; the prompts never carry a
label):

| Judge | Owner-backed cases right (was /17) | Groups meeting the bar on `all` |
|---|---:|---|
| DeepSeek V4.1 Flash | **31/35** | 5 of 5 |
| Gemini 3.8 Flash | 29/35 | 5 of 5 |
| GLM-5.3 | 26/35 (2 errors) | 5 of 5 |
| GPT-6 Luna | 25/35 (5 errors, all JR) | 4 of 5 (JR blocked) |
| Muse Glimmer 30B | 25/35 | 3 of 5 (unchanged) |
| Claude Opus (16 October runs, derived from their counts) | 32/35 run 1, 31/35 runs 2–3 | 5 of 5 |

Majority vote of the five panel models: 220 of 225 decided cases (was 222), because both flipped cases now count
against it.

- **Every judge, Claude included, flags `J3-27-003`.** Six of six called the ironic "optimise" a tell. The judges
  spot the word rather than read how it's used; the rule-27 rubric has no line for a quoted or deflated vendor
  phrase. A rubric change goes through kaizen (human-approved, versioned).
- **Rule-27 fix (same day, owner-approved):** the rubric now passes a vendor's "optimise" the writer doubts
  or deflates, and still fails a paraphrase or a phrase carried on in the same frame. A first wording also passed
  `J3-27-002` (a reported question answered concretely), so the indirect-speech line was added. Claude Opus on the
  final wording: J3 55/55 (with the new minimal pair `J3-27-007`) in 2 of 2 runs; JR 41/42, its one miss the
  pre-existing `JR-12d-001`. Panel re-run on J3 (owner's OK, US$0.71 billed): `J3-27-003` now passes for GLM,
  Gemini, DeepSeek and Glimmer (OpenAI still flags it); `J3-27-002` and `J3-27-007` fail for all five; every model
  meets the bar on J3 and the majority vote gets 54/54 decided (one tie). Misses on other J3 rules rose from 4 to 7
  (J3-2-008, J3-10-003, J3-12c-006, J3-17-001): those rules' wording didn't change, so read it as run-to-run noise.
- **Rule 12c and 17 fixes + repeat run (same day, owner-approved):** 12c gained a scope test, 17 reads
  what the reader knows from the passage, each with a fresh minimal pair (golden set 231). Claude Opus: J3 59/59
  in 2 of 2 runs. Then the four disputed cases plus the four new ones went to the panel three times with the
  serving host recorded (120 calls, US$0.36):
  - `J3-12c-006` and `J3-17-001` right in 15 of 15 for every model (before: 2 and 1–2 misses per run).
  - `J3-2-008` (provisional, arguable): GLM wrong 3 of 3, DeepSeek 2 of 3; sent to the owner's review.
  - One-off flips: OpenAI on `J3-10-003` and `J3-12c-008`, DeepSeek on `J3-12c-008` (1 of 3 each).
  - **Hosts don't explain the flips.** OpenAI ran on Azure 24 of 24, DeepSeek on DigitalOcean 24 of 24, Gemini on
    Google, Glimmer on Together, GLM on CoreWeave 20 of 24. Every flip happened on the same host as the model's
    right answers, at `temperature: 0`, so it's the model (likely reasoning) not the routing. Pinning hosts
    wouldn't help.
- **Owner review 2 (same day):** 6 J3 cases confirmed, no label changes: `J3-2-008` (only just a tell),
  `J3-12c-006` (grey area, not a tell) and the four new pair cases. Human-backed split now 41 (32 confirmed, 9
  endorsed); J3 has 10. Follow-ups not decided: a third 12c case separating claim size from scope (added 19 Oct), and a
  count-based warning for stock significance phrases.
- **Rule 12c size vs scope (19 Oct 2026):** `J3-12c-009` ("far-reaching implications for Wattle Creek Primary",
  only the later start and the buses as evidence) added with the owner's label, fail (mild tell), confirmed; golden
  set 232, J3 60, human-backed 42. Owner's call: the claim names one school, but two small changes don't carry
  "far-reaching".
  - **Claude Opus (subscription, free):** J3 59/60, meets the bar. The one miss is the new case: it answered pass.
    The other 59 J3 cases are unchanged, including `J3-12c-007` (fail) and `J3-12c-008` (pass).
  - **Panel, 12c pair plus the new case** (`J3-12c-007`, `-008`, `-009`; 15 calls; the CLI picks by group, not rule,
    so this is the subset that fit the US$0.25 cap; US$0.04 billed): OpenAI, Gemini and DeepSeek 3 of 3. Glimmer
    got `-007` and `-009` right and failed `-008` (a pass). GLM got `-007` and `-008` right, and `-009` came back
    with no message content, so it counts as an error (a one-case retry hit the run's cap and wasn't repeated).
  - **Reading:** all four panel models that answered `-009` call it a tell, so Claude is the outlier on this case.
    The 12c rubric isn't changed on one case; whether to add scope-versus-evidence wording is the owner's call.
  - **After the 12c rubric line (19 Oct 2026, owner-approved):** the owner chose to add a size test to 12c: a narrow
    scope doesn't excuse an inflated size, so big language about one local thing backed by one or two small changes
    fails; the scope test stays. Claude Opus (subscription, free), two runs of the J3 group: **J3 60/60 in both**
    (TPR 30/30, TNR 30/30, 0 errors; notional US$0.63 and US$0.50, nothing billed). `J3-12c-009` is a fail in both,
    with the sentence quoted and the two small changes named as too small for the claimed size. Every other 12c case
    keeps its label in both runs (`-001` to `-003` and `-007` fail; `-004` to `-006` and `-008` pass). No panel
    re-run (paid, not approved), so the panel figures above predate the line.
- **`JR-12f-001`:** GLM, Gemini and DeepSeek accepted the excuse; only Glimmer (and Claude) rejected it.
- **`JR-12d-001`** (confirmed accept) is still rejected by Claude in all three runs and by DeepSeek and Glimmer.
  The JR rubric's "when unsure, reject" costs a fair excuse here.
- The owner's side notes on items 19 (`J3-12b-005`: "Studies show" overclaims a single report, a nitpick that
  doesn't change the label) and 25 (`JR-2b-003`) were recorded outside the repo. On item 25: the lint does count
  all four WARN words there, because the quotation spans two sentences and the quote detection only covers a quote
  inside one sentence (a one-sentence quote's words are kept at INFO). The case tests the lint as well as the JR
  judge. The quote gap was fixed later, in 0.5.0: a quotation that runs over several sentences now stays quoted.

The rescored report was kept outside the repo.

## Open

1. **The blind test needs the author's own unassisted writing.** The published blog posts were drafted with AI help,
   so they can't stand in as the "person" side. About 10 pieces of 350+ words written without AI (emails, posts,
   notes) would do.
2. A model-access key for the panel (one OpenRouter key) and an OK for each paid run, with a cap.
3. ~~The owner's 25-case labelling sheet~~: done 2026-10-18 (section above).
4. Tier 1 (3–5 human raters) stays the owner's call; `eval blind form` makes their form.
5. Deferred minors from the build: tracked as follow-up work.
