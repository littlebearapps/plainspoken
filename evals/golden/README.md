# The golden set

The golden set is the labelled text the judges and the claims checker are measured against: `plainspoken eval judges`
asks each judge model about every J1–J4 and JR case and compares its answer with the label here, and
`plainspoken eval claims` does the same for the claims checker on the CL cases (`CL.toml`). It is **held out**: no case text is ever
quoted in a rubric, a skill, a guide or a prompt, and a label never reaches a model.

Check it with:

```bash
python3 lib/run.py eval golden validate                   # format, labels, provenance, held-out rule
python3 lib/run.py eval golden validate --require-counts  # also: enough cases to measure (CI)
```

Exit 0 means valid, 1 means problems (one `problem:` line each), and 2 means a missing folder or a file that
isn't the format.

## What's in it

254 cases (as of 23 October 2026): 232 for the judges, 22 for the claims checker.

| Group | Cases | Labels | Confirmed | Endorsed | Provisional |
|---|---|---|---|---|---|
| J1 | 40 | fail 20 · pass 20 | 8 | 0 | 32 |
| J2 | 50 | fail 27 · pass 23 | 5 | 9 | 36 |
| J3 | 60 | fail 30 · pass 30 | 11 | 0 | 49 |
| J4 | 40 | fail 20 · pass 20 | 4 | 0 | 36 |
| JR | 42 | accept 18 · reject 24 | 5 | 0 | 37 |
| **Judges** | **232** | fail 97 · pass 93 · accept 18 · reject 24 | **33** | **9** | **190** |
| CL | 22 | fail 15 · pass 7 (claims: fail 15 · pass 34) | 0 | 0 | 22 |

42 cases carry a human label. 17 came from the owner's recorded decisions, anonymised. On 18 October 2026 the
owner reviewed 25 cases one by one (the doubtful ones first, stratified by group and label): all 25 are now
`confirmed`, two with a changed label (`JR-12f-001` accept → reject, `J3-27-003` fail → pass). A second review the
same day confirmed 6 more J3 cases with no label changes (`J3-2-008`, `J3-12c-006`, and the new pairs
`J3-12c-007`/`-008`, `J3-17-007`/`-008`). The other 190 were constructed and then second-labelled blind by a
separate pass (226/226 agreement at the time), so judge metrics on them are an upper bound until a person confirms
them.

## Files

One TOML file per group: `J1.toml`, `J2.toml`, `J3.toml`, `J4.toml`, `JR.toml` (the reviewer of WARN
justifications) and `CL.toml` (the claims checker). Every `*.toml` file in this folder is loaded, in name order, so a group may be split across
files if one grows too long. Case ids are unique across all of them.

```toml
schema = 1
group = "J1"

[[case]]
id = "J1-5b-001"
rule = "5b"
label = "fail"
content_type = "article"
source = "constructed"
status = "provisional"
origin = "minimal pair for 5b; see J1-5b-002"
text = """
The markdown the judge reads.
"""
```

| Key | What it holds |
|---|---|
| `id` | `<group>-<rule or tag>[-<tag>]-NNN`, for example `J1-5b-001` or `JR-load_bearing-003` (letters, digits and `_`). The prefix is the file's group. |
| `rule` | J1–J4: a rule whose `group` in `data/rules.toml` is this group. JR: any rule id in `data/rules.toml`. |
| `label` | J1–J4: `fail` (the tell is there) or `pass` (it isn't). JR: `accept` or `reject` (the justification). |
| `content_type` | A content type the engine checks: `article` or `social`. |
| `source`, `status` | Where the label came from (next section). |
| `origin` | One line, at most 160 characters: how the case was made or where it came from. No names. |
| `text` | 1 to 4,000 characters of markdown. |

JR cases carry three more keys, and only JR cases may:

| Key | What it holds |
|---|---|
| `kind` | The justification's kind, one of `voice`, `quote`, `load_bearing`, `false_positive`, `format`, `metric`. |
| `reason` | The justification under review. |
| `evidence` | `[{line = 3, quote = "…"}]`: at least one quote, each appearing word for word on that line of `text` (lines count from 1, after the opening `"""`). |

## The claims checker's cases (CL)

`CL.toml` measures the claims checker (`agents/claims-checker.md`, rubric `data/rubrics/claims.md`). A CL case is a
short article and the claims of its ledger. Each claim carries the ledger's own fields (`claim_id`, `text`,
`claim_type`, `prominence`, `status`, `locations`, and `source`, `binding`, `derivation` or `first_hand_scope` as
the claim needs) plus two label keys:

