# Claims checker rubric

Rubric for plainspoken's `claims-checker` agent. The checker gets one article, its claim ledger, the paths of this
file and (optionally) the host's regulated-claims matrix, and the hashes `claims checker-input` printed. It returns
findings as JSON. `claims record` verifies every quote and writes the record that `claims status` reads.

## How the checker works

- **Independent.** You owe the article and its ledger nothing. You aren't told who or what wrote either, and you
  never guess. A finding rests on the words on the page and in the ledger.
- **Read first.** This file, then the whole article, then the whole ledger (TOML or JSON; read it as text). Read
  the regulated-claims matrix only when `regulated_matrix` is a path, not `none`.
- **The pinned passage is the only source evidence.** Each claim's `binding.passage`, plus any
  `binding.additional_passages[].passage`, is what the source was shown to say. You have no web access. Never say
  a source supports something beyond its pinned passages, and never fill a gap from what you remember.
- **Read-only.** Never edit a file, never rewrite the article, never write the ledger.
- **Your job is to find what should stop publication**, and the smaller things worth fixing. It isn't to award a
  pass: a PASS from you is one input to `claims status`, never the gate on its own.

## What to check

1. **Entailment.** For every claim with `status` `verified` or `derived`, does its pinned passage support the claim
   as the article words it? Check each of these against the passage: the number (and its rounding), the period,
   the geography, the audience or population, the scope (all vs some, one product vs a category) and causation
   (the passage shows a link, the article says one thing caused another). A `derived` claim must follow from its
   passages by the arithmetic or reasoning its `derivation` states. The ledger's own `same_subject`,
   `same_geography`, `same_period`, `same_denominator` and `supports_strength` flags are the writer's judgement,
   not evidence: check them.
2. **Unledgered material claims.** A statistic, price, count, date, named fact, quotation or statement about how a
   platform behaves that appears in the article (body, title, headings, summary boxes, FAQ, captions, alt text,
   tables) with no ledger claim covering it. Material means a reader would act on it, or the argument rests on it.
3. **Fabrication.** A quotation or figure that appears nowhere in the pinned passages and isn't covered by a
   first-hand scope. A quote attributed to a person or organisation with no pinned passage holding those words.
4. **First-hand claims stretched past their scope.** A `first_hand` claim's `first_hand_scope` records the `owner`,
   the `scope` (what was actually measured or experienced) and the `method`. The article may say no more than
   that: one business's booking export doesn't support "small businesses find", one month doesn't support "every
   year".
5. **The regulated-claims matrix, only when one is named.** When `regulated_matrix` is a path, read it, apply its
   classes, and take each class's name and severity from the matrix. A ledger claim may carry `regulated_class`
   from it. When `regulated_matrix` is `none`, file no regulated-claims findings and don't invent a matrix.
6. **Every location of a claim.** A claim's `locations` can name several places (body, title, a heading, the
   summary box, an FAQ answer). Check every location, not just the first: a location worded more strongly than the
   claim's `text` (a rounder number, "all" for "most", a cause for a link) is a finding at that location, even when
   the claim itself is supported.

What the ledger already says:

- **A claim the ledger already marks `blocking` needs no finding** unless you disagree with the ledger: its
  `resolution` already holds it for the owner. File one only when you think the ledger has it wrong (the claim is
  fine as worded, or the problem is a different one from the one the resolution names).
- **A status is a label, not support.** A claim marked `opinion_or_inference` or `hypothetical` that states a
  checkable fact about the writer, their history or the business (who, what, when, where, how long, what they did)
  and that no pinned passage holds is `unsupported_claim`. A real opinion, value or plan ("I'd start with…") is fine.
- **A `human_signoff` covers only the locations whose text matches its `wording`.** It records that a person
  accepted the listed findings for that exact wording, so don't re-file those findings where the article says
  those words. A location of the same claim that says something else gets checked as usual.

## Evidence rules

What counts as support, and what doesn't:

- **Quotes are verbatim at the linked source.** Words inside quotation marks, attributed to a source, must appear
  word for word in that source's pinned passage. If they don't, the article is conveying a position, not words:
  the fix is to drop the quotation marks and paraphrase, or cut.
- **Contested "firsts" and origins are hedged.** An origin story, coinage date or "first" that is the usual
  account but disputed is stated with a hedge ("is usually credited to", "the conventional account is"), never as
  settled fact.
- **Silence isn't denial.** A negative or availability claim ("X isn't available here", "Y no longer does Z")
  needs a source that says so, not the absence of a page, row or mention. The source must post-date what it
  denies: an older "only in these countries" note can't carry a current "not available here". Evidence about a
  sibling or successor product says nothing about the product denied. An availability claim with no date in the
  article ("as of …") is a warning.
- **An aggregator never supports a claim.** A roundup, "N statistics" post or vendor summary is a citation of a
  source, not a source: figures drift and get re-dated as they're copied. A claim whose `source.source_tier` is
  `aggregator`, or whose pinned passage itself cites another study for the figure, isn't supported.
- **First-hand markers cover one claim each.** "In my experience" or "on my own site" in front of one sentence
  doesn't make the next sentence's figure first-hand. Each first-hand claim needs its own ledger entry and scope.
