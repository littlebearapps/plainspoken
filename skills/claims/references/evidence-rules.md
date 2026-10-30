# Evidence rules for the producer

These are the rules the `claims-checker` applies (its rubric is `data/rubrics/claims.md`), written for you, the
person or agent building the ledger. Apply them before the checker does: a claim that breaks one is a blocking
finding waiting to happen.

## What support means

A claim is supported when its pinned passage says what the article says, on every one of these:

- **the number**, and its rounding ("42%" can become "about four in ten"; it can't become "almost half");
- **the period** (a 2025 survey doesn't support "this year" in 2026, or "every year");
- **the geography** (a Victorian survey doesn't support "Australians");
- **the audience or population** (households surveyed online aren't "all households");
- **the scope** (some vs all, one product vs a category);
- **causation** (a passage that shows two things together doesn't support "X caused Y").

The five `binding` judgements in the ledger (`same_subject`, `same_geography`, `same_period`, `same_denominator`,
`supports_strength`) are where you record that check. They're your judgement, and the checker checks them. Set one
to `false` when it is false, then soften the sentence until it would be `true`.

A `derived` claim follows from its inputs by the arithmetic or reasoning its `derivation.method` states, and from
nothing else.

## The rules

### Quotes are verbatim at the linked source

Words inside quotation marks, attributed to a person or organisation, must appear word for word in the pinned
passage from that source. If you can't pin them, the article is conveying a position, not words: drop the
quotation marks and paraphrase, or cut. Never tidy a quote's grammar inside the marks.

### Contested "firsts" and origins are hedged

A "first", an origin story or a coinage date that is the usual account but disputed gets a hedge in the article:
"is usually credited to", "the usual account is". Stated as settled fact, it's a finding.

### Silence isn't denial

A negative or availability claim ("X isn't available here", "Y no longer does Z") needs a source that says so. The
absence of a page, a row or a mention proves nothing. The source must be newer than what it denies: an older
"only in these countries" note can't carry a current "not available here". Evidence about a sibling or successor
product says nothing about the product denied. Date availability claims in the article ("as of October 2026"), and
prefer a first-hand check of the interface, recorded as `first_hand`, when one is possible.

### An aggregator never supports a claim

A roundup, an "N statistics" post or a vendor summary cites a source; it isn't one. Figures drift and get re-dated as
they're copied. Trace the figure to the study or page it came from and pin that, or cut the claim. A claim whose
`source.source_tier` is `aggregator` can't be `verified`, and neither can one whose pinned passage itself credits
another study for the figure.

### First-hand markers cover one claim each

"In my experience" or "on our own site" in front of one sentence doesn't make the next sentence's figure first-hand.
Each first-hand claim gets its own ledger entry and its own `first_hand_scope`: who owns it, what was measured or
experienced, and how. The article may say no more than that scope: one business's booking records don't support
"small businesses find", and one month doesn't support "every year".

### A brief speaks only for the person who gave it

A brief pasted into the chat is a source, like a page. Save it under the `sources_dir` exactly as given, one file
per brief (`brief-<slug>.md`), and pin each claim to it. The claim is `verified` against the brief, not
`first_hand`: the pinned passage shows the checker what the brief says, and a first-hand scope can't. Its `source`
has `kind = "brief"`, a `title` naming who gave it and when, and no `url`. It supports what that person can speak for
(their own organisation, work, prices, offers and plans: `source_tier = "primary"`). A figure about a platform, a
law or anyone else still needs that source.

The brief's lines about the piece itself (the call to action, the offer, who it's for, the tone) are sources too.
Ledger the article's call to action as a claim and pin it to the brief's line that asks for it, so the checker reads
what the owner asked for rather than guessing. The call to action may then ask every reader to take that step, in
the article's words; a term the line doesn't give (a price, a length, a deadline, what happens after) needs its own
pin or comes out.

Any result for a client, named or not, is sensitive, even one the brief calls typical: a job finished, time saved,
a before and after. So is a named client or someone's personal details. Ledger each one `first_hand` with
`sensitive = true`, never `verified`, so the owner approves it before it goes out.

### Citation proximity isn't support

A link next to a sentence supports only what that link's pinned passage says. If the sentence says more than the
passage, the difference is unsupported: narrow the sentence, or give the extra part its own claim and source.

### Judgement is labelled

A recommendation, estimate or hypothesis is fine when the article frames it as one ("I'd start with…", "my guess
is", "in our experience"). Record it as `opinion_or_inference`. (`hypothetical` is for a scenario the article
presents as made up.) Stated as fact with no source, it's a finding.

## Choosing a source

- Prefer the primary source: the organisation that ran the survey, the platform's own documentation, the law or
  regulator's own page. Record the tier honestly in `source.source_tier`: `primary`, `near_primary`,
  `reputable_secondary`, `aggregator` or `unknown`.
- Claims about how a platform or product behaves, what a law requires or what a regulator says need an official or
  current source. If you can't find one, soften the claim or cut it.
- A source that doesn't load, or that you couldn't save, supports nothing this session. Leave the claim `blocking`
  and say why in its `resolution`.

## When the evidence is weaker than the sentence

Fix the sentence, never the evidence. Four moves, in this order of preference:

1. **Soften:** narrow the claim to what the passage shows ("in one Victorian survey, 42% of households…").
2. **Attribute:** say whose claim it is ("Example Energy says…").
3. **Qualify:** add the period, the place or the population the passage carries.
4. **Cut:** remove it, and record the claim as `removed` with a `resolution`.

Never add a statistic, a source, an example or a quote to rescue a claim. Never invent a first-hand anecdote, and
never put a view in the owner's mouth.
