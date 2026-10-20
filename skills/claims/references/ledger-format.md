# The claim ledger

One ledger per article: `<ledger_dir>/<key>.claims.toml` (default `.plainspoken/claims/`), or a `.claims.json` with
the same fields. The key is the report key (the stem plus 8 hex of the article's path), so two `index.md` files never
share a ledger. `RUN paths ARTICLE` prints the path; never build it by hand. The schema is
`data/schemas/claim-ledger.schema.json`; `RUN claims validate <ledger>` checks a ledger against it and against the
rules a schema can't express.

In TOML, quote every date and time (`checked_at = "2026-10-14T09:30:00+11:00"`). Unquoted ones still validate, but
quoted strings read the same in TOML and JSON. `checked_at` needs its UTC offset (`+11:00` or `Z`): a time
without one is a schema error. A long string you write yourself may wrap as a TOML `"""…"""` string with `\` at the
end of each line, as two do below; the value is still one line. Paste a pinned `passage` exactly as printed.

## Top-level fields

| Field | What it holds |
|---|---|
| `schema_version` | Always `1`. |
| `article_id` | A short id for the article (`ACME-HW`). Claim ids usually start with it. |
| `article_slug` | The article's slug or file stem. |
| `source_file` | The article's path from the project root, with no leading `/` and no `..` (file types below). |
| `source_content_hash` | `RUN claims hash ARTICLE`, copied in once complete. A mismatch makes every check stale. |
| `checked_at` | When the ledger was last brought up to date, ISO 8601 with an offset. |
| `checked_by` | Who or what did it (a name, or "claims skill"). |
| `coverage_status` | `complete`, `partial`, `stale` or `unstarted`. Anything but `complete` reports INCOMPLETE. |
| `coverage_notes` | Optional: what coverage ran, and anything it couldn't reach. |
| `exclusions` | Optional: non-material candidates, each with `text` and a `reason` (10 characters or more). |
| `claims` | The claims, one table each. |

`source_file` ends in `.md`, `.mdx`, `.markdown`, `.txt` or `.html`. When `source_content_hash` doesn't match the
article, every verification is stale.

## Claim fields

Every claim needs `claim_id`, `text`, `locations`, `claim_type`, `prominence` and `status`.

- `claim_id`: letters and digits joined by `-` or `_` (`ACME-HW-C003`). Never reuse an id, even after `removed`.
- `text`: the claim as the article words it.
- `locations`: one or more `{kind, field?, anchor?}`. `kind` is one of `body`, `frontmatter`, `tldr`, `heading`,
  `chart`, `figcaption`, `faq`, `jsonld`, `table`, `title`, `code_comment`, `alt_text`, `distribution_copy`.
- `claim_type`: `statistic`, `count`, `price`, `date`, `duration`, `version`, `product_feature`, `forecast`,
  `estimate`, `comparison`, `superlative`, `causal`, `outcome`, `platform_behaviour`, `legal_policy`, `quotation`,
  `attributed_paraphrase`, `historical`, `first_hand`, `derived_metric`, `code_behaviour` or `premise`.
- `prominence`: `high` (title, headings, the opening, anything a reader acts on), `medium` or `low`.
- Optional context: `subject`, `metric`, `geography`, `period`, `risk` (`critical`, `high`, `medium`, `low`),
  `refresh_after` (a date to re-check it), `notes`, `regulated_class` (see `regulated-claims.md`).
- `source`: `url`, `title` and `source_tier` (`primary`, `near_primary`, `reputable_secondary`, `aggregator`,
  `unknown`), plus optional `publisher`, `published_at`, `updated_at`, `locator`, `accessed_at`.
- `binding`: the pinned passage and its hashes, pasted from `RUN claims pin`. Its `source_snapshot` is the saved
  source, project-relative and under the `sources_dir` (default `.plainspoken/sources/`); it is never the article
  (`source_file`), and a snapshot outside the `sources_dir` makes `claims status` INCOMPLETE. Then the five judgements
  `same_subject`, `same_geography`, `same_period`, `same_denominator` and `supports_strength` (true or false, each
  set after reading the passage against the claim). `additional_passages` holds further pinned spans that together
  carry a compound claim (pinning.md).
- `derivation`: `method` (the arithmetic or reasoning, in words), plus `inputs` (ids of claims in this ledger it
  starts from), `derived_from_external` (files under the project or `https://` URLs it used that aren't claims),
  or both. Status reads `inputs` as claim ids, so a file or URL listed there reads as a missing claim.
- `first_hand_scope`: `owner`, `scope` (what was measured or experienced, and no more), `method`, plus `sensitive`
  and `approved_by_owner`.
- `resolution`: for `removed` and `blocking`, the original problem, the evidence, the correction and where else the
  claim appeared.
- `human_signoff`: see below.

## The closed status list

There is no "unverified but reasonable". A claim is one of these, with the fields its row names.

| Status | Means | Needs |
|---|---|---|
| `verified` | A pinned passage from a saved source supports the claim as worded. | `source`, `binding` |
| `derived` | Worked out from other claims or passages by stated arithmetic or reasoning. | `derivation` |
| `first_hand` | The owner's own experience or measurement. | `first_hand_scope` |
| `opinion_or_inference` | A judgement, recommendation or estimate, framed as one in the article. | its label |
| `hypothetical` | An example or scenario the article presents as made up. | its label |
| `removed` | Cut from the article. Audit history; it never counts as a passing claim. | `resolution` |
| `blocking` | Unresolved: the article can't publish with it as worded. | `resolution` |

What each one needs, in full:

- `verified`: a `source` and a `binding` with a pinned `passage`. Never an `aggregator` source.
- `derived`: a `derivation`. Its inputs are claims in this ledger with their own support.
- `first_hand`: a `first_hand_scope`. `sensitive = true` blocks until the owner sets `approved_by_owner = true`.
- `opinion_or_inference`: nothing more in the ledger; the article's wording must label it.
- `hypothetical`: nothing more in the ledger; the article must make that plain.
- `removed`: a `resolution`.
- `blocking`: a `resolution` saying what has to happen.

`claims scaffold` writes every candidate as `blocking` with the resolution "unreviewed candidate from claims
scaffold". Replace it with a real status, or with a real resolution if the claim stays blocking. A scaffolded
entry that isn't a material claim (an illustrative value, example copy) is deleted from `claims`, and its text goes
into `exclusions` with a reason. `removed` is only for a claim cut from the article. Each scaffolded location's
`anchor` is the heading of the section the candidate sits in ("before the first heading" above the first one); its
line number is in `notes`.

## `exclusions`

An exclusion says an extractor candidate isn't a material claim: a figure in an obviously made-up example, a value
inside a code sample, a rhetorical string. It needs the exact `text` and a `reason` a reader would accept. An
exclusion that hides a real claim is a bypass, and the checker reports the claim as unledgered.

## `human_signoff`

The owner's recorded sign-off on one claim, after a checker finding routed it to them. You record it only when the
owner has given it in this session, in their words; you never sign for them. Every field is required:

- `signed`: the date (`2026-10-14`);
- `signed_by`: who signed;
- `against_run`: the checker run it answers, as `<date>-<label>` (`2026-10-14-r1`);
- `findings`: the finding ids or classes it addresses;
- `wording`: the exact article wording they approved;
- `scope_note`: what they approved, in their own scope words.

The sign-off is void the moment `wording` no longer appears in the article (whitespace and curly vs straight quotes
aside; case counts): edit the sentence and it needs signing again.

## An annotated example

Invented throughout: Acme Plumbing, a made-up survey at example.com, and hashes from a throwaway run.

```toml
schema_version = 1
article_id = "ACME-HW"
article_slug = "hot-water-replacement"
source_file = "posts/hot-water-replacement.md"
# From `RUN claims hash posts/hot-water-replacement.md`, copied in at step 5.
source_content_hash = "sha256:2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"
checked_at = "2026-10-14T09:45:00+11:00"
checked_by = "claims skill"
coverage_status = "complete"
coverage_notes = "Scaffold candidates reviewed; title, FAQ and alt text read for unledgered claims."

# The invoice total in the worked example is made up, so it isn't a material claim.
[[exclusions]]
text = "$2,480"
reason = "Total on a sample invoice the article labels as made up."

# verified: a pinned passage from a saved source supports the sentence.
[[claims]]
claim_id = "ACME-HW-C001"
text = """In a 2025 survey of 1,200 Victorian households, 42% had replaced their hot water system \
  in the past ten years."""
claim_type = "statistic"
prominence = "high"
geography = "Victoria"
period = "2025 survey; ten years before it"
status = "verified"

[[claims.locations]]
kind = "body"
anchor = "How often systems get replaced"

[claims.source]
url = "https://example.com/energy-survey-2025"
title = "Example Energy Survey 2025"
publisher = "Example Energy"
source_tier = "primary"

# Pasted from `RUN claims pin`; the five judgements were set after reading the passage.
[claims.binding]
passage = "Of 1,200 households surveyed in Victoria, 42% had replaced their hot water system in the past ten years."
passage_sha256 = "sha256:afc1f1f305a4b627894f94bc42aaac407d706aecaf5891478c489344e8a268ef"
source_text_sha256 = "sha256:f7b182a90a99776f6a816a7e68de6373bbe6e76dae77fd0639fab2a7592e13fc"
retrieved_at = "2026-10-14T09:30:00+11:00"
source_snapshot = ".plainspoken/sources/example-energy-survey-2025.txt"
same_subject = true
same_geography = true
same_period = true
same_denominator = true
supports_strength = true

# The survey year comes from the method note, pinned with `--additional`.
[[claims.binding.additional_passages]]
passage = "an online survey of 1,200 households in Victoria, run in March 2025."
passage_sha256 = "sha256:263b7dcc97174b61c3cd7be8c1cb9837121e9a3d464381aef0b143120c96b97c"
source_text_sha256 = "sha256:f7b182a90a99776f6a816a7e68de6373bbe6e76dae77fd0639fab2a7592e13fc"
retrieved_at = "2026-10-14T09:30:00+11:00"
locator = "Method"

# derived: rounding C001 for the summary box. The method says how.
[[claims]]
claim_id = "ACME-HW-C002"
text = "About four in ten Victorian households surveyed had replaced their system within ten years."
claim_type = "derived_metric"
prominence = "medium"
status = "derived"

[[claims.locations]]
kind = "tldr"

[claims.derivation]
method = "42% rounded to the nearest ten per cent and written as a fraction."
inputs = ["ACME-HW-C001"]

# first_hand: the owner's own records, scoped to what was counted.
[[claims]]
claim_id = "ACME-HW-C003"
text = "Of the 38 hot water call-outs I attended in March 2026, 29 were for gas units."
claim_type = "first_hand"
prominence = "medium"
status = "first_hand"

[[claims.locations]]
kind = "body"
anchor = "What I see on call-outs"

[claims.first_hand_scope]
owner = "Acme Plumbing (the author)"
scope = "The author's own job sheets for March 2026: 38 hot water call-outs."
method = "Counted job sheets by unit type."
sensitive = false

# opinion_or_inference: framed as advice in the article ("I'd…").
[[claims]]
claim_id = "ACME-HW-C004"
text = "I'd plan to replace a unit once it passes 15 years, rather than wait for it to fail."
claim_type = "premise"
prominence = "medium"
status = "opinion_or_inference"

[[claims.locations]]
kind = "body"
anchor = "When to replace"

# removed: cut from the article; kept as audit history.
[[claims]]
claim_id = "ACME-HW-C005"
text = "Electric units last twice as long as gas units."
claim_type = "comparison"
prominence = "medium"
status = "removed"
resolution = "No saved source supported the comparison. Cut from the body on 2026-10-14; it appeared nowhere else."

[[claims.locations]]
kind = "body"
anchor = "Gas or electric"

# blocking: waits on the owner. The rebate amount changes, and no current page was saved.
[[claims]]
claim_id = "ACME-HW-C006"
text = "Rebates cover up to $1,000 of a heat pump install."
claim_type = "price"
prominence = "high"
status = "blocking"
resolution = """The scheme page didn't load this session. Owner to confirm the current amount from the scheme \
  page, or the sentence is cut."""

[[claims.locations]]
kind = "faq"
field = "Are there rebates?"
```