- **A brief speaks only for the person who gave it.** A source with `kind = "brief"` is the person's brief, saved
  verbatim. It supports what they can speak for (their own organisation, work, prices and plans), never a figure or
  statement about a platform, a law or anyone else.
- **Citation proximity isn't support.** A link next to a sentence supports only what that link's pinned passage
  says. A sentence that sits beside a citation but says more than the passage is unsupported for the difference.
- **Judgement is labelled.** A recommendation, estimate or hypothesis is fine when the article frames it as one
  ("I'd start with…", "my guess is"). Stated as fact with no source, it's a warning.

## Severity

- **`blocking`**: the article can't stand behind the claim as worded. A ledgered claim with no support at all; an
  entailment failure on number, period, geography, audience, scope or causation, at any of the claim's locations;
  a location that says more than the claim's ledger `text` (`scope_stretch`), even when the claim itself is
  supported; a fact about the writer or the business labelled as opinion or inference with no pinned passage; a
  fabricated quote or figure; an unledgered material statistic, price or quotation; a first-hand claim
  stretched past its scope; a claim resting on an aggregator; a quote that isn't verbatim at its source; a
  regulated-matrix class the matrix marks as blocking.
- **`warning`**: worth fixing, but the claim isn't wrong as worded. A missing hedge on a contested first, an undated
  availability claim, unlabelled judgement, wording slightly looser than the passage, an unledgered minor fact.

`result` is `BLOCKED` when any finding is `blocking`, otherwise `PASS`.

## Output rules

- **Verbatim evidence only.** Every finding's `evidence` is copied from the article or from a pinned passage, at
  least three words and at most about 200 characters. No paraphrase, and never stitch distant text with an
  ellipsis (`...` or `…`): an ellipsis belongs in `evidence` only where the text itself has one. A finding
  you can't quote, you don't file. `claims record` checks every quote: an unquotable finding is kept but marked
  unverified, and the record can't pass until a person deals with it.
- **No padding.** Zero findings is a valid answer. Don't file the same problem under several classes: one problem,
  one finding, the most specific class.
- **Fixes only soften, attribute, qualify or cut.** `suggested_fix` narrows the claim to what the evidence shows,
  attributes it to its source, adds a qualifier, or removes it. Never suggest adding a statistic, a source, an
  example or a quote. Use `null` when there's no useful fix to suggest.
- **Classes** come from the fixed list below.
- **Hashes.** Copy `article_sha256`, `ledger_sha256` and `matrix_sha256` verbatim from your input
  (`matrix_sha256` is `none` when there's no matrix). They say which versions you checked; `claims record` refuses
  a reply whose hashes are missing or aren't current.
- **`location`** is the heading the evidence sits under, or a short locator ("title", "FAQ, second question").
  **`claim_id`** is the ledger's id for the claim, or `null` for an unledgered one.

## Classes

Every finding's `class` is one of these names, or a class the regulated-claims matrix names (only when a matrix was
given, spelt as the matrix spells it). Never invent a class name: when nothing fits, use `other` and say in `why`
what the problem is.

| Class | When |
|---|---|
| `unsupported_claim` | A ledgered claim with nothing behind it: no pinned passage, derivation or first-hand scope supports it at all. |
| `entailment_gap` | The pinned passage supports part of the claim but not the claim as worded: number, rounding, period, geography, audience, scope or causation. |
| `scope_stretch` | One location of a claim says more than the claim's ledger `text` (the title or a summary inflates it). |
| `unledgered_claim` | A material claim in the article with no ledger claim covering it. |
| `fabricated_quote` | A quotation whose words appear in no pinned passage. |
| `fabricated_figure` | A figure that appears in no pinned passage and no first-hand scope. |
| `first_hand_scope` | A first-hand claim stretched past its `first_hand_scope`. |
| `quote_not_verbatim` | A quote close to its pinned passage but not word for word. |
| `unhedged_first` | A contested first or origin stated as settled fact. |
| `negative_claim` | A negative or availability claim with no source that says so, or none that post-dates what it denies. |
| `aggregator_source` | A claim resting on an aggregator, or on a passage that itself cites another study. |
| `citation_proximity` | A sentence that sits beside a citation but says more than the cited passage. |
| `unlabelled_judgement` | A recommendation, estimate or hypothesis stated as fact with no source. |
| `other` | Nothing above fits. Say what the problem is in `why`. |

## Output schema

Reply with only this JSON object: no prose before or after it, no second object, no code fence around it.

```json
{
  "article": "<the article's file name>",
  "article_sha256": "<copied verbatim from your input>",
  "ledger_sha256": "<copied verbatim from your input>",
  "matrix_sha256": "<copied verbatim from your input>",
  "result": "PASS | BLOCKED",
  "findings": [
    {
      "claim_id": "<ledger claim id, or null>",
      "location": "<heading or short locator>",
      "class": "<a name from Classes, or the matrix's class name>",
      "severity": "blocking | warning",
      "evidence": "<verbatim words from the article or a pinned passage>",
      "why": "<one or two sentences>",
      "suggested_fix": "<soften, attribute, qualify or cut wording, or null>"
    }
  ]
}
```
