# The reader-value contract

The contract records the benefit a piece promises its reader. It's written before drafting, in outline mode, and
read against the finished draft in deliver mode. There's one contract per piece: keep it in one place and point to
it, rather than copying it into a brief and a plan where the copies can drift.

## Where it lives

`RUN reader-value validate` reads any of three forms:

- a standalone `.toml` file (the default, `.plainspoken/reader-value/<name>.reader-value.toml`);
- a standalone `.json` file with the same fields;
- a markdown file, such as a brief or a notes file, holding exactly one fenced `toml` or `json` block in the section
  under a `## Reader Value Contract` heading. A fenced `yaml` block is read too, but only a plain subset: flow
  mappings, anchors and tabs make validate exit 2 rather than half-read the contract.

`RUN reader-value template` prints a starter TOML contract with every field explained, using an invented plumbing
example. Replace every value.

## Fields

| Field | Required | What it holds |
|---|---|---|
| `schema_version` | always | `1` |
| `type` | always | what the reader gets (see the next table) |
| `primary_reader` | always | who the piece is for, as specifically as you can say it |
| `problem` | always | their problem or question, in their words |
| `promised_outcome` | always | what the reader has, knows or can do after reading; never a call to action |
| `original_value` | always | the author's real, specific contribution: a method, data, or first-hand experience |
| `cta_excluded_confirmed` | always | `true`: you confirm the outcome and the value leave every call to action out |
| `decision` | `decision` | the decision the piece helps the reader make |
| `first_action` | procedural types | the reader's own first useful step, as `verb`, `object` and `location` |
| `effort` | procedural types | an honest effort or time estimate |
| `success_signal` | procedural types | how the reader knows it worked: the expected result |
| `stop_condition` | procedural types | when to stop, skip the step, or get help |
| `prerequisites` | optional | what the reader needs before they start |
| `evidence_trail` | history types | the sources, places or questions the piece equips the reader to explore |

## Types

| `type` | Suits | Also required |
|---|---|---|
| `task` | a practical how-to | `first_action`, `effort`, `success_signal`, `stop_condition` |
| `self_check` | a checklist the reader runs on their own situation | the same four |
| `implementation` | a technical build the reader can reproduce | the same four |
| `debugging_path` | a fault the reader can trace and fix | the same four |
| `decision` | a choice between options, a prioritise-or-skip call | `decision` |
| `evidence_trail` | history or research the reader can follow up | `evidence_trail` |
| `historical_interpretation` | an argued reading of the past | `evidence_trail` |

Practical guides usually fit `task`, `decision` or `self_check`. Technical posts fit `implementation` or
`debugging_path`. History and commentary fit `evidence_trail` or `historical_interpretation`, and never need steps.

## What validate rejects beyond the schema

- **A CTA-shaped `promised_outcome`:** it holds a call-to-action phrase and fewer than six words are left once the
  phrase is removed. "Book an Acme Drain Service" promises the reader nothing they can do or know.
- **A CTA-shaped `first_action`:** any call-to-action phrase in it. The first useful step is the reader's own, not
  getting in contact with or buying from the author.
- **A vague `original_value`:** the whole value is a stock phrase about insight or expertise. Name the method, the
  data or the experience.

The shipped call-to-action phrases live in the plugin's data, not here. They leave out phrases that are often the
reader's own first step ("booking", "sign up", "get a quote", "reach out"). A project adds its own, usually the names
of its offers and any of those it uses as a call to action, in `.plainspoken/config.toml`:

```toml
[reader_value]
cta_phrases = ["Acme Drain Service", "Acme Care Plan", "get a quote"]
```

They're matched as whole words, case-insensitively, and added to the shipped phrases. Validate reads the config at
the project root, so run it from there.

## Figures are claims

`effort` is a claim when it's a specific figure ("about 20 minutes per chisel"), and so is a price in
`prerequisites`. So is any time or cost figure the draft repeats. Put each one in the claim ledger, with how you
know it (your own timing is a first-hand claim with its method), and verify it with the `claims` skill
(`/plainspoken:claims`). Where you can't support a figure, soften it ("an afternoon") or cut it.

## Examples

All invented. Each passes `RUN reader-value validate`.

A `task` piece for a hobby woodworker:

```toml
schema_version = 1
type = "task"
primary_reader = "A hobby woodworker whose bench chisels tear the grain instead of slicing it"
problem = "My chisels feel blunt and I can't tell whether to hone them or regrind the bevel"
promised_outcome = "A chisel that pares end grain cleanly, and a way to tell when honing isn't enough"
effort = "about 20 minutes per chisel"
prerequisites = ["a combination whetstone", "a honing guide"]
success_signal = "The edge shaves a thin curl from pine end grain without crushing it"
stop_condition = "Stop honing and regrind if there's a chip you can see or the bevel has gone round"
original_value = "A two-minute edge test worked out over five years of restoring second-hand chisels"
cta_excluded_confirmed = true

[first_action]
verb = "check"
object = "the edge for chips and a rounded bevel"
location = "under a bright light at the bench"
```

A `decision` piece for a community choir:

```toml
schema_version = 1
type = "decision"
primary_reader = "The committee of a community choir that has outgrown its church hall"
problem = "We need a bigger rehearsal room and can't tell which costs matter"
decision = "Whether to move rehearsals to the school hall or stay and rehearse in two sections"
promised_outcome = "A side-by-side comparison of both options that the committee can take to its next meeting"
original_value = "The attendance and hire records the choir kept through two seasons of trial rehearsals"
cta_excluded_confirmed = true
```

A `historical_interpretation` piece about the same choir's hall:

```toml
schema_version = 1
type = "historical_interpretation"
primary_reader = "Choir members curious about the hall they rehearse in"
problem = "Who built our hall, and why is there a stage at one end and a kitchen at the other?"
promised_outcome = "An account of the hall's first forty years, with the records a reader can check for themselves"
original_value = "The hall committee's minute books from its first decade, read in full at the local library"
evidence_trail = [
  "the hall committee's minute books, 1921 to 1931",
  "the programme from the opening concert",
  "the local paper's report of the opening",
]
cta_excluded_confirmed = true
```