| Key | What it holds |
|---|---|
| `expect` | `fail`: the checker should file a `blocking` finding against this claim. `pass`: it shouldn't (a warning is fine). |
| `why` | One line, at most 240 characters, that a person can check by reading the case. |

```toml
[[case]]
id = "CL-opinion_label-001"
rule = "opinion_label"
content_type = "article"
source = "constructed"
status = "provisional"
origin = "minimal pair for the opinion-label rule"
text = """
The article the checker reads.
"""

[[case.claim]]
claim_id = "C001"
expect = "fail"
why = "Why the checker should block it."
text = "Words the article holds word for word."
claim_type = "duration"
prominence = "medium"
status = "opinion_or_inference"
locations = [{kind = "body", anchor = "a heading"}]

[case.claim.binding]  # optional, and so on: any table a ledger claim has
```

A CL case has no `label` key: it's `fail` when any claim's `expect` is `fail` (the checker's result should be
BLOCKED), else `pass`. `rule` names the part of the rubric the case tests: `opinion_label`, `derivation`,
`entailment`, `first_hand_scope`, `quote`, `brief` or `aggregator`. `eval golden validate` checks that every claim's
`text` is in the article, that the ledger the claims make is valid against the claim-ledger schema, that a
derivation names other claims of the case, and that a claim's status is one the checker is scored on (not `removed`
or `blocking`). The checker reads the ledger `golden.claims_ledger` builds: fixed top-level fields, a
`source_content_hash` of the case text, and the claims without `expect` and `why`. With `--require-counts`, CL needs
at least 10 cases, 4 of each label, and 10 claims of each verdict, so a checker that blocks everything (or nothing)
can't score well.

## Where a label comes from

Every case says who decided its label, and the two keys must agree:

| `status` | `source` | Meaning |
|---|---|---|
| `confirmed` | `owner` | The owner (the person who maintains the set) labelled this case directly. |
| `endorsed` | `owner-endorsed` | The owner approved it indirectly, such as by approving the fix that removed the tell. |
| `provisional` | `constructed` | Built for the set (a minimal pair, a seeded tell) and not yet checked by a person. |

Human labels are scarce, so most cases start as `provisional`. Metrics are reported on the confirmed and endorsed
cases and on the whole set separately, and the whole-set figure is labelled a proxy.

## Confirming a case

Read the case, decide whether the label is right, and edit the case in place:

- the label is right: set `status = "confirmed"` and `source = "owner"`;
- the label is wrong: fix `label` as well, then confirm it the same way;
- the case is ambiguous or unfair: delete it (ids are never reused).

Run `eval golden validate` afterwards.

## The held-out rule

- No case text, no JR `reason` and no CL claim prose (its `text`, `why`, `notes`, pinned passages, derivation
  method and first-hand scope) is ever quoted in `data/`, `agents/`, `skills/`, `guides/`, `hooks/`,
  `output-styles/`, `templates/` or `evals/briefs/`. `eval golden validate` fails if any file there shares a run
  of 8 or more consecutive words with one of them, or holds the whole of one shorter than 8 words
  (compared case-folded, ignoring punctuation and spacing). A folder or file there it can't read is a problem too.
- A label never goes into a prompt. The eval commands send the text and the rubric, never the answer (for CL, the
  ledger without `expect` and `why`).
- Text taken from a real article is anonymised first: no person, client or business names. The repo's leak guard
  (`scripts/dev/leak_guard.py`) scans this folder too.
- When a rubric needs an example, write a fresh one; never copy or paraphrase a case into it.
